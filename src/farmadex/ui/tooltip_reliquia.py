"""La tarjeta flotante con la tabla de una reliquia (estilo C), dentro y fuera de Farmadex.

Una sola tarjeta para todo:

- En el juego, `captura/reliquia_hover.py` dice que reliquia hay bajo el raton y la
  ventana llama a `ServicioTarjeta.mostrar`.
- Dentro de Farmadex, `AyudaHoverApp` (un filtro de eventos instalado una vez en la
  aplicacion) ve cuando el raton se queda ~0,3 s encima de un enlace `item:<id>` de
  una reliquia en cualquier ficha o texto enriquecido (Buscar, Primes, Objetivos,
  Tablero, Mundo, vista compacta...) o encima de un widget marcado con `marcar()`
  (textos sin enlace, como "Reliquia Lith S19" del Tablero o del HUD del modo juego).

La tarjeta no roba el foco al juego (ventana de tipo tooltip, sin activar y
transparente al raton), va siempre encima, se coloca junto al cursor sin taparlo ni
salirse de la pantalla, y ensena las seis recompensas agrupadas por rareza con su
probabilidad en los cuatro refinamientos, platino (warframe.market, llega aparte),
ducados, lo que te falta, si esta en la boveda y el mejor sitio donde cae.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLabel, QTextBrowser, QWidget

from ..idiomas import glosa, nombre as nombre_idioma, t
from ..registro_log import obtener
from . import widgets
from .estilo_c import COLOR_ERA, _rombo_poligono, color, fuente, px, ruta_chaflan

log = obtener("tooltip_reliquia")

REFINAMIENTOS = ("Intact", "Exceptional", "Flawless", "Radiant")
TITULOS_REFINAMIENTO = {"Intact": "Intacta", "Exceptional": "Excepcional", "Flawless": "Impecable", "Radiant": "Radiante"}
ORDEN_RAREZA = ("Rare", "Uncommon", "Common")
RETARDO_MS = 300  # raton quieto encima de una reliquia antes de ensenar la tarjeta (en la app)
PROPIEDAD = "farmadex_reliquia"  # widgets marcados con `marcar()`
CADUCIDAD_PRECIO_S = 600


# -- datos ---------------------------------------------------------------------------


def _con_padre(nombre: str, padre: str | None) -> str:
    return t("{nombre} de {padre}", nombre=nombre, padre=padre) if padre else nombre


def datos_reliquia(con, reliquia_id: int, usuario_con=None) -> dict | None:
    """Todo lo que ensena la tarjeta de una reliquia del indice; None si no es una reliquia.

    Claves: id, corto ("Lith S19"), era, vaulted, filas (por rareza: oro, plata, bronce;
    cada una con item_id, nombre, rareza, prob {refinamiento: %}, ducados, slug,
    comerciable, platino=None, marca) y donde (texto del mejor sitio, o None).
    """
    from ..datos import indice, relaciones

    fila = con.execute(
        "SELECT id, nombre_en, nombre_es, vaulted, categoria FROM items WHERE id = ?", (reliquia_id,)
    ).fetchone()
    if not fila or fila[4] != "Relics":
        return None
    corto = (fila[1] or "").removesuffix(" Relic").strip()
    era = corto.split(" ")[0]
    probs: dict[int, dict[str, float]] = {}
    rareza_tabla: dict[int, str] = {}
    for refinamiento, item_id, probabilidad, rareza in con.execute(
        "SELECT refinamiento, item_id, probabilidad, rareza FROM reliquia_recompensas WHERE reliquia_id = ?",
        (reliquia_id,),
    ):
        probs.setdefault(item_id, {})[refinamiento] = probabilidad
        if rareza and item_id not in rareza_tabla:
            rareza_tabla[item_id] = rareza
    filas = []
    for item_id, prob in probs.items():
        datos = con.execute(
            """SELECT i.nombre_en, i.nombre_es, p.nombre_en, p.nombre_es, i.ducados, i.market_slug,
                      i.comerciable FROM items i LEFT JOIN items p ON p.id = i.padre_id WHERE i.id = ?""",
            (item_id,),
        ).fetchone()
        if not datos:
            continue
        rareza = None
        for refinamiento in ("Intact", "Radiant", "Exceptional", "Flawless"):
            if refinamiento in prob:
                rareza = relaciones.rareza_reliquia(refinamiento, prob[refinamiento], None)
                if rareza:
                    break
        filas.append({
            "item_id": item_id,
            "nombre": _con_padre(
                nombre_idioma({"nombre_en": datos[0], "nombre_es": datos[1]}),
                nombre_idioma({"nombre_en": datos[2], "nombre_es": datos[3]}) if datos[2] else None,
            ),
            "rareza": rareza or rareza_tabla.get(item_id) or "Common",
            "prob": prob,
            "ducados": datos[4] or None,
            "slug": datos[5] or "",
            "comerciable": bool(datos[6]),
            "platino": None,
            "marca": "",
        })
    filas.sort(key=lambda f: (ORDEN_RAREZA.index(f["rareza"]) if f["rareza"] in ORDEN_RAREZA else 9,
                              f["nombre"]))
    for f in filas:
        f["nombre_rareza"] = _nombre_rareza(con, f["rareza"])
    if usuario_con is not None:
        _marcar_lo_que_falta(con, usuario_con, filas)
    donde = None
    if not fila[3]:
        misiones = relaciones.misiones_de(con, reliquia_id)
        if misiones:
            m = misiones[0]
            trozos = [m.get("donde") or ""]
            if m.get("mision"):
                trozos.append(m["mision"])
            if m.get("rotacion"):
                rot = m["rotacion"]
                trozos.append(glosa(indice.traducir(con, "rotacion", rot), rot))
            prob = m.get("probabilidad_efectiva") or m.get("probabilidad")
            if prob:
                trozos.append(f"{prob:.1f}%")
            donde = t("Cae en") + " " + " · ".join(x for x in trozos if x)
        else:
            donde = t("No cae en ninguna misión activa")
    return {
        "id": reliquia_id,
        "corto": corto,
        "era": era,
        "vaulted": bool(fila[3]),
        "filas": filas,
        "donde": donde,
        "refinamiento": None,
    }


def _marcar_lo_que_falta(con, usuario_con, filas: list[dict]) -> None:
    """La marca de cada pieza: te falta (objetivo), completa set, no lo tienes o ya la tienes."""
    try:
        from ..captura import prioridad
        from ..captura.reliquias import Recompensa, completar

        recompensas = [Recompensa(f["item_id"], f["nombre"], "", (0, 0, 0, 0)) for f in filas]
        completar(recompensas, con, usuario_con)
        for f, r in zip(filas, recompensas):
            for criterio in ("falta", "set", "nueva"):
                if prioridad.cumple(criterio, r):
                    f["marca"] = prioridad.texto_criterio(criterio, r)
                    f["clave_marca"] = criterio
                    break
            else:
                if prioridad.tiene_la_pieza(r):
                    f["marca"] = t("Ya la tienes")
                    f["clave_marca"] = "tienes"
    except Exception:  # noqa: BLE001 - sin marcas la tarjeta sigue valiendo
        log.debug("Sin marcas de objetivos en la tarjeta de reliquia", exc_info=True)


def valor_medio(filas: list[dict], refinamiento: str) -> tuple[float | None, float]:
    """(platino, ducados) que da de media abrir la reliquia con ese refinamiento, a solas.

    El platino es None mientras falte el precio de alguna pieza que se pueda vender;
    lo que no se vende (Forma) cuenta 0.
    """
    platino, ducados, falta = 0.0, 0.0, False
    for f in filas:
        prob = (f["prob"].get(refinamiento) or 0) / 100
        ducados += prob * (f["ducados"] or 0)
        if f["comerciable"] and f["slug"]:
            if f["platino"] is None:
                falta = True
            else:
                platino += prob * f["platino"]
    return (None if falta else platino), ducados


def colocar(tam: tuple[int, int], cursor: tuple[int, int], zona: tuple[int, int, int, int],
            separacion: int = 22) -> tuple[int, int]:
    """Esquina de la tarjeta junto al cursor, sin taparlo ni salirse de `zona` (x, y, ancho, alto).

    Prueba abajo a la derecha, arriba a la derecha, abajo a la izquierda y arriba a la
    izquierda; si no cabe entera en ninguna, la mete a la fuerza dentro de la pantalla
    por el lado con mas sitio, apartada del cursor.
    """
    ancho, alto = tam
    cx, cy = cursor
    zx, zy, zw, zh = zona
    opciones = (
        (cx + separacion, cy + separacion),
        (cx + separacion, cy - separacion - alto),
        (cx - separacion - ancho, cy + separacion),
        (cx - separacion - ancho, cy - separacion - alto),
    )
    for x, y in opciones:
        if zx <= x and x + ancho <= zx + zw and zy <= y and y + alto <= zy + zh:
            return x, y
    # No cabe entera en ninguna esquina: al lado con mas sitio y dentro de la pantalla.
    x = cx + separacion if (zx + zw - cx) >= (cx - zx) else cx - separacion - ancho
    x = max(zx, min(x, zx + zw - ancho))
    y = max(zy, min(cy - alto // 2, zy + zh - alto))
    if x <= cx <= x + ancho and y <= cy <= y + alto:
        # Aun asi taparia el cursor (pantalla muy pequena): encima o debajo de el.
        y = cy + separacion if cy - zy < zh / 2 else cy - separacion - alto
        y = max(zy, min(y, zy + zh - alto))
    return x, y


# -- la tarjeta ----------------------------------------------------------------------


class TarjetaReliquia(QWidget):
    """La tarjeta pintada a mano: no coge el foco ni el raton, y va siempre encima."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.datos: dict | None = None

    # -- medidas --

    def _col(self) -> dict:
        m = QFontMetrics(fuente("pequeno"))
        prob = max(m.horizontalAdvance(t(TITULOS_REFINAMIENTO[r])) for r in REFINAMIENTOS) + px(12, False)
        return {
            "margen": px(14, False),
            "nombre": px(250, False),
            "prob": max(prob, px(58, False)),
            "plat": px(52, False),
            "duc": px(46, False),
            "fila": QFontMetrics(fuente("normal", tam=13)).height() + px(5, False),
            "grupo": m.height() + px(6, False),
        }

    def sizeHint(self) -> QSize:  # noqa: N802
        c = self._col()
        ancho = 2 * c["margen"] + c["nombre"] + 4 * c["prob"] + c["plat"] + c["duc"]
        if not self.datos:
            return QSize(ancho, px(60, False))
        grupos = len({f["rareza"] for f in self.datos["filas"]})
        alto = (c["margen"] + QFontMetrics(fuente("seccion")).height() + px(10, False)  # titulo + filete
                + c["grupo"]  # cabecera de columnas
                + grupos * c["grupo"] + len(self.datos["filas"]) * c["fila"]
                + px(8, False) + QFontMetrics(fuente("pequeno")).height() + px(4, False)  # valor medio
                + self._alto_pie(ancho - 2 * c["margen"]) + c["margen"])
        return QSize(ancho, alto)

    def _alto_pie(self, ancho: int) -> int:
        texto = self._texto_pie()
        if not texto:
            return 0
        m = QFontMetrics(fuente("pequeno"))
        return m.boundingRect(QRect(0, 0, ancho, 1000), Qt.TextWordWrap, texto).height()

    def _texto_pie(self) -> str:
        if not self.datos:
            return ""
        if self.datos["vaulted"]:
            return t("En la bóveda: ya no cae en misiones. Cómprala a otro jugador o espera a que vuelva.")
        return self.datos.get("donde") or ""

    def _texto_valor(self) -> str:
        """'Valor medio al abrirla (Radiante): 12 platino · 38 ducados' (como AlecaFrame)."""
        if not self.datos or not self.datos["filas"]:
            return ""
        refinamiento = self.datos.get("refinamiento") or self.datos.get("refinamiento_valor") or "Intact"
        platino, ducados = valor_medio(self.datos["filas"], refinamiento)
        return t("Valor medio al abrirla ({refinamiento}): {platino} platino · {ducados} ducados",
                 refinamiento=t(TITULOS_REFINAMIENTO.get(refinamiento, "Intacta")),
                 platino="…" if platino is None else f"{platino:.0f}", ducados=f"{ducados:.0f}")

    # -- contenido --

    def poner(self, datos: dict) -> None:
        self.datos = datos
        self.resize(self.sizeHint())
        self.update()

    def poner_precio(self, slug: str, platino) -> bool:
        """Llega el precio de una pieza: se repinta si esta en la tarjeta."""
        if not self.datos:
            return False
        cambiado = False
        for f in self.datos["filas"]:
            if f["slug"] == slug:
                f["platino"] = platino
                f["precio_pedido"] = True
                cambiado = True
        if cambiado:
            self.update()
        return cambiado

    # -- pintura --

    def paintEvent(self, _evento):  # noqa: N802
        if not self.datos:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._col()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        camino = ruta_chaflan(r, px(12, False))
        p.fillPath(camino, color("panel"))
        p.setPen(QPen(color("acento_tenue"), 1))
        p.drawPath(camino)
        p.setPen(QPen(color("acento"), 2))
        p.drawLine(QPointF(r.left() + px(12, False), r.top() + 1), QPointF(r.left() + px(58, False), r.top() + 1))
        d = self.datos
        m = c["margen"]
        ancho_util = self.width() - 2 * m
        y = m
        # Titulo: rombo del color de la era, "Reliquia Lith S19" y boveda a la derecha.
        f_tit = fuente("seccion")
        alto_tit = QFontMetrics(f_tit).height()
        tinta_era = color(COLOR_ERA.get(d["era"], widgets.PALETA["acento"]))
        p.setPen(Qt.NoPen)
        p.setBrush(tinta_era)
        p.drawPolygon(_rombo_poligono(m + px(5, False), y + alto_tit / 2, px(5, False)))
        p.setFont(f_tit)
        p.setPen(tinta_era)
        titulo = t("Reliquia {reliquia}", reliquia=d["corto"])
        p.drawText(QRectF(m + px(16, False), y, ancho_util, alto_tit), Qt.AlignLeft | Qt.AlignVCenter, titulo)
        estado = t("En bóveda") if d["vaulted"] else t("Disponible")
        p.setFont(fuente("rotulo"))
        p.setPen(color(widgets.COLOR_BOVEDA if d["vaulted"] else widgets.COLOR_DISPONIBLE))
        p.drawText(QRectF(m, y, ancho_util, alto_tit), Qt.AlignRight | Qt.AlignVCenter, estado.upper())
        y += alto_tit + px(5, False)
        p.setPen(QPen(color("acento_tenue"), 1))
        p.drawLine(QPointF(m, y), QPointF(self.width() - m, y))
        y += px(5, False)
        # Cabecera de columnas.
        f_peq = fuente("pequeno")
        p.setFont(f_peq)
        x_prob = m + c["nombre"]
        elegido = d.get("refinamiento")
        p.setPen(color("suave"))
        p.drawText(QRectF(m, y, c["nombre"], c["grupo"]), Qt.AlignLeft | Qt.AlignVCenter, t("Recompensa"))
        for i, refinamiento in enumerate(REFINAMIENTOS):
            p.setPen(color("secundario" if refinamiento == elegido else "suave"))
            p.drawText(QRectF(x_prob + i * c["prob"], y, c["prob"], c["grupo"]), Qt.AlignRight | Qt.AlignVCenter,
                       t(TITULOS_REFINAMIENTO[refinamiento]))
        x_plat = x_prob + 4 * c["prob"]
        p.setPen(color("suave"))
        p.drawText(QRectF(x_plat, y, c["plat"], c["grupo"]), Qt.AlignRight | Qt.AlignVCenter, t("Plat."))
        p.drawText(QRectF(x_plat + c["plat"], y, c["duc"], c["grupo"]), Qt.AlignRight | Qt.AlignVCenter, t("Duc."))
        y += c["grupo"]
        # Filas, agrupadas por rareza (oro, plata, bronce).
        f_fila = fuente("normal", tam=13)
        f_marca = fuente("pequeno", peso=600)
        grupo_actual = None
        for fila in d["filas"]:
            tinta = color(widgets.color_rareza(fila["rareza"]))
            if fila["rareza"] != grupo_actual:
                grupo_actual = fila["rareza"]
                p.setFont(fuente("rotulo"))
                p.setPen(tinta)
                p.drawText(QRectF(m, y, ancho_util, c["grupo"]), Qt.AlignLeft | Qt.AlignBottom,
                           (fila.get("nombre_rareza") or fila["rareza"]).upper())
                y += c["grupo"]
            alto = c["fila"]
            p.fillRect(QRectF(m, y + 3, px(3, False), alto - 6), tinta)
            # Nombre (recortado) y, detras, la marca de lo que te falta.
            p.setFont(f_fila)
            p.setPen(color("texto"))
            hueco = c["nombre"] - px(12, False)
            marca = fila.get("marca") or ""
            ancho_marca = QFontMetrics(f_marca).horizontalAdvance(marca) + px(8, False) if marca else 0
            nombre = QFontMetrics(f_fila).elidedText(fila["nombre"], Qt.ElideRight, max(40, hueco - ancho_marca))
            p.drawText(QRectF(m + px(9, False), y, hueco, alto), Qt.AlignLeft | Qt.AlignVCenter, nombre)
            if marca:
                x_marca = m + px(9, False) + QFontMetrics(f_fila).horizontalAdvance(nombre) + px(8, False)
                p.setFont(f_marca)
                p.setPen(color("acento" if fila.get("clave_marca") != "tienes" else "suave"))
                p.drawText(QRectF(x_marca, y, ancho_marca, alto), Qt.AlignLeft | Qt.AlignVCenter, marca)
            p.setFont(f_fila)
            for i, refinamiento in enumerate(REFINAMIENTOS):
                valor = fila["prob"].get(refinamiento)
                texto = f"{valor:.0f}%" if valor is not None and abs(valor - round(valor)) < 0.05 else (
                    f"{valor:.1f}%" if valor is not None else "-")
                p.setPen(color("secundario" if refinamiento == elegido else "texto"))
                p.drawText(QRectF(x_prob + i * c["prob"], y, c["prob"], alto), Qt.AlignRight | Qt.AlignVCenter, texto)
            if not fila["comerciable"] or not fila["slug"]:
                plat, tinta_plat = "-", "tenue"
            elif fila["platino"] is None:
                plat, tinta_plat = ("?" if fila.get("precio_pedido") else "…"), "tenue"
            else:
                plat, tinta_plat = f"{fila['platino']}p", "acento"
            p.setPen(color(tinta_plat))
            p.drawText(QRectF(x_plat, y, c["plat"], alto), Qt.AlignRight | Qt.AlignVCenter, plat)
            p.setPen(color("texto" if fila["ducados"] else "tenue"))
            p.drawText(QRectF(x_plat + c["plat"], y, c["duc"], alto), Qt.AlignRight | Qt.AlignVCenter,
                       str(fila["ducados"]) if fila["ducados"] else "-")
            y += alto
        y += px(6, False)
        p.setFont(f_peq)
        p.setPen(color("acento"))
        alto_valor = QFontMetrics(f_peq).height()
        p.drawText(QRectF(m, y, ancho_util, alto_valor), Qt.AlignLeft | Qt.AlignVCenter, self._texto_valor())
        y += alto_valor
        pie = self._texto_pie()
        if pie:
            y += px(4, False)
            p.setFont(f_peq)
            p.setPen(color(widgets.COLOR_BOVEDA if d["vaulted"] else "suave"))
            p.drawText(QRectF(m, y, ancho_util, self.height() - y - m + 2), Qt.TextWordWrap | Qt.AlignLeft, pie)
        p.end()


def _nombre_rareza(con, rareza: str) -> str:
    """'Rara', 'Poco comun', 'Comun' en el idioma activo, del glosario del indice."""
    from ..datos import indice

    try:
        return glosa(indice.traducir(con, "rareza", rareza), rareza) or rareza
    except Exception:  # noqa: BLE001 - sin glosario, el nombre del juego en ingles
        return rareza


# -- el servicio comun ---------------------------------------------------------------------


class _Avisos(QObject):
    precio = Signal(str, object)  # slug, platino (int o None)


class ServicioTarjeta(QObject):
    """Una tarjeta, sus datos y sus precios. La usan el juego y la propia app.

    `indice` y `usuario` son funciones que devuelven una conexion (o None): asi el
    servicio no se queda con conexiones viejas cuando la ventana rehace el indice.
    """

    def __init__(self, indice: Callable | None = None, usuario: Callable | None = None, parent=None):
        super().__init__(parent)
        self._indice = indice
        self._usuario = usuario or (lambda: None)
        self.tarjeta: TarjetaReliquia | None = None
        self._reliquias: set[int] | None = None
        self._precios: dict[str, tuple[float, object]] = {}
        self._pedidos: set[str] = set()
        self._cerrojo = threading.Lock()
        self._avisos = _Avisos()
        self._avisos.precio.connect(self._precio_listo)
        self._hilos: ThreadPoolExecutor | None = None
        # Quien pide un precio (se cambia en las pruebas para no salir a internet).
        self.pedir_precio: Callable[[str], object] = _precio_market
        self.precios_activos = True
        self.visible_para: int | None = None

    # -- datos --

    def _con(self):
        if self._indice is not None:
            return self._indice(), False
        from ..datos import indice

        if not indice.hay_indice():
            return None, False
        return indice.conectar(), True

    def es_reliquia(self, item_id: int | None) -> bool:
        if not item_id:
            return False
        if self._reliquias is None:
            con, propia = self._con()
            if con is None:
                return False
            try:
                self._reliquias = {r[0] for r in con.execute("SELECT id FROM items WHERE categoria = 'Relics'")}
            finally:
                if propia:
                    con.close()
        return item_id in self._reliquias

    def olvidar_indice(self) -> None:
        """El indice se ha rehecho: los ids pueden haber cambiado."""
        self._reliquias = None
        self.ocultar()

    def datos(self, reliquia_id: int) -> dict | None:
        con, propia = self._con()
        if con is None:
            return None
        try:
            return datos_reliquia(con, reliquia_id, self._usuario())
        finally:
            if propia:
                con.close()

    # -- ensenar --

    def mostrar(self, reliquia_id: int, punto: QPoint | None = None, refinamiento: str | None = None) -> bool:
        datos = self.datos(reliquia_id)
        if not datos:
            return False
        datos["refinamiento"] = refinamiento or None
        # El valor medio, con el refinamiento leido o con el que usa el jugador en Primes.
        try:
            from ..config import cargar

            datos["refinamiento_valor"] = cargar().get("primes_refinamiento") or "Radiant"
        except Exception:  # noqa: BLE001 - sin config, Radiante
            datos["refinamiento_valor"] = "Radiant"
        ahora = time.monotonic()
        for f in datos["filas"]:
            guardado = self._precios.get(f["slug"])
            if guardado and ahora - guardado[0] < CADUCIDAD_PRECIO_S:
                f["platino"], f["precio_pedido"] = guardado[1], True
        if self.tarjeta is None:
            self.tarjeta = TarjetaReliquia()
        self.tarjeta.poner(datos)
        punto = punto if punto is not None else QCursor.pos()
        pantalla = QGuiApplication.screenAt(punto) or QGuiApplication.primaryScreen()
        zona = pantalla.availableGeometry() if pantalla is not None else QRect(0, 0, 1920, 1080)
        x, y = colocar((self.tarjeta.width(), self.tarjeta.height()), (punto.x(), punto.y()),
                       (zona.x(), zona.y(), zona.width(), zona.height()))
        self.tarjeta.move(x, y)
        self.tarjeta.show()
        self.tarjeta.raise_()
        self.visible_para = reliquia_id
        self._pedir_precios(datos)
        return True

    def ocultar(self) -> None:
        self.visible_para = None
        if self.tarjeta is not None and self.tarjeta.isVisible():
            self.tarjeta.hide()

    def visible(self) -> bool:
        return self.tarjeta is not None and self.tarjeta.isVisible()

    def rectangulo(self) -> QRect | None:
        return self.tarjeta.geometry() if self.visible() else None

    # -- precios (warframe.market, en un hilo aparte) --

    def _pedir_precios(self, datos: dict) -> None:
        if not self.precios_activos:
            return
        ahora = time.monotonic()
        for f in datos["filas"]:
            slug = f["slug"]
            if not slug or not f["comerciable"]:
                continue
            guardado = self._precios.get(slug)
            if guardado and ahora - guardado[0] < CADUCIDAD_PRECIO_S:
                continue
            with self._cerrojo:
                if slug in self._pedidos:
                    continue
                self._pedidos.add(slug)
            if self._hilos is None:
                self._hilos = ThreadPoolExecutor(max_workers=1, thread_name_prefix="farmadex-precio-reliquia")
            self._hilos.submit(self._buscar_precio, slug)

    def _buscar_precio(self, slug: str) -> None:
        try:
            platino = self.pedir_precio(slug)
        except Exception:  # noqa: BLE001 - sin precio la tarjeta ensena "?"
            log.debug("Sin precio para %s", slug, exc_info=True)
            platino = None
        finally:
            with self._cerrojo:
                self._pedidos.discard(slug)
        self._avisos.precio.emit(slug, platino)

    def _precio_listo(self, slug: str, platino) -> None:
        self._precios[slug] = (time.monotonic(), platino)
        if self.tarjeta is not None:
            self.tarjeta.poner_precio(slug, platino)

    def cerrar(self) -> None:
        if self._hilos is not None:
            self._hilos.shutdown(wait=False, cancel_futures=True)
            self._hilos = None


def _precio_market(slug: str):
    """El vendedor mas barato en warframe.market (con la cache y el limitador de siempre)."""
    from ..online import market

    precios = market.compartido().precios(slug)
    return None if precios.error else precios.mejor_venta


# -- dentro de la app --------------------------------------------------------------------


def marcar(widget: QWidget, reliquia_id: int | None) -> None:
    """Un texto sin enlace que habla de una reliquia: al dejar el raton encima sale su tabla."""
    widget.setProperty(PROPIEDAD, int(reliquia_id) if reliquia_id else 0)


def reliquia_de_ruta(ruta: dict | None) -> int | None:
    """La reliquia de una ruta de `relaciones.mejor_ruta` (None si no sale de reliquias)."""
    if not ruta or ruta.get("tipo", "reliquia") != "reliquia" or not ruta.get("reliquia"):
        return None
    return ruta["reliquia"].get("reliquia_id")


def reliquia_de_enlace(href: str) -> int | None:
    if href and href.startswith("item:"):
        try:
            return int(href.removeprefix("item:"))
        except ValueError:
            return None
    return None


class AyudaHoverApp(QObject):
    """Filtro de eventos de toda la aplicacion: tabla de la reliquia al quedarse encima.

    Mira solo Enter, Leave, pulsaciones y rueda (todo lo demas sale al instante):
    - un QTextBrowser (las fichas y sus trozos) o un QLabel con enlaces se engancha a
      su senal de enlace resaltado la primera vez que el raton entra en el;
    - un widget marcado con `marcar()` (o cuyo padre lo este) cuenta al entrar.
    """

    _TIPOS = None

    def __init__(self, servicio: ServicioTarjeta, retardo_ms: int = RETARDO_MS, parent=None):
        super().__init__(parent)
        self.servicio = servicio
        self._pendiente: tuple[int, QWidget] | None = None
        self._mostrado: QWidget | None = None
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(retardo_ms)
        self._temporizador.timeout.connect(self._ensenar)
        self.eventos = 0
        if AyudaHoverApp._TIPOS is None:
            AyudaHoverApp._TIPOS = {QEvent.Enter, QEvent.Leave, QEvent.MouseButtonPress, QEvent.Wheel,
                                    QEvent.Hide, QEvent.WindowDeactivate}

    _instalada: "AyudaHoverApp | None" = None

    def instalar(self, app: QApplication | None = None) -> None:
        """Uno solo por aplicacion: si ya habia otro (otra ventana), este lo sustituye."""
        app = app or QApplication.instance()
        anterior = AyudaHoverApp._instalada
        if anterior is not None and anterior is not self:
            try:
                app.removeEventFilter(anterior)
            except RuntimeError:  # ya destruido
                pass
        app.installEventFilter(self)
        AyudaHoverApp._instalada = self

    def quitar(self, app: QApplication | None = None) -> None:
        (app or QApplication.instance()).removeEventFilter(self)
        if AyudaHoverApp._instalada is self:
            AyudaHoverApp._instalada = None

    def eventFilter(self, obj, evento):  # noqa: N802 - firma de Qt
        tipo = evento.type()
        if tipo not in AyudaHoverApp._TIPOS or not isinstance(obj, QWidget):
            return False
        self.eventos += 1
        try:
            if tipo == QEvent.Enter:
                self._entrar(obj)
            elif tipo == QEvent.Leave:
                self._salir(obj)
            elif tipo in (QEvent.MouseButtonPress, QEvent.Wheel):
                self._cancelar()  # un clic o la rueda en cualquier sitio: fuera
            else:
                # Se esconde o deja de estar activa la ventana del texto (no otra cualquiera).
                objetivo = self._pendiente[1] if self._pendiente else self._mostrado
                if objetivo is not None and (obj is objetivo or obj.isAncestorOf(objetivo)):
                    self._cancelar()
        except Exception:  # noqa: BLE001 - un filtro de eventos no puede romper la app
            log.exception("Fallo en la ayuda de reliquias")
        return False

    # -- enganches --

    def _entrar(self, obj: QWidget) -> None:
        if self.servicio.tarjeta is not None and obj is self.servicio.tarjeta:
            return
        navegador = obj if isinstance(obj, QTextBrowser) else (
            obj.parentWidget() if isinstance(obj.parentWidget(), QTextBrowser) else None)
        if navegador is not None:
            if not navegador.property("_farmadex_hover_reliquia"):
                navegador.setProperty("_farmadex_hover_reliquia", True)
                navegador.highlighted.connect(lambda url, w=navegador: self.enlace(url.toString(), w))
            return
        if isinstance(obj, QLabel) and "item:" in obj.text() and not obj.property("_farmadex_hover_reliquia"):
            obj.setProperty("_farmadex_hover_reliquia", True)
            obj.linkHovered.connect(lambda href, w=obj: self.enlace(href, w))
        marcado = _marcado(obj)
        if marcado is not None:
            reliquia_id, widget = marcado
            if reliquia_id and self.servicio.es_reliquia(reliquia_id):
                self._programar(reliquia_id, widget)

    def enlace(self, href: str, widget: QWidget) -> None:
        """El raton pasa por un enlace (o sale de el, con href vacio)."""
        reliquia_id = reliquia_de_enlace(href)
        if reliquia_id and self.servicio.es_reliquia(reliquia_id):
            if self.servicio.visible_para == reliquia_id and self._mostrado is widget:
                return
            self._programar(reliquia_id, widget)
        elif self._pendiente or self._mostrado is widget:
            self._cancelar()

    def _salir(self, obj: QWidget) -> None:
        objetivo = self._pendiente[1] if self._pendiente else self._mostrado
        if objetivo is None:
            return
        if obj is objetivo or obj.isAncestorOf(objetivo) or objetivo.isAncestorOf(obj):
            # Del texto a su viewport (o al reves) no es salir: solo si el raton ya no esta dentro.
            bajo = QApplication.widgetAt(QCursor.pos())
            if bajo is not None and (bajo is objetivo or objetivo.isAncestorOf(bajo)):
                return
            self._cancelar()

    # -- tiempos --

    def _programar(self, reliquia_id: int, widget: QWidget) -> None:
        if self._mostrado is not None and self.servicio.visible_para != reliquia_id:
            self.servicio.ocultar()
            self._mostrado = None
        self._pendiente = (reliquia_id, widget)
        self._temporizador.start()

    def _ensenar(self) -> None:
        if not self._pendiente:
            return
        reliquia_id, widget = self._pendiente
        self._pendiente = None
        try:
            if not widget.isVisible():
                return
        except RuntimeError:  # el widget ya no existe (la ficha se repinto)
            return
        if self.servicio.mostrar(reliquia_id, QCursor.pos()):
            self._mostrado = widget

    def _cancelar(self) -> None:
        self._temporizador.stop()
        self._pendiente = None
        if self._mostrado is not None:
            self._mostrado = None
            self.servicio.ocultar()


def _marcado(obj: QWidget, niveles: int = 4) -> tuple[int, QWidget] | None:
    w = obj
    for _ in range(niveles):
        if w is None:
            return None
        valor = w.property(PROPIEDAD)
        if valor:
            return int(valor), w
        w = w.parentWidget()
    return None
