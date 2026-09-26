"""La ventana sin marco se mueve y se redimensiona como una normal, y la compacta se
puede fijar encima del juego (chincheta que se recuerda).

Sin raton de verdad: se llama a los manejadores con eventos construidos a mano. En la
plataforma sin pantalla `startSystemMove`/`startSystemResize` no existen (devuelven
False) y la ventana cae al movimiento a mano; el camino nativo se comprueba con un
`windowHandle` falso.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.captura.cursor import TurnoLecturas  # noqa: E402
from farmadex.ui import overlay  # noqa: E402


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
    # Nada de SetWindowPos de verdad sobre el escritorio del usuario.
    monkeypatch.setattr(overlay, "poner_encima_sin_foco", lambda w: True)

    idiomas.cargar("es")
    v = overlay.VentanaOverlay()
    v.show()
    yield v
    v.hilo_captura = None
    v._reloj_encima.stop()
    v.hide()
    idiomas.cargar("es")


def _pulsar(x, y, boton=Qt.LeftButton, tipo=QEvent.MouseButtonPress, global_=None):
    g = QPointF(global_ if global_ is not None else QPoint(x + 500, y + 500))
    return QMouseEvent(tipo, QPointF(x, y), g, boton, boton, Qt.NoModifier)


class VentanaNativaFalsa:
    def __init__(self, ok=True):
        self.ok = ok
        self.movida = 0
        self.bordes = []

    def startSystemMove(self):  # noqa: N802
        self.movida += 1
        return self.ok

    def startSystemResize(self, bordes):  # noqa: N802
        self.bordes.append(bordes)
        return self.ok


# -- arrastrar desde cualquier zona vacia --------------------------------------------


def test_se_puede_arrastrar_desde_abajo_no_solo_desde_la_cabecera(ventana):
    """Antes solo valian los 34 px de arriba."""
    ventana.move(100, 100)
    ventana.mousePressEvent(_pulsar(300, ventana.height() - 40, global_=QPoint(400, 540)))
    assert ventana._arrastre is not None
    ventana.mouseMoveEvent(_pulsar(0, 0, tipo=QEvent.MouseMove, global_=QPoint(450, 590)))
    assert ventana.pos() == QPoint(150, 150)
    ventana.mouseReleaseEvent(_pulsar(0, 0, tipo=QEvent.MouseButtonRelease))
    assert ventana._arrastre is None


def test_un_clic_en_una_etiqueta_de_dentro_llega_a_la_ventana_y_arrastra(ventana):
    """La linea de estado del pie ignora el clic: sube hasta la ventana, que arrastra."""
    ventana._arrastre = None
    QTest.mousePress(ventana.estado, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
    assert ventana._arrastre is not None
    QTest.mouseRelease(ventana.estado, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))


def test_un_boton_se_queda_su_clic(ventana):
    ventana._arrastre = None
    QTest.mousePress(ventana.boton_modo, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
    assert ventana._arrastre is None
    QTest.mouseRelease(ventana.boton_modo, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))


def test_con_windows_mueve_el_sistema(ventana, monkeypatch):
    nativa = VentanaNativaFalsa()
    monkeypatch.setattr(ventana, "windowHandle", lambda: nativa)
    ventana._arrastre = None
    ventana.mousePressEvent(_pulsar(300, 300))
    assert nativa.movida == 1 and ventana._arrastre is None


def test_el_boton_derecho_no_arrastra(ventana):
    ventana._arrastre = None
    ventana.mousePressEvent(_pulsar(300, 300, boton=Qt.RightButton))
    assert ventana._arrastre is None


# -- redimensionar desde cualquier borde ----------------------------------------------


@pytest.mark.parametrize("borde", ["n", "s", "e", "o", "no", "ne", "so", "se"])
def test_cada_borde_pide_el_redimensionado_nativo_con_sus_bordes(ventana, monkeypatch, borde):
    nativa = VentanaNativaFalsa()
    monkeypatch.setattr(ventana, "windowHandle", lambda: nativa)
    monkeypatch.setattr(ventana, "_borde_bajo_cursor", lambda evento: borde)
    assert ventana._redimensionar_iniciar(_pulsar(0, 0))
    assert nativa.bordes == [overlay.BORDES_QT[borde]]
    assert ventana._borde_activo is None  # lo lleva Windows, no el modo a mano


def test_sin_redimensionado_nativo_se_hace_a_mano(ventana, monkeypatch):
    monkeypatch.setattr(ventana, "windowHandle", lambda: VentanaNativaFalsa(ok=False))
    assert ventana._redimensionar_iniciar(_pulsar(ventana.width() - 1, ventana.height() - 1))
    assert ventana._borde_activo == "se"
    ventana._redimensionar_soltar()


def test_la_franja_de_los_bordes_es_comoda_de_coger():
    assert overlay.MARGEN_REDIMENSION >= 8


# -- chincheta de la vista compacta ---------------------------------------------------


def test_la_chincheta_solo_sale_en_la_compacta(ventana):
    assert not ventana.boton_fijar.isVisibleTo(ventana)
    ventana.aplicar_modo("compacto")
    assert ventana.boton_fijar.isVisibleTo(ventana)
    ventana.aplicar_modo("completo")
    assert not ventana.boton_fijar.isVisibleTo(ventana)


def test_fijada_por_defecto_y_se_queda_encima(ventana):
    ventana.aplicar_modo("compacto")
    assert ventana.boton_fijar.isChecked()
    assert ventana.windowFlags() & Qt.WindowStaysOnTopHint
    assert ventana._reloj_encima.isActive()  # refuerzo contra el juego "siempre encima"


def test_soltar_la_chincheta_la_deja_como_ventana_normal_y_se_recuerda(ventana):
    from farmadex.config import cargar

    ventana.aplicar_modo("compacto")
    ventana.boton_fijar.setChecked(False)
    assert not (ventana.windowFlags() & Qt.WindowStaysOnTopHint)
    assert not ventana._reloj_encima.isActive()
    assert ventana.isVisible()  # cambiar la bandera no la deja escondida
    assert cargar()["compacta_siempre_encima"] is False
    # La completa sigue siempre encima aunque la compacta este suelta.
    ventana.aplicar_modo("completo")
    assert ventana.windowFlags() & Qt.WindowStaysOnTopHint
    assert not ventana._reloj_encima.isActive()


def test_la_chincheta_suelta_se_recuerda_al_volver_a_abrir(app, tmp_path, monkeypatch):
    from farmadex import config, tareas
    from farmadex.config import cargar, guardar
    from farmadex.datos import indice
    from farmadex.estado import usuario_db

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    datos = cargar()
    datos["compacta_siempre_encima"] = False
    datos["overlay_modo"] = "compacto"
    guardar(datos)
    v = overlay.VentanaOverlay()
    try:
        assert v.modo == "compacto"
        assert not v.boton_fijar.isChecked()
        assert not (v.windowFlags() & Qt.WindowStaysOnTopHint)
    finally:
        v._reloj_encima.stop()
        v.hide()


def test_ocultar_para_el_refuerzo(ventana):
    ventana.aplicar_modo("compacto")
    assert ventana._reloj_encima.isActive()
    ventana.ocultar()
    assert not ventana._reloj_encima.isActive()


# -- el atajo de leer bajo el cursor, desde la ventana ---------------------------------


def test_pulsar_el_atajo_muchas_veces_lanza_una_sola_lectura(ventana):
    lanzadas = []
    ventana.hilo_captura = object()  # solo se mira que no sea None
    ventana.lector_cursor = SimpleNamespace(ultima_pedida=0)
    ventana.turno_cursor = TurnoLecturas(lanzadas.append, programar=lambda ms, f: None)
    for _ in range(25):
        ventana.leer_cursor()
    assert lanzadas == [1]
    assert ventana.lector_cursor.ultima_pedida == 25  # la lectura en marcha sabe que ya es vieja
    ventana._lectura_cursor_terminada(1)
    assert not ventana.turno_cursor.ocupado
