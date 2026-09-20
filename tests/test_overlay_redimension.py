"""Redimensionado a mano de la ventana sin marco: deteccion de borde, calculo de la
geometria nueva, minimos por modo y recolocacion cuando la ventana no cabe en pantalla.

No usa raton de verdad (serian tests fragiles): la deteccion de borde y el calculo de
geometria son funciones puras, y lo demas se comprueba llamando a los metodos de
`VentanaOverlay` directamente, igual que hace `test_compacto.py`.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.ui import overlay, vista_compacta  # noqa: E402
from farmadex.ui.overlay import (  # noqa: E402
    ALTO_MINIMO_COMPLETO,
    ANCHO_MINIMO_COMPLETO,
    MARGEN_REDIMENSION,
    borde_en_posicion,
    geometria_redimensionada,
)

# -- borde_en_posicion: pura, sin ventana -----------------------------------------

ANCHO, ALTO = 400, 300


@pytest.mark.parametrize(
    "x, y, esperado",
    [
        (200, 150, None),  # centro: clic normal
        (200, 0, "n"),
        (200, ALTO, "s"),
        (0, 150, "o"),
        (ANCHO, 150, "e"),
        (0, 0, "no"),
        (ANCHO, 0, "ne"),
        (0, ALTO, "so"),
        (ANCHO, ALTO, "se"),
        (MARGEN_REDIMENSION, 150, "o"),  # justo en el limite del margen: todavia borde
        (MARGEN_REDIMENSION + 1, 150, None),  # un pixel mas adentro: ya no
    ],
)
def test_borde_en_posicion(x, y, esperado):
    assert borde_en_posicion(x, y, ANCHO, ALTO) == esperado


# -- geometria_redimensionada: pura, sin ventana -----------------------------------

GEOM = QRect(100, 100, 400, 300)
MIN_GRANDE = QSize(50, 50)  # no interfiere: solo importan los casos que rozan el minimo


def test_estirar_por_el_este_solo_cambia_el_ancho():
    nueva = geometria_redimensionada("e", GEOM, QPoint(40, 0), MIN_GRANDE)
    assert (nueva.x(), nueva.y(), nueva.width(), nueva.height()) == (100, 100, 440, 300)


def test_estirar_por_el_oeste_mueve_el_origen_y_no_el_borde_derecho():
    nueva = geometria_redimensionada("o", GEOM, QPoint(-30, 0), MIN_GRANDE)
    # El borde derecho (x+w = 500) tiene que quedar donde estaba.
    assert nueva.x() + nueva.width() == GEOM.x() + GEOM.width()
    assert (nueva.x(), nueva.width()) == (70, 430)


def test_estirar_por_el_norte_mueve_el_origen_y_no_el_borde_inferior():
    nueva = geometria_redimensionada("n", GEOM, QPoint(0, -20), MIN_GRANDE)
    assert nueva.y() + nueva.height() == GEOM.y() + GEOM.height()
    assert (nueva.y(), nueva.height()) == (80, 320)


def test_estirar_por_el_sur_solo_cambia_el_alto():
    nueva = geometria_redimensionada("s", GEOM, QPoint(0, 25), MIN_GRANDE)
    assert (nueva.x(), nueva.y(), nueva.width(), nueva.height()) == (100, 100, 400, 325)


def test_esquina_combina_las_dos_direcciones():
    nueva = geometria_redimensionada("se", GEOM, QPoint(10, -10), MIN_GRANDE)
    assert (nueva.width(), nueva.height()) == (410, 290)
    nueva = geometria_redimensionada("no", GEOM, QPoint(10, -10), MIN_GRANDE)
    # x se mueve con el ancho, y con el alto, cada uno por su lado.
    assert nueva.x() + nueva.width() == GEOM.x() + GEOM.width()
    assert nueva.y() + nueva.height() == GEOM.y() + GEOM.height()


def test_no_se_encoge_mas_alla_del_minimo():
    minimo = QSize(380, 280)
    # Arrastrar el este hacia dentro mas de lo que el minimo permite.
    nueva = geometria_redimensionada("e", GEOM, QPoint(-100, 0), minimo)
    assert nueva.width() == 380
    # Y por el oeste: el borde derecho tampoco se mueve al topar con el minimo.
    nueva = geometria_redimensionada("o", GEOM, QPoint(100, 0), minimo)
    assert nueva.width() == 380
    assert nueva.x() + nueva.width() == GEOM.x() + GEOM.width()


# -- integracion con la ventana real -----------------------------------------------


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


def test_minimo_de_la_vista_completa_se_respeta(ventana):
    ventana.resize(1, 1)
    assert ventana.width() >= ANCHO_MINIMO_COMPLETO
    assert ventana.height() >= ALTO_MINIMO_COMPLETO


def test_minimo_de_la_vista_compacta_es_menor_que_el_de_la_completa(ventana):
    ventana.alternar_modo()  # a compacto
    ventana.resize(1, 1)
    assert ventana.width() >= vista_compacta.ANCHO_MINIMO
    assert ventana.height() >= vista_compacta.ALTO_MINIMO
    assert vista_compacta.ANCHO_MINIMO < ANCHO_MINIMO_COMPLETO
    assert vista_compacta.ALTO_MINIMO < ALTO_MINIMO_COMPLETO


def test_arrastrar_una_esquina_redimensiona_de_verdad(ventana):
    ventana.setGeometry(50, 50, 800, 500)
    borde = "se"
    ventana._borde_activo = borde
    ventana._geom_inicio_resize = ventana.geometry()
    ventana._pos_inicio_resize = QPoint(0, 0)

    class _EventoFalso:
        def __init__(self, punto, botones):
            self._punto = punto
            self._botones = botones

        def globalPosition(self):
            class _F:
                def __init__(self, p):
                    self._p = p

                def toPoint(self):
                    return self._p

            return _F(self._punto)

        def buttons(self):
            return self._botones

    from PySide6.QtCore import Qt

    evento = _EventoFalso(QPoint(30, -10), Qt.LeftButton)
    consumido = ventana._redimensionar_mover(evento)
    assert consumido is True
    assert (ventana.width(), ventana.height()) == (830, 490)


def test_soltar_termina_el_redimensionado(ventana):
    ventana._borde_activo = "e"
    ventana._geom_inicio_resize = ventana.geometry()
    ventana._pos_inicio_resize = QPoint(0, 0)
    assert ventana._redimensionar_soltar() is True
    assert ventana._borde_activo is None
    # Sin redimensionado activo, no hay nada que soltar.
    assert ventana._redimensionar_soltar() is False


def test_ventana_fuera_de_pantalla_se_recoloca(ventana):
    pantalla = QApplication.primaryScreen()
    disponible = pantalla.availableGeometry()
    # Muy lejos de cualquier monitor: tiene que reaparecer centrada en el principal.
    ventana.resize(ANCHO_MINIMO_COMPLETO, ALTO_MINIMO_COMPLETO)
    ventana.move(disponible.x() + disponible.width() + 5000, disponible.y() + 5000)
    ventana._asegurar_en_pantalla()
    g = ventana.frameGeometry()
    assert disponible.intersects(g)


def test_ventana_mas_grande_que_la_pantalla_se_encoge_y_se_reencuadra(ventana):
    pantalla = QApplication.primaryScreen()
    disponible = pantalla.availableGeometry()
    # Mas ancha que la pantalla entera: tiene que encogerse para caber, no quedar cortada.
    ventana.setGeometry(disponible.x() - 10, disponible.y() - 10, disponible.width() + 500, 500)
    ventana._asegurar_en_pantalla()
    g = ventana.geometry()
    assert g.x() >= disponible.x()
    assert g.y() >= disponible.y()
    assert g.x() + g.width() <= disponible.x() + disponible.width()
    assert g.y() + g.height() <= disponible.y() + disponible.height()
