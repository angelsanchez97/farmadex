"""Interpretacion de la tarjeta de un agrietado a partir de texto ya leido (sin OCR).

Las lineas de aqui calcan lo que RapidOCR leyo de las tarjetas reales de la wiki
(ver herramientas/banco_agrietados.py): signos que se pierden, "%" leido como
"96", iconos convertidos en letras ("*Cold", "WHeat"), nombres pegados al arma.
"""

import json

import pytest

from farmadex.agrietados import mercado
from farmadex.agrietados.lector import ArmaConocida, LectorTarjeta, parsear_texto

from conftest import FIXTURES


@pytest.fixture(scope="module")
def lector():
    datos = json.load(open(FIXTURES / "market_riven_weapons.json", encoding="utf-8"))
    armas = mercado.analizar_armas(datos)
    return LectorTarjeta([ArmaConocida(a.slug, a.nombre_en, a.nombre_en) for a in armas])


def _stats(tarjeta):
    return [(e.slug, e.valor, e.negativo) for e in tarjeta.estadisticas]


def test_tarjeta_completa_con_signo_perdido_en_el_negativo(lector):
    t = parsear_texto(["18", "Aklex Lexi-insiata", "+116%Puncture", "+190%Damage", "+2.7PunchThrough",
                       "32.5%Damageto", "Infested", "MR8"], lector)
    assert t.arma_slug == "aklex"
    assert t.nombre == "Lexi-insiata"
    assert _stats(t) == [("puncture_damage", 116.0, False), ("base_damage_/_melee_damage", 190.0, False),
                         ("punch_through", 2.7, False), ("damage_vs_infested", 32.5, True)]
    assert t.maestria == 8
    assert t.fiable, t.avisos


def test_nombre_pegado_al_arma_y_maestria_pegada_a_la_estadistica(lector):
    t = parsear_texto(["181", "SomaHexa-visisus", "+82.6%Cslash", "+71.2%StatusChance", "+130.4%Damage MASTERY= 11"], lector)
    assert t.arma_slug == "soma"
    assert t.nombre == "Hexa-visisus"
    assert [s for s, _, _ in _stats(t)] == ["slash_damage", "status_chance", "base_damage_/_melee_damage"]
    assert t.maestria == 11
    assert t.fiable, t.avisos


def test_erratas_tipicas_del_ocr(lector):
    t = parsear_texto(["Glaxion", "Lexi-igniata", "+212.4%Damage", "+117.7966Heat", "+3.3PunchThrough",
                       "49.29AmmoMaximum", "MR10"], lector)
    assert _stats(t) == [("base_damage_/_melee_damage", 212.4, False), ("heat_damage", 117.7, False),
                         ("punch_through", 3.3, False), ("ammo_maximum", 49.2, True)]
    assert t.fiable, t.avisos
    t = parsear_texto(["Penta Heraata", "+86.9%Zo0m", "+237.1%Damage", "60.9%StatusDuration", "03", "MR", "16"], lector)
    assert [s for s, _, _ in _stats(t)] == ["zoom", "base_damage_/_melee_damage", "status_duration"]
    assert t.estadisticas[-1].negativo
    assert t.variado == 3


def test_cero_leido_como_o(lector):
    t = parsear_texto(["Flux Rifle", "Lexi-argidex", "+6.7% Damage to", "Grineer", "+13.2%StatusChance",
                       "+o.5 Punch Through", "-16.5% Slash", "MR14"], lector)
    assert _stats(t) == [("damage_vs_grineer", 6.7, False), ("status_chance", 13.2, False),
                         ("punch_through", 0.5, False), ("slash_damage", 16.5, True)]
    assert t.fiable, t.avisos


def test_arma_y_nombre_en_dos_lineas_y_variado(lector):
    t = parsear_texto(["18", "Aksomati", "Ampi-saticron", "+132.8%Multishot", "+164.4% CriticalChance",
                       "+100.8%Amm0", "Maximum", "-118.8%Puncture", "MR8", "O11"], lector)
    assert t.arma_slug == "aksomati" and t.nombre == "Ampi-saticron"
    assert _stats(t)[2] == ("ammo_maximum", 100.8, False)
    assert t.estadisticas[3].negativo and t.variado == 11 and t.maestria == 8


def test_en_castellano(lector):
    t = parsear_texto(["Rubico Crita-acritis", "+95.2% Probabilidad crítica", "+110.4% Daño crítico",
                       "+83.1% Daño crítico", "-31.5% Daño a Corpus", "RM 12"], lector)
    assert t.arma_slug == "rubico"
    assert [s for s, _, _ in _stats(t)] == ["critical_chance", "critical_damage", "critical_damage", "damage_vs_corpus"]
    assert t.estadisticas[3].negativo and t.maestria == 12


def test_velada_no_tiene_estadisticas(lector):
    t = parsear_texto(["???", "Rifle Riven Mod", "Kill 5 enemies while", "sliding without an ally", "0/5", "VEILED"], lector)
    assert t.velado and not t.estadisticas and not t.fiable


def test_sin_nombre_y_sin_signo_queda_en_duda(lector):
    # Tres estadisticas, ninguna con "-" y el nombre no se leyo: puede ser 3+0 o 2+1.
    t = parsear_texto(["Boar", "+125.6%WeaponRecoil", "+129.4%StatusChance", "48.1%Multishot", "MR12"], lector)
    assert t.arma_slug == "boar"
    assert not t.fiable
    assert any("signo" in a for a in t.avisos)


def test_el_nombre_decide_que_hay_negativo(lector):
    # "Hexamag" son dos positivas (estado y retroceso): la tercera sin signo es la negativa.
    t = parsear_texto(["Boar Hexamag", "125.6%WeaponRecoil", "+129.4%StatusChance", "48.1%Multishot", "MR12"], lector)
    assert [n for _, _, n in _stats(t)] == [False, False, True]
    assert t.fiable, t.avisos


def test_nombre_que_no_cuadra_avisa(lector):
    t = parsear_texto(["Tonkor Critacan", "+161.7%CriticalChance", "+92.9%Damage", "MASTERY 12"], lector)
    assert not t.fiable
    assert any("no cuadra" in a for a in t.avisos)


def test_arma_ambigua_no_se_decide(lector):
    # "Bor" esta a una letra de "Bo" y de "Boar".
    assert lector._casar_arma("Bor") is None
    assert lector._casar_arma("Rubico").slug == "rubico"  # el mercado solo lista el arma base
    assert lector._casar_arma("DualCestra").slug == "dual_cestra"


def test_estadistica_desconocida_no_se_inventa(lector):
    t = parsear_texto(["Dread Critatis", "+110.3%CriticalDamage", "+150.8%CriticalChance", "+204.2%Channeling", "MR12"], lector)
    assert t.estadisticas[2].slug is None and t.estadisticas[2].valor == 204.2
    assert not t.fiable
    assert any("sin identificar" in a for a in t.avisos)


def test_valor_disparatado_queda_pero_no_fiable(lector):
    # "+91.3%" leido como "f913%": el numero es imposible y la evaluacion lo dira; aqui
    # solo se comprueba que no se descarta ni se arregla a ojo.
    t = parsear_texto(["Grinlok Mantides", "+45.4%Damageto", "corpus", "f913%StatusDuration", "MASTERY9"], lector)
    assert _stats(t) == [("damage_vs_corpus", 45.4, False), ("status_duration", 913.0, False)]
    assert t.maestria == 9
    assert not t.fiable and any("imposibles" in a for a in t.avisos)
