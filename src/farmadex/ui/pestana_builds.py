"""Pestana Build: lee la pantalla de mejoras del arsenal y ensena lo que lleva.

Estilo C (maqueta C_herramientas_build.png): a la izquierda el equipo reconocido en su
pedestal, con "Builds en Overframe" y "Abrir ficha", y como se usa; a la derecha una
casilla por mod equipado y, debajo, los arcanos, lo que hay en la coleccion y lo que
se leyo sin reconocer. Cada mod, arcano o equipo reconocido abre su ficha en Buscar al
pulsarlo. Lo que el lector leyo pero no supo casar se ensena aparte, sin inventar nada.

Si se reconoce la warframe o el arma, "Builds en Overframe" abre las builds de la
comunidad de ese equipo en la pestana Web (ui/builds_overframe.py: solo se abre su web).
El boton de leer la pantalla va a la derecha de las sub-pestanas (`controles_cabecera`).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..captura.builds import Build
from ..config import cargar
from ..idiomas import t
from . import builds_overframe, colores_tipo, widgets
from .estilo_c import (
    BotonC,
    EtiquetaC,
    Insignia,
    PanelC,
    Pedestal,
    Tecla,
    columna,
    fila,
    hex_de,
    px,
    transparente,
)

CATEGORIA_ES = {
    "Warframes": "Warframe",
    "Primary": "Arma principal",
    "Secondary": "Arma secundaria",
    "Melee": "Cuerpo a cuerpo",
    "Arch-Gun": "Arch-gun",
    "Arch-Melee": "Arch-melee",
    "Archwing": "Archwing",
    "Sentinels": "Centinela",
    "SentinelWeapons": "Arma de centinela",
    "Pets": "Compañero",
    "Mods": "Mod",
    "Arcanes": "Arcano",
}
# Glifos (Segoe Fluent/MDL2) de los botones del equipo.
GLIFO_BUILD = ""
COLUMNAS_MODS = 4


class _Entrada:
    """Algo reconocido que se ensena (y se puede abrir): lo que las pruebas y la guia leen."""

    def __init__(self, item_id: int, nombre: str, categoria: str, puntuacion: float, widget: QWidget):
        self.item_id, self.nombre, self.categoria, self.puntuacion, self.widget = (
            item_id, nombre, categoria, puntuacion, widget)

    def texto(self) -> str:
        return f"{self.nombre} ({self.categoria})" if self.categoria else self.nombre


class PestanaBuilds(QWidget):
    abrir_item = Signal(int)
    pedir_lectura = Signal()
    # Direccion para ensenar dentro de Farmadex (pestana Web): las builds de Overframe.
    abrir_web = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.config = cargar()
        self.build: Build | None = None
        self.categorias: dict[int, str] = {}
        self.nombres_en: dict[int, str] = {}
        self.imagenes: dict[int, str] = {}
        self._entradas: list[_Entrada] = []
        self._sueltos: list[str] = []
        self._imagenes_pedidas: dict[str, list] = {}
        widgets.imagenes().lista.connect(self._imagen_lista)

        # -- boton de leer (a la derecha de las sub-pestanas) ----------------------------
        self.boton = BotonC(principal=True, icono="buscar", tam=11)
        self.boton.clicked.connect(self.pedir_lectura.emit)
        self.tecla_atajo = Tecla("")
        self.controles_cabecera = transparente(QWidget())
        self.controles_cabecera.setLayout(fila(self.boton, self.tecla_atajo, espacio=px(8, False)))

        # -- izquierda: el equipo -------------------------------------------------------
        self.panel_equipo = PanelC(t("Equipo"))
        self.pedestal = Pedestal(200)
        self.nombre_equipo = EtiquetaC("", "titulo", mayus=True, envolver=True)
        self.nombre_equipo.setAlignment(Qt.AlignCenter)
        self.nombre_equipo.hide()
        self.estado = EtiquetaC("", "pequeno", envolver=True)
        self.estado.setAlignment(Qt.AlignCenter)
        # Solo se ven con una warframe o un arma reconocida.
        self.boton_overframe = BotonC(icono=GLIFO_BUILD, tam=11)
        self.boton_overframe.clicked.connect(self._abrir_overframe)
        self.boton_overframe.hide()
        self.boton_ficha = BotonC(icono="derecha", tam=11)
        self.boton_ficha.clicked.connect(self._abrir_equipo)
        self.boton_ficha.hide()
        self.panel_equipo.capa.addLayout(fila(None, self.pedestal, None))
        self.panel_equipo.capa.addWidget(self.nombre_equipo)
        self.panel_equipo.capa.addWidget(self.estado)
        self.panel_equipo.capa.addLayout(fila(None, self.boton_overframe, self.boton_ficha, None, espacio=px(8, False)))

        self.panel_como = PanelC(t("Cómo se usa"), remate=False)
        self.nota = EtiquetaC("", "pequeno", envolver=True)
        self.panel_como.capa.addWidget(self.nota)

        # -- derecha: mods, arcanos, coleccion y lo no reconocido --------------------------
        self.panel_mods = PanelC(t("Mods equipados"))
        self.rejilla_mods = QGridLayout()
        self.rejilla_mods.setHorizontalSpacing(px(10, False))
        self.rejilla_mods.setVerticalSpacing(px(10, False))
        self.panel_mods.capa.addLayout(self.rejilla_mods)
        self.panel_arcanos = PanelC(t("Arcanos"), remate=False)
        self.panel_coleccion = PanelC(t("En la colección (abajo)"), remate=False)
        self.panel_sueltos = PanelC(t("Se leyó pero no se reconoció"), remate=False)
        self.capa_arcanos = columna(espacio=px(6, False))
        self.capa_coleccion = columna(espacio=px(6, False))
        self.capa_sueltos = columna(espacio=px(6, False))
        self.panel_arcanos.capa.addLayout(self.capa_arcanos)
        self.panel_coleccion.capa.addLayout(self.capa_coleccion)
        self.panel_sueltos.capa.addLayout(self.capa_sueltos)
        abajo = QHBoxLayout()
        abajo.setSpacing(px(12, False))
        for panel, peso in ((self.panel_arcanos, 4), (self.panel_coleccion, 4), (self.panel_sueltos, 3)):
            abajo.addWidget(panel, peso)
        for panel in (self.panel_mods, self.panel_arcanos, self.panel_coleccion, self.panel_sueltos):
            panel.hide()

        izquierda = columna(self.panel_equipo, self.panel_como, None, espacio=px(12, False))
        derecha = columna(self.panel_mods, abajo, None, espacio=px(12, False))
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(px(16, False))
        cuerpo.addLayout(izquierda, 4)
        cuerpo.addLayout(derecha, 7)
        contenido = transparente(QWidget())
        caja_contenido = QVBoxLayout(contenido)
        caja_contenido.setContentsMargins(0, px(4, False), px(4, False), 0)
        caja_contenido.addLayout(cuerpo)
        caja_contenido.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(contenido)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(area)
        self.retraducir()

    def conectar_indice(self, con) -> None:
        """Categorias, nombres ingleses e imagenes por id, para agrupar lo reconocido, para
        las builds de Overframe y para las casillas (se llama con el indice listo)."""
        try:
            filas = list(con.execute("SELECT id, categoria, nombre_en FROM items"))
        except Exception:  # noqa: BLE001 - sin categorias se lista todo junto
            filas = []
        self.categorias = {fila_i[0]: fila_i[1] for fila_i in filas}
        self.nombres_en = {fila_i[0]: fila_i[2] or "" for fila_i in filas}
        try:
            self.imagenes = {i: img for i, img in con.execute("SELECT id, imagen FROM items WHERE imagen IS NOT NULL")}
        except Exception:  # noqa: BLE001 - un indice sin imagenes: casillas con su rombo
            self.imagenes = {}

    def retraducir(self) -> None:
        atajo = self.config.get("hotkey_build", "")
        self.boton.setText(t("Leer la pantalla de mejoras"))
        self.boton.setToolTip(
            t("Leer la pantalla de mejoras ({atajo})", atajo=atajo) if atajo else t("Leer la pantalla de mejoras")
        )
        self.tecla_atajo.setText(atajo.upper())
        self.tecla_atajo.setVisible(bool(atajo))
        self.nota.setText(t(
            "En el juego, abre Arsenal > Mejorar de la warframe o el arma que quieras y pulsa el botón "
            "o el atajo. Farmadex lee los nombres de los mods de la pantalla y te deja pulsar cada uno "
            "para ver de dónde sale. Lo que no reconozca con seguridad lo deja aparte."
        ))
        for panel, titulo in ((self.panel_equipo, "Equipo"), (self.panel_como, "Cómo se usa"),
                              (self.panel_mods, "Mods equipados"), (self.panel_arcanos, "Arcanos"),
                              (self.panel_coleccion, "En la colección (abajo)"),
                              (self.panel_sueltos, "Se leyó pero no se reconoció")):
            panel.poner_titulo(t(titulo))
        self.boton_overframe.setText(t("Builds en Overframe"))
        self.boton_overframe.setToolTip(t("Abre Overframe, la web de builds de la comunidad, con este "
                                          "warframe o arma, dentro de Farmadex (pestaña Web)."))
        self.boton_ficha.setText(t("Abrir ficha"))
        self.boton_ficha.setToolTip(t("Abrir la ficha en Buscar"))
        if self.build is not None:
            self.mostrar_build(self.build)
        else:
            self.estado.setText(t("Todavía no has leído ninguna build. Abre la pantalla de mejoras en el "
                                  "juego y pulsa el botón de arriba."))

    def repintar(self) -> None:
        if self.build is not None:
            self.mostrar_build(self.build)

    # -- resultado -----------------------------------------------------------------

    def url_overframe(self) -> str:
        """Builds en Overframe del equipo reconocido; vacio sin equipo o si no tiene builds."""
        equipo = self.build.equipo if self.build is not None else None
        if equipo is None or not builds_overframe.tiene_builds(self.categorias.get(equipo.item_id)):
            return ""
        return builds_overframe.url_builds(self.nombres_en.get(equipo.item_id))

    def _abrir_overframe(self) -> None:
        url = self.url_overframe()
        if url:
            self.abrir_web.emit(url)

    def _abrir_equipo(self) -> None:
        equipo = self.build.equipo if self.build is not None else None
        if equipo is not None:
            self.abrir_item.emit(int(equipo.item_id))

    def _vaciar(self) -> None:
        self._entradas = []
        self._sueltos = []
        self._imagenes_pedidas.clear()
        for capa in (self.rejilla_mods, self.capa_arcanos, self.capa_coleccion, self.capa_sueltos):
            while capa.count():
                hijo = capa.takeAt(0)
                if hijo.widget() is not None:
                    hijo.widget().deleteLater()
        for panel in (self.panel_mods, self.panel_arcanos, self.panel_coleccion, self.panel_sueltos):
            panel.hide()

    def mostrar_build(self, build: Build) -> None:
        self.build = build
        self._vaciar()
        hay_overframe = bool(self.url_overframe())
        self.boton_overframe.setVisible(hay_overframe)
        self.boton_ficha.setVisible(build.equipo is not None)
        self.pedestal.poner_imagen(None)
        if build.equipo is not None:
            self.nombre_equipo.setText(build.equipo.nombre)
            self._entradas.append(_Entrada(build.equipo.item_id, build.equipo.nombre,
                                           self._categoria(build.equipo.item_id), build.equipo.puntuacion,
                                           self.panel_equipo))
            self._pixmap(self.imagenes.get(build.equipo.item_id), 256, self.pedestal.poner_imagen)
        elif build.equipo_texto:
            self.nombre_equipo.setText(t("\"{texto}\" (sin identificar)", texto=build.equipo_texto))
            self._sueltos.append(build.equipo_texto)
        else:
            self.nombre_equipo.setText("")
        self.nombre_equipo.setVisible(bool(self.nombre_equipo.texto_completo()))

        if build.vacia:
            self.estado.setText(t(
                "No se ha reconocido nada. Comprueba que la pantalla de mejoras está abierta y a la vista."
            ))
            self._pintar_sueltos(build.sin_identificar)
            return
        partes = []
        if build.equipo is not None:
            partes.append(build.equipo.nombre)
        partes.append(t("{n} mods", n=len(build.equipados) + len(build.coleccion)))
        if build.arcanos:
            partes.append(t("{n} arcanos", n=len(build.arcanos)))
        self.estado.setText(t("Leído: {resumen}. Pulsa cualquiera para ver de dónde sale.", resumen=", ".join(partes)))

        for i, r in enumerate(build.equipados):
            casilla = self._casilla_mod(r.item_id, r.nombre, r.puntuacion)
            self.rejilla_mods.addWidget(casilla, i // COLUMNAS_MODS, i % COLUMNAS_MODS)
        for c in range(COLUMNAS_MODS):
            self.rejilla_mods.setColumnStretch(c, 1)
        self.panel_mods.setVisible(bool(build.equipados))
        for r in build.arcanos:
            self.capa_arcanos.addWidget(self._fila_item(r.item_id, r.nombre, r.puntuacion))
        self.panel_arcanos.setVisible(bool(build.arcanos))
        for r in build.coleccion:
            self.capa_coleccion.addWidget(self._fila_item(r.item_id, r.nombre, r.puntuacion))
        self.panel_coleccion.setVisible(bool(build.coleccion))
        self._pintar_sueltos(build.sin_identificar)

    def _categoria(self, item_id: int) -> str:
        categoria = CATEGORIA_ES.get(self.categorias.get(item_id, ""), "")
        return t(categoria) if categoria else ""

    def _insignia(self, item_id: int) -> Insignia | None:
        categoria = self._categoria(item_id)
        if not categoria:
            return None
        tipo = colores_tipo.CATEGORIA_A_TIPO.get(self.categorias.get(item_id, ""), "otro")
        return Insignia(categoria, tinta=colores_tipo.color(tipo, hex_de("panel2")), tam=9)

    def _parecido(self, puntuacion: float) -> EtiquetaC | None:
        if puntuacion >= 100:
            return None
        return EtiquetaC(f"{t('parecido')} {puntuacion:.0f}%", "pequeno", tinta="aviso")

    def _imagen(self, item_id: int, lado: int) -> QLabel:
        etiqueta = QLabel()
        etiqueta.setAlignment(Qt.AlignCenter)
        etiqueta.setFixedSize(px(lado, False), px(lado, False))

        def poner(mapa: QPixmap | None, e=etiqueta, lado=lado) -> None:
            if mapa is None or mapa.isNull():
                e.setText("◇")
                e.setStyleSheet(f"background: transparent; color: {hex_de('tenue')}; font-size: {px(lado // 2)}px;")
                return
            e.setStyleSheet("background: transparent;")
            e.setPixmap(mapa.scaled(px(lado, False), px(lado, False), Qt.KeepAspectRatio, Qt.SmoothTransformation))

        self._pixmap(self.imagenes.get(item_id), 128, poner)
        return etiqueta

    def _casilla_mod(self, item_id: int, nombre: str, puntuacion: float) -> PanelC:
        """Casilla de un mod equipado: imagen, nombre, tipo y (si dudo) cuanto se parecia."""
        casilla = PanelC(remate=False, fondo="panel2", clicable=True)
        m = px(8, False)
        casilla.capa.setContentsMargins(m, m, m, m)
        casilla.capa.setSpacing(px(4, False))
        casilla.setToolTip(t("Abrir la ficha en Buscar"))
        casilla.pulsado.connect(lambda i=item_id: self.abrir_item.emit(int(i)))
        casilla.capa.addLayout(fila(None, self._imagen(item_id, 54), None))
        texto = EtiquetaC(nombre, "fuerte", envolver=True)
        texto.setAlignment(Qt.AlignCenter)
        casilla.capa.addWidget(texto)
        piezas = [w for w in (self._insignia(item_id), self._parecido(puntuacion)) if w is not None]
        casilla.capa.addLayout(fila(None, *piezas, None, espacio=px(6, False)))
        self._entradas.append(_Entrada(item_id, nombre, self._categoria(item_id), puntuacion, casilla))
        return casilla

    def _fila_item(self, item_id: int, nombre: str, puntuacion: float) -> PanelC:
        """Fila de un arcano o de un mod de la coleccion: imagen pequena, nombre y tipo."""
        fila_w = PanelC(remate=False, fondo="panel", borde="panel", chaflan=6, clicable=True)
        fila_w.capa.setContentsMargins(px(4, False), px(3, False), px(4, False), px(3, False))
        fila_w.setToolTip(t("Abrir la ficha en Buscar"))
        fila_w.pulsado.connect(lambda i=item_id: self.abrir_item.emit(int(i)))
        texto = EtiquetaC(nombre, "fuerte", recortar=True)
        texto.setToolTip(t("Abrir la ficha en Buscar"))
        # Sin insignia de tipo: el titulo del panel ya dice si son arcanos o mods, y el
        # nombre necesita el sitio. Si el lector dudo, se dice cuanto se parecia.
        capa = fila(self._imagen(item_id, 28), espacio=px(8, False))
        capa.addWidget(texto, 1)  # el nombre se queda con el sitio; si no cabe, se corta con "..."
        parecido = self._parecido(puntuacion)
        if parecido is not None:
            capa.addWidget(parecido)
        fila_w.capa.addLayout(capa)
        self._entradas.append(_Entrada(item_id, nombre, self._categoria(item_id), puntuacion, fila_w))
        return fila_w

    def _pintar_sueltos(self, textos: list[str]) -> None:
        for texto in textos:
            self.capa_sueltos.addWidget(EtiquetaC(texto, "normal", tinta="suave", recortar=True))
            self._sueltos.append(texto)
        if textos:
            self.capa_sueltos.addWidget(EtiquetaC(t("Busca su nombre en Buscar si lo necesitas."), "pequeno",
                                                  envolver=True))
        self.panel_sueltos.setVisible(bool(textos))

    # -- imagenes -------------------------------------------------------------------

    def _pixmap(self, nombre: str | None, lado: int, destino) -> None:
        """Pone la imagen si ya esta en disco; si no, se pide y se pone al llegar."""
        if not nombre:
            destino(None)
            return
        mapa = widgets.imagenes().pixmap(nombre, lado)
        destino(mapa)
        if mapa is None:
            self._imagenes_pedidas.setdefault(nombre, []).append((lado, destino))

    def _imagen_lista(self, nombre: str) -> None:
        for lado, destino in self._imagenes_pedidas.pop(nombre, []):
            try:
                destino(widgets.imagenes().pixmap(nombre, lado))
            except RuntimeError:
                pass  # la casilla ya se borro al leer otra build

    # -- para las pruebas y para la guia ---------------------------------------------

    def ids_listados(self) -> list[int]:
        """Los ids con ficha, en orden: equipo, equipados, arcanos y coleccion."""
        return [int(e.item_id) for e in self._entradas if e.item_id]

    def textos_listados(self) -> list[str]:
        """Lo que se ve escrito, en orden: "Vitalidad (Mod)"... y luego lo no reconocido."""
        return [e.texto() for e in self._entradas] + list(self._sueltos)

    def widget_de(self, item_id: int) -> QWidget | None:
        """La casilla o la fila que abre ese id (la primera, si sale dos veces)."""
        return next((e.widget for e in self._entradas if e.item_id == item_id), None)
