"""El diagnostico de reliquias desde la ventana y Ajustes, y los avisos que llegan a la bandeja.

Todo lo que fallaba en silencio (reliquia en pantalla completa exclusiva, lector
que no carga) tiene que verse con la ventana escondida: por eso va a la bandeja.
"""

from __future__ import annotations

import os
import sqlite3
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import diagnostico, idiomas  # noqa: E402
from farmadex.captura import pantalla  # noqa: E402
from farmadex.captura.reliquias import Recompensa  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def ventana(app, con, tmp_path, monkeypatch):
    """VentanaOverlay sin hilos ni servicios, como en test_overlay_datos."""
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
    for nombre in ("_arrancar_mundo", "_arrancar_captura", "_arrancar_comparador", "_arrancar_actualizador"):
        monkeypatch.setattr(v, nombre, lambda: None)
    yield v
    v.hide()


def test_reliquia_en_pantalla_completa_exclusiva_avisa_por_la_bandeja_una_vez(ventana, monkeypatch):
    monkeypatch.setattr(pantalla, "modo_pantalla", lambda hwnd=None: pantalla.MODO_EXCLUSIVO)
    avisos = []
    ventana.aviso_bandeja.connect(avisos.append)
    ventana._avisar_si_no_se_va_a_ver()
    ventana._avisar_si_no_se_va_a_ver()  # la siguiente reliquia, un momento despues: no se repite
    assert len(avisos) == 1
    assert "exclusiva" in avisos[0] and "Ventana sin bordes" in avisos[0]
    # El banner de la ventana tambien lo dice, para cuando la abra.
    assert "exclusivo" in ventana._avisos


def test_en_ventana_sin_bordes_no_hay_aviso(ventana, monkeypatch):
    monkeypatch.setattr(pantalla, "modo_pantalla", lambda hwnd=None: pantalla.MODO_SIN_BORDES)
    avisos = []
    ventana.aviso_bandeja.connect(avisos.append)
    ventana._avisar_si_no_se_va_a_ver()
    assert avisos == []


def test_recompensas_leidas_en_exclusiva_se_apuntan_como_leidas_pero_no_pintadas(ventana, monkeypatch):
    monkeypatch.setattr(pantalla, "modo_pantalla", lambda hwnd=None: pantalla.MODO_EXCLUSIVO)
    avisos = []
    ventana.aviso_bandeja.connect(avisos.append)
    ventana._pintar_recompensas([Recompensa(0, "Sin identificar", "x", (10, 10, 100, 100))])
    assert ventana._ultima_lectura is not None and ventana._ultima_lectura[1] == 1
    assert ventana._ultima_pintada is None
    assert avisos and "exclusiva" in avisos[0]
    # El diagnostico lo cuenta como leido pero no pintado.
    ventana._t_reliquia_reloj = ventana._ultima_lectura[0] - 0.5
    d = ventana.diagnostico()
    assert any("no se pintaron" in l.texto for l in d.problemas)
    assert any("exclusiva" in l.texto for l in d.problemas)


def test_el_diagnostico_sin_captura_arrancada_lo_dice_y_ajustes_lo_pinta(ventana, monkeypatch):
    monkeypatch.setattr(pantalla, "modo_pantalla", lambda hwnd=None: pantalla.MODO_DESCONOCIDO)
    d = ventana.mostrar_diagnostico()
    assert any("vigilancia de EE.log no ha arrancado" in l.texto for l in d.problemas)
    assert ventana.ajustes.resultado_diagnostico.isVisibleTo(ventana.ajustes)
    assert "[MAL]" in ventana.ajustes.resultado_diagnostico.text()
    assert "EE.log" in ventana.ajustes.resultado_diagnostico.text()


def test_guardar_informe_deja_el_zip_y_lo_dice_en_ajustes(ventana, tmp_path, monkeypatch):
    monkeypatch.setattr(pantalla, "modo_pantalla", lambda hwnd=None: pantalla.MODO_DESCONOCIDO)
    escritorio = tmp_path / "Escritorio"
    monkeypatch.setattr(diagnostico, "carpeta_escritorio", lambda: escritorio)
    revelados = []
    monkeypatch.setattr(diagnostico, "revelar", revelados.append)
    ruta = ventana.guardar_informe()
    assert ruta is not None and ruta.parent == escritorio and revelados == [ruta]
    with zipfile.ZipFile(ruta) as z:
        assert "diagnostico.txt" in z.namelist()
        assert not any(n.lower() == "ee.log" for n in z.namelist())
    assert str(ruta) in ventana.ajustes.estado_informe.text()


def test_si_el_informe_no_se_puede_escribir_se_dice_sin_reventar(ventana, monkeypatch):
    monkeypatch.setattr(pantalla, "modo_pantalla", lambda hwnd=None: pantalla.MODO_DESCONOCIDO)

    def falla(*_a, **_k):
        raise OSError("disco lleno")

    monkeypatch.setattr(diagnostico, "guardar_informe", falla)
    assert ventana.guardar_informe() is None
    assert "disco lleno" in ventana.ajustes.estado_informe.text()


def test_los_botones_de_ajustes_emiten_las_senales(ventana):
    pedidos, informes = [], []
    ventana.ajustes.pedir_diagnostico.connect(lambda: pedidos.append(1))
    ventana.ajustes.guardar_informe.connect(lambda: informes.append(1))
    ventana.ajustes.boton_diagnostico.click()
    ventana.ajustes.boton_informe.click()
    assert pedidos == [1] and informes == [1]


# --- etiquetas en el monitor del juego ----------------------------------------------


class _PantallaFalsa:
    def __init__(self, rect):
        self._rect = rect

    def geometry(self):
        return self._rect


def test_las_etiquetas_van_al_monitor_donde_esta_el_juego(app, monkeypatch):
    """Con el juego en el segundo monitor, las cajas caen fuera de un widget puesto en el
    primario y no se veia nada. Ahora se elige el monitor de las cajas y se traducen."""
    from farmadex.ui import etiquetas

    primario, segundo = QRect(0, 0, 2560, 1440), QRect(2560, 0, 1920, 1080)

    class QGuiFalsa:
        @staticmethod
        def screens():
            return [_PantallaFalsa(primario), _PantallaFalsa(segundo)]

        @staticmethod
        def primaryScreen():
            return _PantallaFalsa(primario)

    monkeypatch.setattr(etiquetas, "QGuiApplication", QGuiFalsa)
    en_el_segundo = [Recompensa(1, "A", "a", (2560 + 600, 400, 200, 250)), Recompensa(2, "B", "b", (2560 + 1000, 400, 200, 250))]
    assert etiquetas.pantalla_de_las_cajas(en_el_segundo) == segundo
    etiquetas.a_coordenadas_locales(en_el_segundo, segundo)
    assert [r.caja for r in en_el_segundo] == [(600, 400, 200, 250), (1000, 400, 200, 250)]

    en_el_primario = [Recompensa(1, "A", "a", (600, 400, 200, 250))]
    assert etiquetas.pantalla_de_las_cajas(en_el_primario) == primario
    etiquetas.a_coordenadas_locales(en_el_primario, primario)
    assert en_el_primario[0].caja == (600, 400, 200, 250)

    # Cajas que no caen en ningun monitor (captura vieja): el primario, como siempre.
    perdidas = [Recompensa(1, "A", "a", (9000, 9000, 10, 10))]
    assert etiquetas.pantalla_de_las_cajas(perdidas) == primario
    assert etiquetas.pantalla_de_las_cajas([]) == primario


def test_mostrar_pone_la_ventana_de_etiquetas_en_el_monitor_del_juego(app, monkeypatch):
    from farmadex.ui import etiquetas, panel_recompensas

    segundo = QRect(2560, 0, 1920, 1080)

    class QGuiFalsa:
        @staticmethod
        def screens():
            return [_PantallaFalsa(QRect(0, 0, 2560, 1440)), _PantallaFalsa(segundo)]

        @staticmethod
        def primaryScreen():
            return _PantallaFalsa(QRect(0, 0, 2560, 1440))

    monkeypatch.setattr(etiquetas, "QGuiApplication", QGuiFalsa)
    for widget in (etiquetas.EtiquetasRecompensas(), panel_recompensas.PanelRecompensas()):
        widget.mostrar([Recompensa(1, "A", "a", (2560 + 600, 400, 200, 250))], {})
        assert widget.geometry().topLeft() == segundo.topLeft()
        assert widget.recompensas[0].caja == (600, 400, 200, 250)
        widget.hide()
