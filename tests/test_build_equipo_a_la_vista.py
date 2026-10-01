"""Tras leer la pantalla de mejoras, el equipo y "Builds en Overframe" estan a la vista.

Fallo de la 0.6.9: con la pestana Build parada en "Aumentos y sindicatos", una lectura nueva
(por atajo o sola) dejaba delante el diccionario: ni nombre del equipo ni boton de Overframe.

Las lineas de `fixtures/mejoras_es_lineas.json` son lo que el OCR lee en dos capturas reales
de la pantalla de mejoras en espanol (1080p y 1440p), y en su franja de arriba; aqui no se pasa OCR ni se abre nada.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.captura import builds as B  # noqa: E402
from farmadex.captura.ocr import Leido  # noqa: E402

from conftest import FIXTURES  # noqa: E402
from test_captura import _insertar  # noqa: E402

LINEAS = json.loads((FIXTURES / "mejoras_es_lineas.json").read_text(encoding="utf-8"))
ITEMS = [
    ("/w/RhinoPrime", "Rhino Prime", "Rhino Prime", "Warframes"),
    ("/x/Regulators", "Regulators Prime", "Reguladoras Prime", "Misc"),
    ("/m/PrimedFlow", "Primed Flow", "Flujo Prime", "Mods"),
    ("/m/PrimedContinuity", "Primed Continuity", "Continuidad Prime", "Mods"),
    ("/m/Suppress", "Suppress", "Suprimir", "Mods"),
    ("/m/PrimedConvulsion", "Primed Convulsion", "Convulsión Prime", "Mods"),
]
CASOS = {"es_1080_rhino": "RHINO PRIME", "es_1440_reguladoras": "REGULADORAS PRIME"}
MEDIDAS = [(760, 520), (1100, 700), (1280, 800), (1920, 1080), (2560, 1440), None]  # None = maximizada


class MotorFalso:
    """Devuelve las lineas ya leidas de una captura real."""

    def __init__(self, caso: str):
        self.lineas = [Leido(*fila) for fila in LINEAS[caso]["lineas"]]
        # La franja de la cabecera releida sola (el rotulo del video tapa parte de "MEJORAS").
        self.cabecera = [Leido(*fila) for fila in LINEAS[caso]["cabecera"]]
        self.tiempos = {}

    def leer_tira(self, _imagen, alto_deteccion=None):
        return list(self.lineas)

    def leer(self, _franja):
        return list(self.cabecera)


def _imagen(caso: str):
    return np.zeros((LINEAS[caso]["alto"], LINEAS[caso]["ancho"], 3), np.uint8)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def ventana(app, con, tmp_path, monkeypatch):
    from farmadex import config, tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db

    idiomas.cargar("es")
    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    from farmadex.ui.overlay import VentanaOverlay

    _insertar(con, [(u, en, es, cat, None, None) for u, en, es, cat in ITEMS])
    con.execute("UPDATE items SET tipo = 'Exalted Weapon' WHERE unique_name = '/x/Regulators'")
    con.commit()
    v = VentanaOverlay()
    v.builds.conectar_indice(con)
    v.con_prueba = con
    yield v
    v.hide()


def _leer(ventana, caso: str, motor: MotorFalso | None = None) -> B.Build:
    con = ventana.con_prueba
    return B.leer_build(_imagen(caso), motor or MotorFalso(caso), B.crear_casador(con),
                        dict(con.execute("SELECT id, categoria FROM items")))


def _bombear(app, veces: int = 6) -> None:
    for _ in range(veces):
        app.processEvents()


def _a_la_vista(ventana, widget) -> bool:
    """Visible y entero dentro de lo que ensena la ventana (tras llevarlo a la vista)."""
    areas = [a for a in ventana.builds.findChildren(QScrollArea)
             if a.widget() is not None and a.widget().isAncestorOf(widget)]
    if areas:
        areas[0].ensureWidgetVisible(widget, 0, 0)
        QApplication.processEvents()
    if not widget.isVisible() or widget.visibleRegion().isEmpty():
        return False
    return widget.visibleRegion().boundingRect().width() >= min(widget.width(), widget.sizeHint().width()) - 1


@pytest.mark.parametrize("sola", [False, True], ids=["atajo", "sola"])
@pytest.mark.parametrize("caso", list(CASOS))
def test_equipo_y_overframe_a_la_vista_tras_leer(app, ventana, caso, sola):
    p = ventana.builds
    ventana.show()
    ventana.ir_a("herramientas/build")
    p.ver("aumentos")  # el jugador estuvo mirando el diccionario de aumentos
    _bombear(app)
    build = _leer(ventana, caso)
    assert build.equipo is not None, "la cabecera de la captura real trae el equipo"
    ventana._build_sola = sola
    ventana._build_leida(build)
    if sola:  # leida sola no abre la ventana: el jugador va luego a Herramientas > Build
        ventana.ir_a("herramientas/build")
    for medida in MEDIDAS:
        if medida is None:
            ventana.showMaximized()
        else:
            ventana.showNormal()
            ventana.resize(*medida)
        _bombear(app)
        donde = f"{caso} {'sola' if sola else 'atajo'} {medida or 'maximizada'}"
        assert p.pila.currentIndex() == 0, f"{donde}: se queda delante el diccionario de aumentos"
        assert p.nombre_equipo.texto_completo().upper() == CASOS[caso], donde
        assert _a_la_vista(ventana, p.nombre_equipo), f"{donde}: no se ve el nombre del equipo"
        assert p.boton_overframe.text().strip(), f"{donde}: el boton de Overframe no tiene texto"
        assert _a_la_vista(ventana, p.boton_overframe), f"{donde}: no se ve el boton de Overframe"
        if caso == "es_1080_rhino":  # las armas exaltadas no tienen pagina de builds propia
            assert p.url_overframe(), f"{donde}: sin direccion de Overframe para el equipo leido"
        assert _a_la_vista(ventana, p.boton_ficha) and _a_la_vista(ventana, p.boton_basica), donde
        assert _a_la_vista(ventana, p.selector), donde


def test_sin_equipo_se_dice_y_overframe_sigue_ahi(app, ventana):
    """Cabecera tapada: no se inventa el nombre, se dice y se ofrece elegirlo a mano."""
    p = ventana.builds
    ventana.show()
    ventana.ir_a("herramientas/build")
    p.ver("aumentos")
    caso = "es_1080_rhino"
    motor = MotorFalso(caso)
    motor.lineas = [l for l in motor.lineas if l.y > LINEAS[caso]["alto"] * 0.2]  # sin la cabecera
    motor.cabecera = []
    build = _leer(ventana, caso, motor)
    assert build.equipo is None and not build.vacia
    ventana._build_leida(build)
    _bombear(app)
    assert p.pila.currentIndex() == 0
    assert not p.nombre_equipo.isVisible()
    assert "elígelo a mano" in p.estado.texto_completo()
    assert _a_la_vista(ventana, p.boton_overframe) and p.boton_overframe.text().strip()
    assert _a_la_vista(ventana, p.selector)
    equipo = ventana.con_prueba.execute("SELECT id FROM items WHERE nombre_en = 'Rhino Prime'").fetchone()[0]
    p.elegir_equipo(equipo)
    _bombear(app)
    assert _a_la_vista(ventana, p.nombre_equipo) and p.url_overframe()
