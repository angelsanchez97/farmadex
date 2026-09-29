"""Pestana Agrietados: evalua un riven (grado de cada estadistica) y da un precio de referencia.

La via principal es a mano: eliges el arma, apuntas las estadisticas con su
signo y pulsas Evaluar. El lector de pantalla (boton o atajo, con el raton sobre
la tarjeta) solo rellena el formulario; si algo no lo leyo seguro, lo dice y te
deja corregirlo antes de evaluar.

Los grados siguen la guia de agrietados (S..F segun donde cayo el azar dentro
del margen posible para esa arma), y el precio sale de las subastas abiertas de
warframe.market con estadisticas parecidas y de la media semanal que publica DE.

Estilo C (maqueta C_herramientas.png): a la izquierda el panel "El agrietado" con el
formulario; a la derecha "Que tal ha salido" (tabla con la barra de donde cayo cada
valor y la escala de grados), "Veredicto" con "Consultar precio" y el precio de los
parecidos. El boton de leer la tarjeta va a la derecha de las sub-pestanas
(`controles_cabecera`, lo coloca `SeccionConSub`).
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..agrietados import grados, mercado
from ..agrietados.lector import TarjetaLeida
from ..config import cargar
from ..idiomas import t
from ..registro_log import obtener
from .estilo_c import (
    TITULAR,
    BarraFina,
    BotonC,
    CasillaRombo,
    EtiquetaC,
    Linea,
    PanelC,
    RombosDisposicion,
    Tecla,
    columna,
    fila,
    px,
    transparente,
)
from .widgets import PALETA

log = obtener("ui.agrietados")

FILAS_STATS = 4
# Tienda (Segoe Fluent/MDL2): el boton de consultar precio.
GLIFO_TIENDA = ""
# Columnas de la tabla de resultados. La barra va la ultima por dentro (asi el grado
# sigue en la columna 3 para quien la lea) pero se ensena antes del grado.
COL_NOMBRE, COL_VALOR, COL_RANGO, COL_GRADO, COL_BARRA = range(5)
# Titular del veredicto segun la posicion media (0 peor .. 1 mejor) de lo evaluado.
TITULARES = (
    (0.7, "Tirada muy buena: las estadísticas han salido altas."),
    (0.5, "Buena tirada: por encima de lo normal."),
    (0.3, "Tirada normal: ni buena ni mala."),
    (0.0, "Tirada floja: las estadísticas han salido bajas."),
)


def rombos_disposicion(disposicion: float) -> int:
    """Los rombos que ensena el juego: 5 de 1.31 a 1.55, 1 de 0.5 a 0.69."""
    if disposicion >= 1.31:
        return 5
    if disposicion >= 1.11:
        return 4
    if disposicion >= 0.9:
        return 3
    if disposicion >= 0.7:
        return 2
    return 1


def puntos_disposicion(disposicion: float) -> str:
    """Los mismos rombos en texto (para tooltips y registros)."""
    n = rombos_disposicion(disposicion)
    return "●" * n + "○" * (5 - n)


def titular_de(evaluaciones: list) -> str:
    """Una frase de resumen a partir de donde cayo cada estadistica (sin las de fuera)."""
    posiciones = [ev.posicion for ev in evaluaciones if ev.grado and ev.posicion is not None]
    if not posiciones:
        return ""
    media = sum(posiciones) / len(posiciones)
    return next(t(texto) for desde, texto in TITULARES if media >= desde)


def _parar_hilo(hilo) -> None:
    """Para el hilo de red y espera a que acabe (sin fallar si Qt ya lo ha borrado)."""
    try:
        if hilo.isRunning():
            hilo.quit()
            hilo.wait(2000)
    except RuntimeError:  # objeto de Qt ya destruido
        pass


class _Trabajador(QObject):
    """Red en su hilo: lista de armas (con disposicion), subastas y medias de DE."""

    armas = Signal(list)
    precio = Signal(str, object, object, object)  # slug, ResumenSubastas, MediaDE sin variar, MediaDE variado
    horquilla = Signal(str, object)  # clave de la peticion, mercado.Horquilla
    fallo = Signal(str)

    @Slot()
    def cargar_armas(self) -> None:
        try:
            self.armas.emit(mercado.compartido().armas())
        except Exception as e:  # noqa: BLE001 - sin red no hay lista; se avisa
            log.warning("No se pudo cargar la lista de armas con agrietado: %s", e)
            self.fallo.emit(str(e))

    @Slot(str, str, list, list)
    def consultar(self, slug: str, nombre_en: str, positivos: list, negativos: list) -> None:
        try:
            m = mercado.compartido()
            resumen = m.subastas(slug, list(positivos), list(negativos))
            medias = m.medias_de()
            clave = nombre_en.lower()
            self.precio.emit(slug, resumen, medias.get((clave, False)), medias.get((clave, True)))
        except Exception as e:  # noqa: BLE001
            log.warning("Fallo consultando el precio de %s: %s", slug, e)
            self.fallo.emit(str(e))


    @Slot(str, str, list, str)
    def pedir_horquilla(self, clave: str, slug: str, positivos: list, negativo: str) -> None:
        try:
            h = mercado.compartido().horquilla(slug, list(positivos), negativo or None)
        except Exception as e:  # noqa: BLE001 - el hilo de red no se cae por esto
            log.warning("Fallo pidiendo la horquilla de %s: %s", slug, e)
            h = mercado.Horquilla(arma=slug, error=str(e))
        self.horquilla.emit(clave, h)


def clave_horquilla(slug: str, positivos: list[str], negativo: str) -> str:
    """Identifica una peticion de horquilla: si llega la de otro agrietado, se ignora."""
    return f"{slug}|{','.join(sorted(positivos))}|{negativo}"


def texto_horquilla(h) -> str:
    """La horquilla de precio en una frase (HTML sencillo). Nunca pone un precio que no haya."""
    if h is None:
        return ""
    if h.error:
        return t("Precio de parecidos: warframe.market no responde ahora ({error}).", error=h.error)
    if h.suficiente:
        if h.nivel == "positivas":
            base = t("Precio de parecidos: piden entre <b>{bajo}p</b> y <b>{alto}p</b> (mediana {mediana}p), "
                     "según {n} subastas abiertas con las mismas positivas (la negativa cambia).",
                     bajo=h.bajo, alto=h.alto, mediana=h.mediana, n=h.n)
        else:
            base = t("Precio de parecidos: piden entre <b>{bajo}p</b> y <b>{alto}p</b> (mediana {mediana}p), "
                     "según {n} subastas abiertas con las mismas estadísticas.",
                     bajo=h.bajo, alto=h.alto, mediana=h.mediana, n=h.n)
        return base + " " + t("Es lo que piden, no lo que se acaba pagando.")
    if h.n:
        return t("Precio de parecidos: sin datos suficientes (solo {n} subastas parecidas abiertas; "
                 "hacen falta {umbral}). La más barata pide {minimo}p.",
                 n=h.n, umbral=mercado.UMBRAL_HORQUILLA, minimo=h.minimo)
    return t("Precio de parecidos: sin datos suficientes (no hay subastas parecidas abiertas).")


def _rotulo(clave: str = "") -> EtiquetaC:
    """Rotulo pequeno en mayusculas y apagado (ARMA, ESTADISTICA...)."""
    return EtiquetaC(t(clave) if clave else "", "rotulo", tinta="suave", mayus=True)


class PestanaAgrietados(QWidget):
    pedir_lectura = Signal()
    _pedir_armas = Signal()
    _pedir_precio = Signal(str, str, list, list)
    _pedir_horquilla = Signal(str, str, list, str)

    def __init__(self, parent=None, con_red: bool = True):
        super().__init__(parent)
        transparente(self)
        self.config = cargar()
        self.armas: list[mercado.Arma] = []
        self.nombres_es: dict[str, str] = {}
        self.tarjeta: TarjetaLeida | None = None
        self.evaluaciones: list[grados.Evaluacion] = []
        self._precio_pedido: str | None = None
        self._horquilla_pedida: str | None = None

        # -- lectura de pantalla (a la derecha de las sub-pestanas) --------------------
        self.boton_leer = BotonC(principal=True, icono="buscar", tam=11)
        self.boton_leer.clicked.connect(self.pedir_lectura.emit)
        self.tecla_atajo = Tecla("")
        self.controles_cabecera = transparente(QWidget())
        self.controles_cabecera.setLayout(fila(self.boton_leer, self.tecla_atajo, espacio=px(8, False)))

        # -- panel "El agrietado": el formulario ---------------------------------------
        self.panel_form = PanelC(t("El agrietado"))
        self.nombre = EtiquetaC("", "fuerte", tinta="secundario", recortar=True)
        self.panel_form.cabecera.addWidget(self.nombre)
        self.estado = EtiquetaC("", "pequeno", envolver=True)
        self.estado.hide()

        self.arma = QComboBox()
        self.arma.setEditable(True)
        self.arma.setInsertPolicy(QComboBox.NoInsert)
        self.arma.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.arma.currentIndexChanged.connect(self._arma_cambiada)
        self.etiqueta_arma = _rotulo()
        self.etiqueta_disposicion = _rotulo()
        self.rombos = RombosDisposicion(0)
        self.disposicion = EtiquetaC("", "dato", tinta="acento")

        self.filas: list[tuple[QComboBox, QDoubleSpinBox, CasillaRombo]] = []
        rejilla = QGridLayout()
        rejilla.setContentsMargins(0, 0, 0, 0)
        rejilla.setHorizontalSpacing(px(8, False))
        rejilla.setVerticalSpacing(px(6, False))
        self.etiqueta_stat = _rotulo()
        self.etiqueta_valor = _rotulo()
        self.etiqueta_negativo = _rotulo()
        rejilla.addWidget(self.etiqueta_stat, 0, 0)
        rejilla.addWidget(self.etiqueta_valor, 0, 1)
        rejilla.addWidget(self.etiqueta_negativo, 0, 2, Qt.AlignCenter)
        for i in range(FILAS_STATS):
            atributo = QComboBox()
            atributo.addItem("—", "")
            for a in grados.ATRIBUTOS:
                atributo.addItem(f"{a.nombre_es} ({a.nombre_en})", a.slug)
            atributo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            atributo.setMinimumWidth(px(120, False))
            valor = QDoubleSpinBox()
            valor.setDecimals(1)
            valor.setRange(0.0, 999.0)
            valor.setSingleStep(0.1)
            valor.setFixedWidth(px(96, False))
            negativo = CasillaRombo()
            rejilla.addWidget(atributo, i + 1, 0)
            rejilla.addWidget(valor, i + 1, 1)
            rejilla.addWidget(negativo, i + 1, 2, Qt.AlignCenter)
            self.filas.append((atributo, valor, negativo))
        rejilla.setColumnStretch(0, 1)

        self.maestria = QSpinBox()
        self.maestria.setRange(0, 30)
        self.maestria.setSpecialValueText("?")
        self.variado = QSpinBox()
        self.variado.setRange(0, 999)
        self.etiqueta_maestria = _rotulo()
        self.etiqueta_variado = _rotulo()
        self.boton_evaluar = BotonC(principal=True, tam=11)
        self.boton_evaluar.clicked.connect(self.evaluar)
        self.boton_limpiar = BotonC(tam=11)
        self.boton_limpiar.clicked.connect(self.limpiar)

        form = self.panel_form.capa
        form.addWidget(self.estado)
        form.addLayout(fila(self.etiqueta_arma, self.arma, espacio=px(10, False)))
        form.addLayout(fila(self.etiqueta_disposicion, self.rombos, self.disposicion, None, espacio=px(10, False)))
        form.addWidget(Linea())
        form.addLayout(rejilla)
        form.addLayout(fila(self.etiqueta_maestria, self.maestria, px(12, False), self.etiqueta_variado,
                            self.variado, None, espacio=px(8, False)))
        form.addLayout(fila(None, self.boton_limpiar, self.boton_evaluar, espacio=px(8, False)))

        # -- panel "Que tal ha salido": la tabla de grados -------------------------------
        self.panel_tabla = PanelC(t("Qué tal ha salido"))
        self.tabla = QTableWidget(0, 5)
        self.tabla.verticalHeader().hide()
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionMode(QTableWidget.NoSelection)
        self.tabla.setFocusPolicy(Qt.NoFocus)
        self.tabla.setShowGrid(False)
        self.tabla.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cabecera = self.tabla.horizontalHeader()
        cabecera.setHighlightSections(False)
        cabecera.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cabecera.moveSection(COL_BARRA, COL_GRADO)  # la barra se ve antes que el grado
        for col, modo in ((COL_NOMBRE, QHeaderView.ResizeToContents), (COL_VALOR, QHeaderView.ResizeToContents),
                          (COL_RANGO, QHeaderView.ResizeToContents), (COL_BARRA, QHeaderView.Stretch),
                          (COL_GRADO, QHeaderView.Fixed)):
            cabecera.setSectionResizeMode(col, modo)
        self.tabla.setColumnWidth(COL_GRADO, px(64, False))
        self.tabla.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.vacio_tabla = EtiquetaC("", "pequeno", envolver=True)
        self.leyenda = EtiquetaC("", "pequeno")
        self.panel_tabla.capa.addWidget(self.tabla)
        self.panel_tabla.capa.addWidget(self.vacio_tabla)
        self.panel_tabla.capa.addWidget(Linea())
        self.panel_tabla.capa.addWidget(self.leyenda)

        # -- panel "Veredicto" ------------------------------------------------------------
        self.panel_veredicto = PanelC(t("Veredicto"))
        self.titular = EtiquetaC("", "destacado", envolver=True)
        self.titular.hide()
        self.veredicto = EtiquetaC("", "normal", tinta="suave", envolver=True)
        self.veredicto.hide()
        self.boton_precio = BotonC(icono=GLIFO_TIENDA, tam=11)
        self.boton_precio.clicked.connect(self.consultar_precio)
        self.boton_precio.setEnabled(False)
        self.nota_precio = EtiquetaC("", "pequeno", envolver=True)
        # Horquilla de precio de agrietados parecidos: se pide sola al evaluar, en el hilo de red.
        self.horquilla = EtiquetaC("", "normal", envolver=True)
        self.horquilla.setTextFormat(Qt.RichText)
        self.horquilla.hide()
        self.panel_veredicto.capa.addWidget(self.titular)
        self.panel_veredicto.capa.addWidget(self.veredicto)
        self.panel_veredicto.capa.addWidget(self.horquilla)
        self.panel_veredicto.capa.addLayout(fila(self.boton_precio, self.nota_precio, espacio=px(10, False)))

        # -- panel del precio (solo cuando hay algo que ensenar) --------------------------
        self.panel_precio = PanelC(t("Precio de agrietados parecidos"), remate=False)
        self.precio = EtiquetaC("", "normal", envolver=True)
        self.precio.setTextFormat(Qt.RichText)
        self.panel_precio.capa.addWidget(self.precio)
        self.panel_precio.hide()

        # -- pie: como se usa --------------------------------------------------------------
        self.nota = EtiquetaC("", "pequeno", tinta="tenue", envolver=True)

        izquierda = columna(self.panel_form, None, espacio=px(12, False))
        derecha = columna(self.panel_tabla, self.panel_veredicto, self.panel_precio, None, espacio=px(12, False))
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(px(16, False))
        cuerpo.addLayout(izquierda, 4)
        cuerpo.addLayout(derecha, 6)
        contenido = transparente(QWidget())
        caja_contenido = QVBoxLayout(contenido)
        caja_contenido.setContentsMargins(0, px(4, False), px(4, False), 0)
        caja_contenido.setSpacing(px(12, False))
        caja_contenido.addLayout(cuerpo, 1)
        caja_contenido.addWidget(self.nota)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(contenido)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(area)

        # -- hilo de red -----------------------------------------------------------------
        self.hilo: QThread | None = None
        self.trabajador: _Trabajador | None = None
        if con_red:
            self.hilo = QThread(self)
            self.trabajador = _Trabajador()
            self.trabajador.moveToThread(self.hilo)
            self.trabajador.armas.connect(self.poner_armas)
            self.trabajador.precio.connect(self._precio_listo)
            self.trabajador.horquilla.connect(self._horquilla_lista)
            self._pedir_horquilla.connect(self.trabajador.pedir_horquilla)
            self.trabajador.fallo.connect(self._fallo_red)
            self._pedir_armas.connect(self.trabajador.cargar_armas)
            self._pedir_precio.connect(self.trabajador.consultar)
            self.hilo.start()
            self._pedir_armas.emit()
            app = QCoreApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.cerrar)
            # Si la pestana se destruye sin pasar por aboutToQuit (tests, cierre sin exec), Qt
            # mataria el proceso al destruir un QThread vivo ("Destroyed while thread is still
            # running"). `destroyed` llega antes de borrar los hijos: se para aqui el hilo.
            hilo = self.hilo
            self.destroyed.connect(lambda *_: _parar_hilo(hilo))
        self.repintar()
        self.retraducir()
        self._vaciar_tabla()

    # -- ciclo de vida ---------------------------------------------------------------------

    def conectar_indice(self, con) -> None:
        """Nombres en castellano de las armas, para el desplegable."""
        try:
            self.nombres_es = {u: n for u, n in con.execute("SELECT unique_name, nombre_es FROM items WHERE nombre_es IS NOT NULL") if n}
        except Exception:  # noqa: BLE001
            self.nombres_es = {}
        if self.armas:
            self.poner_armas(self.armas)

    def cerrar(self) -> None:
        if self.hilo is not None:
            _parar_hilo(self.hilo)
            self.hilo = None

    def retraducir(self) -> None:
        atajo = self.config.get("hotkey_agrietado", "")
        self.boton_leer.setText(t("Leer la tarjeta bajo el cursor"))
        self.boton_leer.setToolTip(
            t("Leer la tarjeta bajo el cursor ({atajo})", atajo=atajo) if atajo else t("Leer la tarjeta bajo el cursor")
        )
        self.tecla_atajo.setText(atajo.upper())
        self.tecla_atajo.setVisible(bool(atajo))
        self.nota.setText(t(
            "Elige el arma, apunta cada estadística con su valor (marca la negativa) y pulsa Evaluar: "
            "verás entre qué valores puede salir cada una en esa arma y qué grado tiene la tuya, de S "
            "(lo mejor) a F. Si pones el ratón encima de la tarjeta en el juego y pulsas el botón o el "
            "atajo, Farmadex intenta rellenarlo por ti; si no lo lee seguro, te avisa para que lo revises."
        ))
        self.panel_form.poner_titulo(t("El agrietado"))
        self.panel_tabla.poner_titulo(t("Qué tal ha salido"))
        self.panel_veredicto.poner_titulo(t("Veredicto"))
        self.panel_precio.poner_titulo(t("Precio de agrietados parecidos"))
        self.etiqueta_arma.setText(t("Arma"))
        self.etiqueta_disposicion.setText(t("Disposición"))
        self.etiqueta_stat.setText(t("Estadística"))
        self.etiqueta_valor.setText(t("Valor"))
        self.etiqueta_negativo.setText(t("Negativa"))
        self.etiqueta_maestria.setText(t("Maestría"))
        self.etiqueta_variado.setText(t("Veces variado"))
        self.boton_evaluar.setText(t("Evaluar"))
        self.boton_limpiar.setText(t("Limpiar"))
        self.boton_precio.setText(t("Consultar precio"))
        self.nota_precio.setText(t("Mira las subastas de warframe.market y la media de la semana."))
        self.vacio_tabla.setText(t("Apunta las estadísticas y pulsa Evaluar: aquí verás qué tal ha salido cada una."))
        self.tabla.setHorizontalHeaderLabels(
            [t("Estadística").upper(), t("Valor").upper(), t("Puede salir entre").upper(), t("Grado").upper(), ""]
        )
        self._pintar_leyenda()
        self._arma_cambiada(self.arma.currentIndex())
        if self.evaluaciones:
            self._pintar_evaluaciones()

    def repintar(self) -> None:
        """Tras cambiar de tema o de tamano: la tabla y los campos llevan su hoja propia."""
        p = PALETA
        self.setStyleSheet(
            f"QSpinBox, QDoubleSpinBox {{ background: {p['panel2']}; border: 1px solid {p['borde']};"
            f" padding: {px(4, False)}px {px(8, False)}px; font-family: '{TITULAR}'; font-weight: 600;"
            f" font-size: {px(13)}px; }}"
            f" QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {p['acento']}; }}"
        )
        self.tabla.setStyleSheet(
            f"QTableWidget {{ background: transparent; border: none; }}"
            f" QTableWidget::item {{ padding: 0 {px(8, False)}px 0 0; border: none; }}"
            f" QHeaderView {{ background: transparent; }}"
            f" QHeaderView::section {{ background: transparent; color: {p['suave']}; border: none;"
            f" border-bottom: 1px solid {p['borde']}; padding: 0 {px(8, False)}px {px(4, False)}px 0;"
            f" font-family: '{TITULAR}'; font-size: {px(11)}px; font-weight: 600; }}"
        )
        self._pintar_leyenda()
        if self.evaluaciones:
            self._pintar_evaluaciones()

    def _pintar_leyenda(self) -> None:
        """"De peor a mejor: F C- C ... S", cada letra en el color de su grado."""
        letras = " ".join(
            f"<span style='color: {grados.COLOR_GRADO[letra]}; font-family: {TITULAR}; font-weight: 700;'>"
            f"{letra}</span>" for letra, _d, _h in reversed(grados.GRADOS)
        )
        self.leyenda.setText(f"{t('De peor a mejor:')}&nbsp; {letras}")

    # -- armas ------------------------------------------------------------------------------

    @Slot(list)
    def poner_armas(self, armas: list) -> None:
        self.armas = list(armas)
        actual = self.arma.currentData()
        self.arma.blockSignals(True)
        self.arma.clear()
        self.arma.addItem("", None)
        for a in sorted(self.armas, key=lambda a: self._nombre_arma(a).lower()):
            self.arma.addItem(self._nombre_arma(a), a)
        completador = QCompleter([self.arma.itemText(i) for i in range(self.arma.count())], self.arma)
        completador.setCaseSensitivity(Qt.CaseInsensitive)
        completador.setFilterMode(Qt.MatchContains)
        self.arma.setCompleter(completador)
        self.arma.blockSignals(False)
        if actual is not None:
            self.elegir_arma(actual.slug)
        if not self.armas:
            self._poner_estado(t("No hay lista de armas con agrietado: hace falta conexión la primera vez."))

    def _nombre_arma(self, arma: mercado.Arma) -> str:
        nombre_es = self.nombres_es.get(arma.unique_name)
        if nombre_es and nombre_es.lower() != arma.nombre_en.lower():
            return f"{nombre_es} ({arma.nombre_en})"
        return arma.nombre_en

    def arma_elegida(self) -> mercado.Arma | None:
        dato = self.arma.currentData()
        return dato if isinstance(dato, mercado.Arma) else None

    def elegir_arma(self, slug: str) -> bool:
        for i in range(self.arma.count()):
            dato = self.arma.itemData(i)
            if isinstance(dato, mercado.Arma) and dato.slug == slug:
                self.arma.setCurrentIndex(i)
                return True
        return False

    def _arma_cambiada(self, _indice: int) -> None:
        arma = self.arma_elegida()
        if arma is None:
            self.disposicion.setText("")
            self.rombos.poner(0)
            self.rombos.setToolTip("")
            return
        extra = ""
        if arma.tipo == "kitgun":
            extra = "  " + t("(kitgun: se evalúa como secundaria)")
        self.rombos.poner(rombos_disposicion(arma.disposicion))
        self.rombos.setToolTip(t("disposición {d} {puntos}", d=f"{arma.disposicion:.2f}",
                                 puntos=puntos_disposicion(arma.disposicion)))
        self.disposicion.setText(f"×{arma.disposicion:.2f}{extra}")
        self.boton_precio.setEnabled(True)

    # -- formulario -------------------------------------------------------------------------

    def estadisticas(self) -> list[tuple[str, float, bool]]:
        """(slug, valor con signo, negativo) de las filas rellenas."""
        salida = []
        for atributo, valor, negativo in self.filas:
            slug = atributo.currentData()
            if not slug or valor.value() <= 0:
                continue
            v = valor.value()
            salida.append((slug, -v if negativo.isChecked() else v, negativo.isChecked()))
        return salida

    def poner_estadisticas(self, estadisticas: list[tuple[str | None, float | None, bool]]) -> None:
        for i, (atributo, valor, negativo) in enumerate(self.filas):
            if i < len(estadisticas):
                slug, v, neg = estadisticas[i]
                atributo.setCurrentIndex(max(0, atributo.findData(slug or "")))
                valor.setValue(abs(v) if v is not None else 0.0)
                negativo.setChecked(bool(neg))
            else:
                atributo.setCurrentIndex(0)
                valor.setValue(0.0)
                negativo.setChecked(False)

    def limpiar(self) -> None:
        self.tarjeta = None
        self.evaluaciones = []
        self.arma.setCurrentIndex(0)
        self.poner_estadisticas([])
        self.maestria.setValue(0)
        self.variado.setValue(0)
        self.nombre.setText("")
        self._poner_estado("")
        self._poner_veredicto("")
        self._poner_precio("")
        self._poner_horquilla("")
        self._vaciar_tabla()

    def _poner_horquilla(self, texto: str) -> None:
        self.horquilla.setText(texto)
        self.horquilla.setVisible(bool(texto))
        if not texto:
            self._horquilla_pedida = None

    def _poner_estado(self, texto: str) -> None:
        self.estado.setText(texto)
        self.estado.setVisible(bool(texto))

    def _poner_veredicto(self, texto: str, titular: str = "", aviso: bool = False) -> None:
        self.titular.setText(titular)
        self.titular.setVisible(bool(titular))
        self.veredicto.setText(texto)
        self.veredicto.setVisible(bool(texto))
        self.veredicto.poner_tinta("aviso" if aviso else "suave")

    def _poner_precio(self, texto: str) -> None:
        self.precio.setText(texto)
        self.panel_precio.setVisible(bool(texto))

    def _vaciar_tabla(self) -> None:
        self.tabla.setRowCount(0)
        self._ajustar_alto_tabla()
        self.vacio_tabla.show()

    # -- lectura de pantalla ---------------------------------------------------------------

    @Slot(object)
    def mostrar_tarjeta(self, tarjeta: TarjetaLeida) -> None:
        """Rellena el formulario con lo leido y evalua si todo esta claro."""
        self.tarjeta = tarjeta
        self.evaluaciones = []
        self._vaciar_tabla()
        self._poner_veredicto("")
        self._poner_precio("")
        self._poner_horquilla("")
        if tarjeta.velado:
            self._poner_estado(t("La tarjeta está velada: no tiene estadísticas hasta que hagas su desafío."))
            return
        if tarjeta.arma_slug:
            if not self.elegir_arma(tarjeta.arma_slug):
                self.arma.setEditText(tarjeta.arma_nombre or tarjeta.arma_texto)
        elif tarjeta.arma_texto:
            self.arma.setCurrentIndex(0)
            self.arma.setEditText(tarjeta.arma_texto)
        self.nombre.setText(tarjeta.nombre)
        self.poner_estadisticas([(e.slug, e.valor, e.negativo) for e in tarjeta.estadisticas])
        self.maestria.setValue(tarjeta.maestria or 0)
        self.variado.setValue(tarjeta.variado or 0)
        if tarjeta.fiable:
            self._poner_estado(t("Leído de la pantalla. Si algo no cuadra, corrígelo y vuelve a evaluar."))
            self.estado.poner_tinta("suave")
            self.evaluar()
        elif tarjeta.avisos:
            self._poner_estado(t("Leído a medias, revisa antes de evaluar:") + "\n• "
                               + "\n• ".join(t(a) for a in tarjeta.avisos))
            self.estado.poner_tinta("aviso")
        else:
            self._poner_estado(t("No se ve ninguna tarjeta de agrietado bajo el cursor."))
            self.estado.poner_tinta("aviso")

    # -- evaluacion --------------------------------------------------------------------------

    def evaluar(self) -> None:
        arma = self.arma_elegida()
        estadisticas = self.estadisticas()
        if arma is None:
            self._poner_veredicto(t("Elige el arma del agrietado."), aviso=True)
            return
        if len(estadisticas) < 2:
            self._poner_veredicto(t("Apunta al menos dos estadísticas."), aviso=True)
            return
        positivos = [e for e in estadisticas if not e[2]]
        negativos = [e for e in estadisticas if e[2]]
        if len(positivos) not in (2, 3) or len(negativos) > 1:
            self._poner_veredicto(t("Un agrietado lleva 2 o 3 positivas y como mucho 1 negativa."), aviso=True)
            return
        self.evaluaciones = grados.evaluar(estadisticas, arma.clase, arma.disposicion)
        self._pintar_evaluaciones()
        self.boton_precio.setEnabled(True)
        self._consultar_horquilla(arma, positivos, negativos)

    def _consultar_horquilla(self, arma, positivos: list, negativos: list) -> None:
        """Pide en el hilo de red la horquilla de parecidos; la evaluacion ya esta pintada.

        Solo con una evaluacion sin valores imposibles: si el arma o un valor estan mal,
        el precio de "parecidos" seria el de otro agrietado.
        """
        if any(ev.minimo is None or not ev.grado for ev in self.evaluaciones):
            self._poner_horquilla("")
            return
        pos = [s for s, _v, _n in positivos]
        neg = negativos[0][0] if negativos else ""
        clave = clave_horquilla(arma.slug, pos, neg)
        if self.trabajador is None:
            return
        self._poner_horquilla(t("Precio de parecidos: consultando warframe.market..."))
        self._horquilla_pedida = clave
        self._pedir_horquilla.emit(clave, arma.slug, pos, neg)

    @Slot(str, object)
    def _horquilla_lista(self, clave: str, h) -> None:
        if clave != self._horquilla_pedida:
            return  # de un agrietado anterior
        self.horquilla.setText(texto_horquilla(h))
        self.horquilla.show()

    def _celda(self, texto: str, tinta: str = "texto", rol: str = "normal", alineacion=None) -> QTableWidgetItem:
        celda = QTableWidgetItem(texto)
        celda.setForeground(QColor(PALETA.get(tinta, tinta)))
        f = QFont("Segoe UI" if rol == "normal" else TITULAR)
        f.setPixelSize(px(14 if rol != "grado" else 20))
        f.setWeight(QFont.Weight(600 if rol != "suave" else 400))
        if rol == "suave":
            f.setPixelSize(px(13))
        celda.setFont(f)
        celda.setTextAlignment(alineacion or (Qt.AlignLeft | Qt.AlignVCenter))
        return celda

    def _pintar_evaluaciones(self) -> None:
        self.tabla.setRowCount(len(self.evaluaciones))
        self.vacio_tabla.setVisible(not self.evaluaciones)
        fuera = []
        letras = []
        for fila_t, ev in enumerate(self.evaluaciones):
            atributo = ev.atributo
            nombre = atributo.nombre_es if atributo else ev.slug
            self.tabla.setItem(fila_t, COL_NOMBRE, self._celda(nombre + (f" ({t('negativa')})" if ev.negativo else "")))
            self.tabla.setItem(fila_t, COL_VALOR, self._celda(grados.formatear_valor(ev.slug, ev.valor), rol="dato"))
            self.tabla.removeCellWidget(fila_t, COL_BARRA)
            if ev.minimo is None:
                self.tabla.setItem(fila_t, COL_RANGO, self._celda(t("no puede salir en esta arma"), "aviso", "suave"))
                self.tabla.setItem(fila_t, COL_GRADO, self._celda("?", "aviso", "grado", Qt.AlignCenter))
                fuera.append(nombre)
                continue
            self.tabla.setItem(fila_t, COL_RANGO, self._celda(
                f"{grados.formatear_valor(ev.slug, ev.minimo)}  …  {grados.formatear_valor(ev.slug, ev.maximo)}",
                "suave", "suave",
            ))
            color_grado = grados.COLOR_GRADO.get(ev.grado or "", PALETA["aviso"])
            if ev.grado:
                self.tabla.setItem(fila_t, COL_GRADO, self._celda(ev.grado, color_grado, "grado", Qt.AlignCenter))
                letras.append(ev.grado)
            else:
                self.tabla.setItem(fila_t, COL_GRADO, self._celda(t("fuera de rango"), "aviso", "suave", Qt.AlignCenter))
                fuera.append(nombre)
            barra = BarraFina(ev.posicion or 0.0, tinta=color_grado, alto=6)
            hueco = transparente(QWidget())
            hueco.setLayout(fila(barra, espacio=0, margen=(0, 0, px(12, False), 0)))
            barra.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.tabla.setCellWidget(fila_t, COL_BARRA, hueco)
        for fila_t in range(self.tabla.rowCount()):
            self.tabla.setRowHeight(fila_t, px(32, False))
        self._ajustar_alto_tabla()
        if fuera:
            self._poner_veredicto(t(
                "{lista}: el valor no entra en lo posible para esta arma. Suele ser que el arma no es esa, "
                "que el valor está mal apuntado o que el signo está al revés.", lista=", ".join(fuera),
            ), aviso=True)
        else:
            self._poner_veredicto(
                t("Grados: {grados}. Un grado alto solo dice que la tirada fue buena; que el agrietado "
                  "sirva depende de que las estadísticas le vengan bien al arma.", grados=", ".join(letras)),
                titular=titular_de(self.evaluaciones),
            )

    def _ajustar_alto_tabla(self) -> None:
        """La tabla tan alta como sus filas: el desplazamiento lo lleva la pagina entera."""
        alto = self.tabla.horizontalHeader().sizeHint().height()
        alto += sum(self.tabla.rowHeight(f) for f in range(self.tabla.rowCount()))
        self.tabla.setFixedHeight(alto + 4)

    # -- precio ------------------------------------------------------------------------------

    def consultar_precio(self) -> None:
        arma = self.arma_elegida()
        if arma is None or self.trabajador is None:
            return
        estadisticas = self.estadisticas()
        positivos = [s for s, _, n in estadisticas if not n]
        negativos = [s for s, _, n in estadisticas if n]
        self._precio_pedido = arma.slug
        self._poner_precio(t("Consultando warframe.market..."))
        self._pedir_precio.emit(arma.slug, arma.nombre_en, positivos, negativos)

    @Slot(str, object, object, object)
    def _precio_listo(self, slug: str, resumen, media_sin, media_con) -> None:
        if slug != self._precio_pedido:
            return
        self._poner_precio(texto_precio(resumen, media_sin, media_con, variado=self.variado.value()))

    @Slot(str)
    def _fallo_red(self, motivo: str) -> None:
        if self._precio_pedido:
            self._poner_precio(t("No se pudo consultar el precio ({motivo}).", motivo=motivo))


def texto_precio(resumen, media_sin, media_con, variado: int = 0) -> str:
    """El precio de referencia en una o dos frases legibles (HTML sencillo)."""
    partes = []
    if resumen is None or resumen.error:
        partes.append(t("warframe.market: no disponible ({error})", error=(resumen.error if resumen else "")))
    elif not resumen.subastas:
        partes.append(t("warframe.market: ahora mismo no hay subastas de esta arma."))
    else:
        n = len(resumen.subastas)
        partes.append(t(
            "warframe.market: {n} subastas parecidas abiertas, la más barata <b>{minimo}p</b>, mediana <b>{mediana}p</b>.",
            n=n, minimo=resumen.minimo, mediana=f"{resumen.mediana:.0f}",
        ))
    media = media_con if variado else media_sin
    if media is not None:
        partes.append(t(
            "Semana de DE ({tipo}): mediana <b>{mediana}p</b>, media {media}p, {n} ventas.",
            tipo=t("variados") if media.variado else t("sin variar"),
            mediana=f"{media.mediana:.0f}", media=f"{media.media:.0f}", n=media.volumen,
        ))
    partes.append(t("Es solo una referencia: lo que vale de verdad depende de qué estadísticas lleve y de a quién le sirvan."))
    return "<br>".join(partes)
