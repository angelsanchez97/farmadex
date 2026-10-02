"""La build leida, pintada como la pantalla de mejoras del juego.

Los 8 huecos de mod en dos filas de cuatro; encima, el aura y el exilus (o la postura y
el exilus en las armas cuerpo a cuerpo); a la derecha, los arcanos (y el exilus de las
armas de fuego). Las proporciones son las del juego (datos/disposicion_build.py, medidas
sobre capturas reales): el paso entre columnas, el paso entre filas y el tamano de la
tarjeta respecto a ellos.

Tamano: la rejilla ocupa el ancho que le den y nunca pasa del tamano real del juego en
esa pantalla (el paso de columna del juego es 0,228 veces el alto de la pantalla). Con
la ventana maximizada o a pantalla completa hay sitio y queda a tamano real: una copia
a escala 1:1. En una ventana mas estrecha se encoge entera, sin deformarse.

Lo que NO se sabe no se inventa:
- Un hueco donde no se leyo nada se pinta como hueco sin decir "vacio": puede estar
  vacio o llevar un mod que no se reconocio.
- Si no se pudo saber en que hueco va cada mod, van todos en el orden leido, con borde
  discontinuo y un aviso que lo dice.
- Un mod que no cae en ningun hueco (su tarjeta estaba ampliada) va debajo, aparte.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..datos import disposicion_build as disposicion
from ..idiomas import t
from .estilo_c import TITULAR, TEXTO, EtiquetaC, color, px, transparente

# Color del marco de la tarjeta segun la rareza, como en el juego.
COLOR_RAREZA = {"Common": "#b0784f", "Uncommon": "#c9ccd1", "Rare": "#e6c873", "Legendary": "#f4f4f6"}
# Ancho de la rejilla en pasos de columna: cuatro columnas mas la de los arcanos.
ANCHO_PASOS = 5.0
COLUMNAS_ORDEN = 4
# Solo para las pruebas sin pantalla: el alto de pantalla con el que se calcula el tamano
# real del juego (0 = el de la pantalla donde esta la ventana).
ALTO_PANTALLA_FORZADO = 0


@dataclass
class DatosCarta:
    """Lo que hace falta para pintar un mod o un arcano."""

    item_id: int
    nombre: str
    rareza: str = ""
    imagen: QPixmap | None = None
    puntuacion: float = 100.0
    arcano: bool = False
    ayuda: str = ""


def rotulo_hueco(tipo: str) -> str:
    return {"aura": t("Aura"), "exilus": t("Exilus"), "postura": t("Postura"), "arcano": t("Arcano")}.get(tipo, "")


class Carta(QWidget):
    """Una tarjeta de mod (o un arcano) que abre su ficha al pulsarla."""

    pulsada = Signal(int)

    def __init__(self, datos: DatosCarta, dudosa: bool = False, parent=None):
        super().__init__(parent)
        self.datos = datos
        self.dudosa = dudosa
        self._encima = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        ayuda = [datos.nombre]
        if datos.ayuda:
            ayuda.append(datos.ayuda)
        if dudosa:
            ayuda.append(t("No se sabe en qué hueco va: se muestra en el orden leído."))
        ayuda.append(t("Abrir la ficha en Buscar"))
        self.setToolTip("\n".join(ayuda))

    def poner_imagen(self, mapa: QPixmap | None) -> None:
        self.datos.imagen = mapa
        self.update()

    def enterEvent(self, evento):  # noqa: N802
        self._encima = True
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self._encima = False
        self.update()
        super().leaveEvent(evento)

    def mouseReleaseEvent(self, evento):  # noqa: N802
        # La tarjeta "No he podido leer este mod" (sin objeto) no abre nada.
        if evento.button() == Qt.LeftButton and self.datos.item_id and self.rect().contains(evento.position().toPoint()):
            self.pulsada.emit(int(self.datos.item_id))
        super().mouseReleaseEvent(evento)

    def _marco(self) -> QColor:
        if not self.datos.item_id:
            return color("aviso")
        if self.datos.arcano:
            return color("acento")
        return QColor(COLOR_RAREZA.get(self.datos.rareza, color("borde").name()))

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        ancho, alto = self.width(), self.height()
        if self.datos.arcano:
            self._pintar_arcano(p, ancho, alto)
        else:
            self._pintar_mod(p, ancho, alto)
        p.end()

    def _lapiz(self, grosor: float) -> QPen:
        marco = self._marco()
        if self._encima:
            marco = marco.lighter(130)
        lapiz = QPen(marco, grosor)
        if self.dudosa:
            lapiz.setStyle(Qt.DashLine)
        return lapiz

    def _pintar_mod(self, p: QPainter, ancho: int, alto: int) -> None:
        grosor = max(1.5, alto * 0.03)
        caja = QRectF(grosor, grosor, ancho - 2 * grosor, alto - 2 * grosor)
        radio = alto * 0.09
        camino = QPainterPath()
        camino.addRoundedRect(caja, radio, radio)
        p.fillPath(camino, color("panel2"))
        mapa = self.datos.imagen
        if mapa is not None and not mapa.isNull():
            # La ilustracion del mod, oscurecida, detras del nombre (como la tarjeta plegada).
            p.save()
            p.setClipPath(camino)
            p.setOpacity(0.34)
            escala = max(caja.width() / mapa.width(), caja.height() / mapa.height())
            w, h = mapa.width() * escala, mapa.height() * escala
            p.drawPixmap(QRectF(caja.center().x() - w / 2, caja.center().y() - h / 2, w, h), mapa, QRectF(mapa.rect()))
            p.restore()
        p.setPen(self._lapiz(grosor))
        p.drawPath(camino)
        # El nombre, centrado; si no cabe en dos lineas, letra mas pequena.
        margen = ancho * 0.06
        zona = QRectF(margen, alto * 0.1, ancho - 2 * margen, alto * 0.8)
        pie = self.datos.puntuacion < 100
        if pie:
            zona.setHeight(alto * 0.62)
        tinta = color("aviso") if not self.datos.item_id else color("texto")
        self._texto(p, zona, self.datos.nombre, alto * 0.215 if self.datos.item_id else alto * 0.17, tinta, 600)
        if pie:
            f = QFont(TEXTO)
            f.setPixelSize(max(8, int(alto * 0.14)))
            p.setFont(f)
            p.setPen(color("aviso"))
            p.drawText(QRectF(margen, alto * 0.7, ancho - 2 * margen, alto * 0.24), Qt.AlignCenter,
                       f"{t('parecido')} {self.datos.puntuacion:.0f}%")

    def _pintar_arcano(self, p: QPainter, ancho: int, alto: int) -> None:
        lado = alto * 0.56
        icono = QRectF((ancho - lado) / 2, 0, lado, lado)
        mapa = self.datos.imagen
        if mapa is not None and not mapa.isNull():
            escala = min(icono.width() / mapa.width(), icono.height() / mapa.height())
            w, h = mapa.width() * escala, mapa.height() * escala
            p.drawPixmap(QRectF(icono.center().x() - w / 2, icono.center().y() - h / 2, w, h), mapa,
                         QRectF(mapa.rect()))
        else:
            p.setPen(self._lapiz(max(1.5, alto * 0.02)))
            p.drawEllipse(icono.adjusted(lado * 0.12, lado * 0.12, -lado * 0.12, -lado * 0.12))
        if self.dudosa:
            p.setPen(self._lapiz(1.5))
            p.drawRoundedRect(QRectF(1, 1, ancho - 2, alto - 2), 4, 4)
        tinta = color("acento").lighter(125) if self._encima else color("acento")
        pie = self.datos.puntuacion < 100
        self._texto(p, QRectF(0, lado, ancho, alto - lado - (alto * 0.12 if pie else 0)), self.datos.nombre,
                    alto * 0.125, tinta, 600)
        if pie:
            f = QFont(TEXTO)
            f.setPixelSize(max(8, int(alto * 0.1)))
            p.setFont(f)
            p.setPen(color("aviso"))
            p.drawText(QRectF(0, alto * 0.88, ancho, alto * 0.12), Qt.AlignCenter,
                       f"{t('parecido')} {self.datos.puntuacion:.0f}%")

    @staticmethod
    def _texto(p: QPainter, zona: QRectF, texto: str, tam: float, tinta: QColor, peso: int) -> None:
        banderas = int(Qt.AlignCenter | Qt.TextWordWrap)
        tam = max(8.0, tam)
        f = QFont(TITULAR)
        f.setFamilies([TITULAR, TEXTO])
        f.setWeight(QFont.Weight(peso))
        while True:
            f.setPixelSize(int(tam))
            caja = QFontMetrics(f).boundingRect(zona.toRect(), banderas, texto)
            if (caja.height() <= zona.height() + 1 and caja.width() <= zona.width() + 1) or tam <= 8:
                break
            tam -= 1
        p.setFont(f)
        p.setPen(tinta)
        p.drawText(zona, banderas, texto)


class _Lienzo(QWidget):
    """Coloca tarjetas y huecos en unidades de la rejilla del juego y los escala al ancho."""

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        # (x centro en pasos de columna, y centro en pasos de fila, ancho, alto, tarjeta o None, rotulo)
        self.piezas: list[tuple[float, float, float, float, Carta | None, str]] = []
        self._paso = 0.0
        self._origen = 0.0
        self._arriba = 0.0

    def vaciar(self) -> None:
        for *_resto, carta, _rotulo in self.piezas:
            if carta is not None:
                carta.hide()
                carta.deleteLater()
        self.piezas = []

    def anadir(self, x: float, y: float, ancho: float, alto: float, carta: Carta | None, rotulo: str = "") -> None:
        if carta is not None:
            carta.setParent(self)
            carta.show()
        self.piezas.append((x, y, ancho, alto, carta, rotulo))

    def paso_real(self) -> float:
        """El paso de columna del juego en esta pantalla, en pixeles."""
        alto = ALTO_PANTALLA_FORZADO
        if not alto:
            pantalla = self.screen()
            alto = pantalla.size().height() if pantalla is not None else 1080
        return disposicion.PASO_REAL * alto

    def paso(self) -> float:
        return self._paso

    def escala(self) -> float:
        """1.0 = del tamano del juego en esta pantalla."""
        real = self.paso_real()
        return self._paso / real if real else 0.0

    def recolocar(self) -> None:
        if not self.piezas:
            self._paso = 0.0
            self.setFixedHeight(0)
            return
        paso = min(self.paso_real(), self.width() / ANCHO_PASOS)
        self._paso = paso
        fila = paso * disposicion.RELACION_FILAS
        arriba = min(y - alto / 2 for _x, y, _a, alto, _c, _r in self.piezas)
        abajo = max(y + alto / 2 for _x, y, _a, alto, _c, _r in self.piezas)
        # Centrada si sobra sitio; la columna 0 queda a medio paso del borde.
        origen = (self.width() - ANCHO_PASOS * paso) / 2 + paso / 2
        for x, y, ancho, alto, carta, _rotulo in self.piezas:
            if carta is not None:
                carta.setGeometry(*self._caja(origen, arriba, paso, fila, x, y, ancho, alto))
        total = int((abajo - arriba) * fila) + 2
        if self.height() != total:
            self.setFixedHeight(total)
        self._origen, self._arriba = origen, arriba
        self.update()

    @staticmethod
    def _caja(origen: float, arriba: float, paso: float, fila: float, x: float, y: float, ancho: float, alto: float):
        return (int(origen + (x - ancho / 2) * paso), int((y - alto / 2 - arriba) * fila) + 1,
                int(ancho * paso), int(alto * fila))

    def resizeEvent(self, evento):  # noqa: N802
        super().resizeEvent(evento)
        self.recolocar()

    def paintEvent(self, _evento):  # noqa: N802
        if not self.piezas or not self._paso:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paso, fila = self._paso, self._paso * disposicion.RELACION_FILAS
        lapiz = QPen(color("borde"), max(1.0, fila * 0.012))
        lapiz.setStyle(Qt.DotLine)
        f = QFont(TITULAR)
        f.setFamilies([TITULAR, TEXTO])
        f.setPixelSize(max(8, int(fila * 0.13)))
        p.setFont(f)
        for x, y, ancho, alto, carta, rotulo in self.piezas:
            if carta is not None:
                continue
            cx, cy, w, h = self._caja(self._origen, self._arriba, paso, fila, x, y, ancho, alto)
            caja = QRectF(cx + 2, cy + 2, w - 4, h - 4)
            p.setPen(lapiz)
            p.drawRoundedRect(caja, h * 0.08, h * 0.08)
            if rotulo:
                p.setPen(color("tenue"))
                p.drawText(caja, Qt.AlignCenter, rotulo.upper())
        p.end()


class RejillaBuild(QWidget):
    """La build con la disposicion del juego, mas lo que no se supo colocar."""

    abrir_item = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.aviso = EtiquetaC("", "pequeno", tinta="aviso", envolver=True)
        self.lienzo = _Lienzo()
        self.titulo_sueltos = EtiquetaC("", "pequeno", tinta="aviso", envolver=True)
        self.lienzo_sueltos = _Lienzo()
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(px(6, False))
        for w in (self.aviso, self.lienzo, self.titulo_sueltos, self.lienzo_sueltos):
            capa.addWidget(w)
        self.aviso.hide()
        self.titulo_sueltos.hide()
        self.cartas: dict[int, Carta] = {}
        self.cartas_no_leidas: dict[str, Carta] = {}
        self.no_leidos: dict[str, str] = {}
        self.colocacion: disposicion.Disposicion | None = None

    def vaciar(self) -> None:
        self.lienzo.vaciar()
        self.lienzo_sueltos.vaciar()
        self.cartas = {}
        self.cartas_no_leidas = {}
        self.no_leidos = {}
        self.colocacion = None
        self.aviso.hide()
        self.titulo_sueltos.hide()
        self.lienzo.recolocar()
        self.lienzo_sueltos.recolocar()

    def _carta(self, datos: DatosCarta, dudosa: bool) -> Carta:
        carta = Carta(datos, dudosa)
        carta.pulsada.connect(self.abrir_item.emit)
        self.cartas.setdefault(int(datos.item_id), carta)
        return carta

    def poner(self, colocacion: disposicion.Disposicion, mods: list[DatosCarta], arcanos: list[DatosCarta],
              no_leidos: dict[str, str] | None = None) -> None:
        """Pinta la build. `mods` y `arcanos` van en el orden leido, como en `colocacion`.

        `no_leidos` es clave de hueco -> lo que se leyo ahi: huecos que se ven ocupados en la
        pantalla pero cuyo mod no se pudo leer. Se pintan como "No he podido leer este mod",
        nunca como un hueco vacio: el usuario tiene que saber que su build esta incompleta.
        """
        self.vaciar()
        self.colocacion = colocacion
        self.no_leidos = dict(no_leidos or {})
        ac, al = disposicion.ANCHO_CARTA, disposicion.ALTO_CARTA
        aa, ala = disposicion.ANCHO_ARCANO, disposicion.ALTO_ARCANO
        if colocacion.segura:
            for hueco in colocacion.huecos:
                if hueco.tipo == "arcano":
                    i = colocacion.arcanos.get(hueco.clave)
                    carta = self._carta(arcanos[i], False) if i is not None else self._no_leida(hueco)
                    self.lienzo.anadir(hueco.x, hueco.y - 0.3, aa, ala, carta, rotulo_hueco("arcano"))
                else:
                    i = colocacion.mods.get(hueco.clave)
                    carta = self._carta(mods[i], False) if i is not None else self._no_leida(hueco)
                    self.lienzo.anadir(hueco.x, hueco.y, ac, al, carta, rotulo_hueco(hueco.tipo))
            sueltos = [mods[i] for i in colocacion.sueltos_mods] + [arcanos[i] for i in colocacion.sueltos_arcanos]
            if sueltos:
                self.titulo_sueltos.setText(t(
                    "Leídos, pero no se sabe en qué hueco van (su tarjeta estaba ampliada o tapada):"))
                self.titulo_sueltos.show()
                self._en_orden(self.lienzo_sueltos, sueltos, dudosa=True)
        else:
            # No se sabe el hueco de ninguno: todos en el orden leido, y se dice.
            self.aviso.setText(t("No se ha podido saber en qué hueco va cada mod. Se muestran en el orden "
                                 "en que se leyeron (de izquierda a derecha y de arriba abajo), no en su hueco."))
            self.aviso.show()
            self._en_orden(self.lienzo, list(mods) + list(arcanos), dudosa=True)
        self.lienzo.recolocar()
        self.lienzo_sueltos.recolocar()

    def _no_leida(self, hueco: disposicion.Hueco) -> Carta | None:
        """La tarjeta "No he podido leer este mod" de un hueco que se ve ocupado, o None si
        el hueco no esta entre los no leidos (entonces se pinta como hueco)."""
        if hueco.clave not in self.no_leidos:
            return None
        texto = self.no_leidos[hueco.clave]
        if texto.startswith("agrietado:"):
            # Un mod agrietado (riven): no esta en el catalogo, pero se sabe que es.
            texto = texto.partition(":")[2].strip()
            nombre = t("Agrietado")
            ayuda = t("Un mod agrietado (riven). Léelo con el atajo de agrietados para ver sus estadísticas.")
        else:
            nombre = t("No he podido leer este mod") if hueco.tipo != "arcano" else t("No he podido leer este arcano")
            ayuda = t("En la pantalla hay un mod en este hueco, pero no se ha podido leer su nombre "
                      "(tapado, ampliado o con una letra que no se entiende). Vuelve a leer con la "
                      "pantalla despejada.")
        if texto:
            ayuda += "\n" + t("Leído: {texto}", texto=texto)
        datos = DatosCarta(0, nombre, "", None, 100.0, hueco.tipo == "arcano", ayuda)
        carta = Carta(datos, dudosa=True)
        carta.setCursor(Qt.ArrowCursor)
        carta.setToolTip(ayuda)
        self.cartas_no_leidas[hueco.clave] = carta
        return carta

    def _en_orden(self, lienzo: _Lienzo, datos: list[DatosCarta], dudosa: bool) -> None:
        for n, d in enumerate(datos):
            col, fil = n % COLUMNAS_ORDEN, n // COLUMNAS_ORDEN
            carta = self._carta(d, dudosa)
            if d.arcano:
                lienzo.anadir(col, fil * 1.15, disposicion.ANCHO_ARCANO, disposicion.ALTO_ARCANO, carta)
            else:
                lienzo.anadir(col, fil * 1.15, disposicion.ANCHO_CARTA, disposicion.ALTO_CARTA, carta)

    # -- para las pruebas ---------------------------------------------------------------

    def escala(self) -> float:
        return self.lienzo.escala()

    def carta_de(self, item_id: int) -> Carta | None:
        return self.cartas.get(int(item_id))

    def hueco_de(self, item_id: int) -> str | None:
        """La clave del hueco donde esta pintado ese objeto, o None si va sin hueco."""
        c = self.colocacion
        if c is None or not c.segura:
            return None
        carta = self.cartas.get(int(item_id))
        for *_r, pieza, _rot in self.lienzo.piezas:
            if pieza is carta and carta is not None:
                for clave, _i in list(c.mods.items()) + list(c.arcanos.items()):
                    if self._carta_en(clave) is carta:
                        return clave
        return None

    def _carta_en(self, clave: str) -> Carta | None:
        c = self.colocacion
        if c is None:
            return None
        for n, hueco in enumerate(c.huecos):
            if hueco.clave == clave and n < len(self.lienzo.piezas):
                return self.lienzo.piezas[n][4]
        return None
