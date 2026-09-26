"""Un solo Farmadex abierto: candado, tuberia de ordenes, arranque duplicado y cierre.

Cada prueba usa nombres de mutex y de tuberia propios (con uuid) para no chocar con
un Farmadex de verdad que el usuario tenga abierto mientras se pasan las pruebas.
"""

from __future__ import annotations

import ctypes
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import app as modulo_app  # noqa: E402
from farmadex import instancia_unica  # noqa: E402
from farmadex.instancia_unica import InstanciaUnica, avisar_a_la_abierta  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
solo_windows = pytest.mark.skipif(os.name != "nt", reason="mutex y tuberias con nombre de Windows")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def nombres():
    sufijo = uuid.uuid4().hex[:10]
    return f"FarmadexPrueba-{sufijo}", f"FarmadexPruebaMutex-{sufijo}"


def _en_hilo(funcion, *args, **kw):
    """Lo que en la vida real hace OTRO proceso: la tuberia solo termina de escribir
    cuando el que escucha lee, y aqui el que escucha es este hilo con su bucle de Qt."""
    resultado = {}
    hilo = threading.Thread(target=lambda: resultado.setdefault("valor", funcion(*args, **kw)), daemon=True)
    hilo.start()
    return hilo, resultado


def _avisar_desde_otro_proceso(orden: str, tuberia: str):
    """Un segundo Farmadex de verdad: QLocalSocket necesita su propio proceso (en un hilo
    suelto de Python, sin bucle de Qt, la escritura no termina nunca)."""
    import subprocess

    codigo = (
        "import sys; from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]); "
        "from farmadex.instancia_unica import avisar_a_la_abierta as f; "
        f"sys.exit(0 if f({orden!r}, nombre={tuberia!r}, espera_s=2) else 3)"
    )
    entorno = dict(os.environ, PYTHONPATH=str(RAIZ / "src"), QT_QPA_PLATFORM="offscreen")
    return subprocess.Popen([sys.executable, "-c", codigo], env=entorno)


def _esperar(qapp, condicion, segundos=3.0):
    limite = time.monotonic() + segundos
    while not condicion() and time.monotonic() < limite:
        qapp.processEvents()
        time.sleep(0.01)
    return condicion()


@solo_windows
def test_el_segundo_no_consigue_el_candado_hasta_que_el_primero_lo_suelta(qapp, nombres):
    tuberia, mutex = nombres
    primero, segundo = InstanciaUnica(tuberia, mutex), InstanciaUnica(tuberia, mutex)
    assert primero.adquirir()
    assert not segundo.adquirir()
    primero.soltar()
    assert segundo.adquirir()
    segundo.soltar()


@solo_windows
def test_la_orden_llega_y_se_guarda_hasta_que_alguien_escucha(qapp, nombres):
    tuberia, mutex = nombres
    abierta = InstanciaUnica(tuberia, mutex)
    assert abierta.adquirir() and abierta.escuchar()
    recibidas = []
    abierta.orden_recibida.connect(recibidas.append)
    try:
        # La ventana aun no esta montada: la orden se guarda, no se pierde.
        otro = _avisar_desde_otro_proceso("mostrar", tuberia)
        assert _esperar(qapp, lambda: abierta.pendientes == ["mostrar"] and otro.poll() is not None, 20)
        assert otro.returncode == 0
        assert recibidas == []
        abierta.entregar_pendientes()
        assert recibidas == ["mostrar"]
        # A partir de ahi, llegan al momento.
        otro = _avisar_desde_otro_proceso("salir", tuberia)
        assert _esperar(qapp, lambda: recibidas == ["mostrar", "salir"] and otro.poll() is not None, 20)
    finally:
        abierta.soltar()


@solo_windows
def test_una_orden_desconocida_se_ignora(qapp, nombres):
    tuberia, mutex = nombres
    abierta = InstanciaUnica(tuberia, mutex)
    abierta.adquirir()
    abierta.escuchar()
    abierta.entregar_pendientes()
    recibidas = []
    abierta.orden_recibida.connect(recibidas.append)
    try:
        otro = _avisar_desde_otro_proceso("formatea el disco", tuberia)
        assert _esperar(qapp, lambda: otro.poll() is not None, 20)
        _esperar(qapp, lambda: False, segundos=0.2)
        assert recibidas == []
    finally:
        abierta.soltar()


def test_sin_nadie_escuchando_avisar_devuelve_false_y_no_se_cuelga(qapp):
    inicio = time.monotonic()
    assert not avisar_a_la_abierta("mostrar", nombre=f"FarmadexNadie-{uuid.uuid4().hex}", espera_s=0.3)
    assert time.monotonic() - inicio < 3


@solo_windows
def test_el_instalador_puede_pedir_el_cierre_escribiendo_en_la_tuberia_a_pelo(qapp, nombres):
    """Lo mismo que hace PedirCierreFarmadex en instalador.iss: CreateFileW + WriteFile,
    sin Qt. Asi se comprueba el nombre de la tuberia y el protocolo de una linea."""
    tuberia, mutex = nombres
    abierta = InstanciaUnica(tuberia, mutex)
    abierta.adquirir()
    abierta.escuchar()
    abierta.entregar_pendientes()
    recibidas = []
    abierta.orden_recibida.connect(recibidas.append)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    k32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32,
                              ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]

    def escribir_a_pelo():
        handle = k32.CreateFileW("\\\\.\\pipe\\" + tuberia, 0x40000000, 0, None, 3, 0, None)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return False
        escritos = ctypes.c_uint32(0)
        ok = bool(k32.WriteFile(handle, b"salir\n", 6, ctypes.byref(escritos), None))
        k32.CloseHandle(handle)
        return ok

    try:
        hilo, res = _en_hilo(escribir_a_pelo)
        assert _esperar(qapp, lambda: recibidas == ["salir"])
        hilo.join(3)
        assert res["valor"] is True
    finally:
        abierta.soltar()


def test_el_instalador_usa_el_mismo_nombre_de_tuberia_y_mutex():
    iss = (RAIZ / "empaquetado" / "instalador.iss").read_text(encoding="utf-8")
    prefijo = re.search(r"PrefijoTuberia = '([^']+)'", iss).group(1)
    assert prefijo == "\\\\.\\pipe\\" + instancia_unica.PREFIJO_TUBERIA
    assert "GetUserNameString" in iss and "'salir' + #10" in iss
    assert instancia_unica.nombre_tuberia("ana") == instancia_unica.PREFIJO_TUBERIA + "ana"
    # Y el instalador limpia las librerias viejas antes de copiar las nuevas.
    assert re.search(r'^\[InstallDelete\]\s*\n(?:;.*\n)*Type: filesandordirs; Name: "\{app\}\\_internal"', iss, re.M)


# -- arranque duplicado -----------------------------------------------------------


@pytest.fixture()
def main_sin_efectos(qapp, monkeypatch):
    """main() sin tocar ganchos globales ni montar la aplicacion de verdad."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "unraisablehook", sys.unraisablehook)
    monkeypatch.setattr(modulo_app, "instalar_gancho_excepciones", lambda *a, **k: None)
    montadas = []

    class AplicacionFalsa:
        def __init__(self, *a, **k):
            montadas.append(k)

        def ejecutar(self):
            return 0

    monkeypatch.setattr(modulo_app, "Aplicacion", AplicacionFalsa)
    monkeypatch.setattr(modulo_app, "vigilar_cierre", lambda codigo: None)
    return montadas


def test_si_ya_hay_uno_abierto_se_le_pide_que_se_ensene_y_este_se_va(main_sin_efectos, monkeypatch):
    avisos = []
    monkeypatch.setattr(InstanciaUnica, "adquirir", lambda self: False)
    monkeypatch.setattr(instancia_unica, "avisar_a_la_abierta", lambda orden="mostrar", **k: avisos.append(orden) or True)
    assert modulo_app.main(["Farmadex.exe"]) == 0
    assert avisos == ["mostrar"]
    assert main_sin_efectos == []  # no se monta otra ventana


def test_arrancado_con_windows_y_ya_abierto_no_hace_nada(main_sin_efectos, monkeypatch):
    avisos = []
    monkeypatch.setattr(InstanciaUnica, "adquirir", lambda self: False)
    monkeypatch.setattr(instancia_unica, "avisar_a_la_abierta", lambda orden="mostrar", **k: avisos.append(orden))
    assert modulo_app.main(["Farmadex.exe", "--bandeja"]) == 0
    assert avisos == [] and main_sin_efectos == []


def test_el_primero_escucha_antes_de_montar_la_ventana(main_sin_efectos, monkeypatch):
    orden = []
    monkeypatch.setattr(InstanciaUnica, "adquirir", lambda self: orden.append("adquirir") or True)
    monkeypatch.setattr(InstanciaUnica, "escuchar", lambda self: orden.append("escuchar") or True)
    monkeypatch.setattr(InstanciaUnica, "soltar", lambda self: orden.append("soltar"))
    assert modulo_app.main(["Farmadex.exe"]) == 0
    assert orden[:2] == ["adquirir", "escuchar"] and orden[-1] == "soltar"
    assert len(main_sin_efectos) == 1 and main_sin_efectos[0]["instancia"] is not None


def test_cerrar_pide_salir_y_espera(main_sin_efectos, monkeypatch):
    llamadas = []
    monkeypatch.setattr(instancia_unica, "avisar_a_la_abierta", lambda orden, **k: llamadas.append(orden) or True)
    monkeypatch.setattr(instancia_unica, "esperar_a_que_se_cierre", lambda **k: True)
    assert modulo_app.main(["Farmadex.exe", "--cerrar"]) == 0
    assert llamadas == ["salir"] and main_sin_efectos == []


# -- la version vieja se muere de verdad al salir -------------------------------------


def test_el_vigilante_corta_el_proceso_si_no_termina_solo():
    cortes = []
    temporizador = modulo_app.vigilar_cierre(3, espera_s=0.05, salir=cortes.append)
    temporizador.join(2)
    assert cortes == [3]
    assert temporizador.daemon  # si Python sale por las buenas, no retiene nada


def test_la_orden_salir_cierra_la_aplicacion_y_suelta_el_candado():
    """Aplicacion._orden_externa y salir(), sin construir la ventana de verdad."""
    hechos = []

    class Falso:
        pass

    app = modulo_app.Aplicacion.__new__(modulo_app.Aplicacion)
    app.log = modulo_app.obtener("prueba")
    app._saliendo = False
    app.hotkeys = None
    app.ventana = Falso()
    app.ventana.cerrar_de_verdad = lambda: hechos.append("ventana")
    app.ventana.mostrar = lambda: hechos.append("mostrar")
    app.bandeja = Falso()
    app.bandeja.hide = lambda: hechos.append("bandeja")
    app.instancia = Falso()
    app.instancia.soltar = lambda: hechos.append("soltar")
    app.qt = Falso()
    app.qt.quit = lambda: hechos.append("quit")

    app._orden_externa("mostrar")
    app._orden_externa("salir")
    app._orden_externa("salir")  # dos veces no cierra dos veces
    assert hechos == ["mostrar", "ventana", "bandeja", "soltar", "quit"]


def test_salir_sale_aunque_falle_el_cierre_de_la_ventana():
    hechos = []

    class Falso:
        pass

    app = modulo_app.Aplicacion.__new__(modulo_app.Aplicacion)
    app.log = modulo_app.obtener("prueba")
    app._saliendo = False
    app.hotkeys = None
    app.ventana = Falso()
    app.ventana.cerrar_de_verdad = lambda: 1 / 0
    app.bandeja = Falso()
    app.bandeja.hide = lambda: hechos.append("bandeja")
    app.instancia = None
    app.qt = Falso()
    app.qt.quit = lambda: hechos.append("quit")
    app.salir()
    assert hechos == ["bandeja", "quit"]
