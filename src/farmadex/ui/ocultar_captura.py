"""Esconder Farmadex un instante mientras se captura la pantalla del juego.

Farmadex esta siempre encima del juego. Cualquier lectura por captura (build, arcanos
agrietados, bajo el cursor, recompensas de reliquia, reliquia bajo el raton) recogia
tambien nuestras ventanas si estaban encima de lo que habia que leer, y el OCR leia
Farmadex en vez del juego ("con el programa encima no lee bien la build").

Como se arregla, para todas las lecturas a la vez (`pantalla.capturar` llama aqui):

1. El hilo de captura pide al hilo de Qt que esconda las ventanas de Farmadex que se
   solapan con la zona a capturar. Solo esas: el panel de reliquias que esta debajo de
   las cartas se queda como esta si no pisa la zona leida.
2. Esconder = opacidad 0 (no hide()): no cambia el foco, no mueve nada, no relanza la
   disposicion de la ventana y el juego ni se entera.
3. El hilo de captura espera la confirmacion con un limite (si Qt esta ocupado, se
   captura igual) y luego espera a que el compositor de Windows pinte sin ellas
   (1-2 fotogramas, `pantalla.esperar_composicion`).
4. Captura y pide devolverlas. Siempre: `pantalla.ocultando` restaura en su salida pase
   lo que pase, y ademas cada ocultacion arma un temporizador de seguridad en el hilo
   de Qt que las devuelve aunque la peticion de restaurar no llegase nunca.

No se usa la exclusion de captura de Windows (SetWindowDisplayAffinity con
WDA_EXCLUDEFROMCAPTURE): tambien sacaria Farmadex del directo en OBS.

Las lecturas periodicas (lector pasivo) no pasan por aqui: esconder cada 1,5 s haria
parpadear Farmadex todo el rato. Esas descartan lo tapado (`pantalla.descartar_propias`).
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication, QWindow

from ..captura import pantalla
from ..captura.pantalla import Region
from ..registro_log import obtener

log = obtener("ocultar_captura")

# Lo maximo que el hilo de captura espera a que el de Qt esconda las ventanas.
ESPERA_MAX_S = 0.25
# Si la orden de devolverlas se pierde, el hilo de Qt las devuelve solo tras esto.
SEGURIDAD_MS = 1500


class _Peticion:
    """Una ocultacion: que zona, que ventanas se escondieron y en que quedo."""

    __slots__ = ("region", "hecho", "cerrojo", "cancelada", "ventanas", "restaurada")

    def __init__(self, region: Region):
        self.region = region
        self.hecho = threading.Event()
        self.cerrojo = threading.Lock()
        self.cancelada = False
        self.ventanas: list[QWindow] = []
        self.restaurada = False


def _ventanas_qt() -> list[QWindow]:
    """Las ventanas de nivel superior de Farmadex que se ven ahora mismo."""
    visibles = []
    for ventana in QGuiApplication.topLevelWindows():
        try:
            if not ventana.isVisible() or ventana.opacity() <= 0.0:
                continue
            if ventana.visibility() in (QWindow.Hidden, QWindow.Minimized):
                continue
        except RuntimeError:  # borrada por Qt entre medias
            continue
        visibles.append(ventana)
    return visibles


def _rect_fisico(ventana: QWindow) -> Region | None:
    """Rectangulo de la ventana en pixeles fisicos de pantalla, como la captura."""
    if QGuiApplication.platformName() == "windows":
        try:
            return pantalla.region_marco(int(ventana.winId()))
        except (OSError, ValueError, RuntimeError):
            return None
    g = ventana.frameGeometry()
    escala = ventana.devicePixelRatio() or 1.0
    return Region(round(g.x() * escala), round(g.y() * escala),
                  round(g.width() * escala), round(g.height() * escala))


def _hay_propias_en(region: Region) -> bool:
    """Comprobacion rapida desde el hilo de captura (Win32, sin Qt)."""
    return any(pantalla.interseccion(region, r) for r in pantalla.ventanas_propias())


class OcultadorVentanas(QObject):
    """Vive en el hilo de Qt. `ocultar`/`restaurar` se llaman desde cualquier hilo."""

    _pedir = Signal(object)
    _soltar = Signal(object)

    def __init__(self, parent=None, ventanas=None, rect_fisico=None, esperar=None,
                 precomprobar="auto", espera_max_s: float = ESPERA_MAX_S,
                 seguridad_ms: int = SEGURIDAD_MS):
        super().__init__(parent)
        self._ventanas = ventanas or _ventanas_qt
        self._rect_fisico = rect_fisico or _rect_fisico
        self._esperar = esperar or pantalla.esperar_composicion
        if precomprobar == "auto":
            # Solo con ventanas nativas de verdad: en pruebas (offscreen) no hay HWND.
            precomprobar = _hay_propias_en if QGuiApplication.platformName() == "windows" else None
        self._precomprobar = precomprobar
        self.espera_max_s = espera_max_s
        self.seguridad_ms = seguridad_ms
        # ventana -> [opacidad original, cuantas peticiones la tienen escondida]
        self._ocultas: dict[QWindow, list] = {}
        self._pedir.connect(self._aplicar, Qt.QueuedConnection)
        self._soltar.connect(self._devolver, Qt.QueuedConnection)
        # Medicion: cuanto anade esconder a cada lectura.
        self.ocultaciones = 0
        self.segundos = 0.0

    # -- desde el hilo de captura ------------------------------------------------

    def ocultar(self, region: Region) -> _Peticion | None:
        """Esconde lo que tape `region` y espera a que desaparezca de la pantalla.

        Devuelve la ficha para `restaurar`, o None si no habia nada que esconder o el
        hilo de Qt no contesto a tiempo (entonces se captura con lo que haya).
        """
        # (Con otra lectura en curso lo escondido ya no se ve en Win32: se pregunta a Qt.)
        if self._precomprobar is not None and not self._ocultas and not self._precomprobar(region):
            return None  # nada nuestro encima: ni se molesta al hilo de Qt
        t0 = time.perf_counter()
        peticion = _Peticion(region)
        if QThread.currentThread() is self.thread():
            self._aplicar(peticion)  # llamado desde el propio hilo de Qt: directo
        else:
            self._pedir.emit(peticion)
            if not peticion.hecho.wait(self.espera_max_s):
                with peticion.cerrojo:
                    if not peticion.hecho.is_set():
                        peticion.cancelada = True
                        log.debug("La ventana no contesto a tiempo; se captura sin esconderla")
                        return None
        if not peticion.ventanas:
            return None
        self._esperar()
        self.ocultaciones += 1
        self.segundos += time.perf_counter() - t0
        return peticion

    def restaurar(self, peticion: _Peticion | None) -> None:
        if peticion is None:
            return
        if QThread.currentThread() is self.thread():
            self._devolver(peticion)
        else:
            self._soltar.emit(peticion)

    # -- en el hilo de Qt ----------------------------------------------------------

    @Slot(object)
    def _aplicar(self, peticion: _Peticion) -> None:
        with peticion.cerrojo:
            if peticion.cancelada:
                return
            try:
                # Las que ya escondio otra lectura en curso tambien cuentan (estan a 0).
                candidatas = list(self._ventanas())
                candidatas += [v for v in self._ocultas if v not in candidatas]
                for ventana in candidatas:
                    rect = self._rect_fisico(ventana)
                    if rect is None or pantalla.interseccion(rect, peticion.region) is None:
                        continue
                    apunte = self._ocultas.get(ventana)
                    if apunte is None:
                        self._ocultas[ventana] = [ventana.opacity(), 1]
                        ventana.setOpacity(0.0)
                    else:
                        apunte[1] += 1
                    peticion.ventanas.append(ventana)
            except Exception:  # noqa: BLE001 - lo escondido hasta aqui se devuelve abajo
                log.exception("Fallo escondiendo Farmadex para capturar")
            finally:
                peticion.hecho.set()
        if peticion.ventanas:
            QTimer.singleShot(self.seguridad_ms, self, lambda p=peticion: self._devolver(p))

    @Slot(object)
    def _devolver(self, peticion: _Peticion) -> None:
        if peticion.restaurada:
            return
        peticion.restaurada = True
        for ventana in peticion.ventanas:
            apunte = self._ocultas.get(ventana)
            if apunte is None:
                continue
            apunte[1] -= 1
            if apunte[1] > 0:
                continue  # otra lectura la sigue necesitando escondida
            del self._ocultas[ventana]
            try:
                ventana.setOpacity(apunte[0])
            except RuntimeError:  # la ventana ya no existe
                pass

    def restaurar_todo(self) -> None:
        """Al cerrar: nada se queda escondido."""
        for ventana, (opacidad, _n) in list(self._ocultas.items()):
            try:
                ventana.setOpacity(opacidad)
            except RuntimeError:
                pass
        self._ocultas.clear()

    @property
    def escondidas(self) -> int:
        return len(self._ocultas)
