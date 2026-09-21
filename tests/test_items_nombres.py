"""Nombres del catalogo tal como llegan de verdad: con etiquetas de icono, piezas cuyo
nombre ya identifica al objeto, y tablas de drops con numeros escritos como texto."""

import json

from farmadex.datos import indice
from farmadex.datos.drops import ImportadorDrops
from farmadex.datos.items import ImportadorItems, _numero
from farmadex.datos.relaciones import fuentes_de


def _importar(con, tmp_path, catalogos: dict, i18n: dict | None = None) -> ImportadorItems:
    importador = ImportadorItems(con, i18n or {})
    for nombre, objetos in catalogos.items():
        ruta = tmp_path / f"{nombre}.json"
        ruta.write_text(json.dumps(objetos), encoding="utf-8")
        importador.importar_categoria(ruta)
    importador.promocionar_ingredientes()
    importador.registrar_piezas_con_nombre_propio()
    indice.poblar_busqueda(con)
    con.commit()
    return importador


def test_las_etiquetas_de_icono_no_entran_en_el_nombre(con, tmp_path):
    # 75 objetos del catalogo real llevan "<ARCHWING> " o "<Shard_red_simple> " delante.
    importador = _importar(
        con, tmp_path,
        {"Misc": [{"uniqueName": "/x/Shard", "name": "<Shard_red_simple> Crimson Archon Shard",
                   "category": "Misc"}],
         "Arch-Melee": [{"uniqueName": "/a/Agkuza", "name": "Agkuza", "category": "Arch-Melee"}]},
        i18n={"/a/Agkuza": {"name": "<ARCHWING> Agkuza"},
              "/x/Shard": {"name": "<SHARD_RED_SIMPLE> Fragmento Carmesi de Arconte"}},
    )
    assert con.execute("SELECT nombre_en, nombre_es FROM items WHERE unique_name = '/x/Shard'").fetchone() == (
        "Crimson Archon Shard", "Fragmento Carmesi de Arconte")
    assert con.execute("SELECT nombre_es FROM items WHERE unique_name = '/a/Agkuza'").fetchone()[0] == "Agkuza"
    # Las tablas de drops escriben el nombre limpio, y la busqueda lo encuentra exacto.
    assert ImportadorDrops(con, importador.alias).item_id("Crimson Archon Shard")
    assert indice.buscar(con, "agkuza")[0]["nivel"] == 0


def test_una_pieza_con_nombre_propio_casa_por_su_nombre_a_secas(con, tmp_path):
    importador = _importar(con, tmp_path, {
        "Skins": [{"uniqueName": "/s/Kavasa", "name": "Kavasa Prime Kubrow Collar", "category": "Skins",
                   "components": [{"uniqueName": "/s/Kavasa/Band", "name": "Kavasa Prime Band"},
                                  {"uniqueName": "/s/Kavasa/Buckle", "name": "Kavasa Prime Buckle"}]}],
        "Melee": [{"uniqueName": "/m/BrokenWar", "name": "Broken War", "category": "Melee",
                   "components": [{"uniqueName": "/m/BrokenWar/Blade", "name": "War Blade"}]},
                  {"uniqueName": "/m/Cernos", "name": "Cernos", "category": "Melee",
                   "components": [{"uniqueName": "/m/Cernos/Limb", "name": "Upper Limb"}]},
                  {"uniqueName": "/m/Paris", "name": "Paris", "category": "Melee",
                   "components": [{"uniqueName": "/m/Paris/Limb", "name": "Upper Limb"}]}],
        "Warframes": [{"uniqueName": "/w/Volt", "name": "Volt", "category": "Warframes",
                       "components": [{"uniqueName": "/w/Volt/Neu", "name": "Neuroptics"}]},
                      {"uniqueName": "/w/Chroma", "name": "Chroma", "category": "Warframes",
                       "components": [{"uniqueName": "/w/Chroma/VoltNeu", "name": "Volt Neuroptics"}]}],
    })
    drops = ImportadorDrops(con, importador.alias)
    ids = dict(con.execute("SELECT unique_name, id FROM items"))
    # Asi las nombran relics.json y enemyBlueprintTables.json.
    assert drops.item_id("Kavasa Prime Band") == ids["/s/Kavasa/Band"]
    assert drops.item_id("Kavasa Prime Buckle Blueprint") == ids["/s/Kavasa/Buckle"]
    assert drops.item_id("War Blade") == ids["/m/BrokenWar/Blade"]
    # Un nombre que comparten varias piezas no vale como alias: seria de cualquiera.
    assert "upper limb" not in importador.alias
    # La receta de Chroma pide "Volt Neuroptics", pero ese nombre es de la pieza de Volt.
    assert drops.item_id("Volt Neuroptics") == ids["/w/Volt/Neu"]


def test_los_numeros_escritos_como_texto_se_guardan_como_numero(con, tmp_path):
    assert _numero("25.33%") == 25.33
    assert _numero("7,5") == 7.5
    assert _numero(True) is None
    assert _numero(["basura"]) is None

    importador = _importar(con, tmp_path, {
        "Mods": [{"uniqueName": "/m/Serration", "name": "Serration", "category": "Mods",
                  "drops": [{"location": "Grineer Lancer", "chance": "3.5%", "rarity": ["Rare"]}]}],
        "Relics": [{"uniqueName": "/r/AxiA1", "name": "Axi A1 Intact", "category": "Relics",
                    "rewards": [{"item": {"uniqueName": "/m/Serration"}, "chance": "25.33", "rarity": "Common"}]}],
    })
    drops = ImportadorDrops(con, importador.alias)
    ruta = tmp_path / "missionRewards.json"
    ruta.write_text(json.dumps({"missionRewards": {"Sedna": {"Hydron": {"gameMode": "Defense",
        "rewards": {"A": [{"itemName": "Serration", "chance": "11%", "rarity": ["Uncommon"]}]}}}}}),
        encoding="utf-8")
    drops.mission_rewards(ruta)
    serration = con.execute("SELECT id FROM items WHERE unique_name = '/m/Serration'").fetchone()[0]
    assert con.execute(
        "SELECT tipo, probabilidad, rareza FROM fuentes WHERE item_id = ? ORDER BY tipo", (serration,)
    ).fetchall() == [("mision", 11.0, "Uncommon"), ("otro", 3.5, "Rare")]
    assert con.execute("SELECT probabilidad FROM reliquia_recompensas").fetchone() == (25.33,)
    # La ficha ordena por probabilidad efectiva: con texto reventaba en float().
    assert [f["probabilidad_efectiva"] for f in fuentes_de(con, serration)] == [11.0, 3.5]


def test_las_recompensas_que_no_son_objetos_no_cuentan_como_sin_casar(con):
    drops = ImportadorDrops(con, {})
    for nombre in ("2X 3,000 Credits Cache", "10,000 Hollars Cache", "Return: 105,000",
                   "3 Day Affinity Booster", "Resource Drop Chance Booster", "400 Endo", "1,200 Kuva"):
        assert drops.item_id(nombre) is None
    assert not drops.sin_casar
    assert drops.item_id("Kavasa Prime Band") is None
    assert drops.sin_casar == {"Kavasa Prime Band": 1}
