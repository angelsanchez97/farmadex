"""Comprobacion periodica de los datos del juego.

La descarga y la reconstruccion ya las hace `datos.indice.construir`, que deja
el indice nuevo en un fichero aparte y lo sustituye de golpe al final, asi que
la aplicacion se puede seguir usando mientras tanto.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from ..datos import indice
from ..datos.descargas import Descargador
from ..registro_log import obtener

log = obtener("actualizador.datos")

HORAS = 6


class ComprobadorDatos(QObject):
    """Cada 6 horas mira si WFCD o DE han publicado datos nuevos."""

    hay_novedades = Signal(str)  # motivo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.temporizador: QTimer | None = None
        self._hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        self.temporizador = QTimer(self)
        self.temporizador.timeout.connect(self.comprobar)
        self.temporizador.start(HORAS * 3600 * 1000)

    def comprobar(self) -> None:
        """Lanza la comprobacion en un hilo: son dos peticiones HTTP y la
        interfaz no puede quedarse congelada mientras tanto."""
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._hilo = threading.Thread(
            target=self.comprobar_ahora, name="comprobador-datos", daemon=True
        )
        self._hilo.start()

    def comprobar_ahora(self) -> None:
        """La comprobacion en si, sincrona. Nunca propaga: sin red, se anota y ya."""
        try:
            self._comprobar()
        except Exception as e:  # noqa: BLE001 - se reintenta a las 6 horas
            log.warning("No se pudo comprobar si hay datos nuevos: %s", e)

    def _comprobar(self) -> None:
        motivos = []
        descargador = Descargador()
        try:
            sha, _ = descargador.version_items()
            hash_drops, _ = descargador.version_drops()
        finally:
            descargador.cerrar()

        guardado = _meta()
        if sha and guardado.get("items_sha") and sha != guardado["items_sha"]:
            motivos.append("catalogo de objetos")
        if (
            hash_drops
            and guardado.get("drops_hash")
            and hash_drops != guardado["drops_hash"]
        ):
            motivos.append("tablas de drops")

        if motivos:
            log.info("Hay datos nuevos: %s", ", ".join(motivos))
            self.hay_novedades.emit(" y ".join(motivos))
        else:
            log.info("Datos del juego al dia")

    def parar(self) -> None:
        if self.temporizador:
            self.temporizador.stop()


def _meta() -> dict:
    if not indice.hay_indice():
        return {}
    con = indice.conectar()
    try:
        return dict(con.execute("SELECT clave, valor FROM meta").fetchall())
    finally:
        con.close()
