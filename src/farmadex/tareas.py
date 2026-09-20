"""Trabajo pesado fuera del hilo de la interfaz."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .datos import indice
from .idiomas import t
from .registro_log import obtener

log = obtener("tareas")


class TareaDatos(QThread):
    """Descarga los datos y construye el indice, informando del progreso."""

    progreso = Signal(str, int, int)  # texto, hechos, total (total<=0: indeterminado)
    terminada = Signal(bool, str)  # ok, mensaje

    def __init__(self, forzar: bool = False, parent=None):
        super().__init__(parent)
        self.forzar = forzar

    def run(self) -> None:  # noqa: D102
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
                        "Aviso: {n} nombres de las tablas de drops no estan en el catalogo; "
                        "una de las fuentes va por detras del parche",
                        n=resumen["sin_casar"],
                    )
            else:
                mensaje = t("Datos al dia")
            self.terminada.emit(True, mensaje)
        except Exception as e:  # noqa: BLE001 - el fallo se ensena en la ventana
            log.exception("Fallo preparando los datos")
            self.terminada.emit(False, str(e))
