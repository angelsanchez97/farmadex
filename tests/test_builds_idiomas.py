"""Lector de la pantalla de mejoras con el juego en otros idiomas, resoluciones y formatos.

Todo sale de capturas reales de YouTube de jugadores de Francia, Alemania, Brasil, Italia,
Polonia y Rusia, a 1080p, 1440p, 4K y 3440x1440 (ultrapanoramica), y de esas mismas
capturas reducidas a 720p/768p/900p, en 16:10 y 21:9, con la escala de menu al 75 % y
como ventana dentro del escritorio (herramientas/banco_builds.py --variantes). Aqui van
sin OCR, con las lineas tal y como las leyo:

- La cabecera en cada idioma: "APRIMORAMENTOS: SYAM (NÍVEL 30)", "POTENZIAMENTI GYRE
  GRADO 30" (pegado: "POTENZIAMENTIGYREGRADO30"), "ULEPSZENIA: OBERON PRIME RANGA ZERO",
  "UPGRADES: NYX PRIME RANG 30" (el aleman dice UPGRADES), "AMÉLIORATIONS ZEPHYR PRIME
  NIVEAU 30" (sin separador) y el corchete de ancho completo "UPGRADES/NOKKO ［30]".
- La caja de busqueda, el orden y el filtro en cada idioma ("CERCA...", "PROCURAR...",
  "WYSZUKIWANIE...", "SORTUJ WG: RANGA", "CO WSZYSTKIE"); sin ellos toda la coleccion
  salia como equipada.
- "AURA" (etiqueta de la tarjeta de aura ampliada) no es el filtro.
- El panel de estadisticas acaba donde acaban los numeros de "CAPACIDAD", no en un 28 %
  fijo: los nombres largos de la primera columna ("Overextended") se tiraban.
- Las pestanas de configuracion que nombra el jugador ("ZASIEG", "POSZUKIWACZ") no son
  mods, aunque vayan un poco por encima de "POJEMNOSC" o en mayusculas.
- Un nombre a dos lineas del que solo casa una ("Mroczna" / "Intensyfikacja") no inventa.
- La "ł" polaca que el OCR lee "t" ("Mroczne Wtokna").
- El ruso: el OCR no lee cirilico; no se inventa nada y se avisa de por que.
"""

from __future__ import annotations

import pytest

from farmadex.captura import builds as B
from farmadex.captura.ocr import Leido, Reconocido

from test_captura import _insertar

ITEMS = [
    ("/m/Intensify", "Intensify", "Intensificación", "Mods"),
    ("/m/UmbralIntensify", "Umbral Intensify", "Intensificación Umbral", "Mods"),
    ("/m/SteelFiber", "Steel Fiber", "Fibra de acero", "Mods"),
    ("/m/Overextended", "Overextended", "Sobreextendido", "Mods"),
    ("/m/Reach", "Reach", "Alcance", "Mods"),
    ("/m/Seeker", "Seeker", "Buscador", "Mods"),
    ("/m/Vitality", "Vitality", "Vitalidad", "Mods"),
    ("/m/Transient", "Transient Fortitude", "Fortaleza transitoria", "Mods"),
    ("/w/Gyre", "Gyre", "Gyre", "Warframes"),
    ("/w/Syam", "Syam", "Syam", "Melee"),
    ("/w/OberonPrime", "Oberon Prime", "Oberon Prime", "Warframes"),
    ("/w/NyxPrime", "Nyx Prime", "Nyx Prime", "Warframes"),
]
# Nombres polacos de WFCD (tabla items_nombres), como los trae el indice.
POLACO = {
    "/m/Intensify": "Intensyfikacja", "/m/UmbralIntensify": "Mroczna Intensyfikacja",
    "/m/SteelFiber": "Stalowe Włókna", "/m/Transient": "Przejściowe Wzmocnienie", "/m/Reach": "Zasięg", "/m/Seeker": "Poszukiwacz",
}


@pytest.fixture()
def catalogo(con):
    ids = _insertar(con, [(u, en, es, cat, None, None) for u, en, es, cat in ITEMS])
    for unico, nombre in POLACO.items():
        con.execute("INSERT INTO items_nombres (item_id, idioma, nombre) VALUES (?, 'pl', ?)", (ids[unico], nombre))
    con.commit()
    return con, ids


def _l(texto, x, y, ancho=160, alto=24, conf=0.9):
    return Leido(texto, x, y, ancho, alto, conf)


def _r(ids, unico, nombre, caja, texto=None):
    return Reconocido(texto or nombre, ids[unico], nombre, 100.0, caja)


def _categorias(con):
    return dict(con.execute("SELECT id, categoria FROM items"))


@pytest.mark.parametrize("texto, nombre, idioma", [
    ("APRIMORAMENTOS:SYAM(NIVEL3O)", "SYAM", "pt"),
    ("APRIMORAMENTOS:ORAXIA(NIVEL30)", "ORAXIA", "pt"),
    ("POTENZIAMENTIGYREGRADO30", "GYRE", "it"),
    ("P0TENZIAMENTIGYRE GRADO 30", "GYRE", "it"),
    ("ULEPSZENIA: OBERON PRIME RANGA ZERO", "OBERON PRIME", "pl"),
    ("AMÉLIORATIONS ZEPHYR PRIME NIVEAU 30", "ZEPHYR PRIME", "fr"),
    ("UPGRADES/NOKKO ［30]", "NOKKO", "en"),
    ("UPGRADES:NYXPRIMERANG30", "NYXPRIME", "en"),
    ("MEJORAS / HAALVU [22]", "HAALVU", "es"),
    ("+UPGRADES/EXCALIBUR [3O] 美美", "EXCALIBUR", "en"),
])
def test_cabecera_en_cada_idioma(texto, nombre, idioma):
    m = B.es_cabecera(texto)
    assert m is not None and m.group(1) == nombre
    assert B.idioma_de_cabecera(texto) == idioma


def test_palabra_de_cabecera_sola_no_es_cabecera():
    for texto in ("MEJORAS", "MEJORAS /", "UPGRADES:"):
        assert B.es_cabecera(texto) is None, texto


def test_rango_de_cada_idioma_se_quita_del_nombre():
    assert "ZEPHYR PRIME" in B._nombres_de_equipo("ZEPHYR PRIME NIVEAU")  # el numero cortado
    assert "OBERON PRIME" in B._nombres_de_equipo("OBERON PRIME RANGA ZERO")
    assert B._nombres_de_equipo("NOKKO ［30]")[-1] == "NOKKO"


def test_equipo_de_la_cabecera_en_otros_idiomas(catalogo):
    con, ids = catalogo
    casador = B.crear_casador(con)
    categorias = _categorias(con)
    for texto, unico in (("POTENZIAMENTIGYREGRADO30", "/w/Gyre"), ("APRIMORAMENTOS:SYAM(NIVEL3O)", "/w/Syam"),
                         ("ULEPSZENIA: OBERON PRIME RANGA ZERO", "/w/OberonPrime"),
                         ("UPGRADES:NYXPRIMERANG30", "/w/NyxPrime")):
        nombre, linea = B.cabecera([_l(texto, 400, 60, ancho=900, alto=50)])
        equipo = B._casar_equipo(nombre, linea, casador, categorias)
        assert equipo is not None and equipo.item_id == ids[unico], texto


@pytest.mark.parametrize("texto", ["CERCA...", "PROCURAR..", "WYSZUKIWANIE.", "|CHERCHER...", "SUCHE."])
def test_caja_de_busqueda_en_cada_idioma(texto):
    assert B.RE_BUSCAR.match(texto)


@pytest.mark.parametrize("texto", ["SORTUJWG:RANGA", "SORTUJ WG: RANGA", "RARITA", "GRADO", "CUSTO", "NIVEL", "RANG"])
def test_orden_en_cada_idioma(texto):
    assert B.RE_ORDEN.match(texto)


@pytest.mark.parametrize("texto", ["CO WSZYSTKIE", "CO TODOS", "TUTTO", "CO ALLE", "TOUT"])
def test_filtro_en_cada_idioma(texto):
    assert B.RE_FILTRO.match(texto)


@pytest.mark.parametrize("texto", ["POJEMNOSC", "CAPACITA", "CAPACIDADE", "KAPAZITAT", "CAPACITÉ"])
def test_capacidad_en_cada_idioma(texto):
    assert B.RE_CAPACIDAD.match(texto)


def test_separacion_en_italiano_y_polaco(catalogo):
    con, ids = catalogo
    for separador in (_l("CERCA...", 100, 830), _l("WYSZUKIWANIE.", 200, 830), _l("SORTUJ WG: RANGA", 1900, 830)):
        lineas = [_l("Vitality", 900, 400), _l("Reach", 900, 1000), separador]
        reconocidos = [_r(ids, "/m/Vitality", "Vitality", (900, 400, 160, 24)),
                       _r(ids, "/m/Reach", "Reach", (900, 1000, 160, 24))]
        build = B.separar_build(lineas, reconocidos, _categorias(con), ancho=2560)
        assert [r.nombre for r in build.coleccion] == ["Reach"], separador.texto


def test_aura_de_la_tarjeta_ampliada_no_es_el_filtro(catalogo):
    """Captura real en italiano con mando: "AURA" al pie de la tarjeta de aura ampliada
    mandaba a la coleccion la mitad de lo equipado."""
    con, ids = catalogo
    lineas = [_l("Vitality", 900, 700), _l("La squadra ottiene il", 1250, 420, ancho=240), _l("AURA", 1300, 480, ancho=60)]
    reconocidos = [_r(ids, "/m/Vitality", "Vitality", (900, 700, 160, 24))]
    assert B.linea_separadora(lineas, 2560) is None  # el "AURA" de la tarjeta no separa
    build = B.separar_build(lineas, reconocidos, _categorias(con), ancho=2560)
    # Sin separador de verdad ni filas para deducirlo: nada se da por equipado y se avisa.
    assert build.equipados == [] and [r.nombre for r in build.coleccion] == ["Vitality"]
    assert build.aviso == B.AVISO_SIN_SEPARADOR
    # El filtro de polaridad de verdad va en la fila del buscador, con el orden a la derecha.
    aura = _l("AURA", 1300, 800, ancho=60)
    assert B.linea_separadora([aura, _l("POLARNOSC", 1950, 800, ancho=120)], 2560, 1440) == 824
    assert B.linea_separadora([aura], 2560, 1440) is None


def test_nombre_largo_de_la_primera_columna_no_es_del_panel(catalogo):
    """"Overextended" empezaba antes del 28 % del ancho y se tiraba como si fuera del
    panel de estadisticas (captura real en italiano a 4K)."""
    con, ids = catalogo
    lineas = [_l("CAPACITA", 180, 150, ancho=140), _l("7/74", 700, 150, ancho=70), _l("Salute", 190, 240, ancho=90),
              _l("Overextended", 690, 690, ancho=250), _l("CERCA...", 180, 830)]
    reconocidos = [_r(ids, "/m/Overextended", "Overextended", (690, 690, 250, 24)),
                   _r(ids, "/m/Vitality", "Vitality", (190, 240, 90, 24), texto="Salute")]
    build = B.separar_build(lineas, reconocidos, _categorias(con), ancho=2560)
    assert [r.nombre for r in build.equipados] == ["Overextended"]
    assert B.limite_panel(lineas, lineas[0], 2560) == pytest.approx(770 + 25.6)
    # Sin la fila de capacidad, un cuarto del ancho.
    assert B.limite_panel(lineas, None, 2560) == 640


def test_pestanas_de_configuracion_en_polaco_no_son_mods(catalogo):
    """Interfaz de 2021 en polaco: las pestanas "ZASIEG", "SILA" van algo por encima de
    "POJEMNOSC" y "POSZUKIWACZ" casaba con el mod Seeker."""
    con, ids = catalogo
    lineas = [_l("POJEMNOSC", 250, 123, ancho=120), _l("51/68", 460, 123, ancho=60), _l("ZASIEG", 810, 113, ancho=80),
              _l("POSZUKIWACZ", 1000, 141, ancho=130), _l("Vitality", 900, 400), _l("WYSZUKIWANIE...", 250, 830)]
    reconocidos = [_r(ids, "/m/Reach", "Zasięg", (810, 113, 80, 24), texto="ZASIEG"),
                   _r(ids, "/m/Seeker", "Poszukiwacz", (1000, 141, 130, 24), texto="POSZUKIWACZ"),
                   _r(ids, "/m/Vitality", "Vitality", (900, 400, 160, 24))]
    build = B.separar_build(lineas, reconocidos, _categorias(con), ancho=1920)
    assert [r.nombre for r in build.equipados] == ["Vitality"]
    assert build.capacidad == (51, 68)


def test_mod_en_mayusculas_no_es_una_tarjeta(catalogo):
    con, ids = catalogo
    reconocidos = [_r(ids, "/m/Seeker", "Poszukiwacz", (1000, 400, 130, 24), texto="POSZUKIWACZ")]
    build = B.separar_build([_l("CERCA...", 100, 830)], reconocidos, _categorias(con), ancho=1920)
    assert build.equipados == []


def test_nombre_a_dos_lineas_del_que_solo_casa_una(catalogo):
    """1080p polaco reducida a 720p: "Mroczna" / "Intensyfikacja" salian separadas y la de
    abajo casaba sola con el mod Intensify."""
    con, ids = catalogo
    casador = B.crear_casador(con)
    categorias = _categorias(con)
    lineas = [_l("Mroczna", 305, 473, ancho=90, alto=16), _l("164 Intensyfikacja", 290, 492, ancho=130, alto=16)]
    reconocidos = [_r(ids, "/m/Intensify", "Intensyfikacja", (290, 492, 130, 16), texto="164 Intensyfikacja")]
    salida = B._nombres_a_dos_lineas(lineas, reconocidos, casador, categorias)
    assert [r.item_id for r in salida] == [ids["/m/UmbralIntensify"]]
    # Si lo junto no casa con nada, no se da por bueno ninguno de los dos.
    lineas[0] = _l("Qwerty", 305, 473, ancho=90, alto=16)
    assert B._nombres_a_dos_lineas(lineas, reconocidos, casador, categorias) == []
    # Una linea de otra tarjeta (lejos) o una frase de ayuda no cuentan.
    lineas = [_l("Mroczna", 900, 473, ancho=90, alto=16), _l("Intensyfikacja", 290, 492, ancho=130, alto=16),
              _l("Zwiększa prędkość.", 290, 511, ancho=130, alto=16)]
    reconocidos = [_r(ids, "/m/Intensify", "Intensyfikacja", (290, 492, 130, 16))]
    assert B._nombres_a_dos_lineas(lineas, reconocidos, casador, categorias) == reconocidos
    # Dos mitades sin casar ninguna ("Przejsciowe" / "Wzmocnienie") se prueban juntas.
    lineas = [_l("Przejsciowe", 650, 473, ancho=110, alto=16), _l("Wzmocnienie", 652, 492, ancho=110, alto=16)]
    salida = B._nombres_a_dos_lineas(lineas, [], casador, categorias)
    assert [r.item_id for r in salida] == [ids["/m/Transient"]]


def test_descripcion_de_tarjeta_ampliada_no_se_pega_al_nombre(catalogo):
    """La descripcion va con letra mas pequena: "Vitality" y "Increases Health" no son
    un nombre a dos lineas, y el mod no se tira."""
    con, ids = catalogo
    lineas = [_l("Vitality", 300, 400, ancho=120, alto=26), _l("Increases Health", 290, 430, ancho=140, alto=18)]
    reconocidos = [_r(ids, "/m/Vitality", "Vitality", (300, 400, 120, 26))]
    assert B._nombres_a_dos_lineas(lineas, reconocidos, B.crear_casador(con), _categorias(con)) == reconocidos


def test_la_l_polaca_leida_como_t(catalogo):
    con, ids = catalogo
    casador = B.crear_casador(con)
    item_id, _nombre, puntos = casador.casar("Stalowe Wtokna", B.UMBRAL_MODS)
    assert item_id == ids["/m/SteelFiber"] and puntos == 100


# Lineas reales de una captura en ruso a 1080p (Revenant Prime), tal y como las da el OCR.
RUSO = ["BMECTMOCTb", "IUTbI *", "CWoBoeTeyeHne", "CkopocTbbera", "COCOSHOCTb", "AnTenbHOcTb", "KpaTKoBpeMeHHoe",
        "IuT MecMepa", "CekpeTbl", "OOHYCbIPAHFA", "MbIWeHWe", "CTaJbHoe BoJOKHO", "ApxOHTOBOe", "MoAbl"]


def test_ruso_no_inventa_y_avisa(catalogo):
    con, _ids = catalogo

    class Motor:
        tiempos = {}

        def leer_tira(self, imagen, alto_deteccion=None):
            return [_l(t, 300 + 10 * i, 200 + 40 * i) for i, t in enumerate(RUSO)]

        def leer(self, imagen, lado_minimo=None):
            return []

    import numpy as np
    build = B.leer_build(np.zeros((1080, 1920, 3), np.uint8), Motor(), B.crear_casador(con), _categorias(con))
    assert build.vacia and build.aviso == B.AVISO_CIRILICO and build.idioma == "ru"
    assert build.sin_identificar == []  # los garabatos no se ensenan


def test_pantalla_latina_no_parece_cirilico():
    lineas = [_l(t, 0, 40 * i) for i, t in enumerate(
        ["PrimedSureFooted", "MrocznaWitalnosc", "Schattenhafte Verstarkung", "Archon: Kontinuitat", "Blind Rage",
         "Conversion d'Energie", "BelicosidadeArcana", "Umbral Fiber", "Steel Charge", "Adaptation"])]
    assert not B.parece_cirilico(lineas)
    assert B.parece_cirilico([_l(t, 0, 40 * i) for i, t in enumerate(RUSO)])


def test_releer_cabecera_con_la_capacidad_de_ancla():
    """Con la escala de menu al 75 % o en 16:10 la cabecera cae fuera de las franjas fijas:
    se relee justo encima de "CAPACIDAD"."""
    capacidad = _l("CAPACIDAD", 450, 300, ancho=150, alto=26)
    recortes = B.recortes_de_cabecera([capacidad, _l("5/74", 800, 300, ancho=60, alto=26)], 2560, 1440)
    assert len(recortes) == len(B.FRANJAS_CABECERA) + 1
    y0, y1, x0, x1 = recortes[-1]
    assert y0 < 300 - 26 and y1 <= 300 and x0 == 0 and x1 == 2048


def test_tarjeta_tapada_con_las_palabras_pegadas(catalogo):
    """"rnedFeverStrike" (de "Primed Fever Strike", tapada por delante): no es otro mod."""
    con, ids = catalogo
    tapada = _r(ids, "/m/Vitality", "Vitality", (700, 1000, 160, 24), texto="rnedVitality")
    perdio_una = _r(ids, "/m/Vitality", "Vitality", (900, 1000, 160, 24), texto="itality")
    assert B._cortado_por_delante(tapada)
    assert not B._cortado_por_delante(perdio_una)
