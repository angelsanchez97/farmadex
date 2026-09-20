"""Lectura de la pantalla de recompensas de reliquia y etiquetas encima de ella.

Cuando el juego abre esa pantalla (lo dice EE.log) o cuando se pulsa el atajo,
se captura la ventana, se leen los 1-4 nombres y se pinta encima de cada uno
lo que interesa: platino, si esta en boveda y si te sirve para un objetivo.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..idiomas import t
from ..registro_log import obtener
from . import pantalla
from .ocr import Casador, ErrorMotorOCR, MotorOCR, Reconocido, reconocer

log = obtener("reliquias")

# La franja de la pantalla donde el juego pinta las recompensas (proporciones).
# Las tarjetas estan centradas en vertical y repartidas en horizontal.
FRANJA = (0.10, 0.30, 0.90, 0.72)

AVISO_MOTOR = "No se pudo cargar el lector de pantalla (mira el registro)"
AVISO_DATOS = "Los datos del juego todavia no estan preparados"

CATEGORIAS_RECOMPENSA = (
    "Warframes",
    "Primary",
    "Secondary",
    "Melee",
    "Arch-Gun",
    "Arch-Melee",
    "Archwing",
    "Sentinels",
    "SentinelWeapons",
    "Pets",
    "Mods",
    "Resources",
    "Misc",
    "Gear",
    "Railjack",
)


@dataclass
class Recompensa:
    item_id: int
    nombre: str
    texto_ocr: str
    caja: tuple[int, int, int, int]  # en coordenadas de pantalla
    ducados: int | None = None
    vaulted: bool = False
    objetivo: str = ""
    platino: int | None = None
    # Lo rellena `completar`:
    unique_name: str = ""
    market_slug: str = ""
    comerciable: bool = True
    # Lo rellena `comparador.puntuar`:
    rareza: str | None = None  # "comun", "poco comun", "rara" o None si no se sabe
    valor: float | None = None  # platino equivalente; None = no se pudo valorar
    mejor: bool = False  # la que conviene elegir
    nota: str = ""  # por que falta algo ("Sin precio: ...")


class LectorBase(QObject):
    """Lo comun a los lectores: motor compartido, casador y fallos que no revientan.

    Un fallo del motor OCR (modulo que PyInstaller no arrastro, modelo que falta,
    paquete de idioma de Windows sin instalar) se registra, se avisa UNA vez por
    la senal `estado` y la aplicacion sigue con el resto de pestanas. Al cambiar
    el motor en Ajustes (`cambiar_motor`) se vuelve a intentar.
    """

    estado = Signal(str)

    def __init__(self, motor_ocr: str = "rapidocr", categorias=None, parent=None):
        super().__init__(parent)
        self.motor = MotorOCR(motor_ocr)
        self.categorias = categorias
        self.casador: Casador | None = None
        self._ocupado = False
        self._avisado_motor = False

    @Slot()
    def iniciar(self) -> None:
        """Prepara el casador con el indice. Si no hay indice, se reintenta luego."""
        from ..datos import indice

        if not indice.hay_indice():
            self.casador = None
            return
        con = indice.conectar()
        try:
            self.casador = (
                Casador(con, self.categorias) if self.categorias else Casador(con)
            )
        finally:
            con.close()
        pantalla.declarar_dpi()

    @Slot(str)
    def cambiar_motor(self, motor_ocr: str) -> None:
        """El usuario eligio otro motor en Ajustes: se vuelve a intentar con el."""
        MotorOCR.olvidar_fallo(motor_ocr)
        self.motor = MotorOCR(motor_ocr)
        self._avisado_motor = False

    def _preparado(self) -> bool:
        """Casador listo y motor sin fallo conocido; si no, avisa y devuelve False."""
        if self.casador is None:
            self.iniciar()
            if self.casador is None:
                self.estado.emit(t(AVISO_DATOS))
                return False
        if self.motor.fallo:
            self._avisar_motor(self.motor.fallo)
            return False
        return True

    def _avisar_motor(self, motivo: str) -> None:
        if not self._avisado_motor:
            self._avisado_motor = True
            log.error("Lector de pantalla no disponible: %s", motivo)
            self.estado.emit(t(AVISO_MOTOR))
        else:
            log.debug("Lector de pantalla sigue sin estar disponible: %s", motivo)

    def _leer_protegido(self, imagen, umbral: int) -> list[Reconocido] | None:
        """`reconocer` sin que nada se propague: None si el motor no esta disponible."""
        try:
            return reconocer(imagen, self.motor, self.casador, umbral=umbral)
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            return None
        except Exception:  # noqa: BLE001 - un fallo de lectura no puede tumbar la app
            log.exception("Fallo leyendo la pantalla")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            return None


class LectorRecompensas(LectorBase):
    """Hace la captura y el OCR en su hilo; devuelve las recompensas reconocidas."""

    leidas = Signal(list)  # list[Recompensa]

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(motor_ocr, CATEGORIAS_RECOMPENSA, parent)

    @Slot()
    def leer_ahora(self) -> None:
        """Captura la franja de recompensas y reconoce lo que haya."""
        if self._ocupado:
            return
        self._ocupado = True
        try:
            self._leer()
        except Exception:  # noqa: BLE001 - ultima red: nunca un dialogo de error
            log.exception("Fallo inesperado leyendo las recompensas")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            self.leidas.emit([])
        finally:
            self._ocupado = False

    def _leer(self) -> None:
        if not self._preparado():
            self.leidas.emit([])
            return
        self.estado.emit(t("Leyendo la pantalla..."))
        ventana = pantalla.region_objetivo()
        region = ventana.recortar(*FRANJA)
        imagen = pantalla.capturar(region)
        if imagen is None:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.leidas.emit([])
            return
        encontrados = self._leer_protegido(imagen, umbral=80)
        if encontrados is None:
            self.leidas.emit([])
            return
        if not encontrados:
            # Si un parche mueve las tarjetas fuera de la franja habitual, se lee
            # la ventana entera antes de dar la pantalla por vacia.
            log.info("Nada en la franja de recompensas; se prueba con la ventana entera")
            imagen = pantalla.capturar(ventana)
            if imagen is not None:
                region = ventana
                encontrados = self._leer_protegido(imagen, umbral=80)
                if encontrados is None:
                    self.leidas.emit([])
                    return
                if encontrados:
                    log.warning(
                        "Las recompensas estaban fuera de la franja esperada: "
                        "puede que el juego haya cambiado la pantalla"
                    )
        recompensas = [
            Recompensa(
                item_id=r.item_id,
                nombre=r.nombre,
                texto_ocr=r.texto_ocr,
                caja=(
                    region.x + r.caja[0],
                    region.y + r.caja[1],
                    r.caja[2],
                    r.caja[3],
                ),
            )
            for r in _quitar_repetidos(encontrados)
        ]
        log.info(
            "Recompensas leidas: %s",
            ", ".join(f"{r.texto_ocr} -> {r.nombre}" for r in recompensas) or "ninguna",
        )
        self.estado.emit(
            t("{n} recompensas reconocidas", n=len(recompensas)) if recompensas else
            t("No se reconocio ninguna recompensa")
        )
        self.leidas.emit(recompensas)


def _quitar_repetidos(encontrados: list[Reconocido]) -> list[Reconocido]:
    """El OCR parte los nombres en varias lineas: se queda la mejor por objeto."""
    mejores: dict[int, Reconocido] = {}
    for r in encontrados:
        previo = mejores.get(r.item_id)
        if previo is None or r.puntuacion > previo.puntuacion:
            mejores[r.item_id] = r
    return sorted(mejores.values(), key=lambda r: r.caja[0])


def completar(
    recompensas: list[Recompensa], indice_con: sqlite3.Connection, usuario_con=None
) -> list[Recompensa]:
    """Anade ducados, estado de boveda y si cubre algun objetivo pendiente."""
    for r in recompensas:
        fila = indice_con.execute(
            "SELECT ducados, vaulted, unique_name, market_slug, comerciable FROM items WHERE id = ?",
            (r.item_id,),
        ).fetchone()
        if not fila:
            continue
        r.ducados, r.vaulted = fila[0], bool(fila[1])
        r.unique_name = fila[2] or ""
        r.market_slug = fila[3] or ""
        r.comerciable = bool(fila[4])
        if usuario_con is not None:
            objetivo = usuario_con.execute(
                "SELECT nombre, cantidad_actual, cantidad_objetivo FROM objetivos "
                "WHERE item_unique_name = ? AND completado_en IS NULL",
                (fila[2],),
            ).fetchone()
            if objetivo:
                r.objetivo = f"{objetivo[1]}/{objetivo[2]}"
    return recompensas


def resumir(recompensas: list[Recompensa]) -> str:
    """Una linea con lo leido, para cuando no se puede pintar encima del juego."""
    trozos = []
    for r in recompensas:
        detalles = []
        if r.platino is not None:
            detalles.append(t("{n} platino", n=r.platino))
        if r.ducados:
            detalles.append(t("{n} ducados", n=r.ducados))
        if r.vaulted:
            detalles.append(t("En boveda"))
        if r.objetivo:
            detalles.append(t("Objetivo: {nombre}", nombre=r.objetivo))
        if r.nota:
            detalles.append(r.nota)
        nombre = t("MEJOR: {nombre}", nombre=r.nombre) if r.mejor else r.nombre
        trozos.append(f"{nombre} ({', '.join(detalles)})" if detalles else nombre)
    return " · ".join(trozos)


class DisparadorAutomatico(QObject):
    """Convierte los eventos de EE.log en una lectura, con su espera y su interruptor."""

    disparar = Signal()

    ESPERA_MS = 1500  # lo que tarda la animacion de la pantalla de recompensas

    def __init__(self, activo: bool = True, parent=None):
        super().__init__(parent)
        self.activo = activo
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self.disparar.emit)

    def evento(self, nombre: str) -> None:
        if nombre == "reliquia_recompensas" and self.activo:
            self._temporizador.start(self.ESPERA_MS)
        elif nombre in ("reliquia_cerrada", "reliquia_elegida"):
            self._temporizador.stop()
