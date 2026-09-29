"""Las lecturas de pantalla corren en el hilo de captura, no en el de la ventana.

La 0.6.2 las lanzaba con `QTimer.singleShot(0, lector.leer_ahora)`, y PySide6 ejecuta ese
metodo en el hilo que llama: el OCR de las recompensas, de la build y del agrietado corria
en el hilo de la ventana (la congelaba mientras leia) y a la vez el lector atendia en su
hilo los avisos de EE.log, que llegaban cruzados ("por atajo" en una lectura disparada por
EE.log). Lo destapo la autoprueba (farmadex/autoprueba.py).
"""

import os
import sqlite3
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class LectorFalso(QObject):
    """Lo que la ventana conecta de cualquier lector; apunta en que hilo se lee."""

    estado = Signal(str)
    leidas = Signal(list)
    leida = Signal(object)
    encontrado = Signal(int, str)
    candidatos = Signal(list)
    terminado = Signal(int)
    turno_terminado = Signal(int)
    pagina_perfil = Signal(object)
    pagina_inventario = Signal(object)
    hilos: dict = {}

    def __init__(self, *a, **k):
        super().__init__()
        self.ultima_pedida = 0

    def _apunta(self, que):
        LectorFalso.hilos.setdefault(type(self).__name__, []).append((que, QThread.currentThread()))

    @Slot()
    def arrancar(self):  # como LectorBase.arrancar
        self.iniciar()

    @Slot()
    def iniciar(self):
        self._apunta("iniciar")

    @Slot()
    def leer_ahora(self):
        self._apunta("leer")

    @Slot(int)
    def leer_turno(self, numero):  # como LectorBase.leer_turno
        self._apunta("leer")
        self.turno_terminado.emit(numero)

    @Slot(int)
    def leer_solicitud(self, numero):
        self._apunta("leer")
        self.terminado.emit(numero)

    @Slot(int, int, int, str)
    def leer(self, *a):
        self._apunta("leer")

    @Slot(str)
    def cambiar_motor(self, _m):
        pass

    @Slot(str, str)
    def pista(self, *a):
        pass

    @Slot(str)
    def evento(self, _n):
        pass

    @Slot(str, str)
    def pantalla_juego(self, *a):
        pass

    @Slot(bool)
    def activar_perfil(self, _a):
        pass

    @Slot(bool)
    def activar_inventario(self, _a):
        pass


def _clase(nombre):
    if nombre in ("LectorRecompensas", "LectorBuild", "LectorAgrietado"):
        # Como los de verdad: redefinen `iniciar` (y con eso PySide6 lo corria en la ventana).
        def iniciar(self):
            self._apunta("iniciar")

        return type(nombre, (LectorFalso,), {"iniciar": Slot()(iniciar)})
    return type(nombre, (LectorFalso,), {})


class VigilanteFalso(QObject):
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
def ventana(app, con, tmp_path, monkeypatch):
    from farmadex import config, tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db
    from farmadex.ui import overlay

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "conectar", lambda ruta=None: sqlite3.connect(tmp_path / "prueba.sqlite"))
    for nombre in ("LectorRecompensas", "LectorCursor", "LectorBuild", "LectorAgrietado", "LectorPasivo",
                   "LectorHoverReliquia"):
        monkeypatch.setattr(overlay, nombre, _clase(nombre))
    monkeypatch.setattr(overlay, "VigilanteEELog", VigilanteFalso)
    LectorFalso.hilos = {}
    idiomas.cargar("es")
    v = overlay.VentanaOverlay()
    v._arrancar_captura()
    yield v
    v.hover_reliquias.parar()
    for hilo in (v.hilo_captura, getattr(v, "hilo_pasivo", None)):
        if hilo is not None:
            hilo.quit()
            hilo.wait(3000)
    from farmadex.captura import pantalla

    pantalla.registrar_ocultador(None)


def _esperar(app, condicion, segundos=3.0):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        app.processEvents()
        if condicion():
            return True
        time.sleep(0.005)
    return False


@pytest.mark.parametrize("metodo, lector", [
    ("leer_recompensas", "LectorRecompensas"),
    ("leer_build", "LectorBuild"),
    ("leer_agrietado", "LectorAgrietado"),
    ("leer_cursor", "LectorCursor"),
])
def test_cada_lectura_corre_en_el_hilo_de_captura(app, ventana, metodo, lector):
    getattr(ventana, metodo)()
    assert _esperar(app, lambda: any(q == "leer" for q, _h in LectorFalso.hilos.get(lector, [])))
    hilos = [h for q, h in LectorFalso.hilos[lector] if q == "leer"]
    assert all(h is ventana.hilo_captura for h in hilos)
    assert all(h is not app.thread() for h in hilos)


def test_la_lectura_pasiva_tiene_su_propio_hilo(app, ventana):
    """Su OCR de pantalla entera (hasta ~1 s) no puede hacer esperar a una lectura pedida."""
    assert _esperar(app, lambda: LectorFalso.hilos.get("LectorPasivo"))
    hilo = LectorFalso.hilos["LectorPasivo"][0][1]
    assert hilo is ventana.hilo_pasivo
    assert hilo is not ventana.hilo_captura
    assert ventana.hilo_pasivo.priority() == QThread.LowPriority


def test_al_cerrar_se_para_tambien_el_hilo_pasivo(app, ventana):
    ventana.cerrar_de_verdad()
    assert ventana.hilo_pasivo.isFinished()
    assert ventana.hilo_captura.isFinished()


def test_singleshot_con_un_metodo_corre_en_el_hilo_que_llama(app):
    """La razon del arreglo, para que nadie vuelva a lanzar las lecturas asi."""

    class Objeto(QObject):
        visto = None

        @Slot()
        def metodo(self):
            Objeto.visto = QThread.currentThread()

    hilo = QThread()
    objeto = Objeto()
    objeto.moveToThread(hilo)
    hilo.start()
    try:
        QTimer.singleShot(0, objeto.metodo)
        assert _esperar(app, lambda: Objeto.visto is not None)
        assert Objeto.visto is app.thread()  # no el hilo del objeto
    finally:
        hilo.quit()
        hilo.wait(3000)


@pytest.mark.parametrize("lector", ["LectorRecompensas", "LectorBuild", "LectorAgrietado", "LectorCursor"])
def test_los_lectores_se_preparan_en_el_hilo_de_captura(app, ventana, lector):
    """Preparar el OCR y los casadores cuesta 1-3 s: en la ventana la dejaba congelada al
    arrancar (lo vio el vigia de congelaciones de la autoprueba)."""
    assert _esperar(app, lambda: any(q == "iniciar" for q, _h in LectorFalso.hilos.get(lector, [])))
    hilos = [h for q, h in LectorFalso.hilos[lector] if q == "iniciar"]
    assert all(h is ventana.hilo_captura for h in hilos)


@pytest.mark.parametrize("metodo, tipo", [
    ("leer_recompensas", "reliquias"), ("leer_build", "build"), ("leer_agrietado", "agrietado"),
    ("leer_cursor", "cursor"),
])
def test_el_fin_de_una_lectura_por_atajo_se_atiende_en_el_hilo_de_la_ventana(app, ventana, monkeypatch, metodo, tipo):
    """El "ya termine" llega desde el hilo de captura y tiene que atenderse en el de la
    ventana: con una lambda se atendia en el de captura y tocaba los temporizadores del
    recuadro "Leyendo..." desde alli."""
    import threading

    hilos = []
    original = type(ventana)._turno_terminado

    def espia(self, t, numero):
        hilos.append((t, threading.current_thread() is threading.main_thread()))
        return original(self, t, numero)

    monkeypatch.setattr(type(ventana), "_turno_terminado", espia)
    getattr(ventana, metodo)()
    assert _esperar(app, lambda: hilos)
    assert hilos[0] == (tipo, True)
    assert not ventana.turnos[tipo].ocupado

