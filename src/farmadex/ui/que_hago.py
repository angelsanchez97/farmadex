"""Panel "¿Qué hago ahora?" del Tablero: la fisura abierta que antes te da una pieza de tus metas.

El calculo es `datos.que_hago.recomendar` (fisuras del mundo x reliquias del indice x tus
metas y las reliquias leidas en tu inventario). Va en un hilo aparte con su propia
conexion al indice (`BusquedaEnFondo`), y solo se rehace cuando cambian las fisuras,
tus metas o los datos, y con el panel a la vista. Cada 30 s se quitan las fisuras que
ya se han cerrado sin recalcular nada; si se quedan todas fuera, se recalcula.
"""

from __future__ import annotations

import html
import sqlite3
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..datos import eficiencia, que_hago
from ..idiomas import t
from ..registro_log import obtener
from .busqueda_fondo import BusquedaEnFondo
from .estilo_c import BotonC, EtiquetaC, EtiquetaEra, Insignia, PanelC, columna, fila, hex_de, px, transparente

log = obtener("que_hago")

VISIBLES = 3            # consejos a la vista; el resto con "Ver más"
REFRESCO_MS = 30_000    # quitar las fisuras que se cierran


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _vaciar(capa) -> None:
    while capa.count():
        elemento = capa.takeAt(0)
        if elemento.widget() is not None:
            elemento.widget().hide()
            elemento.widget().deleteLater()
        elif elemento.layout() is not None:
            _vaciar(elemento.layout())


def _enlace(href: str, texto: str, tinta: str = "acento") -> str:
    return (f"<a style='color:{hex_de(tinta)};text-decoration:none' href='{href}'>"
            f"{html.escape(texto)}</a>")


def _pct(valor: float) -> str:
    valor = float(valor or 0)
    return f"{valor:.0f} %" if valor >= 10 or valor == int(valor) else f"{valor:.1f} %"


def _restante(expira) -> str:
    from .pestana_mundo import tiempo_restante

    texto = tiempo_restante(expira)
    return "" if texto == "terminado" else texto


def _modo(refinamiento: str, escuadra: int) -> str:
    from .pestana_primes import texto_modo

    return texto_modo(refinamiento, escuadra)


def texto_titulo(c: que_hago.Consejo) -> str:
    """'Abre Lith A5 en la fisura de Hepit, Ceres (Captura)', con la reliquia enlazada."""
    f = c.fisura
    lugar = f"<b>{html.escape(getattr(f, 'nodo', '') or '')}</b>"
    mision = getattr(f, "mision", "") or ""
    if mision:
        lugar += f" ({html.escape(mision)})"
    return t("Abre {reliquia} en la fisura de {lugar}",
             reliquia=_enlace(f"item:{c.reliquia_id}", c.reliquia), lugar=lugar)


def texto_piezas(c: que_hago.Consejo, maximo: int = 3) -> str:
    enlaces = [_enlace(f"item:{p.item_id}", p.nombre, "texto") + f" <span style='color:{hex_de('suave')}'>"
               f"{_pct(p.probabilidad).replace(' ', '&nbsp;')}</span>" for p in c.piezas[:maximo]]
    if len(c.piezas) > maximo:
        enlaces.append(html.escape(t("y {n} más", n=len(c.piezas) - maximo)))
    return t("Da {piezas} de tus metas", piezas=", ".join(enlaces))


def texto_porque(c: que_hago.Consejo, refinamiento: str, escuadra: int) -> str:
    """El porque en una linea: tiempo hasta la pieza, probabilidad y si tienes la reliquia."""
    partes = [
        t("{minutos} de media hasta una pieza", minutos=eficiencia.texto_minutos(c.minutos)),
        t("{pct} por reliquia ({modo})", pct=_pct(c.probabilidad), modo=_modo(refinamiento, escuadra)),
    ]
    if c.la_tienes:
        partes.append(t("tienes {n}", n=c.tienes))
    elif c.sitio_reliquia:
        sitio = c.sitio_reliquia
        donde = sitio.get("donde") or ""
        if sitio.get("rotacion"):
            donde += f" {sitio['rotacion']}"
        clave = ("no la tienes: cae en {donde} ({minutos})" if c.tienes == 0
                 else "si no la tienes, cae en {donde} ({minutos})")
        partes.append(t(clave, donde=donde.strip(),
                        minutos=eficiencia.texto_minutos(c.minutos_reliquia)))
    elif c.vaulted:
        partes.append(t("en la bóveda"))
    f = c.fisura
    if getattr(f, "acero", False):
        partes.append(t("Camino de Acero (si lo tienes): mismos premios, enemigos más duros y 1 Esencia de acero"))
    if getattr(f, "tormenta", False):
        partes.append(t("Tormenta del Vacío (Railjack)"))
    if c.otras_fisuras:
        partes.append(t("también vale en {n} fisura(s) más", n=c.otras_fisuras))
    return " · ".join(partes)


def texto_sin_consejo(r: que_hago.Recomendacion) -> str:
    """Por que no hay consejo y la mejor alternativa real, en una o dos frases."""
    if r.estado == que_hago.SIN_INDICE:
        return t("Comprobando datos...")
    if r.estado == que_hago.SIN_METAS:
        return t("Todavía no tienes metas. Busca algo y pulsa '+ Objetivo' (o marca piezas en Primes) "
                 "y aquí te diré qué fisura abrir.")
    alt = r.alternativa or {}
    if r.estado == que_hago.SIN_RELIQUIAS:
        base = t("Tus metas no salen de reliquias, así que ninguna fisura te sirve.")
        mision = alt.get("mision") or {}
        if mision.get("donde"):
            base += " " + t("Lo más rápido: {meta} en {donde}{minutos}.", meta=r.meta_alternativa,
                            donde=mision["donde"], minutos=_entre_parentesis(alt.get("minutos_medios")))
        return base
    if r.estado == que_hago.SOLO_BOVEDA:
        return t("Lo que te falta solo sale de reliquias en la bóveda y no tienes ninguna leída en el "
                 "inventario: se consiguen por intercambio, Baro Ki'Teer o Prime Resurgence.")
    if r.estado == que_hago.SIN_MUNDO:
        base = t("Todavía no sé qué fisuras hay abiertas.")
    else:
        eras = ", ".join(r.eras) if r.eras else ""
        base = (t("Ninguna fisura abierta te sirve ahora (necesitas {eras}).", eras=eras) if eras
                else t("Ninguna fisura abierta te sirve ahora."))
    mision = alt.get("mision") or {}
    reliquia = alt.get("reliquia") or {}
    if reliquia and mision.get("donde"):
        nombre = que_hago._nombre_reliquia(reliquia)
        base += " " + t("Mientras tanto, farmea {reliquia} en {donde}{minutos} y guárdala para la próxima fisura.",
                        reliquia=nombre, donde=mision["donde"],
                        minutos=_entre_parentesis(alt.get("minutos")))
    return base


def _entre_parentesis(minutos) -> str:
    texto = eficiencia.texto_minutos(minutos)
    return f" ({texto})" if texto else ""


class PanelQueHago(PanelC):
    """El panel. Quien lo contiene le da indice, BD del usuario y mundo, y escucha sus senales."""

    abrir_item = Signal(int)
    navegar = Signal(str)

    def __init__(self, parent=None):
        super().__init__(t("¿Qué hago ahora?"), parent=parent)
        self.indice: sqlite3.Connection | None = None
        self.usuario: sqlite3.Connection | None = None
        self.mundo = None
        self._sabe_mundo = False
        self.resultado: que_hago.Recomendacion | None = None
        self._firma: tuple | None = None
        self._sucio = True
        self._abierto = False
        self._cache: dict = {}
        self._hilo = BusquedaEnFondo(self)

        self.boton_mas = BotonC("", tam=11)
        self.boton_mas.clicked.connect(self._alternar)
        self.boton_mas.hide()
        self.cabecera.addWidget(self.boton_mas)
        self.capa_filas = QVBoxLayout()
        self.capa_filas.setSpacing(px(10, False))
        self.capa.addLayout(self.capa_filas)

        self._diferido = QTimer(self)
        self._diferido.setSingleShot(True)
        self._diferido.setInterval(150)
        self._diferido.timeout.connect(self.recalcular)
        self._reloj = QTimer(self)
        self._reloj.setInterval(REFRESCO_MS)
        self._reloj.timeout.connect(self._quitar_cerradas)
        self._pintar()

    # -- conexion ---------------------------------------------------------------------

    def conectar(self, indice: sqlite3.Connection | None, usuario: sqlite3.Connection | None) -> None:
        self.indice = indice
        self.usuario = usuario
        self._cache.clear()
        self.marcar_sucio()

    def actualizar_mundo(self, mundo) -> None:
        self.mundo = mundo
        self._sabe_mundo = mundo is not None
        firma = que_hago.firma_fisuras(self._fisuras())
        if firma != self._firma:
            self.marcar_sucio()

    def marcar_sucio(self) -> None:
        """Metas, ritmo, preferencias o datos nuevos: se recalcula al verse."""
        self._sucio = True
        if self.isVisible():
            self._diferido.start()

    def olvidar_rutas(self) -> None:
        self._cache.clear()
        self.marcar_sucio()

    def retraducir(self) -> None:
        self.poner_titulo(t("¿Qué hago ahora?"))
        self._cache.clear()  # los nombres del indice van en el idioma de la interfaz
        self.marcar_sucio()
        self._pintar()

    def showEvent(self, evento):  # noqa: N802 - firma de Qt
        super().showEvent(evento)
        self._reloj.start()
        if self._sucio:
            self._diferido.start()

    def hideEvent(self, evento):  # noqa: N802
        super().hideEvent(evento)
        self._reloj.stop()

    # -- calculo ------------------------------------------------------------------------

    def _fisuras(self) -> list | None:
        if not self._sabe_mundo:
            return None
        return list(getattr(self.mundo, "fisuras", None) or [])

    def _indice_vivo(self) -> sqlite3.Connection | None:
        if self.indice is None:
            return None
        try:
            self.indice.execute("SELECT 1")
        except sqlite3.Error:
            self.indice = None
        return self.indice

    def recalcular(self, en_segundo_plano: bool = True) -> None:
        self._sucio = False
        indice = self._indice_vivo()
        fisuras = self._fisuras()
        self._firma = que_hago.firma_fisuras(fisuras)
        metas, tienes, acero = [], {}, False
        if self.usuario is not None:
            try:
                metas, tienes, acero = que_hago.leer_usuario(self.usuario)
            except sqlite3.Error:
                log.warning("No se pudieron leer las metas para '¿Qué hago ahora?'", exc_info=True)
        if indice is None:
            self._recibir(que_hago.recomendar(None, metas, tienes, fisuras))
            return
        from ..datos import ruta_prime

        refinamiento, escuadra = ruta_prime.preferencias()
        ritmo = eficiencia.ritmo()
        cache = self._cache

        def trabajo(con: sqlite3.Connection):
            # La cache de misiones es por conexion: la del hilo no es la de la ventana.
            return que_hago.recomendar(con, metas, tienes, fisuras, refinamiento=refinamiento,
                                       escuadra=escuadra, ritmo=ritmo, cache=cache, acero=acero)

        if en_segundo_plano:
            self._hilo.pedir(indice, trabajo, self._recibir)
        else:
            self._recibir(trabajo(indice))

    def _recibir(self, resultado: que_hago.Recomendacion) -> None:
        self.resultado = resultado
        self._pintar()

    def _quitar_cerradas(self) -> None:
        if not self.resultado or not self.resultado.consejos:
            return
        ahora = _ahora()
        vivos = [c for c in self.resultado.consejos
                 if not (getattr(c.fisura, "expira", None) and c.fisura.expira <= ahora)]
        if len(vivos) != len(self.resultado.consejos):
            self.resultado.consejos = vivos
            if not vivos:
                self.marcar_sucio()
        self._pintar()

    # -- pintado -------------------------------------------------------------------------

    def _alternar(self) -> None:
        self._abierto = not self._abierto
        self._pintar()

    def _pintar(self) -> None:
        _vaciar(self.capa_filas)
        r = self.resultado
        if r is None:
            self.boton_mas.hide()
            texto = t("Pensando qué te conviene...") if self.indice is not None else t("Comprobando datos...")
            self.capa_filas.addWidget(EtiquetaC(texto, "normal", tinta="suave", envolver=True))
            return
        if not r.consejos:
            self.boton_mas.hide()
            etiqueta = EtiquetaC(texto_sin_consejo(r), "normal", tinta="suave", envolver=True)
            self.capa_filas.addWidget(etiqueta)
            if r.estado in (que_hago.SIN_METAS,):
                boton = BotonC(t("Ir a mis metas"), tam=11)
                boton.clicked.connect(lambda: self.navegar.emit("metas/objetivos"))
                self.capa_filas.addLayout(fila(boton, None))
            elif r.alternativa and (r.alternativa.get("reliquia") or {}).get("reliquia_id"):
                rel = r.alternativa["reliquia"]
                boton = BotonC(t("Ver {reliquia}", reliquia=que_hago._nombre_reliquia(rel)), tam=11)
                boton.clicked.connect(lambda _=False, i=rel["reliquia_id"]: self.abrir_item.emit(i))
                self.capa_filas.addLayout(fila(boton, None))
            return
        visibles = r.consejos if self._abierto else r.consejos[:VISIBLES]
        for i, c in enumerate(visibles):
            self.capa_filas.addWidget(self._fila(c, r, primero=i == 0))
        sobran = len(r.consejos) - VISIBLES
        self.boton_mas.setVisible(sobran > 0)
        self.boton_mas.setText(t("Ocultar") if self._abierto else t("Ver {n} más", n=sobran))

    def _fila(self, c: que_hago.Consejo, r: que_hago.Recomendacion, primero: bool) -> QWidget:
        titulo = EtiquetaC(texto_titulo(c), "destacado" if primero else "fuerte", envolver=True)
        piezas = EtiquetaC(texto_piezas(c), "normal", envolver=True)
        porque = EtiquetaC(texto_porque(c, r.refinamiento, r.escuadra), "pequeno", tinta="suave",
                           envolver=True)
        for etiqueta in (titulo, piezas):
            etiqueta.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
            etiqueta.linkActivated.connect(self._enlace)
        derecha = columna(EtiquetaC(_restante(getattr(c.fisura, "expira", None)), "normal", tinta="suave"), None,
                          espacio=0)
        izquierda = columna(EtiquetaEra(getattr(c.fisura, "era", "")), None, espacio=0)
        if getattr(c.fisura, "acero", False):
            izquierda.insertWidget(1, Insignia(t("Acero"), "aviso", tam=9))
        caja = transparente(QWidget())
        capa = QHBoxLayout(caja)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(px(10, False))
        margen = transparente(QWidget())
        margen.setLayout(izquierda)
        margen.setFixedWidth(px(64, False))  # misma sangria para Lith, Meso, Omnia...
        capa.addWidget(margen)
        capa.addLayout(columna(titulo, piezas, porque, espacio=px(2, False)), 1)
        capa.addLayout(derecha)
        caja.setToolTip(t("Clic en la reliquia o en la pieza para abrir su ficha"))
        return caja

    def _enlace(self, href: str) -> None:
        if href.startswith("item:"):
            try:
                self.abrir_item.emit(int(href.split(":", 1)[1]))
            except ValueError:
                pass

    def texto_plano(self) -> str:
        """Todo lo escrito en el panel, sin formato (pruebas y diagnostico)."""
        from PySide6.QtGui import QTextDocumentFragment
        from PySide6.QtWidgets import QLabel

        trozos = []
        for etiqueta in self.findChildren(QLabel):
            if not etiqueta.isVisibleTo(self) and etiqueta.parent() is not None and etiqueta.isHidden():
                continue
            texto = etiqueta.texto_completo() if hasattr(etiqueta, "texto_completo") else etiqueta.text()
            if "<" in texto:
                texto = QTextDocumentFragment.fromHtml(texto).toPlainText()
            trozos.append(texto)
        return "\n".join(trozos)
