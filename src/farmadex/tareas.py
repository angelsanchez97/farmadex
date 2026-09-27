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
