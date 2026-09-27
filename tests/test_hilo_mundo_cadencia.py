"""ServicioMundo.cadencia() no puede tocar su QTimer desde otro hilo.

Encontrado en los registros reales de dos usuarios: al cerrarse el juego (o justo
antes de cerrar Farmadex, que esconde la ventana con `ocultar()` antes de salir de
verdad) salian estos avisos de Qt:

    QObject::killTimer: Timers cannot be stopped from another thread
    QObject::startTimer: Timers cannot be started from another thread

Causa: `VentanaOverlay.mostrar()`/`ocultar()` (hilo de la interfaz) llamaban a
`self.servicio_mundo.cadencia(...)` como un metodo normal de Python, pero
`servicio_mundo` vive en `hilo_mundo` (`moveToThread`). `cadencia()` hace
`self.temporizador.setInterval(...)`; con el temporizador activo, Qt reimplementa
eso como parar y volver a arrancar el timer (`killTimer` + `startTimer`), y las dos
llamadas comprueban el hilo del que las llaman y avisan si no es el suyo.

Arreglo: `cadencia()` es ahora un `@Slot(bool)` y `mostrar()`/`ocultar()` lo piden
por una senal (`VentanaOverlay._cadencia_mundo`) conectada tras el `moveToThread`,
asi Qt la pone en cola hasta el hilo de `ServicioMundo` en vez de ejecutarla en el
hilo de quien la pide.

Las pruebas de aqui trabajan directamente con `ServicioMundo` y su `QThread` (sin
levantar la `VentanaOverlay` entera): es el mismo mecanismo exacto que fallaba, sin
arrastrar el resto de la ventana.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    # QApplication, no QCoreApplication: VentanaOverlay es un QWidget.
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def avisos_qt():
    """Captura los qWarning/qCritical de Qt durante la prueba (como registro_log en la app real)."""
    capturados: list[str] = []

    def manejador(tipo, _contexto, mensaje):
        if tipo in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg):
            capturados.append(mensaje)

    anterior = qInstallMessageHandler(manejador)
    yield capturados
    qInstallMessageHandler(anterior)


def _sin_avisos_de_hilo(avisos: list[str]) -> bool:
    """Los dos avisos exactos de los registros reales (killTimer/startTimer cruzando
    hilos). No cuenta el `QObject::~QObject: ...` que sale al destruir en el hilo
    equivocado un QObject con timer activo: es un problema distinto (el momento en que
    Python recoge la basura de un objeto movido a otro hilo, no una llamada nuestra
    entre hilos) y no el que reportaron los usuarios."""
    return not any(("killTimer" in a or "startTimer" in a) and "another thread" in a for a in avisos)


# -- ServicioMundo aislado: el mecanismo exacto que fallaba ------------------------


def _crear_servicio_en_su_hilo(monkeypatch):
    """ServicioMundo de verdad, en su propio QThread, sin tocar la red."""
    from farmadex.online.worldstate import ServicioMundo

    servicio = ServicioMundo(con=None)
    monkeypatch.setattr(servicio, "refrescar", lambda: None)  # sin red en la prueba
    hilo = QThread()
    servicio.moveToThread(hilo)
    hilo.started.connect(servicio.iniciar)
    hilo.start()
    fin = time.monotonic() + 2.0
    while servicio.temporizador is None and time.monotonic() < fin:
        time.sleep(0.01)
    assert servicio.temporizador is not None, "el temporizador no arranco en su hilo"
    assert servicio.temporizador.isActive()
    return servicio, hilo


def test_cadencia_llamada_directa_desde_otro_hilo_avisa(app, monkeypatch, avisos_qt):
    """Documenta el fallo: `cadencia()` a pelo (como hacian antes mostrar()/ocultar())
    sigue avisando si alguien vuelve a llamarla asi en vez de por senal."""
    servicio, hilo = _crear_servicio_en_su_hilo(monkeypatch)
    try:
        # El hilo de la prueba hace de "hilo de la interfaz": distinto de `hilo`,
        # donde vive de verdad el temporizador.
        servicio.cadencia(visible=False)
        time.sleep(0.1)
    finally:
        hilo.quit()
        hilo.wait(2000)
    assert not _sin_avisos_de_hilo(avisos_qt), (
        "se esperaba el aviso de Qt de setInterval() cruzando hilos al llamar a "
        "cadencia() a pelo; si ya no sale, revisa que esta prueba siga probando "
        "lo mismo (una llamada directa entre hilos)"
    )


def test_cadencia_por_senal_no_cruza_hilos(app, monkeypatch, avisos_qt):
    """La forma correcta: una senal en cola hasta el hilo del servicio, sin avisos."""
    from PySide6.QtCore import QObject, Signal

    servicio, hilo = _crear_servicio_en_su_hilo(monkeypatch)

    class Emisor(QObject):
        cadencia = Signal(bool)

    emisor = Emisor()
    emisor.cadencia.connect(servicio.cadencia)
    try:
        emisor.cadencia.emit(False)
        fin = time.monotonic() + 1.0
        while servicio.temporizador.interval() != servicio.SEGUNDOS_OCULTO * 1000 and time.monotonic() < fin:
            time.sleep(0.01)
        assert servicio.temporizador.interval() == servicio.SEGUNDOS_OCULTO * 1000
    finally:
        hilo.quit()
        hilo.wait(2000)
    assert _sin_avisos_de_hilo(avisos_qt), avisos_qt


def test_cerrar_no_cruza_hilos(app, monkeypatch, avisos_qt):
    """El mismo fallo aparecia en `ServicioMundo.cerrar()`, llamado a pelo justo antes
    de `hilo_mundo.quit()` en `VentanaOverlay.cerrar_de_verdad()` (el caso de "poco antes
    de cerrar Farmadex" de los registros reales): antes tambien paraba el temporizador
    a mano desde el hilo de la interfaz."""
    servicio, hilo = _crear_servicio_en_su_hilo(monkeypatch)
    try:
        servicio.cerrar()
        time.sleep(0.1)
    finally:
        hilo.quit()
        hilo.wait(2000)
    assert _sin_avisos_de_hilo(avisos_qt), avisos_qt


# -- VentanaOverlay.mostrar()/ocultar(): que pidan la cadencia por senal ------------


@pytest.fixture()
def ventana(app, con, tmp_path, monkeypatch):
    """VentanaOverlay sin hilos de verdad (igual que test_overlay_datos.py): aqui solo
    interesa que mostrar()/ocultar() no llamen a cadencia() a pelo."""
    import sqlite3

    from farmadex import config, idiomas, tareas
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


def test_mostrar_y_ocultar_piden_la_cadencia_por_senal(ventana):
    """`mostrar()`/`ocultar()` no deben llamar a `servicio_mundo.cadencia(...)` como un
    metodo normal (eso fue lo que crucaba hilos): tienen que pasar por `_cadencia_mundo`,
    que es la senal conectada a `servicio_mundo.cadencia` en `_arrancar_mundo()`."""

    class ServicioMundoFalso:
        def __init__(self):
            self.llamadas_directas: list[bool] = []

        def cadencia(self, visible: bool) -> None:
            # Si mostrar()/ocultar() siguieran llamando aqui a pelo, se veria aqui.
            self.llamadas_directas.append(visible)

    ventana.servicio_mundo = ServicioMundoFalso()
    recibidas: list[bool] = []
    ventana._cadencia_mundo.connect(recibidas.append)

    ventana.mostrar()
    ventana.ocultar()

    assert ventana.servicio_mundo.llamadas_directas == [], (
        "mostrar()/ocultar() estan llamando a cadencia() directamente otra vez: "
        "eso es justo lo que cruzaba hilos con el QTimer de ServicioMundo"
    )
    assert recibidas == [True, False]


def test_minimizar_y_restaurar_piden_la_cadencia_por_senal(ventana):
    """`changeEvent()` (minimizar/restaurar: barra de tareas, atajo, o el propio Windows
    al perder foco cuando el juego se cierra) tampoco puede llamar a `cadencia()` a pelo."""
    from PySide6.QtWidgets import QApplication

    class ServicioMundoFalso:
        def __init__(self):
            self.llamadas_directas: list[bool] = []

        def cadencia(self, visible: bool) -> None:
            self.llamadas_directas.append(visible)

    ventana.servicio_mundo = ServicioMundoFalso()
    recibidas: list[bool] = []
    ventana._cadencia_mundo.connect(recibidas.append)

    ventana.show()
    QApplication.processEvents()
    ventana.showMinimized()
    QApplication.processEvents()
    ventana.showNormal()
    QApplication.processEvents()

    assert ventana.servicio_mundo.llamadas_directas == [], (
        "changeEvent() esta llamando a cadencia() directamente otra vez"
    )
    # Al menos un "minimizada" (False) y un "restaurada" (True) tienen que haber
    # llegado por la senal para que el mundo siga bajando/subiendo el ritmo.
    assert False in recibidas and True in recibidas, recibidas
