"""Pestana Objetivos: lo que estas farmeando y por donde conseguirlo (estilo C).

Se organiza como pidio un tester: Sin empezar / En progreso / Completados, filtro por
categoria, lo mas reciente arriba y de diez en diez. Los sets son un solo panel que se
despliega con un clic, y las armas con receta se pueden abrir para marcar cada recurso de
fabricacion por separado. El contador nunca pasa de la meta.

A la derecha, la caja "Para esto te sirve hoy": las fisuras, invasiones, alertas y lo de
Baro que ahora mismo te acercan a tus objetivos (lo mismo que calculan Mundo y el Tablero).
"""

from __future__ import annotations

import html
import sqlite3

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config as config_farmadex
from ..datos import eficiencia
from ..datos import indice as indice_datos
from ..estado import objetivos as estado_objetivos
from ..estado import usuario_db
from ..estado.objetivos import COMPLETADOS, EN_PROGRESO, ESTADOS, MAX_CANTIDAD, SIN_EMPEZAR
from ..idiomas import es_castellano, nombre as nombre_idioma, t
from ..registro_log import obtener
from . import glosario, pestana_tablero, widgets
from .estilo_c import (
    COLOR_ERA,
    ESPACIO,
    BarraFina,
    BotonC,
    BotonGlifo,
    CasillaRombo,
    DesplegableC,
    EtiquetaC,
    Insignia,
    PanelC,
    PiezaC,
    Rombo,
    color,
    columna,
    fila,
    hex_de,
    px,
    ruta_chaflan,
    transparente,
)
from .widgets import COLOR_BOVEDA, PALETA

log = obtener("objetivos_ui")

# Ancho de la columna de la derecha (anadir, "Para esto te sirve hoy", ayuda) y ancho de
# pagina por debajo del cual se esconde para dejar sitio a las filas.
ANCHO_LATERAL = 340
ANCHO_SIN_LATERAL = 980
# Lineas como mucho en "Para esto te sirve hoy".
MAX_LINEAS_HOY = 8
ORDEN_ERAS = ("Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia")
# Insignia de cada categoria: texto y color (clave de la paleta).
INSIGNIAS = {
    estado_objetivos.ARMAS: ("Arma", "aviso"),
    estado_objetivos.WARFRAMES: ("Warframe", "secundario"),
    estado_objetivos.RECURSOS: ("Recurso", "acento"),
    estado_objetivos.SETS: ("Pieza", "suave"),
}


def _rotacion(mision: dict, color_texto: str) -> str:
    """'rotacion C' explicando, al pasar el raton, cuando llega en el modo de esa mision."""
    return glosario.enlace_rotacion(
        mision.get("modo"), mision["rotacion"], t("rotación {rot}", rot=mision["rotacion"]), color_texto
    )


def _miles(n: int) -> str:
    """999999 -> '999.999' en castellano, '999,999' en los demas idiomas."""
    texto = f"{n:,}"
    return texto.replace(",", ".") if es_castellano() else texto


def confirmar(parent, titulo: str, texto: str) -> bool:
    """Pregunta Si/No. Los tests la sustituyen para no abrir ventanas."""
    respuesta = QMessageBox.question(
        parent, titulo, texto, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    return respuesta == QMessageBox.Yes


class _SinRuedaSinFoco(QObject):
    """La rueda solo cambia un numero o un desplegable si antes has hecho clic en el.

    Si no, la rueda pasa a la lista y la desplaza, como esperas.
    """

    def eventFilter(self, objeto, evento):  # noqa: N802 - nombre de Qt
        if evento.type() == QEvent.Wheel and not objeto.hasFocus():
            evento.ignore()
            return True
        return False


_FILTRO_RUEDA: _SinRuedaSinFoco | None = None


def _proteger_rueda(control: QWidget) -> None:
    global _FILTRO_RUEDA
    if _FILTRO_RUEDA is None:
        _FILTRO_RUEDA = _SinRuedaSinFoco()
    control.setFocusPolicy(Qt.StrongFocus)
    control.installEventFilter(_FILTRO_RUEDA)


class _Contexto:
    """Lo que la pestana recuerda entre refrescos (las filas se rehacen enteras)."""

    def __init__(self):
        self.pasos: dict[str, int] = {}  # cuantas unidades suma cada clic, por fila
        self.abiertos: set[str] = set()  # sets y recetas desplegados
        self.seleccionados: set[str] = set()  # claves de entrada marcadas para borrar
        # unique_name -> lo que da ahora el mundo (invasion, alerta, Baro), para la fila.
        self.hoy: dict[str, str] = {}
        # Pide la imagen de un objeto para una miniatura (lo pone la pestana).
        self.pedir_imagen = lambda _unico, _miniatura: None
        # Ruta de un objeto (con la cache de la pestana).
        self.ruta = lambda _unico: None


# -- piezas pequenas -------------------------------------------------------------------


class Miniatura(QWidget, PiezaC):
    """Imagen pequena del objeto; sin imagen (o mientras llega), un hueco con esquina cortada."""

    def __init__(self, lado: int = 30, parent=None):
        super().__init__(parent)
        transparente(self)
        self.lado = lado
        self._mapa = None
        self.refrescar_estilo()

    def refrescar_estilo(self) -> None:
        lado = px(self.lado, False)
        self.setFixedSize(lado, lado)
        self.update()

    def poner(self, mapa) -> None:
        self._mapa = mapa if mapa is not None and not mapa.isNull() else None
        self.update()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._mapa is not None:
            mapa = self._mapa.scaled(self.width(), self.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((self.width() - mapa.width()) // 2, (self.height() - mapa.height()) // 2, mapa)
        else:
            r = QRectF(self.rect()).adjusted(3.5, 3.5, -3.5, -3.5)
            p.setPen(QPen(color("borde"), 1.2))
            p.setBrush(color("panel2"))
            p.drawPath(ruta_chaflan(r, 5))
        p.end()


class _Paso(QSpinBox):
    """Cuantas unidades suma cada clic, escrito como "×1" y sin flechas."""

    def __init__(self, valor: int, parent=None):
        super().__init__(parent)
        self.setRange(1, MAX_CANTIDAD)
        self.setValue(max(1, min(valor, MAX_CANTIDAD)))
        self.setPrefix("×")
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setFixedWidth(px(58, False))
        self.setStyleSheet(
            f"QSpinBox {{ background: transparent; border: none; color: {PALETA['suave']};"
            f" font-size: {px(12)}px; padding: 0 2px; }}"
            f" QSpinBox:focus {{ border-bottom: 1px solid {PALETA['acento']}; color: {PALETA['texto']}; }}"
        )
        _proteger_rueda(self)


def _insignia_categoria(categoria: str | None) -> Insignia | None:
    datos = INSIGNIAS.get(categoria or "")
    if not datos:
        return None
    texto, tinta = datos
    return Insignia(t(texto), tinta, tam=10)


def _rotulo_color(texto: str, hex_color: str) -> EtiquetaC:
    """Rotulo en mayusculas de un color propio (el de una era de reliquia, por ejemplo)."""
    etiqueta = EtiquetaC(texto, "dato", mayus=True)
    etiqueta.setStyleSheet(f"color: {hex_color}; background: transparent;")
    return etiqueta


# -- cantidad y dialogo ------------------------------------------------------------------


class ControlCantidad(QWidget):
    """Restar / "X / Y" / sumar y cuanto suma cada clic. Nunca se pasa de la meta.

    `cambio` lleva lo que hay que sumar, ya recortado a 0..meta. Si ya estas en la
    meta y pulsas sumar, sale `ampliar` con las unidades: quien lo use pide confirmacion.
    """

    cambio = Signal(int)
    ampliar = Signal(int)

    def __init__(self, actual: int, meta: int, clave: str, contexto: _Contexto,
                 ancho_barra: int = 0, parent=None, mostrar_paso: bool = True):
        super().__init__(parent)
        transparente(self)
        self.actual, self.meta = actual, max(1, meta)
        self._clave, self._contexto = clave, contexto

        self.menos = BotonC("", icono="menos", tam=11)
        self.mas = BotonC("", icono="mas", tam=11)
        lleno = actual >= self.meta
        self.cuenta = EtiquetaC(f"{_miles(actual)} / {_miles(self.meta)}", "dato",
                                tinta="acento" if lleno else "texto")
        self.cuenta.setAlignment(Qt.AlignCenter)
        self.cuenta.setMinimumWidth(px(max(64, ancho_barra // 3), False))
        self.paso = _Paso(contexto.pasos.get(clave, 1))
        self.paso.setToolTip(t("Cuántas unidades suma o resta cada clic (de 1 a {max}).",
                               max=_miles(MAX_CANTIDAD)))
        self.paso.setAccessibleName(t("Cantidad por clic"))
        self.paso.valueChanged.connect(lambda v: contexto.pasos.__setitem__(clave, v))
        self.paso.setVisible(mostrar_paso)

        self.menos.setEnabled(actual > 0)
        self.menos.setToolTip(t("Restar"))
        self.mas.setToolTip(
            t("Ya llegaste a la meta. Pulsa si quieres ampliarla.") if lleno
            else t("Sumar (sin pasar de la meta)")
        )
        self.menos.clicked.connect(self._restar)
        self.mas.clicked.connect(self._sumar)

        caja = QHBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(px(6, False))
        caja.addWidget(self.menos)
        caja.addWidget(self.cuenta)
        caja.addWidget(self.mas)
        caja.addWidget(self.paso)

    def _sumar(self) -> None:
        paso = self.paso.value()
        if self.actual >= self.meta:
            self.ampliar.emit(paso)
        else:
            self.cambio.emit(min(paso, self.meta - self.actual))

    def _restar(self) -> None:
        if self.actual > 0:
            self.cambio.emit(-min(self.paso.value(), self.actual))


class DialogoCantidad(QDialog):
    """Meta y lo que ya tienes, con los limites a la vista."""

    def __init__(self, nombre: str, meta: int, actual: int, en_inventario: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Editar objetivo"))
        self.meta = QSpinBox()
        self.meta.setRange(1, MAX_CANTIDAD)
        self.meta.setValue(max(1, min(meta, MAX_CANTIDAD)))
        self.actual = QSpinBox()
        self.actual.setRange(0, self.meta.value())
        self.actual.setValue(max(0, min(actual, self.meta.value())))
        for control in (self.meta, self.actual):
            control.setMinimumWidth(110)
            control.setGroupSeparatorShown(True)
            _proteger_rueda(control)
        # Lo que tienes nunca puede pasar de la meta: su maximo sigue a la meta.
        self.meta.valueChanged.connect(self.actual.setMaximum)

        titulo = EtiquetaC(nombre, "seccion")
        form = QFormLayout()
        form.addRow(t("Quiero conseguir"), self.meta)
        form.addRow("", self._nota(t("Mínimo 1, máximo {max}.", max=_miles(MAX_CANTIDAD))))
        form.addRow(t("Ya tengo"), self.actual)
        form.addRow("", self._nota(t("De 0 hasta lo que quieres conseguir.")))

        caja = QVBoxLayout(self)
        caja.addWidget(titulo)
        caja.addLayout(form)
        self.usar_inventario = None
        if en_inventario is not None:
            linea = QHBoxLayout()
            linea.addWidget(self._nota(t("Tu inventario dice que tienes {n}.", n=_miles(en_inventario))), 1)
            self.usar_inventario = BotonC(t("Usar ese número"))
            self.usar_inventario.clicked.connect(
                lambda: self.actual.setValue(min(en_inventario, self.meta.value()))
            )
            linea.addWidget(self.usar_inventario)
            caja.addLayout(linea)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText(t("Guardar"))
        botones.button(QDialogButtonBox.Cancel).setText(t("Cancelar"))
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        caja.addWidget(botones)

    @staticmethod
    def _nota(texto: str) -> QLabel:
        return EtiquetaC(texto, "pequeno", envolver=True)

    def valores(self) -> tuple[int, int]:
        return self.meta.value(), min(self.actual.value(), self.meta.value())


# -- filas -------------------------------------------------------------------------------


def _panel_fila(clicable: bool = False, dentro: bool = False) -> PanelC:
    """El recuadro de una fila: esquinas cortadas, sin remate (lo lleva la fila abierta)."""
    panel = PanelC(remate=False, fondo="panel2" if not dentro else "panel", clicable=clicable,
                   chaflan=10 if dentro else 12)
    m = px(10, False)
    panel.capa.setContentsMargins(m, px(6, False), m, px(6, False))
    panel.capa.setSpacing(px(4, False))
    return panel


class FilaRecurso(QWidget):
    """Un recurso de fabricacion dentro de un objetivo: 300 / 300 Rubedo."""

    cambiado = Signal()

    def __init__(self, objetivo, recurso, usuario, contexto: _Contexto, parent=None):
        super().__init__(parent)
        transparente(self)
        self.objetivo, self.recurso, self.usuario = objetivo, recurso, usuario
        nombre = (recurso.nombre_es or recurso.nombre_en) if es_castellano() else (recurso.nombre_en or recurso.nombre_es)
        self.miniatura = Miniatura(22)
        contexto.pedir_imagen(recurso.unique_name, self.miniatura)
        self.etiqueta = EtiquetaC(nombre or "", "normal", recortar=True)
        self.etiqueta.setMinimumWidth(px(120, False))
        self.barra = BarraFina(recurso.actual / max(1, recurso.necesario),
                               tinta="ok" if recurso.completado else "acento", alto=3)
        self.barra.setMinimumWidth(px(90, False))
        self.barra.setMaximumWidth(px(160, False))
        self.tienes = EtiquetaC(
            t("(tienes {n})", n=_miles(recurso.en_inventario)) if recurso.en_inventario is not None else "",
            "pequeno", tinta="tenue")

        self.control = ControlCantidad(
            recurso.actual, recurso.necesario, f"r:{objetivo.id}:{recurso.unique_name}", contexto
        )
        self.control.cambio.connect(self._sumar)
        # Un recurso no se amplia: lo que pide la receta es lo que pide.
        self.control.ampliar.connect(lambda _n: None)
        if recurso.completado:
            self.control.mas.setToolTip(t("Ya tienes todo lo que pide la receta."))
        self.listo = BotonC(t("Listo"), principal=recurso.completado, tinta="ok" if recurso.completado else "acento",
                            tam=11)
        self.listo.setToolTip(t("Ya tienes todo lo que pide la receta.") if recurso.completado
                              else t("Marcar este recurso como conseguido entero"))
        self.listo.clicked.connect(self._listo)

        caja = QHBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(px(8, False))
        caja.addWidget(self.miniatura)
        caja.addWidget(self.etiqueta, 2)
        caja.addWidget(self.barra, 2)
        caja.addWidget(self.tienes, 1)
        caja.addWidget(self.control)
        caja.addWidget(self.listo)

    def _sumar(self, cantidad: int) -> None:
        estado_objetivos.sumar_recurso(self.usuario, self.objetivo, self.recurso, cantidad)
        self.cambiado.emit()

    def _listo(self) -> None:
        if self.recurso.completado:
            return
        estado_objetivos.fijar_recurso(self.usuario, self.objetivo, self.recurso, self.recurso.necesario)
        self.cambiado.emit()


class FilaObjetivo(QWidget):
    """Un objetivo: su recuadro con nombre, ruta y botones y, si tiene receta, el panel
    de recursos de fabricacion debajo (abierto con la flecha o con un clic en la fila)."""

    cambiada = Signal()
    abrir_item = Signal(str)
    seleccion = Signal(str, bool)

    def __init__(self, objetivo, ruta, usuario, parent=None, *, indice=None,
                 contexto: _Contexto | None = None, seleccionable: bool = True, dentro_de_set: bool = False):
        super().__init__(parent)
        transparente(self)
        self.objetivo = objetivo
        self.usuario = usuario
        self.indice = indice
        self.contexto = contexto or _Contexto()
        self.clave = f"o:{objetivo.id}"
        self._clave_recursos = f"rec:{objetivo.id}"
        con_recursos = estado_objetivos.tiene_recursos(indice, objetivo.unique_name)
        abierto = con_recursos and self._clave_recursos in self.contexto.abiertos

        self.panel = _panel_fila(clicable=con_recursos, dentro=dentro_de_set)
        self.panel.poner_marcado(abierto)
        if con_recursos:
            self.panel.pulsado.connect(self._alternar_recursos)

        nombre = objetivo.nombre if dentro_de_set else objetivo.nombre_completo
        if dentro_de_set and objetivo.grupo_nombre and nombre.startswith(objetivo.grupo_nombre + ":"):
            nombre = nombre[len(objetivo.grupo_nombre) + 1:].strip()  # "Sistemas", sin "Ash Prime:"
        self.titulo = EtiquetaC(nombre, "fuerte" if dentro_de_set else "destacado", recortar=True)

        # Delante: casilla para borrar varios y flecha de los recursos.
        self.marcar = None
        delante = []
        if seleccionable:
            self.marcar = CasillaRombo("")
            self.marcar.setToolTip(t("Marcar para borrar varios a la vez"))
            self.marcar.setChecked(self.clave in self.contexto.seleccionados)
            self.marcar.toggled.connect(lambda v: self.seleccion.emit(self.clave, v))
            self.marcar.setFixedWidth(px(18, False))
            delante.append(self.marcar)
        self.boton_recursos = None
        self.panel_recursos = None
        recursos = []
        if con_recursos:
            recursos = estado_objetivos.recursos_de(self.usuario, self.indice, self.objetivo)
            listos = sum(1 for r in recursos if r.completado)
            self.boton_recursos = BotonGlifo(
                "abajo" if abierto else "derecha",
                t("Recursos de fabricación ({listos} de {total} listos)", listos=listos, total=len(recursos)),
                tam=12,
            )
            self.boton_recursos.setToolTip(
                self.boton_recursos.text() + "\n" + t("Abrir para marcar cada recurso por separado"))
            self.boton_recursos.clicked.connect(self._alternar_recursos)
            delante.append(self.boton_recursos)
        elif not dentro_de_set:
            hueco = transparente(QWidget())
            hueco.setFixedWidth(px(24, False))
            delante.append(hueco)

        self.miniatura = Miniatura(26 if dentro_de_set else 30)
        self.contexto.pedir_imagen(objetivo.unique_name, self.miniatura)

        cabeza = [self.titulo]
        if not dentro_de_set:
            insignia = _insignia_categoria(objetivo.categoria)
            if insignia is not None:
                cabeza.append(insignia)
        if objetivo.completado:
            cabeza.append(Insignia(t("Completado"), "ok", tam=10))
        cabeza.append(None)

        self.donde = EtiquetaC(self._texto_ruta(ruta), "pequeno", envolver=True)
        self.donde.setTextFormat(Qt.RichText)
        # El tipo de mision y la rotacion explican el modo al pasar el raton.
        glosario.conectar_etiqueta(self.donde)
        textos = columna(fila(*cabeza, espacio=px(8, False)), self.donde, espacio=px(1, False))
        hoy = self.contexto.hoy.get(objetivo.unique_name)
        self.hoy = None
        if hoy and not objetivo.completado:
            self.hoy = EtiquetaC(hoy, "pequeno", tinta="secundario", envolver=True)
            textos.addWidget(self.hoy)

        self.control = ControlCantidad(objetivo.actual, objetivo.objetivo, self.clave, self.contexto,
                                       mostrar_paso=not dentro_de_set)
        self.control.cambio.connect(self._sumar)
        self.control.ampliar.connect(self._ampliar)

        self.completar = BotonGlifo("hecho", t("Completar"), tinta="ok")
        self.completar.setToolTip(t("Darlo por conseguido entero"))
        self.completar.setEnabled(not objetivo.completado)
        self.completar.clicked.connect(self._completar)
        self.editar = BotonGlifo("editar", t("Editar"))
        self.editar.setToolTip(t("Cambiar cuánto quieres conseguir y cuánto tienes"))
        self.editar.clicked.connect(self._editar)
        self.quitar = BotonGlifo("cerrar", t("Quitar"))
        self.quitar.setToolTip(t("Quitar"))
        self.quitar.clicked.connect(self._borrar)

        self.panel.capa.addLayout(fila(
            *delante, self.miniatura, textos, px(8, False), self.control, px(4, False),
            self.completar, self.editar, self.quitar, espacio=px(6, False),
        ))

        caja = QVBoxLayout(self)
        caja.setContentsMargins(px(28, False) if dentro_de_set else 0, 0, 0, 0)
        caja.setSpacing(px(4, False))
        caja.addWidget(self.panel)
        if con_recursos:
            self._montar_recursos(recursos, abierto)
            caja.addWidget(self.panel_recursos)

    # -- recursos de fabricacion --

    def _montar_recursos(self, recursos, abierto: bool) -> None:
        listos = sum(1 for r in recursos if r.completado)
        self.panel_recursos = PanelC(remate=False, fondo="panel", chaflan=12)
        m = px(ESPACIO["panel_h"], False)
        self.panel_recursos.capa.setContentsMargins(m + px(44, False), px(8, False), m, px(10, False))
        self.panel_recursos.capa.setSpacing(px(6, False))
        self.rotulo_recursos = EtiquetaC(
            t("Recursos de fabricación · {listos} de {total} listos", listos=listos, total=len(recursos)),
            "rotulo", mayus=True)
        self.panel_recursos.capa.addWidget(self.rotulo_recursos)
        if abierto:
            for recurso in recursos:
                linea = FilaRecurso(self.objetivo, recurso, self.usuario, self.contexto)
                linea.cambiado.connect(self.cambiada.emit)
                self.panel_recursos.capa.addWidget(linea)
        self.panel_recursos.setVisible(abierto)

    def _alternar_recursos(self) -> None:
        clave = self._clave_recursos
        if clave in self.contexto.abiertos:
            self.contexto.abiertos.discard(clave)
        else:
            self.contexto.abiertos.add(clave)
        self.cambiada.emit()  # se repinta con el panel abierto o cerrado

    # -- ruta --

    def _texto_ruta(self, ruta) -> str:
        p = PALETA
        if not ruta:
            return t("Sin ruta conocida: puede venir de una misión de historia o del mercado.")
        reliquia = ruta["reliquia"]
        if ruta.get("tipo") != "reliquia" or not reliquia:
            # No sale de reliquias (Rhino cae del Chacal en Fossa): el sitio, tal cual.
            mision = ruta["mision"]
            if not mision:
                return t("Sin ruta conocida: puede venir de una misión de historia o del mercado.")
            trozos = [f"<b>{html.escape(mision.get('donde') or '')}</b>"]
            if mision.get("mision"):
                trozos.append(glosario.enlace_mision(
                    mision.get("modo"), mision["mision"], p["texto"], mision.get("rotacion")))
            if mision.get("rotacion"):
                trozos.append(_rotacion(mision, p["texto"]))
            if ruta.get("probabilidad"):
                trozos.append(f"{ruta['probabilidad']:.1f}%")
            return f"<span style='color:{p['texto']}'>{' &middot; '.join(trozos)}</span>"
        nombre = html.escape(nombre_idioma(reliquia))
        prob = reliquia["probabilidades"].get("Radiant") or 0
        radiante = t("{prob}% en Radiante", prob=f"{prob:.1f}")
        if ruta["solo_en_boveda"]:
            return (
                f"<span style='color:{COLOR_BOVEDA}'>{t('Solo en bóveda')}</span> &middot; "
                f"<span style='color:{p['texto']}'>{nombre}</span> ({radiante}). "
                + t("Hay que comprarla a otro jugador.")
            )
        mision = ruta["mision"]
        detalle = f"{html.escape(mision['donde'])}" if mision else t("sin misión conocida")
        if mision and mision["mision"]:
            detalle += " &middot; " + glosario.enlace_mision(
                mision.get("modo"), mision["mision"], p["texto"], mision.get("rotacion"))
        if mision and mision["rotacion"]:
            detalle += " &middot; " + _rotacion(mision, p["texto"])
        return (
            f"<span style='color:{p['texto']}'><b>{nombre}</b></span> ({radiante}) "
            f"&middot; {t('farméala en')} <span style='color:{p['texto']}'>{detalle}</span>"
        )

    # -- acciones --

    def _sumar(self, cantidad: int) -> None:
        estado_objetivos.sumar(self.usuario, self.objetivo.id, cantidad)
        self.cambiada.emit()

    def _ampliar(self, cantidad: int) -> None:
        nueva = min(MAX_CANTIDAD, self.objetivo.objetivo + cantidad)
        if nueva <= self.objetivo.objetivo:
            return  # ya en el maximo posible
        if not confirmar(
            self, t("Ampliar la meta"),
            t("Ya tienes los {meta} que querías de {nombre}. ¿Quieres subir la meta a {nueva}?",
              meta=_miles(self.objetivo.objetivo), nombre=self.objetivo.nombre, nueva=_miles(nueva)),
        ):
            return
        estado_objetivos.fijar(self.usuario, self.objetivo.id, meta=nueva,
                               actual=self.objetivo.actual + (nueva - self.objetivo.objetivo))
        self.cambiada.emit()

    def _completar(self) -> None:
        estado_objetivos.completar(self.usuario, self.objetivo.id, self.indice)
        self.cambiada.emit()

    def _dialogo(self) -> DialogoCantidad:
        inventario = estado_objetivos._cantidad_inventario(self.usuario, self.objetivo.unique_name)
        return DialogoCantidad(self.objetivo.nombre_completo, self.objetivo.objetivo, self.objetivo.actual,
                               inventario, self)

    def _editar(self) -> None:
        dialogo = self._dialogo()
        if dialogo.exec() != QDialog.Accepted:
            return
        meta, actual = dialogo.valores()
        estado_objetivos.fijar(self.usuario, self.objetivo.id, meta=meta, actual=actual)
        self.cambiada.emit()

    def _borrar(self) -> None:
        if not confirmar(
            self, t("Quitar objetivo"),
            t("¿Seguro que quieres quitar {nombre}? Se pierde lo que llevabas apuntado.",
              nombre=self.objetivo.nombre_completo),
        ):
            return
        estado_objetivos.borrar(self.usuario, self.objetivo.id)
        self.contexto.seleccionados.discard(self.clave)
        self.cambiada.emit()


class PanelSet(QWidget):
    """Un set (Citrine Prime y sus piezas) como un solo panel que se despliega con un clic.

    Los botones de la cabecera cuentan piezas: + da por conseguida la siguiente que
    falta, - deshace la ultima, la marca las da todas por conseguidas."""

    cambiada = Signal()
    seleccion = Signal(str, bool)

    def __init__(self, entrada, usuario, indice, contexto: _Contexto, parent=None):
        super().__init__(parent)
        transparente(self)
        self.entrada, self.usuario, self.indice, self.contexto = entrada, usuario, indice, contexto
        self.clave = entrada.clave
        hechas, total = entrada.hechas, len(entrada.objetivos)
        abierto = self.clave in contexto.abiertos

        self.panel = _panel_fila(clicable=True)
        self.panel.poner_marcado(abierto)
        self.panel.pulsado.connect(self._alternar)

        self.marcar = CasillaRombo("")
        self.marcar.setToolTip(t("Marcar para borrar varios a la vez"))
        self.marcar.setChecked(self.clave in contexto.seleccionados)
        self.marcar.toggled.connect(lambda v: self.seleccion.emit(self.clave, v))
        self.marcar.setFixedWidth(px(18, False))

        self.cabecera = BotonGlifo("abajo" if abierto else "derecha", entrada.nombre, tam=12)
        self.cabecera.setToolTip(t("Clic para ver u ocultar las piezas"))
        self.cabecera.clicked.connect(self._alternar)
        self.miniatura = Miniatura(30)
        grupo = entrada.objetivos[0].grupo
        contexto.pedir_imagen(grupo or entrada.objetivos[0].unique_name, self.miniatura)

        self.titulo = EtiquetaC(t("Set de {nombre}", nombre=entrada.nombre), "destacado", recortar=True)
        cabeza = [self.titulo]
        insignia = _insignia_categoria(self._categoria_padre(grupo))
        if insignia is not None:
            cabeza.append(insignia)
        if hechas == total:
            cabeza.append(Insignia(t("Completado"), "ok", tam=10))
        cabeza.append(None)
        self.etiqueta = EtiquetaC(t("Set: {hechas} de {total} piezas", hechas=hechas, total=total), "pequeno")

        self.menos = BotonC("", icono="menos", tam=11)
        self.menos.setToolTip(t("Deshacer la última pieza conseguida"))
        self.menos.setEnabled(hechas > 0)
        self.menos.clicked.connect(self._restar)
        self.cuenta = EtiquetaC(f"{hechas} / {total}", "dato", tinta="acento" if hechas == total else "texto")
        self.cuenta.setAlignment(Qt.AlignCenter)
        self.cuenta.setMinimumWidth(px(64, False))
        self.mas = BotonC("", icono="mas", tam=11)
        self.mas.setToolTip(t("Dar por conseguida la siguiente pieza que falta"))
        self.mas.setEnabled(hechas < total)
        self.mas.clicked.connect(self._sumar)
        hueco_paso = transparente(QWidget())
        hueco_paso.setFixedWidth(px(58, False))
        self.completar = BotonGlifo("hecho", t("Completar"), tinta="ok")
        self.completar.setToolTip(t("Dar el set entero por conseguido"))
        self.completar.setEnabled(hechas < total)
        self.completar.clicked.connect(self._completar)
        self.editar = BotonGlifo("editar", t("Editar"))
        self.editar.setToolTip(t("Ver y cambiar cada pieza"))
        self.editar.clicked.connect(self._alternar)
        self.quitar = BotonGlifo("cerrar", t("Quitar set"))
        self.quitar.setToolTip(t("Quitar set"))
        self.quitar.clicked.connect(self._borrar)

        self.panel.capa.addLayout(fila(
            self.marcar, self.cabecera, self.miniatura,
            columna(fila(*cabeza, espacio=px(8, False)), self.etiqueta, espacio=px(1, False)),
            px(8, False), self.menos, self.cuenta, self.mas, hueco_paso, px(4, False),
            self.completar, self.editar, self.quitar, espacio=px(6, False),
        ))

        self.piezas = transparente(QWidget())
        capa_piezas = QVBoxLayout(self.piezas)
        capa_piezas.setContentsMargins(0, 0, 0, 0)
        capa_piezas.setSpacing(px(4, False))
        self.filas: list[FilaObjetivo] = []
        if abierto:  # las piezas se montan solo si se ven
            for objetivo in entrada.objetivos:
                ruta = contexto.ruta(objetivo.unique_name)
                pieza = FilaObjetivo(objetivo, ruta, usuario, indice=indice, contexto=contexto,
                                     seleccionable=False, dentro_de_set=True)
                pieza.cambiada.connect(self.cambiada.emit)
                self.filas.append(pieza)
                capa_piezas.addWidget(pieza)
        self.piezas.setVisible(abierto)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(px(4, False))
        caja.addWidget(self.panel)
        caja.addWidget(self.piezas)

    def _categoria_padre(self, grupo: str | None) -> str | None:
        if not grupo or self.indice is None:
            return None
        try:
            fila_padre = self.indice.execute("SELECT categoria FROM items WHERE unique_name = ?", (grupo,)).fetchone()
        except sqlite3.Error:
            return None
        return estado_objetivos.categoria_de(fila_padre[0], False) if fila_padre else None

    def _alternar(self) -> None:
        if self.clave in self.contexto.abiertos:
            self.contexto.abiertos.discard(self.clave)
        else:
            self.contexto.abiertos.add(self.clave)
        self.cambiada.emit()

    def _sumar(self) -> None:
        siguiente = next((o for o in self.entrada.objetivos if not o.completado), None)
        if siguiente is not None:
            estado_objetivos.completar(self.usuario, siguiente.id, self.indice)
            self.cambiada.emit()

    def _restar(self) -> None:
        ultima = next((o for o in reversed(self.entrada.objetivos) if o.completado), None)
        if ultima is not None:
            estado_objetivos.fijar(self.usuario, ultima.id, actual=0)
            self.cambiada.emit()

    def _completar(self) -> None:
        for objetivo in self.entrada.objetivos:
            if not objetivo.completado:
                estado_objetivos.completar(self.usuario, objetivo.id, self.indice)
        self.cambiada.emit()

    def _borrar(self) -> None:
        if not confirmar(
            self, t("Quitar set"),
            t("¿Seguro que quieres quitar el set {nombre} con sus {n} piezas? Se pierde lo que llevabas apuntado.",
              nombre=self.entrada.nombre, n=len(self.entrada.objetivos)),
        ):
            return
        estado_objetivos.borrar_varios(self.usuario, [o.id for o in self.entrada.objetivos])
        self.contexto.seleccionados.discard(self.clave)
        self.cambiada.emit()


class BotonesEstado(QWidget):
    """Sin empezar / En progreso / Completados como botones C (el marcado, relleno).

    Habla como la QTabBar de antes (`tabText`, `setCurrentIndex`, `currentChanged`) para
    que la guia y quien la use no noten el cambio."""

    currentChanged = Signal(int)  # noqa: N815 - nombre de Qt, como el de QTabBar

    def __init__(self, cuantos: int, parent=None):
        super().__init__(parent)
        transparente(self)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._botones: list[BotonC] = []
        capa = QHBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(px(8, False))
        for i in range(cuantos):
            boton = BotonC("", tam=12)
            boton.setCheckable(True)
            self._grupo.addButton(boton, i)
            self._botones.append(boton)
            capa.addWidget(boton)
        if self._botones:
            self._botones[0].setChecked(True)
        self._grupo.idClicked.connect(self.currentChanged.emit)

    def count(self) -> int:
        return len(self._botones)

    def boton(self, i: int) -> BotonC:
        return self._botones[i]

    def currentIndex(self) -> int:  # noqa: N802
        return self._grupo.checkedId()

    def setCurrentIndex(self, i: int) -> None:  # noqa: N802
        if not 0 <= i < len(self._botones) or i == self.currentIndex():
            return
        self._botones[i].setChecked(True)
        if not self.signalsBlocked():
            self.currentChanged.emit(i)

    def tabText(self, i: int) -> str:  # noqa: N802
        return self._botones[i].text()

    def setTabText(self, i: int, texto: str) -> None:  # noqa: N802
        self._botones[i].setText(texto)
        self._botones[i].updateGeometry()


# -- "Para esto te sirve hoy" ------------------------------------------------------------


def _nombre_paso(paso) -> str:
    return paso.nombre if hasattr(paso, "nombre") else paso.objetivo.nombre_completo


def lineas_hoy(mundo, pasos: list, ahora=None) -> list[dict]:
    """Lo que el mundo ofrece ahora mismo para tus objetivos pendientes.

    `pasos` son los de `pestana_tablero.pasos_pendientes` (ya ordenados de la meta mas
    rapida a la mas lenta). Cada linea: tipo ("fisura", "invasion", "alerta", "baro"),
    titulo, detalle (a que objetivo sirve), derecha (cuantas abiertas, el nodo o el
    tiempo), tinta (un color) y el unique_name del objetivo. Las fisuras siguen la regla
    de Mundo y del Tablero: normales (sin Acero ni Tormenta) de una era que te hace falta.
    """
    if mundo is None or not pasos:
        return []
    ahora = ahora or pestana_tablero._ahora()
    lineas: list[dict] = []
    por_era: dict[str, object] = {}
    for paso in pasos:
        if paso.es_reliquia and not paso.boveda and paso.era and paso.era not in por_era:
            por_era[paso.era] = paso
    for era in sorted(por_era, key=lambda e: ORDEN_ERAS.index(e) if e in ORDEN_ERAS else 99):
        abiertas = pestana_tablero.fisuras_abiertas(mundo, era, ahora)
        if not abiertas:
            continue
        paso = por_era[era]
        lineas.append({
            "tipo": "fisura", "titulo": t("Fisura {era}", era=era), "detalle": _nombre_paso(paso),
            "derecha": t("1 abierta") if abiertas == 1 else t("{n} abiertas", n=abiertas),
            "tinta": COLOR_ERA.get(era, hex_de("secundario")), "unique_name": paso.objetivo.unique_name,
        })

    por_unico = {p.objetivo.unique_name: p for p in pasos}
    por_id = {p.item["id"]: p for p in pasos if getattr(p, "item", None) and p.item.get("id")}

    def buscar(objeto):
        unico = getattr(objeto, "unique_name", "") or ""
        return por_unico.get(unico) or por_id.get(getattr(objeto, "item_id", None))

    vistas = set()

    def anadir(tipo, titulo, paso, derecha, tinta, texto_fila):
        clave = (tipo, paso.objetivo.unique_name, derecha)
        if clave in vistas:
            return
        vistas.add(clave)
        lineas.append({"tipo": tipo, "titulo": titulo, "detalle": _nombre_paso(paso), "derecha": derecha,
                       "tinta": tinta, "unique_name": paso.objetivo.unique_name, "texto_fila": texto_fila})

    for invasion in getattr(mundo, "invasiones", None) or []:
        for objeto in invasion.objetos or []:
            paso = buscar(objeto)
            if paso is not None:
                anadir("invasion", t("Invasión"), paso, invasion.nodo, hex_de("aviso"),
                       t("Una invasión en {nodo} lo da ahora mismo", nodo=invasion.nodo))
    for alerta in getattr(mundo, "alertas", None) or []:
        if alerta.expira and alerta.expira <= ahora:
            continue
        for objeto in alerta.objetos or []:
            paso = buscar(objeto)
            if paso is not None:
                queda = pestana_tablero.restante(alerta.expira, ahora)
                anadir("alerta", t("Alerta"), paso, queda, hex_de("acento"),
                       t("Una alerta lo da ahora mismo") + (f" ({queda})" if queda else ""))
    baro = getattr(mundo, "baro_detalle", None)
    for objeto in (getattr(baro, "inventario", None) or []):
        paso = buscar(objeto)
        if paso is not None:
            anadir("baro", "Baro Ki'Teer", paso, t("ahora"), hex_de("secundario"),
                   t("Baro Ki'Teer lo vende ahora"))
    return lineas


# -- la pestana ---------------------------------------------------------------------------


class PestanaObjetivos(QWidget):
    # Se emite cada vez que la lista cambia (anadir, sumar, borrar): Mundo la usa.
    cambiados = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.usuario: sqlite3.Connection = usuario_db.conectar()
        self.indice: sqlite3.Connection | None = None
        self.mundo = None
        self.contexto = _Contexto()
        self.contexto.pedir_imagen = self._pedir_imagen
        self.contexto.ruta = self._ruta
        self.estado = SIN_EMPEZAR
        self.categoria: str | None = None
        self.pagina = 0
        self._pestana_elegida = False
        self._entradas_pagina: list = []
        # unique_name -> (ruta, item): la ruta no depende del progreso, solo del ritmo.
        self._rutas: dict = {}
        self._ritmo_rutas: str | None = None
        self._imagenes: dict[str, str | None] = {}
        self._esperando_imagen: dict[str, list[Miniatura]] = {}
        widgets.imagenes().lista.connect(self._imagen_lista)

        # -- cabecera (a la derecha de las sub-pestanas si la pagina va en MIS METAS)
        self.boton_inventario = BotonC("", icono="leer")
        self.boton_inventario.setCheckable(True)
        self.boton_inventario.toggled.connect(self._cambiar_inventario)
        self.controles_cabecera = transparente(QWidget(self))
        self.controles_cabecera.setLayout(fila(self.boton_inventario, espacio=px(8, False)))

        # -- estados, filtro y resumen
        self.estados = BotonesEstado(len(ESTADOS))
        self.estados.currentChanged.connect(self._cambiar_estado)
        self.etiqueta_filtro = EtiquetaC("", "pequeno")
        self.filtro = DesplegableC()
        _proteger_rueda(self.filtro)
        self.filtro.currentIndexChanged.connect(self._cambiar_categoria)
        self.resumen = EtiquetaC("", "pequeno", recortar=True)
        self.resumen.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.aviso = EtiquetaC("", "pequeno", tinta="secundario", envolver=True)
        self.aviso.hide()

        # -- lista
        self.contenido = transparente(QWidget())
        self.caja_filas = QVBoxLayout(self.contenido)
        self.caja_filas.setContentsMargins(0, 0, px(6, False), 0)
        self.caja_filas.setSpacing(px(6, False))
        self.caja_filas.addStretch(1)
        self.vacio = EtiquetaC("", "normal", tinta="suave", envolver=True)
        self.vacio.setAlignment(Qt.AlignCenter)
        self.vacio.setContentsMargins(px(30, False), px(30, False), px(30, False), px(30, False))
        self.desplazable = QScrollArea()
        self.desplazable.setWidgetResizable(True)
        self.desplazable.setFrameShape(QScrollArea.NoFrame)
        transparente(self.desplazable)
        transparente(self.desplazable.viewport())
        self.desplazable.setWidget(self.contenido)

        # -- columna de la derecha
        self.boton_anadir = BotonC("", principal=True, icono="mas")
        self.boton_anadir.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.boton_anadir.clicked.connect(self._ir_a_buscar)
        self.panel_hoy = PanelC("")
        self.capa_hoy = QVBoxLayout()
        self.capa_hoy.setSpacing(px(6, False))
        self.panel_hoy.capa.addLayout(self.capa_hoy)
        self.boton_mundo = BotonC("", tam=11)
        self.boton_mundo.clicked.connect(self._ir_a_mundo)
        self.panel_hoy.capa.addLayout(fila(None, self.boton_mundo))
        self.panel_ayuda = PanelC("", remate=False)
        self.ayuda = EtiquetaC("", "pequeno", envolver=True)
        self.panel_ayuda.capa.addWidget(self.ayuda)
        self.lateral = transparente(QWidget())
        self.lateral.setFixedWidth(px(ANCHO_LATERAL, False))
        capa_lateral = QVBoxLayout(self.lateral)
        capa_lateral.setContentsMargins(0, 0, 0, 0)
        capa_lateral.setSpacing(px(12, False))
        capa_lateral.addWidget(self.boton_anadir)
        capa_lateral.addWidget(self.panel_hoy)
        capa_lateral.addWidget(self.panel_ayuda)
        capa_lateral.addStretch(1)

        # -- pie: marcar y borrar varios, paginas
        self.todos = CasillaRombo("")
        self.todos.toggled.connect(self._marcar_pagina)
        self.borrar_marcados = BotonC("", tam=11)
        self.borrar_marcados.clicked.connect(self._borrar_marcados)
        self.anterior = BotonC("", tam=11)
        self.siguiente = BotonC("", tam=11)
        self.texto_pagina = EtiquetaC("", "pequeno")
        self.anterior.clicked.connect(lambda: self._ir_a_pagina(self.pagina - 1))
        self.siguiente.clicked.connect(lambda: self._ir_a_pagina(self.pagina + 1))

        caja = QVBoxLayout(self)
        caja.setContentsMargins(px(4, False), px(6, False), px(4, False), px(4, False))
        caja.setSpacing(px(10, False))
        # Suelta (sin MIS METAS, en los tests) la cabecera va aqui; la seccion se la lleva.
        caja.addWidget(self.controles_cabecera, 0, Qt.AlignRight)
        caja.addLayout(fila(self.estados, px(10, False), self.etiqueta_filtro, self.filtro, None, self.resumen,
                            espacio=px(8, False)))
        caja.addWidget(self.aviso)
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(px(16, False))
        cuerpo.addWidget(self.desplazable, 1)
        cuerpo.addWidget(self.lateral)
        caja.addLayout(cuerpo, 1)
        caja.addLayout(fila(self.todos, px(12, False), self.borrar_marcados, None, self.anterior, px(6, False),
                            self.texto_pagina, px(6, False), self.siguiente, espacio=px(6, False)))

        self._reloj_hoy = QTimer(self)
        self._reloj_hoy.setInterval(60_000)
        self._reloj_hoy.timeout.connect(self._pintar_hoy)
        self._leer_inventario_config()
        self._traducir_fijos()

    def _traducir_fijos(self) -> None:
        self.etiqueta_filtro.setText(t("Mostrar:"))
        self.filtro.blockSignals(True)
        self.filtro.clear()
        for clave, texto in (
            (None, t("Todas las categorías")),
            (estado_objetivos.SETS, t("Sets y piezas")),
            (estado_objetivos.WARFRAMES, t("Warframes")),
            (estado_objetivos.ARMAS, t("Armas")),
            (estado_objetivos.RECURSOS, t("Recursos")),
            (estado_objetivos.OTROS, t("Otros")),
        ):
            self.filtro.addItem(texto, clave)
        self.filtro.setCurrentIndex(max(0, self.filtro.findData(self.categoria)))
        self.filtro.blockSignals(False)
        self.filtro.updateGeometry()
        self.todos.setText(t("Marcar los de esta página"))
        self.anterior.setText(t("‹ Anterior"))
        self.siguiente.setText(t("Siguiente ›"))
        self.boton_inventario.setText(t("Leer inventario de la pantalla"))
        self.boton_inventario.setToolTip(t(
            "Con esto encendido, Farmadex lee solo las cantidades cuando abres el Inventario o la "
            "Fundición en el juego y las apunta en tus objetivos. Es lo mismo que la opción de Ajustes."))
        self.boton_anadir.setText(t("Añadir un objetivo"))
        self.boton_anadir.setToolTip(t("Busca algo y pulsa '+ Objetivo' en su ficha."))
        self.panel_hoy.poner_titulo(t("Para esto te sirve hoy"))
        self.boton_mundo.setText(t("Ver el mundo"))
        self.panel_ayuda.poner_titulo(t("Cómo se usa"))
        self.ayuda.setText("<br>".join(html.escape(x) for x in (
            t("+ y - suman o restan; ×1 elige cuánto suma cada clic."),
            t("Al abrir reliquias en solitario, Farmadex lo suma solo."),
            t("La marca lo da por hecho, el lápiz sirve para editar y la X para quitar."),
            t("La flecha abre las piezas del set o los recursos para fabricarlo."),
        )))

    def conectar_indice(self, con: sqlite3.Connection) -> None:
        self.indice = con
        self._rutas.clear()
        self._imagenes.clear()
        self.refrescar()

    def retraducir(self) -> None:
        """Las filas se generan enteras en cada refresco, asi que basta con repintar."""
        self._rutas.clear()  # los nombres del indice van en el idioma de la interfaz
        self._traducir_fijos()
        self.refrescar()

    def actualizar_mundo(self, mundo) -> None:
        """Estado del mundo nuevo: solo cambia "Para esto te sirve hoy" (las filas no se
        rehacen para no quitarte el foco si estas escribiendo una cantidad)."""
        self.mundo = mundo
        self._pintar_hoy()

    def showEvent(self, evento):  # noqa: N802 - firma de Qt
        super().showEvent(evento)
        self._leer_inventario_config()
        self._reloj_hoy.start()
        self._pintar_hoy()

    def hideEvent(self, evento):  # noqa: N802
        super().hideEvent(evento)
        self._reloj_hoy.stop()

    def resizeEvent(self, evento):  # noqa: N802
        super().resizeEvent(evento)
        self.lateral.setVisible(self.width() >= px(ANCHO_SIN_LATERAL, False))

    # -- navegacion a otras secciones ---------------------------------------------------

    def _ventana(self):
        ventana = self.window()
        return ventana if hasattr(ventana, "ir_a") else None

    def _ir_a_buscar(self) -> None:
        ventana = self._ventana()
        if ventana is not None:
            ventana.ir_a("buscar")
            caja = getattr(getattr(ventana, "buscador", None), "caja", None)
            if caja is not None:
                caja.setFocus()

    def _ir_a_mundo(self) -> None:
        ventana = self._ventana()
        if ventana is not None:
            ventana.ir_a("mundo")

    # -- leer el inventario de la pantalla ---------------------------------------------

    def _leer_inventario_config(self) -> None:
        self.boton_inventario.blockSignals(True)
        self.boton_inventario.setChecked(bool(config_farmadex.cargar().get("inventario_pasivo", False)))
        self.boton_inventario.blockSignals(False)

    def _cambiar_inventario(self, activo: bool) -> None:
        """Enciende o apaga la lectura sola del Inventario: la misma casilla de Ajustes,
        que es la que avisa al lector de la pantalla y lo guarda."""
        ventana = self._ventana()
        casilla = getattr(getattr(ventana, "ajustes", None), "inventario_pasivo", None)
        if casilla is not None and hasattr(casilla, "setChecked"):
            casilla.setChecked(activo)
        else:
            cfg = config_farmadex.cargar()
            cfg["inventario_pasivo"] = activo
            config_farmadex.guardar(cfg)
        self.aviso.setText(
            t("Listo: abre el Inventario o la Fundición en el juego y Farmadex apuntará solo lo que tienes.")
            if activo else t("Farmadex ya no lee el Inventario solo.")
        )
        self.aviso.show()
        QTimer.singleShot(12_000, self.aviso.hide)

    # -- alta desde la ficha --------------------------------------------------

    def anadir_item(self, item_id: int, set_completo: bool = False) -> int:
        if self.indice is None:
            self.indice = indice_datos.conectar()
        if set_completo:
            ids = estado_objetivos.anadir_set(self.usuario, self.indice, item_id)
        else:
            fila_item = self.indice.execute(
                "SELECT unique_name, nombre_en, nombre_es, item_count FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not fila_item:
                return 0
            # El objetivo guarda el nombre con el que se creo, en el idioma de ese momento.
            nombre = (fila_item[2] or fila_item[1]) if es_castellano() else (fila_item[1] or fila_item[2])
            ids = [estado_objetivos.anadir(self.usuario, fila_item[0], nombre, fila_item[3] or 1, indice=self.indice)]
        self._mostrar_objetivo(ids[0] if ids else None)
        self.refrescar()
        return len(ids)

    def _mostrar_objetivo(self, objetivo_id: int | None) -> None:
        """Deja a la vista lo recien anadido: su pestana, sin filtro que lo tape, pagina 1."""
        if objetivo_id is None:
            return
        for entrada in estado_objetivos.entradas(self.usuario):
            if any(o.id == objetivo_id for o in entrada.objetivos):
                if self.categoria and entrada.categoria != self.categoria:
                    self.categoria = None
                    self.filtro.blockSignals(True)
                    self.filtro.setCurrentIndex(0)
                    self.filtro.blockSignals(False)
                self._poner_estado(entrada.estado)
                self.pagina = 0
                self._pestana_elegida = True
                return

    def sumar_por_item(self, unique_name: str, cantidad: int = 1) -> bool:
        objetivo = estado_objetivos.sumar_por_item(self.usuario, unique_name, cantidad)
        if objetivo:
            self.refrescar()
        return objetivo is not None

    # -- navegacion ----------------------------------------------------------------

    def _poner_estado(self, estado: str) -> None:
        self.estado = estado
        self.estados.blockSignals(True)
        self.estados.setCurrentIndex(ESTADOS.index(estado))
        self.estados.blockSignals(False)

    def _cambiar_estado(self, indice: int) -> None:
        self.estado = ESTADOS[indice]
        self.pagina = 0
        self._pestana_elegida = True
        self.refrescar()

    def _cambiar_categoria(self, _indice: int) -> None:
        self.categoria = self.filtro.currentData()
        self.pagina = 0
        self.refrescar()

    def _ir_a_pagina(self, pagina: int) -> None:
        self.pagina = pagina
        self.refrescar()
        self.desplazable.verticalScrollBar().setValue(0)

    def _seleccion(self, clave: str, marcado: bool) -> None:
        if marcado:
            self.contexto.seleccionados.add(clave)
        else:
            self.contexto.seleccionados.discard(clave)
        self._pintar_borrar()

    def _marcar_pagina(self, marcado: bool) -> None:
        for i in range(self.caja_filas.count()):
            widget = self.caja_filas.itemAt(i).widget()
            casilla = getattr(widget, "marcar", None)
            if casilla is not None:
                casilla.setChecked(marcado)

    def _pintar_borrar(self) -> None:
        n = len(self.contexto.seleccionados)
        self.borrar_marcados.setText(t("Borrar marcados ({n})", n=n))
        self.borrar_marcados.setEnabled(n > 0)

    def _ids_marcados(self) -> tuple[list[int], list[str]]:
        ids, nombres = [], []
        for entrada in estado_objetivos.entradas(self.usuario):
            if entrada.clave in self.contexto.seleccionados:
                ids.extend(o.id for o in entrada.objetivos)
                nombres.append(entrada.nombre)
        return ids, nombres

    def _borrar_marcados(self) -> None:
        ids, nombres = self._ids_marcados()
        if not ids:
            self.contexto.seleccionados.clear()
            self._pintar_borrar()
            return
        lista = ", ".join(nombres[:6]) + (" ..." if len(nombres) > 6 else "")
        if not confirmar(
            self, t("Borrar objetivos"),
            t("¿Seguro que quieres borrar {n} objetivos? ({lista}) Se pierde lo que llevabas apuntado.",
              n=len(nombres), lista=lista),
        ):
            return
        estado_objetivos.borrar_varios(self.usuario, ids)
        self.contexto.seleccionados.clear()
        self.refrescar()

    # -- rutas e imagenes -------------------------------------------------------------

    def _indice_vivo(self) -> sqlite3.Connection | None:
        if self.indice is None:
            return None
        try:
            self.indice.execute("SELECT 1")
        except sqlite3.Error:
            self.indice = None  # el indice se esta reconstruyendo
        return self.indice

    def _cache_rutas(self) -> dict:
        """La cache de rutas, vaciada si ha cambiado el ritmo de juego (cambia los tiempos)."""
        ritmo = eficiencia.ritmo()
        if ritmo != self._ritmo_rutas:
            self._rutas.clear()
            self._ritmo_rutas = ritmo
        return self._rutas

    def _ruta(self, unique_name: str):
        if self.indice is None:
            return None
        cache = self._cache_rutas()
        if unique_name not in cache:
            try:
                cache[unique_name] = (estado_objetivos.ruta_de(self.indice, unique_name),
                                      pestana_tablero._item(self.indice, unique_name))
            except sqlite3.Error:
                return None
        return cache[unique_name][0]

    def _nombre_imagen(self, unique_name: str) -> str | None:
        if unique_name not in self._imagenes:
            imagen = None
            if self.indice is not None:
                try:
                    fila_img = self.indice.execute(
                        "SELECT i.imagen, p.imagen FROM items i LEFT JOIN items p ON p.id = i.padre_id "
                        "WHERE i.unique_name = ?", (unique_name,)).fetchone()
                    if fila_img:
                        imagen = fila_img[0] or fila_img[1]
                except sqlite3.Error:
                    imagen = None
            self._imagenes[unique_name] = imagen
        return self._imagenes[unique_name]

    def _pedir_imagen(self, unique_name: str, miniatura: Miniatura) -> None:
        nombre = self._nombre_imagen(unique_name) if unique_name else None
        if not nombre:
            return
        mapa = widgets.imagenes().pixmap(nombre, 64)
        miniatura.poner(mapa)
        if mapa is None:
            self._esperando_imagen.setdefault(nombre, []).append(miniatura)

    def _imagen_lista(self, nombre: str) -> None:
        for miniatura in self._esperando_imagen.pop(nombre, []):
            try:
                miniatura.poner(widgets.imagenes().pixmap(nombre, 64))
            except RuntimeError:
                pass  # la fila ya se rehizo

    # -- pintado ---------------------------------------------------------------

    def _pasos(self) -> list:
        indice = self._indice_vivo()
        try:
            return pestana_tablero.pasos_pendientes(indice, self.usuario, self._cache_rutas() if indice else None)
        except sqlite3.Error:
            log.warning("No se pudieron calcular las metas para 'Para esto te sirve hoy'", exc_info=True)
            return []

    def _pintar_hoy(self) -> None:
        while self.capa_hoy.count():
            elemento = self.capa_hoy.takeAt(0)
            w = elemento.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.boton_mundo.setVisible(self.mundo is not None)
        hay_objetivos = bool(estado_objetivos.listar(self.usuario))
        if not hay_objetivos:
            texto = t("Cuando tengas objetivos, aquí verás las fisuras e invasiones abiertas ahora que te sirven.")
            self.capa_hoy.addWidget(EtiquetaC(texto, "pequeno", envolver=True))
            return
        if self.mundo is None:
            self.capa_hoy.addWidget(EtiquetaC(t("Cargando el estado del mundo..."), "pequeno", envolver=True))
            return
        lineas = lineas_hoy(self.mundo, self._pasos())
        if not lineas:
            texto = t("Ahora mismo no hay fisuras, invasiones ni alertas abiertas que sirvan para tus objetivos.")
            self.capa_hoy.addWidget(EtiquetaC(texto, "pequeno", envolver=True))
            return
        for linea in lineas[:MAX_LINEAS_HOY]:
            caja = transparente(QWidget())
            caja.setLayout(fila(
                Rombo(8, linea["tinta"]), _rotulo_color(linea["titulo"], linea["tinta"]),
                EtiquetaC(linea["detalle"], "pequeno", recortar=True), None,
                EtiquetaC(linea["derecha"], "pequeno", tinta="suave"), espacio=px(8, False)))
            caja.setToolTip(t("Para {nombre}", nombre=linea["detalle"]))
            self.capa_hoy.addWidget(caja)
        if len(lineas) > MAX_LINEAS_HOY:
            self.capa_hoy.addWidget(EtiquetaC(t("y {n} más en Mundo", n=len(lineas) - MAX_LINEAS_HOY),
                                              "pequeno", tinta="suave"))

    def _textos_hoy(self) -> dict[str, str]:
        """unique_name -> lo que da ahora el mundo, para ensenarlo en la fila del objetivo."""
        if self.mundo is None:
            return {}
        try:
            lineas = lineas_hoy(self.mundo, self._pasos())
        except Exception:  # noqa: BLE001 - un mundo raro no puede dejar la lista sin pintar
            log.warning("No se pudo cruzar el mundo con los objetivos", exc_info=True)
            return {}
        salida: dict[str, str] = {}
        for linea in lineas:
            if linea.get("texto_fila"):
                salida.setdefault(linea["unique_name"], linea["texto_fila"])
        return salida

    def refrescar(self) -> None:
        if self._indice_vivo() is not None:
            try:
                estado_objetivos.completar_datos(self.usuario, self.indice)
            except sqlite3.Error:
                self.indice = None  # el indice se esta reconstruyendo
        self._vaciar()
        self._esperando_imagen.clear()
        self.contexto.hoy = self._textos_hoy()

        todas = estado_objetivos.entradas(self.usuario, categoria=self.categoria)
        cuenta = estado_objetivos.contar_por_estado(todas)
        if not self._pestana_elegida and todas:
            # Al abrir: lo que llevas a medias; si no hay, lo pendiente.
            for estado in (EN_PROGRESO, SIN_EMPEZAR, COMPLETADOS):
                if cuenta[estado]:
                    self._poner_estado(estado)
                    break
            self._pestana_elegida = True
        titulos = {
            SIN_EMPEZAR: t("Sin empezar ({n})", n=cuenta[SIN_EMPEZAR]),
            EN_PROGRESO: t("En progreso ({n})", n=cuenta[EN_PROGRESO]),
            COMPLETADOS: t("Completados ({n})", n=cuenta[COMPLETADOS]),
        }
        for i, estado in enumerate(ESTADOS):
            self.estados.setTabText(i, titulos[estado])

        hay_alguno = bool(estado_objetivos.listar(self.usuario))
        if not hay_alguno:
            self.resumen.setText(t("Todavía no tienes objetivos. Busca algo y pulsa '+ Objetivo'."))
        else:
            pendientes = cuenta[SIN_EMPEZAR] + cuenta[EN_PROGRESO]
            self.resumen.setText(
                t("{n} por conseguir", n=pendientes) + " · " + t("{n} completados", n=cuenta[COMPLETADOS])
            )

        lista = [e for e in todas if e.estado == self.estado]
        trozo, self.pagina, total = estado_objetivos.paginar(lista, self.pagina)
        self._entradas_pagina = trozo
        # Lo marcado que ya no existe (borrado desde otra pestana) se olvida.
        vivas = {e.clave for e in estado_objetivos.entradas(self.usuario)}
        self.contexto.seleccionados &= vivas

        if not trozo:
            self.vacio.setText(
                t("Todavía no tienes objetivos. Busca algo y pulsa '+ Objetivo'.") if not hay_alguno
                else t("Aquí no hay nada con este filtro.")
            )
            self.vacio.show()
            self.caja_filas.insertWidget(0, self.vacio)
        for entrada in trozo:
            if entrada.es_set:
                widget = PanelSet(entrada, self.usuario, self.indice, self.contexto)
            else:
                objetivo = entrada.objetivos[0]
                widget = FilaObjetivo(objetivo, self._ruta(objetivo.unique_name), self.usuario,
                                      indice=self.indice, contexto=self.contexto)
            widget.cambiada.connect(lambda clave=entrada.clave: self._tras_cambio(clave))
            widget.seleccion.connect(self._seleccion)
            self.caja_filas.insertWidget(self.caja_filas.count() - 1, widget)

        self.texto_pagina.setText(t("Página {n} de {total}", n=self.pagina + 1, total=total))
        self.anterior.setEnabled(self.pagina > 0)
        self.siguiente.setEnabled(self.pagina < total - 1)
        self.todos.blockSignals(True)
        self.todos.setChecked(bool(trozo) and all(e.clave in self.contexto.seleccionados for e in trozo))
        self.todos.setEnabled(bool(trozo))
        self.todos.blockSignals(False)
        self._pintar_borrar()
        self._pintar_hoy()
        self.cambiados.emit()

    def _tras_cambio(self, clave: str) -> None:
        """Tras tocar una fila, la pestana la sigue: si paso a 'En progreso' o a
        'Completados', se va alli con ella en vez de dejarla desaparecer de la vista."""
        lista = estado_objetivos.entradas(self.usuario, categoria=self.categoria)
        entrada = next((e for e in lista if e.clave == clave), None)
        if entrada is not None and entrada.estado != self.estado:
            self._poner_estado(entrada.estado)
            mismas = [e.clave for e in lista if e.estado == entrada.estado]
            self.pagina = mismas.index(clave) // estado_objetivos.POR_PAGINA
        self.refrescar()

    def _vaciar(self) -> None:
        while self.caja_filas.count() > 1:
            elemento = self.caja_filas.takeAt(0)
            widget = elemento.widget()
            if widget is self.vacio:
                widget.hide()
                continue
            if widget:
                # Fuera ya, no al volver al bucle de eventos: si no, la fila vieja se sigue
                # pintando un instante encima de la nueva (una fila "fantasma" repetida).
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def eras_necesarias(self) -> dict[str, list[str]]:
        if self.indice is None:
            return {}
        return estado_objetivos.eras_necesarias(self.indice, self.usuario)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(px(1100, False), px(700, False))
