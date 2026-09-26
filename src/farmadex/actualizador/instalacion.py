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
import re
import subprocess
import sys
import time
from pathlib import Path

from .. import VERSION
from ..config import DIR_LOGS
from ..ficheros import reemplazar, temporal_de
from ..registro_log import obtener
from .app import numeros
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
# /SILENT (no /VERYSILENT): oculta el asistente pero deja ver la ventana de progreso
# del propio instalador, para que el usuario sepa que algo esta pasando mientras
# Farmadex esta cerrado.
PARAMETROS = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", PARAMETRO_AUTO]
RUTA_PENDIENTE = DIR_DESCARGAS / "pendiente.json"
RUTA_FALLIDA = DIR_DESCARGAS / "fallida.json"
ERROR_ALREADY_EXISTS = 183
# Caracteres que cmd interpreta fuera de comillas: espacios, "&", "^", "(", ")", "|"...
RE_NECESITA_COMILLAS = re.compile(r'[\s&^()|<>"]')

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


def otra_instancia_abierta() -> bool:
    """True si otro Farmadex tiene el mutex de ejecucion.

    Un mutex con nombre existe mientras algun proceso tenga un handle, y el nuestro
    cuenta: se suelta el propio, se mira si sigue existiendo y se vuelve a coger.
    Con dos Farmadex abiertos, el setup esperaria a que se cerrase el otro, se
    rendiria y ese abandono se apuntaria como fallo de la version: mejor no lanzarlo.
    """
    global _mutex
    if os.name != "nt":
        return False
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        if _mutex:
            k32.CloseHandle(_mutex)
            _mutex = None
        handle = k32.CreateMutexW(None, False, MUTEX)
        existe = bool(handle) and ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        _mutex = handle or None
        return existe
    except (AttributeError, OSError) as e:  # pragma: no cover - solo fuera de Windows
        log.debug("No se pudo mirar el mutex de ejecucion: %s", e)
        return False


def parametros_instalador(ruta_setup: Path | str, ruta_log: Path | None = None) -> list[str]:
    """La linea de ordenes del setup en modo actualizacion automatica."""
    if ruta_log is None:
        ruta_log = DIR_LOGS / "instalador.log"
    return [str(ruta_setup), *PARAMETROS, f"/LOG={ruta_log}"]


def instalar_silencioso(
    ruta_setup: Path | str,
    etiqueta: str,
    ejecutable_actual: str | Path | None = None,
    borrar_al_acabar: bool = True,
) -> bool:
    """Lanza el setup en silencio y apunta que version se esta instalando.

    Devuelve True si el proceso arranco: quien llama debe cerrar Farmadex en cuanto
    pueda. Si el setup devuelve error, el envoltorio vuelve a abrir la version
    actual, que al arrancar ve la instalacion pendiente sin cumplir y lo avisa.
    `borrar_al_acabar` False deja el setup donde estaba (el de la carpeta de
    compilaciones no es nuestro: solo se borran los que descarga Farmadex).
    """
    ruta_setup = Path(ruta_setup)
    if not ruta_setup.exists():
        log.warning("El instalador ya no esta: %s", ruta_setup)
        return False
    if ejecutable_actual is None:
        ejecutable_actual = sys.executable
    try:
        DIR_LOGS.mkdir(parents=True, exist_ok=True)
        _escribir(RUTA_PENDIENTE, {
            "version": etiqueta, "setup": str(ruta_setup), "momento": time.time(),
            "borrar_setup": bool(borrar_al_acabar),
        })
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

    Va como cadena, no como lista: cmd necesita sus propias comillas y `||`. Se
    entrecomilla cada parte que lleve algo que cmd interprete (espacios, "&", "^",
    parentesis): `list2cmdline` solo mira espacios, y una carpeta de usuario
    "Ana&Luis" partia la orden en dos. Los parametros del setup van sin comillas,
    tal y como se probaron.
    """
    setup = " ".join(_comillas(p) for p in parametros_instalador(ruta_setup))
    exe = _comillas(str(ejecutable_actual))
    cmd = _comillas(os.environ.get("ComSpec") or "cmd.exe")
    return f'{cmd} /d /c "{setup} || start "" {exe}"'


def _comillas(texto: str) -> str:
    return f'"{texto}"' if RE_NECESITA_COMILLAS.search(texto) else texto


# Lo que el setup escribe en instalador.log (Log() en PrepareToInstall, instalador.iss)
# cuando se rinde porque otro Farmadex sigue abierto. Se busca literalmente.
MARCA_OTRA_INSTANCIA = "Farmadex sigue abierto"
MOTIVO_SIN_RASTRO = "el instalador no llego a arrancar (instalador.log no tiene nada de esa hora)"
MOTIVO_DETENIDO = "el instalador se detuvo: {detalle}"
RE_LINEA_INSTALADOR = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+\s+(.*)$")


def diagnostico_instalador(desde: float, ruta_log: Path | None = None) -> tuple[str, str]:
    """Que cuenta instalador.log del setup lanzado en el instante `desde` (epoch).

    Devuelve (clave, detalle): "sin_rastro" si el log no tiene nada de esa hora (el
    setup no llego a arrancar, o arranco sin poder escribirlo), "otra_instancia" si
    se rindio esperando al mutex, o "detenido" con la ultima linea que dejo.
    """
    if ruta_log is None:
        ruta_log = DIR_LOGS / "instalador.log"
    try:
        lineas = ruta_log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ("sin_rastro", "")
    # Un par de segundos de margen: el apunte se escribe justo antes de lanzar el setup.
    limite = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(desde - 2))
    recientes = []
    for linea in lineas:
        m = RE_LINEA_INSTALADOR.match(linea)
        if m and m.group(1) >= limite:
            recientes.append(m.group(2).strip())
    if not recientes:
        return ("sin_rastro", "")
    if any(MARCA_OTRA_INSTANCIA in texto for texto in recientes):
        return ("otra_instancia", "")
    # La ultima linea con sustancia: "Log closed." y "Deinitializing Setup." no cuentan nada.
    con_sustancia = [t for t in recientes if not t.startswith(("Log closed", "Deinitializing"))]
    return ("detenido", (con_sustancia or recientes)[-1][:160])


def resultado_instalacion_anterior() -> tuple[str, str] | None:
    """Al arrancar: que paso con la ultima instalacion automatica, si la hubo.

    Devuelve ("instalada", version) si esta es ya esa version, ("fallida", version)
    si Farmadex sigue en una anterior, ("aplazada", version) si el setup se rindio
    porque habia otro Farmadex abierto, o None si no habia nada pendiente. Borra el
    apunte. Si fallo, borra tambien el instalador y deja anotada la version y el
    motivo (`motivo_fallida`) para no intentarla otra vez sola; si se aplazo, el
    instalador se queda para que lo lance el ultimo Farmadex que se cierre.
    """
    pendiente = _leer(RUTA_PENDIENTE)
    if pendiente is None:
        return None
    RUTA_PENDIENTE.unlink(missing_ok=True)
    etiqueta = str(pendiente.get("version") or "")
    # Un setup que no descargo Farmadex (carpeta de compilaciones) no se borra nunca.
    setup = pendiente.get("setup") if pendiente.get("borrar_setup", True) else None
    pedida, actual = numeros(etiqueta), numeros(VERSION)
    if not pedida or not actual:
        log.warning("Apunte de actualizacion ilegible (%r): se descarta", etiqueta)
        _borrar_setup(setup)
        return None
    if pedida == actual:
        RUTA_FALLIDA.unlink(missing_ok=True)
        log.info("Actualizacion a %s completada", etiqueta)
        _borrar_setup(setup)
        return ("instalada", etiqueta)
    if pedida < actual:
        # Un apunte de otra epoca (se instalo a mano una version mas nueva): ni
        # exito ni fallo, y desde luego no hay que vetar nada.
        log.info("Apunte de actualizacion a %s anterior a la %s que corre: se descarta", etiqueta, VERSION)
        _borrar_setup(setup)
        return None
    try:
        momento = float(pendiente.get("momento") or 0)
    except (TypeError, ValueError):
        momento = 0.0
    clave, detalle = diagnostico_instalador(momento)
    if clave == "otra_instancia":
        # No es un fallo de esa version: habia otro Farmadex abierto y el setup no
        # quiso pisar nada. El instalador se conserva y se vuelve a intentar al
        # cerrar el ultimo; no se gasta el intento ni se veta la version.
        log.warning(
            "La actualizacion a %s se aplazo: el instalador encontro otro Farmadex abierto "
            "(se reintenta al cerrar el ultimo; el instalador sigue en %s)", etiqueta, setup,
        )
        return ("aplazada", etiqueta)
    motivo = MOTIVO_SIN_RASTRO if clave == "sin_rastro" else MOTIVO_DETENIDO.format(detalle=detalle)
    log.warning(
        "La actualizacion a %s no llego a instalarse; Farmadex sigue en %s. Motivo: %s", etiqueta, VERSION, motivo
    )
    _escribir(RUTA_FALLIDA, {"version": etiqueta, "momento": time.time(), "motivo": motivo})
    _borrar_setup(setup)
    return ("fallida", etiqueta)


def _borrar_setup(setup) -> None:
    if not setup:
        return
    try:
        Path(setup).unlink(missing_ok=True)
    except OSError as e:
        log.info("No se pudo borrar el instalador usado %s: %s", setup, e)


def version_fallida() -> str | None:
    """La version cuya instalacion automatica fallo la ultima vez, si hubo."""
    datos = _leer(RUTA_FALLIDA) or {}
    return str(datos.get("version") or "") or None


def motivo_fallida() -> str | None:
    """Por que fallo la ultima instalacion automatica (texto en castellano, pasa por t())."""
    datos = _leer(RUTA_FALLIDA) or {}
    return str(datos.get("motivo") or "") or None


def _leer(ruta: Path) -> dict | None:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def _escribir(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = temporal_de(ruta)
    tmp.write_text(json.dumps(datos), encoding="utf-8")
    reemplazar(tmp, ruta)

