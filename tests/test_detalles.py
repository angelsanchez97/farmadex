"""Estadisticas de armas, efecto por rango de mods y arcanos, habilidades y codigos de glifo."""

import json
import sqlite3

import httpx
import pytest

from farmadex.datos import detalles, glifos
from farmadex.datos.items import ImportadorItems, es_variante_menor

BRATON = {
    "uniqueName": "/Lotus/Weapons/Tenno/Rifle/BratonPrime", "name": "Braton Prime", "category": "Primary",
    "criticalChance": 0.12, "criticalMultiplier": 2, "procChance": 0.25999999, "fireRate": 9.583334,
    "magazineSize": 75, "reloadTime": 2.1500001, "multishot": 1, "trigger": "Auto", "masteryReq": 8,
    "disposition": 4, "omegaAttenuation": 1.25, "totalDamage": 35,
    "damage": {"total": 35, "impact": 1.75, "puncture": 12.25, "slash": 21, "heat": 0, "shieldDrain": 0},
}
SIERRA = {
    "uniqueName": "/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod", "name": "Serration", "category": "Mods",
    "polarity": "madurai", "rarity": "Common", "baseDrain": 4, "fusionLimit": 2, "compatName": "Rifle",
    "levelStats": [{"stats": ["+15% Damage"]}, {"stats": ["+30% Damage"]}, {"stats": ["+45% <DT_FIRE_COLOR>Heat"]}],
}
SIERRA_ES = {"name": "Sierra", "levelStats": [{"stats": ["+15% de daño"]}, {"stats": ["+30% de daño"]},
                                               {"stats": ["+45% de <DT_FIRE_COLOR>calor"]}]}
ENERGIZAR = {
    "uniqueName": "/Lotus/Upgrades/CosmeticEnhancers/Utility/Energize", "name": "Arcane Energize",
    "category": "Arcanes", "rarity": "Legendary",
    "levelStats": [{"stats": ["On Energy Pickup:\\n25 Energy"]},
                   {"stats": ["On Energy Pickup:\\n50 Energy\\n+1 Arcane Revive", "+1 Arcane Revive"]}],
}


def test_limpiar_quita_marcas_y_pone_saltos_de_linea():
    assert detalles.limpiar("+45% <DT_FIRE_COLOR>Heat") == "+45% Heat"
    assert detalles.limpiar("A:\\nB<LINE_SEPARATOR>C  <LOWER_IS_BETTER>") == "A:\nB\nC"
    assert detalles.limpiar(None) == ""


def test_estadisticas_de_un_arma():
    arma = detalles.extraer(BRATON, "Primary")["arma"]
    assert arma["critico"] == 0.12 and arma["mult_critico"] == 2.0
    assert arma["disposicion"] == 4.0 and arma["riven"] == 1.25
    # Solo los tipos de dano que hacen algo, sin los drenajes internos.
    assert arma["dano"] == {"impact": 1.75, "puncture": 12.25, "slash": 21.0}
    assert "alcance" not in arma and not arma["cuerpo_a_cuerpo"]


def test_efecto_por_rango_de_un_mod_en_los_dos_idiomas():
    mod = detalles.extraer(SIERRA, "Mods", SIERRA_ES)["mod"]
    assert mod["efecto"]["en"][-1] == "+45% Heat"
    assert mod["efecto"]["es"] == ["+15% de daño", "+30% de daño", "+45% de calor"]
    assert (mod["polaridad"], mod["drenaje"], mod["rango_max"], mod["compat"]) == ("madurai", 4.0, 2.0, "Rifle")
    assert detalles.efecto_en_idioma(mod["efecto"], castellano=False)[0] == "+15% Damage"


def test_un_arcano_no_repite_la_linea_suelta():
    arcano = detalles.extraer(ENERGIZAR, "Arcanes")["arcano"]
    assert arcano["efecto"]["en"][1] == "On Energy Pickup:\n50 Energy\n+1 Arcane Revive"
    # Sin traduccion con los mismos rangos, solo ingles.
    assert "es" not in arcano["efecto"]


def test_habilidades_de_un_warframe_y_pasiva_con_huecos_fuera():
    ash = {"uniqueName": "/Ash", "name": "Ash", "health": 455, "shield": 270, "armor": 105, "power": 100,
           "passiveDescription": "Slash deals |DAMAGE|% more",
           "abilities": [{"abilityUniqueName": "/A1", "abilityName": "Shuriken", "description": "Throws"}]}
    trad = {"abilities": [{"abilityUniqueName": "/A1", "abilityName": "Shuriken", "description": "Lanza"}]}
    wf = detalles.extraer(ash, "Warframes", trad)["warframe"]
    assert wf["energia"] == 100.0 and "pasiva" not in wf
    assert wf["habilidades"] == [{"en": "Shuriken", "es": "Shuriken", "desc_en": "Throws", "desc_es": "Lanza"}]


def test_lo_demas_no_trae_detalles():
    assert detalles.extraer({"name": "Cryotic"}, "Resources") == {}


def test_leer_con_un_indice_sin_la_tabla_no_rompe():
    con = sqlite3.connect(":memory:")
    assert detalles.leer(con, 1) == {}


def test_el_importador_guarda_los_detalles_y_se_mezclan(con, tmp_path):
    ruta = tmp_path / "Mods.json"
    ruta.write_text(json.dumps([SIERRA]), encoding="utf-8")
    importador = ImportadorItems(con, {SIERRA["uniqueName"]: SIERRA_ES})
    importador.importar_categoria(ruta)
    item_id = con.execute("SELECT id FROM items WHERE nombre_en = 'Serration'").fetchone()[0]
    detalles.guardar(con, item_id, {"glifo": {"codigo": "X"}})
    guardado = detalles.leer(con, item_id)
    assert guardado["mod"]["efecto"]["es"][0] == "+15% de daño" and guardado["glifo"] == {"codigo": "X"}


def test_la_sierra_de_verdad_se_queda_el_nombre_de_las_tablas(con, tmp_path):
    """La defectuosa (Beginner) sale antes en Mods.json y se llama igual: las tablas de
    drops tienen que casar con la de verdad."""
    flojo = {**SIERRA, "uniqueName": "/Lotus/Upgrades/Mods/Rifle/Beginner/WeaponDamageAmountModBeginner"}
    ruta = tmp_path / "Mods.json"
    ruta.write_text(json.dumps([flojo, SIERRA]), encoding="utf-8")
    importador = ImportadorItems(con, {})
    importador.importar_categoria(ruta)
    de_verdad = con.execute("SELECT id FROM items WHERE unique_name = ?", (SIERRA["uniqueName"],)).fetchone()[0]
    assert importador.alias["serration"] == de_verdad
    assert es_variante_menor(flojo["uniqueName"]) and not es_variante_menor(SIERRA["uniqueName"])


# -- codigos de glifos ------------------------------------------------------------------

WIKITEXT = """
==Promo Code/Drop Glyphs==
{{GlyphBoxPromo|TeshinGlyph.png|Teshin Glyph|WARWITHIN|Given out during Update 19}}
==Creator Glyphs==
{{GlyphBoxPromo|13angTVGlyph.png|13angTV}}
{{GlyphBoxPromo|Goku70sevenGlyphW7.png|Goku707|Amprov}}
{{GlyphBoxPromo|Roto.png|Codigo roto|con espacios}}
"""


def test_leer_wikitext_con_los_dos_formatos_de_la_plantilla():
    pares = glifos.leer_wikitext(WIKITEXT)
    assert ("Teshin Glyph", "WARWITHIN") in pares
    assert ("13angTV", "13angTV") in pares  # sin tercer campo: nombre y codigo a la vez
    assert ("Goku707", "Amprov") in pares
    assert all(codigo != "con espacios" for _, codigo in pares)


def test_aplicar_casa_por_nombre_sin_mayusculas_ni_la_palabra_glyph(con):
    for i, nombre in enumerate(("Teshin Glyph", "13angtv Glyph", "Otro Glyph"), start=1):
        con.execute("INSERT INTO items (id, unique_name, nombre_en, categoria) VALUES (?, ?, ?, 'Glyphs')",
                    (i, f"/g/{i}", nombre))
    assert glifos.aplicar(con, glifos.leer_wikitext(WIKITEXT)) == 2
    assert detalles.leer(con, 1)["glifo"]["codigo"] == "WARWITHIN"
    assert detalles.leer(con, 2)["glifo"]["codigo"] == "13angTV"
    assert detalles.leer(con, 3) == {}


def test_descargar_guarda_copia_y_sin_red_usa_la_guardada(tmp_path):
    respuesta = {"parse": {"wikitext": {"*": WIKITEXT}}}
    bien = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=respuesta)))
    assert ("Teshin Glyph", "WARWITHIN") in glifos.descargar(bien, tmp_path)
    assert (tmp_path / glifos.NOMBRE_FICHERO).exists()

    def sin_red(peticion):
        raise httpx.ConnectError("sin red")

    mal = httpx.Client(transport=httpx.MockTransport(sin_red))
    assert ("Teshin Glyph", "WARWITHIN") in glifos.descargar(mal, tmp_path)
    assert glifos.descargar(mal, tmp_path / "vacia") == []


@pytest.mark.parametrize("codigo", ["WARWITHIN", "13angTV"])
def test_url_de_canje(codigo):
    assert glifos.url_canje(codigo).endswith(f"code={codigo}")
