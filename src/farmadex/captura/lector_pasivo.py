"""Lectura pasiva de las pantallas del menu mientras el usuario juega.

Sin pulsar nada: cada `INTERVALO_MS`, si Warframe esta en primer plano, se
captura su ventana y se compara una miniatura con la anterior (`DetectorPagina`,
~6 ms). Solo cuando la pantalla ha cambiado y se ha quedado quieta se pasa el
OCR entero una vez (~0,9 s a 1440p con 4 hilos, en su propio hilo), y de esas
lineas se intenta sacar:

- una pagina de Perfil > Equipamiento (`perfil_equipo.interpretar_lineas`): si
  aparece la barra de categoria con "COMPLETADO x/y", se guarda como si el
  usuario hubiera pulsado F9 en la herramienta de escaneo;
- una pagina de Inventario o Fundicion (`inventario.interpretar_lineas`): solo
  si el titulo de la pantalla se ha leido y los nombres casan sin dudas.

Coste medido (RTX 5080 / Ryzen 7 9800X3D, captura de 2560x1440): captura 42 ms
+ huella 6 ms cada 1,5 s mientras el juego esta delante, o sea ~3 % de un
nucleo; durante la partida la imagen cambia sin parar y nunca se llega al OCR.
El OCR corre una vez por pantalla de menu nueva y quieta. Con EE.log delante se
ahorra aun mas: si el log dice que lo abierto es el arsenal o el menu de pausa,
no se mira. F9 en `herramientas/escanear_perfil.py` sigue siendo el respaldo.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..datos import indice
from ..registro_log import obtener
from . import inventario as INV
from . import pantalla
from . import perfil_equipo as PE
from .ocr import ErrorMotorOCR, MotorOCR, unir_filas

log = obtener("lector_pasivo")

INTERVALO_MS = 1500
# Por debajo de esta altura de ventana el OCR se hace a 1,5x (ayuda a 1080p).
ALTO_PARA_REESCALAR = 1200
# Pantallas que EE.log identifica y en las que no hay nada que leer.
PANTALLAS_SIN_INTERES = ("arsenal", "pausa", "menu", "carga", "codex")


class LectorPasivo(QObject):
    """Vive en el hilo de captura. `iniciar()` arranca el temporizador."""

    pagina_perfil = Signal(object)  # perfil_equipo.PaginaLeida
    pagina_inventario = Signal(object)  # inventario.PaginaInventario
    estado = Signal(str)

    def __init__(self, motor_ocr: str = "rapidocr", perfil: bool = True, inventario: bool = False, parent=None):
        super().__init__(parent)
        self.motor = MotorOCR(motor_ocr)
        self.activo_perfil = perfil
        self.activo_inventario = inventario
        self.pantalla_log: str | None = None  # lo ultimo que EE.log dijo que esta abierto
        self.detector = PE.DetectorPagina(quietas=2)
        self.casador_equipo = None
        self.casador_inventario = None
        self._temporizador: QTimer | None = None
        self._ocupado = False
        self.lecturas = 0
        self.segundos_ocr = 0.0

    @Slot()
    def iniciar(self) -> None:
        if self._temporizador is not None:
            return
        self._temporizador = QTimer(self)
        self._temporizador.setInterval(INTERVALO_MS)
        self._temporizador.timeout.connect(self.tic)
        self._temporizador.start()
        log.info("Lector pasivo en marcha (perfil=%s, inventario=%s)", self.activo_perfil, self.activo_inventario)

    @Slot()
    def parar(self) -> None:
        if self._temporizador is not None:
            self._temporizador.stop()

    @Slot(bool)
    def activar_perfil(self, activo: bool) -> None:
        self.activo_perfil = activo

    @Slot(bool)
    def activar_inventario(self, activo: bool) -> None:
        self.activo_inventario = activo

    @Slot(str, str)
    def pantalla_juego(self, accion: str, nombre: str) -> None:
        """Lo que EE.log cuenta de las pantallas del menu; sirve para no mirar de mas."""
        if accion == "abierta":
            self.pantalla_log = nombre
        elif accion == "pausa":
            self.pantalla_log = "pausa"
        else:
            self.pantalla_log = None
        # Al cambiar de pantalla la siguiente captura quieta es una pagina nueva.
        self.detector = PE.DetectorPagina(quietas=2)

    @property
    def activo(self) -> bool:
        return self.activo_perfil or self.activo_inventario

    def merece_mirar(self) -> bool:
        """Con EE.log delante: False si lo abierto es una pantalla sin nada que leer."""
        if self.pantalla_log is None or self.pantalla_log.startswith("?"):
            return True  # sin dato, o pantalla nueva sin clasificar: decide el OCR
        if self.pantalla_log in PANTALLAS_SIN_INTERES:
            return False
        return True  # perfil, inventario, fundicion o cualquier otra que no este vetada

    @Slot()
    def tic(self) -> None:
        if self._ocupado or not self.activo:
            return
        try:
            hwnd = pantalla.ventana_juego()
            if not hwnd or pantalla._ventana_activa() != hwnd:
                return
            if not self.merece_mirar():
                return
            region = pantalla.region_ventana(hwnd)
            if region is None:
                return
            imagen = pantalla.capturar(region)
            if imagen is None or not self.detector.observar(imagen):
                return
            self._ocupado = True
            self.leer_imagen(imagen)
        except Exception:  # noqa: BLE001 - un fallo aqui no puede tumbar el hilo
            log.exception("Fallo en la lectura pasiva")
        finally:
            self._ocupado = False

    def leer_imagen(self, imagen) -> tuple[object | None, object | None]:
        """Un OCR y las dos interpretaciones; emite lo que haya. Probable sin ventana."""
        if not self._preparar():
            return None, None
        escala = 1.5 if imagen.shape[0] < ALTO_PARA_REESCALAR else 1.0
        t0 = time.perf_counter()
        try:
            lineas = self._lineas(imagen, escala)
        except ErrorMotorOCR as e:
            log.warning("Lector pasivo sin motor OCR: %s", e)
            self.activo_perfil = self.activo_inventario = False
            return None, None
        self.lecturas += 1
        self.segundos_ocr += time.perf_counter() - t0
        con = indice.conectar()
        try:
            perfil_leido = None
            if self.activo_perfil:
                pagina = PE.interpretar_lineas(lineas, self.casador_equipo, con)
                if pagina.categoria is not None or pagina.completado is not None:
                    perfil_leido = pagina
                    log.info(
                        "Pagina de perfil leida sola: categoria=%s completado=%s tarjetas=%d (OCR %.0f ms)",
                        pagina.categoria, pagina.completado, len(pagina.tarjetas), (time.perf_counter() - t0) * 1000,
                    )
                    self.pagina_perfil.emit(pagina)
            inventario_leido = None
            if perfil_leido is None and self.activo_inventario:
                pagina = INV.interpretar_lineas(lineas, self.casador_inventario, con)
                if pagina.pantalla is not None:
                    inventario_leido = pagina
                    log.info(
                        "Pantalla de %s leida sola: %d cantidades (%d fiables), %d sin casar (OCR %.0f ms)",
                        pagina.pantalla, len(pagina.cantidades), len(pagina.fiables), len(pagina.sin_casar),
                        (time.perf_counter() - t0) * 1000,
                    )
                    self.pagina_inventario.emit(pagina)
            if perfil_leido is None and inventario_leido is None:
                log.debug("Pantalla quieta sin nada que leer (%d lineas, OCR %.0f ms)", len(lineas), (time.perf_counter() - t0) * 1000)
            return perfil_leido, inventario_leido
        finally:
            con.close()

    def _lineas(self, imagen, escala: float):
        if escala != 1.0:
            imagen = PE._reescalar(imagen, escala)
        lineas = [l for l in unir_filas(self.motor.leer(imagen)) if l.confianza >= 0.4]
        if escala != 1.0:
            for l in lineas:
                l.x, l.y = int(l.x / escala), int(l.y / escala)
                l.ancho, l.alto = int(l.ancho / escala), int(l.alto / escala)
        return lineas

    def _preparar(self) -> bool:
        if self.casador_equipo is not None and self.casador_inventario is not None:
            return True
        if not indice.hay_indice():
            return False
        con = indice.conectar()
        try:
            self.casador_equipo = PE.casador_equipamiento(con)
            self.casador_inventario = INV.casador_inventario(con)
        finally:
            con.close()
        pantalla.declarar_dpi()
        return True
