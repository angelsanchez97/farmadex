"""Panel de recompensas de reliquia: una tarjeta por recompensa, al estilo de un overlay.

Alternativa a las etiquetas pequenas (`etiquetas.py`), elegible en Ajustes
(`estilo_recompensas`). Misma interfaz (`mostrar`, `marcar_veredicto`, `hide`)
para que la ventana no distinga cual esta activa.

Diseno: una fila de tarjetas justo DEBAJO de las tarjetas del juego, ocupando
solo el ancho que ocupan ellas. Asi cada tarjeta queda bajo su recompensa, no se
tapa nada del juego que importe (entre tarjeta y tarjeta se ve el juego) y un
overlay de terceros que viva en el borde inferior (AlecaFrame) sigue viendose.
Entre el nombre de la recompensa y el panel queda un hueco (`HUECO_RAREZA`) para
que se vea la marca de rareza que el juego pinta bajo el nombre.

Pensado para leerse en medio segundo: arriba de cada tarjeta, UNA cinta de color
con el motivo principal segun el preajuste de Ajustes ("Al abrir reliquias,
destacar", ver `captura/prioridad.py`): "TE FALTA", "COMPLETA SET 3/4",
"12 PLATINO"... La mejor opcion lleva una estrella, la cinta viva, el borde dorado
y el rotulo "MEJOR OPCION"; las demas se atenuan sin dejar de leerse. Debajo, en
pequeno, los detalles: nombre, platino con su criterio, ducados, objetivo, cuantas
tienes (si se leyo el inventario), farmeo medio, boveda y maestria. Una tarjeta
sin identificar lo dice y no lleva nada mas. Al pie, una barra con el total en
platino y que se esta destacando.

Forma del estilo C ("menu del juego", `estilo_c.py`): esquinas cortadas, remate
dorado, rotulos en mayusculas espaciadas. Los colores salen del tema activo; los
de los motivos y el dorado de "mejor" son fijos porque significan algo.

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

import math
import sys

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ..captura import prioridad as prio
from ..captura.reliquias import SIN_IDENTIFICAR, texto_platino
from ..idiomas import t
from ..registro_log import obtener
from . import widgets
from .estilo_c import TEXTO, TITULAR, ruta_chaflan
from .etiquetas import (
    COLOR_A_MEDIAS,
    COLOR_BOVEDA,
    COLOR_DOMINADO,
    COLOR_MEJOR,
    COLOR_MEJOR_DUDOSO,
    COLOR_SIN_DOMINAR,
    COLOR_TEXTO,
    SEGUNDOS_VISIBLE,
    color_motivo,
    emparejar,
)
from .widgets import imagenes

log = obtener("panel_recompensas")

# Colores fijos de los disenos B y C (el A, el elegido, toma los del tema).
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
ALTO_REFERENCIA = 1080  # las medidas del panel son para una pantalla de este alto
ALTO_PIE = 24        # la barra de abajo (total y que se destaca), dentro del panel
LADO_IMAGEN = 48
ESTRELLA = "★ "
CHAFLAN_TARJETA = 10  # esquinas cortadas de cada tarjeta (estilo C)
# Lo que no es la mejor pierde intensidad sin dejar de leerse. Algo menos que en las
# etiquetas pequenas (0.6): aqui la tarjeta entera ya se apaga con el texto suave.
OPACIDAD_ATENUADA = 0.78
_COLORES_MAESTRIA = {"dominado": COLOR_DOMINADO, "a_medias": COLOR_A_MEDIAS, "sin_tocar": COLOR_SIN_DOMINAR}
_ICONOS = {"falta": "!", "set": "+", "nueva": "*", "platino": "P", "ducados": "D", "boveda": "B"}


def _fuente(puntos: float, negrita: bool = False) -> QFont:
    fuente = QFont("Segoe UI")
    fuente.setPointSizeF(puntos)
    fuente.setBold(negrita)
    return fuente


def _letra(pixeles: int, peso: int = 400, titular: bool = False, espaciado: float = 0.0) -> QFont:
    """Letra del estilo C a tamano fijo: el panel mide lo mismo con cualquier escala."""
    familia = TITULAR if titular else TEXTO
    fuente = QFont(familia)
    fuente.setFamilies([familia, TEXTO])
    fuente.setPixelSize(pixeles)
    fuente.setWeight(QFont.Weight(peso))
    if espaciado:
        fuente.setLetterSpacing(QFont.AbsoluteSpacing, espaciado)
    return fuente


def _tema(clave: str, alfa: int = 255) -> QColor:
    """Un color del tema activo (Ajustes > Apariencia incluido)."""
    c = QColor(widgets.PALETA.get(clave, widgets.PALETA["texto"]))
    c.setAlpha(alfa)
    return c


def _mezcla(a: QColor, b: QColor, fraccion: float) -> QColor:
    """`fraccion` de `a` sobre `b`, opaco (para tenir el fondo de una tarjeta)."""
    return QColor(
        round(a.red() * fraccion + b.red() * (1 - fraccion)),
        round(a.green() * fraccion + b.green() * (1 - fraccion)),
        round(a.blue() * fraccion + b.blue() * (1 - fraccion)),
        235,
    )


def _rombo(pintor: QPainter, cx: float, cy: float, medio: float, c: QColor, relleno: bool) -> None:
    pintor.setPen(QPen(c, 1.2))
    pintor.setBrush(c if relleno else Qt.NoBrush)
    pintor.drawPolygon(QPolygonF([QPointF(cx, cy - medio), QPointF(cx + medio, cy), QPointF(cx, cy + medio),
                                  QPointF(cx - medio, cy)]))


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

    @property
    def factor(self) -> float:
        """Cuanto se agranda el panel con la pantalla del juego: 1 a 1080 de alto, 1.33 a
        1440, 2 a 2160. Todo lo del panel (tarjetas, letra, huecos) esta medido para 1080p;
        a 2560x1440 con la escala de Windows al 100 % salia pequeno al lado de las
        tarjetas del juego, que si crecen con la pantalla."""
        return max(1.0, min(2.0, self.height() / ALTO_REFERENCIA)) if self.height() > 0 else 1.0

    def _centros(self) -> list[float]:
        """Centro de cada recompensa, en unidades del panel (pixeles de 1080p)."""
        f = self.factor
        return [(r.caja[0] + r.caja[2] / 2) / f for r in self.recompensas]

    def _ancho_tarjeta(self) -> int:
        """El hueco entre dos recompensas vecinas: asi cada tarjeta cabe bajo la suya."""
        centros = sorted(self._centros())
        if len(centros) > 1:
            paso = min(b - a for a, b in zip(centros, centros[1:]))
            ancho = int(paso) - HUECO
        else:
            ancho = ANCHO_UNA_TARJETA
        return max(ANCHO_MINIMO_TARJETA, min(ancho, ANCHO_MAXIMO_TARJETA))

    def _panel_l(self) -> QRect:
        """Bajo la fila de tarjetas del juego, abarcando justo las nuestras (unidades del panel)."""
        f = self.factor
        ancho = self._ancho_tarjeta()
        alto = self.alto_tarjeta
        centros = self._centros()
        base = max(r.caja[1] + r.caja[3] for r in self.recompensas)
        izquierda = round(min(centros)) - ancho // 2 - HUECO
        total = round(max(centros)) + ancho // 2 + HUECO - izquierda
        # Si no cabe tal cual (monitor mas pequeno que la captura), se desplaza dentro.
        izquierda = max(0, min(izquierda, int(self.width() / f) - total))
        # Bajo el nombre el juego pinta la marca de rareza (bronce, plata, oro); el
        # panel pegado al nombre la tapaba. El hueco va en proporcion a la pantalla,
        # como la interfaz del juego (no al alto del texto: un nombre en dos lineas
        # lo doblaria). Se mide en pixeles de la pantalla, no del panel escalado, y se
        # redondea hacia arriba para no quedarse ni un pixel corto.
        hueco_rareza = max(30, round(self.height() * HUECO_RAREZA))
        y = min(math.ceil((base + hueco_rareza) / f), int(self.height() / f) - alto - 2 * HUECO - ALTO_PIE)
        return QRect(izquierda, y, total, alto + 2 * HUECO + ALTO_PIE)

    def _tarjetas_l(self, panel: QRect) -> list[QRect]:
        """Cada tarjeta centrada bajo SU recompensa.

        Antes se repartia el ancho del panel a partes iguales, y como los nombres
        del juego no miden lo mismo, las tarjetas quedaban corridas respecto a sus
        recompensas (captura de un usuario con Trumna, Euphona y Caliban).
        """
        ancho = self._ancho_tarjeta()
        rects = []
        for c in self._centros():
            x = max(panel.x() + HUECO // 2, min(round(c) - ancho // 2, panel.right() - ancho - HUECO // 2))
            rects.append(QRect(x, panel.y() + HUECO, ancho, self.alto_tarjeta))
        return rects

    def _pie_l(self, panel: QRect) -> QRect:
        """La barra de abajo: del borde de la primera tarjeta al de la ultima."""
        tarjetas = self._tarjetas_l(panel)
        izquierda = min(r.left() for r in tarjetas)
        derecha = max(r.right() for r in tarjetas)
        return QRect(izquierda, panel.y() + HUECO + self.alto_tarjeta + 6, derecha - izquierda + 1, ALTO_PIE - 2)

    def _a_pantalla(self, r: QRect) -> QRect:
        """De unidades del panel a pixeles de la pantalla."""
        f = self.factor
        x, y = math.floor(r.x() * f), math.floor(r.y() * f)
        return QRect(x, y, math.floor((r.x() + r.width()) * f) - x, math.floor((r.y() + r.height()) * f) - y)

    # En pixeles de pantalla (lo que ven los tests y quien quiera saber que tapa el panel).
    def rectangulo_panel(self) -> QRect:
        return self._a_pantalla(self._panel_l())

    def rectangulos_tarjetas(self, panel: QRect | None = None) -> list[QRect]:
        return [self._a_pantalla(r) for r in self._tarjetas_l(self._panel_l())]

    def rectangulo_pie(self, panel: QRect | None = None) -> QRect:
        return self._a_pantalla(self._pie_l(self._panel_l()))

    # -- pintado ------------------------------------------------------------------

    def paintEvent(self, evento):  # noqa: N802 - firma de Qt
        if not self.recompensas:
            return
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.Antialiasing)
        pintor.setRenderHint(QPainter.TextAntialiasing)
        pintor.setRenderHint(QPainter.SmoothPixmapTransform)
        # Se pinta en unidades de 1080p y el pintor lo agranda a la pantalla del juego.
        pintor.scale(self.factor, self.factor)
        panel = self._panel_l()

        # Hasta que llega el veredicto no hay mejor, y entonces no se atenua nada.
        hay_mejor = any(r.mejor for r in self.recompensas)
        pintar = {"B": self._tarjeta_semaforo, "C": self._tarjeta_compacta}.get(self.variante, self._tarjeta_cinta)
        for r, caja in zip(self.recompensas, self._tarjetas_l(panel)):
            pintor.save()
            atenuada = hay_mejor and not r.mejor
            if atenuada:
                pintor.setOpacity(OPACIDAD_ATENUADA)
            pintar(pintor, r, caja, prio.motivo_principal(r, self.prioridad), atenuada)
            pintor.restore()
        self._pie(pintor, self._pie_l(panel))
        pintor.end()

    def texto_total(self) -> str:
        """'Total en pantalla: 60 platino (4 de 4 con precio)' o que aun no hay precios."""
        con_precio = [r.platino for r in self.recompensas if r.platino is not None]
        if not con_precio:
            return t("Sin precios todavía")
        return t("Total en pantalla: {n} platino ({m} de {k} con precio)",
                 n=sum(con_precio), m=len(con_precio), k=len(self.recompensas))

    def _pie(self, pintor: QPainter, pie: QRect) -> None:
        """Barra del pie: FARMADEX, el total en platino y que se destaca (el elegido en dorado).

        Si no cabe todo (una o dos recompensas), primero se quedan fuera los preajustes no
        elegidos, luego la palabra FARMADEX; el total se recorta el ultimo."""
        camino = ruta_chaflan(QRectF(pie).adjusted(0.5, 0.5, -0.5, -0.5), 7)
        pintor.fillPath(camino, _tema("panel", 235))
        pintor.setPen(QPen(_tema("borde"), 1))
        pintor.drawPath(camino)
        acento = _tema("acento")
        suave, tenue = _tema("suave"), _tema("tenue")
        _rombo(pintor, pie.x() + 14, pie.center().y() + 0.5, 4, acento, False)

        rotulo = _letra(10, 600, titular=True, espaciado=2.5)
        normal = _letra(12)
        elegido = _letra(12, 600)
        x = pie.x() + 26
        derecha = pie.right() - 12
        textos_prio = [t(texto) for clave, texto, _ayuda in prio.PREAJUSTES]
        indice_elegido = prio.CLAVES.index(prio.normalizar(self.prioridad))
        cabecera = t("Destacar:") + " "

        def ancho(fuente: QFont, texto: str) -> int:
            pintor.setFont(fuente)
            return pintor.fontMetrics().horizontalAdvance(texto)

        marca = "FARMADEX"
        ancho_marca = ancho(rotulo, marca) + 14
        total = self.texto_total()
        ancho_total = ancho(normal, total)
        otros = [texto for i, texto in enumerate(textos_prio) if i != indice_elegido]
        ancho_otros = ancho(normal, " · " + " · ".join(otros))
        ancho_prio = ancho(normal, cabecera) + ancho(elegido, textos_prio[indice_elegido])
        disponible = derecha - x
        con_otros = ancho_marca + ancho_total + 24 + ancho_prio + ancho_otros <= disponible
        con_marca = ancho_marca + ancho_total + 24 + ancho_prio <= disponible
        con_prio = ancho_total + 24 + ancho_prio <= disponible

        if con_marca:
            pintor.setFont(rotulo)
            pintor.setPen(acento)
            pintor.drawText(QRect(x, pie.y(), ancho_marca, pie.height()), Qt.AlignLeft | Qt.AlignVCenter, marca)
            x += ancho_marca
        # A la derecha, de fuera hacia dentro: los otros preajustes, el elegido y "Destacar:".
        if con_prio:
            if con_otros:
                self._texto(pintor, QRect(derecha - ancho_otros, pie.y(), ancho_otros, pie.height()),
                            " · " + " · ".join(otros), normal, tenue)
                derecha -= ancho_otros
            ancho_elegido = ancho(elegido, textos_prio[indice_elegido])
            self._texto(pintor, QRect(derecha - ancho_elegido, pie.y(), ancho_elegido, pie.height()),
                        textos_prio[indice_elegido], elegido, acento)
            derecha -= ancho_elegido
            ancho_cab = ancho(normal, cabecera)
            self._texto(pintor, QRect(derecha - ancho_cab, pie.y(), ancho_cab, pie.height()), cabecera, normal, suave)
            derecha -= ancho_cab + 16
        self._texto(pintor, QRect(x, pie.y(), max(10, derecha - x), pie.height()), total, normal, suave)

    # -- piezas comunes -------------------------------------------------------------

    def _color_mejor(self) -> QColor:
        return COLOR_MEJOR if self._seguro else COLOR_MEJOR_DUDOSO

    def _camino(self, caja: QRect):
        return ruta_chaflan(QRectF(caja).adjusted(0.5, 0.5, -0.5, -0.5), CHAFLAN_TARJETA)

    def _marco(self, pintor, r, caja: QRect, fondo: QColor, borde_normal: QColor | None = None) -> None:
        """Tarjeta con dos esquinas cortadas; la mejor, con borde y remate dorados."""
        pintor.fillPath(self._camino(caja), fondo)
        self._marco_sin_fondo(pintor, r, caja, borde_normal)

    def _nombre(self, r) -> str:
        return r.nombre if r.item_id != SIN_IDENTIFICAR else t("Sin identificar")

    def _texto(self, pintor, rect: QRect, texto: str, fuente: QFont, color: QColor,
               alineacion=Qt.AlignLeft | Qt.AlignVCenter) -> None:
        pintor.setFont(fuente)
        pintor.setPen(color)
        pintor.drawText(rect, alineacion, pintor.fontMetrics().elidedText(texto, Qt.ElideRight, rect.width()))

    def _texto_mejor(self) -> str:
        return t("MEJOR OPCIÓN") if self._seguro else t("Probablemente la mejor")

    def _detalles(self, r) -> list[tuple[str, QColor, bool]]:
        """Las lineas pequenas de debajo del nombre: (texto, color, negrita)."""
        suave = _tema("suave")
        if r.item_id == SIN_IDENTIFICAR:
            return [(r.texto_ocr, suave, False)]
        extra = self.extras.get(r.item_id, {})
        lineas: list[tuple[str, QColor, bool]] = []
        # El objetivo primero: es lo que decide en "Lo que me falta".
        if r.objetivo:
            lineas.append((t("Objetivo: {nombre}", nombre=r.objetivo), _tema("secundario"), False))
        if r.platino is not None:
            lineas.append((texto_platino(r), suave, False))
        elif r.nota and r.nota.lower().startswith(("sin precio", "no price", "sans prix", "kein preis", "sem pre")):
            lineas.append((r.nota, suave, False))
        # Siempre: si falta el dato se dice, no desaparece la linea.
        lineas.append((t("{n} ducados", n=r.ducados), suave, False) if r.ducados else (t("Sin ducados"), suave, False))
        if extra.get("tienes") is not None:
            lineas.append((t("Tienes {n}", n=extra["tienes"]), suave, False))
        if extra.get("minutos"):
            lineas.append((t("Farmeo medio: {tiempo}", tiempo=extra["minutos"]), suave, False))
        if r.vaulted:
            lineas.append((t("En bóveda"), COLOR_BOVEDA, False))
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
            trozos.append(t("En bóveda"))
        return " · ".join(trozos) or (r.nota or "")

    # -- A: cinta de color arriba ---------------------------------------------------

    def _tarjeta_cinta(self, pintor, r, caja: QRect, motivo, atenuada: bool) -> None:
        color = color_motivo(motivo.clave)
        camino = self._camino(caja)
        pintor.fillPath(camino, _tema("panel", 240))
        # La cinta ocupa todo el ancho y sigue el corte de la esquina.
        alto_cinta = 34 if r.mejor else 28
        cinta = QColor(color)
        cinta.setAlpha(240 if r.mejor else 150)
        pintor.save()
        pintor.setClipPath(camino)
        pintor.fillRect(QRect(caja.x(), caja.y(), caja.width(), alto_cinta), cinta)
        pintor.restore()
        self._marco_sin_fondo(pintor, r, caja)
        texto = (ESTRELLA + " " if r.mejor else "") + motivo.texto.upper()
        self._texto(pintor, QRect(caja.x() + CHAFLAN_TARJETA, caja.y(), caja.width() - 2 * CHAFLAN_TARJETA, alto_cinta),
                    texto, _letra(16 if r.mejor else 13, 700, titular=True, espaciado=1.5), TINTA_OSCURA, Qt.AlignCenter)

        izquierda = caja.x() + 12
        ancho = caja.width() - 24
        y = caja.y() + alto_cinta + 5
        if r.mejor:
            self._texto(pintor, QRect(izquierda, y, ancho, 14), self._texto_mejor().upper(),
                        _letra(10, 600, titular=True, espaciado=2), self._color_mejor())
            y += 15
        else:
            y += 2
        identificada = r.item_id != SIN_IDENTIFICAR
        color_nombre = _tema("texto") if (r.mejor or not atenuada) else _tema("suave")
        self._texto(pintor, QRect(izquierda, y, ancho, 19), self._nombre(r), _letra(14, 600),
                    color_nombre if identificada else COLOR_SIN_DOMINAR)
        y += 21
        for texto_linea, color_linea, negrita in self._detalles(r):
            if y + 15 > caja.y() + caja.height() - 4:
                break
            self._texto(pintor, QRect(izquierda, y, ancho, 15), texto_linea, _letra(12, 600 if negrita else 400),
                        color_linea)
            y += 16

    def _marco_sin_fondo(self, pintor, r, caja: QRect, borde_normal: QColor | None = None) -> None:
        """Solo el borde (y el remate de la mejor), encima de lo ya pintado."""
        camino = self._camino(caja)
        pintor.setBrush(Qt.NoBrush)
        if not r.mejor:
            pintor.setPen(QPen(borde_normal or _tema("borde"), 1))
            pintor.drawPath(camino)
            return
        pintor.setPen(QPen(self._color_mejor(), 2))
        pintor.drawPath(camino)
        # El remate de los paneles C: un trazo dorado junto a la esquina cortada de abajo.
        largo = min(46, caja.width() / 4)
        pintor.setPen(QPen(self._color_mejor(), 3))
        abajo = caja.bottom() - 1
        pintor.drawLine(QPointF(caja.right() - CHAFLAN_TARJETA - largo, abajo),
                        QPointF(caja.right() - CHAFLAN_TARJETA, abajo))

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
            self._texto(pintor, pie, self._texto_mejor(), _fuente(9, True), self._color_mejor(), Qt.AlignCenter)
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
