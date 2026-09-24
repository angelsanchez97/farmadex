"""Pestana Primes: marcas las piezas que quieres y te dice donde farmearlas antes.

Como la lista de deseos de wf.xuerian.net: una caja por objeto prime con una
casilla por pieza, y debajo (o al lado, si hay sitio) las reliquias que las
contienen y las misiones donde caen esas reliquias. La diferencia es el orden: la
web ordena por porcentaje medio y aqui se ordena por el tiempo medio hasta tener
la pieza (`datos/ruta_prime.py`: reliquias que hay que abrir, fisuras, y todas las
reliquias utiles que caen en la misma rotacion).

Lo marcado son Objetivos: marcar una pieza crea su objetivo y desmarcarla lo
borra, y un objetivo creado desde la ficha sale marcado aqui. Una sola fuente de
verdad, asi que lo que el OCR o EE.log suman a un objetivo se ve en las dos
pestanas. Un objetivo completado sigue marcado (no se desmarca solo), pero ya no
cuenta para el resultado: lo tienes.
"""

from __future__ import annotations

import html
import sqlite3

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .. import perfil
from ..config import cargar, guardar
from ..datos import eficiencia, ruta_prime
from ..datos.items import normalizar
from ..estado import inventario as estado_inventario
from ..estado import objetivos as estado_objetivos
from ..estado import usuario_db
from ..idiomas import nombre as nombre_idioma, t
from . import desglose_tiempo, enlaces_wiki, glosario, relleno_filas
from .maestria import estado_con_padre
from .widgets import COLOR_BOVEDA, COLOR_DISPONIBLE, PALETA

# Nombre de cada refinamiento en la interfaz (las claves son las del indice).
NOMBRES_REFINAMIENTO = {
    "Intact": "Intacta",
    "Exceptional": "Excepcional",
    "Flawless": "Impecable",
    "Radiant": "Radiante",
}
# A partir de este ancho la rejilla y el resultado caben uno al lado del otro con la
# tabla de misiones entera (~620 px); por debajo, un boton cambia entre los dos.
ANCHO_DOBLE = 1360
# Cuantas filas se ensenan de cada lista antes de resumir el resto.
MAX_MISIONES = 40
MAX_RELIQUIAS = 30
CLAVE_BOVEDA = "primes_incluir_boveda"


def _corto(reliquia: dict) -> str:
    """'Meso V13': la era y el codigo se escriben igual en todos los idiomas."""
    return (reliquia.get("nombre_en") or "").removesuffix(" Relic")


def texto_refinamiento(refinamiento: str) -> str:
    return t(NOMBRES_REFINAMIENTO.get(refinamiento, refinamiento))


def texto_modo(refinamiento: str, escuadra: int) -> str:
    """'Radiante, escuadra de 4' o 'Intacta, en solitario'."""
    modo = t("escuadra de {n}", n=escuadra) if escuadra > 1 else t("en solitario")
    return f"{texto_refinamiento(refinamiento)}, {modo}"


# -- piezas de HTML compartidas con la ficha del buscador -----------------------------

def _seccion(titulo: str) -> str:
    return (
        f"<div style='color:{PALETA['acento']};font-size:12px;font-weight:bold;"
        f"margin-top:14px;margin-bottom:4px'>{html.escape(titulo).upper()}</div>"
    )


def _tarjeta(cuerpo: str, color: str) -> str:
    return (
        f"<table cellpadding='8' cellspacing='0' width='100%' style='margin-bottom:6px'>"
        f"<tr><td width='4' style='background:{color}'></td>"
        f"<td style='background:{PALETA['panel2']}'>{cuerpo}</td></tr></table>"
    )


def _tiempo(minutos: float | None, color: str, negrita: bool = True, detalle: str = "") -> str:
    """'~48 min' hasta la pieza; con `detalle` (desglose_tiempo.texto_prime) el tooltip
    desglosa los numeros de ese sitio en vez de la explicacion generica."""
    texto = eficiencia.texto_minutos(minutos)
    return glosario.enlace("tiempo_pieza", texto, color, negrita, detalle) if texto else ""


def _enlace_reliquia(reliquia: dict, color: str) -> str:
    return (
        f"<a style='color:{color};text-decoration:none' href='item:{reliquia['reliquia_id']}'>"
        f"<b>{html.escape(_corto(reliquia))}</b></a>"
    )


def _rotacion(mision: dict, color: str) -> str:
    """'rotacion C' con su explicacion para el modo de la mision al pasar el raton."""
    if mision.get("rotacion"):
        return glosario.enlace_rotacion(
            mision.get("modo"), mision["rotacion"], t("rotacion {rot}", rot=mision["rotacion"]), color
        )
    return html.escape(mision.get("etapa") or "")


def _mision(mision: dict, color: str) -> str:
    """El tipo de mision: que se hace y como van sus recompensas al pasar el raton."""
    if not mision.get("mision"):
        return ""
    return glosario.enlace_mision(mision.get("modo"), mision["mision"], color, mision.get("rotacion"))


def _probabilidades_reliquias(reliquias: list[dict], refinamiento: str) -> str:
    """'Meso V13 o Meso V15 · 20% en Radiante', o cada una con lo suyo si difieren."""
    p = PALETA
    ref = glosario.enlace("refinamiento", texto_refinamiento(refinamiento), p["suave"])
    probs = {round(r["probabilidad"], 2) for r in reliquias}
    if len(probs) == 1:
        nombres = f" {html.escape(t('o'))} ".join(_enlace_reliquia(r, p["texto"]) for r in reliquias)
        # El hueco del refinamiento se rellena despues: es un enlace del glosario.
        hueco = "@@REF@@"
        texto = html.escape(t("{prob}% en {refinamiento}", prob=f"{reliquias[0]['probabilidad']:.1f}",
                              refinamiento=hueco))
        return f"{nombres} <span style='color:{p['suave']}'>&middot; {texto.replace(hueco, '</span>' + ref)}"
    trozos = [
        f"{_enlace_reliquia(r, p['texto'])} <span style='color:{p['suave']}'>{r['probabilidad']:.1f}%</span>"
        for r in reliquias
    ]
    return f" {html.escape(t('o'))} ".join(trozos) + f" <span style='color:{p['suave']}'>&middot;</span> {ref}"


def _sitio(mision: dict, color: str) -> str:
    """'Io, Jupiter (+3)': los nodos con la misma tabla cuentan como uno.

    El nodo enlaza a su pagina de la wiki con `color`, el del texto que lo rodea.
    """
    extra = len(mision.get("sitios") or []) - 1
    texto = enlaces_wiki.donde(mision, color)
    if extra > 0:
        texto += f" <span style='color:{PALETA['suave']}'>(+{extra})</span>"
    return texto


def bloque_ficha(con: sqlite3.Connection | None, item_id: int) -> str | None:
    """"Por donde empezar" de la ficha para una pieza prime o para su objeto entero.

    None si el objeto no sale de reliquias (ni sus piezas): la ficha sigue con lo suyo.
    """
    if con is None:
        return None
    refinamiento, escuadra = ruta_prime.preferencias()
    ruta = ruta_prime.ruta_pieza(con, item_id, refinamiento, escuadra)
    p = PALETA
    cabecera = (
        f"<div style='color:{p['acento']};font-size:12px;font-weight:bold'>"
        f"{html.escape(t('Por donde empezar')).upper()}</div>"
    )
    if ruta is not None:
        return _tarjeta(cabecera + _cuerpo_ruta(ruta), COLOR_BOVEDA if ruta["solo_en_boveda"] else p["acento"])
    piezas = con.execute(
        "SELECT id, nombre_en, nombre_es FROM items WHERE padre_id = ? ORDER BY "
        "unique_name NOT LIKE '%Blueprint', nombre_en",
        (item_id,),
    ).fetchall()
    lineas = []
    for pieza_id, nombre_en, nombre_es in piezas:
        ruta = ruta_prime.ruta_pieza(con, pieza_id, refinamiento, escuadra)
        if ruta is None:
            continue
        nombre = html.escape(nombre_idioma({"nombre_en": nombre_en, "nombre_es": nombre_es}))
        enlace = f"<a style='color:{p['texto']};text-decoration:none' href='item:{pieza_id}'><b>{nombre}</b></a>"
        if ruta["mision"]:
            m = ruta["mision"]
            detalle = " &middot; ".join(
                x for x in (
                    _enlace_reliquia(ruta["reliquia"], p["texto"]),
                    _sitio(m, p["suave"]),
                    _mision(m, p["suave"]),
                    _rotacion(m, p["suave"]),
                    _tiempo(ruta["minutos"], p["texto"], detalle=desglose_tiempo.texto_prime(
                        m, escuadra, texto_modo(refinamiento, escuadra))),
                ) if x
            )
        elif ruta["solo_en_boveda"]:
            detalle = glosario.enlace("boveda", t("en boveda"), COLOR_BOVEDA)
        else:
            detalle = html.escape(t("sin mision que se pueda estimar"))
        lineas.append(f"<div style='margin-top:3px;color:{p['suave']}'>{enlace}: {detalle}</div>")
    if not lineas:
        return None
    pie = (
        f"<div style='color:{p['suave']};font-size:12px;margin-top:4px'>"
        + html.escape(t("Tiempo medio hasta cada pieza ({modo}). Todas juntas, en la pestana Primes.",
                        modo=texto_modo(refinamiento, escuadra)))
        + "</div>"
    )
    return _tarjeta(cabecera + "".join(lineas) + pie, p["acento"])


def _cuerpo_ruta(ruta: dict) -> str:
    """Reliquia (con su %), mision (con su %) y tiempo total hasta la pieza."""
    p = PALETA
    refinamiento, escuadra = ruta["refinamiento"], ruta["escuadra"]
    mision = ruta["mision"]
    reliquias = mision["reliquias"][:3] if mision else [ruta["reliquia"]]
    cuerpo = [f"<div style='font-size:16px;margin-top:2px'>{_probabilidades_reliquias(reliquias, refinamiento)}</div>"]
    if ruta["solo_en_boveda"]:
        cuerpo.append(
            "<div style='margin-top:2px'>"
            + glosario.enlace("boveda", t("En boveda: solo por intercambio, Baro Ki'Teer o Prime Resurgence"), COLOR_BOVEDA)
            + "</div>"
        )
        return "".join(cuerpo)
    if not mision:
        cuerpo.append(
            f"<div style='color:{p['suave']};margin-top:2px'>"
            + html.escape(t("Ninguna de sus reliquias cae en una mision que se pueda estimar."))
            + "</div>"
        )
        return "".join(cuerpo)
    detalle = " &middot; ".join(
        x for x in (
            f"<b>{_sitio(mision, p['texto'])}</b>",
            _mision(mision, p["suave"]),
            _rotacion(mision, p["suave"]),
            f"{mision['probabilidad']:.1f}%",
        ) if x
    )
    cuerpo.append(
        f"<div style='color:{p['suave']};margin-top:2px'>{html.escape(t('Farmea la reliquia en'))} "
        f"<span style='color:{p['texto']}'>{detalle}</span></div>"
    )
    modo = texto_modo(refinamiento, escuadra)
    clave_modo = "radshare" if escuadra > 1 else "refinamiento"
    cuerpo.append(
        f"<div style='margin-top:4px'>"
        f"{_tiempo(ruta['minutos'], p['texto'], detalle=desglose_tiempo.texto_prime(mision, escuadra, modo))} "
        f"<span style='color:{p['suave']}'>{html.escape(t('hasta tener la pieza'))} &middot; </span>"
        + glosario.enlace(clave_modo, modo, p["suave"])
        + "</div>"
    )
    return "".join(cuerpo)


# -- rejilla -----------------------------------------------------------------------

class DisposicionFluida(QLayout):
    """Coloca los widgets en filas que se parten al llegar al borde, como texto."""

    def __init__(self, parent=None, espacio: int = 8):
        super().__init__(parent)
        self._items = []
        self._espacio = espacio
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 - firma de Qt
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, ancho):  # noqa: N802
        return self._colocar(QRect(0, 0, ancho, 0), True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._colocar(rect, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        tam = QSize()
        for item in self._items:
            if not item.isEmpty():
                tam = tam.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return tam + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _colocar(self, rect: QRect, prueba: bool) -> int:
        m = self.contentsMargins()
        zona = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, alto_fila = zona.x(), zona.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            tam = item.sizeHint()
            if x + tam.width() > zona.right() + 1 and alto_fila > 0:
                x = zona.x()
                y += alto_fila + self._espacio
                alto_fila = 0
            if not prueba:
                item.setGeometry(QRect(QPoint(x, y), tam))
            x += tam.width() + self._espacio
            alto_fila = max(alto_fila, tam.height())
        return y + alto_fila - rect.y() + m.bottom()


class CajaPrime(QFrame):
    """Un objeto prime (o los sueltos) con una casilla por pieza."""

    marcada = Signal(dict, bool)

    def __init__(self, titulo: str, piezas: list[dict], objeto: dict | None = None, columnas: int = 1, parent=None):
        super().__init__(parent)
        self.setObjectName("cajaPrime")
        self.objeto = objeto
        self.piezas = piezas
        self.titulo = QLabel()
        self.titulo.setTextFormat(Qt.RichText)
        self._titulo = titulo
        self.casillas: dict[str, QCheckBox] = {}
        caja = QVBoxLayout(self)
        caja.setContentsMargins(10, 6, 10, 8)
        caja.setSpacing(2)
        caja.addWidget(self.titulo)
        rejilla = QGridLayout()
        rejilla.setContentsMargins(0, 0, 0, 0)
        rejilla.setHorizontalSpacing(14)
        rejilla.setVerticalSpacing(1)
        for i, pieza in enumerate(piezas):
            casilla = QCheckBox()
            casilla.toggled.connect(lambda marcado, pieza=pieza: self.marcada.emit(pieza, marcado))
            self.casillas[pieza["unique_name"]] = casilla
            filas = (len(piezas) + columnas - 1) // columnas
            rejilla.addWidget(casilla, i % filas, i // filas)
        caja.addLayout(rejilla)
        # Texto para el filtro: el objeto y sus piezas en los dos idiomas del indice.
        partes = [titulo]
        if objeto:
            partes += [objeto["nombre_en"], objeto["nombre_es"] or ""]
        for pieza in piezas:
            partes += [pieza["nombre_en"], pieza["nombre_es"] or ""]
        self.texto_filtro = normalizar(" ".join(partes))

    def pintar(self, estados: dict[str, tuple[bool, str | None, str]], maestria: str = "") -> None:
        """estados: unique_name -> (marcada, estado 'conseguido'/'tienes'/None, pista)."""
        p = PALETA
        alguna = False
        for unico, casilla in self.casillas.items():
            pieza = next(x for x in self.piezas if x["unique_name"] == unico)
            marcada, estado, pista = estados.get(unico, (False, None, ""))
            alguna = alguna or marcada
            texto = nombre_idioma(pieza)
            if (pieza.get("item_count") or 1) > 1:
                texto += f" ×{pieza['item_count']}"
            color = p["texto"]
            if estado:
                texto += " ✓"
                color = COLOR_DISPONIBLE
            elif pieza["en_boveda"]:
                color = p["suave"]
            casilla.blockSignals(True)
            casilla.setChecked(marcada)
            casilla.blockSignals(False)
            casilla.setText(texto)
            casilla.setStyleSheet(f"QCheckBox {{ color: {color}; font-size: 13px; }}")
            ayuda = [pista] if pista else []
            if pieza["en_boveda"]:
                ayuda.append(t("En boveda: solo por intercambio, Baro Ki'Teer o Prime Resurgence"))
            casilla.setToolTip("\n".join(ayuda))
        etiquetas = ""
        if self.objeto and self.objeto.get("en_boveda"):
            etiquetas += f" <span style='color:{COLOR_BOVEDA};font-size:11px'>{html.escape(t('BOVEDA'))}</span>"
        if maestria:
            etiquetas += f" <span style='color:{COLOR_DISPONIBLE};font-size:11px'>✓ {html.escape(maestria)}</span>"
        self.titulo.setText(
            f"<span style='color:{p['acento'] if alguna else p['texto']};font-weight:600;font-size:13px'>"
            f"{html.escape(self._titulo.upper())}</span>{etiquetas}"
        )
        self.setStyleSheet(
            f"#cajaPrime {{ background: {p['panel2']}; border: 1px solid "
            f"{p['acento'] if alguna else p['borde']}; border-radius: 8px; }}"
        )


class VistaResultado(glosario.FichaConGlosario):
    """La ficha del resultado: glosario y, en los '(+3)', la lista de nodos equivalentes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sitios: dict[int, list[str]] = {}

    def event(self, evento):  # noqa: N802 - firma de Qt
        if evento.type() == QEvent.ToolTip:
            url = self.anchorAt(evento.pos())
            if url.startswith("sitios:"):
                lista = self.sitios.get(int(url.removeprefix("sitios:")), [])
                QToolTip.showText(evento.globalPos(), "\n".join(lista), self)
                return True
        return super().event(evento)


# -- pestana -----------------------------------------------------------------------

class PestanaPrimes(QWidget):
    abrir_item = Signal(int)
    # Lo marcado ha cambiado (son objetivos): quien tenga la lista de objetivos, que repinte.
    marcas_cambiadas = Signal()

    def __init__(self, objetivos=None, usuario: sqlite3.Connection | None = None, parent=None):
        super().__init__(parent)
        # Si llega la pestana Objetivos, se comparte su BD (misma conexion, mismo hilo) y
        # se escucha su senal para marcar aqui lo que se anada alli.
        self._pestana_objetivos = objetivos
        if usuario is None:
            usuario = objetivos.usuario if objetivos is not None else usuario_db.conectar()
        self.usuario: sqlite3.Connection = usuario
        if objetivos is not None:
            objetivos.cambiados.connect(self.refrescar_marcas)
        self.indice: sqlite3.Connection | None = None
        self.config = cargar()
        self._objetos: list[dict] = []
        self._sueltos: list[dict] = []
        self._piezas: dict[str, dict] = {}  # unique_name -> pieza (con 'padre')
        self._cajas: list[CajaPrime] = []
        self._cache_misiones: dict = {}  # reliquia_id -> filas; '_ritmo' -> con que ritmo
        self._cambiando = False
        self._vista = "rejilla"

        # -- barra de arriba
        self.boton_rejilla = QPushButton()
        self.boton_resultado = QPushButton()
        self._grupo_vista = QButtonGroup(self)
        for boton in (self.boton_rejilla, self.boton_resultado):
            boton.setCheckable(True)
            self._grupo_vista.addButton(boton)
        self.boton_rejilla.setChecked(True)
        self.boton_rejilla.clicked.connect(lambda: self._elegir_vista("rejilla"))
        self.boton_resultado.clicked.connect(lambda: self._elegir_vista("resultado"))
        self.refinamiento = QComboBox()
        self.escuadra = QComboBox()
        glosario.aplicar(self.refinamiento, "refinamiento")
        glosario.aplicar(self.escuadra, "radshare")
        self.refinamiento.currentIndexChanged.connect(self._cambiar_modo)
        self.escuadra.currentIndexChanged.connect(self._cambiar_modo)

        arriba = QHBoxLayout()
        arriba.setSpacing(6)
        arriba.addWidget(self.boton_rejilla)
        arriba.addWidget(self.boton_resultado)
        arriba.addStretch(1)
        arriba.addWidget(self.refinamiento)
        arriba.addWidget(self.escuadra)

        # -- rejilla
        self.filtro = QLineEdit()
        self.filtro.setClearButtonEnabled(True)
        self.filtro.textChanged.connect(lambda _: self._aplicar_filtro())
        self.incluir_boveda = QCheckBox()
        self.incluir_boveda.setChecked(bool(self.config.get(CLAVE_BOVEDA, False)))
        self.incluir_boveda.toggled.connect(self._cambiar_boveda)
        glosario.aplicar(self.incluir_boveda, "boveda")
        self.limpiar = QPushButton()
        self.limpiar.clicked.connect(self._desmarcar_todo)
        barra_rejilla = QHBoxLayout()
        barra_rejilla.setSpacing(6)
        barra_rejilla.addWidget(self.filtro, 1)
        barra_rejilla.addWidget(self.incluir_boveda)
        barra_rejilla.addWidget(self.limpiar)

        self.contenido = QWidget()
        self.fluida = DisposicionFluida(self.contenido)
        self.desplazable = QScrollArea()
        self.desplazable.setWidgetResizable(True)
        self.desplazable.setWidget(self.contenido)
        self.panel_rejilla = QWidget()
        caja_rejilla = QVBoxLayout(self.panel_rejilla)
        caja_rejilla.setContentsMargins(0, 0, 0, 0)
        caja_rejilla.setSpacing(6)
        caja_rejilla.addLayout(barra_rejilla)
        caja_rejilla.addWidget(self.desplazable, 1)

        # -- resultado
        self.resultado = VistaResultado()
        self.resultado.setOpenLinks(False)
        self.resultado.anchorClicked.connect(self._enlace)
        self._relleno = relleno_filas.RellenoFilas(self.resultado)

        self.divisor = QSplitter(Qt.Horizontal)
        self.divisor.setChildrenCollapsible(False)
        self.divisor.addWidget(self.panel_rejilla)
        self.divisor.addWidget(self.resultado)
        self.divisor.setStretchFactor(0, 1)
        self.divisor.setStretchFactor(1, 1)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 8, 4, 4)
        caja.setSpacing(6)
        caja.addLayout(arriba)
        caja.addWidget(self.divisor, 1)

        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(60)
        self._temporizador.timeout.connect(self._pintar_resultado)
        self._rellenar_combos()
        self.retraducir()
        self._ajustar_disposicion()

    # -- ciclo de vida ---------------------------------------------------------

    def conectar_indice(self, con: sqlite3.Connection) -> None:
        self.indice = con
        self._cache_misiones.clear()
        self._objetos, self._sueltos = ruta_prime.catalogo(con)
        self._piezas = {}
        for o in self._objetos:
            for pieza in o["piezas"]:
                self._piezas[pieza["unique_name"]] = {**pieza, "padre": o}
        for pieza in self._sueltos:
            self._piezas[pieza["unique_name"]] = {**pieza, "padre": None}
        self._construir_rejilla()

    def retraducir(self) -> None:
        self.filtro.setPlaceholderText(t("Filtra por nombre (p. ej. caliban, forma)"))
        self.incluir_boveda.setText(t("Incluir lo que esta en boveda"))
        self.limpiar.setText(t("Desmarcar todo"))
        self._rellenar_combos()
        self._construir_rejilla()

    def repintar(self) -> None:
        """Tras cambiar de tema: las cajas y el resultado llevan los colores dentro."""
        self.refrescar_marcas()

    def resizeEvent(self, evento):  # noqa: N802 - firma de Qt
        super().resizeEvent(evento)
        self._ajustar_disposicion()

    # -- disposicion -------------------------------------------------------------

    def _doble(self) -> bool:
        return self.width() >= ANCHO_DOBLE

    def _ajustar_disposicion(self) -> None:
        doble = self._doble()
        if doble and not getattr(self, "_era_doble", False):
            mitad = max(1, self.divisor.width() // 2)
            self.divisor.setSizes([mitad, mitad])
        self._era_doble = doble
        self.boton_rejilla.setVisible(not doble)
        self.boton_resultado.setVisible(not doble)
        self.panel_rejilla.setVisible(doble or self._vista == "rejilla")
        self.resultado.setVisible(doble or self._vista == "resultado")

    def _elegir_vista(self, vista: str) -> None:
        self._vista = vista
        self.boton_rejilla.setChecked(vista == "rejilla")
        self.boton_resultado.setChecked(vista == "resultado")
        self._ajustar_disposicion()

    def _rellenar_combos(self) -> None:
        refinamiento, escuadra = ruta_prime.preferencias()
        for combo, opciones, actual in (
            (self.refinamiento, [(texto_refinamiento(r), r) for r in NOMBRES_REFINAMIENTO], refinamiento),
            (self.escuadra, [(t("En solitario"), 1), (t("Escuadra de 4 compartiendo reliquia"), 4)], escuadra),
        ):
            combo.blockSignals(True)
            combo.clear()
            for texto, dato in opciones:
                combo.addItem(texto, dato)
            combo.setCurrentIndex(max(0, combo.findData(actual)))
            combo.blockSignals(False)

    # -- rejilla -------------------------------------------------------------------

    def _construir_rejilla(self) -> None:
        if not hasattr(self, "fluida"):
            return
        while self.fluida.count():
            elemento = self.fluida.takeAt(0)
            viejo = elemento.widget()
            if viejo:
                # Fuera ya, no al volver al bucle de eventos: si no, se pintan encima.
                viejo.hide()
                viejo.setParent(None)
                viejo.deleteLater()
        self._cajas = []
        incluir = self.incluir_boveda.isChecked()
        for o in self._objetos:
            if o["en_boveda"] and not incluir:
                continue
            piezas = [p for p in o["piezas"] if incluir or not p["en_boveda"]]
            caja = CajaPrime(nombre_idioma(o), piezas, o)
            caja.marcada.connect(self._marcar)
            self._cajas.append(caja)
        sueltos = [p for p in self._sueltos if incluir or not p["en_boveda"]]
        if sueltos:
            caja = CajaPrime(t("Otros objetos de reliquia"), sueltos, None, columnas=2)
            caja.marcada.connect(self._marcar)
            self._cajas.append(caja)
        for caja in self._cajas:
            self.fluida.addWidget(caja)
        self._aplicar_filtro()
        self.refrescar_marcas()

    def _aplicar_filtro(self) -> None:
        texto = normalizar(self.filtro.text())
        for caja in self._cajas:
            caja.setVisible(not texto or all(palabra in caja.texto_filtro for palabra in texto.split()))
        self.fluida.invalidate()

    def _cambiar_boveda(self, marcado: bool) -> None:
        self.config[CLAVE_BOVEDA] = marcado
        guardar(self.config)
        self._construir_rejilla()

    def _cambiar_modo(self, *_):
        self.config[ruta_prime.CLAVE_REFINAMIENTO] = self.refinamiento.currentData() or ruta_prime.REFINAMIENTO_POR_DEFECTO
        self.config[ruta_prime.CLAVE_ESCUADRA] = self.escuadra.currentData() or ruta_prime.ESCUADRA_POR_DEFECTO
        guardar(self.config)
        self._temporizador.start()

    # -- marcas (objetivos) ----------------------------------------------------------

    def _objetivos(self) -> dict[str, estado_objetivos.Objetivo]:
        return {o.unique_name: o for o in estado_objetivos.listar(self.usuario)}

    def nombre_pieza(self, pieza: dict) -> str:
        """'Plano de Caliban Prime' (o 'Caliban Prime Blueprint') y, suelta, su nombre."""
        padre = pieza.get("padre")
        if not padre:
            return nombre_idioma(pieza)
        return t("{nombre} de {padre}", nombre=nombre_idioma(pieza), padre=nombre_idioma(padre))

    def _marcar(self, pieza: dict, marcado: bool) -> None:
        unico = pieza["unique_name"]
        self._cambiando = True
        try:
            if marcado:
                padre = self._piezas.get(unico, {}).get("padre")
                # Igual que "+ Set completo": "Caliban Prime: Plano", en el idioma de ahora.
                nombre = f"{nombre_idioma(padre)}: {nombre_idioma(pieza)}" if padre else nombre_idioma(pieza)
                estado_objetivos.anadir(self.usuario, unico, nombre, pieza.get("item_count") or 1)
            else:
                objetivo = self._objetivos().get(unico)
                if objetivo:
                    estado_objetivos.borrar(self.usuario, objetivo.id)
            if self._pestana_objetivos is not None:
                self._pestana_objetivos.refrescar()
            self.marcas_cambiadas.emit()
        finally:
            self._cambiando = False
        self.refrescar_marcas()

    def _desmarcar_todo(self) -> None:
        objetivos = self._objetivos()
        self._cambiando = True
        try:
            for unico in self._piezas:
                objetivo = objetivos.get(unico)
                if objetivo:
                    estado_objetivos.borrar(self.usuario, objetivo.id)
            if self._pestana_objetivos is not None:
                self._pestana_objetivos.refrescar()
            self.marcas_cambiadas.emit()
        finally:
            self._cambiando = False
        self.refrescar_marcas()

    def marcadas(self) -> list[dict]:
        """Las piezas marcadas (objetivos que salen de reliquias), con su objetivo."""
        salida = []
        for unico, objetivo in self._objetivos().items():
            pieza = self._piezas.get(unico)
            if pieza:
                salida.append({**pieza, "objetivo": objetivo})
        salida.sort(key=lambda p: self.nombre_pieza(p))
        return salida

    def refrescar_marcas(self) -> None:
        """Pinta las casillas segun los objetivos y rehace el resultado."""
        if self._cambiando:
            return
        objetivos = self._objetivos()
        hay_perfil = self.indice is not None and perfil.hay_perfil(self.usuario)
        for caja in self._cajas:
            estados = {}
            for pieza in caja.piezas:
                objetivo = objetivos.get(pieza["unique_name"])
                estado, pista = self._estado_pieza(pieza, objetivo)
                estados[pieza["unique_name"]] = (objetivo is not None, estado, pista)
            maestria = ""
            if hay_perfil and caja.objeto:
                if estado_con_padre(self.usuario, self.indice, caja.objeto["id"]).estado == perfil.DOMINADO:
                    maestria = t("Dominado")
            caja.pintar(estados, maestria)
        self._n_marcadas = sum(1 for u in objetivos if u in self._piezas)
        self.boton_rejilla.setText(t("Piezas ({n})", n=self._n_marcadas))
        self.boton_resultado.setText(t("Donde farmear"))
        self._temporizador.start()

    def _estado_pieza(self, pieza: dict, objetivo) -> tuple[str | None, str]:
        """('conseguido' | 'tienes' | None, pista para el tooltip)."""
        if objetivo is not None and objetivo.completado:
            return "conseguido", t("Objetivo completado: ya no cuenta para el resultado")
        lectura = estado_inventario.cantidad_de(self.usuario, pieza["unique_name"])
        if lectura is not None and lectura.cantidad >= (pieza.get("item_count") or 1):
            return "tienes", t("Tienes {n}", n=lectura.cantidad)
        return None, ""

    # -- resultado ---------------------------------------------------------------------

    def calcular(self) -> dict:
        """Reliquias y misiones para lo marcado que falta (sin los objetivos completados)."""
        refinamiento = self.refinamiento.currentData() or ruta_prime.REFINAMIENTO_POR_DEFECTO
        escuadra = self.escuadra.currentData() or ruta_prime.ESCUADRA_POR_DEFECTO
        marcadas = self.marcadas()
        faltan = [p for p in marcadas if not p["objetivo"].completado]
        reliquias = misiones = []
        if self.indice is not None and faltan:
            reliquias = ruta_prime.reliquias_para(self.indice, [p["id"] for p in faltan], refinamiento)
            misiones = ruta_prime.misiones_para(self.indice, reliquias, escuadra, cache=self._cache_misiones)
        disponibles = {pid for r in reliquias if not r["vaulted"] for pid in r["piezas"]}
        return {
            "refinamiento": refinamiento,
            "escuadra": escuadra,
            "marcadas": marcadas,
            "faltan": faltan,
            "reliquias": reliquias,
            "misiones": misiones,
            "solo_boveda": [p for p in faltan if p["id"] not in disponibles],
        }

    def _pintar_resultado(self) -> None:
        posicion = self.resultado.verticalScrollBar().value()
        self.resultado.setHtml(self.html_resultado(self.calcular()))
        self.resultado.verticalScrollBar().setValue(posicion)

    def html_resultado(self, datos: dict) -> str:
        p = PALETA
        self.resultado.sitios = {}
        if self.indice is None:
            return f"<p style='color:{p['suave']}'>{html.escape(t('Preparando los datos...'))}</p>"
        if not datos["marcadas"]:
            return (
                f"<p style='color:{p['suave']}'>"
                + html.escape(t("Marca en la rejilla las piezas que quieres: aqui saldran las reliquias "
                                "que las contienen y las misiones donde farmearlas, de menos a mas tiempo."))
                + "</p>"
            )
        nombres = {p_["id"]: self.nombre_pieza(p_) for p_ in datos["marcadas"]}
        partes = [
            f"<div style='color:{p['suave']}'>"
            + html.escape(t("Piezas por conseguir: {n}", n=len(datos["faltan"])))
            + " &middot; " + glosario.enlace("radshare" if datos["escuadra"] > 1 else "refinamiento",
                                             texto_modo(datos["refinamiento"], datos["escuadra"]), p["texto"])
            + "</div>"
        ]
        completadas = [x for x in datos["marcadas"] if x["objetivo"].completado]
        if completadas:
            partes.append(
                f"<div style='color:{COLOR_DISPONIBLE};font-size:12px'>"
                + html.escape(t("Ya conseguido (no cuenta): {lista}",
                                lista=", ".join(nombres[x["id"]] for x in completadas)))
                + "</div>"
            )
        if not datos["faltan"]:
            return "".join(partes)
        if datos["solo_boveda"]:
            partes.append(_tarjeta(
                glosario.enlace("boveda", t("En boveda: solo por intercambio, Baro Ki'Teer o Prime Resurgence"),
                                COLOR_BOVEDA)
                + f"<div style='color:{p['texto']};margin-top:2px'>"
                + html.escape(", ".join(nombres[x["id"]] for x in datos["solo_boveda"])) + "</div>",
                COLOR_BOVEDA,
            ))
        partes.append(self._html_reliquias(datos, nombres))
        partes.append(self._html_misiones(datos, nombres))
        partes.append(
            f"<div style='color:{p['suave']};font-size:12px;margin:6px 0 4px 4px'>"
            + html.escape(t(
                "Tiempo medio hasta la siguiente pieza de las marcadas: lo que tarda en caer una reliquia "
                "util en esa mision, mas una fisura de ~{fisura} min para abrirla, por las reliquias que hay "
                "que abrir de media. En escuadra de 4 compartiendo reliquia cada fisura gasta una reliquia "
                "tuya y da cuatro tiradas. No cuenta refinar (Trazas del Vacio). Las duraciones son una "
                "estimacion para un jugador medio.", fisura=f"{round(eficiencia.minutos_fisura(), 1):g}"))
            + "</div>"
        )
        return "".join(partes)

    def _html_misiones(self, datos: dict, nombres: dict[int, str]) -> str:
        p = PALETA
        misiones = datos["misiones"]
        if not misiones:
            return _seccion(t("Donde farmear")) + (
                f"<p style='color:{p['suave']}'>"
                + html.escape(t("Ninguna reliquia fuera de boveda cae en una mision que se pueda estimar."))
                + "</p>"
            )
        visibles = misiones[:MAX_MISIONES]
        modo = texto_modo(datos["refinamiento"], datos["escuadra"])
        referencia = relleno_filas.escala(m["minutos"] for m in visibles)
        filas = []
        for i, m in enumerate(visibles):
            self.resultado.sitios[i] = m["sitios"]
            extra = len(m["sitios"]) - 1
            sitio = f"<b>{enlaces_wiki.donde(m, p['texto'])}</b>"
            ancla = relleno_filas.marca(relleno_filas.fraccion(m["minutos"], referencia))
            if ancla:
                sitio = f"<a name='{ancla}'>{sitio}</a>"
            if extra > 0:
                sitio += (f" <a href='sitios:{i}' style='color:{p['suave']};text-decoration:none'>"
                          f"(+{extra})</a>")
            detalle = " &middot; ".join(x for x in (_mision(m, p["suave"]), _rotacion(m, p["suave"])) if x)
            if m.get("nivel_min") is not None:
                detalle += f" &middot; {m['nivel_min']}-{m['nivel_max']}"
            reliquias = ", ".join(_enlace_reliquia(r, p["suave"]) for r in m["reliquias"][:4])
            if len(m["reliquias"]) > 4:
                reliquias += f" +{len(m['reliquias']) - 4}"
            filas.append(
                f"<tr><td width='4' style='background:{p['acento']}'></td>"
                f"<td>{sitio}<br><span style='color:{p['suave']};font-size:12px'>{detalle}</span></td>"
                f"<td style='font-size:12px'>{reliquias}</td>"
                f"<td align='right'><b>{m['probabilidad']:.1f}%</b></td>"
                f"<td align='right'>{_tiempo(m['minutos'], p['texto'], detalle=desglose_tiempo.texto_prime(m, datos['escuadra'], modo))}</td></tr>"
            )
        if len(misiones) > MAX_MISIONES:
            filas.append(
                f"<tr><td colspan='5' style='color:{p['suave']}'>"
                + html.escape(t("y {n} sitios mas, con mas tiempo", n=len(misiones) - MAX_MISIONES))
                + "</td></tr>"
            )
        cabecera = (
            f"<tr style='color:{p['suave']};font-size:11px'><td></td><td>{html.escape(t('Sitio'))}</td>"
            f"<td>{html.escape(t('Reliquias'))}</td><td align='right'>{html.escape(t('Alguna'))}</td>"
            f"<td align='right'>{html.escape(t('Hasta la pieza'))}</td></tr>"
        )
        return _seccion(t("Donde farmear")) + (
            f"<table width='100%' cellspacing='0' cellpadding='5' style='background:{p['panel2']}'>"
            + cabecera + "".join(filas) + "</table>"
        ) + enlaces_wiki.linea(visibles, p["suave"], p["acento"])

    def _html_reliquias(self, datos: dict, nombres: dict[int, str]) -> str:
        p = PALETA
        reliquias = datos["reliquias"]
        if not reliquias:
            return ""
        refinamiento = texto_refinamiento(datos["refinamiento"])
        disponibles = [r for r in reliquias if not r["vaulted"]]
        boveda = [r for r in reliquias if r["vaulted"]]
        filas = []
        for r in disponibles[:MAX_RELIQUIAS]:
            color = COLOR_DISPONIBLE
            estado = glosario.enlace("boveda", t("disponible"), color)
            piezas = ", ".join(
                f"{html.escape(nombres.get(pid, str(pid)))} <span style='color:{p['suave']}'>{prob:.1f}%</span>"
                for pid, prob in sorted(r["piezas"].items(), key=lambda x: -x[1])
            )
            filas.append(
                f"<tr><td width='4' style='background:{color}'></td>"
                # Una sola linea por reliquia: en la ventana minima las misiones tienen que asomar.
                f"<td>{_enlace_reliquia(r, p['texto'])} <span style='font-size:12px'>{estado}</span></td>"
                f"<td style='font-size:12px'>{piezas}</td>"
                f"<td align='right'><b>{r['probabilidad']:.1f}%</b></td></tr>"
            )
        if len(disponibles) > MAX_RELIQUIAS:
            filas.append(
                f"<tr><td colspan='4' style='color:{p['suave']}'>"
                + html.escape(t("y {n} reliquias mas", n=len(disponibles) - MAX_RELIQUIAS))
                + "</td></tr>"
            )
        if boveda:
            # Las de boveda no se farmean: una sola linea, para que no empujen las misiones.
            nombres_boveda = ", ".join(_enlace_reliquia(r, p["suave"]) for r in boveda[:12])
            if len(boveda) > 12:
                nombres_boveda += f" +{len(boveda) - 12}"
            filas.append(
                f"<tr><td width='4' style='background:{COLOR_BOVEDA}'></td><td colspan='3' "
                f"style='font-size:12px'>"
                + glosario.enlace("boveda", t("En boveda ({n}), no entran en el orden:", n=len(boveda)), COLOR_BOVEDA)
                + f" {nombres_boveda}</td></tr>"
            )
        titulo = t("Reliquias ({refinamiento})", refinamiento=refinamiento)
        return _seccion(titulo) + (
            f"<table width='100%' cellspacing='0' cellpadding='5' style='background:{p['panel2']}'>"
            + "".join(filas) + "</table>"
        )

    def _enlace(self, url: QUrl) -> None:
        texto = url.toString()
        if glosario.mostrar(texto, self.resultado):
            return
        if texto.startswith("sitios:"):
            lista = self.resultado.sitios.get(int(texto.removeprefix("sitios:")), [])
            QToolTip.showText(QCursor.pos(), "\n".join(lista), self.resultado)
        elif texto.startswith("item:"):
            self.abrir_item.emit(int(texto.removeprefix("item:")))
        elif texto.startswith("http"):
            # Los nodos y los tipos de mision enlazan a la wiki: solo al pulsar.
            QDesktopServices.openUrl(QUrl(texto))
