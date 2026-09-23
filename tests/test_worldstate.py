import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from farmadex.online import worldstate

FIXTURE = Path(__file__).parent / "fixtures" / "worldstate.json"


@pytest.fixture()
def datos():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def traductor(indice_poblado):
    con, _, _ = indice_poblado
    return worldstate.Traductor(con)


def test_restante_en_castellano():
    ahora = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert worldstate.restante(ahora + timedelta(seconds=45), ahora) == "45s"
    assert worldstate.restante(ahora + timedelta(minutes=3, seconds=2), ahora) == "3m 2s"
    assert worldstate.restante(ahora + timedelta(hours=2, minutes=5), ahora) == "2h 5m"
    assert worldstate.restante(ahora + timedelta(days=1, hours=3), ahora) == "1d 3h"
    assert worldstate.restante(ahora - timedelta(minutes=1), ahora) == "terminado"
    assert worldstate.restante(None) == ""


def test_traductor_de_nodos(traductor):
    # Hydron esta en el indice de prueba, asi que sale con su planeta traducido.
    assert traductor.nodo("Hydron (Sedna)") == "Hydron, Sedna"
    # Uno que no esta: al menos se traduce el planeta con el glosario.
    assert traductor.nodo("Oceanum (Pluto)") == "Oceanum, Pluton"
    assert traductor.nodo(None) == ""


def test_analizar_estado_real(datos, traductor):
    mundo = worldstate.analizar(datos, traductor)

    assert mundo.fisuras, "la captura real trae fisuras"
    primera = mundo.fisuras[0]
    assert primera.era in ("Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia")
    assert "," in primera.nodo  # nodo, planeta
    assert primera.expira is not None

    assert {c.nombre for c in mundo.ciclos} >= {"Tierra", "Cetus"}
    assert mundo.baro_cabecera
    assert mundo.sortie and mundo.sortie[0].texto


def test_las_fisuras_van_ordenadas_por_era(datos, traductor):
    eras = [f.era for f in worldstate.analizar(datos, traductor).fisuras]
    orden = {"Lith": 0, "Meso": 1, "Neo": 2, "Axi": 3, "Requiem": 4, "Omnia": 5}
    assert eras == sorted(eras, key=lambda e: orden.get(e, 9))


def test_una_clave_rota_no_tumba_el_resto(datos, traductor):
    datos["fissures"] = {"esto": "no es una lista de fisuras"}
    mundo = worldstate.analizar(datos, traductor)

    assert mundo.fisuras == []
    assert mundo.ciclos, "los ciclos siguen leyendose aunque las fisuras fallen"


def test_sin_clave_de_fisuras(datos, traductor):
    datos.pop("fissures")
    mundo = worldstate.analizar(datos, traductor)
    assert mundo.fisuras == []
    assert mundo.ciclos


def test_respuesta_vacia(traductor):
    mundo = worldstate.analizar({}, traductor)
    assert mundo.fisuras == [] and mundo.ciclos == [] and mundo.arbitracion is None


def test_arbitracion_de_relleno_se_ignora(datos, traductor):
    datos["arbitration"] = {"node": "SolNode000", "expiry": "+275760-09-13T00:00:00.000Z"}
    assert worldstate.analizar(datos, traductor).arbitracion is None


# -- Baro -------------------------------------------------------------------


def test_baro_con_inventario_casado_con_el_indice(datos, traductor):
    con = traductor.con
    # Un objeto del inventario real de la captura, dado de alta en el indice.
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, market_slug) VALUES "
        "('/Lotus/Upgrades/Mods/Melee/Expert/WeaponMeleeFactionDamageGrineerExpert', "
        "'Primed Smite Grineer', 'Castigar Grineer Prime', 'Mods', 'primed_smite_grineer')"
    )
    mundo = worldstate.analizar(datos, traductor)
    baro = mundo.baro_detalle

    assert baro is not None and baro.activo
    assert baro.lugar == "Larunda Relay, Mercurio"
    assert baro.llegada.isoformat().startswith("2026-09-18T13:00")
    assert baro.expira.isoformat().startswith("2026-09-20T13:00")
    assert len(baro.inventario) == len(datos["voidTrader"]["inventory"])
    # Ordenado por ducados, de mas a menos.
    ducados = [o.ducados for o in baro.inventario]
    assert ducados == sorted(ducados, reverse=True)

    smite = next(o for o in baro.inventario if o.nombre == "Primed Smite Grineer")
    assert smite.en_indice and smite.market_slug == "primed_smite_grineer"
    assert smite.nombre_mostrar == "Castigar Grineer Prime"
    assert smite.ducados == 350 and smite.creditos == 140000
    assert smite.unique_name.startswith("/Lotus/Upgrades/"), "sin el prefijo StoreItems"
    # Lo que no esta en el indice sigue saliendo, con su nombre en ingles.
    assert any(not o.en_indice for o in baro.inventario)
    # La lista antigua sigue rellena para la interfaz de hoy.
    assert len(mundo.baro) == len(baro.inventario) and mundo.baro_cabecera


def test_cuenta_atras_de_baro():
    ahora = datetime(2026, 9, 19, 13, 0, tzinfo=timezone.utc)
    presente = worldstate.Baro("Baro Ki'Teer", "Larunda Relay, Mercurio", True,
                               ahora - timedelta(days=1), ahora + timedelta(days=1), [])
    assert presente.cuenta_atras(ahora) == "1d 0h"
    assert presente.cabecera(ahora) == "Baro Ki'Teer en Larunda Relay, Mercurio · se va en 1d 0h"

    futuro = worldstate.Baro("Baro Ki'Teer", "", False, ahora + timedelta(days=5, hours=2), None, [])
    assert futuro.cuenta_atras(ahora) == "5d 2h"
    assert futuro.cabecera(ahora) == "Baro Ki'Teer llega en 5d 2h"

    sin_fecha = worldstate.Baro("Baro Ki'Teer", "", False, None, None, [])
    assert sin_fecha.cabecera(ahora) == "Baro Ki'Teer todavia no ha llegado"


def test_baro_ausente_deduce_el_estado(traductor):
    crudo = {"character": "Baro Ki'Teer", "location": "Kronia Relay (Saturn)",
             "activation": "2999-01-01T00:00:00.000Z", "expiry": "2999-01-03T00:00:00.000Z", "inventory": []}
    baro = worldstate.analizar_baro(crudo, traductor)
    assert baro is not None and not baro.activo and baro.lugar == "Kronia Relay, Saturno"
    assert worldstate.analizar_baro(None, traductor) is None
    assert worldstate.analizar_baro({"active": True, "inventory": "rota"}, traductor).inventario == []


def test_baro_cubre_objetivos(datos, traductor):
    baro = worldstate.analizar_baro(datos["voidTrader"], traductor)
    cubiertos = worldstate.marcar_objetivos(
        baro,
        ["/Lotus/Upgrades/Mods/Melee/Expert/WeaponMeleeFactionDamageGrineerExpert", "/Lotus/Nada", ""],
    )
    assert [o.nombre for o in cubiertos] == ["Primed Smite Grineer"]
    assert baro.objetivos() == cubiertos
    assert worldstate.marcar_objetivos(None, ["x"]) == []


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"message": "WorldState Not Found", "error": "Not Found", "statusCode": 404},
        {"statusCode": 500, "message": "boom"},
        [],
        "texto",
        {"fisuras": []},
    ],
)
def test_un_error_con_codigo_200_no_pasa_por_estado_del_mundo(cuerpo):
    """La API ha contestado 200 con un error dentro: no se puede pintar la pestana vacia."""
    with pytest.raises(worldstate.ErrorMundo):
        worldstate.comprobar_respuesta(cuerpo)


def test_un_estado_del_mundo_de_verdad_pasa(datos):
    assert worldstate.comprobar_respuesta(datos) is datos


def test_el_servicio_avisa_del_fallo_y_conserva_lo_ultimo_bueno(datos, traductor, monkeypatch):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    servicio = worldstate.ServicioMundo(None)
    servicio.traductor = traductor
    buenos, fallos = [], []
    servicio.actualizado.connect(buenos.append)
    servicio.fallo.connect(fallos.append)
    monkeypatch.setattr(servicio.cliente, "json", lambda *a, **k: datos)
    servicio.refrescar()
    assert len(buenos) == 1 and servicio.ultimo is buenos[0]
    # Ahora la API contesta 200 con un error dentro.
    monkeypatch.setattr(
        servicio.cliente, "json", lambda *a, **k: {"message": "WorldState Not Found", "statusCode": 404}
    )
    servicio.refrescar()
    assert len(buenos) == 1
    assert fallos and "WorldState Not Found" in fallos[-1]
    assert servicio.ultimo is buenos[0]
    servicio.cerrar()


# -- campos booleanos nulos (respuesta real del 2026-09-22) --------------------

FIXTURE_DESFASADO = Path(__file__).parent / "fixtures" / "worldstate_desfasado.json"


@pytest.fixture()
def desfasado():
    """Copia recortada de lo que publicaba api.warframestat.us el 2026-09-22 a las 19:35 UTC:
    'timestamp' de dos horas antes, todas las fisuras caducadas y "active"/"expired" a null."""
    return json.loads(FIXTURE_DESFASADO.read_text(encoding="utf-8"))


def test_bandera_distingue_nulo_de_falso():
    assert worldstate._bandera(True) is True and worldstate._bandera(False) is False
    assert worldstate._bandera(None) is None
    assert worldstate._bandera("") is None and worldstate._bandera("si") is None
    assert worldstate._bandera("true") is True and worldstate._bandera("FALSE") is False
    assert worldstate._bandera(1) is True and worldstate._bandera(0) is False
    assert worldstate._bandera(7) is None and worldstate._bandera([]) is None


def test_expired_nulo_no_borra_las_fisuras(desfasado, traductor):
    assert all(f["expired"] is None for f in desfasado["fissures"])
    mundo = worldstate.analizar(desfasado, traductor)
    assert len(mundo.fisuras) == len(desfasado["fissures"])
    # Lo que si venia bien se conserva.
    assert any(f.acero for f in mundo.fisuras)
    assert mundo.esta_viejo()  # el timestamp es de hace horas: se dice, no se esconde


def test_expired_true_si_se_respeta_y_los_tipos_raros_no(desfasado, traductor):
    desfasado["fissures"][0]["expired"] = True
    desfasado["fissures"][1]["expired"] = "no"  # ni booleano ni nada: no se sabe
    desfasado["fissures"][2]["isHard"] = None
    desfasado["fissures"][2]["isStorm"] = None
    desfasado["fissures"][2]["node"] = "Sover Strait (Earth Proxima)"
    mundo = worldstate.analizar(desfasado, traductor)
    assert len(mundo.fisuras) == len(desfasado["fissures"]) - 1
    tormenta = [f for f in mundo.fisuras if f.tormenta]
    assert len(tormenta) == 1 and not tormenta[0].acero  # deducida del nodo de Railjack


def test_active_nulo_en_baro_se_deduce_de_las_fechas(desfasado, traductor):
    assert desfasado["voidTrader"]["active"] is None
    baro = worldstate.analizar_baro(desfasado["voidTrader"], traductor)
    assert baro is not None and not baro.activo  # llega el 2 de octubre

    ahora = datetime.now(timezone.utc)
    v = dict(desfasado["voidTrader"])
    v["activation"] = (ahora - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    v["expiry"] = (ahora + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assert worldstate.analizar_baro(v, traductor).activo  # nulo + fechas dentro = esta
    v["active"] = False
    assert not worldstate.analizar_baro(v, traductor).activo  # un False de verdad manda


def test_completed_nulo_en_invasiones_se_deduce_del_porcentaje(desfasado, traductor):
    for i in desfasado["invasions"]:
        i["completed"] = None
    desfasado["invasions"][0]["completion"] = 100
    desfasado["invasions"][1]["completion"] = 37.5
    mundo = worldstate.analizar(desfasado, traductor)
    assert len(mundo.invasiones) == 1 and mundo.invasiones[0].porcentaje == 37.5


# -- respaldo con el worldState de DE -------------------------------------------

FIXTURE_DE = Path(__file__).parent / "fixtures" / "worldstate_de.json"


def _crudo_de_ahora():
    """El fixture de DE con su reloj y sus fechas movidos a ahora, para que este al dia."""
    crudo = json.loads(FIXTURE_DE.read_text(encoding="utf-8"))
    ahora = datetime.now(timezone.utc)
    desplazamiento = int(ahora.timestamp()) - int(crudo["Time"])
    crudo["Time"] = int(ahora.timestamp())

    def mover(nodo):
        if isinstance(nodo, dict):
            if "$date" in nodo and isinstance(nodo["$date"], dict):
                nodo["$date"]["$numberLong"] = str(int(nodo["$date"]["$numberLong"]) + desplazamiento * 1000)
            else:
                for v in nodo.values():
                    mover(v)
        elif isinstance(nodo, list):
            for v in nodo:
                mover(v)

    mover(crudo)
    return crudo


def _servicio_con(respuestas, traductor):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    servicio = worldstate.ServicioMundo(None)
    servicio.traductor = traductor
    buenos, fallos = [], []
    servicio.actualizado.connect(buenos.append)
    servicio.fallo.connect(fallos.append)

    def json_por_url(url, **_):
        respuesta = respuestas[url]
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    servicio.cliente.json = json_por_url
    return servicio, buenos, fallos


def test_si_warframestat_esta_desfasado_se_usa_el_crudo_de_de(desfasado, traductor):
    from farmadex.online.worldstate_de import URL_DE

    url = worldstate.URL.format(plataforma=worldstate.PLATAFORMA)
    servicio, buenos, fallos = _servicio_con({url: desfasado, URL_DE: _crudo_de_ahora()}, traductor)
    servicio.refrescar()
    assert len(buenos) == 1 and fallos == []
    mundo = buenos[0]
    assert mundo.fuente == "de" and not mundo.esta_viejo()
    assert len(mundo.fisuras) == 7 and mundo.baro_detalle is not None


def test_si_warframestat_falla_del_todo_tambien_entra_el_respaldo(traductor):
    from farmadex.online.worldstate_de import URL_DE

    url = worldstate.URL.format(plataforma=worldstate.PLATAFORMA)
    servicio, buenos, fallos = _servicio_con({url: RuntimeError("HTTP 502"), URL_DE: _crudo_de_ahora()}, traductor)
    servicio.refrescar()
    assert len(buenos) == 1 and buenos[0].fuente == "de" and fallos == []


def test_si_el_respaldo_tambien_falla_se_ensena_lo_viejo_y_se_avisa(desfasado, traductor):
    from farmadex.online.worldstate_de import URL_DE

    url = worldstate.URL.format(plataforma=worldstate.PLATAFORMA)
    servicio, buenos, fallos = _servicio_con({url: desfasado, URL_DE: RuntimeError("HTTP 404")}, traductor)
    servicio.refrescar()
    assert len(buenos) == 1 and buenos[0].fuente == "warframestat" and buenos[0].esta_viejo()
    assert fallos and "min" in fallos[0]

    # Y si el respaldo esta tan viejo como la principal, tampoco vale.
    viejo = json.loads(FIXTURE_DE.read_text(encoding="utf-8"))  # Time del 2026-09-22
    servicio, buenos, fallos = _servicio_con({url: desfasado, URL_DE: viejo}, traductor)
    servicio.refrescar()
    assert buenos[0].fuente == "warframestat" and fallos


def test_con_warframestat_al_dia_no_se_toca_el_respaldo(desfasado, traductor):
    from farmadex.online.worldstate_de import URL_DE

    url = worldstate.URL.format(plataforma=worldstate.PLATAFORMA)
    desfasado["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    servicio, buenos, fallos = _servicio_con({url: desfasado, URL_DE: AssertionError("no debia pedirse")}, traductor)
    servicio.refrescar()
    assert len(buenos) == 1 and buenos[0].fuente == "warframestat" and fallos == []
