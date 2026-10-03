"""La build pintada como la pantalla de mejoras del juego, los nombres en el idioma del
juego y el diccionario de aumentos (sin OCR ni ventanas visibles).

Las posiciones de `REALES` son las medidas por el lector en capturas reales del juego
(centro del nombre respecto al centro de la pantalla y borde de abajo, en altos de
pantalla): 1080p, 1440p, 4K y 21:9, con la interfaz a distintas escalas.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.captura.builds import Build  # noqa: E402
from farmadex.captura.ocr import Reconocido  # noqa: E402
from farmadex.datos import aumentos, nombres_juego  # noqa: E402
from farmadex.datos import disposicion_build as D  # noqa: E402

M, A, P = "mod", "aura", "postura"
# (clase, [(tipo, x, y, hueco esperado o None si va suelto)], [(x, y, hueco)] de arcanos)
REALES = {
    "rhino_1080": ("warframe", [
        (A, 0.065, 0.237, "aura"), (M, 0.287, 0.234, "exilus"), (M, 0.055, 0.366, "mod2"), (M, -0.176, 0.362, "mod1"),
        (M, 0.284, 0.362, "mod3"), (M, 0.516, 0.361, "mod4"), (M, 0.284, 0.493, "mod7"), (M, 0.055, 0.492, "mod6"),
        (M, 0.515, 0.491, "mod8"), (M, -0.176, 0.488, "mod5")],
        [(0.74, 0.248, "arcano1"), (0.74, 0.453, "arcano2")]),
    # La tarjeta de "Flujo Prime" estaba ampliada bajo el cursor: no cae en ningun hueco.
    "octavia_1440": ("warframe", [
        (A, -0.002, 0.257, "aura"), (M, 0.226, 0.256, "exilus"), (M, -0.002, 0.382, "mod2"), (M, -0.229, 0.381, "mod1"),
        (M, 0.455, 0.381, "mod4"), (M, -0.002, 0.508, "mod6"), (M, 0.454, 0.506, "mod8"), (M, -0.228, 0.506, "mod5"),
        (M, 0.224, 0.57, None)],
        [(0.676, 0.267, "arcano1"), (0.676, 0.471, "arcano2")]),
    "gyre_4k_interfaz_grande": ("warframe", [
        (A, -0.082, 0.24, "aura"), (M, 0.165, 0.24, "exilus"), (M, -0.34, 0.382, "mod1"), (M, 0.418, 0.38, "mod4"),
        (M, -0.087, 0.378, "mod2"), (M, 0.164, 0.516, "mod7"), (M, -0.087, 0.519, "mod6"), (M, 0.419, 0.518, "mod8"),
        (M, -0.34, 0.518, "mod5")],
        [(0.652, 0.275, "arcano1"), (0.652, 0.476, "arcano2")]),
    "haalvu_1080_arma": ("arma", [
        (M, -0.23, 0.32, "mod1"), (M, -0.002, 0.321, "mod2"), (M, 0.226, 0.318, "mod3"), (M, 0.455, 0.319, "mod4"),
        (M, 0.683, 0.383, "exilus"), (M, 0.225, 0.447, "mod7"), (M, 0.454, 0.446, "mod8"), (M, -0.23, 0.445, "mod5"),
        (M, -0.003, 0.444, "mod6")],
        [(0.676, 0.269, "arcano1")]),
    "boltor_21_9": ("arma", [
        (M, -0.348, 0.285, "mod1"), (M, 0.144, 0.289, "mod3"), (M, 0.385, 0.292, "mod4"), (M, 0.619, 0.356, "exilus"),
        (M, -0.097, 0.418, "mod6"), (M, -0.347, 0.419, "mod5"), (M, 0.146, 0.419, "mod7"), (M, 0.385, 0.419, "mod8")],
        [(0.613, 0.237, "arcano1")]),
    "haalvu_4k_interfaz_pequena": ("arma", [
        (M, 0.163, 0.242, "mod2"), (M, 0.368, 0.242, "mod3"), (M, -0.045, 0.241, "mod1"), (M, 0.575, 0.241, "mod4"),
        (M, 0.575, 0.355, "mod8"), (M, 0.162, 0.353, "mod6"), (M, 0.369, 0.354, "mod7")],
        [(0.776, 0.197, "arcano1")]),
    "syam_1440_cuerpo": ("cuerpo", [
        (P, -0.069, 0.256, "postura"), (M, 0.169, 0.257, "exilus"), (M, -0.07, 0.39, "mod2"), (M, 0.169, 0.386, "mod3"),
        (M, 0.408, 0.386, "mod4"), (M, -0.307, 0.387, "mod1"), (M, -0.07, 0.529, "mod6"), (M, 0.169, 0.519, "mod7"),
        (M, -0.309, 0.52, "mod5"), (M, 0.411, 0.517, "mod8")],
        [(0.64, 0.284, "arcano1")]),
}


@pytest.mark.parametrize("caso", sorted(REALES))
def test_cada_mod_cae_en_su_hueco_del_juego(caso):
    clase, mods, arcanos = REALES[caso]
    r = D.colocar(clase, [D.Punto(t, x, y) for t, x, y, _h in mods], [D.Punto("arcano", x, y) for x, y, _h in arcanos])
    assert r.segura and r.clase == clase
    for i, (_t, _x, _y, hueco) in enumerate(mods):
        if hueco is None:
            assert i in r.sueltos_mods
        else:
            assert r.mods.get(hueco) == i, (caso, hueco)
    for j, (_x, _y, hueco) in enumerate(arcanos):
        assert r.arcanos.get(hueco) == j


def test_la_plantilla_lleva_los_huecos_del_juego():
    def claves(clase):
        return [h.clave for h in D.PLANTILLAS[clase]]

    for clase in ("warframe", "arma", "cuerpo"):
        assert sum(1 for h in D.PLANTILLAS[clase] if h.tipo == "mod") == 8
        assert "exilus" in claves(clase)
    assert "aura" in claves("warframe") and claves("warframe").count("arcano1") == 1 and "arcano2" in claves("warframe")
    assert "postura" in claves("cuerpo") and "aura" not in claves("arma")
    # Dos filas de cuatro, y el aura y el exilus encima de las columnas del centro.
    wf = {h.clave: h for h in D.PLANTILLAS["warframe"]}
    assert [wf[f"mod{n}"].x for n in range(1, 9)] == [0, 1, 2, 3, 0, 1, 2, 3]
    assert (wf["aura"].x, wf["exilus"].x, wf["aura"].y) == (1, 2, 0) and wf["arcano1"].x > 3.5
    assert D.plantilla_de("Warframes", "Warframe") == "warframe" and D.plantilla_de("Melee", "Melee") == "cuerpo"
    assert D.plantilla_de("Secondary", "Pistol") == "arma" and D.plantilla_de("Sentinels", "Sentinel") == "companero"
    assert D.plantilla_de("Pets", "Pets") == "companero" and D.plantilla_de("Pets", "Pet Parts") == ""
    # Companeros: dos filas de cinco, sin aura, exilus ni arcanos.
    co = {h.clave: h for h in D.PLANTILLAS["companero"]}
    assert sorted(co) == sorted(f"mod{n}" for n in range(1, 11)) and all(h.tipo == "mod" for h in co.values())
    assert [co[f"mod{n}"].x for n in range(1, 11)] == [0, 1, 2, 3, 4] * 2


def test_si_no_se_sabe_el_hueco_no_se_inventa():
    # Sin medidas (lectura vieja o de prueba): nada colocado.
    r = D.colocar("warframe", [None, None], [None])
    assert not r.segura and r.motivo == "sin_medidas" and r.sueltos_mods == [0, 1] and not r.mods
    # Un solo mod: no da para medir la rejilla.
    r = D.colocar("arma", [D.Punto(M, 0.1, 0.3)], [])
    assert not r.segura and r.motivo == "pocos" and not r.mods
    # Dos mods seguidos en una fila: pueden ser las columnas 1-2, 2-3 o 3-4, y cualquiera
    # de las dos filas. Dos colocaciones igual de buenas: no se elige.
    r = D.colocar("arma", [D.Punto(M, 0.0, 0.32), D.Punto(M, 0.228, 0.32)], [])
    assert not r.segura and r.motivo == "ambigua" and r.sueltos_mods == [0, 1]
    # Con el arcano a la vista ya hay con que anclar las columnas y la fila.
    r = D.colocar("arma", [D.Punto(M, 0.0, 0.32), D.Punto(M, 0.228, 0.32)], [D.Punto("arcano", 0.45, 0.269)])
    assert r.segura and r.mods == {"mod3": 0, "mod4": 1} and r.arcanos == {"arcano1": 0}
    # Nada que colocar: seguro y vacio.
    assert D.colocar("warframe", [], []).segura


def test_el_companero_tiene_sus_diez_huecos():
    # Un companero con una tarjeta ampliada (la del hueco 2 tapa el 7): el 7 queda libre y se
    # sabe donde cae, para avisar de que esta tapado.
    xs = (-0.23, -0.001, 0.226, 0.454, 0.683)
    mods = [D.Punto(M, x, y) for y in (0.319, 0.444) for x in xs]
    del mods[6]
    r = D.colocar("companero", mods, [])
    assert r.segura and r.clase == "companero" and "mod7" not in r.mods and len(r.mods) == 9
    assert r.mods["mod10"] == 8 and abs(r.centro_de(D.PLANTILLAS["companero"][6])[0] - (-0.001)) < 0.01


def test_sin_plantilla_se_respeta_la_fila_y_la_columna_leidas():
    # Sin plantilla (dos filas de cinco): no se dice que huecos hay, solo donde estaba cada mod.
    xs = (-0.23, -0.001, 0.226, 0.454, 0.683)
    mods = [D.Punto(M, x, y) for y in (0.319, 0.444) for x in xs]
    r = D.colocar("", mods, [])
    assert r.segura and r.clase == "" and len(r.huecos) == 10
    assert sorted((h.x, h.y) for h in r.huecos) == sorted((float(c), float(f)) for f in (0, 1) for c in range(5))
    assert D.punto_de((100, 200, 50, 20), 1920, 1080, M) == D.Punto(M, (125 - 960) / 1080, 220 / 1080)
    assert D.punto_de((0, 0, 10, 10), 0, 0, M) is None


# -- indice de prueba ---------------------------------------------------------------------

@pytest.fixture()
def indice(con):
    ids = {}

    def item(unico, en, es, categoria, tipo, detalles=None, otros=None):
        con.execute("INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo) VALUES (?, ?, ?, ?, ?)",
                    (unico, en, es, categoria, tipo))
        ids[en] = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        if detalles is not None:
            con.execute("INSERT INTO detalles (item_id, datos) VALUES (?, ?)", (ids[en], json.dumps(detalles)))
        for codigo, nombre in (otros or {}).items():
            con.execute("INSERT INTO items_nombres (item_id, idioma, nombre) VALUES (?, ?, ?)", (ids[en], codigo, nombre))

    def mod(unico, en, es, compat, tipo="Warframe Mod", rareza="Rare", otros=None):
        item(unico, en, es, "Mods", tipo, {"mod": {"efecto": {"en": ["+1% Health"]}, "rareza": rareza, "compat": compat}}, otros)

    item("/w/Rhino", "Rhino", "Rhino", "Warframes", "Warframe", {"warframe": {"vida": 300}})
    item("/w/Hek", "Hek", "Hek", "Primary", "Shotgun", {"arma": {"critico": 0.1}})
    item("/w/Skana", "Skana", "Skana", "Melee", "Melee", {"arma": {"critico": 0.1}})
    mod("/m/IronShrapnel", "Iron Shrapnel", "Metralla de hierro", "Rhino",
        otros={"fr": "Shrapnel de fer", "de": "Eisernes Schrapnell", "it": "Iron Shrapnel"})
    mod("/m/Scattered", "Scattered Justice", "Justicia dispersa", "Hek", tipo="Primary Mod")
    mod("/m/Acid", "Acid Shells", "Proyectiles ácidos", "Hek", tipo="Primary Mod")
    mod("/m/Rara", "Odd Augment", None, "Rhino")
    mod("/m/Vitality", "Vitality", "Vitalidad", "WARFRAME", rareza="Common", otros={"fr": "Vitalité", "de": "Vitalität"})
    mod("/m/Flow", "Flow", "Flujo", "WARFRAME", otros={"fr": "Flux", "de": "Fluss"})
    mod("/m/Siphon", "Energy Siphon", "Sifón de energía", "AURA", otros={"fr": "Siphon d'Énergie"})
    mod("/m/Stance", "Crimson Dervish", "Derviche carmesí", "Swords", tipo="Stance Mod")
    item("/a/Energize", "Arcane Energize", "Energizar Arcano", "Arcanes", "Arcane",
         {"arcano": {"efecto": {"en": ["x"]}, "rareza": "Legendary"}}, {"fr": "Arcane Énergie"})

    def venta(en, sindicato, lugar, standing):
        con.execute("INSERT INTO fuentes (item_id, tipo, origen_texto, standing, datos_extra) VALUES (?, 'sindicato', ?, ?, ?)",
                    (ids[en], sindicato, standing, json.dumps({"lugar": lugar})))

    venta("Iron Shrapnel", "Steel Meridian", "Steel Meridian, General", 25000)
    venta("Iron Shrapnel", "The Perrin Sequence", "The Perrin Sequence, Partner", 25000)
    venta("Scattered Justice", "Steel Meridian", "Steel Meridian, Protector", 25000)
    venta("Odd Augment", "Cephalon Simaris", "Cephalon Simaris, Complete The Sacrifice", None)
    # Un mod corriente que tambien vende un sindicato: no es un aumento.
    venta("Vitality", "Steel Meridian", "Steel Meridian, General", 1000)
    con.commit()
    aumentos.olvidar_cache()
    nombres_juego.olvidar_cache()
    yield con, ids
    aumentos.olvidar_cache()
    nombres_juego.olvidar_cache()


@pytest.fixture()
def config_propia(tmp_path, monkeypatch):
    from farmadex import config
    from farmadex.datos import evaluar_build

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    evaluar_build.olvidar_cache()
    yield config.cargar()
    idiomas.cargar("es")
    evaluar_build.olvidar_cache()


# -- aumentos y sindicatos -------------------------------------------------------------------

def test_diccionario_de_aumentos_con_sindicato_rango_y_coste(indice, config_propia):
    con, ids = indice
    lista = aumentos.cargar(con)
    # Solo los mods de UN warframe o UN arma: ni Vitalidad (clase WARFRAME) ni la postura.
    assert [a.nombre_en for a in lista] == ["Acid Shells", "Iron Shrapnel", "Odd Augment", "Scattered Justice"]
    por = {a.nombre_en: a for a in lista}
    assert (por["Iron Shrapnel"].clase, por["Iron Shrapnel"].para) == ("warframe", "Rhino")
    assert (por["Scattered Justice"].clase, por["Scattered Justice"].para_id) == ("arma", ids["Hek"])
    ventas = {(v.sindicato, v.rango, v.titulo, v.coste) for v in por["Iron Shrapnel"].ventas}
    assert ventas == {("Steel Meridian", 5, "General", 25000), ("The Perrin Sequence", 5, "Partner", 25000)}
    assert [(v.rango, v.titulo) for v in por["Scattered Justice"].ventas] == [(4, "Protector")]
    # Lo que no trae el dato no se inventa: sin rango conocido ni coste, "no se sabe".
    rara = por["Odd Augment"].ventas[0]
    assert rara.rango is None and rara.coste is None
    texto = aumentos.texto_venta(rara)
    assert "rango: no se sabe" in texto and "coste: no se sabe" in texto and "Simaris" in texto
    assert aumentos.texto_venta(por["Iron Shrapnel"].ventas[0]) == "Meridiano de Acero · rango 5 (General) · 25.000 de reputación"
    # Un aumento que no vende ningun sindicato lo dice; un mod corriente no es aumento.
    assert por["Acid Shells"].ventas == [] and "ningún sindicato" in aumentos.lineas(con, ids["Acid Shells"])[1][0]
    assert aumentos.de(con, ids["Vitality"]) is None and aumentos.lineas(con, ids["Vitality"]) == []


def test_puede_comprarlo_solo_si_el_perfil_sabe_el_rango(indice, config_propia):
    con, ids = indice
    general = aumentos.de(con, ids["Iron Shrapnel"]).ventas[0]
    assert general.sindicato == "Steel Meridian"
    # Sin perfil, o sin ese sindicato en el perfil: no se sabe, no se supone.
    assert aumentos.puede_comprar(general, None) is None and aumentos.puede_comprar(general, {}) is None
    assert aumentos.puede_comprar(general, {"RedVeilSyndicate": (5, 0)}) is None
    assert aumentos.texto_puedes(general, {}) == ("", "")
    assert aumentos.puede_comprar(general, {"SteelMeridianSyndicate": (5, 1000)}) is True
    assert aumentos.puede_comprar(general, {"SteelMeridianSyndicate": (4, 99000)}) is False
    lineas = aumentos.lineas(con, ids["Iron Shrapnel"], {"SteelMeridianSyndicate": (4, 0)})
    assert lineas[0] == ("Aumento de Rhino", "")
    assert ("Según tu perfil eres rango 4: todavía no llegas.", "aviso") in lineas
    assert not any("perfil" in texto for texto, _ in aumentos.lineas(con, ids["Iron Shrapnel"], {}))
    # Sin rango conocido en la venta tampoco se dice nada aunque haya perfil.
    simaris = aumentos.de(con, ids["Odd Augment"]).ventas[0]
    assert aumentos.puede_comprar(simaris, {"SteelMeridianSyndicate": (5, 0)}) is None


def test_pintar_una_build_no_carga_el_diccionario_entero(indice, monkeypatch):
    """La primera build de la sesion paraba la ventana ~0,6 s leyendo el detalle de todos
    los mods para saber si alguno era un aumento: ahora se mira solo cada mod, y da lo mismo."""
    con, ids = indice
    aumentos.olvidar_cache()
    monkeypatch.setattr(aumentos, "_ventas", lambda c, item_id=None, original=aumentos._ventas: (
        pytest.fail("sin item_id lee las ventas de todo el indice") if item_id is None else original(c, item_id)))
    sueltos = {en: aumentos.de(con, i) for en, i in ids.items()}
    assert not aumentos._CACHE  # el diccionario entero sigue sin cargar
    assert sueltos["Vitality"] is None and sueltos["Energy Siphon"] is None and sueltos["Rhino"] is None
    assert [v.sindicato for v in sueltos["Iron Shrapnel"].ventas] == ["Steel Meridian", "The Perrin Sequence"]
    monkeypatch.undo()
    aumentos.olvidar_cache()
    todos = {a.item_id: a for a in aumentos.cargar(con)}
    assert {en: todos.get(i) for en, i in ids.items()} == sueltos
    # Con el diccionario cargado se responde desde el.
    assert aumentos.de(con, ids["Scattered Justice"]) is todos[ids["Scattered Justice"]]


def test_rangos_del_perfil_leido(tmp_path):
    import sqlite3

    usuario = sqlite3.connect(tmp_path / "u.sqlite")
    assert aumentos.rangos_del_perfil(usuario) == {}  # sin tabla: no se sabe
    usuario.execute("CREATE TABLE perfil_sindicatos (tag TEXT PRIMARY KEY, standing INTEGER, titulo INTEGER)")
    usuario.execute("INSERT INTO perfil_sindicatos VALUES ('SteelMeridianSyndicate', 12000, 3)")
    assert aumentos.rangos_del_perfil(usuario) == {"SteelMeridianSyndicate": (3, 12000)}


def test_la_ficha_y_el_recuadro_de_un_aumento_dicen_el_sindicato(indice, config_propia):
    from farmadex.ui import ficha_detalles

    con, ids = indice
    bloque = ficha_detalles.bloque_aumento(con, ids["Scattered Justice"])
    assert "Aumento de Hek" in bloque and "rango 4 (Protector)" in bloque and "25.000" in bloque
    assert ficha_detalles.bloque_aumento(con, ids["Vitality"]) == ""
    assert "Aumento de Hek" in ficha_detalles.html_detalles(con, {"id": ids["Scattered Justice"]})
    assert "Aumento de Hek" in ficha_detalles.bloques(con, {"id": ids["Scattered Justice"]})["mod"]


# -- idioma del juego ------------------------------------------------------------------------

def test_los_nombres_van_en_el_idioma_del_juego_no_en_el_de_la_interfaz(indice, config_propia):
    con, ids = indice
    cfg = config_propia
    # Interfaz en ingles y juego sin ver todavia: el de la interfaz.
    idiomas.cargar("en")
    assert nombres_juego.idioma() == "en" and nombres_juego.nombre(con, ids["Vitality"]) == "Vitality"
    # Se lee una pantalla en espanol: desde ahi, espanol aunque la interfaz siga en ingles.
    assert nombres_juego.apuntar_visto("es") and not nombres_juego.apuntar_visto("es")
    assert cfg["idioma_juego_visto"] == "es" and nombres_juego.idioma() == "es"
    assert nombres_juego.nombre(con, ids["Vitality"]) == "Vitalidad"
    # Elegido a mano manda sobre lo visto; "auto" vuelve a lo visto.
    nombres_juego.elegir("fr")
    assert nombres_juego.nombre(con, ids["Vitality"]) == "Vitalité"
    # Sin traduccion en ese idioma: el ingles (como hace el juego), no un hueco.
    assert nombres_juego.nombre(con, ids["Scattered Justice"]) == "Scattered Justice"
    nombres_juego.elegir("auto")
    assert nombres_juego.idioma() == "es"
    assert nombres_juego.nombres(con, ids["Iron Shrapnel"]) == {
        "es": "Metralla de hierro", "en": "Iron Shrapnel", "fr": "Shrapnel de fer", "de": "Eisernes Schrapnell",
        "it": "Iron Shrapnel"}
    assert nombres_juego.nombre(None, 5, "x") == "x" and nombres_juego.nombre(con, None, "y") == "y"


def test_el_idioma_se_deduce_de_lo_leido_sin_suponer(indice, config_propia):
    con, ids = indice
    es = [("Vitalidad", ids["Vitality"]), ("Flujo", ids["Flow"])]
    en = [("Vitality", ids["Vitality"]), ("Flow", ids["Flow"])]
    de = [("Vitalität", ids["Vitality"]), ("Fluss", ids["Flow"])]
    assert nombres_juego.detectar(con, es) == "es" and nombres_juego.detectar(con, en) == "en"
    # La cabecera "UPGRADES" tambien la pone el juego en aleman: mandan los nombres.
    assert nombres_juego.detectar(con, de, "en") == "de"
    # La cabecera en otro idioma manda aunque los mods salgan en ingles (sin traducir).
    assert nombres_juego.detectar(con, en, "pt") == "pt"
    # Un solo nombre, o nombres que se escriben igual en todos los idiomas: no se sabe.
    assert nombres_juego.detectar(con, [("Vitalidad", ids["Vitality"])]) == ""
    assert nombres_juego.detectar(con, [("Hek", ids["Hek"]), ("Rhino", ids["Rhino"])]) == ""
    assert nombres_juego.detectar(con, []) == "" and nombres_juego.detectar(None, es, "fr") == "fr"


# -- la pestana ------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def pestana(app, indice, config_propia, monkeypatch):
    from farmadex.ui import rejilla_build
    from farmadex.ui.pestana_builds import PestanaBuilds

    monkeypatch.setattr(rejilla_build, "ALTO_PANTALLA_FORZADO", 1080)
    con, ids = indice
    p = PestanaBuilds()
    p.conectar_indice(con)
    yield p, ids, con


def _rec(ids, nombre_en, texto, caja=(0, 0, 10, 10), parecido=100.0):
    return Reconocido(texto, ids[nombre_en], texto, parecido, caja)


def _caja(x, y, ancho=1920, alto=1080):
    """La caja de un nombre de 100 x 20 px cuyo centro y borde de abajo son (x, y) medidos."""
    return (int(ancho / 2 + x * alto - 50), int(y * alto - 20), 100, 20)


def _build_rhino(ids):
    return Build(
        equipo=_rec(ids, "Rhino", "Rhino"),
        equipados=[_rec(ids, "Energy Siphon", "Sifón de energía", _caja(0.0, 0.257)),
                   _rec(ids, "Vitality", "Vitalidad", _caja(-0.228, 0.381)),
                   _rec(ids, "Iron Shrapnel", "Metralla de hierro", _caja(0.456, 0.381)),
                   _rec(ids, "Flow", "Flujo", _caja(0.228, 0.507), 91.0)],
        arcanos=[_rec(ids, "Arcane Energize", "Energizar Arcano", _caja(0.676, 0.471))],
        ancho=1920, alto=1080, idioma="es")


def test_la_build_se_pinta_con_la_disposicion_del_juego(pestana):
    p, ids, _con = pestana
    p.resize(1700, 900)
    p.mostrar_build(_build_rhino(ids))
    assert p.colocacion.segura and p.colocacion.clase == "warframe"
    r = p.rejilla
    assert r.hueco_de(ids["Energy Siphon"]) == "aura" and r.hueco_de(ids["Vitality"]) == "mod1"
    assert r.hueco_de(ids["Iron Shrapnel"]) == "mod4" and r.hueco_de(ids["Flow"]) == "mod7"
    assert r.hueco_de(ids["Arcane Energize"]) == "arcano2"
    # Los 8 huecos de mod, el aura, el exilus y los 2 arcanos estan pintados, llenos o no.
    assert len(r.lienzo.piezas) == 12 and sum(1 for pieza in r.lienzo.piezas if pieza[4] is None) == 7
    assert r.aviso.isHidden() and r.titulo_sueltos.isHidden()
    # La tarjeta dice lo que se sabe: el parecido si el lector dudo, y el sindicato si es un aumento.
    assert r.carta_de(ids["Flow"]).datos.puntuacion == 91.0
    ayuda = r.carta_de(ids["Iron Shrapnel"]).toolTip()
    assert "Aumento de Rhino" in ayuda and "Meridiano de Acero · rango 5 (General)" in ayuda
    textos = [p.capa_aumentos.itemAt(i).widget().text() for i in range(p.capa_aumentos.count())]
    assert textos[0] == "Metralla de hierro: Aumento de Rhino" and any("Secuencia Perrin" in x for x in textos)
    # Pulsar una tarjeta abre su ficha.
    abiertos = []
    p.abrir_item.connect(abiertos.append)
    r.carta_de(ids["Vitality"]).pulsada.emit(ids["Vitality"])
    assert abiertos == [ids["Vitality"]]
    assert p.ids_listados() == [ids["Rhino"], ids["Energy Siphon"], ids["Vitality"], ids["Iron Shrapnel"], ids["Flow"],
                                ids["Arcane Energize"]]


def test_las_tarjetas_guardan_la_proporcion_del_juego_y_no_pasan_del_tamano_real(pestana, app):
    p, ids, _con = pestana
    p.mostrar_build(_build_rhino(ids))
    lienzo = p.rejilla.lienzo
    for ancho, real in ((2400, True), (1231, True), (800, False), (400, False)):
        lienzo.resize(ancho, 400)
        lienzo.recolocar()
        paso = lienzo.paso()
        # Tamano real: el paso de columna del juego a 1080p (0,228 x 1080 = 246 px).
        assert (abs(paso - 246.24) < 0.5) == real and paso <= 246.3
        assert abs(lienzo.escala() - paso / 246.24) < 0.01
        carta = p.rejilla.carta_de(ids["Vitality"])
        siphon = p.rejilla.carta_de(ids["Energy Siphon"])
        flow = p.rejilla.carta_de(ids["Flow"])
        # Tarjeta de 0,915 x 0,685 pasos; filas a 0,553 del paso de columna; columnas a un paso.
        assert abs(carta.width() - 0.915 * paso) <= 1.5 and abs(carta.height() - 0.685 * 0.553 * paso) <= 1.5
        assert abs((siphon.x() - carta.x()) - paso) <= 1.5 and abs((flow.x() - siphon.x()) - paso) <= 1.5
        assert abs((carta.y() - siphon.y()) - 0.553 * paso) <= 1.5 and abs((flow.y() - carta.y()) - 0.553 * paso) <= 1.5
        # Nada se sale del lienzo.
        for *_r, pieza, _rot in lienzo.piezas:
            if pieza is not None:
                assert pieza.x() >= 0 and pieza.x() + pieza.width() <= lienzo.width() + 1


def test_sin_posiciones_se_ensena_el_orden_leido_y_se_dice(pestana):
    p, ids, _con = pestana
    build = Build(equipo=_rec(ids, "Rhino", "Rhino"),
                  equipados=[_rec(ids, "Vitality", "Vitalidad"), _rec(ids, "Flow", "Flujo")],
                  arcanos=[_rec(ids, "Arcane Energize", "Energizar Arcano")])
    p.mostrar_build(build)
    assert not p.colocacion.segura and p.colocacion.motivo == "sin_medidas"
    r = p.rejilla
    assert not r.aviso.isHidden() and "orden" in r.aviso.text()
    assert r.hueco_de(ids["Vitality"]) is None and r.carta_de(ids["Vitality"]).dudosa
    assert [pieza[4].datos.item_id for pieza in r.lienzo.piezas] == [ids["Vitality"], ids["Flow"], ids["Arcane Energize"]]
    assert "No se sabe en qué hueco va" in r.carta_de(ids["Flow"]).toolTip()
    # Un mod que no cae en ningun hueco (tarjeta ampliada) va aparte, marcado; el resto, en su sitio.
    build = _build_rhino(ids)
    build.equipados.append(_rec(ids, "Odd Augment", "Odd Augment", _caja(0.11, 0.6)))
    p.mostrar_build(build)
    assert p.colocacion.segura and r.hueco_de(ids["Vitality"]) == "mod1" and r.hueco_de(ids["Odd Augment"]) is None
    assert not r.titulo_sueltos.isHidden() and r.carta_de(ids["Odd Augment"]).dudosa and r.aviso.isHidden()


def test_toda_la_pestana_habla_el_idioma_del_juego(pestana):
    p, ids, con = pestana
    from farmadex import config

    idiomas.cargar("en")  # interfaz en ingles, juego en espanol
    p.retraducir()
    p.mostrar_build(_build_rhino(ids))
    assert config.cargar()["idioma_juego_visto"] == "es"
    assert "Vitalidad" in [e.nombre for e in p._entradas] and "Vitality" not in [e.nombre for e in p._entradas]
    assert p.rejilla.carta_de(ids["Iron Shrapnel"]).datos.nombre == "Metralla de hierro"
    # "¿Esta bien mi build?" y "Build basica": los nombres de mods, tambien en espanol.
    p.mostrar_evaluacion()
    textos = " ".join(x.texto for x in p.evaluacion.bien + p.evaluacion.mal)
    assert "Sifón de energía" in textos and "Energy Siphon" not in textos
    p.mostrar_basica()
    nombres = [h.mod.nombre for h in p.basica.huecos if h.mod is not None]
    assert "Vitalidad" in nombres and "Vitality" not in nombres
    assert p.selector_idioma.currentData() == "auto" and "Español" in p.selector_idioma.currentText()
    # Elegido a mano en frances: se repinta todo en frances (y lo que no tiene, en ingles).
    p.selector_idioma.setCurrentIndex(p.selector_idioma.findData("fr"))
    assert p.rejilla.carta_de(ids["Vitality"]).datos.nombre == "Vitalité"
    assert p.rejilla.carta_de(ids["Arcane Energize"]).datos.nombre == "Arcane Énergie"
    assert "Vitalité" in [h.mod.nombre for h in p.basica.huecos if h.mod is not None]
    p.selector_idioma.setCurrentIndex(p.selector_idioma.findData("auto"))
    assert p.rejilla.carta_de(ids["Vitality"]).datos.nombre == "Vitalidad"


def test_diccionario_de_aumentos_en_la_pestana(pestana):
    p, ids, _con = pestana
    assert p.vistas.claves() == ["build", "aumentos"]
    p.ver("aumentos")
    d = p.diccionario
    assert p.pila.currentWidget() is d and d.tabla.rowCount() == 4
    # Se encuentra por el nombre en cualquier idioma, por el equipo y por el sindicato.
    assert [a.nombre_en for a in d.buscar("metralla")] == ["Iron Shrapnel"]
    assert [a.nombre_en for a in d.buscar("eisernes")] == ["Iron Shrapnel"]
    assert [a.nombre_en for a in d.buscar("hek")] == ["Acid Shells", "Scattered Justice"]
    assert [a.nombre_en for a in d.buscar("perrin")] == ["Iron Shrapnel"]
    assert d.buscar("no existe") == [] and d.tabla.rowCount() == 0
    d.buscar("")
    d.filtro.setCurrentIndex(d.filtro.findData("arma"))
    assert [a.nombre_en for a in d._visibles] == ["Acid Shells", "Scattered Justice"]
    d.filtro.setCurrentIndex(d.filtro.findData("todos"))
    por = {a.nombre_en: d.celdas(a) for a in d._visibles}
    assert por["Iron Shrapnel"] == ["Metralla de hierro", "Iron Shrapnel", "Rhino",
                                    "Meridiano de Acero / Secuencia Perrin", "5 / 5", "25.000 / 25.000", ""]
    assert por["Odd Augment"][3:6] == ["Cefalon Simaris", "no se sabe", "no se sabe"]
    assert por["Acid Shells"][3:] == ["ninguno lo vende", "", "", ""]
    # Con el rango del perfil se dice si llega; sin el, en blanco.
    d.rangos = {"SteelMeridianSyndicate": (4, 0)}
    assert d.celdas(next(a for a in d._visibles if a.nombre_en == "Scattered Justice"))[6] == "Sí"
    assert d.celdas(next(a for a in d._visibles if a.nombre_en == "Iron Shrapnel"))[6] == ""
    d.rangos = {"SteelMeridianSyndicate": (4, 0), "PerrinSyndicate": (2, 0)}
    assert d.celdas(next(a for a in d._visibles if a.nombre_en == "Iron Shrapnel"))[6] == "Todavía no"
    # El detalle: todos los idiomas y cada sindicato; abrir la ficha.
    d.buscar("metralla")
    d.elegir_fila(0)
    detalle = d.textos_detalle()
    assert detalle[0] == "Metralla de hierro" and detalle[1] == "Aumento de Rhino"
    assert "English: Iron Shrapnel" in detalle[2] and "Deutsch: Eisernes Schrapnell" in detalle[2]
    assert "Meridiano de Acero · rango 5 (General) · 25.000 de reputación" in detalle
    assert "Según tu perfil eres rango 4: todavía no llegas." in detalle
    abiertos = []
    p.abrir_item.connect(abiertos.append)
    d.boton_ficha.click()
    assert abiertos == [ids["Iron Shrapnel"]]
    p.ver("build")
    assert p.pila.currentIndex() == 0
