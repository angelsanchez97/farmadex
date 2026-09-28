"""Leer el objeto bajo el cursor: pulsar el atajo muchas veces no puede tumbar nada.

El fallo del tester: "el programa se peta si presionas demasiadas veces esta opcion".
Cada pulsacion encolaba una lectura completa en el hilo de captura; aqui se reproduce
con un hilo de verdad y una lectura falsa que tarda, y se comprueba que con el turno
solo corren una o dos, la ultima pedida gana, y los resultados viejos no se ensenan.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, Signal, Slot  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex.captura import cursor  # noqa: E402
from farmadex.captura.cursor import LectorCursor, TurnoLecturas  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Reloj:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _turno(pausa=0.8):
    lanzadas, programadas = [], []
    reloj = Reloj()
    turno = TurnoLecturas(lanzadas.append, pausa_s=pausa, reloj=reloj, programar=lambda ms, f: programadas.append((ms, f)))
    return turno, lanzadas, programadas, reloj


# -- el turno, sin hilos ---------------------------------------------------------


def test_veinte_pulsaciones_seguidas_lanzan_una_lectura_y_apuntan_otra():
    turno, lanzadas, programadas, reloj = _turno()
    estados = [turno.pedir() for _ in range(20)]
    assert estados[0] == "lanzada" and set(estados[1:]) == {"en_cola"}
    assert lanzadas == [1] and turno.ocupado and turno.pendiente
    assert turno.descartadas == 18  # las de en medio no se leen nunca

    # Acaba la primera: su resultado ya no vale (hay una pedida despues)...
    reloj.t += 2
    assert turno.terminada(1) is False
    # ...y se lanza UNA mas, la ultima.
    assert len(programadas) == 1
    programadas.pop()[1]()
    assert lanzadas == [1, 20]
    assert turno.terminada(20) is True
    assert not turno.ocupado and not turno.pendiente


def test_entre_lecturas_hay_una_pausa_minima():
    turno, lanzadas, programadas, reloj = _turno(pausa=0.8)
    turno.pedir()
    reloj.t += 0.1
    turno.terminada(1)
    reloj.t += 0.1
    # La anterior ya acabo, pero empezo hace menos de la pausa: se espera lo que falta.
    assert turno.pedir() == "en_cola"
    assert lanzadas == [1]
    ms, siguiente = programadas.pop()
    assert 500 <= ms <= 600
    reloj.t += 0.6
    siguiente()
    assert lanzadas == [1, 2]


def test_una_lectura_colgada_no_deja_el_atajo_muerto_para_siempre():
    turno, lanzadas, _, reloj = _turno()
    turno.pedir()
    reloj.t += TurnoLecturas.LIMITE_S + 1
    assert turno.pedir() == "lanzada"
    assert lanzadas == [1, 2]


# -- reproduccion con un hilo de verdad -------------------------------------------


class Puente(QObject):
    pedir = Signal(int)

    def __init__(self):
        super().__init__()
        self.turno = None

    @Slot(int)
    def fin(self, numero):
        self.turno.terminada(numero)


def _lector_lento(lecturas, segundos):
    lector = LectorCursor("rapidocr")

    def lectura_falsa(numero=0):
        lecturas.append(numero)
        time.sleep(segundos)

    lector._leer = lectura_falsa
    return lector


def _esperar(qapp, condicion, segundos=10.0):
    limite = time.monotonic() + segundos
    while not condicion() and time.monotonic() < limite:
        qapp.processEvents()
        time.sleep(0.005)
    return condicion()


def test_sin_turno_cada_pulsacion_encolaba_una_lectura_entera(qapp):
    """El comportamiento de antes, para dejar constancia de por que se peta."""
    lecturas = []
    hilo = QThread()
    lector = _lector_lento(lecturas, 0.005)
    lector.moveToThread(hilo)
    puente = Puente()
    puente.pedir.connect(lector.leer_solicitud)
    hilo.start()
    try:
        for _ in range(30):
            puente.pedir.emit(0)
        assert _esperar(qapp, lambda: len(lecturas) == 30)
    finally:
        hilo.quit()
        hilo.wait(3000)


def test_con_turno_treinta_pulsaciones_son_como_mucho_dos_lecturas(qapp):
    lecturas = []
    hilo = QThread()
    lector = _lector_lento(lecturas, 0.1)
    lector.moveToThread(hilo)
    puente = Puente()
    turno = TurnoLecturas(puente.pedir.emit, pausa_s=0.0)
    puente.turno = turno
    puente.pedir.connect(lector.leer_solicitud)
    lector.terminado.connect(puente.fin)
    hilo.start()
    try:
        for _ in range(30):
            turno.pedir()
            lector.ultima_pedida = turno.ultima
        assert _esperar(qapp, lambda: not turno.ocupado and not turno.pendiente)
        assert 1 <= len(lecturas) <= 2
        assert lecturas[-1] == 30  # la ultima pulsacion es la que se lee
    finally:
        hilo.quit()
        hilo.wait(3000)


def test_el_resultado_de_una_lectura_vieja_no_abre_la_ficha(monkeypatch):
    lector = LectorCursor("rapidocr")
    region = SimpleNamespace(ancho=100, alto=100)
    monkeypatch.setattr(lector, "_preparado", lambda: True)
    monkeypatch.setattr(cursor.pantalla, "region_juego", lambda: None)
    monkeypatch.setattr(cursor.pantalla, "region_alrededor_del_cursor", lambda *a, limite=None: region)
    monkeypatch.setattr(cursor.pantalla, "capturar", lambda r: object())
    hallado = SimpleNamespace(caja=(40, 40, 20, 20), puntuacion=95, item_id=7, nombre="Ash Prime", texto_ocr="ASH")
    monkeypatch.setattr(lector, "_leer_protegido", lambda imagen, umbral: [hallado])
    abiertos, terminados = [], []
    lector.encontrado.connect(lambda i, n: abiertos.append(i))
    lector.terminado.connect(terminados.append)

    lector.ultima_pedida = 5
    lector.leer_solicitud(3)  # vieja: ya se pidio la 5
    assert abiertos == [] and terminados == [3]
    lector.leer_solicitud(5)
    assert abiertos == [7] and terminados == [3, 5]


def test_un_fallo_en_la_lectura_tambien_avisa_de_que_termino(monkeypatch):
    lector = LectorCursor("rapidocr")
    monkeypatch.setattr(lector, "_leer", lambda numero=0: 1 / 0)
    terminados = []
    lector.terminado.connect(terminados.append)
    lector.leer_solicitud(4)
    assert terminados == [4] and not lector._ocupado


def _leer_con(monkeypatch, hallados, cursor_xy, region):
    lector = LectorCursor("rapidocr")
    monkeypatch.setattr(lector, "_preparado", lambda: True)
    monkeypatch.setattr(cursor.pantalla, "region_juego", lambda: None)
    monkeypatch.setattr(cursor.pantalla, "region_alrededor_del_cursor", lambda *a, limite=None: region)
    monkeypatch.setattr(cursor.pantalla, "capturar", lambda r: object())
    monkeypatch.setattr(cursor.pantalla, "_posicion_cursor", lambda: cursor_xy)
    monkeypatch.setattr(lector, "_leer_protegido", lambda imagen, umbral: hallados)
    abiertos = []
    lector.encontrado.connect(lambda i, n: abiertos.append(i))
    lector.leer_solicitud(0)
    return abiertos


def test_si_lo_que_senala_el_raton_no_se_lee_no_se_abre_el_vecino(monkeypatch):
    """En la pantalla de recompensas a 1079x607 el nombre de la tercera carta no se leia y
    se abria la ficha de la segunda (Masseter en vez de Larkspur): mejor nada que otra."""
    region = cursor.pantalla.Region(310, 165, 620, 170)
    vecino = SimpleNamespace(caja=(104, 80, 116, 11), puntuacion=100, item_id=7, nombre="Masseter Prime Empunadura",
                             texto_ocr="MasseterPrimeHandle")
    assert _leer_con(monkeypatch, [vecino], (620, 250), region) == []


def test_lo_que_esta_bajo_el_raton_se_abre_aunque_el_recuadro_se_haya_desplazado(monkeypatch):
    """Junto al borde del juego el recuadro no esta centrado en el raton: manda el raton."""
    region = cursor.pantalla.Region(459, 165, 620, 170)  # pegado al borde derecho
    izquierda = SimpleNamespace(caja=(85, 80, 127, 12), puntuacion=100, item_id=1, nombre="Larkspur", texto_ocr="L")
    derecha = SimpleNamespace(caja=(221, 80, 128, 12), puntuacion=100, item_id=2, nombre="Revenant", texto_ocr="R")
    # El raton esta sobre Revenant (x=744); el centro del recuadro caeria entre las dos.
    assert _leer_con(monkeypatch, [izquierda, derecha], (744, 250), region) == [2]


def test_alineado_con_raton():
    from farmadex.captura.cursor import alineado_con_raton

    assert alineado_con_raton((100, 10, 80, 12), (140, 60), 620)  # encima del texto
    assert alineado_con_raton((100, 10, 80, 12), (205, 60), 620)  # un poco a la derecha
    assert not alineado_con_raton((100, 10, 80, 12), (300, 60), 620)  # la carta de al lado


def test_recuadro_se_escala_con_el_alto_del_juego():
    # A 4K los nombres miden el doble que a 1080p: el recuadro tambien.
    assert cursor.tamano_recuadro(1080) == (620, 170)
    assert cursor.tamano_recuadro(2160) == (1240, 340)
    assert cursor.tamano_recuadro(1440) == (826, 226)
    assert cursor.tamano_recuadro(720) == (413, 113)
    assert cursor.tamano_recuadro(None) == (620, 170)


def test_lectura_pide_el_recuadro_escalado(monkeypatch):
    pedido = {}

    def region(ancho=620, alto=170, limite=None):
        pedido["tam"] = (ancho, alto)
        return None

    monkeypatch.setattr(cursor.pantalla, "region_juego", lambda: cursor.pantalla.Region(0, 0, 3840, 2160))
    monkeypatch.setattr(cursor.pantalla, "region_alrededor_del_cursor", region)
    monkeypatch.setattr(cursor.pantalla, "capturar", lambda r: None)
    lector = cursor.LectorCursor.__new__(cursor.LectorCursor)
    monkeypatch.setattr(lector, "_preparado", lambda: True, raising=False)
    senales = []
    lector.estado = type("S", (), {"emit": lambda self, x: senales.append(x)})()
    lector.candidatos = type("S", (), {"emit": lambda self, x: senales.append(x)})()
    lector._leer()
    assert pedido["tam"] == (1240, 340)
