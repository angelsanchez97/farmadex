from farmadex.datos import indice, nodos, relaciones


def test_reliquias_de_agrupa_refinamientos(indice_poblado):
    con, _, _ = indice_poblado
    parte = indice.buscar(con, "sistemas ash prime")[0]["item_id"]
    reliquias = relaciones.reliquias_de(con, parte)

    assert len(reliquias) == 1
    r = reliquias[0]
    assert r["nombre_en"] == "Axi A7 Relic"
    assert r["vaulted"] is True
    assert r["probabilidades"]["Radiant"] == 20.0
    assert r["probabilidades"]["Intact"] == 2.0


def test_ocultar_vaulted_deja_la_lista_vacia(indice_poblado):
    con, _, _ = indice_poblado
    parte = indice.buscar(con, "sistemas ash prime")[0]["item_id"]
    assert relaciones.reliquias_de(con, parte, incluir_vaulted=False) == []


def test_misiones_de_la_reliquia_con_nodo_y_rotacion(indice_poblado):
    con, _, _ = indice_poblado
    reliquia = con.execute("SELECT id FROM items WHERE nombre_en = 'Axi A7 Relic'").fetchone()[0]
    misiones = relaciones.misiones_de(con, reliquia)

    assert len(misiones) == 2
    mejor = misiones[0]
    assert mejor["donde"] in ("Hydron, Sedna", "Abaddon, Europa")
    assert mejor["probabilidad"] > 0
    hydron = next(m for m in misiones if m["donde"].startswith("Hydron"))
    assert hydron["rotacion"] == "A"
    assert hydron["mision"] == "Defensa"  # gameMode traducido por el glosario


def test_mejor_ruta_avisa_cuando_todo_esta_en_boveda(indice_poblado):
    con, _, _ = indice_poblado
    parte = indice.buscar(con, "sistemas ash prime")[0]["item_id"]
    ruta = relaciones.mejor_ruta(con, parte)

    assert ruta["solo_en_boveda"] is True
    assert ruta["reliquia"]["nombre_en"] == "Axi A7 Relic"
    assert ruta["mision"]["donde"].endswith(("Sedna", "Europa"))


def test_contenido_de_la_reliquia(indice_poblado):
    con, _, _ = indice_poblado
    reliquia = con.execute("SELECT id FROM items WHERE nombre_en = 'Axi A7 Relic'").fetchone()[0]
    contenido = relaciones.contenido_de(con, reliquia, "Radiant")

    assert [c["nombre_en"] for c in contenido] == ["Systems"]
    assert contenido[0]["padre_en"] == "Ash Prime"
    assert contenido[0]["probabilidad"] == 20


def test_nombre_bonito_traduce_el_planeta(con):
    assert nodos.nombre_bonito(con, "Venus/Bifrost Echo (Caches)") == "Bifrost Echo (Caches), Venus"
    assert nodos.nombre_bonito(con, "Earth/Cambria") == "Cambria, Tierra"
    assert nodos.nombre_bonito(con, "Sin barra") == "Sin barra"


def test_reenlazar_quita_los_sufijos_de_las_tablas(indice_poblado):
    con, _, _ = indice_poblado
    reliquia = con.execute("SELECT id FROM items WHERE nombre_en = 'Axi A7 Relic'").fetchone()[0]
    con.execute(
        "INSERT INTO fuentes (item_id, tipo, origen_texto, probabilidad) "
        "VALUES (?, 'mision', 'Sedna/Hydron (Caches)', 3.0)",
        (reliquia,),
    )
    resultado = nodos.reenlazar_fuentes(con)
    assert resultado["enlazadas"] == 1

    fila = con.execute(
        "SELECT origen_id FROM fuentes WHERE origen_texto = 'Sedna/Hydron (Caches)'"
    ).fetchone()
    nodo = con.execute("SELECT nombre_en FROM nodos WHERE id = ?", (fila[0],)).fetchone()
    assert nodo[0] == "Hydron"


def test_solnodes_de_wfcd_completa_el_mapa_sin_duplicar(indice_poblado):
    con, _, drops = indice_poblado
    # Las tablas de drops dieron de alta 'Uranus/Cordelia' por nombre, sin id de DE.
    drops.crear_nodo("Uranus", "Cordelia", "Sabotage")
    antes = con.execute("SELECT COUNT(*) FROM nodos").fetchone()[0]
    hydron = con.execute("SELECT unique_name FROM nodos WHERE nombre_en = 'Hydron'").fetchone()[0]

    resultado = nodos.aplicar_solnodes(con, {
        hydron: {"value": "Hydron (Sedna)", "enemy": "Grineer", "type": "Defense"},  # ya existe: DE manda
        "SolNode3": {"value": "Cordelia (Uranus)", "enemy": "Grineer", "type": "Sabotage"},
        "CrewBattleNode501": {"value": "Nsu Grid (Veil Proxima)", "enemy": "Grineer", "type": "Skirmish"},
        "EventNode0": {"value": "Balor", "enemy": "Grineer", "type": "Extermination"},
        "SolNode0": {"value": "SolNode0"},  # ni WFCD sabe que es
        "SolNode999": "no es un objeto",
        "SolNode998": {"value": "Hydron (Sedna)", "type": "Defense"},  # mismo nombre que uno de DE: otro id
    })
    assert resultado == {"anadidos": 3, "enlazados": 1, "descartados": 1}
    assert con.execute("SELECT COUNT(*) FROM nodos").fetchone()[0] == antes + 3

    cordelia = con.execute(
        "SELECT unique_name, planeta_es, mision_es FROM nodos WHERE nombre_en = 'Cordelia'"
    ).fetchall()
    assert cordelia == [("SolNode3", "Urano", "Sabotaje")]
    veil = con.execute("SELECT planeta_en, mision_en, faccion_en FROM nodos WHERE unique_name = 'CrewBattleNode501'").fetchone()
    assert veil == ("Veil Proxima", "Skirmish", "Grineer")
    balor = con.execute("SELECT planeta_en, clave_drops FROM nodos WHERE unique_name = 'EventNode0'").fetchone()
    assert balor == ("Event", "Event/Balor")
    # El homonimo de Hydron entra sin clave de drops, para no pisar al de DE.
    assert con.execute("SELECT clave_drops FROM nodos WHERE unique_name = 'SolNode998'").fetchone() == (None,)
    # Segunda pasada: nada cambia.
    assert nodos.aplicar_solnodes(con, {"SolNode3": {"value": "Cordelia (Uranus)"}})["anadidos"] == 0


# -- rutas que no pasan por reliquias ----------------------------------------


def _rhino(con):
    """Un Rhino de mentira con las fuentes reales que tiene el indice, mas ruido."""
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria) VALUES "
        "('/Lotus/Powersuits/Rhino/Rhino', 'Rhino', 'Rhino', 'Warframes')"
    )
    padre = con.execute("SELECT id FROM items WHERE nombre_en = 'Rhino'").fetchone()[0]
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, padre_id) VALUES "
        "('/Lotus/Types/Recipes/WarframeRecipes/RhinoChassisComponent', 'Chassis', 'Chasis', 'Warframes', ?)",
        (padre,),
    )
    chasis = con.execute("SELECT id FROM items WHERE padre_id = ?", (padre,)).fetchone()[0]
    con.execute(
        "INSERT INTO nodos (unique_name, nombre_en, planeta_en, planeta_es, mision_en, nivel_min, nivel_max, clave_drops) "
        "VALUES ('SolNode1', 'Fossa', 'Venus', 'Venus', 'Assassination', 6, 8, 'Venus/Fossa')"
    )
    fossa = con.execute("SELECT id FROM nodos WHERE nombre_en = 'Fossa'").fetchone()[0]
    filas = [
        # La de verdad: el Chacal en Fossa.
        ("mision", fossa, "Venus/Fossa", None, "Common", 38.72, None, None,
         '{"modo": "Assassination", "evento": false}'),
        # Duplicado que dejan las tablas de drops en 'otro'.
        ("otro", None, "Venus/Fossa (Assassination)", None, "Common", 38.72, None, None, None),
        # Ruido: un enemigo con mas probabilidad nominal pero que casi nunca suelta nada.
        ("enemigo", None, "Tusk Thumper Bull", None, None, 60.0, 15.0, None, None),
        # Un sindicato lo da al 100 %: accesible solo con reputacion.
        ("sindicato", None, "Red Veil", None, None, 100.0, None, 1000, '{"lugar": "Red Veil, Respected"}'),
        # Conclave, siempre lo ultimo.
        ("otro", None, "Conclave, Mistral", None, None, 100.0, None, None, None),
    ]
    con.executemany(
        "INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, rotacion, rareza, probabilidad, "
        "probabilidad_enemigo, standing, datos_extra) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(chasis, *f) for f in filas],
    )
    return chasis


def test_mejor_ruta_sin_reliquia_elige_la_mision(indice_poblado):
    con, _, _ = indice_poblado
    chasis = _rhino(con)
    ruta = relaciones.mejor_ruta(con, chasis)

    assert ruta is not None, "antes decia 'sin ruta conocida'"
    assert ruta["tipo"] == "mision" and ruta["reliquia"] is None
    assert ruta["solo_en_boveda"] is False
    assert ruta["mision"]["donde"] == "Fossa, Venus"
    assert ruta["mision"]["mision"] == "Asesinato"
    assert ruta["probabilidad"] == 38.72


def test_fuentes_de_ordena_por_probabilidad_y_accesibilidad(indice_poblado):
    con, _, _ = indice_poblado
    chasis = _rhino(con)
    fuentes = relaciones.fuentes_de(con, chasis)

    assert [f["tipo"] for f in fuentes] == ["mision", "enemigo", "sindicato", "otro"]
    # El 'otro' de Fossa era un duplicado y no aparece; Conclave si, pero al final.
    assert [f["donde"] for f in fuentes] == [
        "Fossa, Venus", "Tusk Thumper Bull", "Red Veil, Respected", "Conclave, Mistral",
    ]
    enemigo = fuentes[1]
    # 60 % de que sea este mod x 15 % de que el enemigo suelte un mod = 9 %.
    assert enemigo["probabilidad_efectiva"] == 9.0
    assert fuentes[0]["nivel_min"] == 6
    assert [f["grado"] for f in fuentes] == [0, 0, 2, 3]


def test_las_reliquias_siguen_mandando_cuando_las_hay(indice_poblado):
    con, _, _ = indice_poblado
    parte = indice.buscar(con, "sistemas ash prime")[0]["item_id"]
    ruta = relaciones.mejor_ruta(con, parte)
    assert ruta["tipo"] == "reliquia" and ruta["reliquia"]["nombre_en"] == "Axi A7 Relic"
    assert ruta["probabilidad"] == 20.0


def test_sin_ninguna_fuente_sigue_sin_ruta(indice_poblado):
    con, _, _ = indice_poblado
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, categoria) VALUES ('/Lotus/X', 'Plano de tienda', 'Warframes')"
    )
    iid = con.execute("SELECT id FROM items WHERE unique_name = '/Lotus/X'").fetchone()[0]
    assert relaciones.mejor_ruta(con, iid) is None
