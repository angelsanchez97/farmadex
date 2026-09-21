"""Pestana Buscar: escribes algo y te dice de donde sale."""

from __future__ import annotations

import html
import sqlite3
import webbrowser

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
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
from ..datos import indice, items, relaciones
from ..datos.nodos import nombre_bonito
from ..idiomas import es_castellano, glosa, nombre as nombre_idioma, t
from . import glosario
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
        # (item_id, texto que se buscaba), para poder rehacer la busqueda al volver.
        self._historial: list[tuple[int, str]] = []
        # Mientras se vuelve atras no se apunta nada nuevo en el historial.
        self._volviendo = False
        self._actual: int | None = None
        self._datos_actuales: dict | None = None
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

        self.lista = QListWidget()
        self.lista.setMinimumWidth(300)
        self.lista.setItemDelegate(DelegadoResultado(self.lista))
        self.lista.setMouseTracking(True)
        self.lista.setUniformItemSizes(True)
        self.ficha = glosario.FichaConGlosario()
        self.ficha.setOpenLinks(False)
        self.ficha.anchorClicked.connect(self._enlace)

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
            self.ficha.setHtml(self._html(self._datos_actuales))
        elif self._sin_resultados is not None:
            self.ficha.setHtml(self._html_sin_resultados(self._sin_resultados))

    def retraducir(self) -> None:
        """Tras cambiar de idioma: textos fijos, lista de resultados y ficha abierta."""
        self.caja.setPlaceholderText(t("Busca un objeto, recurso, mod o pieza  (p. ej. sistemas ash prime)"))
        self.ocultar_vaulted.setText(t("Ocultar reliquias en boveda"))
        self.atras.setText(t("‹ Atras"))
        self.boton_objetivo.setText(t("+ Objetivo"))
        self.boton_set.setText(t("+ Set completo"))
        if self._resultados:
            self._pintar_resultados()
        self.repintar()

    def _imagen_lista(self, nombre: str) -> None:
        self.lista.viewport().update()
        if self._datos_actuales and self._datos_actuales["item"].get("imagen") == nombre:
            posicion = self.ficha.verticalScrollBar().value()
            self.ficha.setHtml(self._html(self._datos_actuales))
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
        elif texto.startswith("buscar:"):
            self.caja.setText(texto.removeprefix("buscar:"))
        elif texto.startswith("http"):
            webbrowser.open(texto)

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
        self.abrir(item_id, recordar=False)
        self.atras.setEnabled(len(self._historial) > 1)

    def _seleccionar_en_lista(self, item_id: int) -> None:
        """Deja marcado en la lista el objeto al que se vuelve, sin abrirlo otra vez."""
        for fila, resultado in enumerate(self._resultados):
            if resultado["item_id"] == item_id:
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
        self._actual = item_id
        self._datos_actuales = datos
        self._sin_resultados = None
        if recordar and (not self._historial or self._historial[-1][0] != item_id):
            # Se guarda con la busqueda que lo encontro, para poder rehacerla al volver.
            self._historial.append((item_id, self.caja.text().strip()))
            del self._historial[:-MAX_HISTORIAL]
        self.atras.setEnabled(len(self._historial) > 1)
        self.ficha.setHtml(self._html(datos))
        self.ficha.verticalScrollBar().setValue(0)
        self._consultar_precio(datos["item"])
        self.boton_objetivo.setEnabled(True)
        # El set solo tiene sentido en algo que se construye con piezas.
        self.boton_set.setEnabled(bool(datos["componentes"] or datos["padre"]))

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
            return
        self._resultados = indice.buscar(self.con, texto)
        self._pintar_resultados()
        self.estado.emit(t("{n} resultados", n=len(self._resultados)))
        if self._resultados:
            self.lista.setCurrentRow(0)
        else:
            # Sin resultados la ficha anterior no puede quedarse: se leeria como la
            # respuesta a lo que se acaba de escribir.
            self._vaciar_ficha()
            self._sin_resultados = texto
            self.ficha.setHtml(self._html_sin_resultados(texto))

    def _vaciar_ficha(self) -> None:
        self._actual = None
        self._datos_actuales = None
        self._sin_resultados = None
        self._slug_actual = ""
        self.ficha.clear()
        self.precios.hide()
        self.boton_objetivo.setEnabled(False)
        self.boton_set.setEnabled(False)

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
            self.abrir(self._resultados[fila]["item_id"])

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
        partes = [cabecera]
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
                + "</li>"
                for c in datos["componentes"]
            )
            partes.append(_seccion(t("Se construye con")) + f"<ul>{filas}</ul>")

        partes.append(self._bloque_ruta(item["id"]))
        partes.append(self._bloque_reliquias(item["id"]))
        if item["categoria"] == "Relics":
            partes.append(self._bloque_contenido(item["id"]))

        agrupadas: dict[str, list[dict]] = {}
        for f in datos["fuentes"]:
            if f["tipo"] != "reliquia":
                agrupadas.setdefault(f["tipo"], []).append(f)
        for tipo in ORDEN_TIPOS:
            grupo = agrupadas.get(tipo)
            if grupo:
                partes.append(_seccion(_glosa(con, "tipo_fuente", tipo)))
                partes.append(self._tabla_fuentes(grupo))

        if not datos["fuentes"] and not datos["componentes"]:
            partes.append(
                f"<p style='color:{p['suave']}'>"
                + html.escape(t("Sin fuentes registradas: puede venir de una mision de historia, "
                                "del mercado, de un evento o de un sindicato."))
                + "</p>"
            )
        if item["wiki_url"]:
            partes.append(
                f"<p style='margin-top:10px'><a style='color:{p['acento']}' "
                f"href='{html.escape(item['wiki_url'])}'>{html.escape(t('Abrir en la wiki'))} &rarr;</a></p>"
            )
        return "".join(partes)

    def _bloque_ruta(self, item_id: int) -> str:
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
                        html.escape(m["donde"]),
                        html.escape(m["mision"]),
                        _rotacion(self.con, m["rotacion"], p["texto"]),
                        f"{m['probabilidad']:.1f}%" if m["probabilidad"] else "",
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
        trozos = [f"<b>{html.escape(m.get('donde') or '')}</b>"]
        if m.get("mision"):
            trozos.append(html.escape(m["mision"]))
        if m.get("rotacion"):
            trozos.append(_rotacion(self.con, m["rotacion"], p["suave"]))
        if m.get("rareza"):
            trozos.append(glosario.enlace("rareza", _glosa(self.con, "rareza", m["rareza"]), color_rareza(m["rareza"])))
        prob = ruta.get("probabilidad")
        if prob:
            trozos.append(f"<b>{prob:.1f}%</b>")
        tipo = _glosa(self.con, "tipo_fuente", ruta.get("tipo"))
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
                f"<div style='color:{p['suave']}'>{html.escape(m['donde'])}"
                + (f" &middot; {html.escape(m['mision'])}" if m["mision"] else "")
                + (f" &middot; {_rotacion(self.con, m['rotacion'], p['suave'])}" if m["rotacion"] else "")
                + (f" &middot; {m['probabilidad']:.1f}%" if m["probabilidad"] else "")
                + "</div>"
                for m in misiones
            ) or f"<div style='color:{p['suave']}'>{html.escape(t('No cae en ninguna mision activa'))}</div>"
            cuerpo = (
                "<table cellpadding='0' cellspacing='0' width='100%'><tr>"
                f"<td><a style='color:{p['texto']};text-decoration:none' "
                f"href='item:{r['reliquia_id']}'><b style='font-size:15px'>{nombre}</b></a>"
                f" &nbsp;<span style='font-size:12px'>{glosario.enlace('boveda', estado, color)}</span></td>"
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

    def _tabla_fuentes(self, grupo: list[dict]) -> str:
        p = PALETA
        filas = []
        sobran = max(0, len(grupo) - MAX_FILAS_POR_TIPO)
        for f in grupo[:MAX_FILAS_POR_TIPO]:
            if f["nodo_en"]:
                planeta = nombre_idioma(f, "planeta")
                mision = _glosa(self.con, "mision", f["mision_en"])
                donde = f"{nombre_idioma(f, 'nodo')}, {planeta}".strip(", ")
                if mision:
                    donde += f" - {mision}"
            else:
                donde = nombre_bonito(self.con, f["origen_texto"])
            extra = []
            if f["rotacion"]:
                extra.append(_rotacion(self.con, f["rotacion"], p["suave"]))
            if f["etapa"]:
                extra.append(html.escape(str(f["etapa"])))
            if f["standing"]:
                extra.append(glosario.enlace(
                    "reputacion", t("{standing} de reputacion", standing=f["standing"]), p["suave"]
                ))
            if f["probabilidad_enemigo"]:
                extra.append(html.escape(t("tabla {prob}%", prob=f"{f['probabilidad_enemigo']:.1f}")))
            prob = f"{f['probabilidad']:.1f}%" if f["probabilidad"] is not None else ""
            color = color_rareza(f["rareza"])
            filas.append(
                f"<tr><td width='6' style='background:{color}'></td>"
                f"<td><b>{html.escape(donde)}</b></td>"
                f"<td style='color:{p['suave']}'>{', '.join(extra)}</td>"
                f"<td>{glosario.enlace('rareza', _glosa(self.con, 'rareza', f['rareza']), color)}</td>"
                f"<td align='right'><b>{prob}</b></td></tr>"
            )
        if sobran:
            filas.append(
                f"<tr><td colspan='5' style='color:{p['suave']}'>"
                f"{html.escape(t('y {n} sitios mas, con menos probabilidad', n=sobran))}</td></tr>"
            )
        return _envolver(filas)


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


def _rotacion(con, rotacion: str | None, color: str) -> str:
    """'Rotacion C' con su explicacion al pasar el raton; vacio si no hay rotacion."""
    if not rotacion:
        return ""
    return glosario.enlace("rotacion", _glosa(con, "rotacion", rotacion), color)


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
