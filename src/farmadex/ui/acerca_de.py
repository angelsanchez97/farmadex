"""Dialogo "Acerca de": que es Farmadex, que no hace y que dice DE de los programas de terceros.

Se abre desde el boton del pie de Ajustes y desde el primer paso de la guia se
remite aqui. Tambien explica por que avisa Windows al instalarlo, de donde bajar la
version buena, como comprobar el fichero y que lee, guarda y no toca Farmadex: esos
textos (`secciones_seguridad`, `preguntas_frecuentes`) los comparte la bienvenida.
La captura es la respuesta real del soporte de Digital Extremes al
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
URL_RELEASES = URL_REPOSITORIO + "/releases"
URL_AVISOS = URL_REPOSITORIO + "/issues"
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


def frase(clave: str, **huecos: str) -> str:
    """Traduce `clave`, la escapa como HTML y rellena sus huecos con HTML ya hecho
    (enlaces, codigo). Los huecos no se escapan: los escribe el propio programa."""
    marcas = {nombre: f"\x00{i}\x00" for i, nombre in enumerate(huecos)}
    texto = html.escape(t(clave, **marcas) if huecos else t(clave))
    for nombre, marca in marcas.items():
        texto = texto.replace(marca, huecos[nombre])
    return texto


def _codigo(texto: str) -> str:
    p = PALETA
    return (f'<span style="font-family: Consolas, monospace; background: {p["panel2"]};'
            f' color: {p["texto"]};">&nbsp;{html.escape(texto)}&nbsp;</span>')


def _lista(elementos: list[str]) -> str:
    return "<ul style='margin-left: -20px;'>" + "".join(f"<li>{e}</li>" for e in elementos) + "</ul>"


def secciones_seguridad(incluir_de: bool = True) -> list[tuple[str, str]]:
    """(titulo, HTML) de cada apartado de "Es seguro?": aviso de Windows, descarga buena,
    como comprobar el fichero, que lee, que guarda, que no toca y (opcional) la postura
    de DE, que el dialogo Acerca de ya cuenta con su captura."""
    secciones = [
        (t("Por que avisa Windows al instalarlo"), frase(
            "Windows ensena un aviso azul (\"Windows protegio tu PC\") con los programas nuevos que "
            "no llevan una firma digital de pago. Farmadex todavia no la lleva: es gratis, lo hace "
            "una sola persona y esa firma cuesta mucho dinero cada ano. El aviso no quiere decir que "
            "tenga un virus, solo que Windows aun no lo conoce. Para seguir, pulsa \"Mas "
            "informacion\" y luego \"Ejecutar de todas formas\"."
        )),
        (t("De donde descargarlo"), frase(
            "Descargalo solo de la pagina de versiones del proyecto: {enlace}. Si te lo pasan por "
            "otro sitio (un Discord, una web de descargas, un amigo), no puedes saber si alguien lo "
            "ha cambiado. Todo el codigo esta ahi mismo, a la vista de quien quiera revisarlo.",
            enlace=_enlace(URL_RELEASES, URL_RELEASES.removeprefix("https://")),
        )),
        (t("Como comprobar que el fichero es el bueno"), frase(
            "Junto a cada version hay un fichero {sumas} con la huella de cada descarga. Abre "
            "PowerShell en la carpeta donde lo descargaste y escribe {orden}. Si el numero largo que "
            "sale es exactamente el mismo que el de {sumas}, el fichero es el que se publico. Si "
            "cambia una sola letra, no lo abras.",
            sumas=_codigo("SHA256SUMS.txt"),
            orden=_codigo(f"Get-FileHash .\\Farmadex-{VERSION}-setup.exe"),
        )),
        (t("Que lee Farmadex"), _lista([
            frase(
                "El registro que escribe el propio juego (EE.log), solo para saber cuando abres "
                "una reliquia o acabas una mision. Ese fichero lleva tu correo y tu IP: Farmadex "
                "solo busca en el unos pocos mensajes del juego y no guarda ni envia nada de el."
            ),
            frase(
                "La pantalla, solo cuando hace falta: las recompensas de una reliquia, el objeto "
                "bajo el raton y, si lo activas, tu Perfil y tu Inventario. Esas capturas se leen "
                "en tu PC y se tiran; no se guardan ni se envian a nadie."
            ),
            frase(
                "Datos publicos de internet: el catalogo de objetos y las tablas de drops (WFCD y "
                "Digital Extremes), lo que pasa ahora en el juego, precios de warframe.market y si "
                "hay una version nueva de Farmadex."
            ),
        ])),
        (t("Que guarda en tu PC"), frase(
            "Solo en su propia carpeta ({carpeta}): tus ajustes, tus objetivos, el catalogo "
            "descargado y un registro de errores para poder ayudarte si algo falla. Nada de eso "
            "sale de tu PC, salvo el informe que tu decidas enviar.",
            carpeta=_codigo("%LOCALAPPDATA%\\Farmadex"),
        )),
        (t("Que NO toca"), frase(
            "No lee ni escribe la memoria del juego, no mira ni cambia su conexion, no modifica sus "
            "ficheros, no pulsa teclas por ti, no entra en tu cuenta y nunca te pide la contrasena."
        )),
    ]
    if incluir_de:
        secciones.append((t("Y que dice Digital Extremes"), frase(
            "DE tiene una pagina sobre los programas de terceros ({enlace}). Dice que no respalda "
            "ninguno (\"{cita1}\") y que quien los usa lo hace por su cuenta (\"{cita2}\"). "
            "Farmadex no hace nada de lo que esa pagina persigue, pero no esta aprobado por DE y "
            "nadie puede prometerte que no haya ningun riesgo: la decision es tuya.",
            enlace=_enlace(URL_POLITICA_DE, t("Politica de DE sobre software de terceros")),
            cita1=html.escape(CITA_NO_RESPALDO),
            cita2=html.escape(CITA_RIESGO),
        )))
    return secciones


def preguntas_frecuentes(atajo: str = "Ctrl+Alt+W") -> list[tuple[str, str]]:
    """(pregunta, respuesta en HTML) para la bienvenida."""
    return [
        (t("No sale nada encima del juego"), frase(
            "Warframe tiene que estar en Ventana sin bordes (o en ventana normal): en pantalla "
            "completa exclusiva ningun programa puede dibujar encima. Se cambia en las opciones de "
            "pantalla del juego. Si aun asi no sale, en Ajustes > Reliquias, \"Comprobar la lectura "
            "de reliquias\" te dice que falla."
        )),
        (t("Como lo abro y lo cierro?"), frase(
            "Con {atajo} se abre y se cierra encima del juego, y con Escape se esconde. Cuando no lo "
            "ves sigue esperando en los iconos junto al reloj de Windows; con clic derecho ahi "
            "puedes salir del todo.",
            atajo=_codigo(atajo),
        )),
        (t("Es seguro para mi cuenta?"), frase(
            "Farmadex no toca el juego: ni su memoria, ni su conexion, ni sus ficheros. Solo mira la "
            "pantalla y el registro que escribe el propio juego, como otras herramientas que la "
            "comunidad usa desde hace anos. Aun asi, DE no aprueba ningun programa de terceros, asi "
            "que nadie puede garantizarte nada: lee su postura en Ajustes > Acerca de y decide tu."
        )),
        (t("Pierdo mis objetivos al actualizar?"), frase(
            "No. Tus objetivos y tus ajustes (tambien los colores y tamanos que elijas) se guardan "
            "aparte del programa y se conservan al actualizar."
        )),
        (t("Estan los datos al dia?"), frase(
            "Farmadex descarga solo el catalogo y las tablas de drops cuando hay nuevas. Justo "
            "despues de una actualizacion de Warframe, DE puede tardar unos dias en publicar sus "
            "tablas: Farmadex te avisa cuando pasa."
        )),
        (t("Es gratis?"), frase(
            "Si, entero y sin anuncios. El codigo es publico en {enlace}.",
            enlace=_enlace(URL_REPOSITORIO, URL_REPOSITORIO.removeprefix("https://")),
        )),
        (t("Tengo un problema o una idea"), frase(
            "Cuentaselo a vaas, que es quien lo hace: en su canal de Twitch ({twitch}) o abriendo "
            "un aviso en GitHub ({avisos}). Si es un fallo, \"Guardar informe para enviar\" (en "
            "Ajustes > Reliquias) prepara un archivo con lo necesario, sin datos de tu cuenta.",
            twitch=_enlace(URL_TWITCH, URL_TWITCH.removeprefix("https://www.")),
            avisos=_enlace(URL_AVISOS, "GitHub Issues"),
        )),
    ]


def html_secciones(secciones: list[tuple[str, str]], nivel: str = "h3") -> str:
    """Titulo + texto de cada seccion, en el color del tema."""
    p = PALETA
    return "".join(
        f"<{nivel} style='color: {p['acento']}; margin-bottom: 2px;'>{html.escape(titulo)}</{nivel}>"
        f"<div style='color: {p['texto']};'>{cuerpo}</div>"
        for titulo, cuerpo in secciones
    )


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

        seguridad_titulo = QLabel(t("Es seguro? Lo que hace y lo que no"))
        seguridad_titulo.setStyleSheet(f"font-weight: bold; color: {p['acento']}; margin-top: 8px;")
        self.seguridad = _parrafo(html_secciones(secciones_seguridad(incluir_de=False), nivel="h4"))

        codigo = _parrafo(
            html.escape(t("Codigo, cambios y descargas:")) + " " + _enlace(URL_REPOSITORIO, URL_REPOSITORIO),
            p["suave"],
        )

        contenido = QWidget()
        dentro = QVBoxLayout(contenido)
        dentro.setContentsMargins(4, 4, 12, 4)
        dentro.setSpacing(10)
        for widget in (titulo, self.autor, no_afiliado, seccion, que_hace, decision, self.enlace_politica,
                       pie_imagen, self.imagen, seguridad_titulo, self.seguridad, codigo):
            dentro.addWidget(widget)
        dentro.addStretch(1)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(contenido)

        cerrar = QPushButton(t("Cerrar"))
        cerrar.clicked.connect(self.accept)
        # La bienvenida vive en la ventana del overlay (una capa encima): solo si el padre la tiene.
        self.boton_bienvenida = QPushButton(t("Ver la bienvenida"))
        self.boton_bienvenida.setToolTip(t("Que es Farmadex, lo basico, preguntas frecuentes y agradecimientos"))
        self.boton_bienvenida.setVisible(hasattr(parent, "mostrar_bienvenida"))
        self.boton_bienvenida.clicked.connect(self._ver_bienvenida)
        botones = QHBoxLayout()
        botones.addWidget(self.boton_bienvenida)
        botones.addStretch(1)
        botones.addWidget(cerrar)

        caja = QVBoxLayout(self)
        caja.addWidget(desplazable, 1)
        caja.addLayout(botones)

    def _ver_bienvenida(self) -> None:
        ventana = self.parent()
        self.accept()
        if hasattr(ventana, "mostrar_bienvenida"):
            ventana.mostrar_bienvenida()


def abrir_acerca_de(parent=None) -> DialogoAcercaDe:
    """Abre el dialogo sin bloquear (el overlay sigue respondiendo a sus atajos)."""
    dialogo = DialogoAcercaDe(parent)
    dialogo.setAttribute(Qt.WA_DeleteOnClose)
    dialogo.show()
    dialogo.raise_()
    dialogo.activateWindow()
    return dialogo
