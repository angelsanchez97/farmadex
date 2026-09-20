"""La ventana del overlay: sin marco, translucida y siempre encima del juego."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QKeySequence, QPainter, QPixmap, QShortcut
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
from ..config import cargar, guardar
from ..datos import indice
from ..idiomas import t
from ..registro.eelog import VigilanteEELog
from ..registro_log import obtener
from ..tareas import TareaDatos
from ..actualizador.app import ComprobadorApp
from ..actualizador.datos import ComprobadorDatos
from ..actualizador.local import ComprobadorLocal, instalar
from ..captura import pantalla
from ..captura.comparador import ServicioComparador
from ..captura.cursor import LectorCursor
from ..captura.reliquias import DisparadorAutomatico, LectorRecompensas, completar, resumir
from ..online.servicio_market import ServicioMarket
from ..online.worldstate import ServicioMundo
from .pestana_ajustes import PestanaAjustes
from .pestana_buscador import PestanaBuscador
from .pestana_mundo import DISENO_POR_DEFECTO, PestanaMundo
from .etiquetas import EtiquetasRecompensas
from .pestana_objetivos import PestanaObjetivos
from .pestana_perfil import PestanaPerfil
from .vista_compacta import (
    ALTO as ALTO_COMPACTO,
    ALTO_MINIMO as ALTO_MINIMO_COMPACTO,
    ANCHO as ANCHO_COMPACTO,
    ANCHO_MINIMO as ANCHO_MINIMO_COMPACTO,
    VistaCompacta,
)
from .maestria import estado_con_padre, texto_maestria
from .widgets import PALETA, BarraProgreso, elegir_tema, hoja_estilos

log = obtener("overlay")

# Atajo, dentro de la ventana, para pasar de la vista completa a la compacta y volver.
ATAJO_MODO = "Ctrl+M"

# Franja en los bordes/esquinas donde el cursor pasa a redimensionar en vez de a arrastrar
# o a hacer clic normal. Cabe dentro de los margenes del marco (10, 6, 10, 8) para no pisar
# ningun widget de dentro.
MARGEN_REDIMENSION = 6

# Minimo de la vista completa: cuatro pestanas y la barra de busqueda siguen legibles,
# comprobado con una captura (herramientas/capturas/overlay_minimo_completo.png).
ANCHO_MINIMO_COMPLETO = 760
ALTO_MINIMO_COMPLETO = 420

_OESTE = {"o", "no", "so"}
_ESTE = {"e", "ne", "se"}
_NORTE = {"n", "no", "ne"}
_SUR = {"s", "so", "se"}

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

    cerrar_programa = Signal()

    def __init__(self):
        super().__init__()
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
        # "completo" (pestanas) o "compacto" (solo busqueda y resultado esencial).
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
        self._pintar_cabecera()

        cabecera = QHBoxLayout()
        cabecera.setContentsMargins(4, 4, 4, 0)
        cabecera.addWidget(self.titulo)
        cabecera.addStretch(1)
        cabecera.addWidget(self.pista)
        cabecera.addWidget(self.boton_modo)
        cabecera.addWidget(boton_cerrar)

        self.pestanas = QTabWidget()
        self.buscador = PestanaBuscador()
        self.mundo = PestanaMundo(diseno=self.config.get("diseno_mundo", DISENO_POR_DEFECTO))
        self.objetivos = PestanaObjetivos()
        self.ajustes = PestanaAjustes()
        # El perfil comparte la BD del usuario con los objetivos (misma conexion, mismo hilo).
        self.perfil = PestanaPerfil(self.objetivos.usuario)
        self.buscador.conectar_usuario(self.objetivos.usuario)
        self.perfil.perfil_cambiado.connect(self.buscador.refrescar_perfil)
        self.perfil.abrir_item.connect(lambda item_id: self._abrir_desde_cursor(item_id, ""))
        self.mundo.abrir_item.connect(lambda item_id: self._abrir_desde_cursor(item_id, ""))
        self.objetivos.cambiados.connect(self.mundo.refrescar_objetivos)
        self.ajustes.reconstruir.connect(lambda: self.preparar_datos(forzar=True))
        self.ajustes.tema_cambiado.connect(self.cambiar_tema)
        self.ajustes.idioma_cambiado.connect(self.cambiar_idioma)
        self.ajustes.diseno_mundo_cambiado.connect(self._cambiar_diseno_mundo)
        self.ajustes.salir.connect(self.cerrar_programa.emit)
        self.ajustes.instalar_version.connect(self._instalar_version)
        for pestana, titulo in self._titulos_pestanas():
            self.pestanas.addTab(pestana, t(titulo))
        self.compacta = VistaCompacta(self.buscador)
        self.compacta.abrir_completo.connect(self._abrir_completo)
        self.servicio_mundo: ServicioMundo | None = None
        self.hilo_captura: QThread | None = None
        self.hilo_comparador: QThread | None = None
        self.etiquetas = EtiquetasRecompensas()
        self.vigilante: VigilanteEELog | None = None
        self._version_encontrada = None
        # Lo que se sabe del juego: cabecera de EE.log (build, modo) y modo de pantalla.
        self.cabecera_juego = None
        self.modo_pantalla = pantalla.MODO_DESCONOCIDO

        # Aviso grande bajo la cabecera: parche sin datos, pantalla completa exclusiva...
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.RichText)
        self.banner.setStyleSheet(
            f"color: {PALETA['aviso']}; border: 1px solid {PALETA['aviso']};"
            " border-radius: 6px; padding: 4px 8px;"
        )
        self.banner.hide()
        self._avisos: dict[str, str] = {}

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
        listo = indice.hay_indice() and not forzar
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
            self.buscador.habilitar(True)
            self.estado.setText(mensaje)
            log.info("Datos listos: %s", mensaje)
            self.objetivos.conectar_indice(indice.conectar())
            self.perfil.conectar_indice(indice.conectar())
            self.mundo.conectar_objetivos(indice.conectar(), self.objetivos.usuario)
            self._arrancar_mundo()
            self._arrancar_captura()
            self._arrancar_comparador()
            self._arrancar_actualizador()
            self._comprobar_desfase()
        elif indice.hay_indice():
            self.buscador.habilitar(True)
            self.estado.setText(t("Datos sin actualizar: {mensaje}", mensaje=mensaje))
        else:
            self.estado.setText(t("Error preparando los datos"))
            QMessageBox.critical(self, f"{NOMBRE_APP}", mensaje)

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
        self.buscador.pedir_precios.connect(self.servicio_market.pedir)
        self.servicio_market.listo.connect(self.buscador.mostrar_precios)
        self.compacta.pedir_precios.connect(self.servicio_market.pedir)
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
        for lector in (self.lector_recompensas, self.lector_cursor):
            lector.moveToThread(self.hilo_captura)
            lector.estado.connect(self.estado.setText)
        self.hilo_captura.started.connect(self.lector_recompensas.iniciar)
        self.hilo_captura.started.connect(self.lector_cursor.iniciar)
        self.lector_recompensas.leidas.connect(self._pintar_recompensas)
        self.lector_cursor.encontrado.connect(self._abrir_desde_cursor)
        self.hilo_captura.start()

        self.disparador = DisparadorAutomatico(bool(self.config.get("ocr_reliquias_auto", True)))
        self.disparador.disparar.connect(self.leer_recompensas)
        self.ajustes.ocr_auto.toggled.connect(
            lambda activo: setattr(self.disparador, "activo", activo)
        )

        self.vigilante = VigilanteEELog(self.config.get("ruta_eelog", ""))
        self.vigilante.evento.connect(self._evento_juego)
        self.vigilante.arranque.connect(self._arranque_juego)
        self.vigilante.start()

    def _arrancar_comparador(self) -> None:
        """Puntua las recompensas en su propio hilo: los precios tardan ~300 ms por pieza
        y no pueden retrasar ni el OCR ni la ventana. Las etiquetas ya se ven sin esto;
        cuando llegue el veredicto, solo se les añade la marca de cual conviene."""
        if self.hilo_comparador is not None:
            return
        self.hilo_comparador = QThread(self)
        self.servicio_comparador = ServicioComparador(escuadra=True)
        self.servicio_comparador.moveToThread(self.hilo_comparador)
        self.lector_recompensas.leidas.connect(self.servicio_comparador.comparar)
        self.servicio_comparador.veredicto.connect(self._veredicto_recompensas)
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
        fecha_build = getattr(self.cabecera_juego, "fecha_build", None)
        atrasadas = indice.desfase_con_el_juego(indice.leer_meta(), fecha_build)
        if not atrasadas:
            self._aviso("parche", None)
            self.ajustes.avisar_parche(None)
            return
        build = getattr(self.cabecera_juego, "build", "") or "?"
        detalle = ", ".join(t("{fuente} del {fecha}", fuente=t(fuente), fecha=fecha) for fuente, fecha in atrasadas)
        texto = t(
            "Warframe se ha actualizado (build {build}) y los datos van por detras: {detalle}. "
            "Puede faltar lo nuevo del parche; se volveran a descargar cuando WFCD y DE los publiquen.",
            build=build,
            detalle=detalle,
        )
        # En Ajustes queda siempre; el banner solo los dias siguientes al parche, que es
        # cuando de verdad falta contenido. Meses despues, si DE no ha tocado las tablas,
        # es que ese parche no cambio los drops.
        if indice.parche_reciente(fecha_build):
            log.warning("Datos anteriores al parche del juego: build %s, %s", build, atrasadas)
            self._aviso("parche", texto)
        else:
            self._aviso("parche", None)
        self.ajustes.avisar_parche(texto)

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
        if self._avisos:
            self.banner.setText("<br>".join(self._avisos.values()))
            self.banner.show()
        else:
            self.banner.hide()

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
        if self.config.get("comprobar_actualizaciones_app", True):
            QTimer.singleShot(5000, self.comprobador_app.comprobar)

    def _hay_datos_nuevos(self, motivo: str) -> None:
        self.estado.setText(t("Actualizando datos ({motivo})...", motivo=motivo))
        self.preparar_datos(forzar=True)

    def _hay_version_nueva(self, version) -> None:
        self.nueva_version = version
        self.estado.setText(
            t("Hay una version nueva ({version}). Descargala desde Ajustes.", version=version.etiqueta)
        )
        self.ajustes.anunciar_version(version)

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
        self.ajustes.estado_version(t("Hay una version nueva: {version}", version=version.etiqueta))
        self.estado.setText(
            t("Hay compilada una version nueva ({version}): instalala desde Ajustes.",
              version=version.etiqueta)
        )
        self.ajustes.anunciar_version(version, local=True)

    def _instalar_version(self, version) -> None:
        if instalar(version):
            self.estado.setText(t("Instalando... Farmadex se va a cerrar."))
            QTimer.singleShot(500, self.cerrar_programa.emit)
        else:
            self.estado.setText(t("No se pudo lanzar el instalador; mira la carpeta que se ha abierto"))

    def _evento_juego(self, nombre: str) -> None:
        self.disparador.evento(nombre)
        if nombre == "reliquia_cerrada":
            self.etiquetas.hide()

    def leer_recompensas(self) -> None:
        """Lee la pantalla de recompensas de reliquia (atajo o aviso de EE.log)."""
        if self.hilo_captura is None:
            self.estado.setText(t("Los datos todavia se estan preparando"))
            return
        self.etiquetas.hide()
        QTimer.singleShot(0, self.lector_recompensas.leer_ahora)

    def leer_cursor(self) -> None:
        if self.hilo_captura is None:
            return
        QTimer.singleShot(0, self.lector_cursor.leer_ahora)

    def _pintar_recompensas(self, recompensas: list) -> None:
        if not recompensas:
            return
        con = indice.conectar()
        try:
            completar(recompensas, con, self.objetivos.usuario)
            maestria = self._maestria_recompensas(recompensas, con)
        finally:
            con.close()
        # El resumen en texto vale en cualquier modo de pantalla (y queda en el log).
        resumen = resumir(recompensas)
        log.info("Recompensas: %s", resumen)
        if self._refrescar_modo_pantalla() == pantalla.MODO_EXCLUSIVO:
            self.estado.setText(t("Recompensas (no se pueden pintar encima del juego): {resumen}", resumen=resumen))
            return
        self.estado.setText(resumen)
        self.etiquetas.mostrar(_a_logicas(recompensas), maestria)

    def _veredicto_recompensas(self, recompensas: list, veredicto) -> None:
        """Llega despues, con los precios: solo añade la marca de "mejor" a lo que ya se ve."""
        if self.modo_pantalla == pantalla.MODO_EXCLUSIVO:
            return
        self.etiquetas.marcar_veredicto(recompensas, veredicto)
        if veredicto.puntuaciones:
            self.estado.setText(veredicto.resumen())

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

    def _abrir_completo(self, item_id: int) -> None:
        """Enter en la vista compacta: la ficha entera de ese objeto."""
        self.aplicar_modo("completo")
        self.pestanas.setCurrentWidget(self.buscador)
        self.buscador.abrir(item_id)

    # -- modo completo y compacto ---------------------------------------------

    def alternar_modo(self) -> None:
        self.aplicar_modo("compacto" if self.modo == "completo" else "completo")

    def aplicar_modo(self, modo: str, guardar_config: bool = True) -> None:
        """Cambia de vista. Cada modo recuerda su propia posicion y tamano."""
        if modo == self.modo and guardar_config:
            return
        if guardar_config:
            self._guardar_geometria()
        self.modo = modo
        compacto = modo == "compacto"
        self.pestanas.setVisible(not compacto)
        self.compacta.setVisible(compacto)
        self.estado.setVisible(not compacto)
        self.pista.setVisible(not compacto)
        self._pintar_boton_modo()
        self.setMaximumSize(16777215, 16777215)
        if compacto:
            self.setMinimumSize(ANCHO_MINIMO_COMPACTO, ALTO_MINIMO_COMPACTO)
        else:
            self.setMinimumSize(ANCHO_MINIMO_COMPLETO, ALTO_MINIMO_COMPLETO)
        geometria = self.config.get(self._clave_geometria())
        if geometria and len(geometria) == 4:
            self.setGeometry(*geometria)
        else:
            tamano = (ANCHO_COMPACTO, ALTO_COMPACTO) if compacto else (1100, 700)
            self.resize(*tamano)
            if compacto and self.isVisible():
                # Sin sitio guardado, la compacta nace en la esquina superior derecha
                # de donde estaba la ventana grande, que es donde menos tapa.
                g = self.config.get("overlay_geometria")
                if g and len(g) == 4:
                    self.move(g[0] + g[2] - ANCHO_COMPACTO, g[1])
        self._asegurar_en_pantalla()
        if guardar_config:
            self.config["overlay_modo"] = modo
            guardar(self.config)
        caja = self.compacta.caja if compacto else self.buscador.caja
        caja.setFocus()
        caja.selectAll()

    def _clave_geometria(self) -> str:
        return "overlay_geometria_compacto" if self.modo == "compacto" else "overlay_geometria"

    def _pintar_boton_modo(self) -> None:
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
        caja = self.compacta.caja if self.modo == "compacto" else self.buscador.caja
        caja.setFocus()
        caja.selectAll()
        if self.servicio_mundo:
            self.servicio_mundo.cadencia(visible=True)

    def ocultar(self) -> None:
        self._guardar_geometria()
        self.hide()
        if self.servicio_mundo:
            self.servicio_mundo.cadencia(visible=False)

    def _guardar_geometria(self) -> None:
        g = self.geometry()
        self.config[self._clave_geometria()] = [g.x(), g.y(), g.width(), g.height()]
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
            (self.mundo, "Mundo"),
            (self.perfil, "Perfil"),
            (self.ajustes, "Ajustes"),
        ]

    def _pintar_pista(self) -> None:
        atajo = self.config.get("hotkey_overlay", "Ctrl+Alt+W")
        self.pista.setText(t("{atajo} o Escape para cerrar", atajo=atajo) + "  ")

    def cambiar_idioma(self, codigo: str) -> None:
        """Cambio al vuelo: todo lo que esta en pantalla se vuelve a escribir."""
        idiomas.cargar(codigo)
        self._pintar_pista()
        self._pintar_boton_modo()
        for i, (_, titulo) in enumerate(self._titulos_pestanas()):
            self.pestanas.setTabText(i, t(titulo))
        self.estado.setText("")
        for pestana in (self.buscador, self.objetivos, self.mundo, self.perfil, self.ajustes, self.compacta):
            pestana.retraducir()

    def _cambiar_diseno_mundo(self, diseno: str) -> None:
        """Cambio al vuelo: rehace Mundo con la disposicion nueva sin perder lo que ya se sabia."""
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

    def cambiar_tema(self, nombre: str) -> None:
        """Se puede cambiar en caliente: la hoja de estilos y lo que lleva color en el HTML."""
        elegir_tema(nombre)
        self.setStyleSheet(hoja_estilos())
        self.aplicar_opacidad(getattr(self, "_opacidad", 0.94))
        self._pintar_cabecera()
        self.estado.setStyleSheet(f"color: {PALETA['suave']};")
        self.buscador.repintar()
        self.objetivos.refrescar()
        self.perfil.repintar()
        self.compacta.repintar()

    # -- arrastre de la ventana ----------------------------------------------

    def mousePressEvent(self, evento):  # noqa: N802 - firma de Qt
        if evento.button() == Qt.LeftButton and evento.position().y() < 34:
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
        self._guardar_geometria()
        self.etiquetas.hide()
        if getattr(self, "comprobador_datos", None):
            self.comprobador_datos.parar()
            self.comprobador_app.cerrar()
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
        super().close()


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
