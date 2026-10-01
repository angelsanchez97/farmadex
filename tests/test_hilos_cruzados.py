"""Nada toca un temporizador o un widget desde un hilo que no es el suyo.

Dos causas distintas de "Timers cannot be started/stopped from another thread" (cada una
seguida, de vez en cuando, de un cierre brusco por access violation):

1. Las sondas de la autoprueba (`autoprueba.Sondas.poner`) sustituian metodos @Slot de
   `ControladorVistas` por funciones normales. Medido con PySide6 6.11: una senal de un
   objeto de otro hilo conectada a un metodo con nombre de slot que Qt ya no reconoce como
   el slot (otra funcion con el mismo nombre) se entrega EN EL HILO DEL EMISOR. Asi
   `mostrar_precio` corria en el hilo del vigia de vistas y tocaba widgets y temporizadores
   de la ventana (unas 60 veces por pasada de autoprueba, y dos pasadas murieron ahi).

2. Al cerrar, los objetos que viven en hilos de trabajo (vigia de vistas, lector pasivo,
   servicio del mundo, lector de fin de mision) se recogian con su QTimer sonando y el
   hilo ya muerto: Qt destruia el temporizador desde el hilo de la ventana y avisaba dos
   veces por objeto ("QObject::killTimer" y "QObject::~QObject"). Ahora
   `tareas.parar_en_su_hilo` para cada temporizador en su hilo antes de cerrarlo.
"""

from __future__ import annotations

import gc
import os
import sqlite3
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QObject, QThread, QTimer, QtMsgType, Signal, Slot, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from farmadex import idiomas


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def avisos_qt():
    """Los qWarning de Qt de hilos cruzados durante la prueba (como registro_log en la app)."""
    capturados: list[str] = []

    def manejador(tipo, _contexto, mensaje):
        if tipo in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg) and "another thread" in mensaje:
            capturados.append(mensaje)

    anterior = qInstallMessageHandler(manejador)
    yield capturados
    qInstallMessageHandler(anterior)


def _bombear(app, segundos: float) -> None:
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        time.sleep(0.005)


# -- 1. las sondas de la autoprueba no cambian el hilo en que corre un slot --------------


class _Emisor(QObject):
    senal = Signal(object)

    @Slot()
    def emitir(self):
        self.senal.emit((10, 20))


class _AvisoFalso:
    tipo = None
    hilo = None

    def leyendo(self, *_a):
        _AvisoFalso.hilo = threading.current_thread()

    def esconder(self):
        pass


def _emitir_desde_otro_hilo(app, receptor_slot, segundos: float = 5.0) -> None:
    """Emite desde un QThread y atiende eventos hasta que el receptor haya corrido (o `segundos`)."""
    emisor = _Emisor()
    hilo = QThread()
    emisor.moveToThread(hilo)
    emisor.senal.connect(receptor_slot)
    hilo.started.connect(emisor.emitir)
    _AvisoFalso.hilo = None
    hilo.start()
    try:
        fin = time.monotonic() + segundos
        while _AvisoFalso.hilo is None and time.monotonic() < fin:
            _bombear(app, 0.02)
        _bombear(app, 0.05)
    finally:
        hilo.quit()
        hilo.wait(3000)


def test_sonda_sobre_un_slot_sigue_corriendo_en_el_hilo_del_receptor(app, avisos_qt, monkeypatch):
    from farmadex.autoprueba import Sondas
    from farmadex.ui import vista_objeto

    original = vista_objeto.ControladorVistas.leyendo_precio
    monkeypatch.setattr(vista_objeto.ControladorVistas, "leyendo_precio", original)  # se restaura al acabar
    sondas = Sondas()
    assert sondas.poner(vista_objeto.ControladorVistas, "leyendo_precio")
    controlador = vista_objeto.ControladorVistas(_AvisoFalso(), con_red=False)
    _AvisoFalso.hilo = None
    _emitir_desde_otro_hilo(app, controlador.leyendo_precio)
    assert _AvisoFalso.hilo is threading.main_thread(), "el slot envuelto corrio en el hilo del emisor"
    assert sondas.n("ControladorVistas.leyendo_precio") == 1
    assert avisos_qt == []


def test_un_slot_sustituido_por_una_funcion_normal_corre_en_el_hilo_del_emisor(app, monkeypatch):
    """El comportamiento de PySide6 que obligo al arreglo. Si algun dia deja de pasar,
    esta prueba lo dira y el disfraz de `Sondas.poner` sobrara."""
    from farmadex.ui import vista_objeto

    original = vista_objeto.ControladorVistas.leyendo_precio

    def leyendo_precio(objeto, punto):
        return original(objeto, punto)

    monkeypatch.setattr(vista_objeto.ControladorVistas, "leyendo_precio", leyendo_precio)
    controlador = vista_objeto.ControladorVistas(_AvisoFalso(), con_red=False)
    _AvisoFalso.hilo = None
    _emitir_desde_otro_hilo(app, controlador.leyendo_precio)
    assert _AvisoFalso.hilo is not None
    assert _AvisoFalso.hilo is not threading.main_thread()


# -- 2. al cerrar, cada temporizador se para en su hilo -----------------------------------


class _VigilanteFalso(QObject):
    evento = Signal(str)
    pista = Signal(str, str)
    pantalla = Signal(str, str)
    arranque = Signal(object)

    def __init__(self, *a, **k):
        super().__init__()

    def start(self):
        pass

    def parar(self):
        pass


@pytest.fixture()
def ventana(app, tmp_path, monkeypatch):
    """VentanaOverlay con sus hilos de trabajo de verdad (vigia de vistas, lector pasivo,
    captura, chat); sin EE.log, sin red y sin descargar datos."""
    from farmadex import config, tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db
    from farmadex.ui import overlay

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "conectar", lambda ruta=None: sqlite3.connect(tmp_path / "prueba.sqlite"))
    monkeypatch.setattr(overlay, "VigilanteEELog", _VigilanteFalso)
    idiomas.cargar("es")
    v = overlay.VentanaOverlay()
    v._arrancar_captura()
    yield v
    from farmadex.captura import pantalla

    pantalla.registrar_ocultador(None)


def _temporizadores_activos(objeto) -> list[QTimer]:
    try:
        return [t for t in objeto.findChildren(QTimer) if t.isActive()]
    except RuntimeError:  # ya destruido
        return []


def test_al_cerrar_los_temporizadores_de_otros_hilos_se_paran_en_su_hilo(app, ventana, avisos_qt):
    _bombear(app, 0.4)
    trabajadores = {n: getattr(ventana, n, None) for n in ("vigia_vistas", "lector_pasivo", "lector_fin_mision")}
    assert trabajadores["vigia_vistas"].thread() is not app.thread()
    assert _temporizadores_activos(trabajadores["vigia_vistas"]), "el vigia deberia estar en marcha"
    assert _temporizadores_activos(trabajadores["lector_pasivo"]), "el lector pasivo deberia estar en marcha"

    ventana.cerrar_de_verdad()
    for nombre, objeto in trabajadores.items():
        assert objeto is None or not _temporizadores_activos(objeto), f"{nombre} sigue con su temporizador sonando"
    for hilo in (ventana.hilo_vista, ventana.hilo_pasivo, ventana.hilo_captura):
        assert not hilo.isRunning()
    # Lo que hace Python al salir: recoger la ventana y, con ella, los objetos de los hilos.
    ventana.deleteLater()
    del ventana
    trabajadores.clear()
    _bombear(app, 0.1)
    gc.collect()
    _bombear(app, 0.1)
    assert avisos_qt == []


def test_parar_en_su_hilo_llama_al_slot_en_el_hilo_del_objeto(app):
    from farmadex.tareas import parar_en_su_hilo

    class Trabajador(QObject):
        def __init__(self):
            super().__init__()
            self.hilo_parar = None
            self.temporizador = None

        @Slot()
        def iniciar(self):
            self.temporizador = QTimer(self)
            self.temporizador.start(10)

        @Slot()
        def parar(self):
            self.hilo_parar = QThread.currentThread()
            self.temporizador.stop()

    trabajador = Trabajador()
    hilo = QThread()
    trabajador.moveToThread(hilo)
    hilo.started.connect(trabajador.iniciar)
    hilo.start()
    _bombear(app, 0.2)
    assert trabajador.temporizador.isActive()
    assert parar_en_su_hilo(trabajador) is True
    assert trabajador.hilo_parar is hilo
    assert not trabajador.temporizador.isActive()
    hilo.quit()
    hilo.wait(3000)
    # Con el hilo ya parado se llama directamente, sin encolar a nadie.
    assert parar_en_su_hilo(trabajador) is True
    assert trabajador.hilo_parar is QThread.currentThread()
    assert parar_en_su_hilo(None) is False
    assert parar_en_su_hilo(object()) is False
