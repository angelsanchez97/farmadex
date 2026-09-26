"""La rueda del raton no cambia desplegables, numeros ni deslizadores sin querer.

Al bajar por Ajustes con la rueda, en cuanto el cursor pasaba por encima de un
desplegable ("Ritmo del juego") o de un numero, la rueda dejaba de mover la
pagina y empezaba a cambiar ese valor. Este filtro, instalado una vez en la
aplicacion, lo corrige para todos los controles, esten en la pestana que esten:

- Desplegables (QComboBox) cerrados: la rueda nunca cambia su valor. Para
  elegir se hace clic y se elige en la lista, y ahi la rueda si funciona.
- Numeros (QSpinBox y parecidos) y deslizadores: solo si el control tiene el
  foco, es decir, si el usuario ha hecho clic en el para cambiarlo.

En los dos casos la rueda sigue desplazando la pagina que haya debajo.
Ademas se les pone foco "fuerte" (clic o tabulador): con el de por defecto, la
propia rueda les daba el foco y con el, el permiso para cambiar el valor.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox, QScrollBar, QWidget

# Propiedad que un control puede ponerse para quedar fuera del filtro (p. ej. un
# deslizador de volumen que SI debe responder a la rueda al pasar por encima).
PROPIEDAD_LIBRE = "farmadex_rueda_libre"


def _controlado(objeto) -> bool:
    # Las barras de desplazamiento tambien son QAbstractSlider, pero son justo lo que
    # la rueda tiene que mover siempre.
    if isinstance(objeto, QScrollBar):
        return False
    return isinstance(objeto, (QComboBox, QAbstractSpinBox, QAbstractSlider)) and not objeto.property(
        PROPIEDAD_LIBRE
    )


def _control_de(objeto) -> QWidget | None:
    """El control al que pertenece `objeto` (la caja de texto de un QSpinBox es hija suya)."""
    w = objeto if isinstance(objeto, QWidget) else None
    for _ in range(3):
        if w is None:
            return None
        if _controlado(w):
            return w
        if w.isWindow():
            # La lista abierta de un desplegable es una ventana aparte hija del
            # desplegable: ahi la rueda tiene que funcionar.
            return None
        w = w.parentWidget()
    return None


def _zona_desplazable(control: QWidget) -> QAbstractScrollArea | None:
    w = control.parentWidget()
    while w is not None:
        if isinstance(w, QAbstractScrollArea):
            return w
        if w.isWindow():
            return None
        w = w.parentWidget()
    return None


def rueda_permitida(control: QWidget) -> bool:
    """Si la rueda puede cambiar el valor de este control ahora mismo."""
    if isinstance(control, QComboBox):
        # Con la lista abierta la rueda la recibe la lista, no el desplegable.
        return False
    return control.hasFocus() or any(
        hijo.hasFocus() for hijo in control.findChildren(QWidget)
    )


class FiltroRueda(QObject):
    """Filtro global: se instala con `instalar()` sobre la QApplication."""

    def eventFilter(self, objeto, evento):  # noqa: N802 - firma de Qt
        tipo = evento.type()
        if tipo == QEvent.Polish and _controlado(objeto):
            if objeto.focusPolicy() == Qt.WheelFocus:
                objeto.setFocusPolicy(Qt.StrongFocus)
            return False
        if tipo != QEvent.Wheel:
            return False
        control = _control_de(objeto)
        if control is None or rueda_permitida(control):
            return False
        # Se le quita el evento al control y se le pasa a la zona con barra de
        # desplazamiento que lo contiene (un evento reenviado no sube solo de padre en padre).
        zona = _zona_desplazable(control)
        if zona is not None:
            visor = zona.viewport()
            global_ = evento.globalPosition()
            local = QPointF(visor.mapFromGlobal(global_.toPoint()))
            copia = QWheelEvent(
                local, global_, evento.pixelDelta(), evento.angleDelta(), evento.buttons(),
                evento.modifiers(), evento.phase(), evento.inverted(),
            )
            QApplication.sendEvent(visor, copia)
        return True


_filtro: FiltroRueda | None = None


def instalar(app: QApplication | None = None) -> FiltroRueda | None:
    """Instala el filtro en la aplicacion (una sola vez). Devuelve el filtro."""
    global _filtro
    app = app or QApplication.instance()
    if app is None:
        return None
    if _filtro is None:
        _filtro = FiltroRueda(app)
        app.installEventFilter(_filtro)
        # Los controles que ya existieran se pulieron antes del filtro.
        for w in app.allWidgets():
            if _controlado(w) and w.focusPolicy() == Qt.WheelFocus:
                w.setFocusPolicy(Qt.StrongFocus)
    return _filtro


def desinstalar(app: QApplication | None = None) -> None:
    """Quita el filtro (para las pruebas)."""
    global _filtro
    app = app or QApplication.instance()
    if app is not None and _filtro is not None:
        app.removeEventFilter(_filtro)
    _filtro = None
