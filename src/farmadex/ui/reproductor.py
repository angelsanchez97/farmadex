"""Panel "Video" de Farmadex: las guias de YouTube dentro de la propia ventana.

El reproductor es una ventana WebView2 de un proceso hijo (farmadex/video.py) incrustada
aqui con QWidget.createWindowContainer(QWindow.fromWinId(hwnd)). Asi el video sigue el
tamano del panel, se esconde y se ensena con el, y en el "modo video" de la ventana
(overlay.py) Farmadex queda reducido a solo el video, encima del juego, para quien juega
con un solo monitor.

Por que la ventana del hijo no va dentro de la del overlay sino en una "anfitriona": el
overlay es translucido (WA_TranslucentBackground: esquinas redondeadas y la opacidad de
Ajustes), y en Windows una ventana asi se pinta con UpdateLayeredWindow, que no dibuja
ventanas nativas hijas (el mismo problema de "airspace" que WPF con AllowsTransparency).
El video incrustado ahi seria un hueco invisible. Por eso el contenedor vive en una
ventana Qt propia, opaca, sin bordes y siempre encima, que es "hija" del overlay (se queda
por encima de el) y se coloca exactamente sobre el hueco del panel cada vez que el overlay
se mueve, cambia de tamano, se esconde o se cambia de pestana. Para el usuario es el
panel; por dentro son dos ventanas pegadas.

Por que asi y no QtWebEngine: QWebEngineView seria mas sencillo, pero mete ~300 MB sin
comprimir (unos 100 MB mas en el instalador y en cada actualizacion automatica). WebView2
ya viene con Windows 10/11 y pywebview + pythonnet son unos pocos MB.

Reglas:
- Nunca se abre nada solo. Si el reproductor no arranca (sin WebView2, sin pywebview, el
  hijo no da su ventana a tiempo), el panel dice "No se puede reproducir aqui" con un
  boton para abrirlo en el navegador; el navegador solo se abre si el usuario lo pulsa.
- El hijo es SOLO el proceso que lanzo este panel: se cierra por su PID (QProcess.kill)
  al cerrar el video, al abrir otro o al salir de Farmadex. Ademas el hijo vigila a
  Farmadex y se cierra solo si este desaparece.
- Esconder Farmadex con el atajo no para el video: sigue sonando (en modo video es lo
  util, se escucha la guia mientras se juega). "Cerrar video" lo para del todo.
- Perfil y cache de WebView2 en la carpeta de datos de Farmadex (reproductor/), nunca en
  el Escritorio; Ajustes tiene "Borrar datos del reproductor".

El mismo mecanismo sirve para cualquier pagina web (PanelWeb, pestana "Web"): las builds
de Overframe se navegan ahi sin salir de Farmadex. Cada panel tiene su proceso hijo, su
fichero de estado y su perfil, asi que se puede escuchar una guia mientras se mira una
build. "Atras" y "Recargar" van al hijo como ordenes en un fichero (farmadex/video.py).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QProcess, QRect, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QWindow
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedLayout, QVBoxLayout, QWidget

from .. import config
from .. import video as hijo
from ..idiomas import t
from ..registro_log import obtener
from .widgets import PALETA

log = obtener("reproductor")

# Cuanto se espera a que el hijo diga su HWND antes de darlo por perdido, y cada cuanto
# se mira el fichero de estado.
ESPERA_MS = 25000
SONDEO_MS = 200


def carpeta_datos() -> Path:
    """Perfil y cache de WebView2, y el fichero de estado del hijo."""
    return config.DIR_BASE / "reproductor"


def comando(url: str, estado: Path, padre: int, datos: Path, congelado: bool | None = None,
            ejecutable: str | None = None) -> tuple[str, list[str]]:
    """Programa y argumentos del proceso hijo.

    En el .exe, el propio Farmadex con --video (empaquetado/arranque.py lo enruta antes
    de arrancar Qt). Desde el codigo, `pythonw -m farmadex.video`: con python.exe se
    abriria una consola negra encima del juego.
    """
    congelado = getattr(sys, "frozen", False) if congelado is None else congelado
    ejecutable = ejecutable or sys.executable
    resto = [url, "--estado", str(estado), "--padre", str(padre), "--datos", str(datos)]
    if congelado:
        return ejecutable, ["--video", *resto]
    ruta = Path(ejecutable)
    sin_consola = ruta.with_name("pythonw.exe")
    programa = str(sin_consola) if ruta.name.lower() == "python.exe" and sin_consola.exists() else ejecutable
    return programa, ["-m", "farmadex.video", *resto]


def leer_estado(ruta: Path) -> tuple[str, str] | None:
    """('HWND', '123') o ('ERROR', 'sin_webview2 ...'); None si el hijo aun no ha escrito."""
    try:
        texto = ruta.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not texto:
        return None
    clave, _, valor = texto.partition(" ")
    return (clave, valor) if clave in ("HWND", "ERROR") else None


class PanelVideo(QWidget):
    """El reproductor de guias. `abrir(url)` lanza (o relanza) el hijo y lo incrusta."""

    estado = Signal(str)  # texto para la barra de estado de la ventana
    modo_video = Signal()  # el usuario pide la ventana reducida a solo el video
    cerrado = Signal()

    # Nombre del panel en sus ficheros: el de video conserva los de siempre (estado_<pid>.txt
    # y perfil/); otro panel (el web) usa estado_<pid>_web.txt y perfil_web/.
    NOMBRE = ""

    def __init__(self, parent=None, lanzar=None, incrustar=None):
        super().__init__(parent)
        # Inyectables para las pruebas: nunca se lanza un proceso ni una ventana de verdad.
        self._lanzar = lanzar or self._lanzar_proceso
        self._incrustar_ventana = incrustar or self._contenedor_nativo
        self.url = ""
        self.proceso: QProcess | None = None
        self._estado: Path | None = None
        self._contenedor: QWidget | None = None
        # Ventana opaca donde vive el contenedor, pegada encima de `self.area` (ver arriba).
        self._anfitrion: QWidget | None = None
        self._ventana_vigilada: QWidget | None = None
        self._esperado = 0
        self._sondeo = QTimer(self)
        self._sondeo.setInterval(SONDEO_MS)
        self._sondeo.timeout.connect(self._sondear)

        self.boton_modo = QPushButton()
        self.boton_modo.clicked.connect(self.modo_video.emit)
        # Navegacion normal dentro de la pagina (de una busqueda de YouTube al video y
        # vuelta, o por las builds de Overframe).
        self.boton_atras = QPushButton()
        self.boton_atras.clicked.connect(lambda: self.ordenar("ATRAS"))
        self.boton_recargar = QPushButton()
        self.boton_recargar.clicked.connect(lambda: self.ordenar("RECARGAR"))
        self.boton_navegador = QPushButton()
        self.boton_navegador.clicked.connect(self.abrir_en_navegador)
        self.boton_cerrar = QPushButton()
        self.boton_cerrar.clicked.connect(self.cerrar)
        barra = QHBoxLayout()
        barra.setContentsMargins(0, 0, 0, 0)
        barra.addWidget(self.boton_modo)
        barra.addWidget(self.boton_atras)
        barra.addWidget(self.boton_recargar)
        barra.addStretch(1)
        barra.addWidget(self.boton_navegador)
        barra.addWidget(self.boton_cerrar)

        self.mensaje = QLabel()
        self.mensaje.setAlignment(Qt.AlignCenter)
        self.mensaje.setWordWrap(True)
        self.boton_fallo = QPushButton()
        self.boton_fallo.clicked.connect(self.abrir_en_navegador)
        self.boton_fallo.hide()
        aviso = QWidget()
        caja_aviso = QVBoxLayout(aviso)
        caja_aviso.addStretch(1)
        caja_aviso.addWidget(self.mensaje)
        caja_aviso.addWidget(self.boton_fallo, 0, Qt.AlignHCenter)
        caja_aviso.addStretch(1)
        # El hueco del video dentro del overlay: negro, y encima se coloca la anfitriona.
        self.area = QWidget()
        self.area.setAttribute(Qt.WA_StyledBackground, True)
        self.area.setStyleSheet("background: #000000;")
        self.area.installEventFilter(self)
        self.pila = QStackedLayout()
        self.pila.addWidget(aviso)
        self.pila.addWidget(self.area)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(4)
        caja.addLayout(barra)
        caja.addLayout(self.pila, 1)
        self._texto = "vacio"
        self.retraducir()

    # -- textos ---------------------------------------------------------------

    def retraducir(self) -> None:
        self.boton_modo.setText(t("Modo video"))
        self.boton_modo.setToolTip(t("Deja Farmadex reducido a solo el video, encima del juego"))
        self.boton_atras.setText(t("‹ Atras"))
        self.boton_atras.setToolTip(t("Vuelve a la pagina anterior"))
        self.boton_recargar.setText(t("Recargar"))
        self.boton_recargar.setToolTip(t("Vuelve a cargar la pagina"))
        self.boton_navegador.setText(t("Abrir en el navegador"))
        self.boton_navegador.setToolTip(t("Abre lo que se esta viendo en tu navegador de siempre"))
        self.boton_cerrar.setText(self._texto_cerrar())
        self.boton_fallo.setText(t("Abrir en el navegador"))
        self._pintar_mensaje()
        self._pintar_botones()

    def _texto_cerrar(self) -> str:
        return t("Cerrar video")

    def _textos_mensaje(self) -> dict[str, str]:
        return {
            "vacio": t("Pulsa \"Guias en YouTube\" en la ficha de una mision o de un objeto y el video "
                       "se vera aqui."),
            "cargando": t("Abriendo el reproductor..."),
            "fallo": t("No se puede reproducir aqui. Puedes abrir la guia en el navegador."),
        }

    def _texto_abierto(self) -> str:
        return t("Guia abierta en el panel Video.")

    def _texto_fallo(self) -> str:
        return t("No se puede reproducir aqui: usa \"Abrir en el navegador\".")

    def repintar(self) -> None:
        self.mensaje.setStyleSheet(f"color: {PALETA['suave']};")

    def _pintar_mensaje(self) -> None:
        self.mensaje.setText(self._textos_mensaje().get(self._texto, ""))
        self.boton_fallo.setVisible(self._texto == "fallo")

    def _pintar_botones(self) -> None:
        hay = bool(self.url)
        self.boton_navegador.setEnabled(hay)
        self.boton_cerrar.setEnabled(hay)
        self.boton_modo.setEnabled(hay)
        self.boton_atras.setEnabled(hay)
        self.boton_recargar.setEnabled(hay)

    def _mostrar(self, texto: str) -> None:
        self._texto = texto
        self._pintar_mensaje()
        self.pila.setCurrentIndex(0)

    # -- ciclo de vida del hijo -----------------------------------------------

    @property
    def reproduciendo(self) -> bool:
        return self._contenedor is not None

    def abrir(self, url: str) -> None:
        """Lanza el reproductor con esa URL; si ya habia uno, lo cierra antes (por su PID)."""
        self._parar_hijo()
        self.url = url
        self._pintar_botones()
        carpeta = carpeta_datos()
        carpeta.mkdir(parents=True, exist_ok=True)
        sufijo = f"_{self.NOMBRE}" if self.NOMBRE else ""
        self._estado = carpeta / f"estado_{os.getpid()}{sufijo}.txt"
        for ruta in (self._estado, *hijo.rutas_auxiliares(self._estado)):
            try:
                ruta.unlink(missing_ok=True)
            except OSError:
                pass
        programa, argumentos = comando(url, self._estado, os.getpid(), carpeta / f"perfil{sufijo}")
        self._mostrar("cargando")
        try:
            self.proceso = self._lanzar(programa, argumentos)
        except Exception:  # noqa: BLE001 - cualquier fallo al lanzar acaba en el aviso
            log.exception("No se pudo lanzar el reproductor")
            self.proceso = None
        if self.proceso is None:
            self._fallo("no_arranca")
            return
        self._esperado = 0
        self._sondeo.start()

    def _lanzar_proceso(self, programa: str, argumentos: list[str]) -> QProcess | None:
        proceso = QProcess(self)
        proceso.setProgram(programa)
        proceso.setArguments(argumentos)
        proceso.start()
        return proceso if proceso.waitForStarted(5000) else None

    def _sondear(self) -> None:
        self._esperado += SONDEO_MS
        leido = leer_estado(self._estado) if self._estado else None
        if leido is None:
            terminado = self.proceso is not None and self.proceso.state() == QProcess.NotRunning
            if terminado or self._esperado >= ESPERA_MS:
                self._fallo("sin_respuesta")
            return
        self._sondeo.stop()
        clave, valor = leido
        if clave == "ERROR":
            self._fallo(valor)
            return
        try:
            contenedor = self._incrustar_ventana(int(valor))
        except Exception:  # noqa: BLE001 - el incrustado falla: aviso y navegador a mano
            log.exception("No se pudo incrustar la ventana del reproductor")
            contenedor = None
        if contenedor is None:
            self._fallo("sin_incrustar")
            return
        self._contenedor = contenedor
        anfitrion = self._crear_anfitrion()
        contenedor.setParent(anfitrion)
        anfitrion.layout().addWidget(contenedor)
        self._anfitrion = anfitrion
        self.pila.setCurrentWidget(self.area)
        self._vigilar_ventana()
        self._recolocar()
        self.estado.emit(self._texto_abierto())

    def _crear_anfitrion(self) -> QWidget:
        """Ventana opaca, sin bordes y encima del overlay (del que es hija) para el video."""
        anfitrion = QWidget(self.window(), Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        anfitrion.setAttribute(Qt.WA_ShowWithoutActivating, True)
        anfitrion.setStyleSheet("background: #000000;")
        caja = QVBoxLayout(anfitrion)
        caja.setContentsMargins(0, 0, 0, 0)
        return anfitrion

    def _contenedor_nativo(self, hwnd: int) -> QWidget | None:
        """La ventana del hijo en un contenedor Qt (mecanismo oficial para ventanas ajenas)."""
        ventana = QWindow.fromWinId(hwnd)
        if ventana is None:
            return None
        return QWidget.createWindowContainer(ventana)

    # -- la anfitriona sigue al hueco del panel -------------------------------

    def _vigilar_ventana(self) -> None:
        ventana = self.window()
        if ventana is self._ventana_vigilada:
            return
        if self._ventana_vigilada is not None:
            self._ventana_vigilada.removeEventFilter(self)
        ventana.installEventFilter(self)
        self._ventana_vigilada = ventana

    def eventFilter(self, objeto, evento):  # noqa: N802 - firma de Qt
        if self._anfitrion is not None and evento.type() in (
            QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide, QEvent.WindowStateChange,
        ):
            # Despues de que Qt termine de colocar lo suyo: si no, se leeria la posicion vieja.
            QTimer.singleShot(0, self._recolocar)
        return super().eventFilter(objeto, evento)

    def hueco(self) -> QRect:
        """Donde esta el hueco del video en la pantalla (coordenadas globales)."""
        return QRect(self.area.mapToGlobal(QPoint(0, 0)), self.area.size())

    def _recolocar(self) -> None:
        """Pone la anfitriona justo encima del hueco, o la esconde si el hueco no se ve
        (otra pestana, overlay escondido, modo compacto)."""
        anfitrion = self._anfitrion
        if anfitrion is None:
            return
        if not self.area.isVisible() or self.area.width() < 2 or self.area.height() < 2:
            anfitrion.hide()
            return
        anfitrion.setGeometry(self.hueco())
        if not anfitrion.isVisible():
            anfitrion.show()
        anfitrion.raise_()

    def _fallo(self, motivo: str) -> None:
        log.warning("El reproductor no arranca (%s)", motivo)
        self._sondeo.stop()
        self._parar_hijo(conservar_url=True)
        self._mostrar("fallo")
        self.estado.emit(self._texto_fallo())

    def _parar_hijo(self, conservar_url: bool = True) -> None:
        self._sondeo.stop()
        if self._anfitrion is not None:
            self._anfitrion.hide()
            self._anfitrion.deleteLater()  # se lleva el contenedor, que es hijo suyo
            self._anfitrion = None
            self._contenedor = None
        elif self._contenedor is not None:
            self._contenedor.deleteLater()
            self._contenedor = None
        if self.proceso is not None:
            # Solo el proceso que lanzo este panel, por su PID; nada mas.
            if self.proceso.state() != QProcess.NotRunning:
                self.proceso.kill()
                self.proceso.waitForFinished(2000)
            self.proceso = None
        if self._estado is not None:
            for ruta in (self._estado, *hijo.rutas_auxiliares(self._estado)):
                try:
                    ruta.unlink(missing_ok=True)
                except OSError:
                    pass
        if not conservar_url:
            self.url = ""

    def cerrar(self) -> None:
        """"Cerrar video": para el reproductor del todo (deja de sonar)."""
        self._parar_hijo(conservar_url=False)
        self._pintar_botones()
        self._mostrar("vacio")
        self.cerrado.emit()

    def ordenar(self, orden: str) -> bool:
        """"Atras" / "Recargar": deja la orden para el hijo; False si no hay pagina abierta."""
        if self._estado is None or self.proceso is None or not self.reproduciendo:
            return False
        ordenes, _ = hijo.rutas_auxiliares(self._estado)
        try:
            hijo.escribir_estado(ordenes, orden)
        except OSError:
            log.warning("No se pudo dejar la orden %s al reproductor", orden)
            return False
        return True

    def url_actual(self) -> str:
        """La direccion que se esta viendo (el hijo la apunta al navegar); si no, la de inicio."""
        if self._estado is not None and self.reproduciendo:
            _, ruta = hijo.rutas_auxiliares(self._estado)
            try:
                actual = ruta.read_text(encoding="utf-8").strip()
            except OSError:
                actual = ""
            if actual.startswith(("http://", "https://")):
                return actual
        return self.url

    def abrir_en_navegador(self) -> None:
        """Solo al pulsar: lo que se esta viendo, en el navegador del sistema."""
        url = self.url_actual()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def borrar_datos(self) -> bool:
        """Cierra el reproductor y borra su perfil de WebView2 (sesion, cookies, cache)."""
        self.cerrar()
        perfil = carpeta_datos() / (f"perfil_{self.NOMBRE}" if self.NOMBRE else "perfil")
        if not perfil.exists():
            return True
        shutil.rmtree(perfil, ignore_errors=True)
        return not perfil.exists()


class PanelWeb(PanelVideo):
    """Pestana "Web": una pagina cualquiera (las builds de Overframe) dentro de Farmadex.

    Es el reproductor de guias con otros textos y sin "modo video": su propio proceso
    hijo, su fichero de estado y su perfil de WebView2 (perfil_web/). Farmadex no lee ni
    guarda nada de la pagina: solo la ensena para que el usuario la navegue.
    """

    NOMBRE = "web"

    def retraducir(self) -> None:
        super().retraducir()
        self.boton_modo.hide()

    def _texto_cerrar(self) -> str:
        return t("Cerrar pagina")

    def _textos_mensaje(self) -> dict[str, str]:
        return {
            "vacio": t("Pulsa \"Builds en Overframe\" en la ficha de un warframe o de un arma, o en la "
                       "pestana Build, y la pagina se vera aqui."),
            "cargando": t("Abriendo la pagina..."),
            "fallo": t("No se puede abrir aqui. Puedes abrir la pagina en el navegador."),
        }

    def _texto_abierto(self) -> str:
        return t("Pagina abierta en la pestana Web.")

    def _texto_fallo(self) -> str:
        return t("No se puede abrir aqui: usa \"Abrir en el navegador\".")
