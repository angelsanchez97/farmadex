"""Farmadex se esconde un instante al capturar lo que tapa (y vuelve siempre).

Todo en offscreen: ventanas Qt simuladas, sin nada visible en el PC de verdad.
"""

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from farmadex.captura import pantalla
from farmadex.captura.pantalla import Region
from farmadex.ui.ocultar_captura import OcultadorVentanas


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def ventanas(app):
    """Una ventana encima de la zona a leer y otra (el panel de reliquias) debajo."""
    encima, debajo = QWidget(), QWidget()
    encima.setGeometry(100, 100, 300, 200)
    debajo.setGeometry(100, 700, 300, 150)
    for w in (encima, debajo):
        w.show()
    app.processEvents()
    yield encima.windowHandle(), debajo.windowHandle()
    for w in (encima, debajo):
        w.close()
        w.deleteLater()
    app.processEvents()


ZONA = Region(150, 150, 400, 300)  # pisa `encima`, no `debajo`


def _ocultador(app, esperas=None, **kw):
    """Ocultador de prueba: solo ve las ventanas de la prueba y no espera a DWM."""
    esperas = esperas if esperas is not None else []
    return OcultadorVentanas(
        esperar=lambda: esperas.append(time.perf_counter()), precomprobar=None, **kw
    )


def _en_hilo(app, funcion, limite_s=5.0):
    """Corre `funcion` en otro hilo mientras el de Qt sigue atendiendo eventos."""
    resultado, fallo = {}, {}

    def cuerpo():
        try:
            resultado["valor"] = funcion()
        except BaseException as e:  # noqa: BLE001
            fallo["e"] = e

    hilo = threading.Thread(target=cuerpo)
    hilo.start()
    fin = time.monotonic() + limite_s
    while hilo.is_alive() and time.monotonic() < fin:
        app.processEvents(QEventLoop.AllEvents, 10)
    hilo.join(0.1)
    app.processEvents()
    assert not hilo.is_alive(), "el hilo de captura se quedo colgado"
    if fallo:
        raise fallo["e"]
    return resultado.get("valor")


def _esperar_ms(app, ms):
    fin = time.monotonic() + ms / 1000
    while time.monotonic() < fin:
        app.processEvents(QEventLoop.AllEvents, 10)


def test_oculta_captura_y_restaura_solo_lo_que_tapa(app, ventanas, monkeypatch):
    encima, debajo = ventanas
    visto = {}

    def crudo(region):
        visto["encima"], visto["debajo"] = encima.opacity(), debajo.opacity()
        return np.zeros((region.alto, region.ancho, 3), np.uint8)

    esperas = []
    ocultador = _ocultador(app, esperas)
    pantalla.registrar_ocultador(ocultador)
    monkeypatch.setattr(pantalla, "_capturar_crudo", crudo)

    imagen = _en_hilo(app, lambda: pantalla.capturar(ZONA))

    assert imagen.shape == (300, 400, 3)
    assert visto == {"encima": 0.0, "debajo": 1.0}  # el panel de debajo no se toca
    assert len(esperas) == 1  # se espero al compositor antes de capturar
    assert encima.opacity() == 1.0 and debajo.opacity() == 1.0
    assert ocultador.escondidas == 0 and ocultador.ocultaciones == 1


def test_sin_nada_encima_ni_se_espera(app, ventanas, monkeypatch):
    esperas = []
    pantalla.registrar_ocultador(_ocultador(app, esperas))
    monkeypatch.setattr(pantalla, "_capturar_crudo", lambda r: "img")
    assert _en_hilo(app, lambda: pantalla.capturar(Region(1000, 1000, 50, 50))) == "img"
    assert esperas == []  # ni un fotograma de mas cuando no hay nada que esconder


def test_restaura_aunque_la_captura_falle(app, ventanas, monkeypatch):
    encima, _ = ventanas
    ocultador = _ocultador(app)
    pantalla.registrar_ocultador(ocultador)

    def revienta(region):
        assert encima.opacity() == 0.0
        raise RuntimeError("driver")

    monkeypatch.setattr(pantalla, "_capturar_crudo", revienta)
    with pytest.raises(RuntimeError):
        _en_hilo(app, lambda: pantalla.capturar(ZONA))
    app.processEvents()
    assert encima.opacity() == 1.0 and ocultador.escondidas == 0


def test_si_qt_no_contesta_se_captura_igual_y_no_queda_nada_escondido(app, ventanas, monkeypatch):
    encima, _ = ventanas
    ocultador = _ocultador(app, espera_max_s=0.05)
    pantalla.registrar_ocultador(ocultador)
    monkeypatch.setattr(pantalla, "_capturar_crudo", lambda r: "img")
    resultado = {}
    # El hilo de Qt no atiende eventos mientras el de captura espera.
    hilo = threading.Thread(target=lambda: resultado.setdefault("img", pantalla.capturar(ZONA)))
    t0 = time.perf_counter()
    hilo.start()
    hilo.join(2)
    assert resultado["img"] == "img"
    assert time.perf_counter() - t0 < 1.0  # espera acotada
    app.processEvents()  # la peticion llega tarde: cancelada, no esconde nada
    assert encima.opacity() == 1.0 and ocultador.escondidas == 0


def test_temporizador_de_seguridad_si_nunca_llega_restaurar(app, ventanas):
    encima, _ = ventanas
    ocultador = _ocultador(app, seguridad_ms=80)
    ficha = _en_hilo(app, lambda: ocultador.ocultar(ZONA))  # y nadie llama a restaurar
    assert ficha is not None and encima.opacity() == 0.0
    _esperar_ms(app, 200)
    assert encima.opacity() == 1.0 and ocultador.escondidas == 0
    ocultador.restaurar(ficha)  # llegar tarde no rompe nada
    app.processEvents()
    assert encima.opacity() == 1.0


def test_dos_lecturas_a_la_vez_se_devuelve_al_acabar_la_ultima(app, ventanas):
    encima, _ = ventanas
    encima.setOpacity(0.9)  # su opacidad de siempre se respeta al volver
    ocultador = _ocultador(app)
    a = _en_hilo(app, lambda: ocultador.ocultar(ZONA))
    b = _en_hilo(app, lambda: ocultador.ocultar(ZONA))
    ocultador.restaurar(a)
    app.processEvents()
    assert encima.opacity() == 0.0
    ocultador.restaurar(b)
    app.processEvents()
    assert encima.opacity() == pytest.approx(0.9, abs=0.01)


def test_desde_el_propio_hilo_de_qt_no_se_bloquea(app, ventanas, monkeypatch):
    encima, _ = ventanas
    pantalla.registrar_ocultador(_ocultador(app))
    visto = []
    monkeypatch.setattr(pantalla, "_capturar_crudo", lambda r: visto.append(encima.opacity()) or "img")
    t0 = time.perf_counter()
    assert pantalla.capturar(ZONA) == "img"
    assert time.perf_counter() - t0 < 0.2
    assert visto == [0.0] and encima.opacity() == 1.0


def test_restaurar_todo_al_cerrar(app, ventanas):
    encima, _ = ventanas
    ocultador = _ocultador(app)
    _en_hilo(app, lambda: ocultador.ocultar(ZONA))
    ocultador.restaurar_todo()
    assert encima.opacity() == 1.0


def test_sin_ocultador_captura_sin_mas(monkeypatch):
    pantalla.registrar_ocultador(None)
    monkeypatch.setattr(pantalla, "_capturar_crudo", lambda r: "img")
    assert pantalla.capturar(ZONA) == "img"


def test_si_el_ocultador_falla_se_captura_igual(monkeypatch):
    class Roto:
        def ocultar(self, region):
            raise OSError("x")

        def restaurar(self, ficha):
            raise AssertionError("no hay ficha que devolver")

    pantalla.registrar_ocultador(Roto())
    monkeypatch.setattr(pantalla, "_capturar_crudo", lambda r: "img")
    assert pantalla.capturar(ZONA) == "img"


def test_tiempo_anadido_por_lectura(app, ventanas, monkeypatch):
    """Esconder y devolver cuesta poco aparte de la espera al compositor (1-2 fotogramas)."""
    ocultador = _ocultador(app)
    pantalla.registrar_ocultador(ocultador)
    monkeypatch.setattr(pantalla, "_capturar_crudo", lambda r: "img")

    def varias():
        for _ in range(20):
            pantalla.capturar(ZONA)

    _en_hilo(app, varias)
    medio_ms = ocultador.segundos / ocultador.ocultaciones * 1000
    assert ocultador.ocultaciones == 20
    assert medio_ms < 50, medio_ms  # ida y vuelta al hilo de Qt, sin contar a DWM


# -- lecturas periodicas: no se esconde, se descarta lo tapado ------------------------


def test_descartar_propias_pinta_de_negro_lo_tapado():
    imagen = np.full((100, 200, 3), 255, np.uint8)
    region = Region(1000, 500, 200, 100)
    tapada = pantalla.descartar_propias(imagen, region, [Region(1150, 450, 300, 300)])
    assert tapada is not imagen
    assert (tapada[:, 150:] == 0).all() and (tapada[:, :150] == 255).all()
    assert (imagen == 255).all()  # la original no se toca


def test_descartar_propias_sin_solape_devuelve_la_misma():
    imagen = np.zeros((10, 10, 3), np.uint8)
    assert pantalla.descartar_propias(imagen, Region(0, 0, 10, 10), [Region(50, 50, 5, 5)]) is imagen


def test_descartar_propias_se_salta_si_tapa_casi_todo():
    imagen = np.zeros((100, 100, 3), np.uint8)
    assert pantalla.descartar_propias(imagen, Region(0, 0, 100, 100), [Region(0, 0, 80, 100)]) is None


def test_lector_pasivo_no_esconde_farmadex(monkeypatch):
    from farmadex.captura import lector_pasivo

    class Espia:
        llamadas = 0

        def ocultar(self, region):
            Espia.llamadas += 1

        def restaurar(self, ficha):
            pass

    pantalla.registrar_ocultador(Espia())
    region = Region(0, 0, 100, 100)
    monkeypatch.setattr(pantalla, "ventana_juego", lambda: 7)
    monkeypatch.setattr(pantalla, "_ventana_activa", lambda: 7)
    monkeypatch.setattr(pantalla, "region_ventana", lambda h: region)
    monkeypatch.setattr(pantalla, "_capturar_crudo", lambda r: np.full((100, 100, 3), 200, np.uint8))
    monkeypatch.setattr(pantalla, "ventanas_propias", lambda: [Region(0, 0, 30, 100)])
    vistas = []
    lector = lector_pasivo.LectorPasivo.__new__(lector_pasivo.LectorPasivo)
    lector._ocupado, lector.activo_perfil, lector.activo_inventario = False, True, False
    lector.pantalla_log = None

    class Detector:
        def observar(self, imagen):
            vistas.append(imagen)
            return False

    lector.detector = Detector()
    lector.tic()
    assert Espia.llamadas == 0
    assert len(vistas) == 1 and (vistas[0][:, :30] == 0).all() and (vistas[0][:, 30:] == 200).all()

    # Si Farmadex tapa casi todo el juego, esa vuelta ni se mira.
    monkeypatch.setattr(pantalla, "ventanas_propias", lambda: [Region(0, 0, 90, 100)])
    lector.tic()
    assert len(vistas) == 1


def test_esperar_composicion_es_corta():
    """DwmFlush x2 en este PC: 1-2 fotogramas. Nunca un parón largo."""
    t0 = time.perf_counter()
    pantalla.esperar_composicion()
    assert time.perf_counter() - t0 < 0.5
