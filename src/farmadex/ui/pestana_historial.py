"""MIS METAS > Historial: las reliquias que has abierto, tu suerte y lo que llevas ganado.

Lee lo que guarda `estado/aperturas.py` (usuario.sqlite). Nada de aqui pide nada a
la red salvo el boton "Actualizar precios", que lo hace en su propio hilo, al
ritmo del limitador compartido de warframe.market y solo para lo que te has
llevado y no tiene precio reciente.

Reglas de lo que se ensena:
- Lo que no se sabe se dice: "sin confirmar", "reliquia desconocida", "sin precio".
- El platino siempre va como estimado y con la fecha del precio mas viejo usado.
- La suerte solo se juzga con muestra suficiente; si no, se dice que son pocas.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from ..datos import vender_fundir
from ..estado import aperturas as datos_aperturas
from ..estado import usuario_db
from ..idiomas import nombre as nombre_idioma, t
from ..registro_log import obtener
from .estilo_c import BotonC, DesplegableC, EtiquetaC, InterruptorTexto, PanelC, fila, px, transparente

log = obtener("pestana_historial")

# Cuantas aperturas se pintan como filas (las estadisticas usan todas).
FILAS_VISIBLES = 60
# Cuantas piezas de tus metas se ensenan en "lo que te falta".
FALTAN_VISIBLES = 8
# Cuantos precios pide como mucho "Actualizar precios" de una vez (a 2 por segundo).
MAXIMO_PRECIOS = 40

NOMBRES_RAREZA = {"Common": "Común", "Uncommon": "Poco común", "Rare": "Rara"}
NOMBRES_REFINAMIENTO = {"Intact": "Intacta", "Exceptional": "Excepcional", "Flawless": "Impecable",
                        "Radiant": "Radiante"}
TINTA_CONSEJO = {"falta": "secundario", "vender": "acento", "fundir": "aviso", "igual": "suave"}


def nombre_pieza(indice: sqlite3.Connection | None, unique_name: str, respaldo: str = "") -> str:
    """'Sistemas de Banshee Prime' en el idioma de la interfaz; lo guardado si no hay indice."""
    if indice is None or not unique_name:
        return respaldo or unique_name
    try:
        f = indice.execute(
            "SELECT i.nombre_en, i.nombre_es, p.nombre_en, p.nombre_es FROM items i "
            "LEFT JOIN items p ON p.id = i.padre_id WHERE i.unique_name = ?", (unique_name,),
        ).fetchone()
    except sqlite3.Error:
        f = None
    if not f:
        return respaldo or unique_name
    nombre = nombre_idioma({"nombre_en": f[0], "nombre_es": f[1]})
    padre = nombre_idioma({"nombre_en": f[2], "nombre_es": f[3]}) if (f[2] or f[3]) else ""
    if padre and not nombre.startswith(padre):
        return t("{nombre} de {padre}", nombre=nombre, padre=padre)
    return nombre or respaldo or unique_name


def _hora(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except ValueError:
        return iso


class _ActualizadorPrecios(QThread):
    """Pide en segundo plano los precios que faltan y los deja en precios_vistos."""

    hecho = Signal(int)

    def __init__(self, piezas: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.piezas = piezas  # [(unique_name, slug)]

    def run(self) -> None:  # noqa: D102
        guardados = 0
        try:
            from ..online.market import compartido

            market = compartido()
            filas = []
            for unico, slug in self.piezas:
                precios = market.precios(slug)
                if precios is None or getattr(precios, "error", "") or not precios.ventas:
                    continue
                filas.append((unico, slug, precios.mejor_venta, len(precios.ventas), len(precios.compras)))
            if filas:
                con = usuario_db.conectar()
                try:
                    datos_aperturas.guardar_precios(con, filas)
                finally:
                    con.close()
                guardados = len(filas)
        except Exception:  # noqa: BLE001 - sin red no hay precios, y ya esta
            log.exception("No se pudieron actualizar los precios del historial")
        self.hecho.emit(guardados)


class PestanaHistorial(QWidget):
    """Historial de aperturas de reliquias (sub-pestana de MIS METAS)."""

    activo_cambiado = Signal(bool)

    def __init__(self, usuario: sqlite3.Connection | None = None, config: dict | None = None, parent=None):
        super().__init__(parent)
        transparente(self)
        self.usuario = usuario if usuario is not None else usuario_db.conectar()
        datos_aperturas.preparar(self.usuario)
        self.config = config if config is not None else {}
        self.indice: sqlite3.Connection | None = None
        self._sucio = True
        self._actualizador: _ActualizadorPrecios | None = None

        # -- cabecera (a la derecha de las sub-pestanas si la pagina va en MIS METAS)
        self.guardar = InterruptorTexto("", bool(self.config.get("historial_aperturas", True)))
        self.guardar.toggled.connect(self._cambiar_activo)
        self.boton_precios = BotonC("", icono=None)
        self.boton_precios.clicked.connect(self.actualizar_precios)
        self.controles_cabecera = transparente(QWidget(self))
        self.controles_cabecera.setLayout(fila(self.guardar, px(8, False), self.boton_precios, espacio=px(8, False)))

        self.estado = EtiquetaC("", "pequeno", envolver=True)
        self.contenido = transparente(QWidget())
        self.capa_contenido = QVBoxLayout(self.contenido)
        self.capa_contenido.setContentsMargins(0, 0, px(6, False), px(6, False))
        self.capa_contenido.setSpacing(px(12, False))
        self.desplazable = QScrollArea()
        self.desplazable.setWidgetResizable(True)
        self.desplazable.setFrameShape(QScrollArea.NoFrame)
        transparente(self.desplazable)
        transparente(self.desplazable.viewport())
        self.desplazable.setWidget(self.contenido)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(px(4, False), px(6, False), px(4, False), px(4, False))
        caja.setSpacing(px(10, False))
        # Suelta (sin MIS METAS, en los tests) la cabecera va aqui; la seccion se la lleva.
        caja.addWidget(self.controles_cabecera, 0, Qt.AlignRight)
        caja.addWidget(self.estado)
        caja.addWidget(self.desplazable, 1)
        self.retraducir()

    # -- ciclo de vida -----------------------------------------------------------

    def conectar_indice(self, con: sqlite3.Connection | None) -> None:
        self.indice = con
        self.marcar_sucio()

    def retraducir(self) -> None:
        self.guardar.setText(t("Guardar aperturas"))
        self.guardar.setToolTip(t("Apunta cada pantalla de recompensas de reliquia que Farmadex lea."))
        self.boton_precios.setText(t("Actualizar precios"))
        self.boton_precios.setToolTip(t("Pide a warframe.market el precio de lo que te has llevado."))
        self.marcar_sucio()

    def repintar(self) -> None:
        self.marcar_sucio()

    def marcar_sucio(self) -> None:
        """Hay datos nuevos: se repinta ya si se ve, o al ensenarse."""
        self._sucio = True
        if self.isVisible():
            self.pintar()

    def showEvent(self, evento):  # noqa: N802 - firma de Qt
        super().showEvent(evento)
        if self._sucio:
            self.pintar()

    def texto_plano(self) -> str:
        """Todo el texto de la pagina, sin formato: para los tests."""
        trozos = []
        for etiqueta in self.contenido.findChildren(QLabel):
            texto = etiqueta.texto_completo() if hasattr(etiqueta, "texto_completo") else etiqueta.text()
            trozos.append(texto)
        return "\n".join(trozos)

    # -- acciones -----------------------------------------------------------------

    def _cambiar_activo(self, activo: bool) -> None:
        self.config["historial_aperturas"] = bool(activo)
        try:
            from .. import config as config_modulo

            config_modulo.guardar(self.config)
        except Exception:  # noqa: BLE001 - sin guardar sigue valiendo para esta sesion
            log.debug("No se pudo guardar historial_aperturas", exc_info=True)
        self.activo_cambiado.emit(bool(activo))

    def pedir_borrar(self) -> None:
        respuesta = QMessageBox.question(
            self, t("Borrar historial"),
            t("¿Borrar todas las aperturas guardadas? No se puede deshacer. Tus metas no se tocan."),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if respuesta == QMessageBox.Yes:
            self.borrar()

    def borrar(self) -> int:
        n = datos_aperturas.borrar_todo(self.usuario)
        self.estado.setText(t("Historial borrado ({n} aperturas).", n=n))
        self.marcar_sucio()
        return n

    def marcar(self, apertura_id: int, unique_name: str | None) -> None:
        if datos_aperturas.marcar_obtenida(self.usuario, apertura_id, unique_name):
            self.marcar_sucio()

    def piezas_sin_precio(self) -> list[tuple[str, str]]:
        """(unique_name, slug) de lo obtenido sin precio reciente, las mas recientes primero."""
        if self.indice is None:
            return []
        lista = datos_aperturas.listar(self.usuario, None)
        vistos = datos_aperturas.precios(self.usuario, [a.obtenida for a in lista if a.obtenida])
        salida, vistas = [], set()
        for a in lista:
            if not a.obtenida or a.obtenida in vistas:
                continue
            vistas.add(a.obtenida)
            precio = vistos.get(a.obtenida)
            edad = precio.edad_s() if precio else None
            if edad is not None and edad <= vender_fundir.EDAD_MAXIMA_S:
                continue
            f = self.indice.execute("SELECT market_slug FROM items WHERE unique_name = ?", (a.obtenida,)).fetchone()
            if f and f[0]:
                salida.append((a.obtenida, f[0]))
        return salida[:MAXIMO_PRECIOS]

    def actualizar_precios(self) -> None:
        if self._actualizador is not None and self._actualizador.isRunning():
            return
        piezas = self.piezas_sin_precio()
        if not piezas:
            self.estado.setText(t("Los precios de lo que te has llevado ya están al día."))
            return
        self.boton_precios.setEnabled(False)
        self.estado.setText(t("Pidiendo {n} precios a warframe.market...", n=len(piezas)))
        self._actualizador = _ActualizadorPrecios(piezas, self)
        self._actualizador.hecho.connect(self._precios_hechos)
        self._actualizador.start()

    def _precios_hechos(self, n: int) -> None:
        self.boton_precios.setEnabled(True)
        self.estado.setText(t("Precios actualizados: {n}.", n=n) if n else
                            t("No se pudo conseguir ningún precio (¿sin conexión?)."))
        self.marcar_sucio()

    def parar(self) -> None:
        if self._actualizador is not None:
            self._actualizador.wait(5000)

    # -- pintado ------------------------------------------------------------------

    def _limpiar(self) -> None:
        while self.capa_contenido.count():
            item = self.capa_contenido.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)  # fuera ya: que no cuente en texto_plano hasta que Qt lo borre
                w.deleteLater()

    def pintar(self) -> None:
        self._sucio = False
        self._limpiar()
        try:
            lista = datos_aperturas.listar(self.usuario, None)
        except sqlite3.Error:
            log.exception("No se pudo leer el historial de aperturas")
            lista = []
        if not lista:
            vacio = PanelC(t("Historial de reliquias"))
            vacio.capa.addWidget(EtiquetaC(
                t("Aún no hay aperturas guardadas. Cuando Farmadex lea una pantalla de recompensas de reliquia "
                  "(sola, por EE.log, o con el atajo), aparecerá aquí."), envolver=True))
            self.capa_contenido.addWidget(vacio)
            self.capa_contenido.addStretch(1)
            return
        self.capa_contenido.addWidget(self._panel_resumen(lista))
        self.capa_contenido.addWidget(self._panel_suerte(lista))
        faltan = self._panel_faltan(lista)
        if faltan is not None:
            self.capa_contenido.addWidget(faltan)
        self.capa_contenido.addWidget(self._panel_aperturas(lista))
        self.capa_contenido.addStretch(1)

    def _panel_resumen(self, lista) -> PanelC:
        panel = PanelC(t("Resumen"))
        tot = datos_aperturas.totales(self.usuario, lista, vender_fundir.EDAD_MAXIMA_S)
        panel.capa.addWidget(EtiquetaC(
            t("Aperturas guardadas: {n} ({c} con la pieza confirmada, {s} sin confirmar)",
              n=tot.aperturas, c=tot.confirmadas, s=tot.sin_confirmar), "fuerte", envolver=True))
        panel.capa.addWidget(EtiquetaC(t("Ducados de lo que te has llevado: {n}", n=tot.ducados), envolver=True))
        if tot.confirmadas:
            if tot.platino or tot.sin_precio < tot.confirmadas:
                texto = t("Platino estimado de lo que te has llevado: unos {n} (precio de mercado del {fecha}, "
                          "vendiendo al más barato; es una estimación)",
                          n=tot.platino, fecha=_hora(tot.precio_mas_viejo or ""))
            else:
                texto = t("Platino estimado: no hay precios recientes. Pulsa \"Actualizar precios\".")
            panel.capa.addWidget(EtiquetaC(texto, envolver=True))
            if tot.sin_precio and (tot.platino or tot.sin_precio < tot.confirmadas):
                panel.capa.addWidget(EtiquetaC(
                    t("{n} piezas sin precio reciente no cuentan en el platino.", n=tot.sin_precio), "pequeno",
                    envolver=True))
        if tot.sin_confirmar:
            panel.capa.addWidget(EtiquetaC(
                t("En escuadra el juego no dice qué pieza elegiste: esas aperturas no suman nada hasta que "
                  "marques abajo cuál te quedaste."), "pequeno", envolver=True))
        return panel

    def _panel_suerte(self, lista) -> PanelC:
        panel = PanelC(t("Tu suerte"))
        suerte = datos_aperturas.suerte(lista)
        if suerte.muestra == 0:
            panel.capa.addWidget(EtiquetaC(
                t("Todavía no hay aperturas con las que medirla. Cuenta solo lo que sale de TU reliquia "
                  "(misiones en solitario) cuando se sabe el refinamiento."), envolver=True))
            return panel
        for r in suerte.por_rareza:
            panel.capa.addWidget(EtiquetaC(
                t("{rareza}: te han salido {n}, lo normal serían {e}",
                  rareza=t(NOMBRES_RAREZA[r.rareza]), n=r.obtenidas, e=f"{r.esperadas:.1f}"), envolver=True))
        if suerte.poca_muestra:
            texto = t("Solo {n} aperturas cuentan: son pocas para hablar de suerte (hacen falta al menos {m}).",
                      n=suerte.muestra, m=datos_aperturas.MUESTRA_MINIMA)
        elif suerte.veredicto == "mas":
            texto = t("Con {n} aperturas, te están saliendo más raras de lo normal.", n=suerte.muestra)
        elif suerte.veredicto == "menos":
            texto = t("Con {n} aperturas, te están saliendo menos raras de lo normal.", n=suerte.muestra)
        else:
            texto = t("Con {n} aperturas, tu suerte está dentro de lo normal.", n=suerte.muestra)
        panel.capa.addWidget(EtiquetaC(texto, "pequeno", envolver=True))
        return panel

    def _panel_faltan(self, lista) -> PanelC | None:
        if self.indice is None:
            return None
        refinamiento = datos_aperturas.refinamiento_habitual(lista)
        try:
            faltan = datos_aperturas.aperturas_que_faltan(
                self.indice, self.usuario, refinamiento or "Intact",
                nombre_de=lambda item_id: self._nombre_por_id(item_id),
            )
        except sqlite3.Error:
            log.exception("No se pudo calcular lo que falta")
            return None
        if not faltan:
            return None
        panel = PanelC(t("Piezas de tu lista: aperturas de media"))
        ref = t(NOMBRES_REFINAMIENTO.get(refinamiento or "Intact", "Intacta"))
        if refinamiento:
            panel.capa.addWidget(EtiquetaC(t("Con tu refinamiento habitual ({ref}).", ref=ref), "pequeno"))
        else:
            panel.capa.addWidget(EtiquetaC(t("Con reliquias sin refinar ({ref}).", ref=ref), "pequeno"))
        for f in faltan[:FALTAN_VISIBLES]:
            boveda = " " + t("(en bóveda)") if f.reliquia_vaulted else ""
            panel.capa.addWidget(EtiquetaC(
                t("{pieza}: {reliquia}{boveda}, {p} % por apertura. Unas {solo} aperturas tú solo, o unas "
                  "{ronda} rondas en escuadra de 4 con la misma reliquia.",
                  pieza=f.nombre, reliquia=f.reliquia, boveda=boveda, p=f"{f.probabilidad:g}",
                  solo=f"{f.aperturas_solo:.0f}", ronda=f"{f.rondas_escuadra:.0f}"), envolver=True))
        panel.capa.addWidget(EtiquetaC(t("Es la media: puede tocarte antes o bastante después."), "pequeno"))
        return panel

    def _nombre_por_id(self, item_id: int) -> str:
        f = self.indice.execute("SELECT unique_name FROM items WHERE id = ?", (item_id,)).fetchone()
        return nombre_pieza(self.indice, f[0]) if f else ""

    def _metas_pendientes(self) -> set[str]:
        try:
            return {f[0] for f in self.usuario.execute(
                "SELECT item_unique_name FROM objetivos WHERE completado_en IS NULL")}
        except sqlite3.Error:
            return set()

    def consejo_de(self, opcion, precio, metas: set[str]):
        edad = precio.edad_s() if precio else None
        return vender_fundir.aconsejar(
            precio.platino if precio else None, opcion.ducados, es_meta=opcion.unique_name in metas,
            vendedores=precio.vendedores if precio else None,
            compradores=precio.compradores if precio else None, edad_s=edad,
        )

    def _panel_aperturas(self, lista) -> PanelC:
        panel = PanelC(t("Aperturas"))
        metas = self._metas_pendientes()
        vistos = datos_aperturas.precios(self.usuario, [o.unique_name for a in lista for o in a.opciones])
        for a in lista[:FILAS_VISIBLES]:
            panel.capa.addWidget(self._fila_apertura(a, metas, vistos))
        if len(lista) > FILAS_VISIBLES:
            panel.capa.addWidget(EtiquetaC(t("Y {n} más antiguas (cuentan en el resumen).",
                                             n=len(lista) - FILAS_VISIBLES), "pequeno"))
        panel.capa.addWidget(EtiquetaC(vender_fundir.explicacion_umbral(), "pequeno", envolver=True))
        # Borrar va al final, lejos de la cabecera: se usa poco y no tiene vuelta atras.
        self.boton_borrar = BotonC(t("Borrar historial"))
        self.boton_borrar.clicked.connect(self.pedir_borrar)
        panel.capa.addLayout(fila(self.boton_borrar, None))
        return panel

    def _fila_apertura(self, a, metas: set[str], vistos: dict) -> QWidget:
        caja = transparente(QWidget())
        capa = QVBoxLayout(caja)
        capa.setContentsMargins(0, px(4, False), 0, px(4, False))
        capa.setSpacing(px(3, False))
        if a.reliquia:
            reliquia = t("Reliquia {nombre}", nombre=a.reliquia)
            if a.refinamiento:
                reliquia += f" ({t(NOMBRES_REFINAMIENTO.get(a.refinamiento, a.refinamiento))})"
        else:
            reliquia = t("Reliquia desconocida")
        modo = "" if a.en_solitario is None else (" · " + (t("en solitario") if a.en_solitario else t("en escuadra")))
        cabeza = EtiquetaC(f"{_hora(a.abierta_en)} · {reliquia}{modo}", "fuerte", recortar=True)
        capa.addWidget(cabeza)
        for o in a.opciones:
            nombre = nombre_pieza(self.indice, o.unique_name, o.nombre)
            trozos = [nombre]
            if o.rareza:
                trozos.append(t(NOMBRES_RAREZA.get(o.rareza, o.rareza)))
            if o.ducados:
                trozos.append(t("{n} ducados", n=o.ducados))
            precio = vistos.get(o.unique_name)
            edad = precio.edad_s() if precio else None
            if precio and edad is not None and edad <= vender_fundir.EDAD_MAXIMA_S:
                trozos.append(t("~{n} platino", n=precio.platino))
            marca = "★ " if o.unique_name == a.obtenida else "· "
            linea = QHBoxLayout()
            linea.setSpacing(px(8, False))
            linea.addWidget(EtiquetaC(marca + " · ".join(trozos), "fuerte" if o.unique_name == a.obtenida else "normal",
                                      recortar=True), 0)
            consejo = self.consejo_de(o, precio, metas)
            if consejo is not None:
                # Junto a la pieza (no al otro lado de la ventana), con el porque al pasar el raton.
                etiqueta = EtiquetaC("· " + consejo.corto, "pequeno", tinta=TINTA_CONSEJO.get(consejo.clave))
                etiqueta.setToolTip(consejo.motivo)
                linea.addWidget(etiqueta, 0)
            linea.addStretch(1)
            capa.addLayout(linea)
        capa.addLayout(self._fila_obtenida(a))
        return caja

    def _fila_obtenida(self, a) -> QHBoxLayout:
        linea = QHBoxLayout()
        linea.setSpacing(px(8, False))
        if a.obtenida and a.como == datos_aperturas.COMO_EELOG:
            texto = t("Te llevaste: {nombre} (lo dijo el juego, misión en solitario)",
                      nombre=nombre_pieza(self.indice, a.obtenida, a.obtenida_nombre or ""))
        elif a.obtenida:
            texto = t("Te llevaste: {nombre} (lo marcaste tú)",
                      nombre=nombre_pieza(self.indice, a.obtenida, a.obtenida_nombre or ""))
        else:
            texto = t("Sin confirmar: no se sabe cuál te quedaste.")
        linea.addWidget(EtiquetaC(texto, "pequeno", recortar=True), 1)
        if len(a.opciones) > 1 or not a.obtenida:
            elegir = DesplegableC()
            elegir.addItem(t("¿Cuál te quedaste?") if not a.obtenida else t("Cambiar"), "")
            for o in a.opciones:
                elegir.addItem(nombre_pieza(self.indice, o.unique_name, o.nombre), o.unique_name)
            if a.obtenida:
                elegir.addItem(t("No lo sé"), "__ninguna__")
            elegir.activated.connect(lambda i, c=elegir, ident=a.id: self._elegido(ident, c.itemData(i)))
            linea.addWidget(elegir, 0)
        return linea

    def _elegido(self, apertura_id: int, dato) -> None:
        if not dato:
            return
        self.marcar(apertura_id, None if dato == "__ninguna__" else dato)
