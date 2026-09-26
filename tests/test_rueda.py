"""La rueda del raton no cambia desplegables ni numeros al pasar por encima.

Caso del informe del tester: bajando por Ajustes con la rueda, al pasar por encima
de "Ritmo del juego" la rueda cambiaba el valor en vez de mover la pagina.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from farmadex.ui import rueda  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def pagina(qapp):
    """Una pagina larga con barra de desplazamiento y un control de cada tipo."""
    rueda.instalar(qapp)
    area = QScrollArea()
    dentro = QWidget()
    caja = QVBoxLayout(dentro)
    combo = QComboBox()
    combo.addItems(["Tranquilo", "Normal", "Rapido"])
    combo.setCurrentIndex(1)
    numero = QSpinBox()
    numero.setRange(0, 100)
    numero.setValue(50)
    deslizador = QSlider(Qt.Horizontal)
    deslizador.setRange(0, 100)
    deslizador.setValue(50)
    for w in (combo, numero, deslizador):
        caja.addWidget(w)
    caja.addSpacing(3000)
    area.setWidget(dentro)
    area.setWidgetResizable(True)
    area.resize(300, 200)
    area.show()
    qapp.processEvents()
    yield area, combo, numero, deslizador
    area.hide()
    area.deleteLater()
    rueda.desinstalar(qapp)


def _rueda(widget, hacia_abajo=True):
    paso = -120 if hacia_abajo else 120
    evento = QWheelEvent(
        QPointF(5, 5), QPointF(widget.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, paso),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    QApplication.sendEvent(widget, evento)


def test_sin_foco_la_rueda_mueve_la_pagina_y_no_el_desplegable(pagina):
    area, combo, _, _ = pagina
    barra = area.verticalScrollBar()
    assert barra.value() == 0
    _rueda(combo)
    assert combo.currentIndex() == 1
    assert barra.value() > 0  # la pagina si se ha movido


def test_sin_foco_tampoco_cambian_numeros_ni_deslizadores(pagina):
    area, _, numero, deslizador = pagina
    _rueda(numero)
    _rueda(deslizador)
    assert numero.value() == 50 and deslizador.value() == 50
    assert area.verticalScrollBar().value() > 0


def test_un_numero_con_foco_si_responde(pagina, monkeypatch):
    _, _, numero, _ = pagina
    # Foco "de mentira": en la plataforma sin pantalla no hay ventana activa.
    monkeypatch.setattr(numero, "hasFocus", lambda: True)
    assert rueda.rueda_permitida(numero)


def test_un_desplegable_cerrado_nunca_cambia_con_la_rueda(pagina, monkeypatch):
    _, combo, _, _ = pagina
    monkeypatch.setattr(combo, "hasFocus", lambda: True)
    assert not rueda.rueda_permitida(combo)


def test_la_rueda_ya_no_les_da_el_foco(pagina):
    _, combo, numero, deslizador = pagina
    for w in (combo, numero, deslizador):
        assert w.focusPolicy() != Qt.WheelFocus


def test_las_barras_de_desplazamiento_no_se_tocan(pagina):
    area, _, _, _ = pagina
    barra = area.verticalScrollBar()
    assert rueda._control_de(barra) is None
    _rueda(barra)
    assert barra.value() > 0


def test_un_control_puede_quedar_libre(pagina):
    _, _, _, deslizador = pagina
    deslizador.setProperty(rueda.PROPIEDAD_LIBRE, True)
    assert rueda._control_de(deslizador) is None
