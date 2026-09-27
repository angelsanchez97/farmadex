"""Minimizar la ventana y su boton en la barra de tareas de Windows.

La ventana es sin marco y siempre encima: el boton de minimizar de la cabecera la
minimiza de verdad, el atajo, la bandeja y "otro Farmadex que se abre" la devuelven, y
en la vista completa sale en la barra de tareas con su icono (en el modo juego no, ni
las ventanas auxiliares). Sin pantalla (offscreen); el estilo Win32 real se comprueba
en un proceso aparte sin ensenar ninguna ventana.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.ui import overlay  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _preparar(tmp_path, monkeypatch):
    from farmadex import config, tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    # Nada de SetWindowPos/ShowWindow de verdad sobre el escritorio del usuario.
    monkeypatch.setattr(overlay, "poner_encima_sin_foco", lambda w: True)
    monkeypatch.setattr(overlay, "restaurar_sin_foco", lambda w: False)
    idiomas.cargar("es")


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


def _tipo(v) -> Qt.WindowType:
    return v.windowFlags() & Qt.WindowType_Mask


# -- el boton ------------------------------------------------------------------------


def test_el_boton_de_minimizar_va_justo_antes_de_la_x(ventana):
    botones = ventana._botones_ventana
    i_min = botones.indexOf(ventana.boton_minimizar)
    i_x = botones.indexOf(ventana.boton_cerrar)
    assert i_min >= 0 and i_x == i_min + 1
    assert ventana.boton_minimizar.isVisibleTo(ventana)
    tip = ventana.boton_minimizar.toolTip()
    assert "Ctrl+Alt+W" in tip and "barra de tareas" in tip


def test_en_el_modo_juego_tambien_esta_y_cabe(ventana):
    ventana.aplicar_modo("compacto")
    ventana.resize(overlay.ANCHO_MINIMO_COMPACTO, ventana.height())
    QApplication.processEvents()
    assert ventana.boton_minimizar.isVisibleTo(ventana)
    # En el modo juego no hay boton en la barra: el tooltip no lo promete.
    assert "barra de tareas" not in ventana.boton_minimizar.toolTip()
    # Cabe entero dentro de la cabecera, sin salirse por la derecha.
    derecha = ventana.boton_cerrar.mapTo(ventana, QPoint(ventana.boton_cerrar.width(), 0)).x()
    assert derecha <= ventana.width()
    assert ventana.boton_minimizar.geometry().right() < ventana.boton_cerrar.geometry().left()


def test_pulsar_el_boton_la_minimiza(ventana):
    ventana.boton_minimizar.click()
    assert ventana.isMinimized()
    assert ventana.isVisible()  # minimizada, no escondida: sigue en la barra de tareas


# -- volver a mostrarla ----------------------------------------------------------------


def test_el_atajo_y_la_bandeja_la_devuelven_si_esta_minimizada(ventana):
    """Ctrl+Alt+W y el clic en la bandeja llaman a `alternar`."""
    ventana.minimizar()
    ventana.alternar()
    assert ventana.isVisible() and not ventana.isMinimized()
    # Y a la siguiente, como siempre, la esconde.
    ventana.alternar()
    assert not ventana.isVisible()


def test_mostrar_la_restaura_para_la_bandeja_y_la_instancia_unica(ventana):
    """"Mostrar" de la bandeja y otro Farmadex que se abre llaman a `mostrar`."""
    ventana.minimizar()
    ventana.mostrar()
    assert not ventana.isMinimized() and ventana.isVisible()


def test_la_x_de_la_barra_con_la_ventana_minimizada_la_esconde_y_luego_vuelve_normal(ventana):
    ventana.minimizar()
    ventana.close()  # "Cerrar ventana" desde la barra de tareas: solo esconde
    assert not ventana.isVisible()
    ventana.mostrar()
    assert ventana.isVisible() and not ventana.isMinimized()


def test_minimizar_y_restaurar_conserva_el_sitio_y_el_tamano(ventana):
    ventana.setGeometry(QRect(20, 30, 700, 500))
    ventana.mostrar()  # la encaja en la pantalla (la de pruebas es pequena)
    antes = ventana.geometry()
    ventana.minimizar()
    ventana.mostrar()
    assert ventana.geometry().size() == antes.size()
    assert ventana.geometry().topLeft() == antes.topLeft()


def test_tras_restaurar_se_sigue_arrastrando_y_redimensionando(ventana):
    ventana.minimizar()
    ventana.mostrar()
    ventana.move(100, 100)
    pulsar = QMouseEvent(QEvent.MouseButtonPress, QPointF(300, 300), QPointF(400, 400),
                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    ventana.mousePressEvent(pulsar)
    mover = QMouseEvent(QEvent.MouseMove, QPointF(0, 0), QPointF(450, 460),
                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    ventana.mouseMoveEvent(mover)
    assert ventana.pos() == QPoint(150, 160)
    ventana.mouseReleaseEvent(pulsar)
    esquina = QMouseEvent(QEvent.MouseButtonPress, QPointF(ventana.width() - 1, ventana.height() - 1),
                          QPointF(0, 0), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    assert ventana._redimensionar_iniciar(esquina)
    ventana._redimensionar_soltar()


def test_no_guarda_como_sitio_el_aparcamiento_de_las_minimizadas(ventana, monkeypatch):
    from farmadex.config import cargar

    ventana.setGeometry(QRect(200, 210, 1000, 700))
    ventana._guardar_geometria()
    monkeypatch.setattr(ventana, "isMinimized", lambda: True)
    monkeypatch.setattr(ventana, "geometry", lambda: QRect(-32000, -32000, 160, 28))
    ventana._guardar_geometria()
    assert cargar()["overlay_geometria"][:2] == [200, 210]


def test_minimizada_no_se_refuerza_encima_y_al_volver_si(ventana):
    ventana.aplicar_modo("compacto")
    assert ventana._reloj_encima.isActive()
    ventana.minimizar()
    assert not ventana._reloj_encima.isActive()
    ventana.mostrar()
    assert ventana._reloj_encima.isActive()


def test_minimizada_el_mundo_va_al_ritmo_de_escondida(ventana):
    # `_cadencia_mundo` va en cola hasta el hilo de ServicioMundo (ver
    # ServicioMundo.cadencia): minimizar()/mostrar() la piden por senal, no llamando a
    # `servicio_mundo.cadencia()` a pelo, asi que aqui basta con escuchar la senal.
    ritmos = []
    ventana.servicio_mundo = SimpleNamespace(cadencia=lambda visible: None)
    ventana._cadencia_mundo.connect(ritmos.append)
    try:
        ventana.minimizar()
        ventana.mostrar()
    finally:
        ventana.servicio_mundo = None
    assert False in ritmos and ritmos[-1] is True


def test_en_pantalla_completa_exclusiva_se_restaura_sin_activarla(ventana, monkeypatch):
    """Con el juego en exclusiva no se le puede quitar el foco: se restaura sin activar."""
    from farmadex.captura import pantalla

    pedidas = []
    monkeypatch.setattr(ventana, "_refrescar_modo_pantalla", lambda: pantalla.MODO_EXCLUSIVO)
    monkeypatch.setattr(ventana, "_pantalla_libre", lambda: ventana.frameGeometry())
    monkeypatch.setattr(overlay, "restaurar_sin_foco", lambda w: pedidas.append(w) or False)
    monkeypatch.setattr(ventana, "activateWindow", lambda: pytest.fail("no debe activarse"))
    ventana.minimizar()
    ventana.mostrar()
    assert pedidas == [ventana]
    assert ventana.testAttribute(Qt.WA_ShowWithoutActivating)
    assert not ventana.isMinimized()


# -- barra de tareas -------------------------------------------------------------------


def test_la_vista_completa_sale_en_la_barra_de_tareas_con_icono(ventana):
    assert _tipo(ventana) == Qt.Window  # no Tool: Windows le da boton en la barra
    banderas = ventana.windowFlags()
    assert banderas & Qt.FramelessWindowHint
    assert banderas & Qt.WindowStaysOnTopHint
    # Sin esto Windows no la minimiza al pulsar su boton en la barra.
    assert banderas & Qt.WindowMinimizeButtonHint
    assert not ventana.windowIcon().isNull()


def test_el_modo_juego_no_sale_en_la_barra(ventana):
    ventana.aplicar_modo("compacto")
    assert _tipo(ventana) == Qt.Tool
    assert ventana.windowFlags() & Qt.FramelessWindowHint
    assert ventana.isVisible()
    ventana.aplicar_modo("completo")
    assert _tipo(ventana) == Qt.Window
    assert ventana.isVisible()


def test_la_chincheta_sigue_funcionando(ventana):
    ventana.aplicar_modo("compacto")
    ventana.boton_fijar.setChecked(False)
    assert not (ventana.windowFlags() & Qt.WindowStaysOnTopHint)
    assert _tipo(ventana) == Qt.Tool and ventana.isVisible()
    ventana.boton_fijar.setChecked(True)
    assert ventana.windowFlags() & Qt.WindowStaysOnTopHint
    assert ventana._reloj_encima.isActive()


def test_las_banderas_no_se_vuelven_a_poner_si_no_cambian(ventana, monkeypatch):
    """Cambiarlas esconde y vuelve a crear la ventana: no puede pasar en cada `mostrar`."""
    puestas = []
    original = ventana.setWindowFlags
    monkeypatch.setattr(ventana, "setWindowFlags", lambda b: puestas.append(b) or original(b))
    ventana.mostrar()
    ventana._aplicar_encima()
    ventana.minimizar()
    ventana.mostrar()
    assert puestas == []


def test_la_opcion_de_ajustes_la_quita_y_la_pone_en_caliente(ventana):
    from farmadex.config import cargar

    assert ventana.ajustes.barra_tareas.isChecked()  # activada por defecto
    ventana.ajustes.barra_tareas.setChecked(False)
    assert _tipo(ventana) == Qt.Tool and ventana.isVisible()
    assert cargar()["mostrar_barra_tareas"] is False
    assert "barra de tareas" not in ventana.boton_minimizar.toolTip()
    ventana.ajustes.barra_tareas.setChecked(True)
    assert _tipo(ventana) == Qt.Window and ventana.isVisible()
    assert cargar()["mostrar_barra_tareas"] is True


def test_sin_barra_de_tareas_se_recuerda_al_abrir(app, tmp_path, monkeypatch):
    from farmadex.config import cargar, guardar

    _preparar(tmp_path, monkeypatch)
    datos = cargar()
    datos["mostrar_barra_tareas"] = False
    guardar(datos)
    v = overlay.VentanaOverlay()
    try:
        assert _tipo(v) == Qt.Tool
        assert not v.ajustes.barra_tareas.isChecked()
        # Minimizar sigue funcionando: vuelve con el atajo o la bandeja.
        v.show()
        v.minimizar()
        assert v.isMinimized()
        v.alternar()
        assert v.isVisible() and not v.isMinimized()
    finally:
        v._reloj_encima.stop()
        v.hide()


def test_las_ventanas_auxiliares_no_salen_en_la_barra(ventana):
    assert _tipo(ventana.etiquetas_pequenas) == Qt.Tool
    assert _tipo(ventana.panel_recompensas) == Qt.Tool
    from farmadex.ui.tooltip_reliquia import TarjetaReliquia

    assert _tipo(TarjetaReliquia()) == Qt.ToolTip
    ventana._mostrar_aviso_actualizando("1.0.0")
    aviso = ventana._aviso_actualizando
    try:
        assert aviso is not None and _tipo(aviso) == Qt.Tool
    finally:
        aviso.close()


# -- estilo Win32 de verdad (sin ensenar ninguna ventana) -------------------------------

_SCRIPT_ESTILO = r"""
import ctypes, sys
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QWidget
from farmadex.ui import overlay

app = QApplication([])
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_MINIMIZEBOX, WS_CAPTION, WS_THICKFRAME = 0x00020000, 0x00C00000, 0x00040000
WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x00000080, 0x00000008
user32 = ctypes.WinDLL("user32")
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
for en_barra in (True, False):
    falsa = SimpleNamespace(_quiere_encima=lambda: True, _en_barra=lambda e=en_barra: e)
    w = QWidget(None, overlay.VentanaOverlay._banderas_ventana(falsa))
    hwnd = ctypes.c_void_p(int(w.winId()))  # crea la ventana nativa SIN ensenarla
    estilo = user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    assert not w.isVisible()
    assert not estilo & (WS_CAPTION | WS_THICKFRAME), hex(estilo)  # sigue sin marco
    if en_barra:
        assert estilo & WS_MINIMIZEBOX, hex(estilo)
        assert not ex & WS_EX_TOOLWINDOW, hex(ex)
    else:
        assert ex & WS_EX_TOOLWINDOW, hex(ex)
    w.deleteLater()
print("ESTILO_OK")
"""


@pytest.mark.skipif(sys.platform != "win32", reason="solo Windows")
def test_estilo_win32_boton_en_la_barra_y_minimizable():
    raiz = Path(__file__).resolve().parents[1]
    entorno = {**os.environ, "QT_QPA_PLATFORM": "windows",
               "PYTHONPATH": str(raiz / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    resultado = subprocess.run([sys.executable, "-c", _SCRIPT_ESTILO], capture_output=True, text=True,
                               env=entorno, timeout=120, cwd=str(raiz))
    assert "ESTILO_OK" in resultado.stdout, resultado.stdout[-2000:] + resultado.stderr[-3000:]
