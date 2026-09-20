"""Atajos de teclado globales en Windows (RegisterHotKey).

Se registran en un hilo propio con su propio bucle de mensajes, porque
RegisterHotKey entrega WM_HOTKEY al hilo que registro el atajo. Windows se
queda la combinacion entera, asi que no llega al juego.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QThread, Signal

from .registro_log import obtener

log = obtener("hotkeys")

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MODIFICADORES = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "mayus": MOD_SHIFT,
    "win": MOD_WIN,
}

# Teclas con codigo virtual propio; las letras y numeros se sacan de su ASCII.
TECLAS = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "space": 0x20, "espacio": 0x20, "intro": 0x0D, "enter": 0x0D, "tab": 0x09,
    "esc": 0x1B, "escape": 0x1B, "insert": 0x2D, "supr": 0x2E, "delete": 0x2E,
    "inicio": 0x24, "home": 0x24, "fin": 0x23, "end": 0x23,
    "arriba": 0x26, "abajo": 0x28, "izquierda": 0x25, "derecha": 0x27,
}


def parsear(combinacion: str) -> tuple[int, int]:
    """'Ctrl+Alt+W' -> (modificadores, codigo de tecla). Lanza ValueError si no vale."""
    if not combinacion or not combinacion.strip():
        raise ValueError("combinacion vacia")
    partes = [p.strip().lower() for p in combinacion.split("+") if p.strip()]
    if not partes:
        raise ValueError("combinacion vacia")

    modificadores = 0
    tecla = None
    for parte in partes:
        if parte in MODIFICADORES:
            modificadores |= MODIFICADORES[parte]
        elif tecla is None:
            tecla = parte
        else:
            raise ValueError(f"dos teclas en la misma combinacion: {combinacion}")

    if tecla is None:
        raise ValueError(f"falta la tecla en {combinacion}")
    if tecla in TECLAS:
        codigo = TECLAS[tecla]
    elif len(tecla) == 1 and (tecla.isalnum()):
        codigo = ord(tecla.upper())
    else:
        raise ValueError(f"tecla desconocida: {tecla}")
    if not modificadores:
        raise ValueError("hace falta al menos un modificador (Ctrl, Alt, Shift o Win)")
    return modificadores | MOD_NOREPEAT, codigo


class GestorHotkeys(QThread):
    """Registra las combinaciones y emite su nombre cuando se pulsan."""

    pulsada = Signal(str)
    fallo = Signal(str, str)  # nombre, motivo

    def __init__(self, combinaciones: dict[str, str], parent=None):
        super().__init__(parent)
        self.combinaciones = dict(combinaciones)
        self._ids: dict[int, str] = {}
        self._id_hilo: int | None = None

    def run(self) -> None:  # noqa: D102
        if not sys.platform.startswith("win"):
            log.warning("Los atajos globales solo estan implementados en Windows")
            return
        user32 = ctypes.windll.user32
        self._id_hilo = ctypes.windll.kernel32.GetCurrentThreadId()

        siguiente = 1
        for nombre, combinacion in self.combinaciones.items():
            try:
                modificadores, tecla = parsear(combinacion)
            except ValueError as e:
                self.fallo.emit(nombre, str(e))
                continue
            if user32.RegisterHotKey(None, siguiente, modificadores, tecla):
                self._ids[siguiente] = nombre
                log.info("Atajo registrado: %s = %s", nombre, combinacion)
                siguiente += 1
            else:
                self.fallo.emit(nombre, f"la combinacion {combinacion} ya la usa otro programa")
                log.warning("No se pudo registrar %s (%s)", nombre, combinacion)

        mensaje = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(mensaje), None, 0, 0) > 0:
            if mensaje.message == WM_HOTKEY:
                nombre = self._ids.get(mensaje.wParam)
                if nombre:
                    self.pulsada.emit(nombre)

        for identificador in self._ids:
            user32.UnregisterHotKey(None, identificador)
        self._ids.clear()

    def parar(self) -> None:
        if not self.isRunning():
            return
        if self._id_hilo and sys.platform.startswith("win"):
            ctypes.windll.user32.PostThreadMessageW(self._id_hilo, WM_QUIT, 0, 0)
        if not self.wait(2000):
            log.warning("El hilo de atajos no termino a tiempo")
