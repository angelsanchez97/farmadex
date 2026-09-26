"""Un solo Farmadex abierto a la vez (instalado o portable, da igual cual).

Dos piezas:

- Un mutex con nombre (`MUTEX_INSTANCIA`) que decide quien es "el" Farmadex. Lo
  suelta Windows solo cuando el proceso muere, asi que un cierre a lo bruto no
  deja el candado puesto.
- Un QLocalServer (una tuberia con nombre en Windows) por el que el segundo
  Farmadex que se abre le pide al primero que se ensene, y por el que el
  instalador le pide que se cierre antes de sustituir sus ficheros.

El protocolo es texto: una orden por linea (`mostrar`, `salir`). El instalador
(empaquetado/instalador.iss) escribe `salir` en `\\\\.\\pipe\\<NOMBRE>` a pelo,
sin Qt: si se cambia el nombre de la tuberia hay que cambiarlo tambien alli.
"""

from __future__ import annotations

import ctypes
import os
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from . import NOMBRE_APP
from .registro_log import obtener

log = obtener("instancia")

MUTEX_INSTANCIA = f"{NOMBRE_APP}InstanciaUnica"
PREFIJO_TUBERIA = f"{NOMBRE_APP}-instancia-"
ORDEN_MOSTRAR = "mostrar"
ORDEN_SALIR = "salir"
ORDENES = (ORDEN_MOSTRAR, ORDEN_SALIR)
ERROR_ALREADY_EXISTS = 183
ASFW_ANY = -1


def usuario_windows() -> str:
    """El nombre de usuario tal y como lo da GetUserName (igual que {username} en Inno)."""
    if os.name == "nt":
        try:
            buf = ctypes.create_unicode_buffer(257)
            tam = ctypes.c_uint32(len(buf))
            if ctypes.windll.advapi32.GetUserNameW(buf, ctypes.byref(tam)) and buf.value:
                return buf.value
        except (AttributeError, OSError):
            pass
    return os.environ.get("USERNAME") or os.environ.get("USER") or "usuario"


def nombre_tuberia(usuario: str | None = None) -> str:
    """Nombre del servidor local. Lleva el usuario para que dos cuentas no choquen."""
    usuario = (usuario or usuario_windows()).replace("\\", "_").replace("/", "_")
    return f"{PREFIJO_TUBERIA}{usuario}"


class InstanciaUnica(QObject):
    """El candado de instancia unica y el canal por el que llegan las ordenes."""

    orden_recibida = Signal(str)

    def __init__(self, nombre: str | None = None, mutex: str | None = MUTEX_INSTANCIA, parent=None):
        super().__init__(parent)
        self.nombre = nombre or nombre_tuberia()
        self.nombre_mutex = mutex
        self._mutex = None
        self._servidor: QLocalServer | None = None
        self._sockets: list[QLocalSocket] = []
        # Ordenes llegadas antes de que alguien escuche la senal (la ventana tarda en
        # construirse): se guardan y se entregan al conectar con `entregar_pendientes`.
        self.pendientes: list[str] = []
        self._entregar_directo = False

    # -- candado --------------------------------------------------------------

    def adquirir(self) -> bool:
        """True si este proceso es el primer Farmadex; False si ya habia otro."""
        if os.name == "nt" and self.nombre_mutex:
            try:
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                k32.CreateMutexW.restype = ctypes.c_void_p
                handle = k32.CreateMutexW(None, False, self.nombre_mutex)
                ya_existia = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
            except (AttributeError, OSError) as e:  # pragma: no cover - solo fuera de Windows
                log.warning("No se pudo crear el mutex de instancia unica: %s", e)
                handle, ya_existia = None, False
            if handle and ya_existia:
                k32.CloseHandle(ctypes.c_void_p(handle))
                return False
            self._mutex = handle
            return True
        # Fuera de Windows (o sin mutex): si alguien contesta en la tuberia, hay otro.
        sonda = QLocalSocket()
        sonda.connectToServer(self.nombre)
        hay_otro = sonda.waitForConnected(300)
        sonda.abort()
        return not hay_otro

    def soltar(self) -> None:
        """Cierra el servidor y suelta el mutex (al salir; Windows lo haria igual al morir)."""
        for socket in self._sockets:
            try:
                socket.readyRead.disconnect(self._leer_todos)
                socket.disconnected.disconnect(self._limpiar)
            except (RuntimeError, TypeError):
                pass
            socket.abort()
            socket.deleteLater()
        self._sockets.clear()
        if self._servidor is not None:
            try:
                self._servidor.newConnection.disconnect(self._conexion_nueva)
            except (RuntimeError, TypeError):
                pass
            self._servidor.close()
            self._servidor.deleteLater()
            self._servidor = None
        if self._mutex and os.name == "nt":
            try:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self._mutex))
            except (AttributeError, OSError):  # pragma: no cover
                pass
        self._mutex = None

    # -- servidor ---------------------------------------------------------------

    def escuchar(self) -> bool:
        """Abre la tuberia. Va nada mas coger el candado, antes de montar la ventana."""
        servidor = QLocalServer(self)
        # Solo el mismo usuario puede escribir en la tuberia.
        servidor.setSocketOptions(QLocalServer.UserAccessOption)
        if not servidor.listen(self.nombre):
            # Un socket huerfano de una ejecucion que murio (fuera de Windows) se quita y
            # se reintenta; en Windows las tuberias desaparecen con su proceso.
            QLocalServer.removeServer(self.nombre)
            if not servidor.listen(self.nombre):
                log.warning("No se pudo abrir la tuberia de instancia unica %s: %s",
                            self.nombre, servidor.errorString())
                return False
        servidor.newConnection.connect(self._conexion_nueva)
        self._servidor = servidor
        log.info("Instancia unica: escuchando en %s", self.nombre)
        return True

    def _conexion_nueva(self) -> None:
        while self._servidor is not None and self._servidor.hasPendingConnections():
            socket = self._servidor.nextPendingConnection()
            if socket is None:
                break
            self._sockets.append(socket)
            socket.readyRead.connect(self._leer_todos)
            socket.disconnected.connect(self._limpiar)
        self._leer_todos()

    def _leer_todos(self) -> None:
        for socket in list(self._sockets):
            self._leer(socket)

    def _limpiar(self) -> None:
        """Los que ya colgaron: se lee lo que dejaran y se borran."""
        for socket in list(self._sockets):
            if socket.state() == QLocalSocket.UnconnectedState:
                self._leer(socket)
                self._sockets.remove(socket)
                socket.deleteLater()

    def _leer(self, socket: QLocalSocket) -> None:
        while socket.canReadLine():
            texto = bytes(socket.readLine().data()).decode("utf-8", "replace").strip().lower()
            if texto:
                self._recibir(texto)

    def _recibir(self, orden: str) -> None:
        if orden not in ORDENES:
            log.warning("Orden desconocida por la tuberia de instancia: %r", orden[:40])
            return
        log.info("Orden recibida de otro proceso: %s", orden)
        if self._entregar_directo:
            self.orden_recibida.emit(orden)
        else:
            self.pendientes.append(orden)

    def entregar_pendientes(self) -> None:
        """A partir de ahora las ordenes se emiten al llegar; las guardadas, ya."""
        self._entregar_directo = True
        pendientes, self.pendientes = self.pendientes, []
        for orden in pendientes:
            self.orden_recibida.emit(orden)


def avisar_a_la_abierta(
    orden: str = ORDEN_MOSTRAR, nombre: str | None = None, espera_s: float = 5.0, espera_lectura_s: float = 10.0
) -> bool:
    """Manda `orden` al Farmadex que ya esta abierto. True si le llego.

    Reintenta durante `espera_s`: el otro puede estar arrancando y aun no haber
    abierto la tuberia. Antes de mandar `mostrar` se le da permiso para ponerse
    delante (Windows solo deja robar el primer plano a quien lo tiene, y el que
    tiene el primer plano ahora es este proceso, recien abierto por el usuario).

    La tuberia no guarda nada por su cuenta: la escritura acaba cuando el otro la
    lee, y si el otro esta aun montando su ventana tarda en leer. Por eso se le
    esperan hasta `espera_lectura_s` antes de darlo por perdido.
    """
    nombre = nombre or nombre_tuberia()
    if orden == ORDEN_MOSTRAR and os.name == "nt":
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
        except (AttributeError, OSError):  # pragma: no cover
            pass
    limite = time.monotonic() + espera_s
    while True:
        socket = QLocalSocket()
        socket.connectToServer(nombre)
        if socket.waitForConnected(500):
            socket.write(f"{orden}\n".encode())
            socket.flush()
            ok = socket.waitForBytesWritten(int(espera_lectura_s * 1000)) or socket.bytesToWrite() == 0
            socket.disconnectFromServer()
            if socket.state() != QLocalSocket.UnconnectedState:
                socket.waitForDisconnected(500)
            return ok
        if time.monotonic() >= limite:
            return False
        time.sleep(0.2)


def esperar_a_que_se_cierre(nombre_mutex: str = MUTEX_INSTANCIA, espera_s: float = 30.0) -> bool:
    """Tras mandar `salir`: espera a que el otro Farmadex suelte el mutex. True si lo solto."""
    if os.name != "nt":
        return True
    limite = time.monotonic() + espera_s
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenMutexW.restype = ctypes.c_void_p
    SYNCHRONIZE = 0x00100000
    while True:
        handle = k32.OpenMutexW(SYNCHRONIZE, False, nombre_mutex)
        if not handle:
            return True
        k32.CloseHandle(ctypes.c_void_p(handle))
        if time.monotonic() >= limite:
            return False
        time.sleep(0.25)
