"""Panel de recompensas de reliquia: una tarjeta por recompensa, al estilo de un overlay.

Alternativa a las etiquetas pequenas (`etiquetas.py`), elegible en Ajustes
(`estilo_recompensas`). Misma interfaz (`mostrar`, `marcar_veredicto`, `hide`)
para que la ventana no distinga cual esta activa.

Diseno: una fila de tarjetas justo DEBAJO de las tarjetas del juego, ocupando
solo el ancho que ocupan ellas. Asi cada tarjeta queda bajo su recompensa, no se
tapa nada del juego que importe (los nombres de la escuadra quedan detras del
panel, semitransparente) y un overlay de terceros que viva en el borde inferior
(AlecaFrame) sigue viendose. Cada tarjeta lleva: miniatura del objeto (las
imagenes que ya se descargan a DIR_IMG), nombre, platino con su criterio,
ducados, boveda, objetivo del usuario ("2/3"), cuantas tienes (si se leyo el
inventario), tiempo medio de farmeo y maestria. La mejor opcion lleva el borde
dorado y su banda; una tarjeta sin identificar lo dice y no lleva nada mas.
Abajo, el total en platino de lo que hay en pantalla.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..captura.reliquias import SIN_IDENTIFICAR, texto_platino
from ..idiomas import t
from ..registro_log import obtener
from .etiquetas import (
    COLOR_A_MEDIAS,
    COLOR_BOVEDA,
    COLOR_DOMINADO,
    COLOR_MEJOR,
    COLOR_MEJOR_DUDOSO,
    COLOR_OBJETIVO,
    COLOR_SIN_DOMINAR,
    COLOR_TEXTO,
    SEGUNDOS_VISIBLE,
)
from .widgets import imagenes

log = obtener("panel_recompensas")

FONDO = QColor(8, 12, 18, 205)
FONDO_TARJETA = QColor(22, 30, 42, 235)
BORDE_TARJETA = QColor(70, 90, 120)
SUAVE = QColor(150, 165, 185)
PLATINO = QColor(120, 190, 255)
DUCADOS = QColor(240, 190, 90)
ALTO_TARJETA = 128
ANCHO_MINIMO_TARJETA = 190
HUECO = 8
LADO_IMAGEN = 56
_COLORES_MAESTRIA = {"dominado": COLOR_DOMINADO, "a_medias": COLOR_A_MEDIAS, "sin_tocar": COLOR_SIN_DOMINAR}


class PanelRecompensas(QWidget):
    """Tarjetas bajo las recompensas del juego. Ventana transparente y atravesable."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.recompensas: list = []
        self.maestria: dict[int, tuple[str, str]] = {}
        self.extras: dict[int, dict] = {}  # item_id -> {"minutos": str, "tienes": int|None}
        self._seguro = True
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self.hide)
        imagenes().lista.connect(lambda _n: self.update())

    # -- misma interfaz que EtiquetasRecompensas -----------------------------------

    def mostrar(self, recompensas: list, maestria: dict | None = None, extras: dict | None = None) -> None:
        self.recompensas = [r for r in recompensas if r.caja]
        self.maestria = maestria or {}
        self.extras = extras or {}
        self._seguro = True
        if not self.recompensas:
            self.hide()
            return
        pantalla = self.screen() or self.windowHandle().screen()
        geometria = pantalla.geometry() if pantalla else QRect(0, 0, 1920, 1080)
        self.setGeometry(geometria)
        self.show()
        self.raise_()
        self.update()
        self._temporizador.start(SEGUNDOS_VISIBLE * 1000)
        if sys.platform.startswith("win"):
            try:
                from .etiquetas import EtiquetasRecompensas

                EtiquetasRecompensas._hacer_atravesable(self)
            except Exception as e:  # noqa: BLE001
                log.debug("No se pudo hacer el panel atravesable: %s", e)

    def marcar_veredicto(self, recompensas: list, veredicto) -> None:
        if not self.recompensas:
            return
        if {r.item_id for r in self.recompensas} != {r.item_id for r in recompensas}:
            return
        actualizadas = {r.item_id: r for r in recompensas}
        for r in self.recompensas:
            nuevo = actualizadas.get(r.item_id)
            if nuevo is None:
                continue
            r.valor, r.mejor, r.nota, r.platino = nuevo.valor, nuevo.mejor, nuevo.nota, nuevo.platino
            r.criterio_platino = nuevo.criterio_platino
        self._seguro = veredicto.seguro
        self.update()

    # -- geometria ----------------------------------------------------------------

    def rectangulo_panel(self) -> QRect:
        """Bajo la fila de tarjetas del juego, del ancho de esa fila (minimo por tarjeta)."""
        n = len(self.recompensas)
        izquierda = min(r.caja[0] for r in self.recompensas)
        derecha = max(r.caja[0] + r.caja[2] for r in self.recompensas)
        base = max(r.caja[1] + r.caja[3] for r in self.recompensas)
        ancho = max(derecha - izquierda + 2 * HUECO, n * (ANCHO_MINIMO_TARJETA + HUECO) + HUECO)
        centro = (izquierda + derecha) // 2
        x = max(0, min(centro - ancho // 2, self.width() - ancho))
        y = min(base + 10, self.height() - ALTO_TARJETA - 2 * HUECO - 24)
        return QRect(x, y, ancho, ALTO_TARJETA + 2 * HUECO + 24)

    def rectangulos_tarjetas(self, panel: QRect) -> list[QRect]:
        n = len(self.recompensas)
        ancho = (panel.width() - HUECO * (n + 1)) // n
        return [
            QRect(panel.x() + HUECO + i * (ancho + HUECO), panel.y() + HUECO, ancho, ALTO_TARJETA)
            for i in range(n)
        ]

    # -- pintado ------------------------------------------------------------------

    def paintEvent(self, evento):  # noqa: N802 - firma de Qt
        if not self.recompensas:
            return
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.Antialiasing)
        panel = self.rectangulo_panel()
        pintor.setPen(Qt.NoPen)
        pintor.setBrush(FONDO)
        pintor.drawRoundedRect(panel, 10, 10)

        normal = QFont("Segoe UI", 10)
        negrita = QFont("Segoe UI", 10)
        negrita.setBold(True)
        pequena = QFont("Segoe UI", 9)
        total_platino = 0
        con_precio = 0
        for r, caja in zip(self.recompensas, self.rectangulos_tarjetas(panel)):
            self._pintar_tarjeta(pintor, r, caja, normal, negrita, pequena)
            if r.platino is not None:
                total_platino += r.platino
                con_precio += 1

        # Pie: total en platino y cuantas tienen precio.
        pintor.setFont(pequena)
        pintor.setPen(SUAVE)
        pie = QRect(panel.x() + HUECO, panel.y() + HUECO + ALTO_TARJETA + 4, panel.width() - 2 * HUECO, 18)
        if con_precio:
            texto = t("Total en pantalla: {n} platino ({m} de {k} con precio)",
                      n=total_platino, m=con_precio, k=len(self.recompensas))
        else:
            texto = t("Sin precios todavia")
        pintor.drawText(pie, Qt.AlignLeft | Qt.AlignVCenter, texto)
        pintor.drawText(pie, Qt.AlignRight | Qt.AlignVCenter, "Farmadex")

    def _pintar_tarjeta(self, pintor, r, caja: QRect, normal, negrita, pequena) -> None:
        borde = BORDE_TARJETA
        grosor = 1
        if r.mejor:
            borde = COLOR_MEJOR if self._seguro else COLOR_MEJOR_DUDOSO
            grosor = 3
        elif r.objetivo:
            borde = COLOR_OBJETIVO
            grosor = 2
        elif r.vaulted:
            borde = COLOR_BOVEDA
            grosor = 2
        pintor.setPen(QPen(borde, grosor))
        pintor.setBrush(FONDO_TARJETA)
        pintor.drawRoundedRect(caja, 8, 8)

        x_texto = caja.x() + 10
        y = caja.y() + 8
        extra = self.extras.get(r.item_id, {})
        mapa = imagenes().pixmap(extra.get("imagen"), LADO_IMAGEN) if extra.get("imagen") else None
        if mapa is not None:
            pintor.drawPixmap(caja.x() + 8, caja.y() + 30, mapa)
            x_texto = caja.x() + 8 + LADO_IMAGEN + 8

        # Nombre (siempre arriba, a todo el ancho).
        pintor.setFont(negrita)
        pintor.setPen(COLOR_TEXTO if r.item_id != SIN_IDENTIFICAR else COLOR_SIN_DOMINAR)
        nombre = r.nombre if r.item_id != SIN_IDENTIFICAR else t("Sin identificar")
        pintor.drawText(QRect(caja.x() + 10, y, caja.width() - 20, 18), Qt.AlignLeft | Qt.AlignVCenter,
                        pintor.fontMetrics().elidedText(nombre, Qt.ElideRight, caja.width() - 20))
        y += 22

        lineas: list[tuple[str, QColor, QFont]] = []
        if r.item_id == SIN_IDENTIFICAR:
            lineas.append((pintor.fontMetrics().elidedText(r.texto_ocr, Qt.ElideRight, caja.width() - 20), SUAVE, pequena))
        else:
            if r.mejor:
                lineas.append((t("MEJOR OPCION") if self._seguro else t("Probablemente la mejor"),
                               COLOR_MEJOR if self._seguro else COLOR_MEJOR_DUDOSO, negrita))
            if r.platino is not None:
                lineas.append((texto_platino(r), PLATINO, normal))
            elif r.nota and r.nota.lower().startswith(("sin precio", "no price", "sans prix", "kein preis", "sem pre")):
                lineas.append((r.nota, SUAVE, pequena))
            if r.ducados:
                lineas.append((t("{n} ducados", n=r.ducados), DUCADOS, normal))
            if r.objetivo:
                lineas.append((t("Objetivo: {nombre}", nombre=r.objetivo), COLOR_OBJETIVO, normal))
            if extra.get("tienes") is not None:
                lineas.append((t("Tienes {n}", n=extra["tienes"]), COLOR_OBJETIVO if extra["tienes"] else SUAVE, pequena))
            if extra.get("minutos"):
                lineas.append((t("Farmeo medio: {tiempo}", tiempo=extra["minutos"]), SUAVE, pequena))
            if r.vaulted:
                lineas.append((t("En boveda"), COLOR_BOVEDA, pequena))
            marca = self.maestria.get(r.item_id)
            if marca:
                lineas.append((marca[0], _COLORES_MAESTRIA.get(marca[1], COLOR_SIN_DOMINAR), pequena))
        ancho_texto = caja.x() + caja.width() - 8 - x_texto
        for texto, color, fuente in lineas:
            if y + 15 > caja.y() + caja.height() - 2:
                break
            pintor.setFont(fuente)
            pintor.setPen(color)
            pintor.drawText(QRect(x_texto, y, ancho_texto, 16), Qt.AlignLeft | Qt.AlignVCenter,
                            pintor.fontMetrics().elidedText(texto, Qt.ElideRight, ancho_texto))
            y += 16
