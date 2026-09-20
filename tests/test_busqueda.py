"""Orden de los resultados de busqueda y tolerancia a erratas, sobre un catalogo pequeno
que imita al real: lo farmeable, sus piezas y la marea de adornos que lo rodea."""

import json

import pytest

from farmadex.datos import indice

# (unique_name, nombre_en, nombre_es, categoria, padre, con_fuentes)
CATALOGO = [
    ("/w/Ash", "Ash", "Ash", "Warframes", None, False),
    ("/w/Ash/Sys", "Systems", "Sistemas", "Warframes", "/w/Ash", True),
    ("/w/AshPrime", "Ash Prime", "Ash Prime", "Warframes", None, False),
    ("/w/AshPrime/Sys", "Systems", "Sistemas", "Warframes", "/w/AshPrime", True),
    ("/w/AshPrime/Chs", "Chassis", "Chasis", "Warframes", "/w/AshPrime", True),
    ("/w/RhinoPrime", "Rhino Prime", "Rhino Prime", "Warframes", None, False),
    ("/w/RhinoPrime/Sys", "Systems", "Sistemas", "Warframes", "/w/RhinoPrime", True),
    ("/w/Excalibur", "Excalibur", "Excalibur", "Warframes", None, False),
    ("/w/Excalibur/Chs", "Chassis", "Chasis", "Warframes", "/w/Excalibur", True),
    ("/w/ExcaliburUmbra", "Excalibur Umbra", "Excalibur Umbra", "Warframes", None, False),
    ("/p/BratonPrime", "Braton Prime", "Braton Prime", "Primary", None, False),
    ("/p/BratonPrime/Bar", "Barrel", "Canon", "Primary", "/p/BratonPrime", True),
    ("/p/Argonak", "Argonak", "Argonak", "Primary", None, True),
    ("/m/Serration", "Serration", "Sierra", "Mods", None, True),
    ("/m/SerrationExpert", "Serration", "Sierra", "Mods", None, False),
    ("/m/Vitality", "Vitality", "Vitalidad", "Mods", None, True),
    ("/m/CondOverload", "Condition Overload", "Sobrecarga de condicion", "Mods", None, True),
    ("/m/ArgonScope", "Argon Scope", "Mira de argon", "Mods", None, True),
    ("/a/ArcaneEnergize", "Arcane Energize", "Arcano Energizar", "Arcanes", None, True),
    ("/r/Nitain", "Nitain Extract", "Extracto de Nitain", "Resources", None, True),
    ("/r/Argon", "Argon Crystal", "Cristal de Argon", "Resources", None, True),
    ("/r/OrokinCell", "Orokin Cell", "Celula orokin", "Resources", None, True),
    ("/r/Neurodes", "Neurodes", "Neurodos", "Resources", None, True),
    ("/r/Kuva", "Kuva", "Kuva", "Resources", None, True),
    ("/x/Forma", "Forma", "Forma", "Misc", None, True),
    ("/x/FormaBp", "Forma Blueprint", "Plano de Forma", "Misc", None, True),
    ("/x/AmpAdapter", "Amp Arcane Adapter", "Adaptador de arcano de amp", "Misc", None, False),
    ("/x/MeleeAdapter", "Melee Arcane Adapter", "Adaptador de arcano cuerpo a cuerpo", "Misc",
     None, False),
    ("/x/Formation", "Formation", "Formacion", "Mods", None, False),
    ("/rel/AxiA7", "Axi A7 Relic", "Reliquia Axi A7", "Relics", None, True),
    ("/rel/AxiA1", "Axi A1 Relic", "Reliquia Axi A1", "Relics", None, True),
    # Lo cosmetico, que en el catalogo real son miles de filas.
    ("/s/AshKoga", "Ash Koga Skin", "Diseno Koga de Ash", "Skins", None, False),
    ("/s/RhinoPrimeSkin", "Rhino Prime Skin", "Diseno de Rhino Prime", "Skins", None, False),
    ("/s/Orokin", "Orokin", "Orokin", "Skins", None, False),
    ("/s/Adornos", "Styanax Tonatiuh Ornaments", "Adornos Tonatiuh de Styanax", "Skins", None,
     False),
    ("/s/OrokinDeco", "Orokin Cell Decoration", "Decoracion de celula orokin", "Skins", None,
     False),
    ("/g/AshGlyph", "Ash Glyph", "Glifo de Ash", "Glyphs", None, False),
    ("/g/AGlyph", "A Glyph", "Glifo A", "Glyphs", None, False),
    ("/sig/Forma", "Forma Sigil", "Sigilo Forma", "Sigils", None, False),
    ("/h/Honoria", "Honoria Orokin Cell", "Honoria de celula orokin", "Honoria", None, False),
]

# Busquedas escritas como las escribe el usuario -> lo que tiene que salir primero.
BUSQUEDAS = [
    ("sistemas ash prime", "Ash Prime Sistemas"),
    ("ash prime systems", "Ash Prime Sistemas"),
    ("ash", "Ash"),
    ("serracion", "Sierra"),
    ("seracion", "Sierra"),
    ("serration", "Sierra"),
    ("nitain", "Extracto de Nitain"),
    ("nitaín", "Extracto de Nitain"),
    ("forma", "Forma"),
    ("argon", "Cristal de Argon"),
    ("axi a7", "Reliquia Axi A7"),
    ("rino prime", "Rhino Prime"),
    ("rhino prime", "Rhino Prime"),
    ("exkalibur", "Excalibur"),
    ("excalibur", "Excalibur"),
    ("condicion overload", "Sobrecarga de condicion"),
    ("sobrecarga de condición", "Sobrecarga de condicion"),
    ("celula orokin", "Celula orokin"),
    ("orokin", "Celula orokin"),
    ("neurodos", "Neurodos"),
    ("vitalidad", "Vitalidad"),
    ("braton prime", "Braton Prime"),
    ("canon braton prime", "Braton Prime Canon"),
    ("kuva", "Kuva"),
    ("energize", "Arcano Energizar"),
]


def etiqueta(r: dict) -> str:
    nombre = r["nombre_es"] or r["nombre_en"]
    padre = r["padre_es"] or r["padre_en"]
    return f"{padre} {nombre}" if padre else nombre


@pytest.fixture()
def catalogo(con):
    ids = {}
    for unico, en, es, categoria, padre, con_fuentes in CATALOGO:
        con.execute(
            "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, padre_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (unico, en, es, categoria, ids.get(padre)),
        )
        ids[unico] = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        if con_fuentes:
            con.execute(
                "INSERT INTO fuentes (item_id, tipo, origen_texto) VALUES (?, 'mision', 'x')",
                (ids[unico],),
            )
    indice.poblar_busqueda(con)
    con.commit()
    return con, ids


def test_las_busquedas_reales_dan_lo_esperado_en_primer_lugar(catalogo):
    con, _ = catalogo
    fallos = []
    for texto, esperado in BUSQUEDAS:
        resultados = indice.buscar(con, texto, 10)
        primero = etiqueta(resultados[0]) if resultados else "(nada)"
        if primero != esperado:
            fallos.append(f"{texto!r}: salio {primero!r}, se esperaba {esperado!r}")
    assert not fallos, "\n".join(fallos)


def test_lo_cosmetico_va_detras_de_lo_farmeable(catalogo):
    con, _ = catalogo
    categorias = [r["categoria"] for r in indice.buscar(con, "a", 40)]
    primer_adorno = next(i for i, c in enumerate(categorias) if c in ("Skins", "Glyphs"))
    assert all(c not in ("Skins", "Glyphs", "Sigils", "Honoria") for c in categorias[:primer_adorno])
    assert primer_adorno >= 6  # antes salian intercalados desde el primer resultado


def test_orden_exacto_empieza_por_y_contiene(catalogo):
    con, _ = catalogo
    nombres = [etiqueta(r) for r in indice.buscar(con, "ash", 10)]
    assert nombres[0] == "Ash"  # exacto
    assert nombres.index("Ash Prime") < nombres.index("Diseno Koga de Ash")  # empieza por
    # Las piezas de Ash ("Ash Sistemas") empiezan por lo escrito; el diseno solo lo contiene.
    assert nombres.index("Ash Sistemas") < nombres.index("Diseno Koga de Ash")


def test_nombres_repetidos_salen_una_sola_vez(catalogo):
    con, _ = catalogo
    nombres = [etiqueta(r) for r in indice.buscar(con, "sierra", 10)]
    assert nombres.count("Sierra") == 1


def test_el_difuso_entra_cuando_fts_devuelve_basura(catalogo):
    con, _ = catalogo
    # FTS encuentra "for"* (Forma, Formacion...) pero nada que empiece por lo escrito.
    nombres = [etiqueta(r) for r in indice.buscar(con, "fomra", 10)]
    assert nombres[0] == "Forma"


def test_sin_fuentes_conocidas_se_penaliza(catalogo):
    con, _ = catalogo
    # Las dos "Sierra" son el mismo mod; gana la fila que tiene fuentes.
    ids = {r["item_id"]: r for r in indice.buscar(con, "serration", 10)}
    unico = con.execute(
        "SELECT unique_name FROM items WHERE id = ?", (next(iter(ids)),)
    ).fetchone()[0]
    assert unico == "/m/Serration"


def test_busqueda_vacia_o_solo_signos(catalogo):
    con, _ = catalogo
    assert indice.buscar(con, "   ") == []
    assert indice.buscar(con, "!!!") == []


def test_un_recurso_deja_de_ser_pieza_al_importarse_como_objeto_propio(con, tmp_path):
    from farmadex.datos.items import ImportadorItems

    (tmp_path / "Warframes.json").write_text(json.dumps([{
        "uniqueName": "/w/Vauban", "name": "Vauban", "category": "Warframes",
        "components": [
            {"uniqueName": "/r/Alertium", "name": "Nitain Extract", "itemCount": 5},
            {"uniqueName": "/w/Vauban/Chs", "name": "Chassis", "itemCount": 1},
        ],
    }]), encoding="utf-8")
    (tmp_path / "Resources.json").write_text(json.dumps([{
        "uniqueName": "/r/Alertium", "name": "Nitain Extract", "category": "Resources",
        "description": "Un recurso raro", "imageName": "nitain.png",
    }]), encoding="utf-8")
    importador = ImportadorItems(con, {})
    importador.importar_categoria(tmp_path / "Warframes.json")
    importador.importar_categoria(tmp_path / "Resources.json")

    fila = con.execute(
        "SELECT categoria, padre_id, item_count, imagen FROM items WHERE unique_name = '/r/Alertium'"
    ).fetchone()
    assert fila == ("Resources", None, None, "nitain.png")
    # La pieza de verdad sigue siendo pieza.
    assert con.execute(
        "SELECT padre_id IS NOT NULL FROM items WHERE unique_name = '/w/Vauban/Chs'"
    ).fetchone()[0] == 1


def _catalogo_con_ingredientes(tmp_path):
    """Tres warframes que piden Cryotic (sin ficha propia) y Neurodes (con ficha en Misc)."""
    recetas = []
    for nombre in ("Ash Prime", "Volt", "Ember"):
        clave = nombre.replace(" ", "")
        recetas.append({
            "uniqueName": f"/w/{clave}", "name": nombre, "category": "Warframes",
            "components": [
                {"uniqueName": "/r/Cryotic", "name": "Cryotic", "itemCount": 500,
                 "drops": [{"location": "Excavacion", "type": "Cryotic", "chance": 1}]},
                {"uniqueName": "/r/Neurodes", "name": "Neurodes", "itemCount": 2},
                {"uniqueName": f"/w/{clave}/Sys", "name": "Systems", "itemCount": 1},
            ],
        })
    (tmp_path / "Warframes.json").write_text(json.dumps(recetas), encoding="utf-8")
    (tmp_path / "Misc.json").write_text(json.dumps([{
        "uniqueName": "/r/Neurodes", "name": "Neurodes", "category": "Misc", "type": "Misc",
    }]), encoding="utf-8")


def test_ingrediente_de_muchas_recetas_es_recurso_aunque_no_tenga_ficha(con, tmp_path):
    from farmadex.datos.items import ImportadorItems

    _catalogo_con_ingredientes(tmp_path)
    importador = ImportadorItems(con, {})
    importador.importar_categoria(tmp_path / "Warframes.json")
    importador.importar_categoria(tmp_path / "Misc.json")
    assert importador.promocionar_ingredientes() == 2

    # Cryotic no viene en ningun catalogo: solo la senal de "muchas recetas" lo salva.
    cryotic = con.execute(
        "SELECT id, categoria, padre_id, item_count, tipo FROM items WHERE unique_name = '/r/Cryotic'"
    ).fetchone()
    assert cryotic[1:] == ("Resources", None, None, "Resource")
    # Sus fuentes siguen colgando de el.
    assert con.execute(
        "SELECT COUNT(*) FROM fuentes WHERE item_id = ?", (cryotic[0],)
    ).fetchone()[0] == 1
    # Neurodes tenia ficha propia en Misc: sale suelto y como recurso, no como cacharro.
    assert con.execute(
        "SELECT categoria, padre_id, tipo FROM items WHERE unique_name = '/r/Neurodes'"
    ).fetchone() == ("Resources", None, "Misc")


def test_las_piezas_de_verdad_siguen_teniendo_padre(con, tmp_path):
    from farmadex.datos.items import ImportadorItems

    _catalogo_con_ingredientes(tmp_path)
    importador = ImportadorItems(con, {})
    importador.importar_categoria(tmp_path / "Warframes.json")
    importador.importar_categoria(tmp_path / "Misc.json")
    importador.promocionar_ingredientes()

    piezas = con.execute(
        "SELECT p.nombre_en, i.categoria, i.item_count FROM items i JOIN items p ON p.id = i.padre_id"
        " WHERE i.nombre_en = 'Systems' ORDER BY p.nombre_en"
    ).fetchall()
    assert piezas == [("Ash Prime", "Warframes", 1), ("Ember", "Warframes", 1), ("Volt", "Warframes", 1)]
    # Una pieza compartida por solo dos recetas (Pride y Wrath comparten hoja) tampoco se toca.
    importador.recetas_por_ingrediente["/w/AshPrime/Sys"] = {1, 2}
    assert importador.promocionar_ingredientes() == 0
