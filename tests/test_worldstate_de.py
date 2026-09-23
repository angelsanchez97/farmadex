"""El respaldo: el worldState.php crudo de DE convertido a lo que entiende `analizar`.

El fixture es una copia recortada de la respuesta real del 2026-09-22 19:33 UTC;
los dos primeros nodos se cambiaron por los que tiene el indice de prueba.
Los ciclos se comprueban contra lo que publicaba warframestat ese mismo dia
a las 17:29:13 UTC (su respuesta, aunque vieja, calculaba bien los ciclos).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from farmadex.online import worldstate, worldstate_de

FIXTURES = Path(__file__).parent / "fixtures"
# Hora de la respuesta de warframestat usada como referencia para los ciclos.
REFERENCIA = datetime(2026, 9, 22, 17, 29, 13, tzinfo=timezone.utc)
# Fin del ciclo de contratos vigente a esa hora (el de despues empieza en el fixture).
FIN_CONTRATOS = datetime(2026, 9, 22, 18, 47, 51, tzinfo=timezone.utc)


@pytest.fixture()
def crudo():
    return json.loads((FIXTURES / "worldstate_de.json").read_text(encoding="utf-8"))


@pytest.fixture()
def traductor(indice_poblado):
    con, _, _ = indice_poblado
    return worldstate.Traductor(con)


def _iso(momento):
    return momento.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def test_el_crudo_se_convierte_a_la_forma_de_warframestat(crudo, traductor):
    ahora = datetime.fromtimestamp(crudo["Time"], timezone.utc)
    datos = worldstate_de.normalizar(crudo, traductor, ahora=ahora)

    assert datos["timestamp"] == _iso(ahora)
    fisuras = datos["fissures"]
    assert len(fisuras) == 5 + 2  # ActiveMissions + VoidStorms
    primera = fisuras[0]
    assert primera["node"] == "Abaddon (Europa)"  # SolNode203 casado con el indice
    assert primera["missionType"] == "Extermination" and primera["tier"] == "Axi"
    assert primera["isHard"] is False and primera["isStorm"] is False
    assert primera["expiry"].endswith("Z") and primera["activation"] < primera["expiry"]
    segunda = fisuras[1]
    assert segunda["node"] == "Hydron (Sedna)" and segunda["tier"] == "Requiem"
    assert segunda["isHard"] is True and segunda["missionType"] == "Assault"
    # Un nodo que el indice no conoce se deja con su id, no se pierde.
    assert fisuras[2]["node"] == "SolNode746"
    tormenta = fisuras[-1]
    assert tormenta["isStorm"] is True and tormenta["tier"] in ("Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia")

    assert datos["voidTrader"]["location"] == "Kronia Relay (Saturn)"
    assert datos["voidTrader"]["character"] == "Baro Ki'Teer"
    assert datos["voidTrader"]["inventory"] == []  # aun no ha llegado: sin Manifest
    assert datos["sortie"]["boss"] == "Ambulas"
    assert datos["sortie"]["variants"][0]["missionType"] == "Rescue"
    assert datos["sortie"]["variants"][0]["modifier"] == "Shields"
    assert datos["archonHunt"]["boss"] == "Archon Boreal"
    assert len(datos["archonHunt"]["variants"]) == 3
    invasion = datos["invasions"][0]
    assert invasion["attacker"]["faction"] == "Corpus" and invasion["defender"]["faction"] == "Grineer"
    assert invasion["attacker"]["reward"]["countedItems"][0]["type"] == "FormaBlueprint"
    assert 0 < invasion["completion"] < 100


def test_el_resultado_pasa_por_analizar_y_sale_traducido(crudo, traductor):
    ahora = datetime.fromtimestamp(crudo["Time"], timezone.utc)
    mundo = worldstate.analizar(worldstate_de.normalizar(crudo, traductor, ahora=ahora), traductor)

    assert mundo.momento == ahora
    orden = ["Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia"]
    eras = [f.era for f in mundo.fisuras]
    assert eras == sorted(eras, key=lambda e: orden.index(e) if e in orden else 99)  # ordenadas por era
    nodos = {f.nodo for f in mundo.fisuras}
    assert "Abaddon, Europa" in nodos and "Hydron, Sedna" in nodos
    assert any(f.acero for f in mundo.fisuras) and any(f.tormenta for f in mundo.fisuras)
    assert {c.nombre for c in mundo.ciclos} >= {"Tierra", "Cetus", "Valle del Orbe", "Llanuras de Cambion", "Zariman", "Duviri"}
    assert mundo.baro_detalle is not None and not mundo.baro_detalle.activo
    assert mundo.baro_detalle.lugar.startswith("Kronia Relay")
    assert mundo.sortie and mundo.arcontes and mundo.invasiones
    assert mundo.nightwave == [] and mundo.acero == []  # no se cubren; no se inventan


def test_los_ciclos_cuadran_con_lo_que_publicaba_warframestat():
    tierra = worldstate_de._ciclo_tierra(REFERENCIA)
    assert tierra == {"state": "day", "expiry": "2026-09-22T20:00:00.000Z"}

    cetus = worldstate_de._ciclo_cetus(FIN_CONTRATOS, REFERENCIA, "day", "night")
    assert cetus == {"state": "day", "expiry": "2026-09-22T17:57:00.000Z"}
    cambion = worldstate_de._ciclo_cetus(FIN_CONTRATOS, REFERENCIA, "fass", "vome")
    assert cambion["state"] == "fass"

    zariman = worldstate_de._ciclo_zariman(FIN_CONTRATOS, REFERENCIA)
    assert zariman == {"state": "grineer", "expiry": "2026-09-22T18:47:00.000Z"}

    valle = worldstate_de._ciclo_valle(REFERENCIA)
    assert valle["state"] == "cold"
    esperado = datetime(2026, 9, 22, 17, 33, 28, tzinfo=timezone.utc)
    assert abs(worldstate._momento(valle["expiry"]) - esperado) <= timedelta(minutes=1)

    duviri = worldstate_de._ciclo_duviri(REFERENCIA)
    assert duviri["state"] == "envy"
    assert abs(worldstate._momento(duviri["expiry"]) - datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)) <= timedelta(minutes=1)


def test_un_crudo_que_no_lo_es_se_rechaza():
    with pytest.raises(worldstate_de.ErrorCrudo):
        worldstate_de.comprobar_crudo({"timestamp": "2026-09-22T19:33:26.000Z", "fissures": []})
    with pytest.raises(worldstate_de.ErrorCrudo):
        worldstate_de.comprobar_crudo("<html>")


def test_sin_indice_los_nodos_quedan_con_su_id(crudo):
    datos = worldstate_de.normalizar(crudo, worldstate.Traductor(None))
    assert datos["fissures"][0]["node"] == "SolNode203"
    assert datos["fissures"][0]["enemy"] == ""
