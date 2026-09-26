"""La ventana del overlay: sin marco, translucida y siempre encima del juego."""

from __future__ import annotations

import sys
import time

import re
from html import unescape

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QCursor, QDesktopServices, QGuiApplication, QKeySequence, QPainter, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import NOMBRE_APP, VERSION, idiomas
from .. import config as config_modulo
from ..config import cargar, guardar
from ..datos import eficiencia, indice
from ..idiomas import es_castellano, t
from ..estado import inventario as estado_inventario
from ..estado import objetivos as estado_objetivos
from ..perfil import desde_ocr
from ..registro.botin import Botin
from ..registro.eelog import VigilanteEELog
from ..registro_log import obtener
from ..tareas import TareaDatos
from ..actualizador import descarga, instalacion
from ..actualizador.app import ComprobadorApp
from ..actualizador.datos import ComprobadorDatos
from ..actualizador.descarga import DescargadorApp
from ..actualizador.local import ComprobadorLocal, instalar
from ..captura import pantalla
from ..captura import prioridad as prioridad_recompensas
from ..captura.agrietados import LectorAgrietado
from ..captura.builds import LectorBuild
from ..captura.comparador import ServicioComparador
from ..captura.cursor import LectorCursor, TurnoLecturas
from ..captura.lector_pasivo import LectorPasivo
from ..captura.reliquias import DisparadorAutomatico, LectorRecompensas, Recompensa, completar, resumir
from ..online.servicio_market import ServicioMarket
from ..online.worldstate import ServicioMundo
from .pestana_agrietados import PestanaAgrietados
from .pestana_ajustes import PestanaAjustes
from .pestana_builds import PestanaBuilds
from .pestana_buscador import PestanaBuscador
from .pestana_mundo import DISENO_POR_DEFECTO, PestanaMundo
from .etiquetas import EtiquetasRecompensas
from .bienvenida import CapaBienvenida, toca_bienvenida
from .guia import CapaGuia
from .panel_recompensas import PanelRecompensas
from .pestana_objetivos import PestanaObjetivos
from .pestana_perfil import PestanaPerfil
from .pestana_primes import PestanaPrimes
from .vista_compacta import (
    ALTO as ALTO_COMPACTO,
    ALTO_MINIMO as ALTO_MINIMO_COMPACTO,
    ANCHO as ANCHO_COMPACTO,
    ANCHO_MINIMO as ANCHO_MINIMO_COMPACTO,
    VistaCompacta,
)
from .maestria import estado_con_padre, texto_maestria
from .reproductor import PanelVideo, PanelWeb
from .widgets import PALETA, BarraProgreso, elegir_tema, hoja_estilos

log = obtener("overlay")

# Atajo, dentro de la ventana, para pasar de la vista completa a la compacta y volver.
ATAJO_MODO = "Ctrl+M"

# Franja en los bordes/esquinas donde el cursor pasa a redimensionar en vez de a arrastrar
# o a hacer clic normal. Solo cuenta donde el raton cae sobre el propio marco (los widgets
# de dentro se quedan sus clics), asi que no le quita nada a ninguno.
MARGEN_REDIMENSION = 8

# Minimo de la vista completa: cuatro pestanas y la barra de busqueda siguen legibles,
# comprobado con una captura (herramientas/capturas/overlay_minimo_completo.png).
ANCHO_MINIMO_COMPLETO = 760
ALTO_MINIMO_COMPLETO = 420

# "Modo video": Farmadex reducido a solo el reproductor, para ponerlo en una esquina encima
# del juego. Nace arriba a la derecha con este tamano (16:9 mas la barra del panel) y
# despues recuerda el suyo (overlay_geometria_video).
ANCHO_VIDEO = 560
ALTO_VIDEO = 380
ANCHO_MINIMO_VIDEO = 320
ALTO_MINIMO_VIDEO = 220

_OESTE = {"o", "no", "so"}
_ESTE = {"e", "ne", "se"}
_NORTE = {"n", "no", "ne"}
_SUR = {"s", "so", "se"}

# Borde de `borde_en_posicion` -> bordes de Qt para QWindow.startSystemResize.
BORDES_QT = {
    "n": Qt.TopEdge,
    "s": Qt.BottomEdge,
    "e": Qt.RightEdge,
    "o": Qt.LeftEdge,
    "no": Qt.TopEdge | Qt.LeftEdge,
    "ne": Qt.TopEdge | Qt.RightEdge,
    "so": Qt.BottomEdge | Qt.LeftEdge,
    "se": Qt.BottomEdge | Qt.RightEdge,
}

# Cada cuanto se vuelve a poner la compacta fijada por encima de todo. Warframe en
# ventana sin bordes puede ponerse el tambien "siempre encima" al recibir el foco y taparla.
REFUERZO_ENCIMA_MS = 1500

CURSOR_POR_BORDE = {
    "n": Qt.SizeVerCursor,
    "s": Qt.SizeVerCursor,
    "e": Qt.SizeHorCursor,
    "o": Qt.SizeHorCursor,
    "no": Qt.SizeFDiagCursor,
    "se": Qt.SizeFDiagCursor,
    "ne": Qt.SizeBDiagCursor,
    "so": Qt.SizeBDiagCursor,
}


def borde_en_posicion(x: int, y: int, ancho: int, alto: int, margen: int = MARGEN_REDIMENSION) -> str | None:
    """A que borde o esquina cae (x, y) dentro de una ventana de (ancho, alto).

    None si el punto no esta en ninguna franja de redimensionado (clic normal).
    """
    izquierda = x <= margen
    derecha = x >= ancho - margen
    arriba = y <= margen
    abajo = y >= alto - margen
    if arriba and izquierda:
        return "no"
    if arriba and derecha:
        return "ne"
    if abajo and izquierda:
        return "so"
    if abajo and derecha:
        return "se"
    if arriba:
        return "n"
    if abajo:
        return "s"
    if izquierda:
        return "o"
    if derecha:
        return "e"
    return None


def geometria_redimensionada(borde: str, geometria: QRect, delta: QPoint, minimo: QSize) -> QRect:
    """Nueva geometria al arrastrar `borde` un `delta` (coordenadas globales de pantalla).

    El borde opuesto al que se arrastra no se mueve; el tamano nunca baja de `minimo`.
    """
    x, y, w, h = geometria.x(), geometria.y(), geometria.width(), geometria.height()
    dx, dy = delta.x(), delta.y()
    min_ancho = max(minimo.width(), 1)
    min_alto = max(minimo.height(), 1)
    nx, ny, nw, nh = x, y, w, h
    if borde in _ESTE:
        nw = max(min_ancho, w + dx)
    elif borde in _OESTE:
        nw = max(min_ancho, w - dx)
        nx = (x + w) - nw
    if borde in _SUR:
        nh = max(min_alto, h + dy)
    elif borde in _NORTE:
        nh = max(min_alto, h - dy)
        ny = (y + h) - nh
    return QRect(nx, ny, nw, nh)


class VentanaOverlay(QWidget):
    """Se abre y se cierra con el atajo; nunca se destruye, para abrir al instante."""

    recompensas_conocidas = Signal(list)  # list[Recompensa] dadas por EE.log, sin caja

    cerrar_programa = Signal()
    # Lectura bajo el cursor pedida al hilo de captura (numero de solicitud).
    _pedir_lectura_cursor = Signal(int)
    # Aviso que tiene que verse aunque la ventana este escondida (lo ensena la bandeja):
    # reliquia abierta en pantalla completa exclusiva, lector de pantalla que no carga...
    aviso_bandeja = Signal(str)
    # Cada cuanto se repite el mismo aviso de bandeja, como mucho.
    REPETIR_AVISO_S = 10 * 60

    def __init__(self):
        super().__init__()
        # Si el fichero ya existia antes de este arranque: un usuario que actualiza, no
        # alguien que instala Farmadex por primera vez. `cargar()` lo crea si falta, asi
        # que hay que mirarlo antes de llamarla.
        self._config_existia_antes = config_modulo.RUTA_CONFIG.exists()
        self.config = cargar()
        # El idioma se fija antes de construir nada: las pestanas leen los textos al nacer.
        idiomas.cargar(self.config.get("idioma_ui"))
        elegir_tema(self.config.get("tema", ""))
        self.setStyleSheet(hoja_estilos())
        self.setWindowTitle(f"{NOMBRE_APP} {VERSION}")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
            if False
            else Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1100, 700)
        self._arrastre: QPoint | None = None
        # Redimensionado a mano por los bordes: que borde se arrastra (o None) y de donde
        # partio, para poder calcular la geometria nueva a cada movimiento del raton.
        self._borde_activo: str | None = None
        self._geom_inicio_resize: QRect | None = None
        self._pos_inicio_resize: QPoint | None = None
        # "completo" (pestanas), "compacto" (solo busqueda y resultado esencial) o "video"
        # (solo el reproductor de guias). El modo video no se recuerda al reiniciar: sin
        # video abierto no pinta nada, asi que se vuelve a la vista completa.
        self.modo = "compacto" if self.config.get("overlay_modo") == "compacto" else "completo"

        self.marco = QFrame(self)
        self.marco.setObjectName("marco")
        self.aplicar_opacidad(float(self.config.get("overlay_opacidad", 0.94)))
        # Sin arrastrar el raton, el marco solo recibe MouseMove si se le pide: hace falta
        # para pintar el cursor de redimensionar con solo pasar por encima del borde.
        self.setMouseTracking(True)
        self.marco.setMouseTracking(True)
        self.marco.installEventFilter(self)

        # Cabecera: titulo, arrastre y cerrar.
        self.titulo = QLabel(f"  {NOMBRE_APP}")
        self.pista = QLabel()
        self._pintar_pista()
        self.boton_cerrar = QPushButton("×")
        self.boton_cerrar.setFixedSize(30, 26)
        self.boton_cerrar.clicked.connect(self.ocultar)
        boton_cerrar = self.boton_cerrar
        self.boton_modo = QPushButton()
        self.boton_modo.setFixedHeight(26)
        self.boton_modo.setCursor(Qt.PointingHandCursor)
        self.boton_modo.clicked.connect(self.alternar_modo)
        self.boton_guia = QPushButton(t("Guia"))
        self.boton_guia.setFixedHeight(26)
        self.boton_guia.setCursor(Qt.PointingHandCursor)
        self.boton_guia.setToolTip(t("Lanza la guia de uso desde el principio"))
        self.boton_guia.clicked.connect(self.mostrar_guia)
        # Chincheta de la vista compacta: fijarla por encima del juego (se recuerda).
        self.boton_fijar = QPushButton(t("Fijar"))
        self.boton_fijar.setCheckable(True)
        self.boton_fijar.setFixedHeight(26)
        self.boton_fijar.setCursor(Qt.PointingHandCursor)
        self.boton_fijar.setChecked(bool(self.config.get("compacta_siempre_encima", True)))
        self.boton_fijar.toggled.connect(self.fijar_encima)
        self._reloj_encima = QTimer(self)
        self._reloj_encima.setInterval(REFUERZO_ENCIMA_MS)
        self._reloj_encima.timeout.connect(self._reforzar_encima)
        self._guia: CapaGuia | None = None
        self._bienvenida: CapaBienvenida | None = None
        self._pintar_cabecera()

        cabecera = QHBoxLayout()
        cabecera.setContentsMargins(4, 4, 4, 0)
        cabecera.addWidget(self.titulo)
        cabecera.addStretch(1)
        cabecera.addWidget(self.pista)
        cabecera.addWidget(self.boton_guia)
        cabecera.addWidget(self.boton_fijar)
        cabecera.addWidget(self.boton_modo)
        cabecera.addWidget(boton_cerrar)

        self.pestanas = QTabWidget()
        self.buscador = PestanaBuscador()
        self.mundo = PestanaMundo(diseno=self.config.get("diseno_mundo", DISENO_POR_DEFECTO))
        self.objetivos = PestanaObjetivos()
        # Lo marcado en Primes son objetivos: comparte su BD y se repintan mutuamente.
        self.primes = PestanaPrimes(self.objetivos)
        self.ajustes = PestanaAjustes()
        # El perfil comparte la BD del usuario con los objetivos (misma conexion, mismo hilo).
        self.perfil = PestanaPerfil(self.objetivos.usuario)
        # Las guias de YouTube se ven dentro de Farmadex, en la pestana Video.
        self.video = PanelVideo()
        self.video.estado.connect(lambda texto: self.estado.setText(texto))
        self.video.modo_video.connect(lambda: self.aplicar_modo("video"))
        self.video.cerrado.connect(self._video_cerrado)
        self.buscador.reproductor = self.abrir_video
        # Paginas web dentro de Farmadex (las builds de Overframe), en la pestana Web.
        self.web = PanelWeb()
        self.web.estado.connect(lambda texto: self.estado.setText(texto))
        self.buscador.navegador_web = self.abrir_web
        self.buscador.conectar_usuario(self.objetivos.usuario)
        self.perfil.perfil_cambiado.connect(self.buscador.refrescar_perfil)
        self.perfil.abrir_item.connect(lambda item_id: self._abrir_desde_cursor(item_id, ""))
        self.mundo.abrir_item.connect(lambda item_id: self._abrir_desde_cursor(item_id, ""))
        self.mundo.buscar_texto.connect(self._buscar_desde_mundo)
        self.mundo.aviso_windows.connect(self.aviso_bandeja.emit)
        self.primes.abrir_item.connect(lambda item_id: self._abrir_desde_cursor(item_id, ""))
        # Build (mods leidos de la pantalla de mejoras) y Agrietados (grados y precio).
        self.builds = PestanaBuilds()
        self.builds.abrir_item.connect(lambda item_id: self._abrir_desde_cursor(item_id, ""))
        self.builds.pedir_lectura.connect(self.leer_build)
        self.builds.abrir_web.connect(self.abrir_web)
        self.agrietados = PestanaAgrietados()
        self.agrietados.pedir_lectura.connect(self.leer_agrietado)
        self.objetivos.cambiados.connect(self.mundo.refrescar_objetivos)
        self.ajustes.reconstruir.connect(lambda: self.preparar_datos(forzar=True))
        self.ajustes.tema_cambiado.connect(self.cambiar_tema)
        self.ajustes.idioma_cambiado.connect(self.cambiar_idioma)
        self.ajustes.diseno_mundo_cambiado.connect(self._cambiar_diseno_mundo)
        self.ajustes.ritmo_cambiado.connect(self._cambiar_ritmo)
        self.ajustes.salir.connect(self.cerrar_programa.emit)
        self.ajustes.instalar_version.connect(self._instalar_version)
        self.ajustes.pedir_diagnostico.connect(self.mostrar_diagnostico)
        self.ajustes.guardar_informe.connect(self.guardar_informe)
        self.ajustes.borrar_reproductor.connect(self._borrar_reproductor)
        # Ajustes > Ayuda y Ajustes > Aspecto (tamanos y colores guardados: se reaplica el tema).
        self.ajustes.ver_bienvenida.connect(self.mostrar_bienvenida)
        self.ajustes.ver_guia.connect(self.mostrar_guia)
        self.ajustes.apariencia_cambiada.connect(lambda: self.cambiar_tema(self.config.get("tema", "")))
        # Lo que el diagnostico cuenta de la ultima reliquia: cuando se vio la pantalla
        # (reloj de pared, para decir "hace 3 min"), que se leyo y que se pinto.
        self._t_reliquia_reloj: float | None = None
        self._ultima_lectura: tuple[float, int] | None = None
        self._ultima_pintada: tuple[float, int] | None = None
        self._avisos_bandeja: dict[str, float] = {}  # clave -> monotonic del ultimo aviso
        for pestana, titulo in self._titulos_pestanas():
            self.pestanas.addTab(pestana, t(titulo))
        self.compacta = VistaCompacta(self.buscador)
        self.compacta.abrir_completo.connect(self._abrir_completo)
        self.servicio_mundo: ServicioMundo | None = None
        self.hilo_captura: QThread | None = None
        self.hilo_comparador: QThread | None = None
        # Las dos formas de ensenar las recompensas conviven; `self.etiquetas` es la activa.
        self.etiquetas_pequenas = EtiquetasRecompensas()
        self.panel_recompensas = PanelRecompensas()
        self.etiquetas = (
            self.panel_recompensas if self.config.get("estilo_recompensas") == "panel" else self.etiquetas_pequenas
        )
        # Que destacar (Ajustes > "Al abrir reliquias, destacar"): lo usan las dos formas
        # de pintar para el motivo grande de cada tarjeta y el comparador para elegir.
        self.prioridad_recompensas = prioridad_recompensas.normalizar(self.config.get("prioridad_recompensas"))
        for vista in (self.etiquetas_pequenas, self.panel_recompensas):
            vista.prioridad = self.prioridad_recompensas
        self.vigilante: VigilanteEELog | None = None
        self._version_encontrada = None
        # Lo que se sabe del juego: cabecera de EE.log (build, modo) y modo de pantalla.
        self.cabecera_juego = None
        self.modo_pantalla = pantalla.MODO_DESCONOCIDO

        # Aviso grande bajo la cabecera: parche sin datos, pantalla completa exclusiva...
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.RichText)
        # Los enlaces normales se abren en el navegador; "farmadex:actualizar" es el
        # boton de "Reiniciar y actualizar" del aviso de actualizacion lista.
        self.banner.setOpenExternalLinks(False)
        self.banner.linkActivated.connect(self._enlace_banner)
        self.banner.setStyleSheet(
            f"color: {PALETA['aviso']}; border: 1px solid {PALETA['aviso']};"
            " border-radius: 6px; padding: 4px 8px;"
        )
        self.banner.hide()
        self._avisos: dict[str, str] = {}
        # Lo que la ventana compacta ha crecido para hacerle sitio al banner (0 sin aviso).
        self._alto_banner_compacto = 0
        # De que version se ha avisado (y si es local), para volver a escribir el aviso
        # al cambiar de idioma o de tema: el texto va traducido y con colores dentro.
        self._version_avisada: tuple[object, bool] | None = None
        self._desfase_comprobado = False
        # Actualizacion automatica: la descarga en curso, la que ya esta lista para
        # instalar (Version, ruta del setup) y el ultimo fallo (etiqueta, motivo).
        self.nueva_version = None
        self.descargador: DescargadorApp | None = None
        self.actualizacion_lista: tuple[object, object] | None = None
        self._fallo_actualizacion: tuple[str, str] | None = None
        self._instalador_lanzado = False
        # El aviso que tapa el hueco entre lanzar el setup y que este proceso muera.
        self._aviso_actualizando: QWidget | None = None

        self.progreso = BarraProgreso()
        self.estado = QLabel("")
        self.estado.setStyleSheet(f"color: {PALETA['suave']};")
        pie = QHBoxLayout()
        pie.addWidget(self.estado, 1)
        pie.addWidget(self.progreso, 0)

        dentro = QVBoxLayout(self.marco)
        dentro.setContentsMargins(10, 6, 10, 8)
        dentro.addLayout(cabecera)
        dentro.addWidget(self.banner)
        dentro.addWidget(self.pestanas, 1)
        dentro.addWidget(self.compacta, 1)
        dentro.addLayout(pie)

        fuera = QVBoxLayout(self)
        fuera.setContentsMargins(0, 0, 0, 0)
        fuera.addWidget(self.marco)

        self.buscador.estado.connect(self.estado.setText)
        self.buscador.anadir_objetivo.connect(self._anadir_objetivo)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.ocultar)
        QShortcut(QKeySequence(ATAJO_MODO), self, activated=self.alternar_modo)

        self.aplicar_modo(self.modo, guardar_config=False)

        self.tarea: TareaDatos | None = None
        self.preparar_datos()

    # -- datos -------------------------------------------------------------

    def preparar_datos(self, forzar: bool = False) -> None:
        if self.tarea and self.tarea.isRunning():
            return
        # Windows no deja sustituir un fichero que alguien tiene abierto: hay que
        # soltar el indice antes de reconstruirlo, o el intercambio final falla.
        self._soltar_indice()
        # Durante una reconstruccion el buscador se queda desactivado: si volviera
        # a abrir el indice, el intercambio del fichero al final fallaria.
        listo = indice.indice_al_dia() and not forzar
        self.buscador.habilitar(
            listo,
            ""
            if listo
            else (
                t("Reconstruyendo el indice...")
                if forzar
                else t("Descargando los datos del juego. La primera vez tarda unos minutos.")
            ),
        )
        self.estado.setText(t("Comprobando datos..."))
        log.info("Preparando los datos del juego%s", " (reconstruccion pedida a mano)" if forzar else "")
        self.tarea = TareaDatos(forzar=forzar)
        self.tarea.progreso.connect(self.progreso.actualizar)
        self.tarea.terminada.connect(self._datos_listos)
        self.tarea.start()

    def _soltar_indice(self) -> None:
        for objeto, atributo in (
            (self.buscador, "con"), (self.objetivos, "indice"), (self.perfil, "indice"), (self.mundo, "indice"),
        ):
            conexion = getattr(objeto, atributo, None)
            if conexion is not None:
                try:
                    conexion.close()
                except Exception:  # noqa: BLE001 - cerrar nunca debe tumbar nada
                    log.debug("No se pudo cerrar una conexion al indice", exc_info=True)
                setattr(objeto, atributo, None)

    def _datos_listos(self, ok: bool, mensaje: str) -> None:
        self.progreso.ocultar()
        self.ajustes.refrescar_estado()
        if ok:
            self.estado.setText(mensaje)
            log.info("Datos listos: %s", mensaje)
        elif indice.hay_indice():
            # La descarga ha fallado (sin red, WFCD caido...) pero el indice anterior sigue
            # ahi: se trabaja con el. Antes solo se reactivaba el buscador y el resto de
            # pestanas (Objetivos, Perfil, Mundo) y el OCR se quedaban muertos hasta reiniciar.
            self.estado.setText(t(
                "No se pudieron actualizar los datos ({motivo}); se sigue con los de antes",
                motivo=mensaje,
            ))
            log.warning("Datos sin actualizar, se sigue con el indice anterior: %s", mensaje)
        else:
            self.estado.setText(t("Error preparando los datos"))
            QMessageBox.critical(
                self, f"{NOMBRE_APP}", t("No se pudieron preparar los datos ({motivo})", motivo=mensaje)
            )
            return
        self.buscador.habilitar(True)
        self.objetivos.conectar_indice(indice.conectar())
        self.primes.conectar_indice(indice.conectar())
        self.perfil.conectar_indice(indice.conectar())
        self.builds.conectar_indice(indice.conectar())
        self.agrietados.conectar_indice(indice.conectar())
        self.mundo.conectar_objetivos(indice.conectar(), self.objetivos.usuario)
        self._arrancar_mundo()
        self._arrancar_captura()
        self._arrancar_comparador()
        self._arrancar_actualizador()
        self._comprobar_desfase()
        self._avisar_o_lanzar_guia()

    def _avisar_o_lanzar_guia(self) -> None:
        """La primera vez que la ventana esta lista: la guia sola si es instalacion nueva,
        o un aviso discreto si quien abre Farmadex ya lo tenia instalado de antes.
        Si toca la bienvenida, va ella primero y es ella quien ofrece la guia."""
        if self._bienvenida is not None or self._bienvenida_si_toca():
            return
        if self.config.get("guia_vista") or self._guia is not None:
            return
        if not self._config_existia_antes:
            QTimer.singleShot(300, self.mostrar_guia)
        elif not self.config.get("guia_aviso_visto"):
            self.config["guia_aviso_visto"] = True
            guardar(self.config)
            enlace = (
                f'<a style="color:{PALETA["acento"]}" href="farmadex:guia">{t("Verla ahora")}</a>'
            )
            self._aviso("guia_nueva", t("Nuevo: guia de uso en la pestana Ajustes.") + " " + enlace)

    def mostrar_guia(self) -> None:
        """Lanza la guia desde el principio: la relanza el boton "Guia" aunque ya se
        hubiera visto o saltado antes."""
        if self._guia is not None:
            return
        if self.modo == "compacto":
            self.aplicar_modo("completo")
        self._aviso("guia_nueva", None)
        self._guia = CapaGuia(self)

    # -- bienvenida (ui/bienvenida.py) ---------------------------------------------

    def _bienvenida_si_toca(self) -> bool:
        """La primera vez (o la primera tras actualizar a una version con bienvenida),
        obligatoria. Nunca en las pruebas ni sin pantalla (ver `toca_bienvenida`)."""
        if self._bienvenida is not None or not toca_bienvenida(self.config):
            return False
        self.mostrar_bienvenida(obligatoria=True)
        return True

    def mostrar_bienvenida(self, obligatoria: bool = False) -> None:
        """Desde Ajustes > Ayuda o Acerca de se abre cerrable; la primera vez, no."""
        if self._bienvenida is not None:
            return
        if self.modo == "compacto":
            self.aplicar_modo("completo")
        self._bienvenida = CapaBienvenida(self, obligatoria=obligatoria)
        self._bienvenida.terminada.connect(lambda con_guia: con_guia and self.mostrar_guia())

    def showEvent(self, evento):  # noqa: N802 - firma de Qt
        super().showEvent(evento)
        # Al abrir la ventana por primera vez, antes incluso de que esten los datos: se
        # lee mientras se descargan. Diferido para que la ventana tenga ya su tamano.
        if self._bienvenida is None and not self.config.get("bienvenida_vista"):
            QTimer.singleShot(0, self._bienvenida_si_toca)

    def _anadir_objetivo(self, item_id: int, set_completo: bool) -> None:
        creados = self.objetivos.anadir_item(item_id, set_completo)
        self.estado.setText(
            t("{n} objetivo(s) anadido(s)", n=creados) if creados else t("No se pudo anadir el objetivo")
        )

    def _arrancar_mundo(self) -> None:
        """El estado del mundo se pide en su propio hilo para no congelar la ventana."""
        if self.servicio_mundo is not None:
            return
        self.hilo_mundo = QThread(self)
        con = indice.conectar()
        # El traductor se queda con lo que necesita; la conexion no viaja al hilo.
        self.servicio_mundo = ServicioMundo(con)
        con.close()
        self.servicio_mundo.moveToThread(self.hilo_mundo)
        self.hilo_mundo.started.connect(self.servicio_mundo.iniciar)
        self.servicio_mundo.actualizado.connect(self.mundo.actualizar)
        self.servicio_mundo.fallo.connect(self.mundo.marcar_desactualizado)
        self.hilo_mundo.start()

        self.hilo_market = QThread(self)
        self.servicio_market = ServicioMarket()
        self.servicio_market.moveToThread(self.hilo_market)
        self.hilo_market.started.connect(self.servicio_market.iniciar)
        for origen in (self.buscador, self.compacta):
            # En directo, para que el servicio sepa ya cual es la ultima peticion y
            # se salte las que se queden viejas en la cola.
            origen.pedir_precios.connect(self.servicio_market.anotar, Qt.DirectConnection)
            origen.pedir_precios.connect(self.servicio_market.pedir)
        self.servicio_market.listo.connect(self.buscador.mostrar_precios)
        self.servicio_market.listo.connect(self.compacta.mostrar_precios)
        self.hilo_market.start()

    def _arrancar_captura(self) -> None:
        """OCR y vigilancia de EE.log, cada cosa en su hilo."""
        if self.hilo_captura is not None:
            return
        motor = self.config.get("motor_ocr", "rapidocr")
        self.hilo_captura = QThread(self)
        self.lector_recompensas = LectorRecompensas(motor)
        self.lector_cursor = LectorCursor(motor)
        self.lector_build = LectorBuild(motor)
        self.lector_agrietado = LectorAgrietado(motor)
        for lector in (self.lector_recompensas, self.lector_cursor, self.lector_build, self.lector_agrietado):
            lector.moveToThread(self.hilo_captura)
            lector.estado.connect(self.estado.setText)
        self.hilo_captura.started.connect(self.lector_recompensas.iniciar)
        self.hilo_captura.started.connect(self.lector_cursor.iniciar)
        self.hilo_captura.started.connect(self.lector_build.iniciar)
        self.hilo_captura.started.connect(self.lector_agrietado.iniciar)
        self.lector_build.leida.connect(self._build_leida)
        self.lector_agrietado.leida.connect(self._agrietado_leido)
        self.lector_recompensas.leidas.connect(self._pintar_recompensas)
        self.lector_cursor.encontrado.connect(self._abrir_desde_cursor)
        # Una lectura bajo el cursor a la vez: pulsar el atajo muchas veces seguidas
        # encolaba una lectura entera por pulsacion y acababa tumbando el programa.
        self.turno_cursor = TurnoLecturas(self._pedir_lectura_cursor.emit)
        self._pedir_lectura_cursor.connect(self.lector_cursor.leer_solicitud)
        self.lector_cursor.terminado.connect(self._lectura_cursor_terminada)
        # Lectura pasiva del perfil, el inventario y la fundicion: mismo hilo, mismo motor.
        self.lector_pasivo = LectorPasivo(
            motor,
            perfil=bool(self.config.get("perfil_pasivo", True)),
            inventario=bool(self.config.get("inventario_pasivo", False)),
        )
        self.lector_pasivo.moveToThread(self.hilo_captura)
        self.hilo_captura.started.connect(self.lector_pasivo.iniciar)
        self.lector_pasivo.pagina_perfil.connect(self._pagina_perfil_leida)
        self.lector_pasivo.pagina_inventario.connect(self._pagina_inventario_leida)
        self.ajustes.perfil_pasivo.toggled.connect(self.lector_pasivo.activar_perfil)
        self.ajustes.inventario_pasivo.toggled.connect(self.lector_pasivo.activar_inventario)
        self.hilo_captura.start()

        self.disparador = DisparadorAutomatico(bool(self.config.get("ocr_reliquias_auto", True)))
        self.disparador.disparar.connect(self.leer_recompensas)
        self.ajustes.ocr_auto.toggled.connect(
            lambda activo: setattr(self.disparador, "activo", activo)
        )
        self.ajustes.estilo_recompensas_cambiado.connect(self.cambiar_estilo_recompensas)
        self.ajustes.prioridad_recompensas_cambiada.connect(self.cambiar_prioridad_recompensas)

        # Botin que EE.log deja claro (reliquia en solitario) va directo a los objetivos.
        self.botin = Botin(self._sumar_botin, bool(self.config.get("botin_eelog_auto", True)))
        self.ajustes.botin_eelog.toggled.connect(lambda activo: setattr(self.botin, "activo", activo))

        self.vigilante = VigilanteEELog(
            self.config.get("ruta_eelog", ""), ruta_por_defecto=config_modulo.POR_DEFECTO["ruta_eelog"]
        )
        self.vigilante.evento.connect(self._evento_juego)
        self.vigilante.pista.connect(self.botin.pista)
        self.vigilante.pista.connect(self.lector_recompensas.pista)
        self.vigilante.evento.connect(self.lector_recompensas.evento)
        self.vigilante.pista.connect(self._pista_juego)
        # Recompensas que EE.log dio: veredicto sin esperar al OCR (se pinta al llegar el OCR).
        self._conocidas_log: list[str] = []
        self._t_reliquia: float | None = None  # monotonic del primer aviso de la pantalla
        # Cuando el juego pinto las tarjetas (monotonic estimado a partir de lo que
        # "Got rewards" llevaba escrita al leerse), y cuando se pintaron los nombres.
        self._t_pantalla: float | None = None
        self._t_pintadas: float | None = None
        self._t_cerrada: float | None = None
        self._t_lectura_pedida: float | None = None
        self._temporizador_conocidas = QTimer(self)
        self._temporizador_conocidas.setSingleShot(True)
        self._temporizador_conocidas.setInterval(150)  # las lineas "gets reward" salen juntas
        self._temporizador_conocidas.timeout.connect(self._recompensas_conocidas)
        self.vigilante.pantalla.connect(self.lector_pasivo.pantalla_juego)
        self.vigilante.arranque.connect(self._arranque_juego)
        self.vigilante.start()

    def _arrancar_comparador(self) -> None:
        """Puntua las recompensas en su propio hilo: los precios tardan ~300 ms por pieza
        y no pueden retrasar ni el OCR ni la ventana. Las etiquetas ya se ven sin esto;
        cuando llegue el veredicto, solo se les añade la marca de cual conviene."""
        if self.hilo_comparador is not None:
            return
        self.hilo_comparador = QThread(self)
        self.servicio_comparador = ServicioComparador(escuadra=True, prioridad=self.prioridad_recompensas)
        self.servicio_comparador.moveToThread(self.hilo_comparador)
        self.hilo_comparador.started.connect(self.servicio_comparador.iniciar)
        self.lector_recompensas.leidas.connect(self.servicio_comparador.comparar)
        self.recompensas_conocidas.connect(self.servicio_comparador.comparar)
        self.servicio_comparador.veredicto.connect(self._veredicto_recompensas)
        # EE.log dice que reliquia llevas unos minutos antes de abrirla, y que le ha
        # tocado a cada companero al abrirse: con eso los precios se piden antes de
        # que haga falta ensenarlos. El vigilante lo crea _arrancar_captura, que va antes.
        if self.vigilante is not None:
            self.vigilante.pista.connect(self.servicio_comparador.precargar)
            self.vigilante.evento.connect(self.servicio_comparador.evento)
        self.hilo_comparador.start()

    # -- el juego: version y modo de pantalla ---------------------------------

    def _arranque_juego(self, cabecera) -> None:
        """EE.log dice con que build y en que modo de ventana ha arrancado Warframe."""
        self.cabecera_juego = cabecera
        self._comprobar_desfase()
        self._refrescar_modo_pantalla()
        comprobador = getattr(self, "comprobador_datos", None)
        if comprobador is not None and self._avisos.get("parche"):
            # Si el juego va por delante de los datos, se mira ya si WFCD/DE han publicado.
            comprobador.comprobar()

    def _comprobar_desfase(self) -> None:
        """Compara la fecha del build del juego con la de los datos descargados."""
        self._desfase_comprobado = True
        fecha_build = getattr(self.cabecera_juego, "fecha_build", None)
        atrasadas = indice.desfase_con_el_juego(indice.leer_meta(), fecha_build)
        if not atrasadas:
            self._aviso("parche", None)
            self.ajustes.avisar_parche(None)
            return
        build = getattr(self.cabecera_juego, "build", "") or "?"
        # Si lo descargado ya es lo ultimo publicado, no es un fallo: DE puede pasar meses
        # sin tocar sus tablas tras un parche. Solo suena a aviso los dias siguientes al
        # parche, que es cuando de verdad puede faltar contenido; despues queda como dato.
        from ..datos.descargas import EstadoDatos, fuentes_pendientes

        pendientes = fuentes_pendientes(EstadoDatos.cargar(), atrasadas)
        reciente = indice.parche_reciente(fecha_build)
        texto, aviso = indice.texto_desfase(atrasadas, pendientes, build, fecha_build, reciente)
        if reciente:
            log.warning("Datos anteriores al parche del juego: build %s, %s", build, atrasadas)
            self._aviso("parche", texto)
        else:
            self._aviso("parche", None)
        self.ajustes.avisar_parche(texto, aviso=aviso)

    def _refrescar_modo_pantalla(self) -> str:
        modo = pantalla.modo_pantalla()
        if modo != self.modo_pantalla:
            log.info("Modo de pantalla del juego: %s", modo)
        self.modo_pantalla = modo
        self.ajustes.mostrar_modo_pantalla(modo)
        if modo == pantalla.MODO_EXCLUSIVO:
            self._aviso(
                "exclusivo",
                t(
                    "Warframe esta en pantalla completa exclusiva: ninguna ventana puede dibujarse "
                    "encima del juego, ni las etiquetas de recompensas. Cambia a Ventana sin bordes "
                    "en Opciones > Pantalla, o usa Farmadex en el segundo monitor."
                ),
            )
        else:
            self._aviso("exclusivo", None)
        return modo

    def _aviso(self, clave: str, texto: str | None) -> None:
        """Mantiene el banner con los avisos activos; sin ninguno, se esconde."""
        if texto:
            self._avisos[clave] = texto
        else:
            self._avisos.pop(clave, None)
        self._pintar_banner()

    def _pintar_banner(self) -> None:
        """En la vista completa, el banner entero. En la compacta, una sola linea recortada
        (el texto entero queda en el tooltip) y la ventana crece lo que mide el banner:
        con 190 px de alto, dos lineas de aviso se comian el resultado de la busqueda."""
        if not self._avisos:
            self.banner.hide()
            self.banner.setToolTip("")
            self._reservar_banner_compacto(False)
            return
        if self.modo == "compacto":
            self.banner.setTextFormat(Qt.PlainText)
            self.banner.setWordWrap(False)
            self.banner.setToolTip(self._banner_plano())
            self._elidir_banner()
        else:
            self.banner.setTextFormat(Qt.RichText)
            self.banner.setWordWrap(True)
            self.banner.setToolTip("")
            self.banner.setText("<br>".join(self._avisos.values()))
        self.banner.show()
        self._reservar_banner_compacto(self.modo == "compacto")

    def _banner_plano(self) -> str:
        return " · ".join(_texto_plano(a) for a in self._avisos.values())

    def _elidir_banner(self) -> None:
        """La linea unica de la compacta, recortada al ancho real del banner."""
        # Margenes del marco (10+10), padding del banner (8+8) y sus bordes.
        ancho = self.banner.contentsRect().width() if self.banner.isVisible() else self.width() - 40
        ancho = max(60, ancho - 16)
        self.banner.setText(self.banner.fontMetrics().elidedText(self._banner_plano(), Qt.ElideRight, ancho))

    def _reservar_banner_compacto(self, reservar: bool) -> None:
        """Hace crecer (o encoger) la ventana compacta lo que ocupa el banner, para que el
        aviso no le quite sitio al resultado. En la completa no hace falta: hay espacio."""
        if self.modo != "compacto":
            reservar = False
        alto = (self.banner.sizeHint().height() + self.marco.layout().spacing()) if reservar else 0
        delta = alto - self._alto_banner_compacto
        self._alto_banner_compacto = alto
        if self.modo == "compacto":
            self.setMinimumHeight(ALTO_MINIMO_COMPACTO + alto)
        if delta:
            self.resize(self.width(), max(self.minimumHeight(), self.height() + delta))

    def _regenerar_avisos(self) -> None:
        """Tras cambiar de idioma o de tema: los avisos se escriben ya traducidos y con
        los colores del tema dentro del HTML, asi que hay que volver a generarlos."""
        if self._version_avisada is not None:
            version, local = self._version_avisada
            if local:
                self._hay_version_local(version)
            else:
                self._hay_version_nueva(version)
        if self._desfase_comprobado:
            self._comprobar_desfase()
        if "exclusivo" in self._avisos:
            self._refrescar_modo_pantalla()
        self._pintar_banner()

    def resizeEvent(self, evento):  # noqa: N802 - firma de Qt
        super().resizeEvent(evento)
        if self.modo == "compacto" and self._avisos:
            self._elidir_banner()
        if self._guia is not None:
            self._guia.reposicionar()

    def _pantalla_libre(self) -> QRect | None:
        """Geometria de un monitor que no sea el del juego, si lo hay."""
        juego = pantalla.region_juego()
        pantallas = QGuiApplication.screens()
        if not juego or len(pantallas) < 2:
            return None
        cx, cy = juego.centro
        for p in pantallas:
            g = p.geometry()
            # Con Windows al 100 % las coordenadas de Qt y de Win32 coinciden; con
            # escala, el monitor del juego se descarta igual por su origen.
            if not g.contains(QPoint(cx, cy)) and not g.contains(QPoint(juego.x, juego.y)):
                return p.availableGeometry()
        return None

    def _asegurar_en_pantalla(self) -> None:
        """La geometria guardada puede apuntar a un monitor que ya no esta, o a una
        resolucion mayor que la actual: se encoge si no cabe y se reencuadra dentro de
        la pantalla mas parecida, sin descolocar mas de lo necesario."""
        g = self.frameGeometry()
        pantallas = QGuiApplication.screens()
        pantalla = next((p for p in pantallas if p.availableGeometry().intersects(g)), None)
        centrar = pantalla is None
        if pantalla is None:
            pantalla = QGuiApplication.primaryScreen()
        if pantalla is None:
            return
        disponible = pantalla.availableGeometry()
        ancho = min(self.width(), disponible.width())
        alto = min(self.height(), disponible.height())
        if (ancho, alto) != (self.width(), self.height()):
            self.resize(ancho, alto)
        if centrar:
            self.move(disponible.center() - QPoint(self.width() // 2, self.height() // 2))
            return
        x = min(max(self.x(), disponible.x()), disponible.x() + disponible.width() - self.width())
        y = min(max(self.y(), disponible.y()), disponible.y() + disponible.height() - self.height())
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def _arrancar_actualizador(self) -> None:
        """Vigila si salen datos nuevos del juego o una version nueva de la app."""
        if getattr(self, "comprobador_datos", None) is not None:
            return
        self.comprobador_datos = ComprobadorDatos(self)
        self.comprobador_datos.hay_novedades.connect(self._hay_datos_nuevos)
        self.comprobador_datos.iniciar()

        # Las compilaciones sin publicar se dejan en una carpeta del PC; las
        # publicadas salen de GitHub. El boton de Ajustes mira las dos.
        self.comprobador_local = ComprobadorLocal(parent=self)
        self.comprobador_local.nueva_version.connect(self._hay_version_local)
        self.ajustes.comprobar_version.connect(self._comprobar_version)
        QTimer.singleShot(2000, self.comprobador_local.comprobar)
        self._reloj_versiones = QTimer(self)
        self._reloj_versiones.timeout.connect(self.comprobador_local.comprobar)
        self._reloj_versiones.start(30 * 60 * 1000)

        self.comprobador_app = ComprobadorApp(self)
        self.comprobador_app.nueva_version.connect(self._hay_version_nueva)
        self.comprobador_app.sin_novedades.connect(self._no_hay_version_nueva)
        self.comprobador_app.fallo.connect(self._fallo_al_comprobar_version)
        self.descargador = DescargadorApp(parent=self)
        self.descargador.progreso.connect(self._progreso_descarga)
        self.descargador.lista.connect(self._actualizacion_lista)
        self.descargador.fallo.connect(self._fallo_descarga)
        # El instalador espera a que este mutex se suelte antes de sustituir los ficheros.
        instalacion.senalar_en_ejecucion()
        self._contar_instalacion_anterior()
        if self.config.get("comprobar_actualizaciones_app", True):
            QTimer.singleShot(5000, self.comprobador_app.comprobar)

    def _contar_instalacion_anterior(self) -> None:
        """Si la sesion anterior lanzo una actualizacion automatica, decir como acabo."""
        try:
            resultado = instalacion.resultado_instalacion_anterior()
        except Exception as e:  # noqa: BLE001 - un apunte ilegible no puede tumbar el arranque
            log.warning("No se pudo leer el resultado de la actualizacion anterior: %s", e)
            return
        if not resultado:
            return
        estado, etiqueta = resultado
        if estado == "instalada":
            self.estado.setText(t("Farmadex se ha actualizado a la version {version}", version=etiqueta))
            # El setup que nos acaba de abrir aun puede estar cerrandose: se barre luego.
            QTimer.singleShot(60_000, descarga.limpiar)
        elif estado == "aplazada":
            # El instalador sigue descargado: la proxima comprobacion lo da por listo
            # al instante y se instala al cerrar el ultimo Farmadex.
            self._aviso(
                "version",
                t(
                    "La actualizacion {version} se aplazo: habia otro Farmadex abierto. "
                    "Se instalara al cerrar el ultimo.",
                    version=etiqueta,
                ),
            )
        else:
            motivo = instalacion.motivo_fallida()
            if motivo:
                # El motivo va en castellano en fallida.json: el fijo se traduce entero y
                # el de "se detuvo" lleva detras la linea del instalador tal cual.
                fijo = instalacion.MOTIVO_DETENIDO.split("{detalle}")[0]
                motivo = (
                    t(instalacion.MOTIVO_DETENIDO, detalle=motivo[len(fijo):])
                    if motivo.startswith(fijo)
                    else t(motivo)
                )
            self._aviso(
                "version",
                t(
                    "La actualizacion {version} no llego a instalarse; sigues en la {actual}. "
                    "Motivo: {motivo}. El detalle esta en logs/instalador.log.",
                    version=etiqueta, actual=VERSION, motivo=motivo or "?",
                ),
            )

    def _hay_datos_nuevos(self, motivo: str) -> None:
        self.estado.setText(t("Actualizando datos ({motivo})...", motivo=motivo))
        self.preparar_datos(forzar=True)

    def _hay_version_nueva(self, version) -> None:
        """Version nueva publicada. Se avisa en el banner, que no se borra solo.

        Antes esto iba a la linea de estado, que a los pocos segundos la pisa el
        primer mensaje de la carga de datos o de la siguiente busqueda: el aviso
        salia y desaparecia sin que diera tiempo a leerlo.
        """
        self.nueva_version = version
        self._version_avisada = (version, False)
        lista = self.actualizacion_lista
        if lista and lista[0].etiqueta == version.etiqueta:
            # Ya descargada (se vuelve a pasar por aqui al cambiar de idioma o tema).
            self._actualizacion_lista(*lista)
            return
        fallo = self._fallo_actualizacion
        if fallo and fallo[0] == version.etiqueta:
            self._avisar_descarga_manual(version, motivo=fallo[1])
            return
        if self._conviene_autoactualizar(version):
            self._descargar_actualizacion(version)
        else:
            self._avisar_descarga_manual(version)

    def _avisar_descarga_manual(self, version, motivo: str | None = None) -> None:
        """El aviso de siempre: enlace de descarga (con el motivo si la automatica fallo)."""
        enlace = f'<a style="color:{PALETA["acento"]}" href="{version.url}">{t("Descargala")}</a>'
        if motivo:
            texto = t(
                "No se pudo preparar la actualizacion {version} ({motivo}). {enlace}",
                version=version.etiqueta, motivo=motivo, enlace=enlace,
            )
        else:
            texto = t(
                "Hay una version nueva de Farmadex ({version}). {enlace}, o instalala desde Ajustes.",
                version=version.etiqueta, enlace=enlace,
            )
        self._aviso("version", texto)
        self.ajustes.anunciar_version(version)

    def _conviene_autoactualizar(self, version) -> bool:
        """Solo si el usuario lo quiere, corre la version instalada con el setup (no el
        portable ni el codigo) y esa misma version no fallo ya al instalarse sola."""
        if not self.config.get("actualizar_automaticamente", True):
            return False
        if not instalacion.es_instalacion_por_instalador():
            return False
        return instalacion.version_fallida() != version.etiqueta

    def _descargar_actualizacion(self, version) -> None:
        self._aviso(
            "version",
            t("Descargando la actualizacion {version} en segundo plano...", version=version.etiqueta),
        )
        self.ajustes.estado_version(t("Descargando la version {version}...", version=version.etiqueta))
        if self.descargador is not None:
            self.descargador.descargar(version)

    def _progreso_descarga(self, pct: int) -> None:
        version = self.nueva_version
        if version is None or self.actualizacion_lista or pct < 0:
            return
        self._aviso(
            "version",
            t(
                "Descargando la actualizacion {version} en segundo plano... {pct}%",
                version=version.etiqueta, pct=pct,
            ),
        )

    def _actualizacion_lista(self, version, ruta) -> None:
        """Descargada y con la huella comprobada: se instala al cerrar, o ahora si se pulsa."""
        self.actualizacion_lista = (version, ruta)
        self._fallo_actualizacion = None
        self._aviso(
            "version",
            t(
                'Actualizacion {version} lista. <a style="color:{color}" href="farmadex:actualizar">'
                "Reiniciar y actualizar</a> (si no, se instala sola al cerrar Farmadex).",
                version=version.etiqueta, color=PALETA["acento"],
            ),
        )
        self.ajustes.anunciar_version(version, lista=True)

    def _fallo_descarga(self, version, motivo: str) -> None:
        """Sin red, sin huella, huella que no cuadra, disco...: se sigue con la actual."""
        self._fallo_actualizacion = (version.etiqueta, motivo)
        self._avisar_descarga_manual(version, motivo=motivo)

    def _enlace_banner(self, href: str) -> None:
        if href == "farmadex:actualizar":
            self._reiniciar_y_actualizar()
        elif href == "farmadex:guia":
            self.mostrar_guia()
        elif href:
            QDesktopServices.openUrl(QUrl(href))

    def _reiniciar_y_actualizar(self) -> None:
        if self._lanzar_instalacion_pendiente(a_mano=True):
            self.estado.setText(t("Instalando... Farmadex se va a cerrar."))
            QTimer.singleShot(500, self.cerrar_programa.emit)

    def _lanzar_instalacion_pendiente(self, a_mano: bool = False) -> bool:
        """Lanza el setup silencioso si hay una actualizacion lista; una sola vez.

        Al cerrar (`a_mano` False) solo si la casilla sigue activada: quien la
        desactiva despues de la descarga no quiere que se instale sola.
        """
        if not self.actualizacion_lista or self._instalador_lanzado:
            return False
        if not a_mano and not self.config.get("actualizar_automaticamente", True):
            return False
        version, ruta = self.actualizacion_lista
        if instalacion.otra_instancia_abierta():
            # El setup esperaria a un Farmadex que no se va a cerrar, se rendiria y
            # ese abandono quedaria apuntado como fallo de la version. Se deja la
            # descarga tal cual: la instala el ultimo Farmadex que se cierre.
            log.info("Hay otro Farmadex abierto: la actualizacion %s se instalara mas tarde", version.etiqueta)
            self._aviso(
                "version",
                t(
                    "Hay otro Farmadex abierto: la actualizacion {version} se instalara al cerrar el ultimo.",
                    version=version.etiqueta,
                ),
            )
            return False
        if instalacion.instalar_silencioso(ruta, version.etiqueta):
            self._mostrar_aviso_actualizando(version.etiqueta)
            self._instalador_lanzado = True
            return True
        self.actualizacion_lista = None
        self._fallo_descarga(version, t("no se pudo lanzar el instalador"))
        return False

    def _mostrar_aviso_actualizando(self, etiqueta: str) -> None:
        """Aviso breve, encima de todo y sin bordes, justo antes de lanzar el instalador.

        Este proceso muere en cuanto arranca el setup, asi que el aviso no se
        mantiene vivo durante la instalacion: de eso ya se encarga la ventana de
        progreso del propio instalador (/SILENT). Solo tapa el hueco entre que se
        lanza el setup y que Farmadex termina de cerrarse.
        """
        aviso = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        aviso.setAttribute(Qt.WA_DeleteOnClose)
        aviso.setStyleSheet(
            hoja_estilos() + f"QWidget {{ border: 1px solid {PALETA['acento']}; border-radius: 10px; }}"
        )
        diseno = QVBoxLayout(aviso)
        diseno.setContentsMargins(26, 20, 26, 20)
        texto = QLabel(t(
            "Actualizando Farmadex a la version {version}. Se cerrara y volvera a abrirse sola.",
            version=etiqueta,
        ))
        texto.setWordWrap(True)
        texto.setStyleSheet(f"color: {PALETA['texto']}; font-size: 14px;")
        diseno.addWidget(texto)
        aviso.adjustSize()
        pantalla = QGuiApplication.primaryScreen()
        if pantalla is not None:
            geo = pantalla.geometry()
            aviso.move(geo.center().x() - aviso.width() // 2, geo.center().y() - aviso.height() // 2)
        aviso.show()
        aviso.raise_()
        QGuiApplication.processEvents()
        self._aviso_actualizando = aviso

    def _comprobar_version(self) -> None:
        """Comprobacion a mano desde Ajustes: siempre contesta algo.

        Primero la carpeta de compilaciones, que es instantanea; si ahi no hay
        nada, se pregunta a GitHub, que tarda y contesta por su cuenta. Hasta
        entonces, Ajustes se queda en "Comprobando...".
        """
        self._version_encontrada = None
        self.comprobador_local.comprobar()
        if self._version_encontrada is not None:
            return
        self.comprobador_app.comprobar_a_mano()

    def _no_hay_version_nueva(self) -> None:
        self.ajustes.estado_version(t("Estas en la ultima version ({version})", version=VERSION))

    def _fallo_al_comprobar_version(self, motivo: str) -> None:
        self.ajustes.estado_version(
            t("No se ha podido comprobar si hay version nueva ({motivo})", motivo=motivo)
        )

    def _hay_version_local(self, version) -> None:
        self._version_encontrada = version
        self._version_avisada = (version, True)
        self.ajustes.estado_version(t("Hay una version nueva: {version}", version=version.etiqueta))
        self._aviso(
            "version",
            t("Hay compilada una version nueva ({version}): instalala desde Ajustes.",
              version=version.etiqueta),
        )
        self.ajustes.anunciar_version(version, local=True)

    def _instalar_version(self, version) -> None:
        lista = self.actualizacion_lista
        if lista and lista[0].etiqueta == getattr(version, "etiqueta", None):
            self._reiniciar_y_actualizar()
            return
        if instalar(version):
            self.estado.setText(t("Instalando... Farmadex se va a cerrar."))
            QTimer.singleShot(500, self.cerrar_programa.emit)
        else:
            self.estado.setText(t("No se pudo lanzar el instalador; mira la carpeta que se ha abierto"))

    def _evento_juego(self, nombre: str) -> None:
        self.disparador.evento(nombre)
        if nombre == "reliquia_abierta":
            self._conocidas_log = []
            self._nueva_pantalla()
        elif nombre == "reliquia_recompensas":
            if self._t_reliquia is None or self._t_cerrada is not None:
                self._nueva_pantalla()  # "Relic rewards initialized" no llego: este es el primer aviso
            self._t_cerrada = None
            self._avisar_si_no_se_va_a_ver()
            self._anotar_pantalla_pintada()
        elif nombre == "reliquia_cerrada":
            self._t_cerrada = time.monotonic()
            self._t_pintadas = None
            self._temporizador_conocidas.stop()
            self.etiquetas.hide()
        if self.botin.evento(nombre):
            self.objetivos.refrescar()

    def _nueva_pantalla(self) -> None:
        self._t_reliquia = time.monotonic()
        self._t_reliquia_reloj = time.time()
        self._t_cerrada = None
        self._t_pantalla = None
        self._t_pintadas = None

    def _anotar_pantalla_pintada(self) -> None:
        """Con "Got rewards" se sabe cuando pinto el juego las tarjetas (la linea se
        escribe en ese momento, aunque llegue segundos despues): queda en el registro
        lo que tardaron los nombres desde ESE instante, que es lo que ve el usuario."""
        retraso = getattr(self.vigilante, "retrasos", {}).get("reliquia_recompensas")
        if retraso is None:
            return
        self._t_pantalla = time.monotonic() - retraso
        if self._t_pintadas is not None:
            log.info(
                "'Got rewards' llego %.0f ms despues de escribirse; los nombres ya estaban "
                "pintados desde %.0f ms despues de que el juego pintara la pantalla",
                retraso * 1000, (self._t_pintadas - self._t_pantalla) * 1000,
            )

    def _pista_juego(self, tipo: str, valor: str) -> None:
        if tipo == "recompensa" and valor not in self._conocidas_log:
            self._conocidas_log.append(valor)
            self._temporizador_conocidas.start()

    def _recompensas_conocidas(self) -> None:
        """Lo que EE.log dio de la reliquia: nombres exactos, ducados y veredicto ya, sin OCR."""
        if not self._conocidas_log or self.hilo_captura is None:
            return
        con = indice.conectar()
        try:
            recompensas = []
            for unique_name in self._conocidas_log:
                fila = indice.fila_por_ruta(con, unique_name, "id, nombre_es, nombre_en")
                if fila:
                    nombre = (fila[1] or fila[2]) if es_castellano() else (fila[2] or fila[1])
                    recompensas.append(Recompensa(fila[0], nombre, "", None))
            if not recompensas:
                return
            completar(recompensas, con, self.objetivos.usuario)
        finally:
            con.close()
        desde = f"{(time.monotonic() - self._t_reliquia) * 1000:.0f} ms" if self._t_reliquia else "?"
        log.info("Recompensas por EE.log (%d de la escuadra, %s desde el aviso): %s",
                 len(recompensas), desde, resumir(recompensas))
        self.estado.setText(t("Por EE.log: {resumen}", resumen=resumir(recompensas)))
        self.servicio_comparador.comparar(recompensas) if self.hilo_comparador is None else \
            self.recompensas_conocidas.emit(recompensas)

    def _sumar_botin(self, unique_name: str, cantidad: int, origen: str) -> None:
        objetivo = estado_objetivos.sumar_por_item(self.objetivos.usuario, unique_name, cantidad, origen=origen)
        if objetivo is not None:
            self.estado.setText(t("+{n} {nombre} (EE.log)", n=cantidad, nombre=objetivo.nombre))

    def _pagina_perfil_leida(self, pagina) -> None:
        """Una pagina de Perfil > Equipamiento leida sola: se guarda como con F9."""
        con = indice.conectar()
        try:
            lecturas = desde_ocr.desde_tarjetas(pagina.tarjetas, pagina.categoria or "")
            completados = (
                {pagina.categoria: pagina.completado} if pagina.categoria and pagina.completado else None
            )
            resultado = desde_ocr.guardar(
                self.objetivos.usuario, con, lecturas, pagina.rango_maestria, completados=completados
            )
        except Exception:  # noqa: BLE001 - una lectura mala no puede tumbar la ventana
            log.exception("No se pudo guardar la pagina de perfil leida sola")
            return
        finally:
            con.close()
        log.info("Perfil actualizado solo: %d objetos con rango, %d sin leer",
                 resultado.guardadas, len(resultado.desconocidas))
        self.estado.setText(t("Perfil leido solo: {n} objetos", n=len(lecturas)))
        self.perfil.pintar()
        self.buscador.refrescar_perfil()

    def _pagina_inventario_leida(self, pagina) -> None:
        """Cantidades leidas solas en Inventario/Fundicion: solo las fiables entran."""
        fiables = pagina.fiables
        if not fiables:
            return
        try:
            n = estado_inventario.guardar(self.objetivos.usuario, fiables, pagina.pantalla)
            cambios = estado_inventario.sincronizar_objetivos(self.objetivos.usuario)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo guardar la lectura del inventario")
            return
        self.estado.setText(t("{n} cantidades leidas solas en pantalla", n=n))
        if cambios:
            self.objetivos.refrescar()
        self.buscador.repintar()

    def leer_recompensas(self) -> None:
        """Lee la pantalla de recompensas de reliquia (atajo o aviso de EE.log)."""
        if self.hilo_captura is None:
            self.estado.setText(t("Los datos todavia se estan preparando"))
            return
        self._t_lectura_pedida = time.monotonic()
        if self._t_pintadas is None:
            # Fuera lo de la pantalla anterior. Si esta ya tiene los nombres pintados
            # (lectura por "Relic rewards initialized" y "Got rewards" que llega tarde),
            # esconderlos hasta la relectura solo haria parpadear el panel.
            self.etiquetas.hide()
        QTimer.singleShot(0, self.lector_recompensas.leer_ahora)

    def leer_build(self) -> None:
        """Atajo o boton de la pestana Build: lee la pantalla de mejoras del arsenal."""
        if self.hilo_captura is None:
            self.estado.setText(t("Los datos todavia se estan preparando"))
            return
        QTimer.singleShot(0, self.lector_build.leer_ahora)

    def _build_leida(self, build) -> None:
        self.builds.mostrar_build(build)
        if build.vacia:
            return
        self.mostrar()
        if self.modo != "completo":
            self.aplicar_modo("completo")
        self.pestanas.setCurrentWidget(self.builds)

    def leer_agrietado(self) -> None:
        """Atajo o boton de la pestana Agrietados: lee la tarjeta que hay bajo el cursor."""
        if self.hilo_captura is None:
            self.estado.setText(t("Los datos todavia se estan preparando"))
            return
        QTimer.singleShot(0, self.lector_agrietado.leer_ahora)

    def _agrietado_leido(self, tarjeta) -> None:
        self.agrietados.mostrar_tarjeta(tarjeta)
        if tarjeta.velado or (not tarjeta.estadisticas and not tarjeta.arma_texto):
            return
        self.mostrar()
        if self.modo != "completo":
            self.aplicar_modo("completo")
        self.pestanas.setCurrentWidget(self.agrietados)

    def leer_cursor(self) -> None:
        """Atajo de "leer el objeto bajo el cursor": una lectura a la vez.

        Si ya hay una en marcha (o la anterior acaba de empezar), la pulsacion se
        apunta y se lee otra vez al terminar; varias pulsaciones seguidas cuentan
        como una sola, la ultima.
        """
        if self.hilo_captura is None:
            return
        estado = self.turno_cursor.pedir()
        self.lector_cursor.ultima_pedida = self.turno_cursor.ultima
        if estado != "lanzada":
            log.debug("Lectura bajo el cursor apuntada para cuando acabe la actual")

    def _lectura_cursor_terminada(self, numero: int) -> None:
        self.turno_cursor.terminada(numero)

    # -- avisos que tienen que verse y diagnostico -----------------------------------

    def _aviso_visible(self, clave: str, texto: str) -> None:
        """Manda `texto` a la bandeja, como mucho una vez cada REPETIR_AVISO_S por clave.

        El banner y la linea de estado viven dentro de la ventana, que durante una
        reliquia esta escondida: el usuario no veia nada y creia que Farmadex no
        hacia nada. El globo de la bandeja se ve encima del juego (salvo en pantalla
        completa exclusiva, donde al menos queda en el centro de notificaciones).
        """
        ahora = time.monotonic()
        ultimo = self._avisos_bandeja.get(clave)
        if ultimo is not None and ahora - ultimo < self.REPETIR_AVISO_S:
            return
        self._avisos_bandeja[clave] = ahora
        log.warning("Aviso al usuario (%s): %s", clave, texto)
        self.aviso_bandeja.emit(texto)

    def _avisar_si_no_se_va_a_ver(self) -> None:
        """Al abrirse una reliquia: si ya se sabe que no va a salir nada, se dice ahora."""
        if self._refrescar_modo_pantalla() == pantalla.MODO_EXCLUSIVO:
            self._aviso_visible("exclusivo", t(
                "Reliquia abierta, pero Warframe esta en pantalla completa exclusiva y Farmadex no "
                "puede pintar encima. En el juego: Opciones > Pantalla > Modo de pantalla = "
                "'Ventana sin bordes'."
            ))
        lector = getattr(self, "lector_recompensas", None)
        if lector is not None and lector.motor.fallo:
            self._aviso_visible("motor", t(
                "Reliquia abierta, pero el lector de pantalla no carga: no se pueden leer las "
                "recompensas. Abre Ajustes > Diagnostico de reliquias."
            ))
        elif getattr(self, "disparador", None) is not None and not self.disparador.activo:
            self._aviso_visible("auto", t(
                "Reliquia abierta, pero la lectura automatica esta desactivada en Ajustes: "
                "pulsa {atajo} para leerla.", atajo=self.config.get("hotkey_reliquias", ""),
            ))

    def diagnostico(self):
        """Todo lo que se sabe de la cadena reliquia -> etiquetas, como `diagnostico.Diagnostico`."""
        from .. import diagnostico as diag

        hwnd = pantalla.ventana_juego()
        juego = pantalla.region_ventana(hwnd) if hwnd else None
        monitor = pantalla.monitor_de(hwnd) if hwnd else None
        lector = getattr(self, "lector_recompensas", None)
        motor = lector.motor if lector is not None else None
        return diag.recoger(
            eelog=self.vigilante.estado() if self.vigilante is not None else None,
            ruta_eelog_configurada=str(self.config.get("ruta_eelog", "")),
            ruta_eelog_por_defecto=str(config_modulo.POR_DEFECTO["ruta_eelog"]),
            modo_pantalla=self._refrescar_modo_pantalla(),
            juego=juego,
            monitor_juego=monitor,
            escala=pantalla.escala_fisica_logica(hwnd) if hwnd else 1.0,
            monitores=len(QGuiApplication.screens()),
            motor_fallo=motor.fallo if motor is not None else None,
            motor_cargado=motor.cargado if motor is not None else None,
            motor_nombre=motor.motor if motor is not None else str(self.config.get("motor_ocr", "rapidocr")),
            config=self.config,
            datos_listos=self.hilo_captura is not None,
            hay_indice=indice.hay_indice(),
            ultima_pantalla=self._t_reliquia_reloj,
            ultima_lectura=self._ultima_lectura,
            ultima_pintada=self._ultima_pintada,
            idioma=idiomas.actual(),
        )

    def mostrar_diagnostico(self):
        """Ajustes > 'Comprobar la lectura de reliquias'."""
        d = self.diagnostico()
        log.info("Diagnostico de reliquias:\n%s", d.texto())
        self.ajustes.mostrar_diagnostico(d)
        return d

    def guardar_informe(self):
        """Ajustes > 'Guardar informe para enviar': el .zip en el Escritorio, y se ensena."""
        from .. import diagnostico as diag

        d = self.mostrar_diagnostico()
        try:
            ruta = diag.guardar_informe(d)
        except OSError as e:
            log.exception("No se pudo guardar el informe de diagnostico")
            self.ajustes.informe_guardado(None, str(e))
            return None
        self.ajustes.informe_guardado(ruta)
        diag.revelar(ruta)
        return ruta

    def _pintar_recompensas(self, recompensas: list) -> None:
        self._ultima_lectura = (time.time(), len(recompensas))
        if not recompensas:
            return
        t0 = time.perf_counter()
        con = indice.conectar()
        try:
            completar(recompensas, con, self.objetivos.usuario)
            maestria = self._maestria_recompensas(recompensas, con)
            extras = self._extras_recompensas(recompensas, con) if self.etiquetas is self.panel_recompensas else {}
        finally:
            con.close()
        t_completar = time.perf_counter() - t0
        # El resumen en texto vale en cualquier modo de pantalla (y queda en el log).
        resumen = resumir(recompensas)
        log.info("Recompensas: %s", resumen)
        if self._refrescar_modo_pantalla() == pantalla.MODO_EXCLUSIVO:
            self.estado.setText(t("Recompensas (no se pueden pintar encima del juego): {resumen}", resumen=resumen))
            self._aviso_visible("exclusivo", t(
                "Recompensas leidas, pero Warframe esta en pantalla completa exclusiva y no se pueden "
                "pintar encima: {resumen}. Cambia el juego a 'Ventana sin bordes' (Opciones > Pantalla).",
                resumen=resumen,
            ))
            return
        self.estado.setText(resumen)
        if (self._t_cerrada is not None and self._t_lectura_pedida is not None
                and self._t_cerrada > self._t_lectura_pedida):
            # La pantalla ya se cerro mientras se leia: pintarlas ahora seria encima
            # de otra cosa. Queda en el log con lo que tardo, que es el dato que importa.
            log.warning(
                "Las recompensas llegaron %.1f s despues de cerrarse la pantalla: no se pintan",
                time.monotonic() - self._t_cerrada,
            )
            return
        t0 = time.perf_counter()
        if self.etiquetas is self.panel_recompensas:
            self.panel_recompensas.mostrar(_a_logicas(recompensas), maestria, extras)
        else:
            self.etiquetas.mostrar(_a_logicas(recompensas), maestria)
        self._ultima_pintada = (time.time(), len(recompensas))
        ahora = time.monotonic()
        if self._t_pintadas is None:
            self._t_pintadas = ahora
        desde = f"{(ahora - self._t_reliquia) * 1000:.0f} ms" if self._t_reliquia else "?"
        desde_pantalla = (
            f" (~{(ahora - self._t_pantalla) * 1000:.0f} ms desde que el juego pinto la pantalla)"
            if self._t_pantalla is not None else ""
        )
        log.info("Reliquia: completar %.1f ms, pintar %.1f ms; nombres en pantalla %s desde el aviso de EE.log%s",
                 t_completar * 1000, (time.perf_counter() - t0) * 1000, desde, desde_pantalla)

    def _veredicto_recompensas(self, recompensas: list, veredicto) -> None:
        """Llega despues, con los precios: solo añade la marca de "mejor" a lo que ya se ve."""
        if self.modo_pantalla == pantalla.MODO_EXCLUSIVO:
            return
        self.etiquetas.marcar_veredicto(recompensas, veredicto)
        if veredicto.puntuaciones:
            self.estado.setText(veredicto.resumen())

    def cambiar_estilo_recompensas(self, estilo: str) -> None:
        """Ajustes: "etiquetas" o "panel". Lo que este en pantalla se esconde."""
        self.etiquetas.hide()
        self.etiquetas = self.panel_recompensas if estilo == "panel" else self.etiquetas_pequenas

    def cambiar_prioridad_recompensas(self, prioridad: str) -> None:
        """Ajustes: que destacar. Vale desde la siguiente reliquia; lo que se ve se repinta
        con el motivo nuevo, pero la marca de "mejor" es del veredicto que ya llego."""
        self.prioridad_recompensas = prioridad_recompensas.normalizar(prioridad)
        for vista in (self.etiquetas_pequenas, self.panel_recompensas):
            vista.prioridad = self.prioridad_recompensas
            vista.update()
        servicio = getattr(self, "servicio_comparador", None)
        if servicio is not None:
            servicio.prioridad = self.prioridad_recompensas

    def _extras_recompensas(self, recompensas: list, con) -> dict[int, dict]:
        """Lo que el panel ensena ademas: miniatura, tiempo medio de farmeo y cuantas tienes."""
        from ..datos import relaciones

        extras: dict[int, dict] = {}
        for r in recompensas:
            if not r.item_id:
                continue
            datos: dict = {}
            fila = con.execute("SELECT imagen FROM items WHERE id = ?", (r.item_id,)).fetchone()
            if fila and fila[0]:
                datos["imagen"] = fila[0]
            try:
                ruta = relaciones.mejor_ruta(con, r.item_id)
                if ruta and ruta.get("minutos_medios") is not None:
                    datos["minutos"] = eficiencia.texto_minutos(ruta["minutos_medios"])
            except Exception:  # noqa: BLE001 - un extra nunca deja sin panel
                log.debug("Sin ruta para la recompensa %s", r.item_id, exc_info=True)
            if r.unique_name:
                lectura = estado_inventario.cantidad_de(self.objetivos.usuario, r.unique_name)
                if lectura is not None:
                    datos["tienes"] = lectura.cantidad
            extras[r.item_id] = datos
        return extras

    def _maestria_recompensas(self, recompensas: list, con) -> dict[int, tuple[str, str]]:
        """Para cada recompensa que da rango (o cuya pieza lo da): (texto, estado). Vacio sin perfil."""
        if not self.perfil.hay_perfil():
            return {}
        marcas = {}
        for r in recompensas:
            estado = estado_con_padre(self.objetivos.usuario, con, r.item_id)
            texto = texto_maestria(estado)
            if texto:
                marcas[r.item_id] = (texto, estado.estado)
        return marcas

    def _abrir_desde_cursor(self, item_id: int, nombre: str) -> None:
        self.mostrar()
        if self.modo == "compacto":
            self.compacta.abrir(item_id)
            return
        self.pestanas.setCurrentWidget(self.buscador)
        self.buscador.abrir(item_id)

    def _buscar_desde_mundo(self, texto: str) -> None:
        """Una recompensa de Mundo que no esta en el indice: se busca por su nombre."""
        self.mostrar()
        if self.modo == "compacto":
            self.aplicar_modo("completo")
        self.pestanas.setCurrentWidget(self.buscador)
        self.buscador.caja.setText(texto)

    def _abrir_completo(self, item_id: int) -> None:
        """Enter en la vista compacta: la ficha entera de ese objeto."""
        self.aplicar_modo("completo")
        self.pestanas.setCurrentWidget(self.buscador)
        self.buscador.abrir(item_id)

    # -- modo completo y compacto ---------------------------------------------

    def alternar_modo(self) -> None:
        # Desde el modo video, Ctrl+M o "Salir del video" vuelven a la vista completa.
        self.aplicar_modo("compacto" if self.modo == "completo" else "completo")

    def aplicar_modo(self, modo: str, guardar_config: bool = True) -> None:
        """Cambia de vista. Cada modo recuerda su propia posicion y tamano."""
        if modo == self.modo and guardar_config:
            return
        if guardar_config:
            self._guardar_geometria()
        self.modo = modo
        compacto = modo == "compacto"
        video = modo == "video"
        self.pestanas.setVisible(not compacto)
        # En modo video se ve solo la pestana Video, sin la barra de pestanas.
        self.pestanas.tabBar().setVisible(not video)
        if video:
            self.pestanas.setCurrentWidget(self.video)
        self.compacta.setVisible(compacto)
        self.estado.setVisible(not compacto and not video)
        self.pista.setVisible(not compacto and not video)
        self.boton_guia.setVisible(not video)
        self.boton_fijar.setVisible(compacto)
        self.video.boton_modo.setVisible(not video)
        self._pintar_boton_modo()
        if guardar_config:
            log.info("Vista cambiada a %s", modo)
        self.setMaximumSize(16777215, 16777215)
        # El sitio del banner se vuelve a reservar mas abajo, sobre la geometria del modo nuevo.
        self._alto_banner_compacto = 0
        if compacto:
            self.setMinimumSize(ANCHO_MINIMO_COMPACTO, ALTO_MINIMO_COMPACTO)
        elif video:
            self.setMinimumSize(ANCHO_MINIMO_VIDEO, ALTO_MINIMO_VIDEO)
        else:
            self.setMinimumSize(ANCHO_MINIMO_COMPLETO, ALTO_MINIMO_COMPLETO)
        geometria = self.config.get(self._clave_geometria())
        if geometria and len(geometria) == 4:
            self.setGeometry(*geometria)
        elif video:
            # Sin sitio guardado, arriba a la derecha de la pantalla: donde menos tapa.
            self.resize(ANCHO_VIDEO, ALTO_VIDEO)
            zona = self.screen().availableGeometry() if self.screen() else None
            if zona is not None:
                self.move(zona.right() - ANCHO_VIDEO - 20, zona.top() + 20)
        else:
            tamano = (ANCHO_COMPACTO, ALTO_COMPACTO) if compacto else (1100, 700)
            self.resize(*tamano)
            if compacto and self.isVisible():
                # Sin sitio guardado, la compacta nace en la esquina superior derecha
                # de donde estaba la ventana grande, que es donde menos tapa.
                g = self.config.get("overlay_geometria")
                if g and len(g) == 4:
                    self.move(g[0] + g[2] - ANCHO_COMPACTO, g[1])
        self._pintar_banner()
        self._asegurar_en_pantalla()
        self._aplicar_encima()
        if guardar_config:
            self.config["overlay_modo"] = modo
            guardar(self.config)
        if video:
            return
        caja = self.compacta.caja if compacto else self.buscador.caja
        caja.setFocus()
        caja.selectAll()

    # -- chincheta: siempre encima en la vista compacta -----------------------

    def _quiere_encima(self) -> bool:
        """La completa y la de video van siempre encima; la compacta, si esta fijada."""
        return self.modo != "compacto" or self.boton_fijar.isChecked()

    def fijar_encima(self, fijada: bool) -> None:
        """La chincheta de la compacta: fijada se queda encima del juego aunque se haga
        clic en el; sin fijar se comporta como una ventana normal y el juego la tapa."""
        self.config["compacta_siempre_encima"] = bool(fijada)
        guardar(self.config)
        log.info("Vista compacta %s", "fijada encima" if fijada else "sin fijar")
        self._aplicar_encima()

    def _aplicar_encima(self) -> None:
        encima = self._quiere_encima()
        self.boton_fijar.setToolTip(
            t("Fijada: se queda por encima del juego. Pulsa para soltarla.")
            if self.boton_fijar.isChecked()
            else t("Pulsa para que se quede siempre por encima del juego.")
        )
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint) != encima:
            visible = self.isVisible()
            # Cambiar las banderas de una ventana ya creada la esconde: se vuelve a ensenar.
            self.setWindowFlag(Qt.WindowStaysOnTopHint, encima)
            if visible:
                self.show()
                self.raise_()
        fijada_compacta = self.modo == "compacto" and encima and self.isVisible()
        if fijada_compacta and not self._reloj_encima.isActive():
            self._reloj_encima.start()
        elif not fijada_compacta and self._reloj_encima.isActive():
            self._reloj_encima.stop()

    def _reforzar_encima(self) -> None:
        """Vuelve a ponerla por encima sin robarle el foco al juego (solo Windows)."""
        if not (self.isVisible() and self.modo == "compacto" and self._quiere_encima()):
            self._reloj_encima.stop()
            return
        poner_encima_sin_foco(self)

    def _clave_geometria(self) -> str:
        return {
            "compacto": "overlay_geometria_compacto",
            "video": "overlay_geometria_video",
        }.get(self.modo, "overlay_geometria")

    # -- reproductor de guias ------------------------------------------------

    def abrir_video(self, url: str) -> None:
        """"Guias en YouTube" de una ficha: el video en la pestana Video (o en el modo video)."""
        if self.modo == "compacto":
            self.aplicar_modo("completo")
        if self.modo != "video":
            self.pestanas.setCurrentWidget(self.video)
        self.video.abrir(url)

    def abrir_web(self, url: str) -> None:
        """Una pagina web (las builds de Overframe) en la pestana Web, dentro de Farmadex."""
        if self.modo != "completo":
            self.aplicar_modo("completo")
        self.pestanas.setCurrentWidget(self.web)
        self.web.abrir(url)

    def _video_cerrado(self) -> None:
        """Al cerrar el video en modo video no queda nada que ver: vuelve la vista completa."""
        if self.modo == "video":
            self.aplicar_modo("completo")

    def _borrar_reproductor(self) -> None:
        log.info("Borrado de los datos del reproductor pedido desde Ajustes")
        web_borrada = self.web.borrar_datos()
        if self.video.borrar_datos() and web_borrada:
            self.estado.setText(t("Datos del reproductor borrados."))
        else:
            self.estado.setText(t("No se pudieron borrar todos los datos del reproductor."))

    def _pintar_boton_modo(self) -> None:
        if self.modo == "video":
            self.boton_modo.setText(t("Salir del video"))
            self.boton_modo.setToolTip(t("Vuelve a la vista completa; el video sigue en la pestana Video"))
            return
        compacto = self.modo == "compacto"
        self.boton_modo.setText(t("Completa") if compacto else t("Compacta"))
        self.boton_modo.setToolTip(
            t("Vista completa ({atajo})", atajo=ATAJO_MODO)
            if compacto
            else t("Vista compacta para el directo ({atajo})", atajo=ATAJO_MODO)
        )

    # -- mostrar y ocultar ---------------------------------------------------

    def alternar(self) -> None:
        self.ocultar() if self.isVisible() else self.mostrar()

    def mostrar(self) -> None:
        modo = self._refrescar_modo_pantalla()
        if modo == pantalla.MODO_EXCLUSIVO:
            libre = self._pantalla_libre()
            if libre is not None:
                # En el segundo monitor y sin robar el foco: si el juego lo pierde,
                # Windows lo minimiza y el usuario se queda sin partida en pantalla.
                if not libre.intersects(self.frameGeometry()):
                    self.move(libre.center() - QPoint(self.width() // 2, self.height() // 2))
                self.setAttribute(Qt.WA_ShowWithoutActivating, True)
                self.show()
                self.raise_()
                self.estado.setText(
                    t("Warframe esta en pantalla completa exclusiva: el overlay se abre en el otro monitor.")
                )
                if self.servicio_mundo:
                    self.servicio_mundo.cadencia(visible=True)
                return
            self.estado.setText(
                t("Warframe esta en pantalla completa exclusiva: el overlay no puede verse encima del juego.")
            )
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self._asegurar_en_pantalla()
        self.show()
        self.raise_()
        self.activateWindow()
        self._aplicar_encima()
        caja = self.compacta.caja if self.modo == "compacto" else self.buscador.caja
        caja.setFocus()
        caja.selectAll()
        if self.servicio_mundo:
            self.servicio_mundo.cadencia(visible=True)

    def ocultar(self) -> None:
        self._guardar_geometria()
        self.hide()
        self._reloj_encima.stop()
        if self.servicio_mundo:
            self.servicio_mundo.cadencia(visible=False)

    def _guardar_geometria(self) -> None:
        g = self.geometry()
        # Lo que la compacta crecio por el banner no es tamano elegido por el usuario.
        alto = g.height() - (self._alto_banner_compacto if self.modo == "compacto" else 0)
        self.config[self._clave_geometria()] = [g.x(), g.y(), g.width(), alto]
        self.config["overlay_modo"] = self.modo
        guardar(self.config)

    def aplicar_opacidad(self, opacidad: float) -> None:
        self._opacidad = opacidad
        self.marco.setStyleSheet(
            f"#marco {{ background: rgba({PALETA['fondo_rgb']}, {opacidad});"
            f" border: 1px solid {PALETA['borde']}; border-radius: 12px; }}"
        )

    def _titulos_pestanas(self) -> list[tuple[QWidget, str]]:
        return [
            (self.buscador, "Buscar"),
            (self.objetivos, "Objetivos"),
            (self.primes, "Primes"),
            (self.mundo, "Mundo"),
            (self.perfil, "Perfil"),
            (self.builds, "Build"),
            (self.agrietados, "Agrietados"),
            (self.ajustes, "Ajustes"),
            (self.video, "Video"),
            (self.web, "Web"),
        ]

    def _pintar_pista(self) -> None:
        atajo = self.config.get("hotkey_overlay", "Ctrl+Alt+W")
        self.pista.setText(t("{atajo} o Escape para cerrar", atajo=atajo) + "  ")

    def cambiar_idioma(self, codigo: str) -> None:
        """Cambio al vuelo: todo lo que esta en pantalla se vuelve a escribir."""
        idiomas.cargar(codigo)
        self._pintar_pista()
        self._pintar_boton_modo()
        self.boton_guia.setText(t("Guia"))
        self.boton_guia.setToolTip(t("Lanza la guia de uso desde el principio"))
        for i, (_, titulo) in enumerate(self._titulos_pestanas()):
            self.pestanas.setTabText(i, t(titulo))
        self.estado.setText("")
        for pestana in (self.buscador, self.objetivos, self.primes, self.mundo, self.perfil, self.ajustes, self.compacta,
                        self.video, self.web, self.builds, self.agrietados):
            pestana.retraducir()
        self._regenerar_avisos()

    def _cambiar_ritmo(self, _ritmo: str) -> None:
        """El ritmo de juego cambia todos los tiempos estimados: se recalcula lo abierto."""
        self.buscador.repintar()
        self.objetivos.refrescar()
        self.primes.repintar()

    def _cambiar_diseno_mundo(self, diseno: str) -> None:
        """Cambio al vuelo: rehace Mundo con la disposicion nueva sin perder lo que ya se sabia."""
        # La disposicion ya se cambia dentro de la propia pestana, sin rehacerla.
        if hasattr(self.mundo, "cambiar_diseno"):
            self.mundo.cambiar_diseno(diseno)
            return
        anterior = self.mundo
        nuevo = PestanaMundo(diseno=diseno)
        if anterior.indice is not None:
            nuevo.conectar_objetivos(anterior.indice, anterior.usuario)
        if anterior.mundo is not None:
            nuevo.actualizar(anterior.mundo)
        elif anterior._motivo_fallo is not None:
            nuevo.marcar_desactualizado(anterior._motivo_fallo)

        nuevo.abrir_item.connect(lambda item_id: self._abrir_desde_cursor(item_id, ""))
        self.objetivos.cambiados.disconnect(anterior.refrescar_objetivos)
        self.objetivos.cambiados.connect(nuevo.refrescar_objetivos)
        if self.servicio_mundo is not None:
            self.servicio_mundo.actualizado.disconnect(anterior.actualizar)
            self.servicio_mundo.fallo.disconnect(anterior.marcar_desactualizado)
            self.servicio_mundo.actualizado.connect(nuevo.actualizar)
            self.servicio_mundo.fallo.connect(nuevo.marcar_desactualizado)

        indice_pestana = self.pestanas.indexOf(anterior)
        activa = self.pestanas.currentWidget() is anterior
        self.pestanas.removeTab(indice_pestana)
        self.pestanas.insertTab(indice_pestana, nuevo, t("Mundo"))
        if activa:
            self.pestanas.setCurrentIndex(indice_pestana)
        self.mundo = nuevo
        anterior.deleteLater()

    def _pintar_cabecera(self) -> None:
        self.titulo.setStyleSheet(
            f"color: {PALETA['acento']}; font-weight: 700; font-size: 17px; letter-spacing: 1px;"
        )
        self.pista.setStyleSheet(f"color: {PALETA['suave']}; font-size: 12px;")
        self.boton_cerrar.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {PALETA['suave']};"
            f" font-size: 20px; font-weight: bold; padding: 0; }}"
            f" QPushButton:hover {{ color: {PALETA['texto']}; }}"
        )
        self.boton_modo.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {PALETA['borde']};"
            f" border-radius: 6px; color: {PALETA['suave']}; font-size: 12px; padding: 0 8px; }}"
            f" QPushButton:hover {{ color: {PALETA['texto']}; border-color: {PALETA['acento']}; }}"
        )
        self.boton_guia.setStyleSheet(self.boton_modo.styleSheet())
        # Fijada se ve encendida (color de acento), suelta como los otros botones.
        self.boton_fijar.setStyleSheet(
            self.boton_modo.styleSheet()
            + f" QPushButton:checked {{ color: {PALETA['acento']}; border-color: {PALETA['acento']};"
            f" font-weight: 700; }}"
        )

    def cambiar_tema(self, nombre: str) -> None:
        """Se puede cambiar en caliente: la hoja de estilos y lo que lleva color en el HTML."""
        elegir_tema(nombre)
        self.setStyleSheet(hoja_estilos())
        self.aplicar_opacidad(getattr(self, "_opacidad", 0.94))
        self._pintar_cabecera()
        self.estado.setStyleSheet(f"color: {PALETA['suave']};")
        self.banner.setStyleSheet(
            f"color: {PALETA['aviso']}; border: 1px solid {PALETA['aviso']};"
            " border-radius: 6px; padding: 4px 8px;"
        )
        self.buscador.repintar()
        self.objetivos.refrescar()
        self.primes.repintar()
        self.perfil.repintar()
        self.compacta.repintar()
        self.ajustes.repintar()
        self.video.repintar()
        self.web.repintar()
        self.builds.repintar()
        self.agrietados.repintar()
        # Mundo genera su HTML con la paleta dentro; retraducir lo vuelve a pintar entero.
        self.mundo.retraducir()
        self._regenerar_avisos()

    # -- arrastre de la ventana ----------------------------------------------

    def mousePressEvent(self, evento):  # noqa: N802 - firma de Qt
        """Arrastrar la ventana desde cualquier zona vacia, no solo desde la cabecera.

        Aqui solo llegan los clics que ningun widget de dentro ha querido (botones,
        listas, cajas de texto y enlaces se quedan los suyos). Se le pide a Windows que
        mueva la ventana el mismo (`startSystemMove`), como con una barra de titulo de
        verdad; donde no se puede (pruebas sin pantalla), se mueve a mano.
        """
        if evento.button() != Qt.LeftButton:
            return
        ventana = self.windowHandle()
        if ventana is not None and ventana.startSystemMove():
            evento.accept()
            return
        self._arrastre = evento.globalPosition().toPoint() - self.frameGeometry().topLeft()
        evento.accept()

    def mouseMoveEvent(self, evento):  # noqa: N802
        if self._arrastre and evento.buttons() & Qt.LeftButton:
            self.move(evento.globalPosition().toPoint() - self._arrastre)
            evento.accept()

    def mouseReleaseEvent(self, evento):  # noqa: N802
        self._arrastre = None

    # -- redimensionado por los bordes ---------------------------------------

    def eventFilter(self, objeto, evento):  # noqa: N802 - firma de Qt
        """El marco cubre toda la ventana: los eventos de raton en el borde llegan a el,
        no a self. Se interceptan aqui antes de que el marco los ignore y burbujeen hacia
        el arrastre de la cabecera, que sigue viviendo en mousePressEvent/mouseMoveEvent."""
        if objeto is self.marco:
            tipo = evento.type()
            if tipo == QEvent.MouseMove:
                if self._redimensionar_mover(evento):
                    return True
            elif tipo == QEvent.MouseButtonPress:
                if self._redimensionar_iniciar(evento):
                    return True
            elif tipo == QEvent.MouseButtonRelease:
                if self._redimensionar_soltar():
                    return True
            elif tipo == QEvent.Leave and self._borde_activo is None:
                self.unsetCursor()
        return super().eventFilter(objeto, evento)

    def _borde_bajo_cursor(self, evento) -> str | None:
        pos = evento.position().toPoint()
        return borde_en_posicion(pos.x(), pos.y(), self.width(), self.height())

    def _redimensionar_iniciar(self, evento) -> bool:
        if evento.button() != Qt.LeftButton:
            return False
        borde = self._borde_bajo_cursor(evento)
        if borde is None:
            return False
        # Redimensionado nativo de Windows (fluido, respeta el minimo); si la plataforma
        # no lo ofrece, se hace a mano con `geometria_redimensionada`.
        ventana = self.windowHandle()
        if ventana is not None and ventana.startSystemResize(BORDES_QT[borde]):
            return True
        self._borde_activo = borde
        self._geom_inicio_resize = self.geometry()
        self._pos_inicio_resize = evento.globalPosition().toPoint()
        return True

    def _redimensionar_mover(self, evento) -> bool:
        if self._borde_activo:
            if not (evento.buttons() & Qt.LeftButton):
                # El boton se solto fuera de la ventana y no llego el release: no se queda
                # arrastrando para siempre.
                self._redimensionar_soltar()
                return False
            delta = evento.globalPosition().toPoint() - self._pos_inicio_resize
            nueva = geometria_redimensionada(
                self._borde_activo, self._geom_inicio_resize, delta, self.minimumSize()
            )
            self.setGeometry(nueva)
            return True
        if evento.buttons() == Qt.NoButton:
            borde = self._borde_bajo_cursor(evento)
            if borde:
                self.setCursor(QCursor(CURSOR_POR_BORDE[borde]))
            else:
                self.unsetCursor()
        return False

    def _redimensionar_soltar(self) -> bool:
        if self._borde_activo is None:
            return False
        self._borde_activo = None
        self._geom_inicio_resize = None
        self._pos_inicio_resize = None
        self.unsetCursor()
        return True

    def closeEvent(self, evento):  # noqa: N802
        # La X del sistema solo esconde: se sale desde la bandeja.
        evento.ignore()
        self.ocultar()

    def cerrar_de_verdad(self) -> None:
        log.info("Cerrando la ventana y los hilos de trabajo")
        self._reloj_encima.stop()
        self._guardar_geometria()
        # El reproductor de guias que lanzo esta ventana (solo ese proceso, por su PID).
        self.video.cerrar()
        self.web.cerrar()
        self.etiquetas.hide()
        if getattr(self, "comprobador_datos", None):
            self.comprobador_datos.parar()
            self.comprobador_app.cerrar()
            if self.descargador is not None:
                self.descargador.cancelar()
            # La actualizacion descargada se instala al salir: el setup espera a que
            # este proceso termine y vuelve a abrir Farmadex al acabar.
            self._lanzar_instalacion_pendiente()
        if self.vigilante:
            self.vigilante.parar()
        if self.hilo_captura:
            self.hilo_captura.quit()
            self.hilo_captura.wait(3000)
        if self.hilo_comparador:
            self.servicio_comparador.cerrar()
            self.hilo_comparador.quit()
            self.hilo_comparador.wait(3000)
        if self.servicio_mundo:
            self.servicio_mundo.cerrar()
            self.hilo_mundo.quit()
            self.hilo_mundo.wait(3000)
            self.servicio_market.cerrar()
            self.hilo_market.quit()
            self.hilo_market.wait(3000)
        if self.tarea and self.tarea.isRunning():
            self.tarea.requestInterruption()
            self.tarea.wait(3000)
        # La conexion con warframe.market la comparten el buscador, el comparador y el
        # indice: se cierra la ultima, cuando ya no queda nadie que la use.
        from ..online import market

        market.cerrar_compartido()
        super().close()


def poner_encima_sin_foco(widget: QWidget) -> bool:
    """SetWindowPos(HWND_TOPMOST) sin activar: la sube por encima de las demas ventanas
    "siempre encima" (el juego incluido) sin quitarle el foco a nadie."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        HWND_TOPMOST = -1
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
        user32 = ctypes.WinDLL("user32")
        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint
        ]
        return bool(user32.SetWindowPos(
            ctypes.c_void_p(int(widget.winId())), ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
        ))
    except (AttributeError, OSError, ValueError):
        return False


def _texto_plano(html_aviso: str) -> str:
    """El aviso sin etiquetas HTML, para la linea unica de la compacta y su tooltip."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html_aviso)).split())


def _a_logicas(recompensas: list) -> list:
    """Pasa las cajas de pixeles fisicos (captura) a logicos (Qt) segun la escala de Windows."""
    escala = pantalla.escala_fisica_logica()
    if abs(escala - 1.0) < 0.01:
        return recompensas
    for r in recompensas:
        r.caja = tuple(round(v / escala) for v in r.caja)
    return recompensas


def icono_bandeja() -> QPixmap:
    """Icono sencillo dibujado a mano para no depender de un fichero."""
    mapa = QPixmap(64, 64)
    mapa.fill(QColor(0, 0, 0, 0))
    pintor = QPainter(mapa)
    pintor.setRenderHint(QPainter.Antialiasing)
    pintor.setBrush(QColor(18, 22, 28))
    pintor.setPen(QColor(74, 163, 255))
    pintor.drawRoundedRect(4, 4, 56, 56, 12, 12)
    pintor.setPen(QColor(74, 163, 255))
    fuente = pintor.font()
    fuente.setPointSize(30)
    fuente.setBold(True)
    pintor.setFont(fuente)
    pintor.drawText(mapa.rect(), Qt.AlignCenter, "F")
    pintor.end()
    return mapa
