"""Descarga del instalador de una version nueva, en segundo plano y comprobada.

Solo se aceptan ficheros del repositorio del proyecto, por HTTPS, y solo se dan
por buenos si su SHA-256 coincide con la huella ("sha256:...") que la API de
GitHub publica para cada adjunto. Sin huella, o con una huella que no cuadra,
el fichero se borra y no se instala nada.

La descarga va a una carpeta propia dentro de los datos del usuario, con el
sufijo ".parcial" mientras dura; si se corta, el siguiente intento la reanuda
con una peticion Range desde donde se quedo.
"""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PySide6.QtCore import QObject, Signal

from ..config import DIR_BASE, USER_AGENT
from ..registro_log import obtener
from .app import PROPIETARIO, REPOSITORIO, Version

log = obtener("actualizador.descarga")

# Carpeta aparte de la de compilaciones locales: aquella la mira ComprobadorLocal
# y ofreceria "instalar desde Ajustes" lo que aqui aun no se ha comprobado.
DIR_DESCARGAS = DIR_BASE / "descargas"
SUFIJO_PARCIAL = ".parcial"
RE_DIGEST = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
INTENTOS = 3
# Segundos entre reintentos (se duplican en cada uno).
ESPERA_REINTENTO = 1.0
TROZO = 256 * 1024
# Un instalador de Farmadex ronda los 150 MB; mas de 1 GB es que algo no cuadra.
TAMANO_MAXIMO = 1024 * 1024 * 1024


class ErrorDescarga(RuntimeError):
    """Motivo legible para el banner: sin red, huella mal, disco lleno..."""


def url_permitida(url: str) -> bool:
    """Solo HTTPS y solo adjuntos de releases del repositorio del proyecto."""
    try:
        partes = urlparse(url)
    except ValueError:
        return False
    if partes.scheme != "https" or partes.netloc.lower() != "github.com":
        return False
    prefijo = f"/{PROPIETARIO}/{REPOSITORIO}/releases/download/".lower()
    return partes.path.lower().startswith(prefijo) and partes.path.lower().endswith(".exe")


def huella_esperada(version: Version) -> str | None:
    """El SHA-256 en hexadecimal minusculas, o None si la release no lo trae bien."""
    m = RE_DIGEST.match((version.digest or "").strip())
    return m.group(1).lower() if m else None


def sha256_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1024 * 1024), b""):
            h.update(trozo)
    return h.hexdigest()


def nombre_fichero(version: Version) -> str:
    nombre = Path(version.nombre or "").name or f"Farmadex-{version.etiqueta.lstrip('v')}-setup.exe"
    # Nada de rutas ni caracteres raros venidos del nombre del adjunto.
    return re.sub(r"[^A-Za-z0-9._-]", "_", nombre)


def descargar(
    version: Version,
    carpeta: Path | str = DIR_DESCARGAS,
    progreso=None,
    cancelado: threading.Event | None = None,
    transporte: httpx.BaseTransport | None = None,
    intentos: int = INTENTOS,
) -> Path:
    """Baja el instalador de `version` a `carpeta` y devuelve su ruta ya verificada.

    `progreso(recibidos, total)` se llama a medida que llegan datos. Lanza
    `ErrorDescarga` con un motivo corto si algo no cuadra; nunca deja un fichero
    a medias con el nombre definitivo.
    """
    huella = huella_esperada(version)
    if not huella:
        raise ErrorDescarga("la release no trae la huella SHA-256 del instalador")
    if not url_permitida(version.url):
        raise ErrorDescarga("el instalador no viene del repositorio de Farmadex")

    if cancelado is None:
        cancelado = threading.Event()
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / nombre_fichero(version)
    parcial = destino.with_name(destino.name + SUFIJO_PARCIAL)

    # Ya bajado y comprobado (por ejemplo, en la sesion anterior): no se repite.
    if destino.exists() and sha256_de(destino) == huella:
        if progreso:
            progreso(destino.stat().st_size, destino.stat().st_size)
        return destino
    if destino.exists():
        destino.unlink()

    cliente = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=10.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"},
        follow_redirects=True,
        transport=transporte,
    )
    try:
        while True:
            # Un trozo de otra sesion que no cuadra con la huella (el adjunto se volvio
            # a subir mientras tanto) se tira y se baja entero una vez; si lo bajado de
            # cero tampoco cuadra, ya no es cosa nuestra.
            reanudada = parcial.exists() and parcial.stat().st_size > 0
            _con_reintentos(cliente, version.url, parcial, progreso, cancelado, intentos)
            if sha256_de(parcial) == huella:
                break
            parcial.unlink(missing_ok=True)
            if not reanudada:
                raise ErrorDescarga("la huella SHA-256 del instalador no coincide con la publicada")
            log.info("El trozo reanudado no cuadra con la huella publicada: se vuelve a bajar entero")
    finally:
        cliente.close()

    parcial.replace(destino)
    log.info("Instalador %s descargado y comprobado: %s", version.etiqueta, destino)
    return destino


def _con_reintentos(cliente: httpx.Client, url: str, parcial: Path, progreso, cancelado, intentos: int) -> None:
    """Hasta `intentos` pasadas de `_bajar`, esperando entre ellas; lanza ErrorDescarga si ninguna acaba."""
    ultimo = "sin intentos"
    for intento in range(max(1, intentos)):
        if cancelado.is_set():
            raise ErrorDescarga("cancelada")
        try:
            _bajar(cliente, url, parcial, progreso, cancelado)
            return
        except httpx.HTTPStatusError as e:
            ultimo = f"HTTP {e.response.status_code}"
            if e.response.status_code == 416:
                # El trozo guardado ya no encaja con el servidor: se empieza de cero.
                parcial.unlink(missing_ok=True)
            elif e.response.status_code < 500 and e.response.status_code not in (408, 429):
                break
        except httpx.TimeoutException:
            ultimo = "el servidor no responde (tiempo agotado)"
        except httpx.HTTPError as e:
            ultimo = "no hay conexion con el servidor" if isinstance(e, httpx.ConnectError) else (str(e) or type(e).__name__)
        except OSError as e:
            # Disco lleno, carpeta sin permisos...: insistir no lo arregla.
            raise ErrorDescarga(f"no se pudo escribir en disco ({e.strerror or e})") from e
        log.info("Intento %d de descarga fallido: %s", intento + 1, ultimo)
        if intento < intentos - 1 and cancelado.wait(ESPERA_REINTENTO * 2**intento):
            raise ErrorDescarga("cancelada")
    raise ErrorDescarga(ultimo)


def _bajar(cliente: httpx.Client, url: str, parcial: Path, progreso, cancelado) -> None:
    """Una pasada de descarga, reanudando desde lo que haya en `parcial`."""
    ya = parcial.stat().st_size if parcial.exists() else 0
    cabeceras = {"Range": f"bytes={ya}-"} if ya else {}
    with cliente.stream("GET", url, headers=cabeceras) as r:
        if r.status_code == 200 and ya:
            # El servidor no reanuda: se empieza de cero.
            ya = 0
        elif r.status_code == 206 and not ya:
            ya = 0
        r.raise_for_status()
        total = _total(r, ya)
        if total and total > TAMANO_MAXIMO:
            raise ErrorDescarga("el instalador es demasiado grande para ser de Farmadex")
        modo = "ab" if ya else "wb"
        with open(parcial, modo) as f:
            recibidos = ya
            for trozo in r.iter_bytes(TROZO):
                if cancelado is not None and cancelado.is_set():
                    raise ErrorDescarga("cancelada")
                f.write(trozo)
                recibidos += len(trozo)
                if recibidos > TAMANO_MAXIMO:
                    raise ErrorDescarga("el instalador es demasiado grande para ser de Farmadex")
                if progreso:
                    progreso(recibidos, total)
    if total and parcial.stat().st_size < total:
        raise httpx.ReadError("la descarga se corto antes de terminar")


def _total(r: httpx.Response, ya: int) -> int:
    rango = r.headers.get("Content-Range", "")
    if r.status_code == 206 and "/" in rango:
        try:
            return int(rango.rsplit("/", 1)[1])
        except ValueError:
            return 0
    try:
        return int(r.headers.get("Content-Length") or 0) + (0 if r.status_code == 200 else ya)
    except ValueError:
        return 0


def limpiar(carpeta: Path | str = DIR_DESCARGAS, conservar: Path | None = None) -> None:
    """Borra instaladores viejos y trozos a medias; `conservar` se deja."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return
    for fichero in carpeta.iterdir():
        if conservar and fichero == conservar:
            continue
        if fichero.suffix.lower() in (".exe", SUFIJO_PARCIAL) or fichero.name.endswith(".exe" + SUFIJO_PARCIAL):
            try:
                fichero.unlink()
            except OSError:
                pass


class DescargadorApp(QObject):
    """Descarga en un hilo y avisa por senales. Una descarga a la vez."""

    progreso = Signal(int)  # porcentaje 0-100 (-1 si no se sabe el total)
    lista = Signal(object, object)  # Version, Path
    fallo = Signal(object, str)  # Version, motivo

    def __init__(self, carpeta: Path | str = DIR_DESCARGAS, transporte=None, parent=None):
        super().__init__(parent)
        self.carpeta = Path(carpeta)
        self.transporte = transporte
        self._hilo: threading.Thread | None = None
        self._cancelar = threading.Event()
        self._ultimo_pct = -2

    @property
    def ocupado(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def descargar(self, version: Version) -> bool:
        if self.ocupado:
            return False
        self._cancelar.clear()
        self._ultimo_pct = -2
        self._hilo = threading.Thread(
            target=self._trabajo, args=(version,), name="descarga-actualizacion", daemon=True
        )
        self._hilo.start()
        return True

    def cancelar(self) -> None:
        self._cancelar.set()

    def _trabajo(self, version: Version) -> None:
        def avanzar(recibidos: int, total: int) -> None:
            pct = int(recibidos * 100 / total) if total else -1
            if pct != self._ultimo_pct:
                self._ultimo_pct = pct
                self.progreso.emit(pct)

        try:
            ruta = descargar(
                version, self.carpeta, progreso=avanzar, cancelado=self._cancelar,
                transporte=self.transporte,
            )
        except ErrorDescarga as e:
            log.warning("No se pudo descargar la version %s: %s", version.etiqueta, e)
            self.fallo.emit(version, str(e))
            return
        except Exception as e:  # noqa: BLE001 - nada de esto puede tumbar la interfaz
            log.warning("Fallo inesperado descargando la version %s: %s", version.etiqueta, e)
            self.fallo.emit(version, str(e) or type(e).__name__)
            return
        limpiar(self.carpeta, conservar=ruta)
        self.lista.emit(version, ruta)
