import sqlite3

import pytest

from farmadex.datos import indice
from farmadex.estado import objetivos, usuario_db
from farmadex.registro.eelog import clasificar


@pytest.fixture()
def usuario(tmp_path):
    return usuario_db.conectar(tmp_path / "usuario.sqlite")


def test_anadir_el_set_crea_una_pieza_por_componente(usuario, indice_poblado):
    con, _, _ = indice_poblado
    ash = con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    creados = objetivos.anadir_set(usuario, con, ash)

    assert len(creados) == 2  # el fixture solo trae Systems y Chassis
    nombres = [o.nombre for o in objetivos.listar(usuario)]
    assert "Ash Prime: Sistemas" in nombres


def test_anadir_desde_una_pieza_anade_el_set_del_padre(usuario, indice_poblado):
    con, _, _ = indice_poblado
    pieza = indice.buscar(con, "sistemas ash prime")[0]["item_id"]
    objetivos.anadir_set(usuario, con, pieza)
    assert len(objetivos.listar(usuario)) == 2


def test_el_progreso_persiste_y_se_completa(usuario, indice_poblado):
    con, _, _ = indice_poblado
    ash = con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    ids = objetivos.anadir_set(usuario, con, ash)

    objetivos.sumar(usuario, ids[0], 1)
    guardado = next(o for o in objetivos.listar(usuario) if o.id == ids[0])
    assert guardado.actual == 1 and guardado.completado

    # Reabrir la base de datos: el progreso sigue ahi.
    ruta = usuario.execute("PRAGMA database_list").fetchone()[2]
    usuario.close()
    otra = sqlite3.connect(ruta)
    assert otra.execute("SELECT cantidad_actual FROM objetivos WHERE id = ?", (ids[0],)).fetchone()[0] == 1


def test_no_baja_de_cero(usuario, indice_poblado):
    con, _, _ = indice_poblado
    ash = con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    ids = objetivos.anadir_set(usuario, con, ash)
    objetivos.sumar(usuario, ids[0], -5)
    assert next(o for o in objetivos.listar(usuario) if o.id == ids[0]).actual == 0


def test_sumar_por_item_solo_afecta_a_lo_que_esta_en_la_lista(usuario, indice_poblado):
    con, _, _ = indice_poblado
    ash = con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    objetivos.anadir_set(usuario, con, ash)
    sistemas = con.execute(
        "SELECT unique_name FROM items WHERE nombre_en = 'Systems'"
    ).fetchone()[0]

    assert objetivos.sumar_por_item(usuario, sistemas, 1, origen="ocr") is not None
    assert objetivos.sumar_por_item(usuario, "/Lotus/NoExiste", 1) is None


def test_eras_necesarias_para_marcar_las_fisuras(usuario, indice_poblado):
    con, _, _ = indice_poblado
    ash = con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    objetivos.anadir_set(usuario, con, ash)
    # Axi A7 esta en boveda en el fixture, asi que no se propone ninguna era.
    assert objetivos.eras_necesarias(con, usuario) == {}


@pytest.mark.parametrize(
    "linea, esperado",
    [
        ("3745.063 Script [Info]: ProjectionRewardChoice.lua: Got rewards", "reliquia_recompensas"),
        (
            "3745.0 Script [Info]: ProjectionRewardChoice.lua: Relic rewards initialized",
            "reliquia_abierta",
        ),
        (
            "3946.0 Script [Info]: ProjectionRewardChoice.lua: Selection countdown done",
            "reliquia_elegida",
        ),
        ("1.0 Script [Info]: EndOfMatch.lua: Mission Succeeded", "mision_completada"),
        ("1.0 Sys [Info]: Cualquier otra linea con datos personales", None),
    ],
)
def test_clasificar_lineas_del_log(linea, esperado):
    assert clasificar(linea) == esperado
