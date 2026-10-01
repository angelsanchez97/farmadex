"""Recuadros flotantes que salen solos encima del juego: precio de un objeto y panel de agrietado.

Los dos son la misma pieza (`CajaJuego`): una ventana de tipo tooltip pintada a mano en
estilo C que no coge el foco ni el raton y va siempre encima, con una lista de filas:

- ("titulo", texto[, tinta])        nombre grande
- ("sub", texto)                    linea pequena gris bajo el titulo
- ("fila", izquierda, derecha[, tinta])   rotulo a la izquierda y dato a la derecha
- ("cols", [celdas], [tintas])      tabla de columnas iguales (R0 / R10...)
- ("texto", texto[, tinta])         parrafo que se parte en lineas
- ("sep",)                          filete

Asi el contenido (que decide `vista_precio`/`panel_riven`) se prueba sin pintar nada, y
el aspecto es el mismo que el de la tarjeta de reliquia y el recuadro de "Leyendo…".
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .estilo_c import color, fuente, px, ruta_chaflan


class CajaJuego(QWidget):
    def __init__(self, ancho: int = 340, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.ancho_base = ancho
        self.filas: list[tuple] = []

    # -- medidas --

    def _margen(self) -> int:
        return px(12, False)

    def _alto_fila(self, fila: tuple, ancho: int) -> int:
        tipo = fila[0]
        if tipo == "titulo":
            return QFontMetrics(fuente("seccion")).height() + px(2, False)
        if tipo == "sub":
            return QFontMetrics(fuente("pequeno")).height() + px(4, False)
        if tipo in ("fila", "cols"):
            return QFontMetrics(fuente("normal", tam=13)).height() + px(4, False)
        if tipo == "texto":
            m = QFontMetrics(fuente("pequeno"))
            return m.boundingRect(QRect(0, 0, ancho, 4000), Qt.TextWordWrap, fila[1]).height() + px(4, False)
        if tipo == "sep":
            return px(9, False)
        return 0

    def sizeHint(self) -> QSize:  # noqa: N802 - firma de Qt
        ancho = px(self.ancho_base, False)
        util = ancho - 2 * self._margen()
        alto = 2 * self._margen() + sum(self._alto_fila(f, util) for f in self.filas)
        return QSize(ancho, max(alto, px(40, False)))

    # -- contenido --

    def poner(self, filas: list[tuple]) -> None:
        self.filas = list(filas)
        self.resize(self.sizeHint())
        self.update()

    def textos(self) -> list[str]:
        """Todo lo que ensena, en texto plano (para las pruebas y el registro)."""
        salida = []
        for f in self.filas:
            if f[0] in ("titulo", "sub", "texto"):
                salida.append(f[1])
            elif f[0] == "fila":
                salida.append(f"{f[1]}: {f[2]}")
            elif f[0] == "cols":
                salida.append(" | ".join(f[1]))
        return salida

    # -- pintura --

    def paintEvent(self, _evento):  # noqa: N802 - firma de Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        camino = ruta_chaflan(r, px(10, False))
        p.fillPath(camino, color("panel"))
        p.setPen(QPen(color("acento_tenue"), 1))
        p.drawPath(camino)
        p.setPen(QPen(color("acento"), 2))
        p.drawLine(QPointF(r.left() + px(10, False), r.top() + 1), QPointF(r.left() + px(48, False), r.top() + 1))
        m = self._margen()
        util = self.width() - 2 * m
        y = m
        for fila in self.filas:
            alto = self._alto_fila(fila, util)
            tipo = fila[0]
            if tipo == "titulo":
                p.setFont(fuente("seccion"))
                p.setPen(color(fila[2] if len(fila) > 2 and fila[2] else "texto"))
                texto = QFontMetrics(fuente("seccion")).elidedText(fila[1], Qt.ElideRight, util)
                p.drawText(QRectF(m, y, util, alto), Qt.AlignLeft | Qt.AlignVCenter, texto)
            elif tipo == "sub":
                p.setFont(fuente("pequeno"))
                p.setPen(color("suave"))
                p.drawText(QRectF(m, y, util, alto), Qt.AlignLeft | Qt.AlignVCenter, fila[1])
            elif tipo == "fila":
                f = fuente("normal", tam=13)
                p.setFont(f)
                p.setPen(color("suave"))
                p.drawText(QRectF(m, y, util, alto), Qt.AlignLeft | Qt.AlignVCenter, fila[1])
                p.setFont(fuente("dato"))
                p.setPen(color(fila[3] if len(fila) > 3 and fila[3] else "texto"))
                p.drawText(QRectF(m, y, util, alto), Qt.AlignRight | Qt.AlignVCenter, fila[2])
            elif tipo == "cols":
                celdas = fila[1]
                tintas = fila[2] if len(fila) > 2 else []
                ancho_celda = util / max(1, len(celdas))
                p.setFont(fuente("normal", tam=13))
                for i, celda in enumerate(celdas):
                    p.setPen(color(tintas[i] if i < len(tintas) and tintas[i] else ("suave" if i == 0 else "texto")))
                    alineado = Qt.AlignLeft if i == 0 else Qt.AlignRight
                    p.drawText(QRectF(m + i * ancho_celda, y, ancho_celda, alto), alineado | Qt.AlignVCenter, celda)
            elif tipo == "texto":
                p.setFont(fuente("pequeno"))
                p.setPen(color(fila[2] if len(fila) > 2 and fila[2] else "suave"))
                p.drawText(QRectF(m, y, util, alto), Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, fila[1])
            elif tipo == "sep":
                p.setPen(QPen(color("acento_tenue"), 1))
                p.drawLine(QPointF(m, y + alto / 2), QPointF(self.width() - m, y + alto / 2))
            y += alto
        p.end()
