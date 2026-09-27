"""Pestana Build: elegir el equipo a mano, Overframe siempre a mano, "¿Esta bien mi build?"
y "Build basica para..." (sin OCR ni ventanas visibles)."""

from __future__ import annotations

import os
from urllib.parse import parse_qs, urlparse

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.captura.builds import Build  # noqa: E402
from farmadex.captura.ocr import Reconocido  # noqa: E402

from test_evaluar_build import indice  # noqa: E402,F401 - el mismo indice de prueba


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def pestana(app, indice, tmp_path, monkeypatch):  # noqa: F811
    from farmadex import config
    from farmadex.datos import evaluar_build

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    evaluar_build.olvidar_cache()
    from farmadex.ui.pestana_builds import PestanaBuilds

    con, ids = indice
    p = PestanaBuilds()
    p.conectar_indice(con)
    yield p, ids
    evaluar_build.olvidar_cache()


def _rec(ids, nombre):
    return Reconocido(nombre, ids[nombre], nombre, 100.0, (0, 0, 10, 10))


def _consulta(url):
    return parse_qs(urlparse(url).query)["q"][0]


def test_sin_leer_se_elige_a_mano_y_abre_overframe(pestana):
    p, ids = pestana
    emitidas = []
    p.abrir_web.connect(emitidas.append)
    assert not p.boton_overframe.isHidden() and p.equipo_actual() is None
    # En el buscador salen los warframes y las armas con su tipo, no los mods.
    lista = p.completador.model().stringList()
    assert "Soma Prime (Arma principal)" in lista and "Excalibur (Warframe)" in lista
    assert not any("Sierra" in x for x in lista)
    p._elegido_en_buscador("Soma Prime (Arma principal)")
    assert p.equipo_actual() == ids["Soma Prime"]
    assert "Soma Prime" in p.estado.text() and p.nombre_equipo.texto_completo() == "SOMA PRIME"
    p.boton_overframe.click()
    assert [_consulta(u) for u in emitidas] == ["site:overframe.gg Soma Prime"]
    abiertos = []
    p.abrir_item.connect(abiertos.append)
    p.boton_ficha.click()
    assert abiertos == [ids["Soma Prime"]]
    # Escrito a medias: si solo uno lo contiene, ese.
    p._elegido_en_buscador("inaros")
    assert p.equipo_actual() == ids["Inaros"]


def test_lectura_sin_equipo_evalua_con_el_elegido(pestana):
    p, ids = pestana
    build = Build(equipados=[_rec(ids, "Hellfire"), _rec(ids, "Speed Trigger")], coleccion=[_rec(ids, "Serration")])
    p.mostrar_build(build)
    assert "elígelo a mano" in p.estado.text()
    assert not p.boton_evaluar.isHidden()
    p.mostrar_evaluacion()
    assert p.evaluacion is not None and "warframe o arma" in p.evaluacion.mal[0].texto
    p.elegir_equipo(ids["Soma Prime"])
    p.mostrar_evaluacion()
    textos = " | ".join(x.texto for x in p.evaluacion.mal)
    assert "daño base" in textos and "multidisparo" in textos
    assert not p.panel_evaluacion.isHidden()


def test_lectura_con_equipo_y_build_basica_marca_lo_que_tienes(pestana):
    p, ids = pestana
    build = Build(equipo=_rec(ids, "Soma Prime"), equipados=[_rec(ids, "Split Chamber")],
                  coleccion=[_rec(ids, "Serration")])
    p.mostrar_build(build)
    assert "Build básica para Soma Prime" in p.boton_basica.text()
    p.mostrar_basica()
    huecos = p.basica.huecos
    assert huecos[0].mod.nombre_en == "Serration" and huecos[0].tienes  # leida en la coleccion
    assert huecos[1].mod.nombre_en == "Split Chamber" and huecos[1].tienes  # equipada
    assert not huecos[2].tienes
    assert not p.panel_basica.isHidden()
    # Las filas de la build basica abren la ficha, pero no cuentan como "leido".
    assert ids["Point Strike"] not in p.ids_listados()


def test_una_lectura_nueva_con_equipo_manda_sobre_el_elegido(pestana):
    p, ids = pestana
    p.elegir_equipo(ids["Excalibur"])
    p.mostrar_build(Build(equipo=_rec(ids, "Soma Prime"), equipados=[_rec(ids, "Serration")]))
    assert p.equipo_actual() == ids["Soma Prime"]


def test_basica_sin_equipo_lleva_al_buscador(pestana):
    p, _ids = pestana
    p.mostrar_basica()
    assert p.basica is None and "buscador" in p.estado.text()


def test_nombres_en_el_idioma_de_la_interfaz(pestana):
    p, ids = pestana
    # El lector pudo casar con otro idioma ("Valse de Mesa"): se ensena el de la interfaz.
    r = Reconocido("Valse", ids["Serration"], "Valse de Mesa", 95.0, (0, 0, 1, 1))
    p.mostrar_build(Build(equipados=[r]))
    assert any(t.startswith("Sierra") for t in p.textos_listados())
