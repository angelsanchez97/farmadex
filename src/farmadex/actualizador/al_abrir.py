"""Actualizar al abrir: si hay version nueva, se instala antes de ensenar la ventana.

Va en el arranque (app.main), despues de coger la instancia unica y antes de
construir la ventana principal. Solo en la version instalada con el instalador y
con "Actualizar automaticamente" y "Actualizar al abrir Farmadex" activados.

1. Si ya hay un instalador bajado y comprobado de una version mas nueva (lo apunta
   `descarga.apuntar_lista`), se vuelve a comprobar su SHA-256 y se instala ya.
2. Si no, se pregunta a GitHub con un plazo corto; si hay version nueva, una
   ventanita ensena la descarga con su barra y un boton "Abrir sin actualizar".
   Al acabar, se instala.

La instalacion es la de siempre (setup silencioso que vuelve a abrir Farmadex con
--tras-actualizar). Cualquier fallo (sin red, huella que no cuadra, setup que no
arranca) deja arrancar normal: la ventana principal lo vuelve a intentar en
segundo plano como siempre.

Arrancado con Windows (--bandeja) nunca sale ninguna ventana: solo se instala lo
que ya estuviera bajado, sin ventana de progreso, y Farmadex vuelve a la bandeja.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .. import NOMBRE_APP
from ..idiomas import t
from ..registro_log import obtener
from . import descarga, instalacion
from .app import ComprobadorApp, Version, es_mas_nueva

log = obtener("actualizador.al_abrir")

# El arranque que hace el propio instalador al acabar: no se vuelve a mirar nada.
ARGUMENTO_TRAS_ACTUALIZAR = "--tras-actualizar"
# Lo que se espera a GitHub antes de arrancar normal. Sin red no se nota.
PLAZO_CONSULTA_S = 3.0


def motivo_para_no_hacerlo(config: dict, argumentos: list[str], es_instalada=None) -> str | None:
    """Por que no toca actualizar al abrir (para el registro), o None si toca."""
    if ARGUMENTO_TRAS_ACTUALIZAR in argumentos:
        return "es el arranque que hace el instalador al acabar"
    if not config.get("actualizar_automaticamente", True):
        return "la actualizacion automatica esta desactivada"
    if not config.get("actualizar_al_abrir", True):
        return "\"Actualizar al abrir Farmadex\" esta desactivado"
    if instalacion.RUTA_PENDIENTE.exists():
        # Se lanzo un setup y aun no se sabe como acabo (lo cuenta la ventana
        # principal): intentar otra vez aqui podria entrar en bucle.
        return "hay una instalacion anterior sin resolver"
    instalada = es_instalada() if es_instalada is not None else instalacion.es_instalacion_por_instalador()
    if not instalada:
        return "no es la version instalada con el instalador (portable o desde el codigo)"
    return None


def instalador_listo(carpeta: Path | str | None = None) -> tuple[str, Path] | None:
    """(version, ruta) del instalador ya bajado, mas nuevo y con la huella bien; o None."""
    carpeta = Path(carpeta) if carpeta is not None else descarga.DIR_DESCARGAS
    apunte = descarga.leer_lista(carpeta)
    if apunte is None:
        return None
    etiqueta, ruta, huella = apunte
    if not es_mas_nueva(etiqueta):
        log.info("El instalador apuntado (%s) no es mas nuevo que esta version: se descarta", etiqueta)
        descarga.borrar_lista(carpeta)
        return None
    if instalacion.version_fallida() == etiqueta:
        log.info("La version %s ya fallo al instalarse sola: no se intenta al abrir", etiqueta)
        return None
    try:
        buena = ruta.is_file() and descarga.sha256_de(ruta) == huella
    except OSError as e:
        log.info("No se pudo leer el instalador apuntado %s: %s", ruta, e)
        buena = False
    if not buena:
        log.info("El instalador apuntado de %s ya no esta o su huella no cuadra: se descarta", etiqueta)
        descarga.borrar_lista(carpeta)
        return None
    return etiqueta, ruta


def consultar_ultima(plazo: float = PLAZO_CONSULTA_S, comprobador: ComprobadorApp | None = None) -> Version | None:
    """La version nueva publicada, si GitHub contesta dentro del plazo; None si no.

    La consulta va en un hilo y se espera como mucho `plazo`: aunque la red se
    quede colgada (DNS, proxy), el arranque sigue.
    """
    propio = comprobador is None
    if comprobador is None:
        comprobador = ComprobadorApp()
        comprobador.cliente.cliente.timeout = _timeout(plazo)
    if not comprobador.activo:
        return None
    resultado: dict = {}
    comprobador.nueva_version.connect(lambda v: resultado.__setitem__("version", v), Qt.DirectConnection)
    comprobador.fallo.connect(lambda m: resultado.__setitem__("fallo", m), Qt.DirectConnection)
    hilo = threading.Thread(
        target=comprobador.comprobar_ahora, kwargs={"manual": True}, name="comprobar-al-abrir", daemon=True
    )
    hilo.start()
    hilo.join(plazo)
    if hilo.is_alive():
        log.info("GitHub no ha contestado en %.0f s: se arranca normal", plazo)
        return None
    if propio:
        comprobador.cerrar()
    if "fallo" in resultado:
        log.info("No se pudo mirar si hay version nueva al abrir (%s): se arranca normal", resultado["fallo"])
    return resultado.get("version")


def _timeout(plazo: float):
    import httpx

    return httpx.Timeout(plazo, connect=plazo)


class VentanaActualizando(QWidget):
    """"Actualizando Farmadex a la X..." con la barra de la descarga y "Abrir sin actualizar"."""

    saltar = Signal()

    def __init__(self, etiqueta: str):
        super().__init__(None, Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.CustomizeWindowHint | Qt.WindowTitleHint
                         | Qt.WindowCloseButtonHint)
        from ..ui.widgets import PALETA, hoja_estilos

        self.setWindowTitle(NOMBRE_APP)
        self.etiqueta = etiqueta
        self.setStyleSheet(hoja_estilos())
        self.setMinimumWidth(380)
        diseno = QVBoxLayout(self)
        diseno.setContentsMargins(24, 20, 24, 20)
        diseno.setSpacing(12)
        self.texto = QLabel(t("Actualizando Farmadex a la versión {version}...", version=etiqueta))
        self.texto.setWordWrap(True)
        self.texto.setStyleSheet(f"color: {PALETA['texto']}; font-size: 14px;")
        diseno.addWidget(self.texto)
        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setValue(0)
        diseno.addWidget(self.barra)
        self.boton = QPushButton(t("Abrir sin actualizar"))
        self.boton.clicked.connect(self._saltar)
        diseno.addWidget(self.boton, 0, Qt.AlignRight)
        self._saltado = False
        # Lo que devuelve la descarga, para quien espera en el bucle.
        self.resultado: dict = {}
        self.bucle: QEventLoop | None = None

    def centrar(self) -> None:
        self.adjustSize()
        pantalla = QGuiApplication.primaryScreen()
        if pantalla is not None:
            geo = pantalla.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

    # Estas reciben las senales del hilo de descarga: al ser metodos de un QWidget,
    # Qt las ejecuta en el hilo de la interfaz.
    def poner_progreso(self, pct: int) -> None:
        if pct < 0:
            self.barra.setRange(0, 0)  # sin total conocido: barra en movimiento
        else:
            self.barra.setRange(0, 100)
            self.barra.setValue(pct)

    def descarga_lista(self, version, ruta) -> None:
        self.resultado["ruta"] = ruta
        self._terminar()

    def descarga_fallida(self, version, motivo: str) -> None:
        self.resultado["fallo"] = motivo
        self._terminar()

    def instalando(self) -> None:
        self.barra.setRange(0, 100)
        self.barra.setValue(100)
        self.texto.setText(t(
            "Instalando la versión {version}... Farmadex se cerrará y volverá a abrirse solo.",
            version=self.etiqueta,
        ))
        self.boton.setEnabled(False)
        QApplication.processEvents()

    def _saltar(self) -> None:
        if self._saltado:
            return
        self._saltado = True
        self.resultado["saltado"] = True
        self.saltar.emit()
        self._terminar()

    def _terminar(self) -> None:
        if self.bucle is not None:
            self.bucle.quit()

    def closeEvent(self, evento) -> None:  # noqa: N802 - nombre de Qt
        # Cerrar con la X es lo mismo que "Abrir sin actualizar".
        if "ruta" not in self.resultado and "fallo" not in self.resultado:
            self._saltar()
        super().closeEvent(evento)


def _instalar(etiqueta: str, ruta: Path, en_bandeja: bool, instalar) -> bool:
    # El setup espera a que este mutex se suelte (proceso muerto) antes de copiar
    # nada: sin el, empezaria a sustituir ficheros con este Farmadex aun cerrandose.
    instalacion.senalar_en_ejecucion()
    if instalar(ruta, etiqueta, en_bandeja=en_bandeja):
        log.info("Al abrir: instalador de %s lanzado%s; este Farmadex se cierra",
                 etiqueta, " sin ventanas (arranque con Windows)" if en_bandeja else "")
        return True
    log.warning("Al abrir: no se pudo lanzar el instalador de %s; se arranca normal", etiqueta)
    return False


def actualizar_al_abrir(
    config: dict,
    argumentos: list[str],
    en_bandeja: bool = False,
    es_instalada=None,
    carpeta: Path | str | None = None,
    comprobador: ComprobadorApp | None = None,
    transporte_descarga=None,
    instalar=None,
    plazo: float = PLAZO_CONSULTA_S,
) -> bool:
    """Hace lo de "actualizar al abrir". True si se lanzo el instalador: hay que salir ya.

    Nunca propaga: un fallo aqui no puede impedir que Farmadex arranque.
    """
    try:
        return _actualizar_al_abrir(config, argumentos, en_bandeja, es_instalada, carpeta, comprobador,
                                    transporte_descarga, instalar, plazo)
    except Exception:  # noqa: BLE001 - el arranque tiene que seguir pase lo que pase
        log.exception("Fallo inesperado al actualizar al abrir; se arranca normal")
        return False


def _actualizar_al_abrir(config, argumentos, en_bandeja, es_instalada, carpeta, comprobador,
                         transporte_descarga, instalar, plazo) -> bool:
    motivo = motivo_para_no_hacerlo(config, argumentos, es_instalada)
    if motivo:
        log.info("Al abrir: no se busca actualizacion (%s)", motivo)
        return False
    if instalar is None:
        instalar = instalacion.instalar_silencioso
    qt = QApplication.instance()
    if qt is not None:
        # Cerrar la ventanita no puede cerrar la aplicacion: Qt dejaria un "salir"
        # en la cola y la ventana principal se cerraria nada mas abrirse.
        qt.setQuitOnLastWindowClosed(False)
    carpeta = Path(carpeta) if carpeta is not None else descarga.DIR_DESCARGAS

    lista = instalador_listo(carpeta)
    if lista is not None:
        etiqueta, ruta = lista
        log.info("Al abrir: la actualizacion %s ya estaba descargada y comprobada: se instala", etiqueta)
        ventana = None
        if not en_bandeja:
            ventana = VentanaActualizando(etiqueta)
            ventana.centrar()
            ventana.show()
            ventana.instalando()
        if _instalar(etiqueta, ruta, en_bandeja, instalar):
            return True
        if ventana is not None:
            ventana.close()
        return False

    if en_bandeja:
        log.info("Al abrir con Windows: nada descargado; la actualizacion, si la hay, se baja en segundo "
                 "plano y se instala al cerrar")
        return False
    if not config.get("comprobar_actualizaciones_app", True):
        log.info("Al abrir: no se pregunta a GitHub (comprobar actualizaciones esta desactivado)")
        return False

    log.info("Al abrir: se mira si hay version nueva (plazo %.0f s)", plazo)
    version = consultar_ultima(plazo, comprobador)
    if version is None:
        log.info("Al abrir: no hay version nueva (o no se pudo mirar); se arranca normal")
        return False
    if instalacion.version_fallida() == version.etiqueta:
        log.info("Al abrir: la %s ya fallo al instalarse sola; se arranca normal", version.etiqueta)
        return False
    if not descarga.huella_esperada(version) or not descarga.url_permitida(version.url):
        log.info("Al abrir: la %s no trae instalador con huella del repositorio; se arranca normal",
                 version.etiqueta)
        return False

    log.info("Al abrir: hay version nueva %s; se descarga antes de abrir", version.etiqueta)
    ventana = VentanaActualizando(version.etiqueta)
    descargador = descarga.DescargadorApp(carpeta, transporte=transporte_descarga)
    descargador.progreso.connect(ventana.poner_progreso)
    descargador.lista.connect(ventana.descarga_lista)
    descargador.fallo.connect(ventana.descarga_fallida)
    ventana.saltar.connect(descargador.cancelar)
    ventana.bucle = QEventLoop()
    ventana.centrar()
    ventana.show()
    descargador.descargar(version)
    # Las senales del hilo llegan por la cola de eventos: aunque acabe antes de este
    # punto, se entregan en cuanto el bucle arranca.
    ventana.bucle.exec()
    resultado = ventana.resultado

    if resultado.get("saltado"):
        log.info("Al abrir: pulsado \"Abrir sin actualizar\"; la %s se bajara en segundo plano", version.etiqueta)
        descargador.cancelar()
        # Que el hilo suelte el .parcial antes de que la ventana principal lo reanude.
        if descargador._hilo is not None:
            descargador._hilo.join(5.0)
        ventana.close()
        return False
    if "fallo" in resultado or "ruta" not in resultado:
        log.info("Al abrir: la descarga de %s fallo (%s); se arranca normal", version.etiqueta,
                 resultado.get("fallo", "?"))
        ventana.close()
        return False

    log.info("Al abrir: %s descargada y comprobada; se instala", version.etiqueta)
    ventana.instalando()
    if _instalar(version.etiqueta, Path(resultado["ruta"]), False, instalar):
        return True
    ventana.close()
    return False

