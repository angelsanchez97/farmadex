"""Panel de recompensas de reliquia: una tarjeta por recompensa, al estilo de un overlay.

Alternativa a las etiquetas pequenas (`etiquetas.py`), elegible en Ajustes
(`estilo_recompensas`). Misma interfaz (`mostrar`, `marcar_veredicto`, `hide`)
para que la ventana no distinga cual esta activa.

Diseno: una fila de tarjetas justo DEBAJO de las tarjetas del juego, ocupando
solo el ancho que ocupan ellas. Asi cada tarjeta queda bajo su recompensa, no se
tapa nada del juego que importe (los nombres de la escuadra quedan detras del
panel, semitransparente) y un overlay de terceros que viva en el borde inferior
(AlecaFrame) sigue viendose.

Pensado para leerse en medio segundo: arriba de cada tarjeta, UNA etiqueta grande
de color con el motivo principal segun el preajuste de Ajustes ("Al abrir
reliquias, destacar", ver `captura/prioridad.py`): "TE FALTA", "COMPLETA SET 3/4",
"12 PLATINO"... La mejor opcion lleva borde dorado y su etiqueta mas grande e
intensa; las demas se atenuan sin dejar de leerse. Debajo, en pequeno, los
detalles: miniatura, nombre, platino con su criterio, ducados, objetivo ("2/3"),
cuantas tienes (si se leyo el inventario), farmeo medio, boveda y maestria. Una
tarjeta sin identificar lo dice y no lleva nada mas. Abajo, el total en platino.

Hay tres disenos (`VARIANTE`) que se probaron renderizados para elegir:

- "A" cinta: la etiqueta es una cinta de color a lo ancho de la tarjeta. Es la
  elegida: el color se ve de reojo, la palabra se lee sin esfuerzo y los
  detalles siguen ahi para quien los quiera.
- "B" semaforo: toda la tarjeta tenida del color del motivo y el numero o la
  palabra enorme en el centro. Se ve de lejos, pero el fondo de color le quita
  contraste al texto pequeno y cabe menos detalle.
- "C" compacta: icono + una sola palabra, la mejor mas grande. La que menos
  tapa, pero pierde casi todos los detalles.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..captura import prioridad as prio
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
    OPACIDAD_ATENUADA,
    SEGUNDOS_VISIBLE,
    color_motivo,
    emparejar,
)
from .widgets import imagenes

log = obtener("panel_recompensas")

FONDO = QColor(8, 12, 18, 205)
FONDO_TARJETA = QColor(22, 30, 42, 235)
BORDE_TARJETA = QColor(70, 90, 120)
SUAVE = QColor(150, 165, 185)
PLATINO = QColor(120, 190, 255)
DUCADOS = QColor(240, 190, 90)
TINTA_OSCURA = QColor(10, 14, 20)  # texto sobre una cinta de color vivo

# El diseno que se usa. Interno a proposito: se eligio uno y los otros quedan para
# poder volver a renderizarlos (herramientas/capturas/capturar_variantes_panel.py).
VARIANTE = "A"
VARIANTES = ("A", "B", "C")
ALTOS = {"A": 150, "B": 150, "C": 96}
ALTO_TARJETA = ALTOS[VARIANTE]
ANCHO_MINIMO_TARJETA = 190
ANCHO_UNA_TARJETA = 260
ANCHO_MAXIMO_TARJETA = 300
HUECO = 8
HUECO_RAREZA = 0.04  # fraccion del alto de pantalla bajo el nombre
LADO_IMAGEN = 48
ESTRELLA = "★ "
_COLORES_MAESTRIA = {"dominado": COLOR_DOMINADO, "a_medias": COLOR_A_MEDIAS, "sin_tocar": COLOR_SIN_DOMINAR}
_ICONOS = {"falta": "!", "set": "+", "nueva": "*", "platino": "P", "ducados": "D", "boveda": "B"}


def _fuente(puntos: float, negrita: bool = False) -> QFont:
    fuente = QFont("Segoe UI")
    fuente.setPointSizeF(puntos)
    fuente.setBold(negrita)
    return fuente


def _mezcla(a: QColor, b: QColor, fraccion: float) -> QColor:
    """`fraccion` de `a` sobre `b`, opaco (para tenir el fondo de una tarjeta)."""
    return QColor(
        round(a.red() * fraccion + b.red() * (1 - fraccion)),
        round(a.green() * fraccion + b.green() * (1 - fraccion)),
        round(a.blue() * fraccion + b.blue() * (1 - fraccion)),
        235,
    )


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
        self.prioridad = prio.PRIORIDAD_POR_DEFECTO  # la pone la ventana desde Ajustes
        self.variante = VARIANTE
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
        # El monitor del juego, no el primario (con dos monitores el panel no se veia).
        from .etiquetas import a_coordenadas_locales, pantalla_de_las_cajas

        geometria = pantalla_de_las_cajas(self.recompensas)
        a_coordenadas_locales(self.recompensas, geometria)
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
        parejas = emparejar(self.recompensas, recompensas)
        if parejas is None:
            return
        for r, nuevo in parejas:
            r.valor, r.mejor, r.nota, r.platino = nuevo.valor, nuevo.mejor, nuevo.nota, nuevo.platino
            r.criterio_platino = nuevo.criterio_platino
        self._seguro = veredicto.seguro
        self.update()

    # -- geometria ----------------------------------------------------------------

    @property
    def alto_tarjeta(self) -> int:
        return ALTOS.get(self.variante, ALTO_TARJETA)

    def _centros(self) -> list[int]:
        return [r.caja[0] + r.caja[2] // 2 for r in self.recompensas]

    def _ancho_tarjeta(self) -> int:
        """El hueco entre dos recompensas vecinas: asi cada tarjeta cabe bajo la suya."""
        centros = sorted(self._centros())
        if len(centros) > 1:
            paso = min(b - a for a, b in zip(centros, centros[1:]))
            ancho = paso - HUECO
        else:
            ancho = ANCHO_UNA_TARJETA
        return max(ANCHO_MINIMO_TARJETA, min(ancho, ANCHO_MAXIMO_TARJETA))

    def rectangulo_panel(self) -> QRect:
        """Bajo la fila de tarjetas del juego, abarcando justo las nuestras."""
        ancho = self._ancho_tarjeta()
        alto = self.alto_tarjeta
        centros = self._centros()
        base = max(r.caja[1] + r.caja[3] for r in self.recompensas)
        izquierda = min(centros) - ancho // 2 - HUECO
        total = max(centros) + ancho // 2 + HUECO - izquierda
        # Si no cabe tal cual (monitor mas pequeno que la captura), se desplaza dentro.
        izquierda = max(0, min(izquierda, self.width() - total))
        # Bajo el nombre el juego pinta la marca de rareza (bronce, plata, oro); el
        # panel pegado al nombre la tapaba. El hueco va en proporcion a la pantalla,
        # como la interfaz del juego (no al alto del texto: un nombre en dos lineas
        # lo doblaria).
        hueco_rareza = max(30, round(self.height() * HUECO_RAREZA))
        y = min(base + hueco_rareza, self.height() - alto - 2 * HUECO - 24)
        return QRect(izquierda, y, total, alto + 2 * HUECO + 24)

    def rectangulos_tarjetas(self, panel: QRect) -> list[QRect]:
        """Cada tarjeta centrada bajo SU recompensa.

        Antes se repartia el ancho del panel a partes iguales, y como los nombres
        del juego no miden lo mismo, las tarjetas quedaban corridas respecto a sus
        recompensas (captura de un usuario con Trumna, Euphona y Caliban).
        """
        ancho = self._ancho_tarjeta()
        rects = []
        for c in self._centros():
            x = max(panel.x() + HUECO // 2, min(c - ancho // 2, panel.right() - ancho - HUECO // 2))
            rects.append(QRect(x, panel.y() + HUECO, ancho, self.alto_tarjeta))
        return rects

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

        # Hasta que llega el veredicto no hay mejor, y entonces no se atenua nada.
        hay_mejor = any(r.mejor for r in self.recompensas)
        pintar = {"B": self._tarjeta_semaforo, "C": self._tarjeta_compacta}.get(self.variante, self._tarjeta_cinta)
        total_platino = 0
        con_precio = 0
        for r, caja in zip(self.recompensas, self.rectangulos_tarjetas(panel)):
            pintor.save()
            atenuada = hay_mejor and not r.mejor
            if atenuada:
                pintor.setOpacity(OPACIDAD_ATENUADA)
            pintar(pintor, r, caja, prio.motivo_principal(r, self.prioridad), atenuada)
            pintor.restore()
            if r.platino is not None:
                total_platino += r.platino
                con_precio += 1

        # Pie: total en platino y cuantas tienen precio.
        pintor.setFont(_fuente(9))
        pintor.setPen(SUAVE)
        pie = QRect(panel.x() + HUECO, panel.y() + HUECO + self.alto_tarjeta + 4, panel.width() - 2 * HUECO, 18)
        if con_precio:
            texto = t("Total en pantalla: {n} platino ({m} de {k} con precio)",
                      n=total_platino, m=con_precio, k=len(self.recompensas))
        else:
            texto = t("Sin precios todavia")
        pintor.drawText(pie, Qt.AlignLeft | Qt.AlignVCenter, texto)
        pintor.drawText(pie, Qt.AlignRight | Qt.AlignVCenter, "Farmadex")

    # -- piezas comunes -------------------------------------------------------------

    def _color_mejor(self) -> QColor:
        return COLOR_MEJOR if self._seguro else COLOR_MEJOR_DUDOSO

    def _marco(self, pintor, r, caja: QRect, fondo: QColor, borde_normal: QColor) -> None:
        if r.mejor:
            pintor.setPen(QPen(self._color_mejor(), 3))
        else:
            pintor.setPen(QPen(borde_normal, 1))
        pintor.setBrush(fondo)
        pintor.drawRoundedRect(caja, 8, 8)

    def _nombre(self, r) -> str:
        return r.nombre if r.item_id != SIN_IDENTIFICAR else t("Sin identificar")

    def _texto(self, pintor, rect: QRect, texto: str, fuente: QFont, color: QColor,
               alineacion=Qt.AlignLeft | Qt.AlignVCenter) -> None:
        pintor.setFont(fuente)
        pintor.setPen(color)
        pintor.drawText(rect, alineacion, pintor.fontMetrics().elidedText(texto, Qt.ElideRight, rect.width()))

    def _detalles(self, r) -> list[tuple[str, QColor, bool]]:
        """Las lineas pequenas de debajo: (texto, color, negrita)."""
        if r.item_id == SIN_IDENTIFICAR:
            return [(r.texto_ocr, SUAVE, False)]
        extra = self.extras.get(r.item_id, {})
        lineas: list[tuple[str, QColor, bool]] = []
        if r.mejor:
            lineas.append((t("MEJOR OPCION") if self._seguro else t("Probablemente la mejor"), self._color_mejor(), True))
        if r.platino is not None:
            lineas.append((texto_platino(r), PLATINO, False))
        elif r.nota and r.nota.lower().startswith(("sin precio", "no price", "sans prix", "kein preis", "sem pre")):
            lineas.append((r.nota, SUAVE, False))
        # Siempre: si falta el dato se dice, no desaparece la linea.
        lineas.append((t("{n} ducados", n=r.ducados), DUCADOS, False) if r.ducados else (t("Sin ducados"), SUAVE, False))
        if r.objetivo:
            lineas.append((t("Objetivo: {nombre}", nombre=r.objetivo), COLOR_OBJETIVO, False))
        if extra.get("tienes") is not None:
            lineas.append((t("Tienes {n}", n=extra["tienes"]), COLOR_OBJETIVO if extra["tienes"] else SUAVE, False))
        if extra.get("minutos"):
            lineas.append((t("Farmeo medio: {tiempo}", tiempo=extra["minutos"]), SUAVE, False))
        if r.vaulted:
            lineas.append((t("En boveda"), COLOR_BOVEDA, False))
        marca = self.maestria.get(r.item_id)
        if marca:
            lineas.append((marca[0], _COLORES_MAESTRIA.get(marca[1], COLOR_SIN_DOMINAR), False))
        return lineas

    def _resumen_corto(self, r) -> str:
        """Una sola linea de detalle para los disenos que no caben mas."""
        trozos = []
        if r.platino is not None:
            trozos.append(t("{n} platino", n=r.platino))
        if r.ducados:
            trozos.append(t("{n} ducados", n=r.ducados))
        if r.vaulted:
            trozos.append(t("En boveda"))
        return " · ".join(trozos) or (r.nota or "")

    # -- A: cinta de color arriba ---------------------------------------------------

    def _tarjeta_cinta(self, pintor, r, caja: QRect, motivo, atenuada: bool) -> None:
        color = color_motivo(motivo.clave)
        self._marco(pintor, r, caja, FONDO_TARJETA, BORDE_TARJETA)
        margen = 3 if r.mejor else 1
        alto_cinta = 38 if r.mejor else 30
        cinta = QRect(caja.x() + margen, caja.y() + margen, caja.width() - 2 * margen, alto_cinta)
        pintor.setPen(Qt.NoPen)
        if r.mejor:
            pintor.setBrush(color)  # viva, con la letra oscura encima
        else:
            tenue = QColor(color)
            tenue.setAlpha(55)
            pintor.setBrush(tenue)
        pintor.drawRoundedRect(cinta, 6, 6)
        pintor.drawRect(cinta.adjusted(0, alto_cinta // 2, 0, 0))  # esquinas de abajo rectas
        texto = (ESTRELLA if r.mejor else "") + motivo.texto.upper()
        self._texto(pintor, cinta.adjusted(8, 0, -8, 0), texto, _fuente(14.5 if r.mejor else 12, True),
                    TINTA_OSCURA if r.mejor else color, Qt.AlignCenter)

        y = cinta.bottom() + 5
        self._texto(pintor, QRect(caja.x() + 10, y, caja.width() - 20, 18), self._nombre(r), _fuente(10, True),
                    COLOR_TEXTO if r.item_id != SIN_IDENTIFICAR else COLOR_SIN_DOMINAR)
        y += 20
        x_texto = caja.x() + 10
        extra = self.extras.get(r.item_id, {})
        mapa = imagenes().pixmap(extra.get("imagen"), LADO_IMAGEN) if extra.get("imagen") else None
        if mapa is not None:
            pintor.drawPixmap(caja.x() + 8, y + 2, mapa)
            x_texto = caja.x() + 8 + LADO_IMAGEN + 8
        ancho_texto = caja.x() + caja.width() - 8 - x_texto
        for texto, color_linea, negrita in self._detalles(r):
            if y + 14 > caja.y() + caja.height() - 3:
                break
            self._texto(pintor, QRect(x_texto, y, ancho_texto, 15), texto, _fuente(8.5, negrita), color_linea)
            y += 15

    # -- B: semaforo, toda la tarjeta del color del motivo --------------------------

    def _tarjeta_semaforo(self, pintor, r, caja: QRect, motivo, atenuada: bool) -> None:
        color = color_motivo(motivo.clave)
        fondo = _mezcla(color, FONDO_TARJETA, 0.55 if r.mejor else 0.30)
        self._marco(pintor, r, caja, fondo, color.darker(140))
        blanco = QColor(245, 248, 252)
        nombre = (ESTRELLA if r.mejor else "") + self._nombre(r)
        self._texto(pintor, QRect(caja.x() + 10, caja.y() + 8, caja.width() - 20, 18), nombre, _fuente(9.5, True),
                    blanco, Qt.AlignCenter)
        centro = QRect(caja.x() + 8, caja.y() + 30, caja.width() - 16, caja.height() - 62)
        numero, _, unidad = motivo.texto.partition(" ")
        if motivo.clave in ("platino", "ducados") and numero.isdigit():
            pintor.setFont(_fuente(30 if r.mejor else 24, True))
            pintor.setPen(blanco)
            pintor.drawText(centro.adjusted(0, 0, 0, -18), Qt.AlignCenter, numero)
            self._texto(pintor, QRect(centro.x(), centro.bottom() - 20, centro.width(), 18), unidad.upper(),
                        _fuente(10, True), blanco, Qt.AlignCenter)
        else:
            pintor.setFont(_fuente(17 if r.mejor else 14, True))
            pintor.setPen(blanco)
            pintor.drawText(centro, Qt.AlignCenter | Qt.TextWordWrap, motivo.texto.upper())
        pie = QRect(caja.x() + 8, caja.bottom() - 28, caja.width() - 16, 24)
        if r.mejor:
            texto_pie = t("MEJOR OPCION") if self._seguro else t("Probablemente la mejor")
            self._texto(pintor, pie, texto_pie, _fuente(9, True), self._color_mejor(), Qt.AlignCenter)
        else:
            self._texto(pintor, pie, self._resumen_corto(r), _fuente(8.5), QColor(225, 232, 240), Qt.AlignCenter)

    # -- C: compacta, icono + una palabra ---------------------------------------------

    def _tarjeta_compacta(self, pintor, r, caja: QRect, motivo, atenuada: bool) -> None:
        color = color_motivo(motivo.clave)
        if atenuada:
            caja = caja.adjusted(8, 8, -8, -8)  # la mejor, mas grande que las demas
        self._marco(pintor, r, caja, FONDO_TARJETA, BORDE_TARJETA)
        lado = 38 if r.mejor else 30
        icono = QRect(caja.x() + 10, caja.y() + (caja.height() - lado) // 2 - 6, lado, lado)
        pintor.setPen(Qt.NoPen)
        pintor.setBrush(color)
        pintor.drawEllipse(icono)
        pintor.setFont(_fuente(15 if r.mejor else 12, True))
        pintor.setPen(TINTA_OSCURA)
        pintor.drawText(icono, Qt.AlignCenter, _ICONOS.get(motivo.clave, "?"))
        x = icono.right() + 10
        ancho = caja.right() - 8 - x
        y = icono.y() - 4
        palabra = (ESTRELLA if r.mejor else "") + motivo.texto.upper()
        self._texto(pintor, QRect(x, y, ancho, 24), palabra, _fuente(14 if r.mejor else 11.5, True), color)
        self._texto(pintor, QRect(x, y + 24, ancho, 16), self._nombre(r), _fuente(8.5, True), COLOR_TEXTO)
        self._texto(pintor, QRect(x, y + 40, ancho, 15), self._resumen_corto(r), _fuente(8), SUAVE)
