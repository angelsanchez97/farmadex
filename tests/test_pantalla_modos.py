"""Modos de pantalla del juego, probados contra una ventana Win32 que imita a Warframe.

No hace falta el juego: se crea una ventana real con su titulo en cada modo
(con marco, sin bordes a pantalla completa) y se comprueba que la deteccion, la
region de captura y el recuadro del cursor salen donde tienen que salir. La
pantalla completa exclusiva no se puede reproducir sin Direct3D: ahi se simula la
respuesta de Windows (SHQueryUserNotificationState).
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

import pytest

from farmadex.captura import pantalla
from farmadex.captura.reliquias import FRANJA

solo_windows = pytest.mark.skipif(sys.platform != "win32", reason="ventanas Win32")

# Las pruebas que crean una ventana Win32 real corren en un interprete aparte: en el
# mismo proceso que el QApplication de las demas pruebas, el bucle de mensajes de Qt
# despacha los mensajes de esa ventana y el interprete se cae (fallo de acceso, no una
# asercion). `test_ventanas_win32_en_proceso_aparte` las lanza; aqui se saltan.
VARIABLE_SUBPROCESO = "FARMADEX_PRUEBAS_VENTANA_WIN32"
EN_SUBPROCESO = os.environ.get(VARIABLE_SUBPROCESO) == "1"
ventana_real = pytest.mark.skipif(
    not EN_SUBPROCESO, reason="corre en su propio proceso (test_ventanas_win32_en_proceso_aparte)"
)


@solo_windows
def test_ventanas_win32_en_proceso_aparte():
    if EN_SUBPROCESO:
        pytest.skip("ya estamos en el proceso aparte")
    entorno = {**os.environ, VARIABLE_SUBPROCESO: "1", "QT_QPA_PLATFORM": "offscreen"}
    resultado = subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__).resolve()), "-q",
         "-p", "no:cacheprovider", "-m", "ventana_win32"],
        capture_output=True, text=True, env=entorno, timeout=300,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert resultado.returncode == 0, (resultado.stdout[-4000:] + resultado.stderr[-2000:])
    assert " passed" in resultado.stdout

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
SW_SHOWNA = 8
CLASE = "FarmadexPruebaWarframe"

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


_proc = None  # el callback tiene que seguir vivo mientras exista la clase


def _registrar_clase() -> None:
    global _proc
    if _proc is not None:
        return
    user32 = ctypes.windll.user32
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _proc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
    clase = WNDCLASSW()
    clase.lpfnWndProc = _proc
    clase.lpszClassName = CLASE
    clase.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    user32.RegisterClassW(ctypes.byref(clase))  # si ya existe, falla y da igual


@pytest.fixture()
def ventana_falsa():
    """Crea una ventana visible titulada 'Warframe' con el estilo y tamano que se pidan."""
    creadas = []
    user32 = ctypes.windll.user32
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    _registrar_clase()

    def crear(estilo: int, x: int, y: int, ancho: int, alto: int) -> int:
        hwnd = user32.CreateWindowExW(
            0, CLASE, "Warframe", estilo | WS_VISIBLE, x, y, ancho, alto, None, None,
            ctypes.windll.kernel32.GetModuleHandleW(None), None,
        )
        assert hwnd, ctypes.get_last_error()
        user32.ShowWindow(hwnd, SW_SHOWNA)
        creadas.append(hwnd)
        return hwnd

    yield crear
    for hwnd in creadas:
        user32.DestroyWindow(hwnd)


def _client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """(x, y, ancho, alto) del area de cliente en pantalla, calculado a mano."""
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    punto = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(punto))
    return punto.x, punto.y, rect.right, rect.bottom


# --- modo ventana ---------------------------------------------------------------

@solo_windows
@ventana_real
@pytest.mark.ventana_win32
def test_modo_ventana_se_detecta_y_se_captura_solo_el_area_de_cliente(ventana_falsa):
    hwnd = ventana_falsa(WS_OVERLAPPEDWINDOW, 120, 90, 800, 600)

    assert pantalla.ventana_juego() == hwnd
    assert pantalla.modo_pantalla(hwnd) == pantalla.MODO_VENTANA

    region = pantalla.region_ventana(hwnd)
    x, y, ancho, alto = _client_rect(hwnd)
    assert (region.x, region.y, region.ancho, region.alto) == (x, y, ancho, alto)
    # El marco y la barra de titulo quedan fuera: el cliente empieza mas abajo y a la derecha.
    marco = pantalla.region_marco(hwnd)
    assert region.y > marco.y and region.x >= marco.x
    assert region.ancho < marco.ancho and region.alto < marco.alto

    # region_objetivo devuelve la ventana, no la pantalla entera.
    objetivo = pantalla.region_objetivo()
    assert (objetivo.x, objetivo.y, objetivo.ancho, objetivo.alto) == (x, y, ancho, alto)

    # La franja de recompensas se recorta en proporciones DENTRO del cliente.
    franja = objetivo.recortar(*FRANJA)
    assert franja.x >= objetivo.x and franja.y >= objetivo.y
    assert franja.x + franja.ancho <= objetivo.x + objetivo.ancho
    assert franja.y + franja.alto <= objetivo.y + objetivo.alto
    assert franja.x == round(x + ancho * FRANJA[0]) and franja.y == round(y + alto * FRANJA[1])


@solo_windows
@ventana_real
@pytest.mark.ventana_win32
def test_en_modo_ventana_el_recuadro_del_cursor_no_se_sale_del_juego(ventana_falsa, monkeypatch):
    hwnd = ventana_falsa(WS_OVERLAPPEDWINDOW, 300, 200, 500, 400)
    juego = pantalla.region_ventana(hwnd)

    # Raton en la esquina superior izquierda del juego: el recuadro se pega al borde
    # del juego, no al del escritorio.
    monkeypatch.setattr(pantalla, "_posicion_cursor", lambda: (juego.x + 5, juego.y + 5))
    region = pantalla.region_alrededor_del_cursor(620, 170, limite=pantalla.region_juego())
    assert (region.x, region.y) == (juego.x, juego.y)
    assert region.ancho <= juego.ancho and region.alto <= juego.alto

    # Raton en la esquina inferior derecha.
    monkeypatch.setattr(
        pantalla, "_posicion_cursor", lambda: (juego.x + juego.ancho - 3, juego.y + juego.alto - 3)
    )
    region = pantalla.region_alrededor_del_cursor(620, 170, limite=pantalla.region_juego())
    assert region.x + region.ancho == juego.x + juego.ancho
    assert region.y + region.alto == juego.y + juego.alto

    # Raton fuera del juego: se usa el escritorio, como siempre.
    monkeypatch.setattr(pantalla, "_posicion_cursor", lambda: (juego.x - 50, juego.y - 50))
    monkeypatch.setattr(pantalla, "_escritorio_virtual", lambda: pantalla.Region(0, 0, 3000, 2000))
    region = pantalla.region_alrededor_del_cursor(620, 170, limite=pantalla.region_juego())
    assert region.x < juego.x


@solo_windows
@ventana_real
@pytest.mark.ventana_win32
def test_una_ventana_pequena_sin_marco_sigue_siendo_modo_ventana(ventana_falsa):
    # Un popup que no llena el monitor no es "sin bordes a pantalla completa".
    hwnd = ventana_falsa(WS_POPUP, 50, 50, 640, 360)
    assert pantalla.modo_pantalla(hwnd) == pantalla.MODO_VENTANA


# --- sin bordes -----------------------------------------------------------------

@solo_windows
@ventana_real
@pytest.mark.ventana_win32
def test_sin_bordes_a_pantalla_completa(ventana_falsa, monkeypatch):
    monitor = pantalla.region_pantalla_completa()
    hwnd = ventana_falsa(WS_POPUP, monitor.x, monitor.y, monitor.ancho, monitor.alto)

    # Windows no dice que sea Direct3D exclusivo: es una ventana sin bordes.
    monkeypatch.setattr(pantalla, "_ventana_activa", lambda: hwnd)
    monkeypatch.setattr(pantalla, "_estado_notificaciones", lambda: 5)  # QUNS_ACCEPTS_NOTIFICATIONS
    assert pantalla.modo_pantalla(hwnd) == pantalla.MODO_SIN_BORDES

    # La captura cubre el monitor entero, como hasta ahora.
    region = pantalla.region_ventana(hwnd)
    assert (region.ancho, region.alto) == (monitor.ancho, monitor.alto)


# --- pantalla completa exclusiva ------------------------------------------------

@solo_windows
@ventana_real
@pytest.mark.ventana_win32
def test_exclusiva_se_detecta_solo_con_la_senal_de_windows(ventana_falsa, monkeypatch):
    monitor = pantalla.region_pantalla_completa()
    hwnd = ventana_falsa(WS_POPUP, monitor.x, monitor.y, monitor.ancho, monitor.alto)

    monkeypatch.setattr(pantalla, "_ventana_activa", lambda: hwnd)
    monkeypatch.setattr(
        pantalla, "_estado_notificaciones", lambda: pantalla.QUNS_RUNNING_D3D_FULL_SCREEN
    )
    assert pantalla.modo_pantalla(hwnd) == pantalla.MODO_EXCLUSIVO

    # Si el juego no es la ventana activa, no se puede saber: se supone sin bordes.
    monkeypatch.setattr(pantalla, "_ventana_activa", lambda: 0)
    assert pantalla.modo_pantalla(hwnd) == pantalla.MODO_SIN_BORDES


def test_sin_juego_el_modo_es_desconocido(monkeypatch):
    monkeypatch.setattr(pantalla, "ventana_juego", lambda: None)
    assert pantalla.modo_pantalla() == pantalla.MODO_DESCONOCIDO
    assert pantalla.region_juego() is None


def test_region_contiene_y_centro():
    r = pantalla.Region(10, 20, 100, 50)
    assert r.contiene(10, 20) and r.contiene(109, 69)
    assert not r.contiene(110, 20) and not r.contiene(9, 20)
    assert r.centro == (60, 45)


def test_resumen_en_texto_de_las_recompensas():
    from farmadex.captura.reliquias import Recompensa, resumir

    recompensas = [
        Recompensa(1, "Sistemas de Ash Prime", "SISTEMAS", (0, 0, 1, 1), ducados=45, vaulted=True,
                   objetivo="1/2", platino=30),
        Recompensa(2, "Forma", "FORMA", (0, 0, 1, 1)),
    ]
    texto = resumir(recompensas)
    assert "Sistemas de Ash Prime (30 platino, 45 ducados, En boveda, Objetivo: 1/2)" in texto
    assert texto.endswith("Forma")
