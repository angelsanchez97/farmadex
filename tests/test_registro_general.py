"""El registro general (farmadex.log) recoge tambien lo que antes se perdia en el .exe:
excepciones de hilos, avisos de Qt, excepciones "no lanzables" y cierres bruscos."""

from __future__ import annotations

import gc
import logging
import sys
import threading

import pytest

from farmadex import registro_log


@pytest.fixture()
def capturado(monkeypatch):
    """Los ganchos globales se restauran al acabar; los mensajes se recogen en memoria."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "unraisablehook", sys.unraisablehook)
    import faulthandler

    estaba = faulthandler.is_enabled()
    registros: list[logging.LogRecord] = []

    class Recoger(logging.Handler):
        def emit(self, record):
            registros.append(record)

    manejador = Recoger(level=logging.DEBUG)
    raiz = logging.getLogger("farmadex")
    raiz.addHandler(manejador)
    yield registros
    raiz.removeHandler(manejador)
    try:
        from PySide6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(None)
    except ImportError:
        pass
    faulthandler.disable()
    if estaba:
        faulthandler.enable(file=sys.__stderr__)


def test_una_excepcion_en_un_hilo_queda_en_el_registro(capturado, tmp_path, monkeypatch):
    monkeypatch.setattr(registro_log, "RUTA_CIERRES_BRUSCOS", tmp_path / "cierres.txt")
    registro_log.instalar_gancho_excepciones()

    def revienta():
        raise ValueError("fallo en el hilo de prueba")

    hilo = threading.Thread(target=revienta, name="hilo-de-prueba")
    hilo.start()
    hilo.join()
    errores = [r for r in capturado if r.levelno == logging.ERROR and "hilo-de-prueba" in r.getMessage()]
    assert errores and errores[0].exc_info[0] is ValueError


def test_las_excepciones_no_lanzables_tambien(capturado, tmp_path, monkeypatch):
    monkeypatch.setattr(registro_log, "RUTA_CIERRES_BRUSCOS", tmp_path / "cierres.txt")
    registro_log.instalar_gancho_excepciones()

    class Roto:
        def __del__(self):
            raise RuntimeError("fallo en __del__")

    Roto()
    gc.collect()
    assert any(r.exc_info and r.exc_info[0] is RuntimeError for r in capturado)


def test_los_avisos_de_qt_van_al_registro(capturado):
    from PySide6.QtCore import qCritical, qWarning

    assert registro_log.instalar_mensajes_qt()
    qWarning("aviso de Qt de prueba")
    qCritical("error de Qt de prueba")
    textos = {(r.levelno, r.getMessage()) for r in capturado if r.name.endswith(".qt")}
    assert (logging.WARNING, "aviso de Qt de prueba") in textos
    assert (logging.ERROR, "error de Qt de prueba") in textos


def test_los_cierres_bruscos_dejan_fichero(capturado, tmp_path):
    ruta = tmp_path / "logs" / "cierres.txt"
    assert registro_log._activar_faulthandler(ruta)
    import faulthandler

    assert faulthandler.is_enabled()
    assert "pid" in ruta.read_text(encoding="utf-8")


def test_el_fichero_de_cierres_no_crece_sin_fin(capturado, tmp_path):
    ruta = tmp_path / "cierres.txt"
    ruta.write_text("x" * 1_100_000, encoding="utf-8")
    assert registro_log._activar_faulthandler(ruta)
    assert ruta.stat().st_size < 1000


def test_el_registro_rota(capturado):
    """farmadex.log no crece sin fin: rota a 2 MB y guarda tres copias."""
    manejadores = [h for h in logging.getLogger("farmadex").handlers if isinstance(h, registro_log.FicheroRotativoSeguro)]
    assert manejadores
    assert manejadores[0].maxBytes > 0 and manejadores[0].backupCount >= 1
