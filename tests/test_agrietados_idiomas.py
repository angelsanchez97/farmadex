"""Tarjetas de agrietado con el juego en frances y aleman (capturas reales de YouTube, 2021 y
2025), con las lineas tal y como las leyo el OCR:

- Las estadisticas en frances y aleman ("+113,2% de Tir Multiple", "+115.6 % Krit. Chance",
  "Einschlag", "Magazingröße") no se reconocian: la tarjeta quedaba sin evaluar.
- La maestria en frances es "PM 11".
- El dano a una faccion va como multiplicador: "x1,4 points de Dégâts aux Infestés" es
  +40 % y "x0,53 ..." -47 %.
- "+37.4.%": un punto colado delante del "%" dejaba la estadistica pegada a la anterior.
- El arma con su nombre en frances ("Fusil Laser" es el Laser Rifle).
"""

from __future__ import annotations

from farmadex.agrietados import grados
from farmadex.agrietados.lector import ArmaConocida, LectorTarjeta, parsear_texto

ARMAS = [
    ArmaConocida("verglas", "Verglas", "Verglas"),
    ArmaConocida("kuva_chakkhurr", "Kuva Chakkhurr", "Kuva Chakkhurr"),
    ArmaConocida("laser_rifle", "Rifle láser", "Laser Rifle", ("Fusil Laser", "Lasergewehr")),
]


def _lector():
    return LectorTarjeta(ARMAS)


def test_tarjeta_en_frances():
    t = parsear_texto(["Verglas Satitin", "+113,2%deTirMultiple", "+60%deTailleDu Chargeur", "PM 11"], _lector())
    assert t.arma_slug == "verglas" and t.maestria == 11
    assert [(e.slug, e.valor, e.negativo) for e in t.estadisticas] == [
        ("multishot", 113.2, False), ("magazine_capacity", 60.0, False)]
    assert t.fiable


def test_tarjeta_en_aleman_con_una_linea_partida():
    t = parsear_texto(["Kuva ChakkhurrCrit", "fevaton", "+115.6%Krit.Chance", "+37.4.%", "Nachladegeschwindigk",
                       "+87.4%XEinschlag", "-31.4%Magazingro", "MR8"], _lector())
    assert [(e.slug, e.valor, e.negativo) for e in t.estadisticas] == [
        ("critical_chance", 115.6, False), ("reload_speed", 37.4, False), ("impact_damage", 87.4, False),
        ("magazine_capacity", 31.4, True)]
    assert t.fiable


def test_dano_a_faccion_como_multiplicador():
    t = parsear_texto(["Verglas Feva- hexaada", "+47,5%deVitessede Recharge", "+81,3%deChancesde Statut",
                       "xl,39points de Degats auxInfestes", "PM 16"], _lector())
    ultima = t.estadisticas[-1]
    assert (ultima.slug, ultima.valor, ultima.negativo) == ("damage_vs_infested", 39.0, False)
    t = parsear_texto(["Verglas Satitin", "+130,3%deDureede Statut", "x0,53pointsdeDegats auxInfestes"], _lector())
    ultima = t.estadisticas[-1]
    assert (ultima.slug, ultima.valor, ultima.negativo) == ("damage_vs_infested", 47.0, True)


def test_multiplicador_que_no_es_de_faccion_no_se_da_por_bueno():
    t = parsear_texto(["Verglas Satitin", "+60%deTailleDu Chargeur", "x1,4 points de Tir Multiple"], _lector())
    assert t.estadisticas[-1].slug is None and not t.fiable


def test_arma_con_su_nombre_en_frances():
    t = parsear_texto(["Fusil Laser Pura-", "acricron", "+107,3% de Dégâts Critiques"], _lector())
    assert t.arma_slug == "laser_rifle"


def test_alias_de_otros_idiomas_son_atributos_conocidos():
    assert set(grados.ALIAS_IDIOMAS) <= set(grados.POR_SLUG)
    claves = dict(grados.nombres_para_casar())
    assert claves["tir multiple"] == "multishot" and claves["magazingroße"] == "magazine_capacity"
    assert claves["wielostrzat"] == "multishot"  # la "ł" polaca leida como "t"
