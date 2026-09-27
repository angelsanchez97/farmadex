"""Captura de pantalla de la ventana del juego.

Solo se leen pixeles de la pantalla, como hace cualquier programa de captura:
no se lee memoria del juego, no se inyecta nada y no se envia ninguna entrada.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass

from ..registro_log import obtener

log = obtener("pantalla")

TITULOS_JUEGO = ("Warframe",)
CLASES_JUEGO = ("Qt5QWindowIcon", "WarframePublicEvolutionGfxD3D11", "D3D Window")


@dataclass
class Region:
    x: int
    y: int
    ancho: int
    alto: int

    @property
    def caja(self) -> dict:
        return {"left": self.x, "top": self.y, "width": self.ancho, "height": self.alto}

    def contiene(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.ancho and self.y <= y < self.y + self.alto

    @property
    def centro(self) -> tuple[int, int]:
        return self.x + self.ancho // 2, self.y + self.alto // 2

    def recortar(self, izq: float, arr: float, der: float, aba: float) -> "Region":
        """Subregion en proporciones (0..1) sobre esta region."""
        return Region(
            round(self.x + self.ancho * izq),
            round(self.y + self.alto * arr),
            max(1, round(self.ancho * (der - izq))),
            max(1, round(self.alto * (aba - arr))),
        )


def declarar_dpi() -> None:
    """Sin esto, Windows escala las coordenadas y la captura sale movida."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):  # pragma: no cover - fuera de Windows
            pass


def ventana_juego() -> int | None:
    """Devuelve el HWND de Warframe, o None si no esta abierto."""
    user32 = ctypes.windll.user32
    encontrado = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visitar(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        largo = user32.GetWindowTextLengthW(hwnd)
        if largo == 0:
            return True
        buffer = ctypes.create_unicode_buffer(largo + 1)
        user32.GetWindowTextW(hwnd, buffer, largo + 1)
        if buffer.value.strip() in TITULOS_JUEGO:
            encontrado.append(hwnd)
            return False
        return True

    user32.EnumWindows(visitar, 0)
    return encontrado[0] if encontrado else None


def region_ventana(hwnd: int) -> Region | None:
    """Area de cliente de la ventana, en coordenadas de pantalla.

    Devuelve None si la ventana esta minimizada (area vacia) o si ya no existe.
    """
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return None
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    punto = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(punto)):
        return None
    ancho, alto = rect.right - rect.left, rect.bottom - rect.top
    if ancho <= 0 or alto <= 0:
        return None
    return Region(punto.x, punto.y, ancho, alto)


# Metricas del escritorio virtual (todos los monitores juntos), no solo el primario.
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79


def _escritorio_virtual() -> Region:
    user32 = ctypes.windll.user32
    return Region(
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def _posicion_cursor() -> tuple[int, int]:
    punto = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(punto))
    return punto.x, punto.y


def region_pantalla_completa() -> Region:
    """El monitor primario (donde el juego va a pantalla completa casi siempre)."""
    user32 = ctypes.windll.user32
    return Region(0, 0, max(1, user32.GetSystemMetrics(0)), max(1, user32.GetSystemMetrics(1)))


def region_alrededor_del_cursor(
    ancho: int = 620, alto: int = 170, limite: Region | None = None
) -> Region:
    """Recuadro centrado en el raton, sin salirse del escritorio (con varios monitores).

    Si se pasa `limite` (la ventana del juego) y el raton esta dentro, el recuadro
    no se sale de ella: con el juego en una ventana pequena, leer el escritorio de
    alrededor solo mete ruido en el OCR.
    """
    cx, cy = _posicion_cursor()
    marco = _escritorio_virtual()
    if limite and limite.contiene(cx, cy):
        marco = limite
    ancho = min(ancho, marco.ancho)
    alto = min(alto, marco.alto)
    x = max(marco.x, min(cx - ancho // 2, marco.x + marco.ancho - ancho))
    y = max(marco.y, min(cy - alto // 2, marco.y + marco.alto - alto))
    return Region(x, y, ancho, alto)


# -- modo de pantalla del juego ---------------------------------------------------

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
# SHQueryUserNotificationState: la ventana activa es una aplicacion Direct3D en
# pantalla completa exclusiva. Es la unica senal fiable que da Windows para
# distinguirla de una ventana sin bordes, que por tamano y estilo es identica.
QUNS_RUNNING_D3D_FULL_SCREEN = 3

MODO_VENTANA = "ventana"
MODO_SIN_BORDES = "sin_bordes"
MODO_EXCLUSIVO = "exclusivo"
MODO_DESCONOCIDO = "desconocido"


def _estilo(hwnd: int) -> int:
    return ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)


def _ventana_activa() -> int:
    # Con el tipo declarado: sin el, ctypes lo trunca a 32 bits con signo.
    ctypes.windll.user32.GetForegroundWindow.restype = wintypes.HWND
    return ctypes.windll.user32.GetForegroundWindow() or 0


def _estado_notificaciones() -> int:
    """Codigo QUNS_* de Windows; 0 si la llamada no esta disponible."""
    estado = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(estado)) != 0:
            return 0
    except (AttributeError, OSError):  # pragma: no cover - shell32 sin la funcion
        return 0
    return estado.value


def region_marco(hwnd: int) -> Region | None:
    """La ventana entera, con bordes y titulo, en coordenadas de pantalla."""
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return Region(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def monitor_de(hwnd: int) -> Region | None:
    """El monitor donde esta (o mas cerca esta) la ventana."""
    MONITOR_DEFAULTTONEAREST = 2
    user32 = ctypes.windll.user32
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return None
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    r = info.rcMonitor
    return Region(r.left, r.top, r.right - r.left, r.bottom - r.top)


def modo_pantalla(hwnd: int | None = None) -> str:
    """En que modo esta Warframe: ventana, sin bordes, exclusivo o desconocido.

    - Con barra de titulo (WS_CAPTION), o sin llenar el monitor: `ventana`.
    - Sin bordes y llenando el monitor: `sin_bordes`, salvo que Windows diga que la
      ventana activa es Direct3D en pantalla completa exclusiva, que es `exclusivo`.
      Eso solo se puede saber mientras el juego es la ventana activa; si no lo es,
      se supone sin bordes, que es el caso habitual.
    - Sin ventana del juego: `desconocido`.
    """
    hwnd = hwnd or ventana_juego()
    if not hwnd:
        return MODO_DESCONOCIDO
    if _estilo(hwnd) & WS_CAPTION:
        return MODO_VENTANA
    marco, monitor = region_marco(hwnd), monitor_de(hwnd)
    if marco and monitor and (marco.ancho, marco.alto) != (monitor.ancho, monitor.alto):
        return MODO_VENTANA
    if _ventana_activa() == hwnd and _estado_notificaciones() == QUNS_RUNNING_D3D_FULL_SCREEN:
        return MODO_EXCLUSIVO
    return MODO_SIN_BORDES


def escala_fisica_logica(hwnd: int | None = None) -> float:
    """Pixeles fisicos por pixel logico del monitor del juego (1.0, 1.25, 1.5...).

    La captura y las coordenadas de Win32 van en pixeles fisicos; Qt pinta en
    logicos. Sin dividir por esto, con Windows al 125 % las etiquetas caen a un
    lado de la tarjeta.
    """
    try:
        hwnd = hwnd or ventana_juego()
        user32 = ctypes.windll.user32
        ppp = user32.GetDpiForWindow(hwnd) if hwnd else user32.GetDpiForSystem()
        return (ppp or 96) / 96.0
    except (AttributeError, OSError):  # pragma: no cover - Windows anterior a 1607
        return 1.0


def capturar(region: Region):
    """Devuelve la region como array numpy BGR, o None si no se pudo capturar.

    Farmadex esta siempre encima del juego, y una captura de pantalla recoge lo que
    se ve: con la ventana (o las etiquetas, el panel, la tarjeta de reliquia...) encima
    de lo que hay que leer, el OCR leia Farmadex en vez del juego. Por eso, justo antes
    de capturar, las ventanas de Farmadex que tapan la region se hacen invisibles un
    instante (ver `ocultando`). No se usa la exclusion de captura de Windows
    (WDA_EXCLUDEFROMCAPTURE) porque tambien las quitaria del directo en OBS.
    """
    with ocultando(region):
        return _capturar_crudo(region)


def capturar_sin_ocultar(region: Region):
    """Como `capturar`, pero sin tocar las ventanas de Farmadex (lecturas periodicas).

    La lectura pasiva mira la pantalla cada poco: esconder Farmadex en cada vuelta lo
    haria parpadear todo el rato. Esas lecturas usan esto y luego `descartar_propias`.
    """
    return _capturar_crudo(region)


def _capturar_crudo(region: Region):
    """La region tal cual esta en pantalla ahora mismo, como array numpy BGR, o None."""
    try:
        import mss
        import numpy as np
    except ImportError as e:  # pragma: no cover - dependencia del empaquetado
        log.error("Falta una dependencia de captura: %s", e)
        return None
    if region.ancho <= 0 or region.alto <= 0:
        return None
    try:
        with mss.mss() as camara:
            crudo = camara.grab(region.caja)
        # BGRA -> BGR contiguo (el OCR y cv2 quieren el array seguido en memoria).
        return np.ascontiguousarray(np.array(crudo)[:, :, :3])
    except Exception as e:  # noqa: BLE001 - mss lanza de todo segun el driver
        log.warning("No se pudo capturar la pantalla: %s", e)
        return None


# -- nuestras propias ventanas ----------------------------------------------------
#
# El mecanismo de esconder vive en la interfaz (ui/ocultar_captura.py), que es la que
# puede tocar las ventanas desde el hilo de Qt; aqui solo hay un gancho para que este
# modulo siga sin depender de Qt. Sin ocultador registrado (herramientas, pruebas),
# `capturar` captura sin mas.

_ocultador = None


def registrar_ocultador(ocultador) -> None:
    """`ocultador.ocultar(region) -> ficha | None` y `ocultador.restaurar(ficha)`; None lo quita."""
    global _ocultador
    _ocultador = ocultador


class ocultando:
    """`with ocultando(region):` esconde lo nuestro que tape `region` y lo devuelve al salir.

    Pase lo que pase dentro (excepcion incluida), al salir se piden restaurar las
    ventanas. Si el ocultador falla, se captura igual: mejor una lectura con Farmadex
    delante que ninguna.
    """

    def __init__(self, region: Region):
        self.region = region
        self.ficha = None
        self.ocultador = None
        self.segundos = 0.0  # lo que ha costado esconder (y esperar al compositor)

    def __enter__(self):
        self.ocultador = _ocultador
        if self.ocultador is None:
            return self
        t0 = time.perf_counter()
        try:
            self.ficha = self.ocultador.ocultar(self.region)
        except Exception:  # noqa: BLE001 - la captura va por delante
            log.exception("No se pudo esconder Farmadex antes de capturar")
            self.ficha = None
        self.segundos = time.perf_counter() - t0
        return self

    def __exit__(self, *_exc):
        ficha, self.ficha = self.ficha, None
        if ficha is not None and self.ocultador is not None:
            try:
                self.ocultador.restaurar(ficha)
            except Exception:  # noqa: BLE001 - el temporizador de seguridad la devuelve igual
                log.exception("No se pudo devolver Farmadex tras capturar")
        return False


def interseccion(a: Region, b: Region) -> Region | None:
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x + a.ancho, b.x + b.ancho), min(a.y + a.alto, b.y + b.alto)
    if x1 <= x0 or y1 <= y0:
        return None
    return Region(x0, y0, x1 - x0, y1 - y0)


def ventanas_propias() -> list[Region]:
    """Rectangulos (pixeles fisicos) de las ventanas visibles de este proceso.

    Solo Win32, sin Qt: vale desde cualquier hilo. Las que estan a opacidad 0 (las que
    se acaban de esconder) no cuentan.
    """
    try:
        user32 = ctypes.windll.user32
    except AttributeError:  # pragma: no cover - fuera de Windows
        return []
    pid_propio = os.getpid()
    encontradas: list[Region] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visitar(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != pid_propio:
                return True
            alfa, banderas = ctypes.c_ubyte(255), wintypes.DWORD(0)
            if (user32.GetLayeredWindowAttributes(hwnd, None, ctypes.byref(alfa), ctypes.byref(banderas))
                    and banderas.value & LWA_ALPHA and alfa.value == 0):
                return True
            marco = region_marco(hwnd)
            if marco and marco.ancho > 0 and marco.alto > 0:
                encontradas.append(marco)
        except Exception:  # noqa: BLE001 - una ventana rara no para la enumeracion
            pass
        return True

    user32.EnumWindows(visitar, 0)
    return encontradas


LWA_ALPHA = 0x2
# Si lo nuestro tapa mas de esta parte de la region, la lectura pasiva no se hace.
TAPADO_MAXIMO = 0.5


def descartar_propias(imagen, region: Region, propias: list[Region] | None = None,
                      tapado_maximo: float = TAPADO_MAXIMO):
    """Pinta de negro lo que tapan nuestras ventanas; None si tapan demasiado.

    Para las lecturas periodicas, que no esconden Farmadex: asi el OCR no lee nuestros
    textos como si fueran del juego (ni el video del panel hace creer que la pantalla
    no para de cambiar). Si la parte tapada pasa de `tapado_maximo`, no merece la pena
    leer y se devuelve None. Devuelve una copia si toca algo; si no, la misma imagen.
    """
    if imagen is None:
        return None
    if propias is None:
        propias = ventanas_propias()
    tapes = [c for c in (interseccion(region, p) for p in propias) if c is not None]
    if not tapes:
        return imagen
    import numpy as np

    alto, ancho = imagen.shape[:2]
    fx, fy = ancho / max(1, region.ancho), alto / max(1, region.alto)
    mascara = np.zeros((alto, ancho), dtype=bool)
    for c in tapes:
        x0, y0 = int((c.x - region.x) * fx), int((c.y - region.y) * fy)
        x1 = int(round((c.x + c.ancho - region.x) * fx))
        y1 = int(round((c.y + c.alto - region.y) * fy))
        mascara[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    if mascara.mean() > tapado_maximo:
        return None
    copia = imagen.copy()
    copia[mascara] = 0
    return copia


def esperar_composicion(fotogramas: int = 2) -> None:
    """Espera a que el compositor de Windows (DWM) pinte `fotogramas` veces.

    Tras cambiar la opacidad de una ventana, la pantalla no cambia hasta que DWM
    compone el siguiente fotograma; capturar antes seria capturar la ventana aun
    visible. DwmFlush bloquea hasta la siguiente composicion; con dos se cubre el caso
    de que el cambio llegase justo cuando un fotograma ya se estaba componiendo.
    Medido en el PC de pruebas: 4-12 ms por llamada (1-2 fotogramas).
    """
    try:
        dwm = ctypes.windll.dwmapi
        for _ in range(fotogramas):
            if dwm.DwmFlush() != 0:
                raise OSError("DwmFlush")
    except (AttributeError, OSError):
        time.sleep(fotogramas / 60.0)  # sin DWM a mano: dos fotogramas a 60 Hz


def region_objetivo() -> Region:
    """La ventana del juego si esta abierto; si no, la pantalla entera."""
    hwnd = ventana_juego()
    if hwnd:
        region = region_ventana(hwnd)
        if region:
            return region
    return region_pantalla_completa()


def region_juego() -> Region | None:
    """Area de cliente del juego, o None si no esta abierto o esta minimizado."""
    hwnd = ventana_juego()
    return region_ventana(hwnd) if hwnd else None
