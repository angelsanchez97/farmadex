"""¿Esta bien mi build? y build basica (datos/evaluar_build.py): reglas con casos conocidos.

Los efectos son los textos de WFCD tal cual (al rango maximo, en ingles). Las reglas son
las de la wiki oficial para quien empieza: dano base, multidisparo, elementos y sus
combinaciones, critico si el arma es de critico, estado si es de estado, versiones de un
mismo mod que no van juntas, huecos vacios, capacidad, aura y supervivencia.
"""

from __future__ import annotations

import json

import pytest

from farmadex import idiomas
from farmadex.datos import evaluar_build as E


@pytest.fixture(autouse=True)
def castellano():
    idiomas.cargar("es")
    E.olvidar_cache()
    yield
    idiomas.cargar("es")
    E.olvidar_cache()


# (unique, nombre_en, nombre_es, tipo, compat, rareza, efecto al rango maximo)
MODS = [
    ("/m/Serration", "Serration", "Sierra", "Primary Mod", "Rifle", "Uncommon", "+165% Damage"),
    ("/m/Amalgam", "Amalgam Serration", "Sierra Amalgama", "Primary Mod", "Rifle", "Rare", "+155% Damage\n+25% Sprint Speed"),
    ("/m/HeavyCaliber", "Heavy Caliber", "Calibre pesado", "Primary Mod", "Rifle", "Rare", "+165% Damage\n-55% Accuracy"),
    ("/m/Split", "Split Chamber", "Cámara dividida", "Primary Mod", "Rifle", "Rare", "+90% Multishot"),
    ("/m/GalvChamber", "Galvanized Chamber", "Cámara Galvanizada", "Primary Mod", "Rifle", "Rare",
     "+80% Multishot\nOn Kill:\n+30% Multishot for 20s. Stacks up to 5x."),
    ("/m/PointStrike", "Point Strike", "Punto de impacto", "Primary Mod", "Rifle", "Common", "+150% Critical Chance"),
    ("/m/VitalSense", "Vital Sense", "Sentido vital", "Primary Mod", "Rifle", "Rare", "+120% Critical Damage"),
    ("/m/Cryo", "Cryo Rounds", "Munición criogénica", "Primary Mod", "Rifle", "Uncommon", "+90% Cold"),
    ("/m/PrimedCryo", "Primed Cryo Rounds", "Munición criogénica Prime", "Primary Mod", "Rifle", "Legendary", "+165% Cold"),
    ("/m/Infected", "Infected Clip", "Cargador infectado", "Primary Mod", "Rifle", "Uncommon", "+90% Toxin"),
    ("/m/Hellfire", "Hellfire", "Fuego infernal", "Primary Mod", "Rifle", "Uncommon", "+90% Heat"),
    ("/m/Storm", "Stormbringer", "Portador de tormentas", "Primary Mod", "Rifle", "Uncommon", "+90% Electricity"),
    ("/m/Aptitude", "Rifle Aptitude", "Aptitud de rifle", "Primary Mod", "Rifle", "Uncommon", "+90% Status Chance"),
    ("/m/Speed", "Speed Trigger", "Gatillo veloz", "Primary Mod", "Rifle", "Rare", "+60% Fire Rate (x2 for Bows)"),
    ("/m/Vitality", "Vitality", "Vitalidad", "Warframe Mod", "WARFRAME", "Common", "+440% Health"),
    ("/m/Redirection", "Redirection", "Redirección", "Warframe Mod", "WARFRAME", "Common", "+440% Shield Capacity"),
    ("/m/SteelFiber", "Steel Fiber", "Fibra de acero", "Warframe Mod", "WARFRAME", "Common", "+110% Armor"),
    ("/m/UmbralFiber", "Umbral Fiber", "Fibra Umbral", "Warframe Mod", "WARFRAME", "Legendary", "+100% Armor"),
    ("/m/Intensify", "Intensify", "Intensificación", "Warframe Mod", "WARFRAME", "Rare", "+30% Ability Strength"),
    ("/m/Continuity", "Continuity", "Continuidad", "Warframe Mod", "WARFRAME", "Rare", "+30% Ability Duration"),
    ("/m/PrimedContinuity", "Primed Continuity", "Continuidad Prime", "Warframe Mod", "WARFRAME", "Legendary",
     "+55% Ability Duration"),
    ("/m/Stretch", "Stretch", "Estirar", "Warframe Mod", "WARFRAME", "Uncommon", "+45% Ability Range"),
    ("/m/Streamline", "Streamline", "Aerodinamizar", "Warframe Mod", "WARFRAME", "Rare", "+30% Ability Efficiency"),
    ("/m/Flow", "Flow", "Flujo", "Warframe Mod", "WARFRAME", "Rare", "+100% Energy Max"),
    ("/m/BlindRage", "Blind Rage", "Rabia ciega", "Warframe Mod", "WARFRAME", "Rare",
     "+99% Ability Strength\n-55% Ability Efficiency"),
    ("/m/Siphon", "Energy Siphon", "Sifón de energía", "Warframe Mod", "AURA", "Uncommon", "Squad receives +0.6 Energy Regen/s"),
    ("/m/SprintBoost", "Sprint Boost", "Impulso de carrera", "Warframe Mod", "AURA", "Common", "+15% Sprint Speed"),
    ("/m/Adaptation", "Adaptation", "Adaptación", "Warframe Mod", "WARFRAME", "Rare",
     "When Damaged:\n+10% Resistance to that Damage Type for 20s. Stacks up to 90%."),
    ("/m/Pressure", "Pressure Point", "Punto de presión", "Melee Mod", "Melee", "Common", "+120% Melee Damage"),
]
EQUIPOS = [
    # (unique, nombre_en, nombre_es, categoria, tipo, detalles)
    ("/w/Soma", "Soma Prime", "Soma Prime", "Primary", "Rifle", {"arma": {"critico": 0.30, "estado": 0.10}}),
    ("/w/Braton", "Braton", "Braton", "Primary", "Rifle", {"arma": {"critico": 0.05, "estado": 0.06}}),
    ("/w/Tonkor", "Tonkor", "Tonkor", "Primary", "Launcher", {"arma": {"critico": 0.25, "estado": 0.25}}),
    ("/w/Excalibur", "Excalibur", "Excalibur", "Warframes", "Warframe",
     {"warframe": {"vida": 300, "escudo": 300, "armadura": 225}}),
    ("/w/Inaros", "Inaros", "Inaros", "Warframes", "Warframe", {"warframe": {"vida": 550, "escudo": 0, "armadura": 200}}),
]


@pytest.fixture()
def indice(con):
    ids = {}
    for unique, en, es, tipo, compat, rareza, efecto in MODS:
        con.execute("INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo) VALUES (?, ?, ?, 'Mods', ?)",
                    (unique, en, es, tipo))
        ids[en] = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        datos = {"mod": {"efecto": {"en": [efecto]}, "rareza": rareza, "compat": compat, "polaridad": "madurai",
                         "drenaje": 4, "rango_max": 10}}
        con.execute("INSERT INTO detalles (item_id, datos) VALUES (?, ?)", (ids[en], json.dumps(datos)))
        # Todos salen en algun sitio menos la Sierra Amalgama (asi no cuenta como facil).
        if en != "Amalgam Serration":
            con.execute("INSERT INTO fuentes (item_id, tipo, origen_texto) VALUES (?, 'enemigo', 'Grineer')", (ids[en],))
    for unique, en, es, categoria, tipo, detalles in EQUIPOS:
        con.execute("INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo) VALUES (?, ?, ?, ?, ?)",
                    (unique, en, es, categoria, tipo))
        ids[en] = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute("INSERT INTO detalles (item_id, datos) VALUES (?, ?)", (ids[en], json.dumps(detalles)))
    con.commit()
    return con, ids


def _textos(puntos):
    return " | ".join(p.texto for p in puntos)


# -- que hace cada mod --------------------------------------------------------------------

@pytest.mark.parametrize("efecto, clases, elementos, corrupto", [
    ("+165% Damage", {"dano_base"}, [], False),
    ("+120% Melee Damage", {"dano_base"}, [], False),
    ("+90% Multishot", {"multidisparo"}, [], False),
    ("+60% Cold\n+60% Status Chance", {"elemento", "estado"}, ["Cold"], False),
    ("+99% Ability Strength\n-55% Ability Efficiency", {"fuerza", "menos_eficiencia"}, [], True),
    ("+165% Damage\n-55% Accuracy", {"dano_base"}, [], True),
    ("+30% Damage to Grineer", {"faccion"}, [], False),
    ("+60% Critical Damage", {"crit_dano"}, [], False),
    ("When Damaged:\n+10% Resistance to that Damage Type for 20s.", {"resistencia"}, [], False),
    ("On Dodge:\nBecome invulnerable for 3s and remove all Status Effects.", {"aguante"}, [], False),
    ("+80% Status Chance\nOn Kill:\n+40% Direct Damage per Status Type affecting the target", {"estado", "dano_base"}, [], False),
    ("+100% Health", {"salud"}, [], False),
    ("+100% Energy Max", {"energia"}, [], False),
])
def test_analizar_efecto(efecto, clases, elementos, corrupto):
    c, e, k, _ = E.analizar_efecto(efecto)
    assert c == clases and e == elementos and k == corrupto


def test_familias_de_mods_que_no_van_juntos():
    assert E.familia("Primed Continuity") == E.familia("Continuity") == E.familia("Archon Continuity")
    assert E.familia("Umbral Fiber") == E.familia("Steel Fiber")
    assert E.familia("Galvanized Chamber") == E.familia("Split Chamber")
    assert E.familia("Amalgam Serration") == E.familia("Serration")
    assert E.familia("Vital Sense") != E.familia("Serration")


def _mods(*elementos):
    return [E.Mod(i, f"m{i}", f"m{i}", elementos=[e], clases={"elemento"}) for i, e in enumerate(elementos)]


def test_elementos_se_combinan_en_el_orden_de_los_huecos():
    assert E.combinar_elementos(_mods("Cold", "Toxin")) == [("Viral", ["Cold", "Toxin"])]
    assert E.combinar_elementos(_mods("Heat", "Cold", "Toxin")) == [("Blast", ["Heat", "Cold"]), ("Toxin", ["Toxin"])]
    assert E.combinar_elementos(_mods("Electricity", "Toxin", "Heat", "Heat")) == [
        ("Corrosive", ["Electricity", "Toxin"]), ("Heat", ["Heat"])]


def test_clase_de_equipo():
    assert E.clase_de_equipo("Primary", "Shotgun") == "escopeta"
    assert E.clase_de_equipo("Primary", "Companion Weapon") == "rifle"
    assert E.clase_de_equipo("Secondary", "Pistol") == "pistola"
    assert E.clase_de_equipo("Melee", "Melee") == "cuerpo"
    assert E.clase_de_equipo("Warframes", "Warframe") == "warframe"
    assert E.clase_de_equipo("Misc", "Exalted Weapon") == "otro"


# -- ¿esta bien mi build? --------------------------------------------------------------------

def test_arma_de_critico_sin_dano_base_ni_multidisparo_ni_critico(indice):
    con, ids = indice
    ev = E.evaluar(con, ids["Soma Prime"], [ids["Hellfire"], ids["Speed Trigger"]])
    malos = _textos(ev.mal)
    assert "daño base" in malos and "Sierra" in malos
    assert "multidisparo" in malos
    assert "crítico (30 %)" in malos
    assert "Farmadex ve 2 mods; caben 8" in malos


def test_arma_bien_montada(indice):
    con, ids = indice
    orden = ["Serration", "Split Chamber", "Point Strike", "Vital Sense", "Cryo Rounds", "Infected Clip", "Hellfire",
             "Speed Trigger"]
    ev = E.evaluar(con, ids["Soma Prime"], [ids[n] for n in orden], capacidad=(2, 60))
    buenos = _textos(ev.bien)
    assert "Llevas daño base: Sierra" in buenos and "Llevas multidisparo: Cámara dividida" in buenos
    assert "Viral (Frío + Toxina), Calor" in buenos
    assert "llevas mods de crítico" in buenos and "todos los huecos" in buenos and "capacidad" in buenos
    assert ev.mal == []


def test_critico_de_sobra_en_un_arma_sin_critico(indice):
    con, ids = indice
    ev = E.evaluar(con, ids["Braton"], [ids["Serration"], ids["Point Strike"], ids["Vital Sense"]])
    sobra = [p for p in ev.mal if p.texto.startswith("Sobra")]
    assert sobra and "Punto de impacto" in sobra[0].texto and "5 %" in sobra[0].texto
    assert set(sobra[0].ids) == {ids["Point Strike"], ids["Vital Sense"]}


def test_versiones_del_mismo_mod_juntas(indice):
    con, ids = indice
    ev = E.evaluar(con, ids["Soma Prime"], [ids["Split Chamber"], ids["Galvanized Chamber"]])
    assert any("no se pueden llevar a la vez" in p.texto for p in ev.mal)


def test_capacidad(indice):
    con, ids = indice
    assert any("Te pasas" in p.texto for p in E.evaluar(con, ids["Soma Prime"], [ids["Serration"]], capacidad=(-3, 60)).mal)
    ev = E.evaluar(con, ids["Soma Prime"], [ids["Serration"]], capacidad=(20, 30))
    assert any("Te sobran 20" in p.texto for p in ev.mal) and any("baja (30)" in p.texto for p in ev.mal)


def test_warframe_sin_aguante_sin_aura_y_con_rabia_ciega(indice):
    con, ids = indice
    ev = E.evaluar(con, ids["Excalibur"], [ids["Blind Rage"], ids["Continuity"]], arcanos_ids=[])
    malos = _textos(ev.mal)
    assert "nada para aguantar" in malos and "ningún aura" in malos and "arcanos" in malos
    assert "te quita eficiencia" in malos
    consejo = next(p for p in ev.mal if "aguantar" in p.texto).porque
    assert "Vitalidad" in consejo and "Redirección" in consejo  # nombres del indice, no a mano


def test_warframe_bien(indice):
    con, ids = indice
    mods = ["Energy Siphon", "Vitality", "Redirection", "Intensify", "Continuity", "Stretch", "Streamline", "Flow",
            "Blind Rage"]
    ev = E.evaluar(con, ids["Excalibur"], [ids[n] for n in mods], arcanos_ids=[1])
    assert ev.mal == []
    assert "Sifón de energía" in _textos(ev.bien)


def test_sin_equipo_o_sin_datos(indice, con):
    con_, ids = indice
    ev = E.evaluar(con_, None, [ids["Serration"]])
    assert ev.mal and "warframe o arma" in ev.mal[0].texto
    con_.execute("DELETE FROM detalles")
    ev = E.evaluar(con_, ids["Soma Prime"], [ids["Serration"]])
    assert ev.sin_datos


# -- build basica ---------------------------------------------------------------------------

def _basica(con, ids, nombre, tengo=()):
    b = E.build_basica(con, ids[nombre], {ids[n] for n in tengo})
    return [(h.rol, h.mod.nombre_en if h.mod else None, h.tienes) for h in b.huecos]


def test_basica_de_un_rifle_de_critico(indice):
    con, ids = indice
    huecos = _basica(con, ids, "Soma Prime", tengo=["Serration"])
    nombres = [m for _r, m, _t in huecos]
    assert nombres[:7] == ["Serration", "Split Chamber", "Point Strike", "Vital Sense", "Cryo Rounds", "Infected Clip",
                           "Hellfire"]
    assert huecos[0][2] is True and huecos[1][2] is False  # la Sierra la tienes
    # Nada caro ni con efectos malos: ni Prime, ni Galvanizada, ni Amalgama, ni Calibre pesado.
    assert not {"Primed Cryo Rounds", "Galvanized Chamber", "Amalgam Serration", "Heavy Caliber"} & set(nombres)
    assert len(huecos) <= E.HUECOS


def test_basica_de_un_rifle_sin_critico_no_pone_critico(indice):
    con, ids = indice
    nombres = [m for _r, m, _t in _basica(con, ids, "Braton")]
    assert "Point Strike" not in nombres and "Vital Sense" not in nombres
    assert "Rifle Aptitude" in nombres  # sobra sitio: estado para los elementos


def test_basica_de_un_warframe_segun_su_escudo(indice):
    con, ids = indice
    excal = [m for _r, m, _t in _basica(con, ids, "Excalibur")]
    assert excal[0] == "Energy Siphon"  # aura de energia antes que la de correr
    assert excal[1:3] == ["Vitality", "Redirection"]
    assert {"Intensify", "Continuity", "Stretch", "Streamline", "Flow"} <= set(excal)
    assert "Primed Continuity" not in excal and "Umbral Fiber" not in excal
    inaros = [m for _r, m, _t in _basica(con, ids, "Inaros")]
    assert inaros[1:3] == ["Vitality", "Steel Fiber"]  # sin escudo: armadura


def test_basica_sin_datos(indice):
    con, ids = indice
    con.execute("DELETE FROM detalles WHERE item_id IN (SELECT id FROM items WHERE categoria = 'Mods')")
    E.olvidar_cache()
    assert E.build_basica(con, ids["Soma Prime"]).sin_datos
