"""Bienvenida: la primera pantalla de Farmadex, antes de tocar nada.

Una capa encima de la ventana del overlay (como la guia) con una tarjeta en el
centro y cinco apartados a la izquierda: que es Farmadex, lo basico paso a paso,
si es seguro, preguntas frecuentes y agradecimientos con los enlaces del autor.

Estilo C (maqueta C_bienvenida.png): tarjeta con esquinas cortadas y filete de acento,
titulo grande con su rombo, filetes con rombo arriba y abajo, apartados en una columna
(rombo lleno en el activo y en los ya vistos) y al pie "Atras · 2 DE 5 · Siguiente".
Lo basico va en pasos numerados; el cuadro de "como empezar" sale en ese apartado (solo
el aviso) y en el ultimo (con los dos botones).

La primera vez es obligatoria: sin boton de cerrar y sin Escape; se sale con
"Empezar" desde el ultimo apartado. Sale tambien una vez a quien actualiza desde
una version que no la tenia (la marca `bienvenida_vista` no existia en su
config.json). Despues se abre cuando se quiera desde Ajustes > Ayuda o desde
Acerca de, y entonces si se puede cerrar en cualquier momento.

Nunca salta sola en las pruebas ni en ningun arranque sin pantalla de verdad
(plataforma "offscreen"), ni con FARMADEX_SIN_BIENVENIDA puesta.
"""

from __future__ import annotations

import html
import os

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import NOMBRE_APP
from ..idiomas import t
from .acerca_de import (
    URL_AVISOS,
    URL_REPOSITORIO,
    _enlace,
    enlace_discord,
    frase,
    html_secciones,
    preguntas_frecuentes,
    secciones_seguridad,
    texto_autor,
)
from .estilo_c import (
    BotonC,
    BotonGlifo,
    EtiquetaC,
    Filete,
    PanelC,
    PiezaC,
    Rombo,
    color,
    fila,
    fuente,
    px,
    transparente,
)
from .widgets import PALETA

CLAVE_VISTA = "bienvenida_vista"
ANCHO_MAXIMO = 940
ALTO_MAXIMO = 600
MARGEN = 16
GLIFO_ATRAS = ""
APARTADO_BASICO = 1  # "Lo basico, paso a paso": el que lleva el aviso de como empezar


def toca_bienvenida(config: dict) -> bool:
    """Si hay que ensenarla sola al abrir: nunca vista y con una pantalla de verdad."""
    if config.get(CLAVE_VISTA):
        return False
    if os.environ.get("FARMADEX_SIN_BIENVENIDA"):
        return False
    app = QApplication.instance()
    return not (app is not None and app.platformName() == "offscreen")


def _tecla_html(texto: str) -> str:
    """Un atajo como tecla de acento dentro de un texto (Ctrl+Alt+W)."""
    p = PALETA
    return (f"<span style='background: {p['acento']}; color: {p['acento_texto']}; font-weight: 700;"
            f" font-family: Bahnschrift;'>&nbsp;{html.escape(texto.upper())}&nbsp;</span>")


def pasos_basicos(atajo: str) -> list[str]:
    """Los ocho pasos de "Lo basico", en HTML y en el idioma activo."""
    return [
        frase("Ábrelo encima del juego con {atajo}, y escóndelo con Escape. Cuando no lo ves, sigue "
              "esperando en los iconos junto al reloj de Windows.", atajo=_tecla_html(atajo)),
        frase("Pon Warframe en Ventana sin bordes (Opciones > Pantalla). En pantalla completa "
              "exclusiva no se puede ver nada encima del juego."),
        frase("En Buscar escribe cualquier cosa, aunque sea con faltas: te dice dónde se consigue, con "
              "qué probabilidad y cuánto se tarda en cada sitio."),
        frase("Con \"+ Objetivo\" lo apuntas. En el Tablero ves tu siguiente paso, y en Mis metas cuánto "
              "te falta y dónde farmear cada cosa ahora mismo."),
        frase("Al abrir una reliquia, Farmadex lee solo las recompensas y te marca la que más te "
              "conviene."),
        frase("En Mundo tienes lo que pasa ahora en el juego: fisuras, ciclos, invasiones, Baro "
              "Ki'Teer... Y si quieres, Windows te avisa cuando pase algo que te interesa."),
        frase("En Herramientas, Build lee los mods de una build desde la pantalla del juego, y Agrietados "
              "te dice si un mod agrietado es bueno y cuánto se pide por uno parecido."),
        frase("En Ajustes, con las secciones a la izquierda, cambias atajos, colores, tamaño de letra "
              "e idioma."),
    ]


def _apartados(atajo: str) -> list[tuple[str, str]]:
    """(titulo del apartado, HTML del contenido), en el idioma activo. El de "Lo basico"
    lleva solo la entradilla: los pasos se pintan aparte, numerados (`pasos_basicos`)."""
    p = PALETA
    que_es = (
        f"<p>{frase('Farmadex es un ayudante para Warframe que se abre encima del juego. Sirve para no '
                    'tener que salir a la wiki: te dice dónde conseguir cada cosa y cuánto se tarda, '
                    'apunta lo que quieres farmear, lee las recompensas de las reliquias y te cuenta '
                    'qué está pasando ahora en el juego.')}</p>"
        f"<p>{frase('Lo hace vaas, un jugador, en su tiempo libre. Es gratis, sin anuncios, y el código es '
                    'público.')}</p>"
        f"<p style='color: {p['suave']};'>{frase('Esta bienvenida sale sola solo esta vez. Puedes volver a '
                                                 'verla cuando quieras en Ajustes > Ayuda.')}</p>"
    )
    basico = f"<p style='color: {p['suave']};'>{frase('Lo que necesitas para empezar, en ocho pasos:')}</p>"
    seguro = html_secciones(secciones_seguridad(), nivel="h4")
    faq = html_secciones(preguntas_frecuentes(atajo), nivel="h4")
    gracias = (
        f"<p>{frase('Gracias por probar Farmadex.')}</p>"
        f"<p>{frase('Los datos salen del trabajo de la comunidad: WFCD (catálogo de objetos y estado del '
                    'mundo), las tablas de drops oficiales de Digital Extremes, la wiki de Warframe y '
                    'warframe.market.')}</p>"
        f"<p>{frase('Y gracias a quienes lo prueban y mandan sus comentarios: mucho de lo que ves ha '
                    'salido de ahí.')}</p>"
        f"<p>{texto_autor()}</p>"
        f"<p>{frase('Dudas, fallos o ideas: escribe en el Discord de Farmadex ({discord}), en el chat '
                    'del canal o abre un aviso en {avisos}.',
                    discord=enlace_discord(), avisos=_enlace(URL_AVISOS, 'GitHub'))}</p>"
        f"<p>{frase('Código y descargas: {enlace}', enlace=_enlace(URL_REPOSITORIO, URL_REPOSITORIO.removeprefix('https://')))}</p>"
        f"<p style='color: {p['suave']};'>{frase('Farmadex no está afiliado a Digital Extremes ni tiene su '
                                                 'respaldo. Warframe y todo su contenido son de Digital '
                                                 'Extremes.')}</p>"
    )
    return [
        (t("Qué es Farmadex"), que_es),
        (t("Lo básico, paso a paso"), basico),
        (t("¿Es seguro?"), seguro),
        (t("Preguntas frecuentes"), faq),
        (t("Gracias"), gracias),
    ]


def _rombo(cx: float, cy: float, medio: float) -> QPolygonF:
    return QPolygonF([QPointF(cx, cy - medio), QPointF(cx + medio, cy), QPointF(cx, cy + medio),
                      QPointF(cx - medio, cy)])


class _EntradaApartado(QAbstractButton, PiezaC):
    """Un apartado de la columna: rombo (lleno si es el activo o ya se vio) y su nombre en
    mayusculas; el activo con fondo tenue y barra de acento."""

    def __init__(self, texto: str, parent=None):
        super().__init__(parent)
        transparente(self)
        self.visto = False
        self.setText(texto)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _fuente(self) -> QFont:
        f = fuente("dato", 12, 600)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        return f

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self._fuente())
        return QSize(px(34, False) + fm.horizontalAdvance(self.text().upper()) + px(10, False),
                     fm.height() + px(18, False))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(px(120, False), self.sizeHint().height())

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        activo = self.isChecked()
        if activo:
            fondo = QColor(color("acento"))
            fondo.setAlpha(30)
            p.fillRect(self.rect(), fondo)
            p.fillRect(0, 0, px(3, False), self.height(), color("acento"))
        lleno = activo or self.visto
        tinta_rombo = color("acento") if lleno else color("tenue")
        p.setPen(QPen(tinta_rombo, 1.2))
        p.setBrush(tinta_rombo if lleno else Qt.NoBrush)
        medio = px(4, False)
        p.drawPolygon(_rombo(px(16, False), self.height() / 2, medio))
        tinta = color("acento") if activo else color("texto" if (self.visto or self.underMouse()) else "suave")
        f = self._fuente()
        p.setFont(f)
        p.setPen(tinta)
        x = px(30, False)
        texto = QFontMetrics(f).elidedText(self.text().upper(), Qt.ElideRight, max(10, self.width() - x - 4))
        p.drawText(QRectF(x, 0, self.width() - x, self.height()), Qt.AlignVCenter | Qt.AlignLeft, texto)
        p.end()

    def enterEvent(self, evento):  # noqa: N802
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.update()
        super().leaveEvent(evento)


def _titulo_apartado(texto: str) -> EtiquetaC:
    """Titulo de un apartado en mayusculas de pantalla, sin cambiar su texto (se busca tal cual)."""
    etiqueta = EtiquetaC(texto, "seccion")
    f = etiqueta.font()
    f.setCapitalization(QFont.AllUppercase)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
    etiqueta.setFont(f)
    return etiqueta


def _texto_rico(contenido: str) -> QLabel:
    etiqueta = EtiquetaC("", "normal", envolver=True)
    # Siempre como HTML (frase() ya escapa): sin etiquetas, EtiquetaC lo tomaria por texto
    # plano y ensenaria los &quot; tal cual.
    etiqueta.setText(contenido if contenido.lstrip().startswith("<") else f"<span>{contenido}</span>")
    etiqueta.setOpenExternalLinks(True)
    etiqueta.setTextInteractionFlags(Qt.TextBrowserInteraction)
    etiqueta.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    return etiqueta


class CapaBienvenida(QWidget):
    """Capa oscura sobre toda la ventana con la tarjeta de bienvenida en el centro."""

    # True si al acabar se pidio el recorrido por la ventana (la guia).
    terminada = Signal(bool)

    def __init__(self, ventana, obligatoria: bool = False):
        super().__init__(ventana)
        self.ventana = ventana
        self.obligatoria = obligatoria
        config = getattr(ventana, "config", {}) or {}
        self._ofrecer_guia = not config.get("guia_vista")
        atajo = config.get("hotkey_overlay", "Ctrl+Alt+W")
        self._apartados = _apartados(atajo)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)

        self.tarjeta = PanelC(fondo="fondo", borde="acento", chaflan=18)
        self.tarjeta.setParent(self)
        self.tarjeta.poner_marcado(True)
        m = self.tarjeta.capa
        m.setContentsMargins(px(34, False), px(22, False), px(34, False), px(20, False))
        m.setSpacing(px(10, False))

        # -- cabecera -------------------------------------------------------------------
        self.titulo = EtiquetaC(t("Bienvenido a {app}", app=NOMBRE_APP), "titulo", tinta="acento", mayus=True)
        f = self.titulo.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 4.0)
        self.titulo.setFont(f)
        self.subtitulo = EtiquetaC(t("Un momento antes de empezar: esto es lo que conviene saber."), "normal",
                                   tinta="suave", envolver=True)
        self.boton_cerrar = BotonGlifo("cerrar", t("Cerrar"), tam=14)
        self.boton_cerrar.setToolTip(t("Cerrar"))
        self.boton_cerrar.clicked.connect(lambda: self.terminar(False))
        self.boton_cerrar.setVisible(not obligatoria)
        m.addLayout(fila(Rombo(16, "acento", relleno=False), self.titulo, None, self.boton_cerrar,
                         espacio=px(12, False)))
        m.addWidget(self.subtitulo)
        m.addWidget(Filete())

        # -- apartados a la izquierda, como el menu de opciones del juego -------------------
        self.lista = transparente(QWidget())
        capa_lista = QVBoxLayout(self.lista)
        capa_lista.setContentsMargins(0, px(6, False), 0, 0)
        capa_lista.setSpacing(px(4, False))
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self.entradas: list[_EntradaApartado] = []
        self.paginas = QStackedWidget()
        transparente(self.paginas)
        self.textos: list[QLabel] = []
        for i, (titulo, contenido) in enumerate(self._apartados):
            entrada = _EntradaApartado(titulo)
            entrada.clicked.connect(lambda _=False, i=i: self._ir_a(i))
            self._grupo.addButton(entrada)
            self.entradas.append(entrada)
            capa_lista.addWidget(entrada)
            self.paginas.addWidget(self._pagina(i, titulo, contenido, atajo))
        capa_lista.addStretch(1)
        self.lista.setFixedWidth(px(240, False))

        # -- como empezar (aviso en "Lo basico"; con los botones en el ultimo) ----------------
        self.caja_empezar = PanelC(remate=False, fondo="panel2", chaflan=12)
        self.nota_empezar = EtiquetaC("", "pequeno", envolver=True)
        # En el ultimo apartado: empezar, con o sin recorrido por la ventana.
        self.boton_guia = BotonC(t("Empezar con el recorrido por la ventana"), principal=True, icono="derecha", tam=10)
        self.boton_guia.clicked.connect(lambda: self.terminar(True))
        self.boton_empezar = BotonC(t("Empezar"), tam=10)
        self.boton_empezar.clicked.connect(lambda: self.terminar(False))
        self.caja_empezar.capa.setContentsMargins(px(16, False), px(10, False), px(16, False), px(10, False))
        self.caja_empezar.capa.setSpacing(px(6, False))
        self.caja_empezar.capa.addWidget(self.nota_empezar)
        self.caja_empezar.capa.addLayout(fila(self.boton_guia, self.boton_empezar, None, espacio=px(8, False)))

        derecha = QVBoxLayout()
        derecha.setSpacing(px(10, False))
        derecha.addWidget(self.paginas, 1)
        derecha.addWidget(self.caja_empezar)
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(px(24, False))
        cuerpo.addWidget(self.lista)
        cuerpo.addLayout(derecha, 1)
        m.addLayout(cuerpo, 1)
        m.addWidget(Filete())

        # -- pie: Atras · n DE 5 · Siguiente ---------------------------------------------------
        self.nota_pie = EtiquetaC(t("Puedes volver a verla en Ajustes > Ayuda."), "pequeno", recortar=True)
        self.contador = EtiquetaC("", "dato", tinta="suave", mayus=True)
        self.boton_atras = BotonC(t("Atrás"), icono=GLIFO_ATRAS, tam=11)
        self.boton_atras.clicked.connect(lambda: self._ir_a(self.paginas.currentIndex() - 1))
        self.boton_siguiente = BotonC(t("Siguiente"), principal=True, icono="derecha", tam=11)
        self.boton_siguiente.clicked.connect(lambda: self._ir_a(self.paginas.currentIndex() + 1))
        pie = fila(espacio=px(12, False))
        pie.addWidget(self.nota_pie, 1)
        for w in (self.boton_atras, self.contador, self.boton_siguiente):
            pie.addWidget(w)
        m.addLayout(pie)

        ventana.installEventFilter(self)
        self.reposicionar()
        self._ir_a(0)
        self.show()
        self.raise_()
        self.setFocus()

    def _pagina(self, indice: int, titulo: str, contenido: str, atajo: str) -> QScrollArea:
        """Un apartado: su titulo y su texto; "Lo basico" con los pasos numerados."""
        dentro = transparente(QWidget())
        caja = QVBoxLayout(dentro)
        caja.setContentsMargins(0, 0, px(10, False), 0)
        caja.setSpacing(px(8, False))
        cabeza = _titulo_apartado(titulo)
        caja.addWidget(cabeza)
        self.textos.append(cabeza)
        texto = _texto_rico(contenido)
        caja.addWidget(texto)
        self.textos.append(texto)
        if indice == APARTADO_BASICO:
            for n, paso in enumerate(pasos_basicos(atajo), 1):
                numero = EtiquetaC(str(n), "dato", tinta="acento")
                numero.setFixedWidth(px(22, False))
                numero.setAlignment(Qt.AlignTop | Qt.AlignLeft)
                linea = _texto_rico(paso)
                fila_paso = QHBoxLayout()
                fila_paso.setSpacing(px(8, False))
                fila_paso.addWidget(numero, 0, Qt.AlignTop)
                fila_paso.addWidget(linea, 1)
                caja.addLayout(fila_paso)
                self.textos.append(linea)
        caja.addStretch(1)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QScrollArea.NoFrame)
        desplazable.setWidget(dentro)
        return desplazable

    # -- navegacion -----------------------------------------------------------

    def _ir_a(self, indice: int) -> None:
        total = self.paginas.count()
        indice = max(0, min(indice, total - 1))
        self.paginas.setCurrentIndex(indice)
        for i, entrada in enumerate(self.entradas):
            if i == indice:
                entrada.visto = True
                entrada.setChecked(True)
            entrada.update()
        ultimo = indice == total - 1
        self.contador.setText(t("{n} de {total}", n=indice + 1, total=total))
        self.boton_atras.setEnabled(indice > 0)
        self.boton_siguiente.setVisible(not ultimo)
        # Empezar solo desde el final la primera vez; luego, siempre a mano con Cerrar.
        self.boton_empezar.setVisible(ultimo)
        self.boton_empezar.setText(t("Empezar sin recorrido") if self._ofrecer_guia else t("Empezar"))
        self.boton_empezar.principal = not self._ofrecer_guia
        self.boton_empezar.update()
        self.boton_guia.setVisible(ultimo and self._ofrecer_guia)
        if ultimo:
            aviso = (t("Elige cómo empezar. El recorrido señala cada parte de la ventana, paso a paso.")
                     if self._ofrecer_guia else "")
        else:
            aviso = t("Al final eliges cómo empezar. El recorrido señala cada parte de la ventana, paso a paso.")
        self.nota_empezar.setText(aviso)
        self.nota_empezar.setVisible(bool(aviso))
        self.caja_empezar.setVisible(ultimo or (indice == APARTADO_BASICO and self._ofrecer_guia))

    def terminar(self, con_guia: bool) -> None:
        """Guarda la marca (no vuelve a salir sola) y quita la capa."""
        from ..config import guardar

        config = getattr(self.ventana, "config", None)
        if config is not None:
            config[CLAVE_VISTA] = True
            # El aviso "Nuevo: guia de uso" ya no hace falta: la bienvenida la ofrece.
            config["guia_aviso_visto"] = True
            if not con_guia and self._ofrecer_guia and self.obligatoria:
                # Eligio empezar sin recorrido: que la guia no se lance sola despues.
                config["guia_vista"] = True
            guardar(config)
        self.ventana.removeEventFilter(self)
        if getattr(self.ventana, "_bienvenida", None) is self:
            self.ventana._bienvenida = None
        self.hide()
        self.deleteLater()
        self.terminada.emit(con_guia)

    # -- geometria --------------------------------------------------------------

    def reposicionar(self) -> None:
        self.setGeometry(self.ventana.rect())
        area = self.rect().adjusted(MARGEN, MARGEN, -MARGEN, -MARGEN)
        ancho = min(px(ANCHO_MAXIMO, letra=False), area.width())
        alto = min(px(ALTO_MAXIMO, letra=False), area.height())
        self.tarjeta.setGeometry(
            area.x() + (area.width() - ancho) // 2, area.y() + (area.height() - alto) // 2, ancho, alto
        )

    def eventFilter(self, objeto: QObject, evento: QEvent) -> bool:  # noqa: N802 - firma de Qt
        if objeto is self.ventana and evento.type() == QEvent.Resize:
            self.reposicionar()
        return False

    # -- pintado y teclado --------------------------------------------------------

    def paintEvent(self, evento) -> None:  # noqa: N802 - firma de Qt
        pintor = QPainter(self)
        pintor.fillRect(self.rect(), QColor(0, 0, 0, 170))

    def event(self, evento) -> bool:  # noqa: N802 - firma de Qt
        # Escape no puede llegar al atajo de la ventana (ocultarla): la obligatoria no se
        # cierra con el, y la otra se cierra, pero sin esconder tambien el overlay.
        if evento.type() == QEvent.ShortcutOverride and evento.key() == Qt.Key_Escape:
            evento.accept()
            return True
        return super().event(evento)

    def keyPressEvent(self, evento) -> None:  # noqa: N802 - firma de Qt
        if evento.key() == Qt.Key_Escape:
            if not self.obligatoria:
                self.terminar(False)
            return
        if evento.key() in (Qt.Key_Right, Qt.Key_PageDown):
            self._ir_a(self.paginas.currentIndex() + 1)
            return
        if evento.key() in (Qt.Key_Left, Qt.Key_PageUp):
            self._ir_a(self.paginas.currentIndex() - 1)
            return
        super().keyPressEvent(evento)
