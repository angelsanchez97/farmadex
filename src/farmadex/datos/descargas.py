"""Descarga y versionado de los ficheros de datos externos.

Fuentes (todas con licencia libre y sin credenciales):
  - WFCD/warframe-items  : catalogo de objetos, componentes, reliquias y nodos.
  - drops.warframestat.us: tablas de drops oficiales de Digital Extremes.

Nada de esto toca el juego: son ficheros JSON publicos.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import httpx

from ..config import DIR_DATOS, RUTA_ESTADO_DATOS, USER_AGENT, crear_carpetas
from ..registro_log import obtener

log = obtener("descargas")

ITEMS_BASE = "https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/"
ITEMS_COMMITS = (
    "https://api.github.com/repos/WFCD/warframe-items/commits?path=data/json&per_page=1"
)
# Los mismos ficheros que sirve drops.warframestat.us, pero desde el repositorio
# de origen: evita depender de un unico dominio y de su certificado.
DROPS_BASE = "https://raw.githubusercontent.com/WFCD/warframe-drop-data/master/data/"
DROPS_ESPEJO = "https://drops.warframestat.us/data/"

# Categorias de warframe-items que se importan al indice.
CATEGORIAS_ITEMS = (
    "Warframes",
    "Primary",
    "Secondary",
    "Melee",
    "Arch-Gun",
    "Arch-Melee",
    "Archwing",
    "Sentinels",
    "SentinelWeapons",
    "Pets",
    "Mods",
    "Arcanes",
    "Relics",
    "Resources",
    "Misc",
    "Gear",
    "Quests",
    "Skins",
    "Sigils",
    "Glyphs",
    "Fish",
    "Railjack",
    "Node",
    "Honoria",
)

FICHEROS_DROPS = (
    "missionRewards.json",
    "relics.json",
    "modLocations.json",
    "enemyModTables.json",
    "blueprintLocations.json",
    "enemyBlueprintTables.json",
    "resourceByAvatar.json",
    "sortieRewards.json",
    "transientRewards.json",
    "cetusBountyRewards.json",
    "solarisBountyRewards.json",
    "deimosRewards.json",
    "entratiLabRewards.json",
    "zarimanRewards.json",
    "hexRewards.json",
    "keyRewards.json",
    "syndicates.json",
    "miscItems.json",
)

# Callback de progreso: (texto, hechos, total). total <= 0 significa indeterminado.
Progreso = Callable[[str, int, int], None]


def _nada(texto: str, hechos: int, total: int) -> None:  # pragma: no cover - por defecto
    pass


@dataclass
class EstadoDatos:
    """Lo que hay descargado ahora mismo y de que version es."""

    items_sha: str = ""
    items_fecha: str = ""
    drops_hash: str = ""
    drops_modified: str = ""
    descargado_en: str = ""
    ficheros: dict = field(default_factory=dict)

    @classmethod
    def cargar(cls) -> "EstadoDatos":
        if RUTA_ESTADO_DATOS.exists():
            try:
                return cls(**json.loads(RUTA_ESTADO_DATOS.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError, TypeError):
                log.warning("estado_datos.json ilegible, se descarga todo de nuevo")
        return cls()

    def guardar(self) -> None:
        crear_carpetas()
        tmp = RUTA_ESTADO_DATOS.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")
        tmp.replace(RUTA_ESTADO_DATOS)


class Descargador:
    """Mantiene al dia la carpeta de datos. Solo descarga lo que ha cambiado."""

    def __init__(self, progreso: Progreso | None = None, cliente: httpx.Client | None = None):
        self.progreso = progreso or _nada
        self.cliente = cliente or httpx.Client(
            timeout=60.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self.estado = EstadoDatos.cargar()

    # -- utilidades -----------------------------------------------------

    def _pedir_json(self, url: str, cabeceras: dict | None = None):
        ultimo = None
        for intento in range(3):
            try:
                r = self.cliente.get(url, headers=cabeceras or {})
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, json.JSONDecodeError) as e:
                ultimo = e
                espera = 2**intento
                log.warning("Fallo pidiendo %s (%s). Reintento en %ss", url, e, espera)
                time.sleep(espera)
        raise RuntimeError(f"No se pudo obtener {url}: {ultimo}")

    def _descargar_fichero(
        self, url: str, destino: Path, etiqueta: str, alternativa: str | None = None
    ) -> None:
        """Descarga en streaming con progreso por bytes y escritura atomica."""
        try:
            self._descargar_una_vez(url, destino, etiqueta)
        except RuntimeError:
            if not alternativa:
                raise
            log.warning("Probando el espejo para %s", destino.name)
            self._descargar_una_vez(alternativa, destino, etiqueta)

    def _descargar_una_vez(self, url: str, destino: Path, etiqueta: str) -> None:
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(destino.suffix + ".tmp")
        ultimo_error = None
        for intento in range(3):
            try:
                with self.cliente.stream("GET", url) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length") or 0)
                    hechos = 0
                    with tmp.open("wb") as f:
                        for trozo in r.iter_bytes(262_144):
                            f.write(trozo)
                            hechos += len(trozo)
                            if total:
                                self.progreso(
                                    f"{etiqueta} ({hechos // 1_048_576} de {total // 1_048_576} MB)",
                                    hechos,
                                    total,
                                )
                            else:
                                self.progreso(f"{etiqueta} ({hechos // 1_048_576} MB)", 0, 0)
                tmp.replace(destino)
                return
            except httpx.HTTPError as e:
                ultimo_error = e
                espera = 2**intento
                log.warning("Fallo descargando %s (%s). Reintento en %ss", url, e, espera)
                time.sleep(espera)
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"No se pudo descargar {url}: {ultimo_error}")

    # -- versiones ------------------------------------------------------

    def version_items(self) -> tuple[str, str]:
        """Devuelve (sha, fecha) del ultimo commit que toco los JSON."""
        try:
            datos = self._pedir_json(ITEMS_COMMITS, {"Accept": "application/vnd.github+json"})
            return datos[0]["sha"], datos[0]["commit"]["committer"]["date"]
        except Exception as e:  # noqa: BLE001 - sin version se sigue adelante
            log.warning("No se pudo leer la version de warframe-items: %s", e)
            return "", ""

    def version_drops(self) -> tuple[str, str]:
        for base in (DROPS_BASE, DROPS_ESPEJO):
            try:
                info = self._pedir_json(base + "info.json")
                return str(info.get("hash", "")), str(info.get("modified", ""))
            except Exception as e:  # noqa: BLE001
                log.warning("No se pudo leer info.json de drop-data en %s: %s", base, e)
        return "", ""

    # -- sincronizacion -------------------------------------------------

    def rutas_items(self) -> dict[str, Path]:
        rutas = {c: DIR_DATOS / f"{c}.json" for c in CATEGORIAS_ITEMS}
        rutas["i18n_es"] = DIR_DATOS / "i18n_es.json"
        return rutas

    def rutas_drops(self) -> dict[str, Path]:
        return {f.removesuffix(".json"): DIR_DATOS / "drops" / f for f in FICHEROS_DROPS}

    def _faltan(self, rutas: Iterable[Path]) -> bool:
        return any(not r.exists() or r.stat().st_size == 0 for r in rutas)

    def sincronizar(self, forzar: bool = False) -> bool:
        """Deja la carpeta de datos al dia. Devuelve True si algo cambio."""
        crear_carpetas()
        cambios = False

        sha, fecha = self.version_items()
        rutas_items = self.rutas_items()
        toca_items = (
            forzar
            or self._faltan(rutas_items.values())
            or (sha and sha != self.estado.items_sha)
        )

        if toca_items:
            total = len(CATEGORIAS_ITEMS) + 1
            for i, categoria in enumerate(CATEGORIAS_ITEMS, start=1):
                self.progreso(f"Descargando catalogo: {categoria} ({i}/{total})", i - 1, total)
                self._descargar_fichero(
                    ITEMS_BASE + f"{categoria}.json",
                    rutas_items[categoria],
                    f"Descargando {categoria}",
                )
            self.progreso(f"Descargando traducciones ({total}/{total})", total - 1, total)
            self._descargar_i18n(rutas_items["i18n_es"])
            self.estado.items_sha, self.estado.items_fecha = sha, fecha
            cambios = True
        else:
            log.info("Catalogo de objetos al dia (%s)", self.estado.items_fecha or "sin version")

        hash_drops, modificado = self.version_drops()
        rutas_drops = self.rutas_drops()
        toca_drops = (
            forzar
            or self._faltan(rutas_drops.values())
            or (hash_drops and hash_drops != self.estado.drops_hash)
        )

        if toca_drops:
            total = len(FICHEROS_DROPS)
            fallos = []
            for i, (clave, ruta) in enumerate(rutas_drops.items(), start=1):
                self.progreso(f"Descargando tablas de drops: {clave} ({i}/{total})", i - 1, total)
                try:
                    self._descargar_fichero(
                        DROPS_BASE + f"{clave}.json",
                        ruta,
                        f"Descargando {clave}",
                        alternativa=DROPS_ESPEJO + f"{clave}.json",
                    )
                except RuntimeError as e:
                    # Una tabla suelta que falle no debe dejar la aplicacion sin datos.
                    log.error("No se pudo descargar la tabla %s: %s", clave, e)
                    fallos.append(clave)
            if len(fallos) > len(FICHEROS_DROPS) // 3:
                raise RuntimeError(
                    "No se pudieron descargar las tablas de drops: " + ", ".join(fallos)
                )
            self.estado.drops_hash, self.estado.drops_modified = hash_drops, modificado
            cambios = True
        else:
            log.info("Tablas de drops al dia (%s)", self.estado.drops_modified or "sin version")

        if cambios:
            self.estado.descargado_en = time.strftime("%Y-%m-%dT%H:%M:%S")
            self.estado.ficheros = {
                k: v.stat().st_size for k, v in {**rutas_items, **rutas_drops}.items() if v.exists()
            }
            self.estado.guardar()
        return cambios

    def _descargar_i18n(self, destino: Path) -> None:
        """i18n.json trae todos los idiomas (~50 MB). Se guarda solo el espanol."""
        crudo = DIR_DATOS / "i18n.json"
        self._descargar_fichero(ITEMS_BASE + "i18n.json", crudo, "Descargando traducciones")
        self.progreso("Filtrando traducciones al espanol", 0, 0)
        with crudo.open(encoding="utf-8") as f:
            todos = json.load(f)
        solo_es = {
            unico: idiomas["es"]
            for unico, idiomas in todos.items()
            if isinstance(idiomas, dict) and idiomas.get("es")
        }
        tmp = destino.with_suffix(".tmp")
        tmp.write_text(json.dumps(solo_es, ensure_ascii=False), encoding="utf-8")
        tmp.replace(destino)
        crudo.unlink(missing_ok=True)
        log.info("Traducciones al espanol: %d objetos", len(solo_es))

    def cerrar(self) -> None:
        self.cliente.close()
