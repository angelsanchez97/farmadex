"""Foto diaria de precios de warframe.market: consultas al instante, sin red.

Cada dia a las 00:00 UTC un workflow de GitHub (herramientas/precios/generar.py)
recorre warframe.market entero y publica `precios.json.gz` en la release fija
"precios" del repositorio. Aqui se baja ese fichero en segundo plano una vez al
dia y se contesta cualquier consulta de precio con un diccionario en memoria.

Contrato (lo usan la vista, el chat y lo que venga):

    from farmadex.online.precios_diarios import precios
    p = precios().buscar("arcane_energize", 5)      # Precio | None, O(1), sin red
    precios().rangos("arcane_energize")             # [0, 1, 3, 5]
    precios().fecha                                 # datetime UTC de la foto o None
    precios().proxima_actualizacion                 # siguiente 00:00 UTC
    precios().al_actualizar(repintar)               # se llama en el hilo de la interfaz

- `precios()` nunca bloquea: la primera vez devuelve el objeto vacio y lanza la
  carga del fichero local en un hilo. Mientras carga, `buscar()` da None (quien
  consulta hace lo de siempre: la consulta en vivo de online/market.py) y, al
  terminar, avisa a los observadores de `al_actualizar`.
- La descarga la hace un solo `Descargador` con cerrojo: el boton "Actualizar
  ahora" y la automatica de medianoche no chocan; si coinciden, el segundo se une
  a la que esta en marcha.
- Si hoy aun no hay foto nueva (el workflow tarda cerca de una hora), se sigue con
  la anterior, que lleva su fecha, y se reintenta mas tarde.
- La foto es de PC. Con otra plataforma configurada `buscar()` da None siempre:
  mejor la consulta en vivo que un precio de otra plataforma.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ..registro_log import obtener

log = obtener("precios_diarios")

FORMATO = 1
NOMBRE = "precios.json.gz"
NOMBRE_VERSION = "precios_version.json"
ETIQUETA_RELEASE = "precios"
# El fichero ronda unos pocos MB; mas de esto es que algo no cuadra.
TAMANO_MAXIMO = 64 * 1024 * 1024
# Margen aleatorio tras las 00:00 UTC antes de mirar si hay foto nueva: da tiempo
# al workflow y reparte a todos los Farmadex para no llegar a GitHub a la vez.
MARGEN_MIN = (5, 20)
# Si aun no esta la foto de hoy, se vuelve a mirar pasado este rato (minutos).
REINTENTO_SIN_FOTO = (15, 30)
# Sin red o con error: 5, 10, 20, 40 y luego cada 60 minutos (mas un poco de azar).
REINTENTO_FALLO_MIN = 5
REINTENTO_FALLO_MAX = 60
# El programador mira el reloj como mucho cada tantos segundos: tras suspender el
# PC se entera enseguida de que ya es otro dia. En reposo no gasta nada.
PASO_RELOJ_S = 60.0


def url_base() -> str:
    from ..actualizador.app import PROPIETARIO, REPOSITORIO

    return f"https://github.com/{PROPIETARIO}/{REPOSITORIO}/releases/download/{ETIQUETA_RELEASE}/"


def carpeta_por_defecto() -> Path:
    from .. import config

    return Path(config.DIR_BASE) / "precios"


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def siguiente_medianoche(ahora: datetime) -> datetime:
    """La proxima 00:00 UTC estrictamente posterior a `ahora`."""
    ahora = ahora.astimezone(timezone.utc)
    return ahora.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def _fecha(texto) -> datetime | None:
    try:
        f = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return f if f.tzinfo else f.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Precio:
    """Precio de un objeto (y rango) segun la foto del dia. None = sin datos, nunca 0 inventado.

    venta_min / venta_mediana / compra_max: ordenes de jugadores conectados en el
    momento de la foto (mediana de las 5 ventas mas baratas, como la consulta en
    vivo). min_30d / max_30d / media_30d / volumen_30d: operaciones cerradas de los
    ultimos 30 dias segun las estadisticas de warframe.market.
    """

    slug: str
    rango: int | None
    venta_min: float | None
    venta_mediana: float | None
    compra_max: float | None
    min_30d: float | None
    max_30d: float | None
    media_30d: float | None
    volumen_30d: int | None
    fecha: datetime | None
    # Extras (con valor por defecto para que los falsos de las pruebas no los necesiten).
    subtipo: str | None = None
    mediana_30d: float | None = None
    dias_30d: int | None = None        # dias de los ultimos 30 con alguna venta
    volumen_48h: int | None = None
    vendedores: int | None = None      # ordenes de venta de conectados
    compradores: int | None = None
    cantidad_venta: int | None = None
    rango_max: int | None = None

    @property
    def tiene_datos(self) -> bool:
        return any(v is not None for v in (self.venta_min, self.compra_max, self.min_30d))


def _clave(rango: int | None, subtipo: str | None) -> str:
    r = "" if rango is None else str(int(rango))
    return f"{r}|{subtipo}" if subtipo else r


def _partir_clave(clave: str) -> tuple[int | None, str | None]:
    r, _, s = clave.partition("|")
    try:
        rango = int(r) if r != "" else None
    except ValueError:
        rango = None
    return rango, (s or None)


def validar_documento(doc) -> str:
    """Motivo por el que `doc` no sirve, o "" si sirve."""
    if not isinstance(doc, dict):
        return "no es un objeto JSON"
    if doc.get("formato") != FORMATO:
        return f"formato {doc.get('formato')!r} desconocido"
    if _fecha(doc.get("fecha")) is None:
        return "sin fecha"
    campos = doc.get("campos")
    if not isinstance(campos, list) or "venta_min" not in campos:
        return "sin campos"
    objetos = doc.get("objetos")
    if not isinstance(objetos, dict) or not objetos:
        return "sin objetos"
    return ""


def _plataforma_configurada() -> str:
    try:
        from .market import plataforma_configurada

        return plataforma_configurada()
    except Exception:  # noqa: BLE001
        return "pc"


class PreciosDiarios:
    """La foto del dia en memoria. Lecturas sin cerrojo: el diccionario se cambia de golpe."""

    def __init__(self, carpeta: Path | None = None, plataforma: str | None = None):
        self.carpeta = Path(carpeta) if carpeta else carpeta_por_defecto()
        self._plataforma = plataforma
        self._doc: dict | None = None
        self._objetos: dict = {}
        self._indices: dict[str, int] = {}
        self._cache: dict[tuple, Precio | None] = {}
        self._fecha: datetime | None = None
        self._observadores: list[Callable[[], None]] = []
        self._cerrojo = threading.Lock()
        self._hilo_carga: threading.Thread | None = None
        self.cargado = threading.Event()   # la carga inicial ha terminado (con o sin fichero)
        self.problema_local = ""           # por que no se pudo usar el fichero local
        self.descargador: Descargador | None = None

    # -- rutas -----------------------------------------------------------------

    @property
    def ruta(self) -> Path:
        return self.carpeta / NOMBRE

    @property
    def ruta_version(self) -> Path:
        return self.carpeta / NOMBRE_VERSION

    # -- carga ------------------------------------------------------------------

    def cargar_en_segundo_plano(self) -> None:
        """Lee el fichero local en un hilo (una sola vez). No bloquea a quien llama."""
        with self._cerrojo:
            if self.cargado.is_set() or self._hilo_carga is not None:
                return
            self._hilo_carga = threading.Thread(target=self.cargar_local, name="precios-carga", daemon=True)
            self._hilo_carga.start()

    def cargar_local(self) -> bool:
        """Lee y activa el fichero local; True si habia uno valido. Solo desde hilos de fondo."""
        try:
            if not self.ruta.exists():
                return False
            doc = json.loads(gzip.decompress(self.ruta.read_bytes()))
            motivo = validar_documento(doc)
            if motivo:
                raise ValueError(motivo)
        except Exception as e:  # noqa: BLE001 - fichero cortado, borrado a medias, otro formato
            self.problema_local = str(e) or type(e).__name__
            log.warning("La foto de precios local no sirve (%s): se usara la consulta en vivo", self.problema_local)
            return False
        finally:
            self.cargado.set()
        self.instalar(doc)
        return True

    def instalar(self, doc: dict) -> None:
        """Pone `doc` (ya validado) como foto activa y avisa a los observadores."""
        campos = doc.get("campos") or []
        indices = {c: i for i, c in enumerate(campos)}
        with self._cerrojo:
            self._doc = doc
            self._objetos = doc.get("objetos") or {}
            self._indices = indices
            self._fecha = _fecha(doc.get("fecha"))
            self._cache = {}
            self.problema_local = ""
        self.cargado.set()
        log.info("Foto de precios activa: %s (%d objetos)", doc.get("fecha"), len(self._objetos))
        self._avisar()

    # -- consultas (hilo de la interfaz: nada de red ni disco) ------------------------

    @property
    def disponible(self) -> bool:
        """Hay foto cargada y es de la plataforma configurada."""
        doc = self._doc
        if doc is None:
            return False
        plataforma = self._plataforma or _plataforma_configurada()
        return str(doc.get("plataforma") or "pc") == plataforma

    @property
    def fecha(self) -> datetime | None:
        return self._fecha

    @property
    def proxima_actualizacion(self) -> datetime:
        return siguiente_medianoche(ahora_utc())

    def __len__(self) -> int:
        return len(self._objetos)

    def __bool__(self) -> bool:
        # Sin esto, una foto aun vacia contaria como falsa en `precios() or ...`.
        return True

    def __contains__(self, slug: str) -> bool:
        return slug in self._objetos

    def rangos(self, slug: str) -> list[int]:
        objeto = self._objetos.get(slug) if self.disponible else None
        if not objeto:
            return []
        return sorted({r for r, _ in map(_partir_clave, objeto.get("p") or {}) if r is not None})

    def subtipos(self, slug: str) -> list[str]:
        objeto = self._objetos.get(slug) if self.disponible else None
        return list(objeto.get("s") or []) if objeto else []

    def rango_max(self, slug: str) -> int | None:
        objeto = self._objetos.get(slug) if self.disponible else None
        return objeto.get("r") if objeto else None

    def buscar(self, slug: str, rango: int | None = None, subtipo: str | None = None) -> Precio | None:
        """Precio del objeto a ese rango. Sin rango, en mods y arcanos, el rango maximo.

        En objetos con subtipos (reliquias: intact/radiant...) sin `subtipo` se da el
        primero que publica warframe.market (Intacta en las reliquias). None si no
        hay foto, el objeto no esta o ese rango no tiene ningun dato.
        """
        clave_cache = (slug, rango, subtipo)
        cache = self._cache
        if clave_cache in cache:
            return cache[clave_cache]
        resultado = self._construir(slug, rango, subtipo) if self.disponible else None
        cache[clave_cache] = resultado
        return resultado

    def _construir(self, slug: str, rango: int | None, subtipo: str | None) -> Precio | None:
        objeto = self._objetos.get(slug)
        if not isinstance(objeto, dict):
            return None
        mercados = objeto.get("p") or {}
        rango_max = objeto.get("r")
        if subtipo is None and objeto.get("s"):
            subtipo = objeto["s"][0]
        if rango is None and rango_max is not None:
            rango = rango_max
            if _clave(rango, subtipo) not in mercados:
                # Sin datos al rango maximo: el mas alto que tenga alguno.
                vistos = [r for r, s in map(_partir_clave, mercados) if r is not None and s == subtipo]
                rango = max(vistos) if vistos else rango
        valores = mercados.get(_clave(rango, subtipo))
        if valores is None and rango_max is None and rango is not None:
            valores = mercados.get(_clave(None, subtipo))  # piden rango de algo sin rangos
            rango = None if valores is not None else rango
        if not isinstance(valores, list):
            return None
        i = self._indices

        def v(campo: str):
            k = i.get(campo)
            return valores[k] if k is not None and k < len(valores) else None

        return Precio(
            slug=slug, rango=rango, venta_min=v("venta_min"), venta_mediana=v("venta_mediana"),
            compra_max=v("compra_max"), min_30d=v("min_30d"), max_30d=v("max_30d"),
            media_30d=v("media_30d"), volumen_30d=v("volumen_30d"), fecha=self._fecha,
            subtipo=subtipo, mediana_30d=v("mediana_30d"), dias_30d=v("dias_30d"),
            volumen_48h=v("volumen_48h"), vendedores=v("vendedores"), compradores=v("compradores"),
            cantidad_venta=v("cantidad_venta"), rango_max=rango_max,
        )

    def objetos(self) -> dict:
        """El diccionario crudo slug -> objeto (para la lista de rentabilidad; solo lectura)."""
        return self._objetos if self.disponible else {}

    # -- observadores ---------------------------------------------------------------

    def al_actualizar(self, callback: Callable[[], None]) -> None:
        """`callback()` cada vez que entra una foto nueva (en el hilo de la interfaz si lo hay)."""
        with self._cerrojo:
            if callback not in self._observadores:
                self._observadores.append(callback)

    def quitar_observador(self, callback: Callable[[], None]) -> None:
        with self._cerrojo:
            if callback in self._observadores:
                self._observadores.remove(callback)

    def _avisar(self) -> None:
        with self._cerrojo:
            observadores = list(self._observadores)
        for cb in observadores:
            _en_hilo_principal(cb)

    # -- descarga ---------------------------------------------------------------------

    def actualizar_ahora(self) -> "Tarea":
        """Boton "Actualizar precios": se une a la descarga en curso si la hay."""
        return self._asegurar_descargador().actualizar(manual=True)

    def _asegurar_descargador(self) -> "Descargador":
        with self._cerrojo:
            if self.descargador is None:
                self.descargador = Descargador(self)
            return self.descargador


def _en_hilo_principal(cb: Callable[[], None]) -> None:
    """Llama a `cb` en el hilo de Qt si hay aplicacion; si no, aqui mismo."""
    try:
        from PySide6.QtCore import QCoreApplication, QThread, QTimer

        app = QCoreApplication.instance()
    except Exception:  # noqa: BLE001
        app = None
    if app is None or QThread.currentThread() is app.thread():
        try:
            cb()
        except Exception:  # noqa: BLE001 - un observador roto no para a los demas
            log.exception("Fallo avisando de precios nuevos")
        return

    def seguro():
        try:
            cb()
        except Exception:  # noqa: BLE001
            log.exception("Fallo avisando de precios nuevos")

    QTimer.singleShot(0, app, seguro)


# -- descarga ---------------------------------------------------------------------------


class Tarea:
    """Una descarga en marcha; quien llega tarde espera a esta misma."""

    def __init__(self, manual: bool):
        self.manual = manual
        self.hecha = threading.Event()
        self.resultado = ""   # nuevo | al_dia | aun_no_hay | sin_red | error | otra_plataforma
        self.detalle = ""

    def esperar(self, segundos: float | None = None) -> str:
        self.hecha.wait(segundos)
        return self.resultado


class Descargador:
    """Baja la foto del dia en segundo plano; uno solo por aplicacion."""

    def __init__(self, precios: PreciosDiarios, base: str | None = None, transporte=None,
                 reloj: Callable[[], datetime] = ahora_utc, azar: random.Random | None = None):
        self.precios = precios
        self.base = base or url_base()
        self.transporte = transporte
        self.reloj = reloj
        self.azar = azar or random.Random()
        self._cerrojo = threading.Lock()
        self._tarea: Tarea | None = None
        self._parar = threading.Event()
        self._despertar = threading.Event()
        self._hilo: threading.Thread | None = None
        self.proximo_intento: datetime | None = None
        self.fallos_seguidos = 0
        self.ultima: Tarea | None = None
        self.estado = "sin_comprobar"
        self.descargas = 0   # descargas reales del fichero grande (para las pruebas)

    # -- una descarga ---------------------------------------------------------------

    def actualizar(self, manual: bool = False) -> Tarea:
        with self._cerrojo:
            if self._tarea is not None and not self._tarea.hecha.is_set():
                return self._tarea  # ya hay una en marcha: se une a esa
            tarea = self._tarea = Tarea(manual)
            self.estado = "descargando"
        threading.Thread(target=self._correr, args=(tarea,), name="precios-descarga", daemon=True).start()
        return tarea

    def _correr(self, tarea: Tarea) -> None:
        try:
            tarea.resultado, tarea.detalle = self._descargar()
        except Exception as e:  # noqa: BLE001 - nunca tumba nada: se reintenta luego
            log.exception("Fallo inesperado bajando la foto de precios")
            tarea.resultado, tarea.detalle = "error", str(e)
        finally:
            self.estado = tarea.resultado
            self.ultima = tarea
            if tarea.resultado in ("sin_red", "error"):
                self.fallos_seguidos += 1
            else:
                self.fallos_seguidos = 0
            tarea.hecha.set()
            self._despertar.set()

    def _cliente(self):
        import httpx

        from ..config import USER_AGENT

        return httpx.Client(
            timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"},
            transport=self.transporte,
        )

    def _descargar(self) -> tuple[str, str]:
        import httpx

        # La carga local va antes: sin ella no se sabe de que dia es lo que ya hay.
        self.precios.cargado.wait(30)
        plataforma = self.precios._plataforma or _plataforma_configurada()
        if plataforma != "pc":
            return "otra_plataforma", plataforma
        hoy = self.reloj().astimezone(timezone.utc).date()
        try:
            with self._cliente() as cliente:
                r = cliente.get(self.base + NOMBRE_VERSION)
                if r.status_code == 404:
                    return "aun_no_hay", "la release aun no tiene precios"
                r.raise_for_status()
                version = r.json()
                if not isinstance(version, dict):
                    return "error", "version con otra forma"
                if version.get("formato") != FORMATO:
                    return "error", f"formato {version.get('formato')!r}: hace falta un Farmadex mas nuevo"
                remota = _fecha(version.get("fecha"))
                if remota is None:
                    return "error", "version sin fecha"
                local = self.precios.fecha
                if local is not None and remota <= local:
                    return ("al_dia" if local.date() == hoy else "aun_no_hay"), ""
                esperado = str(version.get("sha256") or "").lower()
                datos = self._bajar(cliente, self.base + NOMBRE)
        except httpx.HTTPError as e:
            return "sin_red", type(e).__name__
        except ValueError as e:
            return "error", str(e)
        if esperado and hashlib.sha256(datos).hexdigest() != esperado:
            # Lo normal: el workflow estaba subiendo el fichero justo ahora. Se reintenta luego.
            return "aun_no_hay", "la huella no cuadra (a medio publicar)"
        try:
            doc = json.loads(gzip.decompress(datos))
        except Exception as e:  # noqa: BLE001
            return "error", f"fichero ilegible: {e}"
        motivo = validar_documento(doc)
        if motivo:
            return "error", motivo
        self._guardar(datos, version)
        self.descargas += 1
        self.precios.instalar(doc)
        fecha = _fecha(doc.get("fecha"))
        return ("nuevo" if fecha and fecha.date() == hoy else "aun_no_hay"), ""

    def _bajar(self, cliente, url: str) -> bytes:
        trozos = []
        total = 0
        with cliente.stream("GET", url) as r:
            r.raise_for_status()
            for trozo in r.iter_bytes():
                total += len(trozo)
                if total > TAMANO_MAXIMO:
                    raise ValueError("fichero de precios demasiado grande")
                trozos.append(trozo)
        return b"".join(trozos)

    def _guardar(self, datos: bytes, version: dict) -> None:
        """Temporal + renombrar: un corte a medias deja el fichero anterior entero."""
        from ..ficheros import reemplazar, temporal_de

        carpeta = self.precios.carpeta
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = self.precios.ruta
        tmp = temporal_de(destino)
        tmp.write_bytes(datos)
        reemplazar(tmp, destino)
        destino_v = self.precios.ruta_version
        tmp_v = temporal_de(destino_v)
        tmp_v.write_text(json.dumps(version), encoding="utf-8")
        reemplazar(tmp_v, destino_v)

    # -- programacion -------------------------------------------------------------------

    def siguiente(self, ahora: datetime, primera: bool = False) -> datetime:
        """Cuando toca mirar otra vez, segun lo que hay y lo que paso la ultima vez."""
        ahora = ahora.astimezone(timezone.utc)
        medianoche_hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        margen = timedelta(minutes=self.azar.uniform(*MARGEN_MIN))
        fecha = self.precios.fecha
        de_hoy = fecha is not None and fecha.astimezone(timezone.utc).date() == ahora.date()
        if de_hoy:
            return medianoche_hoy + timedelta(days=1) + margen
        resultado = self.ultima.resultado if self.ultima else ""
        if primera or not resultado:
            # Nada antes de 00:00 + margen: la foto de hoy no puede existir aun.
            return max(ahora + timedelta(seconds=3), medianoche_hoy + margen)
        if resultado in ("sin_red", "error"):
            minutos = min(REINTENTO_FALLO_MAX, REINTENTO_FALLO_MIN * 2 ** max(0, self.fallos_seguidos - 1))
            return ahora + timedelta(minutes=minutos * self.azar.uniform(1.0, 1.3))
        if resultado == "otra_plataforma":
            return medianoche_hoy + timedelta(days=1) + margen
        return ahora + timedelta(minutes=self.azar.uniform(*REINTENTO_SIN_FOTO))

    def arrancar(self) -> None:
        """Programador en su hilo: baja al abrir si hace falta y cada dia tras las 00:00 UTC."""
        with self._cerrojo:
            if self._hilo is not None:
                return
            self._parar.clear()
            self._hilo = threading.Thread(target=self._bucle, name="precios-programador", daemon=True)
            self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        self._despertar.set()

    def _bucle(self) -> None:
        self.precios.cargar_en_segundo_plano()
        self.precios.cargado.wait(30)
        self.proximo_intento = self.siguiente(self.reloj(), primera=True)
        while not self._parar.is_set():
            restante = (self.proximo_intento - self.reloj()).total_seconds()
            if restante > 0:
                self._despertar.clear()
                if self._despertar.wait(min(PASO_RELOJ_S, restante)) and not self._parar.is_set():
                    # Ha terminado una descarga (p. ej. la del boton): cambia lo que toca despues.
                    self.proximo_intento = self.siguiente(self.reloj())
                continue
            if self._parar.is_set():
                break
            tarea = self.actualizar(manual=False)
            tarea.esperar()
            self.proximo_intento = self.siguiente(self.reloj())
            log.info("Precios: %s %s; proximo intento %s", tarea.resultado, tarea.detalle,
                     self.proximo_intento.isoformat(timespec="minutes"))


# -- instancia compartida ------------------------------------------------------------------

_instancia: PreciosDiarios | None = None
_cerrojo = threading.Lock()


def precios() -> PreciosDiarios:
    """La foto de precios comun. Nunca bloquea: la carga del fichero va en un hilo."""
    global _instancia
    with _cerrojo:
        if _instancia is None:
            _instancia = PreciosDiarios()
        instancia = _instancia
    instancia.cargar_en_segundo_plano()
    return instancia


def iniciar() -> None:
    """Al abrir Farmadex: carga la foto local y programa las descargas (todo en hilos)."""
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("FARMADEX_SIN_PRECIOS_DIARIOS"):
        return  # las pruebas no tocan GitHub; las que prueban esto montan su Descargador
    p = precios()
    p._asegurar_descargador().arrancar()


def detener() -> None:
    instancia = _instancia
    if instancia is not None and instancia.descargador is not None:
        instancia.descargador.detener()


def _reiniciar_para_pruebas(instancia: PreciosDiarios | None = None) -> None:
    global _instancia
    with _cerrojo:
        _instancia = instancia
