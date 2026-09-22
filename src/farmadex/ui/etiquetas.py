"""Etiquetas flotantes encima de la pantalla de recompensas del juego.

Es una ventana transparente que no se puede pulsar (los clics atraviesan hasta
el juego), solo pinta texto al lado de cada recompensa reconocida.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..captura.reliquias import texto_platino
from ..idiomas import t
from ..registro_log import obtener

log = obtener("etiquetas")

SEGUNDOS_VISIBLE = 12
COLOR_FONDO = QColor(10, 14, 20, 225)
COLOR_BORDE = QColor(74, 163, 255)
COLOR_OBJETIVO = QColor(122, 199, 122)
COLOR_BOVEDA = QColor(240, 166, 60)
COLOR_TEXTO = QColor(230, 235, 245)
COLOR_DOMINADO = QColor(111, 207, 122)
COLOR_A_MEDIAS = QColor(240, 166, 60)
COLOR_SIN_DOMINAR = QColor(147, 160, 180)
# La marca de "esta es la que conviene": dorado vivo si el comparador esta seguro,
# el mismo tono apagado si solo es la mejor apuesta. Nunca se usa para elegir al azar:
# sin datos con que decidir, ninguna recompensa la lleva.
COLOR_MEJOR = QColor(255, 202, 40)
COLOR_MEJOR_DUDOSO = QColor(190, 165, 100)

_COLORES_MAESTRIA = {"dominado": COLOR_DOMINADO, "a_medias": COLOR_A_MEDIAS, "sin_tocar": COLOR_SIN_DOMINAR}


class EtiquetasRecompensas(QWidget):
    """Muestra platino, ducados, boveda y objetivo encima de cada recompensa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.recompensas: list = []
        self.maestria: dict[int, tuple[str, str]] = {}
        self._seguro = True  # del ultimo veredicto recibido; sin veredicto no marca nada

        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self.hide)

    def mostrar(self, recompensas: list, maestria: dict[int, tuple[str, str]] | None = None) -> None:
        """`maestria`: item_id -> (texto, clave de estado) para los que dan rango, si hay perfil."""
        self.recompensas = [r for r in recompensas if r.caja]
        self.maestria = maestria or {}
        self._seguro = True  # se reactiva marca a marca cuando llegue el veredicto nuevo
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
            self._hacer_atravesable()

    def marcar_veredicto(self, recompensas: list, veredicto) -> None:
        """Llega el veredicto del comparador (tarda: precios a ~300 ms por pieza).

        Anade la marca de "mejor" a las etiquetas que ya estan en pantalla, sin
        retrasar lo que ya se vio. Si lo que llega no encaja con lo que se esta
        mostrando ahora mismo (pantalla vieja, o ya escondida), se descarta: pintar
        el veredicto de una reliquia sobre la pantalla de otra seria peor que no
        pintar nada.
        """
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

    def _hacer_atravesable(self) -> None:
        """Por si el gestor de ventanas ignora WindowTransparentForInput."""
        try:
            import ctypes

            GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x20, 0x80000
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            estilo = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, estilo | WS_EX_TRANSPARENT | WS_EX_LAYERED
            )
        except Exception as e:  # noqa: BLE001 - es un apano, no puede tumbar nada
            log.debug("No se pudo hacer la ventana atravesable: %s", e)

    def paintEvent(self, evento):  # noqa: N802 - firma de Qt
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.Antialiasing)
        fuente = QFont("Segoe UI", 11)
        fuente.setBold(True)
        pintor.setFont(fuente)
        metrica = pintor.fontMetrics()

        for r in self.recompensas:
            x, y, ancho, alto = r.caja
            # Cada linea lleva su color, para no adivinarlo luego por el texto.
            lineas = [(r.nombre, COLOR_TEXTO)]
            color_mejor = None
            if r.mejor:
                # Se decide en segundos y con el juego de fondo: la marca va justo
                # bajo el nombre, no al final, para que se vea de un vistazo.
                color_mejor = COLOR_MEJOR if self._seguro else COLOR_MEJOR_DUDOSO
                etiqueta_mejor = t("MEJOR OPCION") if self._seguro else t("Probablemente la mejor")
                lineas.append((etiqueta_mejor, color_mejor))
            detalle = []
            if r.platino is not None:
                detalle.append(texto_platino(r))
            if r.ducados:
                detalle.append(t("{n} ducados", n=r.ducados))
            if detalle:
                lineas.append((" · ".join(detalle), COLOR_TEXTO))
            if r.vaulted:
                lineas.append((t("En boveda"), COLOR_BOVEDA))
            if r.objetivo:
                lineas.append((t("Objetivo: {nombre}", nombre=r.objetivo), COLOR_OBJETIVO))
            marca = self.maestria.get(r.item_id)
            if marca:
                lineas.append((marca[0], _COLORES_MAESTRIA.get(marca[1], COLOR_SIN_DOMINAR)))
            if r.nota:
                # Por que falta un dato o por que no se puede afirmar del todo:
                # la duda se enseña, nunca se esconde detras de una marca segura.
                lineas.append((r.nota, COLOR_SIN_DOMINAR))

            ancho_caja = max(metrica.horizontalAdvance(texto) for texto, _ in lineas) + 18
            alto_caja = metrica.height() * len(lineas) + 12
            caja_x = max(0, x + ancho // 2 - ancho_caja // 2)
            caja_y = max(0, y - alto_caja - 8)

            pintor.setBrush(COLOR_FONDO)
            borde = color_mejor or (COLOR_OBJETIVO if r.objetivo else (COLOR_BOVEDA if r.vaulted else COLOR_BORDE))
            pintor.setPen(QPen(borde, 3 if color_mejor else 2))
            pintor.drawRoundedRect(caja_x, caja_y, ancho_caja, alto_caja, 8, 8)

            for i, (texto, color) in enumerate(lineas):
                pintor.setPen(color)
                pintor.drawText(
                    caja_x + 9,
                    caja_y + 6 + metrica.ascent() + i * metrica.height(),
                    texto,
                )
        pintor.end()

    def keyPressEvent(self, evento):  # noqa: N802 - por si llega el foco igualmente
        if evento.key() == Qt.Key_Escape:
            self.hide()
