"""La pantalla de recompensas con otro overlay debajo (AlecaFrame): fila, casado y precio.

Las lineas son las que RapidOCR leyo de verdad en un fotograma de 2560x1440 del
usuario afectado (coordenadas dentro de la franja, ya reducidas a 1080p): las
tres tarjetas del juego arriba, los tres nombres de la escuadra en medio (aqui
sustituidos por nombres inventados) y el panel de AlecaFrame abajo repitiendo
los mismos objetos. La tercera tarjeta, "Empunadura De Quassus Prime", es la
que se confundio con "Nikana Prime Empunadura".
"""

from __future__ import annotations

import pytest

from farmadex.captura import comparador
from farmadex.captura.ocr import Casador, Leido, Reconocido, casar_lineas
from farmadex.captura.reliquias import SIN_IDENTIFICAR, Recompensa, elegir_fila, texto_platino

from test_captura import _insertar


@pytest.fixture()
def catalogo_reliquia(con):
    ids = _insertar(con, [
        ("/m/FangPrime", "Fang Prime", "Fang Prime", "Melee", None, None),
        ("/m/FangPrime/Bp", "Blueprint", "Plano", "Melee", "/m/FangPrime", 15),
        ("/m/FangPrime/H", "Handle", "Mango", "Melee", "/m/FangPrime", 25),
        ("/m/OrthosPrime", "Orthos Prime", "Orthos Prime", "Melee", None, None),
        ("/m/OrthosPrime/Bp", "Blueprint", "Plano", "Melee", "/m/OrthosPrime", 45),
        ("/m/QuassusPrime", "Quassus Prime", "Quassus Prime", "Melee", None, None),
        ("/m/QuassusPrime/H", "Handle", "Mango", "Melee", "/m/QuassusPrime", 15),
        ("/m/NikanaPrime", "Nikana Prime", "Nikana Prime", "Melee", None, None),
        ("/m/NikanaPrime/H", "Hilt", "Empunadura", "Melee", "/m/NikanaPrime", 100),
    ])
    return con, ids


def _l(texto, x, y, ancho, alto, conf=0.88):
    return Leido(texto, x, y, ancho, alto, conf)


# Franja de 2048x605 reducida a 1536x454 (factor 0,75): y de cada fila.
LINEAS_F026 = [
    _l("EmpunaduraDeQuassus", 1089, 89, 190, 24, 0.90),  # tarjeta 3, primera linea
    _l("PlanoDeFang Prime", 625, 110, 160, 24, 0.89),  # tarjeta 1
    _l("PlanoDeOrthosPrime", 859, 111, 165, 22, 0.90),  # tarjeta 2
    _l("Prime", 1174, 112, 48, 22, 0.83),  # tarjeta 3, segunda linea
    _l("JugadorUno", 875, 180, 120, 19, 0.91),  # escuadra
    _l("JugadorDos", 895, 206, 90, 21, 0.82),
    _l("JugadorTres", 866, 233, 130, 24, 0.90),
    _l("PlanoDeFangPrime", 643, 344, 140, 16, 0.89),  # panel de AlecaFrame
    _l("PlanoDeOrthosPrime", 886, 344, 150, 15, 0.91),
    _l("EmpunaduraDeQuassusPrime", 1111, 345, 200, 14, 0.90),
    _l("vueling", 1556, 351, 70, 34, 0.81),
]


def test_quassus_no_es_nikana_y_casa_como_mango(catalogo_reliquia):
    con, ids = catalogo_reliquia
    casador = Casador(con)
    # El juego dice "Empunadura" donde el catalogo dice "Mango": es la misma pieza.
    assert casador.casar("EMPUNADURA DE QUASSUS PRIME", 80)[0] == ids["/m/QuassusPrime/H"]
    assert casador.casar("EmpunaduraDeQuassusPrime", 80)[0] == ids["/m/QuassusPrime/H"]
    assert casador.casar("MANGO DE FANG PRIME", 80)[0] == ids["/m/FangPrime/H"]
    # Sin la pieza en el catalogo, lo parecido por palabras genericas NO vale.
    con.execute("DELETE FROM items WHERE unique_name = ?", ("/m/QuassusPrime/H",))
    con.commit()
    casador = Casador(con)
    assert casador.casar("EMPUNADURA DE OUASSUS PRIME", 80)[0] is None
    assert casador.casar("EmpunaduraDeQuassusPrime", 80)[0] is None
    assert casador.casar("EMPUNADURA DE NIKANA PRIME", 80)[0] == ids["/m/NikanaPrime/H"]


def test_se_elige_la_fila_de_tarjetas_del_juego_y_no_el_panel_de_abajo(catalogo_reliquia):
    con, ids = catalogo_reliquia
    con.execute("DELETE FROM items WHERE unique_name = ?", ("/m/QuassusPrime/H",))  # como en el indice real
    con.commit()
    casador = Casador(con)
    encontrados = casar_lineas(LINEAS_F026, casador, 80)
    # El panel de AlecaFrame tambien casa Fang y Orthos: hay copias abajo.
    assert sum(1 for r in encontrados if r.item_id == ids["/m/FangPrime/Bp"]) == 2

    fila = elegir_fila(encontrados, LINEAS_F026, maximo=3)

    assert [r.item_id for r in fila] == [ids["/m/FangPrime/Bp"], ids["/m/OrthosPrime/Bp"], SIN_IDENTIFICAR]
    assert all(r.caja[1] < 150 for r in fila)  # todas en la banda de las tarjetas del juego
    assert fila[2].texto_ocr == "EmpunaduraDeQuassus Prime"
    assert fila[0].caja[0] < fila[1].caja[0] < fila[2].caja[0]


def test_con_la_pieza_en_el_catalogo_salen_las_tres_identificadas(catalogo_reliquia):
    con, ids = catalogo_reliquia
    encontrados = casar_lineas(LINEAS_F026, Casador(con), 80)
    fila = elegir_fila(encontrados, LINEAS_F026, maximo=4)
    assert [r.item_id for r in fila] == [ids["/m/FangPrime/Bp"], ids["/m/OrthosPrime/Bp"], ids["/m/QuassusPrime/H"]]


def test_no_mas_recompensas_que_jugadores(catalogo_reliquia):
    con, ids = catalogo_reliquia
    encontrados = casar_lineas(LINEAS_F026, Casador(con), 80)
    fila = elegir_fila(encontrados, LINEAS_F026, maximo=2)
    assert len(fila) == 2


def test_las_recompensas_de_eelog_mandan_sobre_la_altura(catalogo_reliquia):
    """Si EE.log dio Quassus y solo casa en el panel de abajo... no: la fila con
    mas recompensas conocidas gana, y a igualdad, la de arriba."""
    con, ids = catalogo_reliquia
    encontrados = casar_lineas(LINEAS_F026, Casador(con), 80)
    arriba = elegir_fila(encontrados, LINEAS_F026, conocidas={ids["/m/FangPrime/Bp"]})
    assert arriba[0].caja[1] < 150
    # Una fila inventada mas arriba con un solo objeto NO conocido pierde frente a
    # la fila que contiene lo que EE.log dio.
    ruido = [Reconocido("Nikana Prime Empunadura", ids["/m/NikanaPrime/H"], "Nikana Prime Empunadura", 100.0, (700, 10, 200, 20))]
    lineas = [_l("Nikana Prime Empunadura", 700, 10, 200, 20)] + LINEAS_F026
    fila = elegir_fila(ruido + encontrados, lineas, conocidas={ids["/m/FangPrime/Bp"], ids["/m/OrthosPrime/Bp"]})
    assert ids["/m/NikanaPrime/H"] not in [r.item_id for r in fila]
    assert ids["/m/FangPrime/Bp"] in [r.item_id for r in fila]


def test_sin_identificar_nunca_es_la_mejor_y_el_veredicto_queda_en_duda(catalogo_reliquia):
    con, ids = catalogo_reliquia
    recompensas = [
        Recompensa(ids["/m/FangPrime/Bp"], "Fang Prime Plano", "PlanoDeFangPrime", (0, 0, 10, 10)),
        Recompensa(SIN_IDENTIFICAR, "Sin identificar", "EmpunaduraDeQuassus Prime", (100, 0, 10, 10)),
    ]
    veredicto = comparador.puntuar(recompensas, con, None, None, escuadra=True)
    assert veredicto.mejor == 0
    assert veredicto.seguro is False
    assert recompensas[1].mejor is False
    assert "Quassus" in recompensas[1].nota
    # Todas sin identificar: no hay mejor.
    solo = [Recompensa(SIN_IDENTIFICAR, "Sin identificar", "x y z", (0, 0, 10, 10))]
    assert comparador.puntuar(solo, con, None, None).mejor is None


def test_el_precio_dice_que_criterio_es_y_su_falta_se_ve(catalogo_reliquia):
    con, ids = catalogo_reliquia

    class Orden:
        def __init__(self, platino):
            self.platino = platino

    class Precios:
        error = ""

        def __init__(self, ventas):
            self.ventas = [Orden(p) for p in ventas]

        @property
        def mejor_venta(self):
            return self.ventas[0].platino

        @property
        def mediana_venta(self):
            import statistics
            return statistics.median(o.platino for o in self.ventas[:5])

    precios = {"fang_prime_blueprint": Precios([1, 2, 2, 3, 3])}
    con.execute("UPDATE items SET market_slug = 'fang_prime_blueprint', comerciable = 1 WHERE unique_name = '/m/FangPrime/Bp'")
    con.execute("UPDATE items SET market_slug = 'orthos_prime_blueprint', comerciable = 1 WHERE unique_name = '/m/OrthosPrime/Bp'")
    con.commit()
    recompensas = [
        Recompensa(ids["/m/FangPrime/Bp"], "Fang Prime Plano", "", (0, 0, 10, 10)),
        Recompensa(ids["/m/OrthosPrime/Bp"], "Orthos Prime Plano", "", (0, 0, 10, 10)),
    ]
    comparador.puntuar(recompensas, con, lambda slug: precios.get(slug), None, escuadra=True)
    assert (recompensas[0].platino, recompensas[0].criterio_platino) == (1, "minimo")
    assert texto_platino(recompensas[0]) == "1 platino (venta mas barata)"
    # Orthos no tiene ordenes: la etiqueta lo dice, no parece que valga cero.
    assert recompensas[1].platino is None and recompensas[1].nota

    recompensas = [Recompensa(ids["/m/FangPrime/Bp"], "Fang Prime Plano", "", (0, 0, 10, 10))]
    comparador.puntuar(recompensas, con, lambda slug: precios.get(slug), None, escuadra=False)
    assert (recompensas[0].platino, recompensas[0].criterio_platino) == (2, "mediana")
    assert texto_platino(recompensas[0]) == "2 platino (mediana)"
