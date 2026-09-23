"""El modelo de tiempo medio: duraciones estimadas por tipo de mision y el orden que sale."""

import json

from farmadex.datos import eficiencia, relaciones


def _fuente(**campos) -> dict:
    base = {
        "tipo": "mision", "origen_texto": "", "rotacion": None, "etapa": None,
        "probabilidad": None, "probabilidad_enemigo": None, "modo": "", "jefe": False,
    }
    base.update(campos)
    return base


def test_el_ejemplo_del_usuario_ordena_por_tiempo_no_por_porcentaje():
    """20 % en 40 minutos (200 min de media) pierde contra 10 % en 10 minutos (100 min)."""
    lenta = eficiencia.minutos_medios(40.0, 20.0)
    rapida = eficiencia.minutos_medios(10.0, 10.0)
    assert lenta == 200.0 and rapida == 100.0
    orden = sorted([{"minutos_medios": lenta}, {"minutos_medios": rapida}], key=eficiencia.clave_orden)
    assert [f["minutos_medios"] for f in orden] == [100.0, 200.0]


def test_captura_corta_gana_a_supervivencia_rotacion_c_con_mas_porcentaje():
    captura = _fuente(modo="Capture", probabilidad=10.0)
    supervivencia = _fuente(modo="Survival", rotacion="C", probabilidad=20.0)
    for f in (captura, supervivencia):
        f["probabilidad_efectiva"] = f["probabilidad"]
        eficiencia.estimar(f)
    # Captura: 3 min + 1.5 de carga = 4.5 por intento -> 45 min de media.
    assert captura["minutos_intento"] == 4.5 and captura["minutos_medios"] == 45.0
    # Rotacion C: cuatro rotaciones de 5 min + carga = 21.5 por intento -> 107.5 min.
    assert supervivencia["minutos_intento"] == 21.5 and supervivencia["minutos_medios"] == 107.5
    assert sorted([supervivencia, captura], key=eficiencia.clave_orden)[0] is captura


def test_la_rotacion_a_cuesta_menos_que_la_c_en_la_misma_mision():
    minutos = {r: eficiencia.minutos_por_intento(_fuente(modo="Survival", rotacion=r))[0] for r in "ABC"}
    # Saliendo tras la segunda A se llevan dos A en 10 min + carga: 5.75 cada una.
    assert minutos["A"] == 5.75
    assert minutos["A"] < minutos["B"] < minutos["C"]
    assert minutos["C"] == 21.5


def test_espionaje_cobra_las_tres_rotaciones_en_la_misma_partida():
    a = eficiencia.minutos_por_intento(_fuente(modo="Spy", rotacion="A"))[0]
    c = eficiencia.minutos_por_intento(_fuente(modo="Spy", rotacion="C"))[0]
    assert (a, c) == (4.5, 9.5)


def test_los_contratos_rotan_cada_tres_tandas():
    corto = eficiencia.minutos_por_intento(
        _fuente(tipo="bounty", origen_texto="Contratos de Cetus Level 5 - 15 Cetus Bounty", rotacion="B")
    )[0]
    largo = eficiencia.minutos_por_intento(
        _fuente(tipo="bounty", origen_texto="Contratos de Deimos Level 40 - 50 Isolation Vault", rotacion="A")
    )[0]
    assert corto == 3 * (8.0 + 1.5)
    assert largo == 3 * (15.0 + 1.5)


def test_lo_que_no_se_puede_medir_dice_por_que():
    casos = {
        "por_muerte": _fuente(tipo="enemigo", origen_texto="Tusk Thumper Bull", probabilidad=60.0),
        "reputacion": _fuente(tipo="sindicato", probabilidad=100.0),
        "diaria": _fuente(tipo="sortie", probabilidad=5.0),
        "pvp": _fuente(modo="Conclave", rotacion="B", probabilidad=0.25),
        "desconocido": _fuente(tipo="otro", probabilidad=100.0),
    }
    for motivo, f in casos.items():
        f["probabilidad_efectiva"] = f["probabilidad"]
        eficiencia.estimar(f)
        assert f["minutos_medios"] is None and f["motivo"] == motivo, motivo
    # Y van detras de cualquier cosa estimada, por buena que fuese su probabilidad.
    estimada = {"minutos_medios": 5000.0}
    assert sorted([casos["reputacion"], estimada], key=eficiencia.clave_orden)[0] is estimada


def test_un_jefe_es_una_mision_de_asesinato_medible():
    jefe = _fuente(tipo="enemigo", origen_texto="Alad V", probabilidad=97.42, jefe=True)
    jefe["probabilidad_efectiva"] = 97.42
    eficiencia.estimar(jefe)
    assert jefe["minutos_intento"] == 9.5 and jefe["minutos_medios"] == 9.8


def test_texto_de_minutos_legible():
    assert eficiencia.texto_minutos(None) == ""
    assert eficiencia.texto_minutos(34.6) == "~35 min"
    assert eficiencia.texto_minutos(150.0) == "~2.5 h"
    assert eficiencia.texto_minutos(120.0) == "~2 h"
    assert eficiencia.texto_minutos(60 * 72.0) == "~3 d"


# -- Con el indice --------------------------------------------------------

def _nodos_y_recurso(con):
    con.executemany(
        "INSERT INTO nodos (unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_en, nivel_min, nivel_max, clave_drops) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("SolNodeT", "Themisto", "Temisto", "Jupiter", "Jupiter", "Assassination", 18, 20, "Jupiter/Themisto"),
            ("SolNodeA", "Ananke", "Ananke", "Jupiter", "Jupiter", "Capture", 16, 18, "Jupiter/Ananke"),
            ("SolNodeG", "Galilea", "Galilea", "Jupiter", "Jupiter", "Sabotage", 15, 17, "Jupiter/Galilea"),
            ("SolNodeN", "Naamah", "Naamah", "Europa", "Europa", "Assassination", 21, 23, "Europa/Naamah"),
            ("SolNodeS", "Sechura", "Sechura", "Pluto", "Pluton", "Survival", 30, 40, "Pluto/Sechura"),
            ("SolNodeE", "Everest", "Everest", "Earth", "Tierra", "Excavation", 5, 10, "Earth/Everest"),
        ],
    )
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, descripcion_es) VALUES "
        "('/Lotus/Types/Items/NeuralSensors', 'Neural Sensors', 'Sensores neuronales', 'Resources', "
        "'Enlace neuronal.\n\nUbicación: Júpiter')"
    )
    iid = con.execute("SELECT id FROM items WHERE nombre_en = 'Neural Sensors'").fetchone()[0]
    nodo = lambda nombre: con.execute("SELECT id FROM nodos WHERE nombre_en = ?", (nombre,)).fetchone()[0]  # noqa: E731
    con.executemany(
        "INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, rotacion, rareza, probabilidad, datos_extra) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [
            # El Raptor: 50 % por partida, pero las tablas solo dicen el nombre.
            (iid, "enemigo", None, "Raptor", None, None, 50.0, None),
            # Supervivencia rotacion C con mas porcentaje que el jefe de Naamah... en 21 minutos.
            (iid, "mision", nodo("Sechura"), "Pluto/Sechura", "C", "Uncommon", 60.0, '{"modo": "Survival", "evento": false}'),
            # Excavacion rotacion A con poco porcentaje, pero cada intento son 4 minutos.
            (iid, "mision", nodo("Everest"), "Earth/Everest", "A", "Common", 12.0, '{"modo": "Excavation", "evento": false}'),
        ],
    )
    return iid


def test_fuentes_de_ordena_por_tiempo_y_completa_a_los_jefes(con):
    iid = _nodos_y_recurso(con)
    fuentes = relaciones.fuentes_de(con, iid)
    resumen = [(f["donde"], f["motivo"], f["minutos_medios"]) for f in fuentes]
    # Alad V no esta en las tablas de este objeto: entra porque Sensores neuronales es
    # recurso de Jupiter y Alad V suelta el recurso del planeta al morir (97.42 %).
    assert resumen[0] == ("Alad V (Temisto, Jupiter)", "estimado", 9.8)
    assert fuentes[0]["jefe"] and fuentes[0]["recurso_planeta"] and fuentes[0]["mision"] == "Asesinato"
    # El Raptor lleva ahora su nodo y es una partida de 9.5 min al 50 %.
    assert resumen[1] == ("Raptor (Naamah, Europa)", "estimado", 19.0)
    # Excavacion A (4 min por intento / 12 %) gana a Supervivencia C (21.5 / 60 %) aunque
    # tenga cinco veces menos porcentaje: antes el orden era el contrario.
    assert [r[0] for r in resumen[2:]] == ["Everest, Tierra", "Sechura, Pluton"]
    assert fuentes[2]["minutos_medios"] < fuentes[3]["minutos_medios"]

    ruta = relaciones.mejor_ruta(con, iid)
    assert ruta["mision"]["donde"] == "Alad V (Temisto, Jupiter)" and ruta["minutos_medios"] == 9.8


def test_entre_filas_del_mismo_sitio_se_queda_la_que_mas_suelta(con):
    """"Eidolon Hydrolyst (Special)" y "Eidolon Hydrolyst" son el mismo sitio: solo
    entra uno, y tiene que ser el que mas suelta aunque las tablas lo traigan detras
    (mismo porcentaje de objeto, distinto porcentaje de que suelte algo)."""
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, descripcion_es) VALUES "
        "('/Lotus/Types/Arcanes/Grace', 'Arcane Grace', 'Gracia arcana', 'Arcanes', '')"
    )
    iid = con.execute("SELECT id FROM items WHERE nombre_en = 'Arcane Grace'").fetchone()[0]
    con.executemany(
        "INSERT INTO fuentes (item_id, tipo, origen_texto, probabilidad, probabilidad_enemigo) VALUES (?,?,?,?,?)",
        [(iid, "enemigo", "Eidolon Hydrolyst (Special)", 5.0, 10.0), (iid, "enemigo", "Eidolon Hydrolyst", 5.0, 100.0)],
    )
    fuentes = relaciones.fuentes_de(con, iid)
    assert [(f["origen_texto"], f["probabilidad_efectiva"]) for f in fuentes] == [("Eidolon Hydrolyst", 5.0)]


def test_mas_del_cien_por_cien_no_tarda_menos_de_un_intento():
    """Las cajas de las tablas traen 303 %: hasta la primera unidad es un intento."""
    assert eficiencia.minutos_medios(10.0, 303.52) == 10.0
    assert eficiencia.minutos_medios(10.0, 100.0) == 10.0
    assert eficiencia.minutos_medios(10.0, 0) is None and eficiencia.minutos_medios(10.0, None) is None


def test_archimedea_es_semanal_y_no_se_estima():
    """Una tanda a la semana; como partida de 10 min se colaba por delante de todo."""
    for origen in ("Deep Archimedea Legendary Rewards", "Temporal Archimedea Silver Rewards"):
        f = _fuente(tipo="transitoria", origen_texto=origen, probabilidad=25.0)
        eficiencia.estimar(f)
        assert (f["minutos_medios"], f["motivo"]) == (None, "semanal")
        assert eficiencia.clave_orden(f) > eficiencia.clave_orden({"minutos_medios": 9999.0})


def test_recurso_de_planeta_dice_donde_farmearlo(con):
    iid = _nodos_y_recurso(con)
    datos = relaciones.recurso_de_planeta(con, iid)
    assert [p["planeta_en"] for p in datos["planetas"]] == ["Jupiter"]
    # Las misiones mas cortas del planeta primero: Captura antes que Sabotaje.
    assert [(n["donde"], n["mision"], n["minutos"]) for n in datos["nodos"]] == [
        ("Ananke, Jupiter", "Captura", 3.0), ("Galilea, Jupiter", "Sabotaje", 7.0),
    ]
    assert [j["origen_texto"] for j in datos["jefes"]] == ["Alad V"]


def test_el_jefe_solo_entra_en_el_recurso_raro_de_su_planeta(con):
    _nodos_y_recurso(con)
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, descripcion_es) VALUES "
        "('/Lotus/Types/Items/AlloyPlate', 'Alloy Plate', 'Placas de aleacion', 'Resources', "
        "'Ubicación: Venus, Fobos, Ceres, Júpiter, Plutón y Sedna.')"
    )
    iid = con.execute("SELECT id FROM items WHERE nombre_en = 'Alloy Plate'").fetchone()[0]
    datos = relaciones.recurso_de_planeta(con, iid)
    # Cae en Jupiter, pero Alad V suelta Sensores neuronales, no placas.
    assert [p["planeta_en"] for p in datos["planetas"]] == ["Venus", "Phobos", "Ceres", "Jupiter", "Pluto", "Sedna"]
    assert datos["jefes"] == []
    assert relaciones.fuentes_de(con, iid) == []


def test_solo_una_lista_de_planetas_es_recurso_de_planeta(con):
    assert relaciones.planetas_de_descripcion(con, "Ubicación: Ceres, Saturno y Deimos") == ["Ceres", "Saturn", "Deimos"]
    assert relaciones.planetas_de_descripcion(con, "Ubicación: Misiones en el Vacío") == ["Void"]
    assert relaciones.planetas_de_descripcion(con, "Ubicación: Madrigueras de kubrow en la Tierra") == []
    assert relaciones.planetas_de_descripcion(con, "Sin ubicacion") == []
    assert relaciones.planetas_de_descripcion(con, None) == []


def test_las_misiones_de_una_reliquia_tambien_van_por_tiempo(indice_poblado):
    con, _, _ = indice_poblado
    reliquia = con.execute("SELECT id FROM items WHERE nombre_en = 'Axi A7 Relic'").fetchone()[0]
    misiones = relaciones.misiones_de(con, reliquia)
    estimadas = [m["minutos_medios"] for m in misiones if m["minutos_medios"] is not None]
    assert estimadas == sorted(estimadas)
    assert all("motivo" in m and json.dumps(m["minutos_intento"]) for m in misiones)


def test_las_filas_de_conclave_van_juntas_en_una_linea(con):
    """Ocho modos de Conclave al 0,2 % tapaban la tabla de Sensores neuronales."""
    import pytest

    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from farmadex.ui.pestana_buscador import PestanaBuscador

    base = {"jefe": False, "nodo_en": "", "origen_texto": "x", "recurso_planeta": False,
            "rotacion": "B", "etapa": None, "standing": None, "probabilidad_enemigo": None,
            "rareza": "Legendary", "minutos_medios": None}
    grupo = [dict(base, origen_texto="Formido", probabilidad=19.4, motivo=None, minutos_medios=70)]
    grupo += [dict(base, origen_texto=f"Modo {i} - Conclave", probabilidad=0.2, motivo="pvp") for i in range(8)]

    pestana = PestanaBuscador.__new__(PestanaBuscador)
    pestana.con = con
    import farmadex.ui.pestana_buscador as pb

    original = pb.nombre_bonito
    pb.nombre_bonito = lambda con, texto: texto
    try:
        html_tabla = PestanaBuscador._tabla_fuentes(pestana, grupo)
    finally:
        pb.nombre_bonito = original
    assert html_tabla.count("Conclave") == 1
    assert "8" in html_tabla and "Formido" in html_tabla


def test_los_contratos_de_evento_no_salen_como_ruta_principal():
    """La Nitaina recomendaba el contrato de Ghoul, que solo existe durante un evento."""
    from farmadex.datos import eficiencia

    ghoul = {"tipo": "bounty", "origen_texto": "Earth/Cetus (Level 15 - 25 Ghoul Bounty), Rotation A",
             "probabilidad": 30.0, "rotacion": "A"}
    minutos, motivo = eficiencia.minutos_por_intento(ghoul)
    assert minutos is None and motivo == "evento"


def test_todo_motivo_sin_estimacion_tiene_su_etiqueta():
    """"semanal" se anadio al calculo y no a la ficha: la columna de tiempo salia vacia."""
    import re
    from pathlib import Path

    from farmadex.ui.pestana_buscador import MOTIVOS_SIN_ESTIMACION

    codigo = Path(__file__).resolve().parents[1].joinpath("src/farmadex/datos/eficiencia.py").read_text(encoding="utf-8")
    motivos = set(re.findall(r'return None, "(\w+)"', codigo)) - {"desconocido"}
    assert motivos <= set(MOTIVOS_SIN_ESTIMACION), motivos - set(MOTIVOS_SIN_ESTIMACION)


def test_defensa_da_premio_cada_tres_oleadas():
    """La wiki (2026-09): recompensa cada 3 oleadas, no cada 5; la C en la oleada 12."""
    c = eficiencia.minutos_por_intento(_fuente(modo="Defense", rotacion="C"))[0]
    s = eficiencia.minutos_por_intento(_fuente(modo="Survival", rotacion="C"))[0]
    assert c < s
