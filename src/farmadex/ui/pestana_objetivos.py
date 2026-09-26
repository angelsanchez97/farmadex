"""Pestana Objetivos: lo que estas farmeando y por donde conseguirlo.

Se organiza como pidio un tester: pestanas Sin empezar / En progreso / Completados,
filtro por categoria, lo mas reciente arriba y de diez en diez. Los sets son un solo
panel que se despliega con un clic, y las armas con receta se pueden abrir para marcar
cada recurso de fabricacion por separado. El contador nunca pasa de la meta.
"""

from __future__ import annotations

import html
import sqlite3

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from ..datos import indice as indice_datos
from ..estado import objetivos as estado_objetivos
from ..estado import usuario_db
from ..estado.objetivos import COMPLETADOS, EN_PROGRESO, ESTADOS, MAX_CANTIDAD, SIN_EMPEZAR
from ..idiomas import es_castellano, nombre as nombre_idioma, t
from . import glosario
from .widgets import COLOR_BOVEDA, COLOR_DISPONIBLE, PALETA, Tarjeta


def _rotacion(mision: dict, color: str) -> str:
    """'rotacion C' explicando, al pasar el raton, cuando llega en el modo de esa mision."""
    return glosario.enlace_rotacion(
        mision.get("modo"), mision["rotacion"], t("rotacion {rot}", rot=mision["rotacion"]), color
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


# -- piezas de la fila -------------------------------------------------------------


class ControlCantidad(QWidget):
    """Barra 'X de Y' con restar / cuantas / sumar. Nunca se pasa de la meta.

    `cambio` lleva lo que hay que sumar, ya recortado a 0..meta. Si ya estas en la
    meta y pulsas sumar, sale `ampliar` con las unidades: quien lo use pide confirmacion.
    """

    cambio = Signal(int)
    ampliar = Signal(int)

    def __init__(self, actual: int, meta: int, clave: str, contexto: _Contexto,
                 ancho_barra: int = 170, parent=None):
        super().__init__(parent)
        self.actual, self.meta = actual, max(1, meta)
        self._clave, self._contexto = clave, contexto

        self.barra = QProgressBar()
        self.barra.setRange(0, self.meta)
        self.barra.setValue(min(actual, self.meta))
        self.barra.setFormat(t("{actual} de {total}", actual=_miles(actual), total=_miles(self.meta)))
        self.barra.setFixedWidth(ancho_barra)

        self.menos = QPushButton("-")
        self.mas = QPushButton("+")
        for boton in (self.menos, self.mas):
            boton.setFixedWidth(32)
            boton.setStyleSheet("font-size: 17px; font-weight: bold; padding: 1px 0;")
        self.paso = QSpinBox()
        self.paso.setRange(1, MAX_CANTIDAD)
        self.paso.setValue(min(contexto.pasos.get(clave, 1), MAX_CANTIDAD))
        self.paso.setFixedWidth(78)
        self.paso.setToolTip(t("Cuantas unidades suma o resta cada clic (de 1 a {max}).",
                               max=_miles(MAX_CANTIDAD)))
        self.paso.setAccessibleName(t("Cantidad por clic"))
        _proteger_rueda(self.paso)
        self.paso.valueChanged.connect(lambda v: contexto.pasos.__setitem__(clave, v))

        self.menos.setEnabled(actual > 0)
        self.menos.setToolTip(t("Restar"))
        self.mas.setToolTip(
            t("Ya llegaste a la meta. Pulsa si quieres ampliarla.") if actual >= self.meta
            else t("Sumar (sin pasar de la meta)")
        )
        self.menos.clicked.connect(self._restar)
        self.mas.clicked.connect(self._sumar)

        caja = QHBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(4)
        caja.addWidget(self.barra)
        caja.addWidget(self.menos)
        caja.addWidget(self.paso)
        caja.addWidget(self.mas)

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

        titulo = QLabel(f"<b>{html.escape(nombre)}</b>")
        titulo.setTextFormat(Qt.RichText)
        form = QFormLayout()
        form.addRow(t("Quiero conseguir"), self.meta)
        form.addRow("", self._nota(t("Minimo 1, maximo {max}.", max=_miles(MAX_CANTIDAD))))
        form.addRow(t("Ya tengo"), self.actual)
        form.addRow("", self._nota(t("De 0 hasta lo que quieres conseguir.")))

        caja = QVBoxLayout(self)
        caja.addWidget(titulo)
        caja.addLayout(form)
        self.usar_inventario = None
        if en_inventario is not None:
            fila = QHBoxLayout()
            fila.addWidget(self._nota(t("Tu inventario dice que tienes {n}.", n=_miles(en_inventario))), 1)
            self.usar_inventario = QPushButton(t("Usar ese numero"))
            self.usar_inventario.clicked.connect(
                lambda: self.actual.setValue(min(en_inventario, self.meta.value()))
            )
            fila.addWidget(self.usar_inventario)
            caja.addLayout(fila)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText(t("Guardar"))
        botones.button(QDialogButtonBox.Cancel).setText(t("Cancelar"))
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        caja.addWidget(botones)

    @staticmethod
    def _nota(texto: str) -> QLabel:
        nota = QLabel(texto)
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color: {PALETA['suave']}; font-size: 11px;")
        return nota

    def valores(self) -> tuple[int, int]:
        return self.meta.value(), min(self.actual.value(), self.meta.value())


def _boton_pequeno(texto: str, color: str | None = None) -> QPushButton:
    boton = QPushButton(texto)
    boton.setStyleSheet(f"padding: 2px 10px; color: {color or PALETA['suave']};")
    boton.setCursor(Qt.PointingHandCursor)
    return boton


def _flecha(abierto: bool) -> str:
    return "▾" if abierto else "▸"


class FilaRecurso(QWidget):
    """Un recurso de fabricacion dentro de un objetivo: 300 de 300 Rubedo."""

    cambiado = Signal()

    def __init__(self, objetivo, recurso, usuario, contexto: _Contexto, parent=None):
        super().__init__(parent)
        self.objetivo, self.recurso, self.usuario = objetivo, recurso, usuario
        p = PALETA
        nombre = (recurso.nombre_es or recurso.nombre_en) if es_castellano() else (recurso.nombre_en or recurso.nombre_es)
        marca = f"<span style='color:{COLOR_DISPONIBLE}'>✓</span> " if recurso.completado else ""
        texto = f"{marca}<span style='color:{p['texto']}'>{html.escape(nombre or '')}</span>"
        if recurso.en_inventario is not None:
            texto += (f" <span style='color:{p['suave']};font-size:11px'>"
                      + t("(tienes {n})", n=_miles(recurso.en_inventario)) + "</span>")
        self.etiqueta = QLabel(texto)
        self.etiqueta.setTextFormat(Qt.RichText)

        self.control = ControlCantidad(
            recurso.actual, recurso.necesario, f"r:{objetivo.id}:{recurso.unique_name}", contexto, 140
        )
        self.control.cambio.connect(self._sumar)
        # Un recurso no se amplia: lo que pide la receta es lo que pide.
        self.control.ampliar.connect(lambda _n: None)
        if recurso.completado:
            self.control.mas.setToolTip(t("Ya tienes todo lo que pide la receta."))
        self.listo = _boton_pequeno(t("Listo"))
        self.listo.setToolTip(t("Marcar este recurso como conseguido entero"))
        self.listo.setEnabled(not recurso.completado)
        self.listo.clicked.connect(self._listo)

        caja = QHBoxLayout(self)
        caja.setContentsMargins(18, 0, 0, 0)
        caja.setSpacing(6)
        caja.addWidget(self.etiqueta, 1)
        caja.addWidget(self.control)
        caja.addWidget(self.listo)

    def _sumar(self, cantidad: int) -> None:
        estado_objetivos.sumar_recurso(self.usuario, self.objetivo, self.recurso, cantidad)
        self.cambiado.emit()

    def _listo(self) -> None:
        estado_objetivos.fijar_recurso(self.usuario, self.objetivo, self.recurso, self.recurso.necesario)
        self.cambiado.emit()


class FilaObjetivo(Tarjeta):
    cambiada = Signal()
    abrir_item = Signal(str)
    seleccion = Signal(str, bool)

    def __init__(self, objetivo, ruta, usuario, parent=None, *, indice=None,
                 contexto: _Contexto | None = None, seleccionable: bool = True, dentro_de_set: bool = False):
        color = (
            COLOR_DISPONIBLE if objetivo.completado
            else COLOR_BOVEDA if ruta and ruta["solo_en_boveda"]
            else PALETA["acento"] if ruta
            else PALETA["borde"]
        )
        super().__init__(None if dentro_de_set else color, parent)
        self.objetivo = objetivo
        self.usuario = usuario
        self.indice = indice
        self.contexto = contexto or _Contexto()
        self.clave = f"o:{objetivo.id}"
        p = PALETA

        nombre = objetivo.nombre
        if dentro_de_set and objetivo.grupo_nombre and nombre.startswith(objetivo.grupo_nombre + ":"):
            nombre = nombre[len(objetivo.grupo_nombre) + 1:].strip()  # "Sistemas", sin "Ash Prime:"
        tam = 14 if dentro_de_set else 16
        self.titulo = QLabel(
            f"<span style='font-size:{tam}px;font-weight:bold'>{html.escape(nombre)}</span>"
            + (f"  <span style='color:{COLOR_DISPONIBLE};font-size:12px'>{t('Completado').upper()}</span>"
               if objetivo.completado else "")
        )
        self.titulo.setTextFormat(Qt.RichText)

        self.control = ControlCantidad(objetivo.actual, objetivo.objetivo, self.clave, self.contexto)
        self.control.cambio.connect(self._sumar)
        self.control.ampliar.connect(self._ampliar)

        arriba = QHBoxLayout()
        arriba.setSpacing(6)
        self.marcar = None
        if seleccionable:
            self.marcar = QCheckBox()
            self.marcar.setToolTip(t("Marcar para borrar varios a la vez"))
            self.marcar.setChecked(self.clave in self.contexto.seleccionados)
            self.marcar.toggled.connect(lambda v: self.seleccion.emit(self.clave, v))
            arriba.addWidget(self.marcar)
        arriba.addWidget(self.titulo, 1)
        arriba.addWidget(self.control)

        self.donde = QLabel(self._texto_ruta(ruta))
        self.donde.setTextFormat(Qt.RichText)
        self.donde.setWordWrap(True)
        self.donde.setStyleSheet(f"color: {p['suave']};")
        # El tipo de mision y la rotacion explican el modo al pasar el raton.
        glosario.conectar_etiqueta(self.donde)

        self.completar = _boton_pequeno(t("Completar"), COLOR_DISPONIBLE)
        self.completar.setToolTip(t("Darlo por conseguido entero"))
        self.completar.setVisible(not objetivo.completado)
        self.completar.clicked.connect(self._completar)
        self.editar = _boton_pequeno(t("Editar"))
        self.editar.setToolTip(t("Cambiar cuanto quieres conseguir y cuanto tienes"))
        self.editar.clicked.connect(self._editar)
        self.quitar = _boton_pequeno(t("Quitar"))
        self.quitar.clicked.connect(self._borrar)

        abajo = QHBoxLayout()
        abajo.setSpacing(6)
        abajo.addWidget(self.donde, 1)
        abajo.addWidget(self.completar)
        abajo.addWidget(self.editar)
        abajo.addWidget(self.quitar)

        self.caja.addLayout(arriba)
        self.caja.addLayout(abajo)

        # Armas y demas con receta: abrir y marcar cada recurso por separado.
        self.boton_recursos = None
        self.panel_recursos = None
        if estado_objetivos.tiene_recursos(indice, objetivo.unique_name):
            self._montar_recursos()

    # -- recursos de fabricacion --

    def _montar_recursos(self) -> None:
        recursos = estado_objetivos.recursos_de(self.usuario, self.indice, self.objetivo)
        clave = f"rec:{self.objetivo.id}"
        abierto = clave in self.contexto.abiertos
        listos = sum(1 for r in recursos if r.completado)
        self.boton_recursos = QPushButton()
        self.boton_recursos.setFlat(True)
        self.boton_recursos.setCursor(Qt.PointingHandCursor)
        self.boton_recursos.setStyleSheet(
            f"text-align: left; border: none; background: transparent; color: {PALETA['acento']};"
            " padding: 2px 0;"
        )
        self.boton_recursos.setText(
            f"{_flecha(abierto)} " + t("Recursos de fabricacion ({listos} de {total} listos)",
                                        listos=listos, total=len(recursos))
        )
        self.boton_recursos.setToolTip(t("Abrir para marcar cada recurso por separado"))
        self.boton_recursos.clicked.connect(lambda: self._alternar_recursos(clave))
        self.caja.addWidget(self.boton_recursos)

        self.panel_recursos = QWidget()
        caja = QVBoxLayout(self.panel_recursos)
        caja.setContentsMargins(0, 2, 0, 2)
        caja.setSpacing(4)
        if abierto:
            for recurso in recursos:
                fila = FilaRecurso(self.objetivo, recurso, self.usuario, self.contexto)
                fila.cambiado.connect(self.cambiada.emit)
                caja.addWidget(fila)
        self.panel_recursos.setVisible(abierto)
        self.caja.addWidget(self.panel_recursos)

    def _alternar_recursos(self, clave: str) -> None:
        if clave in self.contexto.abiertos:
            self.contexto.abiertos.discard(clave)
        else:
            self.contexto.abiertos.add(clave)
        self.cambiada.emit()  # se repinta con el panel abierto o cerrado

    # -- ruta --

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
                f"<span style='color:{COLOR_BOVEDA}'>{t('Solo en boveda')}</span> &middot; "
                f"<span style='color:{p['texto']}'>{nombre}</span> ({radiante}). "
                + t("Hay que comprarla a otro jugador.")
            )
        mision = ruta["mision"]
        detalle = f"{html.escape(mision['donde'])}" if mision else t("sin mision conocida")
        if mision and mision["mision"]:
            detalle += " &middot; " + glosario.enlace_mision(
                mision.get("modo"), mision["mision"], p["texto"], mision.get("rotacion"))
        if mision and mision["rotacion"]:
            detalle += " &middot; " + _rotacion(mision, p["texto"])
        return (
            f"<span style='color:{p['texto']}'><b>{nombre}</b></span> ({radiante}) "
            f"&middot; {t('farmeala en')} <span style='color:{p['texto']}'>{detalle}</span>"
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
            t("Ya tienes los {meta} que querias de {nombre}. Quieres subir la meta a {nueva}?",
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
        return DialogoCantidad(self.objetivo.nombre, self.objetivo.objetivo, self.objetivo.actual,
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
            t("Seguro que quieres quitar {nombre}? Se pierde lo que llevabas apuntado.",
              nombre=self.objetivo.nombre),
        ):
            return
        estado_objetivos.borrar(self.usuario, self.objetivo.id)
        self.contexto.seleccionados.discard(self.clave)
        self.cambiada.emit()


class PanelSet(Tarjeta):
    """Un set (Ash Prime y sus piezas) como un solo panel que se despliega con un clic."""

    cambiada = Signal()
    seleccion = Signal(str, bool)

    def __init__(self, entrada, usuario, indice, contexto: _Contexto, parent=None):
        hechas, total = entrada.hechas, len(entrada.objetivos)
        color = COLOR_DISPONIBLE if hechas == total else PALETA["acento"]
        super().__init__(color, parent)
        self.entrada, self.usuario, self.indice, self.contexto = entrada, usuario, indice, contexto
        self.clave = entrada.clave
        abierto = self.clave in contexto.abiertos
        p = PALETA

        self.marcar = QCheckBox()
        self.marcar.setToolTip(t("Marcar para borrar varios a la vez"))
        self.marcar.setChecked(self.clave in contexto.seleccionados)
        self.marcar.toggled.connect(lambda v: self.seleccion.emit(self.clave, v))

        self.cabecera = QPushButton()
        self.cabecera.setFlat(True)
        self.cabecera.setCursor(Qt.PointingHandCursor)
        self.cabecera.setStyleSheet(
            f"text-align: left; border: none; background: transparent; color: {p['texto']};"
            " font-size: 16px; font-weight: bold; padding: 2px 0;"
        )
        self.cabecera.setText(f"{_flecha(abierto)}  {entrada.nombre}")
        self.cabecera.setToolTip(t("Clic para ver u ocultar las piezas"))
        self.cabecera.clicked.connect(self._alternar)

        self.etiqueta = QLabel(
            t("Set: {hechas} de {total} piezas", hechas=hechas, total=total)
            + (f"  <span style='color:{COLOR_DISPONIBLE}'>{t('Completado').upper()}</span>"
               if hechas == total else "")
        )
        self.etiqueta.setTextFormat(Qt.RichText)
        self.etiqueta.setStyleSheet(f"color: {p['suave']};")
        self.barra = QProgressBar()
        self.barra.setRange(0, total)
        self.barra.setValue(hechas)
        self.barra.setTextVisible(False)
        self.barra.setFixedSize(120, 8)
        self.quitar = _boton_pequeno(t("Quitar set"))
        self.quitar.clicked.connect(self._borrar)

        arriba = QHBoxLayout()
        arriba.setSpacing(6)
        arriba.addWidget(self.marcar)
        arriba.addWidget(self.cabecera, 1)
        arriba.addWidget(self.etiqueta)
        arriba.addWidget(self.barra)
        arriba.addSpacing(6)
        arriba.addWidget(self.quitar)
        self.caja.addLayout(arriba)

        self.piezas = QWidget()
        caja = QVBoxLayout(self.piezas)
        caja.setContentsMargins(10, 4, 0, 0)
        caja.setSpacing(6)
        self.filas: list[FilaObjetivo] = []
        if abierto:  # las piezas se montan solo si se ven
            for objetivo in entrada.objetivos:
                ruta = estado_objetivos.ruta_de(indice, objetivo.unique_name) if indice is not None else None
                fila = FilaObjetivo(objetivo, ruta, usuario, indice=indice, contexto=contexto,
                                    seleccionable=False, dentro_de_set=True)
                fila.cambiada.connect(self.cambiada.emit)
                self.filas.append(fila)
                caja.addWidget(fila)
        self.piezas.setVisible(abierto)
        self.caja.addWidget(self.piezas)

    def _alternar(self) -> None:
        if self.clave in self.contexto.abiertos:
            self.contexto.abiertos.discard(self.clave)
        else:
            self.contexto.abiertos.add(self.clave)
        self.cambiada.emit()

    def _borrar(self) -> None:
        if not confirmar(
            self, t("Quitar set"),
            t("Seguro que quieres quitar el set {nombre} con sus {n} piezas? Se pierde lo que llevabas apuntado.",
              nombre=self.entrada.nombre, n=len(self.entrada.objetivos)),
        ):
            return
        estado_objetivos.borrar_varios(self.usuario, [o.id for o in self.entrada.objetivos])
        self.contexto.seleccionados.discard(self.clave)
        self.cambiada.emit()


# -- la pestana ---------------------------------------------------------------------


class PestanaObjetivos(QWidget):
    # Se emite cada vez que la lista cambia (anadir, sumar, borrar): Mundo la usa.
    cambiados = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.usuario: sqlite3.Connection = usuario_db.conectar()
        self.indice: sqlite3.Connection | None = None
        self.contexto = _Contexto()
        self.estado = SIN_EMPEZAR
        self.categoria: str | None = None
        self.pagina = 0
        self._pestana_elegida = False
        self._entradas_pagina: list = []

        self.resumen = QLabel("")
        self.resumen.setTextFormat(Qt.RichText)

        self.estados = QTabBar()
        self.estados.setExpanding(False)
        self.estados.setDrawBase(False)
        for _ in ESTADOS:
            self.estados.addTab("")
        self.estados.currentChanged.connect(self._cambiar_estado)

        self.filtro = QComboBox()
        _proteger_rueda(self.filtro)
        self.filtro.currentIndexChanged.connect(self._cambiar_categoria)
        self.todos = QCheckBox()
        self.todos.toggled.connect(self._marcar_pagina)
        self.borrar_marcados = QPushButton()
        self.borrar_marcados.clicked.connect(self._borrar_marcados)

        filtros = QHBoxLayout()
        filtros.setSpacing(8)
        self.etiqueta_filtro = QLabel()
        filtros.addWidget(self.etiqueta_filtro)
        filtros.addWidget(self.filtro)
        filtros.addStretch(1)
        filtros.addWidget(self.todos)
        filtros.addWidget(self.borrar_marcados)

        self.contenido = QWidget()
        self.caja_filas = QVBoxLayout(self.contenido)
        self.caja_filas.setContentsMargins(0, 0, 4, 0)
        self.caja_filas.setSpacing(8)
        self.caja_filas.addStretch(1)
        self.vacio = QLabel()
        self.vacio.setWordWrap(True)
        self.vacio.setAlignment(Qt.AlignCenter)

        self.desplazable = QScrollArea()
        self.desplazable.setWidgetResizable(True)
        self.desplazable.setWidget(self.contenido)

        self.anterior = QPushButton()
        self.siguiente = QPushButton()
        self.texto_pagina = QLabel()
        self.anterior.clicked.connect(lambda: self._ir_a_pagina(self.pagina - 1))
        self.siguiente.clicked.connect(lambda: self._ir_a_pagina(self.pagina + 1))
        paginas = QHBoxLayout()
        paginas.addStretch(1)
        paginas.addWidget(self.anterior)
        paginas.addWidget(self.texto_pagina)
        paginas.addWidget(self.siguiente)
        paginas.addStretch(1)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 8, 4, 4)
        caja.setSpacing(8)
        caja.addWidget(self.resumen)
        caja.addWidget(self.estados)
        caja.addLayout(filtros)
        caja.addWidget(self.desplazable, 1)
        caja.addLayout(paginas)
        self._traducir_fijos()

    def _traducir_fijos(self) -> None:
        self.etiqueta_filtro.setText(t("Mostrar:"))
        self.filtro.blockSignals(True)
        self.filtro.clear()
        for clave, texto in (
            (None, t("Todas las categorias")),
            (estado_objetivos.SETS, t("Sets y piezas")),
            (estado_objetivos.WARFRAMES, t("Warframes")),
            (estado_objetivos.ARMAS, t("Armas")),
            (estado_objetivos.RECURSOS, t("Recursos")),
            (estado_objetivos.OTROS, t("Otros")),
        ):
            self.filtro.addItem(texto, clave)
        self.filtro.setCurrentIndex(max(0, self.filtro.findData(self.categoria)))
        self.filtro.blockSignals(False)
        self.todos.setText(t("Marcar los de esta pagina"))
        self.anterior.setText(t("‹ Anterior"))
        self.siguiente.setText(t("Siguiente ›"))

    def conectar_indice(self, con: sqlite3.Connection) -> None:
        self.indice = con
        self.refrescar()

    def retraducir(self) -> None:
        """Las filas se generan enteras en cada refresco, asi que basta con repintar."""
        self._traducir_fijos()
        self.refrescar()

    # -- alta desde la ficha --------------------------------------------------

    def anadir_item(self, item_id: int, set_completo: bool = False) -> int:
        if self.indice is None:
            self.indice = indice_datos.conectar()
        if set_completo:
            ids = estado_objetivos.anadir_set(self.usuario, self.indice, item_id)
        else:
            fila = self.indice.execute(
                "SELECT unique_name, nombre_en, nombre_es, item_count FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not fila:
                return 0
            # El objetivo guarda el nombre con el que se creo, en el idioma de ese momento.
            nombre = (fila[2] or fila[1]) if es_castellano() else (fila[1] or fila[2])
            ids = [estado_objetivos.anadir(self.usuario, fila[0], nombre, fila[3] or 1, indice=self.indice)]
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
            t("Seguro que quieres borrar {n} objetivos? ({lista}) Se pierde lo que llevabas apuntado.",
              n=len(nombres), lista=lista),
        ):
            return
        estado_objetivos.borrar_varios(self.usuario, ids)
        self.contexto.seleccionados.clear()
        self.refrescar()

    # -- pintado ---------------------------------------------------------------

    def refrescar(self) -> None:
        p = PALETA
        # Tambien se llama al cambiar de tema: el resumen lleva el color en su hoja.
        self.resumen.setStyleSheet(f"color: {p['suave']};")
        self.vacio.setStyleSheet(f"color: {p['suave']}; padding: 30px;")
        if self.indice is not None:
            try:
                self.indice.execute("SELECT 1")
                estado_objetivos.completar_datos(self.usuario, self.indice)
            except sqlite3.Error:
                self.indice = None  # el indice se esta reconstruyendo
        self._vaciar()

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
            self.resumen.setText(t("Todavia no tienes objetivos. Busca algo y pulsa '+ Objetivo'."))
        else:
            pendientes = cuenta[SIN_EMPEZAR] + cuenta[EN_PROGRESO]
            self.resumen.setText(
                t("{n} por conseguir", n=f"<b style='color:{p['texto']}'>{pendientes}</b>")
                + " &middot; " + t("{n} completados", n=cuenta[COMPLETADOS])
            )

        lista = [e for e in todas if e.estado == self.estado]
        trozo, self.pagina, total = estado_objetivos.paginar(lista, self.pagina)
        self._entradas_pagina = trozo
        # Lo marcado que ya no existe (borrado desde otra pestana) se olvida.
        vivas = {e.clave for e in estado_objetivos.entradas(self.usuario)}
        self.contexto.seleccionados &= vivas

        if not trozo:
            self.vacio.setText(
                t("Todavia no tienes objetivos. Busca algo y pulsa '+ Objetivo'.") if not hay_alguno
                else t("Aqui no hay nada con este filtro.")
            )
            self.vacio.show()
            self.caja_filas.insertWidget(0, self.vacio)
        for entrada in trozo:
            if entrada.es_set:
                widget = PanelSet(entrada, self.usuario, self.indice, self.contexto)
            else:
                objetivo = entrada.objetivos[0]
                ruta = (
                    estado_objetivos.ruta_de(self.indice, objetivo.unique_name)
                    if self.indice is not None
                    else None
                )
                widget = FilaObjetivo(objetivo, ruta, self.usuario, indice=self.indice,
                                      contexto=self.contexto)
            widget.cambiada.connect(lambda clave=entrada.clave: self._tras_cambio(clave))
            widget.seleccion.connect(self._seleccion)
            self.caja_filas.insertWidget(self.caja_filas.count() - 1, widget)

        self.texto_pagina.setText(t("Pagina {n} de {total}", n=self.pagina + 1, total=total))
        self.anterior.setEnabled(self.pagina > 0)
        self.siguiente.setEnabled(self.pagina < total - 1)
        for control in (self.anterior, self.siguiente, self.texto_pagina):
            control.setVisible(total > 1)
        self.todos.blockSignals(True)
        self.todos.setChecked(bool(trozo) and all(e.clave in self.contexto.seleccionados for e in trozo))
        self.todos.setEnabled(bool(trozo))
        self.todos.blockSignals(False)
        self._pintar_borrar()
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
                widget.deleteLater()

    def eras_necesarias(self) -> dict[str, list[str]]:
        if self.indice is None:
            return {}
        return estado_objetivos.eras_necesarias(self.indice, self.usuario)
