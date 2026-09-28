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
from .ocr import resumen_tiempos
from .reliquias import LectorBase

log = obtener("cursor")

# Hasta donde amplia RapidOCR el recuadro (620x170) antes de buscar texto. Con los
# 736 de siempre se buscaba a 2684x736; con 608 cuesta ~30 % menos y, medido sobre
# 72 capturas reales (12 recuadros cada una), encuentra 12 nombres mas de los que
# pierde (1) sin colar mas falsos. Con 544 o menos ya perdia nombres.
LADO_MINIMO = 608


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
        self.lado_minimo = LADO_MINIMO  # lo usa LectorBase._leer_protegido

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
        inicio = time.perf_counter()
        # Con el juego en ventana, el recuadro no se sale de ella.
        region = pantalla.region_alrededor_del_cursor(limite=pantalla.region_juego())
        imagen = pantalla.capturar(region)
        if imagen is None:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.candidatos.emit([])
            return
        capturado = time.perf_counter()
        encontrados = self._leer_protegido(imagen, umbral=85)
        fin = time.perf_counter()
        tiempos = getattr(self.motor, "tiempos", None) or {}
        ocr = tiempos.get("total", 0.0)
        log.info("Lectura bajo el cursor en %.0f ms (captura %.0f ms, %s, casado %.0f ms): %d encontrados",
                 (fin - inicio) * 1000, (capturado - inicio) * 1000, resumen_tiempos(tiempos),
                 max(0.0, fin - capturado - ocr) * 1000, len(encontrados or []))
        if encontrados is None:
            self.candidatos.emit([])
            return
        if not encontrados:
            self.estado.emit(t("No se reconoció nada bajo el cursor"))
            self.candidatos.emit([])
            return

        # El que este mas cerca del raton es el que senala. El raton no siempre esta en el
        # centro del recuadro: junto al borde del juego el recuadro se desplaza hacia dentro.
        punto = punto_del_raton(region)

        def distancia(r):
            x = r.caja[0] + r.caja[2] / 2
            y = r.caja[1] + r.caja[3] / 2
            return (x - punto[0]) ** 2 + (y - punto[1]) ** 2

        # Solo cuenta lo que esta encima o debajo del raton: si el nombre que senala no se
        # ha podido leer, el vecino de al lado no es la respuesta (abria la ficha de otra
        # pieza de la pantalla de recompensas).
        cercanos = [r for r in encontrados if alineado_con_raton(r.caja, punto, region.ancho)]
        if not cercanos:
            log.info("Bajo el cursor: nada alineado con el raton (%s)",
                     ", ".join(repr(r.nombre) for r in encontrados))
            self.estado.emit(t("No se reconoció nada bajo el cursor"))
            self.candidatos.emit([])
            return
        ordenados = sorted(cercanos, key=lambda r: (distancia(r), -r.puntuacion))
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


def punto_del_raton(region) -> tuple[float, float]:
    """Donde esta el raton dentro del recuadro capturado; el centro si no se sabe."""
    centro = region.ancho / 2, region.alto / 2
    try:
        cx, cy = pantalla._posicion_cursor()
        x, y = cx - region.x, cy - region.y
    except Exception:  # noqa: BLE001 - sin posicion (o recuadro de prueba): el centro
        return centro
    if 0 <= x < region.ancho and 0 <= y < region.alto:
        return float(x), float(y)
    return centro


def alineado_con_raton(caja, punto: tuple[float, float], ancho_region: int) -> bool:
    """Si el texto leido esta encima o debajo del raton (en horizontal, con holgura).

    En vertical no se limita: el raton suele estar sobre el icono y el nombre va debajo.
    """
    x0, ancho = caja[0], caja[2]
    hueco = max(0.0, x0 - punto[0], punto[0] - (x0 + ancho))
    return hueco <= max(0.5 * ancho, 0.04 * ancho_region)


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
