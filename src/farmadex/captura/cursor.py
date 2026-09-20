"""'Que es esto': lee el texto que hay alrededor del raton y abre su ficha."""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot

from ..idiomas import t
from ..registro_log import obtener
from . import pantalla
from .reliquias import LectorBase

log = obtener("cursor")


class LectorCursor(LectorBase):
    """Captura un recuadro alrededor del cursor y busca ahi un nombre conocido."""

    encontrado = Signal(int, str)  # item_id, nombre
    candidatos = Signal(list)  # [(item_id, nombre, puntuacion)] cuando hay dudas

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(motor_ocr, None, parent)

    @Slot()
    def leer_ahora(self) -> None:
        if self._ocupado:
            return
        self._ocupado = True
        try:
            self._leer()
        except Exception:  # noqa: BLE001 - ultima red: nunca un dialogo de error
            log.exception("Fallo inesperado leyendo bajo el cursor")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            self.candidatos.emit([])
        finally:
            self._ocupado = False

    def _leer(self) -> None:
        if not self._preparado():
            self.candidatos.emit([])
            return
        self.estado.emit(t("Leyendo lo que hay bajo el cursor..."))
        # Con el juego en ventana, el recuadro no se sale de ella.
        region = pantalla.region_alrededor_del_cursor(limite=pantalla.region_juego())
        imagen = pantalla.capturar(region)
        if imagen is None:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.candidatos.emit([])
            return
        encontrados = self._leer_protegido(imagen, umbral=85)
        if encontrados is None:
            self.candidatos.emit([])
            return
        if not encontrados:
            self.estado.emit(t("No se reconocio nada bajo el cursor"))
            self.candidatos.emit([])
            return

        # El que este mas cerca del centro del recuadro es el que senala el raton.
        centro = region.ancho / 2, region.alto / 2

        def distancia(r):
            x = r.caja[0] + r.caja[2] / 2
            y = r.caja[1] + r.caja[3] / 2
            return (x - centro[0]) ** 2 + (y - centro[1]) ** 2

        ordenados = sorted(encontrados, key=lambda r: (distancia(r), -r.puntuacion))
        mejor = ordenados[0]
        log.info("Bajo el cursor: %r -> %s", mejor.texto_ocr, mejor.nombre)
        self.estado.emit(t("Bajo el cursor: {nombre}", nombre=mejor.nombre))
        self.encontrado.emit(mejor.item_id, mejor.nombre)
        self.candidatos.emit(
            [(r.item_id, r.nombre, r.puntuacion) for r in ordenados[:3]]
        )
