"""Arranque de la aplicacion: bandeja, atajos globales y overlay."""

from __future__ import annotations

import os
import sys
import threading

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import NOMBRE_APP, VERSION, arranque, instancia_unica
from .config import cargar, crear_carpetas
from .hotkeys import GestorHotkeys
from .registro_log import configurar, instalar_gancho_excepciones, obtener
from .ui import rueda
from .ui.overlay import VentanaOverlay, icono_bandeja
from .ui.widgets import HOJA_ESTILOS

# "Farmadex.exe --cerrar": pide al Farmadex abierto que se cierre (lo usa quien
# necesite sustituir sus ficheros) y espera a que lo haga.
ARGUMENTO_CERRAR = "--cerrar"
# Tras salir del bucle de Qt, lo maximo que se espera a que el proceso termine solo.
# Un hilo que no suelta (red colgada, OCR a medias) dejaba un Farmadex.exe fantasma
# que el instalador de la actualizacion esperaba en vano: pasado esto, se corta.
ESPERA_CIERRE_S = 12.0


class Aplicacion:
    def __init__(self, argv: list[str], en_bandeja: bool = False, instancia=None):
        self.log = obtener("app")
        self.config = cargar()
        self.en_bandeja = en_bandeja  # arrancado por Windows: sin ventana hasta que se pida
        self._saliendo = False
        self.instancia = instancia

        self.qt = QApplication.instance() or QApplication(argv)
        self.qt.setApplicationName(NOMBRE_APP)
        self.qt.setQuitOnLastWindowClosed(False)  # vive en la bandeja
        self.qt.setStyleSheet(HOJA_ESTILOS)
        # La rueda del raton no cambia desplegables ni numeros al pasar por encima.
        rueda.instalar(self.qt)

        self.icono = QIcon(icono_bandeja())
        self.ventana = VentanaOverlay()
        self.ventana.cerrar_programa.connect(self.salir)
        self.ventana.ajustes.hotkeys_cambiadas.connect(self.recargar_hotkeys)
        self.ventana.ajustes.opacidad_cambiada.connect(self.ventana.aplicar_opacidad)

        self.bandeja = self._crear_bandeja()
        # Avisos que tienen que verse con la ventana escondida (reliquia en pantalla
        # completa exclusiva, lector que no carga): globo de la bandeja.
        self.ventana.aviso_bandeja.connect(self._aviso_bandeja)
        self.hotkeys: GestorHotkeys | None = None
        self.recargar_hotkeys(
            {
                "overlay": self.config["hotkey_overlay"],
                "cursor": self.config["hotkey_cursor"],
                "reliquias": self.config["hotkey_reliquias"],
                "build": self.config.get("hotkey_build", ""),
                "agrietado": self.config.get("hotkey_agrietado", ""),
            }
        )
        # Ordenes de otros procesos: un segundo Farmadex que quiere que nos ensenemos,
        # o el instalador que necesita que nos cerremos para sustituir los ficheros.
        self.instancia = instancia
        if instancia is not None:
            instancia.orden_recibida.connect(self._orden_externa)
            instancia.entregar_pendientes()

    def _orden_externa(self, orden: str) -> None:
        if orden == instancia_unica.ORDEN_MOSTRAR:
            self.log.info("Otro Farmadex ha intentado abrirse: se ensena este")
            self.ventana.mostrar()
        elif orden == instancia_unica.ORDEN_SALIR:
            self.log.info("Otro proceso (instalador) pide cerrar Farmadex")
            self.salir()

    # -- bandeja ------------------------------------------------------------

    def _crear_bandeja(self) -> QSystemTrayIcon:
        bandeja = QSystemTrayIcon(self.icono)
        bandeja.setToolTip(f"{NOMBRE_APP} ({self.config['hotkey_overlay']})")
        menu = QMenu()

        mostrar = QAction("Mostrar", menu)
        mostrar.triggered.connect(self.ventana.mostrar)
        ajustes = QAction("Ajustes", menu)
        ajustes.triggered.connect(self._abrir_ajustes)
        actualizar = QAction("Actualizar datos", menu)
        actualizar.triggered.connect(lambda: self.ventana.preparar_datos(forzar=True))
        salir = QAction("Salir", menu)
        salir.triggered.connect(self.salir)

        for accion in (mostrar, ajustes, actualizar):
            menu.addAction(accion)
        menu.addSeparator()
        menu.addAction(salir)

        bandeja.setContextMenu(menu)
        bandeja.activated.connect(
            lambda motivo: self.ventana.alternar()
            if motivo == QSystemTrayIcon.Trigger
            else None
        )
        bandeja.show()
        return bandeja

    def _abrir_ajustes(self) -> None:
        self.ventana.mostrar()
        self.ventana.pestanas.setCurrentWidget(self.ventana.ajustes)

    def _aviso_bandeja(self, texto: str) -> None:
        self.bandeja.showMessage(NOMBRE_APP, texto, self.icono, 10000)

    # -- atajos --------------------------------------------------------------

    def recargar_hotkeys(self, combinaciones: dict[str, str]) -> None:
        if self.hotkeys:
            self.hotkeys.parar()
        self.hotkeys = GestorHotkeys(combinaciones)
        self.hotkeys.pulsada.connect(self._hotkey)
        self.hotkeys.fallo.connect(self._fallo_hotkey)
        self.hotkeys.start()

    def _hotkey(self, nombre: str) -> None:
        self.log.debug("Atajo pulsado: %s", nombre)
        if nombre == "overlay":
            self.ventana.alternar()
        elif nombre == "reliquias":
            self.ventana.leer_recompensas()
        elif nombre == "cursor":
            self.ventana.leer_cursor()
        elif nombre == "build":
            self.ventana.leer_build()
        elif nombre == "agrietado":
            self.ventana.leer_agrietado()

    def _fallo_hotkey(self, nombre: str, motivo: str) -> None:
        self.log.warning("Atajo %s no registrado: %s", nombre, motivo)
        self.bandeja.showMessage(
            NOMBRE_APP, f"No se pudo registrar el atajo '{nombre}': {motivo}", self.icono, 6000
        )

    # -- ciclo de vida ---------------------------------------------------------

    def salir(self) -> None:
        if self._saliendo:
            return
        self._saliendo = True
        self.log.info("Saliendo de %s", NOMBRE_APP)
        if self.hotkeys:
            self.hotkeys.parar()
        try:
            self.ventana.cerrar_de_verdad()
        except Exception:  # noqa: BLE001 - salir tiene que salir aunque algo falle al cerrar
            self.log.exception("Fallo cerrando la ventana; se sale igualmente")
        self.bandeja.hide()
        if self.instancia is not None:
            # Se suelta ya: si el instalador vuelve a abrir Farmadex mientras este
            # termina de morir, el nuevo no tiene que confundirlo con uno abierto.
            self.instancia.soltar()
        self.qt.quit()

    def ejecutar(self) -> int:
        if self.en_bandeja:
            # Arrancado con Windows: se queda en la bandeja vigilando EE.log; la
            # ventana sale con el atajo o desde el icono, este o no el juego abierto.
            self.log.info("Arrancado en la bandeja (inicio con Windows)")
        else:
            self.ventana.mostrar()
        codigo = self.qt.exec()
        self.log.info("%s cerrado (codigo %s)", NOMBRE_APP, codigo)
        return codigo


def vigilar_cierre(codigo: int, espera_s: float = ESPERA_CIERRE_S, salir=os._exit) -> threading.Timer:
    """Garantiza que el proceso muere aunque un hilo se quede colgado al salir.

    El temporizador es un hilo "daemon": si Python termina por las buenas, muere con
    el sin hacer nada; si algo retiene el proceso, a los `espera_s` lo corta.
    """
    log = obtener("app")

    def cortar():
        vivos = [h.name for h in threading.enumerate() if h is not threading.current_thread() and not h.daemon]
        log.warning("El proceso no terminaba solo %.0f s despues de salir (hilos vivos: %s): se corta",
                    espera_s, ", ".join(vivos) or "ninguno de Python")
        logging_flush()
        salir(codigo)

    temporizador = threading.Timer(espera_s, cortar)
    temporizador.daemon = True
    temporizador.name = "vigilante-cierre"
    temporizador.start()
    return temporizador


def logging_flush() -> None:
    import logging

    for manejador in logging.getLogger(NOMBRE_APP.lower()).handlers:
        try:
            manejador.flush()
        except Exception:  # noqa: BLE001
            pass


def cerrar_la_abierta() -> int:
    """`--cerrar`: pide al Farmadex abierto que salga y espera a que suelte el candado."""
    log = obtener("app")
    if not instancia_unica.avisar_a_la_abierta(instancia_unica.ORDEN_SALIR, espera_s=1.0):
        log.info("--cerrar: no habia ningun Farmadex abierto")
        return 0
    if instancia_unica.esperar_a_que_se_cierre(espera_s=60):
        log.info("--cerrar: el Farmadex abierto se ha cerrado")
        return 0
    log.warning("--cerrar: el Farmadex abierto no se cerro a tiempo")
    return 1


def probar_ocr() -> int:
    """Comprueba que el lector de pantalla funciona en esta instalacion.

    Existe porque un fallo de empaquetado (RapidOCR carga sus piezas por nombre)
    solo se nota al pulsar el atajo dentro del juego. Con `Farmadex.exe --probar-ocr`
    se ve en dos segundos y sin abrir ninguna ventana.
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from .captura.ocr import MotorOCR

    log = obtener("prueba")
    imagen = Image.new("RGB", (900, 120), (12, 16, 22))
    dibujo = ImageDraw.Draw(imagen)
    try:
        fuente = ImageFont.truetype("seguisb.ttf", 40)
    except OSError:
        fuente = ImageFont.load_default()
    dibujo.text((30, 35), "SISTEMAS DE ASH PRIME", fill=(232, 236, 245), font=fuente)

    try:
        leidos = MotorOCR().leer(np.array(imagen)[:, :, ::-1].copy())
    except Exception as e:  # noqa: BLE001 - es justo lo que se quiere detectar
        log.exception("El lector de pantalla no funciona")
        print(f"OCR NO FUNCIONA: {type(e).__name__}: {e}")
        return 1

    textos = [t.texto for t in leidos]
    print(f"OCR OK: {textos}")
    return 0 if any("ASH" in t.upper() for t in textos) else 2


def main(argv: list[str] | None = None) -> int:
    argumentos = argv if argv is not None else sys.argv
    # El reproductor de guias es este mismo programa con --video (farmadex/video.py): va
    # antes de todo, sin carpetas, registro ni ventana de la aplicacion.
    from .video import enrutar

    codigo_video = enrutar(argumentos[1:])
    if codigo_video is not None:
        return codigo_video
    crear_carpetas()
    configurar()
    log = obtener("app")
    log.info("Arrancando %s", NOMBRE_APP)

    if "--probar-ocr" in argumentos:
        # Que en el registro se distinga de una sesion de verdad: esto escribe dos
        # lineas y sale, y ya se ha leido como "el programa se quedo mudo".
        log.info("Modo --probar-ocr: solo se prueba el lector de pantalla y se sale; no es una sesion")
        return probar_ocr()

    # El gancho va antes de construir nada: un fallo al montar la ventana tiene que
    # quedar en el log aunque el ejecutable no tenga consola. Si aun no hay
    # QApplication, el dialogo falla y el propio gancho lo traga; el log queda.
    instalar_gancho_excepciones(
        lambda texto: QMessageBox.critical(None, f"{NOMBRE_APP}: error", texto)
    )
    qt = QApplication.instance() or QApplication(argumentos)
    if ARGUMENTO_CERRAR in argumentos:
        return cerrar_la_abierta()

    en_bandeja = arranque.arrancado_en_bandeja(argumentos)
    instancia = instancia_unica.InstanciaUnica()
    if not instancia.adquirir():
        # Ya hay un Farmadex abierto (instalado o portable): se le pide que se ensene
        # y este se va. Si lo abrio Windows al arrancar, ni eso: el otro ya esta.
        if en_bandeja:
            log.info("Ya hay un %s abierto: este arranque con Windows no hace nada", NOMBRE_APP)
            return 0
        llego = instancia_unica.avisar_a_la_abierta(instancia_unica.ORDEN_MOSTRAR)
        log.info("Ya hay un %s abierto: %s", NOMBRE_APP,
                 "se le ha pedido que se ensene" if llego else "no contesta; este se cierra igualmente")
        return 0
    instancia.escuchar()

    try:
        aplicacion = Aplicacion(argumentos, en_bandeja=en_bandeja, instancia=instancia)
    except Exception:
        log.exception("No se pudo arrancar %s %s", NOMBRE_APP, VERSION)
        raise
    codigo = aplicacion.ejecutar()
    instancia.soltar()
    vigilar_cierre(codigo)
    return codigo


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
