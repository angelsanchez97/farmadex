"""Piezas de interfaz reutilizables, temas de color e imagenes de los objetos."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ..config import DIR_IMG
from ..ficheros import reemplazar, temporal_de
from ..registro_log import obtener

log = obtener("ui")

# -- temas ------------------------------------------------------------------------
# Cuatro aspectos para que el usuario elija. Todos con fondo muy oscuro y opaco,
# porque la ventana se lee encima de una partida, no sobre un fondo neutro.
TEMAS = {
    "vacio": {
        "titulo": "Vacio (azul)",
        "fondo": "#0e1218", "panel": "#171d26", "panel2": "#1f2733", "boton": "#1f2733", "borde": "#2b3442",
        "texto": "#e8ebf1", "suave": "#93a0b4", "acento": "#4aa3ff", "acento_texto": "#08101c",
        "aviso": "#f0a63c", "ok": "#6fcf7a", "fondo_rgb": "14, 18, 24",
    },
    "orokin": {
        "titulo": "Orokin (dorado)",
        "fondo": "#12100c", "panel": "#1c1913", "panel2": "#26221a", "boton": "#26221a", "borde": "#3a3324",
        "texto": "#f1ece0", "suave": "#a89f8a", "acento": "#e2b455", "acento_texto": "#1a1508",
        "aviso": "#f08a3c", "ok": "#8ccf6f", "fondo_rgb": "18, 16, 12",
    },
    "tenno": {
        "titulo": "Tenno (turquesa)",
        "fondo": "#0b1416", "panel": "#12201f", "panel2": "#182b29", "boton": "#182b29", "borde": "#24403c",
        "texto": "#e6f1ef", "suave": "#8fb0aa", "acento": "#39d0c0", "acento_texto": "#04201c",
        "aviso": "#f2b04a", "ok": "#7ee08a", "fondo_rgb": "11, 20, 22",
    },
    "cherry": {
        "titulo": "Cherry (cereza)",
        "fondo": "#150c0f", "panel": "#211217", "panel2": "#2c181f", "boton": "#2c181f", "borde": "#47242f",
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


# -- aspecto personalizado (Ajustes > Aspecto) -----------------------------------------
# Lo que el usuario puede cambiar encima del tema, por categorias fijas: no es un editor
# libre, cada color manda sobre un tipo de elemento de toda la interfaz.
# (clave de la paleta, nombre en Ajustes, que pinta)
CATEGORIAS_COLOR = (
    ("fondo", "Fondo de la ventana", "El color de fondo de toda la ventana"),
    ("panel", "Cajas y listas", "La caja de busqueda, las listas y los recuadros de cada seccion"),
    ("panel2", "Tarjetas", "Las tarjetas de cada objeto, mision o recompensa"),
    ("boton", "Botones", "El fondo de los botones y de los desplegables"),
    ("borde", "Bordes", "Las lineas que separan y rodean cada cosa"),
    ("texto", "Texto", "El texto normal"),
    ("suave", "Texto secundario", "Las notas y explicaciones en pequeno"),
    ("acento", "Color principal", "Titulos, pestana activa, enlaces y el boton principal"),
    ("acento_texto", "Texto del boton principal", "El texto que va encima del color principal"),
    ("aviso", "Avisos", "Lo que pide atencion: datos viejos, algo que falla"),
    ("ok", "Todo bien", "Lo que esta disponible o ha salido bien"),
)
CLAVES_COLOR = tuple(c for c, _n, _a in CATEGORIAS_COLOR)

# Pasos de los dos tamanos: (factor, nombre). 1.0 es como viene.
ESCALAS_INTERFAZ = ((0.9, "Compacta"), (1.0, "Normal"), (1.15, "Grande"), (1.3, "Muy grande"))
ESCALAS_LETRA = ((0.9, "Pequena"), (1.0, "Normal"), (1.15, "Grande"), (1.3, "Muy grande"), (1.5, "Enorme"))

# Escala activa: "interfaz" agranda relleno, bordes redondeados y letra de los controles;
# "letra" solo la letra. La leen `px` y `hoja_estilos`.
ESCALA = {"interfaz": 1.0, "letra": 1.0}


def color_valido(valor) -> bool:
    """Solo "#rrggbb": lo que se guarda en config.json lo puede haber tocado alguien a mano."""
    if not isinstance(valor, str) or len(valor) != 7 or valor[0] != "#":
        return False
    try:
        int(valor[1:], 16)
    except ValueError:
        return False
    return True


def _rgb(valor: str) -> str:
    return ", ".join(str(int(valor[i:i + 2], 16)) for i in (1, 3, 5))


def paleta_de(nombre: str, personal: dict | None = None) -> dict:
    """El tema `nombre` con los colores personalizados encima (los invalidos se ignoran)."""
    paleta = dict(TEMAS.get(nombre) or TEMAS[TEMA_POR_DEFECTO])
    for clave, valor in (personal or {}).items():
        if clave in CLAVES_COLOR and color_valido(valor):
            paleta[clave] = valor.lower()
    paleta["fondo_rgb"] = _rgb(paleta["fondo"])
    return paleta


def escala_valida(valor, pasos) -> float:
    """El factor guardado si es uno de los pasos ofrecidos; si no, 1.0."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return 1.0
    return numero if any(abs(numero - f) < 1e-6 for f, _n in pasos) else 1.0


def aspecto_guardado(config: dict, nombre: str | None = None) -> tuple[dict, float, float]:
    """(colores personalizados del tema, escala de interfaz, escala de letra) de la config."""
    nombre = nombre or config.get("tema") or TEMA_POR_DEFECTO
    todos = config.get("colores_personalizados")
    colores = todos.get(nombre) if isinstance(todos, dict) else None
    colores = {c: v for c, v in (colores or {}).items() if c in CLAVES_COLOR and color_valido(v)}
    return (
        colores,
        escala_valida(config.get("escala_interfaz", 1.0), ESCALAS_INTERFAZ),
        escala_valida(config.get("escala_letra", 1.0), ESCALAS_LETRA),
    )


def px(tamano: float, letra: bool = True, escala: tuple[float, float] | None = None) -> int:
    """Pixeles de un tamano de la interfaz con la escala activa (o la dada, para la vista
    previa). `letra` = es un tamano de letra, que tambien crece con "Tamano de letra"."""
    interfaz, factor_letra = escala or (ESCALA["interfaz"], ESCALA["letra"])
    return max(1, round(tamano * interfaz * (factor_letra if letra else 1.0)))


_LEER_CONFIG = object()


def elegir_tema(nombre: str, personal=_LEER_CONFIG) -> dict:
    """Activa un tema por nombre (desconocido = el de por defecto) y lo devuelve.

    Sin `personal`, aplica tambien lo que el usuario haya personalizado en Ajustes >
    Aspecto (colores de ese tema y tamanos), leido de la configuracion.
    """
    global COLOR_FONDO, COLOR_PANEL, COLOR_TEXTO, COLOR_SUAVE, COLOR_ACENTO, COLOR_AVISO
    if personal is _LEER_CONFIG:
        from ..config import cargar

        personal, interfaz, letra = aspecto_guardado(cargar(), nombre if nombre in TEMAS else None)
        ESCALA["interfaz"], ESCALA["letra"] = interfaz, letra
    PALETA.clear()
    PALETA.update(paleta_de(nombre, personal))
    COLOR_FONDO, COLOR_PANEL = PALETA["fondo"], PALETA["panel"]
    COLOR_TEXTO, COLOR_SUAVE = PALETA["texto"], PALETA["suave"]
    COLOR_ACENTO, COLOR_AVISO = PALETA["acento"], PALETA["aviso"]
    return PALETA


def color_rareza(rareza: str | None) -> str:
    return RAREZA.get(rareza or "", PALETA["texto"])


def hoja_estilos(p: dict | None = None, escala: tuple[float, float] | None = None) -> str:
    """Hoja de toda la ventana. `escala` = (interfaz, letra) para la vista previa;
    sin ella, la activa."""
    p = p or PALETA
    p = {"boton": p.get("panel2"), **p}  # paletas de antes de existir "boton"
    esc = escala or (ESCALA["interfaz"], ESCALA["letra"])

    def f(n: int) -> str:  # letra
        return f"{px(n, True, esc)}px"

    def m(n: int) -> str:  # medidas (relleno, radios)
        return f"{px(n, False, esc)}px"

    return f"""
QWidget {{ background: {p['fondo']}; color: {p['texto']};
           font-family: 'Segoe UI'; font-size: {f(14)}; }}
QLabel, QCheckBox, QSlider, QTabBar, QSplitter {{ background: transparent; }}
QLineEdit {{ background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: {m(8)};
             padding: {m(9)} {m(12)}; font-size: {f(15)}; selection-background-color: {p['acento']}; }}
QLineEdit:focus {{ border-color: {p['acento']}; }}
QListWidget {{ background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: {m(8)};
               outline: none; }}
QListWidget::item {{ padding: 0; border-bottom: 1px solid {p['borde']}; }}
QListWidget::item:selected {{ background: {p['panel2']}; border-left: 3px solid {p['acento']}; }}
QListWidget::item:hover {{ background: {p['panel2']}; }}
QTextBrowser {{ background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: {m(8)};
                padding: {m(10)}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {p['suave']}; padding: {m(8)} {m(18)};
                margin-right: {m(4)}; border-bottom: 2px solid transparent; font-size: {f(15)}; }}
QTabBar::tab:selected {{ color: {p['acento']}; border-bottom: 2px solid {p['acento']}; }}
QTabBar::tab:hover {{ color: {p['texto']}; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {p['borde']}; }}
QTabWidget, QTabWidget > QStackedWidget {{ background: transparent; }}
QPushButton {{ background: {p['boton']}; border: 1px solid {p['borde']}; border-radius: {m(7)};
               padding: {m(6)} {m(14)}; }}
QPushButton:hover {{ border-color: {p['acento']}; }}
QPushButton:pressed {{ background: {p['panel']}; }}
QPushButton:disabled {{ color: {p['suave']}; border-color: {p['panel2']}; }}
QPushButton#principal {{ background: {p['acento']}; color: {p['acento_texto']};
                         font-weight: 600; border: none; }}
QCheckBox {{ spacing: {m(8)}; }}
QCheckBox::indicator {{ width: {m(16)}; height: {m(16)}; border: 1px solid {p['borde']};
                        border-radius: {m(4)}; background: {p['panel']}; }}
QCheckBox::indicator:checked {{ background: {p['acento']}; border-color: {p['acento']}; }}
QComboBox {{ background: {p['boton']}; border: 1px solid {p['borde']}; border-radius: {m(7)};
             padding: {m(5)} {m(10)}; }}
QComboBox QAbstractItemView {{ background: {p['boton']}; selection-background-color: {p['acento']};
                               selection-color: {p['acento_texto']}; }}
QGroupBox {{ border: 1px solid {p['borde']}; border-radius: {m(10)}; margin-top: {m(14)};
             padding: {m(10)} {m(8)} {m(6)} {m(8)}; background: {p['panel']}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 {m(6)}; color: {p['acento']};
                    font-weight: 600; font-size: {f(13)}; text-transform: uppercase; }}
QProgressBar {{ background: {p['panel2']}; border: 1px solid {p['borde']}; border-radius: {m(7)};
                height: {m(14)}; text-align: center; color: {p['texto']}; font-size: {f(12)}; }}
QProgressBar::chunk {{ background: {p['acento']}; border-radius: {m(6)}; }}
QSlider::groove:horizontal {{ height: {m(4)}; background: {p['borde']}; border-radius: {m(2)}; }}
QSlider::handle:horizontal {{ width: {m(16)}; margin: -{m(6)} 0; background: {p['acento']};
                              border-radius: {m(8)}; }}
QScrollBar:vertical {{ background: transparent; width: {m(10)}; margin: {m(2)}; }}
QScrollBar::handle:vertical {{ background: {p['borde']}; border-radius: {m(4)}; min-height: {m(30)}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}
QSplitter::handle {{ background: transparent; width: {m(8)}; }}
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
            f"color: {PALETA['acento']}; font-weight: 600; font-size: {px(12)}px; letter-spacing: 1px;"
            f" margin-top: {px(6, False)}px;"
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
                    tmp = temporal_de(destino)
                    tmp.write_bytes(r.content)
                    reemplazar(tmp, destino)
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
