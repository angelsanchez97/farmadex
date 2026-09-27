"""Regresion: un jefe de asesinato que suelta el recurso raro de su planeta (Alad V con
Sensores neuronales, el Consejero Vay Hek con Neurodes, el General Sargas Ruk con la
Celula orokin...) tiene nodo y modo como cualquier mision, pero su fuente queda marcada
con tipo 'enemigo' en la base de datos. Antes de este arreglo, `_bloque_fuentes` agrupaba
la ficha por ese tipo tal cual y el jefe salia en su propia seccion "ENEMIGOS", aparte de
"MISIONES" y por debajo de ella. El usuario vio que "Como conseguirlo" recomendaba el
asesinato del jefe (es el sitio mas rapido) pero no lo encontraba en "Donde se consigue >
MISIONES", donde solo salian misiones normales y mas lentas.

El arreglo agrupa cualquier fuente con `jefe=True` junto con las de tipo 'mision', asi
que sale siempre en la misma seccion que el resto, ordenada por tiempo como todas.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

# Nodo, planeta y mision del jefe (tabla real de eficiencia.JEFES / RECURSO_RARO): el
# General Sargas Ruk esta en Tethys (Saturno) y suelta Celula orokin, el recurso raro
# de Saturno, al morir.
NODO_JEFE = ("SolNodeJefe", "Tethys", "Tethys", "Saturn", "Saturn", "Assassination", 20, 24, "Saturn/Tethys")
# Una mision normal, mas lenta, para que "Misiones" no este vacia antes del arreglo.
NODO_MISION = ("SolNodeMision", "Marduk", "Marduk", "Void", "Vacio", "Survival", 20, 30, "Void/Marduk")


@pytest.fixture()
def aplicacion():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def _celula_con_jefe(con):
    """Celula orokin: cae en Marduk (misiones) y la suelta Sargas Ruk (jefe) al morir."""
    con.executemany(
        "INSERT INTO nodos (unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_en, "
        "nivel_min, nivel_max, clave_drops) VALUES (?,?,?,?,?,?,?,?,?)",
        [NODO_JEFE, NODO_MISION],
    )
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, descripcion_es) VALUES "
        "('/Lotus/Types/Items/MiscItems/OrokinCell', 'Orokin Cell', 'Célula orokin', 'Resources', "
        "'Celula energetica orokin.\n\nUbicación: Saturno')"
    )
    iid = con.execute(
        "SELECT id FROM items WHERE unique_name = '/Lotus/Types/Items/MiscItems/OrokinCell'"
    ).fetchone()[0]
    marduk = con.execute("SELECT id FROM nodos WHERE nombre_en = 'Marduk'").fetchone()[0]
    con.execute(
        "INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, rotacion, rareza, probabilidad, datos_extra) "
        "VALUES (?, 'mision', ?, 'Void/Marduk', 'C', 'Uncommon', 15.1, ?)",
        (iid, marduk, '{"modo": "Survival", "evento": false}'),
    )
    # El jefe no trae nodo en las tablas de drops (drops.py solo guarda el nombre); lo
    # completa `relaciones._completar_jefe` buscandolo en `eficiencia.JEFES`.
    con.execute(
        "INSERT INTO fuentes (item_id, tipo, origen_texto, probabilidad) VALUES (?, 'enemigo', ?, ?)",
        (iid, "General Sargas Ruk", 97.42),
    )
    con.commit()
    return iid


@pytest.fixture()
def buscador(con, aplicacion):
    from farmadex import idiomas
    from farmadex.ui.pestana_buscador import PestanaBuscador

    idiomas.cargar("es")
    pestana = PestanaBuscador()
    pestana.con = con
    yield pestana
    pestana.close()


def test_recomendado_en_como_conseguirlo_aparece_en_la_lista(buscador, con):
    """La ruta que 'Como conseguirlo' recomienda tiene que estar en la lista de fuentes,
    sea cual sea su tipo: si no aparece, la recomendacion de arriba es mentira."""
    from farmadex.datos import relaciones

    iid = _celula_con_jefe(con)
    ruta = relaciones.mejor_ruta(con, iid)
    recomendado = ruta["mision"]
    assert recomendado is not None

    todas = relaciones.fuentes_de(con, iid)
    clave = (recomendado["donde"], recomendado.get("rotacion"), recomendado.get("etapa"))
    assert clave in {(f["donde"], f.get("rotacion"), f.get("etapa")) for f in todas}, (
        "lo recomendado en 'Como conseguirlo' no esta entre las fuentes de la ficha"
    )


def test_jefe_de_asesinato_sale_junto_a_las_misiones_por_tiempo(buscador, con):
    """El caso real reportado: el jefe (mas rapido) tiene que salir en la seccion de
    Misiones, no perdido en una seccion 'Enemigos' aparte y mas abajo."""
    from farmadex.datos import relaciones

    iid = _celula_con_jefe(con)
    fuentes = relaciones.fuentes_de(con, iid)
    jefe = next(f for f in fuentes if f["tipo"] == "enemigo")
    assert jefe["jefe"] is True and "Sargas Ruk" in jefe["donde"]

    ruta = relaciones.mejor_ruta(con, iid)
    assert ruta["mision"] is jefe or ruta["mision"]["donde"] == jefe["donde"], (
        "el jefe tendria que ser la ruta recomendada: es la mas rapida"
    )

    html = buscador._bloque_fuentes(iid)
    texto = html.upper()
    assert "MARDUK" in texto, "la mision normal tiene que seguir saliendo"
    assert "SARGAS RUK" in texto, "el jefe tiene que salir en la ficha"
    # La cabecera de seccion es un rotulo propio (">ENEMIGOS<"); el texto suelto
    # "enemigos" puede seguir saliendo dentro de un tooltip sin que sea un fallo.
    assert ">ENEMIGOS<" not in texto, (
        "el jefe de asesinato ya no deberia tener su propia seccion: es una mision mas"
    )
    assert texto.count(">MISIONES<") == 1
    # Las dos filas viven en la MISMA seccion (una sola cabecera "Misiones" en el HTML).
    seccion_misiones = texto.split(">MISIONES<", 1)[1]
    assert "SARGAS RUK" in seccion_misiones and "MARDUK" in seccion_misiones


def test_otro_jefe_de_planeta_tambien_se_agrupa_con_misiones(con, aplicacion):
    """No es un caso especial de un solo jefe: Alad V (Sensores neuronales, Jupiter)
    tiene que comportarse igual, sin tocar nada especifico de un boss en concreto."""
    from farmadex import idiomas
    from farmadex.datos import relaciones
    from farmadex.ui.pestana_buscador import PestanaBuscador

    idiomas.cargar("es")
    con.executemany(
        "INSERT INTO nodos (unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_en, "
        "nivel_min, nivel_max, clave_drops) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("SolNodeT", "Themisto", "Temisto", "Jupiter", "Jupiter", "Assassination", 18, 20, "Jupiter/Themisto"),
            ("SolNodeE", "Everest", "Everest", "Earth", "Tierra", "Excavation", 5, 10, "Earth/Everest"),
        ],
    )
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, descripcion_es) VALUES "
        "('/Lotus/Types/Items/NeuralSensors', 'Neural Sensors', 'Sensores neuronales', 'Resources', "
        "'Enlace neuronal.\n\nUbicación: Júpiter')"
    )
    iid = con.execute("SELECT id FROM items WHERE nombre_en = 'Neural Sensors'").fetchone()[0]
    everest = con.execute("SELECT id FROM nodos WHERE nombre_en = 'Everest'").fetchone()[0]
    con.execute(
        "INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, rotacion, rareza, probabilidad, datos_extra) "
        "VALUES (?, 'mision', ?, 'Earth/Everest', 'A', 'Common', 12.0, ?)",
        (iid, everest, '{"modo": "Excavation", "evento": false}'),
    )
    con.commit()

    fuentes = relaciones.fuentes_de(con, iid)
    alad_v = next(f for f in fuentes if f["tipo"] == "enemigo")
    assert alad_v["jefe"] and alad_v["recurso_planeta"]

    pestana = PestanaBuscador()
    pestana.con = con
    try:
        html = pestana._bloque_fuentes(iid)
        assert ">ENEMIGOS<" not in html.upper()
        assert "ALAD V" in html.upper() and "EVEREST" in html.upper()
    finally:
        pestana.close()
