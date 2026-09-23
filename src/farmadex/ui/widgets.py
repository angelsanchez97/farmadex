"""Piezas de interfaz reutilizables, temas de color e imagenes de los objetos."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ..config import DIR_IMG
from ..registro_log import obtener

log = obtener("ui")

# -- temas ------------------------------------------------------------------------
# Cuatro aspectos para que el usuario elija. Todos con fondo muy oscuro y opaco,
# porque la ventana se lee encima de una partida, no sobre un fondo neutro.
TEMAS = {
    "vacio": {
        "titulo": "Vacio (azul)",
        "fondo": "#0e1218", "panel": "#171d26", "panel2": "#1f2733", "borde": "#2b3442",
        "texto": "#e8ebf1", "suave": "#93a0b4", "acento": "#4aa3ff", "acento_texto": "#08101c",
        "aviso": "#f0a63c", "ok": "#6fcf7a", "fondo_rgb": "14, 18, 24",
    },
    "orokin": {
        "titulo": "Orokin (dorado)",
        "fondo": "#12100c", "panel": "#1c1913", "panel2": "#26221a", "borde": "#3a3324",
        "texto": "#f1ece0", "suave": "#a89f8a", "acento": "#e2b455", "acento_texto": "#1a1508",
        "aviso": "#f08a3c", "ok": "#8ccf6f", "fondo_rgb": "18, 16, 12",
    },
    "tenno": {
        "titulo": "Tenno (turquesa)",
        "fondo": "#0b1416", "panel": "#12201f", "panel2": "#182b29", "borde": "#24403c",
        "texto": "#e6f1ef", "suave": "#8fb0aa", "acento": "#39d0c0", "acento_texto": "#04201c",
        "aviso": "#f2b04a", "ok": "#7ee08a", "fondo_rgb": "11, 20, 22",
    },
    "cherry": {
        "titulo": "Cherry (cereza)",
        "fondo": "#150c0f", "panel": "#211217", "panel2": "#2c181f", "borde": "#47242f",
        "texto": "#f4e8eb", "suave": "#b39aa1", "acento": "#e8456a", "acento_texto": "#1f060c",
        "aviso": "#f2a444", "ok": "#7fd88a", "fondo_rgb": "21, 12, 15",
    },
}
TEMA_POR_DEFECTO = "orokin"

# Colores por rareza (los del juego) y por estado.
RAREZA = {
    "Common": "#d0956a",
    "Uncommon": "#cfd6e0",
    "Rare": "#f5cd4f",
    "Legendary": "#d9a6ff",
}
COLOR_BOVEDA = "#f0a63c"
COLOR_DISPONIBLE = "#6fcf7a"

# La paleta activa. Los modulos la leen al construir y al pintar, no al importar.
PALETA = dict(TEMAS[TEMA_POR_DEFECTO])

# Nombres antiguos, que siguen usando los modulos que no cambian de color con el tema.
COLOR_FONDO = PALETA["fondo"]
COLOR_PANEL = PALETA["panel"]
COLOR_TEXTO = PALETA["texto"]
COLOR_SUAVE = PALETA["suave"]
COLOR_ACENTO = PALETA["acento"]
COLOR_AVISO = PALETA["aviso"]


def elegir_tema(nombre: str) -> dict:
    """Activa un tema por nombre (desconocido = el de por defecto) y lo devuelve."""
    global COLOR_FONDO, COLOR_PANEL, COLOR_TEXTO, COLOR_SUAVE, COLOR_ACENTO, COLOR_AVISO
    PALETA.clear()
    PALETA.update(TEMAS.get(nombre) or TEMAS[TEMA_POR_DEFECTO])
    COLOR_FONDO, COLOR_PANEL = PALETA["fondo"], PALETA["panel"]
    COLOR_TEXTO, COLOR_SUAVE = PALETA["texto"], PALETA["suave"]
    COLOR_ACENTO, COLOR_AVISO = PALETA["acento"], PALETA["aviso"]
    return PALETA


def color_rareza(rareza: str | None) -> str:
    return RAREZA.get(rareza or "", PALETA["texto"])


def hoja_estilos(p: dict | None = None) -> str:
    p = p or PALETA
    return f"""
QWidget {{ background: {p['fondo']}; color: {p['texto']};
           font-family: 'Segoe UI'; font-size: 14px; }}
QLabel, QCheckBox, QSlider, QTabBar, QSplitter {{ background: transparent; }}
QLineEdit {{ background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: 8px;
             padding: 9px 12px; font-size: 15px; selection-background-color: {p['acento']}; }}
QLineEdit:focus {{ border-color: {p['acento']}; }}
QListWidget {{ background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: 8px;
               outline: none; }}
QListWidget::item {{ padding: 0px; border-bottom: 1px solid {p['borde']}; }}
QListWidget::item:selected {{ background: {p['panel2']}; border-left: 3px solid {p['acento']}; }}
QListWidget::item:hover {{ background: {p['panel2']}; }}
QTextBrowser {{ background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: 8px;
                padding: 10px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {p['suave']}; padding: 8px 18px;
                margin-right: 4px; border-bottom: 2px solid transparent; font-size: 15px; }}
QTabBar::tab:selected {{ color: {p['acento']}; border-bottom: 2px solid {p['acento']}; }}
QTabBar::tab:hover {{ color: {p['texto']}; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {p['borde']}; }}
QTabWidget, QTabWidget > QStackedWidget {{ background: transparent; }}
QPushButton {{ background: {p['panel2']}; border: 1px solid {p['borde']}; border-radius: 7px;
               padding: 6px 14px; }}
QPushButton:hover {{ border-color: {p['acento']}; }}
QPushButton:pressed {{ background: {p['panel']}; }}
QPushButton:disabled {{ color: {p['suave']}; border-color: {p['panel2']}; }}
QPushButton#principal {{ background: {p['acento']}; color: {p['acento_texto']};
                         font-weight: 600; border: none; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {p['borde']};
                        border-radius: 4px; background: {p['panel']}; }}
QCheckBox::indicator:checked {{ background: {p['acento']}; border-color: {p['acento']}; }}
QComboBox {{ background: {p['panel2']}; border: 1px solid {p['borde']}; border-radius: 7px;
             padding: 5px 10px; }}
QComboBox QAbstractItemView {{ background: {p['panel2']}; selection-background-color: {p['acento']};
                               selection-color: {p['acento_texto']}; }}
QGroupBox {{ border: 1px solid {p['borde']}; border-radius: 10px; margin-top: 14px;
             padding: 10px 8px 6px 8px; background: {p['panel']}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {p['acento']};
                    font-weight: 600; font-size: 13px; text-transform: uppercase; }}
QProgressBar {{ background: {p['panel2']}; border: 1px solid {p['borde']}; border-radius: 7px;
                height: 14px; text-align: center; color: {p['texto']}; font-size: 12px; }}
QProgressBar::chunk {{ background: {p['acento']}; border-radius: 6px; }}
QSlider::groove:horizontal {{ height: 4px; background: {p['borde']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; background: {p['acento']};
                              border-radius: 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['borde']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}
QSplitter::handle {{ background: transparent; width: 8px; }}
QToolTip {{ background: {p['panel2']}; color: {p['texto']}; border: 1px solid {p['borde']}; }}
QStatusBar {{ color: {p['suave']}; }}
"""


# app.py la aplica a toda la aplicacion al arrancar; el overlay pone encima la del tema.
HOJA_ESTILOS = hoja_estilos(TEMAS[TEMA_POR_DEFECTO])


# -- piezas -----------------------------------------------------------------------

class Tarjeta(QFrame):
    """Un bloque con fondo propio, borde redondeado y una franja de color a la izquierda."""

    def __init__(self, color_franja: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("tarjeta")
        self.caja = QVBoxLayout(self)
        self.caja.setContentsMargins(14, 10, 12, 10)
        self.caja.setSpacing(4)
        self.pintar_franja(color_franja)

    def pintar_franja(self, color: str | None) -> None:
        p = PALETA
        franja = f"border-left: 4px solid {color};" if color else ""
        self.setStyleSheet(
            f"#tarjeta {{ background: {p['panel2']}; border: 1px solid {p['borde']};"
            f" border-radius: 8px; {franja} }}"
        )


class Titulo(QLabel):
    """Cabecera de seccion: pequena, en mayusculas y en el color de acento."""

    def __init__(self, texto: str, parent=None):
        super().__init__(texto.upper(), parent)
        self.setStyleSheet(
            f"color: {PALETA['acento']}; font-weight: 600; font-size: 12px; letter-spacing: 1px;"
            " margin-top: 6px;"
        )


class BarraProgreso(QWidget):
    """Texto + barra. Se oculta sola cuando no hay nada en marcha."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.etiqueta = QLabel("")
        self.etiqueta.setStyleSheet(f"color: {PALETA['suave']};")
        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setFixedWidth(260)

        caja = QHBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(self.etiqueta, 1)
        caja.addWidget(self.barra, 0, Qt.AlignRight)
        self.ocultar()

    def actualizar(self, texto: str, hechos: int, total: int) -> None:
        self.setVisible(True)
        self.etiqueta.setText(texto)
        if total > 0:
            self.barra.setRange(0, total)
            self.barra.setValue(hechos)
        else:
            self.barra.setRange(0, 0)  # indeterminada

    def ocultar(self) -> None:
        self.setVisible(False)
        self.etiqueta.setText("")
        self.barra.setRange(0, 1)
        self.barra.setValue(0)


# -- imagenes de los objetos --------------------------------------------------------

CDN_IMAGENES = "https://cdn.warframestat.us/img/"


class CacheImagenes(QObject):
    """Imagenes del catalogo en disco (carpeta de datos), descargadas en segundo plano.

    `pixmap(nombre)` devuelve la imagen si ya esta en disco; si no, la pide en un
    hilo y devuelve None. Cuando llega, emite `lista(nombre)` para repintar.
    Nunca se descarga nada en tiempo de pintado.
    """

    lista = Signal(str)

    def __init__(self, carpeta: Path = DIR_IMG, parent=None):
        super().__init__(parent)
        self.carpeta = Path(carpeta)
        self._memoria: dict[str, QPixmap] = {}
        self._pendientes: set[str] = set()
        self._fallidas: set[str] = set()
        self._cerrojo = threading.Lock()
        self._hilo: threading.Thread | None = None
        self._cola: list[str] = []

    def ruta(self, nombre: str) -> Path:
        return self.carpeta / Path(nombre).name

    def pixmap(self, nombre: str | None, lado: int = 64) -> QPixmap | None:
        if not nombre:
            return None
        clave = f"{nombre}@{lado}"
        if clave in self._memoria:
            return self._memoria[clave]
        ruta = self.ruta(nombre)
        if ruta.exists():
            mapa = QPixmap(str(ruta))
            if not mapa.isNull():
                mapa = mapa.scaled(QSize(lado, lado), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._memoria[clave] = mapa
                return mapa
            self._fallidas.add(nombre)
            return None
        self._pedir(nombre)
        return None

    def _pedir(self, nombre: str) -> None:
        with self._cerrojo:
            if nombre in self._pendientes or nombre in self._fallidas:
                return
            self._pendientes.add(nombre)
            self._cola.append(nombre)
            if self._hilo is None or not self._hilo.is_alive():
                self._hilo = threading.Thread(target=self._descargar, name="imagenes", daemon=True)
                self._hilo.start()

    def _descargar(self) -> None:
        import httpx

        self.carpeta.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=15.0, follow_redirects=True) as cliente:
            while True:
                with self._cerrojo:
                    if not self._cola:
                        return
                    nombre = self._cola.pop(0)
                destino = self.ruta(nombre)
                try:
                    r = cliente.get(CDN_IMAGENES + nombre)
                    r.raise_for_status()
                    tmp = destino.with_suffix(destino.suffix + ".tmp")
                    tmp.write_bytes(r.content)
                    tmp.replace(destino)
                    self.lista.emit(nombre)
                except Exception as e:  # noqa: BLE001 - sin imagen se sigue igual
                    log.debug("Sin imagen para %s: %s", nombre, e)
                    self._fallidas.add(nombre)
                finally:
                    with self._cerrojo:
                        self._pendientes.discard(nombre)


_cache_imagenes: CacheImagenes | None = None


def imagenes() -> CacheImagenes:
    """La cache compartida por toda la interfaz (se crea con la primera llamada)."""
    global _cache_imagenes
    if _cache_imagenes is None:
        _cache_imagenes = CacheImagenes()
    return _cache_imagenes
