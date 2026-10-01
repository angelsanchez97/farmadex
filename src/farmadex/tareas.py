"""Trabajo pesado fuera del hilo de la interfaz."""

from __future__ import annotations

import httpx
from PySide6.QtCore import QThread, Signal

from .datos import indice
from .datos.descargas import ErrorDescarga, FuenteCambiada
from .idiomas import t
from .registro_log import obtener

log = obtener("tareas")


def motivo_para_el_usuario(error: Exception) -> str:
    """Una causa corta y comprensible para la barra de estado.

    Antes se ensenaba la excepcion tal cual: una URL de GitHub, el texto de httpx y un
    enlace a la documentacion de Mozilla sobre el 404. El detalle queda en el registro.
    """
    if isinstance(error, FuenteCambiada):
        return t("la fuente ha cambiado")
    if isinstance(error, ErrorDescarga):
        if error.estado is None:
            return t("sin conexión con la fuente")
        if error.estado >= 500 or error.estado in (408, 429):
            return t("la fuente no responde")
        return t("la fuente ha cambiado")
    if isinstance(error, (httpx.TransportError, ConnectionError, TimeoutError)):
        return t("sin conexión con la fuente")
    return t("fallo inesperado; detalles en el registro")


class TareaDatos(QThread):
    """Descarga los datos y construye el indice, informando del progreso."""

    progreso = Signal(str, int, int)  # texto, hechos, total (total<=0: indeterminado)
    terminada = Signal(bool, str)  # ok, mensaje

    def __init__(self, forzar: bool = False, parent=None):
        super().__init__(parent)
        self.forzar = forzar

    def run(self) -> None:  # noqa: D102
        # Reconstruir el indice tras actualizar es trabajo pesado de CPU y disco: con
        # prioridad baja el PC (y el juego) siguen respondiendo mientras tanto.
        try:
            QThread.currentThread().setPriority(QThread.LowPriority)
        except Exception:  # noqa: BLE001 - la prioridad es un detalle, nunca un fallo
            pass
        try:
            resumen = indice.construir(progreso=self.progreso.emit, forzar=self.forzar)
            if resumen.get("reconstruido"):
                mensaje = t(
                    "{objetos} objetos importados en {segundos} s ({nombres} nombres indexados)",
                    objetos=resumen["objetos"],
                    segundos=resumen["segundos"],
                    nombres=resumen["entradas_busqueda"],
                )
                if resumen.get("sin_casar", 0) > indice.UMBRAL_SIN_CASAR:
                    # Muchos nombres de las tablas de DE que el catalogo de WFCD no conoce:
                    # una de las dos fuentes va por detras del parche.
                    mensaje += " · " + t(
                        "Aviso: {n} nombres de las tablas de drops no están en el catálogo; "
                        "una de las fuentes va por detrás del parche",
                        n=resumen["sin_casar"],
                    )
            else:
                mensaje = t("Datos al día")
            self.terminada.emit(True, mensaje)
        except Exception as e:  # noqa: BLE001 - el fallo se ensena en la ventana
            log.exception("Fallo preparando los datos")
            self.terminada.emit(False, motivo_para_el_usuario(e))


def parar_en_su_hilo(objeto, metodo: str = "parar", espera_ms: int = 2000) -> bool:
    """Llama a `objeto.<metodo>()` EN EL HILO DEL OBJETO y espera a que acabe.

    Para los objetos movidos a un hilo de trabajo (`moveToThread`) que tienen un QTimer:
    pararlo o destruirlo desde el hilo de la ventana da "QObject::killTimer: Timers cannot
    be stopped from another thread" y "QObject::~QObject: ..." (salian cuatro parejas en
    cada cierre de Farmadex desde la 0.6.4). Si el hilo del objeto ya no corre, o es el
    hilo actual, se llama directamente. `metodo` tiene que ser un @Slot sin argumentos.
    Devuelve False si no se pudo (objeto sin ese metodo, o Qt no pudo encolar la llamada).
    """
    from PySide6.QtCore import QMetaObject, Qt, QTimer

    if objeto is None or not hasattr(objeto, metodo):
        return False
    try:
        hilo = objeto.thread()
        if hilo is None or hilo is QThread.currentThread() or not hilo.isRunning():
            getattr(objeto, metodo)()
            return True
        if not any(temporizador.isActive() for temporizador in objeto.findChildren(QTimer)):
            return True  # nada sonando: ni se molesta al hilo (ni se le deja un evento pendiente)
        # Bloqueante: al volver, el slot ya ha corrido en su hilo y no queda ningun evento
        # pendiente en la cola de ese hilo (un QMetaCallEvent con un slot de Python que se
        # queda sin atender en un hilo que luego muere se destruye al salir, ya sin Python
        # debajo, y tumbaba el proceso al terminar: pytest acababa con codigo 139). Si el
        # hilo esta a mitad de una lectura, espera lo que tarde esa lectura (el ocultador de
        # ventanas que esa lectura puede pedir a la ventana tiene su propio plazo maximo).
        return bool(QMetaObject.invokeMethod(objeto, metodo, Qt.BlockingQueuedConnection))
    except RuntimeError:  # el objeto de C++ ya no existe
        return False

