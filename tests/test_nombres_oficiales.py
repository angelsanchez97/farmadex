"""Nombres de modos de mision, facciones y planetas como los dice el juego en castellano.

El tester vio "Disrupcion" en las misiones: en el juego es "Interrupcion". Los nombres
salen de los textos del juego que publica WFCD (warframe-worldstate-data, data/es).
"""

import json

import pytest

from farmadex import idiomas
from farmadex.config import DIR_RECURSOS
from farmadex.datos import misiones, modos_mision


@pytest.fixture()
def castellano():
    idiomas.cargar("es")
    yield
    idiomas.cargar("es")


GLOSARIO = json.loads((DIR_RECURSOS / "glosario_es.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("en, es", [
    ("Disruption", "Interrupción"), ("Interception", "Interceptación"), ("Hijack", "Usurpación"),
    ("Infested Salvage", "Salvamento infestado"), ("Mirror Defense", "Defensa reflectante"),
    ("Mobile Defense", "Defensa móvil"), ("Excavation", "Excavación"), ("Defection", "Deserción"),
    ("Sanctuary Onslaught", "Masacre en el Santuario"), ("Junction", "Convergencia"),
    ("Void Flood", "Inundación del Vacío"), ("Relay", "Repetidor"),
])
def test_glosario_de_misiones_con_los_nombres_del_juego(en, es):
    assert GLOSARIO["mision"][en] == es


def test_facciones_y_planetas_con_tilde_como_en_el_juego():
    assert GLOSARIO["faccion"]["Sentient"] == "Conscientes"
    assert GLOSARIO["planeta"]["Pluto"] == "Plutón" and GLOSARIO["planeta"]["Void"] == "Vacío"


def test_ningun_nombre_viejo_queda_en_el_glosario():
    viejos = {"Disrupcion", "Intercepcion", "Secuestro", "Rescate infestado", "Sintientes", "Relevo"}
    usados = {v for dominio in GLOSARIO.values() for v in dominio.values()}
    assert not viejos & usados


def test_el_modo_se_llama_como_en_el_juego_y_coincide_con_el_glosario(castellano):
    assert modos_mision.nombre("Disruption") == "Interrupción"
    for modo, (es, en, _, _) in modos_mision.MODOS.items():
        if modo in GLOSARIO["mision"]:
            assert es == GLOSARIO["mision"][modo], modo


def test_en_otro_idioma_sale_el_catalogo_o_el_ingles():
    try:
        idiomas.cargar("en")
        assert modos_mision.nombre("Disruption") == "Disruption"
        # El catalogo tiene la clave sin tilde: se sigue encontrando.
        assert modos_mision.nombre("Void Storm") == idiomas.t("Tormenta del Vacio")
    finally:
        idiomas.cargar("es")


def test_buscar_por_el_nombre_viejo_sigue_encontrando_el_modo(con, castellano):
    claves = [r["clave"] for r in misiones.buscar(con, "disrupcion")]
    assert "modo:Disruption" in claves
    assert "modo:Disruption" in [r["clave"] for r in misiones.buscar(con, "interrupcion")]
