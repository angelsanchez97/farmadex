"""Grados de agrietados: la formula de la wiki y la escala de la guia, con numeros."""

import pytest

from farmadex.agrietados import grados


def test_ejemplo_de_la_guia_strun():
    # Guia de agrietados: Strun (escopeta), disposicion 1.4, 3 positivos y 1 negativo,
    # 163.3 % de multidisparo -> +3.94 % sobre el centro -> grado A-.
    minimo, maximo = grados.rango("multishot", "shotgun", 1.4, 3, 1)
    assert round((minimo + maximo) / 2, 1) == 157.1
    assert round(grados.desviacion(163.3, minimo, maximo), 2) == 3.94
    assert grados.grado(163.3, minimo, maximo) == "A-"


def test_rango_de_un_negativo_va_en_negativo_y_ordenado():
    minimo, maximo = grados.rango("magazine_capacity", "rifle", 1.0, 2, 1, negativo=True)
    assert minimo < maximo < 0
    # 50 x 1.0 x -0.495 = -24.75 de centro; entre el 90 y el 110 %.
    assert round(minimo, 3) == -27.225 and round(maximo, 3) == -22.275


def test_negativo_que_quita_menos_tiene_mejor_grado():
    minimo, maximo = grados.rango("magazine_capacity", "rifle", 1.0, 2, 1, negativo=True)
    assert grados.grado(-22.3, minimo, maximo, negativo=True) == "S"
    assert grados.grado(-27.2, minimo, maximo, negativo=True) == "F"
    assert grados.grado(-24.75, minimo, maximo, negativo=True) == "B"


@pytest.mark.parametrize("desv, letra", [(10, "S"), (9.5, "S"), (8, "A+"), (6, "A"), (4, "A-"), (2, "B+"),
                                          (0, "B"), (-2, "B-"), (-4, "C+"), (-6, "C"), (-8, "C-"), (-10, "F")])
def test_escala_de_grados(desv, letra):
    minimo, maximo = 90.0, 110.0  # centro 100
    assert grados.grado(100 + desv, minimo, maximo) == letra


def test_fuera_de_lo_posible_no_tiene_grado():
    minimo, maximo = grados.rango("critical_chance", "rifle", 0.5, 2, 0)
    assert grados.grado(200.0, minimo, maximo) is None
    assert grados.evaluar([("critical_chance", 200.0, False), ("multishot", 40.0, False)], "rifle", 0.5)[0].fuera_de_rango


def test_lo_que_no_puede_salir_en_esa_clase_no_tiene_rango():
    assert grados.rango("multishot", "melee", 1.0, 2, 0) is None
    assert grados.rango("range", "rifle", 1.0, 2, 0) is None
    assert grados.rango("zoom", "shotgun", 1.0, 2, 0) is None
    # Y un reparto imposible (4 positivos) tampoco.
    assert grados.rango("multishot", "rifle", 1.0, 4, 0) is None


def test_evaluar_cuenta_positivos_y_negativos():
    evaluaciones = grados.evaluar(
        [("multishot", 90.0, False), ("critical_chance", 180.0, False), ("recoil", -45.0, True)], "rifle", 1.0
    )
    assert [e.slug for e in evaluaciones] == ["multishot", "critical_chance", "recoil"]
    # 2+1: positivos x1.2375 -> multidisparo centro 111.4; 90 queda por debajo del 90 % -> sin grado.
    assert evaluaciones[0].grado is None
    # Critico centro 185.6: 180 es un -3 % -> B-.
    assert evaluaciones[1].grado == "B-"
    assert evaluaciones[2].negativo and evaluaciones[2].minimo < 0


def test_descomponer_nombre():
    assert grados.descomponer_nombre("Hexa-scidra") == ["status_chance", "slash_damage", "fire_rate_/_attack_speed"]
    assert grados.descomponer_nombre("Critacan") == ["critical_chance", "multishot"]
    assert grados.descomponer_nombre("Lexi-insiata") == ["punch_through", "puncture_damage", "base_damage_/_melee_damage"]
    assert grados.descomponer_nombre("Visicron") == ["base_damage_/_melee_damage", "critical_chance"]
    assert grados.descomponer_nombre("Excalibur") is None
    assert grados.descomponer_nombre("ab") is None


def test_clase_segun_market():
    assert grados.clase_de("zaw", "zaw") == "melee"
    assert grados.clase_de("rifle", "archgun") == "archgun"
    assert grados.clase_de("kitgun", "kitgun") == "pistol"
    assert grados.clase_de("shotgun", "sentinel") == "shotgun"
    assert grados.clase_de("", "") == "rifle"


def test_formatear_valor_como_el_juego():
    assert grados.formatear_valor("multishot", 116.0) == "+116%"
    assert grados.formatear_valor("punch_through", 2.7) == "+2.7m"
    assert grados.formatear_valor("combo_duration", 8.1) == "+8.1s"
    assert grados.formatear_valor("magazine_capacity", -24.75) == "-24.8%"
    assert grados.formatear_valor("channeling_damage", 24.5) == "+24.5"


def test_todos_los_atributos_tienen_prefijo_y_sufijo_distintos():
    prefijos = [a.prefijo for a in grados.ATRIBUTOS]
    sufijos = [a.sufijo for a in grados.ATRIBUTOS]
    assert len(set(prefijos)) == len(prefijos)
    assert len(set(sufijos)) == len(sufijos)
    for a in grados.ATRIBUTOS:
        assert any(v is not None for v in a.base.values()), a.slug
