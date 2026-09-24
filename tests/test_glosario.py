"""Glosario al pasar el raton y busqueda sin resultados (sin ficha fantasma)."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.ui import glosario  # noqa: E402

CATALOGOS = sorted(idiomas.dir_catalogos().glob("*.json"))


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("ruta", CATALOGOS, ids=lambda r: r.stem)
def test_cada_termino_esta_traducido(ruta):
    catalogo = json.loads(ruta.read_text(encoding="utf-8"))
    faltan = [
        clave for clave, (titulo, explicacion) in glosario.TERMINOS.items()
        if titulo not in catalogo or explicacion not in catalogo
    ]
    assert not faltan, f"terminos sin traducir en {ruta.stem}.json: {faltan}"


def test_el_texto_lleva_titulo_y_explicacion_en_el_idioma(app):
    idiomas.cargar("es")
    texto = glosario.texto("boveda")
    assert "<b>Boveda</b>" in texto and "otro jugador" in texto
    idiomas.cargar("en")
    assert "<b>Vault</b>" in glosario.texto("boveda")
    idiomas.cargar("es")
    assert glosario.texto("no-existe") == ""


def test_el_enlace_solo_sirve_para_el_tooltip():
    enlace = glosario.enlace("rotacion", "Rotacion C", "#abc")
    assert "href='glosa:rotacion'" in enlace and "text-decoration:none" in enlace
    assert glosario.es_glosa("glosa:era") and not glosario.es_glosa("item:3")


@pytest.fixture()
def buscador(app, indice_poblado, tmp_path, monkeypatch):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_buscador import PestanaBuscador

    idiomas.cargar("es")
    con, _, _ = indice_poblado
    b = PestanaBuscador()
    b.con = con
    yield b
    idiomas.cargar("es")


def _id(con, nombre_en):
    return con.execute("SELECT id FROM items WHERE nombre_en = ?", (nombre_en,)).fetchone()[0]


def test_la_ficha_lleva_los_terminos_del_glosario(buscador):
    buscador.abrir(_id(buscador.con, "Axi A7 Relic"))
    html = buscador.ficha.toHtml()
    # La ficha de una reliquia explica reliquia, era, boveda y refinamiento al pasar el raton.
    for clave in ("reliquia", "era", "boveda", "refinamiento"):
        assert f"glosa:{clave}" in html, clave


def test_el_tooltip_sale_por_el_evento_de_la_ficha(buscador, monkeypatch):
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QToolTip

    mostrados = []
    monkeypatch.setattr(QToolTip, "showText", lambda pos, texto, *a: mostrados.append(texto))
    monkeypatch.setattr(buscador.ficha, "anchorAt", lambda pos: "glosa:era")
    evento = QHelpEvent(QEvent.ToolTip, QPoint(5, 5), QPoint(5, 5))
    assert buscador.ficha.event(evento)
    assert mostrados and "<b>Era</b>" in mostrados[0]


def test_sin_resultados_no_queda_la_ficha_anterior(buscador):
    buscador.caja.setText("ash prime")
    buscador._temporizador.stop()
    buscador._buscar()
    assert buscador._actual is not None and buscador.boton_objetivo.isEnabled()

    buscador.caja.setText("como consigo rhino")
    buscador._temporizador.stop()
    buscador._buscar()
    assert buscador.lista.count() == 0
    assert buscador._actual is None and buscador._datos_actuales is None
    assert not buscador.boton_objetivo.isEnabled() and not buscador.boton_set.isEnabled()
    texto = buscador.ficha.toPlainText()
    assert "No he encontrado nada para «como consigo rhino»" in texto
    assert "no por preguntas" in texto


def test_la_muletilla_de_pregunta_no_estorba(buscador):
    # "como consigo ash" busca "ash": sale Ash Prime directamente, sin sugerencias.
    buscador.caja.setText("como consigo ash")
    buscador._temporizador.stop()
    buscador._buscar()
    assert buscador._actual == _id(buscador.con, "Ash Prime")


def test_sugiere_lo_parecido_palabra_a_palabra(buscador):
    buscador.caja.setText("dame ash ya")
    buscador._temporizador.stop()
    buscador._buscar()
    nombres = [r["nombre_en"] for r in buscador.sugerencias("dame ash ya")]
    assert "Ash Prime" in nombres
    assert "Quiza buscabas" in buscador.ficha.toPlainText()
    # Pinchar una sugerencia abre su ficha.
    from PySide6.QtCore import QUrl

    buscador._enlace(QUrl(f"item:{_id(buscador.con, 'Ash Prime')}"))
    assert buscador._actual == _id(buscador.con, "Ash Prime")
    assert buscador._sin_resultados is None


def test_el_aviso_de_sin_resultados_cambia_de_idioma(buscador):
    buscador.caja.setText("zzzz")
    buscador._temporizador.stop()
    buscador._buscar()
    idiomas.cargar("en")
    buscador.retraducir()
    assert "Nothing found for" in buscador.ficha.toPlainText()


def test_borrar_la_caja_limpia_la_ficha(buscador):
    buscador.abrir(_id(buscador.con, "Ash Prime"))
    buscador.caja.setText("")
    buscador._temporizador.stop()
    buscador._buscar()
    assert buscador._actual is None and buscador.ficha.toPlainText() == ""


def test_el_glosario_en_mundo_y_en_el_filtro(app):
    from farmadex.ui.pestana_buscador import PestanaBuscador
    from farmadex.ui.pestana_mundo import PestanaMundo

    idiomas.cargar("es")
    mundo = PestanaMundo()
    assert "Lith, Meso" in mundo.filtro_era.toolTip()
    assert "<b>Camino de Acero</b>" in mundo.filtro_modo.toolTip()
    buscador = PestanaBuscador()
    assert "<b>Boveda</b>" in buscador.ocultar_vaulted.toolTip()
