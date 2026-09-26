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

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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
    QWidgetItem,
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
CLAVE_ORDEN = "primes_orden"
# Como se pueden ordenar los sets (clave -> texto). Los genericos van siempre aparte, al final.
ORDENES = (
    ("nombre", "Por nombre"),
    ("marcados", "Marcados primero"),
    ("buscadas", "Mas piezas en busqueda"),
    ("recientes", "Mas recientes"),
    ("conseguidos", "Recien conseguidos"),
)
# Ancho de las tarjetas: el del texto mas largo, pero dentro de estos limites, para que
# la rejilla sea como una hoja de calculo y no cada caja de un tamano.
ANCHO_CAJA_MIN = 230
ANCHO_CAJA_MAX = 360
# Cuanto se queda desactivado "Incluir lo que esta en boveda" tras cargar, como minimo.
MS_ESPERA_BOVEDA = 400


def es_generico(nombre_en: str) -> bool:
    """Forma, Adaptadores Exilus y demas: salen de reliquias pero no son de un set Prime."""
    return "prime" not in (nombre_en or "").lower()


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
        # Con ancho de celda, todas las cajas miden lo mismo y forman columnas; a 0,
        # cada una mide lo que pida (como antes).
        self.ancho_min = 0
        self.ancho_max = 0
        self.setContentsMargins(0, 0, 0, 0)

    def reordenar(self, widgets) -> None:
        """Cambia el orden sin rehacer los widgets (que ya son hijos del contenedor)."""
        self._items = [QWidgetItem(w) for w in widgets]
        self.invalidate()

    def celda(self, ancho_zona: int) -> tuple[int, int]:
        """(columnas, ancho de cada celda) para un ancho disponible."""
        if not self.ancho_min:
            return 0, 0
        columnas = max(1, (ancho_zona + self._espacio) // (self.ancho_min + self._espacio))
        ancho = (ancho_zona - (columnas - 1) * self._espacio) // columnas
        tope = self.ancho_max or ancho
        return columnas, max(min(ancho, tope), min(self.ancho_min, ancho_zona))

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
        if self.ancho_min:
            return self._colocar_en_rejilla(rect, prueba)
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

    def _colocar_en_rejilla(self, rect: QRect, prueba: bool) -> int:
        """Celdas del mismo ancho en columnas; las de una fila, todas de la misma altura.

        Un widget con la propiedad `fila_entera` (las cabeceras) ocupa una fila el solo.
        """
        m = self.contentsMargins()
        zona = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        columnas, ancho = self.celda(zona.width())
        filas: list[tuple[bool, list]] = []
        actual: list = []
        for item in self._items:
            if item.isEmpty():
                continue
            widget = item.widget()
            if widget is not None and widget.property("fila_entera"):
                if actual:
                    filas.append((False, actual))
                    actual = []
                filas.append((True, [item]))
                continue
            actual.append(item)
            if len(actual) == columnas:
                filas.append((False, actual))
                actual = []
        if actual:
            filas.append((False, actual))
        y = zona.y()
        for entera, items in filas:
            if entera:
                item = items[0]
                alto = item.heightForWidth(zona.width()) if item.hasHeightForWidth() else item.sizeHint().height()
                if not prueba:
                    item.setGeometry(QRect(zona.x(), y, zona.width(), alto))
            else:
                alto = max(item.sizeHint().height() for item in items)
                if not prueba:
                    for i, item in enumerate(items):
                        item.setGeometry(QRect(zona.x() + i * (ancho + self._espacio), y, ancho, alto))
            y += alto + self._espacio
        if filas:
            y -= self._espacio
        return y - rect.y() + m.bottom()


class CajaPrime(QFrame):
    """Un objeto prime (o los sueltos) con una casilla por pieza."""

    marcada = Signal(dict, bool)

    def __init__(self, titulo: str, piezas: list[dict], objeto: dict | None = None, columnas: int = 1,
                 parent=None, nombres: dict[str, str] | None = None):
        super().__init__(parent)
        self.setObjectName("cajaPrime")
        self.objeto = objeto
        self.piezas = piezas
        # unique_name -> texto de la casilla, cuando no basta con el nombre de la pieza
        # (en los genericos, "Plano" solo no dice de que es).
        self.nombres = nombres or {}
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
        # En una fila todas las cajas miden lo mismo: lo que sobra, abajo.
        caja.addStretch(1)
        # Texto para el filtro: el objeto y sus piezas en los dos idiomas del indice.
        partes = [titulo]
        if objeto:
            partes += [objeto["nombre_en"], objeto["nombre_es"] or ""]
        for pieza in piezas:
            partes += [pieza["nombre_en"], pieza["nombre_es"] or ""]
        partes += list(self.nombres.values())
        self.texto_filtro = normalizar(" ".join(partes))

    def pintar(self, estados: dict[str, tuple[bool, str | None, str]], maestria: str = "") -> None:
        """estados: unique_name -> (marcada, estado 'conseguido'/'tienes'/None, pista)."""
        p = PALETA
        alguna = False
        for unico, casilla in self.casillas.items():
            pieza = next(x for x in self.piezas if x["unique_name"] == unico)
            marcada, estado, pista = estados.get(unico, (False, None, ""))
            alguna = alguna or marcada
            texto = self.nombres.get(unico) or nombre_idioma(pieza)
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
        self._cargando_boveda = False
        self.orden = QComboBox()
        self.orden.currentIndexChanged.connect(self._cambiar_orden)
        self.limpiar = QPushButton()
        self.limpiar.clicked.connect(self._desmarcar_todo)
        barra_rejilla = QHBoxLayout()
        barra_rejilla.setSpacing(6)
        barra_rejilla.addWidget(self.filtro, 1)
        barra_rejilla.addWidget(self.orden)
        barra_rejilla.addWidget(self.incluir_boveda)
        barra_rejilla.addWidget(self.limpiar)

        self.contenido = QWidget()
        self.fluida = DisposicionFluida(self.contenido)
        self._cabeceras: dict[str, QLabel] = {}
        self._fechas: dict[int, str] | None = None
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
        self._fechas = None
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
        if not self._cargando_boveda:
            self.incluir_boveda.setText(t("Incluir lo que esta en boveda"))
        self.limpiar.setText(t("Desmarcar todo"))
        self._rellenar_orden()
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
            # Las cabeceras se reutilizan: fuera de la rejilla, pero vivas.
            if viejo and viejo not in self._cabeceras.values():
                # Fuera ya, no al volver al bucle de eventos: si no, se pintan encima.
                viejo.hide()
                viejo.setParent(None)
                viejo.deleteLater()
        self._cajas = []
        self._cajas_sets: list[CajaPrime] = []
        self._cajas_genericas: list[CajaPrime] = []
        incluir = self.incluir_boveda.isChecked()
        genericos: list[dict] = []  # objetos que no son un set Prime (Adaptador Exilus...)
        for o in self._objetos:
            if o["en_boveda"] and not incluir:
                continue
            piezas = [p for p in o["piezas"] if incluir or not p["en_boveda"]]
            if es_generico(o["nombre_en"]):
                genericos.append({**o, "piezas": piezas})
                continue
            caja = CajaPrime(nombre_idioma(o), piezas, o)
            caja.marcada.connect(self._marcar)
            self._cajas_sets.append(caja)
        # Genericos: Formas y Adaptadores Exilus juntos, y lo demas (Kuva, mods de Requiem...)
        # en "Otros objetos de reliquia". Ninguno es de un set: van aparte, al final.
        sueltos = [p for p in self._sueltos if incluir or not p["en_boveda"]]
        formas = [p for p in sueltos if "forma" in p["nombre_en"].lower()]
        otros = [p for p in sueltos if p not in formas]
        nombres: dict[str, str] = {}
        piezas_formas = list(formas)
        for o in genericos:
            if "exilus" in o["nombre_en"].lower() or "forma" in o["nombre_en"].lower():
                for pieza in o["piezas"]:
                    nombres[pieza["unique_name"]] = f"{nombre_idioma(o)}: {nombre_idioma(pieza)}"
                    piezas_formas.append(pieza)
            else:
                caja = CajaPrime(nombre_idioma(o), o["piezas"], o)
                caja.marcada.connect(self._marcar)
                self._cajas_genericas.append(caja)
        if piezas_formas:
            caja = CajaPrime(t("Formas y Adaptadores Exilus"), piezas_formas, None, nombres=nombres)
            caja.marcada.connect(self._marcar)
            self._cajas_genericas.insert(0, caja)
        if otros:
            caja = CajaPrime(t("Otros objetos de reliquia"), otros, None, columnas=4)
            # Muchas cosas sueltas: ocupa la fila entera en vez de ensanchar todas las celdas.
            caja.setProperty("fila_entera", True)
            caja.marcada.connect(self._marcar)
            self._cajas_genericas.append(caja)
        # Los genericos primero en la lista (los busca quien quiera "los sueltos"), aunque
        # en pantalla vayan al final.
        self._cajas = self._cajas_genericas + self._cajas_sets
        for clave in ("sets", "genericos"):
            if clave not in self._cabeceras:
                cabecera = QLabel()
                cabecera.setProperty("fila_entera", True)
                cabecera.setTextFormat(Qt.RichText)
                self._cabeceras[clave] = cabecera
        self._pintar_cabeceras()
        self._colocar_cajas()
        self._aplicar_filtro()
        self.refrescar_marcas()
        self._ajustar_celdas()

    def _pintar_cabeceras(self) -> None:
        p = PALETA
        textos = {
            "sets": t("Sets Prime ({n})", n=len(getattr(self, "_cajas_sets", []))),
            "genericos": t("Objetos genericos: no son de ningun set"),
        }
        for clave, cabecera in self._cabeceras.items():
            cabecera.setText(
                f"<span style='color:{p['acento']};font-size:12px;font-weight:bold;letter-spacing:1px'>"
                f"{html.escape(textos[clave].upper())}</span>"
            )

    def _colocar_cajas(self) -> None:
        """Pone las cajas en la rejilla en el orden elegido; los genericos, aparte y al final."""
        if not hasattr(self, "_cajas_sets"):
            return
        orden = self._orden_sets()
        widgets: list[QWidget] = []
        if self._cajas_sets:
            widgets.append(self._cabeceras["sets"])
            widgets += orden
        if self._cajas_genericas:
            widgets.append(self._cabeceras["genericos"])
            widgets += self._cajas_genericas
        for clave, cabecera in self._cabeceras.items():
            if cabecera not in widgets:
                cabecera.hide()
        self.fluida.reordenar(widgets)
        for w in widgets:
            if w.parent() is not self.contenido:
                w.setParent(self.contenido)
        self._aplicar_filtro()

    def _ajustar_celdas(self) -> None:
        """Ancho de celda: el de la caja mas ancha, entre un minimo y un maximo."""
        if not self._cajas:
            return
        normales = [c for c in self._cajas if not c.property("fila_entera")]
        if not normales:
            return
        ancho = max(c.sizeHint().width() for c in normales)
        self.fluida.ancho_min = max(ANCHO_CAJA_MIN, min(ANCHO_CAJA_MAX, ancho))
        self.fluida.ancho_max = int(self.fluida.ancho_min * 1.3)
        self.fluida.invalidate()

    # -- orden de los sets ------------------------------------------------------------

    def _rellenar_orden(self) -> None:
        actual = self.orden.currentData() or self.config.get(CLAVE_ORDEN) or "nombre"
        self.orden.blockSignals(True)
        self.orden.clear()
        for clave, texto in ORDENES:
            self.orden.addItem(t(texto), clave)
        self.orden.setCurrentIndex(max(0, self.orden.findData(actual)))
        self.orden.setToolTip(t("Como ordenar los sets. Los objetos genericos van siempre al final."))
        self.orden.blockSignals(False)

    def _cambiar_orden(self, *_):
        self.config[CLAVE_ORDEN] = self.orden.currentData() or "nombre"
        guardar(self.config)
        self._colocar_cajas()

    def showEvent(self, evento):  # noqa: N802 - firma de Qt
        super().showEvent(evento)
        # Lo marcado o conseguido desde otra pestana cambia el orden: se aplica al volver
        # (no mientras se marca aqui, para que la caja no salte debajo del raton).
        if (self.orden.currentData() or "nombre") != "nombre":
            self._colocar_cajas()

    def fechas_salida(self) -> dict[int, str]:
        """id del objeto -> fecha de salida ('2026-09-23'); vacio con un indice sin esas fechas."""
        if self._fechas is None:
            self._fechas = {}
            if self.indice is not None:
                try:
                    self._fechas = {
                        fila[0]: fila[1]
                        for fila in self.indice.execute(
                            "SELECT id, fecha_salida FROM items WHERE fecha_salida IS NOT NULL")
                    }
                except sqlite3.Error:
                    # Indice de antes de guardar fechas: se ordena por nombre.
                    self._fechas = {}
        return self._fechas

    def _conseguidos(self) -> dict[str, str]:
        """unique_name -> cuando se consiguio por ultima vez (objetivo completado o reliquia)."""
        salida: dict[str, str] = {}
        consultas = (
            "SELECT item_unique_name, completado_en FROM objetivos WHERE completado_en IS NOT NULL",
            "SELECT elegido_unique_name, MAX(leido_en) FROM historial_recompensas "
            "WHERE elegido_unique_name IS NOT NULL GROUP BY elegido_unique_name",
        )
        for consulta in consultas:
            try:
                for unico, cuando in self.usuario.execute(consulta):
                    if unico and cuando and cuando > salida.get(unico, ""):
                        salida[unico] = cuando
            except sqlite3.Error:
                continue
        return salida

    def _orden_sets(self) -> list[CajaPrime]:
        cajas = sorted(self._cajas_sets, key=lambda c: normalizar(c._titulo))
        orden = self.orden.currentData() or "nombre"
        if orden == "nombre":
            return cajas
        if orden in ("marcados", "buscadas"):
            objetivos = self._objetivos()

            def cuenta(caja: CajaPrime) -> tuple[int, int]:
                marcadas = [objetivos[p["unique_name"]] for p in caja.piezas if p["unique_name"] in objetivos]
                return len(marcadas), sum(1 for o in marcadas if not o.completado)

            if orden == "marcados":
                return sorted(cajas, key=lambda c: cuenta(c)[0] == 0)
            return sorted(cajas, key=lambda c: -cuenta(c)[1])
        if orden == "recientes":
            fechas = self.fechas_salida()
            con_fecha = [c for c in cajas if fechas.get(c.objeto["id"])]
            sin_fecha = [c for c in cajas if not fechas.get(c.objeto["id"])]
            return sorted(con_fecha, key=lambda c: fechas[c.objeto["id"]], reverse=True) + sin_fecha
        if orden == "conseguidos":
            cuando = self._conseguidos()

            def ultimo(caja: CajaPrime) -> str:
                return max((cuando.get(p["unique_name"], "") for p in caja.piezas), default="")

            con = [c for c in cajas if ultimo(c)]
            return sorted(con, key=ultimo, reverse=True) + [c for c in cajas if not ultimo(c)]
        return cajas

    def _aplicar_filtro(self) -> None:
        texto = normalizar(self.filtro.text())
        for caja in self._cajas:
            caja.setVisible(not texto or all(palabra in caja.texto_filtro for palabra in texto.split()))
        # Una cabecera sin ninguna caja debajo sobra.
        for clave, cajas in (("sets", getattr(self, "_cajas_sets", [])),
                             ("genericos", getattr(self, "_cajas_genericas", []))):
            if clave in self._cabeceras:
                self._cabeceras[clave].setVisible(any(not c.isHidden() for c in cajas))
        self.fluida.invalidate()

    def _cambiar_boveda(self, marcado: bool) -> None:
        """Rehace la rejilla con (o sin) lo de boveda, sin dejar que se lance dos veces.

        En un equipo lento tarda: si el usuario vuelve a pulsar porque parece que no
        responde, esos clics llegan con la casilla desactivada y Qt los descarta.
        """
        if self._cargando_boveda:
            return
        self._cargando_boveda = True
        self.config[CLAVE_BOVEDA] = marcado
        guardar(self.config)
        self.incluir_boveda.setEnabled(False)
        self.incluir_boveda.setText(t("Cargando, espera..."))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # Que se vea el "Cargando" antes de ponerse a trabajar.
            self.incluir_boveda.repaint()
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
            self._construir_rejilla()
            # Los clics que se hayan acumulado mientras tanto llegan ahora, con la
            # casilla todavia desactivada: se pierden, que es lo que se quiere.
            QApplication.processEvents()
        finally:
            QApplication.restoreOverrideCursor()
            self._cargando_boveda = False
        QTimer.singleShot(MS_ESPERA_BOVEDA, self._boveda_lista)

    def _boveda_lista(self) -> None:
        if self._cargando_boveda:
            return
        self.incluir_boveda.setText(t("Incluir lo que esta en boveda"))
        self.incluir_boveda.setEnabled(True)

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
