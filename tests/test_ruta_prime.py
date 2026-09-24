"""Modelo de tiempo hasta una pieza prime (datos/ruta_prime.py), con numeros a mano.

Indice sintetico: una pieza al 10 % en Radiante en una reliquia disponible, que cae
en una Captura al 10 % y en la rotacion C de una Supervivencia al 30 %; la misma
pieza al 20 % en una reliquia en boveda que aun figura en una mision al 50 %.
"""

from __future__ import annotations

import pytest

from farmadex.datos import eficiencia, relaciones, ruta_prime


def _item(con, unico, en, es=None, categoria="Warframes", padre=None, vaulted=None, tipo=None):
    cur = con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo, es_prime, padre_id, vaulted, item_count) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
        (unico, en, es, categoria, tipo, padre, vaulted, 1 if padre else None),
    )
    return cur.lastrowid


def _nodo(con, clave, nombre, planeta, mision, nivel=(10, 15)):
    cur = con.execute(
        "INSERT INTO nodos (unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_en, "
        "nivel_min, nivel_max, clave_drops) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (clave, nombre, nombre, planeta, planeta, mision, nivel[0], nivel[1], clave),
    )
    return cur.lastrowid


def _premio(con, reliquia, item, probs):
    for refinamiento, prob in probs.items():
        con.execute(
            "INSERT INTO reliquia_recompensas (reliquia_id, refinamiento, item_id, probabilidad) VALUES (?, ?, ?, ?)",
            (reliquia, refinamiento, item, prob),
        )
        con.execute(
            "INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, refinamiento, probabilidad) "
            "VALUES (?, 'reliquia', ?, 'x', ?, ?)",
            (item, reliquia, refinamiento, prob),
        )


def _cae(con, reliquia, nodo, clave, prob, rotacion=None):
    con.execute(
        "INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, rotacion, probabilidad) "
        "VALUES (?, 'mision', ?, ?, ?, ?)",
        (reliquia, nodo, clave, rotacion, prob),
    )


@pytest.fixture()
def prime(con):
    padre = _item(con, "/P/CalibanPrime", "Caliban Prime", "Caliban Prime")
    plano = _item(con, "/P/CalibanPrimeBlueprint", "Blueprint", "Plano", padre=padre, tipo="Componente")
    chasis = _item(con, "/P/CalibanPrimeChassis", "Chassis", "Chasis", padre=padre, tipo="Componente")
    ash = _item(con, "/P/AshPrime", "Ash Prime", "Ash Prime")
    sistemas = _item(con, "/P/AshPrimeSystems", "Systems", "Sistemas", padre=ash, tipo="Componente")
    forma = _item(con, "/P/Forma", "Forma", "Forma", categoria="Resources")
    lith = _item(con, "/R/LithT1", "Lith T1 Relic", "Reliquia Lith T1", "Relics", vaulted=0)
    meso = _item(con, "/R/MesoT3", "Meso T3 Relic", "Reliquia Meso T3", "Relics", vaulted=0)
    axi = _item(con, "/R/AxiT2", "Axi T2 Relic", "Reliquia Axi T2", "Relics", vaulted=1)
    _premio(con, lith, plano, {"Intact": 2.0, "Radiant": 10.0})
    _premio(con, lith, forma, {"Intact": 25.33, "Radiant": 16.67})
    _premio(con, meso, chasis, {"Intact": 11.0, "Radiant": 20.0})
    _premio(con, axi, plano, {"Intact": 11.0, "Radiant": 20.0})
    _premio(con, axi, sistemas, {"Intact": 2.0, "Radiant": 10.0})
    captura = _nodo(con, "Earth/Captura", "Captura", "Earth", "Capture")
    gemela = _nodo(con, "Mars/Gemela", "Gemela", "Mars", "Capture", nivel=(20, 25))
    superv = _nodo(con, "Earth/Superv", "Superv", "Earth", "Survival")
    _cae(con, lith, captura, "Earth/Captura", 10.0)
    _cae(con, lith, gemela, "Mars/Gemela", 10.0)
    _cae(con, lith, superv, "Earth/Superv", 30.0, "C")
    _cae(con, meso, captura, "Earth/Captura", 10.0)
    # Las tablas aun traen reliquias en boveda en alguna mision: no pueden contar.
    _cae(con, axi, captura, "Earth/Captura", 50.0)
    con.commit()
    return {"plano": plano, "chasis": chasis, "sistemas": sistemas, "padre": padre, "ash": ash,
            "forma": forma, "lith": lith, "meso": meso, "axi": axi}


def test_reliquias_de_media_solo_y_en_escuadra():
    # Pieza al 10 %: en solitario 10 reliquias; en escuadra de 4, 1 / (1 - 0.9^4) = 2.908.
    assert ruta_prime.reliquias_necesarias(10.0, 1) == pytest.approx(10.0)
    assert ruta_prime.reliquias_necesarias(10.0, 4) == pytest.approx(1 / 0.3439, rel=1e-6)
    assert ruta_prime.probabilidad_por_fisura(10.0, 4) == pytest.approx(0.3439)
    assert ruta_prime.reliquias_necesarias(0, 4) is None


def test_una_pieza_al_10_por_ciento_con_numeros_a_mano(con, prime):
    assert eficiencia.FISURA == 3.5
    solo = ruta_prime.ruta_pieza(con, prime["plano"], "Radiant", 1)
    escuadra = ruta_prime.ruta_pieza(con, prime["plano"], "Radiant", 4)
    # Captura: 1 + 1.5 min por intento, reliquia al 10 % -> 25 min por reliquia.
    # Solo: 10 reliquias x (25 + 3.5) = 285 min. Escuadra: 2.908 x 28.5 = 82.9 min.
    assert solo["minutos"] == 285.0
    assert escuadra["minutos"] == 82.9
    assert escuadra["mision"]["mision"] == "Captura"
    assert escuadra["mision"]["minutos_reliquia"] == 25.0
    assert escuadra["reliquia"]["nombre_en"] == "Lith T1 Relic"
    # Intacta (2 %) en solitario: 50 reliquias x 28.5 = 1425 min.
    assert ruta_prime.ruta_pieza(con, prime["plano"], "Intact", 1)["minutos"] == 1425.0


def test_gana_el_menor_porcentaje_de_mision_si_tarda_menos(con, prime):
    """Supervivencia C al 30 % pierde contra Captura al 10 %: 21.5 min por intento."""
    misiones = ruta_prime.ruta_pieza(con, prime["plano"], "Radiant", 4)["misiones"]
    assert [m["modo"] for m in misiones] == ["Capture", "Survival"]
    captura, superv = misiones
    assert captura["probabilidad"] == 10.0 and superv["probabilidad"] == 30.0
    # (21.5 + 3.5 x 0.3) / (0.3 x 0.3439) = 218.6 min, frente a 82.9.
    assert superv["minutos"] == 218.6 and captura["minutos"] < superv["minutos"]
    # Dos nodos con la misma tabla y la misma duracion son una sola fila.
    assert captura["sitios"] == ["Captura, Earth", "Gemela, Mars"]


def test_la_reliquia_en_boveda_se_lista_pero_no_entra_en_el_orden(con, prime):
    ruta = ruta_prime.ruta_pieza(con, prime["plano"], "Radiant", 4)
    axi = next(r for r in ruta["reliquias"] if r["nombre_en"] == "Axi T2 Relic")
    assert axi["vaulted"] and axi["probabilidad"] == 20.0
    assert ruta["reliquias"][-1] is axi  # al final, aunque tenga mas probabilidad
    for m in ruta["misiones"]:
        assert all(r["nombre_en"] != "Axi T2 Relic" for r in m["reliquias"])
    # La Captura sigue al 10 %: el 50 % de la Axi en boveda no se suma.
    assert ruta["misiones"][0]["probabilidad"] == 10.0

    solo_boveda = ruta_prime.ruta_pieza(con, prime["sistemas"], "Radiant", 4)
    assert solo_boveda["solo_en_boveda"] and solo_boveda["mision"] is None and solo_boveda["minutos"] is None


def test_varias_piezas_cuentan_la_siguiente_cualquiera(con, prime):
    reliquias = ruta_prime.reliquias_para(con, [prime["plano"], prime["chasis"]], "Radiant")
    misiones = ruta_prime.misiones_para(con, reliquias, 4)
    captura = misiones[0]
    # En la Captura caen las dos reliquias utiles (10 % cada una): la rotacion vale por las dos.
    assert {r["nombre_en"] for r in captura["reliquias"]} == {"Lith T1 Relic", "Meso T3 Relic"}
    assert captura["probabilidad"] == 20.0
    p_plano = ruta_prime.probabilidad_por_fisura(10.0, 4)
    p_chasis = ruta_prime.probabilidad_por_fisura(20.0, 4)
    esperado = (2.5 + 3.5 * 0.2) / (0.1 * p_plano + 0.1 * p_chasis)
    assert captura["minutos"] == round(esperado, 1)
    assert captura["minutos"] < ruta_prime.ruta_pieza(con, prime["plano"], "Radiant", 4)["minutos"]
    assert captura["reliquias"][0]["nombre_en"] == "Meso T3 Relic"  # la que mas aporta, primero


def test_catalogo_separa_objetos_sueltos_y_boveda(con, prime):
    objetos, sueltos = ruta_prime.catalogo(con)
    por_nombre = {o["nombre_en"]: o for o in objetos}
    assert [p["nombre_en"] for p in por_nombre["Caliban Prime"]["piezas"]] == ["Blueprint", "Chassis"]
    assert not por_nombre["Caliban Prime"]["en_boveda"]
    assert por_nombre["Ash Prime"]["en_boveda"]  # su unica pieza solo esta en la Axi
    assert [s["nombre_en"] for s in sueltos] == ["Forma"]


def test_mejor_ruta_elige_por_tiempo_hasta_la_pieza(con, prime):
    ruta = relaciones.mejor_ruta(con, prime["plano"])
    assert ruta["reliquia"]["nombre_en"] == "Lith T1 Relic"
    assert ruta["mision"]["mision"] == "Captura" and ruta["minutos_pieza"] == 82.9


def test_las_preferencias_salen_de_la_configuracion(con, prime, monkeypatch, tmp_path):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    assert ruta_prime.preferencias() == ("Radiant", 4)
    ajustes = config.cargar()
    ajustes[ruta_prime.CLAVE_ESCUADRA] = 1
    ajustes[ruta_prime.CLAVE_REFINAMIENTO] = "Nada"
    assert ruta_prime.preferencias() == ("Radiant", 1)
    assert ruta_prime.ruta_pieza(con, prime["plano"])["minutos"] == 285.0
