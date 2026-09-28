"""Arreglos de la auditoria de datos contra la tabla oficial de DE (2026-09-28).

Cada prueba reproduce, en pequeno, un fallo que se vio en el indice real: Requiem en
boveda, drops colgados de la pieza de otro objeto, eventos triplicados, sabotajes con el
modo de un evento viejo y premios repetidos de una reliquia que se perdian.
"""
from __future__ import annotations

import json

from farmadex.datos import eficiencia, indice, nodos, tabla_oficial
from farmadex.datos.drops import ImportadorDrops, _sin_tabla_repetida
from farmadex.datos.items import ImportadorItems, normalizar
from farmadex.datos.tabla_oficial import PREFIJO_SINTETICO


def _alta(con, nombre, categoria="Misc", padre=None, unico=None, nombre_es=None, **extra):
    cur = con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, padre_id, vaulted) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (unico or f"/Prueba/{nombre}/{padre}", nombre, nombre_es, categoria, padre,
         extra.get("vaulted")),
    )
    return cur.lastrowid


# -- 1. Requiem ---------------------------------------------------------------------

def test_las_requiem_nunca_estan_en_boveda(con):
    requiem = _alta(con, "Requiem II Relic", "Relics", vaulted=1)
    lith = _alta(con, "Lith A1 Relic", "Relics", vaulted=0)
    con.execute("INSERT INTO fuentes (item_id, tipo, origen_texto) VALUES (?, 'mision', 'Mercury/Apollodorus')", (lith,))
    indice.corregir_boveda(con)
    assert con.execute("SELECT vaulted FROM items WHERE id = ?", (requiem,)).fetchone()[0] == 0


def test_el_comodin_requiem_relic_no_es_una_reliquia(con):
    importador = ImportadorItems(con, {})
    importador._importar_reliquia({"name": "Requiem Relic", "uniqueName": "/x/RequiemRandom", "rewards": []})
    importador._importar_reliquia({"name": "Requiem IV Intact", "uniqueName": "/x/RequiemIV", "rewards": []})
    nombres = [n for (n,) in con.execute("SELECT nombre_en FROM items WHERE categoria = 'Relics'")]
    assert nombres == ["Requiem IV Relic"]


def test_la_reliquia_sintetica_se_escribe_normal():
    assert tabla_oficial._nombre_reliquia("ETERNA") == "Eterna"
    assert tabla_oficial._nombre_reliquia("iv") == "IV"
    assert tabla_oficial._nombre_reliquia("c10") == "C10"
    assert tabla_oficial._nombre_reliquia("A1") == "A1"


# -- 2. Drops al objeto equivocado ---------------------------------------------------

def test_el_plano_con_padre_delante_va_a_la_pieza_de_ese_padre(con):
    fuselaje_rj = _alta(con, "Fuselage")
    plano_rj = _alta(con, "Blueprint", padre=fuselaje_rj)
    xiphos = _alta(con, "Xiphos")
    fuselaje_xiphos = _alta(con, "Fuselage", padre=xiphos)
    alias = {"xiphos fuselage blueprint": plano_rj, "xiphos fuselage": fuselaje_xiphos,
             "fuselage blueprint": plano_rj}
    drops = ImportadorDrops(con, alias)
    assert drops.item_id("Xiphos Fuselage Blueprint") == fuselaje_xiphos
    assert drops.item_id("Fuselage Blueprint") == plano_rj  # el de verdad sigue casando
    assert "Xiphos Fuselage Blueprint" in drops.padre_equivocado


def test_las_palabras_del_padre_valen_aunque_no_sea_el_nombre_entero(con):
    collar = _alta(con, "Kavasa Prime Kubrow Collar", "Pets")
    banda = _alta(con, "Kavasa Prime Band", "Pets", padre=collar)
    hebilla = _alta(con, "Buckle", "Pets", padre=collar)
    drops = ImportadorDrops(con, {"kavasa prime band": banda, "kavasa prime buckle": hebilla})
    assert drops.item_id("Kavasa Prime Band") == banda
    assert drops.item_id("Kavasa Prime Buckle") == hebilla


def test_la_pieza_colgada_de_otro_arma_crea_una_sintetica_con_su_padre(con):
    pride = _alta(con, "Pride", "Melee")
    hoja_pride = _alta(con, "Blade", "Melee", padre=pride, nombre_es="Hoja")
    wrath = _alta(con, "Wrath", "Melee")
    alias = {"pride": pride, "wrath": wrath, "wrath blade": hoja_pride,
             "wrath blade blueprint": hoja_pride}
    drops = ImportadorDrops(con, alias)
    nuevo = drops.item_id("Wrath Blade Blueprint")
    assert nuevo not in (None, hoja_pride)
    fila = con.execute("SELECT nombre_en, nombre_es, padre_id, unique_name, tipo FROM items WHERE id = ?",
                       (nuevo,)).fetchone()
    assert fila[:3] == ("Blade", "Hoja", wrath)
    assert fila[3].startswith(PREFIJO_SINTETICO) and fila[4] == "Componente"
    # Y la segunda vez no se crea otra.
    assert ImportadorDrops(con, alias).item_id("Wrath Blade Blueprint") == nuevo


def test_equinox_dia_y_noche_tienen_sus_piezas_y_su_receta(con):
    equinox = _alta(con, "Equinox", "Warframes")
    dia = _alta(con, "Day Aspect", "Warframes", padre=equinox)
    noche = _alta(con, "Night Aspect", "Warframes", padre=equinox)
    drops = ImportadorDrops(con, {"equinox": equinox, "equinox day aspect": dia,
                                  "equinox night aspect": noche})
    chasis = drops.item_id("Equinox Day Chassis Blueprint")
    sistemas = drops.item_id("Equinox Night Systems Blueprint")
    assert con.execute("SELECT nombre_en, padre_id FROM items WHERE id = ?", (chasis,)).fetchone() == (
        "Day Chassis", equinox)
    assert con.execute("SELECT padre_id FROM recetas WHERE item_id = ?", (chasis,)).fetchone()[0] == dia
    assert con.execute("SELECT padre_id FROM recetas WHERE item_id = ?", (sistemas,)).fetchone()[0] == noche
    # El casador ya los conoce por su nombre completo.
    assert drops.alias[normalizar("Equinox Day Chassis")] == chasis


def test_no_se_inventa_pieza_si_ya_hay_una_parecida(con):
    keratinos = _alta(con, "Keratinos", "Melee")
    hojas = _alta(con, "Blades", "Melee", padre=keratinos)
    drops = ImportadorDrops(con, {"keratinos": keratinos, "keratinos blades": hojas,
                                  "keratinos blades blueprint": hojas})
    assert drops.item_id("Keratinos Blade Blueprint") == hojas
    assert not drops.sinteticos


# -- 3. Eventos ---------------------------------------------------------------------

def test_la_tabla_de_evento_repetida_cuenta_una_vez_y_los_repetidos_de_verdad_se_quedan():
    tabla = [{"itemName": n, "chance": c, "rarity": "Uncommon"}
             for n, c in (("Vitality", 10.84), ("Rush", 11.06), ("Stretch", 0.34))]
    assert _sin_tabla_repetida(tabla * 3) == tabla
    hepit = tabla + [{"itemName": "Vitality", "chance": 10.84, "rarity": "Uncommon"}]
    assert _sin_tabla_repetida(hepit) == hepit
    assert _sin_tabla_repetida(tabla[:1] * 2) == tabla[:1] * 2  # dos filas no son una tabla


def test_mision_de_evento_sin_triplicar_y_marcada(con):
    tabla = [{"itemName": "Vitality", "chance": 10.84, "rarity": "Uncommon"},
             {"itemName": "Rush", "chance": 11.06, "rarity": "Uncommon"},
             {"itemName": "Stretch", "chance": 0.34, "rarity": "Rare"}]
    for nombre in ("Vitality", "Rush", "Stretch"):
        _alta(con, nombre, "Mods")
    alias = {normalizar(n): i for i, n in con.execute("SELECT id, nombre_en FROM items")}
    drops = ImportadorDrops(con, alias)
    drops.mission_rewards({"missionRewards": {"Europa": {"Cryotic Front": {
        "gameMode": "Capture", "isEvent": True, "rewards": tabla * 3}}}})
    filas = con.execute("SELECT probabilidad, datos_extra FROM fuentes WHERE tipo = 'mision'").fetchall()
    assert sorted(p for p, _ in filas) == [0.34, 10.84, 11.06]
    assert all(json.loads(e)["evento"] for _, e in filas)


def test_la_cabecera_repetida_de_la_tabla_de_de_no_crea_otro_nodo():
    fila = '<tr><th colspan="2">Event: Europa/Cryotic Front (Capture)</th></tr>' \
           '<tr><td>Vitality</td><td>Uncommon (10.84%)</td></tr>' \
           '<tr><td>Rush</td><td>Uncommon (11.06%)</td></tr>'
    excavacion = '<tr><th colspan="2">Event: Europa/Cryotic Front (Excavation)</th></tr>' \
                 '<tr><th colspan="2">Rotation A</th></tr><tr><td>Flow</td><td>Rare (5.00%)</td></tr>'
    misiones = tabla_oficial._leer_misiones(fila + excavacion + fila + fila)
    europa = misiones["Europa"]
    assert set(europa) == {"Cryotic Front", "Cryotic Front (Excavation)"}
    assert [p["itemName"] for p in europa["Cryotic Front"]["rewards"]] == ["Vitality", "Rush"]
    assert europa["Cryotic Front"]["isEvent"] is True


def test_la_mision_de_evento_no_se_estima_ni_se_recomienda():
    f = {"tipo": "mision", "origen_texto": "Europa/Cryotic Front", "probabilidad": 10.84,
         "modo": "Capture", "datos_extra": json.dumps({"modo": "Capture", "evento": True})}
    eficiencia.estimar(f)
    assert f["motivo"] == "evento" and f["minutos_medios"] is None
    normal = dict(f, datos_extra=json.dumps({"modo": "Capture", "evento": False}))
    eficiencia.estimar(normal)
    assert normal["motivo"] == "estimado" and normal["minutos_medios"]
    assert eficiencia.clave_orden(normal) < eficiencia.clave_orden(f)


# -- 4. Sabotajes -------------------------------------------------------------------

def test_los_sabotajes_recuperan_su_modo(con):
    def nodo(nombre, modo):
        return con.execute(
            "INSERT INTO nodos (unique_name, nombre_en, planeta_en, mision_en, clave_drops) "
            "VALUES (?, ?, 'Mercury', ?, ?)", (nombre, nombre, modo, f"Mercury/{nombre}"),
        ).lastrowid
    neruda = nodo("Neruda", "Ancient Retribution")
    terminus = nodo("Terminus", None)
    suelto = nodo("Sin Alijos", None)
    exterminio = nodo("Apollodorus", "Exterminate")
    mod = _alta(con, "Vitality", "Mods")
    for nid, texto in ((terminus, "Mercury/Terminus (Caches)"), (exterminio, "Mercury/Apollodorus (Caches)")):
        con.execute("INSERT INTO fuentes (item_id, tipo, origen_texto, origen_id) VALUES (?, 'mision', ?, ?)",
                    (mod, texto, nid))
    assert nodos.corregir_modos(con) == 2
    modos = dict(con.execute("SELECT id, mision_en FROM nodos"))
    assert modos[neruda] == modos[terminus] == "Sabotage"
    assert modos[suelto] is None and modos[exterminio] == "Exterminate"
    assert con.execute("SELECT mision_es FROM nodos WHERE id = ?", (neruda,)).fetchone()[0] == "Sabotaje"


# -- 5. Premios repetidos en una reliquia -------------------------------------------

def test_el_premio_repetido_de_una_reliquia_suma_sus_probabilidades(con):
    reliquia = _alta(con, "Meso D1 Relic", "Relics")
    forma = _alta(con, "Forma", "Resources")
    plano = _alta(con, "Blueprint", "Resources", padre=forma)
    drops = ImportadorDrops(con, {"meso d1 relic": reliquia, "forma blueprint": plano, "forma": forma})
    drops.relics({"relics": [{"tier": "Meso", "relicName": "D1", "state": "Intact", "rewards": [
        {"itemName": "2X Forma Blueprint", "chance": 25.33, "rarity": "Common"},
        {"itemName": "Forma Blueprint", "chance": 11.0, "rarity": "Uncommon"},
    ]}]})
    assert con.execute("SELECT item_id, probabilidad FROM reliquia_recompensas").fetchall() == [(plano, 36.33)]
    assert con.execute("SELECT probabilidad FROM fuentes WHERE tipo = 'reliquia'").fetchall() == [(36.33,)]


def test_las_misiones_del_catalogo_de_la_pieza_confundida_se_quitan(con):
    fuselaje_rj = _alta(con, "Fuselage")
    plano_rj = _alta(con, "Blueprint", padre=fuselaje_rj)
    xiphos = _alta(con, "Xiphos")
    fuselaje_xiphos = _alta(con, "Fuselage", padre=xiphos)
    for texto in ("Venus/Ishtar (Caches), Rotation C", "Vem Tabook", "Earth/Otro Sitio, Rotation A"):
        con.execute("INSERT INTO fuentes (item_id, tipo, origen_texto) VALUES (?, 'otro', ?)", (plano_rj, texto))
    drops = ImportadorDrops(con, {"xiphos fuselage blueprint": plano_rj, "xiphos fuselage": fuselaje_xiphos})
    drops.mission_rewards({"missionRewards": {"Venus": {"Ishtar (Caches)": {
        "gameMode": "Caches", "isEvent": False,
        "rewards": {"C": [{"itemName": "Xiphos Fuselage Blueprint", "chance": 0.5, "rarity": "Rare"}]}}}}})
    assert drops.quitar_misiones_ajenas() == 1
    quedan = [t for (t,) in con.execute("SELECT origen_texto FROM fuentes WHERE item_id = ?", (plano_rj,))]
    assert quedan == ["Vem Tabook", "Earth/Otro Sitio, Rotation A"]
    assert con.execute("SELECT count(*) FROM fuentes WHERE item_id = ? AND tipo = 'mision'",
                       (fuselaje_xiphos,)).fetchone()[0] == 1


def test_rareza_de_reliquia_sale_de_la_probabilidad():
    import sqlite3

    from farmadex.datos.indice import corregir_rareza_reliquias

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE reliquia_recompensas (reliquia_id INTEGER, refinamiento TEXT, item_id INTEGER, "
                "rareza TEXT, probabilidad REAL)")
    con.executemany("INSERT INTO reliquia_recompensas VALUES (1, ?, ?, ?, ?)", [
        ("Intact", 1, "Uncommon", 25.33), ("Radiant", 2, "Uncommon", 10.0), ("Radiant", 3, "Common", 20.0),
        ("Radiant", 4, "Uncommon", 16.67), ("Intact", 5, "Rare", 9.5),
    ])
    assert corregir_rareza_reliquias(con) == 4
    rarezas = dict(con.execute("SELECT item_id, rareza FROM reliquia_recompensas").fetchall())
    assert rarezas == {1: "Common", 2: "Rare", 3: "Uncommon", 4: "Common", 5: "Rare"}
