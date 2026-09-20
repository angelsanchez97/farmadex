from farmadex.datos import indice, items


def test_la_reliquia_sabe_en_que_mision_cae(indice_poblado):
    import sqlite3

    con, _, _ = indice_poblado
    con.row_factory = sqlite3.Row
    reliquia_id = con.execute(
        "SELECT id FROM items WHERE nombre_en = 'Axi A7 Relic'"
    ).fetchone()[0]
    fuentes = [
        dict(f)
        for f in con.execute(
            "SELECT f.rotacion, f.probabilidad, n.nombre_en AS nodo, n.planeta_en, n.mision_en "
            "FROM fuentes f LEFT JOIN nodos n ON n.id = f.origen_id "
            "WHERE f.item_id = ? AND f.tipo = 'mision'",
            (reliquia_id,),
        ).fetchall()
    ]
    con.row_factory = None
    assert len(fuentes) == 2, "faltan misiones que sueltan la reliquia"
    hydron = next(f for f in fuentes if f["nodo"] == "Hydron")
    assert hydron["planeta_en"] == "Sedna"
    assert hydron["mision_en"] == "Defense"
    assert hydron["rotacion"] == "A"


def test_los_nombres_con_blueprint_casan_con_el_componente(indice_poblado):
    con, _, drops = indice_poblado
    chasis = indice.buscar(con, "chasis ash prime")[0]["item_id"]
    assert drops.item_id("Ash Prime Chassis Blueprint") == chasis


def test_lo_que_no_casa_se_cuenta_en_vez_de_romper(indice_poblado):
    _, _, drops = indice_poblado
    assert drops.item_id("Objeto Que No Existe En El Catalogo 12345") is None
    assert drops.sin_casar


def test_la_cadena_completa_parte_reliquia_mision(indice_poblado):
    """Sistemas de Ash Prime -> Axi A7 (en boveda) -> Hydron (Sedna)."""
    con, _, _ = indice_poblado
    parte = indice.buscar(con, "sistemas ash prime")[0]["item_id"]
    ficha = items.ficha(con, parte)
    reliquia_id = next(f["origen_id"] for f in ficha["fuentes"] if f["tipo"] == "reliquia")

    ficha_reliquia = items.ficha(con, reliquia_id)
    assert ficha_reliquia["item"]["vaulted"] == 1
    nodos = {f["nodo_en"] for f in ficha_reliquia["fuentes"] if f["tipo"] == "mision"}
    assert nodos == {"Hydron", "Abaddon"}
