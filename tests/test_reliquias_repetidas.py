"""Varias reliquias seguidas, sin juego: la segunda y la tercera lectura tienen que salir.

Reproduce el aviso de un usuario ("la primera vez salio pero ya no"): EE.log
recibe tres aperturas de la pantalla de recompensas, el `VigilanteEELog` real las
lee del fichero, el `DisparadorAutomatico` real dispara y el `LectorRecompensas`
real corre en su hilo, como en la aplicacion. La primera lectura termina de las
tres formas posibles (bien, con excepcion dentro del hilo, sin recompensas) y
las siguientes tienen que seguir funcionando en los tres casos.
"""

from __future__ import annotations

import sqlite3
import time

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QThread, QTimer
from PySide6.QtWidgets import QApplication

from farmadex.captura import ocr, pantalla
from farmadex.captura.ocr import Leido, MotorOCR
from farmadex.captura.reliquias import DisparadorAutomatico, LectorRecompensas
from farmadex.registro.eelog import VigilanteEELog

from test_captura import _insertar, catalogo  # noqa: F401 - fixture

ABIERTA = "404.207 Script [Info]: ProjectionRewardChoice.lua: Relic rewards initialized\n"
GOT = "404.409 Script [Info]: ProjectionRewardChoice.lua: Got rewards\n"
ELEGIDA = "419.500 Script [Info]: ProjectionRewardChoice.lua: Selection countdown done\n"
CERRADA = "421.000 Script [Info]: ProjectionRewardChoice.lua: Relic reward screen shut down\n"
LINEAS_OK = [Leido("MIRAGE PRIME", 10, 10, 200, 20, 0.9), Leido("SYSTEMS", 10, 32, 100, 20, 0.9)]
# "MK N" es lo que el OCR saca de "MK IV" o de "MK I": contra el catalogo entero no se decide.
LINEAS_EMPATE = [Leido("CRONUS VIDAR MK N", 10, 10, 260, 20, 0.9)]
# Calco de la linea real de EE.log, con el id de jugador inventado.
RECOMPENSA_MK4 = (
    "404.409 Sys [Info]: VoidProjections: 0123456789abcdef01234567 gets reward "
    "/Lotus/StoreItems/r/CronusMk4\n"
)


def _app():
    return QApplication.instance() or QCoreApplication.instance() or QApplication([])


def _esperar(condicion, segundos: float = 4.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        _app().processEvents()
        if condicion():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture()
def escenario(catalogo, monkeypatch, tmp_path):  # noqa: F811
    from farmadex.datos import indice

    con, _ = catalogo
    # Dos objetos que solo se distinguen por el numeral, con la ruta que EE.log da.
    _insertar(con, [
        ("/Lotus/r/CronusMk1", "Cronus Vidar MK I", "Cronus Vidar MK I", "Railjack", None, None),
        ("/Lotus/r/CronusMk4", "Cronus Vidar MK IV", "Cronus Vidar MK IV", "Railjack", None, None),
    ])
    # El lector abre su propia conexion en su hilo, como en la aplicacion.
    monkeypatch.setattr(indice, "hay_indice", lambda *a, **k: True)
    monkeypatch.setattr(indice, "conectar", lambda *a, **k: sqlite3.connect(tmp_path / "prueba.sqlite"))
    monkeypatch.setattr(pantalla, "capturar", lambda region: np.zeros((60, 300, 3), np.uint8))
    monkeypatch.setattr(pantalla, "declarar_dpi", lambda: None)
    monkeypatch.setattr(MotorOCR, "precalentar", lambda self: None)
    MotorOCR.descargar()

    comportamiento = {"modo": "ok"}

    def leer_falso(self, imagen):
        if comportamiento["modo"] == "excepcion":
            raise RuntimeError("onnxruntime: fallo simulado dentro del hilo de captura")
        if comportamiento["modo"] == "vacio":
            return []
        if comportamiento["modo"] == "empate":
            return [Leido(l.texto, l.x, l.y, l.ancho, l.alto, l.confianza) for l in LINEAS_EMPATE]
        return [Leido(l.texto, l.x, l.y, l.ancho, l.alto, l.confianza) for l in LINEAS_OK]

    monkeypatch.setattr(MotorOCR, "leer", leer_falso)

    app = _app()
    ruta = tmp_path / "EE.log"
    ruta.write_text("0.000 Sys [Diag]: Build Label: 2026.09.01.00.00 Retail Windows x64\n", encoding="utf-8")

    hilo = QThread()
    lector = LectorRecompensas("rapidocr")
    lector.moveToThread(hilo)
    hilo.started.connect(lector.iniciar)
    leidas: list[list] = []
    lector.leidas.connect(leidas.append)

    disparador = DisparadorAutomatico(True)
    disparador.ESPERA_MS = 20
    # Igual que VentanaOverlay.leer_recompensas: singleShot hacia el objeto del otro hilo.
    disparador.disparar.connect(lambda: QTimer.singleShot(0, lector.leer_ahora))

    vigilante = VigilanteEELog(ruta)
    vigilante.INTERVALO = 0.02
    eventos: list[str] = []
    vigilante.evento.connect(eventos.append)
    vigilante.evento.connect(disparador.evento)
    # Como en la aplicacion: lo que EE.log dice de las recompensas llega al lector.
    vigilante.pista.connect(lector.pista)
    vigilante.evento.connect(lector.evento)

    hilo.start()
    vigilante.start()
    assert _esperar(lambda: lector.casador is not None)

    def abrir(modo: str, extra: str = "") -> list:
        comportamiento["modo"] = modo
        antes = len(leidas)
        with ruta.open("a", encoding="utf-8") as f:
            f.write(ABIERTA + extra + GOT)
        assert _esperar(lambda: len(leidas) > antes), f"la lectura en modo {modo!r} no llego"
        with ruta.open("a", encoding="utf-8") as f:
            f.write(ELEGIDA + CERRADA)
        assert _esperar(lambda: eventos.count("reliquia_cerrada") == antes + 1)
        return leidas[-1]

    yield abrir, eventos, lector, app

    vigilante.parar()
    hilo.quit()
    hilo.wait(3000)
    MotorOCR.descargar()


@pytest.mark.parametrize("primera", ["ok", "excepcion", "vacio"])
def test_tres_reliquias_seguidas_se_leen_todas(escenario, primera):
    abrir, eventos, lector, _ = escenario
    resultado_1 = abrir(primera)
    resultado_2 = abrir("ok")
    resultado_3 = abrir("ok")

    if primera == "ok":
        assert [r.nombre for r in resultado_1] == ["Mirage Prime Systems"]
    else:
        assert resultado_1 == []  # la interfaz recibe su respuesta aunque no haya nada
    assert [r.nombre for r in resultado_2] == ["Mirage Prime Systems"]
    assert [r.nombre for r in resultado_3] == ["Mirage Prime Systems"]
    assert eventos.count("reliquia_recompensas") == 3
    assert lector._ocupado is False


def test_la_recompensa_que_da_eelog_decide_lo_que_el_ocr_deja_en_empate(escenario):
    """Sin EE.log el OCR no distingue MK I de MK IV; con la linea "gets reward" se
    casa contra ese conjunto cerrado y sale. Y en la reliquia siguiente, sin
    linea, el lector vuelve a no saber: lo conocido no se arrastra."""
    abrir, _, lector, _ = escenario
    assert abrir("empate") == []
    con_log = abrir("empate", extra=RECOMPENSA_MK4)
    assert [r.nombre for r in con_log] == ["Cronus Vidar MK IV"]
    assert lector.conocidas == []  # se limpia al cerrarse la pantalla
    assert abrir("empate") == []


def test_el_vigilante_sigue_leyendo_tras_cada_evento(tmp_path):
    """La posicion en el fichero avanza y no se pierde ninguna apertura posterior."""
    ruta = tmp_path / "EE.log"
    ruta.write_text("cabecera\n", encoding="utf-8")
    vigilante = VigilanteEELog(ruta)
    vigilante.INTERVALO = 0.02
    eventos: list[str] = []
    vigilante.evento.connect(eventos.append)
    arrancado = []
    vigilante.arranque.connect(arrancado.append)
    vigilante.start()
    assert _esperar(lambda: arrancado)  # ya ha fijado la posicion inicial: lo nuevo cuenta
    try:
        for i in range(3):
            with ruta.open("a", encoding="utf-8") as f:
                f.write(ABIERTA + GOT + ELEGIDA + CERRADA)
            assert _esperar(lambda: eventos.count("reliquia_cerrada") == i + 1)
    finally:
        vigilante.parar()
    assert eventos == ["reliquia_abierta", "reliquia_recompensas", "reliquia_elegida", "reliquia_cerrada"] * 3


def test_las_etiquetas_vuelven_a_salir_tras_esconderse():
    from farmadex.captura.reliquias import Recompensa
    from farmadex.ui.etiquetas import EtiquetasRecompensas

    _app()
    etiquetas = EtiquetasRecompensas()
    recompensas = [Recompensa(1, "Mirage Prime Systems", "MIRAGE", (100, 100, 200, 40))]
    etiquetas.mostrar(recompensas)
    assert etiquetas.isVisible()
    etiquetas.hide()
    etiquetas.mostrar([])  # una lectura vacia esconde
    assert not etiquetas.isVisible()
    etiquetas.mostrar(recompensas)
    assert etiquetas.isVisible()
    etiquetas.hide()
