"""Casos limite encontrados en la revision: cada test cubre un fallo que existio."""

import json
import sqlite3

from farmadex.datos import indice, items
from farmadex.online import worldstate
from farmadex.registro import eelog


def test_ficha_no_deja_row_factory_cambiado(indice_poblado):
    con, _, _ = indice_poblado
    item_id = indice.buscar(con, "ash prime")[0]["item_id"]
    items.ficha(con, item_id)
    assert con.row_factory is None
    # La busqueda comparte la conexion y sigue funcionando despues.
    assert indice.buscar(con, "ash prime")[0]["item_id"] == item_id


def test_busqueda_difusa_ordena_por_parecido(indice_poblado):
    con, _, _ = indice_poblado
    resultados = indice.buscar(con, "asch prmie sistemas")
    assert resultados
    assert resultados[0]["nombre_en"] == "Systems"
    assert resultados[0]["padre_en"] == "Ash Prime"


def test_fuentes_de_reliquias_inexistentes_se_descartan(indice_poblado):
    con, importador, _ = indice_poblado
    item_id = indice.buscar(con, "ash prime")[0]["item_id"]
    con.execute(
        "INSERT INTO fuentes (item_id, tipo, origen_texto, refinamiento, datos_extra) "
        "VALUES (?, 'reliquia', 'Requiem undefined Relic', 'Intact', ?)",
        (item_id, json.dumps({"reliquia": "Requiem UNDEFINED"})),
    )
    importador.enlazar_reliquias()
    huerfanas = con.execute(
        "SELECT COUNT(*) FROM fuentes WHERE tipo = 'reliquia' AND origen_id IS NULL"
    ).fetchone()[0]
    assert huerfanas == 0


def test_los_nodos_que_de_no_publica_se_crean_desde_los_drops(indice_poblado, tmp_path):
    con, _, drops = indice_poblado
    tabla = {
        "Venus": {
            "Bifrost Echo": {
                "gameMode": "Defense",
                "rewards": [{"itemName": "Axi A7 Relic", "rarity": "Rare", "chance": 5.0}],
            },
            "Bifrost Echo (Caches)": {
                "gameMode": "Caches",
                "rewards": [{"itemName": "Axi A7 Relic", "rarity": "Rare", "chance": 1.0}],
            },
        }
    }
    ruta = tmp_path / "missionRewards.json"
    ruta.write_text(json.dumps({"missionRewards": tabla}), encoding="utf-8")
    drops.mission_rewards(ruta)
    drops.traducir_nodos()

    nodos = con.execute(
        "SELECT nombre_en, planeta_en, mision_en, mision_es FROM nodos WHERE planeta_en = 'Venus'"
    ).fetchall()
    # Las dos entradas ("Bifrost Echo" y su variante de cofres) son el mismo nodo,
    # y el modo de mision sale de la principal, no de la de cofres.
    assert nodos == [("Bifrost Echo", "Venus", "Defense", "Defensa")]
    assert drops.nodos_creados == 1
    sin_nodo = con.execute(
        "SELECT COUNT(*) FROM fuentes WHERE tipo = 'mision' AND origen_id IS NULL"
    ).fetchone()[0]
    assert sin_nodo == 0


def test_los_nombres_sin_casar_se_recuerdan(indice_poblado):
    _, _, drops = indice_poblado
    for _ in range(3):
        assert drops.item_id("Objeto Inventado Zzz") is None
    assert drops.sin_casar["Objeto Inventado Zzz"] == 3
    assert ("Objeto Inventado Zzz", True) in drops._memoria
    # Endo y creditos no son objetos del catalogo: ni se intentan ni ensucian el log.
    assert drops.item_id("400 Endo") is None
    assert "400 Endo" not in drops.sin_casar


def test_los_sindicatos_casan_aunque_lleven_el_warframe_entre_parentesis(indice_poblado):
    con, _, drops = indice_poblado
    ash = con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    assert drops.item_id("Ash Prime (Warframe)") == ash
    assert drops.item_id("2X Ash Prime") == ash


def test_una_fisura_que_no_es_objeto_no_tumba_las_demas(indice_poblado):
    con, _, _ = indice_poblado
    traductor = worldstate.Traductor(con)
    datos = {
        "fissures": [
            "esto no es una fisura",
            {"tier": "Axi", "node": "Hydron (Sedna)", "missionType": "Defense", "expiry": None},
        ],
        "voidTrader": "tampoco es un objeto",
        "sortie": {"variants": ["cadena suelta"]},
    }
    mundo = worldstate.analizar(datos, traductor)
    assert len(mundo.fisuras) == 1
    assert mundo.fisuras[0].nodo == "Hydron, Sedna"
    assert mundo.sortie == []
    assert mundo.baro == []


def test_eelog_lee_solo_lineas_completas_y_avanza(tmp_path):
    ruta = tmp_path / "EE.log"
    ruta.write_bytes(
        b"123.4 Sys [Info]: nada\n"
        b"123.5 Script [Info]: ProjectionRewardChoice.lua: Got rewards\n"
        b"123.6 Script [Info]: EndOfMatch.lua: Mission Succ"
    )
    eventos, posicion = eelog.leer_eventos(ruta, 0)
    assert eventos == ["reliquia_recompensas"]
    # La linea a medio escribir se deja para la siguiente pasada.
    assert posicion == ruta.stat().st_size - len(b"123.6 Script [Info]: EndOfMatch.lua: Mission Succ")

    with ruta.open("ab") as f:
        f.write(b"eeded\n")
    eventos, posicion = eelog.leer_eventos(ruta, posicion)
    assert eventos == ["mision_completada"]
    assert posicion == ruta.stat().st_size
    # Sin nada nuevo no se repite ningun evento.
    assert eelog.leer_eventos(ruta, posicion) == ([], posicion)


def test_hay_indice_cierra_la_conexion_si_falta_el_esquema(tmp_path):
    ruta = tmp_path / "vacio.sqlite"
    sqlite3.connect(ruta).close()
    assert indice.hay_indice(ruta) is False
    # Si la conexion quedara abierta, en Windows no se podria borrar el fichero.
    ruta.unlink()


def test_un_indice_de_esquema_viejo_se_reconstruye(con, tmp_path):
    ruta = tmp_path / "prueba.sqlite"  # la misma que abre la fixture 'con'
    con.execute("INSERT INTO items (unique_name, nombre_en, categoria) VALUES ('x', 'X', 'Misc')")
    con.execute("INSERT INTO meta VALUES ('construido_en', 'hoy'), ('esquema_version', '0')")
    con.commit()
    assert indice.hay_indice(ruta) is False
    con.execute("UPDATE meta SET valor = ? WHERE clave = 'esquema_version'", (indice.VERSION_ESQUEMA,))
    con.commit()
    assert indice.hay_indice(ruta) is True
