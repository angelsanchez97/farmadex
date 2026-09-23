"""Relleno de fondo de las filas de fuentes: cuanto mas rapido se consigue, mas lleno.

El texto enriquecido de Qt no entiende `linear-gradient`, asi que el relleno no puede ir
en el HTML. La fila lleva una marca (`<a name='relleno-873'>`, sin href: no es un enlace
ni cambia de color) y, una vez maquetado el documento, se le pone a cada celda un QBrush
con un QLinearGradient en ObjectBoundingMode con un corte duro. El corte de la fila se
reparte entre sus celdas segun su ancho real, para que el relleno recorra la fila entera
como una sola barra. Los anchos cambian al redimensionar, asi que se recalcula cada vez
que cambia el documento o su tamano.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QBrush, QColor, QGradient, QLinearGradient, QTextCursor
from PySide6.QtWidgets import QTextEdit

from .widgets import PALETA

# La mas rapida casi llena (no del todo, para que se vea donde acaba la barra) y la
# mas lenta con un minimo visible.
RELLENO_MIN = 0.08
RELLENO_MAX = 0.97
# Si todas las opciones tardan parecido (30 frente a 35 min), no se estiran de lleno a
# vacio: la escala cubre como poco un factor 6 entre la mejor y la peor.
RANGO_MINIMO = 6.0
# Cuanto tine el relleno al fondo del panel: tenue, para no quitar legibilidad.
OPACIDAD = 0.30
# Verde azulado para lo rapido y ambar para lo lento; se mezclan con los del tema.
VERDE_AZULADO = "#39d0c0"
AMBAR = "#f0b43c"

PREFIJO = "relleno-"
_MARCA = re.compile(r"^relleno-(\d{1,4})$")


def escala(minutos: Iterable[float | None]) -> tuple[float, float] | None:
    """(mejor, peor) de los tiempos con estimacion; None si no hay ninguno."""
    validos = [m for m in minutos if m is not None and m > 0]
    if not validos:
        return None
    return min(validos), max(validos)


def fraccion(minutos: float | None, referencia: tuple[float, float] | None) -> float | None:
    """Parte de la fila que se rellena, en escala logaritmica; None sin estimacion.

    Logaritmica porque los tiempos van de minutos a horas: en lineal la peor ocuparia
    todo y las buenas serian un punto. 10 min frente a 70 min queda casi lleno frente
    al minimo; 20 frente a 25 min, parecidos.
    """
    if minutos is None or minutos <= 0 or not referencia:
        return None
    mejor, peor = referencia
    rango = max(peor / mejor, RANGO_MINIMO)
    lento = math.log(max(minutos, mejor) / mejor) / math.log(rango)
    return RELLENO_MIN + (RELLENO_MAX - RELLENO_MIN) * max(0.0, min(1.0, 1.0 - lento))


def marca(valor: float | None) -> str:
    """Nombre de ancla que lleva la fila en el HTML; vacio si no lleva relleno."""
    return f"{PREFIJO}{round(valor * 1000)}" if valor is not None else ""


def _mezcla(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def color(valor: float, paleta: dict | None = None) -> QColor:
    """Tono del relleno ya fundido con el panel: ambar si es lento, verde azulado si es rapido."""
    p = paleta or PALETA
    rapido = _mezcla(QColor(p["ok"]), QColor(VERDE_AZULADO), 0.6)
    lento = _mezcla(QColor(p["aviso"]), QColor(AMBAR), 0.5)
    t = (valor - RELLENO_MIN) / (RELLENO_MAX - RELLENO_MIN)
    tono = _mezcla(lento, rapido, max(0.0, min(1.0, t)))
    return _mezcla(QColor(p["panel2"]), tono, OPACIDAD)


def _pincel(corte: float, tinte: QColor) -> QBrush:
    """Celda rellena hasta `corte` (0..1 de su ancho) y transparente despues."""
    if corte >= 1.0:
        return QBrush(tinte)
    if corte <= 0.0:
        return QBrush()
    gradiente = QLinearGradient(0, 0, 1, 0)
    gradiente.setCoordinateMode(QGradient.ObjectBoundingMode)
    vacio = QColor(tinte)
    vacio.setAlpha(0)
    gradiente.setColorAt(0.0, tinte)
    gradiente.setColorAt(corte, tinte)
    gradiente.setColorAt(min(1.0, corte + 1e-4), vacio)
    gradiente.setColorAt(1.0, vacio)
    return QBrush(gradiente)


class RellenoFilas(QObject):
    """Pinta el relleno de las filas marcadas de un QTextEdit y lo rehace al cambiar."""

    def __init__(self, vista: QTextEdit):
        super().__init__(vista)
        self.vista = vista
        self._aplicando = False
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(0)
        self._temporizador.timeout.connect(self.aplicar)
        documento = vista.document()
        documento.setUndoRedoEnabled(False)  # la ficha es de solo lectura
        documento.contentsChanged.connect(self._programar)
        documento.documentLayout().documentSizeChanged.connect(self._programar)

    def _programar(self, *_):
        if not self._aplicando:
            self._temporizador.start()

    def _filas(self):
        """(tabla, fila, fraccion) de cada fila marcada del documento."""
        bloque = self.vista.document().begin()
        vistas = set()
        while bloque.isValid():
            it = bloque.begin()
            while not it.atEnd():
                for nombre in it.fragment().charFormat().anchorNames():
                    encaje = _MARCA.match(nombre)
                    if not encaje:
                        continue
                    cursor = QTextCursor(bloque)
                    tabla = cursor.currentTable()
                    if tabla is None:
                        continue
                    fila = tabla.cellAt(cursor).row()
                    clave = (tabla.firstPosition(), fila)
                    if clave not in vistas:
                        vistas.add(clave)
                        yield tabla, fila, int(encaje.group(1)) / 1000
                it += 1
            bloque = bloque.next()

    def aplicar(self) -> None:
        documento = self.vista.document()
        maqueta = documento.documentLayout()
        self._aplicando = True
        try:
            for tabla, fila, valor in self._filas():
                relleno = tabla.format().cellPadding()
                # La primera columna es la franja de rareza: se respeta su color.
                celdas = [tabla.cellAt(fila, c) for c in range(1, tabla.columns())]
                tramos = []
                for celda in celdas:
                    caja = maqueta.blockBoundingRect(celda.firstCursorPosition().block())
                    tramos.append((caja.left() - relleno, caja.right() + relleno))
                izquierda, derecha = tramos[0][0], tramos[-1][1]
                if derecha - izquierda <= 1:
                    continue  # aun sin maquetar (vista oculta): se hara al mostrarse
                limite = izquierda + valor * (derecha - izquierda)
                tinte = color(valor)
                for celda, (a, b) in zip(celdas, tramos):
                    corte = (limite - a) / (b - a) if b > a else (1.0 if limite >= b else 0.0)
                    pincel = _pincel(corte, tinte)
                    formato = celda.format()
                    if formato.background() != pincel:
                        formato.setBackground(pincel)
                        celda.setFormat(formato)
        finally:
            self._aplicando = False
