"""Recuadro "Leyendo..." que sale al instante al pulsar un atajo de lectura.

Una lectura de pantalla tarda de una decima a medio segundo, y hasta ahora no se veia
nada mientras tanto: parecia que el atajo no habia hecho caso y el jugador lo volvia a
pulsar. Ahora, en cuanto se pulsa (recompensas, build, agrietado o lo que hay bajo el
cursor), aparece un recuadro pequeno con "Leyendo..." junto al cursor (o arriba, en las
recompensas). Al acabar:

- si se ha leido algo, el recuadro se va y sale el resultado de siempre (ficha, panel,
  pestana), sin restos;
- si no, dice que no se ha podido leer y se va solo a los pocos segundos.

No retrasa la lectura: se pinta en el hilo de la ventana mientras la captura va en el
suyo. Y no se cuela en ella: se excluye de las capturas de pantalla con
SetWindowDisplayAffinity (WDA_EXCLUDEFROMCAPTURE), asi que no hay que esconderlo antes de
capturar ni parpadea. Ese modo tambien lo quita de OBS, lo que para un aviso de medio
segundo es justo lo que se quiere. Si Windows no lo admite (anterior a Windows 10 2004),
se coloca arriba, fuera de lo que se va a leer, para que no haya que esconderlo (y en la
build, que se lee la pantalla entera, no se ensena: esconderlo retrasaria la lectura).
"""

from __future__ import annotations

import ctypes
import time

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..idiomas import t
from ..registro_log import obtener
from .estilo_c import color, fuente, px, ruta_chaflan

log = obtener("aviso_lectura")

WDA_EXCLUDEFROMCAPTURE = 0x11
# Marca (propiedad de la QWindow) de las ventanas que el ocultador de capturas no toca.
PROPIEDAD_SIN_OCULTAR = "farmadex_sin_ocultar"

# Lo que se lee con cada atajo (titulo del recuadro).
TITULOS = {
    "reliquias": "Recompensas de reliquia",
    "build": "Pantalla de mejoras",
    "agrietado": "Agrietado",
    "cursor": "Bajo el cursor",
}
SEGUNDOS_FALLO = 3.0  # lo que se queda "No se ha podido leer" en pantalla
LIMITE_S = 20.0  # si la lectura no contesta nunca, el recuadro no se queda para siempre


def excluir_de_capturas(widget: QWidget) -> bool:
    """Pide a Windows que la ventana no salga en las capturas; True si lo acepta."""
    if QGuiApplication.platformName() != "windows":
        return False
    try:
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE))
    except (AttributeError, OSError, ValueError):
        return False


class CajaLectura(QWidget):
    """El recuadro pintado a mano: no coge el foco ni el raton y va siempre encima."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.titulo = ""
        self.texto = ""
        self.fallo = False
        self.excluida = False

    def poner(self, titulo: str, texto: str, fallo: bool = False) -> None:
        self.titulo, self.texto, self.fallo = titulo, texto, fallo
        margen = px(12, False)
        ancho = max(QFontMetrics(fuente("rotulo")).horizontalAdvance(titulo.upper()),
                    QFontMetrics(fuente("normal")).horizontalAdvance(texto)) + 2 * margen + px(14, False)
        alto = QFontMetrics(fuente("rotulo")).height() + QFontMetrics(fuente("normal")).height() + 2 * margen
        self.resize(min(ancho, px(420, False)), alto)
        self.update()

    def paintEvent(self, _evento):  # noqa: N802 - firma de Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        camino = ruta_chaflan(r, px(8, False))
        p.fillPath(camino, color("panel"))
        p.setPen(QPen(color("aviso" if self.fallo else "acento_tenue"), 1))
        p.drawPath(camino)
        p.setPen(QPen(color("aviso" if self.fallo else "acento"), 2))
        p.drawLine(QPointF(r.left() + px(8, False), r.top() + 1), QPointF(r.left() + px(40, False), r.top() + 1))
        m = px(12, False)
        f_tit, f_txt = fuente("rotulo"), fuente("normal")
        alto_tit = QFontMetrics(f_tit).height()
        ancho = self.width() - 2 * m
        p.setFont(f_tit)
        p.setPen(color("suave"))
        p.drawText(QRectF(m, m, ancho, alto_tit), Qt.AlignLeft | Qt.AlignVCenter, self.titulo.upper())
        p.setFont(f_txt)
        p.setPen(color("aviso" if self.fallo else "texto"))
        p.drawText(QRectF(m, m + alto_tit, ancho, QFontMetrics(f_txt).height()),
                   Qt.AlignLeft | Qt.AlignVCenter, self.texto)


def colocar(tam: tuple[int, int], punto: tuple[int, int], zona: tuple[int, int, int, int],
            arriba: bool = False) -> tuple[int, int]:
    """Donde va el recuadro: abajo a la derecha del cursor (o centrado arriba), sin salirse."""
    ancho, alto = tam
    zx, zy, zw, zh = zona
    if arriba:
        x, y = zx + (zw - ancho) // 2, zy + int(zh * 0.06)
    else:
        separacion = px(22, False)
        x, y = punto[0] + separacion, punto[1] + separacion
        if x + ancho > zx + zw:
            x = punto[0] - separacion - ancho
        if y + alto > zy + zh:
            y = punto[1] - separacion - alto
    return max(zx, min(x, zx + zw - ancho)), max(zy, min(y, zy + zh - alto))


class AvisoLectura(QObject):
    """Lleva el recuadro: una lectura a la vez, la ultima pulsada manda."""

    def __init__(self, parent=None, activo: bool = True, reloj=time.monotonic):
        super().__init__(parent)
        self.activo = activo
        self._reloj = reloj
        self.caja: CajaLectura | None = None
        self.tipo: str | None = None  # lectura que ensena ahora mismo
        self.estado: str | None = None  # "leyendo", "fallo" o None (escondido)
        self._t = 0.0
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self._caducar)
        # Medicion: cuanto cuesta ensenarlo (tiene que ser nada al lado de la lectura).
        self.ultimo_ms = 0.0

    def _crear(self) -> CajaLectura:
        if self.caja is None:
            self.caja = CajaLectura()
            self.caja.winId()  # la ventana nativa ya, para poder excluirla antes de ensenarla
            self.caja.excluida = excluir_de_capturas(self.caja)
            ventana = self.caja.windowHandle()
            if self.caja.excluida and ventana is not None:
                ventana.setProperty(PROPIEDAD_SIN_OCULTAR, True)
            log.debug("Recuadro de lectura creado (fuera de las capturas: %s)", self.caja.excluida)
        return self.caja

    def leyendo(self, tipo: str, punto: QPoint | None = None, zona_juego: QRect | None = None) -> None:
        """Se ha pulsado el atajo: el recuadro sale ya con "Leyendo..."."""
        if not self.activo:
            return
        t0 = time.perf_counter()
        caja = self._crear()
        if not caja.excluida and tipo == "build":
            # Sin exclusion de capturas, la build (pantalla entera) tendria que esconderlo antes
            # de capturar: costaria tiempo de lectura. Mejor sin recuadro.
            self.esconder()
            return
        caja.poner(t(TITULOS.get(tipo, "Lectura")), t("Leyendo…"))
        punto = punto if punto is not None else QCursor.pos()
        if zona_juego is None or zona_juego.isEmpty():
            pantalla = QGuiApplication.screenAt(punto) or QGuiApplication.primaryScreen()
            zona_juego = pantalla.geometry() if pantalla is not None else QRect(0, 0, 1920, 1080)
        x, y = colocar((caja.width(), caja.height()), (punto.x(), punto.y()),
                       (zona_juego.x(), zona_juego.y(), zona_juego.width(), zona_juego.height()),
                       # Fuera de las capturas puede ir junto al cursor; si no, arriba, lejos de
                       # lo que se lee (tarjeta, nombre bajo el cursor, fila de recompensas).
                       arriba=tipo == "reliquias" or not caja.excluida)
        caja.move(x, y)
        caja.show()
        caja.raise_()
        self.tipo, self.estado, self._t = tipo, "leyendo", self._reloj()
        self._temporizador.start(int(LIMITE_S * 1000))
        self.ultimo_ms = (time.perf_counter() - t0) * 1000

    def listo(self, tipo: str) -> None:
        """La lectura de `tipo` ha dado resultado (el resultado se ensena por su lado)."""
        if tipo == self.tipo:
            self.esconder()

    def fallo(self, tipo: str, motivo: str = "") -> None:
        """La lectura de `tipo` no ha podido leer nada."""
        if tipo != self.tipo or self.caja is None or self.estado is None:
            return
        self.caja.poner(t(TITULOS.get(tipo, "Lectura")), motivo or t("No se ha podido leer"), fallo=True)
        self.estado = "fallo"
        self._temporizador.start(int(SEGUNDOS_FALLO * 1000))

    def esconder(self) -> None:
        self._temporizador.stop()
        self.tipo, self.estado = None, None
        if self.caja is not None and self.caja.isVisible():
            self.caja.hide()

    def _caducar(self) -> None:
        if self.estado == "leyendo":
            log.info("La lectura (%s) no contesto a tiempo: fuera el recuadro", self.tipo)
        self.esconder()

    def visible(self) -> bool:
        return self.caja is not None and self.caja.isVisible()

    def cerrar(self) -> None:
        self.esconder()
        if self.caja is not None:
            self.caja.deleteLater()
            self.caja = None
