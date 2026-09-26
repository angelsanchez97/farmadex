"""Pestana Agrietados: evalua un riven (grado de cada estadistica) y da un precio de referencia.

La via principal es a mano: eliges el arma, apuntas las estadisticas con su
signo y pulsas Evaluar. El lector de pantalla (boton o atajo, con el raton sobre
la tarjeta) solo rellena el formulario; si algo no lo leyo seguro, lo dice y te
deja corregirlo antes de evaluar.

Los grados siguen la guia de agrietados (S..F segun donde cayo el azar dentro
del margen posible para esa arma), y el precio sale de las subastas abiertas de
warframe.market con estadisticas parecidas y de la media semanal que publica DE.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
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
from .widgets import PALETA

log = obtener("ui.agrietados")

FILAS_STATS = 4


def puntos_disposicion(disposicion: float) -> str:
    """Los circulos que ensena el juego: 5 de 1.31 a 1.55, 1 de 0.5 a 0.69."""
    if disposicion >= 1.31:
        n = 5
    elif disposicion >= 1.11:
        n = 4
    elif disposicion >= 0.9:
        n = 3
    elif disposicion >= 0.7:
        n = 2
    else:
        n = 1
    return "●" * n + "○" * (5 - n)



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


class PestanaAgrietados(QWidget):
    pedir_lectura = Signal()
    _pedir_armas = Signal()
    _pedir_precio = Signal(str, str, list, list)

    def __init__(self, parent=None, con_red: bool = True):
        super().__init__(parent)
        self.config = cargar()
        self.armas: list[mercado.Arma] = []
        self.nombres_es: dict[str, str] = {}
        self.tarjeta: TarjetaLeida | None = None
        self.evaluaciones: list[grados.Evaluacion] = []
        self._precio_pedido: str | None = None

        # -- lectura de pantalla ----------------------------------------------------
        self.boton_leer = QPushButton()
        self.boton_leer.setObjectName("principal")
        self.boton_leer.setCursor(Qt.PointingHandCursor)
        self.boton_leer.clicked.connect(self.pedir_lectura.emit)
        self.nota = QLabel()
        self.nota.setWordWrap(True)
        self.nota.setStyleSheet(f"color: {PALETA['suave']};")
        self.estado = QLabel("")
        self.estado.setWordWrap(True)

        # -- formulario --------------------------------------------------------------
        self.arma = QComboBox()
        self.arma.setEditable(True)
        self.arma.setInsertPolicy(QComboBox.NoInsert)
        self.arma.currentIndexChanged.connect(self._arma_cambiada)
        self.disposicion = QLabel("")
        self.disposicion.setStyleSheet(f"color: {PALETA['suave']};")
        self.nombre = QLabel("")
        self.nombre.setStyleSheet(f"color: {PALETA['suave']};")
        self.filas: list[tuple[QComboBox, QDoubleSpinBox, QCheckBox]] = []
        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(8)
        self.etiqueta_stat = QLabel()
        self.etiqueta_valor = QLabel()
        self.etiqueta_negativo = QLabel()
        rejilla.addWidget(self.etiqueta_stat, 0, 0)
        rejilla.addWidget(self.etiqueta_valor, 0, 1)
        rejilla.addWidget(self.etiqueta_negativo, 0, 2)
        for i in range(FILAS_STATS):
            atributo = QComboBox()
            atributo.addItem("—", "")
            for a in grados.ATRIBUTOS:
                atributo.addItem(f"{a.nombre_es} ({a.nombre_en})", a.slug)
            valor = QDoubleSpinBox()
            valor.setDecimals(1)
            valor.setRange(0.0, 999.0)
            valor.setSingleStep(0.1)
            negativo = QCheckBox()
            rejilla.addWidget(atributo, i + 1, 0)
            rejilla.addWidget(valor, i + 1, 1)
            rejilla.addWidget(negativo, i + 1, 2)
            self.filas.append((atributo, valor, negativo))
        self.maestria = QSpinBox()
        self.maestria.setRange(0, 30)
        self.maestria.setSpecialValueText("?")
        self.variado = QSpinBox()
        self.variado.setRange(0, 999)
        self.boton_evaluar = QPushButton()
        self.boton_evaluar.setObjectName("principal")
        self.boton_evaluar.clicked.connect(self.evaluar)
        self.boton_limpiar = QPushButton()
        self.boton_limpiar.clicked.connect(self.limpiar)

        formulario = QFormLayout()
        formulario.setHorizontalSpacing(12)
        self.etiqueta_arma = QLabel()
        self.etiqueta_maestria = QLabel()
        self.etiqueta_variado = QLabel()
        fila_arma = QHBoxLayout()
        fila_arma.addWidget(self.arma, 1)
        fila_arma.addWidget(self.disposicion)
        formulario.addRow(self.etiqueta_arma, fila_arma)
        fila_pie = QHBoxLayout()
        fila_pie.addWidget(self.etiqueta_maestria)
        fila_pie.addWidget(self.maestria)
        fila_pie.addSpacing(12)
        fila_pie.addWidget(self.etiqueta_variado)
        fila_pie.addWidget(self.variado)
        fila_pie.addStretch(1)
        fila_pie.addWidget(self.boton_limpiar)
        fila_pie.addWidget(self.boton_evaluar)

        # -- resultado ------------------------------------------------------------------
        self.tabla = QTableWidget(0, 4)
        self.tabla.verticalHeader().hide()
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionMode(QTableWidget.NoSelection)
        self.tabla.horizontalHeader().setStretchLastSection(True)
        self.veredicto = QLabel("")
        self.veredicto.setWordWrap(True)
        self.precio = QLabel("")
        self.precio.setWordWrap(True)
        self.precio.setTextFormat(Qt.RichText)
        self.boton_precio = QPushButton()
        self.boton_precio.clicked.connect(self.consultar_precio)
        self.boton_precio.setEnabled(False)
        fila_precio = QHBoxLayout()
        fila_precio.addWidget(self.boton_precio)
        fila_precio.addWidget(self.precio, 1)

        arriba = QHBoxLayout()
        arriba.addWidget(self.boton_leer)
        arriba.addWidget(self.nombre, 1)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 8, 4, 4)
        caja.setSpacing(8)
        caja.addLayout(arriba)
        caja.addWidget(self.nota)
        caja.addWidget(self.estado)
        caja.addLayout(formulario)
        caja.addLayout(rejilla)
        caja.addLayout(fila_pie)
        caja.addWidget(self.tabla, 1)
        caja.addWidget(self.veredicto)
        caja.addLayout(fila_precio)

        # -- hilo de red -----------------------------------------------------------------
        self.hilo: QThread | None = None
        self.trabajador: _Trabajador | None = None
        if con_red:
            self.hilo = QThread(self)
            self.trabajador = _Trabajador()
            self.trabajador.moveToThread(self.hilo)
            self.trabajador.armas.connect(self.poner_armas)
            self.trabajador.precio.connect(self._precio_listo)
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
        self.retraducir()

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
        self.boton_leer.setText(
            t("Leer la tarjeta bajo el cursor ({atajo})", atajo=atajo) if atajo else t("Leer la tarjeta bajo el cursor")
        )
        self.nota.setText(t(
            "Elige el arma, apunta cada estadistica con su valor (marca la negativa) y pulsa Evaluar: "
            "veras entre que valores puede salir cada una en esa arma y que grado tiene la tuya, de S "
            "(lo mejor) a F. Si pones el raton encima de la tarjeta en el juego y pulsas el boton o el "
            "atajo, Farmadex intenta rellenarlo por ti; si no lo lee seguro, te avisa para que lo revises."
        ))
        self.etiqueta_arma.setText(t("Arma"))
        self.etiqueta_stat.setText(t("Estadistica"))
        self.etiqueta_valor.setText(t("Valor"))
        self.etiqueta_negativo.setText(t("Negativa"))
        self.etiqueta_maestria.setText(t("Maestria"))
        self.etiqueta_variado.setText(t("Veces variado"))
        self.boton_evaluar.setText(t("Evaluar"))
        self.boton_limpiar.setText(t("Limpiar"))
        self.boton_precio.setText(t("Consultar precio"))
        self.tabla.setHorizontalHeaderLabels([t("Estadistica"), t("Valor"), t("Puede salir entre"), t("Grado")])
        if self.evaluaciones:
            self._pintar_evaluaciones()

    def repintar(self) -> None:
        self.nota.setStyleSheet(f"color: {PALETA['suave']};")
        self.disposicion.setStyleSheet(f"color: {PALETA['suave']};")
        self.nombre.setStyleSheet(f"color: {PALETA['suave']};")
        if self.evaluaciones:
            self._pintar_evaluaciones()

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
            self.estado.setText(t("No hay lista de armas con agrietado: hace falta conexion la primera vez."))

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
            return
        extra = ""
        if arma.tipo == "kitgun":
            extra = "  " + t("(kitgun: se evalua como secundaria)")
        self.disposicion.setText(
            t("disposicion {d} {puntos}", d=f"{arma.disposicion:.2f}", puntos=puntos_disposicion(arma.disposicion)) + extra
        )
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
        self.estado.setText("")
        self.veredicto.setText("")
        self.precio.setText("")
        self.tabla.setRowCount(0)

    # -- lectura de pantalla ---------------------------------------------------------------

    @Slot(object)
    def mostrar_tarjeta(self, tarjeta: TarjetaLeida) -> None:
        """Rellena el formulario con lo leido y evalua si todo esta claro."""
        self.tarjeta = tarjeta
        self.evaluaciones = []
        self.tabla.setRowCount(0)
        self.veredicto.setText("")
        self.precio.setText("")
        if tarjeta.velado:
            self.estado.setText(t("La tarjeta esta velada: no tiene estadisticas hasta que hagas su desafio."))
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
            self.estado.setText(t("Leido de la pantalla. Si algo no cuadra, corrigelo y vuelve a evaluar."))
            self.evaluar()
        elif tarjeta.avisos:
            self.estado.setText(t("Leido a medias, revisa antes de evaluar:") + "\n• " + "\n• ".join(t(a) for a in tarjeta.avisos))
        else:
            self.estado.setText(t("No se ve ninguna tarjeta de agrietado bajo el cursor."))

    # -- evaluacion --------------------------------------------------------------------------

    def evaluar(self) -> None:
        arma = self.arma_elegida()
        estadisticas = self.estadisticas()
        if arma is None:
            self.veredicto.setText(t("Elige el arma del agrietado."))
            return
        if len(estadisticas) < 2:
            self.veredicto.setText(t("Apunta al menos dos estadisticas."))
            return
        positivos = [e for e in estadisticas if not e[2]]
        negativos = [e for e in estadisticas if e[2]]
        if len(positivos) not in (2, 3) or len(negativos) > 1:
            self.veredicto.setText(t("Un agrietado lleva 2 o 3 positivas y como mucho 1 negativa."))
            return
        self.evaluaciones = grados.evaluar(estadisticas, arma.clase, arma.disposicion)
        self._pintar_evaluaciones()
        self.boton_precio.setEnabled(True)

    def _pintar_evaluaciones(self) -> None:
        self.tabla.setRowCount(len(self.evaluaciones))
        fuera = []
        letras = []
        for fila, ev in enumerate(self.evaluaciones):
            atributo = ev.atributo
            nombre = atributo.nombre_es if atributo else ev.slug
            self.tabla.setItem(fila, 0, QTableWidgetItem(nombre + ("  (−)" if ev.negativo else "")))
            self.tabla.setItem(fila, 1, QTableWidgetItem(grados.formatear_valor(ev.slug, ev.valor)))
            if ev.minimo is None:
                self.tabla.setItem(fila, 2, QTableWidgetItem(t("no puede salir en esta arma")))
                self.tabla.setItem(fila, 3, QTableWidgetItem("?"))
                fuera.append(nombre)
                continue
            self.tabla.setItem(fila, 2, QTableWidgetItem(
                f"{grados.formatear_valor(ev.slug, ev.minimo)}  …  {grados.formatear_valor(ev.slug, ev.maximo)}"
            ))
            celda = QTableWidgetItem(ev.grado or t("fuera de rango"))
            if ev.grado:
                celda.setForeground(Qt.GlobalColor.black)
                celda.setBackground(_color(grados.COLOR_GRADO[ev.grado]))
                letras.append(ev.grado)
            else:
                fuera.append(nombre)
            celda.setTextAlignment(Qt.AlignCenter)
            self.tabla.setItem(fila, 3, celda)
        self.tabla.resizeColumnsToContents()
        if fuera:
            self.veredicto.setText(t(
                "{lista}: el valor no entra en lo posible para esta arma. Suele ser que el arma no es esa, "
                "que el valor esta mal apuntado o que el signo esta al reves.", lista=", ".join(fuera),
            ))
            self.veredicto.setStyleSheet(f"color: {PALETA['aviso']};")
        else:
            self.veredicto.setStyleSheet("")
            self.veredicto.setText(t("Grados: {grados}. Un grado alto solo dice que la tirada fue buena; que el agrietado "
                                     "sirva depende de que las estadisticas le vengan bien al arma.",
                                     grados=", ".join(letras)))

    # -- precio ------------------------------------------------------------------------------

    def consultar_precio(self) -> None:
        arma = self.arma_elegida()
        if arma is None or self.trabajador is None:
            return
        estadisticas = self.estadisticas()
        positivos = [s for s, _, n in estadisticas if not n]
        negativos = [s for s, _, n in estadisticas if n]
        self._precio_pedido = arma.slug
        self.precio.setText(t("Consultando warframe.market..."))
        self._pedir_precio.emit(arma.slug, arma.nombre_en, positivos, negativos)

    @Slot(str, object, object, object)
    def _precio_listo(self, slug: str, resumen, media_sin, media_con) -> None:
        if slug != self._precio_pedido:
            return
        self.precio.setText(texto_precio(resumen, media_sin, media_con, variado=self.variado.value()))

    @Slot(str)
    def _fallo_red(self, motivo: str) -> None:
        if self._precio_pedido:
            self.precio.setText(t("No se pudo consultar el precio ({motivo}).", motivo=motivo))


def texto_precio(resumen, media_sin, media_con, variado: int = 0) -> str:
    """El precio de referencia en una o dos frases legibles (HTML sencillo)."""
    partes = []
    if resumen is None or resumen.error:
        partes.append(t("warframe.market: no disponible ({error})", error=(resumen.error if resumen else "")))
    elif not resumen.subastas:
        partes.append(t("warframe.market: ahora mismo no hay subastas de este arma."))
    else:
        n = len(resumen.subastas)
        partes.append(t(
            "warframe.market: {n} subastas parecidas abiertas, la mas barata <b>{minimo}p</b>, mediana <b>{mediana}p</b>.",
            n=n, minimo=resumen.minimo, mediana=f"{resumen.mediana:.0f}",
        ))
    media = media_con if variado else media_sin
    if media is not None:
        partes.append(t(
            "Semana de DE ({tipo}): mediana <b>{mediana}p</b>, media {media}p, {n} ventas.",
            tipo=t("variados") if media.variado else t("sin variar"),
            mediana=f"{media.mediana:.0f}", media=f"{media.media:.0f}", n=media.volumen,
        ))
    partes.append(t("Es solo una referencia: lo que vale de verdad depende de que estadisticas lleve y de a quien le sirvan."))
    return "<br>".join(partes)


def _color(hexadecimal: str):
    from PySide6.QtGui import QColor

    return QColor(hexadecimal)
