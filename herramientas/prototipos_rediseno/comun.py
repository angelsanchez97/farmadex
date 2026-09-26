"""Piezas comunes de los prototipos de rediseno: datos reales del indice y ayudas de pintado.

No es codigo de produccion. Los prototipos solo leen el indice (una copia en la caja de
arena de FARMADEX_DATOS) y el worldState guardado; no escriben nada del usuario.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SCRATCH = Path(os.environ.get(
    "FARMADEX_SCRATCH",
    r"C:\Users\angel\AppData\Local\Temp\claude\C--Users-angel-Escritorio"
    r"\f328cee1-3a14-49d7-8b31-81bdc7c465a5\scratchpad",
))


def preparar_entorno() -> None:
    """Antes de importar Qt o farmadex: sin pantalla, sin bienvenida y con datos de prueba."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    os.environ.setdefault("FARMADEX_SIN_BIENVENIDA", "1")
    os.environ.setdefault("FARMADEX_DATOS", str(SCRATCH / "rediseno" / "datos"))
    if str(RAIZ / "src") not in sys.path:
        sys.path.insert(0, str(RAIZ / "src"))


preparar_entorno()

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget  # noqa: E402

# -- tipografia: cinco tamanos y nada mas -------------------------------------------
# La queja del tester era "todo pesa lo mismo". Una escala corta y con saltos grandes.
T_PORTADA = 30   # lo unico que hay que leer si solo miras un segundo
T_TITULO = 22    # titulo de pagina / de ficha
T_SECCION = 16   # cabecera de bloque
T_NORMAL = 14    # texto
T_PEQUENO = 12   # metadatos, pistas

ICONOS = "Segoe Fluent Icons"
IC = {
    "buscar": "\ue721", "metas": "\ue734", "mundo": "\ue774", "herramientas": "\ue90f",
    "ajustes": "\ue713", "juego": "\ue7fc", "pin": "\ue718", "reloj": "\ue823",
    "derecha": "\ue76c", "abajo": "\ue70d", "arriba": "\ue70e", "atras": "\ue72b", "cerrar": "\ue711",
    "ventana": "\ue73f", "estrella": "\ue735", "mapa": "\ue707", "fisura": "\ue945",
    "tienda": "\ue719", "copiar": "\ue8c8", "web": "\ue774", "check": "\ue73e",
    "grupo": "\ue716", "info": "\ue946", "video": "\ue714", "build": "\ue90f",
    "mas": "\ue710", "sol": "\ue706", "luna": "\ue708", "reliquia": "\ue7b8",
}

# Paleta base: la del tema por defecto de Farmadex (Orokin), para comparar solo estructura.
BASE = {
    "fondo": "#12100c", "panel": "#1c1913", "panel2": "#26221a", "borde": "#3a3324",
    "texto": "#f1ece0", "suave": "#a89f8a", "tenue": "#766e5c", "acento": "#e2b455",
    "acento_texto": "#1a1508", "aviso": "#f08a3c", "ok": "#8ccf6f", "boveda": "#f0a63c",
}


def hoja(p: dict) -> str:
    return f"""
QWidget {{ background: transparent; color: {p['texto']}; font-family: 'Segoe UI'; font-size: {T_NORMAL}px; }}
QLineEdit {{ background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: 10px;
             padding: 10px 14px; font-size: 17px; color: {p['texto']}; }}
QLineEdit:focus {{ border-color: {p['acento']}; }}
"""


def lbl(texto: str, tam: int = T_NORMAL, color: str | None = None, peso: int = 400,
        envolver: bool = False, espaciado: float = 0, familia: str | None = None) -> QLabel:
    e = QLabel(texto)
    f = QFont(familia or "Segoe UI")
    f.setPixelSize(tam)
    f.setWeight(QFont.Weight(peso))
    if espaciado:
        f.setLetterSpacing(QFont.AbsoluteSpacing, espaciado)
    e.setFont(f)
    # La hoja de la ventana pisa la fuente del QLabel: tamano, peso y familia van en su hoja.
    fam = familia or "Segoe UI"
    e.setStyleSheet(f"{'color: ' + color + ';' if color else ''} background: transparent;"
                    f" font-family: '{fam}'; font-size: {tam}px; font-weight: {peso};")
    e.setWordWrap(envolver)
    e.setTextFormat(Qt.RichText if "<" in texto else Qt.PlainText)
    return e


def icono(clave: str, tam: int = 18, color: str = "#fff") -> QLabel:
    e = QLabel(IC.get(clave, clave))
    f = QFont(ICONOS)
    f.setPixelSize(tam)
    e.setFont(f)
    e.setStyleSheet(f"color: {color}; background: transparent; font-family: '{ICONOS}'; font-size: {tam}px;")
    e.setFixedWidth(int(tam * 1.4))
    e.setAlignment(Qt.AlignCenter)
    return e


def chip(texto: str, color: str, relleno: bool = False, tam: int = T_PEQUENO) -> QLabel:
    c = QColor(color)
    fondo = f"rgba({c.red()},{c.green()},{c.blue()},{255 if relleno else 38})"
    tinta = "#141008" if relleno else color
    e = lbl(texto, tam, None, 600)
    e.setStyleSheet(f"background: {fondo}; color: {tinta}; border-radius: 9px; padding: 2px 9px;"
                    f" font-size: {tam}px; font-weight: 600;")
    e.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return e


def caja(color_fondo: str, borde: str | None = None, radio: int = 12, izq: str | None = None) -> QFrame:
    """Un panel con fondo; `izq` pinta una franja de color a la izquierda (estado)."""
    marco = QFrame()
    marco.setObjectName("caja")
    extra = f"border-left: 4px solid {izq};" if izq else ""
    marco.setStyleSheet(
        f"QFrame#caja {{ background: {color_fondo}; border: 1px solid {borde or color_fondo};"
        f" border-radius: {radio}px; {extra} }}"
    )
    return marco


def fila(*widgets, espacio: int = 8, margen=(0, 0, 0, 0), estirar_final: bool = False) -> QHBoxLayout:
    capa = QHBoxLayout()
    capa.setContentsMargins(*margen)
    capa.setSpacing(espacio)
    for w in widgets:
        if w is None:
            capa.addStretch(1)
        elif isinstance(w, int):
            capa.addSpacing(w)
        elif isinstance(w, (QHBoxLayout, QVBoxLayout)):
            capa.addLayout(w, 1)
        else:
            capa.addWidget(w)
    if estirar_final:
        capa.addStretch(1)
    return capa


def columna(*widgets, espacio: int = 8, margen=(0, 0, 0, 0)) -> QVBoxLayout:
    capa = QVBoxLayout()
    capa.setContentsMargins(*margen)
    capa.setSpacing(espacio)
    for w in widgets:
        if w is None:
            capa.addStretch(1)
        elif isinstance(w, int):
            capa.addSpacing(w)
        elif isinstance(w, (QHBoxLayout, QVBoxLayout)):
            capa.addLayout(w)
        else:
            capa.addWidget(w)
    return capa


def imagen(nombre: str | None, lado: int) -> QLabel:
    e = QLabel()
    e.setFixedSize(lado, lado)
    e.setAlignment(Qt.AlignCenter)
    e.setStyleSheet("background: transparent;")
    if nombre:
        ruta = Path(os.environ["FARMADEX_DATOS"]) / "Farmadex" / "datos" / "img" / nombre
        if ruta.exists():
            mapa = QPixmap(str(ruta)).scaled(lado, lado, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            e.setPixmap(mapa)
    return e


class FondoPartida(QWidget):
    """Imitacion de una escena de juego con luces fuertes, para juzgar el overlay encima."""

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1d2a3a"))
        w, h = self.width(), self.height()
        for (x, y, r, c) in ((0.75, 0.25, 0.55, "#b98a4a"), (0.15, 0.85, 0.6, "#2f6b5a"),
                             (0.3, 0.15, 0.4, "#4a6aa8"), (0.9, 0.9, 0.3, "#d05a3a")):
            g = QRadialGradient(QPointF(w * x, h * y), max(w, h) * r)
            col = QColor(c)
            g.setColorAt(0, col)
            col.setAlpha(0)
            g.setColorAt(1, col)
            p.fillRect(self.rect(), g)
        # Un "HUD" de juego falso en la esquina para dar escala.
        p.setPen(QPen(QColor(255, 255, 255, 120), 2))
        p.drawArc(QRectF(w - 110, h - 110, 80, 80), 0, 270 * 16)
        p.end()


def ruta_chaflan(r: QRectF, c: float) -> QPainterPath:
    """Rectangulo con dos esquinas cortadas en diagonal (arriba-izq y abajo-dcha)."""
    camino = QPainterPath()
    camino.moveTo(r.left() + c, r.top())
    camino.lineTo(r.right(), r.top())
    camino.lineTo(r.right(), r.bottom() - c)
    camino.lineTo(r.right() - c, r.bottom())
    camino.lineTo(r.left(), r.bottom())
    camino.lineTo(r.left(), r.top() + c)
    camino.closeSubpath()
    return camino


def plural(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


def minutos_txt(m: float | None) -> str:
    if m is None:
        return "sin estimar"
    m = round(m)
    if m < 60:
        return f"{m} min"
    h, r = divmod(m, 60)
    return f"{h} h {r:02d} min" if r else f"{h} h"


# -- datos reales ------------------------------------------------------------------


@dataclass
class Meta:
    item_id: int
    nombre: str
    tipo: str
    imagen: str | None
    reliquia: str = ""
    era: str = ""
    donde: str = ""
    mision: str = ""
    minutos: float | None = None
    boveda: bool = False
    tengo: int = 0
    necesito: int = 1


@dataclass
class Datos:
    busqueda_texto: str = ""
    resultados: list = field(default_factory=list)
    ficha: dict = field(default_factory=dict)
    metas: list = field(default_factory=list)
    fisuras: list = field(default_factory=list)
    fisuras_para_ti: list = field(default_factory=list)
    ciclos: list = field(default_factory=list)
    baro: str = ""
    momento = None


def _nombre_completo(con, fila) -> str:
    from farmadex.idiomas import nombre

    n = nombre(fila)
    if fila.get("padre_id"):
        padre = con.execute("SELECT nombre_es, nombre_en FROM items WHERE id=?", (fila["padre_id"],)).fetchone()
        if padre:
            return f"{n} de {padre[0] or padre[1]}"
    return n


def _era(nombre_reliquia: str) -> str:
    for e in ("Lith", "Meso", "Neo", "Axi", "Requiem"):
        if e in nombre_reliquia:
            return e
    return ""


_CACHE: Datos | None = None


def cargar(busqueda: str = "citrine", ficha_id: int | None = None) -> Datos:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    from farmadex.datos import indice, items, relaciones, ruta_prime
    from farmadex.idiomas import nombre
    from farmadex.online.worldstate import Traductor, analizar
    from farmadex.ui import colores_tipo

    con = indice.conectar()
    d = Datos(busqueda_texto=busqueda)

    # Resultados de busqueda reales, con su tipo (para el color).
    for r in indice.buscar(con, busqueda)[:12]:
        d.resultados.append({
            "id": r["item_id"], "nombre": _nombre_completo(con, r), "tipo": colores_tipo.tipo_de(r),
            "tipo_txt": colores_tipo.nombre(colores_tipo.tipo_de(r)), "vaulted": bool(r.get("vaulted")),
            "imagen": r.get("imagen"), "categoria": r.get("categoria"), "pieza": bool(r.get("padre_id")),
        })

    # Ficha: Chasis de Citrine Prime (fuera de boveda, tiene ruta completa).
    if ficha_id is None:
        ficha_id = indice.buscar(con, "chasis citrine prime")[0]["item_id"]
    f = items.ficha(con, ficha_id)
    it, padre = f["item"], f["padre"]
    ruta = ruta_prime.ruta_pieza(con, ficha_id)
    rel = relaciones.reliquias_de(con, ficha_id)
    reliquias = []
    for r in rel[:4]:
        mis = relaciones.misiones_de(con, r["reliquia_id"])[:2]
        reliquias.append({
            "nombre": nombre(r).replace("Reliquia ", ""), "vaulted": bool(r["vaulted"]),
            "probs": r["probabilidades"],
            "misiones": [{"donde": m["donde"], "mision": m.get("mision") or "", "prob": m.get("probabilidad"),
                          "min": m.get("minutos_medios")} for m in mis],
        })
    hermanas = []
    if padre:
        for c in con.execute("SELECT id, nombre_es, nombre_en, imagen FROM items WHERE padre_id=? ORDER BY nombre_en", (padre["id"],)):
            hermanas.append({"id": c[0], "nombre": c[1] or c[2], "imagen": c[3]})
    mis_ruta = ruta["mision"] if ruta else None
    d.ficha = {
        "nombre": _nombre_completo(con, it), "corto": nombre(it), "padre": padre and (padre["nombre_es"] or padre["nombre_en"]),
        "imagen_padre": padre and padre["imagen"], "imagen": it["imagen"], "ducados": it["ducados"],
        "vaulted": bool(it["vaulted"]), "tipo": "warframe", "hermanas": hermanas, "id": ficha_id,
        "reliquia": ruta["reliquia"] and nombre(ruta["reliquia"]).replace("Reliquia ", "") if ruta else "",
        "prob_radiante": ruta and ruta["reliquia"]["probabilidades"].get("Radiant"),
        "donde": mis_ruta and mis_ruta["donde"], "mision": mis_ruta and mis_ruta["mision"],
        "min_reliquia": mis_ruta and mis_ruta.get("minutos_reliquia"),
        "min_pieza": ruta and ruta["minutos"], "escuadra": ruta and ruta["escuadra"],
        "otras": [{"donde": m["donde"], "mision": m["mision"], "min": m["minutos"]} for m in (ruta["misiones"][1:4] if ruta else [])],
        "reliquias": reliquias, "n_reliquias": len(rel),
    }
    d.ficha["era"] = _era(d.ficha["reliquia"])

    # Metas de muestra: dos piezas de Citrine Prime, una en boveda y un recurso.
    for q, tengo, necesito in (("chasis citrine prime", 0, 1), ("sistemas citrine prime", 0, 1),
                               ("celula orokin", 2, 5), ("sistemas ash prime", 0, 1)):
        r = indice.buscar(con, q)[0]
        mr = relaciones.mejor_ruta(con, r["item_id"]) or {}
        m = mr.get("mision") or {}
        rel_nombre = nombre(mr["reliquia"]).replace("Reliquia ", "") if mr.get("reliquia") else ""
        d.metas.append(Meta(
            r["item_id"], _nombre_completo(con, r), colores_tipo.tipo_de(r), r.get("imagen"),
            rel_nombre, _era(rel_nombre), m.get("donde") or "", m.get("mision") or "",
            mr.get("minutos_pieza") or mr.get("minutos_medios"), bool(mr.get("solo_en_boveda")), tengo, necesito,
        ))

    # Mundo: el worldState guardado en el scratchpad (21/09), con "ahora" = su propia hora.
    ws = SCRATCH / "ws.json"
    if ws.exists():
        mundo = analizar(json.loads(ws.read_text(encoding="utf-8")), Traductor(con))
        ahora = mundo.momento + timedelta(minutes=3) if mundo.momento else None
        d.momento = ahora

        def resta(exp):
            if not exp or not ahora:
                return ""
            s = max(0, int((exp - ahora).total_seconds()))
            h, r = divmod(s // 60, 60)
            return f"{h} h {r:02d} min" if h else f"{r} min"

        eras_meta = {m.era for m in d.metas if m.era and not m.boveda}
        for fi in mundo.fisuras:
            if fi.acero or fi.tormenta:
                continue
            item = {"era": fi.era, "nodo": fi.nodo, "mision": fi.mision, "enemigo": fi.enemigo,
                    "resta": resta(fi.expira)}
            d.fisuras.append(item)
            if fi.era in eras_meta:
                item["para"] = next(m.nombre for m in d.metas if m.era == fi.era and not m.boveda)
                d.fisuras_para_ti.append(item)
        for c in mundo.ciclos:
            d.ciclos.append({"nombre": c.nombre, "estado": c.estado, "resta": resta(c.expira)})
        d.baro = mundo.baro_cabecera
    _CACHE = d
    return d


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    d = cargar()
    print(d.resultados[:5])
    print({k: v for k, v in d.ficha.items() if k != "reliquias"})
    print(d.ficha["reliquias"][:2])
    for m in d.metas:
        print(m)
    print(len(d.fisuras), d.fisuras_para_ti[:3])
    print(d.ciclos, d.baro)
