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
