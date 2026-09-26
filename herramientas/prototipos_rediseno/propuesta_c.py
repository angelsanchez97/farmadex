"""Propuesta C - "Menu del juego": estetica Orokin, menu superior grande y overlay como HUD.

La idea: que Farmadex se sienta parte del juego. Cabecera con un menu en mayusculas como el
de la nave, paneles con esquinas cortadas y filete dorado, un tablero de estado al abrir y
una ficha tipo "inspeccionar objeto" del arsenal. En partida no hay ventana: hay dos o tres
tarjetas pequenas flotando (siguiente pieza, fisura util) que se leen de un vistazo, y el
buscador sale con la tecla. Sin logos ni arte de DE: solo formas y colores propios.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from comun import T_NORMAL, T_PEQUENO, columna, fila, hoja, icono, imagen, lbl, minutos_txt, plural, ruta_chaflan

P = {
    "fondo": "#090c0d", "panel_opaco": "#101617", "panel2": "#172022", "borde": "#3b3627",
    "texto": "#ece3cc", "suave": "#9a927e", "tenue": "#6b6555", "oro": "#d4b06a", "oro_tenue": "#8a7442",
    "turquesa": "#58d3c0", "aviso": "#f0a63c", "ok": "#8fd08a", "acento_texto": "#151008",
}
TITULAR = "Bahnschrift"


def mayus(texto: str, tam: int, color: str | None = None, peso: int = 600, espaciado: float = 2.0) -> QWidget:
    e = lbl(texto.upper(), tam, color or P["texto"], peso, espaciado=espaciado, familia=TITULAR)
    # Sin este margen, la tilde de las mayusculas (CÓMO) se corta en Bahnschrift.
    e.setStyleSheet(e.styleSheet() + f" padding-top: {max(2, tam // 5)}px;")
    return e


class Panel(QFrame):
    """Panel con dos esquinas cortadas, filete fino y un remate dorado en la esquina."""

    def __init__(self, titulo: str | None = None, remate: bool = True, fondo: str | None = None, borde: str | None = None):
        super().__init__()
        self._remate = remate
        self._fondo = QColor(fondo or P["panel_opaco"])
        self._borde = QColor(borde or P["borde"])
        self.capa = QVBoxLayout(self)
        self.capa.setContentsMargins(20, 14, 20, 16)
        self.capa.setSpacing(10)
        if titulo:
            self.capa.addLayout(fila(_rombo(8, P["oro"]), mayus(titulo, 13, P["oro"], 600, 2.5), None, espacio=8))

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        camino = ruta_chaflan(r, 14)
        p.fillPath(camino, self._fondo)
        p.setPen(QPen(self._borde, 1))
        p.drawPath(camino)
        if self._remate:
            p.setPen(QPen(QColor(P["oro"]), 2))
            p.drawLine(QPointF(r.left() + 14, r.top() + 1), QPointF(r.left() + 60, r.top() + 1))
            p.drawLine(QPointF(r.right() - 60, r.bottom() - 1), QPointF(r.right() - 14, r.bottom() - 1))
        p.end()


class Rombo(QWidget):
    def __init__(self, lado: int, color: str, relleno: bool = True):
        super().__init__()
        self.setFixedSize(lado + 2, lado + 2)
        self._c, self._r = QColor(color), relleno

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width() - 1, self.height() - 1
        pol = QPolygonF([QPointF(w / 2, 0.5), QPointF(w, h / 2), QPointF(w / 2, h), QPointF(0.5, h / 2)])
        p.setPen(QPen(self._c, 1.2))
        p.setBrush(self._c if self._r else Qt.NoBrush)
        p.drawPolygon(pol)
        p.end()


def _rombo(lado: int, color: str, relleno: bool = True) -> Rombo:
    return Rombo(lado, color, relleno)


class Filete(QWidget):
    """Linea dorada con un rombo en el centro, como separador de cabecera."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(12)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, y = self.width(), 6
        p.setPen(QPen(QColor(P["oro_tenue"]), 1))
        p.drawLine(0, y, w // 2 - 14, y)
        p.drawLine(w // 2 + 14, y, w, y)
        p.setPen(QPen(QColor(P["oro"]), 1.2))
        p.setBrush(QColor(P["fondo"]))
        p.drawPolygon(QPolygonF([QPointF(w / 2, 1), QPointF(w / 2 + 8, y), QPointF(w / 2, 11), QPointF(w / 2 - 8, y)]))
        p.end()


class Pedestal(QWidget):
    """Circulo de luz tenue detras de la imagen del objeto, como en el arsenal."""

    def __init__(self, nombre_img: str, lado: int):
        super().__init__()
        self.setFixedSize(lado, lado)
        img = imagen(nombre_img, int(lado * 0.78))
        img.setParent(self)
        img.move(int(lado * 0.11), int(lado * 0.08))

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        g = QRadialGradient(QPointF(w / 2, h * 0.55), w * 0.5)
        g.setColorAt(0, QColor(212, 176, 106, 70))
        g.setColorAt(1, QColor(212, 176, 106, 0))
        p.fillRect(self.rect(), g)
        p.setPen(QPen(QColor(P["oro_tenue"]), 1))
        p.drawEllipse(QRectF(w * 0.12, h * 0.86, w * 0.76, h * 0.1))
        p.end()


def _raiz() -> QFrame:
    r = QFrame()
    r.setObjectName("raiz")
    r.setStyleSheet(hoja({**P, "panel": P["panel_opaco"], "acento": P["oro"]}) + f"QFrame#raiz {{ background: {P['fondo']}; }}")
    r.setFixedSize(1280, 800)
    return r


def _cabecera(activa: str) -> QVBoxLayout:
    menu = []
    for clave, texto in (("inicio", "Tablero"), ("buscar", "Buscar"), ("metas", "Mis metas"), ("mundo", "Mundo"),
                         ("herramientas", "Herramientas"), ("ajustes", "Ajustes")):
        on = clave == activa
        item = QWidget()
        item.setLayout(columna(
            fila(None, _rombo(6, P["oro"] if on else P["fondo"]), None),
            mayus(texto, 15, P["oro"] if on else P["suave"], 600 if on else 500, 2.0),
            espacio=4,
        ))
        menu.append(item)
        menu.append(18)
    juego = Panel(remate=False, fondo=P["panel2"], borde=P["oro"])
    juego.capa.setContentsMargins(14, 6, 14, 6)
    juego.setMinimumWidth(236)
    juego.capa.addLayout(fila(icono("juego", 17, P["oro"]), mayus("Modo juego", 13, P["texto"], 600, 1.5),
                              lbl("Ctrl+Alt+W", T_PEQUENO, P["suave"]), espacio=8))
    cab = fila(_rombo(14, P["oro"], False), mayus("Farmadex", 22, P["oro"], 600, 5), 28, *menu, None, juego,
               margen=(30, 18, 30, 8), espacio=10)
    return columna(cab, Filete(), espacio=0)


def _hueco(nombre_img: str | None, texto: str, sub: str, progreso: float, marcado: bool = False, lado: int = 120) -> Panel:
    """Casilla de arsenal: imagen, nombre y barra de progreso."""
    h = Panel(remate=marcado, fondo=P["panel2"], borde=P["oro"] if marcado else P["borde"])
    h.setFixedWidth(lado + 60)
    h.capa.setContentsMargins(10, 10, 10, 10)
    h.capa.setSpacing(4)
    img = imagen(nombre_img, 58)
    h.capa.addLayout(fila(None, img, None))
    n = lbl(texto, 13, P["texto"], 600, envolver=True)
    n.setAlignment(Qt.AlignCenter)
    h.capa.addWidget(n)
    s = lbl(sub, 12, P["suave"])
    s.setAlignment(Qt.AlignCenter)
    h.capa.addWidget(s)
    barra = QFrame()
    barra.setFixedHeight(4)
    lleno = max(0.02, min(1.0, progreso))
    barra.setStyleSheet(
        f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {P['oro']}, stop:{lleno:.2f} {P['oro']},"
        f" stop:{min(1.0, lleno + 0.001):.3f} {P['borde']}, stop:1 {P['borde']});"
    )
    h.capa.addWidget(barra)
    return h


def inicio(d) -> QWidget:
    r = _raiz()
    capa = QVBoxLayout(r)
    capa.setContentsMargins(0, 0, 0, 0)
    capa.setSpacing(0)
    capa.addLayout(_cabecera("inicio"))
    cuerpo = QVBoxLayout()
    cuerpo.setContentsMargins(30, 18, 30, 22)
    cuerpo.setSpacing(16)
    capa.addLayout(cuerpo, 1)
    # Buscador, como una barra de consola del juego.
    b = Panel(remate=False, fondo=P["panel2"], borde=P["oro_tenue"])
    b.capa.setContentsMargins(18, 4, 18, 4)
    caja = QLineEdit()
    caja.setPlaceholderText("Busca un objeto, una reliquia o una misión")
    caja.setStyleSheet(f"background: transparent; border: none; font-size: 18px; font-family: '{TITULAR}'; padding: 10px 4px;")
    b.capa.addLayout(fila(icono("buscar", 19, P["oro"]), caja, lbl("Enter", T_PEQUENO, P["tenue"]), espacio=8))
    cuerpo.addWidget(b)

    arriba = fila(espacio=16)
    # Heroe: tu siguiente paso.
    piezas = [m for m in d.metas if m.reliquia and not m.boveda and m.minutos]
    sig = min(piezas, key=lambda m: m.minutos)
    heroe = Panel("Tu siguiente paso")
    heroe.capa.addLayout(fila(
        Pedestal("CitrinePrime.png", 250),
        columna(
            mayus(sig.nombre, 26, P["texto"], 600, 1.5),
            lbl(f"Reliquia <b style='color:{P['turquesa']}'>{sig.reliquia}</b>", 19, P["suave"]),
            lbl(f"{sig.mision} en <b style='color:{P['texto']}'>{sig.donde}</b>", 16, P["suave"]),
            12,
            fila(mayus(minutos_txt(sig.minutos), 30, P["oro"], 600, 1), lbl("hasta tener la pieza", T_NORMAL, P["suave"]), None, espacio=10),
            lbl(f"Te faltan {plural(len(piezas), 'pieza', 'piezas')} de Citrine Prime para el set", T_NORMAL, P["suave"]),
            14,
            _linea_hito("Ábrela en una fisura " + sig.era,
                        plural(sum(1 for x in d.fisuras if x["era"] == sig.era), "abierta ahora", "abiertas ahora"), P["turquesa"]),
            _linea_hito("Después", next((f"{m.nombre}: {m.reliquia} · {minutos_txt(m.minutos)}" for m in piezas if m is not sig), ""), P["oro"]),
            None, espacio=6,
        ), espacio=20,
    ))
    arriba.addWidget(heroe, 3)
    fis = Panel("Fisuras que te sirven")
    for x in d.fisuras_para_ti[:5]:
        fis.capa.addLayout(fila(
            _rombo(10, P["turquesa"]), mayus(x["era"], 13, P["turquesa"], 600, 1.5), 4,
            columna(lbl(x["nodo"], 15, P["texto"], 600), lbl(f"{x['mision']} · para {x['para']}", 12, P["suave"]), espacio=0),
            None, lbl(x["resta"], 13, P["suave"]), espacio=8,
        ))
    fis.capa.addStretch(1)
    arriba.addWidget(fis, 2)
    cuerpo.addLayout(arriba, 1)

    abajo = fila(espacio=16)
    metas = Panel("Mis metas")
    huecos = [_hueco(m.imagen, m.nombre, f"{m.tengo} de {m.necesito}", m.tengo / m.necesito, i == 1) for i, m in enumerate(d.metas)]
    metas.capa.addLayout(fila(*huecos, None, espacio=12))
    abajo.addWidget(metas, 3)
    ciclos = Panel("Ciclos")
    for c in d.ciclos[:4]:
        noche = c["estado"].lower() in ("noche", "frio", "fass")
        ciclos.capa.addLayout(fila(icono("luna" if noche else "sol", 15, P["turquesa"] if noche else P["oro"]),
                                   lbl(c["nombre"], 14, P["texto"], 600), lbl(c["estado"], 14, P["suave"]), None,
                                   lbl(c["resta"], 13, P["suave"]), espacio=8))
    ciclos.capa.addStretch(1)
    abajo.addWidget(ciclos, 2)
    cuerpo.addLayout(abajo)
    return r


def ficha(d) -> QWidget:
    f = d.ficha
    r = _raiz()
    capa = QVBoxLayout(r)
    capa.setContentsMargins(0, 0, 0, 0)
    capa.setSpacing(0)
    capa.addLayout(_cabecera("buscar"))
    cuerpo = QHBoxLayout()
    cuerpo.setContentsMargins(30, 16, 30, 10)
    cuerpo.setSpacing(24)
    capa.addLayout(cuerpo, 1)
    # Izquierda: el objeto "en la vitrina".
    izq = columna(
        fila(None, Pedestal(f["imagen_padre"], 330), None),
        _centrado(mayus(f["corto"], 18, P["suave"], 500, 4)),
        _centrado(mayus(f["padre"], 36, P["texto"], 600, 3)),
        8,
        fila(None, _etiqueta("Warframe", "#4fc3f7"), _etiqueta("Se puede farmear", P["ok"]),
             _etiqueta(f"{f['ducados']} ducados", P["oro"]), None, espacio=8),
        14, _ahora_en_juego(d, f["era"]),
        None, espacio=4,
    )
    cuerpo.addLayout(izq, 5)
    # Derecha: como conseguirlo, en forma de ruta con hitos.
    der = QVBoxLayout()
    der.setSpacing(14)
    ruta = Panel("Cómo conseguirlo")
    pasos = (
        (f"Consigue la reliquia {f['reliquia']}", f"{f['mision']} en {f['donde']} · unos {minutos_txt(f['min_reliquia'])}"),
        (f"Ábrela en una fisura {f['era']}", f"Refinada a Radiante: {f['prob_radiante']:.0f} % de que salga"),
        ("Elige la pieza al acabar", f"En total, unas {minutos_txt(f['min_pieza'])} con escuadra de {f['escuadra']}"),
    )
    for i, (t, det) in enumerate(pasos, 1):
        ruta.capa.addLayout(fila(
            columna(_rombo(16, P["oro"], i == 1), None, espacio=0),
            columna(fila(mayus(f"Paso {i}", 12, P["oro"], 600, 2), None), lbl(t, 18, P["texto"], 600), lbl(det, T_NORMAL, P["suave"]), espacio=1),
            espacio=14,
        ))
    der.addWidget(ruta)
    datos = Panel("Datos")
    for k, v, c in (("Tiempo hasta la pieza", minutos_txt(f["min_pieza"]), P["oro"]),
                    ("Probabilidad en Radiante", f"{f['prob_radiante']:.0f} %", P["texto"]),
                    ("Otras misiones con la reliquia", f"{len(f['otras'])}", P["texto"]),
                    ("Fisuras " + f["era"] + " abiertas ahora", str(sum(1 for x in d.fisuras if x["era"] == f["era"])), P["turquesa"])):
        datos.capa.addLayout(fila(lbl(k, 15, P["suave"]), None, mayus(v, 17, c, 600, 1)))
    der.addWidget(datos)
    set_ = Panel("El set")
    set_.capa.addLayout(fila(*[_hueco(h["imagen"], h["nombre"], "tú estás aquí" if h["id"] == f["id"] else "", 0.0 if h["id"] != f["id"] else 1.0,
                                      h["id"] == f["id"], lado=70) for h in f["hermanas"]], None, espacio=10))
    der.addWidget(set_)
    der.addStretch(1)
    cuerpo.addLayout(der, 6)
    # Barra de teclas al pie, como en los menus del juego.
    pie = fila(None, _tecla("+", "Añadir a mis metas"), 26, _tecla("W", "Abrir la wiki"), 26, _tecla("Esc", "Volver"),
               margen=(30, 6, 30, 14), espacio=0)
    capa.addWidget(Filete())
    capa.addLayout(pie)
    return r


def _linea_hito(titulo: str, texto: str, color: str) -> QWidget:
    w = Panel(remate=False, fondo=P["panel2"], borde=P["borde"])
    w.capa.setContentsMargins(14, 8, 14, 8)
    w.capa.addLayout(fila(_rombo(9, color), mayus(titulo, 13, color, 600, 1.5), None, lbl(texto, 14, P["texto"]), espacio=8))
    return w


def _ahora_en_juego(d, era: str) -> Panel:
    abiertas = [x for x in d.fisuras if x["era"] == era]
    pan = Panel("Ahora en el juego")
    if not abiertas:
        pan.capa.addWidget(lbl(f"No hay fisuras {era} abiertas", 14, P["suave"]))
    for x in abiertas[:2]:
        pan.capa.addLayout(fila(_rombo(10, P["turquesa"]), mayus(x["era"], 13, P["turquesa"], 600, 1.5), 4,
                                lbl(x["nodo"], 15, P["texto"], 600), lbl(f"{x['mision']} · {x['enemigo']}", 13, P["suave"]),
                                None, lbl(x["resta"], 13, P["suave"]), espacio=8))
    return pan


def _centrado(w: QWidget) -> QWidget:
    w.setAlignment(Qt.AlignCenter)
    return w


def _etiqueta(texto: str, color: str) -> QWidget:
    c = QColor(color)
    e = mayus(texto, 12, color, 600, 1.5)
    e.setStyleSheet(e.styleSheet() + f"border: 1px solid rgba({c.red()},{c.green()},{c.blue()},140); padding: 3px 10px;")
    return e


def _tecla(tecla: str, texto: str) -> QWidget:
    k = mayus(tecla, 13, P["acento_texto"], 700, 1)
    k.setStyleSheet(k.styleSheet() + f"background: {P['oro']}; padding: 2px 8px; border-radius: 3px;")
    w = QWidget()
    w.setLayout(fila(k, mayus(texto, 13, P["texto"], 500, 1.5), espacio=8))
    return w


def compacto(d) -> QWidget:
    """En partida: tarjetas sueltas tipo HUD, sin ventana; el buscador sale con la tecla."""
    f = d.ficha
    r = QFrame()
    r.setObjectName("hud")
    r.setStyleSheet(hoja({**P, "panel": P["panel_opaco"], "acento": P["oro"]}) + "QFrame#hud { background: transparent; }")
    r.setFixedWidth(380)
    capa = QVBoxLayout(r)
    capa.setContentsMargins(0, 0, 0, 0)
    capa.setSpacing(8)
    piezas = [m for m in d.metas if m.reliquia and not m.boveda and m.minutos]
    sig = min(piezas, key=lambda m: m.minutos)
    t1 = Panel(fondo="#0d1213", borde=P["oro_tenue"])
    t1.capa.setContentsMargins(16, 10, 16, 12)
    t1.capa.setSpacing(2)
    t1.capa.addLayout(fila(_rombo(8, P["oro"]), mayus("Siguiente pieza", 12, P["oro"], 600, 2), None,
                           mayus(minutos_txt(sig.minutos), 16, P["oro"], 600, 1), espacio=6))
    t1.capa.addWidget(lbl(sig.nombre, 18, P["texto"], 600))
    t1.capa.addWidget(lbl(f"Reliquia <b style='color:{P['turquesa']}'>{sig.reliquia}</b> · {sig.mision} en {sig.donde}", 14, P["suave"]))
    capa.addWidget(t1)
    fis = d.fisuras_para_ti[0] if d.fisuras_para_ti else None
    if fis:
        t2 = Panel(remate=False, fondo="#0d1213", borde=P["borde"])
        t2.capa.setContentsMargins(16, 10, 16, 12)
        t2.capa.setSpacing(2)
        t2.capa.addLayout(fila(_rombo(8, P["turquesa"]), mayus(f"Fisura {fis['era']} abierta", 12, P["turquesa"], 600, 2), None,
                               lbl(fis["resta"], 13, P["suave"]), espacio=6))
        t2.capa.addWidget(lbl(f"{fis['nodo']} · {fis['mision']}", 16, P["texto"], 600))
        t2.capa.addWidget(lbl(f"Te sirve para {fis['para']}", 13, P["suave"]))
        capa.addWidget(t2)
    t3 = Panel(remate=False, fondo="#0d1213", borde=P["borde"])
    t3.capa.setContentsMargins(14, 6, 14, 6)
    t3.capa.addLayout(fila(icono("buscar", 14, P["oro"]), lbl("Buscar algo", 13, P["suave"]), None,
                           _tecla("Ctrl+Alt+W", ""), espacio=6))
    capa.addWidget(t3)
    r.adjustSize()
    return r
