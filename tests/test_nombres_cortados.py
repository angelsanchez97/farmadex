"""Un nombre leido que es parte de otro mas largo no se afirma si la tarjeta puede estar
tapada, y una pieza leida con o sin "Prime" solo casa con su variante.

Los dos primeros casos son capturas reales (videos en castellano a 1080p) en las que la
0.6.11 invento un mod: "Intensificación / U..." con la ayuda de un arcano encima de la
segunda linea salia como "Intensificación", y un "Continuidad" cortado por una tarjeta
ampliada, como "Continuidad". Aqui van las lineas que leyo el OCR en ellas (sin la imagen).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from farmadex.captura import builds as B  # noqa: E402
from farmadex.captura import huecos_build as H  # noqa: E402
from farmadex.captura.ocr import Casador, Leido, Reconocido  # noqa: E402
from test_captura import _insertar  # noqa: E402

LINEAS = json.loads((Path(__file__).parent / "fixtures" / "capturas_build" / "lineas_nombres_cortados.json")
                    .read_text(encoding="utf-8"))

CATALOGO = [
    ("/w/Uriel", "Uriel", "Uriel", "Warframes"),
    ("/m/CombatDiscipline", "Combat Discipline", "Disciplina de combate", "Mods"),
    ("/m/Intensify", "Intensify", "Intensificación", "Mods"),
    ("/m/UmbralIntensify", "Umbral Intensify", "Intensificación Umbral", "Mods"),
    ("/m/ArchonIntensify", "Archon Intensify", "Intensificación Arconte", "Mods"),
    ("/m/Flow", "Flow", "Flujo", "Mods"),
    ("/m/PrimedFlow", "Primed Flow", "Flujo Prime", "Mods"),
    ("/m/Continuity", "Continuity", "Continuidad", "Mods"),
    ("/m/PrimedContinuity", "Primed Continuity", "Continuidad Prime", "Mods"),
    ("/m/BlindRage", "Blind Rage", "Rabia ciega", "Mods"),
    ("/m/Infernum", "Uriel Infernum", "Infernum", "Mods"),
    ("/m/Overextended", "Overextended", "Ampliado", "Mods"),
    ("/m/Recrystalize", "Recrystalize", "Recristalizar", "Mods"),
    ("/m/PrimedSureFooted", "Primed Sure Footed", "Pies firmes Prime", "Mods"),
    ("/m/SteelCharge", "Steel Charge", "Carga de acero", "Mods"),
    ("/m/Rejuvenation", "Rejuvenation", "Breve respiro", "Mods"),
    ("/m/LootDetector", "Loot Detector", "Detector de saqueo", "Mods"),
    ("/m/PistolAmp", "Pistol Amp", "Amplificador de pistola", "Mods"),
    ("/m/RifleAmp", "Rifle Amp", "Amplificador de rifle", "Mods"),
    ("/a/Avenger", "Arcane Avenger", "Vengador Arcano", "Arcanes"),
    ("/a/Crepuscular", "Arcane Crepuscular", "Arcano Crepuscular", "Arcanes"),
    ("/a/Blessing", "Arcane Blessing", "Bendición Arcana", "Arcanes"),
    ("/a/Battery", "Arcane Battery", "Batería Arcana", "Arcanes"),
]


class _MotorDeLineas:
    """Devuelve las lineas guardadas de la captura entera; las relecturas de un recorte no
    leen nada (la palabra que falta esta tapada de verdad)."""

    tiempos: dict = {}

    def __init__(self, caso: dict):
        self.caso = caso

    def leer_tira(self, imagen, alto_deteccion=None):
        if imagen.shape[0] != self.caso["alto"] or imagen.shape[1] != self.caso["ancho"]:
            return []
        return [Leido(*fila) for fila in self.caso["lineas"]]


@pytest.fixture()
def catalogo(con):
    ids = _insertar(con, [(u, en, es, cat, None, None) for u, en, es, cat in CATALOGO])
    con.execute("UPDATE items SET tipo = 'Warframe' WHERE unique_name LIKE '/w/%'")
    con.execute("UPDATE items SET tipo = 'Warframe Mod' WHERE unique_name LIKE '/m/%'")
    con.execute("INSERT OR REPLACE INTO detalles (item_id, datos) VALUES (?, ?)",
                (ids["/m/CombatDiscipline"], json.dumps({"compat": "AURA"})))
    con.commit()
    return con


def _leer(con, caso: dict, quitar=lambda fila: False):
    caso = dict(caso, lineas=[f for f in caso["lineas"] if not quitar(f)])
    casador = B.crear_casador(con)
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    imagen = np.zeros((caso["alto"], caso["ancho"], 3), dtype=np.uint8)
    return B.leer_build(imagen, _MotorDeLineas(caso), casador, categorias, H.cargar_tipos_de_hueco(con))


def _dudosos(build) -> list[str]:
    return [h.texto for h in build.no_leidos if h.motivo == "dudoso"] + [s for s in build.sin_identificar if "¿" in s]


def test_la_segunda_linea_tapada_por_una_ayuda_no_se_da_por_el_mod_corto(catalogo):
    build = _leer(catalogo, LINEAS["uriel_ayuda_de_arcano"])
    nombres = [r.nombre for r in build.equipados]
    assert "Intensificación" not in nombres  # era "Intensificación Umbral" con "Umbral" tapado
    assert {"Continuidad Prime", "Flujo Prime", "Rabia ciega", "Infernum"} <= set(nombres)
    dudosos = _dudosos(build)
    assert len(dudosos) == 1 and dudosos[0].startswith("Intensificación (¿") and "Intensificación Umbral" in dudosos[0]


def test_el_mismo_mod_sin_nada_encima_se_da_por_seguro(catalogo):
    # La misma pantalla sin la ayuda del arcano abierta: no hay motivo para dudar.
    build = _leer(catalogo, LINEAS["uriel_ayuda_de_arcano"],
                  quitar=lambda f: 1150 <= f[1] <= 1600 and 395 <= f[2] <= 660)
    assert "Intensificación" in [r.nombre for r in build.equipados]
    assert not _dudosos(build)


def test_un_nombre_cortado_por_una_tarjeta_ampliada_no_se_da_por_el_mod_corto(catalogo):
    build = _leer(catalogo, LINEAS["tarjeta_ampliada_encima"])
    nombres = [r.nombre for r in build.equipados]
    assert "Continuidad" not in nombres
    assert {"Ampliado", "Recristalizar"} <= set(nombres)
    assert _dudosos(build) == ["Continuidad (¿Continuidad Prime?)"]


def test_la_ayuda_de_la_propia_tarjeta_ampliada_no_hace_dudar(catalogo):
    # La tarjeta bajo el raton crece y ensena su descripcion debajo del nombre, centrada con
    # el: el nombre se ve entero.
    casador = B.crear_casador(catalogo)
    categorias = dict(catalogo.execute("SELECT id, categoria FROM items"))
    flujo = casador.casar("Flujo", 85)
    lineas = [Leido("Flujo", 900, 400, 80, 24, 0.9), Leido("+275 de energia", 850, 432, 180, 22, 0.9),
              Leido("maxima.", 900, 458, 80, 22, 0.9), Leido("WARFRAME", 880, 490, 120, 22, 0.9)]
    build = B.Build(equipados=[Reconocido("Flujo", flujo[0], flujo[1], 100.0, (900, 400, 80, 24))],
                    lineas=lineas, ancho=1920, alto=1080)
    H.apartar_dudosos(None, build, None, casador, categorias, 85)
    assert [r.nombre for r in build.equipados] == ["Flujo"] and not _dudosos(build)


def test_si_al_releer_la_tarjeta_sale_el_nombre_largo_se_pone_el_largo(catalogo):
    casador = B.crear_casador(catalogo)
    categorias = dict(catalogo.execute("SELECT id, categoria FROM items"))
    corto = casador.casar("Intensificación", 85)
    lineas = [Leido("Intensificacion", 1135, 373, 140, 27, 0.9), Leido("ARCANO CREPUSCULAR", 1192, 399, 286, 23, 0.9)]
    build = B.Build(equipados=[Reconocido("Intensificacion", corto[0], corto[1], 100.0, (1135, 373, 140, 27))],
                    lineas=lineas, ancho=1920, alto=1080)

    class _Motor:
        def leer_tira(self, imagen, alto_deteccion=None):
            return [Leido("Intensificación", 40, 60, 300, 50, 0.9), Leido("Umbral", 120, 115, 140, 50, 0.9)]

    H.apartar_dudosos(np.zeros((1080, 1920, 3), dtype=np.uint8), build, _Motor(), casador, categorias, 85)
    assert [r.nombre for r in build.equipados] == ["Intensificación Umbral"] and not _dudosos(build)


# -- piezas con y sin Prime --------------------------------------------------------------

@pytest.fixture()
def piezas(con):
    _insertar(con, [
        ("/w/Ember", "Ember", "Ember", "Warframes", None, None),
        ("/w/Ember/Neu", "Neuroptics", "Neurópticas", "Warframes", "/w/Ember", None),
        ("/w/EmberPrime", "Ember Prime", "Ember Prime", "Warframes", None, None),
        ("/w/EmberPrime/Neu", "Neuroptics", "Neurópticas", "Warframes", "/w/EmberPrime", 45),
        ("/w/EmberPrime/Chs", "Chassis", "Chasis", "Warframes", "/w/EmberPrime", 45),
    ])
    return Casador(con)


def test_un_prime_mal_leido_no_casa_con_la_pieza_sin_prime(piezas):
    # Captura real en frances: "Ember Prime Neuroptiques" leido "EberPnke Neuroptiques".
    assert piezas.casar("EberPnke Neuroptics", 82)[0] is None
    assert piezas.casar("Ember Pr Neuroptics", 82)[0] is None
    assert piezas.casar("Neuropticas de Ember Pr", 82)[0] is None


def test_con_y_sin_prime_bien_leidos_casan_cada_uno_con_el_suyo(piezas):
    prime = piezas.casar("Ember Prime Neuroptics", 82)
    normal = piezas.casar("Ember Neuroptics", 82)
    assert prime[0] and normal[0] and prime[0] != normal[0]
    # Con una errata que no toca a "Prime" (o que lo deja reconocible) sigue siendo la suya.
    assert piezas.casar("Embr Prime Neuroptics", 82)[0] == prime[0]
    assert piezas.casar("Ember Prme Neuroptics", 82)[0] == prime[0]
    assert piezas.casar("Neuropticas de Embr Prime", 82)[0] == prime[0]
    assert piezas.casar("Embr Neuroptics", 82)[0] == normal[0]
    assert piezas.casar("Neuropticas de Embor", 82)[0] == normal[0]
