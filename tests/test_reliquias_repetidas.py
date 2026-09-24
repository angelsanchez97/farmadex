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
        cerradas = eventos.count("reliquia_cerrada")
        with ruta.open("a", encoding="utf-8") as f:
            f.write(ABIERTA + extra + GOT)
        assert _esperar(lambda: len(leidas) > antes), f"la lectura en modo {modo!r} no llego"
        with ruta.open("a", encoding="utf-8") as f:
            f.write(ELEGIDA + CERRADA)
        assert _esperar(lambda: eventos.count("reliquia_cerrada") == cerradas + 1)
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
    # Cada pantalla dispara dos lecturas (una por marcador); la segunda puede seguir
    # en el hilo de captura al cerrarse la ultima. Lo que importa es que termine.
    assert _esperar(lambda: lector._ocupado is False, 1.0)


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


def test_la_espera_fija_ya_no_se_come_el_segundo():
    """En el video de un usuario los nombres se leen en el primer fotograma."""
    from farmadex.captura.reliquias import DisparadorAutomatico

    assert DisparadorAutomatico.ESPERA_MS <= 200


def test_una_lectura_corta_se_reintenta_solo_dentro_del_plazo():
    import time

    from farmadex.captura.reliquias import LectorRecompensas

    lector = LectorRecompensas.__new__(LectorRecompensas)
    lector.jugadores = 3
    lector._t_aviso = time.monotonic()
    assert lector._toca_reintentar(0) and lector._toca_reintentar(2)
    assert not lector._toca_reintentar(3)
    lector._t_aviso = time.monotonic() - 10  # la pantalla ya lleva un rato: no se insiste
    assert not lector._toca_reintentar(0)
    lector._t_aviso = None  # lectura a mano (atajo): una sola vez, como siempre
    assert not lector._toca_reintentar(0)
    lector._t_aviso, lector.jugadores = time.monotonic(), None  # sin saber cuantos: al menos una
    assert lector._toca_reintentar(0) and not lector._toca_reintentar(1)


def test_una_segunda_lectura_peor_no_pisa_a_la_buena():
    """Registro real: la 1a mirada leyo "Plano chasisDe CitrinePrime" (el chasis) y la 2a,
    de la misma tarjeta, solo "Citrine Prime": salia el plano en vez del chasis."""
    from farmadex.captura.reliquias import SIN_IDENTIFICAR, Recompensa, conservar_mejores

    primera = [
        Recompensa(1, "Daikyu Prime Plano", "Plano De Daiky Prime", (100, 500, 250, 30)),
        Recompensa(2, "Vadarya Prime Receptor", "Receptor De Vadarya Prime", (420, 500, 250, 30)),
        Recompensa(3, "Citrine Prime Chasis", "Plano chasisDe CitrinePrime", (740, 490, 250, 50)),
    ]
    segunda = [
        Recompensa(1, "Daikyu Prime Plano", "Plano De Daikyu Prime", (100, 500, 250, 30)),
        Recompensa(2, "Vadarya Prime Receptor", "Receptor De Vadarya Prime", (420, 500, 250, 30)),
        Recompensa(SIN_IDENTIFICAR, "Sin identificar", "Citrine Prime", (760, 510, 200, 30)),
        Recompensa(4, "Citrine Prime Plano", "Plano Citrine Prime", (1060, 500, 250, 30)),
    ]
    juntas = conservar_mejores(primera, segunda)
    assert [r.item_id for r in juntas] == [1, 2, 3, 4]
    assert juntas[2].caja == (760, 510, 200, 30)  # posicion de la ultima mirada

    # Una lectura nueva con mas texto y otro objeto si gana; y lo que no se ve no se pierde.
    mejor = [Recompensa(5, "Otra", "Plano De Chasis De Citrine Prime", (740, 490, 250, 50))]
    juntas = conservar_mejores(primera, mejor)
    assert [r.item_id for r in juntas] == [1, 2, 5]


def test_el_disparador_lee_con_el_primer_marcador_de_la_pantalla():
    """"Relic rewards initialized" llega al instante; "Got rewards", escrita 0,6 s
    despues, tardo 4,8 s en un EE.log real. Con el primero ya se esta mirando."""
    _app()
    disparador = DisparadorAutomatico(True)
    disparador.ESPERA_MS = 1
    disparos: list[float] = []
    disparador.disparar.connect(lambda: disparos.append(time.monotonic()))
    disparador.evento("reliquia_abierta")
    assert _esperar(lambda: len(disparos) == 1, 1.0)
    disparador.evento("reliquia_recompensas")  # el segundo marcador sigue disparando (confirmacion)
    assert _esperar(lambda: len(disparos) == 2, 1.0)
    disparador.evento("reliquia_abierta")
    disparador.evento("reliquia_cerrada")  # cerrada antes de la espera: no se lee
    time.sleep(0.05)
    _app().processEvents()
    assert len(disparos) == 2
    disparador.activo = False
    disparador.evento("reliquia_abierta")
    time.sleep(0.05)
    _app().processEvents()
    assert len(disparos) == 2
