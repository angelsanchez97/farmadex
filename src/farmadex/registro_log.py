"""Registro a fichero rotativo que no se queda mudo, y captura de excepciones.

En el ejecutable sin consola `sys.stderr` es None, y `logging.Handler.handleError`
solo imprime el fallo si hay stderr: cualquier excepcion al escribir una linea
se tragaba y el registro moria sin dejar rastro. Aqui cada fallo de un handler
se apunta en `logs/registro_errores.txt` con su traza, y el fichero se reabre
en la siguiente linea en vez de darse por perdido.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import re
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import NOMBRE_APP, VERSION
from .config import DIR_LOGS, crear_carpetas

RUTA_LOG = DIR_LOGS / f"{NOMBRE_APP.lower()}.log"
RUTA_ERRORES_REGISTRO = DIR_LOGS / "registro_errores.txt"
MAX_FALLOS_APUNTADOS = 50  # trazas que se guardan; despues solo se cuenta

_configurado = False
_cerrojo = threading.Lock()
_fallos = 0
_ultimo_fallo: str | None = None


def apuntar_fallo_registro(origen: str, detalle: str, ruta: Path | None = None) -> None:
    """Deja constancia de un fallo del propio registro donde se pueda leer.

    Va a `registro_errores.txt` (y a stderr si existe). Nunca lanza: es el ultimo
    recurso y no puede tumbar a quien intentaba escribir una linea normal.
    """
    global _fallos, _ultimo_fallo
    # El resumen es la ultima linea de la traza (la excepcion), no la linea perdida.
    lineas = [l for l in detalle.strip().splitlines() if l.strip() and not l.startswith("Linea perdida")]
    with _cerrojo:
        _fallos += 1
        _ultimo_fallo = f"{origen}: {lineas[-1].strip() if lineas else '?'}"
        numero = _fallos
    texto = (
        f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} fallo {numero} del registro en {origen} "
        f"({NOMBRE_APP} {VERSION}, pid {os.getpid()}, hilo {threading.current_thread().name})\n{detalle.rstrip()}\n"
    )
    if sys.stderr:
        try:
            sys.stderr.write(texto)
        except Exception:  # noqa: BLE001 - stderr puede estar roto; no hay mas que hacer
            pass
    if numero > MAX_FALLOS_APUNTADOS:
        return
    ruta = ruta or RUTA_ERRORES_REGISTRO
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(texto)
    except Exception:  # noqa: BLE001 - si ni esto se puede escribir, se cuenta y ya
        pass


def fallos_del_registro() -> tuple[int, str | None]:
    """Cuantas lineas ha perdido el registro en esta ejecucion y el ultimo motivo."""
    return _fallos, _ultimo_fallo


def ruta_real(ruta: Path) -> Path | None:
    """Donde esta de verdad el fichero, preguntandoselo a Windows por su handle.

    Dentro de un contenedor con AppData virtualizado (todo lo que lanza la app de
    escritorio de Claude, por ejemplo) `%LOCALAPPDATA%\\Farmadex\\logs\\farmadex.log`
    se sirve desde `Packages\\<paquete>\\LocalCache\\Local\\...`: la ruta es la misma,
    el fichero no, y lo que escribe el Farmadex que abre el usuario desde el menu
    Inicio no se ve desde dentro. `GetFinalPathNameByHandle` devuelve la ruta
    redirigida; fuera de Windows, o si falla, None.
    """
    if os.name != "nt":
        return None
    try:
        import msvcrt

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        with open(ruta, "rb") as f:
            handle = ctypes.c_void_p(msvcrt.get_osfhandle(f.fileno()))
            buf = ctypes.create_unicode_buffer(32768)
            n = k32.GetFinalPathNameByHandleW(handle, buf, len(buf), 0)
        if not n or n >= len(buf):
            return None
        texto = buf.value[:n]
        return Path(texto[4:] if texto.startswith("\\\\?\\") else texto)
    except (AttributeError, OSError, ValueError):
        return None


RE_LOCALCACHE = re.compile(r"\\packages\\[^\\]+\\localcache\\", re.IGNORECASE)


def registro_redirigido() -> Path | None:
    """La ruta real del registro si un contenedor la ha desviado a su LocalCache.

    Se compara con la ruta tal cual se configuro (sin resolver: `Path.resolve`
    tambien pregunta por el handle y devolveria la desviada). Un enlace o union
    del usuario no cuenta: solo se avisa cuando lo real cae en Packages\\...\\LocalCache
    y lo configurado no.
    """
    real = ruta_real(RUTA_LOG)
    if real is None:
        return None
    esperada = os.path.abspath(str(RUTA_LOG))
    if os.path.normcase(str(real)) == os.path.normcase(esperada):
        return None
    if RE_LOCALCACHE.search(str(real)) and not RE_LOCALCACHE.search(esperada):
        return real
    return None


class FicheroRotativoSeguro(RotatingFileHandler):
    """RotatingFileHandler que apunta sus fallos y reabre el fichero tras cada uno."""

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - nombre de logging
        try:
            mensaje = record.getMessage()
        except Exception:  # noqa: BLE001 - el propio mensaje puede ser lo que falla
            mensaje = repr(record.msg)
        detalle = traceback.format_exc() + f"Linea perdida: {record.name} {record.levelname}: {mensaje}"
        apuntar_fallo_registro(f"fichero {self.baseFilename}", detalle)
        # El stream puede haber quedado inservible (fichero borrado, handle roto):
        # se cierra y el siguiente emit lo vuelve a abrir.
        try:
            if self.stream:
                self.stream.close()
        except Exception:  # noqa: BLE001
            pass
        self.stream = None


class ConsolaSegura(logging.StreamHandler):
    """StreamHandler que no revienta si stderr desaparece a mitad de ejecucion."""

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - nombre de logging
        apuntar_fallo_registro("consola", traceback.format_exc())


def configurar(nivel: int = logging.INFO) -> logging.Logger:
    global _configurado
    raiz = logging.getLogger(NOMBRE_APP.lower())
    if _configurado:
        return raiz
    crear_carpetas()
    raiz.setLevel(nivel)
    formato = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    try:
        fichero = FicheroRotativoSeguro(RUTA_LOG, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    except OSError:
        # Sin fichero de registro (carpeta de solo lectura, disco lleno) se sigue
        # arrancando: se apunta el motivo y quedan la consola y el fichero de errores.
        apuntar_fallo_registro(f"abrir {RUTA_LOG}", traceback.format_exc())
        fichero = None
    if fichero is not None:
        fichero.setFormatter(formato)
        raiz.addHandler(fichero)

    if sys.stderr is not None:  # en el .exe sin consola no hay stderr
        consola = ConsolaSegura(sys.stderr)
        consola.setFormatter(formato)
        raiz.addHandler(consola)

    _configurado = True
    raiz.info(
        "%s %s | registro en %s | %s | Python %s | pid %d",
        NOMBRE_APP,
        VERSION,
        RUTA_LOG if fichero is not None else "NINGUN FICHERO (ver registro_errores.txt)",
        "ejecutable congelado" if getattr(sys, "frozen", False) else "codigo sin congelar",
        platform.python_version(),
        os.getpid(),
    )
    redirigido = registro_redirigido() if fichero is not None else None
    if redirigido is not None:
        raiz.warning(
            "AppData REDIRIGIDO por un contenedor: este fichero es en realidad %s. "
            "NO es el registro del Farmadex que abre el usuario desde el menu Inicio",
            redirigido,
        )
    return raiz


def obtener(nombre: str) -> logging.Logger:
    configurar()
    return logging.getLogger(f"{NOMBRE_APP.lower()}.{nombre}")


def instalar_gancho_excepciones(mostrar_dialogo=None) -> None:
    """Manda cualquier excepcion no capturada al log (y opcionalmente a un dialogo)."""
    log = obtener("excepciones")

    def gancho(tipo, valor, traza):
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, valor, traza)
            return
        log.error("Excepcion no controlada", exc_info=(tipo, valor, traza))
        if mostrar_dialogo is not None:
            try:
                mostrar_dialogo(f"{tipo.__name__}: {valor}")
            except Exception:  # noqa: BLE001 - el dialogo nunca debe tumbar el gancho
                log.exception("Fallo al mostrar el dialogo de error")

    sys.excepthook = gancho
