"""Herramientas > Mercado: que merece la pena vender, por niveles (S, A, B, C, D).

Todo sale de la foto diaria de precios (online/precios_diarios.py), sin red: la cuenta
(datos/rentabilidad.py) va en un hilo de fondo y la tabla es un QTableView con modelo
propio, que solo pinta las filas que se ven (miles de objetos sin atascar la ventana).

Parada no gasta nada: el reloj de la cuenta atras solo corre con la pagina a la vista, y
si llega una foto nueva mientras esta escondida se recalcula al volver a ensenarla.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QLineEdit, QTableView, QVBoxLayout, QWidget

from .. import idiomas
from ..datos import rentabilidad as rent
from ..idiomas import t
from ..online import precios_diarios as pd
from ..registro_log import obtener
from . import widgets
from .estilo_c import TITULAR, BotonC, DesplegableC, EtiquetaC, InterruptorTexto, PanelC, px, transparente
from .panel_precios import texto_cuenta_atras, texto_fecha

log = obtener("mercado")

# Cada cuanto se repasan la cuenta atras y el boton mientras la pagina se ve.
REPINTAR_MS = 15_000
# El boton de actualizar se apaga desde un poco antes de las 00:00 UTC hasta un poco
# despues: a esa hora la foto nueva aun no existe (se prepara a partir de medianoche) y
# la descarga automatica sale sola pasados unos minutos. Pulsarlo ahi no daria nada.
APAGADO_ANTES_S = 120
APAGADO_DESPUES_S = 300
# Tras una descarga a mano, un respiro antes de dejar pedir otra.
RESPIRO_S = 30

COLUMNAS = ("nivel", "objeto", "rango", "precio", "ventas", "ventas48", "venden", "compran", "margen")
TITULOS = {
    "nivel": "Nivel", "objeto": "Objeto", "rango": "Vender a", "precio": "Precio habitual",
    "ventas": "Ventas al día", "ventas48": "Últimas 48 h", "venden": "Venden desde",
    "compran": "Compran hasta", "margen": "Margen",
}
PISTAS = {
    "nivel": "Precio habitual × rapidez de venta. S es lo mejor; D, lo que casi no compensa.",
    "objeto": "Pulsa un objeto para abrir su ficha.",
    "rango": "El rango (o la variante) al que más conviene venderlo.",
    "precio": "El precio del medio de las ventas cerradas en los últimos 30 días.",
    "ventas": "Cuántos se venden al día, contando las ventas cerradas de los últimos 30 días.",
    "ventas48": "Cuántos se han vendido al día en las últimas 48 horas.",
    "venden": "El vendedor conectado más barato cuando se guardaron los precios.",
    "compran": "El comprador conectado que más pagaba cuando se guardaron los precios.",
    "margen": "Lo que hay entre el mejor comprador y el vendedor más barato.",
}
NOMBRES_TIPO = {
    "mods": "Mods", "arcanos": "Arcanos", "sets_prime": "Sets prime", "piezas_prime": "Piezas prime",
    "reliquias": "Reliquias", "otros": "Otros",
}
TINTA_NIVEL = {"S": "acento", "A": "secundario", "B": "ok", "C": "texto", "D": "suave", "": "aviso"}
SUBTIPOS = {
    "intact": "Intacta", "exceptional": "Excepcional", "flawless": "Impecable", "radiant": "Radiante",
    "blueprint": "Plano", "crafted": "Fabricado",
}


def numero(valor: float | None) -> str:
    """Un precio sin ceros de sobra: 139, 77.5. None = "—" (sin datos, nunca un 0)."""
    if valor is None:
        return "—"
    if valor >= 100 or float(valor).is_integer():
        return f"{valor:.0f}"
    return f"{valor:.1f}"


def ritmo(valor: float | None) -> str:
    """Ventas al dia: con un decimal si son pocas."""
    if valor is None:
        return "—"
    if valor >= 10:
        return f"{valor:.0f}"
    if 0 < valor < 0.1:
        return "<0.1"
    return f"{valor:.1f}".removesuffix(".0")


def texto_rango(f: rent.Fila) -> str:
    v = f.venta
    if v.rango is not None and f.rango_max:
        return t("Rango {n}", n=v.rango)
    if v.subtipo:
        return t(SUBTIPOS[v.subtipo]) if v.subtipo in SUBTIPOS else v.subtipo.replace("_", " ").capitalize()
    return ""


def margen_de(f: rent.Fila) -> float | None:
    """Solo se ensena un margen con sentido (alguien vende mas caro de lo que otro compra)."""
    if f.tipo == "reliquias":
        # En las reliquias las ordenes a la vista no casan con las ventas cerradas (en la
        # foto real: venden desde 85 lo que se vende a 6): un margen ahi seria enganoso.
        return None
    m = f.venta.margen
    return m if m is not None and m > 0 else None


def explicacion_rango(f: rent.Fila) -> str:
    """Por que se recomienda ese rango, en una frase."""
    v, o = f.venta, f.otra
    if f.motivo_rango == "unico":
        return t("Solo hay ventas suficientes a rango {n}: no se puede comparar con otro rango.", n=v.rango)
    if f.motivo_rango == "arcano_max" and o is not None:
        return t("Al rango {n} se vende a {precio}. Para subirlo hacen falta {copias} sin rango, que sueltos "
                 "darían {suelto}: sale mejor venderlo subido.",
                 n=v.rango, precio=numero(v.precio), copias=f.copias, suelto=numero(f.copias * o.precio))
    if f.motivo_rango == "arcano_suelto" and o is not None:
        return t("Sin rango se vende a {precio} cada uno. Para subirlo al rango {n} hacen falta {copias}, que "
                 "sueltos dan {suelto}; subido solo se vende a {subido}: sale mejor venderlos sueltos.",
                 precio=numero(v.precio), n=o.rango, copias=f.copias, suelto=numero(f.copias * v.precio),
                 subido=numero(o.precio))
    if f.motivo_rango == "mod_precio" and o is not None:
        base, tope = (o, v) if (v.rango or 0) > (o.rango or 0) else (v, o)
        texto = t("Sin rango se vende a {base}; al rango {n}, a {tope}.",
                  base=numero(base.precio), n=tope.rango, tope=numero(tope.precio))
        if f.endo:
            texto += " " + t("Subirlo cuesta {endo} de endo; como el endo no tiene precio en platino, aquí solo "
                             "se comparan los precios.", endo=f"{f.endo:,}".replace(",", "."))
        else:
            texto += " " + t("No se sabe cuánto cuesta subirlo: aquí solo se comparan los precios.")
        return texto
    return ""


def pista_fila(f: rent.Fila) -> str:
    v = f.venta
    lineas = [f"<b>{f.nombre}</b>"]
    if f.pocos_datos:
        lineas.append(t("Pocos datos: solo {ventas} ventas en 30 días. No se le pone nivel.", ventas=v.ventas_30d))
    else:
        lineas.append(t("Nivel {nivel}: {puntos} puntos = precio {precio} × rapidez {rapidez}",
                        nivel=f.nivel, puntos=numero(v.puntos), precio=numero(v.precio),
                        rapidez=f"{v.rapidez:.2f}".rstrip("0").rstrip(".")))
    lineas.append(t("{ventas} ventas en 30 días ({ritmo} al día)", ventas=v.ventas_30d, ritmo=ritmo(v.ventas_dia)))
    if v.min_30d is not None and v.max_30d is not None:
        lineas.append(t("Se ha vendido entre {minimo} y {maximo} de platino", minimo=numero(v.min_30d),
                        maximo=numero(v.max_30d)))
    rango = explicacion_rango(f)
    if rango:
        lineas.append(rango)
    if f.boveda is True:
        lineas.append(t("Está en la bóveda."))
    lineas.append(f"<i>{t('Pulsa para abrir su ficha.')}</i>")
    return "<div style='white-space: normal; max-width: 420px;'>" + "<br>".join(lineas) + "</div>"


class ModeloMercado(QAbstractTableModel):
    """Las filas ya filtradas y ordenadas. Qt solo pide las que se ven."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filas: list[rent.Fila] = []
        self._columna, self._orden = 0, Qt.DescendingOrder

    # -- datos -----------------------------------------------------------------------

    def rowCount(self, padre=QModelIndex()) -> int:  # noqa: N802 - firma de Qt
        return 0 if padre.isValid() else len(self.filas)

    def columnCount(self, padre=QModelIndex()) -> int:  # noqa: N802
        return 0 if padre.isValid() else len(COLUMNAS)

    def poner(self, filas: list[rent.Fila]) -> None:
        self.beginResetModel()
        self.filas = self._ordenadas(filas)
        self.endResetModel()

    def fila(self, n: int) -> rent.Fila | None:
        return self.filas[n] if 0 <= n < len(self.filas) else None

    def texto(self, f: rent.Fila, columna: str) -> str:
        v = f.venta
        if columna == "nivel":
            return f.nivel or t("Pocos datos")
        if columna == "objeto":
            return f.nombre or f.nombre_en
        if columna == "rango":
            return texto_rango(f)
        if columna == "precio":
            return numero(v.precio)
        if columna == "ventas":
            return ritmo(v.ventas_dia)
        if columna == "ventas48":
            return ritmo(v.ventas_dia_48h)
        if columna == "venden":
            return numero(v.venta_min)
        if columna == "compran":
            return numero(v.compra_max)
        if columna == "margen":
            m = margen_de(f)
            if m is None:
                return "—"
            pct = f" ({m / v.compra_max * 100:.0f}%)" if v.compra_max else ""
            return f"{numero(m)}{pct}"
        return ""

    def data(self, indice, rol=Qt.DisplayRole):
        if not indice.isValid():
            return None
        f = self.fila(indice.row())
        if f is None:
            return None
        columna = COLUMNAS[indice.column()]
        if rol == Qt.DisplayRole:
            return self.texto(f, columna)
        if rol == Qt.TextAlignmentRole:
            if columna == "objeto":
                return int(Qt.AlignLeft | Qt.AlignVCenter)
            return int(Qt.AlignCenter)
        if rol == Qt.ForegroundRole:
            if columna == "nivel":
                return QColor(widgets.PALETA.get(TINTA_NIVEL.get(f.nivel, "texto"), widgets.PALETA["texto"]))
            if columna in ("venden", "compran", "margen", "ventas48", "rango"):
                return QColor(widgets.PALETA["suave"])
            return QColor(widgets.PALETA["texto"])
        if rol == Qt.FontRole and columna == "nivel":
            letra = QFont(TITULAR)
            letra.setPixelSize(px(17 if f.nivel else 11))
            letra.setWeight(QFont.DemiBold)
            return letra
        if rol == Qt.ToolTipRole:
            return pista_fila(f)
        return None

    def headerData(self, seccion, orientacion, rol=Qt.DisplayRole):  # noqa: N802
        if orientacion != Qt.Horizontal or not 0 <= seccion < len(COLUMNAS):
            return None
        if rol == Qt.DisplayRole:
            return t(TITULOS[COLUMNAS[seccion]]).upper()
        if rol == Qt.ToolTipRole:
            return t(PISTAS[COLUMNAS[seccion]])
        if rol == Qt.TextAlignmentRole and COLUMNAS[seccion] == "objeto":
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    # -- orden -----------------------------------------------------------------------

    @staticmethod
    def _clave(f: rent.Fila, columna: str):
        v = f.venta
        if columna == "nivel":
            return None if f.pocos_datos else v.puntos
        if columna == "objeto":
            return rent.normalizar(f.nombre or f.nombre_en)
        if columna == "rango":
            return v.rango if f.rango_max else None
        if columna == "precio":
            return v.precio
        if columna == "ventas":
            return v.ventas_dia
        if columna == "ventas48":
            return v.ventas_dia_48h
        if columna == "venden":
            return v.venta_min
        if columna == "compran":
            return v.compra_max
        return margen_de(f)

    def _ordenadas(self, filas: list[rent.Fila]) -> list[rent.Fila]:
        columna = COLUMNAS[self._columna]
        con = [(self._clave(f, columna), f) for f in filas]
        # Lo que no tiene dato en esa columna va siempre al final, se ordene como se ordene.
        tienen = [par for par in con if par[0] is not None]
        faltan = [par[1] for par in con if par[0] is None]
        tienen.sort(key=lambda par: par[0], reverse=self._orden == Qt.DescendingOrder)
        if columna == "nivel":
            faltan.sort(key=rent.orden_por_defecto)
        return [par[1] for par in tienen] + faltan

    def sort(self, columna: int, orden=Qt.AscendingOrder) -> None:
        if not 0 <= columna < len(COLUMNAS):
            return
        self._columna, self._orden = columna, orden
        self.layoutAboutToBeChanged.emit()
        self.filas = self._ordenadas(self.filas)
        self.layoutChanged.emit()


def motivo_boton_apagado(ahora: datetime, descargando: bool, ultima_manual: datetime | None = None) -> str:
    """Por que no se puede pulsar "Actualizar" ahora ("" = si se puede).

    "descargando", "medianoche" (alrededor de las 00:00 UTC, cuando la foto nueva aun no
    existe y la descarga automatica esta al caer) o "respiro" (acaba de pedirse una).
    """
    if descargando:
        return "descargando"
    ahora = ahora.astimezone(timezone.utc)
    desde_medianoche = ahora.hour * 3600 + ahora.minute * 60 + ahora.second
    if desde_medianoche < APAGADO_DESPUES_S or 86400 - desde_medianoche <= APAGADO_ANTES_S:
        return "medianoche"
    if ultima_manual is not None and 0 <= (ahora - ultima_manual).total_seconds() < RESPIRO_S:
        return "respiro"
    return ""


class PestanaMercado(QWidget):
    abrir_item = Signal(int)       # clic en un objeto que esta en el indice
    buscar_texto = Signal(str)     # clic en uno que no: se busca por su nombre
    _calculado = Signal(int, object)

    def __init__(self, precios: pd.PreciosDiarios | None = None, reloj=pd.ahora_utc,
                 ruta_indice: Path | None = None, parent=None):
        super().__init__(parent)
        transparente(self)
        self._precios = precios
        self._reloj = reloj
        self._ruta_indice = ruta_indice
        self._filas: list[rent.Fila] = []
        self._generacion = 0
        self._calculando = False
        self._sucio = True              # hay que (re)calcular cuando se vea
        self._tarea: pd.Tarea | None = None
        self._ultima_manual: datetime | None = None
        self.ultimo_calculo_s: float | None = None

        # -- cabecera: de cuando son los precios, cuenta atras y boton ----------------
        self.titulo = EtiquetaC("", "seccion", mayus=True)
        self.fecha = EtiquetaC("", "pequeno", recortar=True)
        self.cuenta = EtiquetaC("", "pequeno", tinta="tenue", recortar=True)
        self.estado = EtiquetaC("", "pequeno", tinta="aviso", recortar=True)
        for etiqueta in (self.fecha, self.cuenta, self.estado):
            etiqueta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.boton = BotonC("", tam=11)
        self.boton.clicked.connect(self.actualizar_ahora)
        columna_fecha = QVBoxLayout()
        columna_fecha.setSpacing(1)
        columna_fecha.addWidget(self.fecha)
        columna_fecha.addWidget(self.cuenta)
        cabecera = QHBoxLayout()
        cabecera.setSpacing(px(12, False))
        cabecera.addWidget(self.titulo)
        cabecera.addLayout(columna_fecha, 1)
        cabecera.addWidget(self.boton)

        # -- filtros ----------------------------------------------------------------------
        self.caja = QLineEdit()
        self.caja.setClearButtonEnabled(True)
        self.caja.setMinimumWidth(px(150, False))
        self.caja.textChanged.connect(self._filtrar)
        self.tipo = DesplegableC()
        self.boveda = DesplegableC()
        self.tipo.currentIndexChanged.connect(self._filtrar)
        self.boveda.currentIndexChanged.connect(self._filtrar)
        self.con_pocos = InterruptorTexto("", True)
        self.con_pocos.toggled.connect(self._filtrar)
        self.cuantos = EtiquetaC("", "pequeno", tinta="tenue")
        filtros = QHBoxLayout()
        filtros.setSpacing(px(10, False))
        filtros.addWidget(self.caja, 1)
        filtros.addWidget(self.tipo)
        filtros.addWidget(self.boveda)
        pie_filtros = QHBoxLayout()
        pie_filtros.setSpacing(px(10, False))
        pie_filtros.addWidget(self.con_pocos)
        pie_filtros.addStretch(1)
        pie_filtros.addWidget(self.estado, 4)
        pie_filtros.addWidget(self.cuantos)

        # -- la formula, a la vista -------------------------------------------------------
        self.nota = EtiquetaC("", "pequeno", envolver=True)
        self.leyenda = EtiquetaC("", "pequeno", envolver=True)

        # -- tabla ------------------------------------------------------------------------
        self.modelo = ModeloMercado(self)
        self.tabla = QTableView()
        self.tabla.setModel(self.modelo)
        self.tabla.setSelectionMode(QAbstractItemView.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setShowGrid(False)
        self.tabla.setWordWrap(False)
        self.tabla.setMouseTracking(True)
        self.tabla.setFocusPolicy(Qt.NoFocus)
        self.tabla.setCursor(Qt.PointingHandCursor)
        self.tabla.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tabla.verticalHeader().hide()
        self.tabla.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        cab = self.tabla.horizontalHeader()
        cab.setHighlightSections(False)
        cab.setSectionsClickable(True)
        cab.setSortIndicatorShown(True)
        cab.setSortIndicator(0, Qt.DescendingOrder)
        cab.sortIndicatorChanged.connect(self.modelo.sort)
        cab.setDefaultAlignment(Qt.AlignCenter)
        cab.setSectionResizeMode(QHeaderView.Fixed)
        cab.setSectionResizeMode(COLUMNAS.index("objeto"), QHeaderView.Stretch)
        cab.setMinimumSectionSize(px(40, False))
        self.tabla.clicked.connect(self._pulsada)
        self.tabla.installEventFilter(self)
        self.vacio = EtiquetaC("", "normal", tinta="suave", envolver=True)
        self.vacio.setAlignment(Qt.AlignCenter)

        self.panel = PanelC(None)
        self.panel.capa.addLayout(cabecera)
        self.panel.capa.addWidget(self.nota)
        self.panel.capa.addWidget(self.leyenda)
        self.panel.capa.addLayout(filtros)
        self.panel.capa.addLayout(pie_filtros)
        self.panel.capa.addWidget(self.tabla, 1)
        self.panel.capa.addWidget(self.vacio, 1)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.addWidget(self.panel)

        self.reloj_pantalla = QTimer(self)
        self.reloj_pantalla.setInterval(REPINTAR_MS)
        self.reloj_pantalla.timeout.connect(self.refrescar_cabecera)
        self._calculado.connect(self._recibir)
        self.retraducir(recalcular=False)
        self.repintar()
        self.p.al_actualizar(self._foto_nueva)
        self.destroyed.connect(lambda *_a, p=self.p, cb=self._foto_nueva: p.quitar_observador(cb))

    # -- la foto --------------------------------------------------------------------------

    @property
    def p(self) -> pd.PreciosDiarios:
        return self._precios if self._precios is not None else pd.precios()

    def _foto_nueva(self) -> None:
        """Ha entrado una foto (la carga inicial o la descarga del dia)."""
        self._sucio = True
        if self.isVisible():
            self.recalcular()
        self.refrescar_cabecera()

    def recalcular(self) -> None:
        """Lanza la cuenta en un hilo; el resultado llega por `_calculado`."""
        self._sucio = False
        self._generacion += 1
        self._calculando = True
        generacion, fotos = self._generacion, self.p
        castellano = idiomas.es_castellano()
        ruta = self._ruta_indice
        self._pintar_vacio()

        def trabajo():
            import time

            inicio = time.perf_counter()
            try:
                filas = rent.calcular(fotos)
                con = self._abrir_indice(ruta)
                try:
                    rent.poner_nombres(filas, con, castellano)
                finally:
                    if con is not None:
                        con.close()
            except Exception:  # noqa: BLE001 - una foto rara no tumba la pagina
                log.exception("Fallo calculando la lista de rentabilidad")
                filas = []
            try:
                self._calculado.emit(generacion, (filas, time.perf_counter() - inicio))
            except RuntimeError:
                pass  # la pagina ya no existe

        threading.Thread(target=trabajo, name="mercado-calculo", daemon=True).start()

    @staticmethod
    def _abrir_indice(ruta: Path | None):
        if ruta is None:
            from ..config import RUTA_INDICE

            ruta = RUTA_INDICE
        try:
            if not Path(ruta).exists():
                return None
            return sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro", uri=True)
        except sqlite3.Error:
            return None

    def _recibir(self, generacion: int, resultado) -> None:
        if generacion != self._generacion:
            return  # ha llegado otra foto mientras tanto: este resultado ya es viejo
        self._filas, self.ultimo_calculo_s = resultado
        self._calculando = False
        self._filtrar()

    def esperar_calculo(self, segundos: float = 10.0) -> bool:
        """Para las pruebas: procesa eventos hasta que la cuenta en curso termina."""
        import time

        from PySide6.QtCore import QCoreApplication

        limite = time.monotonic() + segundos
        while self._calculando and time.monotonic() < limite:
            QCoreApplication.processEvents()
            time.sleep(0.005)
        return not self._calculando

    # -- filtros y tabla --------------------------------------------------------------------

    def _filtrar(self, *_a) -> None:
        visibles = rent.filtrar(
            self._filas, tipo=self.tipo.currentData() or "", boveda=self.boveda.currentData() or "",
            texto=self.caja.text(), con_pocos_datos=self.con_pocos.isChecked(),
        )
        self.modelo.poner(visibles)
        self.tabla.scrollToTop()
        self.cuantos.setText(t("{n} objetos", n=len(visibles)) if self._filas else "")
        self._pintar_vacio()

    def _pintar_vacio(self) -> None:
        p = self.p
        if self._calculando and not self._filas:
            texto = t("Calculando…")
        elif not p.cargado.is_set():
            texto = t("Cargando los precios guardados…")
        elif p.fecha is not None and not p.disponible:
            texto = t("Los precios diarios son de PC: en tu plataforma esta lista no está disponible.")
        elif p.fecha is None:
            texto = t("Todavía no hay precios guardados. Farmadex los baja solo; también puedes pulsar "
                      "«Actualizar precios ahora».")
        elif not self._filas:
            texto = t("Calculando…") if self._sucio else t("No hay ventas con las que calcular.")
        elif not self.modelo.filas:
            texto = t("Nada coincide con lo que has filtrado.")
        else:
            texto = ""
        self.vacio.setText(texto)
        self.vacio.setVisible(bool(texto))
        self.tabla.setVisible(not texto)

    def _pulsada(self, indice) -> None:
        f = self.modelo.fila(indice.row())
        if f is None:
            return
        if f.item_id is not None:
            self.abrir_item.emit(int(f.item_id))
        else:
            self.buscar_texto.emit(f.nombre or f.nombre_en)

    # -- cabecera: fecha, cuenta atras y boton --------------------------------------------------

    def _descargando(self) -> bool:
        if self._tarea is not None and not self._tarea.hecha.is_set():
            return True
        descargador = self.p.descargador
        return bool(descargador and descargador.estado == "descargando")

    def motivo_apagado(self) -> str:
        return motivo_boton_apagado(self._reloj(), self._descargando(), self._ultima_manual)

    def actualizar_ahora(self) -> None:
        """El boton. Vuelve a mirar el reloj: si entre el ultimo repaso y el clic han dado
        las 00:00 UTC (o ya hay una descarga en marcha), no pide nada."""
        if self.motivo_apagado():
            self.refrescar_cabecera()
            return
        self._ultima_manual = self._reloj()
        try:
            self._tarea = self.p.actualizar_ahora()
        except Exception:  # noqa: BLE001 - el boton nunca rompe la pagina
            log.exception("No se pudo pedir la descarga de precios")
            self._tarea = None
        self.refrescar_cabecera()
        QTimer.singleShot(400, self._mirar_tarea)

    def _mirar_tarea(self) -> None:
        if self._tarea is not None and not self._tarea.hecha.is_set():
            QTimer.singleShot(400, self._mirar_tarea)
            return
        self.refrescar_cabecera()
        # El respiro se acaba solo aunque nadie mueva nada.
        QTimer.singleShot(RESPIRO_S * 1000 + 200, self.refrescar_cabecera)

    def refrescar_cabecera(self) -> None:
        p = self.p
        ahora = self._reloj()
        fecha = p.fecha
        if fecha is not None:
            self.fecha.setText(t("Precios de warframe.market del {fecha}", fecha=texto_fecha(fecha)))
        elif not p.cargado.is_set():
            self.fecha.setText(t("Cargando los precios guardados…"))
        else:
            self.fecha.setText(t("Todavía no hay precios guardados."))
        self.cuenta.setText(t("Se actualizan solos en {hhmm} (a las 00:00 UTC)",
                              hhmm=texto_cuenta_atras(ahora, pd.siguiente_medianoche(ahora))))
        motivo = self.motivo_apagado()
        self.boton.setEnabled(not motivo)
        self.boton.setToolTip({
            "descargando": t("Ya se están descargando los precios."),
            "medianoche": t("Los precios nuevos se preparan a medianoche (hora UTC) y Farmadex los baja solo en "
                            "unos minutos. El botón vuelve enseguida."),
            "respiro": t("Acabas de pedirlos. Espera un momento."),
        }.get(motivo, t("Mira ahora si hay precios más nuevos.")))
        descargador = p.descargador
        estado = "descargando" if motivo == "descargando" else (descargador.estado if descargador else "")
        de_hoy = fecha is not None and fecha.astimezone(timezone.utc).date() == ahora.astimezone(timezone.utc).date()
        mensajes = {
            "descargando": t("Descargando los precios…"),
            "sin_red": t("Sin conexión: se usan los últimos precios guardados. Se volverá a intentar solo."),
            "error": t("No se pudieron descargar los precios. Se volverá a intentar más tarde."),
            "otra_plataforma": t("Los precios diarios son de PC: en tu plataforma se consultan en vivo."),
            "aun_no_hay": "" if de_hoy else t("Los precios de hoy aún se están preparando; se volverá a mirar en un rato."),
            "al_dia": t("Ya tienes los precios de hoy."),
            "nuevo": t("Ya tienes los precios de hoy."),
        }
        texto = mensajes.get(estado, "")
        if motivo == "medianoche" and estado != "descargando":
            texto = t("Los precios nuevos llegan solos en unos minutos.")
        self.estado.setText(texto)
        self.estado.poner_tinta("suave" if estado in ("al_dia", "nuevo", "descargando") or motivo == "medianoche"
                                else "aviso")
        self.estado.setVisible(bool(texto))

    # -- textos y aspecto --------------------------------------------------------------------------

    def retraducir(self, recalcular: bool = True) -> None:
        self.titulo.setText(t("Qué vender"))
        self.boton.setText(t("Actualizar precios ahora"))
        self.caja.setPlaceholderText(t("Buscar por nombre"))
        for desplegable, opciones in (
            (self.tipo, [("", t("Todos los tipos"))] + [(c, t(NOMBRES_TIPO[c])) for c in rent.TIPOS]),
            (self.boveda, [("", t("Bóveda: todo")), ("si", t("En la bóveda")), ("no", t("Fuera de la bóveda"))]),
        ):
            elegido = desplegable.currentData()
            desplegable.blockSignals(True)
            desplegable.clear()
            for clave, texto in opciones:
                desplegable.addItem(texto, clave)
            desplegable.setCurrentIndex(max(0, desplegable.findData(elegido)))
            desplegable.blockSignals(False)
        self.boveda.setToolTip(t("La bóveda solo se sabe en reliquias y en objetos prime."))
        self.con_pocos.setText(t("Enseñar los de pocos datos"))
        self.con_pocos.setToolTip(t("Con menos de {ventas} ventas en 30 días, o ventas en menos de {dias} días, "
                                    "no se pone nivel: no hay bastante para fiarse.",
                                    ventas=rent.MIN_VENTAS, dias=rent.MIN_DIAS))
        self.nota.setText(t(
            "Nivel según las ventas reales de 30 días: <b>puntos = precio habitual × rapidez</b> "
            "(rapidez de 0 a 1; 1 = se venden {tope} o más al día). Con pocas ventas no se pone nivel.",
            tope=int(rent.VENTAS_DIA_TOPE)))
        umbral = dict(rent.UMBRALES)
        colores = {n: widgets.PALETA.get(TINTA_NIVEL[n], widgets.PALETA["texto"]) for n in rent.NIVELES}
        trozos = [
            f"<span style='color:{colores[n]}'><b>{n}</b></span> "
            + (t("{puntos} puntos o más", puntos=int(umbral[n])) if n in umbral else t("menos"))
            for n in rent.NIVELES
        ]
        self.leyenda.setText(" · ".join(trozo.replace(" ", "&nbsp;") .replace("<span&nbsp;style", "<span style")
                                        for trozo in trozos))
        pista = t(
            "Cómo se calcula:\n"
            "· Precio habitual: el precio del medio de las ventas cerradas en 30 días.\n"
            "· Rapidez: ventas al día ÷ {tope}, con tope en 1.\n"
            "· Puntos = precio habitual × rapidez.\n"
            "· Arcanos: se compara venderlo subido con vender sueltas las copias que cuesta subirlo.\n"
            "· Mods: subirlos cuesta endo, que no tiene precio en platino; solo se comparan los precios.\n"
            "· Sin ventas no aparece; con pocas, aparece sin nivel.", tope=int(rent.VENTAS_DIA_TOPE))
        self.nota.setToolTip(pista)
        self.leyenda.setToolTip(pista)
        self.modelo.headerDataChanged.emit(Qt.Horizontal, 0, len(COLUMNAS) - 1)
        self.refrescar_cabecera()
        if recalcular and self._filas:
            # Los nombres van en el idioma del jugador: hay que volver a ponerlos.
            if self.isVisible():
                self.recalcular()
            else:
                self._sucio = True
        self._pintar_vacio()

    def repintar(self) -> None:
        """Tema o escala nuevos: hoja de la tabla y medidas de las columnas."""
        p = widgets.PALETA
        self.tabla.setStyleSheet(
            f"QTableView {{ background: transparent; border: none; color: {p['texto']};"
            f" font-size: {px(13)}px; outline: none; }}"
            f"QTableView::item {{ border-bottom: 1px solid {p['borde']}; padding: 0 {px(6, False)}px; }}"
            f"QTableView::item:hover {{ background: {p.get('panel2', p['panel'])}; }}"
            f"QHeaderView {{ background: transparent; }}"
            f"QHeaderView::section {{ background: transparent; color: {p['acento']}; border: none;"
            f" border-bottom: 1px solid {p.get('acento_tenue', p['borde'])}; padding: {px(5, False)}px {px(4, False)}px;"
            f" font-family: '{TITULAR}'; font-size: {px(11)}px; font-weight: 600; }}"
            f"QTableCornerButton::section {{ background: transparent; border: none; }}"
        )
        self.tabla.verticalHeader().setDefaultSectionSize(px(30))
        anchos = {"nivel": 92, "rango": 96, "precio": 118, "ventas": 108, "ventas48": 104, "venden": 108,
                  "compran": 116, "margen": 104}
        for columna, ancho in anchos.items():
            self.tabla.setColumnWidth(COLUMNAS.index(columna), px(ancho))
        self._ajustar_columnas()
        self.retraducir(recalcular=False)

    def _ajustar_columnas(self, ancho: int | None = None) -> None:
        """En ventanas estrechas se esconden las columnas menos importantes, por orden."""
        if ancho is None:
            ancho = self.tabla.width()
        ancho -= px(14, False)  # la barra de desplazamiento
        necesarias = px(92 + 96 + 118 + 108) + px(190, False)
        sobrantes = {"ventas48": px(104), "venden": px(108), "compran": px(116), "margen": px(104)}
        libre = ancho - necesarias
        for columna in ("ventas48", "venden", "compran", "margen"):
            cabe = libre >= sobrantes[columna]
            if cabe:
                libre -= sobrantes[columna]
            self.tabla.setColumnHidden(COLUMNAS.index(columna), not cabe)

    def eventFilter(self, objeto, evento):  # noqa: N802 - firma de Qt
        if objeto is self.tabla and evento.type() == QEvent.Resize:
            self._ajustar_columnas(evento.size().width())
        return super().eventFilter(objeto, evento)

    def showEvent(self, evento):  # noqa: N802
        super().showEvent(evento)
        self.reloj_pantalla.start()
        self.refrescar_cabecera()
        if self._sucio and self.p.disponible:
            self.recalcular()
        else:
            self._pintar_vacio()

    def hideEvent(self, evento):  # noqa: N802
        super().hideEvent(evento)
        self.reloj_pantalla.stop()
