"""'Que es esto': lee el texto que hay alrededor del raton y abre su ficha.

Pulsar el atajo muchas veces seguidas tumbaba el programa: cada pulsacion
encolaba una lectura completa (captura + OCR) en el hilo de captura, y cada una
al acabar volvia a abrir la ventana. Ahora `TurnoLecturas` (en el hilo de la
interfaz) deja una sola lectura en marcha, espera un minimo entre lecturas y,
si se pulsa mientras lee, guarda solo la ultima peticion: las de en medio se
descartan, y el resultado de una lectura que ya tiene otra detras no se ensena.
"""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QTimer, Signal, Slot

from ..idiomas import t
from ..registro_log import obtener
from . import pantalla
from .reliquias import LectorBase

log = obtener("cursor")


class LectorCursor(LectorBase):
    """Captura un recuadro alrededor del cursor y busca ahi un nombre conocido."""

    encontrado = Signal(int, str)  # item_id, nombre
    candidatos = Signal(list)  # [(item_id, nombre, puntuacion)] cuando hay dudas
    terminado = Signal(int)  # numero de la solicitud; siempre, haya ido bien o mal

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(motor_ocr, None, parent)
        # La ultima solicitud que ha pedido la interfaz. La escribe el hilo de la
        # interfaz (un entero: asignacion atomica) y la lee este hilo antes de ensenar
        # un resultado, para no abrir la ficha de algo que ya no se esta mirando.
        self.ultima_pedida = 0

    @Slot()
    def leer_ahora(self) -> None:
        self.leer_solicitud(0)

    @Slot(int)
    def leer_solicitud(self, numero: int) -> None:
        if self._ocupado:
            self.terminado.emit(numero)
            return
        self._ocupado = True
        try:
            self._leer(numero)
        except Exception:  # noqa: BLE001 - ultima red: nunca un dialogo de error
            log.exception("Fallo inesperado leyendo bajo el cursor")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            self.candidatos.emit([])
        finally:
            self._ocupado = False
            self.terminado.emit(numero)

    def _vieja(self, numero: int) -> bool:
        return bool(numero) and numero < self.ultima_pedida

    def _leer(self, numero: int = 0) -> None:
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
        if self._vieja(numero):
            # Mientras se leia se volvio a pulsar el atajo: manda la lectura nueva.
            log.info("Lectura bajo el cursor %d descartada: ya hay otra pedida (%r)", numero, mejor.nombre)
            return
        log.info("Bajo el cursor: %r -> %s", mejor.texto_ocr, mejor.nombre)
        self.estado.emit(t("Bajo el cursor: {nombre}", nombre=mejor.nombre))
        self.encontrado.emit(mejor.item_id, mejor.nombre)
        self.candidatos.emit(
            [(r.item_id, r.nombre, r.puntuacion) for r in ordenados[:3]]
        )


class TurnoLecturas:
    """Una lectura bajo el cursor a la vez, con pausa minima y la ultima peticion gana.

    Vive en el hilo de la interfaz. `lanzar(numero)` manda la lectura al hilo de
    captura; quien la haga tiene que avisar con `terminada(numero)` al acabar.
    Si una lectura no avisa nunca (hilo colgado), a los `LIMITE_S` se deja de
    esperarla para que el atajo no se quede muerto para siempre.
    """

    PAUSA_S = 0.8  # entre el inicio de una lectura y el de la siguiente
    LIMITE_S = 20.0

    def __init__(
        self,
        lanzar: Callable[[int], None],
        pausa_s: float | None = None,
        reloj: Callable[[], float] = time.monotonic,
        programar: Callable[[int, Callable[[], None]], None] | None = None,
    ):
        self._lanzar = lanzar
        self.pausa_s = self.PAUSA_S if pausa_s is None else pausa_s
        self._reloj = reloj
        self._programar = programar or (lambda ms, f: QTimer.singleShot(ms, f))
        self.ultima = 0  # numero de la ultima peticion
        self.en_curso: int | None = None
        self._t_inicio = float("-inf")
        self.pendiente = False
        self._programada = False
        self.descartadas = 0

    @property
    def ocupado(self) -> bool:
        return self.en_curso is not None

    def pedir(self) -> str:
        """Una pulsacion del atajo. Devuelve "lanzada" o "en_cola"."""
        self.ultima += 1
        ahora = self._reloj()
        if self.en_curso is not None and ahora - self._t_inicio > self.LIMITE_S:
            log.warning("La lectura bajo el cursor %d no termino en %.0f s: se deja de esperar",
                        self.en_curso, self.LIMITE_S)
            self.en_curso = None
        if self.en_curso is None and ahora - self._t_inicio >= self.pausa_s and not self._programada:
            self._arrancar()
            return "lanzada"
        if self.pendiente:
            self.descartadas += 1
        self.pendiente = True
        if self.en_curso is None:
            self._programar_siguiente()
        return "en_cola"

    def terminada(self, numero: int) -> bool:
        """La lectura `numero` acabo. Devuelve si su resultado sigue valiendo."""
        vigente = numero == self.ultima
        if numero == self.en_curso or numero == 0:
            self.en_curso = None
        if self.pendiente and self.en_curso is None:
            self._programar_siguiente()
        return vigente

    def _programar_siguiente(self) -> None:
        if self._programada:
            return
        falta = max(0.0, self.pausa_s - (self._reloj() - self._t_inicio))
        self._programada = True
        self._programar(int(falta * 1000), self._siguiente)

    def _siguiente(self) -> None:
        self._programada = False
        if self.pendiente and self.en_curso is None:
            self._arrancar()

    def _arrancar(self) -> None:
        self.pendiente = False
        self.en_curso = self.ultima
        self._t_inicio = self._reloj()
        self._lanzar(self.ultima)
