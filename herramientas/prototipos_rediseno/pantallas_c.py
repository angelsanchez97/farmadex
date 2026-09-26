"""Maquetas de TODAS las pantallas en el estilo de la propuesta C ("menu del juego").

No es codigo de produccion: pinta cada pantalla con datos reales del indice (copia en la
caja de arena de FARMADEX_DATOS) y el worldState guardado, y guarda un PNG de 1280x800.

Uso: .venv/Scripts/python herramientas/prototipos_rediseno/pantallas_c.py [nombre ...]
Salida: <scratchpad>/rediseno/C_<nombre>.png
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import comun  # noqa: E402  (prepara el entorno antes de Qt)

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout, QWidget  # noqa: E402

from comun import columna, fila, icono, imagen, lbl, minutos_txt, ruta_chaflan  # noqa: E402
from propuesta_c import P, TITULAR, Filete, Panel, Pedestal, _cabecera, _raiz, _rombo, mayus  # noqa: E402

DESTINO = comun.SCRATCH / "rediseno"

# Colores de tipo del buscador (los de farmadex.ui.colores_tipo, ya legibles sobre el fondo C).
TIPO = {
    "warframe": ("Warframe", "#4fc3f7"), "arma": ("Arma", "#ff8a50"), "companero": ("Compañero", "#81c784"),
    "mod": ("Mod", "#7c9cff"), "arcano": ("Arcano", "#c78bff"), "recurso": ("Recurso", "#ffd54f"),
    "reliquia": ("Reliquia", "#d7b27a"), "glifo": ("Glifo", "#f48fb1"), "mision": ("Misión", "#4dd0a8"),
    "cosmetico": ("Aspecto", "#b0a8c8"), "otro": ("Otros", "#9aa4b2"),
}
FACCION = {
    "Grineer": "#e0784a", "Corpus": "#5cb8f0", "Infestados": "#9fd45a", "Infested": "#9fd45a",
    "Orokin": P["oro"], "Corrupto": P["oro"], "Fuego cruzado": "#c890f0", "Crossfire": "#c890f0",
    "Murmullo": "#b0a8c8",
}
ERA = {"Lith": "#9fc9a5", "Meso": "#8fb4e0", "Neo": "#c9a0e0", "Axi": "#e6c070", "Requiem": "#e07070", "Omnia": "#e8e0c8"}


# -- piezas nuevas del lenguaje C ---------------------------------------------------------


class Boton(QFrame):
    """Boton con una esquina cortada: dorado relleno si es el principal, filete si no."""

    def __init__(self, texto: str, ico: str | None = None, primario: bool = False, tam: int = 12,
                 color: str | None = None, ancho: int | None = None):
        super().__init__()
        self._prim = primario
        self._c = QColor(color or P["oro"])
        capa = QHBoxLayout(self)
        capa.setContentsMargins(12, 5, 14, 5)
        capa.setSpacing(6)
        tinta = P["acento_texto"] if primario else (color or P["oro"])
        if ico:
            capa.addWidget(icono(ico, tam + 2, tinta))
        capa.addWidget(mayus(texto, tam, tinta, 600, 1.5))
        if ancho:
            self.setFixedWidth(ancho)
            capa.insertStretch(0, 1)
            capa.addStretch(1)
        self.setFixedHeight(tam + 16)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        camino = ruta_chaflan(r, 7)
        if self._prim:
            p.fillPath(camino, self._c)
        else:
            c = QColor(self._c)
            c.setAlpha(22)
            p.fillPath(camino, c)
            c.setAlpha(170)
            p.setPen(QPen(c, 1))
            p.drawPath(camino)
        p.end()


class Barra(QWidget):
    """Barra fina de progreso; con `dos` pinta un tira y afloja entre dos colores (invasiones)."""

    def __init__(self, progreso: float, color: str = P["oro"], alto: int = 4, dos: str | None = None, ancho: int | None = None):
        super().__init__()
        self._p, self._c, self._dos = max(0.0, min(1.0, progreso)), QColor(color), dos
        self.setFixedHeight(alto)
        if ancho:
            self.setFixedWidth(ancho)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(self._dos) if self._dos else QColor(P["borde"]))
        p.fillRect(0, 0, int(w * self._p), h, self._c)
        if self._dos:
            p.fillRect(int(w * self._p) - 1, 0, 2, h, QColor(P["fondo"]))
        p.end()


class Puntos(QWidget):
    """Puntos en rombo (disposicion de agrietado): n llenos de 5."""

    def __init__(self, n: int, total: int = 5, color: str = P["oro"], lado: int = 11):
        super().__init__()
        self._n, self._t, self._c, self._l = n, total, QColor(color), lado
        self.setFixedSize(total * (lado + 6), lado + 4)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        l2 = self._l / 2
        for i in range(self._t):
            cx, cy = i * (self._l + 6) + l2 + 1, l2 + 2
            pol = QPolygonF([QPointF(cx, cy - l2), QPointF(cx + l2, cy), QPointF(cx, cy + l2), QPointF(cx - l2, cy)])
            p.setPen(QPen(self._c if i < self._n else QColor(P["tenue"]), 1.2))
            p.setBrush(self._c if i < self._n else Qt.NoBrush)
            p.drawPolygon(pol)
        p.end()


class Interruptor(QWidget):
    def __init__(self, on: bool):
        super().__init__()
        self._on = on
        self.setFixedSize(38, 20)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 3.5, 37, 13)
        p.setPen(QPen(QColor(P["oro"] if self._on else P["tenue"]), 1))
        c = QColor(P["oro"])
        c.setAlpha(60 if self._on else 0)
        p.setBrush(c)
        p.drawRoundedRect(r, 6.5, 6.5)
        x = 29 if self._on else 9
        pol = QPolygonF([QPointF(x, 1), QPointF(x + 9, 10), QPointF(x, 19), QPointF(x - 9, 10)])
        p.setBrush(QColor(P["oro"] if self._on else P["suave"]))
        p.setPen(Qt.NoPen)
        p.drawPolygon(pol)
        p.end()


class Deslizador(QWidget):
    def __init__(self, valor: float, ancho: int = 220):
        super().__init__()
        self._v = valor
        self.setFixedSize(ancho, 20)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width() - 16
        p.fillRect(8, 9, w, 2, QColor(P["borde"]))
        p.fillRect(8, 9, int(w * self._v), 2, QColor(P["oro"]))
        x = 8 + w * self._v
        p.setBrush(QColor(P["oro"]))
        p.setPen(QPen(QColor(P["fondo"]), 2))
        p.drawPolygon(QPolygonF([QPointF(x, 1), QPointF(x + 8, 10), QPointF(x, 19), QPointF(x - 8, 10)]))
        p.end()


class Muestra(QWidget):
    """Cuadrado de color (selector de color)."""

    def __init__(self, color: str, lado: int = 22, marcado: bool = False):
        super().__init__()
        self._c, self._m = QColor(color), marcado
        self.setFixedSize(lado, lado)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.fillPath(ruta_chaflan(r, 5), self._c)
        p.setPen(QPen(QColor(P["oro"] if self._m else P["borde"]), 2 if self._m else 1))
        p.drawPath(ruta_chaflan(r, 5))
        p.end()


def texto(t: str, tam: int = 14, color: str | None = None, peso: int = 400, envolver: bool = False):
    return lbl(t, tam, color or P["texto"], peso, envolver=envolver)


def suave(t: str, tam: int = 13, envolver: bool = False):
    return lbl(t, tam, P["suave"], envolver=envolver)


def chip_tipo(clave: str, tam: int = 11):
    nombre, color = TIPO.get(clave, TIPO["otro"])
    return etiqueta(nombre, color, tam)


def etiqueta(t: str, color: str, tam: int = 11, relleno: bool = False):
    c = QColor(color)
    e = mayus(t, tam, P["acento_texto"] if relleno else color, 600, 1.2)
    fondo = f"background: {color};" if relleno else f"background: rgba({c.red()},{c.green()},{c.blue()},26);"
    e.setStyleSheet(e.styleSheet() + fondo + f" border: 1px solid rgba({c.red()},{c.green()},{c.blue()},150);"
                    " padding-left: 7px; padding-right: 7px; padding-bottom: 1px;")
    e.setSizePolicy(e.sizePolicy().horizontalPolicy(), e.sizePolicy().verticalPolicy())
    e.setFixedHeight(tam + 12)
    return e


def tecla(k: str, t: str = "") -> QWidget:
    e = mayus(k, 12, P["acento_texto"], 700, 1)
    e.setStyleSheet(e.styleSheet() + f"background: {P['oro']}; padding: 1px 7px; border-radius: 3px;")
    if not t:
        return e
    w = QWidget()
    w.setLayout(fila(e, mayus(t, 12, P["texto"], 500, 1.3), espacio=7))
    return w


def contador(tengo: int, necesito: int, paso: bool = False) -> QWidget:
    w = QWidget()

    def boton(simbolo):
        b = Boton(simbolo, tam=13)
        b.layout().setContentsMargins(8, 0, 9, 0)
        b.setFixedSize(30, 24)
        return b

    num = mayus(f"{tengo} / {necesito}", 15, P["oro"] if tengo >= necesito else P["texto"], 600, 1)
    num.setFixedWidth(84)
    num.setAlignment(Qt.AlignCenter)
    extra = [lbl("×1", 11, P["tenue"])] if paso else []
    w.setLayout(fila(boton("−"), num, boton("+"), *extra, espacio=4))
    w.setFixedWidth(160 + (26 if paso else 0))
    return w


def valor(t: str, tam: int = 15, color: str | None = None) -> QWidget:
    """Cifra en la letra de titulares pero sin pasar a mayusculas (9,58/s, 1 h 19 min)."""
    return lbl(t, tam, color or P["texto"], 600, familia=TITULAR)


def img_o_rombo(nombre: str | None, lado: int) -> QWidget:
    """La imagen del objeto; si no esta en la caja de arena, un rombo tenue del mismo tamano."""
    ruta = Path(comun.os.environ["FARMADEX_DATOS"]) / "Farmadex" / "datos" / "img" / (nombre or "-")
    if nombre and ruta.exists():
        return imagen(nombre, lado)
    return SinImagen(lado)


class SinImagen(QWidget):
    """Hueco de imagen vacio: un recuadro tenue con esquinas cortadas."""

    def __init__(self, lado: int):
        super().__init__()
        self.setFixedSize(lado, lado)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = self.width() * 0.18
        r = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        p.setPen(QPen(QColor(P["borde"]), 1))
        p.fillPath(ruta_chaflan(r, r.width() / 4), QColor(P["panel2"]))
        p.drawPath(ruta_chaflan(r, r.width() / 4))
        p.end()


def subpestanas(opciones: list[tuple[str, str]], activa: str, derecha: QWidget | None = None) -> QHBoxLayout:
    """Segunda fila de menu: mas pequena, con subrayado dorado en la activa y un contador opcional."""
    items = []
    for clave, t in opciones:
        on = clave == activa
        w = QWidget()
        c = columna(mayus(t, 14, P["texto"] if on else P["suave"], 600 if on else 500, 2), espacio=3)
        linea = QFrame()
        linea.setFixedHeight(2)
        linea.setStyleSheet(f"background: {P['oro'] if on else 'transparent'};")
        c.addWidget(linea)
        w.setLayout(c)
        items += [w, 22]
    capa = fila(*items, None, margen=(30, 10, 30, 0), espacio=0)
    if isinstance(derecha, QHBoxLayout):
        capa.addLayout(derecha)
    elif derecha is not None:
        capa.addWidget(derecha)
    return capa


def pagina(activa: str, sub: list[tuple[str, str]] | None = None, sub_activa: str = "",
           sub_derecha: QWidget | None = None, margen=(30, 12, 30, 16)):
    r = _raiz()
    capa = QVBoxLayout(r)
    capa.setContentsMargins(0, 0, 0, 0)
    capa.setSpacing(0)
    capa.addLayout(_cabecera(activa))
    if sub:
        capa.addLayout(subpestanas(sub, sub_activa, sub_derecha))
    cuerpo = QVBoxLayout()
    cuerpo.setContentsMargins(*margen)
    cuerpo.setSpacing(12)
    capa.addLayout(cuerpo, 1)
    return r, capa, cuerpo


def pie_teclas(capa: QVBoxLayout, *pares) -> None:
    items = []
    for k, t in pares:
        items += [tecla(k, t), 24]
    capa.addWidget(Filete())
    capa.addLayout(fila(None, *items[:-1], margen=(30, 4, 30, 10), espacio=0))


def panel(titulo: str | None = None, remate: bool = True, fondo: str | None = None, borde: str | None = None,
          margen=None, espacio: int | None = None) -> Panel:
    pn = Panel(titulo, remate, fondo, borde)
    if margen:
        pn.capa.setContentsMargins(*margen)
    if espacio is not None:
        pn.capa.setSpacing(espacio)
    return pn


def buscador(textos: str = "", pista: str = "Busca un objeto, una reliquia o una misión") -> Panel:
    b = panel(remate=False, fondo=P["panel2"], borde=P["oro_tenue"], margen=(16, 3, 16, 3))
    if textos:
        caja = lbl(textos, 18, P["texto"], 400, familia=TITULAR)
    else:
        caja = lbl(pista, 18, P["tenue"], 400, familia=TITULAR)
    caja.setStyleSheet(caja.styleSheet() + " padding: 9px 4px;")
    b.capa.addLayout(fila(icono("buscar", 18, P["oro"]), caja, None, lbl("Enter", 12, P["tenue"]), espacio=8))
    return b


def ficha_foto(nombre_img: str | None, lado: int) -> QWidget:
    return Pedestal(nombre_img, lado) if nombre_img else QWidget()


def separador() -> QFrame:
    s = QFrame()
    s.setFixedHeight(1)
    s.setStyleSheet(f"background: {P['borde']};")
    return s


# -- datos --------------------------------------------------------------------------------

_CON = None


def con():
    global _CON
    if _CON is None:
        from farmadex.datos import indice

        _CON = indice.conectar()
    return _CON


def _mundo():
    from farmadex.online.worldstate import Traductor, analizar

    m = analizar(json.loads((comun.SCRATCH / "ws.json").read_text(encoding="utf-8")), Traductor(con()))
    ahora = m.momento + timedelta(minutes=3)

    def resta(exp):
        if not exp:
            return ""
        s = max(0, int((exp - ahora).total_seconds()))
        d, s2 = divmod(s, 86400)
        h, r = divmod(s2 // 60, 60)
        if d:
            return f"{d} d {h} h"
        return f"{h} h {r:02d} min" if h else f"{r} min"

    return m, resta


def nombre_item(fila_item) -> str:
    from farmadex.idiomas import nombre

    return nombre(fila_item)


# -- 1. BUSCAR ------------------------------------------------------------------------------


def _lista_resultados(consulta: str, activa_clave: str, limite: int = 11) -> Panel:
    from farmadex.datos import indice, misiones
    from farmadex.ui import colores_tipo

    c = con()
    filas = []
    for m in misiones.buscar(c, consulta)[:3]:
        if m["tipo_resultado"] != "nodo":
            continue
        filas.append(("mision", m["nodo_es"] or m["nodo_en"], f"{m['mision_es']} · {m['planeta_es']}", None, m["clave"]))
    for r in indice.buscar(c, consulta)[: limite - len(filas)]:
        tipo = colores_tipo.tipo_de(r)
        sub = r.get("padre_es") or {"Mods": "Mod", "Warframes": "Warframe", "Primary": "Arma principal",
                                     "Misc": "Varios", "Sigils": "Emblema", "Skins": "Decoración"}.get(r["categoria"], r["categoria"])
        filas.append((tipo, r["nombre_es"] or r["nombre_en"], sub, r.get("imagen"), str(r["item_id"])))
    pn = panel(margen=(12, 12, 12, 12), espacio=2)
    pn.capa.addLayout(fila(mayus(f"{len(filas)} resultados", 12, P["oro"], 600, 2), None,
                           Interruptor(False), suave("Ocultar bóveda", 12), margen=(6, 0, 4, 4), espacio=6))
    for tipo, nom, sub, img, clave in filas:
        on = clave == activa_clave
        _, col = TIPO.get(tipo, TIPO["otro"])
        linea = QFrame()
        linea.setObjectName("res")
        fondo = "rgba(212,176,106,30)" if on else "transparent"
        borde = P["oro"] if on else "transparent"
        linea.setStyleSheet(f"QFrame#res {{ background: {fondo}; border: 1px solid {borde}; border-left: 3px solid {col}; }}")
        ico = imagen(img, 30) if img else icono("mapa", 18, col)
        if not img:
            ico.setFixedSize(30, 30)
        linea.setLayout(fila(ico, columna(texto(nom, 14, P["texto"], 600), suave(sub, 12), espacio=0), None,
                             chip_tipo(tipo, 10), margen=(8, 4, 8, 4), espacio=10))
        pn.capa.addWidget(linea)
    pn.capa.addStretch(1)
    # Leyenda de colores al pie, en pequeno.
    for claves in (("warframe", "arma", "companero", "mod", "arcano"), ("recurso", "reliquia", "mision", "glifo", "cosmetico")):
        ley = []
        for k in claves:
            ley += [_rombo(7, TIPO[k][1]), lbl(TIPO[k][0], 11, P["suave"]), 8]
        pn.capa.addLayout(fila(*ley[:-1], None, espacio=4, margen=(4, 2, 0, 0)))
    return pn


def buscar_mision() -> QWidget:
    from farmadex.datos import misiones

    c = con()
    nodo = next(m for m in misiones.buscar(c, "hidron") if m["tipo_resultado"] == "nodo")
    rec = misiones.recompensas_de_nodo(c, nodo["id"])
    r, capa, cuerpo = pagina("buscar")
    cuerpo.addWidget(buscador("hidr"))
    fila_principal = fila(espacio=16)
    cuerpo.addLayout(fila_principal, 1)
    izq = _lista_resultados("hidr", nodo["clave"])
    izq.setFixedWidth(400)
    fila_principal.addWidget(izq)

    der = QVBoxLayout()
    der.setSpacing(12)
    fila_principal.addLayout(der, 1)
    # Cabecera de la ficha de mision.
    cab = panel(margen=(22, 14, 22, 14), espacio=6)
    nombre_nodo = nodo["nodo_es"] or nodo["nodo_en"]
    cab.capa.addLayout(fila(
        columna(Boton("Atrás", "atras", tam=10), 4), 8,
        columna(mayus("Misión · " + nodo["planeta_es"], 13, TIPO["mision"][1], 600, 2.5),
                mayus(nombre_nodo, 34, P["texto"], 600, 3), espacio=0),
        None,
        columna(fila(None, etiqueta(nodo["mision_es"], TIPO["mision"][1], 12),
                     etiqueta(f"Nivel {nodo['nivel_min']}–{nodo['nivel_max']}", P["suave"], 12), espacio=6),
                fila(None, Boton("Wiki", "web"), Boton("YouTube", "video"), Boton("Overframe", "build"), espacio=8),
                espacio=10),
        espacio=12,
    ))
    der.addWidget(cab)

    # Rotaciones AABC como una tira de rondas.
    from farmadex.datos import modos_mision

    unidad, cada = modos_mision.AABC["Defense"]
    _, _, que_hacer, recompensas_txt = modos_mision.MODOS["Defense"]
    tira = panel("Qué te dan y cuándo", margen=(22, 12, 22, 14), espacio=8)
    rondas = fila(espacio=6)
    for i, rot in enumerate("AABCAABC", 1):
        caja = QFrame()
        caja.setObjectName("ronda")
        col = {"A": P["suave"], "B": P["turquesa"], "C": P["oro"]}[rot]
        caja.setStyleSheet(f"QFrame#ronda {{ border: 1px solid {col}; background: rgba(255,255,255,{12 if i <= 4 else 4}); }}")
        caja.setLayout(columna(_c(mayus(rot, 20, col, 600, 1)), _c(lbl(f"{unidad} {i * cada}", 11, P["suave"])),
                               margen=(4, 2, 4, 4), espacio=0))
        rondas.addWidget(caja, 1)
    tira.capa.addLayout(rondas)
    from farmadex.idiomas import t as tr

    que_hacer, recompensas_txt = tr(que_hacer).replace("mision", "misión"), tr(recompensas_txt)
    tira.capa.addWidget(suave(recompensas_txt + " Aquí las reliquias Axi solo salen en B y C.", 13, True))
    der.addWidget(tira)

    rots = fila(espacio=12)
    for rot, titulo in (("A", "Rotación A"), ("B", "Rotación B"), ("C", "Rotación C")):
        col = {"A": P["suave"], "B": P["turquesa"], "C": P["oro"]}[rot]
        pn = panel(titulo, remate=rot == "C", margen=(16, 12, 16, 12), espacio=5)
        for x in rec.get(rot, [])[:6]:
            nom = (x["nombre_es"] or x["nombre_en"]).replace("Reliquia ", "")
            es_rel = (x["nombre_en"] or "").startswith(("Lith", "Meso", "Neo", "Axi", "Requiem")) or "Reliquia" in (x["nombre_es"] or "")
            era = nom.split()[0] if es_rel else ""
            pn.capa.addLayout(fila(_rombo(7, ERA.get(era, col)), texto(nom, 13, P["texto"], 500), None,
                                   lbl(f"{x['probabilidad']:.1f} %".replace(".", ","), 12, P["suave"]), espacio=7))
        resto = len(rec.get(rot, [])) - 6
        if resto > 0:
            pn.capa.addWidget(lbl(f"y {resto} más", 12, P["tenue"]))
        pn.capa.addStretch(1)
        rots.addWidget(pn, 1)
    der.addLayout(rots, 1)

    hacer = panel("Qué hacer", remate=False, margen=(22, 12, 22, 12), espacio=4)
    hacer.capa.addWidget(texto(que_hacer, 14, P["texto"], envolver=True))
    der.addWidget(hacer)
    pie_teclas(capa, ("+", "Añadir a mis metas"), ("C", "Copiar nombre"), ("Esc", "Volver"))
    return r


def _c(w):
    w.setAlignment(Qt.AlignCenter)
    return w


def buscar_arma() -> QWidget:
    from farmadex.datos import detalles, indice, items, relaciones
    from farmadex.ui.pestana_agrietados import puntos_disposicion

    c = con()
    res = indice.buscar(c, "braton prime")[0]
    f = items.ficha(c, res["item_id"])
    it = f["item"]
    arma = detalles.leer(c, res["item_id"]).get("arma", {})
    r, capa, cuerpo = pagina("buscar", margen=(30, 12, 30, 10))
    cuerpo.addWidget(buscador("braton prime"))
    principal = fila(espacio=20)
    cuerpo.addLayout(principal, 1)

    # Izquierda: vitrina y disposicion.
    izq = QVBoxLayout()
    izq.setSpacing(8)
    izq.addLayout(fila(None, Pedestal(it["imagen"], 250), None))
    izq.addWidget(_c(mayus("Arma principal · rifle", 13, P["suave"], 500, 3)))
    izq.addWidget(_c(mayus(nombre_item(it), 32, P["texto"], 600, 3)))
    izq.addLayout(fila(None, chip_tipo("arma", 11), etiqueta("Se puede farmear", P["ok"], 11),
                       etiqueta(f"Maestría {int(arma.get('maestria', 0))}", P["suave"], 11), None, espacio=6))
    disp = panel("Disposición de agrietado", margen=(18, 12, 18, 12), espacio=6)
    n = puntos_disposicion(arma.get("riven", 1)).count("●")
    disp.capa.addLayout(fila(Puntos(n, lado=13), 10, mayus(f"×{arma.get('riven', 1):.2f}".replace(".", ","), 18, P["oro"], 600, 1),
                             None, Boton("Precios", "tienda"), espacio=6))
    disp.capa.addWidget(suave("Cuantos más rombos, más fuertes salen sus agrietados. Este va en la media.", 12, True))
    izq.addWidget(disp)
    tuyo = panel(remate=False, margen=(18, 10, 18, 10), espacio=4)
    tuyo.capa.addLayout(fila(mayus("Maestría", 12, P["suave"], 600, 1.5), None, lbl("Sin dominar", 13, P["aviso"], 600), espacio=6))
    tuyo.capa.addLayout(fila(mayus("Tienes", 12, P["suave"], 600, 1.5), None, lbl("2 de 4 piezas", 13, P["texto"], 600), espacio=6))
    tuyo.capa.addLayout(fila(mayus("Mercado", 12, P["suave"], 600, 1.5), None, lbl("set desde 60 p · te lo compran por 52 p", 13, P["turquesa"], 600), espacio=6))
    izq.addWidget(tuyo)
    izq.addStretch(1)
    principal.addLayout(izq, 5)

    der = QVBoxLayout()
    der.setSpacing(12)
    principal.addLayout(der, 7)
    est = panel("Estadísticas", margen=(20, 12, 20, 12), espacio=4)
    pares = (
        ("Probabilidad crítica", f"{arma['critico'] * 100:.0f} %", arma["critico"] / 0.5),
        ("Multiplicador crítico", f"×{arma['mult_critico']:.1f}", arma["mult_critico"] / 4),
        ("Probabilidad de estado", f"{arma['estado'] * 100:.0f} %", arma["estado"] / 0.5),
        ("Cadencia", f"{arma['cadencia']:.2f}".rstrip("0").rstrip(".") + " por segundo", arma["cadencia"] / 15),
        ("Cargador", f"{arma['cargador']:.0f}", arma["cargador"] / 200),
        ("Recarga", f"{arma['recarga']:.1f} s", 1 - arma["recarga"] / 4),
    )
    rej = QHBoxLayout()
    rej.setSpacing(28)
    for mitad in (pares[:3], pares[3:]):
        col = QVBoxLayout()
        col.setSpacing(7)
        for k, v, frac in mitad:
            col.addLayout(fila(suave(k, 13), None, valor(v.replace(".", ","), 15)))
            col.addWidget(Barra(frac, P["oro_tenue"], 3))
        rej.addLayout(col, 1)
    est.capa.addLayout(rej)
    est.capa.addSpacing(4)
    dano = arma.get("dano", {})
    total = sum(dano.values()) or 1
    nombres = {"impact": ("Impacto", "#9fb4c8"), "puncture": ("Perforación", "#d8c890"), "slash": ("Cortante", "#e07a6a")}
    trozos = fila(mayus(f"Daño {arma.get('dano_total', total):.0f}", 13, P["oro"], 600, 1.5), 10, espacio=0)
    for k, v in dano.items():
        nom, col = nombres.get(k, (k, P["suave"]))
        b = Barra(1, col, 8)
        trozos.addWidget(b, int(v / total * 100))
    est.capa.addLayout(trozos)
    ley = []
    for k, v in dano.items():
        nom, col = nombres.get(k, (k, P["suave"]))
        ley += [_rombo(7, col), lbl(f"{nom} {v:.1f}".replace(".", ","), 12, P["suave"]), 10]
    est.capa.addLayout(fila(*ley, None, espacio=4))
    der.addWidget(est)

    donde = panel("Dónde se consigue", margen=(20, 12, 20, 12), espacio=6)
    for comp in f["componentes"]:
        mr = relaciones.mejor_ruta(c, comp["id"]) or {}
        rel = mr.get("reliquia") or {}
        rel_n = nombre_item(rel).replace("Reliquia ", "") if rel else "—"
        era = rel_n.split()[0] if rel else ""
        m = mr.get("mision") or {}
        if mr.get("solo_en_boveda"):
            detalle = lbl("Solo en bóveda: intercambio o Baro", 13, P["aviso"])
            tiempo = etiqueta("Bóveda", P["aviso"], 10)
        else:
            detalle = suave(f"{m.get('mision', '')} en {m.get('donde', '')}", 13)
            tiempo = valor(minutos_txt(mr.get("minutos_pieza")), 13, P["oro"])
        img = imagen(comp.get("imagen"), 30)
        donde.capa.addLayout(fila(img, texto(comp["nombre_es"] or comp["nombre_en"], 14, P["texto"], 600), 6,
                                  _rombo(8, ERA.get(era, P["suave"])), lbl(rel_n, 13, ERA.get(era, P["suave"]), 600),
                                  detalle, None, tiempo, espacio=8))
    der.addWidget(donde)
    rels = panel("Reliquias", remate=False, margen=(20, 12, 20, 12), espacio=6)
    vistas = []
    for comp in f["componentes"]:
        for rl in relaciones.reliquias_de(c, comp["id"]):
            vistas.append((nombre_item(rl).replace("Reliquia ", ""), bool(rl["vaulted"]), comp["nombre_es"] or comp["nombre_en"],
                           (rl.get("probabilidades") or {}).get("Radiant")))
    vistas.sort(key=lambda v: (v[1], v[0]))
    fl = QHBoxLayout()
    fl.setSpacing(18)
    for mitad in (vistas[:4], vistas[4:8]):
        col = QVBoxLayout()
        col.setSpacing(4)
        for nom, bov, pieza, prob in mitad:
            era = nom.split()[0]
            col.addLayout(fila(_rombo(8, ERA.get(era, P["suave"])), lbl(nom, 13, ERA.get(era, P["suave"]), 600),
                               suave(pieza, 12), None,
                               etiqueta("Bóveda", P["aviso"], 9) if bov else lbl(f"{prob:.0f} % en Radiante" if prob else "", 12, P["suave"]),
                               espacio=6))
        col.addStretch(1)
        fl.addLayout(col, 1)
    rels.capa.addLayout(fl)
    if len(vistas) > 8:
        rels.capa.addWidget(lbl(f"y {len(vistas) - 8} reliquias más en bóveda", 12, P["tenue"]))
    der.addWidget(rels)
    der.addLayout(fila(None, Boton("Añadir el set a mis metas", "mas", primario=True), Boton("Wiki", "web"),
                       Boton("YouTube", "video"), Boton("Overframe", "build"), espacio=8))
    der.addStretch(1)
    pie_teclas(capa, ("+", "Añadir a mis metas"), ("W", "Wiki"), ("O", "Overframe"), ("Esc", "Volver"))
    return r


# -- 2. MIS METAS --------------------------------------------------------------------------

SUB_METAS = [("objetivos", "Objetivos"), ("primes", "Primes"), ("perfil", "Perfil")]


def _fila_meta(img, nombre, tipo, sub, tengo, necesito, desplegado: bool | None = None, marcado=False, hija=False,
               sub_color: str | None = None):
    fondo = P["panel2"] if not hija else "#0e1415"
    pn = panel(remate=marcado, fondo=fondo, borde=P["oro"] if marcado else P["borde"], margen=(10, 5, 12, 5), espacio=0)
    flecha = icono("abajo" if desplegado else "derecha", 12, P["oro"]) if desplegado is not None else QWidget()
    flecha.setFixedWidth(16)
    acciones = [icono("check", 15, P["ok"]), icono("", 14, P["suave"]), icono("cerrar", 12, P["tenue"])]
    pn.capa.addLayout(fila(
        _casilla(False) if not hija else fila_w(), flecha, img_o_rombo(img, 34 if not hija else 26),
        columna(fila(texto(nombre, 15 if not hija else 13, P["texto"], 600), chip_tipo(tipo, 10) if tipo else QWidget(), None, espacio=8),
                lbl(sub, 12, sub_color or P["suave"]), espacio=0),
        None, contador(tengo, necesito, paso=not hija), 6, *acciones, espacio=8,
    ))
    return pn


def metas_objetivos() -> QWidget:
    from farmadex.datos import indice, relaciones
    from farmadex.estado import objetivos

    c = con()
    der = fila(Boton("Leer inventario de la pantalla", "ventana", tam=11), espacio=0)
    r, capa, cuerpo = pagina("metas", SUB_METAS, "objetivos", der)
    estados = fila(espacio=0)
    for i, (t, n) in enumerate((("Sin empezar", 6), ("En progreso", 3), ("Completados", 11))):
        estados.addWidget(Boton(f"{t}  {n}", primario=i == 0, tam=11))
        estados.addSpacing(8)
    estados.addSpacing(10)
    estados.addWidget(suave("Mostrar:", 12))
    estados.addSpacing(6)
    estados.addWidget(Boton("Todas las categorías", "abajo", tam=10))
    estados.addStretch(1)
    estados.addWidget(suave("9 por conseguir · 11 completados", 12))
    cuerpo.addLayout(estados)

    principal = fila(espacio=16)
    cuerpo.addLayout(principal, 1)
    lista = QVBoxLayout()
    lista.setSpacing(5)
    principal.addLayout(lista, 7)

    # Magistar desplegado con sus recursos de fabricacion (receta real del indice).
    mag = indice.buscar(c, "magistar")[0]
    un = c.execute("SELECT unique_name FROM items WHERE id=?", (mag["item_id"],)).fetchone()[0]
    lista.addWidget(_fila_meta(mag["imagen"], "Magistar", "arma", "Plano en el mercado · se fabrica en la fundición", 0, 1, True, True))
    tengo = {"Ferrite": 512, "Rubedo": 300, "Alloy Plate": 35, "Gallium": 1, "Blueprint": 1}
    receta = objetivos.receta_de(c, un)
    listos = sum(1 for _u, en, _e, cant in receta if tengo.get(en, 0) >= cant)
    rejilla = panel(remate=False, fondo="#0e1415", borde=P["borde"], margen=(62, 6, 12, 8), espacio=4)
    rejilla.capa.addWidget(mayus(f"Recursos de fabricación · {listos} de {len(receta)} listos", 11, P["oro"], 600, 1.5))
    for u, en, es, cant in receta:
        t = tengo.get(en, 0)
        img = c.execute("SELECT imagen FROM items WHERE unique_name=?", (u,)).fetchone()
        nom = texto(es or en, 13, P["texto"], 500)
        nom.setFixedWidth(150)
        tienes = lbl(f"(tienes {t})" if en != "Blueprint" else "", 11, P["tenue"])
        tienes.setFixedWidth(80)
        listo = etiqueta("Listo", P["ok"], 9, relleno=True) if t >= cant else Boton("Listo", tam=9)
        listo.setFixedWidth(64)
        rejilla.capa.addLayout(fila(img_o_rombo(img and img[0], 22), nom,
                                    Barra(t / cant, P["ok"] if t >= cant else P["oro"], 3, ancho=150), tienes, None,
                                    contador(t, cant), 4, listo, espacio=10))
    lista.addWidget(rejilla)

    # Set de Citrine Prime desplegado: una fila por pieza, con su mejor ruta.
    cit = indice.buscar(c, "citrine prime")[0]
    lista.addWidget(_fila_meta(cit["imagen"], "Set de Citrine Prime", "warframe", "Set: 1 de 4 piezas", 1, 4, True))
    padre = c.execute("SELECT id FROM items WHERE nombre_en='Citrine Prime' AND padre_id IS NULL").fetchone()[0]
    for pid, pe, pen, pim in c.execute("SELECT id, nombre_es, nombre_en, imagen FROM items WHERE padre_id=? ORDER BY nombre_en", (padre,)):
        mr = relaciones.mejor_ruta(c, pid) or {}
        rel = mr.get("reliquia")
        hecho = pen == "Blueprint"
        sub = ("Conseguida" if hecho else
               f"Fárméala en {mr['mision']['donde']} ({mr['mision']['mision']}) · {nombre_item(rel).replace('Reliquia ', '')}"
               if rel and mr.get("mision") else "Sin ruta conocida")
        w = _fila_meta(pim, pe or pen, None, sub.replace("Fárméala", "Farméala"), 1 if hecho else 0, 1, None, hija=True)
        w.capa.setContentsMargins(62, 3, 12, 3)
        lista.addWidget(w)
    forma = c.execute("SELECT imagen FROM items WHERE nombre_en='Forma' AND padre_id IS NULL").fetchone()
    lista.addWidget(_fila_meta(forma and forma[0], "Forma", "recurso", "Invasión en Antea (Saturno) da el plano ahora mismo", 1, 3, False,
                               sub_color=P["turquesa"]))
    lista.addStretch(1)
    pie = fila(_casilla(False), suave("Marcar los de esta página", 12), 10, Boton("Borrar marcados (0)", tam=10), None,
               Boton("‹ Anterior", tam=10), suave("Página 1 de 1", 12), Boton("Siguiente ›", tam=10), espacio=8)
    lista.addLayout(pie)

    lado = QVBoxLayout()
    lado.setSpacing(12)
    principal.addLayout(lado, 3)
    lado.addWidget(Boton("Añadir un objetivo", "mas", primario=True, tam=12))
    ahora = panel("Para esto te sirve hoy", margen=(18, 12, 18, 12), espacio=8)
    for era, n, para in (("Lith", 3, "Sistemas"), ("Neo", 1, "Chasis")):
        ahora.capa.addLayout(fila(_rombo(9, ERA[era]), mayus(f"Fisura {era}", 12, ERA[era], 600, 1.5), suave(para, 12), None,
                                  suave(f"{n} abierta{'s' if n > 1 else ''}", 12), espacio=6))
    ahora.capa.addLayout(fila(_rombo(9, FACCION["Grineer"]), mayus("Invasión", 12, FACCION["Grineer"], 600, 1.5), suave("Forma", 12), None,
                              suave("Antea", 12), espacio=6))
    lado.addWidget(ahora)
    ayuda = panel("Cómo se usa", remate=False, margen=(18, 12, 18, 12), espacio=6)
    for linea in ("+ y − suman o restan; ×1 elige cuánto suma cada clic.",
                  "Al abrir reliquias en solitario, Farmadex lo suma solo.",
                  "✓ lo da por hecho · lápiz para editar · × para quitar.",
                  "La flecha abre las piezas del set o los recursos para fabricarlo."):
        ayuda.capa.addWidget(suave(linea, 12, True))
    lado.addWidget(ayuda)
    lado.addStretch(1)
    return r


def metas_primes() -> QWidget:
    from farmadex.datos import ruta_prime

    c = con()
    objetos, sueltos = ruta_prime.catalogo(c)
    der = fila(suave("Reliquias:", 12), Boton("Radiante", "abajo", tam=10), 10, suave("Jugando:", 12),
               Boton("Escuadra de 4 compartiendo reliquia", "abajo", tam=10), espacio=6)
    r, capa, cuerpo = pagina("metas", SUB_METAS, "primes", der)
    barra = fila(espacio=10)
    filtro = panel(remate=False, fondo=P["panel2"], borde=P["oro_tenue"], margen=(12, 1, 12, 1))
    filtro.capa.addLayout(fila(icono("buscar", 14, P["oro"]), lbl("Filtra por nombre (p. ej. caliban, forma)", 13, P["tenue"]), None, espacio=6))
    filtro.setFixedWidth(310)
    barra.addWidget(filtro)
    barra.addWidget(fila_w(Interruptor(True), suave("Incluir lo que está en bóveda", 12)))
    barra.addStretch(1)

    barra.addWidget(suave("Ordenar:", 12))
    barra.addWidget(Boton("Marcados primero", "abajo", tam=11))
    barra.addWidget(Boton("Desmarcar todo", tam=11))
    barra.addWidget(Boton("Ver qué farmear", "derecha", primario=True, tam=11))
    cuerpo.addLayout(barra)

    marcados = {"Citrine Prime": {"Blueprint"}, "Braton Prime": {"Blueprint", "Stock"}, "Ash Prime": set(),
                "Acceltra Prime": {"Barrel"}}
    orden = sorted(objetos, key=lambda o: (o["nombre_en"] not in marcados, o["nombre_en"]))
    rej = QVBoxLayout()
    rej.setSpacing(10)
    cols = 5
    for fila_i in range(4):
        fl = fila(espacio=10)
        for o in orden[fila_i * cols:(fila_i + 1) * cols]:
            fl.addWidget(_caja_set(o, marcados.get(o["nombre_en"])), 1)
        rej.addLayout(fl)
    cuerpo.addLayout(rej)
    gen = panel(f"Genéricos (no son de ningún set) · además de {len(objetos)} sets Prime", remate=False, margen=(18, 10, 18, 10), espacio=6)
    fl = fila(espacio=16)
    for s in sueltos[:6]:
        fl.addWidget(fila_w(_casilla(False), texto(s["nombre_es"] or s["nombre_en"], 13)))
    fl.addStretch(1)
    fl.addWidget(suave(f"y {len(sueltos) - 6} más", 12))
    gen.capa.addLayout(fl)
    cuerpo.addWidget(gen)
    cuerpo.addStretch(1)
    return r


def fila_w(*ws, espacio=6) -> QWidget:
    w = QWidget()
    w.setLayout(fila(*ws, espacio=espacio))
    return w


def _casilla(on: bool) -> QWidget:
    return _rombo(12, P["oro"], on) if on else _rombo(12, P["tenue"], False)


def _caja_set(o: dict, marcado: set | None) -> Panel:
    c = con()
    img = c.execute("SELECT imagen FROM items WHERE id=?", (o["id"],)).fetchone()[0]
    activo = marcado is not None
    pn = panel(remate=activo, fondo=P["panel2"], borde=P["oro"] if activo else P["borde"], margen=(12, 7, 12, 7), espacio=2)
    cab = fila(img_o_rombo(img, 34), columna(texto(o["nombre_es"] or o["nombre_en"], 14, P["texto"], 600),
                                        (etiqueta("Bóveda", P["aviso"], 9) if o["en_boveda"] else etiqueta("Se farmea", P["ok"], 9)),
                                        espacio=2), None, espacio=8)
    pn.capa.addLayout(cab)
    for p in o["piezas"][:4]:
        on = bool(marcado) and p["nombre_en"] in marcado
        nom = p["nombre_es"] or p["nombre_en"]
        pn.capa.addLayout(fila(_casilla(on), lbl(nom, 12, P["texto"] if on else P["suave"]), None,
                               lbl("×" + str(p["item_count"]) if (p.get("item_count") or 1) > 1 else "", 11, P["tenue"]), espacio=6))
    pn.capa.addStretch(1)
    return pn


def metas_perfil() -> QWidget:
    der = fila(fila_w(Interruptor(True), suave("Nodos pendientes del Camino de Acero", 12)), 12,
               Boton("Importar perfil (JSON)", "ventana", primario=True, tam=11), espacio=0)
    r, capa, cuerpo = pagina("metas", SUB_METAS, "perfil", der)
    c = con()
    # Totales reales de lo que da maestria por categoria (del indice); el avance es de ejemplo.
    cats = (("Warframes", "Warframes", 0.74), ("Primary", "Armas principales", 0.61), ("Secondary", "Armas secundarias", 0.55),
            ("Melee", "Cuerpo a cuerpo", 0.58), ("Sentinels", "Centinelas", 0.5), ("Pets", "Compañeros", 0.42),
            ("Archwing", "Archwing", 0.6), ("Arch-Gun", "Armas Archwing", 0.33))
    arriba = fila(espacio=14)
    rango = panel("Tu maestría", margen=(22, 12, 22, 14), espacio=4)
    rango.capa.addLayout(fila(
        columna(mayus("Rango", 12, P["suave"], 500, 3), mayus("24", 58, P["oro"], 600, 2), espacio=0),
        20,
        columna(texto("Te faltan 187 400 puntos para el rango 25", 15, P["texto"], 600),
                Barra(0.62, P["oro"], 6),
                suave("Clan: —  ·  PC  ·  importado el 21/09 a las 17:41", 12),
                suave("Lo más rápido: subir a 30 lo que ya tienes a medias.", 12), None, espacio=7),
        espacio=0))
    arriba.addWidget(rango, 5)
    nodos = panel("Mapa estelar", margen=(22, 12, 22, 14), espacio=5)
    nodos.capa.addLayout(fila(valor("214 / 227", 28), None, suave("normal", 12), espacio=6))
    nodos.capa.addWidget(Barra(214 / 227, P["turquesa"], 5))
    nodos.capa.addLayout(fila(valor("186 / 227", 18, P["suave"]), None, suave("Camino de Acero", 12), espacio=6))
    nodos.capa.addWidget(Barra(186 / 227, P["oro_tenue"], 3))
    arriba.addWidget(nodos, 3)
    cuerpo.addLayout(arriba)

    medio = fila(espacio=14)
    tabla = panel("Maestría por categoría", margen=(22, 12, 22, 12), espacio=5)
    cab = fila(lbl("", 12), None, espacio=0)
    for t, col in (("Dominados", P["ok"]), ("A medias", P["oro"]), ("Sin tocar", P["suave"]), ("Total", P["suave"])):
        e = mayus(t, 10, col, 600, 1.2)
        e.setFixedWidth(74)
        e.setAlignment(Qt.AlignRight)
        cab.addWidget(e)
    tabla.capa.addLayout(cab)
    for cat, nom, frac in cats:
        total = c.execute("SELECT COUNT(*) FROM items WHERE categoria=? AND padre_id IS NULL AND tipo NOT IN ('Componente')", (cat,)).fetchone()[0]
        dom = int(total * frac)
        med = int(total * 0.12)
        sin = total - dom - med
        n = texto(nom, 13, P["texto"], 600)
        n.setFixedWidth(140)
        fl = fila(n, espacio=10)
        fl.addWidget(Barra(dom / max(1, total), P["ok"], 4, dos=P["borde"]), 1)
        for v, col in ((dom, P["ok"]), (med, P["oro"]), (sin, P["suave"]), (total, P["suave"])):
            e = valor(str(v), 13, col)
            e.setFixedWidth(74)
            e.setAlignment(Qt.AlignRight)
            fl.addWidget(e)
        tabla.capa.addLayout(fl)
    medio.addWidget(tabla, 5)
    lado = QVBoxLayout()
    lado.setSpacing(12)
    intr = panel("Intrínsecos", remate=False, margen=(20, 12, 20, 12), espacio=5)
    for grupo, lista in (("Railjack", (("Táctica", 10), ("Pilotaje", 10), ("Artillería", 8), ("Ingeniería", 7), ("Mando", 6))),
                         ("Errante", (("Combate", 6), ("Montar", 5), ("Oportunidad", 4), ("Resistencia", 3)))):
        intr.capa.addWidget(mayus(grupo, 11, P["oro"], 600, 1.5))
        intr.capa.addLayout(fila(*[w for k, v in lista for w in (suave(k, 12), valor(str(v), 12))], None, espacio=5))
    lado.addWidget(intr)
    sind = panel("Sindicatos", remate=False, margen=(20, 12, 20, 12), espacio=4)
    for nom, rango_s, col in (("Velo Rojo", "Rango 5", "#e07070"), ("Nuevo Loka", "Rango 3", P["ok"]), ("Hexis de Arbitrio", "Rango 2", P["turquesa"])):
        sind.capa.addLayout(fila(_rombo(8, col), texto(nom, 13, P["texto"], 600), None, suave(rango_s, 12), espacio=6))
    lado.addWidget(sind)
    lado.addStretch(1)
    medio.addLayout(lado, 3)
    cuerpo.addLayout(medio)

    abajo = fila(espacio=14)
    por = panel("Por dominar", remate=False, margen=(20, 10, 20, 10), espacio=4)
    por.capa.addLayout(fila(*[w for n in ("Hildryn", "Hind", "Magistar", "Braton Prime", "Lex Prime", "Orthos Prime")
                              for w in (_rombo(7, P["oro"]), texto(n, 13))], None, lbl("y 128 más", 12, P["tenue"]), espacio=6))
    abajo.addWidget(por, 5)
    pend = panel("Nodos pendientes", remate=False, margen=(20, 10, 20, 10), espacio=4)
    pend.capa.addLayout(fila(texto("Plutón 3 · Sedna 4 · Eris 6", 13), None, Boton("Ver cuáles", "derecha", tam=10), espacio=6))
    abajo.addWidget(pend, 3)
    cuerpo.addLayout(abajo)
    nota = panel("De dónde sale esto", remate=False, margen=(20, 10, 20, 12), espacio=4)
    nota.capa.addWidget(suave("Hoy el juego no deja descargar el perfil solo: si tienes tu perfil en un fichero JSON, impórtalo con el botón de arriba. "
                              "Además, la maestría se marca sola cuando abres Perfil › Equipamiento en el juego: Farmadex solo mira la pantalla.", 12, True))
    cuerpo.addWidget(nota)
    cuerpo.addStretch(1)
    return r


# -- 3. MUNDO ---------------------------------------------------------------------------------


def mundo() -> QWidget:
    m, resta = _mundo()
    der = fila(Boton("Personalizar y avisos", "ajustes", tam=11), espacio=0)
    r, capa, cuerpo = pagina("mundo", [("todo", "Todo"), ("fisuras", "Fisuras"), ("tienda", "Baro y Teshin"),
                                       ("eventos", "Invasiones y alertas")], "todo", der, margen=(30, 12, 30, 14))
    arriba = fila(espacio=14)
    cuerpo.addLayout(arriba, 6)
    # Fisuras: una columna por era, con la faccion en color.
    fis = panel("Fisuras del Vacío", margen=(18, 12, 18, 12), espacio=8)
    modos = fila(Boton("Normales", primario=True, tam=10), Boton("Camino de Acero", tam=10), Boton("Tormentas", tam=10),
                 Boton("Facciones: todas", "abajo", tam=10), None, *[w for f, col in (("Grineer", FACCION["Grineer"]), ("Corpus", FACCION["Corpus"]),
                                          ("Infestados", FACCION["Infestados"]), ("Fuego cruzado", FACCION["Crossfire"]))
                         for w in (_rombo(8, col), lbl(f, 11, P["suave"]))], espacio=5)
    fis.capa.addLayout(modos)
    cols = fila(espacio=14)
    for era in ("Lith", "Meso", "Neo", "Axi", "Requiem"):
        col = QVBoxLayout()
        col.setSpacing(5)
        lista = [f for f in m.fisuras if f.era == era and not f.acero and not f.tormenta]
        para = {"Lith": "Sistemas de Citrine", "Neo": "Chasis de Citrine"}.get(era)
        col.addLayout(fila(_rombo(9, ERA[era]), mayus(era, 14, ERA[era], 600, 2), None, lbl(str(len(lista)), 12, P["tenue"]), espacio=6))
        col.addWidget(separador())
        for f in lista[:4]:
            colf = FACCION.get(f.enemigo, P["suave"])
            caja = QFrame()
            caja.setObjectName("fis")
            util = bool(para)
            borde = f"border: 1px solid {P['oro']};" if util else ""
            caja.setStyleSheet(f"QFrame#fis {{ background: rgba(255,255,255,6); {borde} border-left: 3px solid {colf}; }}")
            nodo, _, planeta = f.nodo.partition(", ")
            caja.setLayout(columna(texto(nodo, 13, P["texto"], 600), lbl(f"{f.mision} · {planeta}", 11, P["suave"]),
                                   lbl(f"★ para {para}" if util else f.enemigo, 11, P["oro"] if util else colf, 600),
                                   margen=(8, 3, 4, 3), espacio=0))
            col.addWidget(caja)
        col.addStretch(1)
        cols.addLayout(col, 1)
    fis.capa.addLayout(cols, 1)
    fis.capa.addWidget(lbl("★ con borde dorado: te sirve para tus metas · Omnia: Comunas Tuvul (Zariman), Cascada del Vacío", 11, P["tenue"]))
    arriba.addWidget(fis, 13)

    lado = QVBoxLayout()
    lado.setSpacing(12)
    arriba.addLayout(lado, 6)
    b = m.baro_detalle
    baro = panel("Baro Ki'Teer", margen=(18, 12, 18, 12), espacio=4)
    baro.capa.addLayout(fila(columna(mayus("Llega en " + resta(b.llegada), 20, P["oro"], 600, 1),
                                     suave(b.lugar + " · se queda 2 días", 12), espacio=0), None,
                             Boton("Avisarme", "reloj", tam=11), espacio=6))
    baro.capa.addWidget(suave("Cuando llegue verás aquí lo que trae, con lo que te falta marcado.", 12, True))
    lado.addWidget(baro)
    t = m.acero[0]
    teshin = panel("Teshin · Camino de Acero", remate=False, margen=(18, 12, 18, 12), espacio=4)
    teshin.capa.addLayout(fila(columna(texto(t.texto.replace(",", "."), 16, P["texto"], 600),
                                       suave(t.detalle.replace("de esencia", "esencias de Acero"), 12), espacio=0), None,
                               columna(lbl("cambia en", 11, P["tenue"]), mayus(resta(t.expira), 13, P["suave"], 600, 1), espacio=0),
                               espacio=6))
    lado.addWidget(teshin)
    hoy = panel("Hoy", remate=False, margen=(18, 12, 18, 12), espacio=5)
    for tit, det, col in (("Incursión", m.sortie[0].texto.split(" - ")[0] + " y 2 más", P["oro"]),
                          ("Caza de arcontes", m.arcontes[0].texto.split(" - ")[0] + " y 2 más", "#e07070"),
                          ("Onda nocturna", "3 diarios · 1 semanal", P["turquesa"]),
                          ("Arbitraje", "sin publicar ahora", P["suave"])):
        hoy.capa.addLayout(fila(_rombo(8, col), mayus(tit, 12, col, 600, 1.2), None, suave(det, 12), espacio=6))
    lado.addWidget(hoy)
    lado.addStretch(1)

    abajo = fila(espacio=14)
    cuerpo.addLayout(abajo, 5)
    inv = panel("Invasiones", margen=(18, 12, 18, 12), espacio=6)
    for i in m.invasiones[:4]:
        ca, cd = FACCION.get(i.atacante, P["suave"]), FACCION.get(i.defensor, P["suave"])
        premios = fila(espacio=6)
        vistos = set()
        for o in i.objetos:
            nom = f"{o.cantidad}× {o.nombre_es or o.nombre_en}" if o.cantidad > 1 else (o.nombre_es or o.nombre_en)
            if nom in vistos:
                continue
            vistos.add(nom)
            e = lbl(f"<u>{nom}</u> ›", 12, P["oro"], 600)
            premios.addWidget(e)
        premios.addStretch(1)
        nodo, _, planeta = i.nodo.partition(", ")
        inv.capa.addLayout(fila(texto(nodo, 13, P["texto"], 600), suave(planeta, 11), None,
                                lbl(i.atacante, 11, ca, 600), lbl("contra", 11, P["tenue"]), lbl(i.defensor, 11, cd, 600), espacio=5))
        inv.capa.addWidget(Barra(i.porcentaje / 100, ca, 3, dos=cd))
        inv.capa.addLayout(premios)
    inv.capa.addStretch(1)
    abajo.addWidget(inv, 7)
    ale = panel("Alertas", remate=False, margen=(18, 12, 18, 12), espacio=6)
    ale.capa.addWidget(texto("Ahora no hay ninguna alerta.", 14, P["texto"], 600))
    ale.capa.addWidget(suave("Suelen traer catalizadores, reactores o aspectos. Si quieres, te aviso en cuanto salga una.", 12, True))
    ale.capa.addWidget(Boton("Avisarme de alertas", "reloj", tam=11))
    ale.capa.addStretch(1)
    abajo.addWidget(ale, 4)
    cic = panel("Ciclos", margen=(18, 12, 18, 12), espacio=5)
    for ci in m.ciclos[:6]:
        noche = ci.estado.lower() in ("noche", "frio", "fass", "miedo")
        cic.capa.addLayout(fila(icono("luna" if noche else "sol", 14, P["turquesa"] if noche else P["oro"]),
                                texto(ci.nombre, 13, P["texto"], 600), suave(ci.estado, 12), None,
                                lbl(resta(ci.expira) if ci.expira else "", 12, P["suave"]), espacio=6))
    cic.capa.addStretch(1)
    abajo.addWidget(cic, 5)
    cuerpo.addWidget(lbl("Datos del juego de hace 3 min · se actualiza solo cada minuto", 11, P["tenue"]))
    return r


def mundo_avisos() -> QWidget:
    from farmadex.online import avisos_mundo

    der = fila(Boton("Volver a Mundo", "atras", tam=11), espacio=0)
    r, capa, cuerpo = pagina("mundo", [("todo", "Todo"), ("fisuras", "Fisuras"), ("tienda", "Baro y Teshin"),
                                       ("eventos", "Invasiones y alertas")], "todo", der)
    cuerpo.addLayout(fila(mayus("Personalizar y avisos", 22, P["texto"], 600, 3), 16,
                          suave("Todo viene apagado. Cada aviso sale una sola vez, como aviso de Windows.", 13), None, espacio=0))
    principal = fila(espacio=14)
    cuerpo.addLayout(principal, 1)
    ver = panel("Qué bloques enseñar", margen=(18, 12, 18, 12), espacio=5)
    for on, nom in ((True, "Ahora: ciclos y Baro de un vistazo"), (True, "Ciclos"), (True, "Fisuras para tus metas"),
                    (True, "Fisuras del Vacío"), (False, "Fisuras del Camino de Acero"), (False, "Tormentas del Vacío"),
                    (True, "Incursión y arcontes"), (True, "Baro Ki'Teer"), (True, "Teshin · Camino de Acero"),
                    (True, "Invasiones y alertas"), (False, "Onda nocturna")):
        ver.capa.addLayout(fila(texto(nom, 13, P["texto"] if on else P["suave"], 600 if on else 400), None, Interruptor(on), espacio=8))
    ver.capa.addStretch(1)
    ver.capa.addWidget(suave("Lo que apagues desaparece de la pestaña Mundo.", 12, True))
    principal.addWidget(ver, 4)

    av = panel("Avísame cuando…", margen=(18, 12, 18, 12), espacio=5)
    reglas = (
        (True, "Salga una fisura como estas", "fisura", True),
        (True, "Llegue Baro Ki'Teer", "tienda", False),
        (True, "Baro traiga algo de mis metas", "tienda", False),
        (False, "Teshin ofrezca Kuva esta semana", "estrella", False),
        (True, "Teshin ofrezca Forma Umbra esta semana", "estrella", False),
        (False, "Cada semana, lo que ofrezca Teshin", "estrella", False),
        (False, "Recordatorio semanal: Kuva de Palladino", "reloj", False),
        (False, "Arbitrajes de estos tipos", "grupo", False),
        (True, "Invasiones con: Orokin, Forma, Exilus", "grupo", False),
        (False, "Alertas nuevas", "info", False),
        (False, "Incursión nueva (cada día)", "info", False),
        (False, "Caza de arcontes nueva (cada semana)", "info", False),
        (True, "Se haga de noche en Cetus", "luna", False),
    )
    for on, tit, ico, abierta in reglas:
        pn = panel(remate=False, fondo=P["panel2"] if not abierta else "#1b2426", borde=P["oro"] if abierta else (P["oro_tenue"] if on else P["borde"]),
                   margen=(12, 4, 12, 4), espacio=0)
        pn.capa.addLayout(fila(icono(ico, 14, P["oro"] if on else P["tenue"]), texto(tit, 13, P["texto"] if on else P["suave"], 600 if on else 400),
                               None, icono("derecha", 11, P["oro"]) if abierta else QWidget(), Interruptor(on), espacio=8))
        av.capa.addWidget(pn)
    av.capa.addStretch(1)
    principal.addWidget(av, 5)

    det = panel("Fisuras: de qué tipo", margen=(18, 12, 18, 12), espacio=7)
    det.capa.addWidget(mayus("Tipo de misión", 11, P["oro"], 600, 1.5))
    marcados = {"Supervivencia", "Defensa", "Exterminio", "Captura", "Interrupción"}
    tipos = [n.replace(" del Vacío", "") for _, n in avisos_mundo.TIPOS_FISURA]
    for i in range(0, len(tipos), 3):
        det.capa.addLayout(fila(*[etiqueta(t, P["oro"] if t in marcados else P["tenue"], 10, relleno=t in marcados) for t in tipos[i:i + 3]],
                                None, espacio=5))
    det.capa.addWidget(mayus("Eras (ninguna = todas)", 11, P["oro"], 600, 1.5))
    det.capa.addLayout(fila(*[etiqueta(e, ERA[e], 10, relleno=e in ("Neo", "Axi")) for e in ERA], None, espacio=5))
    det.capa.addWidget(mayus("Dificultad", 11, P["oro"], 600, 1.5))
    det.capa.addLayout(fila(Boton("Normal o Acero", primario=True, tam=9), Boton("Solo normales", tam=9), Boton("Solo Acero", tam=9), None, espacio=5))
    det.capa.addLayout(fila(suave("Solo de las facciones elegidas en el filtro", 12), None, Interruptor(False), espacio=6))
    det.capa.addWidget(separador())
    det.capa.addWidget(mayus("Invasiones cuya recompensa diga", 11, P["oro"], 600, 1.5))
    campo = panel(remate=False, fondo=P["panel2"], borde=P["oro_tenue"], margen=(10, 4, 10, 4))
    campo.capa.addWidget(texto("Orokin, Forma, Exilus", 13))
    det.capa.addWidget(campo)
    det.capa.addWidget(mayus("Arbitrajes de estos tipos (ninguno = todos)", 11, P["oro"], 600, 1.5))
    arb = [n for _, n in avisos_mundo.TIPOS_ARBITRAJE]
    for i in range(0, len(arb), 4):
        det.capa.addLayout(fila(*[etiqueta(t, P["tenue"], 10) for t in arb[i:i + 4]], None, espacio=5))
    det.capa.addStretch(1)
    det.capa.addWidget(Boton("Probar un aviso", "reloj", tam=11))
    principal.addWidget(det, 5)
    return r


# -- 4. HERRAMIENTAS -----------------------------------------------------------------------

SUB_HERR = [("build", "Build"), ("agrietados", "Agrietados"), ("video", "Vídeo"), ("web", "Web")]


def herramientas_agrietados() -> QWidget:
    from farmadex.agrietados import grados
    from farmadex.ui.pestana_agrietados import puntos_disposicion

    der = fila(Boton("Leer la tarjeta bajo el cursor", "buscar", primario=True, tam=11), 8, tecla("Ctrl+Alt+G"), espacio=0)
    r, capa, cuerpo = pagina("herramientas", SUB_HERR, "agrietados", der)
    disp = 1.25  # Braton Prime (omegaAttenuation del indice)
    # Un agrietado de ejemplo: 3 positivas y 1 negativa, con valores dentro de lo posible.
    base = [("critical_chance", +5.9, False), ("critical_damage", +8.0, False), ("multishot", -1.0, False), ("zoom", -5.1, True)]
    estad = []
    for slug, desv, neg in base:
        lo, hi = grados.rango(slug, "rifle", disp, 3, 1, neg)
        centro = (lo + hi) / 2
        estad.append((slug, round(centro * (1 + desv / 100), 1), neg))
    ev = grados.evaluar(estad, "rifle", disp)

    principal = fila(espacio=16)
    cuerpo.addLayout(principal, 1)
    izq = QVBoxLayout()
    izq.setSpacing(12)
    principal.addLayout(izq, 4)
    form = panel("El agrietado", margen=(20, 12, 20, 14), espacio=8)
    arma = panel(remate=False, fondo=P["panel2"], borde=P["oro_tenue"], margen=(12, 4, 12, 4))
    arma.capa.addLayout(fila(texto("Braton Prime", 15, P["texto"], 600), None, icono("abajo", 12, P["oro"]), espacio=6))
    form.capa.addLayout(fila(mayus("Arma", 11, P["suave"], 600, 1.5), 8, arma, espacio=0))
    n = puntos_disposicion(disp).count("●")
    form.capa.addLayout(fila(mayus("Disposición", 11, P["suave"], 600, 1.5), 8, Puntos(n), valor("×1,25", 13, P["oro"]), None, espacio=8))
    form.capa.addWidget(separador())
    cab = fila(mayus("Estadística", 10, P["suave"], 600, 1.2), None, mayus("Valor", 10, P["suave"], 600, 1.2), 30,
               mayus("Negativa", 10, P["suave"], 600, 1.2), espacio=0)
    form.capa.addLayout(cab)
    for e in ev:
        a = e.atributo
        campo = panel(remate=False, fondo=P["panel2"], borde=P["borde"], margen=(10, 3, 10, 3))
        campo.capa.addWidget(texto(a.nombre_es, 13))
        v = panel(remate=False, fondo=P["panel2"], borde=P["borde"], margen=(10, 3, 10, 3))
        v.setFixedWidth(88)
        v.capa.addWidget(valor(grados.formatear_valor(e.slug, e.valor).replace(".", ","), 13))
        form.capa.addLayout(fila(campo, v, 18, _casilla(e.negativo), 16, espacio=6))
    form.capa.addLayout(fila(mayus("Maestría", 11, P["suave"], 600, 1.5), valor("12", 13), 16,
                             mayus("Veces variado", 11, P["suave"], 600, 1.5), valor("7", 13), None, espacio=8))
    form.capa.addLayout(fila(None, Boton("Limpiar", tam=11), Boton("Evaluar", primario=True, tam=11), espacio=8))
    izq.addWidget(form)
    izq.addStretch(1)

    der_c = QVBoxLayout()
    der_c.setSpacing(12)
    principal.addLayout(der_c, 6)
    tabla = panel("Qué tal ha salido", margen=(20, 12, 20, 14), espacio=8)
    cab = fila(espacio=10)
    for t, w in (("Estadística", 190), ("Valor", 80), ("Puede salir entre", 150), ("", 0), ("Grado", 60)):
        e = mayus(t, 10, P["suave"], 600, 1.2)
        if w:
            e.setFixedWidth(w)
        cab.addWidget(e, 0 if w else 1)
    tabla.capa.addLayout(cab)
    tabla.capa.addWidget(separador())
    for e in ev:
        col = grados.COLOR_GRADO.get(e.grado, P["suave"])
        fl = fila(espacio=10)
        n1 = texto(e.atributo.nombre_es + (" (negativa)" if e.negativo else ""), 14, P["texto"], 600)
        n1.setFixedWidth(190)
        n2 = valor(grados.formatear_valor(e.slug, e.valor).replace(".", ","), 14)
        n2.setFixedWidth(80)
        lo, hi = sorted((e.minimo, e.maximo), key=abs)
        n3 = suave(f"{grados.formatear_valor(e.slug, lo)} a {grados.formatear_valor(e.slug, hi)}".replace(".", ","), 13)
        n3.setFixedWidth(150)
        fl.addWidget(n1)
        fl.addWidget(n2)
        fl.addWidget(n3)
        fl.addWidget(Barra(e.posicion or 0, col, 6), 1)
        g = mayus(e.grado or "?", 20, col, 700, 1)
        g.setFixedWidth(60)
        g.setAlignment(Qt.AlignCenter)
        fl.addWidget(g)
        tabla.capa.addLayout(fl)
    tabla.capa.addWidget(separador())
    escala = fila(suave("De peor a mejor:", 12), espacio=6)
    for letra in ("F", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+", "S"):
        escala.addWidget(lbl(letra, 12, grados.COLOR_GRADO[letra], 700))
    escala.addStretch(1)
    tabla.capa.addLayout(escala)
    der_c.addWidget(tabla)
    ver = panel("Veredicto", margen=(20, 12, 20, 14), espacio=6)
    ver.capa.addWidget(texto("Buen agrietado: el crítico ha salido alto y la negativa (zoom) casi no molesta.", 15, P["texto"], 600, True))
    ver.capa.addWidget(suave("Merece la pena quedárselo. Si lo vendes, pide al menos lo que piden por los parecidos.", 13, True))
    ver.capa.addLayout(fila(Boton("Consultar precio", "tienda", tam=11), suave("Mira las subastas de warframe.market y la media de la semana.", 12), None, espacio=10))
    der_c.addWidget(ver)
    pre = panel("Precio de agrietados parecidos", remate=False, margen=(20, 12, 20, 12), espacio=5)
    for k, v in (("Subastas en warframe.market", "14 · desde 180 platino"), ("Media de la semana (DE)", "95 platino"),
                 ("Con las mismas positivas", "3 · desde 260 platino")):
        pre.capa.addLayout(fila(suave(k, 13), None, valor(v, 13, P["turquesa"]), espacio=6))
    pre.capa.addWidget(lbl("Consultado hace 2 min", 11, P["tenue"]))
    der_c.addWidget(pre)
    der_c.addStretch(1)
    cuerpo.addWidget(lbl("Abre el agrietado en el juego, pon el ratón encima y pulsa Ctrl+Alt+G: se rellena solo. También puedes escribirlo a mano.", 12, P["tenue"]))
    return r


def herramientas_build() -> QWidget:
    c = con()
    der = fila(Boton("Leer la pantalla de mejoras", "buscar", primario=True, tam=11), 8, tecla("Ctrl+Alt+B"), espacio=0)
    r, capa, cuerpo = pagina("herramientas", SUB_HERR, "build", der)

    def item(nombre_en: str):
        f = c.execute("SELECT nombre_es, nombre_en, imagen FROM items WHERE nombre_en=? ORDER BY padre_id IS NOT NULL LIMIT 1", (nombre_en,)).fetchone()
        return (f[0] or f[1], f[2]) if f else (nombre_en, None)

    principal = fila(espacio=16)
    cuerpo.addLayout(principal, 1)
    izq = QVBoxLayout()
    izq.setSpacing(12)
    principal.addLayout(izq, 4)
    eq = panel("Equipo", margen=(20, 12, 20, 14), espacio=6)
    eq.capa.addLayout(fila(None, Pedestal("CitrinePrime.png", 200), None))
    eq.capa.addWidget(_c(mayus("Citrine Prime", 24, P["texto"], 600, 3)))
    eq.capa.addWidget(_c(suave("Leído de Arsenal › Mejorar hace un momento", 12)))
    eq.capa.addLayout(fila(None, Boton("Builds en Overframe", "build", tam=11), Boton("Abrir ficha", "derecha", tam=11), None, espacio=8))
    izq.addWidget(eq)
    como = panel("Cómo se usa", remate=False, margen=(20, 12, 20, 12), espacio=4)
    for t in ("En el juego, entra en Arsenal › Mejorar con la build que quieras.",
              "Pulsa Ctrl+Alt+B: Farmadex lee los mods de la pantalla.",
              "Pulsa cualquier mod para ver su ficha y dónde conseguirlo."):
        como.capa.addWidget(suave(t, 12, True))
    izq.addWidget(como)
    izq.addStretch(1)

    der_c = QVBoxLayout()
    der_c.setSpacing(12)
    principal.addLayout(der_c, 7)
    mods = panel("Mods equipados", margen=(20, 12, 20, 14), espacio=8)
    lista = ["Umbral Vitality", "Primed Continuity", "Intensify", "Stretch", "Flow", "Adaptation", "Steel Fiber", "Transient Fortitude"]
    for i in range(0, 8, 4):
        fl = fila(espacio=10)
        for nom in lista[i:i + 4]:
            es, img = item(nom)
            carta = panel(remate=False, fondo=P["panel2"], borde=P["borde"], margen=(8, 8, 8, 8), espacio=3)
            carta.capa.addLayout(fila(None, img_o_rombo(img, 54), None))
            t = texto(es, 12, P["texto"], 600, True)
            t.setAlignment(Qt.AlignCenter)
            carta.capa.addWidget(t)
            carta.capa.addLayout(fila(None, chip_tipo("mod", 9), None))
            fl.addWidget(carta, 1)
        mods.capa.addLayout(fl)
    der_c.addWidget(mods)
    fila_b = fila(espacio=12)
    arc = panel("Arcanos", remate=False, margen=(20, 12, 20, 12), espacio=6)
    for nom in ("Arcane Grace", "Arcane Energize"):
        es, img = item(nom)
        arc.capa.addLayout(fila(img_o_rombo(img, 30), texto(es, 13, P["texto"], 600), None, chip_tipo("arcano", 9), espacio=8))
    fila_b.addWidget(arc, 1)
    col = panel("En la colección (abajo)", remate=False, margen=(20, 12, 20, 12), espacio=6)
    for nom in ("Vitality", "Continuity"):
        es, img = item(nom)
        col.capa.addLayout(fila(img_o_rombo(img, 30), texto(es, 13, P["texto"], 600), None, espacio=8))
    fila_b.addWidget(col, 1)
    rara = panel("Leído sin reconocer", remate=False, margen=(20, 12, 20, 12), espacio=6)
    rara.capa.addLayout(fila(texto("Fortaleza trans…", 13, P["suave"]), None, lbl("parecido 82 %", 12, P["aviso"]), espacio=8))
    rara.capa.addWidget(suave("Pulsa para elegir el bueno.", 12))
    fila_b.addWidget(rara, 1)
    der_c.addLayout(fila_b)
    der_c.addStretch(1)
    return r


# -- 5. AJUSTES ----------------------------------------------------------------------------


def ajustes_apariencia() -> QWidget:
    from farmadex.ui.widgets import CATEGORIAS_COLOR, TEMAS

    r, capa, cuerpo = pagina("ajustes", margen=(30, 14, 30, 14))
    principal = fila(espacio=16)
    cuerpo.addLayout(principal, 1)
    menu = panel(margen=(14, 16, 14, 14), espacio=4)
    menu.setFixedWidth(230)
    for clave, t, ico in (("general", "General", "ajustes"), ("atajos", "Atajos", "juego"), ("apariencia", "Apariencia", "sol"),
                          ("reliquias", "Reliquias", "reliquia"), ("datos", "Datos del juego", "reloj"), ("ayuda", "Ayuda", "info")):
        on = clave == "apariencia"
        item = QFrame()
        item.setObjectName("mi")
        item.setStyleSheet(f"QFrame#mi {{ background: {'rgba(212,176,106,30)' if on else 'transparent'};"
                           f" border-left: 3px solid {P['oro'] if on else 'transparent'}; }}")
        item.setLayout(fila(icono(ico, 15, P["oro"] if on else P["suave"]), mayus(t, 13, P["oro"] if on else P["suave"], 600, 1.5),
                            None, margen=(10, 7, 8, 7), espacio=8))
        menu.capa.addWidget(item)
    menu.capa.addStretch(1)
    menu.capa.addWidget(separador())
    menu.capa.addWidget(lbl("Acerca de Farmadex", 12, P["oro"], 600))
    menu.capa.addWidget(lbl("Salir de Farmadex", 12, P["aviso"], 600))
    menu.capa.addSpacing(4)
    menu.capa.addWidget(lbl("Datos de WFCD y Digital Extremes", 11, P["tenue"]))
    menu.capa.addWidget(lbl("Creado por vaas · twitch.tv/vaas1897", 11, P["tenue"]))
    menu.capa.addWidget(lbl("Farmadex 0.5.1", 11, P["tenue"]))
    principal.addWidget(menu)

    medio = QVBoxLayout()
    medio.setSpacing(12)
    principal.addLayout(medio, 6)
    tema = panel("Tema", margen=(20, 12, 20, 14), espacio=8)
    fl = fila(espacio=10)
    for clave, tm in TEMAS.items():
        on = clave == "orokin"
        carta = panel(remate=on, fondo=tm["panel"], borde=tm["acento"] if on else P["borde"], margen=(12, 8, 12, 8), espacio=4)
        carta.capa.addLayout(fila(*[Muestra(tm[k], 16) for k in ("fondo", "panel2", "acento", "texto")], None, espacio=4))
        carta.capa.addWidget(lbl(tm["titulo"].replace("Vacio", "Vacío"), 12, tm["texto"], 600))
        fl.addWidget(carta, 1)
    tema.capa.addLayout(fl)
    tema.capa.addLayout(fila(texto("Opacidad del fondo", 13), None, Deslizador(0.84, 240), valor("92 %", 13, P["oro"]), espacio=10))
    medio.addWidget(tema)
    pers = panel("Tamaño", margen=(20, 12, 20, 14), espacio=10)
    for nombre, opciones, activa in (("Tamaño de la interfaz", ("Compacta", "Normal", "Grande", "Muy grande"), "Normal"),
                                     ("Tamaño de letra", ("Pequeña", "Normal", "Grande", "Muy grande", "Enorme"), "Grande")):
        n = texto(nombre, 13)
        n.setFixedWidth(160)
        pers.capa.addLayout(fila(n, *[Boton(o, primario=o == activa, tam=10) for o in opciones], None, espacio=6))
    medio.addWidget(pers)
    cols = panel("Colores", margen=(20, 12, 20, 14), espacio=6)
    rej = QHBoxLayout()
    rej.setSpacing(20)
    base = TEMAS["orokin"]
    cambiado = {"acento": "#d4b06a"}
    mitad = (len(CATEGORIAS_COLOR) + 1) // 2
    for trozo in (CATEGORIAS_COLOR[:mitad], CATEGORIAS_COLOR[mitad:]):
        col = QVBoxLayout()
        col.setSpacing(5)
        for clave, nombre, _ayuda in trozo:
            nom = nombre.replace("boton", "botón")
            col.addLayout(fila(Muestra(cambiado.get(clave, base[clave]), 20, clave in cambiado), texto(nom, 12), None,
                               icono("", 12, P["oro"] if clave in cambiado else P["tenue"]), espacio=8))
        col.addStretch(1)
        rej.addLayout(col, 1)
    cols.capa.addLayout(rej)
    cols.capa.addLayout(fila(suave("Pulsa un color para cambiarlo · la flecha lo devuelve al del tema", 11), None,
                             Boton("Volver a lo de fábrica", tam=10), espacio=8))
    medio.addWidget(cols)
    medio.addStretch(1)

    der_c = QVBoxLayout()
    der_c.setSpacing(12)
    principal.addLayout(der_c, 4)
    vista = panel("Vista previa", margen=(18, 12, 18, 14), espacio=8)
    mini = panel(fondo=P["fondo"], borde=P["oro_tenue"], margen=(14, 10, 14, 12), espacio=6)
    mini.capa.addLayout(fila(_rombo(10, P["oro"], False), mayus("Farmadex", 14, P["oro"], 600, 3), None, espacio=6))
    mini.capa.addWidget(Filete())
    res = panel(remate=False, fondo=P["panel2"], borde=P["borde"], margen=(10, 6, 10, 6))
    res.capa.addLayout(fila(imagen("CitrinePrime.png", 30), columna(texto("Chasis de Citrine Prime", 13, P["texto"], 600),
                                                                   suave("Neo C11 · Captura en Ukko", 11), espacio=0), None, espacio=8))
    mini.capa.addWidget(res)
    mini.capa.addLayout(fila(Boton("Añadir", "mas", primario=True, tam=10), Boton("Wiki", "web", tam=10), None, espacio=6))
    mini.capa.addWidget(lbl("Datos del juego antiguos", 12, P["aviso"], 600))
    mini.capa.addWidget(lbl("Se puede farmear", 12, P["ok"], 600))
    vista.capa.addWidget(mini)
    vista.capa.addWidget(lbl("Hay cambios sin guardar.", 12, P["aviso"]))
    vista.capa.addLayout(fila(Boton("Guardar", primario=True, tam=11), Boton("Descartar", tam=11), None, espacio=8))
    der_c.addWidget(vista)
    der_c.addStretch(1)
    return r


# -- 6. RELIQUIAS EN EL JUEGO --------------------------------------------------------------


# Colores de rareza del juego (farmadex.ui.widgets.RAREZA) y geometria de la escena.
RAREZA_JUEGO = {"Common": "#d0956a", "Uncommon": "#cfd6e0", "Rare": "#f5cd4f", "Legendary": "#d9a6ff"}
Y_TARJETAS = 150
ALTO_TARJETA = 250


class FondoRecompensas(QWidget):
    """Imita la pantalla de recompensas de una fisura: fondo del Vacio y cuatro tarjetas."""

    def __init__(self, recompensas):
        super().__init__()
        self.setFixedSize(1280, 800)
        self._rec = recompensas

    def paintEvent(self, _):  # noqa: N802
        from PySide6.QtGui import QFont, QPixmap

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor("#1a1422"))
        g.setColorAt(1, QColor("#08070d"))
        p.fillRect(self.rect(), g)
        for (x, y, rr, c) in ((0.5, 0.35, 0.55, "#6a3fa0"), (0.15, 0.9, 0.4, "#2a4a6a"), (0.85, 0.1, 0.35, "#a07040")):
            rg = QRadialGradient(QPointF(w * x, h * y), max(w, h) * rr)
            col = QColor(c)
            col.setAlpha(110)
            rg.setColorAt(0, col)
            col.setAlpha(0)
            rg.setColorAt(1, col)
            p.fillRect(self.rect(), rg)
        # Texto superior generico y cuenta atras.
        f = QFont(TITULAR)
        f.setPixelSize(24)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 6)
        p.setFont(f)
        p.setPen(QColor(235, 230, 240, 200))
        p.drawText(QRectF(0, 40, w, 40), Qt.AlignCenter, "ELIGE TU RECOMPENSA")
        p.setPen(QPen(QColor(235, 230, 240, 160), 2))
        p.drawEllipse(QRectF(w / 2 - 22, 92, 44, 44))
        f.setPixelSize(18)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0)
        p.setFont(f)
        p.drawText(QRectF(w / 2 - 22, 92, 44, 44), Qt.AlignCenter, "11")
        # Tarjetas del juego: recuadros oscuros con imagen, nombre y, al pie, el brillo de la
        # rareza (bronce, plata, oro), que es lo que el panel de Farmadex no debe tapar.
        ancho, alto, hueco = 250, 250, 24
        x0 = (w - (4 * ancho + 3 * hueco)) / 2
        y0 = Y_TARJETAS
        f2 = QFont("Segoe UI")
        f2.setPixelSize(15)
        for i, rcp in enumerate(self._rec):
            x = x0 + i * (ancho + hueco)
            rect = QRectF(x, y0, ancho, alto)
            p.fillRect(rect, QColor(10, 10, 16, 190))
            p.setPen(QPen(QColor(200, 190, 220, 90), 1))
            p.drawRect(rect)
            p.setPen(QColor(240, 238, 245))
            p.setFont(f2)
            rareza = QColor(RAREZA_JUEGO.get(rcp["rareza"], "#d0956a"))
            brillo = QLinearGradient(0, y0 + alto - 90, 0, y0 + alto)
            c0 = QColor(rareza)
            c0.setAlpha(0)
            c1 = QColor(rareza)
            c1.setAlpha(95)
            brillo.setColorAt(0, c0)
            brillo.setColorAt(1, c1)
            p.fillRect(QRectF(x + 1, y0 + alto - 90, ancho - 2, 89), brillo)
            p.fillRect(QRectF(x, y0 + alto - 4, ancho, 4), rareza)
            p.setPen(QColor(240, 238, 245))
            p.drawText(QRectF(x + 10, y0 + alto - 70, ancho - 20, 54), Qt.AlignHCenter | Qt.TextWordWrap, rcp["nombre"].upper())
            ruta = Path(comun.os.environ["FARMADEX_DATOS"]) / "Farmadex" / "datos" / "img" / (rcp["imagen"] or "-")
            if ruta.exists():
                mapa = QPixmap(str(ruta)).scaled(130, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                p.drawPixmap(int(x + (ancho - mapa.width()) / 2), int(y0 + 30), mapa)
        p.end()


def reliquias() -> QWidget:
    from PySide6.QtWidgets import QGraphicsOpacityEffect

    from farmadex.datos import relaciones

    c = con()
    rid = c.execute("SELECT id FROM items WHERE nombre_en='Lith S19 Relic'").fetchone()[0]
    cont = {(x["padre_es"], x["nombre_es"]): x for x in relaciones.contenido_de(c, rid)}

    def img(item_id):
        f = c.execute("SELECT imagen FROM items WHERE id=?", (item_id,)).fetchone()
        return f and f[0]

    elegidas = [("Citrine Prime", "Sistemas"), ("Sarofang Prime", "Hoja"), ("Braton Prime", "Cañón"), ("Bronco Prime", "Receptor")]
    datos = []
    for padre, pieza in elegidas:
        x = cont[(padre, pieza)]
        datos.append({"nombre": f"{pieza} de {padre}", "imagen": img(x["item_id"]), "rareza": x["rareza"]})
    motivos = [
        ("Te falta", "#8fd08a", True, ["Objetivo: Set de Citrine Prime", "8 platino (venta más barata)", "45 ducados"]),
        ("45 platino", "#6aa8ff", False, ["45 platino (mediana)", "100 ducados", "No lo tienes"]),
        ("Completa set 3/4", "#58d3c0", False, ["Tienes Plano y Culata", "5 platino (venta más barata)", "15 ducados"]),
        ("15 ducados", "#f0b04a", False, ["2 platino (venta más barata)", "15 ducados", "Tienes 3"]),
    ]
    fondo = FondoRecompensas(datos)
    ancho, hueco = 250, 24
    x0 = (1280 - (4 * ancho + 3 * hueco)) // 2
    hud = QWidget(fondo)
    hud.setStyleSheet("background: transparent;")
    # Como en panel_recompensas.py: el panel empieza bajo la tarjeta del juego dejando un
    # hueco proporcional a la pantalla (HUECO_RAREZA) para que se vea el color de rareza.
    from farmadex.ui.panel_recompensas import HUECO_RAREZA

    base_nombre = Y_TARJETAS + ALTO_TARJETA - 16
    y_panel = base_nombre + max(30, round(800 * HUECO_RAREZA))
    hud.setGeometry(x0, y_panel, 4 * ancho + 3 * hueco, 230)
    h = QVBoxLayout(hud)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    fl = fila(espacio=hueco)
    for d, (motivo, col, mejor, lineas) in zip(datos, motivos):
        pn = Panel(remate=mejor, fondo="#0d1213", borde=P["oro"] if mejor else P["borde"])
        pn.setFixedWidth(ancho)
        pn.capa.setContentsMargins(1, 1, 1, 10)
        pn.capa.setSpacing(4)
        cinta = QFrame()
        cinta.setObjectName("cinta")
        cq = QColor(col)
        cinta.setStyleSheet(f"QFrame#cinta {{ background: rgba({cq.red()},{cq.green()},{cq.blue()},{235 if mejor else 150}); }}")
        cinta.setFixedHeight(40 if mejor else 32)
        cinta.setLayout(fila(None, mayus(("★  " if mejor else "") + motivo, 15 if mejor else 13, "#0b0d0e", 700, 1.5), None, margen=(8, 0, 8, 0)))
        pn.capa.addWidget(cinta)
        cuerpo = columna(espacio=3, margen=(14, 4, 14, 0))
        cuerpo.addWidget(mayus("Mejor opción" if mejor else " ", 11, P["oro"], 600, 2))
        cuerpo.addWidget(texto(d["nombre"], 15, P["texto"] if mejor else P["suave"], 600, True))
        for i, t in enumerate(lineas):
            cuerpo.addWidget(lbl(t, 12, (P["turquesa"] if i == 0 and mejor else P["suave"])))
        pn.capa.addLayout(cuerpo)
        pn.capa.addStretch(1)
        if not mejor:
            efecto = QGraphicsOpacityEffect(pn)
            efecto.setOpacity(0.8)
            pn.setGraphicsEffect(efecto)
        fl.addWidget(pn)
    h.addLayout(fl, 1)
    pie = Panel(remate=False, fondo="#0d1213", borde=P["borde"])
    pie.capa.setContentsMargins(14, 5, 14, 5)
    pie.capa.addLayout(fila(_rombo(8, P["oro"], False), mayus("Farmadex", 11, P["oro"], 600, 2.5), 12,
                            suave("Total en pantalla: 60 platino (4 de 4 con precio)", 12), None,
                            suave("Destacar:", 12), lbl("Lo que me falta", 12, P["oro"], 600),
                            lbl("· Más platino · Más ducados · Equilibrado", 12, P["tenue"]), espacio=6))
    h.addWidget(pie)
    return fondo


# -- 7. BIENVENIDA ----------------------------------------------------------------------------


class Atenuado(QWidget):
    def __init__(self, fondo):
        super().__init__()
        self.setFixedSize(1280, 800)
        self._f = fondo

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.drawPixmap(0, 0, self._f)
        p.fillRect(self.rect(), QColor(4, 6, 7, 205))
        p.end()


def bienvenida() -> QWidget:
    import propuesta_c

    base = propuesta_c.inicio(comun.cargar())
    base.show()
    QApplication.processEvents()
    fondo = Atenuado(base.grab())
    base.close()
    capa = QVBoxLayout(fondo)
    capa.setContentsMargins(170, 120, 170, 120)
    tarjeta = Panel(fondo=P["fondo"], borde=P["oro"])
    tarjeta.capa.setContentsMargins(34, 24, 34, 22)
    tarjeta.capa.setSpacing(12)
    capa.addWidget(tarjeta)
    tarjeta.capa.addLayout(fila(_rombo(18, P["oro"], False), mayus("Bienvenido a Farmadex", 28, P["oro"], 600, 4), None, espacio=12))
    tarjeta.capa.addWidget(suave("Un momento antes de empezar: esto es lo que conviene saber.", 15))
    tarjeta.capa.addWidget(Filete())
    cuerpo = fila(espacio=24)
    tarjeta.capa.addLayout(cuerpo, 1)
    indice_ = QVBoxLayout()
    indice_.setSpacing(6)
    for i, t in enumerate(("Qué es Farmadex", "Lo básico, paso a paso", "¿Es seguro?", "Preguntas frecuentes", "Gracias")):
        on = i == 1
        hecho = i < 1
        item = QFrame()
        item.setObjectName("ix")
        item.setStyleSheet(f"QFrame#ix {{ background: {'rgba(212,176,106,30)' if on else 'transparent'};"
                           f" border-left: 3px solid {P['oro'] if on else 'transparent'}; }}")
        item.setLayout(fila(_rombo(9, P["oro"] if (on or hecho) else P["tenue"], hecho or on),
                            mayus(t, 12, P["oro"] if on else (P["texto"] if hecho else P["suave"]), 600, 1.2),
                            None, margen=(10, 8, 8, 8), espacio=8))
        indice_.addWidget(item)
    indice_.addStretch(1)
    w_ind = QWidget()
    w_ind.setLayout(indice_)
    w_ind.setFixedWidth(250)
    cuerpo.addWidget(w_ind)
    pasos = QVBoxLayout()
    pasos.setSpacing(8)
    pasos.addWidget(mayus("Lo básico, paso a paso", 18, P["texto"], 600, 2))
    textos = (
        ("Ábrelo encima del juego con", "Ctrl+Alt+W", "y escóndelo con Escape."),
        ("Pon Warframe en", None, "Ventana sin bordes (Opciones › Pantalla)."),
        ("En Buscar escribe lo que sea,", None, "aunque sea con faltas."),
        ("Pulsa", "+", "para apuntarlo en Mis metas."),
        ("Al abrir una reliquia,", None, "te marca la recompensa que más te conviene."),
        ("En Mundo:", None, "fisuras, Baro, invasiones… y avisos si quieres."),
        ("En Herramientas:", None, "lee tu build y mira si un agrietado es bueno."),
        ("En Ajustes:", None, "atajos, colores y tamaño de letra."),
    )
    for n, (a, k, b) in enumerate(textos, 1):
        num = mayus(str(n), 15, P["oro"], 700, 0)
        num.setFixedWidth(22)
        partes = [num, texto(a, 14, P["texto"], 600)]
        if k:
            partes.append(tecla(k))
        partes.append(suave(b, 14))
        pasos.addLayout(fila(*partes, None, espacio=8))
    pasos.addStretch(1)
    fin = panel(remate=False, fondo=P["panel2"], borde=P["borde"], margen=(16, 10, 16, 10), espacio=6)
    fin.capa.addWidget(suave("Al final eliges cómo empezar. El recorrido señala cada parte de la ventana, paso a paso.", 12, True))
    fin.capa.addLayout(fila(Boton("Empezar con el recorrido", "derecha", tam=10), Boton("Empezar sin recorrido", tam=10), None, espacio=8))
    pasos.addWidget(fin)
    cuerpo.addLayout(pasos, 1)
    tarjeta.capa.addWidget(Filete())
    tarjeta.capa.addLayout(fila(suave("Puedes volver a verla en Ajustes › Ayuda.", 12), None, Boton("Atrás", "atras", tam=11),
                                mayus("2 de 5", 13, P["suave"], 600, 1.5), Boton("Siguiente", "derecha", primario=True, tam=11),
                                espacio=12))
    return fondo


PANTALLAS = {
    "buscar": buscar_mision, "buscar_arma": buscar_arma,
    "metas_objetivos": metas_objetivos, "metas_primes": metas_primes, "metas_perfil": metas_perfil,
    "mundo": mundo, "mundo_avisos": mundo_avisos,
    "herramientas": herramientas_agrietados, "herramientas_build": herramientas_build,
    "ajustes": ajustes_apariencia, "reliquias": reliquias, "bienvenida": bienvenida,
}


def main(nombres: list[str]) -> None:
    app = QApplication.instance() or QApplication([])
    DESTINO.mkdir(parents=True, exist_ok=True)
    for n in nombres or list(PANTALLAS):
        w = PANTALLAS[n]()
        w.show()
        QApplication.processEvents()
        ruta = DESTINO / f"C_{n}.png"
        w.grab().save(str(ruta))
        print(ruta, w.width(), "x", w.height())
        w.close()
    app.quit()


if __name__ == "__main__":
    main(sys.argv[1:])
