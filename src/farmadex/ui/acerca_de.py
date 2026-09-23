"""Dialogo "Acerca de": que es Farmadex, que no hace y que dice DE de los programas de terceros.

Se abre desde el boton del pie de Ajustes y desde el primer paso de la guia se
remite aqui. La captura es la respuesta real del soporte de Digital Extremes al
autor (con su nombre de cuenta tapado), la misma que ensena el README. Las dos
frases citadas de DE van en ingles tal cual en todos los idiomas: por eso entran
por hueco y no forman parte de la clave traducible.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import NOMBRE_APP, VERSION
from ..idiomas import t
from .widgets import PALETA, hoja_estilos

URL_POLITICA_DE = "https://support.warframe.com/hc/en-us/articles/360030014351-Third-Party-Software-and-You"
URL_REPOSITORIO = "https://github.com/angelsanchez97/farmadex"
AUTOR = "vaas"
URL_TWITCH = "https://www.twitch.tv/vaas1897"
CITA_NO_RESPALDO = "we do not endorse any use of third-party software"
CITA_RIESGO = "at your own risk"
ANCHO_IMAGEN = 560


def ruta_imagen_soporte() -> Path:
    """`docs/img/respuesta_soporte_de.png` junto al codigo, o dentro del paquete de PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return base / "docs" / "img" / "respuesta_soporte_de.png"


def _enlace(url: str, texto: str) -> str:
    return f'<a href="{html.escape(url)}" style="color: {PALETA["acento"]};">{html.escape(texto)}</a>'


def texto_autor() -> str:
    """"Creado por vaas · twitch.tv/vaas1897", con el canal enlazado (Acerca de y pie de Ajustes)."""
    return (html.escape(t("Creado por {autor}", autor=AUTOR)) + " · "
            + _enlace(URL_TWITCH, URL_TWITCH.removeprefix("https://www.")))


def _parrafo(texto: str, color: str | None = None) -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setWordWrap(True)
    etiqueta.setTextFormat(Qt.RichText)
    etiqueta.setOpenExternalLinks(True)
    etiqueta.setTextInteractionFlags(Qt.TextBrowserInteraction)
    if color:
        etiqueta.setStyleSheet(f"color: {color};")
    return etiqueta


class DialogoAcercaDe(QDialog):
    """Ventana aparte, hija de la del overlay para quedar encima de ella."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Acerca de {app}", app=NOMBRE_APP))
        self.setStyleSheet(hoja_estilos())
        self.resize(640, 680)
        p = PALETA

        titulo = QLabel(f"{NOMBRE_APP} <b>{VERSION}</b>")
        titulo.setStyleSheet(f"font-size: 20px; color: {p['acento']};")
        self.autor = _parrafo(texto_autor())

        no_afiliado = _parrafo(html.escape(t(
            "No esta afiliado a Digital Extremes ni tiene su respaldo. Warframe y todo su "
            "contenido son propiedad de Digital Extremes."
        )), p["suave"])

        seccion = QLabel(t("Farmadex y la politica de Digital Extremes"))
        seccion.setStyleSheet(f"font-weight: bold; color: {p['acento']}; margin-top: 8px;")

        que_hace = _parrafo(html.escape(t(
            "Farmadex no hace nada de lo que la politica de DE persigue: no lee ni escribe la "
            "memoria del juego, no modifica sus ficheros, no inyecta nada, no pulsa teclas ni "
            "automatiza nada, y no toca tu cuenta. Solo mira la pantalla y el registro que "
            "escribe el propio juego (EE.log), lo mismo que llevan anos haciendo WFInfo y "
            "AlecaFrame."
        )))
        decision = _parrafo(html.escape(t(
            "Hasta donde sabemos, no incumple el EULA. Aun asi, DE no garantiza nada a ningun "
            "programa de terceros (\"{cita1}\", \"{cita2}\"), asi que la decision es tuya.",
            cita1=CITA_NO_RESPALDO,
            cita2=CITA_RIESGO,
        )))
        self.enlace_politica = _parrafo(_enlace(URL_POLITICA_DE, t("Politica de DE sobre software de terceros")))

        pie_imagen = _parrafo(html.escape(t(
            "Respuesta del soporte de Digital Extremes cuando se les pregunto por programas de "
            "terceros:"
        )), p["suave"])
        self.imagen = QLabel()
        self.imagen.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        mapa = QPixmap(str(ruta_imagen_soporte()))
        if not mapa.isNull():
            self.imagen.setPixmap(mapa.scaledToWidth(ANCHO_IMAGEN, Qt.SmoothTransformation))
            self.imagen.setFixedSize(self.imagen.pixmap().size())
            self.imagen.setStyleSheet(f"border: 1px solid {p['borde']};")
        else:  # la receta no la llevo: se dice en vez de dejar un hueco
            self.imagen.setText(t("(no se ha encontrado la imagen)"))

        codigo = _parrafo(
            html.escape(t("Codigo, cambios y descargas:")) + " " + _enlace(URL_REPOSITORIO, URL_REPOSITORIO),
            p["suave"],
        )

        contenido = QWidget()
        dentro = QVBoxLayout(contenido)
        dentro.setContentsMargins(4, 4, 12, 4)
        dentro.setSpacing(10)
        for widget in (titulo, self.autor, no_afiliado, seccion, que_hace, decision, self.enlace_politica,
                       pie_imagen, self.imagen, codigo):
            dentro.addWidget(widget)
        dentro.addStretch(1)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(contenido)

        cerrar = QPushButton(t("Cerrar"))
        cerrar.clicked.connect(self.accept)
        botones = QHBoxLayout()
        botones.addStretch(1)
        botones.addWidget(cerrar)

        caja = QVBoxLayout(self)
        caja.addWidget(desplazable, 1)
        caja.addLayout(botones)


def abrir_acerca_de(parent=None) -> DialogoAcercaDe:
    """Abre el dialogo sin bloquear (el overlay sigue respondiendo a sus atajos)."""
    dialogo = DialogoAcercaDe(parent)
    dialogo.setAttribute(Qt.WA_DeleteOnClose)
    dialogo.show()
    dialogo.raise_()
    dialogo.activateWindow()
    return dialogo
