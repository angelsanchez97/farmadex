"""Pestana Objetivos: lo que estas farmeando y por donde conseguirlo."""

from __future__ import annotations

import html
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..datos import indice as indice_datos
from ..estado import objetivos as estado_objetivos
from ..estado import usuario_db
from ..idiomas import es_castellano, nombre as nombre_idioma, t
from .widgets import COLOR_BOVEDA, COLOR_DISPONIBLE, PALETA, Tarjeta


class FilaObjetivo(Tarjeta):
    cambiada = Signal()
    abrir_item = Signal(str)

    def __init__(self, objetivo, ruta, usuario, parent=None):
        color = (
            COLOR_DISPONIBLE if objetivo.completado
            else COLOR_BOVEDA if ruta and ruta["solo_en_boveda"]
            else PALETA["acento"] if ruta
            else PALETA["borde"]
        )
        super().__init__(color, parent)
        self.objetivo = objetivo
        self.usuario = usuario
        p = PALETA

        titulo = QLabel(
            f"<span style='font-size:16px;font-weight:bold'>{html.escape(objetivo.nombre)}</span>"
            + (f"  <span style='color:{COLOR_DISPONIBLE};font-size:12px'>{t('Completado').upper()}</span>"
               if objetivo.completado else "")
        )
        titulo.setTextFormat(Qt.RichText)

        barra = QProgressBar()
        barra.setRange(0, max(1, objetivo.objetivo))
        barra.setValue(objetivo.actual)
        barra.setFormat(t("{actual} de {total}", actual=objetivo.actual, total=objetivo.objetivo))
        barra.setFixedWidth(170)

        menos = QPushButton("-")
        mas = QPushButton("+")
        quitar = QPushButton(t("Quitar"))
        for boton in (menos, mas):
            boton.setFixedWidth(34)
            boton.setStyleSheet("font-size: 18px; font-weight: bold; padding: 2px 0;")
        menos.clicked.connect(lambda: self._sumar(-1))
        mas.clicked.connect(lambda: self._sumar(1))
        quitar.clicked.connect(self._borrar)
        quitar.setStyleSheet(f"color: {p['suave']};")

        arriba = QHBoxLayout()
        arriba.setSpacing(6)
        arriba.addWidget(titulo, 1)
        arriba.addWidget(barra)
        arriba.addWidget(menos)
        arriba.addWidget(mas)
        arriba.addSpacing(6)
        arriba.addWidget(quitar)

        self.donde = QLabel(self._texto_ruta(ruta))
        self.donde.setTextFormat(Qt.RichText)
        self.donde.setWordWrap(True)
        self.donde.setStyleSheet(f"color: {p['suave']};")

        self.caja.addLayout(arriba)
        self.caja.addWidget(self.donde)

    def _texto_ruta(self, ruta) -> str:
        p = PALETA
        if not ruta:
            return t("Sin ruta conocida: puede venir de una mision de historia o del mercado.")
        reliquia = ruta["reliquia"]
        if ruta.get("tipo") != "reliquia" or not reliquia:
            # No sale de reliquias (Rhino cae del Chacal en Fossa): el sitio, tal cual.
            mision = ruta["mision"]
            if not mision:
                return t("Sin ruta conocida: puede venir de una mision de historia o del mercado.")
            trozos = [f"<b>{html.escape(mision.get('donde') or '')}</b>"]
            if mision.get("mision"):
                trozos.append(html.escape(mision["mision"]))
            if mision.get("rotacion"):
                trozos.append(t("rotacion {rot}", rot=mision["rotacion"]))
            if ruta.get("probabilidad"):
                trozos.append(f"{ruta['probabilidad']:.1f}%")
            return f"<span style='color:{p['texto']}'>{' &middot; '.join(trozos)}</span>"
        nombre = html.escape(nombre_idioma(reliquia))
        prob = reliquia["probabilidades"].get("Radiant") or 0
        radiante = t("{prob}% en Radiante", prob=f"{prob:.1f}")
        if ruta["solo_en_boveda"]:
            return (
                f"<span style='color:{COLOR_BOVEDA}'>{t('Solo en boveda')}</span> &middot; "
                f"<span style='color:{p['texto']}'>{nombre}</span> ({radiante}). "
                + t("Hay que comprarla a otro jugador.")
            )
        mision = ruta["mision"]
        detalle = f"{html.escape(mision['donde'])}" if mision else t("sin mision conocida")
        if mision and mision["mision"]:
            detalle += f" &middot; {html.escape(mision['mision'])}"
        if mision and mision["rotacion"]:
            detalle += " &middot; " + t("rotacion {rot}", rot=mision["rotacion"])
        return (
            f"<span style='color:{p['texto']}'><b>{nombre}</b></span> ({radiante}) "
            f"&middot; {t('farmeala en')} <span style='color:{p['texto']}'>{detalle}</span>"
        )

    def _sumar(self, cantidad: int) -> None:
        estado_objetivos.sumar(self.usuario, self.objetivo.id, cantidad)
        self.cambiada.emit()

    def _borrar(self) -> None:
        estado_objetivos.borrar(self.usuario, self.objetivo.id)
        self.cambiada.emit()


class PestanaObjetivos(QWidget):
    # Se emite cada vez que la lista cambia (anadir, sumar, borrar): Mundo la usa.
    cambiados = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.usuario: sqlite3.Connection = usuario_db.conectar()
        self.indice: sqlite3.Connection | None = None

        self.resumen = QLabel("")
        self.resumen.setStyleSheet(f"color: {PALETA['suave']};")
        self.contenido = QWidget()
        self.caja_filas = QVBoxLayout(self.contenido)
        self.caja_filas.setContentsMargins(0, 0, 4, 0)
        self.caja_filas.setSpacing(8)
        self.caja_filas.addStretch(1)

        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(self.contenido)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 8, 4, 4)
        caja.setSpacing(8)
        caja.addWidget(self.resumen)
        caja.addWidget(desplazable, 1)

    def conectar_indice(self, con: sqlite3.Connection) -> None:
        self.indice = con
        self.refrescar()

    def retraducir(self) -> None:
        """Las filas se generan enteras en cada refresco, asi que basta con repintar."""
        self.refrescar()

    # -- alta desde la ficha --------------------------------------------------

    def anadir_item(self, item_id: int, set_completo: bool = False) -> int:
        if self.indice is None:
            self.indice = indice_datos.conectar()
        if set_completo:
            creados = len(estado_objetivos.anadir_set(self.usuario, self.indice, item_id))
        else:
            fila = self.indice.execute(
                "SELECT unique_name, nombre_en, nombre_es, item_count FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not fila:
                return 0
            # El objetivo guarda el nombre con el que se creo, en el idioma de ese momento.
            nombre = (fila[2] or fila[1]) if es_castellano() else (fila[1] or fila[2])
            estado_objetivos.anadir(self.usuario, fila[0], nombre, fila[3] or 1)
            creados = 1
        self.refrescar()
        return creados

    def sumar_por_item(self, unique_name: str, cantidad: int = 1) -> bool:
        objetivo = estado_objetivos.sumar_por_item(self.usuario, unique_name, cantidad)
        if objetivo:
            self.refrescar()
        return objetivo is not None

    # -- pintado ---------------------------------------------------------------

    def refrescar(self) -> None:
        # Tambien se llama al cambiar de tema: el resumen lleva el color en su hoja.
        self.resumen.setStyleSheet(f"color: {PALETA['suave']};")
        if self.indice is not None:
            try:
                self.indice.execute("SELECT 1")
            except sqlite3.Error:
                self.indice = None  # el indice se esta reconstruyendo
        while self.caja_filas.count() > 1:
            elemento = self.caja_filas.takeAt(0)
            if elemento.widget():
                elemento.widget().deleteLater()

        lista = estado_objetivos.listar(self.usuario)
        if not lista:
            self.resumen.setText(t("Todavia no tienes objetivos. Busca algo y pulsa '+ Objetivo'."))
            return
        pendientes = [o for o in lista if not o.completado]
        self.resumen.setText(
            t("{n} por conseguir", n=f"<b style='color:{PALETA['texto']}'>{len(pendientes)}</b>")
            + " &middot; " + t("{n} completados", n=len(lista) - len(pendientes))
        )
        for objetivo in lista:
            ruta = (
                estado_objetivos.ruta_de(self.indice, objetivo.unique_name)
                if self.indice is not None
                else None
            )
            fila = FilaObjetivo(objetivo, ruta, self.usuario)
            fila.cambiada.connect(self.refrescar)
            self.caja_filas.insertWidget(self.caja_filas.count() - 1, fila)
        self.cambiados.emit()

    def eras_necesarias(self) -> dict[str, list[str]]:
        if self.indice is None:
            return {}
        return estado_objetivos.eras_necesarias(self.indice, self.usuario)
