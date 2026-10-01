"""Precios en el chat y al copiar: nombres, rangos, sets, agrietados, colores del chat y coste.

Lo que importa: nunca inventar (lo que no casa es "no reconocido", sin snapshot es "sin
datos"), no mirar la pantalla mas que una vez por parada del raton y solo leer si hay
amarillo de enlace en el chat, el portapapeles apagado por defecto y sin sondeo, y el
historial apagado por defecto.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import config  # noqa: E402
from farmadex.chat import enlace as E  # noqa: E402
from farmadex.chat import precios as P  # noqa: E402
from farmadex.chat import rivens as R  # noqa: E402
from farmadex.chat import texto as T  # noqa: E402
from farmadex.chat.historial import HistorialChat  # noqa: E402
from farmadex.chat.nombres import Resolutor  # noqa: E402
from farmadex.datos.items import normalizar  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# -- indice de juguete -------------------------------------------------------------------

ITEMS = [
    # id, slug, en, es, categoria, padre, tipo, unique
    (1, "loki_prime_set", "Loki Prime", "Loki Prime", "Warframes", None, "Warframe", "/W/LokiPrime"),
    (2, "loki_prime_neuroptics_blueprint", "Neuroptics", "Neurópticas", "Warframes", 1, None, "/W/LokiPrimeHelm"),
    (3, "loki_prime_blueprint", "Blueprint", "Plano", "Warframes", 1, None, "/W/LokiPrimeBP"),
    (4, "arcane_grace", "Arcane Grace", "Gracia Arcana", "Arcanes", None, None, "/A/Grace"),
    (5, "serration", "Serration", "Sierra", "Mods", None, None, "/M/Serration"),
    (6, "lith_s19_relic", "Lith S19 Relic", "Reliquia Lith S19", "Relics", None, None, "/R/LithS19"),
    (7, None, "Rubico", "Rubico", "Primary", None, "Rifle", "/P/Rubico"),
    (8, "rubico_prime_set", "Rubico Prime", "Rubico Prime", "Primary", None, "Rifle", "/P/RubicoPrime"),
    (9, None, "Banshee", "Banshee", "Warframes", None, "Warframe", "/W/Banshee"),
    (10, "banshee_prime_set", "Banshee Prime", "Banshee Prime", "Warframes", None, "Warframe", "/W/BansheePrime"),
    (11, None, "Catchmoon", "Catchmoon", "Misc", None, "Kitgun Component", "/K/Barrel/CatchmoonPart"),
    (12, "blind_rage", "Blind Rage", "Rabia ciega", "Mods", None, None, "/M/BlindRage"),
    (13, "supra_vandal", "Supra Vandal", "Supra Vándalo", "Primary", None, "Rifle", "/P/SupraVandal"),
    (14, None, "Loki Prime Glyph", "Glifo de Loki Prime", "Glyphs", None, None, "/G/Loki"),
]
OTROS_IDIOMAS = {4: {"de": "Arkana: Anmut", "pt": "Graciosidade Arcana"}}


@pytest.fixture(scope="module")
def res():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, market_slug TEXT, nombre_en TEXT, nombre_es TEXT,"
                " categoria TEXT, padre_id INTEGER, tipo TEXT, unique_name TEXT)")
    con.execute("CREATE TABLE busqueda (texto TEXT, item_id INTEGER, idioma TEXT, categoria TEXT)")
    por_id = {f[0]: f for f in ITEMS}
    for f in ITEMS:
        con.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,?)", f)
        padre = por_id.get(f[5])
        en = f"{padre[2]} {f[2]}" if padre else f[2]
        es = f"{padre[3]} {f[3]}" if padre else f[3]
        for texto, idioma in ((en, "en"), (es, "es"), *((v, k) for k, v in OTROS_IDIOMAS.get(f[0], {}).items())):
            con.execute("INSERT INTO busqueda VALUES (?,?,?,?)", (normalizar(texto), f[0], idioma, f[4]))
    return Resolutor(con)


@dataclass(frozen=True)
class Precio:
    slug: str
    rango: int | None
    venta_min: float | None = None
    venta_mediana: float | None = None
    compra_max: float | None = None
    min_30d: float | None = None
    max_30d: float | None = None
    media_30d: float | None = None
    volumen_30d: int | None = None
    fecha: datetime | None = None


class SnapshotFalso:
    fecha = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)

    def __init__(self):
        self.datos = {
            ("loki_prime_set", None): Precio("loki_prime_set", None, 95, 100, 80, 85, 130, 101, 400),
            ("arcane_grace", 0): Precio("arcane_grace", 0, 60, 65, 50, 55, 80, 62, 90),
            ("arcane_grace", 5): Precio("arcane_grace", 5, 300, 320, 250, 280, 400, 330, 40),
            ("serration", 0): Precio("serration", 0, 5, 6, 3, 4, 9, 6, 20),
            ("serration", 10): Precio("serration", 10, 20, 22, 15, 18, 30, 22, 30),
            ("lith_s19_relic", None): Precio("lith_s19_relic", None, 4, 5, 2, 3, 8, 5, 50),
        }
        self.pedidos: list = []

    def rangos(self, slug):
        return sorted(r for (s, r) in self.datos if s == slug and r is not None)

    def buscar(self, slug, rango=None):
        self.pedidos.append((slug, rango))
        return self.datos.get((slug, rango))


# -- nombres -------------------------------------------------------------------------------


@pytest.mark.parametrize("escrito, slug", [
    ("Loki Prime", "loki_prime_set"),
    ("LOKI PRIME", "loki_prime_set"),  # sin distinguir mayusculas
    ("loki prime neuroptics blueprint", "loki_prime_neuroptics_blueprint"),
    ("Plano de Neurópticas de Loki Prime", "loki_prime_neuroptics_blueprint"),
    ("Loki Prime Blueprint", "loki_prime_blueprint"),  # el plano principal no es el set
    ("Plano de Loki Prime", "loki_prime_blueprint"),
    ("Gracia Arcana", "arcane_grace"),
    ("gracia arcana", "arcane_grace"),
    ("Arkana: Anmut", "arcane_grace"),  # aleman
    ("Graciosidade Arcana", "arcane_grace"),  # portugues
    ("Reliquia Lith S19", "lith_s19_relic"),
])
def test_nombre_exacto_en_varios_idiomas(res, escrito, slug):
    assert res.buscar(escrito).slug == slug


def test_lo_que_no_existe_no_casa_ni_por_parecido(res):
    assert res.buscar("Blorbo Prime") is None
    assert res.buscar_difuso("Blorbo Prime") is None
    assert res.buscar_difuso("xyz") is None


def test_parecido_arregla_una_letra_del_ocr_pero_no_adivina(res):
    assert res.buscar_difuso("Arcane Grece").slug == "arcane_grace"
    assert res.buscar_difuso("Supra Vandai").slug == "supra_vandal"
    assert res.buscar_difuso("Arcane") is None


def test_entre_un_adorno_y_lo_que_se_vende_gana_lo_que_se_vende(res):
    assert res.buscar("Loki Prime").slug == "loki_prime_set"


# -- enlaces --------------------------------------------------------------------------------


def test_enlace_de_objeto_set_y_agrietado(res):
    e = T.interpretar_enlace("[Arcane Grace]", res)
    assert e.slug == "arcane_grace" and e.rango is None and not e.es_set
    e = T.interpretar_enlace("[Loki Prime Set]", res)
    assert e.slug == "loki_prime_set" and e.es_set
    e = T.interpretar_enlace("[Rubico Critacan]", res)
    assert e.riven.arma == "Rubico" and e.riven.estadisticas == ["critical_chance", "multishot"]
    e = T.interpretar_enlace("[Catchmoon Sati-visitio]", res)
    assert e.riven.arma == "Catchmoon" and len(e.riven.estadisticas) == 3


def test_enlace_con_el_corchete_leido_como_letra(res):
    assert T.interpretar_enlace("[Supra Vandal]", res).slug == "supra_vandal"  # la l final es suya
    assert T.interpretar_enlace("lSupra Vandall", res).slug == "supra_vandal"
    assert T.interpretar_enlace("[Rubico Critacanl", res).riven is not None


def test_enlace_que_no_es_nada_no_se_ensena(res):
    assert T.interpretar_enlace("Feedbackwav:", res) is None  # un nombre de usuario en amarillo
    assert T.interpretar_enlace("[Blorbo Prime]", res) is None
    assert T.interpretar_enlace("", res) is None


# -- listas ----------------------------------------------------------------------------------


def _por_nombre(entradas):
    return {e.nombre(): e for e in entradas}


def test_lista_con_corchetes_rangos_y_precios(res):
    entradas = T.analizar_lista(
        "[15:00] Vendedor: WTB r0 [Arcane Grace] 140:platinum: WTS Maxed [Blind Rage] 200:platinum: [Loki Prime] SET 95p",
        res)
    e = {x.slug: x for x in entradas}
    assert e["arcane_grace"].rango == 0 and e["arcane_grace"].precio_pedido == 140
    assert e["blind_rage"].rango_max and e["blind_rage"].precio_pedido == 200
    assert e["loki_prime_set"].es_set and e["loki_prime_set"].precio_pedido == 95


def test_lista_sin_corchetes_en_ingles_y_espanol(res):
    entradas = T.analizar_lista("WTS Loki Prime set 100p, Arcane Grace R5 300p, Serration max 20p", res)
    assert [(e.slug, e.rango, e.rango_max, e.precio_pedido) for e in entradas] == [
        ("loki_prime_set", None, False, 100), ("arcane_grace", 5, False, 300), ("serration", None, True, 20)]
    entradas = T.analizar_lista("Vendo set de Loki Prime 90p y Gracia Arcana rango 5 por 250p", res)
    assert [(e.slug, e.es_set, e.rango) for e in entradas] == [("loki_prime_set", True, None), ("arcane_grace", False, 5)]
    entradas = T.analizar_lista("Vendo [Set de Loki Prime] 95p | [Gracia Arcana] R5 300p | [Sierra] 15p", res)
    assert [(e.slug, e.rango) for e in entradas] == [("loki_prime_set", None), ("arcane_grace", 5), ("serration", None)]


def test_agrietado_abreviado_en_una_lista(res):
    entradas = T.analizar_lista("VENDO: Rubico Critacan 3k, Reliquia Lith S19 5p", res)
    assert entradas[0].riven.estadisticas == ["critical_chance", "multishot"] and entradas[0].precio_pedido == 3000
    assert entradas[1].slug == "lith_s19_relic"


def test_cabecera_prime_sets(res):
    entradas = T.analizar_lista("SELLING PRIME SETS:>Banshee, Loki", res)
    assert [e.slug for e in entradas] == ["banshee_prime_set", "loki_prime_set"]


def test_lo_desconocido_sale_como_no_reconocido_y_nunca_con_otro_objeto(res):
    entradas = T.analizar_lista("WTS [Blorbo Prime] 50p [Loki Prime Set] 100p", res)
    assert not entradas[0].reconocido and entradas[0].slug is None
    assert entradas[1].slug == "loki_prime_set"


@pytest.mark.parametrize("copiado", [
    "hola que tal, alguien juega esta noche?",
    "WTB [Arcane Grace] 200p",  # compra, no venta
    "https://wiki.warframe.com/w/Loki",
    "def f(x): return x + 1",
    "",
    "Loki Prime",  # un nombre suelto no es una lista de venta
])
def test_lo_que_no_es_una_lista_de_venta_no_sale(res, copiado):
    assert T.analizar_lista(copiado, res) is None


def test_texto_enorme_no_se_analiza(res):
    assert T.analizar_lista("WTS [Loki Prime] 100p " * 500, res) is None


# -- precios (snapshot local) -----------------------------------------------------------------


def test_mod_sin_rango_ensena_r0_y_maximo_y_con_rango_solo_ese():
    s = SnapshotFalso()
    assert [f.rango for f in P.filas("arcane_grace", None, s)] == [0, 5]
    assert [f.rango for f in P.filas("arcane_grace", 5, s)] == [5]
    assert [f.rango for f in P.filas("arcane_grace", None, s, solo_maximo=True)] == [5]
    assert [f.rango for f in P.filas("serration", 99, s)] == [10]  # mas que el maximo: el maximo
    assert [f.rango for f in P.filas("loki_prime_set", None, s)] == [None]


def test_sin_snapshot_o_sin_dato_dice_sin_datos(monkeypatch):
    monkeypatch.setattr(P, "_precios", lambda: None)
    filas = P.filas("arcane_grace")
    assert filas[0].precio is None and P.texto_30d(filas[0].precio) == "sin datos"
    s = SnapshotFalso()
    assert P.texto_30d(P.filas("rubico_prime_set", None, s)[0].precio) == "sin datos"
    assert P.texto_fecha(None) == "Sin precios descargados todavía"


def test_adaptador_devuelve_none_si_no_esta_el_modulo():
    # En esta rama el modulo de la zona "precios" puede no existir: nunca revienta.
    assert P._precios() is None or hasattr(P._precios(), "buscar")


def test_textos_de_precio():
    s = SnapshotFalso()
    p = s.buscar("arcane_grace", 5)
    assert P.texto_30d(p) == "280–400 p"
    assert P.texto_ahora(p) == "venden desde 300 · compran hasta 250"
    assert "30/09 00:00" in P.texto_fecha(s.fecha)


# -- contenido de la tarjeta y de la lista ------------------------------------------------------


def test_contenido_de_la_tarjeta_y_la_lista(res, qapp):
    from farmadex.ui import precios_chat as U

    s = SnapshotFalso()
    c = U.contenido_enlace(T.interpretar_enlace("[Arcane Grace]", res), s)
    assert [f[0] for f in c["filas"]] == ["R0", "R5"] and c["filas"][1][1] == "280–400 p"
    c = U.contenido_enlace(T.interpretar_enlace("[Rubico]", res), s)
    assert c["nota"] == "No se vende entre jugadores" and not c["filas"]
    c = U.contenido_enlace(T.interpretar_enlace("[Rubico Critacan]", res), s, None)
    assert c["nota"] == "buscando parecidos…" and "Multidisparo" in c["sub"]
    entradas = T.analizar_lista("WTS [Blorbo] 5p [Arcane Grace] R5 300p [Serration] [Loki Prime] set", res)
    filas = U.filas_lista(entradas, s)
    assert filas[0]["nota"] == "no reconocido" and not filas[0]["columnas"]
    assert filas[1]["columnas"] == [("R5", "280–400 p", "300")] and filas[1]["pedido"] == 300
    assert [c[0] for c in filas[2]["columnas"]] == ["R0", "R10"]
    assert filas[3]["nombre"].endswith("set") and filas[3]["columnas"][0][1] == "85–130 p"
    assert "no reconocido" in U.html_lista(filas, "pie")


# -- agrietados ---------------------------------------------------------------------------------


def test_horquilla_de_parecidos_sin_inventar():
    from farmadex.agrietados import mercado as M

    class Mercado:
        def __init__(self, precios_y_stats):
            self.s = precios_y_stats

        def armas(self):
            return [M.Arma("rubico", "Rubico", "/P/Rubico", "rifle", "primary", 1.0)]

        def subastas(self, arma, positivos, negativos, limite=30):
            r = M.ResumenSubastas(arma=arma)
            r.subastas = [M.Subasta(p, None, [(s, 10.0, False) for s in stats], 0, 8, 8, "", "", "", "ingame")
                          for p, stats in self.s]
            return r

    buenas = [(p, ["critical_chance", "multishot"]) for p in (100, 150, 200, 250, 300, 400)]
    h = R.calcular("Rubico", ["critical_chance", "multishot"], Mercado(buenas))
    assert h.suficiente and h.n == 6 and "parecidos a la venta" in R.texto_horquilla(h)
    # Subastas del arma sin esas estadisticas (lo que devuelve el mercado si el filtro no da nada): no cuentan.
    otras = [(p, ["toxin_damage"]) for p in (10, 20, 30, 40, 50, 60)]
    h = R.calcular("Rubico", ["critical_chance", "multishot"], Mercado(otras))
    assert h.n == 0 and R.texto_horquilla(h) == "ningún parecido a la venta ahora"
    h = R.calcular("Rubico", ["critical_chance", "multishot"], Mercado(buenas[:2]))
    assert not h.suficiente and "pocos para dar un precio" in R.texto_horquilla(h)
    assert R.calcular("Nada", ["multishot"], Mercado(buenas)).error


# -- colores del chat -----------------------------------------------------------------------------

ALTO_JUEGO = 1080


def _bgr(rgb):
    return (rgb[2], rgb[1], rgb[0])


def _linea_chat(color_enlace=E.AMARILLO, fondo=(8, 8, 8), ancho=860, alto=96):
    """Tira como la del juego: '[hora] Usuario: WTS [Arcane Grace] 300p' con sus colores."""
    import cv2

    img = np.full((alto, ancho, 3), fondo, np.uint8)
    fuente, escala, grosor = cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1
    x = 10
    cajas = {}
    for clave, texto, color in (("hora", "[15:00] ", (230, 230, 230)), ("usuario", "Vendedor: ", E.USUARIO),
                                ("texto", "WTS ", (230, 230, 230)), ("enlace", "[Arcane Grace]", color_enlace),
                                ("resto", " 300p", (230, 230, 230))):
        (w, h), _ = cv2.getTextSize(texto, fuente, escala, grosor)
        cv2.putText(img, texto, (x, 55), fuente, escala, _bgr(color), grosor, cv2.LINE_AA)
        cajas[clave] = (x, 55 - h, w, h)
        x += w
    # Otra linea encima con un enlace sin raton, como en el chat de verdad.
    cv2.putText(img, "[Loki Prime]", (120, 25), fuente, escala, _bgr(E.ENLACE), grosor, cv2.LINE_AA)
    return img, cajas


def test_los_tres_colores_se_distinguen_entre_si_y_del_blanco():
    img, _ = _linea_chat()
    usuario, enlace, amarillo = (E.mascara(img, c) for c in (E.USUARIO, E.ENLACE, E.AMARILLO))
    assert usuario.sum() > 50 and enlace.sum() > 50 and amarillo.sum() > 50
    assert not (usuario & enlace).any() and not (usuario & amarillo).any() and not (enlace & amarillo).any()
    blanco = np.full((20, 20, 3), 235, np.uint8)
    dorado = np.full((20, 20, 3), _bgr((255, 170, 0)), np.uint8)
    for c in (E.USUARIO, E.ENLACE, E.AMARILLO):
        assert not E.mascara(blanco, c).any() and not E.mascara(dorado, c).any()


def test_los_bordes_mezclados_con_fondo_oscuro_siguen_contando():
    medio = np.full((4, 4, 3), [int(v * 0.6) for v in _bgr(E.ENLACE)], np.uint8)
    assert E.mascara(medio, E.ENLACE).all()
    apagado = np.full((4, 4, 3), [int(v * 0.2) for v in _bgr(E.ENLACE)], np.uint8)
    assert not E.mascara(apagado, E.ENLACE).any()


def test_caja_del_enlace_bajo_el_cursor():
    img, cajas = _linea_chat()
    x, y, w, h = cajas["enlace"]
    caja = E.caja_bajo_cursor(E.mascara(img, E.AMARILLO), (x + w // 2, y + h // 2), ALTO_JUEGO)
    assert caja is not None and abs(caja.x - x) <= 6 and abs(caja.ancho - w) <= 12
    # Con el raton en otra parte de la linea (sobre el nombre) no hay enlace bajo el cursor.
    ux, uy, uw, uh = cajas["usuario"]
    assert E.caja_bajo_cursor(E.mascara(img, E.AMARILLO), (ux + uw // 2, uy + uh // 2), ALTO_JUEGO) is None


class MotorFalso:
    fallo = None


def test_lector_solo_lee_si_hay_amarillo_y_parece_el_chat(monkeypatch):
    leidos = []
    monkeypatch.setattr(E, "leer_recorte", lambda motor, imagen: (leidos.append(imagen.shape) or "[Arcane Grace]", 0.95))
    lector = E.LectorEnlaceChat()
    lector.motor = MotorFalso()
    img, cajas = _linea_chat()
    x, y, w, h = cajas["enlace"]
    texto, confianza, usuario, motivo = lector.leer_imagen(img, (x + w // 2, y + h // 2), ALTO_JUEGO)
    assert (texto, motivo) == ("[Arcane Grace]", "") and len(leidos) == 1 and usuario == ""
    # Enlace sin el raton encima (azul): no hay amarillo -> no se llama al OCR.
    azul, _ = _linea_chat(color_enlace=E.ENLACE)
    assert not E.amarillo_suficiente(azul, ALTO_JUEGO)
    assert lector.leer_imagen(azul, (x + w // 2, y + h // 2), ALTO_JUEGO)[0] == "" and len(leidos) == 1
    # Amarillo fuera del chat (un menu dorado, sin nombres ni enlaces alrededor): tampoco.
    import cv2

    menu = np.full((96, 860, 3), 8, np.uint8)
    cv2.putText(menu, "COMPRAR AHORA", (300, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, _bgr(E.AMARILLO), 1, cv2.LINE_AA)
    assert lector.leer_imagen(menu, (360, 50), ALTO_JUEGO)[3] == "no parece el chat" and len(leidos) == 1


def test_usuario_de_la_linea_solo_con_el_historial_encendido(monkeypatch):
    monkeypatch.setattr(E, "leer_recorte", lambda motor, imagen: ("Vendedor:", 0.9) if imagen.shape[1] < 400 else ("[Arcane Grace]", 0.9))
    lector = E.LectorEnlaceChat()
    lector.motor = MotorFalso()
    img, cajas = _linea_chat()
    x, y, w, h = cajas["enlace"]
    lector.con_usuario = True
    assert lector.leer_imagen(img, (x + w // 2, y + h // 2), ALTO_JUEGO)[2] == "Vendedor"


# -- una lectura por parada, nada en reposo ---------------------------------------------------------


def _hover(qapp, mostrar=None):
    reloj = {"t": 0.0}
    pedidas, ocultas = [], []
    h = E.HoverChat(mostrar or (lambda lectura: True), lambda: ocultas.append(1), reloj=lambda: reloj["t"])
    pos = {"p": (500, 800)}
    h.cursor = lambda: pos["p"]
    h.juego_delante = lambda: True
    h.pedir_lectura.connect(lambda n, x, y: pedidas.append((n, x, y)))
    return h, reloj, pos, pedidas, ocultas


def test_una_lectura_por_parada_y_ninguna_con_el_raton_quieto(qapp):
    h, reloj, pos, pedidas, _ = _hover(qapp)
    for _ in range(200):  # diez segundos con el raton quieto
        reloj["t"] += 0.05
        h.tic()
    assert len(pedidas) == 1
    h.leida(E.Lectura(1, 500, 800, motivo="sin amarillo"))
    for _ in range(200):
        reloj["t"] += 0.05
        h.tic()
    assert len(pedidas) == 1  # sigue quieto: no se vuelve a mirar
    pos["p"] = (700, 820)
    for _ in range(10):
        reloj["t"] += 0.05
        h.tic()
    assert len(pedidas) == 2


def test_sin_el_juego_delante_o_apagado_no_se_mira(qapp):
    h, reloj, pos, pedidas, _ = _hover(qapp)
    h.juego_delante = lambda: False
    for i in range(100):
        reloj["t"] += 0.05
        pos["p"] = (500 + (i % 2) * 50, 800)
        h.tic()
    assert pedidas == []
    h.juego_delante = lambda: True
    h.activo = False
    for _ in range(100):
        reloj["t"] += 0.05
        h.tic()
    assert pedidas == []


def test_se_ensena_y_se_esconde_al_alejarse_y_lo_viejo_no_se_ensena(qapp):
    vistos = []
    h, reloj, pos, pedidas, ocultas = _hover(qapp, lambda lectura: vistos.append(lectura.texto) or True)
    for _ in range(5):
        reloj["t"] += 0.05
        h.tic()
    h.leida(E.Lectura(1, 500, 800, "[Arcane Grace]", 0.9))
    assert vistos == ["[Arcane Grace]"] and h.visible
    pos["p"] = (900, 300)
    reloj["t"] += 0.05
    h.tic()
    assert ocultas == [1] and not h.visible
    # Una lectura que llega cuando el raton ya esta en otro sitio no se ensena.
    for _ in range(5):
        reloj["t"] += 0.05
        h.tic()
    pos["p"] = (100, 100)
    h.leida(E.Lectura(2, 900, 300, "[Loki Prime]", 0.9))
    assert vistos == ["[Arcane Grace]"]


# -- historial y ajustes -----------------------------------------------------------------------------


def test_todo_lo_delicado_viene_apagado():
    assert config.POR_DEFECTO["portapapeles_ventas"] is False
    assert config.POR_DEFECTO["historial_chat"] is False
    assert config.POR_DEFECTO["precio_enlaces_chat"] is True


def test_historial_apagado_no_escribe_y_se_puede_borrar(tmp_path):
    ruta = tmp_path / "historial_chat.jsonl"
    h = HistorialChat(ruta, activo=False)
    assert not h.apuntar("Gracia Arcana", "arcane_grace", "R0 55–80 p", "Vendedor") and not ruta.exists()
    h.activo = True
    assert h.apuntar("Gracia Arcana", "arcane_grace", "R0 55–80 p", "Vendedor")
    fila = h.leer()[0]
    assert fila["objeto"] == "Gracia Arcana" and fila["usuario"] == "Vendedor" and fila["hora"]
    assert h.borrar() and not ruta.exists() and h.leer() == []


# -- servicio: portapapeles por evento ---------------------------------------------------------------


def _servicio(qapp, res, monkeypatch, **ajustes):
    from farmadex.chat import nombres
    from farmadex.ui import precios_chat as U

    monkeypatch.setattr(nombres, "resolutor", lambda: res)
    monkeypatch.setattr(P, "_precios", lambda: SnapshotFalso())
    cfg = dict(config.POR_DEFECTO)
    cfg.update(ajustes)
    s = U.ServicioChat(cfg, motor_ocr="rapidocr")
    s.historial.ruta = None
    return s, U


def _esperar(qapp, condicion, segundos=3.0):
    import time

    fin = time.monotonic() + segundos
    while time.monotonic() < fin and not condicion():
        qapp.processEvents()
        time.sleep(0.005)
    return condicion()


def test_portapapeles_apagado_no_mira_y_encendido_ensena_la_lista(qapp, res, monkeypatch):
    s, U = _servicio(qapp, res, monkeypatch)
    try:
        monkeypatch.setattr(U.QGuiApplication, "applicationState", staticmethod(lambda: U.Qt.ApplicationInactive))
        s._portapapeles = qapp.clipboard()
        qapp.clipboard().setText("WTS [Loki Prime] 100p [Arcane Grace] R5 300p")
        s._portapapeles_cambiado()
        qapp.processEvents()
        assert s.lista is None  # apagado por defecto: ni se lee el texto
        s.activar_portapapeles(True)
        s._portapapeles_cambiado()
        assert _esperar(qapp, lambda: s.lista is not None and s.lista.isVisible())
        assert "280–400 p" in s.lista.cuerpo.text() and s.latencias_lista[-1] < 1000
        # Lo que copia el propio Farmadex (el susurro) se ignora.
        s.lista.hide()
        assert not s.analizar_texto("/w Vendedor Hi! I want to buy: Loki Prime Set for 100 platinum.")
        # Y lo que no es una lista de venta no ensena nada.
        s.analizar_texto("hola que tal")
        _esperar(qapp, lambda: False, 0.2)
        assert not s.lista.isVisible()
    finally:
        s.cerrar()


def test_con_farmadex_delante_lo_copiado_es_suyo_y_no_se_analiza(qapp, res, monkeypatch):
    s, U = _servicio(qapp, res, monkeypatch, portapapeles_ventas=True)
    try:
        monkeypatch.setattr(U.QGuiApplication, "applicationState", staticmethod(lambda: U.Qt.ApplicationActive))
        s._portapapeles = qapp.clipboard()
        qapp.clipboard().setText("WTS [Loki Prime] 100p [Arcane Grace] R5 300p")
        s._portapapeles_cambiado()
        _esperar(qapp, lambda: False, 0.2)
        assert s.lista is None
    finally:
        s.cerrar()


def test_enlace_leido_ensena_tarjeta_y_apunta_historial_si_esta_encendido(qapp, res, monkeypatch, tmp_path):
    s, U = _servicio(qapp, res, monkeypatch, historial_chat=True)
    try:
        s.historial.ruta = tmp_path / "h.jsonl"
        assert s.lector.con_usuario
        assert s._mostrar_enlace(E.Lectura(1, 10, 10, "[Arcane Grace]", 0.9, usuario="Vendedor"))
        assert s.tarjeta.isVisible() and "R5" in s.tarjeta.cuerpo.text()
        assert s.historial.leer()[0]["usuario"] == "Vendedor"
        # Poca confianza del OCR o un nombre que no existe: no se ensena nada.
        s._ocultar_enlace()
        assert not s._mostrar_enlace(E.Lectura(2, 10, 10, "[Arcane Grace]", 0.2))
        assert not s._mostrar_enlace(E.Lectura(3, 10, 10, "[Blorbo]", 0.99))
        assert not s.tarjeta.isVisible() and len(s.historial.leer()) == 1
    finally:
        s.cerrar()
