"""Bienvenida: la primera pantalla de Farmadex, antes de tocar nada.

Una capa encima de la ventana del overlay (como la guia) con una tarjeta en el
centro y cinco apartados a la izquierda: que es Farmadex, lo basico paso a paso,
si es seguro, preguntas frecuentes y agradecimientos con los enlaces del autor.

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

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
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
    frase,
    html_secciones,
    preguntas_frecuentes,
    secciones_seguridad,
    texto_autor,
)
from .widgets import PALETA, px

CLAVE_VISTA = "bienvenida_vista"
ANCHO_MAXIMO = 860
ALTO_MAXIMO = 620
MARGEN = 16


def toca_bienvenida(config: dict) -> bool:
    """Si hay que ensenarla sola al abrir: nunca vista y con una pantalla de verdad."""
    if config.get(CLAVE_VISTA):
        return False
    if os.environ.get("FARMADEX_SIN_BIENVENIDA"):
        return False
    app = QApplication.instance()
    return not (app is not None and app.platformName() == "offscreen")


def _apartados(atajo: str) -> list[tuple[str, str]]:
    """(titulo del apartado, HTML del contenido), en el idioma activo."""
    p = PALETA
    pasos = [
        frase("Abrelo encima del juego con {atajo}, y escondelo con Escape. Cuando no lo ves, sigue "
              "esperando en los iconos junto al reloj de Windows.", atajo=f"<b>{html.escape(atajo)}</b>"),
        frase("Pon Warframe en Ventana sin bordes (Opciones > Pantalla). En pantalla completa "
              "exclusiva no se puede ver nada encima del juego."),
        frase("En Buscar escribe cualquier cosa, aunque sea con faltas: te dice donde se consigue, con "
              "que probabilidad y cuanto se tarda en cada sitio."),
        frase("Con \"+ Objetivo\" lo apuntas. En Objetivos ves cuanto te falta y donde farmear cada "
              "cosa ahora mismo."),
        frase("Al abrir una reliquia, Farmadex lee solo las recompensas y te marca la que mas te "
              "conviene."),
        frase("En Mundo tienes lo que pasa ahora en el juego: fisuras, ciclos, invasiones, Baro "
              "Ki'Teer... Y si quieres, Windows te avisa cuando pase algo que te interesa."),
        frase("En Build lees los mods de una build desde la pantalla del juego, y en Agrietados ves si "
              "un mod agrietado es bueno y cuanto se pide por uno parecido."),
        frase("En Ajustes, con las secciones a la izquierda, cambias atajos, colores, tamano de letra "
              "e idioma."),
    ]
    lista = "<ol style='margin-left: -16px;'>" + "".join(
        f"<li style='margin-bottom: 6px;'>{paso}</li>" for paso in pasos
    ) + "</ol>"

    que_es = (
        f"<p>{frase('Farmadex es un ayudante para Warframe que se abre encima del juego. Sirve para no '
                    'tener que salir a la wiki: te dice donde conseguir cada cosa y cuanto se tarda, '
                    'apunta lo que quieres farmear, lee las recompensas de las reliquias y te cuenta '
                    'que esta pasando ahora en el juego.')}</p>"
        f"<p>{frase('Lo hace vaas, un jugador, en su tiempo libre. Es gratis, sin anuncios, y el codigo es '
                    'publico.')}</p>"
        f"<p style='color: {p['suave']};'>{frase('Esta bienvenida sale sola solo esta vez. Puedes volver a '
                                                 'verla cuando quieras en Ajustes > Ayuda.')}</p>"
    )
    basico = (
        f"<p>{frase('Lo que necesitas para empezar, en ocho pasos:')}</p>{lista}"
        f"<p style='color: {p['suave']};'>{frase('Al terminar puedes hacer un recorrido por la ventana que '
                                                 'te ensena cada parte en su sitio.')}</p>"
    )
    seguro = html_secciones(secciones_seguridad(), nivel="h4")
    faq = html_secciones(preguntas_frecuentes(atajo), nivel="h4")
    gracias = (
        f"<p>{frase('Gracias por probar Farmadex.')}</p>"
        f"<p>{frase('Los datos salen del trabajo de la comunidad: WFCD (catalogo de objetos y estado del '
                    'mundo), las tablas de drops oficiales de Digital Extremes, la wiki de Warframe y '
                    'warframe.market.')}</p>"
        f"<p>{frase('Y gracias a quienes lo prueban y mandan sus comentarios: mucho de lo que ves ha '
                    'salido de ahi.')}</p>"
        f"<p>{texto_autor()}</p>"
        f"<p>{frase('Dudas, fallos o ideas: escribe en el chat del canal o abre un aviso en {avisos}.',
                    avisos=_enlace(URL_AVISOS, 'GitHub'))}</p>"
        f"<p>{frase('Codigo y descargas: {enlace}', enlace=_enlace(URL_REPOSITORIO, URL_REPOSITORIO.removeprefix('https://')))}</p>"
        f"<p style='color: {p['suave']};'>{frase('Farmadex no esta afiliado a Digital Extremes ni tiene su '
                                                 'respaldo. Warframe y todo su contenido son de Digital '
                                                 'Extremes.')}</p>"
    )
    return [
        (t("Que es Farmadex"), que_es),
        (t("Lo basico, paso a paso"), basico),
        (t("Es seguro?"), seguro),
        (t("Preguntas frecuentes"), faq),
        (t("Gracias"), gracias),
    ]


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
        self._apartados = _apartados(config.get("hotkey_overlay", "Ctrl+Alt+W"))
        p = PALETA

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)

        self.tarjeta = QFrame(self)
        self.tarjeta.setObjectName("tarjetaBienvenida")
        self.tarjeta.setStyleSheet(
            f"#tarjetaBienvenida {{ background: {p['fondo']}; border: 1px solid {p['acento']};"
            " border-radius: 12px; }"
        )

        self.titulo = QLabel(t("Bienvenido a {app}", app=NOMBRE_APP))
        self.titulo.setStyleSheet(f"color: {p['acento']}; font-weight: 700; font-size: {px(20)}px;")
        self.subtitulo = QLabel(t("Un momento antes de empezar: esto es lo que conviene saber."))
        self.subtitulo.setWordWrap(True)
        self.subtitulo.setStyleSheet(f"color: {p['suave']}; font-size: {px(13)}px;")

        # Apartados a la izquierda, como el menu de opciones del juego.
        self.lista = QListWidget()
        self.lista.setObjectName("apartadosBienvenida")
        self.lista.setFixedWidth(px(190, letra=False))
        self.lista.setStyleSheet(
            f"#apartadosBienvenida {{ background: {p['panel']}; border: 1px solid {p['borde']};"
            f" border-radius: 8px; padding: 4px; }}"
            f" #apartadosBienvenida::item {{ padding: {px(9, False)}px {px(10, False)}px; border: none;"
            f" border-left: 3px solid transparent; color: {p['suave']}; }}"
            f" #apartadosBienvenida::item:selected {{ background: {p['panel2']}; color: {p['texto']};"
            f" border-left: 3px solid {p['acento']}; }}"
            f" #apartadosBienvenida::item:hover {{ color: {p['texto']}; }}"
        )
        self.paginas = QStackedWidget()
        self.textos: list[QLabel] = []
        for titulo, contenido in self._apartados:
            self.lista.addItem(titulo)
            texto = QLabel(
                f"<h2 style='color: {p['acento']}; margin-top: 0;'>{html.escape(titulo)}</h2>{contenido}"
            )
            texto.setWordWrap(True)
            texto.setTextFormat(Qt.RichText)
            texto.setOpenExternalLinks(True)
            texto.setTextInteractionFlags(Qt.TextBrowserInteraction)
            texto.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            texto.setStyleSheet(f"color: {p['texto']}; font-size: {px(14)}px;")
            desplazable = QScrollArea()
            desplazable.setWidgetResizable(True)
            dentro = QWidget()
            caja = QVBoxLayout(dentro)
            caja.setContentsMargins(6, 0, 10, 0)
            caja.addWidget(texto)
            caja.addStretch(1)
            desplazable.setWidget(dentro)
            self.paginas.addWidget(desplazable)
            self.textos.append(texto)
        self.lista.currentRowChanged.connect(self._ir_a)

        self.contador = QLabel()
        self.contador.setStyleSheet(f"color: {p['suave']}; font-size: {px(12)}px;")
        self.boton_cerrar = QPushButton(t("Cerrar"))
        self.boton_cerrar.clicked.connect(lambda: self.terminar(False))
        self.boton_cerrar.setVisible(not obligatoria)
        self.boton_atras = QPushButton(t("Atras"))
        self.boton_atras.clicked.connect(lambda: self._ir_a(self.paginas.currentIndex() - 1))
        self.boton_siguiente = QPushButton(t("Siguiente"))
        self.boton_siguiente.setObjectName("principal")
        self.boton_siguiente.clicked.connect(lambda: self._ir_a(self.paginas.currentIndex() + 1))
        # En el ultimo apartado: empezar, con o sin recorrido por la ventana.
        self.boton_guia = QPushButton(t("Empezar con el recorrido por la ventana"))
        self.boton_guia.setObjectName("principal")
        self.boton_guia.clicked.connect(lambda: self.terminar(True))
        self.boton_empezar = QPushButton(t("Empezar"))
        self.boton_empezar.clicked.connect(lambda: self.terminar(False))

        botones = QHBoxLayout()
        botones.addWidget(self.contador)
        botones.addStretch(1)
        for boton in (self.boton_cerrar, self.boton_atras, self.boton_siguiente, self.boton_empezar,
                      self.boton_guia):
            botones.addWidget(boton)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(14)
        cuerpo.addWidget(self.lista)
        cuerpo.addWidget(self.paginas, 1)

        caja = QVBoxLayout(self.tarjeta)
        caja.setContentsMargins(20, 16, 20, 14)
        caja.setSpacing(8)
        caja.addWidget(self.titulo)
        caja.addWidget(self.subtitulo)
        caja.addLayout(cuerpo, 1)
        caja.addLayout(botones)

        ventana.installEventFilter(self)
        self.reposicionar()
        self.lista.setCurrentRow(0)
        self._ir_a(0)
        self.show()
        self.raise_()
        self.setFocus()

    # -- navegacion -----------------------------------------------------------

    def _ir_a(self, indice: int) -> None:
        total = self.paginas.count()
        indice = max(0, min(indice, total - 1))
        if self.lista.currentRow() != indice:
            self.lista.setCurrentRow(indice)  # vuelve a entrar aqui por la senal
            return
        self.paginas.setCurrentIndex(indice)
        ultimo = indice == total - 1
        self.contador.setText(t("{n} de {total}", n=indice + 1, total=total))
        self.boton_atras.setEnabled(indice > 0)
        self.boton_siguiente.setVisible(not ultimo)
        # Empezar solo desde el final la primera vez; luego, siempre a mano con Cerrar.
        self.boton_empezar.setVisible(ultimo)
        self.boton_empezar.setText(t("Empezar sin recorrido") if self._ofrecer_guia else t("Empezar"))
        self.boton_guia.setVisible(ultimo and self._ofrecer_guia)
        self.boton_empezar.setObjectName("" if self._ofrecer_guia else "principal")
        self.boton_empezar.style().unpolish(self.boton_empezar)
        self.boton_empezar.style().polish(self.boton_empezar)

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
