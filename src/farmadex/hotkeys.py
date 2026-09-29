"""Atajos globales en Windows: teclado, botones del raton y mando.

Hay tres clases de atajo y cada una se vigila de la forma mas barata que no estorbe
al juego:

- Combinacion con modificador (Ctrl, Alt, Shift o Win + tecla): RegisterHotKey, como
  siempre. Windows entrega WM_HOTKEY al hilo que la registro y se queda la
  combinacion, asi que no llega al juego (es lo que se hacia hasta ahora).
- Tecla sola (F9, G...) y botones del raton (rueda, laterales), con o sin
  modificadores: se miran con GetAsyncKeyState unas 60 veces por segundo. No se
  traga nada: la tecla sigue llegando al juego, porque una tecla sola que el juego
  dejara de recibir le romperia los controles al jugador.
- Mando (XInput: Xbox y compatibles): se lee el estado del mando al mismo ritmo.
  Si no hay ningun mando conectado solo se pregunta cada pocos segundos, y si
  ningun atajo usa el mando ni se carga la libreria.

Todo corre en un hilo propio. Sin atajos de sondeo, el hilo se queda dormido en su
bucle de mensajes y no gasta nada. La configuracion sigue siendo un texto por atajo
("Ctrl+Alt+W", "F9", "Mouse4", "Mando:View+A"): lo que el usuario ya tenia vale tal cual.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from .registro_log import obtener

log = obtener("hotkeys")

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MODIFICADORES = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "mayus": MOD_SHIFT,
    "mayús": MOD_SHIFT,
    "win": MOD_WIN,
}
# Orden y nombre con el que se escriben al guardar.
NOMBRES_MODIFICADOR = ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win"))
# Codigo virtual de cada modificador (para mirarlo con GetAsyncKeyState).
VK_MODIFICADOR = {MOD_CONTROL: 0x11, MOD_ALT: 0x12, MOD_SHIFT: 0x10, MOD_WIN: (0x5B, 0x5C)}

# Teclas con codigo virtual propio; las letras y numeros se sacan de su ASCII.
TECLAS = {
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    "space": 0x20, "espacio": 0x20, "intro": 0x0D, "enter": 0x0D, "tab": 0x09,
    "esc": 0x1B, "escape": 0x1B, "insert": 0x2D, "supr": 0x2E, "delete": 0x2E,
    "inicio": 0x24, "home": 0x24, "fin": 0x23, "end": 0x23,
    "pageup": 0x21, "repag": 0x21, "pagedown": 0x22, "avpag": 0x22,
    "arriba": 0x26, "abajo": 0x28, "izquierda": 0x25, "derecha": 0x27,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "backspace": 0x08, "retroceso": 0x08, "pause": 0x13, "pausa": 0x13,
    "capslock": 0x14, "bloqmayus": 0x14, "printscreen": 0x2C, "imppant": 0x2C,
    "scrolllock": 0x91, "bloqdespl": 0x91, "numlock": 0x90,
    **{f"num{i}": 0x60 + i for i in range(10)},
    "num*": 0x6A, "num+": 0x6B, "num-": 0x6D, "num.": 0x6E, "num/": 0x6F,
}
# Nombre con el que se guarda cada codigo (el primero que aparece arriba en ingles).
NOMBRE_TECLA = {
    **{0x6F + i: f"F{i}" for i in range(1, 25)},
    0x20: "Space", 0x0D: "Enter", 0x09: "Tab", 0x1B: "Esc", 0x2D: "Insert", 0x2E: "Delete",
    0x24: "Home", 0x23: "End", 0x21: "PageUp", 0x22: "PageDown", 0x26: "Up", 0x28: "Down",
    0x25: "Left", 0x27: "Right", 0x08: "Backspace", 0x13: "Pause", 0x14: "CapsLock",
    0x2C: "PrintScreen", 0x91: "ScrollLock", 0x90: "NumLock",
    **{0x60 + i: f"Num{i}" for i in range(10)},
    0x6A: "Num*", 0x6B: "Num+", 0x6D: "Num-", 0x6E: "Num.", 0x6F: "Num/",
}

# Botones del raton que se pueden usar (el izquierdo y el derecho no: romperian todo).
BOTONES_RATON = {"mouse3": 0x04, "mouse4": 0x05, "mouse5": 0x06}
NOMBRE_RATON = {0x04: "Mouse3", 0x05: "Mouse4", 0x06: "Mouse5"}

# Mando XInput: bit de cada boton; los gatillos se tratan como botones con bits propios.
BOTONES_MANDO = {
    "up": 0x0001, "down": 0x0002, "left": 0x0004, "right": 0x0008,
    "menu": 0x0010, "start": 0x0010, "view": 0x0020, "back": 0x0020,
    "ls": 0x0040, "rs": 0x0080, "lb": 0x0100, "rb": 0x0200,
    "a": 0x1000, "b": 0x2000, "x": 0x4000, "y": 0x8000,
    "lt": 0x10000, "rt": 0x20000,
}
ORDEN_MANDO = (("LB", 0x0100), ("RB", 0x0200), ("LT", 0x10000), ("RT", 0x20000), ("View", 0x0020),
               ("Menu", 0x0010), ("LS", 0x0040), ("RS", 0x0080), ("Up", 0x0001), ("Down", 0x0002),
               ("Left", 0x0004), ("Right", 0x0008), ("A", 0x1000), ("B", 0x2000), ("X", 0x4000),
               ("Y", 0x8000))
PREFIJOS_MANDO = ("mando:", "pad:")
UMBRAL_GATILLO = 30  # XINPUT_GAMEPAD_TRIGGER_THRESHOLD

# Teclas que casi todo el mundo usa jugando a Warframe con la configuracion de fabrica.
# Una tecla sola de estas se permite, pero se avisa: dispararia el atajo cada vez que
# se usa en el juego.
TECLAS_DEL_JUEGO = {
    ord(c) for c in "WASDQEFRGCXZVBTYUIOPHJKLMN1234567890"
} | {0x20, 0x09, 0x1B, 0x0D, 0x10, 0x11, 0x12, 0x14}


@dataclass(frozen=True)
class Atajo:
    """Un atajo ya interpretado."""

    tipo: str  # "teclado", "raton" o "mando"
    modificadores: int = 0  # MOD_* (sin MOD_NOREPEAT)
    codigo: int = 0  # tecla virtual o boton del raton
    botones: int = 0  # mando: mascara de botones

    @property
    def registrable(self) -> bool:
        """Si va por RegisterHotKey (combinacion de teclado con modificador)."""
        return self.tipo == "teclado" and bool(self.modificadores)

    @property
    def de_texto(self) -> bool:
        """Tecla sola que se escribe (letra, numero, espacio): no vale mientras se escribe en Farmadex."""
        return (self.tipo == "teclado" and not (self.modificadores & (MOD_CONTROL | MOD_ALT | MOD_WIN))
                and (0x30 <= self.codigo <= 0x5A or self.codigo in (0x20, 0x08, 0x0D) or self.codigo >= 0xBA))

    def texto(self) -> str:
        """Como se guarda en la configuracion."""
        return formatear(self)


def _codigo_tecla(tecla: str) -> int:
    if tecla in TECLAS:
        return TECLAS[tecla]
    if len(tecla) == 1 and tecla.isascii() and tecla.isalnum():
        return ord(tecla.upper())
    if tecla.startswith("vk") and tecla[2:].isdigit():
        codigo = int(tecla[2:])
        if 0 < codigo < 0xFF:
            return codigo
    raise ValueError(f"tecla desconocida: {tecla}")


def interpretar(combinacion: str) -> Atajo:
    """'Ctrl+Alt+W', 'F9', 'Mouse4', 'Mando:View+A' -> Atajo. Lanza ValueError si no vale."""
    if not combinacion or not combinacion.strip():
        raise ValueError("combinacion vacia")
    texto = combinacion.strip()
    bajo = texto.lower()
    for prefijo in PREFIJOS_MANDO:
        if bajo.startswith(prefijo):
            botones = 0
            for parte in bajo[len(prefijo):].split("+"):
                parte = parte.strip()
                if not parte:
                    continue
                if parte not in BOTONES_MANDO:
                    raise ValueError(f"boton de mando desconocido: {parte}")
                botones |= BOTONES_MANDO[parte]
            if not botones:
                raise ValueError("falta el boton del mando")
            return Atajo("mando", botones=botones)

    partes = [p.strip().lower() for p in texto.split("+") if p.strip()]
    if texto.endswith("++") or texto == "+":
        partes.append("num+")  # "Ctrl++" no se escribe asi, pero que no pete
    if not partes:
        raise ValueError("combinacion vacia")
    modificadores = 0
    tecla = None
    for parte in partes:
        if parte in MODIFICADORES:
            modificadores |= MODIFICADORES[parte]
        elif tecla is None:
            tecla = parte
        else:
            raise ValueError(f"dos teclas en la misma combinacion: {combinacion}")
    if tecla is None:
        raise ValueError(f"falta la tecla en {combinacion}")
    if tecla in BOTONES_RATON:
        return Atajo("raton", modificadores, BOTONES_RATON[tecla])
    return Atajo("teclado", modificadores, _codigo_tecla(tecla))


def parsear(combinacion: str) -> tuple[int, int]:
    """'Ctrl+Alt+W' -> (modificadores | MOD_NOREPEAT, codigo de tecla), para RegisterHotKey.

    Ya no exige modificador: 'F9' da (MOD_NOREPEAT, 0x78). Lanza ValueError si el texto
    no es un atajo de teclado (tambien si es del raton o del mando).
    """
    atajo = interpretar(combinacion)
    if atajo.tipo != "teclado":
        raise ValueError(f"{combinacion} no es una tecla")
    return atajo.modificadores | MOD_NOREPEAT, atajo.codigo


def formatear(atajo: Atajo) -> str:
    """El texto con el que se guarda (y se reconoce luego con `interpretar`)."""
    if atajo.tipo == "mando":
        return "Mando:" + "+".join(n for n, bit in ORDEN_MANDO if atajo.botones & bit)
    partes = [n for bit, n in NOMBRES_MODIFICADOR if atajo.modificadores & bit]
    if atajo.tipo == "raton":
        partes.append(NOMBRE_RATON.get(atajo.codigo, f"Mouse{atajo.codigo}"))
    elif atajo.codigo in NOMBRE_TECLA:
        partes.append(NOMBRE_TECLA[atajo.codigo])
    elif 0x30 <= atajo.codigo <= 0x5A:
        partes.append(chr(atajo.codigo))
    else:
        partes.append(f"VK{atajo.codigo}")
    return "+".join(partes)


def normalizar(combinacion: str) -> str:
    """El mismo atajo escrito de forma canonica ('ctrl + alt + w' -> 'Ctrl+Alt+W'); '' si esta vacio."""
    if not combinacion or not combinacion.strip():
        return ""
    return formatear(interpretar(combinacion))


def choca_con_el_juego(combinacion: str) -> bool:
    """Tecla sola (o con solo Shift) que el juego usa de fabrica, o boton de mando suelto."""
    try:
        atajo = interpretar(combinacion)
    except ValueError:
        return False
    if atajo.tipo == "mando":
        return bin(atajo.botones).count("1") == 1
    if atajo.tipo != "teclado" or atajo.modificadores & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return False
    return atajo.codigo in TECLAS_DEL_JUEGO


ERROR_HOTKEY_ALREADY_REGISTERED = 1409


def motivo_registro(codigo_error: int, combinacion: str) -> str:
    """Texto para el usuario segun el GetLastError que dejo RegisterHotKey."""
    if codigo_error == ERROR_HOTKEY_ALREADY_REGISTERED:
        return f"la combinacion {combinacion} ya la usa otro programa"
    return f"Windows no acepta la combinacion {combinacion} (error {codigo_error})"


# -- lectura del teclado, el raton y el mando (sondeo) ---------------------------------------


class _XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


class _XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", _XINPUT_GAMEPAD)]


ERROR_DEVICE_NOT_CONNECTED = 1167


class Mandos:
    """Los mandos XInput conectados. La libreria se carga la primera vez que hace falta.

    Preguntar por un hueco sin mando cuesta mucho mas que por uno conectado (Windows
    busca el dispositivo): los huecos vacios solo se miran cada `REVISAR_VACIOS_S`.
    """

    REVISAR_VACIOS_S = 3.0
    HUECOS = 4

    def __init__(self, obtener_estado=None, reloj=time.monotonic):
        self._obtener = obtener_estado
        self._reloj = reloj
        self._conectados: set[int] = set()
        self._t_vacios = float("-inf")
        self.disponible = True

    def _cargar(self):
        if self._obtener is not None:
            return self._obtener
        for nombre in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                dll = ctypes.WinDLL(nombre)
            except OSError:
                continue
            funcion = dll.XInputGetState
            funcion.argtypes = [wintypes.DWORD, ctypes.POINTER(_XINPUT_STATE)]
            funcion.restype = wintypes.DWORD
            estado = _XINPUT_STATE()

            def obtener_estado(hueco: int, _f=funcion, _e=estado):
                if _f(hueco, ctypes.byref(_e)) != 0:
                    return None
                g = _e.Gamepad
                botones = g.wButtons
                if g.bLeftTrigger > UMBRAL_GATILLO:
                    botones |= BOTONES_MANDO["lt"]
                if g.bRightTrigger > UMBRAL_GATILLO:
                    botones |= BOTONES_MANDO["rt"]
                return botones

            self._obtener = obtener_estado
            log.info("Mando: XInput cargado (%s)", nombre)
            return obtener_estado
        self.disponible = False
        log.warning("Mando: no se encontro XInput en este Windows; los atajos de mando no funcionaran")
        return None

    def botones(self) -> int:
        """Botones pulsados ahora mismo en cualquier mando (mascara)."""
        obtener_estado = self._cargar() if self.disponible else None
        if obtener_estado is None:
            return 0
        ahora = self._reloj()
        huecos = set(self._conectados)
        if ahora - self._t_vacios >= self.REVISAR_VACIOS_S:
            self._t_vacios = ahora
            huecos = set(range(self.HUECOS))
        total = 0
        for hueco in sorted(huecos):
            try:
                estado = obtener_estado(hueco)
            except Exception:  # noqa: BLE001 - un driver raro no puede tumbar los atajos
                estado = None
            if estado is None:
                if hueco in self._conectados:
                    log.info("Mando %d desconectado", hueco + 1)
                self._conectados.discard(hueco)
                continue
            if hueco not in self._conectados:
                log.info("Mando %d conectado", hueco + 1)
            self._conectados.add(hueco)
            total |= estado
        return total

    @property
    def hay_mando(self) -> bool:
        return bool(self._conectados)


def _estado_win(vk: int, _cache={}) -> int:  # noqa: B006 - cache de la funcion de user32
    funcion = _cache.get("f")
    if funcion is None:
        funcion = ctypes.windll.user32.GetAsyncKeyState
        funcion.argtypes = [ctypes.c_int]
        funcion.restype = ctypes.c_short
        _cache["f"] = funcion
    return int(funcion(vk))


def _tecla_abajo_win(vk: int) -> bool:
    """Si la tecla esta pulsada ahora mismo."""
    return bool(_estado_win(vk) & 0x8000)


def _tecla_pulsada_win(vk: int) -> bool:
    """Pulsada ahora o pulsada y soltada desde el vistazo anterior (un toque muy rapido).

    El bit bajo de GetAsyncKeyState dice "se ha pulsado desde la ultima vez que se
    pregunto": con el, un toque mas corto que el ritmo del sondeo no se pierde.
    """
    return bool(_estado_win(vk) & 0x8001)


def _primer_plano_es_nuestro() -> bool:
    """Si la ventana activa es de Farmadex (entonces una letra suelta es escribir, no un atajo)."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == os.getpid()
    except (AttributeError, OSError):
        return False


@dataclass
class Sondeo:
    """Detecta la pulsacion de los atajos que no van por RegisterHotKey.

    Cada `mirar()` lee el estado y devuelve los nombres de los atajos que se acaban de
    pulsar (flanco: pasar de no pulsado a pulsado). Mantener la tecla no repite. Se
    prueba sin Windows sustituyendo `tecla_abajo`, `mandos` y `primer_plano_nuestro`.
    """

    atajos: dict[str, Atajo]
    tecla_abajo: object = None
    mandos: Mandos | None = None
    tecla_pulsada: object = None  # la tecla principal (con los toques rapidos); por defecto = tecla_abajo
    primer_plano_nuestro: object = None
    _pulsados: set = field(default_factory=set)
    pausado: bool = False

    def __post_init__(self):
        if self.tecla_abajo is None:
            self.tecla_abajo = _tecla_abajo_win
            self.tecla_pulsada = self.tecla_pulsada or _tecla_pulsada_win
        self.tecla_pulsada = self.tecla_pulsada or self.tecla_abajo
        # Un primer vistazo que se tira: el "pulsada desde la ultima vez" de antes de
        # arrancar no puede disparar nada.
        for atajo in self.atajos.values():
            if atajo.tipo != "mando":
                try:
                    self.tecla_pulsada(atajo.codigo)
                except Exception:  # noqa: BLE001
                    pass
        self.primer_plano_nuestro = self.primer_plano_nuestro or _primer_plano_es_nuestro
        if self.mandos is None and any(a.tipo == "mando" for a in self.atajos.values()):
            self.mandos = Mandos()

    @property
    def usa_mando(self) -> bool:
        return any(a.tipo == "mando" for a in self.atajos.values())

    def _modificadores_ok(self, atajo: Atajo) -> bool:
        """Exactamente los modificadores del atajo (G no salta con Ctrl+G, ni al reves)."""
        for bit, vk in VK_MODIFICADOR.items():
            abajo = any(self.tecla_abajo(v) for v in vk) if isinstance(vk, tuple) else self.tecla_abajo(vk)
            if bool(atajo.modificadores & bit) != abajo:
                return False
        return True

    def mirar(self) -> list[str]:
        botones_mando = self.mandos.botones() if (self.mandos is not None and self.usa_mando) else 0
        nuestro = None
        disparados = []
        for nombre, atajo in self.atajos.items():
            if atajo.tipo == "mando":
                abajo = (botones_mando & atajo.botones) == atajo.botones
            else:
                abajo = self.tecla_pulsada(atajo.codigo) and self._modificadores_ok(atajo)
            if not abajo:
                self._pulsados.discard(nombre)
                continue
            if nombre in self._pulsados:
                continue  # sigue pulsado: ya salto
            self._pulsados.add(nombre)
            if self.pausado:
                continue
            if atajo.de_texto:
                if nuestro is None:
                    nuestro = bool(self.primer_plano_nuestro())
                if nuestro:
                    continue  # escribiendo en Farmadex
            disparados.append(nombre)
        return disparados


# Mientras Ajustes espera a que el usuario pulse una tecla, los atajos no saltan.
_pausa_global = {"activa": False}


def pausar(activa: bool) -> None:
    """Ajustes > Atajos: mientras se captura una tecla nueva, ningun atajo de sondeo salta."""
    _pausa_global["activa"] = bool(activa)


def en_pausa() -> bool:
    return _pausa_global["activa"]


QS_ALLINPUT = 0x04FF
PM_REMOVE = 0x0001
WAIT_TIMEOUT = 0x102
INFINITO = 0xFFFFFFFF


class GestorHotkeys(QThread):
    """Registra y vigila los atajos; emite su nombre cuando se pulsan."""

    pulsada = Signal(str)
    fallo = Signal(str, str)  # nombre, motivo

    # Ritmo del sondeo (tecla sola, raton y mando): unas 60 veces por segundo. Se piden
    # 10 ms porque Windows redondea la espera a su tic de reloj (15,6 ms): pidiendo 16
    # salian 31 ms medidos. Una pulsacion normal dura bastante mas; mirar cuesta microsegundos.
    SONDEO_MS = 10

    def __init__(self, combinaciones: dict[str, str], parent=None):
        super().__init__(parent)
        self.combinaciones = dict(combinaciones)
        self._ids: dict[int, str] = {}
        self._id_hilo: int | None = None
        self.sondeo: Sondeo | None = None
        self._parar = False

    def _interpretar_todos(self) -> tuple[dict[str, Atajo], dict[str, Atajo]]:
        registrables, sondeados = {}, {}
        for nombre, combinacion in self.combinaciones.items():
            if not (combinacion or "").strip():
                continue  # atajo desactivado
            try:
                atajo = interpretar(combinacion)
            except ValueError as e:
                self.fallo.emit(nombre, str(e))
                continue
            (registrables if atajo.registrable else sondeados)[nombre] = atajo
        return registrables, sondeados

    def run(self) -> None:  # noqa: D102
        if not sys.platform.startswith("win"):
            log.warning("Los atajos globales solo estan implementados en Windows")
            return
        try:
            self._ejecutar()
        except Exception:  # noqa: BLE001 - un fallo aqui no puede tumbar el programa
            log.exception("El hilo de atajos ha fallado; los atajos dejan de funcionar hasta reiniciar")

    def _ejecutar(self) -> None:
        # use_last_error: sin esto GetLastError se pisa entre llamadas de ctypes y no
        # se sabe si el atajo lo tiene otro programa o Windows lo rechaza por otra cosa.
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._id_hilo = ctypes.windll.kernel32.GetCurrentThreadId()
        registrables, sondeados = self._interpretar_todos()

        siguiente = 1
        for nombre, atajo in registrables.items():
            combinacion = self.combinaciones[nombre]
            if user32.RegisterHotKey(None, siguiente, atajo.modificadores | MOD_NOREPEAT, atajo.codigo):
                self._ids[siguiente] = nombre
                log.info("Atajo registrado: %s = %s", nombre, combinacion)
                siguiente += 1
            else:
                motivo = motivo_registro(ctypes.get_last_error(), combinacion)
                self.fallo.emit(nombre, motivo)
                log.warning("No se pudo registrar %s (%s): %s", nombre, combinacion, motivo)
        if sondeados:
            self.sondeo = Sondeo(sondeados)
            log.info("Atajos vigilados sin quitarle la tecla al juego: %s",
                     ", ".join(f"{n} = {formatear(a)}" for n, a in sondeados.items()))
        if not self._ids and not sondeados and self.combinaciones:
            log.error("Ningun atajo global quedo registrado; el overlay solo se abre desde la bandeja")

        mensaje = wintypes.MSG()
        espera = user32.MsgWaitForMultipleObjects
        espera.argtypes = [wintypes.DWORD, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, wintypes.DWORD]
        espera.restype = wintypes.DWORD
        try:
            while not self._parar:
                plazo = self.SONDEO_MS if self.sondeo is not None else INFINITO
                espera(0, None, False, plazo, QS_ALLINPUT)
                while user32.PeekMessageW(ctypes.byref(mensaje), None, 0, 0, PM_REMOVE):
                    if mensaje.message == WM_QUIT:
                        self._parar = True
                        break
                    if mensaje.message == WM_HOTKEY:
                        nombre = self._ids.get(mensaje.wParam)
                        if nombre:
                            self.pulsada.emit(nombre)
                if self._parar or self.sondeo is None:
                    continue
                self.sondeo.pausado = en_pausa()
                try:
                    disparados = self.sondeo.mirar()
                except Exception:  # noqa: BLE001 - un fallo leyendo el estado no para los atajos
                    log.exception("Fallo mirando el teclado, el raton o el mando")
                    disparados = []
                for nombre in disparados:
                    self.pulsada.emit(nombre)
        finally:
            for identificador in self._ids:
                user32.UnregisterHotKey(None, identificador)
            self._ids.clear()

    def parar(self) -> None:
        if not self.isRunning():
            return
        self._parar = True
        # Se insiste: si el hilo aun no habia creado su cola de mensajes, el primer aviso
        # se pierde y se quedaria esperando para siempre.
        limite = time.monotonic() + 2.0
        while time.monotonic() < limite:
            if self._id_hilo and sys.platform.startswith("win"):
                ctypes.windll.user32.PostThreadMessageW(self._id_hilo, WM_QUIT, 0, 0)
            if self.wait(50):
                return
        log.warning("El hilo de atajos no termino a tiempo")
