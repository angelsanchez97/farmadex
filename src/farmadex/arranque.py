"""Arranque con Windows: alta y baja en HKCU\\...\\Run, sin administrador.

Solo tiene sentido en la version instalada con el instalador: el valor del
registro apunta al .exe instalado con `--bandeja`, que arranca Farmadex escondido
en la bandeja sin abrir la ventana. En la portable el .exe puede moverse o
borrarse, asi que se registra igual (apuntando a donde este ahora) pero la
interfaz avisa; desde el codigo sin congelar no se registra nada.

La escritura en el registro esta inyectada (`escribir`, `borrar`, `leer`) para
que las pruebas no toquen el registro real.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

from . import NOMBRE_APP
from .registro_log import obtener

log = obtener("arranque")

CLAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOMBRE_VALOR = NOMBRE_APP
ARGUMENTO_BANDEJA = "--bandeja"


def comando_arranque(ejecutable: str | Path | None = None) -> str | None:
    """Lo que se apunta en el registro; None si no hay .exe (ejecucion desde el codigo)."""
    if ejecutable is None:
        if not getattr(sys, "frozen", False):
            return None
        ejecutable = sys.executable
    return f'"{Path(ejecutable)}" {ARGUMENTO_BANDEJA}'


def es_portable(ejecutable: str | Path | None = None, leer_registro=None) -> bool:
    """True si corre desde un .exe que no puso el instalador (zip portable)."""
    from .actualizador.instalacion import es_instalacion_por_instalador

    if ejecutable is None and not getattr(sys, "frozen", False):
        return False
    return not es_instalacion_por_instalador(ejecutable, leer_registro)


# -- registro de Windows, inyectable -------------------------------------------


def _escribir_run(nombre: str, comando: str) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_RUN, 0, winreg.KEY_SET_VALUE) as clave:
        winreg.SetValueEx(clave, nombre, 0, winreg.REG_SZ, comando)


def _borrar_run(nombre: str) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_RUN, 0, winreg.KEY_SET_VALUE) as clave:
        try:
            winreg.DeleteValue(clave, nombre)
        except FileNotFoundError:
            pass


def _leer_run(nombre: str) -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_RUN) as clave:
            valor, _ = winreg.QueryValueEx(clave, nombre)
    except OSError:
        return None
    return str(valor) if valor else None


def activar(
    comando: str | None = None,
    escribir: Callable[[str, str], None] | None = None,
) -> bool:
    """Registra el arranque; False si no hay comando (desde el codigo) o falla."""
    comando = comando or comando_arranque()
    if not comando:
        log.warning("No se registra el arranque con Windows: no hay ejecutable (codigo sin congelar)")
        return False
    if os.name != "nt" and escribir is None:
        return False
    try:
        (escribir or _escribir_run)(NOMBRE_VALOR, comando)
    except OSError as e:
        log.warning("No se pudo registrar el arranque con Windows: %s", e)
        return False
    log.info("Arranque con Windows registrado: %s", comando)
    return True


def desactivar(borrar: Callable[[str], None] | None = None) -> bool:
    if os.name != "nt" and borrar is None:
        return False
    try:
        (borrar or _borrar_run)(NOMBRE_VALOR)
    except OSError as e:
        log.warning("No se pudo quitar el arranque con Windows: %s", e)
        return False
    log.info("Arranque con Windows quitado")
    return True


def esta_activo(leer: Callable[[str], str | None] | None = None) -> bool:
    if os.name != "nt" and leer is None:
        return False
    try:
        return bool((leer or _leer_run)(NOMBRE_VALOR))
    except OSError:
        return False


def sincronizar(activo: bool, comando: str | None = None, escribir=None, borrar=None, leer=None) -> bool:
    """Deja el registro como dice el ajuste. Devuelve si el registro quedo como se pidio."""
    if activo:
        return activar(comando, escribir)
    if esta_activo(leer):
        return desactivar(borrar)
    return True


def arrancado_en_bandeja(argv: list[str]) -> bool:
    return ARGUMENTO_BANDEJA in argv
