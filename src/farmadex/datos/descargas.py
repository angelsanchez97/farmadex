"""Descarga y versionado de los ficheros de datos externos.

Fuentes (todas con licencia libre y sin credenciales):
  - WFCD/warframe-items  : catalogo de objetos, componentes, reliquias y nodos.
  - drops.warframestat.us: tablas de drops oficiales de Digital Extremes.
  - warframe.com/droptables: la pagina original de esas tablas, que DE publica antes de
    que WFCD la vuelque a JSON (ver tabla_oficial.py). Es un extra: si falla, se sigue.

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
from .tabla_oficial import NOMBRE_FICHERO as FICHERO_TABLA_OFICIAL
from .tabla_oficial import URL_TABLA_OFICIAL, fecha_publicacion
from ..ficheros import reemplazar, temporal_de

log = obtener("descargas")

ITEMS_BASE = "https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/"
# Desde el 2026-09-24 (PR #992 de WFCD) las traducciones vienen una por idioma en esta
# carpeta, de 4 a 7 MB cada una, y el i18n.json con todas juntas (~50 MB) ya no existe.
# Se prueba primero la carpeta y, si no esta, el fichero grande: asi sirve con los dos.
ITEMS_I18N = ITEMS_BASE + "i18n/"
# Catalogo aparte de las piezas de receta (mismo PR). Con el formato nuevo cada objeto solo
# lleva {"uniqueName", "itemCount"} de sus piezas y el resto (nombre, ducados, drops) esta
# aqui. Con el antiguo no existe y las piezas vienen enteras dentro de cada objeto.
CATALOGO_PIEZAS = "Components"
ITEMS_COMMITS = (
    "https://api.github.com/repos/WFCD/warframe-items/commits?path=data/json&per_page=1"
)
# Los mismos ficheros que sirve drops.warframestat.us, pero desde el repositorio
# de origen: evita depender de un unico dominio y de su certificado.
DROPS_BASE = "https://raw.githubusercontent.com/WFCD/warframe-drop-data/master/data/"
DROPS_ESPEJO = "https://drops.warframestat.us/data/"

# Idiomas de i18n.json que se guardan aparte del espanol, para casar y buscar objetos
# cuando el juego esta en ese idioma. WFCD trae bastantes mas (ja, ko, ru, zh...) pero
# estos son los que el casador sabe tratar (ver glosario_<idioma>.json en datos/).
IDIOMAS_EXTRA = ("fr", "de", "pt", "it", "pl")

# Codigos de idioma que usa el i18n.json antiguo como claves de cada objeto. Sirven para
# reconocer ese formato por su contenido y no por la fecha ni por la URL de la que vino.
CODIGOS_I18N = frozenset(
    {"en", "de", "es", "fr", "it", "ja", "ko", "pl", "pt", "ru", "tc", "th", "tr", "uk", "zh"}
)

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

# Sin estas el indice no sirve para lo que se usa (piezas prime, reliquias, recursos): si
# una falta en la fuente no se construye nada y se sigue con el indice anterior entero.
# Las demas son opcionales: si fallan se avisa en el log y se usa la copia que ya hubiera.
CATEGORIAS_ESENCIALES = ("Warframes", "Primary", "Secondary", "Melee", "Relics", "Resources")

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


class ErrorDescarga(RuntimeError):
    """Un fichero que no se ha podido bajar. `estado` es el codigo HTTP (None si ni
    siquiera hubo respuesta: sin red, DNS, certificado...)."""

    def __init__(self, url: str, causa: Exception | None, estado: int | None = None):
        super().__init__(f"No se pudo descargar {url}: {causa}")
        self.url = url
        self.estado = estado

    @property
    def no_existe(self) -> bool:
        """La fuente contesta, pero ese fichero ya no esta (lo han movido o quitado)."""
        return self.estado in (404, 410)


class FuenteCambiada(RuntimeError):
    """La fuente ya no publica algo imprescindible, o lo publica con un formato que no se
    sabe leer. El texto va al registro; al usuario solo se le dice que la fuente ha cambiado
    y que se sigue con los datos de antes (ver tareas.motivo_para_el_usuario)."""


def extraer_idioma(datos, idioma: str) -> dict:
    """Las traducciones de un idioma como {uniqueName: {"name", "description", ...}}.

    Acepta los dos formatos de WFCD y los distingue por contenido: en el antiguo
    (i18n.json) cada objeto lleva un diccionario por codigo de idioma
    ({"es": {...}, "fr": {...}}); en el nuevo (i18n/<idioma>.json) lleva directamente
    el nombre y la descripcion. Lo que no trae nada en ese idioma se descarta.
    """
    salida: dict = {}
    if not isinstance(datos, dict):
        return salida
    for unico, valor in datos.items():
        if not isinstance(valor, dict):
            continue
        if isinstance(valor.get(idioma), dict):
            valor = valor[idioma]
        elif CODIGOS_I18N.intersection(valor):
            # Formato antiguo sin este idioma: las claves son otros idiomas, no campos.
            continue
        if valor:
            salida[unico] = valor
    return salida


@dataclass
class EstadoDatos:
    """Lo que hay descargado ahora mismo y de que version es."""

    items_sha: str = ""
    items_fecha: str = ""
    drops_hash: str = ""
    drops_modified: str = ""
    descargado_en: str = ""
    ficheros: dict = field(default_factory=dict)
    # Lo ultimo que WFCD y DE tenian publicado la ultima vez que se miro. Comparado con
    # lo descargado dice si falta algo por bajar o si sencillamente no han publicado
    # nada mas nuevo (DE puede pasar meses sin tocar sus tablas tras un parche).
    publicado_items_sha: str = ""
    publicado_drops_hash: str = ""
    comprobado_en: str = ""
    # Version (ETag o Last-Modified) y fecha de "Last Update" de la tabla oficial de DE.
    oficial_version: str = ""
    oficial_fecha: str = ""

    # Nombre de cada fuente tal como lo da indice.desfase_con_el_juego.
    FUENTES = {
        "catalogo de objetos": ("items_sha", "publicado_items_sha"),
        "tablas de drops": ("drops_hash", "publicado_drops_hash"),
    }

    def al_dia_con_lo_publicado(self, fuente: str) -> bool | None:
        """True si lo descargado es lo ultimo publicado, False si hay algo mas nuevo,
        None si esa fuente nunca se ha podido comprobar."""
        claves = self.FUENTES.get(fuente)
        if not claves:
            return None
        nuestro, publicado = getattr(self, claves[0]), getattr(self, claves[1])
        if not nuestro or not publicado:
            return None
        return nuestro == publicado

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
        reemplazar(tmp, RUTA_ESTADO_DATOS)


def fuentes_pendientes(estado: EstadoDatos, atrasadas: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """De las fuentes anteriores al parche, las que ademas tienen algo mas nuevo publicado
    que no se ha descargado (o que no se ha podido comprobar). Las demas ya son lo ultimo
    que existe: el parche no las ha cambiado todavia."""
    return [(f, fecha) for f, fecha in atrasadas if estado.al_dia_con_lo_publicado(f) is not True]


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
        tmp = temporal_de(destino)
        ultimo_error = None
        estado: int | None = None
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
                reemplazar(tmp, destino)
                return
            except httpx.HTTPError as e:
                ultimo_error = e
                estado = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
                if estado is not None and 400 <= estado < 500 and estado not in (408, 429):
                    # Un 404 no se arregla esperando: reintentar solo retrasaba 7 s el aviso.
                    break
                espera = 2**intento
                log.warning("Fallo descargando %s (%s). Reintento en %ss", url, e, espera)
                time.sleep(espera)
        tmp.unlink(missing_ok=True)
        raise ErrorDescarga(url, ultimo_error, estado)

    # -- versiones ------------------------------------------------------

    def version_items(self) -> tuple[str, str]:
        """Devuelve (sha, fecha) del ultimo commit que toco los JSON."""
        try:
            datos = self._pedir_json(ITEMS_COMMITS, {"Accept": "application/vnd.github+json"})
            sha = str(datos[0]["sha"])
            self._anotar_publicado("publicado_items_sha", sha)
            return sha, datos[0]["commit"]["committer"]["date"]
        except Exception as e:  # noqa: BLE001 - sin version se sigue adelante
            log.warning("No se pudo leer la version de warframe-items: %s", e)
            return "", ""

    def version_drops(self) -> tuple[str, str]:
        for base in (DROPS_BASE, DROPS_ESPEJO):
            try:
                info = self._pedir_json(base + "info.json")
                hash_drops = str(info.get("hash", ""))
                self._anotar_publicado("publicado_drops_hash", hash_drops)
                return hash_drops, str(info.get("modified", ""))
            except Exception as e:  # noqa: BLE001
                log.warning("No se pudo leer info.json de drop-data en %s: %s", base, e)
        return "", ""

    def _anotar_publicado(self, clave: str, valor: str) -> None:
        """Deja apuntado que version esta publicada ahora mismo. Se consulta aqui, que es
        cuando ya se ha pedido; Ajustes lo lee del fichero y no hace ninguna peticion."""
        if not valor:
            return
        setattr(self.estado, clave, valor)
        self.estado.comprobado_en = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            self.estado.guardar()
        except OSError as e:
            log.warning("No se pudo guardar estado_datos.json: %s", e)

    # -- sincronizacion -------------------------------------------------

    def rutas_items(self) -> dict[str, Path]:
        rutas = {c: DIR_DATOS / f"{c}.json" for c in CATEGORIAS_ITEMS}
        rutas["i18n_es"] = DIR_DATOS / "i18n_es.json"
        for idioma in IDIOMAS_EXTRA:
            rutas[f"i18n_{idioma}"] = DIR_DATOS / f"i18n_{idioma}.json"
        return rutas

    @staticmethod
    def ruta_piezas() -> Path:
        return DIR_DATOS / f"{CATALOGO_PIEZAS}.json"

    def rutas_imprescindibles(self) -> list[Path]:
        """Lo que, si falta en disco, obliga a descargar el catalogo aunque no haya version
        nueva. Solo lo esencial: si WFCD deja de publicar un opcional (un idioma, una
        categoria de adornos), buscarlo en cada arranque bajaria 25 MB cada vez para nada."""
        rutas = self.rutas_items()
        return [rutas[c] for c in CATEGORIAS_ESENCIALES] + [rutas["i18n_es"]]

    def rutas_drops(self) -> dict[str, Path]:
        return {f.removesuffix(".json"): DIR_DATOS / "drops" / f for f in FICHEROS_DROPS}

    @staticmethod
    def ruta_tabla_oficial() -> Path:
        return DIR_DATOS / "drops" / FICHERO_TABLA_OFICIAL

    def _faltan(self, rutas: Iterable[Path]) -> bool:
        return any(not r.exists() or r.stat().st_size == 0 for r in rutas)

    def _faltan_piezas(self, rutas_items: dict[str, Path]) -> bool:
        """True si las recetas en disco son del formato nuevo y falta su Components.json.

        Es lo que dejo en disco la version 0.3.0 el dia del cambio de WFCD: bajaba las
        categorias nuevas y se cortaba en el 404 de i18n.json, antes de que existiera el
        catalogo de piezas. Si ademas no se puede leer la version publicada (limite de la
        API de GitHub), nada obligaba a bajar de nuevo y el indice no se podia construir.
        """
        if self.ruta_piezas().exists():
            return False
        try:
            objetos = json.loads(rutas_items["Warframes"].read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            return False
        if not isinstance(objetos, list):
            return False
        return any(
            isinstance(pieza, dict) and not pieza.get("name")
            for obj in objetos
            if isinstance(obj, dict) and isinstance(obj.get("components"), list)
            for pieza in obj["components"]
        )

    def sincronizar(self, forzar: bool = False) -> bool:
        """Deja la carpeta de datos al dia. Devuelve True si algo cambio."""
        crear_carpetas()
        cambios = False

        sha, fecha = self.version_items()
        rutas_items = self.rutas_items()
        toca_items = (
            forzar
            or self._faltan(self.rutas_imprescindibles())
            or self._faltan_piezas(rutas_items)
            or (sha and sha != self.estado.items_sha)
        )

        if toca_items:
            self._descargar_catalogo(rutas_items)
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

        if self._sincronizar_tabla_oficial(forzar):
            cambios = True

        if cambios:
            self.estado.descargado_en = time.strftime("%Y-%m-%dT%H:%M:%S")
            self.estado.ficheros = {
                k: v.stat().st_size
                for k, v in {
                    **rutas_items, **rutas_drops, "tabla_oficial": self.ruta_tabla_oficial(),
                    CATALOGO_PIEZAS: self.ruta_piezas(),
                }.items()
                if v.exists()
            }
            self.estado.guardar()
        return cambios

    def _sincronizar_tabla_oficial(self, forzar: bool = False) -> bool:
        """Baja la tabla oficial de DE si ha cambiado. True si hay una nueva.

        Nunca lanza: sin ella el indice se construye solo con WFCD, como siempre. La
        descarga es atomica (fichero .tmp), asi que no puede quedar una pagina a medias.
        """
        ruta = self.ruta_tabla_oficial()
        try:
            r = self.cliente.head(URL_TABLA_OFICIAL, timeout=20.0)
            r.raise_for_status()
            version = r.headers.get("etag") or r.headers.get("last-modified") or ""
        except httpx.HTTPError as e:
            log.warning("No se pudo consultar la tabla oficial de DE (%s); se sigue con WFCD", e)
            return False
        hay = ruta.exists() and ruta.stat().st_size > 0
        if hay and not forzar and version and version == self.estado.oficial_version:
            log.info("Tabla oficial de DE al dia (%s)", self.estado.oficial_fecha or version)
            return False
        self.progreso("Descargando la tabla oficial de DE", 0, 0)
        try:
            self._descargar_una_vez(URL_TABLA_OFICIAL, ruta, "Descargando la tabla oficial de DE")
            with ruta.open(encoding="utf-8", errors="replace") as f:
                fecha = fecha_publicacion(f.read(20_000))
        except (RuntimeError, OSError) as e:
            log.warning("No se pudo descargar la tabla oficial de DE (%s); se sigue con WFCD", e)
            return False
        self.estado.oficial_version = version
        self.estado.oficial_fecha = fecha.isoformat() if fecha else ""
        log.info("Tabla oficial de DE descargada (%s)", self.estado.oficial_fecha or "sin fecha")
        return True

    def _descargar_catalogo(self, rutas_items: dict[str, Path]) -> None:
        """Baja las categorias, el catalogo de piezas y las traducciones.

        Un fichero esencial que la fuente ya no tiene (404) lanza FuenteCambiada antes de
        construir nada: el indice anterior se queda entero. Uno opcional que falle solo deja
        un aviso en el registro y se sigue con la copia que hubiera en disco, si la hay.
        """
        total = len(CATEGORIAS_ITEMS) + 2
        for i, categoria in enumerate(CATEGORIAS_ITEMS, start=1):
            self.progreso(f"Descargando catalogo: {categoria} ({i}/{total})", i - 1, total)
            try:
                self._descargar_fichero(
                    ITEMS_BASE + f"{categoria}.json",
                    rutas_items[categoria],
                    f"Descargando {categoria}",
                )
            except ErrorDescarga as e:
                if categoria in CATEGORIAS_ESENCIALES:
                    if e.no_existe:
                        raise FuenteCambiada(f"WFCD ya no publica {categoria}.json ({e})") from e
                    raise
                self._avisar_opcional(f"{categoria}.json", e, rutas_items[categoria])

        self.progreso(
            f"Descargando catalogo: {CATALOGO_PIEZAS} ({total - 1}/{total})", total - 2, total
        )
        try:
            self._descargar_fichero(
                ITEMS_BASE + f"{CATALOGO_PIEZAS}.json",
                self.ruta_piezas(),
                f"Descargando {CATALOGO_PIEZAS}",
            )
        except ErrorDescarga as e:
            if e.no_existe:
                # Formato antiguo: las piezas vienen dentro de cada objeto. Si los objetos
                # traen referencias y falta el catalogo, lo detecta el importador.
                log.info("WFCD no publica %s.json; se espera el formato con las piezas dentro "
                         "de cada objeto", CATALOGO_PIEZAS)
            else:
                self._avisar_opcional(f"{CATALOGO_PIEZAS}.json", e, self.ruta_piezas())

        self.progreso(f"Descargando traducciones ({total}/{total})", total - 1, total)
        self._descargar_i18n(rutas_items)

    @staticmethod
    def _avisar_opcional(nombre: str, error: Exception, ruta: Path) -> None:
        if ruta.exists() and ruta.stat().st_size > 0:
            log.warning("No se pudo actualizar %s (%s); se usa la copia anterior", nombre, error)
        else:
            log.warning("No se pudo descargar %s (%s); el indice se construye sin el", nombre, error)

    def _descargar_i18n(self, rutas_items: dict[str, Path]) -> None:
        """Deja un i18n_<idioma>.json por idioma (es, y ademas IDIOMAS_EXTRA) con
        {uniqueName: {"name", "description"}}, que es lo que lee el indice.

        Primero se prueba la carpeta i18n/ del formato nuevo, bajando solo los idiomas que
        se usan (unos 27 MB en vez de los ~70 de los catorce). Lo que no este ahi se busca
        en el i18n.json antiguo, que trae todos los idiomas juntos. Si un idioma no sale de
        ninguno de los dos se conserva el fichero anterior; sin castellano, ni anterior ni
        nuevo, no se construye (seria un indice con media interfaz en ingles).
        """
        faltan: list[str] = []
        for idioma in ("es", *IDIOMAS_EXTRA):
            crudo = DIR_DATOS / f"i18n_{idioma}.descarga"
            try:
                self._descargar_fichero(
                    ITEMS_I18N + f"{idioma}.json", crudo, f"Descargando traducciones ({idioma})"
                )
                with crudo.open(encoding="utf-8") as f:
                    datos = json.load(f)
            except (ErrorDescarga, OSError, ValueError) as e:
                if not (isinstance(e, ErrorDescarga) and e.no_existe):
                    log.warning("Traducciones al %s de la carpeta i18n/ sin bajar: %s", idioma, e)
                faltan.append(idioma)
                continue
            finally:
                crudo.unlink(missing_ok=True)
            if not self._guardar_idioma(datos, idioma, rutas_items[f"i18n_{idioma}"]):
                faltan.append(idioma)

        if faltan:
            self._descargar_i18n_antiguo(faltan, rutas_items)

    @staticmethod
    def _guardar_idioma(datos, idioma: str, destino: Path) -> bool:
        """Guarda las traducciones de un idioma. False si no traian ninguna (formato raro)."""
        solo_idioma = extraer_idioma(datos, idioma)
        if not solo_idioma:
            log.warning("Las traducciones al %s no traen ningun nombre reconocible", idioma)
            return False
        tmp = temporal_de(destino)
        tmp.write_text(json.dumps(solo_idioma, ensure_ascii=False), encoding="utf-8")
        reemplazar(tmp, destino)
        log.info("Traducciones al %s: %d objetos", idioma, len(solo_idioma))
        return True

    def _descargar_i18n_antiguo(self, idiomas: list[str], rutas_items: dict[str, Path]) -> None:
        """i18n.json con todos los idiomas (~50 MB): el formato de WFCD hasta septiembre de 2026."""
        crudo = DIR_DATOS / "i18n.json"
        todos = None
        try:
            self._descargar_fichero(ITEMS_BASE + "i18n.json", crudo, "Descargando traducciones")
            self.progreso("Filtrando traducciones", 0, 0)
            with crudo.open(encoding="utf-8") as f:
                todos = json.load(f)
        except (ErrorDescarga, OSError, ValueError) as e:
            log.warning("Tampoco se pudo usar el i18n.json antiguo: %s", e)
        finally:
            crudo.unlink(missing_ok=True)
        for idioma in idiomas:
            destino = rutas_items[f"i18n_{idioma}"]
            if todos is not None and self._guardar_idioma(todos, idioma, destino):
                continue
            if destino.exists() and destino.stat().st_size > 0:
                log.warning("Sin traducciones nuevas al %s; se usan las anteriores", idioma)
            elif idioma == "es":
                raise FuenteCambiada("WFCD no publica las traducciones al castellano en ningun "
                                     "formato conocido (ni i18n/es.json ni i18n.json)")
            else:
                log.warning("Sin traducciones al %s: esos nombres saldran en ingles", idioma)

    def cerrar(self) -> None:
        self.cliente.close()
