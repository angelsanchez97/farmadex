"""Busquedas en un hilo aparte, para que escribir en el buscador nunca se atasque.

Buscar en el indice entero cuesta decenas de milisegundos (y segundos si rapidfuzz cae a
Python puro). Hecho en el hilo de la ventana, cada pausa al escribir congelaba la caja de
texto. Aqui el trabajo pesado va a un hilo propio con su propia conexion al indice (sqlite
no deja compartirla entre hilos) y a la ventana solo vuelve el resultado de la ULTIMA
peticion: las que se han quedado viejas mientras se seguia escribiendo se tiran sin
ensenarse, y las que aun no habian empezado ni se ejecutan.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..registro_log import obtener

log = obtener(__name__)

_FALLO = object()


def ruta_de(con: sqlite3.Connection | None) -> str:
    """Fichero de la base de datos de `con`; vacio si es en memoria (no se puede reabrir)."""
    if con is None:
        return ""
    try:
        return con.execute("PRAGMA database_list").fetchone()[2] or ""
    except sqlite3.Error:
        return ""


class _Tarea(QRunnable):
    def __init__(self, dueno: BusquedaEnFondo, generacion: int, ruta: str, marca: int,
                 trabajo: Callable[[sqlite3.Connection], Any]):
        super().__init__()
        self.dueno = dueno
        self.generacion = generacion
        self.ruta = ruta
        self.marca = marca
        self.trabajo = trabajo

    def run(self) -> None:  # hilo aparte
        dueno = self.dueno
        if dueno.generacion != self.generacion:
            return  # ya hay otra peticion mas nueva: ni se empieza
        try:
            resultado = self.trabajo(dueno._conexion_del_hilo(self.ruta, self.marca))
        except Exception:  # noqa: BLE001 - se repite en la ventana, que sabra ensenar el fallo
            log.exception("Fallo la busqueda en segundo plano; se repite en primer plano")
            resultado = _FALLO
        try:
            dueno._hecho.emit(self.generacion, resultado)
        except RuntimeError:
            pass  # la ventana ya se cerro


class BusquedaEnFondo(QObject):
    """Lanza `trabajo(con)` en un hilo y entrega el resultado con `al_terminar(resultado)`
    en el hilo de la ventana, solo si nadie ha pedido otra cosa mientras tanto."""

    _hecho = Signal(int, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.generacion = 0
        self._pendiente: tuple[Callable, Callable, sqlite3.Connection] | None = None
        self._piscina = QThreadPool(self)
        # Un solo hilo: las busquedas no compiten entre si por la CPU (y el usuario esta
        # jugando); la vieja que ya esta en marcha termina y su resultado se tira.
        self._piscina.setMaxThreadCount(1)
        self._piscina.setExpiryTimeout(-1)  # conserva el hilo y su conexion abierta
        self._local = threading.local()
        self._hecho.connect(self._entregar)

    def pedir(self, con: sqlite3.Connection, trabajo: Callable[[sqlite3.Connection], Any],
              al_terminar: Callable[[Any], None]) -> None:
        """Una peticion nueva deja sin efecto las anteriores que aun no se hayan entregado."""
        self.generacion += 1
        ruta = ruta_de(con)
        if not ruta:
            # Base en memoria: no se puede abrir desde otro hilo. Se hace aqui mismo.
            self._pendiente = None
            al_terminar(trabajo(con))
            return
        self._pendiente = (trabajo, al_terminar, con)
        self._piscina.start(_Tarea(self, self.generacion, ruta, id(con), trabajo))

    def cancelar(self) -> None:
        """Lo que este en marcha ya no se ensenara (p. ej. al buscar en primer plano)."""
        self.generacion += 1
        self._pendiente = None

    def ocupada(self) -> bool:
        return self._pendiente is not None

    def esperar(self, ms: int = 5000) -> bool:
        """Espera a que el hilo termine (pruebas y mediciones). El resultado llega despues,
        al procesar los eventos de la ventana."""
        return self._piscina.waitForDone(ms)

    def _conexion_del_hilo(self, ruta: str, marca: int) -> sqlite3.Connection:
        # Se reabre si la ventana cambio de conexion (indice reconstruido o cambiado).
        actual = getattr(self._local, "con", None)
        if actual is None or getattr(self._local, "clave", None) != (ruta, marca):
            if actual is not None:
                actual.close()
            actual = sqlite3.connect(ruta)
            self._local.con = actual
            self._local.clave = (ruta, marca)
        return actual

    def _entregar(self, generacion: int, resultado: Any) -> None:
        if generacion != self.generacion or self._pendiente is None:
            return  # vieja: ya se pidio otra cosa
        trabajo, al_terminar, con = self._pendiente
        self._pendiente = None
        if resultado is _FALLO:
            resultado = trabajo(con)  # en primer plano, con la conexion de la ventana
        al_terminar(resultado)
