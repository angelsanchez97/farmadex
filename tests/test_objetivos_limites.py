"""Objetivos: limites del contador, sets, estados, paginas, borrado y recursos de fabricacion.

Todo sale del informe de un tester (3.2 y bugs): el contador se pasaba de la meta, no se
podian poner 500 de Criotica, se borraba sin preguntar y la lista era un scroll infinito.
"""

import sqlite3

import pytest

from farmadex.estado import inventario as estado_inventario
from farmadex.estado import objetivos, usuario_db
from farmadex.estado.objetivos import COMPLETADOS, EN_PROGRESO, MAX_CANTIDAD, SIN_EMPEZAR


@pytest.fixture()
def usuario(tmp_path):
    con = usuario_db.conectar(tmp_path / "usuario.sqlite")
    yield con
    con.close()


class _Cantidad:
    def __init__(self, unique_name, cantidad):
        self.unique_name, self.cantidad, self.nombre, self.confianza = unique_name, cantidad, unique_name, 1.0


def _magistar(con):
    """Arma de clan con receta de recursos compartidos, como en el juego (sin padre)."""
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo) "
        "VALUES ('/Mag', 'Magistar', 'Magistar', 'Melee', 'Melee')"
    )
    mag = con.execute("SELECT id FROM items WHERE unique_name = '/Mag'").fetchone()[0]
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo, padre_id, item_count) "
        "VALUES ('/MagBP', 'Blueprint', 'Plano', 'Melee', 'Componente', ?, 1)", (mag,)
    )
    receta = [("/MagBP", 1)]
    for unico, en, es, n in (("/Ferrite", "Ferrite", "Ferrita", 750), ("/Rubedo", "Rubedo", "Rubedo", 300)):
        con.execute(
            "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo) "
            "VALUES (?, ?, ?, 'Resources', 'Resource')", (unico, en, es)
        )
        receta.append((unico, n))
    for unico, n in receta:
        item = con.execute("SELECT id FROM items WHERE unique_name = ?", (unico,)).fetchone()[0]
        con.execute("INSERT INTO recetas (padre_id, item_id, cantidad) VALUES (?, ?, ?)", (mag, item, n))
    con.commit()
    return mag


# -- el contador no pasa de la meta ---------------------------------------------------


def test_sumar_se_para_en_la_meta_y_no_apunta_de_mas(usuario):
    oid = objetivos.anadir(usuario, "/Cryotic", "Criotica", 500)
    assert objetivos.sumar(usuario, oid, 450).actual == 450
    o = objetivos.sumar(usuario, oid, 100)
    assert (o.actual, o.objetivo, o.completado) == (500, 500, True)
    assert objetivos.sumar(usuario, oid, 1).actual == 500
    eventos = [f[0] for f in usuario.execute(
        "SELECT cantidad FROM progreso_eventos WHERE objetivo_id = ? ORDER BY id", (oid,))]
    assert eventos == [450, 50]  # lo recortado se apunta tal cual; lo que no cambia, no


def test_cantidades_grandes_validadas(usuario):
    oid = objetivos.anadir(usuario, "/Cryotic", "Criotica", 500)
    assert objetivos.obtener_objetivo(usuario, oid).objetivo == 500
    o = objetivos.fijar(usuario, oid, meta=300, actual=1000)
    assert (o.objetivo, o.actual, o.completado) == (300, 300, True)
    o = objetivos.fijar(usuario, oid, meta=0)
    assert o.objetivo == 1  # minimo 1: nada de numeros que desaparecen
    assert objetivos.fijar(usuario, oid, meta=10**9).objetivo == MAX_CANTIDAD
    assert objetivos.validar_cantidad("1.000") == 1000
    assert objetivos.validar_cantidad(-5) == 1
    assert objetivos.validar_cantidad(-5, 0) == 0
    for malo in ("abc", 2.5, None, True, "1,5"):
        with pytest.raises(ValueError):
            objetivos.validar_cantidad(malo)


def test_ampliar_la_meta_reabre_el_objetivo(usuario):
    oid = objetivos.anadir(usuario, "/Cryotic", "Criotica", 5)
    objetivos.sumar(usuario, oid, 5)
    o = objetivos.ampliar_meta(usuario, oid, 10)
    assert (o.objetivo, o.actual, o.completado) == (15, 5, False)


def test_volver_a_anadir_con_mas_meta_lo_devuelve_a_pendiente(usuario):
    oid = objetivos.anadir(usuario, "/Cryotic", "Criotica", 1)
    objetivos.sumar(usuario, oid, 1)
    assert objetivos.anadir(usuario, "/Cryotic", "Criotica", 500) == oid
    o = objetivos.obtener_objetivo(usuario, oid)
    assert (o.objetivo, o.actual, o.completado) == (500, 1, False)


def test_al_crear_cuenta_lo_que_ya_tienes_en_el_inventario(usuario):
    estado_inventario.guardar(usuario, [_Cantidad("/Cryotic", 120), _Cantidad("/Neuro", 9)])
    cri = objetivos.obtener_objetivo(usuario, objetivos.anadir(usuario, "/Cryotic", "Criotica", 500))
    neu = objetivos.obtener_objetivo(usuario, objetivos.anadir(usuario, "/Neuro", "Neurodos", 5))
    assert (cri.actual, cri.estado) == (120, EN_PROGRESO)
    assert (neu.actual, neu.completado) == (5, True)  # tope en la meta


def test_el_inventario_no_pasa_el_contador_de_la_meta(usuario):
    oid = objetivos.anadir(usuario, "/Cryotic", "Criotica", 500)
    estado_inventario.guardar(usuario, [_Cantidad("/Cryotic", 900)])
    assert estado_inventario.sincronizar_objetivos(usuario) == [("/Cryotic", 0, 500)]
    assert objetivos.obtener_objetivo(usuario, oid).actual == 500
    assert estado_inventario.sincronizar_objetivos(usuario) == []  # sigue siendo idempotente


# -- entradas: sets, estados, orden, categorias y paginas ---------------------------------


def test_sets_en_un_solo_panel_y_estados(usuario, indice_poblado):
    con, _, _ = indice_poblado
    ash = con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    ids = objetivos.anadir_set(usuario, con, ash)
    suelto = objetivos.anadir(usuario, "/Cryotic", "Criotica", 500)

    lista = objetivos.entradas(usuario)
    assert [e.es_set for e in lista].count(True) == 1
    ash_entrada = next(e for e in lista if e.es_set)
    assert ash_entrada.nombre == "Ash Prime" and len(ash_entrada.objetivos) == 2
    assert ash_entrada.categoria == objetivos.SETS and ash_entrada.estado == SIN_EMPEZAR

    objetivos.sumar(usuario, ids[0], 1)
    assert next(e for e in objetivos.entradas(usuario) if e.es_set).estado == EN_PROGRESO
    objetivos.completar(usuario, ids[1])
    assert next(e for e in objetivos.entradas(usuario) if e.es_set).estado == COMPLETADOS
    # Lo completado sigue ahi y se puede corregir.
    objetivos.fijar(usuario, ids[1], actual=0)
    assert next(e for e in objetivos.entradas(usuario) if e.es_set).estado == EN_PROGRESO

    cuenta = objetivos.contar_por_estado(objetivos.entradas(usuario))
    assert cuenta == {SIN_EMPEZAR: 1, EN_PROGRESO: 1, COMPLETADOS: 0}
    assert [e.clave for e in objetivos.entradas(usuario, estado=SIN_EMPEZAR)] == [f"o:{suelto}"]


def test_mas_recientes_arriba_filtro_y_diez_por_pagina(usuario):
    for i in range(25):
        oid = objetivos.anadir(usuario, f"/R{i}", f"Recurso {i}", 10, categoria=objetivos.RECURSOS)
        usuario.execute("UPDATE objetivos SET creado_en = ? WHERE id = ?", (f"2026-09-{i + 1:02d}T10:00:00", oid))
    objetivos.anadir(usuario, "/W", "Rhino", 1, categoria=objetivos.WARFRAMES)
    usuario.commit()

    lista = objetivos.entradas(usuario)
    assert lista[0].nombre == "Rhino" and lista[1].nombre == "Recurso 24"
    assert [e.nombre for e in objetivos.entradas(usuario, categoria=objetivos.WARFRAMES)] == ["Rhino"]

    trozo, pagina, total = objetivos.paginar(lista, 0)
    assert (len(trozo), pagina, total) == (10, 0, 3)
    trozo, pagina, _ = objetivos.paginar(lista, 99)
    assert pagina == 2 and len(trozo) == 6
    assert objetivos.paginar([], 3) == ([], 0, 1)


def test_borrar_varios(usuario):
    ids = [objetivos.anadir(usuario, f"/X{i}", f"X{i}") for i in range(4)]
    objetivos.sumar(usuario, ids[0], 1)
    assert objetivos.borrar_varios(usuario, ids[:3]) == 3
    assert [o.id for o in objetivos.listar(usuario)] == [ids[3]]
    assert usuario.execute("SELECT COUNT(*) FROM progreso_eventos").fetchone()[0] == 0


# -- migracion de datos viejos ------------------------------------------------------------


def test_migracion_v2_conserva_los_objetivos_y_recorta_lo_pasado(tmp_path, indice_poblado):
    con, _, _ = indice_poblado
    sistemas = con.execute("SELECT unique_name FROM items WHERE nombre_en = 'Systems'").fetchone()[0]
    ruta = tmp_path / "viejo.sqlite"
    viejo = sqlite3.connect(ruta)
    viejo.executescript(
        "CREATE TABLE meta (clave TEXT PRIMARY KEY, valor TEXT);"
        "INSERT INTO meta VALUES ('esquema_version', '2');"
        "CREATE TABLE objetivos (id INTEGER PRIMARY KEY, item_unique_name TEXT NOT NULL, nombre TEXT NOT NULL,"
        " cantidad_objetivo INTEGER NOT NULL DEFAULT 1, cantidad_actual INTEGER NOT NULL DEFAULT 0,"
        " creado_en TEXT NOT NULL, completado_en TEXT, notas TEXT, orden INTEGER);"
    )
    viejo.execute(
        "INSERT INTO objetivos (item_unique_name, nombre, cantidad_objetivo, cantidad_actual, creado_en, completado_en)"
        " VALUES (?, 'Ash Prime: Sistemas', 1, 7, '2026-09-01T10:00:00', '2026-09-02T10:00:00')", (sistemas,)
    )
    viejo.execute(
        "INSERT INTO objetivos (item_unique_name, nombre, cantidad_objetivo, cantidad_actual, creado_en)"
        " VALUES ('/Cryotic', 'Criotica', 1, 3, '2026-09-03T10:00:00')"
    )
    viejo.commit()
    viejo.close()

    usuario = usuario_db.conectar(ruta)
    lista = {o.unique_name: o for o in objetivos.listar(usuario)}
    assert (lista[sistemas].actual, lista[sistemas].completado) == (1, True)
    assert (lista["/Cryotic"].actual, lista["/Cryotic"].completado) == (1, True)  # sin completado_en antes
    assert lista[sistemas].categoria is None

    assert objetivos.completar_datos(usuario, con) == 2
    lista = {o.unique_name: o for o in objetivos.listar(usuario)}
    assert (lista[sistemas].categoria, lista[sistemas].grupo_nombre) == (objetivos.SETS, "Ash Prime")
    assert lista["/Cryotic"].categoria == objetivos.OTROS  # no esta en el indice de prueba
    assert objetivos.completar_datos(usuario, con) == 0
    usuario.close()


# -- recursos de fabricacion ----------------------------------------------------------


def test_el_indice_guarda_las_recetas(indice_poblado):
    con, _, _ = indice_poblado
    ash = con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    assert con.execute("SELECT COUNT(*) FROM recetas WHERE padre_id = ?", (ash,)).fetchone()[0] == 2


def test_recursos_de_un_arma_uno_a_uno(usuario, con):
    _magistar(con)
    oid = objetivos.anadir(usuario, "/Mag", "Magistar", 2, indice=con)
    o = objetivos.obtener_objetivo(usuario, oid)
    assert o.categoria == objetivos.ARMAS and objetivos.tiene_recursos(con, "/Mag")

    recursos = {r.unique_name: r for r in objetivos.recursos_de(usuario, con, o)}
    assert recursos["/Ferrite"].necesario == 1500  # dos Magistar, el doble
    assert recursos["/Rubedo"].necesario == 600 and recursos["/Rubedo"].actual == 0

    objetivos.sumar_recurso(usuario, o, recursos["/Rubedo"], 10_000)
    assert recursos["/Rubedo"].actual == 600  # tampoco pasa de lo que pide la receta
    o = objetivos.obtener_objetivo(usuario, oid)
    assert o.actual == 0 and o.estado == EN_PROGRESO

    objetivos.completar(usuario, oid, con)
    o = objetivos.obtener_objetivo(usuario, oid)
    assert o.completado
    assert all(r.completado for r in objetivos.recursos_de(usuario, con, o))


def test_recursos_con_lo_que_dice_el_inventario(usuario, con):
    _magistar(con)
    estado_inventario.guardar(usuario, [_Cantidad("/Ferrite", 5000)])
    o = objetivos.obtener_objetivo(usuario, objetivos.anadir(usuario, "/Mag", "Magistar", 1, indice=con))
    ferrita = next(r for r in objetivos.recursos_de(usuario, con, o) if r.unique_name == "/Ferrite")
    assert (ferrita.actual, ferrita.en_inventario, ferrita.completado) == (750, 5000, True)


def test_indice_viejo_sin_tabla_recetas(usuario, indice_poblado):
    con, _, _ = indice_poblado
    con.execute("DROP TABLE recetas")
    receta = objetivos.receta_de(con, "/Lotus/Powersuits/Ninja/NinjaPrime")
    assert len(receta) == 2  # cae a las piezas propias
    assert objetivos.receta_de(None, "/x") == [] and objetivos.receta_de(con, "/no") == []
