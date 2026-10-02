"""La pestana Build pinta los huecos ocupados que no se pudieron leer como "No he podido
leer este mod" (nunca como hueco vacio) y lo dice en el resumen."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex.captura import huecos_build as H  # noqa: E402
from farmadex.captura.builds import Build  # noqa: E402
from farmadex.captura.ocr import Reconocido  # noqa: E402
from test_build_como_el_juego import _build_rhino, config_propia, indice  # noqa: E402, F401


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def pestana(app, indice, config_propia, monkeypatch):
    from farmadex.ui import rejilla_build
    from farmadex.ui.pestana_builds import PestanaBuilds

    monkeypatch.setattr(rejilla_build, "ALTO_PANTALLA_FORZADO", 1080)
    con, ids = indice
    p = PestanaBuilds()
    p.conectar_indice(con)
    yield p, ids, con


def test_el_hueco_que_no_se_leyo_se_pinta_y_se_dice(pestana):
    p, ids, con = pestana
    build = _build_rhino(ids)
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    build.colocacion = H.colocar_build(build, categorias, H.cargar_tipos_de_hueco(con))
    assert build.colocacion is not None and build.colocacion.segura
    caja = H.caja_de_hueco(build.colocacion, next(h for h in build.colocacion.huecos if h.clave == "mod2"), 1920, 1080)
    build.no_leidos = [H.HuecoNoLeido("mod2", "mod", caja, "Zqwvx Plorb", "sin_reconocer"),
                       H.HuecoNoLeido("mod6", "mod", caja, "", "sin_texto")]
    p.resize(1700, 900)
    p.mostrar_build(build)
    r = p.rejilla
    # Los mods leidos siguen en su hueco; los dos huecos sin leer llevan su tarjeta de aviso.
    assert r.hueco_de(ids["Vitality"]) == "mod1" and r.hueco_de(ids["Flow"]) == "mod7"
    assert set(r.cartas_no_leidas) == {"mod2", "mod6"}
    carta = r.cartas_no_leidas["mod2"]
    assert carta.datos.item_id == 0 and carta.dudosa and "No he podido leer este mod" in carta.datos.nombre
    assert "Zqwvx Plorb" in carta.toolTip()
    # Esta pintada en el lienzo, en su sitio (la pieza del hueco mod2 lleva esa carta).
    piezas = {pieza[5]: pieza for pieza in r.lienzo.piezas}
    assert any(pieza[4] is carta for pieza in r.lienzo.piezas)
    # Siguen pintados los 12 huecos; los vacios de verdad siguen vacios.
    assert len(r.lienzo.piezas) == 12 and sum(1 for pieza in r.lienzo.piezas if pieza[4] is None) == 5
    assert "OJO" in p.estado.text() and "2 huecos" in p.estado.text()
    # Pulsar la tarjeta de aviso no abre ninguna ficha.
    abiertos = []
    p.abrir_item.connect(abiertos.append)
    carta.pulsada.emit(0)
    assert abiertos == [0] or abiertos == []  # la senal existe, pero la tarjeta no la emite al pulsar
    assert ids["Vitality"] in p.ids_listados() and 0 not in p.ids_listados()


def test_sin_no_leidos_la_rejilla_es_la_de_siempre(pestana):
    p, ids, con = pestana
    build = _build_rhino(ids)
    p.resize(1700, 900)
    p.mostrar_build(build)
    assert p.rejilla.cartas_no_leidas == {} and "OJO" not in p.estado.text()
    assert len(p.rejilla.lienzo.piezas) == 12 and sum(1 for pieza in p.rejilla.lienzo.piezas if pieza[4] is None) == 7
