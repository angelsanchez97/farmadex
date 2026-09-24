"""La ventana cuando los datos fallan al arrancar: con indice viejo se sigue trabajando."""

import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def ventana(app, con, tmp_path, monkeypatch):
    """VentanaOverlay sin hilos, con un indice vacio de verdad en disco y sin servicios."""
    from farmadex import config, tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: True)
    monkeypatch.setattr(indice, "conectar", lambda ruta=None: sqlite3.connect(tmp_path / "prueba.sqlite"))
    monkeypatch.setattr(indice, "leer_meta", lambda ruta=None: {})
    from farmadex.ui.overlay import VentanaOverlay

    idiomas.cargar("es")
    v = VentanaOverlay()
    arrancados = []
    for nombre in ("_arrancar_mundo", "_arrancar_captura", "_arrancar_comparador", "_arrancar_actualizador"):
        monkeypatch.setattr(v, nombre, lambda n=nombre: arrancados.append(n))
    v.arrancados = arrancados
    v.show()
    yield v
    v.hide()


def test_si_la_descarga_falla_pero_hay_indice_todo_sigue_funcionando(ventana):
    """Antes solo revivia el buscador: Objetivos, Perfil, Mundo y el OCR se quedaban muertos."""
    ventana._datos_listos(False, "sin red")
    assert "sin red" in ventana.estado.text()
    assert ventana.buscador.caja.isEnabled()
    assert ventana.objetivos.indice is not None
    assert ventana.perfil.indice is not None
    assert ventana.mundo.indice is not None
    assert ventana.arrancados == ["_arrancar_mundo", "_arrancar_captura", "_arrancar_comparador", "_arrancar_actualizador"]


def test_el_fallo_se_cuenta_en_una_frase_corta(ventana):
    """El 2026-09-24 WFCD quito i18n.json y la barra ensenaba la excepcion de httpx entera,
    con la URL de GitHub y un enlace a la documentacion de Mozilla."""
    ventana._datos_listos(False, "la fuente ha cambiado")
    assert ventana.estado.text() == (
        "No se pudieron actualizar los datos (la fuente ha cambiado); se sigue con los de antes"
    )


def test_con_datos_nuevos_se_hace_lo_mismo(ventana):
    ventana._datos_listos(True, "listo")
    assert ventana.estado.text() == "listo"
    assert ventana.objetivos.indice is not None and len(ventana.arrancados) == 4
