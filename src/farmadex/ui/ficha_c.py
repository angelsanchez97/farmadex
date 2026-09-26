"""Piezas de la ficha de Buscar en el estilo C (paneles, tira de rondas, pasos, barras).

La ficha deja de ser un solo QTextBrowser: es una columna (o dos) de paneles C. Lo que
lleva enlaces y glosario (tablas de fuentes, reliquias, habilidades...) sigue siendo texto
enriquecido, pero en trozos (`BloqueHtml`) que miden lo que su contenido y van dentro de
cada panel; lo demas (cabecera, imagen en su pedestal, pasos, barras, rombos) son piezas
pintadas.

`FichaC` es el contenedor con desplazamiento. Conserva la forma de hablar del
QTextBrowser de antes (`toPlainText`, `toHtml`, `setHtml`, `clear`, `anchorAt`,
`anchorClicked`, `document`) para que el resto del programa y las pruebas no tengan que
saber como esta montada por dentro.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QTextDocument, QTextDocumentFragment
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..idiomas import t
from . import glosario, relleno_filas
from .estilo_c import (
    BarraFina,
    EtiquetaC,
    Insignia,
    PiezaC,
    TEXTO,
    Rombo,
    color,
    columna,
    fila,
    fuente,
    px,
    transparente,
)

# Por debajo de este ancho (a escala 1) la ficha de objeto va en una sola columna.
ANCHO_DOS_COLUMNAS = 700


def etiqueta(texto: str, rol: str = "normal", tinta: str | None = None, mayus: bool = False,
             envolver: bool = False, enlaces=None) -> EtiquetaC:
    """EtiquetaC que recuerda su texto original (antes de pasarlo a mayusculas).

    `FichaC.toHtml` devuelve ese texto original: "Sedna", no "SEDNA". Con `enlaces` (una
    funcion que recibe la URL) los enlaces del texto se pueden pulsar y los del glosario
    ensenan su explicacion al pasar el raton.
    """
    e = EtiquetaC(texto, rol, tinta=tinta, mayus=mayus, envolver=envolver)
    e.setProperty("fuenteC", texto)
    if enlaces is not None:
        e.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        e.setOpenExternalLinks(False)
        glosario.conectar_etiqueta(e)
        e.linkActivated.connect(lambda url: None if glosario.es_glosa(url) else enlaces(url))
    return e


class InsigniaGlosa(Insignia):
    """Insignia (BÓVEDA, RELIQUIA...) que explica su termino del glosario al pasar el raton."""

    def __init__(self, texto: str, tinta: str = "acento", clave: str | None = None, tam: int = 11, parent=None):
        self.clave = clave
        self._visible = texto
        super().__init__(texto, tinta=tinta, tam=tam, parent=parent)
        if clave:
            self.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
            glosario.conectar_etiqueta(self)

    def setText(self, texto: str) -> None:  # noqa: N802 - nombre de Qt
        self._visible = texto or ""
        if not getattr(self, "clave", None):
            super().setText(texto)
            return
        visible = (texto or "").upper().replace("&", "&amp;").replace("<", "&lt;")
        c = color(getattr(self, "tinta", "acento")).name()
        # El espacio de anchura cero en Segoe UI sube la linea: en texto enriquecido la tilde
        # de las mayusculas de Bahnschrift (EN BÓVEDA) se cortaba por arriba.
        QLabel.setText(self, f"<span style=\"font-family:'{TEXTO}'\">&#8203;</span>"
                             f"<a href='{glosario.PREFIJO}{self.clave}' style='color:{c};"
                             f"text-decoration:none'>{visible}</a>")

    def refrescar_estilo(self) -> None:
        super().refrescar_estilo()
        if getattr(self, "clave", None):
            self.setText(self._visible)


# -- texto enriquecido que mide lo que su contenido -------------------------------------


class BloqueHtml(glosario.FichaConGlosario):
    """Trozo de ficha en texto enriquecido, sin barras ni fondo, tan alto como su texto.

    Sigue siendo un QTextBrowser: enlaces, glosario al pasar el raton y el relleno de las
    filas de fuentes (relleno_filas) funcionan igual que en la ficha de antes. La rueda del
    raton se la deja a la ficha entera.
    """

    def __init__(self, contenido: str = "", parent=None):
        super().__init__(parent)
        transparente(self)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.viewport().setAutoFillBackground(False)
        # La hoja global da relleno y borde a los QTextBrowser: aqui sobran.
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; padding: 0; margin: 0; }")
        self.document().setDocumentMargin(0)
        self._ajustando = False
        self._relleno = relleno_filas.RellenoFilas(self)
        self.document().documentLayout().documentSizeChanged.connect(self._ajustar)
        if contenido:
            self.setHtml(contenido)

    def setHtml(self, contenido: str) -> None:  # noqa: N802 - nombre de Qt
        super().setHtml(contenido)
        self._ajustar()
        self._relleno.aplicar()

    def _ajustar(self, *_):
        if self._ajustando:
            return
        self._ajustando = True
        try:
            ancho = max(40, self.viewport().width())
            self.document().setTextWidth(ancho)
            marco = self.height() - self.viewport().height() if self.viewport().height() > 0 else 0
            alto = math.ceil(self.document().size().height()) + max(0, marco) + 2
            if self.height() != alto or self.minimumHeight() != alto:
                self.setFixedHeight(alto)
        finally:
            self._ajustando = False

    def resizeEvent(self, evento):  # noqa: N802 - firma de Qt
        super().resizeEvent(evento)
        self._ajustar()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(px(200, False), self.height())

    def wheelEvent(self, evento):  # noqa: N802
        evento.ignore()


# -- el contenedor ------------------------------------------------------------------------


def _texto_plano(w: QWidget) -> str:
    if isinstance(w, QTextBrowser):
        return w.toPlainText()
    if isinstance(w, QLabel):
        texto = w.text()
        if w.textFormat() == Qt.RichText or "<" in texto:
            return QTextDocumentFragment.fromHtml(texto).toPlainText()
        return texto
    return ""


def _texto_html(w: QWidget) -> str:
    if isinstance(w, QTextBrowser):
        return w.toHtml()
    if isinstance(w, QLabel):
        fuente_c = w.property("fuenteC")
        return fuente_c if isinstance(fuente_c, str) and fuente_c else w.text()
    return ""


class FichaC(QScrollArea):
    """Ficha con desplazamiento: una columna de paneles (o dos, si cabe).

    `anadir(widget)` apila piezas; `bloque(html)` crea un BloqueHtml cuyos enlaces salen
    por `anchorClicked`. `vaciar()` borra todo menos lo que el llamante haya aparcado
    antes. `cambio_ancho(estrecha)` avisa al cruzar ANCHO_DOS_COLUMNAS.
    """

    anchorClicked = Signal(QUrl)
    cambio_ancho = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.StrongFocus)
        self._contenido = transparente(QWidget())
        self.capa = QVBoxLayout(self._contenido)
        self.capa.setContentsMargins(0, 0, px(6, False), px(6, False))
        self.capa.setSpacing(px(12, False))
        self.setWidget(self._contenido)
        self.viewport().setAutoFillBackground(False)
        # Objeto que filtra las teclas de la ficha (lo pone la pestana); se instala en cada
        # trozo de texto, que es quien tiene el foco al pinchar dentro.
        self.filtro_teclas = None
        self._estrecha = self.estrecha()

    # -- montaje -------------------------------------------------------------------------

    def vaciar(self) -> None:
        while self.capa.count():
            item = self.capa.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                _borrar_capa(item.layout())

    def clear(self) -> None:
        self.vaciar()

    def anadir(self, pieza, estirar: int = 0):
        if pieza is None:
            return None
        if isinstance(pieza, (QHBoxLayout, QVBoxLayout, QGridLayout)):
            self.capa.addLayout(pieza, estirar)
        else:
            self.capa.addWidget(pieza, estirar)
        return pieza

    def terminar(self) -> None:
        self.capa.addStretch(1)

    def bloque(self, contenido: str = "") -> BloqueHtml:
        b = BloqueHtml(contenido)
        b.anchorClicked.connect(self.anchorClicked)
        if self.filtro_teclas is not None:
            b.installEventFilter(self.filtro_teclas)
        return b

    def setHtml(self, contenido: str) -> None:  # noqa: N802 - como el QTextBrowser de antes
        self.vaciar()
        if contenido:
            self.anadir(self.bloque(contenido))
        self.terminar()

    def estrecha(self) -> bool:
        return self.viewport().width() < px(ANCHO_DOS_COLUMNAS, False)

    def resizeEvent(self, evento):  # noqa: N802
        super().resizeEvent(evento)
        estrecha = self.estrecha()
        if estrecha != self._estrecha:
            self._estrecha = estrecha
            self.cambio_ancho.emit(estrecha)

    # -- lectura (como el QTextBrowser de antes) -----------------------------------------

    def piezas(self) -> list[QWidget]:
        """Las piezas visibles de la ficha en orden de lectura (arriba abajo, izq. a der.)."""
        salida: list[QWidget] = []
        _recorrer(self.capa, salida)
        return salida

    def toPlainText(self) -> str:  # noqa: N802
        return "\n".join(t for t in (_texto_plano(w) for w in self.piezas()) if t)

    def toHtml(self) -> str:  # noqa: N802
        return "\n".join(t for t in (_texto_html(w) for w in self.piezas()) if t)

    def bloques(self) -> list[BloqueHtml]:
        return [w for w in self.piezas() if isinstance(w, BloqueHtml)]

    def document(self) -> QTextDocument:
        """El documento del primer trozo de texto (fichas de un solo trozo)."""
        bloques = self.bloques()
        if bloques:
            return bloques[0].document()
        if not hasattr(self, "_vacio"):
            self._vacio = QTextDocument(self)
        return self._vacio

    def anchorAt(self, pos) -> str:  # noqa: N802
        w = self.childAt(pos)
        while w is not None and not isinstance(w, QTextBrowser):
            w = w.parentWidget()
        if w is None:
            return ""
        return w.anchorAt(w.viewport().mapFrom(self, pos))

    def event(self, evento):  # noqa: N802
        if evento.type() == QEvent.ToolTip:
            url = self.anchorAt(evento.pos())
            if glosario.es_glosa(url):
                QToolTip.showText(evento.globalPos(), glosario.texto(url.removeprefix(glosario.PREFIJO)), self)
                return True
        return super().event(evento)


def _recorrer(capa, salida: list) -> None:
    for i in range(capa.count()):
        item = capa.itemAt(i)
        w = item.widget()
        if w is not None:
            # Solo cuenta lo escondido a proposito: lo recien anadido a una ficha visible
            # sigue "escondido" hasta que Qt lo ensena en la siguiente vuelta del bucle.
            if (w.isHidden() and w.testAttribute(Qt.WA_WState_ExplicitShowHide)) or isinstance(w, QAbstractButton):
                continue
            if isinstance(w, (QTextBrowser, QLabel)):
                salida.append(w)
            elif w.layout() is not None:
                _recorrer(w.layout(), salida)
        elif item.layout() is not None:
            _recorrer(item.layout(), salida)


def _borrar_capa(capa) -> None:
    while capa.count():
        item = capa.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            _borrar_capa(item.layout())


# -- piezas propias de la ficha --------------------------------------------------------------


class TiraRondas(QWidget, PiezaC):
    """Casillas A A B C con lo que da cada parada ("oleada 3", "min 10"...).

    `celdas` = [(letra, pie, explicacion)]: la explicacion sale al pasar el raton. Las
    rotaciones B y C van destacadas: son las que se esperan.
    """

    def __init__(self, celdas: list[tuple[str, str, str]], parent=None):
        super().__init__(parent)
        transparente(self)
        self.celdas = celdas
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refrescar_estilo()

    def refrescar_estilo(self) -> None:
        self.setFixedHeight(px(52, False))
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(len(self.celdas) * px(60, False), px(52, False))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(len(self.celdas) * px(34, False), px(52, False))

    def _cajas(self) -> list[QRectF]:
        n = max(1, len(self.celdas))
        hueco = px(8, False)
        ancho = (self.width() - hueco * (n - 1)) / n
        return [QRectF(i * (ancho + hueco) + 0.5, 0.5, ancho - 1, self.height() - 1) for i in range(n)]

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f_letra = fuente("dato", 20, 600)
        f_pie = fuente("pequeno")
        for caja, (letra, pie, _x) in zip(self._cajas(), self.celdas):
            tinta = {"B": "secundario", "C": "acento"}.get(letra, "texto")
            borde = color("secundario") if letra == "B" else color("borde")
            fondo = QColor(color(tinta))
            fondo.setAlpha(26 if letra in ("B", "C") else 0)
            p.setPen(QPen(borde, 1))
            p.setBrush(fondo)
            p.drawRect(caja)
            p.setFont(f_letra)
            p.setPen(color(tinta))
            p.drawText(QRectF(caja.left(), caja.top() + 2, caja.width(), caja.height() * 0.58),
                       Qt.AlignHCenter | Qt.AlignBottom, letra)
            p.setFont(f_pie)
            p.setPen(color("suave"))
            texto = QFontMetrics(f_pie).elidedText(pie, Qt.ElideRight, int(caja.width()) - 4)
            p.drawText(QRectF(caja.left(), caja.top() + caja.height() * 0.58, caja.width(), caja.height() * 0.4),
                       Qt.AlignHCenter | Qt.AlignTop, texto)
        p.end()

    def event(self, evento):  # noqa: N802
        if evento.type() == QEvent.ToolTip:
            for caja, (_l, _p, explicacion) in zip(self._cajas(), self.celdas):
                if caja.contains(QPointF(evento.pos())) and explicacion:
                    QToolTip.showText(evento.globalPos(), explicacion, self)
                    return True
            QToolTip.hideText()
            return True
        return super().event(evento)


class BarraDano(QWidget, PiezaC):
    """Barra partida por tipos de dano, cada tramo de su color y de su parte del total."""

    def __init__(self, tramos: list[tuple[float, str]], parent=None):
        super().__init__(parent)
        transparente(self)
        self.tramos = [(v, c) for v, c in tramos if v > 0]
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refrescar_estilo()

    def refrescar_estilo(self) -> None:
        self.setFixedHeight(px(8, False))
        self.update()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        total = sum(v for v, _c in self.tramos) or 1
        x = 0.0
        p.fillRect(self.rect(), color("borde"))
        for valor, tinta in self.tramos:
            ancho = self.width() * valor / total
            p.fillRect(QRectF(x, 0, ancho, self.height()), QColor(tinta))
            x += ancho
        p.end()


def hitos(pasos: list[tuple[str, str]], enlaces) -> QWidget:
    """Los pasos para conseguir algo: rombo, PASO n, titulo y detalle (con enlaces y glosario).

    El primer rombo va lleno (lo que hay que hacer ya); los demas, huecos.
    """
    caja = transparente(QWidget())
    capa = QVBoxLayout(caja)
    capa.setContentsMargins(0, 0, 0, 0)
    capa.setSpacing(px(12, False))
    for i, (titulo, detalle) in enumerate(pasos):
        rombo = Rombo(13, "acento", relleno=(i == 0))
        textos = columna(
            etiqueta(t("Paso {n}", n=i + 1), "rotulo", mayus=True),
            etiqueta(titulo, "destacado", envolver=True, enlaces=enlaces),
            espacio=px(2, False),
        )
        if detalle:
            textos.addWidget(etiqueta(detalle, "pequeno", envolver=True, enlaces=enlaces))
        linea = QHBoxLayout()
        linea.setContentsMargins(0, 0, 0, 0)
        linea.setSpacing(px(12, False))
        linea.addWidget(rombo, 0, Qt.AlignTop)
        linea.addLayout(textos, 1)
        capa.addLayout(linea)
    return caja


def filas_datos(pares: list[tuple[str, QWidget | str]], enlaces=None) -> QWidget:
    """Filas "ROTULO ........ valor" (Maestria, Tienes, Mercado...)."""
    caja = transparente(QWidget())
    rejilla = QGridLayout(caja)
    rejilla.setContentsMargins(0, 0, 0, 0)
    rejilla.setHorizontalSpacing(px(14, False))
    rejilla.setVerticalSpacing(px(8, False))
    for i, (rotulo, valor) in enumerate(pares):
        r = etiqueta(rotulo, "rotulo", tinta="suave", mayus=True)
        rejilla.addWidget(r, i, 0, Qt.AlignLeft | Qt.AlignTop)
        if isinstance(valor, str):
            valor = etiqueta(valor, "fuerte", envolver=True, enlaces=enlaces)
            valor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rejilla.addWidget(valor, i, 1)
    rejilla.setColumnStretch(1, 1)
    return caja


def estadisticas(filas: list[tuple[str, str, float | None]], columnas: int = 2) -> QWidget:
    """Rejilla de estadisticas: nombre a la izquierda, cifra a la derecha y barra debajo."""
    caja = transparente(QWidget())
    rejilla = QGridLayout(caja)
    rejilla.setContentsMargins(0, 0, 0, 0)
    rejilla.setHorizontalSpacing(px(28, False))
    rejilla.setVerticalSpacing(px(8, False))
    por_columna = math.ceil(len(filas) / max(1, columnas))
    for i, (nombre, valor, parte) in enumerate(filas):
        col, fila_n = divmod(i, por_columna) if columnas > 1 else (0, i)
        celda = transparente(QWidget())
        capa = QVBoxLayout(celda)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(px(3, False))
        capa.addLayout(fila(etiqueta(nombre, "normal", tinta="suave"), None, etiqueta(valor, "dato"), espacio=6))
        barra = BarraFina(parte or 0.0, tinta="acento_tenue" if parte is None else "acento", alto=3)
        if parte is None:
            barra.hide()
        capa.addWidget(barra)
        rejilla.addWidget(celda, fila_n, col)
    for c in range(columnas):
        rejilla.setColumnStretch(c, 1)
    return caja


__all__ = [
    "ANCHO_DOS_COLUMNAS", "BarraDano", "BloqueHtml", "FichaC", "InsigniaGlosa", "TiraRondas", "estadisticas",
    "etiqueta", "filas_datos", "hitos",
]
