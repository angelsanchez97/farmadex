"""Maximizar y restaurar la vista completa, como un programa normal de Windows.

Boton entre minimizar y la x, doble clic en la cabecera, arrastrar la maximizada la
restaura, se recuerda al cerrar y el modo juego nunca se maximiza. Sin pantalla.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import config, idiomas  # noqa: E402
from farmadex.ui import overlay  # noqa: E402
from farmadex.ui.estilo_c import ICONO  # noqa: E402

from test_minimizar import _preparar  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def ventana(app, tmp_path, monkeypatch):
    _preparar(tmp_path, monkeypatch)
    v = overlay.VentanaOverlay()
    v.show()
    yield v
    v.hilo_captura = None
    v._reloj_encima.stop()
    v.hide()
    idiomas.cargar("es")


def _clic(v, pos: QPoint, tipo=QEvent.MouseButtonPress, botones=Qt.LeftButton):
    global_ = v.mapToGlobal(pos)
    evento = QMouseEvent(tipo, QPointF(pos), QPointF(global_), Qt.LeftButton, botones, Qt.NoModifier)
    if tipo == QEvent.MouseButtonPress:
        v.mousePressEvent(evento)
    elif tipo == QEvent.MouseMove:
        v.mouseMoveEvent(evento)
    else:
        v.mouseReleaseEvent(evento)


def _hueco_cabecera(v) -> QPoint:
    barra = v.barra_cabecera
    return barra.mapTo(v, QPoint(barra.width() // 2, barra.height() // 2))


def test_doble_clic_puro():
    t0 = (1.0, QPoint(10, 10))
    assert overlay.es_doble_clic(t0, (1.3, QPoint(12, 11)), 0.5)
    assert not overlay.es_doble_clic(t0, (1.6, QPoint(10, 10)), 0.5)  # tarde
    assert not overlay.es_doble_clic(t0, (1.1, QPoint(40, 10)), 0.5)  # lejos


def test_el_boton_maximiza_y_restaura_y_cambia_de_icono(ventana):
    assert ventana.boton_maximizar.isVisibleTo(ventana)
    ventana.boton_maximizar.click()
    assert ventana.isMaximized()
    assert ventana.boton_maximizar.toolTip() == "Restaurar"
    assert ventana.boton_maximizar.glifo == ICONO["restaurar"]
    ventana.boton_maximizar.click()
    assert not ventana.isMaximized()
    assert ventana.boton_maximizar.toolTip() == "Maximizar"


def test_doble_clic_en_la_cabecera_maximiza_y_fuera_no(ventana):
    punto = _hueco_cabecera(ventana)
    _clic(ventana, punto)
    _clic(ventana, punto, QEvent.MouseButtonRelease, Qt.NoButton)
    _clic(ventana, punto)
    assert ventana.isMaximized()
    _clic(ventana, punto, QEvent.MouseButtonRelease, Qt.NoButton)
    _clic(ventana, punto)
    _clic(ventana, punto, QEvent.MouseButtonRelease, Qt.NoButton)
    _clic(ventana, punto)
    assert not ventana.isMaximized()
    # Un doble clic abajo, fuera de la cabecera, no maximiza nada.
    abajo = QPoint(ventana.width() // 2, ventana.height() - 20)
    _clic(ventana, abajo)
    _clic(ventana, abajo, QEvent.MouseButtonRelease, Qt.NoButton)
    _clic(ventana, abajo)
    assert not ventana.isMaximized()


def test_maximizada_no_tiene_bordes_de_redimensionar(ventana):
    ventana.alternar_maximizado()
    evento = QMouseEvent(QEvent.MouseMove, QPointF(2, 2), QPointF(2, 2), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    assert ventana._borde_bajo_cursor(evento) is None


def test_arrastrar_la_maximizada_la_restaura(ventana):
    ventana.resize(1000, 700)
    ventana.alternar_maximizado()
    assert ventana.isMaximized()
    punto = _hueco_cabecera(ventana)
    _clic(ventana, punto)
    assert ventana.isMaximized()  # un clic suelto no la mueve
    _clic(ventana, punto + QPoint(40, 30), QEvent.MouseMove, Qt.LeftButton)
    assert not ventana.isMaximized()
    _clic(ventana, punto, QEvent.MouseButtonRelease, Qt.NoButton)


def test_se_guarda_el_sitio_de_antes_y_que_estaba_maximizada(ventana):
    ventana.showNormal()
    ventana.setGeometry(100, 120, 1000, 700)
    normal = ventana.geometry()
    ventana.alternar_maximizado()
    ventana._guardar_geometria()
    assert ventana.config["overlay_maximizada"] is True
    assert ventana.config["overlay_geometria"] == [normal.x(), normal.y(), normal.width(), normal.height()]
    ventana.alternar_maximizado()
    assert ventana.config["overlay_maximizada"] is False


def test_el_modo_juego_nunca_se_maximiza_y_al_volver_si(ventana):
    ventana.alternar_maximizado()
    ventana.aplicar_modo("compacto")
    assert not ventana.isMaximized()
    assert not ventana.boton_maximizar.isVisibleTo(ventana)
    ventana.alternar_maximizado()  # desde el modo juego no hace nada
    assert not ventana.isMaximized()
    assert not (ventana._banderas_ventana() & Qt.WindowMaximizeButtonHint)
    ventana.aplicar_modo("completo")
    assert ventana.isMaximized()
    assert ventana.boton_maximizar.isVisibleTo(ventana)


def test_se_abre_maximizada_si_se_cerro_asi(app, tmp_path, monkeypatch):
    _preparar(tmp_path, monkeypatch)
    datos = dict(config.POR_DEFECTO, overlay_maximizada=True)
    import json

    (tmp_path / "config.json").write_text(json.dumps(datos), encoding="utf-8")
    config.cargar(recargar=True)
    v = overlay.VentanaOverlay()
    try:
        assert not v.isMaximized()
        v.mostrar()
        assert v.isMaximized()
    finally:
        v.hilo_captura = None
        v._reloj_encima.stop()
        v.hide()


def test_en_la_barra_de_tareas_lleva_la_pista_de_maximizar(ventana):
    assert ventana._banderas_ventana() & Qt.WindowMaximizeButtonHint


@pytest.mark.parametrize("ancho,alto", [(1920, 1080), (2560, 1440), (3840, 2160)])
def test_maximizada_el_contenido_ocupa_la_pantalla(ventana, ancho, alto):
    """A 1080p, 1440p y 4K el contenido se estira con la ventana (nada fijo a 1100 px)."""
    ventana.setMaximumSize(16777215, 16777215)
    ventana.resize(ancho, alto)
    QApplication.processEvents()
    assert ventana.marco.width() >= ancho - 2
    assert ventana.zona_secciones.width() >= ancho * 0.9
    assert ventana.zona_secciones.height() >= alto * 0.75
