"""Pagina Buscar: escribes algo y te dice de donde sale (diseno C, "menu del juego").

Arriba el buscador y la fila de acciones (Atras, + Objetivo, + Set, Wiki, YouTube,
Overframe); debajo, a la izquierda, los resultados con una franja del color de su tipo y
la leyenda al pie; a la derecha, la ficha en paneles C (`ficha_c.FichaC`):

- Objeto (tipo arsenal): imagen en su pedestal, nombre e insignias, disposicion de
  agrietado con rombos, Maestria / Tienes / Mercado; y a la derecha "Como conseguirlo"
  en pasos, estadisticas, donde se consigue, reliquias y el resto del set.
- Mision: cabecera, tira de rondas A A B C, un panel por rotacion con lo que suelta y
  "Que hacer".

Al pie, la barra de teclas del juego: + anadir objetivo, W wiki, O Overframe, Y YouTube,
C copiar el nombre y Esc volver. Las teclas funcionan con el foco en la lista o en la
ficha (en la caja se escribe): Enter en la caja pasa el foco a la lista.

`_html(datos)` sigue devolviendo la ficha entera como un solo HTML (lo usan las pruebas y
sirve de referencia de que no se pierde nada al repartirla en paneles).
"""

from __future__ import annotations

import html
import sqlite3
from urllib.parse import quote

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..config import cargar, guardar
from .. import perfil
from ..perfil import SIN_TOCAR
from ..estado import inventario as estado_inventario
from ..datos import consultas, eficiencia, indice, items, misiones, modos_mision, novedades, relaciones, ruta_prime
from ..datos.nodos import etapa_bonita, nombre_bonito
from ..idiomas import es_castellano, glosa, nombre as nombre_idioma, t
from . import (
    builds_overframe, colores_tipo, desglose_tiempo, enlaces_wiki, ficha_detalles, glosario, guias_youtube,
    pestana_primes, relleno_filas,
)
from .busqueda_fondo import BusquedaEnFondo
from .estilo_c import (
    COLOR_ERA,
    BarraTeclas,
    BotonC,
    CasillaC,
    EtiquetaC,
    Interruptor,
    PanelC,
    Pedestal,
    RombosDisposicion,
    columna,
    fila,
    fuente,
    icono,
    px,
    refrescar_todo,
    transparente,
)
from .ficha_c import BarraDano, FichaC, InsigniaGlosa, TiraRondas, estadisticas, etiqueta, filas_datos, hitos
from .maestria import colores_maestria, estado_con_padre, texto_maestria
from .widgets import COLOR_BOVEDA, COLOR_DISPONIBLE, PALETA, color_rareza, imagenes

# Palabras sueltas que no sirven para sugerir nada cuando una busqueda no da resultados.
PALABRAS_VACIAS = {
    "como", "consigo", "conseguir", "donde", "cae", "sale", "que", "para", "por", "con", "del",
    "los", "las", "una", "uno", "the", "how", "get", "where", "does", "drop", "farm", "farmear",
}
MAX_SUGERENCIAS = 5

ORDEN_TIPOS = [
    "mision",
    "bounty",
    "enemigo",
    "transitoria",
    "llave",
    "sindicato",
    "sortie",
    "otro",
]

REFINAMIENTOS = ("Intact", "Exceptional", "Flawless", "Radiant")
ERAS = ("Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia")


# Espera tras la ultima tecla antes de buscar: corta para que los resultados lleguen
# enseguida, suficiente para no buscar (ni pedir precio al mercado) a cada letra.
RETARDO_TECLAS_MS = 100


def calcular_busqueda(con: sqlite3.Connection, texto: str) -> dict:
    """La parte pesada de Buscar, sin tocar la ventana: se puede hacer en otro hilo.

    "como sacar citrine prime" busca "citrine prime"; "el ultimo warframe" no es un
    nombre sino una pregunta por lo nuevo, salvo que sea exactamente un objeto.
    """
    consulta = consultas.limpiar(texto)
    calculado = {
        "objetos": indice.buscar(con, consulta),
        "filtro": consultas.intencion_novedad(consulta),
        "encontradas": misiones.buscar(con, consulta),
    }
    # Sin nada, la ficha propone parecidos: tambien cuestan, se dejan hechos aqui.
    if not calculado["objetos"] and not calculado["encontradas"]:
        calculado["sugerencias"] = buscar_sugerencias(con, texto)
    return calculado


def buscar_sugerencias(con: sqlite3.Connection, texto: str) -> list[dict]:
    """Objetos parecidos a una busqueda fallida: se prueba cada palabra por separado.

    `como consigo rhino` no encuentra nada entero, pero `rhino` si. Se devuelven
    los primeros resultados de cada palabra util, sin repetir.
    """
    vistos: set[int] = set()
    salida: list[dict] = []
    palabras = [p for p in texto.split() if len(p) >= 3 and p.lower() not in PALABRAS_VACIAS]
    for palabra in palabras:
        if palabra.lower() == texto.lower():
            continue
        for r in indice.buscar(con, palabra, limite=MAX_SUGERENCIAS):
            if r["item_id"] not in vistos:
                vistos.add(r["item_id"])
                salida.append(r)
            if len(salida) >= MAX_SUGERENCIAS:
                return salida
    return salida


def era_de(nombre_en: str | None) -> str:
    """'Axi' de 'Axi A7 Relic'; vacio si el nombre no empieza por una era conocida."""
    era = (nombre_en or "").split(" ")[0]
    return era if era in ERAS else ""

# Cuantas reliquias se detallan con sus misiones antes de resumir el resto.
MAX_RELIQUIAS_DETALLADAS = 12
# Y cuantas filas se ensenan por tipo de fuente (un mod cae de 300 enemigos).
MAX_FILAS_POR_TIPO = 25
# Cuantas fichas recuerda el boton 'Atras'.
MAX_HISTORIAL = 50
# Filas de cada panel de rotacion antes de "y N mas".
MAX_FILAS_ROTACION = 6
# Reliquias de la lista compacta de un set (el resto se resume en una linea).
MAX_RELIQUIAS_SET = 8

CATEGORIAS_ES = {
    "Warframes": "Warframe", "Primary": "Arma primaria", "Secondary": "Arma secundaria",
    "Melee": "Cuerpo a cuerpo", "Archwing": "Archwing", "Arch-Gun": "Archcañón",
    "Arch-Melee": "Arch-melee", "Sentinels": "Centinela", "SentinelWeapons": "Arma de centinela",
    "Pets": "Compañero", "Mods": "Mod", "Arcanes": "Arcano", "Relics": "Reliquia",
    "Resources": "Recurso", "Misc": "Objeto", "Gear": "Equipo", "Railjack": "Railjack",
    "Skins": "Aspecto", "Glyphs": "Glifo", "Sigils": "Sigilo", "Fish": "Pez",
    "Quests": "Misión", "Honoria": "Honoria",
}
# Categorias de arma: el rotulo de la ficha anade su tipo ("Arma primaria · Rifle").
CATEGORIAS_ARMA = {"Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee", "SentinelWeapons"}

ROL_SUBTITULO = Qt.UserRole + 1
ROL_IMAGEN = Qt.UserRole + 2
ROL_RAREZA = Qt.UserRole + 3
# Tipo de objeto (clave de colores_tipo.TIPOS): el color de su franja y de su insignia.
ROL_TIPO = Qt.UserRole + 4


# Lo que se pone al lado del nombre: categoria y, si es pieza, "Componente".
def categoria_es(categoria: str, tipo: str | None = None) -> str:
    base = t(CATEGORIAS_ES.get(categoria, categoria))
    return t("{base} · pieza", base=base) if tipo == "Componente" else base


def _glosa(con, dominio: str, en: str | None) -> str:
    """Termino del glosario del indice en el idioma de la interfaz."""
    return glosa(indice.traducir(con, dominio, en), en)


class DelegadoResultado(QStyledItemDelegate):
    """Cada resultado: franja del color de su tipo, imagen, nombre, detalle en gris y a la
    derecha la insignia del tipo (MOD, ARMA, MISIÓN...)."""

    ALTO = 50
    LADO_IMAGEN = 30

    def sizeHint(self, opcion, indice):  # noqa: N802 - firma de Qt
        return QSize(opcion.rect.width(), px(self.ALTO, False))

    def paint(self, pintor: QPainter, opcion, indice):  # noqa: N802
        p = PALETA
        rect: QRect = opcion.rect.adjusted(0, 1, -1, -2)
        pintor.save()
        pintor.setRenderHint(QPainter.Antialiasing)
        clave = indice.data(ROL_TIPO) or "otro"
        tinta = QColor(colores_tipo.color(clave, p["panel"]))
        if opcion.state & QStyle.State_Selected:
            pintor.fillRect(rect, QColor(p["panel2"]))
            pintor.setPen(QPen(QColor(p["acento_tenue"] if "acento_tenue" in p else p["acento"]), 1))
            pintor.drawRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5))
        elif opcion.state & QStyle.State_MouseOver:
            pintor.fillRect(rect, QColor(p["panel2"]).darker(108))
        # Franja del tipo, a todo lo alto de la fila.
        pintor.fillRect(QRect(rect.left(), rect.top(), px(3, False), rect.height()), tinta)

        lado = px(self.LADO_IMAGEN, False)
        x = rect.left() + px(14, False)
        mapa = imagenes().pixmap(indice.data(ROL_IMAGEN), lado)
        if mapa is not None:
            y = rect.top() + (rect.height() - mapa.height()) // 2
            pintor.drawPixmap(x + (lado - mapa.width()) // 2, y, mapa)
        else:
            # Sin imagen, un rombo hueco del color del tipo en su sitio.
            cx, cy, m = x + lado / 2, rect.center().y() + 0.5, lado * 0.22
            pintor.setPen(QPen(tinta, 1.2))
            pintor.setBrush(Qt.NoBrush)
            pintor.drawPolygon(QPolygonF([QPointF(cx, cy - m), QPointF(cx + m, cy), QPointF(cx, cy + m),
                                          QPointF(cx - m, cy)]))
        x += lado + px(12, False)

        # Insignia del tipo a la derecha.
        f_ins = fuente("dato", 11, 600)
        f_ins.setLetterSpacing(QFont.AbsoluteSpacing, 1.3)
        pintor.setFont(f_ins)
        nombre_tipo = colores_tipo.nombre(clave).upper()
        ancho_ins = pintor.fontMetrics().horizontalAdvance(nombre_tipo) + px(14, False)
        alto_ins = pintor.fontMetrics().height() + px(4, False)
        caja_ins = QRect(rect.right() - px(10, False) - ancho_ins, rect.center().y() - alto_ins // 2, ancho_ins, alto_ins)
        fondo = QColor(tinta)
        fondo.setAlpha(30)
        borde = QColor(tinta)
        borde.setAlpha(150)
        pintor.setPen(QPen(borde, 1))
        pintor.setBrush(fondo)
        pintor.drawRect(QRectF(caja_ins).adjusted(0.5, 0.5, -0.5, -0.5))
        pintor.setPen(tinta)
        pintor.drawText(caja_ins, Qt.AlignCenter, nombre_tipo)

        ancho = caja_ins.left() - x - px(8, False)
        pintor.setFont(fuente("fuerte"))
        pintor.setPen(QColor(p["texto"]))
        nombre = pintor.fontMetrics().elidedText(indice.data(Qt.DisplayRole) or "", Qt.ElideRight, ancho)
        medio = rect.center().y()
        pintor.drawText(QRect(x, rect.top() + px(5, False), ancho, medio - rect.top() - px(4, False)),
                        Qt.AlignBottom | Qt.AlignLeft, nombre)
        pintor.setFont(fuente("pequeno"))
        pintor.setPen(QColor(p["suave"]))
        subtitulo = pintor.fontMetrics().elidedText(indice.data(ROL_SUBTITULO) or "", Qt.ElideRight, ancho)
        pintor.drawText(QRect(x, medio + px(1, False), ancho, rect.bottom() - medio - px(4, False)),
                        Qt.AlignTop | Qt.AlignLeft, subtitulo)
        pintor.restore()


class _EtiquetaPulsable(EtiquetaC):
    """El texto al lado de un interruptor: pulsarlo tambien lo cambia."""

    pulsada = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, evento):  # noqa: N802 - firma de Qt
        if evento.button() == Qt.LeftButton:
            self.pulsada.emit()
            evento.accept()
            return
        super().mousePressEvent(evento)


class _FiltroTeclas(QObject):
    """Las teclas de la barra del pie (+, W, O, Y, C, Esc) en la lista y en la ficha."""

    def __init__(self, pestana: "PestanaBuscador"):
        super().__init__(pestana)
        self.pestana = pestana

    def eventFilter(self, objeto, evento):  # noqa: N802 - firma de Qt
        tipo = evento.type()
        if tipo == QEvent.ShortcutOverride and evento.key() == Qt.Key_Escape and self.pestana.puede_volver():
            # Sin esto, el Esc de la ventana (esconderla) se adelantaria al "volver".
            evento.accept()
            return True
        if tipo == QEvent.KeyPress and self.pestana.tecla(evento):
            return True
        return False


class PestanaBuscador(QWidget):
    estado = Signal(str)
    pedir_precios = Signal(str)
    anadir_objetivo = Signal(int, bool)  # item_id, set completo

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.con: sqlite3.Connection | None = None
        # BD del usuario, solo para leer el perfil importado; None hasta que la ventana la pasa.
        self.usuario: sqlite3.Connection | None = None
        self._hay_perfil = False
        self.config = cargar()
        self._resultados: list[dict] = []
        # (item_id, texto que se buscaba), para poder rehacer la busqueda al volver. Una
        # ficha de mision se apunta con su clave ('nodo:98', 'modo:Survival') en vez del id.
        self._historial: list[tuple[int | str, str]] = []
        # Mientras se vuelve atras no se apunta nada nuevo en el historial.
        self._volviendo = False
        self._actual: int | None = None
        self._datos_actuales: dict | None = None
        # Ficha de mision abierta ('nodo:98' o 'modo:Survival'); None si es de objeto o no hay.
        self._mision_actual: str | None = None
        # Paneles de rotacion desplegados enteros ("y N mas" pulsado) en la ficha de mision.
        self._rotaciones_abiertas: set[str] = set()
        # Quien reproduce las guias de YouTube dentro de Farmadex (la ventana lo pone);
        # sin el, el navegador del sistema.
        self.reproductor = None
        # Quien ensena paginas web dentro de Farmadex (la pestana Web; la ventana lo pone);
        # sin el, el navegador del sistema.
        self.navegador_web = None
        # "Lo mas nuevo" cuando se abrio una ficha de objeto por "el ultimo warframe": la
        # nota con los demas objetos de esa actualizacion, que va debajo del nombre.
        self._nota_novedad: dict | None = None
        # Lo ultimo que se busco sin exito, para volver a pintar el aviso al cambiar de idioma.
        self._sin_resultados: str | None = None
        self._sugerencias_hechas: dict[str, list[dict]] = {}
        # Imagenes que la ficha abierta esta esperando (al llegar, se repinta).
        self._imagenes_ficha: set[str] = set()
        self.pedestal: Pedestal | None = None
        self._teclas = _FiltroTeclas(self)

        # -- buscador ---------------------------------------------------------------------
        self.caja = QLineEdit()
        self.caja.setObjectName("cajaC")
        self.caja.setClearButtonEnabled(True)
        self.caja.returnPressed.connect(self._enter)
        self.pista_enter = EtiquetaC("Enter", "pequeno", tinta="tenue")
        self.panel_buscar = PanelC(remate=False, fondo="panel2", borde="acento_tenue")
        self.panel_buscar.capa.setContentsMargins(px(18, False), px(2, False), px(18, False), px(2, False))
        self.panel_buscar.capa.addLayout(fila(icono("buscar", 19), self.caja, self.pista_enter, espacio=8))

        # -- acciones (siempre en el mismo sitio; apagadas si no hay ficha) ---------------
        self.atras = BotonC()
        self.atras.setEnabled(False)
        self.atras.clicked.connect(self._volver)
        self.boton_objetivo = BotonC(principal=True)
        self.boton_objetivo.setEnabled(False)
        self.boton_objetivo.clicked.connect(
            lambda: self._actual and self.anadir_objetivo.emit(self._actual, False)
        )
        self.boton_set = BotonC()
        self.boton_set.setEnabled(False)
        self.boton_set.clicked.connect(
            lambda: self._actual and self.anadir_objetivo.emit(self._actual, True)
        )
        # Para lo que Farmadex no cuenta (habilidades, construccion, historia): la wiki
        # oficial con lo escrito, o la pagina del objeto de la ficha abierta.
        self.boton_wiki = BotonC(icono="mundo")
        self.boton_wiki.setEnabled(False)
        self.boton_wiki.clicked.connect(self._abrir_wiki)
        # Guias en video de la ficha abierta (mision u objeto), dentro de Farmadex.
        self.boton_youtube = BotonC()
        self.boton_youtube.setEnabled(False)
        self.boton_youtube.clicked.connect(self._abrir_youtube)
        # Builds de la comunidad en Overframe del warframe/arma/companero abierto, dentro
        # de Farmadex (pestana Web). Solo se abre su web: no se lee nada de ella. Escondido
        # si la ficha no tiene builds; la ficha lleva ademas "Builds en Overframe".
        self.boton_overframe = BotonC("Overframe")
        self.boton_overframe.hide()
        self.boton_overframe.clicked.connect(self._abrir_overframe)
        for boton in (self.atras, self.boton_objetivo, self.boton_set, self.boton_wiki, self.boton_youtube,
                      self.boton_overframe):
            boton.installEventFilter(self._teclas)
        self.barra_acciones = transparente(QWidget())
        self.barra_acciones.setLayout(fila(
            self.atras, None, self.boton_objetivo, self.boton_set, self.boton_wiki, self.boton_youtube,
            self.boton_overframe, espacio=px(8, False),
        ))

        # -- resultados -------------------------------------------------------------------
        self.rotulo_resultados = EtiquetaC("", "rotulo", mayus=True)
        self.ocultar_vaulted = Interruptor(bool(self.config.get("ocultar_vaulted", False)))
        self.ocultar_vaulted.toggled.connect(self._cambiar_filtro)
        glosario.aplicar(self.ocultar_vaulted, "boveda")
        self.texto_ocultar = _EtiquetaPulsable("", "pequeno")
        self.texto_ocultar.pulsada.connect(self.ocultar_vaulted.toggle)
        self.lista = QListWidget()
        self.lista.setObjectName("listaResultadosC")
        self.lista.setFrameShape(QFrame.NoFrame)
        self.lista.setItemDelegate(DelegadoResultado(self.lista))
        self.lista.setMouseTracking(True)
        self.lista.setUniformItemSizes(True)
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lista.installEventFilter(self._teclas)
        # Que color es cada tipo, solo con los tipos que hay en la lista y en letra pequena.
        self.leyenda = QLabel("")
        self.leyenda.setTextFormat(Qt.RichText)
        self.leyenda.setWordWrap(True)
        self.leyenda.hide()
        self.panel_resultados = PanelC()
        self.panel_resultados.setMinimumWidth(px(280, False))
        self.panel_resultados.capa.setContentsMargins(px(12, False), px(12, False), px(12, False), px(14, False))
        self.panel_resultados.capa.addLayout(fila(
            self.rotulo_resultados, None, self.ocultar_vaulted, self.texto_ocultar, espacio=8,
            margen=(px(8, False), 0, 0, 0),
        ))
        self.panel_resultados.capa.addWidget(self.lista, 1)
        self.panel_resultados.capa.addWidget(self.leyenda)
        self.panel_resultados.hide()

        # -- ficha ------------------------------------------------------------------------
        self.ficha = FichaC()
        self.ficha.filtro_teclas = self._teclas
        self.ficha.installEventFilter(self._teclas)
        self.ficha.anchorClicked.connect(self._enlace)
        self.ficha.cambio_ancho.connect(lambda _e: self._montar(conservar_scroll=True))
        # Precio del mercado de la ficha abierta: la respuesta llega despues, asi que es
        # una etiqueta que sobrevive a los repintados de la ficha.
        self.precios = etiqueta("", "normal", envolver=True)
        self.precios.hide()
        self._aparcadero = QWidget(self)
        self._aparcadero.hide()
        self.precios.setParent(self._aparcadero)
        self._slug_actual = ""

        self.divisor = QSplitter(Qt.Horizontal)
        self.divisor.setChildrenCollapsible(False)
        self.divisor.setHandleWidth(px(14, False))
        self.divisor.setStyleSheet("QSplitter::handle { background: transparent; }")
        self.divisor.addWidget(self.panel_resultados)
        self.divisor.addWidget(self.ficha)
        self.divisor.setStretchFactor(1, 1)
        self.divisor.setSizes([px(390, False), px(800, False)])

        self.aviso = EtiquetaC(t("Preparando los datos..."), "pequeno")
        self.barra_teclas: BarraTeclas | None = None
        self._pie = transparente(QWidget())
        self._capa_pie = QVBoxLayout(self._pie)
        self._capa_pie.setContentsMargins(0, 0, 0, 0)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, px(4, False), px(4, False), px(2, False))
        caja.setSpacing(px(10, False))
        caja.addWidget(self.panel_buscar)
        caja.addWidget(self.aviso)
        caja.addWidget(self.barra_acciones)
        caja.addWidget(self.divisor, 1)
        caja.addWidget(self._pie)

        self._repintado_imagenes = QTimer(self)
        self._repintado_imagenes.setSingleShot(True)
        self._repintado_imagenes.setInterval(150)
        self._repintado_imagenes.timeout.connect(lambda: self._montar(conservar_scroll=True))

        # Al escribir se espera un momento a que se deje de teclear y la busqueda va a un hilo
        # aparte (busqueda_fondo): la caja nunca se atasca y solo se ensena la ultima.
        self._busqueda = BusquedaEnFondo(self)
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(RETARDO_TECLAS_MS)
        self._temporizador.timeout.connect(self._buscar_en_fondo)

        self.caja.textChanged.connect(lambda _: self._temporizador.start())
        self.caja.textChanged.connect(lambda _: self._actualizar_boton_wiki())
        self.lista.currentRowChanged.connect(self._elegir_resultado)
        imagenes().lista.connect(self._imagen_lista)
        self._mensaje_aviso = "Preparando los datos..."
        self.retraducir()
        self.habilitar(False, self._mensaje_aviso)

    # -- ciclo de vida ---------------------------------------------------

    def habilitar(self, listo: bool, mensaje: str = "") -> None:
        """`mensaje` llega ya traducido (quien lo manda sabe el motivo); aqui se pinta."""
        self.caja.setEnabled(listo)
        self.aviso.setText(mensaje)
        self.aviso.setVisible(bool(mensaje))
        # Lo que estuviera buscando el hilo era sobre el indice de antes.
        self._busqueda.cancelar()
        self._sugerencias_hechas.clear()
        if listo:
            self.con = indice.conectar()
            self.caja.setFocus()
            if not self.caja.text().strip():
                self._poner_portada()

    def conectar_usuario(self, usuario: sqlite3.Connection | None) -> None:
        self.usuario = usuario
        self.refrescar_perfil()

    def refrescar_perfil(self) -> None:
        """Tras importar (o no tener) perfil: la ficha abierta cambia su marca de maestria."""
        self._hay_perfil = self.usuario is not None and perfil.hay_perfil(self.usuario)
        self.repintar()

    def _estado_maestria(self, item_id: int):
        if not self._hay_perfil or self.con is None or self.usuario is None:
            return None
        return estado_con_padre(self.usuario, self.con, item_id)

    def _etiqueta_maestria(self, item_id: int) -> str:
        """Dominado / a medias / sin dominar, o nada si no hay perfil o el objeto no da maestria.
        (HTML: lo usa tambien la vista compacta.)"""
        estado = self._estado_maestria(item_id)
        texto = texto_maestria(estado) if estado is not None else None
        if not texto:
            return ""
        fondo, color = colores_maestria(estado)
        return _etiqueta(texto, fondo, color, "dominado")

    def _etiqueta_inventario(self, unique_name: str) -> str:
        """'Tienes 3', si el inventario se ha leido en pantalla."""
        if self.usuario is None:
            return ""
        lectura = estado_inventario.cantidad_de(self.usuario, unique_name)
        if lectura is None:
            return ""
        texto = t("Tienes {n}", n=lectura.cantidad)
        if lectura.cantidad:
            return _etiqueta(texto, "#15301a", COLOR_DISPONIBLE, "inventario")
        return _etiqueta(texto, PALETA["panel"], PALETA["suave"], "inventario")

    def _tienes_componente(self, componente) -> str:
        """En la lista de piezas: '(tienes 2)', verde si cubre lo que pide la receta."""
        if self.usuario is None:
            return ""
        lectura = estado_inventario.cantidad_de(self.usuario, componente["unique_name"])
        if lectura is None:
            return ""
        cubre = lectura.cantidad >= (componente["item_count"] or 1)
        color = COLOR_DISPONIBLE if cubre else PALETA["suave"]
        texto = html.escape(t("tienes {n}", n=lectura.cantidad))
        return f" <span style='color:{color}'>({texto})</span>"

    def repintar(self) -> None:
        """Tras cambiar de tema, idioma o ritmo: la ficha lleva colores y textos dentro."""
        p = PALETA
        self.lista.setStyleSheet(
            "QListWidget#listaResultadosC { background: transparent; border: none; outline: none; }"
        )
        self.leyenda.setStyleSheet(f"color: {p['suave']}; font-size: {px(11)}px; background: transparent;")
        self._poner_leyenda()
        self.lista.viewport().update()
        refrescar_todo(self)
        self._montar(conservar_scroll=True)

    def _poner_ficha(self, contenido: str) -> None:
        """Pinta un HTML suelto como ficha (sin paneles), con su relleno de filas al momento."""
        self._aparcar()
        self.ficha.setHtml(contenido)
        self._poner_barra_teclas()

    def retraducir(self) -> None:
        """Tras cambiar de idioma: textos fijos, lista de resultados y ficha abierta."""
        self.caja.setPlaceholderText(t("Busca un objeto, una misión o pregunta  (p. ej. sistemas ash prime, hepit, el último warframe)"))
        self.texto_ocultar.setText(t("Ocultar bóveda"))
        self.texto_ocultar.setToolTip(t("Ocultar reliquias en bóveda"))
        self.atras.setText(t("‹ Atrás"))
        self.boton_objetivo.setText(t("+ Objetivo"))
        self.boton_set.setText(t("+ Set completo"))
        self.boton_wiki.setText(t("Wiki"))
        self.boton_youtube.setText(t("YouTube"))
        self.boton_youtube.setToolTip(t("Busca guías en YouTube de la misión o el objeto abierto, "
                                        "ordenadas por visitas, y las abre en el reproductor de Farmadex."))
        self.boton_overframe.setToolTip(t("Abre Overframe, la web de builds de la comunidad, con este "
                                          "warframe o arma, dentro de Farmadex (pestaña Web)."))
        self.boton_wiki.setToolTip(t("Abre la wiki oficial de Warframe en el navegador: la página "
                                     "del objeto abierto o, si no hay ninguno, la búsqueda de lo escrito."))
        if self._resultados:
            self._pintar_resultados()
        self.repintar()

    def _imagen_lista(self, nombre: str) -> None:
        self.lista.viewport().update()
        if nombre in self._imagenes_ficha:
            self._imagenes_ficha.discard(nombre)
            if self.pedestal is not None and self._datos_actuales and \
                    self._datos_actuales["item"].get("imagen") == nombre:
                self.pedestal.poner_imagen(imagenes().pixmap(nombre, px(240, False)))
            else:
                # Varias imagenes de un set llegan casi a la vez: se repinta una sola vez.
                self._repintado_imagenes.start()

    def _pedir_imagen(self, nombre: str | None, lado: int):
        """La imagen si ya esta en disco; si no, se pide y se apunta para repintar al llegar."""
        if not nombre:
            return None
        mapa = imagenes().pixmap(nombre, lado)
        if mapa is None:
            self._imagenes_ficha.add(nombre)
        return mapa

    # -- teclas ------------------------------------------------------------

    def _enter(self) -> None:
        """Enter en la caja: busca ya y pasa el foco a la lista (alli funcionan las teclas)."""
        self._temporizador.stop()
        self._buscar()
        if self.lista.count():
            self.lista.setFocus()

    def hay_ficha(self) -> bool:
        return bool(self._datos_actuales or self._mision_actual)

    def puede_volver(self) -> bool:
        return len(self._historial) > 1 and self.hay_ficha()

    def tecla(self, evento) -> bool:
        """Una tecla de la barra del pie; True si se ha usado."""
        if evento.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        clave, texto = evento.key(), evento.text()
        if clave == Qt.Key_Escape:
            if self.puede_volver():
                self._volver()
                return True
            return False
        if not self.hay_ficha():
            return False
        if texto == "+" or clave == Qt.Key_Plus:
            if self.boton_objetivo.isEnabled():
                self.boton_objetivo.click()
            return True
        acciones = {
            Qt.Key_W: self.boton_wiki,
            Qt.Key_Y: self.boton_youtube,
            Qt.Key_O: self.boton_overframe,
        }
        if clave in acciones:
            boton = acciones[clave]
            if boton.isEnabled() and not boton.isHidden():
                boton.click()
            return True
        if clave == Qt.Key_C:
            nombre = self.nombre_ficha()
            if nombre:
                self.copiar(nombre)
            return True
        return False

    def nombre_ficha(self) -> str:
        """El nombre de lo que se ve, tal cual se escribe en el juego (para copiarlo)."""
        if self._datos_actuales:
            item, padre = self._datos_actuales["item"], self._datos_actuales["padre"]
            return _con_padre(nombre_idioma(item), nombre_idioma(padre) if padre else None)
        return self.tema_video()

    def resizeEvent(self, evento):  # noqa: N802 - firma de Qt
        super().resizeEvent(evento)
        self._ajustar_pie()

    def _ajustar_pie(self) -> None:
        """En una ventana estrecha la barra de teclas no cabe: se esconde (las teclas siguen)."""
        if self.barra_teclas is not None:
            self.barra_teclas.setVisible(self.width() >= px(900, False))

    def _poner_barra_teclas(self) -> None:
        """La barra del pie con las teclas que sirven en la ficha abierta."""
        if self.barra_teclas is not None:
            self.barra_teclas.setParent(None)
            self.barra_teclas.deleteLater()
            self.barra_teclas = None
        if not self.hay_ficha():
            return
        pares = []
        if self.boton_objetivo.isEnabled():
            pares.append(("+", t("Añadir a mis metas")))
        if self.boton_wiki.isEnabled():
            pares.append(("W", t("Wiki")))
        if not self.boton_overframe.isHidden():
            pares.append(("O", "Overframe"))
        if self.boton_youtube.isEnabled():
            pares.append(("Y", t("YouTube")))
        pares.append(("C", t("Copiar nombre")))
        if self.puede_volver():
            pares.append(("Esc", t("Volver")))
        self.barra_teclas = BarraTeclas(pares)
        self._capa_pie.addWidget(self.barra_teclas)
        self._ajustar_pie()

    # -- navegacion --------------------------------------------------------

    def _cambiar_filtro(self, marcado: bool) -> None:
        self.config["ocultar_vaulted"] = marcado
        guardar(self.config)
        if self._actual:
            self.abrir(self._actual, recordar=False)

    def _enlace(self, url: QUrl | str) -> None:
        texto = url.toString() if isinstance(url, QUrl) else str(url)
        if glosario.mostrar(texto, self.ficha):
            return
        if texto.startswith(ficha_detalles.PREFIJO_COPIAR):
            self.copiar(texto.removeprefix(ficha_detalles.PREFIJO_COPIAR))
        elif texto.startswith("item:"):
            self.abrir(int(texto.removeprefix("item:")))
        elif texto.startswith(("nodo:", "modo:", "novedades:")):
            self.abrir_mision(texto)
        elif texto.startswith("mas:"):
            letra = texto.removeprefix("mas:")
            self._rotaciones_abiertas ^= {letra}
            self._montar(conservar_scroll=True)
        elif texto == "video:":
            self._abrir_youtube()
        elif texto == "overframe:":
            self._abrir_overframe()
        elif texto.startswith("buscar:"):
            self.caja.setText(texto.removeprefix("buscar:"))
        elif texto.startswith("http"):
            QDesktopServices.openUrl(QUrl(texto))

    def copiar(self, texto: str) -> None:
        """Copia al portapapeles (el codigo de un glifo) y lo dice en la barra de estado."""
        QGuiApplication.clipboard().setText(texto)
        self.estado.emit(t("Copiado: {codigo}", codigo=texto))

    def url_wiki(self) -> str:
        """Lo que abre "Wiki": la pagina del objeto abierto o la busqueda.

        Con un objeto sin pagina conocida se busca por su nombre ingles, que es el de la
        wiki; sin ficha, lo escrito tal cual (la wiki salta a la pagina si coincide).
        """
        if self._datos_actuales:
            item = self._datos_actuales["item"]
            return enlaces_wiki.url_item(item) or enlaces_wiki.url_busqueda(item.get("nombre_en") or "")
        if self._mision_actual:
            tipo, valor = self._mision_actual.split(":", 1)
            if tipo == "novedades":
                datos = novedades.ultima(self.con, valor)
                return enlaces_wiki.url_busqueda(datos["actualizacion"]) if datos else ""
            if tipo == "modo":
                return enlaces_wiki.url_modo(valor)
            n = misiones.nodo(self.con, int(valor)) if self.con else None
            return enlaces_wiki.url_nodo(n["nodo_en"]) if n else ""
        texto = self.caja.text().strip()
        return enlaces_wiki.url_busqueda(texto) if texto else ""

    def _abrir_wiki(self) -> None:
        url = self.url_wiki()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _actualizar_boton_wiki(self) -> None:
        hay_ficha = self.hay_ficha()
        self.boton_wiki.setEnabled(hay_ficha or bool(self.caja.text().strip()))
        self.boton_youtube.setEnabled(hay_ficha)
        self.boton_overframe.setVisible(bool(self.url_overframe()))

    def tema_video(self) -> str:
        """De que se buscan guias: 'Hepit Captura', 'Supervivencia' o el objeto abierto."""
        if self._datos_actuales:
            item, padre = self._datos_actuales["item"], self._datos_actuales["padre"]
            return _con_padre(nombre_idioma(item), nombre_idioma(padre) if padre else None)
        if self._mision_actual and self.con:
            tipo, valor = self._mision_actual.split(":", 1)
            if tipo == "novedades":
                datos = novedades.ultima(self.con, valor)
                return novedades.titulo(datos) if datos else ""
            if tipo == "modo":
                return modos_mision.nombre(valor)
            n = misiones.nodo(self.con, int(valor))
            return f"{misiones.titulo_nodo(n)} {modos_mision.nombre(n['modo'])}" if n else ""
        return ""

    def url_youtube(self) -> str:
        return guias_youtube.url_guia(self.tema_video(), cargar().get(guias_youtube.CLAVE_API))

    def _abrir_youtube(self) -> None:
        url = self.url_youtube()
        if not url:
            return
        if self.reproductor is not None:
            self.reproductor(url)
        else:
            QDesktopServices.openUrl(QUrl(url))

    def url_overframe(self) -> str:
        """Builds en Overframe del objeto abierto (o de su padre si es una pieza); vacio si no tiene."""
        if not self._datos_actuales:
            return ""
        datos = self._datos_actuales
        return builds_overframe.url_builds(builds_overframe.nombre_con_builds(datos["item"], datos.get("padre")))

    def _abrir_overframe(self) -> None:
        url = self.url_overframe()
        if not url:
            return
        if self.navegador_web is not None:
            self.navegador_web(url)
        else:
            QDesktopServices.openUrl(QUrl(url))

    def _ver_agrietados(self) -> None:
        """"Precios" de la disposicion: la herramienta Agrietados con esta arma elegida."""
        ventana = self.window()
        pagina = getattr(ventana, "agrietados", None)
        if pagina is None or not hasattr(ventana, "ir_a") or not self._datos_actuales:
            return
        ventana.ir_a("herramientas/agrietados")
        unico = self._datos_actuales["item"].get("unique_name")
        combo = getattr(pagina, "arma", None)
        if combo is None:
            return
        for i in range(combo.count()):
            dato = combo.itemData(i)
            if getattr(dato, "unique_name", None) == unico:
                combo.setCurrentIndex(i)
                return

    def _volver(self) -> None:
        """Vuelve a la ficha anterior, venga de donde venga: de la lista, de una
        busqueda distinta o de un enlace dentro de una ficha."""
        if len(self._historial) < 2:
            return
        self._historial.pop()  # la que se esta viendo
        item_id, consulta = self._historial[-1]
        # Si aquella ficha salio de otra busqueda, se recupera tambien el texto y
        # su lista; si no, la lista de resultados dejaria de cuadrar con la ficha.
        if consulta and consulta != self.caja.text().strip():
            self._volviendo = True
            self.caja.setText(consulta)
            self._buscar()
            self._volviendo = False
        self._seleccionar_en_lista(item_id)
        if isinstance(item_id, str):
            self.abrir_mision(item_id, recordar=False)
        else:
            self.abrir(item_id, recordar=False)
        self.atras.setEnabled(len(self._historial) > 1)
        self._poner_barra_teclas()

    def _seleccionar_en_lista(self, item_id: int) -> None:
        """Deja marcado en la lista el objeto al que se vuelve, sin abrirlo otra vez."""
        for fila_n, resultado in enumerate(self._resultados):
            if (resultado.get("clave") or resultado["item_id"]) == item_id:
                self.lista.blockSignals(True)
                self.lista.setCurrentRow(fila_n)
                self.lista.blockSignals(False)
                return

    def abrir(self, item_id: int, recordar: bool = True) -> None:
        if not self.con:
            return
        datos = items.ficha(self.con, item_id)
        if not datos:
            return
        if self._actual != item_id:
            self._nota_novedad = None  # la nota era de otro objeto
        self._actual = item_id
        self._datos_actuales = datos
        self._mision_actual = None
        self._sin_resultados = None
        if recordar and (not self._historial or self._historial[-1][0] != item_id):
            # Se guarda con la busqueda que lo encontro, para poder rehacerla al volver.
            self._historial.append((item_id, self.caja.text().strip()))
            del self._historial[:-MAX_HISTORIAL]
        self.atras.setEnabled(len(self._historial) > 1)
        self.boton_objetivo.setEnabled(True)
        # El set solo tiene sentido en algo que se construye con piezas.
        self.boton_set.setEnabled(bool(datos["componentes"] or datos["padre"]))
        self._actualizar_boton_wiki()
        self._consultar_precio(datos["item"])
        self._montar()
        self.ficha.verticalScrollBar().setValue(0)

    def _consultar_precio(self, item: dict) -> None:
        slug = item.get("market_slug")
        self._slug_actual = slug or ""
        if not slug:
            self.precios.hide()
            return
        self.precios.setText(_sin_prefijo_mercado(t("Mercado: consultando precios...")))
        self.precios.show()
        self.pedir_precios.emit(slug)

    def mostrar_precios(self, slug: str, precios) -> None:
        from ..online.servicio_market import resumen

        if slug != self._slug_actual:
            return
        self.precios.setText(_sin_prefijo_mercado(resumen(precios)))
        self.precios.show()

    # -- busqueda ---------------------------------------------------------

    def _buscar(self) -> None:
        """Busca ya, en primer plano (Enter, volver atras). Lo tecleado va por _buscar_en_fondo."""
        if not self.con:
            return
        self._temporizador.stop()
        self._busqueda.cancelar()
        texto = self.caja.text().strip()
        self._aplicar_busqueda(texto, calcular_busqueda(self.con, texto) if len(texto) >= 2 else None)

    def _buscar_en_fondo(self) -> None:
        """Lo que salta al dejar de teclear: lo pesado en otro hilo, la ventana libre."""
        if not self.con:
            return
        texto = self.caja.text().strip()
        if len(texto) < 2:
            self._buscar()  # portada: no hay nada que buscar
            return

        def al_terminar(calculado: dict) -> None:
            if self.caja.text().strip() == texto:
                self._aplicar_busqueda(texto, calculado)

        self._busqueda.pedir(self.con, lambda con: calcular_busqueda(con, texto), al_terminar)

    def _aplicar_busqueda(self, texto: str, calculado: dict | None) -> None:
        self.lista.clear()
        if calculado and "sugerencias" in calculado:
            if len(self._sugerencias_hechas) > 20:
                self._sugerencias_hechas.clear()
            self._sugerencias_hechas[texto] = calculado["sugerencias"]
        if calculado is None:
            self._resultados = []
            self._pintar_resultados()
            self._vaciar_ficha()
            self._poner_portada()
            return
        objetos = calculado["objetos"]
        mejor_objeto = min((r["nivel"] for r in objetos), default=9)
        filtro = calculado["filtro"]
        if filtro and mejor_objeto > 0 and self._buscar_novedades(filtro):
            return
        # Nodos y tipos de mision: delante solo si casan mejor que el mejor objeto que se
        # puede conseguir ("hepit" solo es nodo); si empatan, los objetos siguen primero.
        # Lo que no tiene fuentes no cuenta: el reto de Onda nocturna "Supervivencia" no
        # puede tapar al tipo de mision.
        mejor_farmeable = min((r["nivel"] for r in objetos if r["peso"][2] == 0), default=9)
        encontradas = calculado["encontradas"]
        self._resultados = (
            [m for m in encontradas if m["nivel"] < mejor_farmeable]
            + objetos
            + [m for m in encontradas if m["nivel"] >= mejor_farmeable]
        )
        self._pintar_resultados()
        self.estado.emit(t("{n} resultados", n=len(self._resultados)))
        if self._resultados:
            self.lista.setCurrentRow(0)
        else:
            # Sin resultados la ficha anterior no puede quedarse: se leeria como la
            # respuesta a lo que se acaba de escribir.
            self._vaciar_ficha()
            self._sin_resultados = texto
            self._montar()

    def _buscar_novedades(self, filtro: str) -> bool:
        """Lo nuevo de la ultima actualizacion, filtrado por lo pedido.

        'el ultimo warframe' con un solo warframe nuevo que no es prime (Narin) abre su
        ficha directamente, con los demas de la actualizacion en una nota; si no, la
        ficha de novedades. Sin datos de fecha, un aviso en vez de nada.
        """
        datos = novedades.ultima(self.con, filtro)
        self._resultados = datos["items"] if datos else []
        self._pintar_resultados()
        if not datos:
            self._vaciar_ficha()
            self._poner_ficha(
                f"<p style='color:{PALETA['suave']};margin-top:8px'>"
                + html.escape(t("No hay datos de fecha de salida en el índice. Se añaden al "
                                "actualizar los datos del juego."))
                + "</p>"
            )
            return True
        self.estado.emit(t("{n} resultados", n=len(self._resultados)))
        no_primes = [f for f in datos["items"] if not f["es_prime"]]
        if filtro in ("warframe", "arma") and len(no_primes) == 1:
            otros = [f for f in datos["items"] if f is not no_primes[0]]
            self.abrir(no_primes[0]["item_id"])
            self._nota_novedad = {**datos, "items": otros}
            self._seleccionar_en_lista(no_primes[0]["item_id"])
            self._montar()
            return True
        self.abrir_mision(f"novedades:{filtro}")
        return True

    def _html_portada(self) -> str:
        datos = novedades.ultima(self.con) if self.con is not None else None
        if not datos:
            return ""
        p = PALETA
        nombres = ", ".join(
            f"<a style='color:{p['acento']};text-decoration:none' href='item:{f['item_id']}'>"
            f"{html.escape(nombre_idioma(f))}</a>"
            for f in datos["items"][:6]
        )
        if len(datos["items"]) > 6:
            nombres += f", <a style='color:{p['acento']}' href='novedades:todo'>&hellip;</a>"
        titulo = t("Novedades ({actualizacion})", actualizacion=novedades.titulo(datos))
        return (
            f"<p style='color:{p['suave']}'>"
            f"<a style='color:{p['suave']};text-decoration:none' href='novedades:todo'>{html.escape(titulo)}</a>: "
            f"{nombres}</p>"
        )

    def _poner_portada(self) -> None:
        """Con el buscador vacio, un panel discreto con lo nuevo de la ultima actualizacion."""
        contenido = self._html_portada()
        if not contenido:
            return
        self._aparcar()
        self.ficha.vaciar()
        panel = PanelC()
        panel.capa.addWidget(self.ficha.bloque(contenido))
        self.ficha.anadir(panel)
        self.ficha.terminar()
        self._poner_barra_teclas()

    def _html_novedades(self, filtro: str) -> str:
        datos = novedades.ultima(self.con, filtro)
        if not datos:
            return ""
        return (
            f"<div style='font-size:22px;font-weight:bold'>{html.escape(self._titulo_novedades(datos))}</div>"
            f"<div style='color:{PALETA['suave']};font-size:13px;margin-top:2px'>"
            f"{html.escape(datos['actualizacion'])}</div>"
            + _seccion(t("Objetos nuevos ({n})", n=len(datos["items"])))
            + self._tabla_novedades(datos)
        )

    @staticmethod
    def _titulo_novedades(datos: dict) -> str:
        return t("Lo nuevo de la {actualizacion} ({fecha})", actualizacion=novedades.titulo(datos),
                 fecha=novedades.fecha_legible(datos["fecha"]))

    def _tabla_novedades(self, datos: dict) -> str:
        p = PALETA
        filas = []
        for f in datos["items"]:
            tipo = colores_tipo.tipo_de(f)
            filas.append(
                f"<tr><td width='4' style='background:{colores_tipo.color(tipo, p['panel2'])}'></td>"
                f"<td><a style='color:{p['texto']};text-decoration:none' href='item:{f['item_id']}'>"
                f"<b>{html.escape(nombre_idioma(f))}</b></a></td>"
                f"<td style='color:{p['suave']}'>{html.escape(categoria_es(f['categoria'], f.get('tipo')))}</td>"
                f"<td align='right'><a style='color:{p['acento']};text-decoration:none' href='item:{f['item_id']}'>"
                f"{html.escape(t('Cómo conseguirlo'))} &rarr;</a></td></tr>"
            )
        return _envolver(filas)

    def _html_nota_novedad(self) -> str:
        """'Lo mas nuevo: Actualizacion 44.0 (23/09/2026). Tambien salio: Citrine Prime.'"""
        nota = self._nota_novedad
        if not nota:
            return ""
        p = PALETA
        texto = html.escape(t("Lo más nuevo: {actualizacion} ({fecha}).", actualizacion=novedades.titulo(nota),
                              fecha=novedades.fecha_legible(nota["fecha"])))
        if nota["items"]:
            otros = ", ".join(
                f"<a style='color:{p['acento']};text-decoration:none' href='item:{f['item_id']}'>"
                f"{html.escape(nombre_idioma(f))}</a>"
                for f in nota["items"]
            )
            texto += f" {html.escape(t('También salió:'))} {otros}."
        return f"<div style='color:{p['suave']};margin-top:6px'>{texto}</div>"

    def _vaciar_ficha(self) -> None:
        self._actual = None
        self._datos_actuales = None
        self._mision_actual = None
        self._nota_novedad = None
        self._sin_resultados = None
        self._slug_actual = ""
        self._imagenes_ficha.clear()
        self._aparcar()
        self.ficha.clear()
        self.precios.hide()
        self.boton_objetivo.setEnabled(False)
        self.boton_set.setEnabled(False)
        self._actualizar_boton_wiki()
        self._poner_barra_teclas()

    def sugerencias(self, texto: str) -> list[dict]:
        """Objetos parecidos a una busqueda fallida (ver `buscar_sugerencias`). Si la
        busqueda en segundo plano ya las calculo, no se repiten en el hilo de la ventana."""
        if not self.con:
            return []
        hechas = self._sugerencias_hechas.get(texto)
        return hechas if hechas is not None else buscar_sugerencias(self.con, texto)

    def _html_sin_resultados(self, texto: str) -> str:
        p = PALETA
        partes = [
            f"<div style='font-size:18px;font-weight:bold'>"
            f"{html.escape(t('No he encontrado nada para «{busqueda}»', busqueda=texto))}</div>"
        ]
        parecidos = self.sugerencias(texto)
        if parecidos:
            enlaces = "".join(
                f"<li><a style='color:{p['acento']};text-decoration:none' href='item:{r['item_id']}'>"
                f"{html.escape(_con_padre(nombre_idioma(r), nombre_idioma(r, 'padre')))}</a>"
                f" <span style='color:{p['suave']}'>&middot; "
                f"{html.escape(categoria_es(r['categoria'], r.get('tipo')))}</span></li>"
                for r in parecidos
            )
            partes.append(
                f"<div style='color:{p['suave']};margin-top:10px'>"
                f"{html.escape(t('Quizá buscabas:'))}</div><ul>{enlaces}</ul>"
            )
        partes.append(
            f"<p style='color:{p['suave']};margin-top:10px'>"
            + html.escape(t(
                "Busca por el nombre del objeto, la pieza, el mod o la reliquia "
                "(p. ej. Rhino, Sierra, Axi A7), no por preguntas."
            ))
            + "</p>"
        )
        return "".join(partes)

    def _pintar_resultados(self) -> None:
        fila_actual = self.lista.currentRow()
        self.lista.blockSignals(True)
        self.lista.clear()
        for r in self._resultados:
            if r.get("clave"):
                self.lista.addItem(self._elemento_mision(r))
                continue
            nombre = nombre_idioma(r)
            padre = nombre_idioma(r, "padre")
            elemento = QListWidgetItem(_con_padre(nombre, padre))
            subtitulo = categoria_es(r["categoria"], r.get("tipo"))
            # Debajo, el nombre en el otro idioma del indice, si es distinto.
            otro = r["nombre_en"] if es_castellano() else r["nombre_es"]
            if otro and otro != nombre:
                subtitulo += f" · {otro}"
            elemento.setData(ROL_SUBTITULO, subtitulo)
            elemento.setData(ROL_IMAGEN, r.get("imagen"))
            elemento.setData(ROL_TIPO, colores_tipo.tipo_de(r))
            elemento.setToolTip(r["categoria"])
            self.lista.addItem(elemento)
        if 0 <= fila_actual < self.lista.count():
            self.lista.setCurrentRow(fila_actual)
        self.lista.blockSignals(False)
        n = len(self._resultados)
        self.rotulo_resultados.setText(t("1 resultado") if n == 1 else t("{n} resultados", n=n))
        self.panel_resultados.setVisible(bool(self._resultados))
        self._poner_leyenda()

    def _poner_leyenda(self) -> None:
        texto = colores_tipo.leyenda_html(
            (colores_tipo.tipo_de(r) for r in self._resultados), PALETA["panel"]
        )
        self.leyenda.setText(texto)
        self.leyenda.setVisible(bool(texto))

    def _elegir_resultado(self, fila_n: int) -> None:
        # Moverse por la lista tambien cuenta como navegar: antes se borraba el
        # historial aqui y el boton "Atras" quedaba apagado casi siempre.
        if 0 <= fila_n < len(self._resultados) and not self._volviendo:
            resultado = self._resultados[fila_n]
            if resultado.get("clave"):
                self.abrir_mision(resultado["clave"])
            else:
                self.abrir(resultado["item_id"])

    def _elemento_mision(self, r: dict) -> QListWidgetItem:
        """Un nodo ('Hepit' / 'Nodo · Vacio · Captura') o un tipo de mision en la lista."""
        if r["tipo_resultado"] == "modo":
            elemento = QListWidgetItem(modos_mision.nombre(r["modo"]))
            n = len(misiones.nodos_de_modo(self.con, r["modo"])) if self.con else 0
            subtitulo = t("Tipo de misión") + (" · " + t("{n} nodos", n=n) if n else "")
        else:
            elemento = QListWidgetItem(misiones.titulo_nodo(r))
            subtitulo = " · ".join(
                x for x in (modos_mision.nombre(r["modo"]), nombre_idioma(r, "planeta")) if x
            )
        elemento.setData(ROL_SUBTITULO, subtitulo)
        elemento.setData(ROL_IMAGEN, None)
        elemento.setData(ROL_TIPO, "mision")
        return elemento

    # -- fichas de mision -------------------------------------------------

    def abrir_mision(self, clave: str, recordar: bool = True) -> None:
        """Ficha de un nodo ('nodo:98'), de un tipo de mision ('modo:Survival') o de novedades."""
        if not self.con:
            return
        if not self._mision_valida(clave):
            return
        if clave != self._mision_actual:
            self._rotaciones_abiertas.clear()
        self._actual = None
        self._datos_actuales = None
        self._mision_actual = clave
        self._sin_resultados = None
        if recordar and (not self._historial or self._historial[-1][0] != clave):
            self._historial.append((clave, self.caja.text().strip()))
            del self._historial[:-MAX_HISTORIAL]
        self.atras.setEnabled(len(self._historial) > 1)
        self._slug_actual = ""
        self.precios.hide()
        self.boton_objetivo.setEnabled(False)
        self.boton_set.setEnabled(False)
        self._actualizar_boton_wiki()
        self._montar()
        self.ficha.verticalScrollBar().setValue(0)

    def _mision_valida(self, clave: str) -> bool:
        tipo, _, valor = clave.partition(":")
        if tipo == "novedades":
            return novedades.ultima(self.con, valor) is not None
        if tipo == "modo":
            return bool(modos_mision.normalizar(valor))
        return tipo == "nodo" and valor.isdigit() and misiones.nodo(self.con, int(valor)) is not None

    def _html_mision(self, clave: str) -> str:
        """La ficha de mision entera en un solo HTML (referencia y pruebas)."""
        tipo, _, valor = clave.partition(":")
        if tipo == "novedades":
            return self._html_novedades(valor)
        if tipo == "modo":
            return self._html_modo(valor)
        if tipo == "nodo" and valor.isdigit():
            n = misiones.nodo(self.con, int(valor))
            return self._html_nodo(n) if n else ""
        return ""

    def _etiquetas_nodo(self, n: dict) -> list[tuple[str, str, str | None]]:
        """(texto, tinta, clave del glosario) de las insignias de un nodo."""
        salida = []
        detalle = modos_mision.explicacion(n["modo"])
        salida.append((modos_mision.nombre(n["modo"]), "secundario",
                       f"mision?{quote(detalle, safe='')}" if detalle else None))
        faccion = glosa(n["faccion_es"], n["faccion_en"]) if n.get("faccion_es") else (n.get("faccion_en") or "")
        if faccion:
            salida.append((faccion, "suave", None))
        if n.get("nivel_min") is not None:
            salida.append((t("nivel {min}-{max}", min=n["nivel_min"], max=n["nivel_max"]), "suave", None))
        return salida

    def _html_nodo(self, n: dict) -> str:
        p = PALETA
        modo = n["modo"]
        titulo = misiones.titulo_nodo(n)
        otro = n["nodo_en"] if es_castellano() else (n["nodo_es"] or "")
        subtitulo = " &middot; ".join(
            html.escape(x) for x in (otro if otro != titulo else "", nombre_idioma(n, "planeta")) if x
        )
        etiquetas = [
            f"<span style='background:{p['panel']};font-size:12px;padding:2px 8px'>&nbsp;"
            + glosario.enlace_mision(modo, modos_mision.nombre(modo), p["acento"])
            + "&nbsp;</span>"
        ] + [_etiqueta(texto, p["panel"], p["suave"]) for texto, _t, _c in self._etiquetas_nodo(n)[1:]]
        return "".join((
            f"<div style='font-size:22px;font-weight:bold'>{html.escape(titulo)}</div>"
            f"<div style='color:{p['suave']};font-size:13px;margin-top:2px'>{subtitulo}</div>"
            f"<div style='margin-top:6px'>{' '.join(etiquetas)}</div>",
            self._bloque_modo(modo),
            self._bloque_recompensas_nodo(n),
            self._pie_mision([n], modo),
        ))

    def _html_modo(self, modo_en: str) -> str:
        modo = modos_mision.normalizar(modo_en)
        if not modo:
            return ""
        return "".join((
            f"<div style='font-size:22px;font-weight:bold'>{html.escape(modos_mision.nombre(modo))}</div>"
            f"<div style='color:{PALETA['suave']};font-size:13px;margin-top:2px'>{self._detalle_modo(modo)}</div>",
            self._bloque_modo(modo),
            self._bloque_nodos_modo(modo),
            self._pie_mision([], modo),
        ))

    def _detalle_modo(self, modo: str) -> str:
        nombre = modos_mision.nombre(modo)
        otro = modos_mision.MODOS[modo][1] if es_castellano() else ""
        detalle = html.escape(t("Tipo de misión"))
        if otro and otro != nombre:
            detalle += " &middot; " + html.escape(otro)
        return detalle

    def _bloque_nodos_modo(self, modo: str, titulo: bool = True) -> str:
        p = PALETA
        nodos = misiones.nodos_de_modo(self.con, modo)
        if not nodos:
            return ""
        filas = []
        for n in nodos:
            nivel = (
                " &middot; " + html.escape(t("nivel {min}-{max}", min=n["nivel_min"], max=n["nivel_max"]))
                if n.get("nivel_min") is not None else ""
            )
            filas.append(
                f"<li><a style='color:{p['acento']};text-decoration:none' href='nodo:{n['id']}'>"
                f"{html.escape(misiones.titulo_nodo(n))}</a>"
                f" <span style='color:{p['suave']}'>&middot; {html.escape(nombre_idioma(n, 'planeta'))}"
                f"{nivel}</span></li>"
            )
        cabecera = _seccion(t("Nodos de este tipo ({n})", n=len(nodos))) if titulo else ""
        return cabecera + f"<ul style='margin-top:0'>{''.join(filas)}</ul>"

    def _html_que_te_dan(self, modo: str, premios: dict | None = None) -> str:
        """Como van las recompensas en ese modo y cuando cae cada rotacion (sin titulo)."""
        p = PALETA
        if modo not in modos_mision.MODOS:
            return ""
        _, _, _que, recompensas = modos_mision.MODOS[modo]
        texto = html.escape(t(recompensas))
        pista = self._pista_eras(premios) if premios else ""
        if pista:
            texto += " " + html.escape(pista)
        partes = [f"<p style='margin:0 0 4px 0;color:{p['suave']}'>{texto}</p>"]
        if modo == "Disruption":
            partes.append(self._tabla_disrupcion())
        partes.append(self._lineas_rotacion(modo))
        return "".join(partes)

    def _html_que_hacer(self, modo: str) -> str:
        if modo not in modos_mision.MODOS:
            return ""
        que = modos_mision.MODOS[modo][2]
        return f"<p style='margin:0'>{html.escape(t(que))}</p>"

    def _bloque_modo(self, modo: str) -> str:
        """Que se hace, como van las recompensas y cuando cae cada rotacion en ese modo."""
        p = PALETA
        if modo not in modos_mision.MODOS:
            return ""
        _, _, que, recompensas = modos_mision.MODOS[modo]
        return (
            _seccion(t("Cómo se juega"), "mision")
            + f"<p style='margin:2px 0 6px 0'><b>{html.escape(t('Qué hacer:'))}</b> {html.escape(t(que))}</p>"
            + f"<p style='margin:2px 0 6px 0'><b>{html.escape(t('Recompensas:'))}</b> "
              f"{html.escape(t(recompensas))}</p>"
            + (self._tabla_disrupcion() if modo == "Disruption" else "")
            + self._lineas_rotacion(modo)
        )

    def _lineas_rotacion(self, modo: str) -> str:
        p = PALETA
        lineas = []
        for letra in modos_mision.rotaciones_del_modo(modo):
            visible = _rotacion(self.con, letra, p["acento"], modo)
            larga = modos_mision.linea_rotacion(modo, letra)
            lineas.append(f"<li>{visible}: <span style='color:{p['suave']}'>{html.escape(larga)}</span></li>")
        return f"<ul style='margin-top:2px;margin-bottom:0'>{''.join(lineas)}</ul>" if lineas else ""

    def _pista_eras(self, premios: dict) -> str:
        """'Aqui las reliquias Axi solo salen en: B, C.' si una era no sale en todas."""
        letras = sorted(r for r in premios if r)
        if len(letras) < 2:
            return ""
        eras: dict[str, set[str]] = {}
        for letra in letras:
            for r in premios[letra]:
                era = era_de(r.get("nombre_en"))
                if era:
                    eras.setdefault(era, set()).add(letra)
        trozos = []
        for era in ERAS:
            donde = eras.get(era)
            if donde and len(donde) < len(letras):
                trozos.append(t("Aquí las reliquias {era} solo salen en: {letras}.", era=era,
                                letras=", ".join(sorted(donde))))
        return " ".join(trozos)

    def _celdas_tira(self, modo: str) -> list[tuple[str, str, str]]:
        """Casillas de la tira de rondas de un modo; vacio si no tiene rotaciones claras."""
        if modo in modos_mision.AABC:
            unidad, cada = modos_mision.AABC[modo]
            plantilla = modos_mision.CORTAS_UNIDAD[unidad][0]
            return [
                (letra, t(plantilla, n=(i + 1) * cada), modos_mision.linea_rotacion(modo, letra))
                for i, letra in enumerate("AABCAABC")
            ]
        if modo in modos_mision.CORTAS and modo != "Disruption":
            return [(letra, t(modos_mision.CORTAS[modo][letra]), modos_mision.linea_rotacion(modo, letra))
                    for letra in "ABC"]
        return []

    def _tabla_disrupcion(self) -> str:
        """Ronda x conductos salvados -> letra, tal cual la tabla de la wiki."""
        p = PALETA
        filas = [
            f"<tr style='color:{p['suave']};font-size:12px'><td>{html.escape(t('Ronda'))}</td>"
            f"<td colspan='4' align='center'>{html.escape(t('Conductos salvados'))}</td></tr>",
            f"<tr style='color:{p['suave']};font-size:12px'><td></td>"
            + "".join(f"<td align='center'>{n}</td>" for n in (1, 2, 3, 4)) + "</tr>",
        ]
        filas += [
            f"<tr><td><b>{ronda}</b></td>" + "".join(f"<td align='center'>{letra}</td>" for letra in letras) + "</tr>"
            for ronda, letras in modos_mision.TABLA_DISRUPCION
        ]
        return _envolver(filas)

    def _filas_rotacion(self, premios: list[dict], todas: bool, letra: str) -> str:
        """Tabla compacta de un panel de rotacion: rombo, objeto y probabilidad."""
        p = PALETA
        visibles = premios if todas else premios[:MAX_FILAS_ROTACION]
        filas = []
        for r in visibles:
            era = era_de(r.get("nombre_en"))
            color = COLOR_ERA.get(era) or color_rareza(r["rareza"])
            rombo = glosario.enlace("rareza", "◆", color, detalle=_glosa(self.con, "rareza", r["rareza"]) or "")
            # Una reliquia se nombra como en el juego sin la palabra "Reliquia" (Neo C11).
            etiqueta_r = ((r.get("nombre_en") or "").removesuffix(" Relic") if era
                          else _con_padre(nombre_idioma(r), nombre_idioma(r, "padre")))
            filas.append(
                f"<tr><td width='14'>{rombo}</td>"
                f"<td><a style='color:{p['texto']};text-decoration:none' href='item:{r['item_id']}'>"
                f"{html.escape(etiqueta_r)}</a></td>"
                f"<td align='right' style='color:{p['suave']}'>{(r['probabilidad'] or 0):.1f}%</td></tr>"
            )
        salida = ("<table width='100%' cellspacing='0' cellpadding='2'>" + "".join(filas) + "</table>")
        sobran = len(premios) - len(visibles)
        if sobran > 0:
            salida += (f"<div style='margin-top:4px'><a style='color:{p['suave']};text-decoration:none' "
                       f"href='mas:{letra}'>{html.escape(t('y {n} más', n=sobran))}</a></div>")
        elif todas and len(premios) > MAX_FILAS_ROTACION:
            salida += (f"<div style='margin-top:4px'><a style='color:{p['suave']};text-decoration:none' "
                       f"href='mas:{letra}'>{html.escape(t('ver menos'))}</a></div>")
        return salida

    def _bloque_recompensas_nodo(self, n: dict) -> str:
        p = PALETA
        premios = misiones.recompensas_de_nodo(self.con, n["id"])
        if not premios:
            return _seccion(t("Recompensas")) + (
                f"<p style='color:{p['suave']}'>"
                f"{html.escape(t('Este nodo no trae tabla de recompensas en los datos.'))}</p>"
            )
        partes = [_seccion(t("Recompensas"))]
        for rot in sorted(premios):
            if rot:
                titulo = _rotacion(self.con, rot, p["acento"], n["modo"])
            else:
                titulo = html.escape(t("Al terminar la misión"))
            partes.append(f"<div style='margin:6px 0 2px 4px;font-weight:bold'>{titulo}</div>")
            filas = []
            for r in premios[rot]:
                color = color_rareza(r["rareza"])
                etiqueta_r = _con_padre(nombre_idioma(r), nombre_idioma(r, "padre"))
                filas.append(
                    f"<tr><td width='6' style='background:{color}'></td>"
                    f"<td><a style='color:{p['texto']};text-decoration:none' href='item:{r['item_id']}'>"
                    f"{html.escape(etiqueta_r)}</a></td>"
                    f"<td>{glosario.enlace('rareza', _glosa(self.con, 'rareza', r['rareza']), color)}</td>"
                    f"<td align='right'><b>{(r['probabilidad'] or 0):.1f}%</b></td></tr>"
                )
            partes.append(_envolver(filas))
        return "".join(partes)

    def _pie_mision(self, nodos: list[dict], modo: str) -> str:
        """Wiki del nodo y del modo, y el enlace a las guias en video."""
        p = PALETA
        linea = enlaces_wiki.linea(nodos or [{"modo": modo}], p["suave"], p["acento"])
        video = (
            f"<p style='margin-top:6px;margin-bottom:0'><a style='color:{p['acento']};text-decoration:none' "
            f"href='video:'>{html.escape(t('Guías en YouTube'))} &rarr;</a></p>"
        )
        return linea + video

    # -- montaje de la ficha en paneles ----------------------------------------

    def _aparcar(self) -> None:
        """Saca de la ficha lo que sobrevive a los repintados antes de vaciarla."""
        self.precios.setParent(self._aparcadero)
        self.pedestal = None

    def _montar(self, conservar_scroll: bool = False) -> None:
        """Rehace la ficha con lo que haya abierto (objeto, mision, sin resultados o portada)."""
        posicion = self.ficha.verticalScrollBar().value() if conservar_scroll else 0
        # Sin setUpdatesEnabled(False) alrededor: con las actualizaciones apagadas, las piezas
        # metidas en capas anidadas se quedaban escondidas (Qt no llegaba a ensenarlas).
        if self._datos_actuales:
            self._montar_item(self._datos_actuales)
        elif self._mision_actual and self.con:
            self._montar_mision(self._mision_actual)
        elif self._sin_resultados is not None:
            self._aparcar()
            self.ficha.vaciar()
            panel = PanelC()
            panel.capa.addWidget(self.ficha.bloque(self._html_sin_resultados(self._sin_resultados)))
            self.ficha.anadir(panel)
            self.ficha.terminar()
        elif self.con is not None and not self.caja.text().strip():
            self.ficha.vaciar()
            self._poner_portada()
        self._poner_barra_teclas()
        if conservar_scroll:
            self.ficha.verticalScrollBar().setValue(posicion)

    def _panel(self, titulo: str | None = None, clave: str | None = None, html_titulo: str = "") -> PanelC:
        """PanelC con su rotulo; con `clave`, el rotulo explica el termino al pasar el raton."""
        panel = PanelC(titulo if titulo is not None or html_titulo else None)
        if panel.rotulo is not None and (clave or html_titulo):
            contenido = html_titulo or glosario.enlace(clave, (titulo or "").upper(), PALETA["acento"])
            panel.rotulo.setText(contenido)
            panel.rotulo.setProperty("fuenteC", contenido)
            panel.rotulo.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
            glosario.conectar_etiqueta(panel.rotulo)
        return panel

    def _panel_html(self, titulo: str | None, contenido: str, clave: str | None = None) -> PanelC | None:
        if not contenido:
            return None
        panel = self._panel(titulo, clave)
        panel.capa.addWidget(self.ficha.bloque(contenido))
        return panel

    def _cabecera(self, rotulo: str, titulo: str, subtitulo_html: str = "",
                  insignias: list[tuple[str, str, str | None]] | None = None, mayus: bool = True) -> PanelC:
        """Cabecera de una ficha de mision o novedades: rotulo turquesa, titulo grande e insignias."""
        panel = PanelC()
        izquierda = columna(espacio=px(2, False))
        if rotulo:
            izquierda.addWidget(etiqueta(rotulo, "rotulo", tinta="secundario", mayus=True))
        izquierda.addWidget(etiqueta(titulo, "titulo", mayus=mayus, envolver=True))
        if subtitulo_html:
            # Siempre como texto enriquecido: puede traer entidades (&middot;) sin etiquetas.
            rico = subtitulo_html if "<" in subtitulo_html else f"<span>{subtitulo_html}</span>"
            izquierda.addWidget(etiqueta(rico, "pequeno", envolver=True, enlaces=self._enlace))
        linea = QHBoxLayout()
        linea.setSpacing(px(12, False))
        linea.addLayout(izquierda, 1)
        if insignias:
            derecha = QHBoxLayout()
            derecha.setSpacing(px(8, False))
            for texto, tinta, clave in insignias:
                derecha.addWidget(InsigniaGlosa(texto, tinta=tinta, clave=clave, tam=12), 0, Qt.AlignTop)
            linea.addLayout(derecha)
        panel.capa.addLayout(linea)
        return panel

    def _montar_mision(self, clave: str) -> None:
        f = self.ficha
        self._aparcar()
        f.vaciar()
        tipo, _, valor = clave.partition(":")
        p = PALETA
        if tipo == "novedades":
            datos = novedades.ultima(self.con, valor)
            if not datos:
                f.terminar()
                return
            f.anadir(self._cabecera(t("Novedades"), self._titulo_novedades(datos),
                                    html.escape(datos["actualizacion"]), mayus=False))
            panel = self._panel_html(t("Objetos nuevos ({n})", n=len(datos["items"])), self._tabla_novedades(datos))
            f.anadir(panel)
            f.terminar()
            return
        if tipo == "modo":
            modo = modos_mision.normalizar(valor)
            if not modo:
                f.terminar()
                return
            f.anadir(self._cabecera(t("Misión||nodo"), modos_mision.nombre(modo), self._detalle_modo(modo)))
            self._paneles_modo(modo, None)
            f.anadir(self._panel_html(t("Qué hacer"), self._html_que_hacer(modo) + self._pie_mision([], modo)))
            f.anadir(self._panel_html(t("Nodos de este tipo ({n})", n=len(misiones.nodos_de_modo(self.con, modo))),
                                      self._bloque_nodos_modo(modo, titulo=False)))
            f.terminar()
            return
        n = misiones.nodo(self.con, int(valor)) if valor.isdigit() else None
        if not n:
            f.terminar()
            return
        modo = n["modo"]
        titulo = misiones.titulo_nodo(n)
        otro = n["nodo_en"] if es_castellano() else (n["nodo_es"] or "")
        planeta = nombre_idioma(n, "planeta")
        rotulo = " · ".join(x for x in (t("Misión||nodo"), planeta) if x)
        # El planeta ya va en el rotulo; debajo, el nombre en el otro idioma del indice.
        sub = html.escape(otro) if otro and otro != titulo else ""
        f.anadir(self._cabecera(rotulo, titulo, sub, self._etiquetas_nodo(n)))
        premios = misiones.recompensas_de_nodo(self.con, n["id"])
        self._paneles_modo(modo, premios)
        # Un panel por rotacion, en columnas si caben.
        if premios:
            letras = sorted(premios)
            columnas = 1 if f.estrecha() else min(3, len(letras))
            rejilla = QGridLayout()
            rejilla.setHorizontalSpacing(px(12, False))
            rejilla.setVerticalSpacing(px(12, False))
            for i, rot in enumerate(letras):
                if rot:
                    visible = t("Rotación {rot}", rot=rot)
                    html_titulo = glosario.enlace("rotacion", visible.upper(), p["acento"],
                                                  detalle=modos_mision.explicacion_rotacion(modo, rot))
                    panel = self._panel(visible, html_titulo=html_titulo)
                    corta = modos_mision.rotacion_corta(modo, rot)
                    if corta and panel.cabecera is not None:
                        panel.cabecera.addWidget(etiqueta(corta, "pequeno", tinta="suave"))
                else:
                    panel = self._panel(t("Al terminar la misión"))
                panel.capa.addWidget(f.bloque(self._filas_rotacion(premios[rot], rot in self._rotaciones_abiertas,
                                                                   rot)))
                panel.capa.addStretch(1)
                rejilla.addWidget(panel, i // columnas, i % columnas)
            for c in range(columnas):
                rejilla.setColumnStretch(c, 1)
            f.anadir(rejilla)
        else:
            f.anadir(self._panel_html(t("Recompensas"), f"<p style='color:{p['suave']};margin:0'>"
                                      f"{html.escape(t('Este nodo no trae tabla de recompensas en los datos.'))}</p>"))
        f.anadir(self._panel_html(t("Qué hacer"), self._html_que_hacer(modo) + self._pie_mision([n], modo)))
        f.terminar()

    def _paneles_modo(self, modo: str, premios: dict | None) -> None:
        """'Que te dan y cuando': tira de rondas y como van las recompensas."""
        contenido = self._html_que_te_dan(modo, premios)
        if not contenido:
            return
        panel = self._panel(t("Qué te dan y cuándo"), "rotacion")
        celdas = self._celdas_tira(modo)
        if celdas:
            panel.capa.addWidget(TiraRondas(celdas))
        panel.capa.addWidget(self.ficha.bloque(contenido))
        self.ficha.anadir(panel)

    # -- ficha de objeto -----------------------------------------------------------

    def _rotulo_y_titulo(self, item: dict, padre: dict | None) -> tuple[str, str]:
        """Pieza: 'CHASIS' sobre 'CITRINE PRIME'. Lo demas: la categoria sobre el nombre."""
        if padre:
            return nombre_idioma(item), nombre_idioma(padre)
        rotulo = categoria_es(item["categoria"], item.get("tipo"))
        tipo = item.get("tipo") or ""
        if item["categoria"] in CATEGORIAS_ARMA and tipo and tipo != "Componente":
            rotulo += f" · {t(tipo)}"
        return rotulo, nombre_idioma(item)

    def _insignias_item(self, item: dict, detalles_arma: dict | None) -> list[tuple[str, str, str | None]]:
        es_reliquia = item["categoria"] == "Relics"
        tipo = colores_tipo.tipo_de(item)
        salida: list[tuple[str, str, str | None]] = [
            (colores_tipo.nombre(tipo), colores_tipo.color(tipo, PALETA["panel"]),
             "reliquia" if es_reliquia else None)
        ]
        if item.get("tipo") == "Componente":
            salida.append((t("Pieza"), "suave", "pieza"))
        era = era_de(item["nombre_en"]) if es_reliquia else ""
        if era:
            salida.append((t(era), COLOR_ERA.get(era, "acento"), "era"))
        if item["es_prime"]:
            salida.append(("Prime", color_rareza("Rare"), "prime"))
        if item["vaulted"]:
            salida.append((t("En bóveda"), COLOR_BOVEDA, "boveda"))
        elif item["vaulted"] == 0 and es_reliquia:
            salida.append((t("Disponible"), COLOR_DISPONIBLE, "boveda"))
        elif item["vaulted"] == 0 and item["es_prime"]:
            salida.append((t("Se puede farmear"), COLOR_DISPONIBLE, "boveda"))
        if item["ducados"]:
            salida.append((t("{n} ducados", n=item["ducados"]), "suave", "ducados"))
        if detalles_arma and detalles_arma.get("maestria"):
            salida.append((t("Maestría {n}", n=ficha_detalles.numero(detalles_arma["maestria"], 0)), "suave",
                           "maestria"))
        return salida

    def _montar_item(self, datos: dict) -> None:
        f = self.ficha
        self._aparcar()
        f.vaciar()
        self._imagenes_ficha.clear()
        item, padre = datos["item"], datos["padre"]
        pasos = self._pasos_ruta(item["id"])
        # Un set sin fuentes propias ya dice pieza a pieza donde sale ("Donde se consigue"):
        # sin repetirlo arriba. Si ademas cae el solo (un recurso con plano), va su ruta.
        # La columna derecha mide lo que sobra de la ficha tras la izquierda (330).
        ancho_der = f.viewport().width() - (0 if f.estrecha() else px(348, False))
        partes = self._partes_item(datos, con_como=not pasos and (not datos["componentes"] or bool(datos["fuentes"])),
                                   columnas_reliquias=2 if ancho_der >= px(600, False) else 1)
        extra = partes["detalles"]
        arma = (extra.get("_datos") or {}).get("arma")

        estrecha = f.estrecha()

        # -- cabecera: pedestal, nombre, insignias ----------------------------------------
        # En una sola columna (la ventana de 1100x700) la imagen va pequena y al lado del
        # nombre: lo que se busca (como y donde conseguirlo) tiene que verse sin bajar.
        self.pedestal = Pedestal(96 if estrecha else 220)
        self.pedestal.poner_imagen(self._pedir_imagen(item.get("imagen"), px(120 if estrecha else 240, False)))
        alinear = Qt.AlignLeft if estrecha else Qt.AlignHCenter
        nombre = QVBoxLayout()
        nombre.setSpacing(px(4 if estrecha else 10, False))
        rotulo, titulo = self._rotulo_y_titulo(item, padre)
        for pieza in (etiqueta(rotulo, "rotulo", tinta="suave", mayus=True),
                      etiqueta(titulo, "titulo", mayus=True, envolver=True)):
            pieza.setAlignment(alinear)
            nombre.addWidget(pieza)
        otro = item["nombre_en"] if es_castellano() else (item["nombre_es"] or "")
        sub = " · ".join(x for x in (otro if otro and otro != nombre_idioma(item) else "",
                                     t("pieza ×{n}", n=item["item_count"]) if item["item_count"] else "") if x)
        if sub:
            e = etiqueta(sub, "pequeno", envolver=True)
            e.setAlignment(alinear)
            nombre.addWidget(e)
        for html_extra in (partes["pieza_de"], partes["nota"]):
            if html_extra:
                e = etiqueta(html_extra, "pequeno", envolver=True, enlaces=self._enlace)
                e.setAlignment(alinear)
                nombre.addWidget(e)
        insignias = self._insignias_item(item, arma)
        por_linea = 4 if estrecha else 3
        for i in range(0, len(insignias), por_linea):
            linea = QHBoxLayout()
            linea.setSpacing(px(8, False))
            if not estrecha:
                linea.addStretch(1)
            for texto, tinta, clave in insignias[i:i + por_linea]:
                linea.addWidget(InsigniaGlosa(texto, tinta=tinta, clave=clave))
            linea.addStretch(1)
            nombre.addLayout(linea)

        # -- datos propios: descripcion, disposicion, maestria/tienes/mercado ------------
        propios: list = []
        if item["descripcion_es"]:
            propios.append(etiqueta(item["descripcion_es"], "pequeno", envolver=True))
        if arma:
            propios.append(self._panel_disposicion(arma))
        propios.append(self._panel_datos(datos))
        propios = [x for x in propios if x is not None]

        # -- como y donde conseguirlo: lo primero que se busca ------------------------------
        conseguir: list = []
        # El codigo de un glifo es la ficha entera: arriba del todo.
        if extra.get("glifo"):
            conseguir.append(self._panel_html(t("Código de canje"), extra["glifo"]))
        if pasos:
            panel = self._panel(t("Cómo conseguirlo"))
            panel.capa.addWidget(hitos(pasos, self._enlace))
            conseguir.append(panel)
        elif partes["como"]:
            conseguir.append(self._panel_html(t("Cómo conseguirlo"), partes["como"]))
        # Todas las fuentes propias, con su relleno por rapidez, aunque el objeto tambien se
        # fabrique (Celula orokin, Sensores neuronales: plano + misiones). Solo un set sin
        # fuentes propias dice "donde se consigue" pieza a pieza.
        # La tabla de sitios va justo debajo de "Como conseguirlo"; el plano, despues.
        donde_panel: list = []
        # Las misiones primero (lo que se ve sin bajar); la tarjeta de recurso de planeta,
        # que no tiene porcentaje, detras.
        propias = partes["fuentes"] + partes["planeta"]
        donde = propias + partes["sin_fuentes"] if propias or not partes["componentes"] else partes["componentes"]
        if donde:
            donde_panel.append(self._panel_html(t("Dónde se consigue"), donde))
        if partes["reliquias"]:
            donde_panel.append(self._panel_html(t("Reliquias"), partes["reliquias"], "reliquia"))
        if partes["contenido"]:
            donde_panel.append(self._panel_html(t("Contenido en Radiante"), partes["contenido"], "refinamiento"))
        if partes["componentes"] and propias:
            donde_panel.append(self._panel_html(t("Se construye con"), partes["componentes"]))

        # -- estadisticas y lo largo (habilidades, efecto rango a rango), el set y enlaces --
        estadisticas_p: list = []
        if arma:
            estadisticas_p.append(self._panel_estadisticas_arma(arma))
        if extra.get("warframe"):
            estadisticas_p.append(self._panel_html(t("Estadísticas"), extra["warframe"]))
        largo: list = []
        for clave_d, titulo_d in (("habilidades", _g_hab()), ("mod", _g_efecto()), ("arcano", _g_efecto())):
            if extra.get(clave_d):
                largo.append(self._panel_html(titulo_d, extra[clave_d]))
        largo.append(self._panel_set(datos))
        if partes["enlaces"]:
            largo.append(f.bloque(partes["enlaces"]))

        if estrecha:
            cabecera = QHBoxLayout()
            cabecera.setSpacing(px(14, False))
            cabecera.addWidget(self.pedestal, 0, Qt.AlignTop)
            cabecera.addLayout(nombre, 1)
            f.anadir(cabecera)
            # Como y donde, justo debajo del nombre; lo propio y lo largo despues. Si no se
            # sabe de donde sale (la Hek: "Plano · Sin fuentes registradas"), ese panel no
            # dice nada util y van antes los datos propios (disposicion, estadisticas...).
            if self._tiene_fuentes(datos, partes):
                orden = conseguir + donde_panel + propios + estadisticas_p + largo
            else:
                orden = conseguir + propios + estadisticas_p + donde_panel + largo
            for pieza in orden:
                f.anadir(pieza)
        else:
            izq = QVBoxLayout()
            izq.setSpacing(px(10, False))
            izq.addWidget(self.pedestal, 0, Qt.AlignHCenter)
            izq.addLayout(nombre)
            for pieza in propios:
                izq.addWidget(pieza)
            # Orden: lo que se busca primero arriba, luego como y donde conseguirlo, y lo
            # largo (habilidades, efecto rango a rango) al final.
            der = QVBoxLayout()
            der.setSpacing(px(12, False))
            for pieza in conseguir + estadisticas_p + donde_panel + largo:
                if pieza is not None:
                    der.addWidget(pieza)
            columnas = QHBoxLayout()
            columnas.setSpacing(px(18, False))
            envoltura = transparente(QWidget())
            envoltura.setFixedWidth(px(330, False))
            izq.setContentsMargins(0, 0, 0, 0)
            izq.addStretch(1)
            envoltura.setLayout(izq)
            columnas.addWidget(envoltura, 0)
            der.addStretch(1)
            columnas.addLayout(der, 1)
            f.anadir(columnas)
        f.terminar()

    def _tiene_fuentes(self, datos: dict, partes: dict) -> bool:
        """Si se sabe de donde sale el objeto o alguna de sus piezas (misiones, reliquias...)."""
        if partes["fuentes"] or partes["planeta"] or partes["reliquias"] or partes["contenido"] or partes["como"]:
            return True
        ids = [c["id"] for c in datos["componentes"]]
        if not ids or self.con is None:
            return False
        marcas = ",".join("?" * len(ids))
        return self.con.execute(f"SELECT 1 FROM fuentes WHERE item_id IN ({marcas}) LIMIT 1", ids).fetchone() is not None

    def _panel_disposicion(self, arma: dict) -> PanelC | None:
        try:
            n = int(round(float(arma.get("disposicion") or 0)))
        except (TypeError, ValueError):
            return None
        if not 1 <= n <= 5:
            return None
        panel = self._panel(t("Disposición de agrietado"), "disposicion")
        rombos = RombosDisposicion(n)
        rombos.setToolTip(glosario.texto("disposicion"))
        exacta = etiqueta(f"×{ficha_detalles.numero(arma['riven'], 2)}" if arma.get("riven") else "", "seccion")
        boton = BotonC(t("Precios"))
        boton.setToolTip(t("Lo que piden por sus agrietados: abre la herramienta Agrietados con esta arma."))
        boton.clicked.connect(self._ver_agrietados)
        panel.capa.addLayout(fila(rombos, exacta, None, boton, espacio=px(14, False)))
        if n <= 2:
            nota = t("Cuantos más rombos, más fuertes salen sus agrietados. Este sale flojo: es de las más usadas.")
        elif n == 3:
            nota = t("Cuantos más rombos, más fuertes salen sus agrietados. Este va en la media.")
        else:
            nota = t("Cuantos más rombos, más fuertes salen sus agrietados. Este sale fuerte: casi nadie la usa.")
        panel.capa.addWidget(etiqueta(nota, "pequeno", envolver=True))
        return panel

    def _panel_datos(self, datos: dict) -> PanelC | None:
        """Maestria, lo que tienes y el mercado: lo que es tuyo o cambia cada dia."""
        item = datos["item"]
        pares: list[tuple[str, object]] = []
        estado = self._estado_maestria(item["id"])
        texto = texto_maestria(estado) if estado is not None else None
        if texto:
            fondo, color = colores_maestria(estado)
            valor = etiqueta(texto, "fuerte")
            valor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            valor.setStyleSheet(f"color: {PALETA['acento'] if estado.estado == SIN_TOCAR else color};")
            glosario.aplicar(valor, "dominado")
            pares.append((t("Maestría"), valor))
        tienes = self._texto_tienes(datos)
        if tienes:
            pares.append((t("Tienes"), tienes))
        if self._slug_actual:
            self.precios.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            pares.append((t("Mercado"), self.precios))
            self.precios.show()
        if not pares:
            return None
        panel = PanelC()
        panel.capa.addWidget(filas_datos(pares, self._enlace))
        return panel

    def _texto_tienes(self, datos: dict) -> str:
        """'Tienes 3' o, en un set, '2 de 4 piezas', si el inventario se ha leido."""
        if self.usuario is None:
            return ""
        componentes = datos["componentes"]
        if componentes:
            lecturas = [(c, estado_inventario.cantidad_de(self.usuario, c["unique_name"])) for c in componentes]
            leidas = [(c, x) for c, x in lecturas if x is not None]
            if leidas:
                cubiertas = sum(1 for c, x in leidas if x.cantidad >= (c["item_count"] or 1))
                return t("{n} de {total} piezas", n=cubiertas, total=len(componentes))
        lectura = estado_inventario.cantidad_de(self.usuario, datos["item"]["unique_name"])
        if lectura is None:
            return ""
        return t("Tienes {n}", n=lectura.cantidad)

    def _panel_estadisticas_arma(self, arma: dict) -> PanelC:
        panel = self._panel(t("Estadísticas"))
        filas = ficha_detalles.estadisticas_arma(arma)
        panel.capa.addWidget(estadisticas(filas, 1 if self.ficha.estrecha() and len(filas) > 4 else 2))
        dano = ficha_detalles.dano_arma(arma)
        if arma.get("dano_total") or dano:
            total = arma.get("dano_total") or sum(v for _c, _n, v, _col in dano)
            rotulo = etiqueta(t("Daño {n}", n=ficha_detalles.numero(total)), "rotulo", mayus=True)
            linea = QHBoxLayout()
            linea.setSpacing(px(12, False))
            linea.addWidget(rotulo)
            if dano:
                linea.addWidget(BarraDano([(v, col) for _c, _n, v, col in dano]), 1)
            panel.capa.addLayout(linea)
            if dano:
                leyenda = " &nbsp; ".join(
                    f"<span style='color:{col}'>◆</span> {html.escape(nombre)} {ficha_detalles.numero(v)}"
                    for _c, nombre, v, col in dano
                )
                panel.capa.addWidget(etiqueta(leyenda, "pequeno", envolver=True))
        return panel

    def _panel_set(self, datos: dict) -> PanelC | None:
        """Las piezas del set de una pieza, con la que se ve marcada: se salta de una a otra."""
        padre = datos["padre"]
        if not padre or self.con is None:
            return None
        del_padre = items.ficha(self.con, padre["id"])
        piezas = (del_padre or {}).get("componentes") or []
        if len(piezas) < 2:
            return None
        panel = self._panel(t("El set"))
        rejilla = QGridLayout()
        rejilla.setSpacing(px(10, False))
        # En una ficha estrecha, de dos en dos: cuatro casillas en fila ensanchaban la ficha.
        por_fila = 2 if self.ficha.estrecha() else max(4, len(piezas))
        actual = datos["item"]["id"]
        for i, c in enumerate(piezas):
            progreso = 0.0
            if self.usuario is not None:
                lectura = estado_inventario.cantidad_de(self.usuario, c["unique_name"])
                if lectura is not None:
                    progreso = min(1.0, lectura.cantidad / (c["item_count"] or 1))
            casilla = CasillaC(nombre_idioma(c), t("tú estás aquí") if c["id"] == actual else "", progreso,
                               marcada=c["id"] == actual, lado_imagen=46)
            casilla.nombre.setProperty("fuenteC", nombre_idioma(c))
            casilla.poner_imagen(self._pedir_imagen(c.get("imagen"), px(46, False)))
            casilla.setMinimumWidth(px(84, False))
            casilla.pulsado.connect(lambda item_id=c["id"]: self.abrir(item_id))
            rejilla.addWidget(casilla, i // por_fila, i % por_fila)
        for columna_n in range(min(por_fila, len(piezas))):
            rejilla.setColumnStretch(columna_n, 1)
        panel.capa.addLayout(rejilla)
        return panel

    def _pasos_ruta(self, item_id: int) -> list[tuple[str, str]] | None:
        """'Como conseguirlo' en pasos: consigue la reliquia, abrela en una fisura, elige.

        None si el objeto no tiene una ruta clara (la ficha pone entonces lo de siempre).
        """
        if self.con is None:
            return None
        p = PALETA
        refinamiento, escuadra = ruta_prime.preferencias()
        ruta = ruta_prime.ruta_pieza(self.con, item_id, refinamiento, escuadra)
        if ruta is not None:
            reliquia = ruta["reliquia"]
            m = ruta["mision"]
            reliquias = (m["reliquias"][:3] if m else None) or [reliquia]
            nombres = f" {html.escape(t('o'))} ".join(_enlace_reliquia(r, p["texto"]) for r in reliquias)
            era = era_de(reliquia.get("nombre_en")) or ""
            prob = reliquias[0].get("probabilidad")
            modo_txt = pestana_primes.texto_modo(refinamiento, escuadra)
            ref_txt = glosario.enlace("refinamiento", pestana_primes.texto_refinamiento(refinamiento), p["suave"])
            if ruta["solo_en_boveda"]:
                paso1 = (t("Consigue la reliquia {reliquia}", reliquia=nombres),
                         glosario.enlace("boveda", t("En bóveda: solo por intercambio, Baro Ki'Teer o Prime Resurgence"),
                                         COLOR_BOVEDA))
            elif m:
                sitio = " &middot; ".join(x for x in (
                    enlaces_wiki.donde(m, p["suave"]),
                    glosario.enlace_mision(m.get("modo"), m["mision"], p["suave"], m.get("rotacion"))
                    if m.get("mision") else "",
                    _rotacion_prime(m, p["suave"]),
                    f"{m['probabilidad']:.1f}%" if m.get("probabilidad") else "",
                ) if x)
                tiempo = eficiencia.texto_minutos(m.get("minutos_reliquia"))
                paso1 = (t("Consigue la reliquia {reliquia}", reliquia=nombres),
                         sitio + (f" &middot; {html.escape(t('unos {tiempo}', tiempo=tiempo))}" if tiempo else ""))
            else:
                paso1 = (t("Consigue la reliquia {reliquia}", reliquia=nombres),
                         html.escape(t("Ninguna de sus reliquias cae en una misión que se pueda estimar.")))
            fisura = glosario.enlace("fisura", t("fisura {era}", era=era) if era else t("fisura"), p["texto"])
            detalle2 = (html.escape(t("Refinada a {refinamiento}: {prob}% de que salga", refinamiento="@@R@@",
                                      prob=f"{prob:.1f}")).replace("@@R@@", ref_txt)
                        if prob else ref_txt)
            paso2 = (t("Ábrela en una {fisura}", fisura=fisura), detalle2)
            if m and ruta.get("minutos"):
                clave_modo = "radshare" if escuadra > 1 else "refinamiento"
                tiempo_total = glosario.enlace(
                    "tiempo_pieza", eficiencia.texto_minutos(ruta["minutos"]), p["texto"], True,
                    desglose_tiempo.texto_prime(m, escuadra, modo_txt))
                detalle3 = (f"{tiempo_total} {html.escape(t('hasta tener la pieza'))} &middot; "
                            + glosario.enlace(clave_modo, modo_txt, p["suave"]))
            else:
                detalle3 = ""
            return [paso1, paso2, (t("Elige la pieza al acabar"), detalle3)]
        ruta = relaciones.mejor_ruta(self.con, item_id)
        if not ruta or ruta.get("tipo") == "reliquia" or not ruta.get("mision"):
            return None
        m = ruta["mision"]
        sitio = enlaces_wiki.donde(m, p["texto"])
        if not sitio:
            return None
        trozos = [x for x in (
            glosario.enlace_mision(m.get("modo"), m["mision"], p["suave"], m.get("rotacion")) if m.get("mision") else "",
            _rotacion(self.con, m.get("rotacion"), p["suave"], m.get("modo")),
            glosario.enlace("rareza", _glosa(self.con, "rareza", m["rareza"]), color_rareza(m["rareza"]))
            if m.get("rareza") else "",
        ) if x]
        if m.get("recurso_planeta"):
            trozos.append(html.escape(t("Jefe: suelta un recurso del planeta al morir")))
        prob = ruta.get("probabilidad")
        tiempo = _tiempo(ruta.get("minutos_medios"), p["texto"], negrita=True, fila=m)
        detalle2 = " &middot; ".join(x for x in (
            html.escape(t("{prob}% cada vez", prob=f"{prob:.1f}")) if prob else "",
            (tiempo + " " + html.escape(t("de media"))) if tiempo else "",
        ) if x)
        return [(t("Ve a {sitio}", sitio=f"<b>{sitio}</b>"), " &middot; ".join(trozos)),
                (t("Juega hasta que caiga"), detalle2)]

    def _partes_item(self, datos: dict, con_como: bool = True, columnas_reliquias: int = 2) -> dict:
        """Los trozos de la ficha de un objeto, en HTML y por separado (ver `_html`)."""
        con = self.con
        p = PALETA
        item, padre = datos["item"], datos["padre"]
        partes: dict = {}
        partes["nota"] = self._html_nota_novedad()
        partes["pieza_de"] = (
            f"{html.escape(t('Pieza de'))} <a style='color:{p['acento']};text-decoration:none' "
            f"href='item:{padre['id']}'>{html.escape(nombre_idioma(padre))}</a>"
            if padre else ""
        )
        partes["como"] = self._bloque_ruta(item["id"]) if con_como else ""
        partes["detalles"] = ficha_detalles.bloques(con, item)
        partes["componentes"] = self._bloque_componentes(datos)
        if datos["componentes"]:
            partes["reliquias"] = self._bloque_reliquias_set(datos, columnas_reliquias)
        else:
            partes["reliquias"] = self._bloque_reliquias(item["id"], titulo=False)
        partes["contenido"] = self._bloque_contenido(item["id"], titulo=False) if item["categoria"] == "Relics" else ""
        partes["planeta"] = self._bloque_planeta(item["id"])
        partes["fuentes"] = self._bloque_fuentes(item["id"])
        es_reliquia = item["categoria"] == "Relics"
        partes["sin_fuentes"] = ""
        if es_reliquia and not datos["fuentes"]:
            # Una reliquia sin mision no "puede venir de una mision de historia": esta en
            # boveda (o acaba de salir de ella) y se compra a otro jugador. Lo mismo que
            # dicen la vista compacta y Objetivos de esa misma reliquia.
            texto = t("No cae en ninguna misión activa")
            if item["vaulted"]:
                texto += ". " + t("Hay que comprarla a otro jugador.")
            partes["sin_fuentes"] = (
                f"<p>{glosario.enlace('boveda', texto, COLOR_BOVEDA if item['vaulted'] else p['suave'])}</p>"
            )
        elif not datos["fuentes"] and not datos["componentes"]:
            partes["sin_fuentes"] = (
                f"<p style='color:{p['suave']}'>"
                + html.escape(t("Sin fuentes registradas: puede venir de una misión de historia, "
                                "del mercado, de un evento o de un sindicato."))
                + "</p>"
            )
        enlaces = []
        # Las reliquias no traen wiki_url, pero su pagina se llama como ellas (Lith S19).
        url_wiki = enlaces_wiki.url_item(item)
        if url_wiki:
            enlaces.append(f"<a style='color:{p['acento']};text-decoration:none' href='{html.escape(url_wiki)}'>"
                           f"{html.escape(t('Abrir en la wiki'))} &rarr;</a>")
        # Builds de la comunidad (warframes, armas, companeros): se abren en la pestana Web.
        if builds_overframe.nombre_con_builds(item, datos.get("padre")):
            enlaces.append(f"<a style='color:{p['acento']};text-decoration:none' href='overframe:'>"
                           f"{html.escape(t('Builds en Overframe'))} &rarr;</a>")
        partes["enlaces"] = f"<p style='margin:0'>{' &nbsp;&nbsp; '.join(enlaces)}</p>" if enlaces else ""
        return partes

    def _cabecera_html(self, datos: dict) -> str:
        """Cabecera de la ficha en HTML (solo para `_html`: en pantalla va en piezas C)."""
        p = PALETA
        item, padre = datos["item"], datos["padre"]
        nombre = html.escape(nombre_idioma(item))
        if padre:
            nombre = _con_padre(nombre, f"<span style='color:{p['suave']}'>{html.escape(nombre_idioma(padre))}</span>")
        otro_nombre = item["nombre_en"] if es_castellano() else (item["nombre_es"] or "")
        etiquetas = []
        for texto, tinta, clave in self._insignias_item(item, None):
            color = PALETA.get(tinta, tinta)
            etiquetas.append(_etiqueta(texto, p["panel"], color, clave))
        maestria = self._etiqueta_maestria(item["id"])
        if maestria:
            etiquetas.append(maestria)
        tienes = self._etiqueta_inventario(item["unique_name"])
        if tienes:
            etiquetas.append(tienes)
        return (
            f"<div style='font-size:22px;font-weight:bold'>{nombre}</div>"
            f"<div style='color:{p['suave']};font-size:13px;margin-top:2px'>{html.escape(otro_nombre)}"
            + (" &middot; " + html.escape(t("pieza ×{n}", n=item["item_count"])) if item["item_count"] else "")
            + f"</div><div style='margin-top:6px'>{' '.join(etiquetas)}</div>"
        )

    def _html(self, datos: dict) -> str:
        """La ficha de un objeto entera en un solo HTML, con los mismos trozos que los paneles."""
        p = PALETA
        partes = self._partes_item(datos)
        item = datos["item"]
        salida = [self._cabecera_html(datos), partes["nota"]]
        if partes["pieza_de"]:
            salida.append(f"<div style='color:{p['suave']};margin-top:4px'>{partes['pieza_de']}</div>")
        if item["descripcion_es"]:
            salida.append(f"<p style='color:{p['suave']};margin-top:8px'>{html.escape(item['descripcion_es'])}</p>")
        salida.append(partes["como"])
        salida.append(ficha_detalles.html_detalles(self.con, item))
        if partes["componentes"]:
            salida.append(_seccion(t("Dónde se consigue")) + partes["componentes"])
        if partes["reliquias"]:
            salida.append(_seccion(t("Reliquias"), "reliquia") + partes["reliquias"])
        if partes["contenido"]:
            salida.append(_seccion(t("Contenido en Radiante"), "refinamiento") + partes["contenido"])
        salida += [partes["planeta"], partes["fuentes"], partes["sin_fuentes"], partes["enlaces"]]
        return "".join(salida)

    def _bloque_componentes(self, datos: dict) -> str:
        """'Donde se consigue' de un set: cada pieza con su mejor reliquia o sitio y su tiempo."""
        componentes = datos["componentes"]
        if not componentes or self.con is None:
            return ""
        p = PALETA
        refinamiento, escuadra = ruta_prime.preferencias()
        filas = []
        for c in componentes:
            ruta_p = ruta_prime.ruta_pieza(self.con, c["id"], refinamiento, escuadra)
            imagen = ""
            if c.get("imagen"):
                ruta_img = imagenes().ruta(c["imagen"])
                if ruta_img.exists():
                    imagen = f"<img src='{ruta_img.as_uri()}' width='26' height='26'>"
                else:
                    self._pedir_imagen(c["imagen"], 26)
            nombre = (f"<a style='color:{p['texto']};text-decoration:none' href='item:{c['id']}'>"
                      f"<b>{html.escape(nombre_idioma(c))}</b></a>"
                      + (f" <span style='color:{p['suave']}'>&times;{c['item_count']}</span>" if c["item_count"] else "")
                      + self._tienes_componente(c))
            donde, tiempo = "", ""
            if ruta_p is not None:
                rel = ruta_p["reliquia"]
                era = era_de(rel.get("nombre_en"))
                rombo = f"<span style='color:{COLOR_ERA.get(era, p['acento'])}'>◆</span> "
                enlace_rel = _enlace_reliquia(rel, COLOR_ERA.get(era, p["texto"]))
                m = ruta_p["mision"]
                if ruta_p["solo_en_boveda"]:
                    donde = rombo + enlace_rel + " " + glosario.enlace(
                        "boveda", t("Solo en bóveda: intercambio o Baro"), COLOR_BOVEDA)
                elif m:
                    sitio = " ".join(x for x in (
                        glosario.enlace_mision(m.get("modo"), m["mision"], p["suave"], m.get("rotacion"))
                        if m.get("mision") else "",
                        html.escape(t("en")) if m.get("mision") else "",
                        enlaces_wiki.donde(m, p["suave"]),
                    ) if x)
                    donde = f"{rombo}{enlace_rel} <span style='color:{p['suave']}'>{sitio}</span>"
                    tiempo = glosario.enlace("tiempo_pieza", eficiencia.texto_minutos(ruta_p["minutos"]),
                                             p["acento"], True, desglose_tiempo.texto_prime(
                                                 m, escuadra, pestana_primes.texto_modo(refinamiento, escuadra)))
                else:
                    donde = rombo + enlace_rel
            else:
                ruta = relaciones.mejor_ruta(self.con, c["id"])
                m = (ruta or {}).get("mision")
                if m:
                    donde = " &middot; ".join(x for x in (
                        enlaces_wiki.donde(m, p["texto"]),
                        glosario.enlace_mision(m.get("modo"), m["mision"], p["suave"], m.get("rotacion"))
                        if m.get("mision") else "",
                        _rotacion(self.con, m.get("rotacion"), p["suave"], m.get("modo")),
                    ) if x)
                    tiempo = _tiempo(ruta.get("minutos_medios"), p["acento"], negrita=True, fila=m)
                elif ruta and ruta.get("reliquia"):
                    donde = _enlace_reliquia(ruta["reliquia"], p["texto"])
                else:
                    donde = f"<span style='color:{p['suave']}'>{html.escape(t('Sin fuentes registradas'))}</span>"
            filas.append(
                f"<tr><td width='30'>{imagen}</td><td>{nombre}</td><td>{donde}</td>"
                f"<td align='right'>{tiempo}</td></tr>"
            )
        return "<table width='100%' cellspacing='0' cellpadding='5'>" + "".join(filas) + "</table>"

    def _bloque_reliquias_set(self, datos: dict, columnas: int = 2) -> str:
        """Las reliquias de todas las piezas de un set, en dos columnas compactas."""
        p = PALETA
        incluir = not self.ocultar_vaulted.isChecked()
        filas = []
        for c in datos["componentes"]:
            for r in relaciones.reliquias_de(self.con, c["id"], incluir_vaulted=incluir):
                filas.append((r, c))
        if not filas:
            return ""
        filas.sort(key=lambda x: (bool(x[0]["vaulted"]), -(x[0]["probabilidades"].get("Radiant") or 0)))
        visibles = filas[:MAX_RELIQUIAS_SET]
        celdas = []
        for r, c in visibles:
            era = era_de(r.get("nombre_en"))
            color = COLOR_ERA.get(era, p["acento"])
            if r["vaulted"]:
                estado = glosario.enlace("boveda", t("en bóveda").upper(), COLOR_BOVEDA)
            else:
                prob = r["probabilidades"].get("Radiant")
                estado = (glosario.enlace("refinamiento", t("{prob}% en Radiante", prob=f"{prob:.0f}"), p["suave"])
                          if prob is not None else "")
            celdas.append(
                f"<td><span style='color:{color}'>◆</span> {_enlace_reliquia(r, color)} "
                f"<span style='color:{p['suave']}'>{html.escape(nombre_idioma(c))}</span></td>"
                f"<td align='right'>{estado}</td>"
            )
        filas_html = []
        if columnas < 2:
            filas_html = [f"<tr>{celda}</tr>" for celda in celdas]
        else:
            mitad = (len(celdas) + 1) // 2
            for i in range(mitad):
                derecha = celdas[i + mitad] if i + mitad < len(celdas) else "<td></td><td></td>"
                filas_html.append(f"<tr>{celdas[i]}<td width='18'></td>{derecha}</tr>")
        salida = "<table width='100%' cellspacing='0' cellpadding='3'>" + "".join(filas_html) + "</table>"
        resto = filas[MAX_RELIQUIAS_SET:]
        if resto:
            en_boveda = sum(1 for r, _c in resto if r["vaulted"])
            salida += (f"<div style='color:{p['suave']};margin-top:4px'>"
                       + html.escape(t("y {n} reliquias más ({boveda} en bóveda)", n=len(resto), boveda=en_boveda))
                       + "</div>")
        return salida

    def _bloque_ruta(self, item_id: int) -> str:
        # Pieza prime (o el prime entero): reliquia, mision y tiempo hasta la pieza.
        prime = pestana_primes.bloque_ficha(self.con, item_id)
        if prime is not None:
            return prime
        ruta = relaciones.mejor_ruta(self.con, item_id)
        if not ruta:
            return ""
        p = PALETA
        reliquia = ruta["reliquia"]
        if ruta.get("tipo") != "reliquia" or not reliquia:
            return self._tarjeta_ruta_directa(ruta)
        nombre = nombre_idioma(reliquia)
        prob = reliquia["probabilidades"].get("Radiant") or max(
            list(reliquia["probabilidades"].values()) or [0]
        )
        radiante = glosario.enlace("refinamiento", t("{prob}% en Radiante", prob=f"{prob:.1f}"), p["suave"])
        cuerpo = [
            f"<div style='color:{p['acento']};font-size:12px;font-weight:bold'>"
            f"{html.escape(t('Por dónde empezar')).upper()}</div>",
            f"<div style='font-size:16px;margin-top:2px'><a style='color:{p['texto']};"
            f"text-decoration:none' href='item:{reliquia['reliquia_id']}'><b>{html.escape(nombre)}</b></a>"
            f" <span style='color:{p['suave']}'>&middot; {radiante}</span></div>",
        ]
        if ruta["solo_en_boveda"]:
            cuerpo.append(
                "<div style='margin-top:2px'>"
                + glosario.enlace("boveda", t("Solo en bóveda: hay que comprarla a otro jugador"), COLOR_BOVEDA)
                + "</div>"
            )
            color = COLOR_BOVEDA
        else:
            color = p["acento"]
            if ruta["mision"]:
                m = ruta["mision"]
                detalle = " &middot; ".join(
                    x
                    for x in (
                        enlaces_wiki.donde(m, p["texto"]),
                        glosario.enlace_mision(m.get("modo"), m["mision"], p["texto"], m["rotacion"])
                        if m["mision"] else "",
                        _rotacion(self.con, m["rotacion"], p["texto"], m.get("modo")),
                        f"{m['probabilidad']:.1f}%" if m["probabilidad"] else "",
                        _tiempo(m.get("minutos_medios"), p["texto"], fila=m),
                    )
                    if x
                )
                cuerpo.append(f"<div style='color:{p['suave']};margin-top:2px'>"
                              f"{html.escape(t('Farmea la reliquia en'))} "
                              f"<span style='color:{p['texto']}'>{detalle}</span></div>")
        return _tarjeta("".join(cuerpo), color)

    def _tarjeta_ruta_directa(self, ruta: dict) -> str:
        """Lo que no sale de reliquias (Rhino, un mod): el mejor sitio, sin mas vueltas."""
        p = PALETA
        m = ruta["mision"]
        if not m:
            return ""
        trozos = [f"<b>{enlaces_wiki.donde(m, p['texto'])}</b>"]
        if m.get("mision"):
            trozos.append(glosario.enlace_mision(m.get("modo"), m["mision"], p["texto"], m.get("rotacion")))
        if m.get("rotacion"):
            trozos.append(_rotacion(self.con, m["rotacion"], p["suave"], m.get("modo")))
        if m.get("rareza"):
            trozos.append(glosario.enlace("rareza", _glosa(self.con, "rareza", m["rareza"]), color_rareza(m["rareza"])))
        prob = ruta.get("probabilidad")
        if prob:
            trozos.append(f"<b>{prob:.1f}%</b>")
        if ruta.get("minutos_medios") is not None:
            trozos.append(_tiempo(ruta["minutos_medios"], p["texto"], negrita=True, fila=m))
        tipo = _glosa(self.con, "tipo_fuente", ruta.get("tipo"))
        if m.get("recurso_planeta"):
            tipo = t("Jefe: suelta un recurso del planeta al morir")
        cuerpo = [
            f"<div style='color:{p['acento']};font-size:12px;font-weight:bold'>"
            f"{html.escape(t('Por dónde empezar')).upper()}</div>",
            f"<div style='font-size:16px;margin-top:2px'>{' &middot; '.join(trozos)}</div>",
        ]
        if tipo:
            cuerpo.append(f"<div style='color:{p['suave']};margin-top:2px'>{html.escape(tipo)}</div>")
        return _tarjeta("".join(cuerpo), p["acento"])

    def _bloque_reliquias(self, item_id: int, titulo: bool = True) -> str:
        reliquias = relaciones.reliquias_de(
            self.con, item_id, incluir_vaulted=not self.ocultar_vaulted.isChecked()
        )
        if not reliquias:
            return ""
        p = PALETA
        # Con objetos muy comunes (Forma sale en 380 reliquias) pedir las misiones
        # de todas cuesta segundos. Se detallan las mejores y el resto se resume.
        detalladas = reliquias[:MAX_RELIQUIAS_DETALLADAS]
        resto = reliquias[MAX_RELIQUIAS_DETALLADAS:]
        tarjetas = []
        for r in detalladas:
            era = era_de(r.get("nombre_en"))
            nombre = html.escape(nombre_idioma(r))
            color = COLOR_BOVEDA if r["vaulted"] else COLOR_DISPONIBLE
            # Espacio duro: en la columna estrecha "en" y "bóveda" se partian en dos lineas.
            estado = (t("en bóveda") if r["vaulted"] else t("disponible")).replace(" ", " ")
            probs = " &nbsp; ".join(
                glosario.enlace("refinamiento", _glosa(self.con, "refinamiento", ref)[:3], p["suave"])
                # &nbsp;: la abreviatura y su cifra no se separan al partir la linea.
                + f"&nbsp;<b>{r['probabilidades'][ref]:.1f}%</b>"
                for ref in REFINAMIENTOS
                if ref in r["probabilidades"]
            )
            misiones_r = relaciones.misiones_de(self.con, r["reliquia_id"])[:3]
            donde = "".join(
                f"<div style='color:{p['suave']}'>{enlaces_wiki.donde(m, p['suave'])}"
                + (f" &middot; {glosario.enlace_mision(m.get('modo'), m['mision'], p['suave'], m['rotacion'])}"
                   if m["mision"] else "")
                + (f" &middot; {_rotacion(self.con, m['rotacion'], p['suave'], m.get('modo'))}" if m["rotacion"] else "")
                + (f" &middot; {m['probabilidad']:.1f}%" if m["probabilidad"] else "")
                + (f" &middot; {_tiempo(m['minutos_medios'], p['suave'], fila=m)}" if m["minutos_medios"] is not None else "")
                + "</div>"
                for m in misiones_r
            ) or f"<div style='color:{p['suave']}'>{html.escape(t('No cae en ninguna misión activa'))}</div>"
            cuerpo = (
                "<table cellpadding='0' cellspacing='0' width='100%'><tr>"
                f"<td><span style='color:{COLOR_ERA.get(era, p['acento'])}'>◆</span> "
                f"<a style='color:{p['texto']};text-decoration:none' "
                f"href='item:{r['reliquia_id']}'><b style='font-size:15px'>{nombre}</b></a>"
                f" &nbsp;<span style='font-size:12px'>{glosario.enlace('boveda', estado, color)}"
                # Su pagina en la wiki, discreta y del color del texto secundario.
                f" &middot; {enlaces_wiki.enlace(enlaces_wiki.url_reliquia(r.get('nombre_en')), html.escape(t('wiki')) + ' &rarr;', p['suave'])}"
                "</span></td>"
                f"<td align='right'>{probs}</td></tr></table>{donde}"
            )
            tarjetas.append(_tarjeta(cuerpo, color))
        if resto:
            disponibles = sum(1 for r in resto if not r["vaulted"])
            tarjetas.append(
                f"<div style='color:{p['suave']};margin:4px 0 8px 4px'>"
                + html.escape(t("y {n} reliquias más ({disponibles} fuera de bóveda), todas con "
                                "probabilidades más bajas", n=len(resto), disponibles=disponibles))
                + "</div>"
            )
        cabecera = _seccion(t("Reliquias"), "reliquia") if titulo else ""
        return cabecera + "".join(tarjetas)

    def _bloque_contenido(self, reliquia_id: int, titulo: bool = True) -> str:
        contenido = relaciones.contenido_de(self.con, reliquia_id, "Radiant")
        if not contenido:
            return ""
        p = PALETA
        filas = []
        for c in contenido:
            etiqueta_c = _con_padre(nombre_idioma(c), nombre_idioma(c, "padre"))
            color = color_rareza(c["rareza"])
            filas.append(
                f"<tr><td width='6' style='background:{color}'></td>"
                f"<td><a style='color:{p['texto']};text-decoration:none' "
                f"href='item:{c['item_id']}'>{html.escape(etiqueta_c)}</a></td>"
                f"<td>{glosario.enlace('rareza', _glosa(self.con, 'rareza', c['rareza']), color)}</td>"
                f"<td align='right'><b>{c['probabilidad']:.1f}%</b></td></tr>"
            )
        cabecera = _seccion(t("Contenido en Radiante"), "refinamiento") if titulo else ""
        return cabecera + _envolver(filas)

    def _bloque_fuentes(self, item_id: int) -> str:
        """Todas las fuentes, por tipo (misiones, contratos, enemigos...), con su nota de tiempos."""
        con = self.con
        p = PALETA
        agrupadas: dict[str, list[dict]] = {}
        for f in relaciones.fuentes_de(con, item_id):
            # Un jefe de asesinato (f["jefe"]) tiene nodo y modo como cualquier mision: si
            # se queda en "enemigos" (la tabla de los que sueltan por muerte, sin sitio fijo)
            # desaparece de la lista de Misiones aunque "Como conseguirlo" lo recomiende el
            # primero, porque su tiempo es mejor que el de las misiones normales. Se agrupa
            # con las misiones para que salga siempre en su misma seccion, por tiempo.
            clave_grupo = "mision" if f.get("jefe") else f["tipo"]
            agrupadas.setdefault(clave_grupo, []).append(f)
        hay_estimacion = False
        # Una sola escala para toda la ficha: el mismo tiempo se rellena igual en
        # Misiones que en Contratos, y las secciones se comparan entre si.
        referencia = relleno_filas.escala(
            f["minutos_medios"]
            for tipo in ORDEN_TIPOS
            for f in _filas_visibles(agrupadas.get(tipo) or [])
        )
        partes = []
        for tipo in ORDEN_TIPOS:
            grupo = agrupadas.get(tipo)
            if grupo:
                partes.append(_seccion(_glosa(con, "tipo_fuente", tipo), primero=not partes))
                partes.append(self._tabla_fuentes(grupo, referencia))
                hay_estimacion = hay_estimacion or any(f["minutos_medios"] is not None for f in grupo)
        if hay_estimacion:
            partes.append(
                f"<div style='color:{p['suave']};font-size:12px;margin:2px 0 0 4px'>"
                + html.escape(t("Los tiempos son una estimación para un jugador medio: lo que suele "
                                "durar la misión dividido por la probabilidad. Los enemigos comunes "
                                "(probabilidad por muerte), los sindicatos y las incursiones no se "
                                "pueden estimar así."))
                + "</div>"
            )
        return "".join(partes)

    def _tabla_fuentes(self, grupo: list[dict], referencia: tuple[float, float] | None = None) -> str:
        p = PALETA
        filas = []
        # Cada modo de Conclave es una fila con un 0,2 %: ocho filas iguales que
        # tapaban lo farmeable. Van juntas en una sola linea al final.
        pvp = [f for f in grupo if f.get("motivo") == "pvp"]
        sobran = max(0, sum(1 for f in grupo if f.get("motivo") != "pvp") - MAX_FILAS_POR_TIPO)
        visibles = _filas_visibles(grupo)
        if referencia is None:
            referencia = relleno_filas.escala(f.get("minutos_medios") for f in visibles)
        for f in visibles:
            # El tipo de mision es un enlace del glosario: al pasar el raton dice que se
            # hace en ella y como van sus recompensas (modos_mision).
            modo = f.get("modo") or f.get("mision_en")
            if f.get("jefe"):
                # "Alad V (Temisto, Jupiter) - Asesinato": el nodo lo pone relaciones.
                donde = html.escape(f["donde"]) + (
                    " - " + glosario.enlace_mision(modo, f["mision"], p["texto"], f["rotacion"])
                    if f.get("mision") else ""
                )
            elif f["nodo_en"]:
                planeta = nombre_idioma(f, "planeta")
                mision = _glosa(self.con, "mision", f["mision_en"])
                # El nodo enlaza a su pagina de la wiki, con el mismo color que ya tenia.
                nodo = nombre_idioma(f, "nodo")
                donde = enlaces_wiki.enlace(enlaces_wiki.url_nodo(f["nodo_en"]), html.escape(nodo), p["texto"])
                if planeta:
                    donde += html.escape(f", {planeta}")
                if mision:
                    donde += " - " + glosario.enlace_mision(modo, mision, p["texto"], f["rotacion"])
            else:
                # Sin nodo (Railjack, Arbitraje, Tormenta del Vacio): el modo, si se sabe,
                # sirve al menos para explicar la rotacion.
                modo = modo or modos_mision.modo_de_origen(f["origen_texto"])
                donde = html.escape(nombre_bonito(self.con, f["origen_texto"]))
            extra = []
            if f.get("recurso_planeta"):
                extra.append(html.escape(t("recurso del planeta")))
            if f["rotacion"]:
                extra.append(_rotacion(self.con, f["rotacion"], p["suave"], modo))
            if f["etapa"]:
                extra.append(html.escape(etapa_bonita(f["etapa"])))
            if f["standing"]:
                extra.append(glosario.enlace(
                    "reputacion", t("{standing} de reputación", standing=f["standing"]), p["suave"]
                ))
            if f["probabilidad_enemigo"]:
                extra.append(html.escape(t("tabla {prob}%", prob=f"{f['probabilidad_enemigo']:.1f}")))
            prob = f"{f['probabilidad']:.1f}%" if f["probabilidad"] is not None else ""
            color = color_rareza(f["rareza"])
            tiempo = _tiempo(f.get("minutos_medios"), p["texto"], fila=f) or _sin_estimacion(f.get("motivo"), p["suave"])
            # La marca no es un enlace (sin href): solo dice cuanto rellenar la fila.
            ancla = relleno_filas.marca(relleno_filas.fraccion(f.get("minutos_medios"), referencia))
            nombre = f"<b>{donde}</b>"
            if ancla:
                nombre = f"<a name='{ancla}'>{nombre}</a>"
            # Dos lineas por sitio (el sitio y, debajo, rotacion y rareza; a la derecha el % y
            # el tiempo): cabe en la columna estrecha de la ficha C sin partir las palabras.
            rareza = glosario.enlace("rareza", _glosa(self.con, "rareza", f["rareza"]), color)
            detalle = " &middot; ".join(x for x in (", ".join(extra), rareza) if x)
            filas.append(
                f"<tr><td width='4' style='background:{color}'></td>"
                f"<td>{nombre}<br><span style='color:{p['suave']};font-size:12px'>{detalle}</span></td>"
                f"<td align='right'><span style='white-space:nowrap'><b>{prob}</b></span><br>"
                f"<span style='white-space:nowrap'>{tiempo}</span></td></tr>"
            )
        if sobran:
            filas.append(
                f"<tr><td colspan='3' style='color:{p['suave']}'>"
                f"{html.escape(t('y {n} sitios más, con más tiempo o menos probabilidad', n=sobran))}</td></tr>"
            )
        if pvp:
            maxima = max((f["probabilidad"] or 0) for f in pvp)
            filas.append(
                f"<tr><td colspan='3' style='color:{p['suave']}'>"
                + html.escape(t("Conclave (PvP): {n} modos, hasta un {prob}% por partida",
                                n=len(pvp), prob=f"{maxima:.1f}"))
                + "</td></tr>"
            )
        return _envolver(filas) + enlaces_wiki.linea(visibles, p["suave"], p["acento"])

    def _bloque_planeta(self, item_id: int) -> str:
        """Recurso de planeta: cae en cualquier mision de esos planetas, sin porcentaje."""
        datos = relaciones.recurso_de_planeta(self.con, item_id)
        if not datos:
            return ""
        p = PALETA
        planetas = ", ".join(html.escape(nombre_idioma(x, "planeta")) for x in datos["planetas"])
        cuerpo = [
            f"<div style='color:{p['acento']};font-size:12px;font-weight:bold'>"
            f"{html.escape(t('Recurso de planeta')).upper()}</div>",
            f"<div style='margin-top:2px'>{html.escape(t('Cae en cualquier misión de'))} "
            f"<b>{planetas}</b>: {html.escape(t('lo sueltan los enemigos y los contenedores, sin porcentaje conocido.'))}</div>",
        ]
        if datos["nodos"]:
            rapidas = " &middot; ".join(
                f"<span style='color:{p['texto']}'>{html.escape(n['donde'])}</span> "
                f"({html.escape(n['mision'])}, ~{n['minutos']:.0f} min)"
                for n in datos["nodos"]
            )
            cuerpo.append(f"<div style='color:{p['suave']};margin-top:2px'>"
                          f"{html.escape(t('Misiones rápidas para farmearlo:'))} {rapidas}</div>")
        return _tarjeta("".join(cuerpo), p["acento"])


def _sin_prefijo_mercado(texto: str) -> str:
    """En la fila MERCADO de la ficha sobra repetir "Mercado:" delante."""
    prefijo = t("Mercado: {resumen}", resumen="")
    if prefijo and texto.startswith(prefijo):
        texto = texto[len(prefijo):]
    return texto[:1].upper() + texto[1:] if texto else texto


def _g_hab() -> str:
    return glosa("Habilidades", "Abilities")


def _g_efecto() -> str:
    return glosa("Efecto", "Effect")


def _filas_visibles(grupo: list[dict]) -> list[dict]:
    """Las filas que pinta la tabla de fuentes: sin las de Conclave y con el tope por tipo."""
    return [f for f in grupo if f.get("motivo") != "pvp"][:MAX_FILAS_POR_TIPO]


def _con_padre(nombre: str, padre: str | None) -> str:
    """'Sistemas de Ash Prime' o 'Ash Prime Systems', segun el idioma."""
    return t("{nombre} de {padre}", nombre=nombre, padre=padre) if padre else nombre


def _enlace_reliquia(reliquia: dict, color: str) -> str:
    """'Neo C11' (sin 'Relic') enlazado a su ficha."""
    corto = (reliquia.get("nombre_en") or "").removesuffix(" Relic")
    return (f"<a style='color:{color};text-decoration:none' href='item:{reliquia['reliquia_id']}'>"
            f"<b>{html.escape(corto)}</b></a>")


def _rotacion_prime(mision: dict, color: str) -> str:
    if mision.get("rotacion"):
        return glosario.enlace_rotacion(mision.get("modo"), mision["rotacion"],
                                        t("rotación {rot}", rot=mision["rotacion"]), color)
    return html.escape(mision.get("etapa") or "")


def _seccion(titulo: str, clave_glosario: str | None = None, primero: bool = False) -> str:
    texto = (
        glosario.enlace(clave_glosario, titulo.upper(), PALETA["acento"])
        if clave_glosario
        else html.escape(titulo).upper()
    )
    return (
        f"<div style='color:{PALETA['acento']};font-size:12px;font-weight:bold;letter-spacing:2px;"
        f"margin-top:{2 if primero else 16}px;margin-bottom:4px'>{texto}</div>"
    )


def _etiqueta(texto: str, fondo: str, color: str, clave_glosario: str | None = None) -> str:
    cuerpo = glosario.enlace(clave_glosario, texto, color) if clave_glosario else html.escape(texto)
    return (
        f"<span style='background:{fondo};color:{color};font-size:12px;"
        f"padding:2px 8px'>&nbsp;{cuerpo}&nbsp;</span>"
    )


def _tiempo(minutos: float | None, color: str, negrita: bool = False, fila: dict | None = None) -> str:
    """'~35 min' con la explicacion de la estimacion al pasar el raton; vacio si no hay.

    Con `fila` (la fuente de ese tiempo) el tooltip desglosa SUS numeros: minutos por
    partida, partidas de media y total (desglose_tiempo); sin ella, la explicacion generica.
    """
    texto = eficiencia.texto_minutos(minutos)
    if not texto:
        return ""
    return glosario.enlace("tiempo_medio", texto, color, negrita, desglose_tiempo.texto(fila))


MOTIVOS_SIN_ESTIMACION = {
    "por_muerte": "por muerte",
    "reputacion": "reputación",
    "diaria": "1 al día",
    "semanal": "1 a la semana",
    "pvp": "PvP",
    "evento": "solo en evento",
}


def _sin_estimacion(motivo: str | None, color: str) -> str:
    texto = MOTIVOS_SIN_ESTIMACION.get(motivo or "")
    return glosario.enlace("tiempo_medio", t(texto), color) if texto else ""


def _rotacion(con, rotacion: str | None, color: str, modo: str | None = None) -> str:
    """'Rotacion C' con su explicacion al pasar el raton; vacio si no hay rotacion.

    Con el modo de la fila la explicacion es la de ese modo (en Supervivencia la C es
    el minuto 20; en Espionaje, la tercera boveda); sin el, la generica.
    """
    if not rotacion:
        return ""
    return glosario.enlace_rotacion(modo, rotacion, _glosa(con, "rotacion", rotacion), color)


def _tarjeta(cuerpo: str, color: str) -> str:
    """QTextBrowser no sabe de bordes redondeados: una tabla con franja de color."""
    return (
        f"<table cellpadding='8' cellspacing='0' width='100%' style='margin-bottom:6px'>"
        f"<tr><td width='3' style='background:{color}'></td>"
        f"<td style='background:{PALETA['panel2']}'>{cuerpo}</td></tr></table>"
    )


def _envolver(filas: list[str]) -> str:
    return (
        f"<table width='100%' cellspacing='0' cellpadding='6' style='background:{PALETA['panel2']}'>"
        + "".join(filas) + "</table>"
    )
