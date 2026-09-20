"""Escaneo del perfil por OCR: lectura de Perfil > Equipamiento, fusion y herramienta.

Las pruebas con OCR de verdad usan pantallas sinteticas (sintetico_perfil.py) y,
cuando estan en disco, las capturas reales del usuario en
tests/fixtures/capturas_perfil/, que son la medida que cuenta.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from farmadex import perfil as P
from farmadex.captura import perfil_equipo as PE
from farmadex.captura.ocr import Leido, MotorOCR
from farmadex.estado import usuario_db

from conftest import FIXTURES
from sintetico_perfil import pintar_cabecera_perfil, pintar_pagina

CAPTURAS = FIXTURES / "capturas_perfil"

# (unique_name, nombre_en, nombre_es, categoria, tipo): lo que sale en las capturas reales
# mas algun vecino que se le parece, para que el casado tenga con que confundirse.
ITEMS = [
    ("/Lotus/Powersuits/Ninja/Ninja", "Ash", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Ninja/NinjaPrimeX", "Ash Prime", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Brawler/Brawler", "Atlas", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Brawler/BrawlerPrime", "Atlas Prime", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Banshee/Banshee", "Banshee", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Banshee/BansheePrime", "Banshee Prime", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Pacifist/Pacifist", "Baruuk", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Pacifist/PacifistPrime", "Baruuk Prime", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Caliban/Caliban", "Caliban", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Caliban/CalibanPrime", "Caliban Prime", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Dragon/Dragon", "Chroma", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Dragon/DragonPrime", "Chroma Prime", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Citrine/Citrine", "Citrine", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Cyte09/Cyte09", "Cyte-09", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Dagath/Dagath", "Dagath", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Dante/Dante", "Dante", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/Excalibur/Excalibur", "Excalibur", None, "Warframes", "Warframe"),
    ("/Lotus/Powersuits/EntratiMech/NechroTech", "Voidrig", None, "Warframes", "Necramech"),
    ("/Lotus/Weapons/Tenno/Rifle/Acceltra", "Acceltra", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/AcceltraPrime", "Acceltra Prime", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/Aeolak", "Aeolak", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/Afentis", "Afentis", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/AfentisPrime", "Afentis Prime", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/Alternox", "Alternox", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/AlternoxPrime", "Alternox Prime", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/Ambassador", "Ambassador", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/Amprex", "Amprex", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/Argonak", "Argonak", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Shotgun/Astilla", "Astilla", None, "Primary", "Shotgun"),
    ("/Lotus/Weapons/Tenno/Shotgun/AstillaPrime", "Astilla Prime", None, "Primary", "Shotgun"),
    ("/Lotus/Weapons/Tenno/Bows/Attica", "Attica", None, "Primary", "Bow"),
    ("/Lotus/Weapons/Tenno/Rifle/AX52", "AX-52", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/Basmu", "Basmu", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/CodaBassocyst", "Coda Bassocyst", "Bassocyst Coda", "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Rifle/StartingRifle", "Braton", None, "Primary", "Rifle"),
    ("/Lotus/Weapons/Tenno/Pistol/Hikou", "Hikou", None, "Secondary", "Throwing"),
    ("/Lotus/Weapons/Tenno/Pistol/HikouPrime", "Hikou Prime", None, "Secondary", "Throwing"),
    ("/Lotus/Weapons/Tenno/Pistol/Hystrix", "Hystrix", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/HystrixPrime", "Hystrix Prime", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/Knell", "Knell", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/KnellPrime", "Knell Prime", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Grineer/Pistol/Kohmak", "Kohmak", None, "Secondary", "Shotgun Sidearm"),
    ("/Lotus/Weapons/Grineer/Pistol/TwinKohmak", "Twin Kohmak", "Kohmak Gemelas", "Secondary", "Dual Shotguns"),
    ("/Lotus/Weapons/Tenno/Pistol/Kompressa", "Kompressa", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/KompressaPrime", "Kompressa Prime", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Corpus/Pistol/Kraken", "Kraken", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Grineer/Pistol/KuvaKraken", "Kuva Kraken", "Kraken Kuva", "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/Kulstar", "Kulstar", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/Kunai", "Kunai", None, "Secondary", "Throwing"),
    ("/Lotus/Weapons/Tenno/Pistol/Laetum", "Laetum", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/Lato", "Lato", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/LatoVandal", "Lato Vandal", "Lato Vandalo", "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/LatoPrime", "Lato Prime", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/Lex", "Lex", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/LexPrime", "Lex Prime", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/Magnus", "Magnus", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Tenno/Pistol/MagnusPrime", "Magnus Prime", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Grineer/Pistol/Marelok", "Marelok", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/Grineer/Pistol/VaykorMarelok", "Vaykor Marelok", "Marelok Vaykor", "Secondary", "Pistol"),
    ("/Lotus/Weapons/MK1Series/MK1Furis", "MK1-Furis", None, "Secondary", "Pistol"),
    ("/Lotus/Weapons/MK1Series/MK1Kunai", "MK1-Kunai", None, "Secondary", "Throwing"),
    ("/Lotus/Types/Recipes/Weapons/LexBlueprint", "Lex Blueprint", "Lex Plano", "Secondary", "Componente"),
]

D, N, A = "dominado", "no_dominado", "a_medias"

# Las ocho capturas de la segunda tanda: fichas de catalogo que hacen falta para casarlas
# (nombre_en, nombre_es, categoria, tipo) y lo que se ve en cada una. `perdidas` son las
# tarjetas que se sabe que NO se leen y por que; el test exige que todo lo demas salga exacto.
FICHAS_2 = [
    # cuerpo a cuerpo (160/234)
    ("Ack & Brunt", None, "Melee", "Melee"), ("Tenet Agendus", "Agendus Tenet", "Melee", "Melee"),
    ("Amanata", None, "Melee", "Melee"), ("Amphis", None, "Melee", "Melee"), ("Anku", None, "Melee", "Melee"),
    ("Ankyros", None, "Melee", "Melee"), ("Ankyros Prime", None, "Melee", "Melee"),
    ("Argo & Vel", None, "Melee", "Melee"), ("Arum Spinosa", None, "Melee", "Melee"),
    ("Atterax", None, "Melee", "Melee"), ("Azothane", None, "Melee", "Melee"), ("Balla", None, "Melee", "Melee"),
    ("Twin Basolk", "Basolk Gemelas", "Melee", "Melee"), ("Bo", None, "Melee", "Melee"),
    ("Bo Prime", None, "Melee", "Melee"), ("Boltace", None, "Melee", "Melee"),
    # roboticos (28/46)
    ("Stinger", "Aguijón", "Sentinels", "Sentinel Weapon"), ("Artax", None, "Sentinels", "Sentinel Weapon"),
    ("Sweeper", "Barredora", "Sentinels", "Sentinel Weapon"), ("Sweeper Prime", "Barredora Prime", "Sentinels", "Sentinel Weapon"),
    ("Batoten", None, "Sentinels", "Sentinel Weapon"), ("Carrier", None, "Sentinels", "Sentinel"),
    ("Carrier Prime", None, "Sentinels", "Sentinel"), ("Cryotra", None, "Sentinels", "Sentinel Weapon"),
    ("Deconstructor", "Desarmador", "Sentinels", "Sentinel Weapon"),
    ("Deconstructor Prime", "Desarmador Prime", "Sentinels", "Sentinel Weapon"),
    ("Dethcube", None, "Sentinels", "Sentinel"), ("Dethcube Prime", None, "Sentinels", "Sentinel"),
    ("Diriga", None, "Sentinels", "Sentinel"), ("Djinn", None, "Sentinels", "Sentinel"),
    ("Helios", None, "Sentinels", "Sentinel"), ("Helios Prime", None, "Sentinels", "Sentinel"),
    # companeros (7/15)
    ("Helminth Charger", "Cargador Helminto", "Pets", "Pets"), ("Adarza Kavat", "Kavat Adarza", "Pets", "Pets"),
    ("Smeeta Kavat", "Kavat Smeeta", "Pets", "Pets"), ("Vasca Kavat", "Kavat Vasca", "Pets", "Pets"),
    ("Chesa Kubrow", "Kubrow Chesa", "Pets", "Pets"), ("Huras Kubrow", "Kubrow Huras", "Pets", "Pets"),
    ("Raksa Kubrow", "Kubrow Raksa", "Pets", "Pets"), ("Sahasa Kubrow", "Kubrow Sahasa", "Pets", "Pets"),
    ("Sunika Kubrow", "Kubrow Sunika", "Pets", "Pets"), ("Pharaoh Predasite", "Predásito Faraón", "Pets", "Pets"),
    ("Medjay Predasite", "Predásito Medjay", "Pets", "Pets"), ("Vizier Predasite", "Predásito Visir", "Pets", "Pets"),
    ("Crescent Vulpaphyla", "Vulpafila Medialuna", "Pets", "Pets"), ("Panzer Vulpaphyla", "Vulpafila Panzer", "Pets", "Pets"),
    ("Sly Vulpaphyla", "Vulpafila Taimada", "Pets", "Pets"),
    # vehiculos (4/13)
    ("Bonewidow", None, "Warframes", "Necramech"), ("Bad Baby", "Bebé malo", "Misc", "K-Drive Component"),
    ("Fever Spine", "Espina de fiebre", "Misc", "K-Drive Component"), ("Runaway", "Fugitivo", "Misc", "K-Drive Component"),
    ("Flatbelly", "Panza plana", "Misc", "K-Drive Component"), ("Needlenose", "Puntiagudo", "Misc", "K-Drive Component"),
    ("Itzal", "<ARCHWING> Itzal", "Archwing", "Archwing"), ("Odonata", None, "Archwing", "Archwing"),
    ("Odonata Prime", None, "Archwing", "Archwing"), ("Amesha", None, "Archwing", "Archwing"),
    ("Elytron", None, "Archwing", "Archwing"),
    # archcanones (6/20)
    ("Corvas Prime", None, "Arch-Gun", "Arch-Gun"), ("Dual Decurion", "Decuriones Dobles", "Arch-Gun", "Arch-Gun"),
    ("Prisma Dual Decurions", "Decuriones Dobles Prisma", "Arch-Gun", "Arch-Gun"),
    ("Arbucep", None, "Arch-Gun", "Arch-Gun"), ("Cyngas", None, "Arch-Gun", "Arch-Gun"),
    ("Corvas", None, "Arch-Gun", "Arch-Gun"), ("Kuva Ayanga", "Ayanga Kuva", "Arch-Gun", "Arch-Gun"),
    ("Cortege", None, "Arch-Gun", "Arch-Gun"), ("Imperator Vandal", "Imperator Vándalo", "Arch-Gun", "Arch-Gun"),
    ("Kuva Grattler", "Grattler Kuva", "Arch-Gun", "Arch-Gun"), ("Imperator", None, "Arch-Gun", "Arch-Gun"),
    ("Grattler", None, "Arch-Gun", "Arch-Gun"), ("Larkspur Prime", None, "Arch-Gun", "Arch-Gun"),
    ("Fluctus", None, "Arch-Gun", "Arch-Gun"), ("Larkspur", None, "Arch-Gun", "Arch-Gun"),
    ("Mandonel", None, "Arch-Gun", "Arch-Gun"),
    # archmelee (1/7)
    ("Veritux", None, "Arch-Melee", "Arch-Melee"), ("Centaur", "Centauro", "Arch-Melee", "Arch-Melee"),
    ("Knux", None, "Arch-Melee", "Arch-Melee"), ("Agkuza", None, "Arch-Melee", "Arch-Melee"),
    ("Kaszas", None, "Arch-Melee", "Arch-Melee"), ("Onorix", None, "Arch-Melee", "Arch-Melee"),
    ("Rathbone", None, "Arch-Melee", "Arch-Melee"),
    # amps (3/10)
    ("Klamora Prism", "Prisma Klamora", "Misc", "Amp"), ("Mote Prism", "Prisma Mota", "Misc", "Amp"),
    ("Lega Prism", "Prisma Lega", "Misc", "Amp"), ("Rahn Prism", "Prisma Rahn", "Misc", "Amp"),
    ("Raplak Prism", "Prisma Raplak", "Misc", "Amp"), ("Cantic Prism", "Prisma Cantic", "Misc", "Amp"),
    ("Granmu Prism", "Prisma Granmu", "Misc", "Amp"), ("Shwaak Prism", "Prisma Shwaak", "Misc", "Amp"),
    ("Sirocco", None, "Primary", "Pistol"),
]


def _unique_2(nombre_en: str, tipo: str) -> str:
    base = "/Test/" + nombre_en.replace(" ", "").replace("&", "And")
    if tipo == "K-Drive Component":
        return base + "Deck"
    if tipo == "Amp":
        return base + "Barrel"
    return base


ITEMS += [(_unique_2(en, tipo), en, es, cat, tipo) for en, es, cat, tipo in FICHAS_2]

# Segunda tanda: (categoria leida, COMPLETADO x/y, {nombre_en: estado o (a_medias, rango)}, perdidas).
VERDAD_REAL_2 = {
    "equipo_160-234": ("cuerpo_a_cuerpo", (160, 234), {
        "Ack & Brunt": D, "Tenet Agendus": (A, 38), "Amanata": D, "Amphis": D, "Anku": D, "Ankyros": D,
        "Ankyros Prime": D, "Argo & Vel": N, "Arum Spinosa": N, "Atterax": D, "Azothane": N, "Balla": N,
        "Twin Basolk": N, "Bo": D, "Bo Prime": N, "Boltace": D}, {}),
    "equipo_28-46": ("roboticos", (28, 46), {
        "Stinger": D, "Artax": D, "Sweeper": D, "Sweeper Prime": N, "Batoten": D, "Carrier": D,
        "Carrier Prime": N, "Cryotra": N, "Deconstructor": D, "Deconstructor Prime": D, "Dethcube": D,
        "Dethcube Prime": N, "Diriga": D, "Djinn": D, "Helios": D, "Helios Prime": D}, {}),
    "equipo_7-15": ("companeros", (7, 15), {
        "Helminth Charger": D, "Adarza Kavat": D, "Smeeta Kavat": D, "Vasca Kavat": D, "Chesa Kubrow": N,
        "Huras Kubrow": D, "Raksa Kubrow": D, "Sahasa Kubrow": N, "Sunika Kubrow": N, "Pharaoh Predasite": N,
        "Medjay Predasite": N, "Vizier Predasite": N, "Crescent Vulpaphyla": N, "Panzer Vulpaphyla": D,
        "Sly Vulpaphyla": N}, {}),
    "equipo_4-13": ("vehiculos", (4, 13), {
        "Bonewidow": (A, 30), "Bad Baby": N, "Fever Spine": N, "Runaway": N, "Flatbelly": N, "Needlenose": N,
        "Itzal": D, "Odonata": D, "Odonata Prime": N, "Amesha": N, "Elytron": N,
        # Un efecto de luz tapa la linea de rango ("RANGO MI"): esta dominado, pero no se afirma.
        "Voidrig": "desconocido"},
        {"Plexus": "no esta en el catalogo"}),
    "equipo_6-20": ("archcanones", (6, 20), {
        "Corvas Prime": D, "Dual Decurion": N, "Prisma Dual Decurions": N, "Arbucep": N, "Cyngas": N,
        "Corvas": N, "Kuva Ayanga": N, "Cortege": N, "Imperator Vandal": D, "Kuva Grattler": (A, 30),
        "Imperator": D, "Grattler": D, "Larkspur Prime": N, "Fluctus": N, "Larkspur": N, "Mandonel": N}, {}),
    "equipo_1-7": ("archmelee", (1, 7), {
        "Veritux": D, "Centaur": N, "Knux": N, "Agkuza": N, "Kaszas": N, "Onorix": N, "Rathbone": N}, {}),
    "equipo_3-10": ("amps", (3, 10), {
        "Klamora Prism": D, "Mote Prism": (A, 24), "Lega Prism": N, "Rahn Prism": N, "Raplak Prism": N,
        "Cantic Prism": N, "Granmu Prism": N, "Shwaak Prism": D, "Sirocco": N},
        {"Amp (Mote Amp)": "el juego lo llama solo AMP y el catalogo no lo tiene"}),
}

# Verdad de las capturas reales: (nombre en pantalla, dominado).
VERDAD_REAL = {
    "warframes": ("warframes", (108, 116), [
        ("Ash", 1), ("Ash Prime", 1), ("Atlas", 1), ("Atlas Prime", 1), ("Banshee", 1),
        ("Banshee Prime", 1), ("Baruuk", 1), ("Baruuk Prime", 1), ("Caliban", 1), ("Caliban Prime", 1),
        ("Chroma", 1), ("Chroma Prime", 1), ("Citrine", 1), ("Cyte-09", 0), ("Dagath", 1), ("Dante", 1)]),
    "primarias": ("primarias", (147, 198), [
        ("Acceltra", 1), ("Acceltra Prime", 1), ("Aeolak", 1), ("Afentis", 1), ("Afentis Prime", 0),
        ("Alternox", 1), ("Alternox Prime", 0), ("Ambassador", 1), ("Amprex", 1), ("Argonak", 1),
        ("Astilla", 1), ("Astilla Prime", 1), ("Attica", 1), ("AX-52", 1), ("Basmu", 1),
        ("Coda Bassocyst", 1)]),
    "secundarias": ("secundarias", (102, 151), [
        ("Hikou Prime", 0), ("Hystrix", 1), ("Hystrix Prime", 1), ("Knell", 1), ("Knell Prime", 1),
        ("Kohmak", 0), ("Twin Kohmak", 0), ("Kompressa", 0), ("Kompressa Prime", 1), ("Kraken", 1),
        ("Kuva Kraken", 0), ("Kulstar", 1), ("Kunai", 1), ("Laetum", 1), ("Lato", 1), ("Lato Vandal", 1),
        ("Lex", 1), ("Lex Prime", 1), ("Magnus", 1), ("Magnus Prime", 1), ("Marelok", 1),
        ("Vaykor Marelok", 0), ("MK1-Furis", 1), ("MK1-Kunai", 1)]),
}


@pytest.fixture()
def catalogo(indice_poblado, tmp_path):
    con, _, _ = indice_poblado
    con.executemany(
        "INSERT OR IGNORE INTO items (unique_name, nombre_en, nombre_es, categoria, tipo) VALUES (?, ?, ?, ?, ?)",
        ITEMS,
    )
    con.commit()
    return con


@pytest.fixture()
def usuario(tmp_path):
    con = usuario_db.conectar(tmp_path / "usuario.sqlite")
    yield con
    con.close()


@pytest.fixture(scope="module")
def motor():
    return MotorOCR()


def _un(catalogo, nombre_en: str) -> str:
    return catalogo.execute("SELECT unique_name FROM items WHERE nombre_en = ?", (nombre_en,)).fetchone()[0]


def _l(texto, x, y, ancho=150, alto=24, conf=0.9) -> Leido:
    return Leido(texto, x, y, ancho, alto, conf)


def _cabecera() -> list[Leido]:
    return [_l("COMPLETADO", 162, 484, 157, 24), _l("108/116", 447, 475, 121, 36),
            _l("WARFRAME", 898, 492, 154, 27), _l("ORDENAR POR: NOMBRE", 1879, 493, 273, 23)]


# --- interpretacion sin OCR ------------------------------------------------------------------


def test_la_linea_de_rango_se_reconoce_en_sus_variantes():
    maximo = ("RANGO MAXIMO", "RANGO MÁXIMO", "RANGOMAXIMO", "RANG0 MAXIM0", "Max Rank", "MAX RANK",
              "RANGO MAX.", "MASTERED", "DOMINADO")
    for texto in maximo:
        r = PE._como_linea_de_rango(_l(texto, 0, 0))
        assert r is not None and r.maximo, texto
    parcial = PE._como_linea_de_rango(_l("RANGO 14", 0, 0))
    assert parcial is not None and parcial.rango == 14 and not parcial.maximo
    suelta = PE._como_linea_de_rango(_l("3O/30", 0, 0))
    assert suelta is not None and (suelta.rango, suelta.tope_declarado) == (30, 30)
    for texto in ("ASH PRIME", "12.0 %", "108/116", "PX 90 121 051", "Bo", "RANGO 87", "1/4"):
        assert PE._como_linea_de_rango(_l(texto, 0, 0)) is None, texto


def test_la_cabecera_da_contador_categoria_y_corte(catalogo):
    casador = PE.casador_equipamiento(catalogo)
    lineas = _cabecera() + [
        # Fila MAS USADO, por encima de la barra: se descarta aunque case.
        _l("INAROSPRIME", 163, 384, 164, 20), _l("RANGO MAXIMO", 160, 406, 185, 27),
        _l("ASH", 158, 715, 52, 25), _l("RANGO MAXIMO", 157, 738, 184, 29),
        _l("CYTE-09", 1539, 998, 104, 23),
    ]
    pagina = PE.interpretar_lineas(lineas, casador, catalogo)
    assert pagina.completado == (108, 116) and pagina.categoria == "warframes"
    assert pagina.cabecera_en_y == 519
    nombres = {t.nombre: t.estado for t in pagina.tarjetas}
    assert nombres == {"Ash": P.DOMINADO, "Cyte-09": P.NO_DOMINADO}
    assert "COMPLETADO" not in pagina.sin_casar and "WARFRAME" not in pagina.sin_casar


def test_sin_cabecera_la_falta_de_linea_no_se_da_por_no_dominado(catalogo):
    casador = PE.casador_equipamiento(catalogo)
    pagina = PE.interpretar_lineas([_l("CYTE-09", 1539, 998, 104, 23)], casador, catalogo)
    assert pagina.cabecera_en_y is None
    assert pagina.tarjetas[0].estado == P.DESCONOCIDO
    assert "MAS USADO" in pagina.tarjetas[0].motivo


def test_la_linea_de_rango_no_se_presta_a_la_tarjeta_de_al_lado(catalogo):
    casador = PE.casador_equipamiento(catalogo)
    # KOHMAK (no dominada, nombre bajo) al lado de KNELL PRIME (dominada): la linea de
    # KNELL PRIME no solapa en horizontal con KOHMAK, asi que KOHMAK sigue sin linea.
    lineas = _cabecera() + [
        _l("KNELL PRIME", 1288, 598, 152, 23), _l("RANGO MAXIMO", 1288, 624, 182, 23),
        _l("KOHMAK", 1562, 624, 104, 24),
    ]
    pagina = PE.interpretar_lineas(lineas, casador, catalogo)
    estados = {t.nombre: t.estado for t in pagina.tarjetas}
    assert estados == {"Knell Prime": P.DOMINADO, "Kohmak": P.NO_DOMINADO}


def test_dudas_quedan_como_desconocido_nunca_como_dominado(catalogo):
    casador = PE.casador_equipamiento(catalogo)
    lineas = _cabecera() + [
        _l("ASH", 158, 715, 52, 25), _l("RANGO MAXIMO", 157, 738, 184, 29, conf=0.45),  # dudosa
        _l("ATLAS", 708, 715, 77, 25), _l("RANGO 38", 708, 740, 120, 26),  # imposible (tope 30)
        _l("KRAKEN KUVA", 1258, 715, 160, 25), _l("RANGO 30", 1258, 740, 120, 26),  # tope 40
        _l("BANSHEE", 1809, 715, 107, 20), _l("RANGO 14", 1809, 740, 120, 26),  # a medias
    ]
    pagina = PE.interpretar_lineas(lineas, casador, catalogo)
    por = {t.nombre: t for t in pagina.tarjetas}
    assert por["Ash"].estado == P.DESCONOCIDO and "dudosa" in por["Ash"].motivo
    assert por["Atlas"].estado == P.DESCONOCIDO and "imposible" in por["Atlas"].motivo
    assert por["Kraken Kuva"].estado == P.A_MEDIAS and por["Kraken Kuva"].rango == 30
    assert por["Banshee"].estado == P.A_MEDIAS and por["Banshee"].rango == 14
    assert not [t for t in pagina.tarjetas if t.estado == P.DOMINADO]
    # Un objeto que el catalogo dice que no da maestria no puede salir dominado.
    sin_tope = PE.Tarjeta("X", 1, "/x", "X", 100.0, (0, 0, 1, 1), tope=None, rango=30, confianza_rango=0.9)
    PE._decidir(sin_tope, True)
    assert sin_tope.estado == P.NO_APLICA
    # El filtro del casador deja fuera los componentes: ninguna tarjeta sin tope.
    assert all(t.tope is not None for t in pagina.tarjetas)


def test_rango_de_maestria_de_la_cabecera_del_perfil():
    assert PE.leer_rango_maestria([_l("Rango de maestria 21", 0, 0)]) == 21
    assert PE.leer_rango_maestria([_l("RANGO DE MAESTRÍA", 120, 200, 220, 24), _l("21", 120, 236, 60, 60)]) == 21
    assert PE.leer_rango_maestria([_l("RANGO DE MAESTRÍA", 120, 200, 220, 24), _l("21", 900, 900, 60, 60)]) is None
    assert PE.leer_rango_maestria([_l("<titulo>", 0, 0)]) is None


# --- OCR sobre pantallas sinteticas -----------------------------------------------------------


def test_pagina_sintetica_se_lee_entera(catalogo, motor):
    casador = PE.casador_equipamiento(catalogo)
    verdad = [("ASH", True), ("ASH PRIME", True), ("ATLAS", True), ("ATLAS PRIME", False),
              ("BANSHEE", True), ("BANSHEE PRIME", False), ("BARUUK", True), ("BARUUK PRIME", True),
              ("CALIBAN", False), ("CALIBAN PRIME", True), ("CHROMA", True), ("CHROMA PRIME", True),
              ("CITRINE", True), ("CYTE-09", False), ("DAGATH", True), ("DANTE", True)]
    imagen = pintar_pagina(verdad, "WARFRAME", (108, 116))
    pagina = PE.leer_pagina(imagen, motor, casador, catalogo)

    assert pagina.completado == (108, 116) and pagina.categoria == "warframes"
    estados = {t.nombre.upper(): t.estado for t in pagina.tarjetas}
    esperados = {n: (P.DOMINADO if d else P.NO_DOMINADO) for n, d in verdad}
    faltan = set(esperados) - set(estados)
    assert len(faltan) <= 1, faltan  # el OCR puede perder un nombre; nunca inventar uno
    assert not (set(estados) - set(esperados))
    assert all(estados[n] == esperados[n] for n in estados), estados
    # La fila MAS USADO (INAROS PRIME, AMPREX...) no se cuela aunque case con el catalogo.
    assert "AMPREX" not in estados


def test_pagina_sintetica_a_1080p_con_reescalado(catalogo, motor):
    casador = PE.casador_equipamiento(catalogo)
    verdad = [("LEX", True), ("LEX PRIME", True), ("MAGNUS", True), ("MAGNUS PRIME", False),
              ("MARELOK", True), ("MARELOK VAYKOR", False), ("MK1-FURIS", True), ("MK1-KUNAI", True)]
    imagen = pintar_pagina(verdad, "SECUNDARIA", (102, 151), ancho=1920, alto=1080)
    pagina = PE.leer_pagina(imagen, motor, casador, catalogo, escala=1.5)
    assert pagina.completado == (102, 151) and pagina.categoria == "secundarias"
    estados = {t.nombre.upper(): t.estado for t in pagina.tarjetas}
    assert len(estados) >= 7
    assert not [n for n, e in estados.items() if e == P.DOMINADO and n in ("MAGNUS PRIME", "VAYKOR MARELOK")]


def test_cabecera_del_perfil_da_el_rango_de_maestria(motor, catalogo):
    casador = PE.casador_equipamiento(catalogo)
    pagina = PE.leer_pagina(pintar_cabecera_perfil("<titulo>", 21), motor, casador, catalogo)
    assert pagina.rango_maestria == 21
    assert pagina.tarjetas == []


# --- OCR sobre las capturas reales -------------------------------------------------------------


def _captura(nombre: str) -> Path | None:
    for ext in (".jpg", ".png"):  # las reducidas primero: son las que quedan en el repositorio
        if (CAPTURAS / f"{nombre}{ext}").exists():
            return CAPTURAS / f"{nombre}{ext}"
    return None


def _leer_captura(nombre, catalogo, motor):
    ruta = _captura(nombre)
    if ruta is None:
        pytest.skip(f"falta {nombre} en {CAPTURAS}")
    import cv2

    return PE.leer_pagina(cv2.imread(str(ruta)), motor, PE.casador_equipamiento(catalogo), catalogo)


@pytest.mark.parametrize("nombre", sorted(VERDAD_REAL))
def test_captura_real(nombre, catalogo, motor):
    categoria, completado, verdad = VERDAD_REAL[nombre]
    pagina = _leer_captura(nombre, catalogo, motor)

    assert pagina.categoria == categoria and pagina.completado == completado
    # El casador devuelve la etiqueta en el idioma en que caso (es o en): se compara por unique_name.
    estados = {t.unique_name: t.estado for t in pagina.tarjetas}
    esperados = {_un(catalogo, n): (P.DOMINADO if d else P.NO_DOMINADO) for n, d in verdad}
    assert estados == esperados  # todos los nombres, todos los estados, ninguno de mas
    assert not pagina.desconocidas


@pytest.mark.parametrize("nombre", sorted(VERDAD_REAL_2))
def test_captura_real_segunda_tanda(nombre, catalogo, motor):
    """Las siete categorias restantes, con la categoria leida de la propia pantalla.

    Se exige exactitud total salvo en las tarjetas listadas en `perdidas` (dos: una
    que no esta en el catalogo y una tapada por un efecto de luz), que tienen que
    faltar, no salir mal.
    """
    categoria, completado, verdad, perdidas = VERDAD_REAL_2[nombre]
    pagina = _leer_captura(nombre, catalogo, motor)

    assert pagina.categoria == categoria and pagina.completado == completado
    leidas = {t.unique_name: t for t in pagina.tarjetas}
    esperadas = {}
    for n, e in verdad.items():
        esperadas[_un(catalogo, n)] = e if isinstance(e, tuple) else (e, None)
    assert set(leidas) == set(esperadas), (set(leidas) ^ set(esperadas), perdidas)
    for unique_name, (estado, rango) in esperadas.items():
        t = leidas[unique_name]
        assert t.estado == estado, (t.nombre, t.estado, t.motivo)
        if rango is not None:
            assert t.rango == rango, (t.nombre, t.rango)
    # Solo queda como desconocido lo previsto (Voidrig, con la linea de rango tapada).
    desconocidas = {t.unique_name for t in pagina.desconocidas}
    assert desconocidas == {u for u, (e, _) in esperadas.items() if e == P.DESCONOCIDO}
    # El ruido de la captura (medidor de FPS, avisos de Windows, chat) no llega al informe.
    assert not [s for s in pagina.sin_casar if "FPS" in s.upper() or "Recortes" in s]


def test_portada_real_da_el_rango_de_maestria_por_el_titulo(catalogo, motor):
    pagina = _leer_captura("perfil_portada", catalogo, motor)
    assert pagina.rango_maestria == 30  # "MAESTRO VERDADERO"; el siguiente es "LEGENDARIO 1"
    assert pagina.tarjetas == [] and pagina.completado is None


def test_titulos_de_maestria_sin_ocr():
    etiqueta = _l("RANGO DE MAESTRÍA", 1882, 194, 263, 25)
    assert PE.leer_rango_maestria([etiqueta, _l("MAESTROVERDADERO", 1885, 359)]) == 30
    assert PE.leer_rango_maestria([etiqueta, _l("SIGUIENTE RANGO: LEGENDARI0 1 EN 85 296", 1764, 452)]) == 30
    assert PE.leer_rango_maestria([etiqueta, _l("LEGENDARIO 3", 1885, 359)]) == 33
    assert PE.leer_rango_maestria([etiqueta, _l("DRAGÓN DE PLATA", 1885, 359)]) == 22
    assert PE.leer_rango_maestria([etiqueta, _l("Gold Novice", 1885, 359)]) == 5
    assert PE.leer_rango_maestria([_l("MAESTROVERDADERO", 1885, 359)]) is None  # sin etiqueta no es la portada


# --- del OCR al perfil guardado ---------------------------------------------------------------


def _lecturas(catalogo, *filas):
    return [P.LecturaOCR(_un(catalogo, n), r, e, 0.9, n, p) for n, r, e, p in filas]


def test_el_ocr_construye_un_perfil_que_el_almacen_fusiona_entre_sesiones(usuario, catalogo):
    hoy = _lecturas(catalogo, ("Lex", 30, P.DOMINADO, "secundarias"), ("Kuva Kraken", 30, P.A_MEDIAS, "secundarias"),
                    ("Kohmak", None, P.NO_DOMINADO, "secundarias"), ("Kunai", None, P.DESCONOCIDO, "secundarias"))
    resultado = P.guardar_desde_ocr(usuario, catalogo, hoy, rango_maestria=21)
    assert resultado.perfil.origen == "ocr" and resultado.guardadas == 2
    assert [l.nombre for l in resultado.desconocidas] == ["Kohmak", "Kunai"]

    assert P.estado_por_unique_name(usuario, catalogo, _un(catalogo, "Lex")).dominado
    kraken = P.estado_por_unique_name(usuario, catalogo, _un(catalogo, "Kuva Kraken"))
    assert kraken.estado == P.A_MEDIAS and kraken.rango == 30 and kraken.umbral == 800_000
    meta = P.resumen(usuario)
    assert meta["rango"] == 21 and meta["origen"] == "ocr" and meta["objetos_xp"] == 2

    # Manana, las warframes: lo de ayer sigue ahi.
    manana = _lecturas(catalogo, ("Ash", 30, P.DOMINADO, "warframes"), ("Kunai", 30, P.DOMINADO, "secundarias"))
    P.guardar_desde_ocr(usuario, catalogo, manana)
    assert P.estado_por_unique_name(usuario, catalogo, _un(catalogo, "Lex")).dominado
    assert P.estado_por_unique_name(usuario, catalogo, _un(catalogo, "Ash")).dominado
    assert P.estado_por_unique_name(usuario, catalogo, _un(catalogo, "Kunai")).dominado
    assert P.resumen(usuario)["objetos_xp"] == 4 and P.resumen(usuario)["rango"] == 21
    assert P.desconocidos_ocr(usuario) == []  # Kunai ya se leyo; Kohmak es "no dominado", no una duda


def test_una_lectura_dudosa_no_pisa_una_buena_y_el_desconocido_se_ve(usuario, catalogo):
    P.guardar_desde_ocr(usuario, catalogo, _lecturas(catalogo, ("Lex", 30, P.DOMINADO, "secundarias")))
    P.guardar_desde_ocr(usuario, catalogo, _lecturas(catalogo, ("Lex", None, P.DESCONOCIDO, "secundarias"),
                                                     ("Magnus", None, P.DESCONOCIDO, "secundarias")))
    assert P.estado_por_unique_name(usuario, catalogo, _un(catalogo, "Lex")).dominado
    lecturas = {l["nombre"]: l for l in P.lecturas_ocr(usuario)}
    assert lecturas["Lex"]["estado"] == P.DOMINADO and lecturas["Lex"]["veces"] == 2
    assert [l["nombre"] for l in P.desconocidos_ocr(usuario)] == ["Magnus"]

    filas = {f["nombre_en"]: f["estado"] for f in P.estados_de_todos(usuario, catalogo)}
    assert filas["Magnus"] == P.DESCONOCIDO and filas["Lex"] == P.DOMINADO and filas["Kunai"] == P.SIN_TOCAR
    resumen = P.resumen_maestria(usuario, catalogo)
    assert resumen["Secondary"][P.DESCONOCIDO] == 1
    assert P.DESCONOCIDO not in resumen["Warframes"]  # la clave solo aparece cuando hay alguno
    pendientes = P.pendientes_por_categoria(usuario, catalogo)["Secondary"]
    assert any(f["nombre_en"] == "Magnus" and f["estado"] == P.DESCONOCIDO for f in pendientes)


def test_el_json_sigue_sustituyendo_todo_incluido_lo_del_ocr(usuario, catalogo):
    P.guardar_desde_ocr(usuario, catalogo, _lecturas(catalogo, ("Lex", 30, P.DOMINADO, "secundarias"),
                                                     ("Magnus", None, P.DESCONOCIDO, "secundarias")))
    P.importar(FIXTURES / "perfil_recortado.json", usuario, catalogo)
    assert P.resumen(usuario)["origen"] == "json" and P.resumen(usuario)["nombre"] == "TennoPrueba"
    assert not P.estado_por_unique_name(usuario, catalogo, _un(catalogo, "Lex")).dominado
    assert P.lecturas_ocr(usuario) == []
    # Y un OCR posterior encima del JSON deja el origen en "mixto".
    P.guardar_desde_ocr(usuario, catalogo, _lecturas(catalogo, ("Lex", 30, P.DOMINADO, "secundarias")))
    assert P.resumen(usuario)["origen"] == "mixto" and P.resumen(usuario)["nombre"] == "TennoPrueba"


def test_xp_sintetica_y_rango_se_invierten():
    from farmadex.perfil import maestria

    for umbral in (maestria.XP_ARMA_30, maestria.XP_ARMA_40, maestria.XP_WARFRAME_30, maestria.XP_WARFRAME_40):
        tope = maestria.tope_rango(umbral)
        for rango in (0, 1, 14, 29, tope):
            assert maestria.rango_actual(maestria.xp_sintetica(rango, umbral), umbral) == rango
        assert maestria.xp_sintetica(tope, umbral) == umbral
    assert maestria.estado_por_rango(30, 40) == P.A_MEDIAS
    assert maestria.estado_por_rango(40, 40) == P.DOMINADO
    assert maestria.estado_por_rango(31, 30) == P.DESCONOCIDO
    assert maestria.estado_por_rango(None, 30) == P.DESCONOCIDO
    assert maestria.estado_por_rango(30, None) == P.NO_APLICA


def test_desde_tarjetas_descarta_lo_que_no_da_maestria():
    class T:
        def __init__(self, estado, rango):
            self.unique_name, self.nombre, self.estado, self.rango, self.confianza_rango = "/x", "X", estado, rango, 0.8

    lecturas = P.desde_tarjetas([T(P.NO_APLICA, 30), T(P.DOMINADO, 30), T(P.DESCONOCIDO, 12)], "amps")
    assert [(l.estado, l.rango, l.pantalla) for l in lecturas] == [(P.DOMINADO, 30, "amps"), (P.DESCONOCIDO, None, "amps")]


# --- deteccion de cambio de pagina -------------------------------------------------------------


def test_el_detector_avisa_una_vez_por_pagina_quieta():
    a = np.zeros((90, 160, 3), np.uint8)
    b = np.full((90, 160, 3), 120, np.uint8)
    detector = PE.DetectorPagina(quietas=2)
    assert not detector.observar(a)  # primera vez: aun no esta quieta
    assert detector.observar(a)  # segunda igual: pagina nueva
    assert not detector.observar(a)  # sigue igual: ya se dio
    assert not detector.observar(b)  # cambio: esperar a que se quede quieta
    assert detector.observar(b)
    assert not detector.observar(b)
    # Volver a una pagina anterior se vuelve a dar (solo se recuerda la ultima); el
    # almacen fusiona, asi que repetir no duplica nada.
    assert not detector.observar(a)
    assert detector.observar(a)


# --- herramienta de consola -----------------------------------------------------------------------


def test_la_herramienta_procesa_una_carpeta_y_guarda(catalogo, tmp_path, capsys):
    import cv2

    ruta = Path(__file__).resolve().parents[1] / "herramientas" / "escanear_perfil.py"
    spec = importlib.util.spec_from_file_location("escanear_perfil", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    carpeta = tmp_path / "capturas"
    carpeta.mkdir()
    cv2.imwrite(str(carpeta / "warframes_01.png"),
                pintar_pagina([("ASH", True), ("ATLAS", False), ("DANTE", True)], "WARFRAME", (2, 3)))
    cv2.imwrite(str(carpeta / "perfil_01.png"), pintar_cabecera_perfil("Tenno", 21))
    db = tmp_path / "usuario.sqlite"
    indice = tmp_path / "prueba.sqlite"  # el que crea la fixture `con`
    codigo = modulo.main(["--desde", str(carpeta), "--db", str(db), "--indice", str(indice)])
    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert "dominados: 2" in salida and "Rango de maestria leido: 21" in salida
    assert "warframes: 2 dominados de los 2 que dice el juego" in salida

    usuario = usuario_db.conectar(db)
    assert P.estado_por_unique_name(usuario, catalogo, _un(catalogo, "Ash")).dominado
    assert not P.estado_por_unique_name(usuario, catalogo, _un(catalogo, "Atlas")).dominado
    assert P.resumen(usuario)["rango"] == 21
    usuario.close()
