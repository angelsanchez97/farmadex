"""Etiquetas flotantes encima de la pantalla de recompensas del juego.

Es una ventana transparente que no se puede pulsar (los clics atraviesan hasta
el juego), solo pinta texto al lado de cada recompensa reconocida.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..captura import prioridad as prio
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

# Un color por motivo (captura/prioridad.py), el mismo en las etiquetas y en el panel:
# con la cuenta atras corriendo se lee antes un color que una palabra.
COLORES_MOTIVO = {
    "falta": QColor(92, 214, 120),  # verde: es para lo que farmeas
    "set": QColor(64, 200, 214),  # turquesa: casi lo mismo, pero no es un objetivo
    "nueva": QColor(176, 146, 255),  # violeta: aun no lo tienes
    "platino": QColor(120, 190, 255),
    "ducados": QColor(240, 190, 90),
    "boveda": COLOR_BOVEDA,
}
# Lo que no se ha elegido pierde intensidad sin dejar de leerse.
OPACIDAD_ATENUADA = 0.6


def color_motivo(clave: str) -> QColor:
    return COLORES_MOTIVO.get(clave, COLOR_SIN_DOMINAR)


def emparejar(en_pantalla: list, llegadas: list) -> list[tuple] | None:
    """Cada recompensa en pantalla con su version del veredicto, o None si no encajan.

    Se empareja por POSICION: con dos recompensas iguales (dos jugadores con el
    mismo plano) emparejar por objeto dejaba las dos con los datos de la ultima,
    y si la mejor era la primera, la marca de "mejor" desaparecia de las dos.
    """
    ids_pantalla = [r.item_id for r in en_pantalla]
    ids_llegadas = [r.item_id for r in llegadas]
    if ids_pantalla == ids_llegadas:
        return list(zip(en_pantalla, llegadas))
    if sorted(ids_pantalla) != sorted(ids_llegadas):
        return None  # es otra pantalla
    # Mismas recompensas en otro orden: cada una de las que llegan se usa una sola vez.
    libres = list(llegadas)
    parejas = []
    for r in en_pantalla:
        nuevo = next(x for x in libres if x.item_id == r.item_id)
        libres.remove(nuevo)
        parejas.append((r, nuevo))
    return parejas


def pantalla_de_las_cajas(recompensas: list) -> QRect:
    """Geometria del monitor donde estan las tarjetas, que es el del juego.

    Las cajas vienen en coordenadas de escritorio. Antes la ventana se ponia
    siempre en el monitor del propio widget (el primario, porque nunca se ha
    ensenado): con el juego en el segundo monitor, las etiquetas se pintaban a
    2560 px de un widget de 2560 de ancho, o sea fuera, y no se veian nunca. Si
    ninguna pantalla contiene las cajas (captura vieja, pruebas sin monitor real)
    se vuelve al primario, como antes.
    """
    pantallas = QGuiApplication.screens()
    if recompensas and pantallas:
        x, y, ancho, alto = recompensas[0].caja
        cx, cy = x + ancho // 2, y + alto // 2
        for p in pantallas:
            if p.geometry().contains(cx, cy):
                return p.geometry()
    primaria = QGuiApplication.primaryScreen()
    return primaria.geometry() if primaria else QRect(0, 0, 1920, 1080)


def a_coordenadas_locales(recompensas: list, origen: QRect) -> None:
    """Pasa las cajas de coordenadas de escritorio a las de la ventana en `origen`."""
    if origen.x() == 0 and origen.y() == 0:
        return
    for r in recompensas:
        x, y, ancho, alto = r.caja
        r.caja = (x - origen.x(), y - origen.y(), ancho, alto)


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
        self.prioridad = prio.PRIORIDAD_POR_DEFECTO  # la pone la ventana desde Ajustes

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
        geometria = pantalla_de_las_cajas(self.recompensas)
        a_coordenadas_locales(self.recompensas, geometria)
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
        parejas = emparejar(self.recompensas, recompensas)
        if parejas is None:
            return
        for r, nuevo in parejas:
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
        # El motivo del preajuste va mas grande que el resto: es lo que se lee primero.
        grande = QFont("Segoe UI", 13)
        grande.setBold(True)
        muy_grande = QFont("Segoe UI", 15)
        muy_grande.setBold(True)
        hay_mejor = any(r.mejor for r in self.recompensas)

        # La mejor se pinta la ultima: si las etiquetas se pisan (tarjetas estrechas), queda encima.
        for r in sorted(self.recompensas, key=lambda r: r.mejor):
            x, y, ancho, alto = r.caja
            motivo = prio.motivo_principal(r, self.prioridad)
            color = color_motivo(motivo.clave)
            # Cada linea lleva su color y su letra, para no adivinarlos luego por el texto.
            lineas = [(r.nombre, COLOR_TEXTO, fuente)]
            color_mejor = None
            if r.mejor:
                color_mejor = COLOR_MEJOR if self._seguro else COLOR_MEJOR_DUDOSO
                lineas.append(("\u2605 " + motivo.texto.upper(), color, muy_grande))
                # Se decide en segundos y con el juego de fondo: la marca va justo
                # bajo el motivo, no al final, para que se vea de un vistazo.
                etiqueta_mejor = t("MEJOR OPCION") if self._seguro else t("Probablemente la mejor")
                lineas.append((etiqueta_mejor, color_mejor, fuente))
            else:
                lineas.append((motivo.texto.upper(), color, grande))
            detalle = []
            if r.platino is not None:
                detalle.append(texto_platino(r))
            if r.ducados:
                detalle.append(t("{n} ducados", n=r.ducados))
            if detalle:
                lineas.append((" · ".join(detalle), COLOR_TEXTO, fuente))
            if r.vaulted:
                lineas.append((t("En boveda"), COLOR_BOVEDA, fuente))
            if r.objetivo:
                lineas.append((t("Objetivo: {nombre}", nombre=r.objetivo), COLOR_OBJETIVO, fuente))
            marca = self.maestria.get(r.item_id)
            if marca:
                lineas.append((marca[0], _COLORES_MAESTRIA.get(marca[1], COLOR_SIN_DOMINAR), fuente))
            if r.nota:
                # Por que falta un dato o por que no se puede afirmar del todo:
                # la duda se enseña, nunca se esconde detras de una marca segura.
                lineas.append((r.nota, COLOR_SIN_DOMINAR, fuente))

            metricas = [QFontMetrics(f) for _texto, _color, f in lineas]
            ancho_caja = max(m.horizontalAdvance(texto) for m, (texto, _c, _f) in zip(metricas, lineas)) + 18
            alto_caja = sum(m.height() for m in metricas) + 12
            caja_x = max(0, x + ancho // 2 - ancho_caja // 2)
            caja_y = max(0, y - alto_caja - 8)

            pintor.save()
            if hay_mejor and not r.mejor:
                pintor.setOpacity(OPACIDAD_ATENUADA)
            pintor.setBrush(COLOR_FONDO)
            pintor.setPen(QPen(color_mejor or color, 3 if color_mejor else 2))
            pintor.drawRoundedRect(caja_x, caja_y, ancho_caja, alto_caja, 8, 8)

            y_linea = caja_y + 6
            for m, (texto, color_linea, fuente_linea) in zip(metricas, lineas):
                pintor.setFont(fuente_linea)
                pintor.setPen(color_linea)
                pintor.drawText(caja_x + 9, y_linea + m.ascent(), texto)
                y_linea += m.height()
            pintor.restore()
        pintor.end()

    def keyPressEvent(self, evento):  # noqa: N802 - por si llega el foco igualmente
        if evento.key() == Qt.Key_Escape:
            self.hide()
