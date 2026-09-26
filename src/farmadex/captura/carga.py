"""Cuanta CPU esta gastando el resto del equipo (el juego, sobre todo).

Lo usa el OCR en modo automatico para no quitarle nucleos al juego cuando va
apretado. Se mide el uso de todo el sistema con `GetSystemTimes` y se le resta
lo que gasta el propio Farmadex (`GetProcessTimes`): asi las lecturas del OCR no
se cuentan a si mismas como "carga" y no hay vaivenes.

Sin dependencias: ctypes contra kernel32. Fuera de Windows no se mide nada y
`uso_ajeno()` devuelve None (el OCR usa entonces sus hilos normales).

Barato a proposito: un hilo dormido que toma una muestra por segundo (dos
llamadas al sistema, microsegundos) y guarda las ultimas; decidir es hacer una
media de lo guardado, sin esperar ni medir nada en el momento de leer.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque

from ..registro_log import obtener

log = obtener("carga")

INTERVALO_S = 1.0  # una muestra por segundo
MUESTRAS = 4  # la media mira los ultimos ~4 segundos


_k32 = None


def _kernel32():  # pragma: no cover - depende del SO
    """kernel32 propio, con los tipos declarados, sin tocar el `ctypes.windll` que usa el resto."""
    global _k32
    if _k32 is None:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        puntero = ctypes.POINTER(wintypes.FILETIME)
        k32.GetSystemTimes.argtypes = [puntero, puntero, puntero]
        k32.GetSystemTimes.restype = wintypes.BOOL
        k32.GetCurrentProcess.argtypes = []
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE, puntero, puntero, puntero, puntero]
        k32.GetProcessTimes.restype = wintypes.BOOL
        _k32 = k32
    return _k32


def _leer_sistema() -> tuple[int, int] | None:  # pragma: no cover - depende del SO
    """(ocupado, total) de todos los nucleos juntos, en unidades de 100 ns."""
    import ctypes
    from ctypes import wintypes

    reposo, nucleo, usuario = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not _kernel32().GetSystemTimes(ctypes.byref(reposo), ctypes.byref(nucleo), ctypes.byref(usuario)):
        return None
    a_int = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime  # noqa: E731
    total = a_int(nucleo) + a_int(usuario)  # el tiempo de nucleo ya incluye el de reposo
    return total - a_int(reposo), total


def _leer_proceso() -> int | None:  # pragma: no cover - depende del SO
    """CPU gastada por este proceso (todos sus hilos), en unidades de 100 ns."""
    import ctypes
    from ctypes import wintypes

    k32 = _kernel32()
    creado, salido, nucleo, usuario = (wintypes.FILETIME() for _ in range(4))
    if not k32.GetProcessTimes(
        k32.GetCurrentProcess(), ctypes.byref(creado), ctypes.byref(salido), ctypes.byref(nucleo), ctypes.byref(usuario)
    ):
        return None
    a_int = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime  # noqa: E731
    return a_int(nucleo) + a_int(usuario)


class MedidorCarga:
    """Media reciente del uso de CPU de los demas procesos, de 0 a 1."""

    def __init__(self, intervalo: float = INTERVALO_S, muestras: int = MUESTRAS,
                 leer_sistema=None, leer_proceso=None):
        self.intervalo = intervalo
        self._leer_sistema = leer_sistema or _leer_sistema
        self._leer_proceso = leer_proceso or _leer_proceso
        self._muestras: deque[tuple[int, int]] = deque(maxlen=max(1, muestras))
        self._previa: tuple[int, int, int] | None = None
        self._cerrojo = threading.Lock()
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self._roto = False

    def _foto(self) -> tuple[int, int, int] | None:
        try:
            sistema = self._leer_sistema()
            propio = self._leer_proceso()
        except Exception as e:  # noqa: BLE001 - medir nunca puede tumbar la lectura
            if not self._roto:
                log.warning("No se pudo medir la carga del equipo: %s", e)
                self._roto = True
            return None
        if sistema is None or propio is None:
            return None
        return sistema[0], sistema[1], propio

    def muestrear(self) -> None:
        """Toma una muestra y la compara con la anterior (lo llama el hilo cada segundo)."""
        foto = self._foto()
        if foto is None:
            return
        with self._cerrojo:
            previa, self._previa = self._previa, foto
            if previa is None:
                return
            total = foto[1] - previa[1]
            if total <= 0:
                return
            ajeno = (foto[0] - previa[0]) - (foto[2] - previa[2])
            self._muestras.append((min(max(ajeno, 0), total), total))

    def uso_ajeno(self) -> float | None:
        """Uso medio reciente (0-1) de la CPU por otros procesos; None si no se sabe."""
        with self._cerrojo:
            if not self._muestras:
                return None
            ocupado = sum(o for o, _ in self._muestras)
            total = sum(t for _, t in self._muestras)
        return ocupado / total if total > 0 else None

    def nucleos_libres(self, nucleos: int | None = None) -> float | None:
        """Cuantos nucleos logicos quedan sin usar por los demas, segun la media reciente."""
        uso = self.uso_ajeno()
        if uso is None:
            return None
        return (1.0 - uso) * (nucleos or os.cpu_count() or 4)

    def iniciar(self) -> None:
        """Arranca el hilo de muestreo (una vez; las siguientes llamadas no hacen nada)."""
        with self._cerrojo:
            if self._hilo is not None:
                return
            self._parar.clear()
            self._hilo = threading.Thread(target=self._bucle, name="farmadex-carga", daemon=True)
        self.muestrear()  # la primera foto: la media sale al segundo
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        hilo, self._hilo = self._hilo, None
        if hilo is not None and hilo is not threading.current_thread():
            hilo.join(timeout=2)

    def _bucle(self) -> None:
        while not self._parar.wait(self.intervalo):
            self.muestrear()


_compartido: MedidorCarga | None = None
_cerrojo_modulo = threading.Lock()


def disponible() -> bool:
    """Si en este sistema se puede medir la carga (solo Windows)."""
    return sys.platform == "win32"


def medidor() -> MedidorCarga | None:
    """El medidor compartido, arrancado la primera vez; None fuera de Windows."""
    global _compartido
    if not disponible():
        return None
    with _cerrojo_modulo:
        if _compartido is None:
            _compartido = MedidorCarga()
            _compartido.iniciar()
            log.info("Medidor de carga de CPU en marcha")
        return _compartido


def uso_ajeno() -> float | None:
    """Atajo: uso medio reciente de la CPU por otros procesos (0-1), o None."""
    m = medidor()
    return m.uso_ajeno() if m is not None else None


def esperar_primera_media(tope_s: float = 1.5) -> None:
    """Para herramientas de medida: espera a que haya al menos una media (no usar en la app)."""
    m = medidor()
    fin = time.monotonic() + tope_s
    while m is not None and m.uso_ajeno() is None and time.monotonic() < fin:
        time.sleep(0.05)
