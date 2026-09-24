"""Pestana Buscar: escribes algo y te dice de donde sale."""

from __future__ import annotations

import html
import sqlite3

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..config import cargar, guardar
from .. import perfil
from ..estado import inventario as estado_inventario
from ..datos import consultas, eficiencia, indice, items, misiones, modos_mision, novedades, relaciones
from ..datos.nodos import etapa_bonita, nombre_bonito
from ..idiomas import es_castellano, glosa, nombre as nombre_idioma, t
from . import desglose_tiempo, enlaces_wiki, glosario, guias_youtube, pestana_primes, relleno_filas
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

CATEGORIAS_ES = {
    "Warframes": "Warframe", "Primary": "Arma primaria", "Secondary": "Arma secundaria",
    "Melee": "Cuerpo a cuerpo", "Archwing": "Archwing", "Arch-Gun": "Archcanon",
    "Arch-Melee": "Arch-melee", "Sentinels": "Centinela", "SentinelWeapons": "Arma de centinela",
    "Pets": "Companero", "Mods": "Mod", "Arcanes": "Arcano", "Relics": "Reliquia",
    "Resources": "Recurso", "Misc": "Objeto", "Gear": "Equipo", "Railjack": "Railjack",
    "Skins": "Aspecto", "Glyphs": "Glifo", "Sigils": "Sigilo", "Fish": "Pez",
    "Quests": "Mision", "Honoria": "Honoria",
}

ROL_SUBTITULO = Qt.UserRole + 1
ROL_IMAGEN = Qt.UserRole + 2
ROL_RAREZA = Qt.UserRole + 3

# Lo que se pone al lado del nombre: categoria y, si es pieza, "Componente".
def categoria_es(categoria: str, tipo: str | None = None) -> str:
    base = t(CATEGORIAS_ES.get(categoria, categoria))
    return t("{base} · pieza", base=base) if tipo == "Componente" else base


def _glosa(con, dominio: str, en: str | None) -> str:
    """Termino del glosario del indice en el idioma de la interfaz."""
    return glosa(indice.traducir(con, dominio, en), en)


class DelegadoResultado(QStyledItemDelegate):
    """Cada resultado: imagen, nombre grande y debajo la categoria en gris."""

    ALTO = 54
    LADO_IMAGEN = 40

    def sizeHint(self, opcion, indice):  # noqa: N802 - firma de Qt
        return QSize(opcion.rect.width(), self.ALTO)

    def paint(self, pintor: QPainter, opcion, indice):  # noqa: N802
        p = PALETA
        rect: QRect = opcion.rect
        pintor.save()
        if opcion.state & QStyle.State_Selected:
            pintor.fillRect(rect, QColor(p["panel2"]))
            pintor.fillRect(QRect(rect.left(), rect.top(), 3, rect.height()), QColor(p["acento"]))
        elif opcion.state & QStyle.State_MouseOver:
            pintor.fillRect(rect, QColor(p["panel2"]).darker(110))
        pintor.setPen(QPen(QColor(p["borde"])))
        pintor.drawLine(rect.left() + 8, rect.bottom(), rect.right() - 8, rect.bottom())

        x = rect.left() + 12
        mapa = imagenes().pixmap(indice.data(ROL_IMAGEN), self.LADO_IMAGEN)
        if mapa is not None:
            y = rect.top() + (rect.height() - mapa.height()) // 2
            pintor.drawPixmap(x + (self.LADO_IMAGEN - mapa.width()) // 2, y, mapa)
        else:
            pintor.setPen(QPen(QColor(p["borde"])))
            pintor.setBrush(QColor(p["panel"]))
            pintor.drawRoundedRect(x, rect.top() + 7, self.LADO_IMAGEN, self.LADO_IMAGEN, 6, 6)
        x += self.LADO_IMAGEN + 12

        fuente = QFont(opcion.font)
        fuente.setPointSize(11)
        fuente.setBold(True)
        pintor.setFont(fuente)
        pintor.setPen(QColor(p["texto"]))
        ancho = rect.right() - x - 8
        nombre = pintor.fontMetrics().elidedText(indice.data(Qt.DisplayRole), Qt.ElideRight, ancho)
        pintor.drawText(QRect(x, rect.top() + 7, ancho, 22), Qt.AlignVCenter | Qt.AlignLeft, nombre)

        fuente.setPointSize(9)
        fuente.setBold(False)
        pintor.setFont(fuente)
        pintor.setPen(QColor(p["suave"]))
        subtitulo = pintor.fontMetrics().elidedText(
            indice.data(ROL_SUBTITULO) or "", Qt.ElideRight, ancho
        )
        pintor.drawText(QRect(x, rect.top() + 29, ancho, 18), Qt.AlignVCenter | Qt.AlignLeft, subtitulo)
        pintor.restore()


class PestanaBuscador(QWidget):
    estado = Signal(str)
    pedir_precios = Signal(str)
    anadir_objetivo = Signal(int, bool)  # item_id, set completo

    def __init__(self, parent=None):
        super().__init__(parent)
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
        # Quien reproduce las guias de YouTube dentro de Farmadex (la ventana lo pone);
        # sin el, el navegador del sistema.
        self.reproductor = None
        # "Lo mas nuevo" cuando se abrio una ficha de objeto por "el ultimo warframe": la
        # nota con los demas objetos de esa actualizacion, que va debajo del nombre.
        self._nota_novedad: dict | None = None
        # Lo ultimo que se busco sin exito, para volver a pintar el aviso al cambiar de idioma.
        self._sin_resultados: str | None = None
        p = PALETA

        self.caja = QLineEdit()
        self.caja.setClearButtonEnabled(True)
        self.caja.setMinimumHeight(40)

        self.ocultar_vaulted = QCheckBox()
        self.ocultar_vaulted.setChecked(bool(self.config.get("ocultar_vaulted", False)))
        self.ocultar_vaulted.toggled.connect(self._cambiar_filtro)
        glosario.aplicar(self.ocultar_vaulted, "boveda")

        self.atras = QPushButton()
        self.atras.setEnabled(False)
        self.atras.clicked.connect(self._volver)

        self.boton_objetivo = QPushButton()
        self.boton_objetivo.setObjectName("principal")
        self.boton_objetivo.setEnabled(False)
        self.boton_objetivo.clicked.connect(
            lambda: self._actual and self.anadir_objetivo.emit(self._actual, False)
        )
        self.boton_set = QPushButton()
        self.boton_set.setEnabled(False)
        self.boton_set.clicked.connect(
            lambda: self._actual and self.anadir_objetivo.emit(self._actual, True)
        )
        # Para lo que Farmadex no cuenta (habilidades, construccion, historia): la wiki
        # oficial con lo escrito, o la pagina del objeto de la ficha abierta. Solo al
        # pulsarlo; apagado si no hay nada que buscar.
        self.boton_wiki = QPushButton()
        self.boton_wiki.setEnabled(False)
        self.boton_wiki.clicked.connect(self._abrir_wiki)
        # Guias en video de la ficha abierta (mision u objeto), dentro de Farmadex.
        self.boton_youtube = QPushButton()
        self.boton_youtube.setEnabled(False)
        self.boton_youtube.clicked.connect(self._abrir_youtube)

        self.lista = QListWidget()
        self.lista.setMinimumWidth(300)
        self.lista.setItemDelegate(DelegadoResultado(self.lista))
        self.lista.setMouseTracking(True)
        self.lista.setUniformItemSizes(True)
        self.ficha = glosario.FichaConGlosario()
        self.ficha.setOpenLinks(False)
        self.ficha.anchorClicked.connect(self._enlace)
        # Fondo de las filas de fuentes relleno segun lo rapido que es conseguirlo ahi.
        self._relleno = relleno_filas.RellenoFilas(self.ficha)

        divisor = QSplitter(Qt.Horizontal)
        divisor.addWidget(self.lista)
        divisor.addWidget(self.ficha)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([340, 760])

        self.aviso = QLabel(t("Preparando los datos..."))
        self.aviso.setStyleSheet(f"color: {p['suave']};")
        self.precios = QLabel("")
        self.precios.setTextFormat(Qt.RichText)
        self.precios.setWordWrap(True)
        self.precios.setStyleSheet(
            f"color: {p['texto']}; background: {p['panel2']}; border: 1px solid {p['borde']};"
            " border-radius: 8px; padding: 6px 10px;"
        )
        self.precios.hide()
        self._slug_actual = ""

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 8, 4, 4)
        caja.setSpacing(8)
        caja.addWidget(self.caja)
        fila = QHBoxLayout()
        fila.addWidget(self.atras)
        fila.addStretch(1)
        fila.addWidget(self.ocultar_vaulted)
        fila.addWidget(self.boton_wiki)
        fila.addWidget(self.boton_youtube)
        fila.addWidget(self.boton_set)
        fila.addWidget(self.boton_objetivo)
        caja.addLayout(fila)
        caja.addWidget(self.aviso)
        caja.addWidget(self.precios)
        caja.addWidget(divisor, 1)

        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(180)
        self._temporizador.timeout.connect(self._buscar)

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

    def _etiqueta_maestria(self, item_id: int) -> str:
        """Dominado / a medias / sin dominar, o nada si no hay perfil o el objeto no da maestria."""
        if not self._hay_perfil or self.con is None or self.usuario is None:
            return ""
        estado = estado_con_padre(self.usuario, self.con, item_id)
        texto = texto_maestria(estado)
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
        """Tras cambiar de tema: la ficha lleva los colores dentro del HTML."""
        p = PALETA
        self.aviso.setStyleSheet(f"color: {p['suave']};")
        self.precios.setStyleSheet(
            f"color: {p['texto']}; background: {p['panel2']}; border: 1px solid {p['borde']};"
            " border-radius: 8px; padding: 6px 10px;"
        )
        self.lista.viewport().update()
        if self._datos_actuales:
            self._poner_ficha(self._html(self._datos_actuales))
        elif self._mision_actual and self.con:
            self._poner_ficha(self._html_mision(self._mision_actual))
        elif self._sin_resultados is not None:
            self._poner_ficha(self._html_sin_resultados(self._sin_resultados))
        elif self.con is not None and not self.caja.text().strip():
            self._poner_portada()

    def _poner_ficha(self, contenido: str) -> None:
        """Pinta la ficha y su relleno de filas en el acto, sin esperar al bucle de eventos:
        con fichas largas el temporizador podia quedarse sin disparar antes de pintarse."""
        self.ficha.setHtml(contenido)
        self._relleno.aplicar()

    def retraducir(self) -> None:
        """Tras cambiar de idioma: textos fijos, lista de resultados y ficha abierta."""
        self.caja.setPlaceholderText(t("Busca un objeto, una mision o pregunta  (p. ej. sistemas ash prime, hepit, el ultimo warframe)"))
        self.ocultar_vaulted.setText(t("Ocultar reliquias en boveda"))
        self.atras.setText(t("‹ Atras"))
        self.boton_objetivo.setText(t("+ Objetivo"))
        self.boton_set.setText(t("+ Set completo"))
        self.boton_wiki.setText(t("Buscar en la wiki"))
        self.boton_youtube.setText(t("Guias en YouTube"))
        self.boton_youtube.setToolTip(t("Busca guias en YouTube de la mision o el objeto abierto, "
                                        "ordenadas por visitas, y las abre en el reproductor de Farmadex."))
        self.boton_wiki.setToolTip(t("Abre la wiki oficial de Warframe en el navegador: la pagina "
                                     "del objeto abierto o, si no hay ninguno, la busqueda de lo escrito."))
        if self._resultados:
            self._pintar_resultados()
        self.repintar()

    def _imagen_lista(self, nombre: str) -> None:
        self.lista.viewport().update()
        if self._datos_actuales and self._datos_actuales["item"].get("imagen") == nombre:
            posicion = self.ficha.verticalScrollBar().value()
            self._poner_ficha(self._html(self._datos_actuales))
            self.ficha.verticalScrollBar().setValue(posicion)

    # -- navegacion --------------------------------------------------------

    def _cambiar_filtro(self, marcado: bool) -> None:
        self.config["ocultar_vaulted"] = marcado
        guardar(self.config)
        if self._actual:
            self.abrir(self._actual, recordar=False)

    def _enlace(self, url: QUrl) -> None:
        texto = url.toString()
        if glosario.mostrar(texto, self.ficha):
            return
        if texto.startswith("item:"):
            self.abrir(int(texto.removeprefix("item:")))
        elif texto.startswith(("nodo:", "modo:", "novedades:")):
            self.abrir_mision(texto)
        elif texto == "video:":
            self._abrir_youtube()
        elif texto.startswith("buscar:"):
            self.caja.setText(texto.removeprefix("buscar:"))
        elif texto.startswith("http"):
            QDesktopServices.openUrl(QUrl(texto))

    def url_wiki(self) -> str:
        """Lo que abre "Buscar en la wiki": la pagina del objeto abierto o la busqueda.

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
        hay_ficha = bool(self._datos_actuales or self._mision_actual)
        self.boton_wiki.setEnabled(hay_ficha or bool(self.caja.text().strip()))
        self.boton_youtube.setEnabled(hay_ficha)

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

    def _seleccionar_en_lista(self, item_id: int) -> None:
        """Deja marcado en la lista el objeto al que se vuelve, sin abrirlo otra vez."""
        for fila, resultado in enumerate(self._resultados):
            if (resultado.get("clave") or resultado["item_id"]) == item_id:
                self.lista.blockSignals(True)
                self.lista.setCurrentRow(fila)
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
        self._poner_ficha(self._html(datos))
        self.ficha.verticalScrollBar().setValue(0)
        self._consultar_precio(datos["item"])
        self.boton_objetivo.setEnabled(True)
        # El set solo tiene sentido en algo que se construye con piezas.
        self.boton_set.setEnabled(bool(datos["componentes"] or datos["padre"]))
        self._actualizar_boton_wiki()

    def _consultar_precio(self, item: dict) -> None:
        slug = item.get("market_slug")
        self._slug_actual = slug or ""
        if not slug:
            self.precios.hide()
            return
        self.precios.setText(t("Mercado: consultando precios..."))
        self.precios.show()
        self.pedir_precios.emit(slug)

    def mostrar_precios(self, slug: str, precios) -> None:
        from ..online.servicio_market import resumen

        if slug != self._slug_actual:
            return
        self.precios.setText(resumen(precios))
        self.precios.show()

    # -- busqueda ---------------------------------------------------------

    def _buscar(self) -> None:
        if not self.con:
            return
        texto = self.caja.text().strip()
        self.lista.clear()
        if len(texto) < 2:
            self._resultados = []
            self._vaciar_ficha()
            self._poner_portada()
            return
        # "como sacar citrine prime" busca "citrine prime"; "el ultimo warframe" no es un
        # nombre sino una pregunta por lo nuevo, salvo que sea exactamente un objeto.
        consulta = consultas.limpiar(texto)
        objetos = indice.buscar(self.con, consulta)
        mejor_objeto = min((r["nivel"] for r in objetos), default=9)
        filtro = consultas.intencion_novedad(consulta)
        if filtro and mejor_objeto > 0 and self._buscar_novedades(filtro):
            return
        # Nodos y tipos de mision: delante solo si casan mejor que el mejor objeto que se
        # puede conseguir ("hepit" solo es nodo); si empatan, los objetos siguen primero.
        # Lo que no tiene fuentes no cuenta: el reto de Onda nocturna "Supervivencia" no
        # puede tapar al tipo de mision.
        mejor_farmeable = min((r["nivel"] for r in objetos if r["peso"][2] == 0), default=9)
        encontradas = misiones.buscar(self.con, consulta)
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
            self._poner_ficha(self._html_sin_resultados(texto))

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
                + html.escape(t("No hay datos de fecha de salida en el indice. Se anaden al "
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
            self._poner_ficha(self._html(self._datos_actuales))
            return True
        self.abrir_mision(f"novedades:{filtro}")
        return True

    def _poner_portada(self) -> None:
        """Con el buscador vacio, una linea discreta con lo nuevo de la ultima actualizacion."""
        datos = novedades.ultima(self.con) if self.con is not None else None
        if not datos:
            return
        p = PALETA
        nombres = ", ".join(
            f"<a style='color:{p['acento']}' href='item:{f['item_id']}'>{html.escape(nombre_idioma(f))}</a>"
            for f in datos["items"][:6]
        )
        if len(datos["items"]) > 6:
            nombres += f", <a style='color:{p['acento']}' href='novedades:todo'>&hellip;</a>"
        titulo = t("Novedades ({actualizacion})", actualizacion=novedades.titulo(datos))
        self.ficha.setHtml(
            f"<p style='color:{p['suave']};margin-top:8px'>"
            f"<a style='color:{p['suave']};text-decoration:none' href='novedades:todo'>{html.escape(titulo)}</a>: "
            f"{nombres}</p>"
        )

    def _html_novedades(self, filtro: str) -> str:
        datos = novedades.ultima(self.con, filtro)
        if not datos:
            return ""
        p = PALETA
        titulo = t("Lo nuevo de la {actualizacion} ({fecha})", actualizacion=novedades.titulo(datos),
                   fecha=novedades.fecha_legible(datos["fecha"]))
        filas = []
        for f in datos["items"]:
            filas.append(
                f"<tr><td><a style='color:{p['texto']};text-decoration:none' href='item:{f['item_id']}'>"
                f"<b>{html.escape(nombre_idioma(f))}</b></a></td>"
                f"<td style='color:{p['suave']}'>{html.escape(categoria_es(f['categoria'], f.get('tipo')))}</td>"
                f"<td align='right'><a style='color:{p['acento']}' href='item:{f['item_id']}'>"
                f"{html.escape(t('Como conseguirlo'))} &rarr;</a></td></tr>"
            )
        return (
            f"<div style='font-size:22px;font-weight:bold'>{html.escape(titulo)}</div>"
            f"<div style='color:{p['suave']};font-size:13px;margin-top:2px'>"
            f"{html.escape(datos['actualizacion'])}</div>"
            + _seccion(t("Objetos nuevos ({n})", n=len(datos["items"])))
            + _envolver(filas)
        )

    def _html_nota_novedad(self) -> str:
        """'Lo mas nuevo: Actualizacion 44.0 (23/09/2026). Tambien salio: Citrine Prime.'"""
        nota = self._nota_novedad
        if not nota:
            return ""
        p = PALETA
        texto = html.escape(t("Lo mas nuevo: {actualizacion} ({fecha}).", actualizacion=novedades.titulo(nota),
                              fecha=novedades.fecha_legible(nota["fecha"])))
        if nota["items"]:
            otros = ", ".join(
                f"<a style='color:{p['acento']}' href='item:{f['item_id']}'>{html.escape(nombre_idioma(f))}</a>"
                for f in nota["items"]
            )
            texto += f" {html.escape(t('Tambien salio:'))} {otros}."
        return f"<div style='color:{p['suave']};margin-top:6px'>{texto}</div>"

    def _vaciar_ficha(self) -> None:
        self._actual = None
        self._datos_actuales = None
        self._mision_actual = None
        self._nota_novedad = None
        self._sin_resultados = None
        self._slug_actual = ""
        self.ficha.clear()
        self.precios.hide()
        self.boton_objetivo.setEnabled(False)
        self.boton_set.setEnabled(False)
        self._actualizar_boton_wiki()

    def sugerencias(self, texto: str) -> list[dict]:
        """Objetos parecidos a una busqueda fallida: se prueba cada palabra por separado.

        `como consigo rhino` no encuentra nada entero, pero `rhino` si. Se devuelven
        los primeros resultados de cada palabra util, sin repetir.
        """
        if not self.con:
            return []
        vistos: set[int] = set()
        salida: list[dict] = []
        palabras = [p for p in texto.split() if len(p) >= 3 and p.lower() not in PALABRAS_VACIAS]
        for palabra in palabras:
            if palabra.lower() == texto.lower():
                continue
            for r in indice.buscar(self.con, palabra, limite=MAX_SUGERENCIAS):
                if r["item_id"] not in vistos:
                    vistos.add(r["item_id"])
                    salida.append(r)
                if len(salida) >= MAX_SUGERENCIAS:
                    return salida
        return salida

    def _html_sin_resultados(self, texto: str) -> str:
        p = PALETA
        partes = [
            f"<div style='font-size:18px;font-weight:bold;margin-top:8px'>"
            f"{html.escape(t('No he encontrado nada para «{busqueda}»', busqueda=texto))}</div>"
        ]
        parecidos = self.sugerencias(texto)
        if parecidos:
            enlaces = "".join(
                f"<li><a style='color:{p['acento']}' href='item:{r['item_id']}'>"
                f"{html.escape(_con_padre(nombre_idioma(r), nombre_idioma(r, 'padre')))}</a>"
                f" <span style='color:{p['suave']}'>&middot; "
                f"{html.escape(categoria_es(r['categoria'], r.get('tipo')))}</span></li>"
                for r in parecidos
            )
            partes.append(
                f"<div style='color:{p['suave']};margin-top:10px'>"
                f"{html.escape(t('Quiza buscabas:'))}</div><ul>{enlaces}</ul>"
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
            elemento.setToolTip(r["categoria"])
            self.lista.addItem(elemento)
        if 0 <= fila_actual < self.lista.count():
            self.lista.setCurrentRow(fila_actual)
        self.lista.blockSignals(False)

    def _elegir_resultado(self, fila: int) -> None:
        # Moverse por la lista tambien cuenta como navegar: antes se borraba el
        # historial aqui y el boton "Atras" quedaba apagado casi siempre.
        if 0 <= fila < len(self._resultados) and not self._volviendo:
            resultado = self._resultados[fila]
            if resultado.get("clave"):
                self.abrir_mision(resultado["clave"])
            else:
                self.abrir(resultado["item_id"])

    def _elemento_mision(self, r: dict) -> QListWidgetItem:
        """Un nodo ('Hepit' / 'Nodo · Vacio · Captura') o un tipo de mision en la lista."""
        if r["tipo_resultado"] == "modo":
            elemento = QListWidgetItem(modos_mision.nombre(r["modo"]))
            n = len(misiones.nodos_de_modo(self.con, r["modo"])) if self.con else 0
            subtitulo = t("Tipo de mision") + (" · " + t("{n} nodos", n=n) if n else "")
        else:
            elemento = QListWidgetItem(misiones.titulo_nodo(r))
            subtitulo = " · ".join(
                x for x in (t("Nodo"), nombre_idioma(r, "planeta"), modos_mision.nombre(r["modo"])) if x
            )
        elemento.setData(ROL_SUBTITULO, subtitulo)
        elemento.setData(ROL_IMAGEN, None)
        return elemento

    # -- fichas de mision -------------------------------------------------

    def abrir_mision(self, clave: str, recordar: bool = True) -> None:
        """Ficha de un nodo ('nodo:98') o de un tipo de mision ('modo:Survival')."""
        if not self.con:
            return
        contenido = self._html_mision(clave)
        if not contenido:
            return
        self._actual = None
        self._datos_actuales = None
        self._mision_actual = clave
        self._sin_resultados = None
        if recordar and (not self._historial or self._historial[-1][0] != clave):
            self._historial.append((clave, self.caja.text().strip()))
            del self._historial[:-MAX_HISTORIAL]
        self.atras.setEnabled(len(self._historial) > 1)
        self._poner_ficha(contenido)
        self.ficha.verticalScrollBar().setValue(0)
        self._slug_actual = ""
        self.precios.hide()
        self.boton_objetivo.setEnabled(False)
        self.boton_set.setEnabled(False)
        self._actualizar_boton_wiki()

    def _html_mision(self, clave: str) -> str:
        tipo, _, valor = clave.partition(":")
        if tipo == "novedades":
            return self._html_novedades(valor)
        if tipo == "modo":
            return self._html_modo(valor)
        if tipo == "nodo" and valor.isdigit():
            n = misiones.nodo(self.con, int(valor))
            return self._html_nodo(n) if n else ""
        return ""

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
        ]
        faccion = glosa(n["faccion_es"], n["faccion_en"]) if n.get("faccion_es") else (n.get("faccion_en") or "")
        if faccion:
            etiquetas.append(_etiqueta(faccion, p["panel"], p["suave"]))
        if n.get("nivel_min") is not None:
            etiquetas.append(_etiqueta(t("nivel {min}-{max}", min=n["nivel_min"], max=n["nivel_max"]),
                                       p["panel"], p["suave"]))
        return "".join((
            f"<div style='font-size:22px;font-weight:bold'>{html.escape(titulo)}</div>"
            f"<div style='color:{p['suave']};font-size:13px;margin-top:2px'>{subtitulo}</div>"
            f"<div style='margin-top:6px'>{' '.join(etiquetas)}</div>",
            self._bloque_modo(modo),
            self._bloque_recompensas_nodo(n),
            self._pie_mision([n], modo),
        ))

    def _html_modo(self, modo_en: str) -> str:
        p = PALETA
        modo = modos_mision.normalizar(modo_en)
        if not modo:
            return ""
        nombre = modos_mision.nombre(modo)
        otro = modos_mision.MODOS[modo][1] if es_castellano() else ""
        detalle = html.escape(t("Tipo de mision"))
        if otro and otro != nombre:
            detalle += " &middot; " + html.escape(otro)
        partes = [
            f"<div style='font-size:22px;font-weight:bold'>{html.escape(nombre)}</div>"
            f"<div style='color:{p['suave']};font-size:13px;margin-top:2px'>{detalle}</div>",
            self._bloque_modo(modo),
        ]
        nodos = misiones.nodos_de_modo(self.con, modo)
        if nodos:
            filas = []
            for n in nodos:
                nivel = (
                    " &middot; " + html.escape(t("nivel {min}-{max}", min=n["nivel_min"], max=n["nivel_max"]))
                    if n.get("nivel_min") is not None else ""
                )
                filas.append(
                    f"<li><a style='color:{p['acento']}' href='nodo:{n['id']}'>"
                    f"{html.escape(misiones.titulo_nodo(n))}</a>"
                    f" <span style='color:{p['suave']}'>&middot; {html.escape(nombre_idioma(n, 'planeta'))}"
                    f"{nivel}</span></li>"
                )
            partes.append(_seccion(t("Nodos de este tipo ({n})", n=len(nodos))) + f"<ul>{''.join(filas)}</ul>")
        partes.append(self._pie_mision([], modo))
        return "".join(partes)

    def _bloque_modo(self, modo: str) -> str:
        """Que se hace, como van las recompensas y cuando cae cada rotacion en ese modo."""
        p = PALETA
        if modo not in modos_mision.MODOS:
            return ""
        _, _, que, recompensas = modos_mision.MODOS[modo]
        partes = [
            _seccion(t("Como se juega"), "mision"),
            f"<p style='margin:2px 0 6px 0'><b>{html.escape(t('Que hacer:'))}</b> {html.escape(t(que))}</p>",
            f"<p style='margin:2px 0 6px 0'><b>{html.escape(t('Recompensas:'))}</b> "
            f"{html.escape(t(recompensas))}</p>",
        ]
        if modo == "Disruption":
            partes.append(self._tabla_disrupcion())
        lineas = []
        for letra in modos_mision.rotaciones_del_modo(modo):
            visible = _rotacion(self.con, letra, p["acento"], modo)
            larga = modos_mision.linea_rotacion(modo, letra)
            lineas.append(f"<li>{visible}: <span style='color:{p['suave']}'>{html.escape(larga)}</span></li>")
        if lineas:
            partes.append(f"<ul style='margin-top:2px'>{''.join(lineas)}</ul>")
        return "".join(partes)

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
                titulo = html.escape(t("Al terminar la mision"))
            partes.append(f"<div style='margin:6px 0 2px 4px;font-weight:bold'>{titulo}</div>")
            filas = []
            for r in premios[rot]:
                color = color_rareza(r["rareza"])
                etiqueta = _con_padre(nombre_idioma(r), nombre_idioma(r, "padre"))
                filas.append(
                    f"<tr><td width='6' style='background:{color}'></td>"
                    f"<td><a style='color:{p['texto']};text-decoration:none' href='item:{r['item_id']}'>"
                    f"{html.escape(etiqueta)}</a></td>"
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
            f"<p style='margin-top:6px'><a style='color:{p['acento']}' href='video:'>"
            f"{html.escape(t('Guias en YouTube'))} &rarr;</a></p>"
        )
        return linea + video

    # -- pintado ----------------------------------------------------------

    def _html(self, datos: dict) -> str:
        con = self.con
        p = PALETA
        item, padre = datos["item"], datos["padre"]
        nombre = html.escape(nombre_idioma(item))
        if padre:
            nombre = _con_padre(
                nombre,
                f"<span style='color:{p['suave']}'>{html.escape(nombre_idioma(padre))}</span>",
            )
        # Debajo del nombre, el mismo en el otro idioma del indice.
        otro_nombre = item["nombre_en"] if es_castellano() else (item["nombre_es"] or "")

        es_reliquia = item["categoria"] == "Relics"
        clave_categoria = "reliquia" if es_reliquia else ("pieza" if item["tipo"] == "Componente" else None)
        etiquetas = [
            _etiqueta(categoria_es(item["categoria"], item["tipo"]), p["panel"], p["suave"], clave_categoria)
        ]
        era = era_de(item["nombre_en"]) if es_reliquia else ""
        if era:
            etiquetas.append(_etiqueta(t(era), p["panel"], p["acento"], "era"))
        if item["es_prime"]:
            etiquetas.append(_etiqueta("Prime", p["panel"], color_rareza("Rare"), "prime"))
        if item["vaulted"]:
            etiquetas.append(_etiqueta(t("En boveda"), "#3a2a12", COLOR_BOVEDA, "boveda"))
        elif item["vaulted"] == 0 and es_reliquia:
            etiquetas.append(_etiqueta(t("Disponible"), "#15301a", COLOR_DISPONIBLE, "boveda"))
        if item["ducados"]:
            etiquetas.append(_etiqueta(t("{n} ducados", n=item["ducados"]), p["panel"], p["suave"], "ducados"))
        maestria = self._etiqueta_maestria(item["id"])
        if maestria:
            etiquetas.append(maestria)
        tienes = self._etiqueta_inventario(item["unique_name"])
        if tienes:
            etiquetas.append(tienes)

        imagen = ""
        ruta = imagenes().ruta(item["imagen"]) if item.get("imagen") else None
        if ruta and ruta.exists():
            imagen = f"<img src='{ruta.as_uri()}' width='88' height='88'>"
        elif item.get("imagen"):
            imagenes().pixmap(item["imagen"])  # la pide en segundo plano
        cabecera = (
            "<table cellpadding='0' cellspacing='0' width='100%'><tr>"
            + (f"<td width='100' valign='top'>{imagen}</td>" if imagen else "")
            + f"<td valign='top'><div style='font-size:22px;font-weight:bold'>{nombre}</div>"
            f"<div style='color:{p['suave']};font-size:13px;margin-top:2px'>"
            f"{html.escape(otro_nombre)}"
            + (" &middot; " + html.escape(t("pieza ×{n}", n=item["item_count"])) if item["item_count"] else "")
            + "</div>"
            f"<div style='margin-top:6px'>{' '.join(etiquetas)}</div></td></tr></table>"
        )
        partes = [cabecera, self._html_nota_novedad()]
        if padre:
            partes.append(
                f"<div style='color:{p['suave']};margin-top:4px'>{t('Pieza de')} "
                f"<a style='color:{p['acento']}' href='item:{padre['id']}'>"
                f"{html.escape(nombre_idioma(padre))}</a></div>"
            )
        if item["descripcion_es"]:
            partes.append(
                f"<p style='color:{p['suave']};margin-top:8px'>"
                f"{html.escape(item['descripcion_es'])}</p>"
            )

        if datos["componentes"]:
            filas = "".join(
                f"<li><a style='color:{p['acento']}' href='item:{c['id']}'>"
                f"{html.escape(nombre_idioma(c))}</a>"
                + (f" <span style='color:{p['suave']}'>&times;{c['item_count']}</span>"
                   if c["item_count"] else "")
                + self._tienes_componente(c)
                + "</li>"
                for c in datos["componentes"]
            )
            partes.append(_seccion(t("Se construye con")) + f"<ul>{filas}</ul>")

        partes.append(self._bloque_ruta(item["id"]))
        partes.append(self._bloque_reliquias(item["id"]))
        if item["categoria"] == "Relics":
            partes.append(self._bloque_contenido(item["id"]))

        partes.append(self._bloque_planeta(item["id"]))
        agrupadas: dict[str, list[dict]] = {}
        for f in relaciones.fuentes_de(con, item["id"]):
            agrupadas.setdefault(f["tipo"], []).append(f)
        hay_estimacion = False
        # Una sola escala para toda la ficha: el mismo tiempo se rellena igual en
        # Misiones que en Contratos, y las secciones se comparan entre si.
        referencia = relleno_filas.escala(
            f["minutos_medios"]
            for tipo in ORDEN_TIPOS
            for f in _filas_visibles(agrupadas.get(tipo) or [])
        )
        for tipo in ORDEN_TIPOS:
            grupo = agrupadas.get(tipo)
            if grupo:
                partes.append(_seccion(_glosa(con, "tipo_fuente", tipo)))
                partes.append(self._tabla_fuentes(grupo, referencia))
                hay_estimacion = hay_estimacion or any(f["minutos_medios"] is not None for f in grupo)
        if hay_estimacion:
            partes.append(
                f"<div style='color:{p['suave']};font-size:12px;margin:2px 0 8px 4px'>"
                + html.escape(t("Los tiempos son una estimacion para un jugador medio: lo que suele "
                                "durar la mision dividido por la probabilidad. Los enemigos comunes "
                                "(probabilidad por muerte), los sindicatos y las incursiones no se "
                                "pueden estimar asi."))
                + "</div>"
            )

        if es_reliquia and not datos["fuentes"]:
            # Una reliquia sin mision no "puede venir de una mision de historia": esta en
            # boveda (o acaba de salir de ella) y se compra a otro jugador. Lo mismo que
            # dicen la vista compacta y Objetivos de esa misma reliquia.
            texto = t("No cae en ninguna mision activa")
            if item["vaulted"]:
                texto += ". " + t("Hay que comprarla a otro jugador.")
            partes.append(f"<p>{glosario.enlace('boveda', texto, COLOR_BOVEDA if item['vaulted'] else p['suave'])}</p>")
        elif not datos["fuentes"] and not datos["componentes"]:
            partes.append(
                f"<p style='color:{p['suave']}'>"
                + html.escape(t("Sin fuentes registradas: puede venir de una mision de historia, "
                                "del mercado, de un evento o de un sindicato."))
                + "</p>"
            )
        # Las reliquias no traen wiki_url, pero su pagina se llama como ellas (Lith S19).
        url_wiki = enlaces_wiki.url_item(item)
        if url_wiki:
            partes.append(
                f"<p style='margin-top:10px'><a style='color:{p['acento']}' "
                f"href='{html.escape(url_wiki)}'>{html.escape(t('Abrir en la wiki'))} &rarr;</a></p>"
            )
        return "".join(partes)

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
            f"{html.escape(t('Por donde empezar')).upper()}</div>",
            f"<div style='font-size:16px;margin-top:2px'><a style='color:{p['texto']};"
            f"text-decoration:none' href='item:{reliquia['reliquia_id']}'><b>{html.escape(nombre)}</b></a>"
            f" <span style='color:{p['suave']}'>&middot; {radiante}</span></div>",
        ]
        if ruta["solo_en_boveda"]:
            cuerpo.append(
                "<div style='margin-top:2px'>"
                + glosario.enlace("boveda", t("Solo en boveda: hay que comprarla a otro jugador"), COLOR_BOVEDA)
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
            f"{html.escape(t('Por donde empezar')).upper()}</div>",
            f"<div style='font-size:16px;margin-top:2px'>{' &middot; '.join(trozos)}</div>",
        ]
        if tipo:
            cuerpo.append(f"<div style='color:{p['suave']};margin-top:2px'>{html.escape(tipo)}</div>")
        return _tarjeta("".join(cuerpo), p["acento"])

    def _bloque_reliquias(self, item_id: int) -> str:
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
            nombre = html.escape(nombre_idioma(r))
            color = COLOR_BOVEDA if r["vaulted"] else COLOR_DISPONIBLE
            estado = t("en boveda") if r["vaulted"] else t("disponible")
            probs = " &nbsp; ".join(
                glosario.enlace("refinamiento", _glosa(self.con, "refinamiento", ref)[:3], p["suave"])
                + f" <b>{r['probabilidades'][ref]:.1f}%</b>"
                for ref in REFINAMIENTOS
                if ref in r["probabilidades"]
            )
            misiones = relaciones.misiones_de(self.con, r["reliquia_id"])[:3]
            donde = "".join(
                f"<div style='color:{p['suave']}'>{enlaces_wiki.donde(m, p['suave'])}"
                + (f" &middot; {glosario.enlace_mision(m.get('modo'), m['mision'], p['suave'], m['rotacion'])}"
                   if m["mision"] else "")
                + (f" &middot; {_rotacion(self.con, m['rotacion'], p['suave'], m.get('modo'))}" if m["rotacion"] else "")
                + (f" &middot; {m['probabilidad']:.1f}%" if m["probabilidad"] else "")
                + (f" &middot; {_tiempo(m['minutos_medios'], p['suave'], fila=m)}" if m["minutos_medios"] is not None else "")
                + "</div>"
                for m in misiones
            ) or f"<div style='color:{p['suave']}'>{html.escape(t('No cae en ninguna mision activa'))}</div>"
            cuerpo = (
                "<table cellpadding='0' cellspacing='0' width='100%'><tr>"
                f"<td><a style='color:{p['texto']};text-decoration:none' "
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
                + html.escape(t("y {n} reliquias mas ({disponibles} fuera de boveda), todas con "
                                "probabilidades mas bajas", n=len(resto), disponibles=disponibles))
                + "</div>"
            )
        return _seccion(t("Reliquias"), "reliquia") + "".join(tarjetas)

    def _bloque_contenido(self, reliquia_id: int) -> str:
        contenido = relaciones.contenido_de(self.con, reliquia_id, "Radiant")
        if not contenido:
            return ""
        p = PALETA
        filas = []
        for c in contenido:
            etiqueta = _con_padre(nombre_idioma(c), nombre_idioma(c, "padre"))
            color = color_rareza(c["rareza"])
            filas.append(
                f"<tr><td width='6' style='background:{color}'></td>"
                f"<td><a style='color:{p['texto']};text-decoration:none' "
                f"href='item:{c['item_id']}'>{html.escape(etiqueta)}</a></td>"
                f"<td>{glosario.enlace('rareza', _glosa(self.con, 'rareza', c['rareza']), color)}</td>"
                f"<td align='right'><b>{c['probabilidad']:.1f}%</b></td></tr>"
            )
        return _seccion(t("Contenido en Radiante"), "refinamiento") + _envolver(filas)

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
                    "reputacion", t("{standing} de reputacion", standing=f["standing"]), p["suave"]
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
            filas.append(
                f"<tr><td width='6' style='background:{color}'></td>"
                f"<td>{nombre}</td>"
                f"<td style='color:{p['suave']}'>{', '.join(extra)}</td>"
                f"<td>{glosario.enlace('rareza', _glosa(self.con, 'rareza', f['rareza']), color)}</td>"
                f"<td align='right'><b>{prob}</b></td>"
                f"<td align='right'>{tiempo}</td></tr>"
            )
        if sobran:
            filas.append(
                f"<tr><td colspan='6' style='color:{p['suave']}'>"
                f"{html.escape(t('y {n} sitios mas, con mas tiempo o menos probabilidad', n=sobran))}</td></tr>"
            )
        if pvp:
            maxima = max((f["probabilidad"] or 0) for f in pvp)
            filas.append(
                f"<tr><td colspan='6' style='color:{p['suave']}'>"
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
            f"<div style='margin-top:2px'>{html.escape(t('Cae en cualquier mision de'))} "
            f"<b>{planetas}</b>: {html.escape(t('lo sueltan los enemigos y los contenedores, sin porcentaje conocido.'))}</div>",
        ]
        if datos["nodos"]:
            rapidas = " &middot; ".join(
                f"<span style='color:{p['texto']}'>{html.escape(n['donde'])}</span> "
                f"({html.escape(n['mision'])}, ~{n['minutos']:.0f} min)"
                for n in datos["nodos"]
            )
            cuerpo.append(f"<div style='color:{p['suave']};margin-top:2px'>"
                          f"{html.escape(t('Misiones rapidas para farmearlo:'))} {rapidas}</div>")
        return _tarjeta("".join(cuerpo), p["acento"])


def _filas_visibles(grupo: list[dict]) -> list[dict]:
    """Las filas que pinta la tabla de fuentes: sin las de Conclave y con el tope por tipo."""
    return [f for f in grupo if f.get("motivo") != "pvp"][:MAX_FILAS_POR_TIPO]


def _con_padre(nombre: str, padre: str | None) -> str:
    """'Sistemas de Ash Prime' o 'Ash Prime Systems', segun el idioma."""
    return t("{nombre} de {padre}", nombre=nombre, padre=padre) if padre else nombre


def _seccion(titulo: str, clave_glosario: str | None = None) -> str:
    texto = (
        glosario.enlace(clave_glosario, titulo.upper(), PALETA["acento"])
        if clave_glosario
        else html.escape(titulo).upper()
    )
    return (
        f"<div style='color:{PALETA['acento']};font-size:12px;font-weight:bold;"
        f"margin-top:16px;margin-bottom:4px'>{texto}</div>"
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
    "reputacion": "reputacion",
    "diaria": "1 al dia",
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
        f"<tr><td width='4' style='background:{color}'></td>"
        f"<td style='background:{PALETA['panel2']}'>{cuerpo}</td></tr></table>"
    )


def _envolver(filas: list[str]) -> str:
    return (
        f"<table width='100%' cellspacing='0' cellpadding='6' style='background:{PALETA['panel2']}'>"
        + "".join(filas) + "</table>"
    )
