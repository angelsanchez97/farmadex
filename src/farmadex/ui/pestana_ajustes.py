"""Pestana Ajustes: secciones en vertical a la izquierda, como el menu de opciones del juego.

General (idioma, arranque, version), Atajos, Apariencia (tema, tamanos y colores con
vista previa), Reliquias (lecturas de pantalla y diagnostico), Datos del juego
(con el mantenimiento plegado en "Avanzado") y Ayuda (bienvenida, guia, Acerca de).

Estilo C (maqueta C_ajustes.png): la columna de secciones es un panel con esquinas
cortadas, con "Acerca de", "Salir" y los creditos al pie; cada grupo de opciones es un
panel con su rotulo. En Apariencia los temas son tarjetas con sus colores, los tamanos
una fila de botones y los colores unas muestras con su flecha para volver al del tema.

Cada opcion rara lleva debajo una linea que dice que hace y que pasa al usarla:
lo pidio un tester, con razon, porque un boton que nadie entiende no lo usa nadie.
"""

from __future__ import annotations

import html
import os
import subprocess
import sqlite3
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import NOMBRE_APP, VERSION, idiomas
from ..captura import ocr
from ..captura import prioridad as prio
from ..config import DIR_BASE, cargar, guardar
from ..datos import eficiencia, indice
from ..hotkeys import parsear
from ..idiomas import t
from . import widgets
from .acerca_de import abrir_acerca_de, enlace_discord, frase, texto_autor, texto_discord_corto
from .estilo_c import (
    TITULAR,
    BotonC,
    BotonGlifo,
    EtiquetaC,
    Filete,
    Linea,
    PanelC,
    PiezaC,
    Rombo,
    color,
    fila,
    fuente,
    fuente_iconos,
    px,
    ruta_chaflan,
    transparente,
)
from .widgets import (
    CATEGORIAS_COLOR,
    ESCALAS_INTERFAZ,
    ESCALAS_LETRA,
    PALETA,
    TEMA_POR_DEFECTO,
    TEMAS,
    aspecto_guardado,
    hoja_estilos,
    paleta_de,
)

# Secciones de la columna izquierda: (clave, titulo). El orden es el de la columna.
SECCIONES = (
    ("general", "General"),
    ("atajos", "Atajos"),
    ("aspecto", "Apariencia"),
    ("reliquias", "Reliquias"),
    ("datos", "Datos del juego"),
    ("ayuda", "Ayuda"),
)
# Glifo (Segoe Fluent/MDL2) de cada seccion: ajustes, mando, sol, reliquia, reloj, info.
GLIFOS_SECCION = {
    "general": "", "atajos": "", "aspecto": "",
    "reliquias": "", "datos": "", "ayuda": "",
}
GLIFO_DESHACER = ""
# Colores de cada tarjeta de tema, de izquierda a derecha.
MUESTRAS_TEMA = ("fondo", "panel2", "acento", "texto")
# Modos del lector de pantalla (captura/ocr.py): (clave en config, texto).
MODOS_OCR = (
    ("auto", "Automático (recomendado)"),
    ("rapido", "Rápido (usa más procesador)"),
    ("ligero", "Ligero (usa menos procesador)"),
    ("windows", "OCR de Windows"),
)


def _texto_sobre(color_hex: str) -> str:
    """Negro o blanco, lo que mas se lea encima de `color_hex` (para las muestras)."""
    c = QColor(color_hex)
    luz = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return "#101010" if luz > 140 else "#f4f4f4"


def _rombo(cx: float, cy: float, medio: float) -> QPolygonF:
    return QPolygonF([QPointF(cx, cy - medio), QPointF(cx + medio, cy), QPointF(cx, cy + medio),
                      QPointF(cx - medio, cy)])


# -- piezas propias de Ajustes ---------------------------------------------------------------


class _EntradaSeccion(QAbstractButton, PiezaC):
    """Una seccion de la columna: glifo y nombre en mayusculas; la activa con fondo tenue,
    barra de acento a la izquierda y letra de acento."""

    def __init__(self, glifo: str, parent=None):
        super().__init__(parent)
        transparente(self)
        self.glifo = glifo
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _fuente(self) -> QFont:
        f = fuente("dato", 13, 600)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        return f

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self._fuente())
        ancho = px(10, False) + px(22, False) + px(10, False) + fm.horizontalAdvance(self.text().upper()) + px(10, False)
        return QSize(ancho, fm.height() + px(16, False))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        activa = self.isChecked()
        if activa:
            fondo = QColor(color("acento"))
            fondo.setAlpha(30)
            p.fillRect(self.rect(), fondo)
            p.fillRect(0, 0, px(3, False), self.height(), color("acento"))
        tinta = color("acento") if activa else color("texto" if self.underMouse() else "suave")
        x = px(10, False)
        p.setFont(fuente_iconos(15))
        p.setPen(tinta)
        p.drawText(QRectF(x, 0, px(22, False), self.height()), Qt.AlignCenter, self.glifo)
        x += px(22, False) + px(10, False)
        p.setFont(self._fuente())
        p.drawText(QRectF(x, 0, self.width() - x, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text().upper())
        p.end()

    def enterEvent(self, evento):  # noqa: N802
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.update()
        super().leaveEvent(evento)


class MenuSecciones(QWidget):
    """La columna de secciones. Imita lo que se usaba de QListWidget: `count()`,
    `item(i).text()`, `setCurrentRow()`, `currentRow()` y `currentRowChanged(int)`."""

    currentRowChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._entradas: list[_EntradaSeccion] = []
        self._actual = -1
        self._capa = QVBoxLayout(self)
        self._capa.setContentsMargins(0, 0, 0, 0)
        self._capa.setSpacing(px(2, False))

    def anadir(self, glifo: str) -> _EntradaSeccion:
        entrada = _EntradaSeccion(glifo)
        indice_entrada = len(self._entradas)
        entrada.clicked.connect(lambda _=False, i=indice_entrada: self.setCurrentRow(i))
        self._grupo.addButton(entrada)
        self._entradas.append(entrada)
        self._capa.addWidget(entrada)
        return entrada

    def count(self) -> int:
        return len(self._entradas)

    def item(self, i: int) -> _EntradaSeccion:
        return self._entradas[i]

    def currentRow(self) -> int:  # noqa: N802 - nombre de QListWidget
        return self._actual

    def setCurrentRow(self, i: int) -> None:  # noqa: N802
        if not 0 <= i < len(self._entradas):
            return
        self._entradas[i].setChecked(True)
        if i != self._actual:
            self._actual = i
            self.currentRowChanged.emit(i)

    def ancho_necesario(self) -> int:
        return max((e.sizeHint().width() for e in self._entradas), default=px(150, False))


class _OpcionTamano(BotonC):
    """Un tamano (NORMAL, GRANDE...): boton C marcable, lleno cuando es el elegido."""

    def __init__(self, texto: str, parent=None):
        super().__init__(texto, tam=10, parent=parent)
        self.setCheckable(True)


class TarjetaTema(QAbstractButton, PiezaC):
    """Un tema: sus cuatro colores principales y su nombre, pintados con SUS colores (no
    con los del tema activo), para ver como queda antes de elegirlo."""

    def __init__(self, clave: str, texto: str, parent=None):
        super().__init__(parent)
        transparente(self)
        self.clave = clave
        self.setText(texto)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _tema(self) -> dict:
        return TEMAS.get(self.clave) or TEMAS[TEMA_POR_DEFECTO]

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(fuente("fuerte", 12))
        return QSize(max(px(120, False), fm.horizontalAdvance(self.text()) + px(28, False)),
                     px(16, False) + px(12, False) + fm.height() + px(18, False))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(px(110, False), self.sizeHint().height())

    def paintEvent(self, _evento):  # noqa: N802
        tema = self._tema()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        corte = px(10, False)
        camino = ruta_chaflan(r, corte)
        p.fillPath(camino, QColor(tema["panel"]))
        elegido = self.isChecked()
        borde = QColor(tema["acento"] if elegido else PALETA["borde"])
        if self.underMouse() and not elegido:
            borde = QColor(PALETA["acento_tenue"])
        p.setPen(QPen(borde, 1.5 if elegido else 1))
        p.drawPath(camino)
        if elegido:
            p.setPen(QPen(QColor(tema["acento"]), 2))
            largo = min(40.0, r.width() / 3)
            p.drawLine(QPointF(r.right() - corte - largo, r.bottom() - 1), QPointF(r.right() - corte, r.bottom() - 1))
        lado = px(14, False)
        x, y = px(12, False), px(10, False)
        for clave in MUESTRAS_TEMA:
            cuadro = QRectF(x, y, lado, lado)
            p.fillPath(ruta_chaflan(cuadro, 3, "i"), QColor(tema[clave]))
            p.setPen(QPen(QColor(tema["borde"]), 1))
            p.drawPath(ruta_chaflan(cuadro, 3, "i"))
            x += lado + px(5, False)
        p.setFont(fuente("fuerte", 12))
        p.setPen(QColor(tema["texto"]))
        arriba = y + lado + px(6, False)
        p.drawText(QRectF(px(12, False), arriba, r.width() - px(20, False), r.height() - arriba - px(4, False)),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(p.font()).elidedText(self.text(), Qt.ElideRight, int(r.width() - px(20, False))))
        p.end()

    def enterEvent(self, evento):  # noqa: N802
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.update()
        super().leaveEvent(evento)


class SelectorC(QWidget, PiezaC):
    """Opciones exclusivas a la vista (una fila de botones o de tarjetas) con la API de un
    QComboBox: addItem, count, itemText, setItemText, itemData, findData, currentIndex,
    setCurrentIndex, currentData, currentText y la senal currentIndexChanged(int)."""

    currentIndexChanged = Signal(int)

    def __init__(self, fabrica: Callable[[str, object], QAbstractButton], columnas: int = 0, parent=None):
        super().__init__(parent)
        transparente(self)
        self._fabrica = fabrica
        self._columnas = columnas  # 0 = todos en una fila
        self._botones: list[QAbstractButton] = []
        self._datos: list[object] = []
        self._indice = -1
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._capa = QGridLayout(self)
        self._capa.setContentsMargins(0, 0, 0, 0)
        self._capa.setHorizontalSpacing(px(8, False))
        self._capa.setVerticalSpacing(px(8, False))

    def addItem(self, texto: str, dato=None) -> None:  # noqa: N802 - nombre de QComboBox
        boton = self._fabrica(texto, dato)
        i = len(self._botones)
        boton.clicked.connect(lambda _=False, i=i: self.setCurrentIndex(i))
        self._grupo.addButton(boton)
        self._botones.append(boton)
        self._datos.append(dato)
        self._recolocar(self._columnas)
        if self._indice < 0:
            self.setCurrentIndex(0)

    def _recolocar(self, columnas: int) -> None:
        for boton in self._botones:
            self._capa.removeWidget(boton)
        por_fila = columnas or len(self._botones) or 1
        for i, boton in enumerate(self._botones):
            self._capa.addWidget(boton, i // por_fila, i % por_fila)

    def poner_columnas(self, columnas: int) -> None:
        if columnas != self._columnas:
            self._columnas = columnas
            self._recolocar(columnas)

    def boton(self, i: int) -> QAbstractButton:
        return self._botones[i]

    def count(self) -> int:
        return len(self._botones)

    def itemText(self, i: int) -> str:  # noqa: N802
        return self._botones[i].text() if 0 <= i < len(self._botones) else ""

    def setItemText(self, i: int, texto: str) -> None:  # noqa: N802
        if 0 <= i < len(self._botones):
            self._botones[i].setText(texto)
            self._botones[i].updateGeometry()
            self._botones[i].update()

    def itemData(self, i: int):  # noqa: N802
        return self._datos[i] if 0 <= i < len(self._datos) else None

    def findData(self, dato) -> int:  # noqa: N802
        for i, d in enumerate(self._datos):
            if d == dato or (isinstance(d, float) and isinstance(dato, (int, float)) and abs(d - dato) < 1e-6):
                return i
        return -1

    def currentIndex(self) -> int:  # noqa: N802
        return self._indice

    def currentData(self):  # noqa: N802
        return self.itemData(self._indice)

    def currentText(self) -> str:  # noqa: N802
        return self.itemText(self._indice)

    def setCurrentIndex(self, i: int) -> None:  # noqa: N802
        if not 0 <= i < len(self._botones):
            return
        self._botones[i].setChecked(True)
        if i != self._indice:
            self._indice = i
            self.currentIndexChanged.emit(i)

    def refrescar_estilo(self) -> None:
        self._capa.setHorizontalSpacing(px(8, False))
        self._capa.setVerticalSpacing(px(8, False))


class DeslizadorC(QSlider, PiezaC):
    """QSlider horizontal pintado en estilo C: raya fina, tramo de acento y un rombo."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        transparente(self)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(px(22, False))

    def refrescar_estilo(self) -> None:
        self.setFixedHeight(px(22, False))
        self.update()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        medio = self.height() / 2
        lado = px(8, False)
        ancho = self.width() - 2 * lado
        tramo = self.maximum() - self.minimum() or 1
        fraccion = (self.value() - self.minimum()) / tramo
        p.fillRect(QRectF(lado, medio - 1, ancho, 2), color("borde"))
        p.fillRect(QRectF(lado, medio - 1, ancho * fraccion, 2), color("acento"))
        x = lado + ancho * fraccion
        p.setBrush(color("acento"))
        p.setPen(QPen(color("fondo"), 2))
        p.drawPolygon(_rombo(x, medio, lado))
        p.end()


class MuestraColor(QPushButton, PiezaC):
    """Cuadrado del color con la esquina cortada. `text()` es el color ("#rrggbb"), que
    no se pinta (va en el tooltip); `personal` = cambiado por el usuario (filete de acento)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.personal = False
        self.setCursor(Qt.PointingHandCursor)
        self.refrescar_estilo()

    def refrescar_estilo(self) -> None:
        self.setFixedSize(px(22, False), px(22, False))
        self.update()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        camino = ruta_chaflan(r, px(5, False))
        p.fillPath(camino, QColor(self.text() or "#000000"))
        marcado = self.personal or self.underMouse()
        p.setPen(QPen(color("acento" if marcado else "borde"), 2 if self.personal else 1))
        p.drawPath(camino)
        p.end()

    def enterEvent(self, evento):  # noqa: N802
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.update()
        super().leaveEvent(evento)


class _EnlaceC(QPushButton):
    """Boton que parece un enlace (Acerca de, Salir): texto en color, sin recuadro."""

    def __init__(self, tinta: str = "acento", parent=None):
        super().__init__(parent)
        self.tinta = tinta
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)

    def hoja(self) -> str:
        return (
            f"QPushButton {{ background: transparent; border: none; color: {PALETA[self.tinta]};"
            f" font-family: '{TITULAR}'; font-weight: 600; font-size: {px(13)}px; text-align: left;"
            f" padding: {px(2, False)}px 0; }}"
            f" QPushButton:hover {{ text-decoration: underline; }}"
        )


# -- vista previa ----------------------------------------------------------------------------


def _pintar_con_paleta(widget: QWidget, pintar) -> None:
    """Pinta una pieza C con la paleta de la vista previa (lo pendiente, sin aplicar): las
    piezas leen `widgets.PALETA` al pintarse, asi que se cambia solo mientras se pinta."""
    vista = widget.parentWidget()
    while vista is not None and not isinstance(vista, VistaPrevia):
        vista = vista.parentWidget()
    paleta = getattr(vista, "paleta", None)
    guardada = widgets.PALETA
    if paleta:
        widgets.PALETA = paleta
    try:
        pintar()
    finally:
        widgets.PALETA = guardada


class _PanelPrevia(PanelC):
    def paintEvent(self, evento):  # noqa: N802
        _pintar_con_paleta(self, lambda: PanelC.paintEvent(self, evento))


class _BotonPrevia(BotonC):
    def paintEvent(self, evento):  # noqa: N802
        _pintar_con_paleta(self, lambda: BotonC.paintEvent(self, evento))


class _RomboPrevia(Rombo):
    def paintEvent(self, evento):  # noqa: N802
        _pintar_con_paleta(self, lambda: Rombo.paintEvent(self, evento))


class _FiletePrevia(Filete):
    def paintEvent(self, evento):  # noqa: N802
        _pintar_con_paleta(self, lambda: Filete.paintEvent(self, evento))


def _columna_junta(*piezas) -> QVBoxLayout:
    capa = QVBoxLayout()
    capa.setContentsMargins(0, 0, 0, 0)
    capa.setSpacing(0)
    for w in piezas:
        capa.addWidget(w)
    return capa


class VistaPrevia(QFrame):
    """Un trocito de Farmadex pintado con el aspecto que se esta eligiendo, sin aplicarlo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.setObjectName("vistaPrevia")
        self.setMinimumWidth(px(250, False))
        self.paleta: dict | None = None
        self.marco = _PanelPrevia(fondo="fondo", borde="acento_tenue")
        self.cabecera = EtiquetaC("FARMADEX", "seccion", tinta="acento", mayus=True)
        self.menu = [EtiquetaC("", "rotulo", mayus=True) for _ in range(3)]
        self.caja = QLineEdit()
        self.caja.setReadOnly(True)
        self.caja.setFocusPolicy(Qt.NoFocus)
        self.tarjeta = _PanelPrevia(remate=False, fondo="panel2", borde="borde")
        self.nombre = EtiquetaC("", "fuerte")
        self.detalle = EtiquetaC("", "pequeno", envolver=True)
        self.ok = EtiquetaC("", "fuerte")
        self.aviso = EtiquetaC("", "fuerte", envolver=True)
        self.boton = _BotonPrevia(tam=10)
        self.principal = _BotonPrevia(principal=True, icono="mas", tam=10)
        for boton in (self.boton, self.principal):
            boton.setFocusPolicy(Qt.NoFocus)

        self.tarjeta.capa.setContentsMargins(px(10, False), px(6, False), px(10, False), px(6, False))
        self.tarjeta.capa.setSpacing(px(2, False))
        self.tarjeta.capa.addLayout(fila(_RomboPrevia(14, "secundario", relleno=False),
                                         _columna_junta(self.nombre, self.detalle), espacio=px(8, False)))
        m = self.marco.capa
        m.setSpacing(px(6, False))
        m.addLayout(fila(_RomboPrevia(10, "acento", relleno=False), self.cabecera, None, espacio=px(6, False)))
        m.addWidget(_FiletePrevia())
        m.addLayout(fila(*self.menu, None, espacio=px(14, False)))
        m.addWidget(self.caja)
        m.addWidget(self.tarjeta)
        m.addLayout(fila(self.principal, self.boton, None, espacio=px(6, False)))
        m.addWidget(self.aviso)
        m.addWidget(self.ok)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(self.marco)
        self.retraducir()

    def retraducir(self) -> None:
        for etiqueta, titulo in zip(self.menu, ("Buscar", "Objetivos", "Mundo")):
            etiqueta.setText(t(titulo))
        self.caja.setPlaceholderText(t("Busca un objeto, misión o reliquia..."))
        self.nombre.setText("Ash Prime")
        self.detalle.setText(t("Texto secundario: dónde se consigue y cuánto se tarda."))
        self.ok.setText(t("Disponible ahora"))
        self.aviso.setText(t("Aviso: los datos van por detrás del juego."))
        self.boton.setText(t("Botón"))
        self.principal.setText(t("Botón principal"))

    def pintar(self, paleta: dict, escala: tuple[float, float]) -> None:
        p = paleta
        self.paleta = dict(paleta)
        # La hoja entera con la paleta pendiente: las etiquetas C (rolC/tinta) la siguen.
        self.setStyleSheet(hoja_estilos(p, escala) + " #vistaPrevia { background: transparent; }")
        self.menu[0].setStyleSheet(f"color: {p['acento']};")
        for etiqueta in self.menu[1:]:
            etiqueta.setStyleSheet(f"color: {p['suave']};")
        self.ok.setStyleSheet(f"color: {p['ok']}; font-size: {widgets.px(13, True, escala)}px;")
        self.aviso.setStyleSheet(f"color: {p['aviso']}; font-size: {widgets.px(13, True, escala)}px;")
        # Alto minimo segun la letra elegida: si no, con letra grande el hueco de la vista
        # previa aplasta las lineas unas encima de otras. (etiqueta, tamano, lineas)
        for etiqueta, tamano, lineas in ((self.nombre, 14, 1), (self.detalle, 12, 2), (self.ok, 13, 1),
                                         (self.aviso, 13, 2), (self.cabecera, 16, 1)):
            etiqueta.setMinimumHeight(int(widgets.px(tamano, True, escala) * 1.45 * lineas))
        for w in self.findChildren(QWidget):
            w.update()


# -- la pestana ----------------------------------------------------------------------------


class PestanaAjustes(QWidget):
    reconstruir = Signal()
    salir = Signal()
    hotkeys_cambiadas = Signal(dict)
    opacidad_cambiada = Signal(float)
    tema_cambiado = Signal(str)
    idioma_cambiado = Signal(str)
    # La disposicion de Mundo se cambia ahora en la propia pestana Mundo; la senal se
    # conserva para quien siga conectado a ella.
    diseno_mundo_cambiado = Signal(str)
    ritmo_cambiado = Signal(str)
    comprobar_version = Signal()
    instalar_version = Signal(object)
    # Diagnostico de reliquias: la ventana es quien sabe como va todo; aqui solo se pide.
    pedir_diagnostico = Signal()
    guardar_informe = Signal()
    # Borra el perfil de WebView2 del reproductor de guias (sesion de YouTube, cache).
    borrar_reproductor = Signal()
    # Se guardo un aspecto nuevo (tamanos o colores): la ventana vuelve a aplicar el tema.
    apariencia_cambiada = Signal()
    # Ajustes > Ayuda: la bienvenida y la guia viven en la ventana, no aqui.
    ver_bienvenida = Signal()
    ver_guia = Signal()
    estilo_recompensas_cambiado = Signal(str)
    prioridad_recompensas_cambiada = Signal(str)
    ocr_modo_cambiado = Signal(str)  # "auto", "rapido", "ligero" o "windows" (captura/ocr.py)

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.config = cargar()
        # Textos fijos que hay que volver a escribir al cambiar de idioma:
        # (funcion que pone el texto, clave en castellano).
        self._fijos: list[tuple[Callable[[str], None], str]] = []
        self._notas: list[QLabel] = []
        # Hojas de estilo que dependen del tema o del tamano: se rehacen en repintar().
        self._estilos: list[tuple[QWidget, Callable[[], str]]] = []
        # Color de la linea de version ("suave" normal, "aviso" si hay version nueva).
        self._color_version = "suave"
        self._modo_pantalla: str | None = None
        self._texto_parche: str | None = None

        # -- columna de secciones (con Acerca de, Salir y creditos al pie) -----------------
        self.secciones = MenuSecciones()
        self.paginas = QStackedWidget()
        transparente(self.paginas)
        self._claves_seccion: list[str] = []
        self._contenido: dict[str, QVBoxLayout] = {}
        for clave, titulo in SECCIONES:
            entrada = self.secciones.anadir(GLIFOS_SECCION[clave])
            self._fijo(entrada.setText, titulo)
            self._claves_seccion.append(clave)
            self._contenido[clave] = self._pagina()
        self.secciones.currentRowChanged.connect(self.paginas.setCurrentIndex)

        self._construir_general()
        self._construir_atajos()
        self._construir_aspecto()
        self._construir_reliquias()
        self._construir_datos()
        self._construir_ayuda()
        for dentro in self._contenido.values():
            dentro.addStretch(1)
        self.secciones.setCurrentRow(0)

        # Que es Farmadex y que dice DE de los programas de terceros (ui/acerca_de.py).
        self.boton_acerca = _EnlaceC("acento")
        self._estilo(self.boton_acerca, self.boton_acerca.hoja)
        self._fijo(lambda s: self.boton_acerca.setText(s.format(app=NOMBRE_APP)), "Acerca de {app}")
        self.boton_acerca.clicked.connect(self._abrir_acerca)
        self.boton_salir = _EnlaceC("aviso")
        self._estilo(self.boton_salir, self.boton_salir.hoja)
        self._fijo(lambda s: self.boton_salir.setText(s.format(app=NOMBRE_APP)), "Salir de {app}")
        self.boton_salir.clicked.connect(self.salir.emit)
        creditos = self._nota("Datos de WFCD y Digital Extremes")
        creditos.poner_tinta("tenue")
        self.autor = EtiquetaC("", "pequeno", envolver=True)
        self.autor.setOpenExternalLinks(True)
        self.autor.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._fijo(lambda _s: self.autor.setText(texto_autor()), "Creado por {autor}")
        self.discord = EtiquetaC("", "pequeno", envolver=True)
        self.discord.setOpenExternalLinks(True)
        self.discord.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._fijo(lambda _s: self.discord.setText(texto_discord_corto()), "Dudas y sugerencias: {enlace}")
        self.version_pie = EtiquetaC(f"{NOMBRE_APP} {VERSION}", "pequeno", tinta="tenue")

        self.panel_secciones = PanelC()
        columna_menu = self.panel_secciones.capa
        columna_menu.setContentsMargins(px(12, False), px(16, False), px(12, False), px(14, False))
        columna_menu.setSpacing(px(4, False))
        columna_menu.addWidget(self.secciones)
        columna_menu.addStretch(1)
        columna_menu.addWidget(Linea())
        columna_menu.addWidget(self.boton_acerca)
        columna_menu.addWidget(self.boton_salir)
        columna_menu.addSpacing(px(4, False))
        columna_menu.addWidget(creditos)
        columna_menu.addWidget(self.autor)
        columna_menu.addWidget(self.discord)
        columna_menu.addWidget(self.version_pie)
        self._ajustar_ancho_secciones()

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(px(16, False))
        cuerpo.addWidget(self.panel_secciones)
        cuerpo.addWidget(self.paginas, 1)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, px(4, False), 0, 0)
        caja.addLayout(cuerpo, 1)

        self.refrescar_estado()

    # -- piezas ---------------------------------------------------------------------

    def _pagina(self) -> QVBoxLayout:
        contenido = transparente(QWidget())
        dentro = QVBoxLayout(contenido)
        dentro.setContentsMargins(0, 0, px(8, False), 0)
        dentro.setSpacing(px(12, False))
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QScrollArea.NoFrame)
        desplazable.setWidget(contenido)
        self.paginas.addWidget(desplazable)
        return dentro

    def _ajustar_ancho_secciones(self) -> None:
        """Tan ancha como el titulo mas largo en el idioma activo, sin cortar ni sobrar."""
        if not hasattr(self, "panel_secciones"):
            return
        margenes = self.panel_secciones.capa.contentsMargins()
        ancho = self.secciones.ancho_necesario() + margenes.left() + margenes.right() + px(6, False)
        self.panel_secciones.setFixedWidth(max(px(200, False), ancho))

    def _estilo(self, widget: QWidget, hoja: Callable[[], str]) -> None:
        widget.setStyleSheet(hoja())
        self._estilos.append((widget, hoja))

    def _fijo(self, poner: Callable[[str], None], clave: str) -> None:
        poner(t(clave))
        self._fijos.append((poner, clave))

    def _boton(self, clave: str, principal: bool = False) -> BotonC:
        boton = BotonC(principal=principal, tam=11)
        self._fijo(boton.setText, clave)
        return boton

    def _grupo(self, clave: str) -> PanelC:
        grupo = PanelC("")
        self._fijo(grupo.poner_titulo, clave)
        return grupo

    def _nota(self, clave: str) -> EtiquetaC:
        nota = EtiquetaC("", "pequeno", envolver=True)
        self._fijo(nota.setText, clave)
        self._notas.append(nota)
        return nota

    def _fila(self, formulario: QFormLayout, clave: str, campo: QWidget) -> None:
        etiqueta = EtiquetaC("", "normal")
        self._fijo(etiqueta.setText, clave)
        formulario.addRow(etiqueta, campo)

    @staticmethod
    def _formulario() -> QFormLayout:
        formulario = QFormLayout()
        formulario.setHorizontalSpacing(px(16, False))
        formulario.setVerticalSpacing(px(6, False))
        formulario.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        formulario.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return formulario

    def _meter(self, seccion: str, grupo: PanelC, disposicion) -> PanelC:
        grupo.capa.addLayout(disposicion)
        self._contenido[seccion].addWidget(grupo)
        return grupo

    # -- secciones --------------------------------------------------------------------

    def _construir_general(self) -> None:
        # Los nombres de los idiomas van cada uno en su idioma, no se traducen.
        self.idioma = QComboBox()
        self.idioma.addItem(t("Automático (el de Windows)"), idiomas.AUTOMATICO)
        for codigo, nombre in idiomas.IDIOMAS.items():
            self.idioma.addItem(nombre, codigo)
        guardado = self.config.get("idioma_ui") or idiomas.AUTOMATICO
        self.idioma.setCurrentIndex(max(0, self.idioma.findData(guardado)))
        self.idioma.currentIndexChanged.connect(self._cambiar_idioma)
        self.iniciar_windows = QCheckBox()
        self._fijo(self.iniciar_windows.setText, "Iniciar con Windows (escondido en la bandeja)")
        self.iniciar_windows.setChecked(bool(self.config.get("iniciar_con_windows", False)))
        self.iniciar_windows.toggled.connect(self._cambiar_arranque)
        self.aviso_arranque = EtiquetaC("", "pequeno", envolver=True)
        self._pintar_aviso_arranque()

        general = self._formulario()
        self._fila(general, "Idioma", self.idioma)
        general.addRow(self._nota("El menú de la bandeja cambia de idioma al reiniciar Farmadex."))
        general.addRow(self.iniciar_windows)
        general.addRow(self._nota(
            "Farmadex se abre solo al encender el PC, sin ventana, listo para el atajo."
        ))
        general.addRow(self.aviso_arranque)
        self._meter("general", self._grupo("General"), general)

        # -- version ----------------------------------------------------------------
        self.etiqueta_version = EtiquetaC(f"{NOMBRE_APP} <b>{VERSION}</b>", "seccion")
        self.aviso_version = QLabel(t("Estás en la última versión"))
        self.aviso_version.setWordWrap(True)
        self.aviso_version.setOpenExternalLinks(True)
        self.aviso_version.setStyleSheet(f"color: {PALETA['suave']};")
        self.boton_comprobar = self._boton("Comprobar ahora")
        self.boton_comprobar.clicked.connect(self._pedir_comprobacion)
        self.boton_instalar = self._boton("Instalar la versión nueva", principal=True)
        self.boton_instalar.setVisible(False)
        # Para la actualizacion ya descargada y comprobada por la propia app.
        self.boton_reiniciar = self._boton("Reiniciar y actualizar", principal=True)
        self.boton_reiniciar.setVisible(False)
        self.auto_actualizar = QCheckBox()
        self._fijo(self.auto_actualizar.setText, "Actualizar automáticamente (se instala al cerrar Farmadex)")
        self.auto_actualizar.setChecked(bool(self.config.get("actualizar_automaticamente", True)))
        self.auto_actualizar.toggled.connect(lambda v: self._guardar("actualizar_automaticamente", v))
        version = QVBoxLayout()
        version.setSpacing(px(6, False))
        version.addWidget(self.etiqueta_version)
        version.addWidget(self.aviso_version)
        version.addWidget(self.auto_actualizar)
        version.addWidget(self._nota(
            "La versión nueva se baja sola, se comprueba y se instala al cerrar Farmadex, "
            "sustituyendo a la anterior. Tus objetivos y ajustes se conservan."
        ))
        version.addLayout(fila(self.boton_comprobar, self.boton_instalar, self.boton_reiniciar, None,
                               espacio=px(8, False)))
        self._meter("general", self._grupo("Versión"), version)

    def _construir_atajos(self) -> None:
        self.campos_hotkey = {
            "overlay": QLineEdit(self.config["hotkey_overlay"]),
            "cursor": QLineEdit(self.config["hotkey_cursor"]),
            "reliquias": QLineEdit(self.config["hotkey_reliquias"]),
            "build": QLineEdit(self.config.get("hotkey_build", "")),
            "agrietado": QLineEdit(self.config.get("hotkey_agrietado", "")),
        }
        for campo in self.campos_hotkey.values():
            campo.setMaximumWidth(px(260, False))
        formulario = self._formulario()
        self._fila(formulario, "Abrir y cerrar el overlay", self.campos_hotkey["overlay"])
        formulario.addRow(self._nota("Abre y cierra esta ventana encima del juego."))
        self._fila(formulario, "Leer el objeto bajo el cursor", self.campos_hotkey["cursor"])
        formulario.addRow(self._nota(
            "Es un atajo de teclado: en el juego, pon el ratón encima del nombre de un objeto "
            "(inventario, mercado, chat...) y púlsalo. Farmadex lee el texto de alrededor y abre su "
            "ficha; si duda entre varios, te deja elegir. Hace una sola lectura a la vez: si lo "
            "pulsas varias veces seguidas, las de más se ignoran."
        ))
        self._fila(formulario, "Leer las recompensas de reliquia", self.campos_hotkey["reliquias"])
        formulario.addRow(self._nota(
            "Por si la lectura automática no salta: con la pantalla de recompensas delante, las lee "
            "a mano."
        ))
        self._fila(formulario, "Leer la pantalla de mejoras (Build)", self.campos_hotkey["build"])
        self._fila(formulario, "Leer la tarjeta de un agrietado", self.campos_hotkey["agrietado"])
        self.aviso_hotkey = QLabel("")
        self.aviso_hotkey.setWordWrap(True)
        self.aviso_hotkey.setStyleSheet(f"color: {PALETA['aviso']};")
        boton_hotkeys = self._boton("Aplicar atajos", principal=True)
        boton_hotkeys.clicked.connect(self._aplicar_hotkeys)
        formulario.addRow(self._nota("Escríbelos así: Ctrl+Alt+W. Los cambios valen al pulsar Aplicar."))
        fila_hotkeys = fila(boton_hotkeys, espacio=px(10, False))
        fila_hotkeys.addWidget(self.aviso_hotkey, 1)
        formulario.addRow(fila_hotkeys)
        self._meter("atajos", self._grupo("Atajos de teclado"), formulario)

    def _construir_aspecto(self) -> None:
        # -- tema y opacidad ----------------------------------------------------------------
        self.tema = SelectorC(lambda texto, clave: TarjetaTema(clave, texto))
        for clave, tema in TEMAS.items():
            self.tema.addItem(t(tema["titulo"]), clave)
        actual = self.config.get("tema") or TEMA_POR_DEFECTO
        self.tema.setCurrentIndex(max(0, self.tema.findData(actual)))
        self.tema.currentIndexChanged.connect(self._cambiar_tema)
        self.opacidad = DeslizadorC()
        self.opacidad.setRange(50, 100)
        self.opacidad.setValue(int(float(self.config["overlay_opacidad"]) * 100))
        self.opacidad.setMinimumWidth(px(200, False))
        self.opacidad.setMaximumWidth(px(280, False))
        self.valor_opacidad = EtiquetaC("", "dato", tinta="acento")
        self.valor_opacidad.setMinimumWidth(px(44, False))
        self.valor_opacidad.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.opacidad.valueChanged.connect(self._cambiar_opacidad)
        self._pintar_opacidad()
        etiqueta_opacidad = EtiquetaC("", "normal")
        self._fijo(etiqueta_opacidad.setText, "Opacidad del fondo")
        tema = QVBoxLayout()
        tema.setSpacing(px(10, False))
        tema.addWidget(self.tema)
        tema.addLayout(fila(etiqueta_opacidad, None, self.opacidad, self.valor_opacidad, espacio=px(10, False)))
        tema.addWidget(self._nota("El tema y la opacidad se aplican al momento."))
        self.panel_tema = self._grupo("Tema")
        self.panel_tema.capa.addLayout(tema)

        # -- tamanos --------------------------------------------------------------------------
        self.escala_interfaz = SelectorC(lambda texto, _f: _OpcionTamano(texto))
        for factor, nombre in ESCALAS_INTERFAZ:
            self.escala_interfaz.addItem(t(nombre), factor)
        self.escala_letra = SelectorC(lambda texto, _f: _OpcionTamano(texto))
        for factor, nombre in ESCALAS_LETRA:
            self.escala_letra.addItem(t(nombre), factor)
        self.escala_interfaz.currentIndexChanged.connect(self._cambio_pendiente)
        self.escala_letra.currentIndexChanged.connect(self._cambio_pendiente)
        tamanos = QGridLayout()
        tamanos.setHorizontalSpacing(px(16, False))
        tamanos.setVerticalSpacing(px(10, False))
        for i, (clave, selector) in enumerate((("Tamaño de la interfaz", self.escala_interfaz),
                                               ("Tamaño de letra", self.escala_letra))):
            etiqueta = EtiquetaC("", "normal")
            self._fijo(etiqueta.setText, clave)
            tamanos.addWidget(etiqueta, i, 0)
            tamanos.addWidget(selector, i, 1, Qt.AlignLeft)
        tamanos.setColumnStretch(1, 1)
        self.panel_tamano = self._grupo("Tamaño")
        self.panel_tamano.capa.addLayout(tamanos)

        # -- colores: una muestra por categoria; clic = elegir, la flecha vuelve al del tema -----
        self.muestras: dict[str, MuestraColor] = {}
        self.deshacer_color: dict[str, BotonGlifo] = {}
        columnas = QHBoxLayout()
        columnas.setSpacing(px(24, False))
        mitad = (len(CATEGORIAS_COLOR) + 1) // 2
        for trozo in (CATEGORIAS_COLOR[:mitad], CATEGORIAS_COLOR[mitad:]):
            col = QVBoxLayout()
            col.setSpacing(px(5, False))
            for clave, nombre, ayuda in trozo:
                muestra = MuestraColor()
                self._fijo(muestra.setToolTip, ayuda)
                muestra.clicked.connect(lambda _=False, c=clave: self._elegir_color(c))
                etiqueta = EtiquetaC("", "normal")
                self._fijo(etiqueta.setText, nombre)
                self._fijo(etiqueta.setToolTip, ayuda)
                deshacer = BotonGlifo(GLIFO_DESHACER, tinta="acento", tam=12)
                self._fijo(deshacer.setToolTip, "Volver al color del tema")
                deshacer.clicked.connect(lambda _=False, c=clave: self._poner_color(c, None))
                self.muestras[clave] = muestra
                self.deshacer_color[clave] = deshacer
                col.addLayout(fila(muestra, etiqueta, None, deshacer, espacio=px(10, False)))
            col.addStretch(1)
            columnas.addLayout(col, 1)
        self.boton_fabrica = self._boton("Volver a lo de fábrica")
        self._fijo(self.boton_fabrica.setToolTip, "Quita todos los colores y tamaños personalizados, en todos los temas")
        self.boton_fabrica.clicked.connect(self.aspecto_de_fabrica)
        nota_colores = self._nota(
            "Colores del tema elegido, por partes. Pulsa un color para cambiarlo; la flecha lo deja "
            "como venía."
        )
        self.panel_colores = self._grupo("Colores")
        self.panel_colores.capa.addLayout(columnas)
        pie_colores = fila(espacio=px(10, False))
        pie_colores.addWidget(nota_colores, 1)
        pie_colores.addWidget(self.boton_fabrica, 0, Qt.AlignBottom)
        self.panel_colores.capa.addLayout(pie_colores)

        # -- vista previa con Guardar y Descartar ----------------------------------------------
        self.vista_previa = VistaPrevia()
        self.estado_aspecto = EtiquetaC("", "pequeno", envolver=True)
        self.boton_guardar_aspecto = self._boton("Guardar", principal=True)
        self.boton_guardar_aspecto.clicked.connect(self.guardar_aspecto)
        self.boton_descartar_aspecto = self._boton("Descartar")
        self.boton_descartar_aspecto.clicked.connect(self.descartar_aspecto)
        self.panel_previa = self._grupo("Vista previa")
        self.panel_previa.capa.addWidget(self.vista_previa)
        self.panel_previa.capa.addWidget(self.estado_aspecto)
        # Guardar y Descartar debajo de la vista previa, a la vista sin bajar la pagina.
        self.panel_previa.capa.addLayout(fila(self.boton_guardar_aspecto, self.boton_descartar_aspecto, None,
                                              espacio=px(8, False)))
        self.panel_previa.capa.addWidget(self._nota(
            "Nada cambia hasta que pulsas Guardar. Se guarda en tu configuración, así que se "
            "mantiene al actualizar Farmadex."
        ))

        izquierda = QVBoxLayout()
        izquierda.setSpacing(px(12, False))
        izquierda.addWidget(self.panel_tema)
        izquierda.addWidget(self.panel_tamano)
        izquierda.addWidget(self.panel_colores)
        derecha = QVBoxLayout()
        derecha.addWidget(self.panel_previa)
        derecha.addStretch(1)
        # Lado a lado si cabe; con letra grande o ventana estrecha, la vista previa baja
        # debajo de los colores (ver _ajustar_disposicion) en vez de salirse por la derecha.
        arriba = QBoxLayout(QBoxLayout.LeftToRight)
        arriba.setSpacing(px(16, False))
        arriba.addLayout(izquierda, 3)
        arriba.addLayout(derecha, 2)
        self._arriba_aspecto, self._izquierda_aspecto = arriba, izquierda
        self._contenido["aspecto"].addLayout(arriba)
        self._fabrica_todos = False
        self._cargar_aspecto()

    def _construir_reliquias(self) -> None:
        self.estilo_recompensas = QComboBox()
        self.estilo_recompensas.addItem(t("Etiquetas pequeñas junto a cada tarjeta"), "etiquetas")
        self.estilo_recompensas.addItem(t("Panel con una tarjeta por recompensa"), "panel")
        self.estilo_recompensas.setCurrentIndex(
            max(0, self.estilo_recompensas.findData(self.config.get("estilo_recompensas") or "etiquetas"))
        )
        self.estilo_recompensas.currentIndexChanged.connect(self._cambiar_estilo_recompensas)
        # Un solo desplegable con preajustes: una lista ordenable de criterios no la toca
        # nadie, y lo que se pidio fue ver de un vistazo lo importante.
        self.prioridad_recompensas = QComboBox()
        for clave, _texto, _ayuda in prio.PREAJUSTES:
            self.prioridad_recompensas.addItem("", clave)
        self._textos_prioridad()
        self.prioridad_recompensas.setCurrentIndex(max(0, self.prioridad_recompensas.findData(
            prio.normalizar(self.config.get("prioridad_recompensas")))))
        self.prioridad_recompensas.currentIndexChanged.connect(self._cambiar_prioridad_recompensas)
        self.ocr_auto = QCheckBox()
        self._fijo(self.ocr_auto.setText, "Leer sola la pantalla de recompensas de reliquia")
        self.ocr_auto.setChecked(bool(self.config["ocr_reliquias_auto"]))
        self.ocr_auto.toggled.connect(lambda v: self._guardar("ocr_reliquias_auto", v))
        self.perfil_pasivo = QCheckBox()
        self._fijo(self.perfil_pasivo.setText, "Leer sola la maestría al abrir Perfil > Equipamiento")
        self.perfil_pasivo.setChecked(bool(self.config.get("perfil_pasivo", True)))
        self.perfil_pasivo.toggled.connect(lambda v: self._guardar("perfil_pasivo", v))
        self.inventario_pasivo = QCheckBox()
        self._fijo(self.inventario_pasivo.setText, "Leer solas las cantidades del Inventario y la Fundición (experimental)")
        self.inventario_pasivo.setChecked(bool(self.config.get("inventario_pasivo", False)))
        self.inventario_pasivo.toggled.connect(lambda v: self._guardar("inventario_pasivo", v))
        self.botin_eelog = QCheckBox()
        self._fijo(self.botin_eelog.setText, "Sumar a los objetivos la recompensa de reliquia de las misiones en solitario (EE.log)")
        self.botin_eelog.setChecked(bool(self.config.get("botin_eelog_auto", True)))
        self.botin_eelog.toggled.connect(lambda v: self._guardar("botin_eelog_auto", v))

        lectura = self._formulario()
        self._fila(lectura, "Recompensas de reliquia", self.estilo_recompensas)
        lectura.addRow(self._nota("Cómo se enseñan encima del juego las cuatro recompensas."))
        self._fila(lectura, "Al abrir reliquias, destacar", self.prioridad_recompensas)
        lectura.addRow(self._nota(
            "Qué se marca en grande en cada recompensa: lo que te falta, lo que vale más platino o "
            "más ducados."
        ))
        lectura.addRow(self.ocr_auto)
        lectura.addRow(self._nota(
            "Al abrir una reliquia, Farmadex lee solo la pantalla de recompensas. Si lo quitas, "
            "tendrás que usar el atajo."
        ))
        lectura.addRow(self.perfil_pasivo)
        lectura.addRow(self._nota("Al abrir Perfil > Equipamiento en el juego, apunta tu maestría sin que hagas nada."))
        lectura.addRow(self.inventario_pasivo)
        lectura.addRow(self._nota("Todavía en pruebas: puede leer mal alguna cantidad."))
        lectura.addRow(self.botin_eelog)
        lectura.addRow(self._nota(
            "En misiones en solitario, suma a tus objetivos la pieza que te toca, leyendo el "
            "registro del propio juego."
        ))
        lectura.addRow(self._nota(
            "Las lecturas solas solo miran la pantalla cuando Warframe está delante y se ha "
            "quedado quieta; F9 en la herramienta de escaneo sigue valiendo."
        ))
        lectura.addRow(self._nota(
            "Warframe tiene que estar en Ventana sin bordes (o en DX12). En pantalla "
            "completa exclusiva el overlay no se ve."
        ))
        # Lo que se ha detectado del juego: se rellena cuando la ventana lo mira.
        self.estado_juego = QLabel("")
        self.estado_juego.setWordWrap(True)
        self.estado_juego.setStyleSheet(f"color: {PALETA['suave']}; font-size: {px(12)}px;")
        lectura.addRow(self.estado_juego)
        self._meter("reliquias", self._grupo("Lectura de pantalla"), lectura)

        # -- diagnostico de reliquias ----------------------------------------------
        # Para el "no me sale nada al abrir una reliquia" de quien no sabe mandar el
        # registro: una lista de comprobaciones con veredicto y un .zip en el Escritorio.
        self.boton_diagnostico = self._boton("Comprobar la lectura de reliquias", principal=True)
        self.boton_diagnostico.clicked.connect(self.pedir_diagnostico.emit)
        self.boton_informe = self._boton("Guardar informe para enviar")
        self.boton_informe.clicked.connect(self.guardar_informe.emit)
        self.resultado_diagnostico = QLabel("")
        self.resultado_diagnostico.setTextFormat(Qt.RichText)
        self.resultado_diagnostico.setWordWrap(True)
        self.resultado_diagnostico.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.resultado_diagnostico.hide()
        self.estado_informe = QLabel("")
        self.estado_informe.setWordWrap(True)
        # Texto rico: tras guardar el informe lleva el enlace al foro de ayuda del Discord.
        self.estado_informe.setTextFormat(Qt.RichText)
        self.estado_informe.setOpenExternalLinks(True)
        self.estado_informe.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.estado_informe.setStyleSheet(f"color: {PALETA['suave']}; font-size: {px(12)}px;")
        self.estado_informe.hide()
        diagnostico = QVBoxLayout()
        diagnostico.setSpacing(px(6, False))
        diagnostico.addWidget(self._nota(
            "Si al abrir una reliquia no sale nada encima del juego, pulsa 'Comprobar': dice si "
            "EE.log se está leyendo, en qué modo de pantalla va el juego y si el lector está listo. "
            "'Guardar informe' deja un .zip en el Escritorio con el registro de Farmadex para "
            "enviarlo; nunca incluye EE.log ni datos de tu cuenta."
        ))
        diagnostico.addWidget(self.resultado_diagnostico)
        diagnostico.addLayout(fila(self.boton_diagnostico, self.boton_informe, None, espacio=px(8, False)))
        diagnostico.addWidget(self.estado_informe)
        self._meter("reliquias", self._grupo("Diagnóstico de reliquias"), diagnostico)

    def _construir_datos(self) -> None:
        self.estado_datos = QLabel("")
        self.estado_datos.setWordWrap(True)
        self.estado_datos.setStyleSheet(f"color: {PALETA['suave']};")
        self.aviso_parche = QLabel("")
        self.aviso_parche.setWordWrap(True)
        self.aviso_parche.setStyleSheet(f"color: {PALETA['aviso']};")
        self.aviso_parche.hide()
        # Ritmo de juego: multiplica las duraciones estimadas (eficiencia.RITMOS), no las
        # probabilidades. Un desplegable de tres y no un deslizador: el factor exacto no
        # dice nada a quien juega, "Rapido" o "Tranquilo" si.
        self.ritmo = QComboBox()
        for clave in eficiencia.RITMOS:
            self.ritmo.addItem("", clave)
        self._textos_ritmo()
        ritmo_guardado = self.config.get(eficiencia.CLAVE_RITMO) or eficiencia.RITMO_POR_DEFECTO
        self.ritmo.setCurrentIndex(max(0, self.ritmo.findData(ritmo_guardado)))
        self.ritmo.currentIndexChanged.connect(self._cambiar_ritmo)

        datos = self._formulario()
        datos.addRow(self.estado_datos)
        datos.addRow(self.aviso_parche)
        self._fila(datos, "Ritmo de juego", self.ritmo)
        datos.addRow(self._nota(
            "Farmadex calcula cuánto se tarda en conseguir cada cosa. Si juegas más rápido o más "
            "tranquilo que la media, cámbialo y los tiempos se ajustan. No cambia las probabilidades "
            "ni el orden de los sitios."
        ))
        self._meter("datos", self._grupo("Datos del juego"), datos)

        # -- avanzado (plegado): mantenimiento que casi nadie necesita --------------------
        self.boton_avanzado = QPushButton()
        self.boton_avanzado.setCheckable(True)
        self.boton_avanzado.setObjectName("plegable")
        self.boton_avanzado.setCursor(Qt.PointingHandCursor)
        self._estilo(self.boton_avanzado, lambda: (
            f"QPushButton#plegable {{ background: transparent; border: none; color: {PALETA['acento']};"
            f" font-family: '{TITULAR}'; font-weight: 600; text-align: left; padding: 4px 2px;"
            f" font-size: {px(13)}px; letter-spacing: 1px; }}"
        ))
        self.boton_avanzado.toggled.connect(self._plegar_avanzado)
        self.avanzado = transparente(QWidget())
        boton_datos = self._boton("Reconstruir el índice")
        boton_datos.clicked.connect(self.reconstruir.emit)
        boton_carpeta = self._boton("Abrir la carpeta de datos")
        boton_carpeta.clicked.connect(self._abrir_carpeta)
        boton_reproductor = self._boton("Borrar datos del reproductor")
        self._fijo(boton_reproductor.setToolTip, "Cierra el vídeo y borra la sesión y la cache del reproductor de guías")
        boton_reproductor.clicked.connect(self.borrar_reproductor.emit)
        self.boton_reconstruir, self.boton_carpeta, self.boton_reproductor = (
            boton_datos, boton_carpeta, boton_reproductor)
        # Rejilla del mantenimiento: a la izquierda el control, a la derecha su explicacion.
        # `anadir_avanzado` mete filas nuevas aqui.
        self.capa_avanzado = QGridLayout(self.avanzado)
        self.capa_avanzado.setContentsMargins(px(4, False), 0, 0, 0)
        self.capa_avanzado.setHorizontalSpacing(px(12, False))
        self.capa_avanzado.setVerticalSpacing(px(10, False))
        self.capa_avanzado.setColumnStretch(1, 1)
        for boton, texto in (
            (boton_datos, "Vuelve a preparar el catálogo desde cero, descargando lo que haga falta. "
                          "Úsalo solo si la búsqueda sale rara o faltan objetos nuevos. Tarda un poco "
                          "y mientras tanto no se puede buscar; tus objetivos no se tocan."),
            (boton_carpeta, "Abre la carpeta donde Farmadex guarda tus ajustes, objetivos y registros, "
                            "por si alguien que te ayuda te pide un fichero. No borres nada de ahí."),
            (boton_reproductor, "Cierra el vídeo y borra la sesión de YouTube y la cache del reproductor "
                                "de guías. Sirve si los vídeos no cargan; después tendrás que volver a "
                                "aceptar las cookies de YouTube."),
        ):
            self.anadir_avanzado(boton, self._nota(texto))

        # Lectura de pantalla (OCR): cuanta CPU puede usar el lector (captura/ocr.py).
        # El OCR de Windows solo se ofrece si esta instalado; guardado sin estarlo cuenta
        # como "auto" (captura/ocr.py, modo_de_config).
        con_windows = ocr.winocr_disponible()
        self.ocr_modo = QComboBox()
        for i, (clave, texto) in enumerate(m for m in MODOS_OCR if con_windows or m[0] != "windows"):
            self.ocr_modo.addItem("", clave)
            self._fijo(lambda s, i=i: self.ocr_modo.setItemText(i, s), texto)
        self.ocr_modo.setCurrentIndex(max(0, self.ocr_modo.findData(ocr.modo_de_config(self.config))))

        def cambiar_ocr_modo(_indice: int) -> None:
            modo = self.ocr_modo.currentData() or "auto"
            self._guardar("ocr_modo", modo)
            self.ocr_modo_cambiado.emit(modo)

        self.ocr_modo.currentIndexChanged.connect(cambiar_ocr_modo)
        etiqueta_ocr = EtiquetaC("", "normal")
        self._fijo(etiqueta_ocr.setText, "Lectura de pantalla (OCR)")
        nota_ocr = self._nota(
            "Cómo lee Farmadex la pantalla del juego.\n"
            "Automático: lee rápido y, si el juego está usando mucho el ordenador, lee con más calma "
            "para no quitarle rendimiento.\n"
            "Rápido: siempre a tope. Para ordenadores que van sobrados.\n"
            "Ligero: siempre con calma. Tarda un poco más, pero el juego casi no lo nota."
        )
        if con_windows:
            self._fijo(lambda s: nota_ocr.setText(nota_ocr.text() + "\n" + s),
                       "OCR de Windows: usa el lector de texto que trae Windows. Si tu Windows no lo tiene, "
                       "Farmadex usa el suyo.")
        self.anadir_avanzado(self.ocr_modo, nota_ocr, etiqueta_ocr)

        self.avanzado.setVisible(False)
        self.panel_avanzado = PanelC(remate=False)
        self.panel_avanzado.capa.setSpacing(px(8, False))
        self.panel_avanzado.capa.addWidget(self.boton_avanzado)
        self.panel_avanzado.capa.addWidget(self.avanzado)
        self._contenido["datos"].addWidget(self.panel_avanzado)
        self._plegar_avanzado(False)

    def anadir_avanzado(self, control: QWidget, nota: QWidget, etiqueta: QWidget | None = None) -> None:
        """Una fila mas en Datos del juego > Avanzado: `control` a la izquierda (con su
        `etiqueta` encima, si la lleva) y `nota` (lo que hace) a la derecha."""
        fila_nueva = self.capa_avanzado.rowCount()
        if etiqueta is not None:
            izquierda = transparente(QWidget())
            capa = QVBoxLayout(izquierda)
            capa.setContentsMargins(0, 0, 0, 0)
            capa.setSpacing(px(4, False))
            capa.addWidget(etiqueta)
            capa.addWidget(control)
            self.capa_avanzado.addWidget(izquierda, fila_nueva, 0, Qt.AlignTop)
        else:
            self.capa_avanzado.addWidget(control, fila_nueva, 0, Qt.AlignTop)
        self.capa_avanzado.addWidget(nota, fila_nueva, 1)

    def _construir_ayuda(self) -> None:
        self.boton_bienvenida = self._boton("Ver la bienvenida", principal=True)
        self.boton_bienvenida.clicked.connect(self.ver_bienvenida.emit)
        self.boton_guia = self._boton("Recorrido por la ventana")
        self.boton_guia.clicked.connect(self.ver_guia.emit)
        self.boton_acerca_ayuda = BotonC(tam=11)
        self._fijo(lambda s: self.boton_acerca_ayuda.setText(s.format(app=NOMBRE_APP)), "Acerca de {app}")
        self.boton_acerca_ayuda.clicked.connect(self._abrir_acerca)
        ayuda = QGridLayout()
        ayuda.setHorizontalSpacing(px(12, False))
        ayuda.setVerticalSpacing(px(10, False))
        filas = (
            (self.boton_bienvenida, "Qué es Farmadex, lo básico paso a paso, si es seguro, preguntas "
                                    "frecuentes y agradecimientos."),
            (self.boton_guia, "Te enseña cada parte de la ventana en su sitio, paso a paso."),
            (self.boton_acerca_ayuda, "Versión, qué dice Digital Extremes de los programas de terceros "
                                      "y cómo comprobar que tu descarga es la buena."),
        )
        for fila_n, (boton, texto) in enumerate(filas):
            ayuda.addWidget(boton, fila_n, 0, Qt.AlignTop | Qt.AlignLeft)
            ayuda.addWidget(self._nota(texto), fila_n, 1)
        ayuda.setColumnStretch(1, 1)
        self._meter("ayuda", self._grupo("Ayuda"), ayuda)

    def resizeEvent(self, evento) -> None:  # noqa: N802 - firma de Qt
        super().resizeEvent(evento)
        self._ajustar_disposicion()

    def _ajustar_disposicion(self) -> None:
        """Colores y vista previa en fila si caben en el ancho de la pagina; si no, en columna.
        Las tarjetas de tema, todas en una fila si caben; si no, de tres en tres."""
        arriba = getattr(self, "_arriba_aspecto", None)
        if arriba is None:
            return
        necesario = (self._izquierda_aspecto.minimumSize().width()
                     + self.vista_previa.minimumSizeHint().width() + px(80, False))
        direccion = (QBoxLayout.LeftToRight if self.paginas.width() >= necesario
                     else QBoxLayout.TopToBottom)
        if arriba.direction() != direccion:
            arriba.setDirection(direccion)
        ancho_tema = self.paginas.width() * (0.6 if direccion == QBoxLayout.LeftToRight else 1.0)
        por_fila = self.tema.count()
        minimo = px(118, False) + px(8, False)
        if por_fila * minimo > ancho_tema - px(40, False):
            por_fila = 3
        self.tema.poner_columnas(0 if por_fila == self.tema.count() else por_fila)

    # -- navegacion ---------------------------------------------------------------------

    def ir_a(self, seccion: str) -> None:
        """Muestra una seccion por su clave ("general", "reliquias"...)."""
        if seccion in self._claves_seccion:
            self.secciones.setCurrentRow(self._claves_seccion.index(seccion))

    def seccion_actual(self) -> str:
        return self._claves_seccion[max(0, self.secciones.currentRow())]

    def _plegar_avanzado(self, abierto: bool) -> None:
        self.avanzado.setVisible(abierto)
        flecha = "▾" if abierto else "▸"
        self.boton_avanzado.setText(f"{flecha}  {t('Avanzado (mantenimiento)')}")

    # -- aspecto: pendiente, vista previa, guardar ------------------------------------------

    def _tema_actual(self) -> str:
        return self.tema.currentData() or TEMA_POR_DEFECTO

    def _cargar_aspecto(self) -> None:
        """Lo guardado pasa a ser lo pendiente (al abrir, al descartar, al cambiar de tema)."""
        colores, interfaz, letra = aspecto_guardado(self.config, self._tema_actual())
        self._pend_colores = dict(colores)
        self._fabrica_todos = False
        for selector, valor in ((self.escala_interfaz, interfaz), (self.escala_letra, letra)):
            selector.blockSignals(True)
            selector.setCurrentIndex(max(0, selector.findData(valor)))
            selector.blockSignals(False)
        self._pintar_aspecto()

    def _pendiente(self) -> tuple[dict, float, float]:
        return (dict(self._pend_colores), float(self.escala_interfaz.currentData()),
                float(self.escala_letra.currentData()))

    def hay_cambios_aspecto(self) -> bool:
        if self._fabrica_todos and self.config.get("colores_personalizados"):
            return True
        return self._pendiente() != aspecto_guardado(self.config, self._tema_actual())

    def _cambio_pendiente(self, *_args) -> None:
        self._pintar_aspecto()

    def _elegir_color(self, clave: str) -> None:
        actual = paleta_de(self._tema_actual(), self._pend_colores)[clave]
        nombre = next(n for c, n, _a in CATEGORIAS_COLOR if c == clave)
        elegido = QColorDialog.getColor(QColor(actual), self, t(nombre))
        if elegido.isValid():
            self._poner_color(clave, elegido.name())

    def _poner_color(self, clave: str, valor: str | None) -> None:
        """Cambia un color pendiente; None (o el mismo del tema) lo devuelve al del tema."""
        base = TEMAS.get(self._tema_actual(), TEMAS[TEMA_POR_DEFECTO])
        if valor is None or valor.lower() == base[clave].lower():
            self._pend_colores.pop(clave, None)
        else:
            self._pend_colores[clave] = valor.lower()
        self._pintar_aspecto()

    def _pintar_aspecto(self) -> None:
        colores, interfaz, letra = self._pendiente()
        paleta = paleta_de(self._tema_actual(), colores)
        for clave, muestra in self.muestras.items():
            valor = paleta[clave]
            muestra.setText(valor)
            muestra.personal = clave in colores
            muestra.update()
            self.deshacer_color[clave].setEnabled(clave in colores)
        self.vista_previa.pintar(paleta, (interfaz, letra))
        cambios = self.hay_cambios_aspecto()
        self.boton_guardar_aspecto.setEnabled(cambios)
        self.boton_descartar_aspecto.setEnabled(cambios)
        if cambios:
            texto = (t("Vista previa con lo de fábrica: pulsa Guardar para aplicarlo.")
                     if self._fabrica_todos else t("Hay cambios sin guardar."))
            tinta = "aviso"
        else:
            texto, tinta = t("Es el aspecto que estás usando."), "suave"
        self.estado_aspecto.setText(texto)
        self.estado_aspecto.poner_tinta(tinta)

    def guardar_aspecto(self) -> None:
        colores, interfaz, letra = self._pendiente()
        tema = self._tema_actual()
        todos = {} if self._fabrica_todos else dict(self.config.get("colores_personalizados") or {})
        if colores:
            todos[tema] = colores
        else:
            todos.pop(tema, None)
        self.config["colores_personalizados"] = todos
        self.config["escala_interfaz"] = interfaz
        self.config["escala_letra"] = letra
        guardar(self.config)
        self._fabrica_todos = False
        # La ventana lo recibe y vuelve a aplicar el tema (con esto encima) a todo.
        self.apariencia_cambiada.emit()
        self._pintar_aspecto()

    def descartar_aspecto(self) -> None:
        self._cargar_aspecto()

    def aspecto_de_fabrica(self) -> None:
        self._pend_colores = {}
        self._fabrica_todos = True
        for selector in (self.escala_interfaz, self.escala_letra):
            selector.blockSignals(True)
            selector.setCurrentIndex(max(0, selector.findData(1.0)))
            selector.blockSignals(False)
        self._pintar_aspecto()

    # -- textos fijos, tema e idioma -----------------------------------------------------

    def repintar(self) -> None:
        """Tras cambiar de tema o de tamano: las etiquetas llevan el color puesto a mano."""
        p = PALETA
        for widget, hoja in self._estilos:
            widget.setStyleSheet(hoja())
        self.aviso_hotkey.setStyleSheet(f"color: {p['aviso']};")
        self.estado_datos.setStyleSheet(f"color: {p['suave']};")
        self.estado_informe.setStyleSheet(f"color: {p['suave']}; font-size: {px(12)}px;")
        alerta = getattr(self, "_aviso_parche_es_alerta", True)
        self.aviso_parche.setStyleSheet(f"color: {p['aviso' if alerta else 'suave']};")
        self.aviso_version.setStyleSheet(f"color: {p[self._color_version]};")
        self.autor.setText(texto_autor())  # el enlace lleva el color de acento del tema
        self.discord.setText(texto_discord_corto())
        if self._modo_pantalla is not None:
            self.mostrar_modo_pantalla(self._modo_pantalla)
        for i in range(self.tema.count()):
            self.tema.boton(i).update()
        self._ajustar_ancho_secciones()
        self._ajustar_disposicion()
        if self.hay_cambios_aspecto():
            self._pintar_aspecto()
        else:
            self._cargar_aspecto()

    def retraducir(self) -> None:
        """Vuelve a escribir todo lo fijo en el idioma activo; lo dinamico se refresca."""
        for poner, clave in self._fijos:
            poner(t(clave))
        for i, tema in enumerate(TEMAS.values()):
            self.tema.setItemText(i, t(tema["titulo"]))
        self.idioma.setItemText(0, t("Automático (el de Windows)"))
        for selector, pasos in ((self.escala_interfaz, ESCALAS_INTERFAZ), (self.escala_letra, ESCALAS_LETRA)):
            for i, (_factor, nombre) in enumerate(pasos):
                selector.setItemText(i, t(nombre))
        self._textos_ritmo()
        self.estilo_recompensas.setItemText(0, t("Etiquetas pequeñas junto a cada tarjeta"))
        self.estilo_recompensas.setItemText(1, t("Panel con una tarjeta por recompensa"))
        self._textos_prioridad()
        self._plegar_avanzado(self.boton_avanzado.isChecked())
        self.vista_previa.retraducir()
        self._pintar_aspecto()
        self._ajustar_ancho_secciones()
        self.aviso_hotkey.setText("")
        self.estado_version(t("Estás en la última versión"))
        self.refrescar_estado()
        if self._modo_pantalla is not None:
            self.mostrar_modo_pantalla(self._modo_pantalla)

    # -- lo detectado del juego ---------------------------------------------------

    MODOS_PANTALLA = {
        "ventana": "Ventana",
        "sin_bordes": "Ventana sin bordes",
        "exclusivo": "Pantalla completa exclusiva (el overlay no puede verse encima)",
        "desconocido": "Warframe no está abierto",
    }

    def mostrar_modo_pantalla(self, modo: str) -> None:
        """La ventana lo llama cada vez que mira en que modo esta el juego."""
        self._modo_pantalla = modo
        etiqueta = t(self.MODOS_PANTALLA.get(modo, self.MODOS_PANTALLA["desconocido"]))
        self.estado_juego.setText(t("Modo de pantalla detectado: {modo}", modo=etiqueta))
        tinta = PALETA["aviso"] if modo == "exclusivo" else PALETA["suave"]
        self.estado_juego.setStyleSheet(f"color: {tinta}; font-size: {px(12)}px;")

    # -- diagnostico de reliquias --------------------------------------------------

    def mostrar_diagnostico(self, diagnostico) -> None:
        """Pinta el resultado (`diagnostico.Diagnostico`) con el color de cada veredicto."""
        p = PALETA
        colores = {"ok": p.get("ok", p["acento"]), "mal": p["aviso"], "aviso": p["aviso"], "dato": p["suave"]}
        self._ultimo_diagnostico = diagnostico
        self.resultado_diagnostico.setText(diagnostico.html(colores))
        self.resultado_diagnostico.show()
        self.ir_a("reliquias")  # el resultado se ve donde esta el boton que lo pidio

    def informe_guardado(self, ruta, error: str = "") -> None:
        """Donde quedo el .zip, o por que no se pudo escribir."""
        if error:
            self.estado_informe.setStyleSheet(f"color: {PALETA['aviso']}; font-size: {px(12)}px;")
            self.estado_informe.setText(html.escape(t("No se pudo guardar el informe: {error}", error=error)))
        else:
            self.estado_informe.setStyleSheet(f"color: {PALETA['suave']}; font-size: {px(12)}px;")
            self.estado_informe.setText(
                frase("Informe guardado en {ruta}. Envíaselo a quien te ayude; no contiene EE.log.",
                      ruta=html.escape(str(ruta)))
                + "<br>" + frase("Puedes enviarlo en el foro de ayuda del Discord de Farmadex: {enlace}",
                                 enlace=enlace_discord())
            )
        self.estado_informe.show()

    def avisar_parche(self, texto: str | None, aviso: bool = True) -> None:
        """Aviso de que los datos son anteriores al parche del juego; None lo quita.

        Con `aviso` en False va en color neutro: los datos son lo ultimo publicado y
        solo se informa de que DE no ha actualizado sus tablas desde el parche.
        """
        self._texto_parche = texto
        self._aviso_parche_es_alerta = aviso
        self.aviso_parche.setStyleSheet(f"color: {PALETA['aviso' if aviso else 'suave']};")
        self.aviso_parche.setText(texto or "")
        self.aviso_parche.setVisible(bool(texto))

    # -- acciones ----------------------------------------------------------

    def _guardar(self, clave: str, valor) -> None:
        self.config[clave] = valor
        guardar(self.config)

    def _abrir_acerca(self) -> None:
        abrir_acerca_de(self.window())

    def _cambiar_estilo_recompensas(self, _indice: int) -> None:
        estilo = self.estilo_recompensas.currentData()
        self._guardar("estilo_recompensas", estilo)
        self.estilo_recompensas_cambiado.emit(estilo)

    def _textos_prioridad(self) -> None:
        """Nombre y tooltip de una linea de cada preajuste, en el idioma activo."""
        for i, (_clave, texto, ayuda) in enumerate(prio.PREAJUSTES):
            self.prioridad_recompensas.setItemText(i, t(texto))
            self.prioridad_recompensas.setItemData(i, t(ayuda), Qt.ToolTipRole)
        actual = max(0, self.prioridad_recompensas.currentIndex())
        self.prioridad_recompensas.setToolTip(t(prio.PREAJUSTES[actual][2]))

    def _cambiar_prioridad_recompensas(self, indice: int) -> None:
        clave = prio.normalizar(self.prioridad_recompensas.currentData())
        self.prioridad_recompensas.setToolTip(t(prio.PREAJUSTES[max(0, indice)][2]))
        self._guardar("prioridad_recompensas", clave)
        self.prioridad_recompensas_cambiada.emit(clave)

    def _pintar_opacidad(self) -> None:
        self.valor_opacidad.setText(f"{self.opacidad.value()} %")

    def _cambiar_opacidad(self, valor: int) -> None:
        self._pintar_opacidad()
        self._guardar("overlay_opacidad", valor / 100)
        self.opacidad_cambiada.emit(valor / 100)

    def _cambiar_tema(self, _indice: int) -> None:
        clave = self.tema.currentData() or TEMA_POR_DEFECTO
        self._guardar("tema", clave)
        self._cargar_aspecto()  # lo pendiente era del tema anterior
        self.tema_cambiado.emit(clave)

    def _cambiar_idioma(self, _indice: int) -> None:
        codigo = self.idioma.currentData() or idiomas.AUTOMATICO
        self._guardar("idioma_ui", codigo)
        self.idioma_cambiado.emit(codigo)

    RITMOS = {
        "rapido": "Rápido: veterano con buen equipo (x{factor})",
        "normal": "Normal: jugador medio (x{factor})",
        "tranquilo": "Tranquilo: empezando o explorando (x{factor})",
    }

    def _textos_ritmo(self) -> None:
        for i in range(self.ritmo.count()):
            clave = self.ritmo.itemData(i)
            self.ritmo.setItemText(i, t(self.RITMOS[clave], factor=f"{eficiencia.RITMOS[clave]:g}"))

    def _cambiar_ritmo(self, _indice: int) -> None:
        clave = self.ritmo.currentData() or eficiencia.RITMO_POR_DEFECTO
        self._guardar(eficiencia.CLAVE_RITMO, clave)
        self.ritmo_cambiado.emit(clave)

    def _cambiar_arranque(self, activo: bool) -> None:
        """Alta o baja en HKCU\\...\\Run; si no se puede (codigo sin congelar), se desmarca."""
        from .. import arranque

        if arranque.sincronizar(activo):
            self._guardar("iniciar_con_windows", activo)
        elif activo:
            self.iniciar_windows.blockSignals(True)
            self.iniciar_windows.setChecked(False)
            self.iniciar_windows.blockSignals(False)
            self._guardar("iniciar_con_windows", False)
        self._pintar_aviso_arranque()

    def _pintar_aviso_arranque(self) -> None:
        from .. import arranque

        if arranque.comando_arranque() is None:
            self.aviso_arranque.setText(t("Solo disponible en la versión instalada o portable (.exe)."))
        elif arranque.es_portable():
            self.aviso_arranque.setText(
                t("Versión portable: si mueves o borras el .exe, el arranque dejará de funcionar.")
            )
        else:
            self.aviso_arranque.setText("")

    def _aplicar_hotkeys(self) -> None:
        nuevas = {}
        for nombre, campo in self.campos_hotkey.items():
            texto = campo.text().strip()
            try:
                parsear(texto)
            except ValueError as e:
                self.aviso_hotkey.setText(f"{texto or t('(vacío)')}: {e}")
                return
            nuevas[nombre] = texto
        for nombre, texto in nuevas.items():
            self._guardar(f"hotkey_{nombre}", texto)
        self.aviso_hotkey.setText(t("Atajos aplicados."))
        self.hotkeys_cambiadas.emit(nuevas)

    def _abrir_carpeta(self) -> None:
        if os.name == "nt":
            os.startfile(DIR_BASE)  # noqa: S606 - abrir el explorador es la intencion
        else:  # pragma: no cover - solo para desarrollo fuera de Windows
            subprocess.Popen(["xdg-open", str(DIR_BASE)])

    # -- version ----------------------------------------------------------------

    def _pedir_comprobacion(self) -> None:
        self.estado_version(t("Comprobando..."))
        self.comprobar_version.emit()

    def estado_version(self, texto: str) -> None:
        """Lo escribe quien hace la comprobacion: 'Estas en la ultima version', etc."""
        self.aviso_version.setText(texto)
        self._color_version = "suave"
        self.aviso_version.setStyleSheet(f"color: {PALETA['suave']};")

    def anunciar_version(self, version, local: bool = False, lista: bool = False) -> None:
        """Avisa de una version nueva.

        `local`: compilacion en la carpeta del PC, se instala con el boton.
        `lista`: ya descargada y comprobada por la app; se instala al cerrar o con
        "Reiniciar y actualizar". Sin ninguna de las dos, solo el enlace de descarga.
        """
        cabecera = t("Hay una versión nueva: <b>{version}</b>.", version=version.etiqueta)
        self.boton_reiniciar.setVisible(lista)
        if lista:
            self.aviso_version.setText(
                cabecera + " " + t(
                    "Ya está descargada y comprobada: se instala sola al cerrar Farmadex, "
                    "o ahora mismo con el botón. Tus objetivos y ajustes se conservan."
                )
            )
            self.boton_instalar.setVisible(False)
            try:
                self.boton_reiniciar.clicked.disconnect()
            except RuntimeError:
                pass
            self.boton_reiniciar.clicked.connect(lambda: self.instalar_version.emit(version))
        elif local:
            self.aviso_version.setText(
                cabecera + " " + t("Al instalarla se cierra Farmadex; tus objetivos y ajustes se conservan.")
            )
            self.boton_instalar.setVisible(True)
            try:
                self.boton_instalar.clicked.disconnect()
            except RuntimeError:
                pass
            self.boton_instalar.clicked.connect(lambda: self.instalar_version.emit(version))
        else:
            self.aviso_version.setText(
                f'{cabecera} <a style="color:{PALETA["acento"]}" href="{version.url}">'
                f"{t('Descargarla')}</a>"
            )
        self._color_version = "aviso"
        self.aviso_version.setStyleSheet(f"color: {PALETA['aviso']};")

    # -- datos ------------------------------------------------------------------

    def refrescar_estado(self) -> None:
        if not indice.hay_indice():
            self.estado_datos.setText(t("Todavía no hay índice construido."))
            return
        try:
            con = indice.conectar()
            meta = dict(con.execute("SELECT clave, valor FROM meta").fetchall())
            objetos = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            con.close()
        except sqlite3.Error as e:
            self.estado_datos.setText(t("No se pudo leer el índice: {error}", error=e))
            return
        self.estado_datos.setText(
            t("<b>{n}</b> objetos en el catálogo", n=objetos) + "<br>"
            + t("Catálogo del {fecha}", fecha=meta.get("items_fecha", "?")[:10]) + " &middot; "
            + t("tablas de drops del {fecha}", fecha=_fecha(meta.get("drops_modified"))) + "<br>"
            + t("Índice construido el {fecha}",
                fecha=meta.get("construido_en", "?")[:16].replace("T", " "))
        )


def _fecha(valor: str | None) -> str:
    """drop-data da la fecha en milisegundos desde 1970; el resto ya viene legible."""
    if not valor:
        return "?"
    if valor.isdigit():
        from datetime import datetime

        return datetime.fromtimestamp(int(valor) / 1000).strftime("%Y-%m-%d %H:%M")
    return valor[:16].replace("T", " ")
