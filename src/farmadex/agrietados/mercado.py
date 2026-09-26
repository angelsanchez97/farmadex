"""Datos publicos de agrietados: disposiciones y subastas (warframe.market) y medias de DE.

- `armas()`: la lista de armas con agrietado de warframe.market (v2), con su
  disposicion numerica, su tipo y su uniqueName del juego. Se guarda en disco un
  dia: es lo que hace falta para evaluar aunque no haya red en ese momento.
- `subastas(arma, ...)`: las subastas abiertas de ese arma (v1, la unica API de
  subastas publicada), filtrables por estadisticas. Cache de diez minutos.
- `medias_de()`: la tabla semanal que publica Digital Extremes con precio medio,
  mediana y volumen de cada arma (weeklyRivensPC.json). Cache de un dia.

Limites: warframe.market publica 3 peticiones por segundo; aqui se hace 1 por
segundo, que sobra para una consulta hecha a mano.
"""

from __future__ import annotations

import json
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import NOMBRE_APP, URL_CONTACTO, VERSION
from ..config import DIR_DATOS, PLATAFORMA
from ..online.http import Cliente
from ..registro_log import obtener
from . import grados

log = obtener("agrietados.mercado")

BASE_V2 = "https://api.warframe.market/v2"
BASE_V1 = "https://api.warframe.market/v1"
URL_MEDIAS_DE = "https://www-static.warframe.com/repos/weeklyRivensPC.json"
POR_SEGUNDO = 1.0
CACHE_SUBASTAS = 600
CACHE_ARMAS = 86400
FICHERO_ARMAS = "agrietados_armas.json"


@dataclass(frozen=True)
class Arma:
    slug: str
    nombre_en: str
    unique_name: str
    tipo: str  # rivenType de warframe.market: rifle, shotgun, pistol, melee, zaw, kitgun
    grupo: str  # primary, secondary, melee, archgun, sentinel, zaw, kitgun
    disposicion: float
    maestria: int | None = None

    @property
    def clase(self) -> str:
        return grados.clase_de(self.tipo, self.grupo)


@dataclass
class Subasta:
    precio: int | None  # buyout; None si es puja pura
    puja_inicial: int | None
    atributos: list[tuple[str, float, bool]]  # (slug, valor, negativo)
    variado: int
    rango: int
    maestria: int | None
    polaridad: str
    nombre: str
    vendedor: str
    estado: str  # ingame, online, offline

    @property
    def referencia(self) -> int | None:
        return self.precio if self.precio is not None else self.puja_inicial


@dataclass
class ResumenSubastas:
    arma: str
    total: int = 0
    subastas: list[Subasta] = field(default_factory=list)
    error: str = ""

    @property
    def precios(self) -> list[int]:
        return sorted(s.referencia for s in self.subastas if s.referencia)

    @property
    def minimo(self) -> int | None:
        p = self.precios
        return p[0] if p else None

    @property
    def mediana(self) -> float | None:
        p = self.precios
        return statistics.median(p) if p else None


@dataclass
class MediaDE:
    arma_en: str
    variado: bool
    media: float
    mediana: float
    minimo: float
    maximo: float
    volumen: int


class MercadoAgrietados:
    def __init__(self, idioma: str = "es", carpeta: Path = DIR_DATOS, cliente: Cliente | None = None):
        contacto = URL_CONTACTO or "herramienta personal, aun sin publicar"
        self.cliente = cliente or Cliente(
            por_segundo=POR_SEGUNDO,
            cabeceras={
                "User-Agent": f"{NOMBRE_APP}/{VERSION} (+{contacto})",
                "Language": idioma,
                "Platform": PLATAFORMA,
                "Accept": "application/json",
            },
        )
        self.carpeta = Path(carpeta)
        self._armas: list[Arma] | None = None
        self._medias_cache: tuple[float, dict] | None = None
        self._cerrojo = threading.Lock()

    # -- armas y disposiciones ------------------------------------------------------------

    def armas(self, forzar_red: bool = False) -> list[Arma]:
        """Armas con agrietado. Primero el fichero de disco (si tiene menos de un dia); si no, la red."""
        with self._cerrojo:
            if self._armas is not None and not forzar_red:
                return self._armas
            ruta = self.carpeta / FICHERO_ARMAS
            guardado = _leer_guardado(ruta)
            if guardado and not forzar_red and time.time() - guardado.get("cuando", 0) < CACHE_ARMAS:
                self._armas = [Arma(**a) for a in guardado["armas"]]
                return self._armas
            try:
                datos = self.cliente.json(f"{BASE_V2}/riven/weapons", segundos_cache=CACHE_ARMAS)
                armas = analizar_armas(datos)
            except Exception as e:  # noqa: BLE001 - sin red se usa lo guardado aunque sea viejo
                log.warning("No se pudo bajar la lista de armas con agrietado: %s", e)
                armas = [Arma(**a) for a in guardado["armas"]] if guardado else []
            else:
                _guardar(ruta, {"cuando": time.time(), "armas": [a.__dict__ for a in armas]})
            self._armas = armas
            return armas

    def arma_por_unique_name(self, unique_name: str) -> Arma | None:
        for arma in self.armas():
            if arma.unique_name == unique_name:
                return arma
        return None

    def arma_por_slug(self, slug: str) -> Arma | None:
        for arma in self.armas():
            if arma.slug == slug:
                return arma
        return None

    # -- subastas ----------------------------------------------------------------------

    def subastas(
        self,
        arma_slug: str,
        positivos: list[str] | None = None,
        negativos: list[str] | None = None,
        limite: int = 30,
    ) -> ResumenSubastas:
        """Subastas abiertas de ese arma, de mas barata a mas cara.

        `positivos`/`negativos` son slugs de atributo: con ellos se piden solo las
        que los lleven (asi el precio de referencia es de agrietados parecidos, que
        es como manda la guia). Sin resultados con filtro, se vuelve a pedir sin el.
        """
        positivos = [p for p in (positivos or []) if p]
        negativos = [n for n in (negativos or []) if n]
        try:
            resumen = self._pedir_subastas(arma_slug, positivos, negativos, limite)
            if not resumen.subastas and (positivos or negativos):
                resumen = self._pedir_subastas(arma_slug, [], [], limite)
            return resumen
        except Exception as e:  # noqa: BLE001 - un fallo de red no puede tumbar el hilo
            log.warning("Sin subastas de %s: %s", arma_slug, e)
            return ResumenSubastas(arma=arma_slug, error=str(e))

    def _pedir_subastas(self, arma_slug: str, positivos: list[str], negativos: list[str], limite: int) -> ResumenSubastas:
        partes = [f"type=riven", f"weapon_url_name={arma_slug}", "sort_by=price_asc", "buyout_policy=direct"]
        if positivos:
            partes.append("positive_stats=" + ",".join(positivos))
        if negativos:
            partes.append("negative_stats=" + ",".join(negativos))
        datos = self.cliente.json(f"{BASE_V1}/auctions/search?" + "&".join(partes), segundos_cache=CACHE_SUBASTAS)
        resumen = analizar_subastas(arma_slug, datos)
        resumen.subastas = resumen.subastas[:limite]
        return resumen

    # -- medias de DE ----------------------------------------------------------------------

    def medias_de(self) -> dict[tuple[str, bool], MediaDE]:
        """(nombre en ingles en minusculas, variado) -> media semanal de DE. Vacio si no hay red.

        El fichero de DE no es JSON estricto (claves sin comillas, cadenas con comilla
        simple), asi que se baja como texto y lo arregla `analizar_medias_de`.
        """
        with self._cerrojo:
            guardado = self._medias_cache
            if guardado and time.monotonic() - guardado[0] < CACHE_ARMAS:
                return guardado[1]
        try:
            self.cliente.limitador.esperar()
            respuesta = self.cliente.cliente.get(URL_MEDIAS_DE)
            respuesta.raise_for_status()
            medias = analizar_medias_de(respuesta.text)
        except Exception as e:  # noqa: BLE001
            log.info("Sin medias semanales de DE: %s", e)
            return {}
        with self._cerrojo:
            self._medias_cache = (time.monotonic(), medias)
        return medias

    def cerrar(self) -> None:
        self.cliente.cerrar()


# -- parseo (sin red, para las pruebas) -------------------------------------------------


def analizar_armas(datos: dict) -> list[Arma]:
    lista = datos.get("data") if isinstance(datos, dict) else None
    if not isinstance(lista, list):
        raise ValueError("falta 'data' o no es una lista")
    armas = []
    for e in lista:
        if not isinstance(e, dict) or not e.get("slug"):
            continue
        nombre = ((e.get("i18n") or {}).get("en") or {}).get("name") or e["slug"].replace("_", " ").title()
        try:
            disposicion = float(e.get("disposition") or 0)
        except (TypeError, ValueError):
            disposicion = 0.0
        if disposicion <= 0:
            continue
        maestria = e.get("reqMasteryRank")
        armas.append(Arma(
            slug=str(e["slug"]),
            nombre_en=str(nombre),
            unique_name=str(e.get("gameRef") or ""),
            tipo=str(e.get("rivenType") or ""),
            grupo=str(e.get("group") or ""),
            disposicion=disposicion,
            maestria=int(maestria) if isinstance(maestria, (int, float)) else None,
        ))
    return armas


def analizar_subastas(arma_slug: str, datos: dict) -> ResumenSubastas:
    cuerpo = (datos.get("payload") or {}) if isinstance(datos, dict) else {}
    lista = cuerpo.get("auctions")
    if not isinstance(lista, list):
        raise ValueError("falta 'payload.auctions'")
    resumen = ResumenSubastas(arma=arma_slug, total=len(lista))
    for a in lista:
        if not isinstance(a, dict) or a.get("closed"):
            continue
        item = a.get("item") or {}
        if item.get("type") != "riven":
            continue
        atributos = []
        for at in item.get("attributes") or []:
            slug = at.get("url_name")
            try:
                valor = float(at.get("value"))
            except (TypeError, ValueError):
                continue
            if slug:
                atributos.append((str(slug), valor, not at.get("positive", valor >= 0)))
        dueno = a.get("owner") or {}
        resumen.subastas.append(Subasta(
            precio=_entero(a.get("buyout_price")),
            puja_inicial=_entero(a.get("starting_price")),
            atributos=atributos,
            variado=int(item.get("re_rolls") or 0),
            rango=int(item.get("mod_rank") or 0),
            maestria=_entero(item.get("mastery_level")),
            polaridad=str(item.get("polarity") or ""),
            nombre=str(item.get("name") or ""),
            vendedor=str(dueno.get("ingame_name") or ""),
            estado=str(dueno.get("status") or "offline"),
        ))
    resumen.subastas.sort(key=lambda s: (s.referencia is None, s.referencia or 0))
    return resumen


def _js_a_json(texto: str) -> str:
    """El fichero de DE viene como objeto de JavaScript: claves a pelo y comillas simples."""
    import re

    texto = re.sub(r"(?m)^(\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', texto)
    texto = re.sub(r"'((?:[^'\\]|\\.)*)'", lambda m: '"' + m.group(1).replace("\\'", "'").replace('"', '\\"') + '"', texto)
    return texto


def analizar_medias_de(datos) -> dict[tuple[str, bool], MediaDE]:
    if isinstance(datos, (str, bytes)):
        texto = datos.decode("utf-8", "replace") if isinstance(datos, bytes) else datos
        try:
            datos = json.loads(texto)
        except ValueError:
            datos = json.loads(_js_a_json(texto))
    if not isinstance(datos, list):
        raise ValueError("la tabla de DE no es una lista")
    salida = {}
    for fila in datos:
        if not isinstance(fila, dict):
            continue
        arma = fila.get("compatibility")
        if not arma:
            continue  # la fila generica de cada tipo (sin arma) no sirve
        try:
            media = MediaDE(
                arma_en=str(arma),
                variado=bool(fila.get("rerolled")),
                media=float(fila.get("avg") or 0),
                mediana=float(fila.get("median") or 0),
                minimo=float(fila.get("min") or 0),
                maximo=float(fila.get("max") or 0),
                volumen=int(fila.get("pop") or 0),
            )
        except (TypeError, ValueError):
            continue
        salida[(media.arma_en.lower(), media.variado)] = media
    return salida


def _entero(valor) -> int | None:
    try:
        return int(float(valor)) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _leer_guardado(ruta: Path) -> dict | None:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) and isinstance(datos.get("armas"), list) else None


def _guardar(ruta: Path, datos: dict) -> None:
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        log.warning("No se pudo guardar %s: %s", ruta, e)


# -- instancia compartida ---------------------------------------------------------------

_instancia: MercadoAgrietados | None = None
_cerrojo = threading.Lock()


def compartido() -> MercadoAgrietados:
    global _instancia
    with _cerrojo:
        if _instancia is None:
            _instancia = MercadoAgrietados()
        return _instancia


def cerrar_compartido() -> None:
    global _instancia
    with _cerrojo:
        instancia, _instancia = _instancia, None
    if instancia is not None:
        instancia.cerrar()
