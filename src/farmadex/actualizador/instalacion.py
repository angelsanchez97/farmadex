"""Instalacion silenciosa de una version ya descargada y comprobada.

Solo tiene sentido cuando Farmadex se ejecuta desde una instalacion hecha con el
instalador (clave de desinstalacion de Inno Setup en HKCU y ejecutable dentro de
esa carpeta). El zip portable no tiene instalador que lo sustituya: ahi se deja
el aviso con el enlace de siempre.

Como el instalador tiene que sustituir el propio Farmadex.exe, la secuencia es:
se lanza el setup, Farmadex se cierra, el setup espera a que suelte el mutex
(`PrepareToInstall` en instalador.iss), copia los ficheros y vuelve a abrir
Farmadex con la entrada [Run] que solo se ejecuta en actualizaciones
automaticas. Antes de lanzarlo se apunta que version se esta instalando; al
arrancar la siguiente vez, si la version que corre no es esa, es que fallo, y
se dice en el banner en vez de volver a intentarlo en bucle.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .. import VERSION
from ..config import DIR_LOGS
from ..registro_log import obtener
from .app import es_mas_nueva
from .descarga import DIR_DESCARGAS

log = obtener("actualizador.instalacion")

# El AppId de instalador.iss, tal y como Inno Setup nombra su clave de desinstalacion.
APP_ID = "{9E2B7C41-5B1A-4F0E-9E1E-FARMADEX0001}"
CLAVE_DESINSTALACION = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
# Nombre del mutex por el que el instalador sabe que Farmadex sigue abierto.
MUTEX = "FarmadexEnEjecucion"
# Parametro propio con el que el instalador distingue una actualizacion automatica
# de una instalacion a mano (relanza Farmadex al acabar, sin asistente).
PARAMETRO_AUTO = "/AUTOACTUALIZAR=1"
PARAMETROS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", PARAMETRO_AUTO]
RUTA_PENDIENTE = DIR_DESCARGAS / "pendiente.json"
RUTA_FALLIDA = DIR_DESCARGAS / "fallida.json"

_mutex = None


def carpeta_instalada(leer_registro=None) -> Path | None:
    """La carpeta donde el instalador dejo Farmadex, segun HKCU; None si no esta."""
    if leer_registro is None:
        leer_registro = _leer_install_location
    try:
        ruta = leer_registro()
    except Exception:  # noqa: BLE001 - sin registro (Linux, permisos) es "no instalado"
        return None
    return Path(ruta) if ruta else None


def _leer_install_location() -> str | None:
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_DESINSTALACION) as clave:
            valor, _ = winreg.QueryValueEx(clave, "InstallLocation")
    except OSError:
        return None
    return str(valor) if valor else None


def es_instalacion_por_instalador(ejecutable: str | Path | None = None, leer_registro=None) -> bool:
    """True si el .exe que corre esta dentro de la carpeta que registro el instalador.

    Ejecutar desde el codigo (sin congelar) o desde el zip portable da False aunque
    haya otra copia instalada: no se puede sustituir con el setup lo que no instalo el.
    """
    if ejecutable is None:
        if not getattr(sys, "frozen", False):
            return False
        ejecutable = sys.executable
    carpeta = carpeta_instalada(leer_registro)
    if carpeta is None:
        return False
    try:
        exe = Path(ejecutable).resolve()
        carpeta = carpeta.resolve()
    except OSError:
        return False
    return exe.parent == carpeta or carpeta in exe.parents


def senalar_en_ejecucion() -> None:
    """Crea el mutex que el instalador espera a que se libere antes de copiar ficheros."""
    global _mutex
    if os.name != "nt" or _mutex is not None:
        return
    try:
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX)
    except (AttributeError, OSError) as e:  # pragma: no cover - solo fuera de Windows
        log.debug("Sin mutex de ejecucion: %s", e)


def parametros_instalador(ruta_setup: Path | str, ruta_log: Path | None = None) -> list[str]:
    """La linea de ordenes del setup en modo actualizacion automatica."""
    if ruta_log is None:
        ruta_log = DIR_LOGS / "instalador.log"
    return [str(ruta_setup), *PARAMETROS, f"/LOG={ruta_log}"]


def instalar_silencioso(ruta_setup: Path | str, etiqueta: str, ejecutable_actual: str | Path | None = None) -> bool:
    """Lanza el setup en silencio y apunta que version se esta instalando.

    Devuelve True si el proceso arranco: quien llama debe cerrar Farmadex en cuanto
    pueda. Si el setup devuelve error, el envoltorio vuelve a abrir la version
    actual, que al arrancar ve la instalacion pendiente sin cumplir y lo avisa.
    """
    ruta_setup = Path(ruta_setup)
    if not ruta_setup.exists():
        log.warning("El instalador ya no esta: %s", ruta_setup)
        return False
    if ejecutable_actual is None:
        ejecutable_actual = sys.executable
    try:
        DIR_LOGS.mkdir(parents=True, exist_ok=True)
        _escribir(RUTA_PENDIENTE, {"version": etiqueta, "setup": str(ruta_setup), "momento": time.time()})
        orden = _linea_de_ordenes(ruta_setup, Path(ejecutable_actual))
        banderas = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(orden, close_fds=True, creationflags=banderas)  # noqa: S603 - ruta verificada por SHA-256
    except OSError as e:
        log.error("No se pudo lanzar el instalador: %s", e)
        RUTA_PENDIENTE.unlink(missing_ok=True)
        return False
    log.info("Instalador lanzado en silencio: %s", ruta_setup)
    return True


def _linea_de_ordenes(ruta_setup: Path, ejecutable_actual: Path) -> str:
    """cmd ejecuta el setup y, solo si devuelve error, vuelve a abrir el Farmadex actual.

    Va como cadena, no como lista: cmd necesita sus propias comillas y `||`.
    """
    setup = subprocess.list2cmdline(parametros_instalador(ruta_setup))
    exe = subprocess.list2cmdline([str(ejecutable_actual)])
    return f'cmd.exe /d /c "{setup} || start "" {exe}"'


def resultado_instalacion_anterior() -> tuple[str, str] | None:
    """Al arrancar: que paso con la ultima instalacion automatica, si la hubo.

    Devuelve ("instalada", version) si esta es ya esa version, ("fallida", version)
    si Farmadex sigue en una anterior, o None si no habia nada pendiente. Borra
    el apunte y el instalador usado, y deja anotada la version fallida para no
    intentar instalarla otra vez sola.
    """
    pendiente = _leer(RUTA_PENDIENTE)
    if not pendiente:
        return None
    RUTA_PENDIENTE.unlink(missing_ok=True)
    etiqueta = str(pendiente.get("version") or "")
    setup = pendiente.get("setup")
    if setup:
        try:
            Path(setup).unlink(missing_ok=True)
        except OSError:
            pass
    if etiqueta and not es_mas_nueva(etiqueta, VERSION):
        RUTA_FALLIDA.unlink(missing_ok=True)
        log.info("Actualizacion a %s completada", etiqueta)
        return ("instalada", etiqueta)
    log.warning("La actualizacion a %s no llego a instalarse; Farmadex sigue en %s", etiqueta, VERSION)
    _escribir(RUTA_FALLIDA, {"version": etiqueta, "momento": time.time()})
    return ("fallida", etiqueta)


def version_fallida() -> str | None:
    """La version cuya instalacion automatica fallo la ultima vez, si hubo."""
    datos = _leer(RUTA_FALLIDA) or {}
    return str(datos.get("version") or "") or None


def _leer(ruta: Path) -> dict | None:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def _escribir(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos), encoding="utf-8")
    tmp.replace(ruta)

