"""Pestana Primes (marcar, guardar, resultado ordenado) y "Por donde empezar" de la ficha."""

from __future__ import annotations

import pytest

from test_ruta_prime import prime  # noqa: F401 - fixture del indice sintetico

from farmadex.estado import objetivos as estado_objetivos
from farmadex.estado import usuario_db


@pytest.fixture()
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def entorno(app, con, prime, tmp_path, monkeypatch):  # noqa: F811
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    usuario = usuario_db.conectar(tmp_path / "usuario.sqlite")
    return con, prime, usuario


def _pestana(con, usuario):
    from farmadex.ui.pestana_primes import PestanaPrimes

    pestana = PestanaPrimes(usuario=usuario)
    pestana.conectar_indice(con)
    return pestana


def _caja(pestana, nombre_en):
    return next((c for c in pestana._cajas if c.objeto and c.objeto["nombre_en"] == nombre_en), None)


def test_rejilla_solo_lo_farmeable_salvo_que_se_pida_la_boveda(entorno):
    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    assert _caja(pestana, "Caliban Prime") is not None
    assert _caja(pestana, "Ash Prime") is None  # todo en boveda
    sueltos = next(c for c in pestana._cajas if c.objeto is None)
    assert [p["nombre_en"] for p in sueltos.piezas] == ["Forma"]

    pestana.incluir_boveda.setChecked(True)
    assert _caja(pestana, "Ash Prime") is not None

    pestana.filtro.setText("calib")
    visibles = [c for c in pestana._cajas if not c.isHidden()]
    assert [c.objeto["nombre_en"] for c in visibles] == ["Caliban Prime"]


def test_marcar_crea_el_objetivo_y_se_recuerda(entorno):
    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    caja = _caja(pestana, "Caliban Prime")
    caja.casillas["/P/CalibanPrimeBlueprint"].setChecked(True)
    assert [o.nombre for o in estado_objetivos.listar(usuario)] == ["Caliban Prime: Plano"]

    # Otra pestana (otra sesion) con la misma BD: sale marcada.
    otra = _pestana(con, usuario)
    assert _caja(otra, "Caliban Prime").casillas["/P/CalibanPrimeBlueprint"].isChecked()

    # Y al reves: un objetivo anadido desde la ficha se marca aqui.
    estado_objetivos.anadir(usuario, "/P/CalibanPrimeChassis", "Chasis")
    otra.refrescar_marcas()
    assert _caja(otra, "Caliban Prime").casillas["/P/CalibanPrimeChassis"].isChecked()

    caja.casillas["/P/CalibanPrimeBlueprint"].setChecked(False)
    assert [o.unique_name for o in estado_objetivos.listar(usuario)] == ["/P/CalibanPrimeChassis"]


def test_resultado_ordenado_por_tiempo(entorno):
    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    _caja(pestana, "Caliban Prime").casillas["/P/CalibanPrimeBlueprint"].setChecked(True)

    datos = pestana.calcular()
    assert (datos["refinamiento"], datos["escuadra"]) == ("Radiant", 4)
    assert [m["modo"] for m in datos["misiones"]] == ["Capture", "Survival"]
    assert datos["misiones"][0]["minutos"] == 82.9
    html = pestana.html_resultado(datos)
    assert html.index("Lith T1") < html.index("Captura</a>, Earth") < html.index("Superv</a>, Earth")
    assert "En boveda (1)" in html and "Axi T2" in html  # listada, pero fuera del orden
    assert "~83 min" in html

    # En solitario: 505 min, y se guarda para la proxima vez (y para la ficha).
    pestana.escuadra.setCurrentIndex(pestana.escuadra.findData(1))
    assert pestana.calcular()["misiones"][0]["minutos"] == 285.0
    from farmadex.datos import ruta_prime

    assert ruta_prime.preferencias() == ("Radiant", 1)


def test_lo_conseguido_sigue_marcado_pero_no_cuenta(entorno):
    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    caja = _caja(pestana, "Caliban Prime")
    caja.casillas["/P/CalibanPrimeBlueprint"].setChecked(True)
    objetivo = estado_objetivos.listar(usuario)[0]
    estado_objetivos.sumar(usuario, objetivo.id, 1)
    pestana.refrescar_marcas()

    casilla = caja.casillas["/P/CalibanPrimeBlueprint"]
    assert casilla.isChecked() and casilla.text().endswith("✓")
    datos = pestana.calcular()
    assert datos["faltan"] == [] and datos["misiones"] == []
    assert "Ya conseguido" in pestana.html_resultado(datos)


def test_pieza_solo_en_boveda_sale_aparte(entorno):
    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    pestana.incluir_boveda.setChecked(True)
    _caja(pestana, "Ash Prime").casillas["/P/AshPrimeSystems"].setChecked(True)
    datos = pestana.calcular()
    assert [p["nombre_en"] for p in datos["solo_boveda"]] == ["Systems"]
    assert "Prime Resurgence" in pestana.html_resultado(datos)


def test_ficha_por_donde_empezar(entorno):
    con, prime, usuario = entorno
    from farmadex.ui.pestana_primes import bloque_ficha

    pieza = bloque_ficha(con, prime["plano"])
    assert "POR DONDE EMPEZAR" in pieza
    assert "Lith T1" in pieza and "10.0%" in pieza and "Radiante" in pieza
    assert "Captura</a>, Earth" in pieza and "(+1)" in pieza and "~83 min" in pieza
    assert "hasta tener la pieza" in pieza

    objeto = bloque_ficha(con, prime["padre"])
    assert "Plano" in objeto and "Chasis" in objeto and "Lith T1" in objeto and "Meso T3" in objeto

    boveda = bloque_ficha(con, prime["sistemas"])
    assert "Axi T2" in boveda and "Prime Resurgence" in boveda
    # Lo que no sale de reliquias sigue con la ruta de siempre.
    assert bloque_ficha(con, prime["lith"]) is None


def test_la_ficha_del_buscador_usa_la_ruta_completa(entorno):
    con, prime, usuario = entorno
    from farmadex.ui.pestana_buscador import PestanaBuscador

    buscador = PestanaBuscador()
    buscador.con = con
    buscador.abrir(prime["plano"])
    html = buscador._html(buscador._datos_actuales)
    assert "hasta tener la pieza" in html and "Lith T1" in html and "~83 min" in html
