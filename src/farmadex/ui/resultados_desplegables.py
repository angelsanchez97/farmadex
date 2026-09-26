"""Lista de resultados de la vista compacta que se despliega en su sitio.

Antes la vista compacta ensenaba un resultado cada vez y para ver mas habia que ir a la
ficha completa, que es otra vista. Ahora salen todos los resultados en lista, cada uno
con el color de su tipo, y al pulsar uno se abren sus detalles justo debajo (donde sale,
probabilidades, estadisticas...) sin perder la busqueda. Pulsarlo otra vez lo cierra.

El widget no sabe de indices ni de fichas: la vista compacta le da los resultados y el
HTML del detalle del que este abierto. Los enlaces "copiar:" (codigo de un glifo) se
resuelven aqui; los del glosario se ensenan al pasar el raton; el resto se reenvian.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..idiomas import nombre as nombre_idioma, t
from . import colores_tipo, glosario
from .ficha_detalles import PREFIJO_COPIAR
from .widgets import PALETA


def titulo_resultado(r: dict) -> str:
    """'Sistemas de Ash Prime', 'Hepit' o 'Supervivencia': el nombre de la fila."""
    if r.get("clave"):
        return r.get("nodo_es") or r.get("nodo_en") or r.get("modo") or ""
    nombre = nombre_idioma(r)
    padre = nombre_idioma(r, "padre")
    return t("{nombre} de {padre}", nombre=nombre, padre=padre) if padre else nombre


class _Cabecera(QLabel):
    pulsada = Signal()

    def mousePressEvent(self, evento):  # noqa: N802 - firma de Qt
        if evento.button() == Qt.LeftButton:
            self.pulsada.emit()
            evento.accept()
            return
        super().mousePressEvent(evento)


class _Fila(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cabecera = _Cabecera()
        self.cabecera.setTextFormat(Qt.RichText)
        self.cabecera.setCursor(Qt.PointingHandCursor)
        self.detalle = QLabel()
        self.detalle.setTextFormat(Qt.RichText)
        self.detalle.setWordWrap(True)
        self.detalle.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.TextSelectableByMouse)
        self.detalle.hide()
        glosario.conectar_etiqueta(self.detalle)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(6, 3, 6, 3)
        caja.setSpacing(2)
        caja.addWidget(self.cabecera)
        caja.addWidget(self.detalle)


class ResultadosDesplegables(QScrollArea):
    # Se ha pulsado una fila cerrada: la vista compacta la abre con _mostrar(fila).
    elegida = Signal(int)
    # Enlace de un detalle que no es del glosario ni de copiar (item:, buscar:...).
    enlace = Signal(str)
    # Se ha copiado un texto al portapapeles (el codigo de un glifo).
    copiado = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._contenido = QWidget()
        self._caja = QVBoxLayout(self._contenido)
        self._caja.setContentsMargins(0, 0, 0, 0)
        self._caja.setSpacing(1)
        self._caja.addStretch(1)
        self.setWidget(self._contenido)
        self._resultados: list[dict] = []
        self._filas: list[_Fila] = []
        self.abierta = -1
        # Fila que el usuario cerro a mano: no se vuelve a abrir sola al repintar.
        self._cerrada_a_mano = -1

    # -- datos -------------------------------------------------------------------

    def poner(self, resultados: list[dict]) -> None:
        for fila in self._filas:
            fila.setParent(None)
            fila.deleteLater()
        self._filas = []
        self._resultados = list(resultados)
        self.abierta = self._cerrada_a_mano = -1
        for posicion, r in enumerate(self._resultados):
            fila = _Fila(self._contenido)
            fila.cabecera.pulsada.connect(lambda p=posicion: self._pulsada(p))
            fila.detalle.linkActivated.connect(lambda url, f=fila: self._enlace(url, f.detalle))
            self._caja.insertWidget(self._caja.count() - 1, fila)
            self._filas.append(fila)
        self.repintar()
        self.verticalScrollBar().setValue(0)

    def desplegar(self, posicion: int, contenido: str) -> None:
        """Abre la fila `posicion` con ese HTML y cierra las demas."""
        if not 0 <= posicion < len(self._filas):
            return
        if posicion == self._cerrada_a_mano:
            return
        self._cerrada_a_mano = -1
        for i, fila in enumerate(self._filas):
            if i != posicion:
                fila.detalle.hide()
        fila = self._filas[posicion]
        fila.detalle.setText(contenido)
        fila.detalle.show()
        self.abierta = posicion
        self._marcar()
        self.ensureWidgetVisible(fila, 0, 0)

    def plegar(self) -> None:
        for fila in self._filas:
            fila.detalle.hide()
        self._cerrada_a_mano = self.abierta
        self.abierta = -1
        self._marcar()

    # -- aspecto -------------------------------------------------------------------

    def repintar(self) -> None:
        p = PALETA
        for r, fila in zip(self._resultados, self._filas):
            clave = colores_tipo.tipo_de(r)
            color = colores_tipo.color(clave, p["panel2"])
            fila.cabecera.setText(
                f"<span style='color:{color}'>&#9679;</span>&nbsp;"
                f"<b style='color:{p['texto']}'>{html.escape(titulo_resultado(r))}</b>"
                f"&nbsp;&nbsp;<span style='color:{color};font-size:11px'>{html.escape(colores_tipo.nombre(clave))}</span>"
            )
        self._marcar()

    def _marcar(self) -> None:
        p = PALETA
        for i, fila in enumerate(self._filas):
            fondo = p["panel2"] if i == self.abierta else "transparent"
            borde = p["acento"] if i == self.abierta else "transparent"
            fila.setStyleSheet(
                f"_Fila {{ background: {fondo}; border-left: 3px solid {borde}; border-radius: 4px; }}"
            )

    # -- eventos -------------------------------------------------------------------

    def _pulsada(self, posicion: int) -> None:
        if posicion == self.abierta:
            self.plegar()
            return
        self._cerrada_a_mano = -1
        self.elegida.emit(posicion)

    def _enlace(self, url: str, etiqueta: QLabel) -> None:
        if url.startswith(PREFIJO_COPIAR):
            texto = url.removeprefix(PREFIJO_COPIAR)
            QGuiApplication.clipboard().setText(texto)
            self.copiado.emit(texto)
            return
        if glosario.mostrar(url, etiqueta):
            return
        self.enlace.emit(url)
