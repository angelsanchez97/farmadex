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

import re
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .. import config
from ..datos import indice
from ..registro_log import obtener
from . import inventario as INV
from . import pantalla
from . import perfil_equipo as PE
from .ocr import ErrorMotorOCR, MotorOCR, resumen_tiempos, unir_filas

log = obtener("lector_pasivo")

INTERVALO_MS = 1500
# Con la misma pagina quieta y ya vista se mira la mitad de veces (una captura de la
# ventana entera a 4K no es gratis); al cambiar algo se vuelve a INTERVALO_MS.
INTERVALO_QUIETO_MS = 3000
# La ventana del juego (EnumWindows) se busca como mucho cada tanto, como el hover.
CACHE_VENTANA_S = 2.0
# Por debajo de esta altura de ventana el OCR se hace a 1,5x (ayuda a 1080p).
ALTO_PARA_REESCALAR = 1200
# Por encima de esta altura (4K) el texto se busca en una copia reducida a ella y se lee a
# tamano real: buscar en la captura de 4K entera pedia de golpe ~1,3 GB de memoria cada vez
# que se quedaba quieta una pantalla nueva. A 1440 se busca con el mismo detalle que en una
# ventana de 1440p, que se lee entera.
ALTO_DETECCION_PASIVA = PE.ALTO_DETECCION_PANTALLA
# Pantallas que EE.log identifica y en las que no hay nada que leer.
PANTALLAS_SIN_INTERES = ("arsenal", "pausa", "menu", "carga", "codex")


def motor_de_fondo(motor_ocr: str) -> str:
    """El motor de la lectura pasiva: una sesion propia, salvo con el OCR de Windows."""
    return motor_ocr if motor_ocr in ("winocr", "windows") else "fondo"


# Tras el aviso de EE.log de una pantalla de reliquia, cuanto se deja de mirar como mucho
# (si el aviso de que se cerro no llega). En esa pantalla no hay perfil ni inventario que
# leer y su OCR entero competiria con la lectura de las recompensas.
PAUSA_RELIQUIA_S = 20.0


class LectorPasivo(QObject):
    """Vive en el hilo de captura. `iniciar()` arranca el temporizador."""

    _reliquia_hasta = 0.0  # tambien a nivel de clase: hay pruebas que no pasan por __init__
    pagina_perfil = Signal(object)  # perfil_equipo.PaginaLeida
    pagina_inventario = Signal(object)  # inventario.PaginaInventario
    estado = Signal(str)

    def __init__(self, motor_ocr: str = "rapidocr", perfil: bool = True, inventario: bool = False, parent=None):
        super().__init__(parent)
        self.motor = MotorOCR(motor_de_fondo(motor_ocr))
        self._reliquia_hasta = 0.0  # monotonic hasta el que hay una pantalla de reliquia
        self.activo_perfil = perfil
        self.activo_inventario = inventario
        self.pantalla_log: str | None = None  # lo ultimo que EE.log dijo que esta abierto
        self.detector = PE.DetectorPagina(quietas=2)
        self.casador_equipo = None
        self.casador_inventario = None
        # Las cifras dudosas ("780WNED") solo entran si otra lectura da la misma.
        self.confirmador = INV.ConfirmadorCantidades()
        self._temporizador: QTimer | None = None
        self._ocupado = False
        self._hwnd = None
        self._hwnd_hasta = 0.0
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

    @Slot(str)
    def cambiar_motor(self, motor_ocr: str) -> None:
        """El usuario cambio la lectura de pantalla en Ajustes (modo de OCR)."""
        MotorOCR.olvidar_fallo(motor_ocr)
        self.motor = MotorOCR(motor_de_fondo(motor_ocr))

    @Slot(str)
    def evento(self, nombre: str) -> None:
        """Los avisos de EE.log de la pantalla de reliquia: mientras este abierta, no se mira."""
        if nombre in ("reliquia_abierta", "reliquia_recompensas"):
            self._reliquia_hasta = time.monotonic() + PAUSA_RELIQUIA_S
        elif nombre in ("reliquia_cerrada", "reliquia_elegida"):
            self._reliquia_hasta = 0.0

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
        self._ritmo(INTERVALO_MS)

    # Valores de clase: algunas pruebas crean el lector sin pasar por __init__.
    _hwnd = None
    _hwnd_hasta = 0.0

    def _ritmo(self, intervalo: int) -> None:
        if getattr(self, "_temporizador", None) is not None and self._temporizador.interval() != intervalo:
            self._temporizador.setInterval(intervalo)

    def _ventana_juego(self):
        ahora = time.monotonic()
        if ahora >= self._hwnd_hasta:
            self._hwnd = pantalla.ventana_juego()
            self._hwnd_hasta = ahora + CACHE_VENTANA_S
        return self._hwnd

    @property
    def activo(self) -> bool:
        return self.activo_perfil or self.activo_inventario

    def merece_mirar(self) -> bool:
        """Con EE.log delante: False si lo abierto es una pantalla sin nada que leer."""
        if time.monotonic() < self._reliquia_hasta:
            return False
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
            hwnd = self._ventana_juego()
            if not hwnd or pantalla._ventana_activa() != hwnd:
                self._ritmo(INTERVALO_MS)
                return
            if not self.merece_mirar():
                return
            region = pantalla.region_ventana(hwnd)
            if region is None:
                return
            # Sin esconder Farmadex (cada 1,5 s lo haria parpadear): lo que tapan nuestras
            # ventanas se pinta de negro y, si tapan casi todo, esta vuelta no se lee.
            imagen = pantalla.descartar_propias(pantalla.capturar_sin_ocultar(region), region)
            if imagen is None:
                return
            nueva = self.detector.observar(imagen)
            # Mas vueltas iguales de las que hacen falta para darla por quieta: ya leida.
            self._ritmo(INTERVALO_QUIETO_MS if self.detector._iguales > self.detector.quietas else INTERVALO_MS)
            if not nueva:
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
                        "Pagina de perfil leida sola: categoria=%s completado=%s tarjetas=%d (OCR %.0f ms: %s)",
                        pagina.categoria, pagina.completado, len(pagina.tarjetas), (time.perf_counter() - t0) * 1000,
                        resumen_tiempos(getattr(self.motor, "tiempos", None)),
                    )
                    motivo = self.motivo_para_no_guardar(pagina)
                    if motivo:
                        log.info("Pagina de perfil leida sola NO guardada: %s", motivo)
                    else:
                        self.pagina_perfil.emit(pagina)
            inventario_leido = None
            if perfil_leido is None and self.activo_inventario:
                pagina = INV.interpretar_lineas(lineas, self.casador_inventario, con)
                if pagina.pantalla is not None:
                    self.confirmador.confirmar(pagina)
                    inventario_leido = pagina
                    log.info(
                        "Pantalla de %s leida sola: %d cantidades (%d fiables), %d sin casar (OCR %.0f ms: %s)",
                        pagina.pantalla, len(pagina.cantidades), len(pagina.fiables), len(pagina.sin_casar),
                        (time.perf_counter() - t0) * 1000, resumen_tiempos(getattr(self.motor, "tiempos", None)),
                    )
                    self.pagina_inventario.emit(pagina)
            if perfil_leido is None and inventario_leido is None:
                log.debug("Pantalla quieta sin nada que leer (%d lineas, OCR %.0f ms)", len(lineas), (time.perf_counter() - t0) * 1000)
            return perfil_leido, inventario_leido
        finally:
            con.close()

    def motivo_para_no_guardar(self, pagina) -> str:
        """Por que una pagina de perfil leida sola no se guarda ("" si se guarda).

        La pantalla de perfil de OTRO jugador es igual que la tuya: sin el nombre de
        cuenta de la cabecera casado con el del usuario no se sabe de quien es. Y el
        Codice tambien lleva "COMPLETADO x/y" con nombres de categoria parecidos.
        """
        if pagina.es_codice:
            return "no se ven las pestanas del perfil (puede ser el Codice)"
        nombres = self.nombres_usuario()
        if not nombres:
            return "no se sabe el nombre de cuenta del usuario"
        if not pagina.es_de(nombres):
            return "el nombre de la cabecera no es el del usuario (perfil de otro jugador?)"
        return ""

    def nombres_usuario(self) -> set[str]:
        """El nombre de cuenta del usuario: el del perfil importado y el de EE.log.

        Solo en memoria: nunca se escribe ni se registra (EE.log lleva datos personales).
        """
        ahora = time.monotonic()
        if getattr(self, "_nombres", None) is not None and ahora < getattr(self, "_nombres_hasta", 0.0):
            return self._nombres
        nombres: set[str] = set()
        try:
            nombre = nombre_de_cuenta_eelog(config.cargar().get("ruta_eelog", ""))
            if nombre:
                nombres.add(nombre)
        except Exception:  # noqa: BLE001 - sin EE.log se usa lo demas
            pass
        try:
            import sqlite3

            if config.RUTA_USUARIO_DB.exists():
                con = sqlite3.connect(f"file:{config.RUTA_USUARIO_DB}?mode=ro", uri=True)
                try:
                    fila = con.execute("SELECT valor FROM perfil_meta WHERE clave = 'nombre'").fetchone()
                finally:
                    con.close()
                if fila and fila[0] and fila[0] != "Tenno":  # "Tenno": sin nombre de verdad
                    nombres.add(fila[0])
        except Exception:  # noqa: BLE001 - tabla sin crear: nunca se importo un perfil
            pass
        self._nombres, self._nombres_hasta = nombres, ahora + 60.0
        return nombres

    def _lineas(self, imagen, escala: float):
        if escala != 1.0:
            imagen = PE._reescalar(imagen, escala)
        # La ampliada (1080p a 1,5x) se busca entera, como siempre: solo se reduce la de 4K.
        alto = ALTO_DETECCION_PASIVA if escala == 1.0 else None
        lineas = [l for l in unir_filas(self.motor.leer(imagen, alto_deteccion=alto)) if l.confianza >= 0.4]
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


# "Sys [Info]: Logged in <nombre>" (en versiones viejas seguia " (<id>)"): solo se toma
# el nombre, en memoria.
_RE_LOGIN = re.compile(rb"Logged in ([^\s(]+)")


def nombre_de_cuenta_eelog(ruta) -> str | None:
    """El nombre con el que entro el jugador, del principio de EE.log (o None)."""
    if not ruta:
        return None
    try:
        with open(ruta, "rb") as f:
            datos = f.read(8 * 1024 * 1024)  # el inicio de sesion va en los primeros segundos
    except OSError:
        return None
    m = _RE_LOGIN.search(datos)
    return m.group(1).decode("utf-8", errors="replace") if m else None
