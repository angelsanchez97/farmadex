"""Vista compacta para el directo: alternar, recordar el modo y la geometria de cada uno."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.ui import vista_compacta  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def ventana(app, tmp_path, monkeypatch):
    """Una VentanaOverlay sin hilos, sin indice y con su configuracion en una carpeta temporal."""
    from farmadex import config, tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    from farmadex.ui.overlay import VentanaOverlay

    idiomas.cargar("es")
    v = VentanaOverlay()
    v.show()
    yield v
    v.hide()
    idiomas.cargar("es")


def test_nace_completa_y_alterna_a_compacta(ventana):
    from farmadex.config import cargar

    assert ventana.modo == "completo"
    assert ventana.pestanas.isVisibleTo(ventana) and not ventana.compacta.isVisibleTo(ventana)
    assert ventana.boton_modo.text() == "Compacta"

    ventana.alternar_modo()
    assert ventana.modo == "compacto"
    assert ventana.compacta.isVisibleTo(ventana) and not ventana.pestanas.isVisibleTo(ventana)
    assert ventana.height() == vista_compacta.ALTO and ventana.width() == vista_compacta.ANCHO
    assert ventana.boton_modo.text() == "Completa"
    assert cargar()["overlay_modo"] == "compacto"


def test_cada_modo_recuerda_su_posicion_y_tamano(ventana):
    from farmadex.config import cargar

    ventana.setGeometry(100, 100, 1100, 650)
    ventana.alternar_modo()  # a compacto: guarda la geometria de la completa
    ventana.move(300, 40)
    ventana.alternar_modo()  # vuelve a completa: recupera 100,100 1100x650
    g = ventana.geometry()
    assert (g.x(), g.y(), g.width(), g.height()) == (100, 100, 1100, 650)
    guardado = cargar()
    assert guardado["overlay_geometria_compacto"][:2] == [300, 40]
    assert guardado["overlay_geometria"] == [100, 100, 1100, 650]
    ventana.alternar_modo()
    assert (ventana.x(), ventana.y()) == (300, 40)


def test_el_modo_guardado_se_aplica_al_arrancar(app, tmp_path, monkeypatch):
    from farmadex import config, tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    cfg = config.cargar()
    cfg["overlay_modo"] = "compacto"
    cfg["overlay_geometria_compacto"] = [50, 60, 600, 250]
    config.guardar(cfg)
    from farmadex.ui.overlay import VentanaOverlay

    v = VentanaOverlay()
    assert v.modo == "compacto"
    assert (v.x(), v.y(), v.width(), v.height()) == (50, 60, 600, 250)


def test_el_atajo_y_el_idioma(ventana):
    from farmadex.ui.overlay import ATAJO_MODO

    assert ATAJO_MODO in ventana.boton_modo.toolTip()
    ventana.cambiar_idioma("en")
    assert ventana.boton_modo.text() == "Compact"
    assert "Enter" in ventana.compacta.pie.text()


def test_enter_en_la_compacta_abre_la_ficha_completa(ventana):
    ventana.alternar_modo()
    recibidos = []
    ventana.buscador.abrir = lambda item_id, recordar=True: recibidos.append(item_id)
    ventana.compacta._datos = {"item": {"id": 7}}
    evento = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    QApplication.sendEvent(ventana.compacta.caja, evento)
    assert recibidos == [7]
    assert ventana.modo == "completo"
    assert ventana.pestanas.currentWidget() is ventana.buscador


def test_sin_indice_la_compacta_no_rompe(ventana):
    ventana.alternar_modo()
    ventana.compacta.caja.setText("ash prime")
    assert "Escribe" in ventana.compacta.resumen.text()
