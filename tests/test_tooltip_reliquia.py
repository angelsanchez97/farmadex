"""La tarjeta con la tabla de una reliquia: datos, sitio en pantalla y hover dentro de la app."""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QEnterEvent, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QTextBrowser, QVBoxLayout, QWidget  # noqa: E402

from farmadex.ui import tooltip_reliquia as TR  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


PROBS = {  # probabilidades reales de una reliquia por refinamiento
    "Rare": {"Intact": 2.0, "Exceptional": 4.0, "Flawless": 6.0, "Radiant": 10.0},
    "Uncommon": {"Intact": 11.0, "Exceptional": 13.0, "Flawless": 17.0, "Radiant": 20.0},
    "Common": {"Intact": 25.33, "Exceptional": 23.33, "Flawless": 20.0, "Radiant": 16.67},
}


def _reliquia(con, nombre="Lith S19 Relic", vaulted=0):
    cur = con.execute("INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, vaulted) VALUES (?, ?, ?, 'Relics', ?)",
                      ("R/" + nombre, nombre, "Reliquia " + nombre.removesuffix(" Relic"), vaulted))
    reliquia = cur.lastrowid
    padre = con.execute("INSERT INTO items (unique_name, nombre_en, nombre_es, categoria) VALUES "
                        "('/W/Ash', 'Ash Prime', 'Ash Prime', 'Warframes')").lastrowid
    piezas = [("Systems", "Sistemas", "Rare", 65, "ash_prime_systems"), ("Chassis", "Chasis", "Uncommon", 45, "ash_prime_chassis"),
              ("Forma Blueprint", "Plano de Forma", "Common", None, "")]
    for en, es, rareza, ducados, slug in piezas:
        item = con.execute(
            "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, padre_id, ducados, market_slug, comerciable) "
            "VALUES (?, ?, ?, 'Warframes', ?, ?, ?, ?)",
            ("/P/" + en + nombre, en, es, padre if slug else None, ducados, slug or None, 1 if slug else 0)).lastrowid
        for refinamiento, prob in PROBS[rareza].items():
            con.execute("INSERT INTO reliquia_recompensas VALUES (?, ?, ?, 'Uncommon', ?)", (reliquia, refinamiento, item, prob))
    con.commit()
    return reliquia


def test_datos_de_la_tarjeta_por_rareza_y_refinamiento(con):
    reliquia = _reliquia(con, vaulted=1)
    datos = TR.datos_reliquia(con, reliquia)
    assert datos["corto"] == "Lith S19" and datos["era"] == "Lith" and datos["vaulted"]
    assert [f["rareza"] for f in datos["filas"]] == ["Rare", "Uncommon", "Common"]  # la tabla dice Uncommon a todo
    oro = datos["filas"][0]
    assert oro["prob"] == PROBS["Rare"] and oro["ducados"] == 65 and oro["slug"] == "ash_prime_systems"
    assert "Ash Prime" in oro["nombre"]
    assert datos["filas"][2]["comerciable"] is False


def test_lo_que_no_es_reliquia_no_tiene_tarjeta(con):
    item = con.execute("INSERT INTO items (unique_name, nombre_en, categoria) VALUES ('/X', 'Ash Prime', 'Warframes')").lastrowid
    assert TR.datos_reliquia(con, item) is None
    assert TR.datos_reliquia(con, 999999) is None


def test_marca_lo_que_te_falta(con, tmp_path):
    import sqlite3

    reliquia = _reliquia(con)
    usuario = sqlite3.connect(tmp_path / "u.sqlite")
    usuario.execute("CREATE TABLE objetivos (nombre TEXT, cantidad_actual INT, cantidad_objetivo INT, "
                    "item_unique_name TEXT, completado_en TEXT)")
    usuario.execute("INSERT INTO objetivos VALUES ('Sistemas', 0, 1, '/P/SystemsLith S19 Relic', NULL)")
    datos = TR.datos_reliquia(con, reliquia, usuario)
    assert datos["filas"][0]["marca"]  # "Te falta"
    assert datos["filas"][0]["clave_marca"] == "falta"


@pytest.mark.parametrize("cursor", [(10, 10), (1900, 10), (10, 1070), (1900, 1070), (960, 540), (1500, 900)])
def test_la_tarjeta_no_tapa_el_cursor_ni_se_sale(cursor):
    ancho, alto = 620, 300
    x, y = TR.colocar((ancho, alto), cursor, (0, 0, 1920, 1080))
    assert 0 <= x and x + ancho <= 1920 and 0 <= y and y + alto <= 1080
    assert not (x <= cursor[0] <= x + ancho and y <= cursor[1] <= y + alto)


def test_con_sitio_va_abajo_a_la_derecha():
    assert TR.colocar((300, 200), (100, 100), (0, 0, 1920, 1080), separacion=20) == (120, 120)


def test_la_tarjeta_se_pinta_y_recibe_precios(qapp, con):
    reliquia = _reliquia(con)
    tarjeta = TR.TarjetaReliquia()
    assert tarjeta.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert tarjeta.windowFlags() & Qt.WindowTransparentForInput
    assert tarjeta.testAttribute(Qt.WA_ShowWithoutActivating)
    datos = TR.datos_reliquia(con, reliquia)
    datos["refinamiento"] = "Radiant"
    tarjeta.poner(datos)
    assert tarjeta.poner_precio("ash_prime_systems", 30)
    assert datos["filas"][0]["platino"] == 30
    assert not tarjeta.poner_precio("otra_cosa", 1)
    imagen = QImage(tarjeta.size(), QImage.Format_ARGB32)
    imagen.fill(0)
    p = QPainter(imagen)
    tarjeta.render(p, QPoint(0, 0))
    p.end()
    assert tarjeta.width() > 300 and tarjeta.height() > 150


_creados: list = []


def _entrar():
    """Un Enter de verdad (QEnterEvent): los widgets de Qt 6 lo leen como tal."""
    return QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5))


def _servicio(con):
    servicio = TR.ServicioTarjeta(indice=lambda: con)
    servicio.pedir_precio = lambda slug: {"ash_prime_systems": 42, "ash_prime_chassis": 7}.get(slug)
    return servicio


def _esperar(condicion, segundos=3.0):
    fin = time.monotonic() + segundos
    while not condicion() and time.monotonic() < fin:
        QApplication.processEvents()
        time.sleep(0.01)
    return condicion()


def test_el_servicio_ensena_la_tarjeta_y_le_llegan_los_precios(qapp, con):
    reliquia = _reliquia(con)
    servicio = _servicio(con)
    assert servicio.es_reliquia(reliquia)
    assert servicio.mostrar(reliquia, QPoint(200, 200), "Radiant")
    assert servicio.visible() and servicio.visible_para == reliquia
    assert _esperar(lambda: servicio.tarjeta.datos["filas"][0]["platino"] == 42)
    # Un segundo hover no vuelve a pedir el precio: sale de la cache.
    servicio.pedir_precio = lambda slug: pytest.fail("no deberia volver a pedirse")
    servicio.ocultar()
    servicio.mostrar(reliquia, QPoint(200, 200))
    assert servicio.tarjeta.datos["filas"][0]["platino"] == 42
    servicio.ocultar()
    assert not servicio.visible()
    servicio.cerrar()


def test_hover_en_un_enlace_de_reliquia_dentro_de_la_app(qapp, con):
    reliquia = _reliquia(con)
    otro = con.execute("INSERT INTO items (unique_name, nombre_en, categoria) VALUES ('/Y', 'Ash Prime', 'Warframes')").lastrowid
    servicio = _servicio(con)
    ayuda = TR.AyudaHoverApp(servicio, retardo_ms=20)
    ayuda.instalar()
    try:
        navegador = QTextBrowser()
        navegador.setHtml(f"<a href='item:{reliquia}'>Lith S19</a> <a href='item:{otro}'>Ash</a>")
        navegador.show()
        _creados.append(navegador)
        # Al entrar el raton se engancha a la senal de enlace resaltado del navegador.
        QApplication.sendEvent(navegador.viewport(), _entrar())
        assert navegador.property("_farmadex_hover_reliquia")
        navegador.highlighted.emit(f"item:{reliquia}")
        assert _esperar(servicio.visible)
        assert servicio.visible_para == reliquia
        navegador.highlighted.emit("")  # sale del enlace
        assert not servicio.visible()
        navegador.highlighted.emit(f"item:{otro}")  # no es una reliquia: nada
        assert not _esperar(servicio.visible, 0.2)
    finally:
        ayuda.quitar()
        servicio.ocultar()
        servicio.cerrar()
        for w in list(_creados):
            w.close()
        _creados.clear()


def test_hover_en_un_texto_marcado_sin_enlace(qapp, con):
    reliquia = _reliquia(con)
    servicio = _servicio(con)
    ayuda = TR.AyudaHoverApp(servicio, retardo_ms=20)
    ayuda.instalar()
    try:
        caja = QWidget()
        etiqueta = QLabel("Reliquia Lith S19", caja)
        QVBoxLayout(caja).addWidget(etiqueta)
        TR.marcar(caja, reliquia)  # marcado el padre: vale para lo que hay dentro
        caja.show()
        _creados.append(caja)
        QApplication.sendEvent(etiqueta, _entrar())
        assert _esperar(servicio.visible)
        QApplication.sendEvent(caja, QEvent(QEvent.WindowDeactivate))  # cambiar de ventana la quita
        assert not servicio.visible()
        TR.marcar(caja, None)
        QApplication.sendEvent(etiqueta, _entrar())
        assert not _esperar(servicio.visible, 0.2)
    finally:
        ayuda.quitar()
        servicio.ocultar()
        servicio.cerrar()
        for w in list(_creados):
            w.close()
        _creados.clear()


def test_etiqueta_con_enlaces_se_engancha_al_entrar(qapp, con):
    reliquia = _reliquia(con)
    servicio = _servicio(con)
    ayuda = TR.AyudaHoverApp(servicio, retardo_ms=20)
    ayuda.instalar()
    try:
        etiqueta = QLabel(f"<a href='item:{reliquia}'>Lith S19</a>")
        etiqueta.show()
        _creados.append(etiqueta)
        QApplication.sendEvent(etiqueta, _entrar())
        etiqueta.linkHovered.emit(f"item:{reliquia}")
        assert _esperar(servicio.visible)
        etiqueta.linkHovered.emit("")
        assert not servicio.visible()
    finally:
        ayuda.quitar()
        servicio.ocultar()
        servicio.cerrar()
        for w in list(_creados):
            w.close()
        _creados.clear()


def test_reliquia_de_ruta():
    assert TR.reliquia_de_ruta({"tipo": "reliquia", "reliquia": {"reliquia_id": 5}}) == 5
    assert TR.reliquia_de_ruta({"tipo": "mision", "reliquia": None}) is None
    assert TR.reliquia_de_ruta(None) is None


def test_valor_medio_al_abrirla():
    filas = [
        {"prob": {"Intact": 2.0, "Radiant": 10.0}, "ducados": 100, "comerciable": True, "slug": "a", "platino": 50},
        {"prob": {"Intact": 25.33, "Radiant": 16.67}, "ducados": None, "comerciable": False, "slug": "", "platino": None},
    ]
    platino, ducados = TR.valor_medio(filas, "Radiant")
    assert platino == pytest.approx(5.0) and ducados == pytest.approx(10.0)
    filas[0]["platino"] = None  # falta un precio: todavia no se sabe
    assert TR.valor_medio(filas, "Intact")[0] is None


def test_ajustes_de_la_tabla_en_el_juego(qapp, tmp_path, monkeypatch):
    """Ajustes > Reliquias: activada por defecto, modo automatico, la tecla solo vale en modo tecla."""
    import json

    from farmadex import config, idiomas
    from farmadex.ui.pestana_ajustes import PestanaAjustes

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    ajustes = PestanaAjustes()
    assert ajustes.hover_reliquia.isChecked()
    assert ajustes.hover_reliquia_modo.currentData() == "auto"
    assert not ajustes.hover_reliquia_tecla.isEnabled()
    ajustes.hover_reliquia.setChecked(False)
    ajustes.hover_reliquia_modo.setCurrentIndex(ajustes.hover_reliquia_modo.findData("tecla"))
    ajustes.hover_reliquia_tecla.setCurrentIndex(ajustes.hover_reliquia_tecla.findData("raton4"))
    assert ajustes.hover_reliquia_tecla.isEnabled()
    guardado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert guardado["hover_reliquia"] is False
    assert guardado["hover_reliquia_modo"] == "tecla" and guardado["hover_reliquia_tecla"] == "raton4"
    idiomas.cargar("en")
    ajustes.retraducir()
    assert ajustes.hover_reliquia_modo.itemText(1) == "Only while I hold a key"
    idiomas.cargar("es")
