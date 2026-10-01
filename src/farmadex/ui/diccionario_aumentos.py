"""Diccionario de aumentos: todos los mods de aumento de warframes y de armas, con su
nombre en el idioma del juego y en ingles, de quien son y en que sindicato se compran,
a que rango y por cuanto (datos/aumentos.py: todo sale del indice).

Arriba, un buscador que encuentra por el nombre en cualquier idioma, por el warframe o
el arma y por el sindicato. Al elegir una fila, el panel de abajo ensena el nombre en
todos los idiomas, cada sindicato que lo vende y, si el perfil leido trae tu rango en
ese sindicato, si ya puedes comprarlo. Lo que no se sabe se dice: "no se sabe".
"""

from __future__ import annotations

import re
import unicodedata

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHeaderView, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ..datos import aumentos, nombres_juego
from ..idiomas import t
from .estilo_c import BotonC, DesplegableC, EtiquetaC, PanelC, columna, fila, hex_de, px, transparente

COL_NOMBRE, COL_INGLES, COL_PARA, COL_SINDICATO, COL_RANGO, COL_COSTE, COL_PUEDES = range(7)
FILTROS = (("todos", "Todos"), ("warframe", "De warframe"), ("arma", "De arma"))


def _plano(texto: str) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin.lower()).strip()


class DiccionarioAumentos(QWidget):
    abrir_item = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.con = None
        self.rangos: dict[str, tuple[int, int]] = {}
        self._filas: list[tuple[aumentos.Aumento, str]] = []  # (aumento, texto para buscar)
        self._visibles: list[aumentos.Aumento] = []
        self._cargado = False

        self.buscador = QLineEdit()
        self.buscador.setClearButtonEnabled(True)
        self.buscador.textChanged.connect(self._filtrar)
        self.filtro = DesplegableC()
        self.filtro.currentIndexChanged.connect(self._filtrar)
        self.cuenta = EtiquetaC("", "pequeno")
        self.tabla = QTableWidget(0, 7)
        self.tabla.verticalHeader().hide()
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.setShowGrid(False)
        self.tabla.setWordWrap(False)
        self.tabla.setMinimumHeight(px(260, False))
        cabecera = self.tabla.horizontalHeader()
        cabecera.setHighlightSections(False)
        cabecera.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for col in range(7):
            cabecera.setSectionResizeMode(col, QHeaderView.Stretch if col in (COL_NOMBRE, COL_INGLES, COL_SINDICATO)
                                          else QHeaderView.ResizeToContents)
        self.tabla.itemSelectionChanged.connect(self._elegida)
        self.tabla.cellDoubleClicked.connect(lambda fila_i, _c: self._abrir(fila_i))

        self.panel_detalle = PanelC("", remate=False)
        self.detalle_titulo = EtiquetaC("", "titulo", envolver=True)
        self.detalle_para = EtiquetaC("", "normal", envolver=True)
        self.detalle_nombres = EtiquetaC("", "pequeno", envolver=True)
        self.capa_ventas = columna(espacio=px(4, False))
        self.boton_ficha = BotonC(icono="derecha", tam=11)
        self.boton_ficha.clicked.connect(lambda: self._abrir(self.tabla.currentRow()))
        for w in (self.detalle_titulo, self.detalle_para, self.detalle_nombres):
            self.panel_detalle.capa.addWidget(w)
        self.panel_detalle.capa.addLayout(self.capa_ventas)
        self.panel_detalle.capa.addLayout(fila(None, self.boton_ficha))
        self.panel_detalle.hide()
        self.nota = EtiquetaC("", "pequeno", envolver=True)

        self.panel = PanelC("")
        arriba = fila(espacio=px(8, False))
        arriba.addWidget(self.buscador, 1)
        arriba.addWidget(self.filtro)
        self.panel.capa.addLayout(arriba)
        self.panel.capa.addWidget(self.cuenta)
        self.panel.capa.addWidget(self.tabla, 1)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, px(4, False), px(4, False), 0)
        capa.setSpacing(px(12, False))
        capa.addWidget(self.panel, 1)
        capa.addWidget(self.panel_detalle)
        capa.addWidget(self.nota)
        self.retraducir()

    # -- datos ---------------------------------------------------------------------------

    def conectar_indice(self, con) -> None:
        self.con = con
        self._cargado = False
        if self.isVisible():
            self.cargar()

    def showEvent(self, evento):  # noqa: N802
        super().showEvent(evento)
        self.cargar()

    def cargar(self, forzar: bool = False) -> None:
        """Lee los aumentos del indice y el rango del perfil (la primera vez que se ve)."""
        if self.con is None or (self._cargado and not forzar):
            return
        self._cargado = True
        try:
            lista = aumentos.cargar(self.con)
        except Exception:  # noqa: BLE001 - un indice raro no tumba la pestana
            lista = []
        self.rangos = aumentos.rangos_del_perfil()
        self._filas = []
        for a in lista:
            partes = list(nombres_juego.nombres(self.con, a.item_id).values()) + [a.nombre_en, a.para]
            partes += list(nombres_juego.nombres(self.con, a.para_id).values())
            for v in a.ventas:
                partes += [v.sindicato, aumentos.NOMBRE_ES.get(v.sindicato, ""), v.titulo]
            self._filas.append((a, _plano(" | ".join(p for p in partes if p))))
        self._filtrar()

    def refrescar_perfil(self) -> None:
        """Tras leer el perfil: vuelve a mirar los rangos."""
        if self._cargado:
            self.cargar(forzar=True)

    # -- textos --------------------------------------------------------------------------

    def retraducir(self) -> None:
        self.panel.poner_titulo(t("Diccionario de aumentos"))
        self.buscador.setPlaceholderText(t("Buscar un aumento, un warframe, un arma o un sindicato…"))
        self.buscador.setStyleSheet(
            f"QLineEdit {{ background: {hex_de('panel2')}; color: {hex_de('texto')}; border: none;"
            f" border-bottom: 1px solid {hex_de('acento')}; padding: {px(6, False)}px {px(8, False)}px;"
            f" font-size: {px(13)}px; }}")
        self.tabla.setStyleSheet(
            f"QTableWidget {{ background: transparent; color: {hex_de('texto')}; border: none;"
            f" font-size: {px(12)}px; selection-background-color: {hex_de('panel2')};"
            f" selection-color: {hex_de('acento')}; }}"
            f"QHeaderView::section {{ background: transparent; color: {hex_de('suave')}; border: none;"
            f" border-bottom: 1px solid {hex_de('borde')}; padding: {px(4, False)}px; font-size: {px(11)}px; }}")
        elegido = self.filtro.currentData()
        self.filtro.blockSignals(True)
        self.filtro.clear()
        for clave, texto in FILTROS:
            self.filtro.addItem(t(texto), clave)
        self.filtro.setCurrentIndex(max(0, self.filtro.findData(elegido)))
        self.filtro.blockSignals(False)
        self.tabla.setHorizontalHeaderLabels([
            t("Aumento"), t("En inglés"), t("Para"), t("Sindicato"), t("Rango"), t("Coste"), t("¿Puedes?")])
        self.boton_ficha.setText(t("Abrir ficha"))
        self.nota.setText(t(
            "El sindicato, el rango y el coste salen de los datos del juego. \"¿Puedes?\" solo se rellena si "
            "has leído tu perfil y trae tu rango en ese sindicato; si no, queda en blanco porque no se sabe. "
            "Además del rango necesitas tener esa reputación para gastar."))
        if self._cargado:
            self._filtrar()

    def repintar(self) -> None:
        self.retraducir()

    # -- la tabla ------------------------------------------------------------------------

    def _filtrar(self) -> None:
        palabras = _plano(self.buscador.text()).split()
        clase = self.filtro.currentData() or "todos"
        self._visibles = [a for a, texto in self._filas
                          if (clase == "todos" or a.clase == clase) and all(p in texto for p in palabras)]
        self.tabla.setUpdatesEnabled(False)
        self.tabla.clearSelection()
        self.tabla.setRowCount(len(self._visibles))
        for fila_i, a in enumerate(self._visibles):
            celdas = self.celdas(a)
            for col, texto in enumerate(celdas):
                celda = QTableWidgetItem(texto)
                celda.setToolTip(texto)
                self.tabla.setItem(fila_i, col, celda)
        self.tabla.setUpdatesEnabled(True)
        self.cuenta.setText(t("{n} aumentos", n=len(self._visibles)) if self._filas else
                            t("Faltan los datos de los mods: actualiza los datos del juego en Ajustes > Datos."))
        self.panel_detalle.hide()

    def celdas(self, a: aumentos.Aumento) -> list[str]:
        """Los siete textos de la fila de un aumento."""
        nombre = nombres_juego.nombre(self.con, a.item_id, a.nombre_en)
        para = nombres_juego.nombre(self.con, a.para_id, a.para)
        if not a.ventas:
            return [nombre, a.nombre_en, para, t("ninguno lo vende"), "", "", ""]
        sindicatos = " / ".join(aumentos.nombre_sindicato(v.sindicato) for v in a.ventas)
        rangos = " / ".join(str(v.rango) if v.rango is not None else t("no se sabe") for v in a.ventas)
        costes = " / ".join(f"{v.coste:,}".replace(",", ".") if v.coste is not None else t("no se sabe")
                            for v in a.ventas)
        estados = [aumentos.puede_comprar(v, self.rangos) for v in a.ventas]
        if any(e is True for e in estados):
            puedes = t("Sí")
        elif any(e is False for e in estados) and all(e is not None for e in estados):
            puedes = t("Todavía no")
        else:
            puedes = ""
        return [nombre, a.nombre_en, para, sindicatos, rangos, costes, puedes]

    def _elegida(self) -> None:
        fila_i = self.tabla.currentRow()
        if not (0 <= fila_i < len(self._visibles)) or not self.tabla.selectedItems():
            self.panel_detalle.hide()
            return
        a = self._visibles[fila_i]
        self.detalle_titulo.setText(nombres_juego.nombre(self.con, a.item_id, a.nombre_en))
        para = nombres_juego.nombre(self.con, a.para_id, a.para)
        self.detalle_para.setText(t("Aumento de {equipo}", equipo=para))
        todos = nombres_juego.nombres(self.con, a.item_id)
        self.detalle_nombres.setText("   ·   ".join(
            f"{nombres_juego.NOMBRE_IDIOMA[c]}: {n}" for c, n in todos.items()))
        while self.capa_ventas.count():
            hijo = self.capa_ventas.takeAt(0)
            if hijo.widget() is not None:
                hijo.widget().deleteLater()
        for texto, tinta in aumentos.lineas(self.con, a.item_id, self.rangos)[1:]:
            self.capa_ventas.addWidget(EtiquetaC(texto, "normal", tinta=tinta or None, envolver=True))
        if a.ventas and not self.rangos:
            self.capa_ventas.addWidget(EtiquetaC(
                t("No se sabe tu rango en los sindicatos: lee tu perfil (pestaña Perfil) para saber si puedes "
                  "comprarlo."), "pequeno", envolver=True))
        self.panel_detalle.show()

    def _abrir(self, fila_i: int) -> None:
        if 0 <= fila_i < len(self._visibles):
            self.abrir_item.emit(int(self._visibles[fila_i].item_id))

    # -- para las pruebas ----------------------------------------------------------------

    def buscar(self, texto: str) -> list[aumentos.Aumento]:
        self.buscador.setText(texto)
        return list(self._visibles)

    def elegir_fila(self, fila_i: int) -> None:
        self.tabla.selectRow(fila_i)

    def textos_detalle(self) -> list[str]:
        salida = [self.detalle_titulo.text(), self.detalle_para.text(), self.detalle_nombres.text()]
        for i in range(self.capa_ventas.count()):
            w = self.capa_ventas.itemAt(i).widget()
            if w is not None:
                salida.append(w.text())
        return salida
