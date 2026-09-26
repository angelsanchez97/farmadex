"""Sistema de diseno C ("menu del juego"): tipografia, medidas y piezas con forma Orokin.

El estilo C define la FORMA (esquinas cortadas, filetes dorados, rombos, jerarquia de
letra) y toma los COLORES del tema activo (`widgets.PALETA`, con lo que el usuario haya
personalizado en Ajustes > Apariencia). Nada de aqui guarda un color fijo salvo los que
tienen significado en el juego (eras de reliquia).

Como se usa (resumen; el detalle esta en cada clase):

    from .estilo_c import PanelC, BotonC, EtiquetaC, Rombo, SubPestanasC

    panel = PanelC(t("Tu siguiente paso"))          # titulo con rombo y filete dorado
    panel.capa.addWidget(EtiquetaC("Sistemas de Citrine Prime", "titulo", mayus=True))
    panel.capa.addWidget(EtiquetaC(t("hasta tener la pieza"), "pequeno"))
    boton = BotonC(t("Ver que farmear"), principal=True)   # QPushButton de verdad
    boton.clicked.connect(...)

Tipografia: cinco tamanos (`TAM`) y roles de texto (`ROLES`). Los roles se pintan desde
la hoja de estilos global (`hoja_c`, que `widgets.hoja_estilos` incluye) por la propiedad
`rolC` de cada QLabel, asi que siguen solos al tema y a la escala de Ajustes. El color de
una etiqueta se cambia con su propiedad `tinta` (una clave de la paleta).

Colores de la paleta que usa el estilo, ademas de los de siempre: `secundario` (el
turquesa de la maqueta: fisuras, reliquias, lo que se puede hacer ya), `tenue` (texto
muy apagado) y `acento_tenue` (filetes dorados apagados). `widgets.paleta_de` los
calcula para todos los temas.

Las piezas pintadas a mano (rombos, paneles, botones, menus) leen la paleta y la escala
al pintarse; tras cambiar de tema basta con `refrescar_todo(ventana)` para que vuelvan
a medirse.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# -- tipografia ----------------------------------------------------------------------
# La queja del tester era "todo pesa lo mismo": una escala corta, con saltos grandes.
TITULAR = "Bahnschrift"        # titulos, menu, rotulos y cifras (viene con Windows 10/11)
TEXTO = "Segoe UI"             # texto corrido
ICONOS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")  # Windows 11 / Windows 10

TAM = {
    "portada": 30,   # lo unico que hay que leer si solo miras un segundo (1 H 09 MIN)
    "titulo": 24,    # titulo de pagina o de ficha
    "seccion": 16,   # menu superior, nombre destacado dentro de un panel
    "normal": 14,    # texto
    "pequeno": 12,   # rotulos de panel, metadatos, pistas
}

# rol -> (familia, tamano, peso, espaciado entre letras, color por defecto)
ROLES = {
    "portada": (TITULAR, "portada", 600, 1.0, "acento"),
    "titulo": (TITULAR, "titulo", 600, 1.5, "texto"),
    "seccion": (TITULAR, "seccion", 600, 1.0, "texto"),
    "rotulo": (TITULAR, "pequeno", 600, 2.5, "acento"),   # cabecera de panel, en mayusculas
    "dato": (TITULAR, "normal", 600, 0.5, "texto"),        # cifras y valores cortos
    "destacado": (TEXTO, "seccion", 600, 0.0, "texto"),    # nombre de una fila (Afrodita, Venus)
    "normal": (TEXTO, "normal", 400, 0.0, "texto"),
    "fuerte": (TEXTO, "normal", 600, 0.0, "texto"),
    "pequeno": (TEXTO, "pequeno", 400, 0.0, "suave"),
}

# Espaciados (px a escala 1): margenes de pagina, de panel y separaciones.
ESPACIO = {"pagina": 30, "bloque": 16, "panel_h": 20, "panel_v": 14, "fila": 10, "junto": 6}
CHAFLAN = 14        # corte de las esquinas de un panel
CHAFLAN_BOTON = 7   # corte de la esquina de un boton

# Colores con significado en el juego: no dependen del tema.
COLOR_ERA = {
    "Lith": "#9fc9a5", "Meso": "#8fb4e0", "Neo": "#c9a0e0", "Axi": "#e6c070",
    "Requiem": "#e07070", "Omnia": "#e8e0c8",
}

# Glifos de la fuente de iconos de Windows (misma posicion en Fluent y en MDL2).
ICONO = {
    "buscar": "", "juego": "", "pin": "", "reloj": "", "derecha": "",
    "abajo": "", "cerrar": "", "mas": "", "sol": "", "luna": "",
    "ayuda": "", "mundo": "", "estrella": "", "info": "",
}


# Glifos de MIS METAS (marcar hecho, editar, leer la pantalla, importar).
ICONO.update({"hecho": "", "editar": "", "leer": "", "importar": "", "menos": ""})


def px(tamano: float, letra: bool = True) -> int:
    """Pixeles de una medida con la escala activa de Ajustes (ver `widgets.px`)."""
    return widgets.px(tamano, letra)


def color(clave_o_hex: str | None, defecto: str = "texto") -> QColor:
    """Una clave de la paleta activa ("acento", "secundario"...) o un "#rrggbb"."""
    valor = clave_o_hex or defecto
    return QColor(widgets.PALETA.get(valor, valor))


def hex_de(clave_o_hex: str | None, defecto: str = "texto") -> str:
    return color(clave_o_hex, defecto).name()


def fuente(rol: str = "normal", tam: int | None = None, peso: int | None = None) -> QFont:
    """QFont de un rol (o de un tamano suelto), ya escalado."""
    familia, clave, peso_rol, espaciado, _c = ROLES.get(rol, ROLES["normal"])
    f = QFont(familia)
    f.setFamilies([familia, TEXTO])
    f.setPixelSize(px(tam if tam is not None else TAM[clave]))
    f.setWeight(QFont.Weight(peso if peso is not None else peso_rol))
    if espaciado:
        f.setLetterSpacing(QFont.AbsoluteSpacing, espaciado)
    return f


def fuente_iconos(tam: int) -> QFont:
    f = QFont(ICONOS[0])
    f.setFamilies(list(ICONOS))
    f.setPixelSize(px(tam))
    return f


def hoja_c(p: dict, f, m) -> str:
    """Reglas del estilo C para la hoja global. `f`/`m` escalan letra y medidas."""
    reglas = []
    for rol, (familia, clave, peso, _esp, tinta) in ROLES.items():
        reglas.append(
            f"QLabel[rolC=\"{rol}\"] {{ font-family: '{familia}'; font-size: {f(TAM[clave])};"
            f" font-weight: {peso}; color: {p.get(tinta, p['texto'])}; background: transparent; }}"
        )
    # La tinta va despues: a igual especificidad gana la ultima regla.
    for clave in ("texto", "suave", "tenue", "acento", "acento_tenue", "secundario", "aviso", "ok"):
        if clave in p:
            reglas.append(f"QLabel[tinta=\"{clave}\"] {{ color: {p[clave]}; }}")
    reglas.append("*[transparenteC=\"true\"] { background: transparent; }")
    reglas.append(
        f"QLineEdit#cajaC {{ background: transparent; border: none; padding: {m(10)} {m(4)};"
        f" font-family: '{TITULAR}'; font-size: {f(18)}; }}"
    )
    return "\n".join(reglas) + "\n"


# widgets.py necesita `hoja_c` al importarse (su HOJA_ESTILOS): por eso este import va
# despues de definirla y no arriba; importar estilo_c primero no crea un ciclo roto.
from . import widgets  # noqa: E402


def transparente(w: QWidget) -> QWidget:
    """Sin el fondo que la hoja global da a todo QWidget: para contenedores y piezas
    pintadas, que si no taparian las esquinas cortadas o la transparencia de la ventana."""
    w.setProperty("transparenteC", True)
    return w


def refrescar_todo(raiz: QWidget) -> None:
    """Tras cambiar de tema o de escala: las piezas pintadas a mano se vuelven a medir."""
    for w in raiz.findChildren(QWidget):
        if isinstance(w, PiezaC):
            w.refrescar_estilo()


class PiezaC:
    """Mezcla para las piezas del estilo que se miden o se colorean a mano."""

    def refrescar_estilo(self) -> None:  # pragma: no cover - lo sobrescriben
        self.updateGeometry()
        self.update()


# -- utilidades de forma -----------------------------------------------------------------


def ruta_chaflan(r: QRectF, c: float, esquinas: str = "id") -> QPainterPath:
    """Rectangulo con esquinas cortadas en diagonal: "i" arriba-izquierda, "d" abajo-derecha."""
    camino = QPainterPath()
    ci = c if "i" in esquinas else 0
    cd = c if "d" in esquinas else 0
    camino.moveTo(r.left() + ci, r.top())
    camino.lineTo(r.right(), r.top())
    camino.lineTo(r.right(), r.bottom() - cd)
    camino.lineTo(r.right() - cd, r.bottom())
    camino.lineTo(r.left(), r.bottom())
    camino.lineTo(r.left(), r.top() + ci)
    camino.closeSubpath()
    return camino


def _rombo_poligono(cx: float, cy: float, medio: float) -> QPolygonF:
    return QPolygonF([QPointF(cx, cy - medio), QPointF(cx + medio, cy), QPointF(cx, cy + medio),
                      QPointF(cx - medio, cy)])


def fila(*piezas, espacio: int = 8, margen=(0, 0, 0, 0)) -> QHBoxLayout:
    """QHBoxLayout rapido: None = hueco elastico, int = espacio fijo, layouts se anaden."""
    capa = QHBoxLayout()
    capa.setContentsMargins(*margen)
    capa.setSpacing(espacio)
    for w in piezas:
        if w is None:
            capa.addStretch(1)
        elif isinstance(w, int):
            capa.addSpacing(w)
        elif isinstance(w, (QHBoxLayout, QVBoxLayout)):
            capa.addLayout(w, 1)
        else:
            capa.addWidget(w)
    return capa


def columna(*piezas, espacio: int = 6, margen=(0, 0, 0, 0)) -> QVBoxLayout:
    capa = QVBoxLayout()
    capa.setContentsMargins(*margen)
    capa.setSpacing(espacio)
    for w in piezas:
        if w is None:
            capa.addStretch(1)
        elif isinstance(w, int):
            capa.addSpacing(w)
        elif isinstance(w, (QHBoxLayout, QVBoxLayout)):
            capa.addLayout(w)
        else:
            capa.addWidget(w)
    return capa


# -- texto -------------------------------------------------------------------------------


class EtiquetaC(QLabel):
    """QLabel con un rol tipografico. `mayus` la escribe en mayusculas (la letra de titulares
    sin mayusculas pierde el aire de menu del juego); `tinta` cambia el color por clave.
    `recortar` = si no cabe, se corta con "..." (y el texto entero va al tooltip) en vez de
    ensanchar la pagina: para nombres y detalles en filas estrechas."""

    def __init__(self, texto: str = "", rol: str = "normal", tinta: str | None = None,
                 mayus: bool = False, envolver: bool = False, recortar: bool = False, parent=None):
        super().__init__(parent)
        self._mayus = mayus
        self._recortar = recortar and not envolver
        self._completo = ""
        if self._recortar:
            # Con un minimo explicito, el layout puede encogerla hasta ahi (y no mas alla).
            self.setMinimumWidth(px(40, False))
        self.setProperty("rolC", rol if rol in ROLES else "normal")
        if tinta:
            self.setProperty("tinta", tinta)
        espaciado = ROLES.get(rol, ROLES["normal"])[3]
        if espaciado:
            f = self.font()
            f.setLetterSpacing(QFont.AbsoluteSpacing, espaciado)
            self.setFont(f)
        if rol in ("titulo", "portada", "seccion", "rotulo") and mayus:
            # Sin este margen, la tilde de las mayusculas (CÓMO) se corta en Bahnschrift.
            self.setContentsMargins(0, 2, 0, 0)
        self.setWordWrap(envolver)
        self.setText(texto)

    def setText(self, texto: str) -> None:  # noqa: N802 - nombre de Qt
        texto = texto or ""
        if "<" in texto:
            self.setTextFormat(Qt.RichText)
        else:
            self.setTextFormat(Qt.PlainText)
            if self._mayus:
                texto = texto.upper()
        self._completo = texto
        if self._recortar and self.textFormat() == Qt.PlainText:
            self._poner_recortado()
            return
        super().setText(texto)

    def texto_completo(self) -> str:
        return self._completo

    def _poner_recortado(self) -> None:
        visible = self.fontMetrics().elidedText(self._completo, Qt.ElideRight, max(10, self.contentsRect().width()))
        QLabel.setText(self, visible)
        self.setToolTip(self._completo if visible != self._completo else "")

    def resizeEvent(self, evento):  # noqa: N802 - firma de Qt
        super().resizeEvent(evento)
        if self._recortar and self.textFormat() == Qt.PlainText:
            self._poner_recortado()

    def sizeHint(self) -> QSize:  # noqa: N802
        base = super().sizeHint()
        if self._recortar:
            return QSize(self.fontMetrics().horizontalAdvance(self._completo) + 4, base.height())
        return base

    def poner_tinta(self, tinta: str | None) -> None:
        self.setProperty("tinta", tinta or "")
        self.style().unpolish(self)
        self.style().polish(self)


def icono(clave: str, tam: int = 18, tinta: str = "acento") -> QLabel:
    """Glifo de la fuente de iconos de Windows, como QLabel."""
    e = QLabel(ICONO.get(clave, clave))
    e.setObjectName("iconoC")
    e.setFont(fuente_iconos(tam))
    e.setStyleSheet(f"color: {hex_de(tinta)}; background: transparent; font-family: '{ICONOS[0]}';"
                    f" font-size: {px(tam)}px;")
    e.setAlignment(Qt.AlignCenter)
    e.setFixedWidth(int(px(tam) * 1.4))
    return e


# -- piezas pintadas ------------------------------------------------------------------------


class Rombo(QWidget, PiezaC):
    """Rombo relleno o hueco, del color de una clave de la paleta (o un hex)."""

    def __init__(self, lado: int = 8, tinta: str = "acento", relleno: bool = True, parent=None):
        super().__init__(parent)
        transparente(self)
        self.lado, self.tinta, self.relleno = lado, tinta, relleno
        self.refrescar_estilo()

    def refrescar_estilo(self) -> None:
        lado = px(self.lado, False) + 2
        self.setFixedSize(lado, lado)
        self.update()

    def poner(self, tinta: str | None = None, relleno: bool | None = None) -> None:
        if tinta is not None:
            self.tinta = tinta
        if relleno is not None:
            self.relleno = relleno
        self.update()

    def paintEvent(self, _evento):  # noqa: N802 - firma de Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width() - 1, self.height() - 1
        c = color(self.tinta)
        p.setPen(QPen(c, 1.2))
        p.setBrush(c if self.relleno else Qt.NoBrush)
        p.drawPolygon(_rombo_poligono(w / 2 + 0.5, h / 2 + 0.5, w / 2))
        p.end()


class Filete(QWidget, PiezaC):
    """Linea dorada apagada con un rombo en el centro: separa la cabecera del contenido."""

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.setFixedHeight(12)

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, y = self.width(), 6
        p.setPen(QPen(color("acento_tenue"), 1))
        p.drawLine(0, y, w // 2 - 14, y)
        p.drawLine(w // 2 + 14, y, w, y)
        p.setPen(QPen(color("acento"), 1.2))
        p.setBrush(color("fondo"))
        p.drawPolygon(QPolygonF([QPointF(w / 2, 1), QPointF(w / 2 + 8, y), QPointF(w / 2, 11),
                                 QPointF(w / 2 - 8, y)]))
        p.end()


class PanelC(QFrame, PiezaC):
    """Panel con dos esquinas cortadas, filete fino y un remate dorado en las esquinas.

    `titulo` pone la cabecera (rombo + rotulo en mayusculas); el contenido va en `capa`.
    `fondo`/`borde` son claves de la paleta. `marcado` = borde en color de acento (la
    casilla elegida). Con `clicable`, emite `pulsado` al hacer clic en cualquier parte.
    """

    pulsado = Signal()

    def __init__(self, titulo: str | None = None, remate: bool = True, fondo: str = "panel",
                 borde: str = "borde", chaflan: int = CHAFLAN, clicable: bool = False, parent=None):
        super().__init__(parent)
        transparente(self)
        self._remate, self._fondo, self._borde, self._chaflan = remate, fondo, borde, chaflan
        self._marcado = False
        self._clicable = clicable
        if clicable:
            self.setCursor(Qt.PointingHandCursor)
        self.capa = QVBoxLayout(self)
        self.capa.setContentsMargins(px(ESPACIO["panel_h"], False), px(ESPACIO["panel_v"], False),
                                     px(ESPACIO["panel_h"], False), px(ESPACIO["panel_v"] + 2, False))
        self.capa.setSpacing(px(ESPACIO["fila"], False))
        self.rotulo: EtiquetaC | None = None
        self.cabecera: QHBoxLayout | None = None
        if titulo is not None:
            self.rotulo = EtiquetaC(titulo, "rotulo", mayus=True)
            self.cabecera = fila(Rombo(8, "acento"), self.rotulo, None, espacio=8)
            self.capa.addLayout(self.cabecera)

    def poner_titulo(self, texto: str) -> None:
        if self.rotulo is not None:
            self.rotulo.setText(texto)

    def poner_marcado(self, marcado: bool) -> None:
        self._marcado = marcado
        self.update()

    def mouseReleaseEvent(self, evento):  # noqa: N802
        if self._clicable and evento.button() == Qt.LeftButton and self.rect().contains(evento.position().toPoint()):
            self.pulsado.emit()
            evento.accept()
            return
        super().mouseReleaseEvent(evento)

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        corte = px(self._chaflan, False)
        camino = ruta_chaflan(r, corte)
        p.fillPath(camino, color(self._fondo))
        p.setPen(QPen(color("acento" if self._marcado else self._borde), 1))
        p.drawPath(camino)
        if self._remate or self._marcado:
            largo = min(46, r.width() / 4)
            p.setPen(QPen(color("acento"), 2))
            p.drawLine(QPointF(r.left() + corte, r.top() + 1), QPointF(r.left() + corte + largo, r.top() + 1))
            p.drawLine(QPointF(r.right() - corte - largo, r.bottom() - 1), QPointF(r.right() - corte, r.bottom() - 1))
        p.end()


class BotonC(QPushButton, PiezaC):
    """Boton con una esquina cortada: relleno de acento si es el principal, filete si no.

    Es un QPushButton normal (clicked, setText, checkable, teclado...). `icono` es una
    clave de `ICONO`; `pista` es un texto pequeno a la derecha (un atajo: "Ctrl+M").
    Marcado (checkable) se pinta como principal. `solo_icono` esconde el texto (sigue en
    `text()` y conviene repetirlo en el tooltip): para cabeceras estrechas.
    """

    def __init__(self, texto: str = "", principal: bool = False, icono: str | None = None,
                 pista: str = "", tam: int = 12, tinta: str = "acento", parent=None):
        super().__init__(texto, parent)
        transparente(self)
        self.principal = principal
        self.icono = icono
        self.pista = pista
        self.tam = tam
        self.tinta = tinta
        self.solo_icono = False
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def poner_pista(self, pista: str) -> None:
        self.pista = pista
        self.updateGeometry()
        self.update()

    def poner_solo_icono(self, solo: bool) -> None:
        self.solo_icono = bool(solo) and bool(self.icono)
        self.updateGeometry()
        self.update()

    def _fuentes(self) -> tuple[QFont, QFont, QFont]:
        return fuente("dato", self.tam, 600), fuente("pequeno"), fuente_iconos(self.tam + 3)

    def _trozos(self) -> list[tuple[str, QFont, str, int]]:
        """(tipo, fuente, texto, ancho) de lo que se pinta, de izquierda a derecha."""
        f_texto, f_pista, f_icono = self._fuentes()
        trozos = []
        if self.icono:
            glifo = ICONO.get(self.icono, self.icono)
            trozos.append(("icono", f_icono, glifo, QFontMetrics(f_icono).horizontalAdvance(glifo)))
        texto = "" if self.solo_icono else self.text().upper()
        if texto:
            trozos.append(("texto", f_texto, texto, QFontMetrics(f_texto).horizontalAdvance(texto)))
        if self.pista and not self.solo_icono:
            trozos.append(("pista", f_pista, self.pista, QFontMetrics(f_pista).horizontalAdvance(self.pista)))
        return trozos

    def _ancho_contenido(self, trozos) -> int:
        huecos = {"texto": px(8, False), "pista": px(12, False)}
        return sum(a for *_x, a in trozos) + sum(huecos.get(t, 0) for t, *_x in trozos[1:])

    def sizeHint(self) -> QSize:  # noqa: N802
        trozos = self._trozos()
        lado = px(10 if len(trozos) == 1 and trozos[0][0] == "icono" else 14, False)
        return QSize(self._ancho_contenido(trozos) + 2 * lado, px(self.tam, True) + px(16, False))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        camino = ruta_chaflan(r, px(CHAFLAN_BOTON, False), "d")
        base = color(self.tinta)
        lleno = self.principal or self.isChecked()
        if not self.isEnabled():
            base = color("tenue")
        if lleno:
            c = QColor(base)
            if self.underMouse() and self.isEnabled():
                c = c.lighter(112)
            p.fillPath(camino, c)
            tinta = color("acento_texto")
        else:
            c = QColor(base)
            c.setAlpha(55 if (self.underMouse() and self.isEnabled()) else 22)
            p.fillPath(camino, c)
            c.setAlpha(190 if self.hasFocus() else 150)
            p.setPen(QPen(c, 1))
            p.drawPath(camino)
            tinta = base
        trozos = self._trozos()
        x = (self.width() - self._ancho_contenido(trozos)) / 2
        huecos = {"texto": px(8, False), "pista": px(12, False)}
        for i, (tipo, f, texto, ancho) in enumerate(trozos):
            if i:
                x += huecos.get(tipo, 0)
            p.setFont(f)
            p.setPen(tinta if tipo != "pista" else (color("acento_texto") if lleno else color("suave")))
            p.drawText(QRectF(x, 0, ancho + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, texto)
            x += ancho
        p.end()

    def enterEvent(self, evento):  # noqa: N802
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.update()
        super().leaveEvent(evento)


# -- menus -------------------------------------------------------------------------------


class _EntradaMenu(QAbstractButton, PiezaC):
    """Una opcion del menu superior (grande, rombo encima de la activa) o de una fila de
    sub-pestanas (mas pequena, subrayado dorado en la activa)."""

    def __init__(self, clave: str, texto: str, grande: bool, parent=None):
        super().__init__(parent)
        transparente(self)
        self.clave = clave
        self.grande = grande
        self.menuda = False  # menu superior con la letra de las sub-pestanas (ventana estrecha)
        self.setCheckable(True)
        self.setText(texto)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)

    def _fuente(self) -> QFont:
        peso = 600 if self.isChecked() else 500
        return fuente("dato", TAM["seccion"] if self.grande and not self.menuda else TAM["normal"], peso)

    def _f(self) -> QFont:
        f = self._fuente()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        return f

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self._f())
        ancho = fm.horizontalAdvance(self.text().upper()) + px(4, False)
        if self.grande:
            return QSize(ancho, fm.height() + px(12, False))
        return QSize(ancho, fm.height() + px(8, False))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        activa = self.isChecked()
        if activa:
            tinta = color("acento" if self.grande else "texto")
        elif self.underMouse():
            tinta = color("texto")
        else:
            tinta = color("suave")
        f = self._f()
        fm = QFontMetrics(f)
        p.setFont(f)
        p.setPen(tinta)
        if self.grande:
            arriba = px(12, False)
            p.drawText(QRectF(0, arriba, self.width(), fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       self.text().upper())
            if activa:
                medio = px(3, False)
                p.setPen(Qt.NoPen)
                p.setBrush(color("acento"))
                p.drawPolygon(_rombo_poligono(self.width() / 2, medio + 1, medio))
        else:
            p.drawText(QRectF(0, 0, self.width(), fm.height() + px(2, False)), Qt.AlignLeft | Qt.AlignVCenter,
                       self.text().upper())
            if activa:
                p.fillRect(QRectF(0, self.height() - 2, self.width(), 2), color("acento"))
        p.end()

    def enterEvent(self, evento):  # noqa: N802
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.update()
        super().leaveEvent(evento)


class SubPestanasC(QWidget):
    """Fila de opciones exclusivas: el menu superior (`grande=True`) o las sub-pestanas de
    una seccion. `cambiada(clave)` al pulsar; `poner_activa(clave)` no emite nada.

    `derecha` es un QHBoxLayout al final de la fila para los controles propios de cada
    seccion (filtros, botones...).
    """

    cambiada = Signal(str)

    def __init__(self, opciones: list[tuple[str, str]] | None = None, grande: bool = False, parent=None):
        super().__init__(parent)
        transparente(self)
        self.grande = grande
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._entradas: dict[str, _EntradaMenu] = {}
        self._capa = QHBoxLayout(self)
        self._capa.setContentsMargins(0, 0, 0, 0)
        self._capa.setSpacing(px(36 if grande else 26, False))
        self._fin = QHBoxLayout()
        self._fin.setContentsMargins(0, 0, 0, 0)
        self._capa.addStretch(1)
        self.derecha = QHBoxLayout()
        self.derecha.setSpacing(px(8, False))
        self._capa.addLayout(self.derecha)
        for clave, texto in opciones or []:
            self.anadir(clave, texto)

    def anadir(self, clave: str, texto: str) -> _EntradaMenu:
        entrada = _EntradaMenu(clave, texto, self.grande)
        entrada.clicked.connect(lambda _=False, c=clave: self._pulsada(c))
        self._grupo.addButton(entrada)
        self._entradas[clave] = entrada
        self._capa.insertWidget(len(self._entradas) - 1, entrada, 0, Qt.AlignBottom)
        if len(self._entradas) == 1:
            entrada.setChecked(True)
        return entrada

    def _pulsada(self, clave: str) -> None:
        self.cambiada.emit(clave)

    def poner_activa(self, clave: str) -> None:
        entrada = self._entradas.get(clave)
        if entrada is not None and not entrada.isChecked():
            entrada.setChecked(True)
        for e in self._entradas.values():
            e.updateGeometry()
            e.update()

    def activa(self) -> str | None:
        return next((c for c, e in self._entradas.items() if e.isChecked()), None)

    def claves(self) -> list[str]:
        return list(self._entradas)

    def entrada(self, clave: str) -> _EntradaMenu | None:
        return self._entradas.get(clave)

    def poner_texto(self, clave: str, texto: str) -> None:
        entrada = self._entradas.get(clave)
        if entrada is not None:
            entrada.setText(texto)
            entrada.updateGeometry()

    def compactar(self, compacto: bool, menuda: bool = False) -> None:
        """Cuando no caben (ventana estrecha): menos aire entre opciones y, si aun asi no
        caben, letra mas pequena."""
        self._compacto, self._menuda = compacto, menuda
        self._capa.setSpacing(px((14 if compacto else 36) if self.grande else 26, False))
        for e in self._entradas.values():
            e.menuda = menuda
            e.updateGeometry()
            e.update()

    def refrescar_estilo(self) -> None:
        self.compactar(getattr(self, "_compacto", False), getattr(self, "_menuda", False))
        for e in self._entradas.values():
            e.refrescar_estilo()


# -- insignias, teclas, barras --------------------------------------------------------------


class Insignia(QLabel, PiezaC):
    """Etiqueta con recuadro (BÓVEDA, SE FARMEA, WARFRAME): texto en mayusculas del color
    dado sobre un fondo muy tenue del mismo color; `relleno` = fondo lleno."""

    def __init__(self, texto: str, tinta: str = "acento", relleno: bool = False, tam: int = 11, parent=None):
        super().__init__(parent)
        self.tinta, self.relleno, self.tam = tinta, relleno, tam
        f = self.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.3)
        self.setFont(f)
        self.setText(texto)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.refrescar_estilo()

    def setText(self, texto: str) -> None:  # noqa: N802
        super().setText((texto or "").upper())

    def poner(self, texto: str | None = None, tinta: str | None = None) -> None:
        if texto is not None:
            self.setText(texto)
        if tinta is not None:
            self.tinta = tinta
        self.refrescar_estilo()

    def refrescar_estilo(self) -> None:
        c = color(self.tinta)
        rgb = f"{c.red()},{c.green()},{c.blue()}"
        fondo = c.name() if self.relleno else f"rgba({rgb},30)"
        letra = hex_de("acento_texto") if self.relleno else c.name()
        self.setStyleSheet(
            f"background: {fondo}; color: {letra}; border: 1px solid rgba({rgb},150);"
            f" font-family: '{TITULAR}'; font-size: {px(self.tam)}px; font-weight: 600;"
            f" padding: {px(2, False)}px {px(7, False)}px;"
        )


class EtiquetaEra(QLabel, PiezaC):
    """El nombre de una era de reliquia en mayusculas (LITH, NEO). Por defecto en el color
    secundario del tema, como en la maqueta; `por_era=True` usa el color propio de cada era."""

    def __init__(self, era: str, por_era: bool = False, tam: int = 13, parent=None):
        super().__init__((era or "").upper(), parent)
        self.era, self.por_era, self.tam = era, por_era, tam
        f = self.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        self.setFont(f)
        self.refrescar_estilo()

    def refrescar_estilo(self) -> None:
        tinta = COLOR_ERA.get(self.era, hex_de("secundario")) if self.por_era else hex_de("secundario")
        self.setStyleSheet(f"color: {tinta}; background: transparent; font-family: '{TITULAR}';"
                           f" font-size: {px(self.tam)}px; font-weight: 600;")


class RombosDisposicion(QWidget, PiezaC):
    """Cinco rombos, `n` llenos: la disposicion de un arma para los agrietados."""

    def __init__(self, n: int = 0, total: int = 5, tinta: str = "acento", lado: int = 11, parent=None):
        super().__init__(parent)
        transparente(self)
        self.n, self.total, self.tinta, self.lado = n, total, tinta, lado
        self.refrescar_estilo()

    def poner(self, n: int) -> None:
        self.n = max(0, min(self.total, int(n)))
        self.update()

    def refrescar_estilo(self) -> None:
        lado = px(self.lado, False)
        self.setFixedSize(self.total * (lado + 6), lado + 4)
        self.update()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        lado = px(self.lado, False)
        medio = lado / 2
        lleno, vacio = color(self.tinta), color("tenue")
        for i in range(self.total):
            cx, cy = i * (lado + 6) + medio + 1, medio + 2
            p.setPen(QPen(lleno if i < self.n else vacio, 1.2))
            p.setBrush(lleno if i < self.n else Qt.NoBrush)
            p.drawPolygon(_rombo_poligono(cx, cy, medio))
        p.end()


class Tecla(QLabel, PiezaC):
    """Una tecla en su recuadro de acento ("Esc", "W", "+")."""

    def __init__(self, tecla: str, parent=None):
        super().__init__(tecla.upper(), parent)
        self.refrescar_estilo()

    def refrescar_estilo(self) -> None:
        self.setStyleSheet(
            f"background: {hex_de('acento')}; color: {hex_de('acento_texto')}; border-radius: 3px;"
            f" font-family: '{TITULAR}'; font-size: {px(12)}px; font-weight: 700;"
            f" padding: {px(1, False)}px {px(7, False)}px;"
        )


class BarraTeclas(QWidget):
    """Pie de pagina como el de los menus del juego: un filete y teclas con su accion,
    a la derecha. `anadir(tecla, texto)` devuelve la etiqueta del texto (para retraducir)."""

    def __init__(self, pares: list[tuple[str, str]] | None = None, parent=None):
        super().__init__(parent)
        transparente(self)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(px(4, False))
        capa.addWidget(Filete())
        self._fila = fila(None, espacio=px(24, False))
        capa.addLayout(self._fila)
        self.textos: dict[str, EtiquetaC] = {}
        for tecla, texto in pares or []:
            self.anadir(tecla, texto)

    def anadir(self, tecla: str, texto: str) -> EtiquetaC:
        etiqueta = EtiquetaC(texto, "dato", mayus=True)
        par = QWidget()
        par.setLayout(fila(Tecla(tecla), etiqueta, espacio=7))
        self._fila.addWidget(par)
        self.textos[tecla] = etiqueta
        return etiqueta


class Interruptor(QAbstractButton, PiezaC):
    """Interruptor si/no con un rombo que se desliza (Incluir lo de la boveda...).
    Es un boton marcable: `toggled(bool)`, `isChecked()`, `setChecked()`."""

    def __init__(self, marcado: bool = False, parent=None):
        super().__init__(parent)
        transparente(self)
        self.setCheckable(True)
        self.setChecked(marcado)
        self.setCursor(Qt.PointingHandCursor)
        self.refrescar_estilo()

    def refrescar_estilo(self) -> None:
        self.setFixedSize(px(38, False), px(20, False))
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(px(38, False), px(20, False))

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        on = self.isChecked()
        acento = color("acento")
        r = QRectF(0.5, h * 0.18, w - 1, h * 0.64)
        p.setPen(QPen(acento if on else color("tenue"), 1))
        fondo = QColor(acento)
        fondo.setAlpha(60 if on else 0)
        p.setBrush(fondo)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        medio = h / 2 - 1
        x = w - medio - 1 if on else medio + 1
        p.setPen(Qt.NoPen)
        p.setBrush(acento if on else color("suave"))
        p.drawPolygon(_rombo_poligono(x, h / 2, medio))
        p.end()


class BarraFina(QWidget, PiezaC):
    """Barra de progreso fina (casillas de metas): `progreso` de 0 a 1."""

    def __init__(self, progreso: float = 0.0, tinta: str = "acento", alto: int = 4, parent=None):
        super().__init__(parent)
        transparente(self)
        self.progreso, self.tinta, self.alto = 0.0, tinta, alto
        self.poner(progreso)
        self.refrescar_estilo()

    def poner(self, progreso: float) -> None:
        self.progreso = max(0.0, min(1.0, float(progreso or 0)))
        self.update()

    def refrescar_estilo(self) -> None:
        self.setFixedHeight(px(self.alto, False))
        self.update()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, color("borde"))
        # Siempre un poquito de barra: sin nada no se entiende que es una barra.
        p.fillRect(0, 0, max(2, int(w * self.progreso)), h, color(self.tinta))
        p.end()


class Pedestal(QWidget, PiezaC):
    """Circulo de luz tenue y una peana bajo la imagen del objeto, como en el arsenal."""

    def __init__(self, lado: int = 240, parent=None):
        super().__init__(parent)
        transparente(self)
        self.lado = lado
        self._mapa: QPixmap | None = None
        self.refrescar_estilo()

    def refrescar_estilo(self) -> None:
        # Crece hasta `lado` y encoge hasta la mitad si la ventana es pequena.
        lado = px(self.lado, False)
        self.setMinimumSize(lado // 2, lado // 2)
        self.setMaximumSize(lado, lado)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        lado = px(self.lado, False)
        return QSize(lado, lado)

    def poner_imagen(self, mapa: QPixmap | None) -> None:
        self._mapa = mapa if mapa is not None and not mapa.isNull() else None
        self.update()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        lado = min(self.width(), self.height())
        p.translate((self.width() - lado) / 2, (self.height() - lado) / 2)
        w = h = lado
        luz = color("acento")
        g = QRadialGradient(QPointF(w / 2, h * 0.55), w * 0.5)
        luz.setAlpha(70)
        g.setColorAt(0, luz)
        luz.setAlpha(0)
        g.setColorAt(1, luz)
        p.fillRect(QRectF(0, 0, w, h), g)
        p.setPen(QPen(color("acento_tenue"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(w * 0.12, h * 0.86, w * 0.76, h * 0.1))
        if self._mapa is not None:
            lado = int(w * 0.74)
            mapa = self._mapa.scaled(lado, lado, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(int((w - mapa.width()) / 2), int(h * 0.88 - mapa.height()), mapa)
        else:
            # Sin imagen (aun descargandose o sin ella): un rombo tenue en su sitio.
            p.setPen(QPen(color("borde"), 1.5))
            p.setBrush(color("panel2"))
            p.drawPolygon(_rombo_poligono(w / 2, h * 0.5, w * 0.18))
        p.end()


class CasillaC(PanelC):
    """Casilla de arsenal: imagen, nombre, "0 de 1" y barra de progreso. Clicable."""

    def __init__(self, nombre: str = "", sub: str = "", progreso: float = 0.0, marcada: bool = False,
                 lado_imagen: int = 58, parent=None):
        super().__init__(remate=False, fondo="panel2", borde="borde", clicable=True, parent=parent)
        self.poner_marcado(marcada)
        m = px(10, False)
        self.capa.setContentsMargins(m, m, m, m)
        self.capa.setSpacing(px(4, False))
        self.imagen = QLabel()
        self.imagen.setAlignment(Qt.AlignCenter)
        self.imagen.setFixedHeight(px(lado_imagen, False))
        self.imagen.setStyleSheet("background: transparent;")
        self._lado = lado_imagen
        self.nombre = EtiquetaC(nombre, "fuerte", envolver=True)
        self.nombre.setAlignment(Qt.AlignCenter)
        self.sub = EtiquetaC(sub, "pequeno")
        self.sub.setAlignment(Qt.AlignCenter)
        self.barra = BarraFina(progreso)
        self.capa.addWidget(self.imagen)
        self.capa.addWidget(self.nombre)
        self.capa.addWidget(self.sub)
        self.capa.addStretch(1)
        self.capa.addWidget(self.barra)

    def poner_imagen(self, mapa: QPixmap | None) -> None:
        if mapa is None or mapa.isNull():
            self.imagen.setText("◇")
            self.imagen.setStyleSheet(f"background: transparent; color: {hex_de('tenue')}; font-size: {px(28)}px;")
            return
        lado = px(self._lado, False)
        self.imagen.setStyleSheet("background: transparent;")
        self.imagen.setPixmap(mapa.scaled(lado, lado, Qt.KeepAspectRatio, Qt.SmoothTransformation))


# -- controles de formulario (MIS METAS) -------------------------------------------------------


class CasillaRombo(QAbstractButton, PiezaC):
    """Casilla marcable con un rombo: hueco sin marcar, lleno (de acento) marcada.

    Es un boton marcable de verdad (`toggled`, `isChecked`, `setChecked`, `text`). `extra`
    es un texto pequeno pegado a la derecha ("×2"). Sin marcar, el texto va apagado y
    marcado, en claro; `tinta` lo fuerza (una clave de la paleta: "ok" = ya conseguido).
    """

    def __init__(self, texto: str = "", marcada: bool = False, extra: str = "", tinta: str | None = None,
                 tam: int = 13, parent=None):
        super().__init__(parent)
        transparente(self)
        self.extra, self.tinta, self.tam = extra, tinta, tam
        self.setCheckable(True)
        self.setChecked(marcada)
        self.setText(texto)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def poner(self, texto: str | None = None, extra: str | None = None, tinta: str | None = "") -> None:
        """Cambia texto, extra o tinta (tinta None = la de por defecto; "" = no tocarla)."""
        if texto is not None:
            self.setText(texto)
        if extra is not None:
            self.extra = extra
        if tinta != "":
            self.tinta = tinta
        self.updateGeometry()
        self.update()

    def _medidas(self) -> tuple[QFont, QFont, int]:
        return fuente("normal", self.tam), fuente("pequeno"), px(10, False) + 2

    def sizeHint(self) -> QSize:  # noqa: N802
        f, f_extra, lado = self._medidas()
        ancho = lado + px(8, False) + QFontMetrics(f).horizontalAdvance(self.text()) + 4
        if self.extra:
            ancho += px(12, False) + QFontMetrics(f_extra).horizontalAdvance(self.extra)
        return QSize(ancho, QFontMetrics(f).height() + px(4, False))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        f, _fe, lado = self._medidas()
        return QSize(lado + px(40, False), QFontMetrics(f).height() + px(4, False))

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f, f_extra, lado = self._medidas()
        marcada = self.isChecked()
        encima = self.underMouse() and self.isEnabled()
        tinta_rombo = color("acento") if marcada else color("texto" if encima else "suave")
        p.setPen(QPen(tinta_rombo, 1.2))
        p.setBrush(tinta_rombo if marcada else Qt.NoBrush)
        medio = (lado - 2) / 2
        p.drawPolygon(_rombo_poligono(medio + 1, self.height() / 2, medio))
        x = lado + px(8, False)
        derecha = self.width()
        if self.extra:
            p.setFont(f_extra)
            p.setPen(color("suave"))
            ancho_extra = QFontMetrics(f_extra).horizontalAdvance(self.extra)
            p.drawText(QRectF(derecha - ancho_extra - 2, 0, ancho_extra + 2, self.height()),
                       Qt.AlignVCenter | Qt.AlignRight, self.extra)
            derecha -= ancho_extra + px(10, False)
        tinta = self.tinta or ("texto" if (marcada or encima) else "suave")
        if not self.isEnabled():
            tinta = "tenue"
        p.setFont(f)
        p.setPen(color(tinta))
        visible = QFontMetrics(f).elidedText(self.text(), Qt.ElideRight, max(10, int(derecha - x)))
        p.drawText(QRectF(x, 0, derecha - x, self.height()), Qt.AlignVCenter | Qt.AlignLeft, visible)
        p.end()

    def enterEvent(self, evento):  # noqa: N802
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.update()
        super().leaveEvent(evento)


class DesplegableC(QComboBox, PiezaC):
    """QComboBox con forma de boton C: esquina cortada, filete de acento, flecha y el
    texto elegido en mayusculas. Todo lo demas es un QComboBox normal (addItem,
    currentData, findData, currentIndexChanged...)."""

    def __init__(self, tam: int = 12, parent=None):
        super().__init__(parent)
        transparente(self)
        self.tam = tam
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def _fuentes(self) -> tuple[QFont, QFont]:
        return fuente("dato", self.tam, 600), fuente_iconos(self.tam)

    def sizeHint(self) -> QSize:  # noqa: N802
        f, _fi = self._fuentes()
        fm = QFontMetrics(f)
        ancho = max((fm.horizontalAdvance(self.itemText(i).upper()) for i in range(self.count())), default=px(60, False))
        return QSize(ancho + px(14, False) * 2 + px(20, False), px(self.tam, True) + px(16, False))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        camino = ruta_chaflan(r, px(CHAFLAN_BOTON, False), "d")
        base = color("acento") if self.isEnabled() else color("tenue")
        c = QColor(base)
        c.setAlpha(55 if (self.underMouse() and self.isEnabled()) else 22)
        p.fillPath(camino, c)
        c.setAlpha(190 if self.hasFocus() else 150)
        p.setPen(QPen(c, 1))
        p.drawPath(camino)
        f, fi = self._fuentes()
        x = px(12, False)
        p.setFont(fi)
        p.setPen(base)
        p.drawText(QRectF(x, 0, px(14, False), self.height()), Qt.AlignCenter, ICONO["abajo"])
        x += px(20, False)
        p.setFont(f)
        texto = QFontMetrics(f).elidedText(self.currentText().upper(), Qt.ElideRight,
                                           max(10, int(self.width() - x - px(8, False))))
        p.drawText(QRectF(x, 0, self.width() - x, self.height()), Qt.AlignVCenter | Qt.AlignLeft, texto)
        p.end()

    def enterEvent(self, evento):  # noqa: N802
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.update()
        super().leaveEvent(evento)


class InterruptorTexto(Interruptor):
    """`Interruptor` con su texto al lado ("Incluir lo que esta en boveda")."""

    def __init__(self, texto: str = "", marcado: bool = False, parent=None):
        super().__init__(marcado, parent)
        self.setText(texto)

    def refrescar_estilo(self) -> None:
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(fuente("normal", 13))
        return QSize(px(38, False) + px(8, False) + fm.horizontalAdvance(self.text()) + 4,
                     max(px(20, False), fm.height() + px(2, False)))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = px(38, False), px(20, False)
        arriba = (self.height() - h) / 2
        on = self.isChecked()
        acento = color("acento") if self.isEnabled() else color("tenue")
        r = QRectF(0.5, arriba + h * 0.18, w - 1, h * 0.64)
        p.setPen(QPen(acento if on else color("tenue"), 1))
        fondo = QColor(acento)
        fondo.setAlpha(60 if on else 0)
        p.setBrush(fondo)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        medio = h / 2 - 1
        x = w - medio - 1 if on else medio + 1
        p.setPen(Qt.NoPen)
        p.setBrush(acento if on else color("suave"))
        p.drawPolygon(_rombo_poligono(x, arriba + h / 2, medio))
        p.setFont(fuente("normal", 13))
        p.setPen(color("texto" if self.isEnabled() else "suave"))
        x = w + px(8, False)
        p.drawText(QRectF(x, 0, self.width() - x, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class Linea(QWidget, PiezaC):
    """Raya fina horizontal que separa bloques dentro de un panel (cabecera de una tabla,
    pie de un menu). `tinta` es una clave de la paleta ("borde" o "acento_tenue")."""

    def __init__(self, tinta: str = "borde", parent=None):
        super().__init__(parent)
        transparente(self)
        self.tinta = tinta
        self.setFixedHeight(5)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setPen(QPen(color(self.tinta), 1))
        p.drawLine(0, 2, self.width(), 2)
        p.end()


class BotonGlifo(QPushButton, PiezaC):
    """Boton plano con un solo glifo de la fuente de iconos (marcar hecho, editar, quitar,
    desplegar). `text()` no se pinta: sirve de nombre accesible y de tooltip si no hay otro."""

    def __init__(self, glifo: str, texto: str = "", tinta: str = "suave", tam: int = 14, parent=None):
        super().__init__(texto, parent)
        transparente(self)
        self.glifo, self.tinta, self.tam = ICONO.get(glifo, glifo), tinta, tam
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.refrescar_estilo()

    def poner_glifo(self, glifo: str) -> None:
        self.glifo = ICONO.get(glifo, glifo)
        self.update()

    def refrescar_estilo(self) -> None:
        lado = px(self.tam + 12, False)
        self.setFixedSize(lado, lado)
        self.update()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            tinta = color("tenue")
        elif self.underMouse():
            tinta = color("texto")
        else:
            tinta = color(self.tinta)
        p.setFont(fuente_iconos(self.tam))
        p.setPen(tinta)
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, self.glifo)
        p.end()

    def enterEvent(self, evento):  # noqa: N802
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.update()
        super().leaveEvent(evento)
