"""Lectura de la pantalla de mejoras (Build) y de tarjetas de agrietado con el OCR de verdad.

Las pantallas son sinteticas (tests/sintetico_builds.py), calcadas de la captura real
de la wiki a 1920x1080. Las capturas reales bajadas de internet no van en el
repositorio; el banco que las mide es herramientas/banco_builds.py.
"""

from __future__ import annotations

import pytest

from farmadex.captura import builds as B
from farmadex.captura.agrietados import leer_tarjeta
from farmadex.captura.ocr import Leido, MotorOCR, Reconocido
from farmadex.agrietados.lector import ArmaConocida, LectorTarjeta

import sintetico_builds as SINT
from test_captura import _insertar

MODS = [
    ("/m/Vitality", "Vitality", "Vitalidad", "Mods"),
    ("/m/Redirection", "Redirection", "Redirección", "Mods"),
    ("/m/Intensify", "Intensify", "Intensificar", "Mods"),
    ("/m/Continuity", "Continuity", "Continuidad", "Mods"),
    ("/m/Stretch", "Stretch", "Estirar", "Mods"),
    ("/m/Streamline", "Streamline", "Optimizar", "Mods"),
    ("/m/Flow", "Flow", "Flujo", "Mods"),
    ("/m/Rush", "Rush", "Prisa", "Mods"),
    ("/m/SteelFiber", "Steel Fiber", "Fibra de acero", "Mods"),
    ("/m/HeavyImpact", "Heavy Impact", "Impacto pesado", "Mods"),
    ("/m/LightningRod", "Lightning Rod", "Pararrayos", "Mods"),
    ("/m/Reach", "Reach", "Alcance", "Mods"),
    ("/m/Equilibrium", "Equilibrium", "Equilibrio", "Mods"),
    ("/m/ThiefsWit", "Thief's Wit", "Astucia del ladrón", "Mods"),
]
OTROS = [
    ("/w/Excalibur", "Excalibur", "Excalibur", "Warframes"),
    ("/w/ExcaliburUmbra", "Excalibur Umbra", "Excalibur Umbra", "Warframes"),
    ("/w/Hydroid", "Hydroid", "Hydroid", "Warframes"),
    ("/a/Energize", "Arcane Energize", "Energizar Arcano", "Arcanes"),
]


@pytest.fixture()
def catalogo(con):
    ids = _insertar(con, [(u, en, es, cat, None, None) for u, en, es, cat in MODS + OTROS])
    for mod in ("/m/Vitality", "/m/Reach"):
        con.execute("UPDATE items SET tipo = 'Warframe Mod' WHERE unique_name = ?", (mod,))
    con.commit()
    return con, ids


@pytest.fixture(scope="module")
def motor():
    return MotorOCR()


def _l(texto, x, y, ancho=120, alto=20, conf=0.9):
    return Leido(texto, x, y, ancho, alto, conf)


def test_separar_build_sin_ocr():
    categorias = {1: "Warframes", 2: "Mods", 3: "Mods", 4: "Arcanes", 5: "Mods"}
    lineas = [
        _l("UPGRADES/EXCALIBUR[30]", 190, 48, 500, 34),
        _l("Range", 106, 376),  # panel de estadisticas de la izquierda
        _l("Vitality", 700, 398),
        _l("Arcane Energize", 900, 260),
        _l("SEARCH...", 106, 638),
        _l("Flow", 700, 750),
        _l("Reach", 120, 750),  # abajo, en la coleccion, aunque este a la izquierda
        _l("CONFIG A", 900, 124),
        _l("Zzzzz", 900, 900),
    ]
    reconocidos = [
        Reconocido("Range", 5, "Alcance", 100.0, (106, 376, 120, 20)),
        Reconocido("Vitality", 2, "Vitality", 100.0, (700, 398, 120, 20)),
        Reconocido("Arcane Energize", 4, "Arcane Energize", 100.0, (900, 260, 120, 20)),
        Reconocido("Flow", 3, "Flow", 100.0, (700, 750, 120, 20)),
        Reconocido("Reach", 5, "Alcance", 100.0, (120, 750, 120, 20)),
    ]
    equipo = Reconocido("EXCALIBUR", 1, "Excalibur", 100.0, (190, 48, 500, 34))
    build = B.separar_build(lineas, reconocidos, categorias, equipo, ancho=1920)
    assert build.equipo.nombre == "Excalibur" and build.equipo_texto == "EXCALIBUR"
    assert [r.nombre for r in build.equipados] == ["Vitality"]
    assert [r.nombre for r in build.arcanos] == ["Arcane Energize"]
    assert [r.nombre for r in build.coleccion] == ["Alcance", "Flow"]  # de izquierda a derecha
    # "Range" del panel izquierdo no cuenta; "CONFIG A" es interfaz; "Zzzzz" no se reconocio.
    assert build.sin_identificar == ["Zzzzz"]
    assert not build.vacia


def test_cabecera_en_varios_idiomas():
    for texto, esperado in (("UPGRADES / EXCALIBUR [30]", "EXCALIBUR"), ("MEJORAS/HYDROID[30]", "HYDROID"),
                            ("AMÉLIORATIONS / BRATON PRIME [30]", "BRATON PRIME"), ("Vitality", "")):
        nombre, _ = B.cabecera([_l(texto, 0, 0)])
        assert nombre == esperado, texto


def test_filtro_deja_fuera_piezas_y_agrietados_genericos():
    assert not B._filtro_build("Warframes", "Componente", "/Lotus/Types/Recipes/WarframeRecipes/AshChassis")
    assert not B._filtro_build("Mods", "Rifle Riven Mod", "/Lotus/Upgrades/Mods/Randomized/LotusRifleRandomModRare")
    assert B._filtro_build("Mods", "Warframe Mod", "/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod")


@pytest.mark.parametrize("idioma", ["en", "es"])
def test_pantalla_sintetica_de_mejoras(catalogo, motor, idioma):
    con, ids = catalogo
    casador = B.crear_casador(con)
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    nombres = dict(con.execute("SELECT nombre_en, nombre_es FROM items"))
    equipados_en = ["Vitality", "Redirection", "Intensify", "Continuity", "Stretch", "Streamline", "Equilibrium", "Thief's Wit"]
    coleccion_en = ["Flow", "Rush", "Steel Fiber", "Heavy Impact", "Lightning Rod", "Reach"]
    traducir = (lambda n: nombres[n]) if idioma == "es" else (lambda n: n)
    imagen = SINT.pintar_arsenal("Excalibur", [traducir(n) for n in equipados_en], [traducir(n) for n in coleccion_en],
                                 idioma=idioma, semilla=1)
    build = B.leer_build(imagen, motor, casador, categorias)
    assert build.equipo is not None and build.equipo.item_id == ids["/w/Excalibur"]
    esperados = {ids[u] for u, en, _, _ in MODS if en in equipados_en + coleccion_en}
    leidos = {r.item_id for r in build.equipados + build.coleccion}
    assert leidos <= esperados, [r.nombre for r in build.equipados + build.coleccion]  # cero falsos
    assert len(leidos & esperados) >= len(esperados) * 0.8
    assert {r.item_id for r in build.equipados} <= {ids[u] for u, en, _, _ in MODS if en in equipados_en}
    assert {r.item_id for r in build.coleccion} <= {ids[u] for u, en, _, _ in MODS if en in coleccion_en}
    # Las palabras de la interfaz no se cuelan como "sin identificar" salvo las que no se
    # sabe leer ("CONFIG A"); nunca un nombre de mod ya reconocido.
    for texto in build.sin_identificar:
        assert texto.lower() not in {r.nombre.lower() for r in build.equipados + build.coleccion}


@pytest.fixture(scope="module")
def lector_tarjetas():
    return LectorTarjeta([
        ArmaConocida("rubico", "Rubico", "Rubico"),
        ArmaConocida("rubico_prime", "Rubico Prime", "Rubico Prime"),
        ArmaConocida("soma", "Soma", "Soma"),
        ArmaConocida("dual_cestra", "Dual Cestra", "Dual Cestra"),
        ArmaConocida("boar", "Boar", "Boar"),
        ArmaConocida("bo", "Bo", "Bo"),
    ])


@pytest.mark.parametrize("caso", [
    # (arma, nombre, estadisticas como las pinta el juego, en dos lineas, idioma)
    ("Rubico", "Crita-acritis", [("+", 95.2, "Critical Chance"), ("+", 110.4, "Critical Damage"),
                                 ("+", 83.1, "Status Chance"), ("-", 31.5, "Damage to Corpus")], False, "en"),
    ("Dual Cestra", "Visitak", [("+", 380.3, "Damage"), ("+", 77.7, "Reload Speed"), ("-", 30.0, "Damage to Grineer")], True, "en"),
    ("Soma", "Hexa-visisus", [("+", 82.6, "Cortante"), ("+", 71.2, "Probabilidad de estado"), ("+", 130.4, "Daño")], False, "es"),
])
def test_tarjeta_sintetica_con_ocr(motor, lector_tarjetas, caso):
    arma, nombre, estadisticas, dos_lineas, _ = caso
    # Sin "veces variado": el icono sintetico (un circulo) no siempre se lee; en las
    # capturas reales el icono del juego sale como "O" y se lee bien (banco_agrietados).
    imagen = SINT.pintar_tarjeta_agrietado(arma, nombre, estadisticas, maestria=12, variado=None, en_dos_lineas=dos_lineas, semilla=2)
    tarjeta = leer_tarjeta(imagen, motor, lector_tarjetas)
    assert tarjeta.arma_nombre == arma, tarjeta
    assert tarjeta.nombre == nombre
    assert [(e.valor, e.negativo) for e in tarjeta.estadisticas] == [(v, s == "-") for s, v, _ in estadisticas]
    assert all(e.slug for e in tarjeta.estadisticas), tarjeta.estadisticas
    assert tarjeta.maestria == 12
    assert tarjeta.fiable, tarjeta.avisos


# --- sin separador: la caja de buscar, el orden y el filtro tapados ------------------------

def _pantalla_sin_separador(con_equipados=True, alto=1440):
    """Como es_1440_mesa_a (captura real) sin "BUSCAR"/"ORDENAR"/"TODOS": aura y exilus a
    y=260, dos filas de cuatro a y=490 y y=674, y la coleccion en dos filas desde y=916."""
    from farmadex.captura.ocr import Leido, Reconocido
    lineas = [Leido("CAPACIDAD", 206, 125, 180, 32, 0.9), Leido("MESA PRIME", 700, 40, 300, 40, 0.9)]
    rec, cats, n = [], {}, 100

    def mod(y, x, alto_caja=31):
        nonlocal n
        n += 1
        cats[n] = "Mods"
        rec.append(Reconocido(f"Mod {n}", n, f"Mod {n}", 100.0, (x, y, 230, alto_caja)))
        return n

    equipados = []
    if con_equipados:
        equipados += [mod(260, 1257, 80), mod(260, 1580, 80)]
        equipados += [mod(490, x) for x in (910, 1232, 1566, 1909)]
        equipados += [mod(674, x) for x in (913, 1290, 1586, 1936)]
    coleccion = [mod(965, x) for x in (605, 1290, 1630, 1934)] + [mod(916, 934, 97)]
    coleccion += [mod(1145, x) for x in (594, 914, 1249, 1596, 1954, 2296)]
    return lineas, rec, cats, set(equipados), set(coleccion)


def test_sin_separador_el_corte_sale_de_las_filas():
    lineas, rec, cats, equipados, coleccion = _pantalla_sin_separador()
    build = B.separar_build(lineas, rec, cats, ancho=2560, alto=1440)
    assert {r.item_id for r in build.equipados} == equipados
    assert {r.item_id for r in build.coleccion} == coleccion
    assert build.separador == "huecos" and not build.aviso


def test_sin_separador_y_sin_equipados_todo_a_la_coleccion_con_aviso():
    # Antes toda la coleccion contaba como equipada (22/0) y se evaluaba esa "build".
    lineas, rec, cats, _, coleccion = _pantalla_sin_separador(con_equipados=False)
    build = B.separar_build(lineas, rec, cats, ancho=2560, alto=1440)
    assert not build.equipados
    assert {r.item_id for r in build.coleccion} == coleccion
    assert build.separador == "" and build.aviso == B.AVISO_SIN_SEPARADOR


def test_con_caja_de_buscar_no_cambia_nada():
    from farmadex.captura.ocr import Leido
    lineas, rec, cats, equipados, coleccion = _pantalla_sin_separador()
    lineas.append(Leido("BUSCAR...", 200, 830, 150, 30, 0.9))
    build = B.separar_build(lineas, rec, cats, ancho=2560, alto=1440)
    assert {r.item_id for r in build.equipados} == equipados
    assert build.separador == "buscar"


def test_tarjeta_enorme_se_reduce_antes_del_ocr():
    """Un recuadro mayor que el de una pantalla 4K se reduce: el OCR con entradas enormes
    se quedaba con cientos de MB (autoprueba, flujo agrietado)."""
    import numpy as np

    from farmadex.captura.agrietados import ALTO_MAXIMO_LECTURA

    vistos = []

    class Motor:
        def leer(self, imagen):
            vistos.append(imagen.shape[:2])
            return []

    class Lector:
        def leer(self, lineas, **_relecturas):
            return lineas

    leer_tarjeta(np.zeros((2736, 2016, 3), np.uint8), Motor(), Lector())
    leer_tarjeta(np.zeros((1000, 700, 3), np.uint8), Motor(), Lector())
    assert vistos[0][0] == ALTO_MAXIMO_LECTURA
    assert vistos[1] == (1000, 700)
