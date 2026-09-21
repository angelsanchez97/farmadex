"""Arranque de la aplicacion: bandeja, atajos globales y overlay."""

from __future__ import annotations

import sys

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import NOMBRE_APP
from .config import cargar, crear_carpetas
from .hotkeys import GestorHotkeys
from .registro_log import configurar, instalar_gancho_excepciones, obtener
from .ui.overlay import VentanaOverlay, icono_bandeja
from .ui.widgets import HOJA_ESTILOS


class Aplicacion:
    def __init__(self, argv: list[str]):
        self.log = obtener("app")
        self.config = cargar()

        self.qt = QApplication(argv)
        self.qt.setApplicationName(NOMBRE_APP)
        self.qt.setQuitOnLastWindowClosed(False)  # vive en la bandeja
        self.qt.setStyleSheet(HOJA_ESTILOS)

        self.icono = QIcon(icono_bandeja())
        self.ventana = VentanaOverlay()
        self.ventana.cerrar_programa.connect(self.salir)
        self.ventana.ajustes.hotkeys_cambiadas.connect(self.recargar_hotkeys)
        self.ventana.ajustes.opacidad_cambiada.connect(self.ventana.aplicar_opacidad)

        self.bandeja = self._crear_bandeja()
        self.hotkeys: GestorHotkeys | None = None
        self.recargar_hotkeys(
            {
                "overlay": self.config["hotkey_overlay"],
                "cursor": self.config["hotkey_cursor"],
                "reliquias": self.config["hotkey_reliquias"],
            }
        )

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

    # -- atajos --------------------------------------------------------------

    def recargar_hotkeys(self, combinaciones: dict[str, str]) -> None:
        if self.hotkeys:
            self.hotkeys.parar()
        self.hotkeys = GestorHotkeys(combinaciones)
        self.hotkeys.pulsada.connect(self._hotkey)
        self.hotkeys.fallo.connect(self._fallo_hotkey)
        self.hotkeys.start()

    def _hotkey(self, nombre: str) -> None:
        if nombre == "overlay":
            self.ventana.alternar()
        elif nombre == "reliquias":
            self.ventana.leer_recompensas()
        elif nombre == "cursor":
            self.ventana.leer_cursor()

    def _fallo_hotkey(self, nombre: str, motivo: str) -> None:
        self.log.warning("Atajo %s no registrado: %s", nombre, motivo)
        self.bandeja.showMessage(
            NOMBRE_APP, f"No se pudo registrar el atajo '{nombre}': {motivo}", self.icono, 6000
        )

    # -- ciclo de vida ---------------------------------------------------------

    def salir(self) -> None:
        if self.hotkeys:
            self.hotkeys.parar()
        self.ventana.cerrar_de_verdad()
        self.bandeja.hide()
        self.qt.quit()

    def ejecutar(self) -> int:
        self.ventana.mostrar()
        return self.qt.exec()


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
    crear_carpetas()
    configurar()
    log = obtener("app")
    log.info("Arrancando %s", NOMBRE_APP)

    argumentos = argv if argv is not None else sys.argv
    if "--probar-ocr" in argumentos:
        return probar_ocr()

    # El gancho va antes de construir nada: un fallo al montar la ventana tiene que
    # quedar en el log aunque el ejecutable no tenga consola. Si aun no hay
    # QApplication, el dialogo falla y el propio gancho lo traga; el log queda.
    instalar_gancho_excepciones(
        lambda texto: QMessageBox.critical(None, f"{NOMBRE_APP}: error", texto)
    )
    try:
        aplicacion = Aplicacion(argumentos)
    except Exception:
        log.exception("No se pudo arrancar %s", NOMBRE_APP)
        raise
    return aplicacion.ejecutar()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
