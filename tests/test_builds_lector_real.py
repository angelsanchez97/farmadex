"""Lector de la pantalla de mejoras: los fallos vistos en capturas reales de YouTube (2026,
1080p/1440p/4K, castellano e ingles) y su arreglo, sin OCR (lineas ya leidas).

- La caja de busqueda con el cursor delante ("|BUSCAR...", "IBUSCAR.") no se reconocia y
  toda la coleccion salia como equipada.
- Con la caja tapada (camara del streamer, una ayuda abierta, mando sin texto) la
  separacion sale del orden de la derecha ("DRENAJE", "RANK") o del filtro ("TODOS").
- Los nombres de las configuraciones ("Alcance") en la fila de "CAPACIDAD" no son mods.
- El mismo mod o arcano dos veces equipado es su ayuda o la tarjeta ampliada.
- "ned Cryo Rounds" (tarjeta tapada por delante) no es "Cryo Rounds"; "ocus Energy" si
  es "Focus Energy" (el OCR solo perdio una letra).
- "EMPTY ARCANE SLOT" no es "Arcane Tempo".
- Con la cabecera tapada en parte se relee la franja de arriba sola.
- El nombre a dos lineas de la tarjeta ampliada, con su descripcion debajo.
"""

from __future__ import annotations

import numpy as np
import pytest

from farmadex.captura import builds as B
from farmadex.captura.ocr import Leido, Reconocido

from test_captura import _insertar

ITEMS = [
    ("/m/Vitality", "Vitality", "Vitalidad", "Mods"),
    ("/m/Flow", "Flow", "Flujo", "Mods"),
    ("/m/Reach", "Reach", "Alcance", "Mods"),
    ("/m/Cryo", "Cryo Rounds", "Munición criogénica", "Mods"),
    ("/m/PrimedCryo", "Primed Cryo Rounds", "Munición criogénica Prime", "Mods"),
    ("/m/Focus", "Focus Energy", "Energía concentrada", "Mods"),
    ("/m/Deconstructor", "Synth Deconstruct", "Deconstrucción de sintetizador", "Mods"),
    ("/a/Tempo", "Arcane Tempo", "Tempo Arcano", "Arcanes"),
    ("/a/Energize", "Arcane Energize", "Energizar Arcano", "Arcanes"),
    ("/w/Rhino", "Rhino Prime", "Rhino Prime", "Warframes"),
    ("/x/Regulators", "Regulators Prime", "Reguladoras Prime", "Misc"),
]


@pytest.fixture()
def catalogo(con):
    ids = _insertar(con, [(u, en, es, cat, None, None) for u, en, es, cat in ITEMS])
    con.execute("UPDATE items SET tipo = 'Exalted Weapon' WHERE unique_name = '/x/Regulators'")
    con.commit()
    return con, ids


def _l(texto, x, y, ancho=160, alto=24, conf=0.9):
    return Leido(texto, x, y, ancho, alto, conf)


def _r(ids, unico, nombre, caja, texto=None):
    return Reconocido(texto or nombre, ids[unico], nombre, 100.0, caja)


def _categorias(con):
    return dict(con.execute("SELECT id, categoria FROM items"))


def test_buscar_con_el_cursor_delante():
    for texto in ("|BUSCAR...", "IBUSCAR.", "BUSCAR..", "SEARCH...", "[BUSCAR"):
        assert B.RE_BUSCAR.match(texto), texto


@pytest.mark.parametrize("separador", [
    _l("IBUSCAR.", 130, 845), _l("DRENAJE", 1480, 825), _l("RANK", 1870, 848, ancho=60), _l("TODOS", 1230, 800, alto=30),
])
def test_separacion_sin_la_caja_de_busqueda(catalogo, separador):
    con, ids = catalogo
    lineas = [_l("Vitalidad", 900, 400), _l("Flujo", 900, 1000), separador]
    reconocidos = [_r(ids, "/m/Vitality", "Vitalidad", (900, 400, 160, 24)), _r(ids, "/m/Flow", "Flujo", (900, 1000, 160, 24))]
    build = B.separar_build(lineas, reconocidos, _categorias(con), ancho=2560)
    assert [r.nombre for r in build.equipados] == ["Vitalidad"]
    assert [r.nombre for r in build.coleccion] == ["Flujo"]


def test_filtro_centrado_arriba_de_la_pantalla_no_separa(catalogo):
    con, _ids = catalogo
    assert B.linea_separadora([_l("TODOS", 1230, 100)], 2560, 1440) is None


def test_configuraciones_de_la_fila_de_capacidad_no_son_mods(catalogo):
    con, ids = catalogo
    lineas = [_l("CAPACIDAD", 210, 150, ancho=110), _l("2/74", 700, 150, ancho=60), _l("Alcance", 1100, 152),
              _l("Rhinnio Coleman", 1500, 152), _l("Vitalidad", 900, 400), _l("BUSCAR...", 200, 830)]
    reconocidos = [_r(ids, "/m/Reach", "Alcance", (1100, 152, 160, 24)),
                   _r(ids, "/m/Vitality", "Vitalidad", (900, 400, 160, 24))]
    build = B.separar_build(lineas, reconocidos, _categorias(con), ancho=2560)
    assert [r.nombre for r in build.equipados] == ["Vitalidad"]
    assert build.capacidad == (2, 74)
    assert "Rhinnio Coleman" not in build.sin_identificar


def test_mismo_mod_o_arcano_repetido_es_su_ayuda(catalogo):
    con, ids = catalogo
    reconocidos = [_r(ids, "/m/Vitality", "Vitalidad", (900, 400, 160, 24)),
                   _r(ids, "/m/Vitality", "Vitalidad", (1300, 500, 300, 30)),
                   _r(ids, "/a/Energize", "Energizar Arcano", (2200, 300, 160, 24)),
                   _r(ids, "/a/Energize", "ENERGIZAR ARCANO", (1600, 220, 300, 30)),
                   _r(ids, "/m/Flow", "Flujo", (400, 1000, 160, 24)), _r(ids, "/m/Flow", "Flujo", (700, 1000, 160, 24))]
    build = B.separar_build([_l("BUSCAR...", 200, 830)], reconocidos, _categorias(con), ancho=2560)
    assert len(build.equipados) == 1 and len(build.arcanos) == 1
    assert len(build.coleccion) == 2  # en la coleccion si puede haber copias


def test_tarjeta_tapada_por_delante_no_inventa(catalogo):
    con, ids = catalogo
    reconocidos = [_r(ids, "/m/Cryo", "Cryo Rounds", (700, 1000, 160, 24), texto="ned Cryo Rounds"),
                   _r(ids, "/m/Focus", "Focus Energy", (900, 1000, 160, 24), texto="ocus Energy"),
                   _r(ids, "/m/Cryo", "Cryo Rounds", (1100, 1000, 160, 24), texto="16r Cryo Rounds")]
    build = B.separar_build([_l("SEARCH...", 200, 830)], reconocidos, _categorias(con), ancho=2560)
    assert [r.texto_ocr for r in build.coleccion] == ["ocus Energy", "16r Cryo Rounds"]
    assert "ned Cryo Rounds" in build.sin_identificar


def test_hueco_de_arcano_vacio(catalogo):
    con, ids = catalogo
    reconocidos = [_r(ids, "/a/Tempo", "Arcane Tempo", (2200, 300, 160, 24), texto="EMPTYARCANE")]
    build = B.separar_build([], reconocidos, _categorias(con), ancho=2560)
    assert build.arcanos == []
    assert B.RE_HUECO_VACIO.search("RANURA DE ARCANO VACÍA") and not B.RE_HUECO_VACIO.search("Vacuum")


def test_rango_delante_no_sale_en_sin_identificar(catalogo):
    con, _ids = catalogo
    build = B.separar_build([_l("16Y Zzzzzz Qqqq", 900, 1000), _l("BUSCAR...", 200, 830)], [], _categorias(con), ancho=2560)
    assert build.sin_identificar == ["Zzzzzz Qqqq"]
    build = B.separar_build([_l("Gana 1 Sobreguardia por", 900, 700), _l("Sobreguardia.", 900, 730),
                             _l("Cadencia De Fuego", 200, 300), _l("BUSCAR...", 200, 830)], [], _categorias(con), ancho=2560)
    assert build.sin_identificar == []  # frase de una ayuda y estadistica del panel izquierdo


class MotorFalso:
    """leer_tira da la pantalla con la cabecera rota; leer (la franja sola) la da entera."""

    tiempos = {"detector": 0.1}

    def __init__(self, franja: list[Leido]):
        self.franja = franja
        self.franjas_leidas = 0

    def leer_tira(self, imagen, alto_deteccion=None):
        return [_l("E[30]", 700, 30, ancho=120, alto=60), _l("Vitalidad", 900, 400), _l("BUSCAR...", 200, 830)]

    def leer(self, imagen, lado_minimo=None):
        self.franjas_leidas += 1
        self.tiempos = {"detector": 9}
        return self.franja


def test_cabecera_tapada_se_relee_sola(catalogo):
    con, ids = catalogo
    casador = B.crear_casador(con)
    motor = MotorFalso([_l("FehaRAS/RHINO PRIME [30]", 0, 20, ancho=900, alto=60)])
    build = B.leer_build(np.zeros((1440, 2560, 3), np.uint8), motor, casador, _categorias(con))
    assert build.equipo is not None and build.equipo.item_id == ids["/w/Rhino"]
    assert build.tiempos.get("detector") == 0.1  # el registro sigue con los tiempos de la lectura grande
    # Lo que va tras la barra tiene que casar con un warframe o un arma: nunca se adivina.
    motor = MotorFalso([_l("FehaRAS/ZZZZ QQQQ [30]", 0, 20, ancho=900, alto=60)])
    build = B.leer_build(np.zeros((1440, 2560, 3), np.uint8), motor, casador, _categorias(con))
    # Se prueban las franjas fijas y la que sale del trozo leido ("E[30]"), y ya.
    recortes = B.recortes_de_cabecera(motor.leer_tira(None), 2560, 1440)
    assert build.equipo is None and motor.franjas_leidas == len(recortes) == len(B.FRANJAS_CABECERA) + 1


def test_armas_exaltadas_son_equipo(catalogo):
    con, ids = catalogo
    casador = B.crear_casador(con)
    motor = MotorFalso([_l("FRAS/REGULADORAS PRIME[30]", 0, 20, ancho=900, alto=60)])
    build = B.leer_build(np.zeros((1440, 2560, 3), np.uint8), motor, casador, _categorias(con))
    assert build.equipo is not None and build.equipo.item_id == ids["/x/Regulators"]


def test_nombre_a_dos_lineas_de_la_tarjeta_ampliada(catalogo):
    con, ids = catalogo
    casador = B.crear_casador(con)
    lineas = [_l("9Y", 1990, 200, ancho=40), _l("Deconstruccion ae", 1990, 230, ancho=260, alto=30),
              _l("sintetizador", 2020, 262, ancho=200, alto=30), _l("Los enemigos heridos", 2000, 300, ancho=240),
              _l("por los companeros", 2000, 328, ancho=240)]
    extra = B._tarjetas_ampliadas(lineas, [], casador, _categorias(con))
    assert [r.item_id for r in extra] == [ids["/m/Deconstructor"]]
    # Una descripcion cualquiera no casa con nada con tanta seguridad.
    lineas = [_l("Voruna nunca pelea sola", 300, 600, ancho=300), _l("misiones manten las", 300, 630, ancho=300),
              _l("para invocarla", 300, 660, ancho=300)]
    assert B._tarjetas_ampliadas(lineas, [], casador, _categorias(con)) == []
