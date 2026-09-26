"""Captura y lectura de la tarjeta de un agrietado que hay bajo el cursor.

El usuario pone el raton sobre la tarjeta (en el arsenal, en los mods o en el
comercio) y pulsa el atajo: se captura un recuadro alrededor del cursor del
tamano de una tarjeta, se lee con el OCR y `agrietados.lector` lo interpreta.
Las armas con agrietado (y su disposicion) vienen de warframe.market a traves
de `agrietados.mercado`, que las guarda en disco; los nombres en castellano
salen del indice.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Signal, Slot

from ..agrietados import mercado
from ..agrietados.lector import ArmaConocida, LectorTarjeta, TarjetaLeida
from ..idiomas import t
from ..registro_log import obtener
from . import pantalla
from .ocr import ErrorMotorOCR, unir_filas
from .reliquias import LectorBase

log = obtener("captura.agrietados")

# Una tarjeta mide unos 316x400 px a 1080p; el recuadro va holgado y se escala con
# la ventana del juego para que a 1440p siga cabiendo entera.
ANCHO_TARJETA, ALTO_TARJETA = 560, 760
MINIMO_CONFIANZA = 0.4
# Por debajo de esta altura el OCR pierde decimales: se amplia la captura antes de leer.
ALTO_MINIMO_LECTURA = 500


def armas_conocidas(con=None) -> list[ArmaConocida]:
    """Las armas con agrietado, con su nombre en castellano si el indice lo tiene."""
    armas = mercado.compartido().armas()
    nombres_es: dict[str, str] = {}
    if con is not None and armas:
        try:
            filas = con.execute("SELECT unique_name, nombre_es FROM items WHERE nombre_es IS NOT NULL")
            nombres_es = {u: n for u, n in filas if n}
        except Exception as e:  # noqa: BLE001 - sin nombres en castellano se lee igual
            log.debug("Sin nombres en castellano para las armas: %s", e)
    return [ArmaConocida(a.slug, nombres_es.get(a.unique_name) or a.nombre_en, a.nombre_en) for a in armas]


class LectorAgrietado(LectorBase):
    """Lee la tarjeta bajo el cursor en el hilo de captura y la devuelve por senal."""

    leida = Signal(object)  # TarjetaLeida

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(motor_ocr, None, parent)
        self.lector: LectorTarjeta | None = None

    @Slot()
    def iniciar(self) -> None:
        from ..datos import indice

        self._precalentar()
        con = indice.conectar() if indice.hay_indice() else None
        try:
            armas = armas_conocidas(con)
        finally:
            if con is not None:
                con.close()
        if armas:
            self.lector = LectorTarjeta(armas)
        else:
            log.warning("Sin lista de armas con agrietado (hace falta red la primera vez)")
        pantalla.declarar_dpi()

    @Slot()
    def leer_ahora(self) -> None:
        if self._ocupado:
            return
        self._ocupado = True
        try:
            self._leer()
        except Exception:  # noqa: BLE001 - nunca un dialogo de error
            log.exception("Fallo inesperado leyendo un agrietado")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            self.leida.emit(TarjetaLeida(avisos=[t("Fallo al leer la pantalla (mira el registro)")]))
        finally:
            self._ocupado = False

    def _leer(self) -> None:
        if self.lector is None:
            self.iniciar()
            if self.lector is None:
                self.estado.emit(t("Falta la lista de armas con agrietado: hace falta conexion la primera vez"))
                self.leida.emit(TarjetaLeida(avisos=[t("Falta la lista de armas con agrietado: hace falta conexion la primera vez")]))
                return
        if self.motor.fallo:
            self._avisar_motor(self.motor.fallo)
            self.leida.emit(TarjetaLeida(avisos=[t("El lector de pantalla no esta disponible")]))
            return
        self.estado.emit(t("Leyendo la tarjeta bajo el cursor..."))
        juego = pantalla.region_juego()
        escala = (juego.alto / 1080.0) if juego else 1.0
        region = pantalla.region_alrededor_del_cursor(
            int(ANCHO_TARJETA * escala), int(ALTO_TARJETA * escala), limite=juego
        )
        imagen = pantalla.capturar(region)
        if imagen is None:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.leida.emit(TarjetaLeida(avisos=[t("No se pudo capturar la pantalla")]))
            return
        inicio = time.monotonic()
        try:
            tarjeta = leer_tarjeta(imagen, self.motor, self.lector)
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            self.leida.emit(TarjetaLeida(avisos=[t("El lector de pantalla no esta disponible")]))
            return
        log.info("Agrietado leido en %.0f ms: arma=%s nombre=%s stats=%d fiable=%s avisos=%s",
                 (time.monotonic() - inicio) * 1000, tarjeta.arma_slug, tarjeta.nombre,
                 len(tarjeta.estadisticas), tarjeta.fiable, tarjeta.avisos)
        if tarjeta.velado:
            self.estado.emit(t("La tarjeta esta velada: no hay nada que evaluar"))
        elif tarjeta.fiable:
            self.estado.emit(t("Agrietado leido: {arma} {nombre}", arma=tarjeta.arma_nombre, nombre=tarjeta.nombre))
        elif not tarjeta.estadisticas and not tarjeta.arma_texto:
            self.estado.emit(t("No se ve ninguna tarjeta de agrietado bajo el cursor"))
        else:
            self.estado.emit(t("Agrietado leido a medias: revisa lo que falta"))
        self.leida.emit(tarjeta)


def leer_tarjeta(imagen, motor, lector: LectorTarjeta) -> TarjetaLeida:
    """OCR del recuadro (ampliado si es pequeno) e interpretacion de la tarjeta."""
    alto = imagen.shape[0]
    if alto < ALTO_MINIMO_LECTURA:
        try:
            import cv2

            factor = ALTO_MINIMO_LECTURA / alto
            imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
        except ImportError:  # pragma: no cover - cv2 viene con rapidocr
            pass
    lineas = [l for l in unir_filas(motor.leer(imagen)) if l.confianza >= MINIMO_CONFIANZA]
    return lector.leer(lineas)
