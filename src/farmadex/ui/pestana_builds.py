"""Pestana Build: lee la pantalla de mejoras del arsenal, dice si la build va bien y
propone una build basica.

Estilo C (maqueta C_herramientas_build.png): a la izquierda el equipo en su pedestal,
un buscador para elegirlo a mano, "Builds en Overframe", "Abrir ficha" y "Build basica
para..."; a la derecha los mods y los arcanos con la misma disposicion que la pantalla
de mejoras del juego (ui/rejilla_build.py: los 8 huecos, aura, exilus o postura y los
arcanos, a escala), "¿Esta bien mi build?" y, debajo, lo que diga la evaluacion o la
build basica, la coleccion y lo que se leyo sin reconocer. Los nombres van en el idioma
del juego (datos/nombres_juego.py). Arriba, una segunda vista: el diccionario de
aumentos y sindicatos (ui/diccionario_aumentos.py). Cada mod, arcano o equipo reconocido abre su ficha en Buscar al pulsarlo.
Lo que el lector leyo pero no supo casar se ensena aparte, sin inventar nada.

El equipo sale de la cabecera de la pantalla y, si no se reconocio (o sin leer nada),
se elige a mano en el buscador. Con equipo, "Builds en Overframe" abre las builds de la
comunidad de ese equipo en la pestana Web (ui/builds_overframe.py: solo se abre su web,
no se lee ni se copia nada de ella). La evaluacion y la build basica son reglas propias
sobre los datos del indice (datos/evaluar_build.py).
El boton de leer la pantalla va a la derecha de las sub-pestanas (`controles_cabecera`).
"""

from __future__ import annotations

import sqlite3
import time

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCompleter,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..captura.builds import Build
from ..config import cargar
from ..datos import aumentos, disposicion_build, evaluar_build, nombres_juego
from ..idiomas import es_castellano, t
from .campo_atajo import texto_legible, texto_tecla
from ..registro_log import obtener
from . import builds_overframe, colores_tipo, widgets
from .diccionario_aumentos import DiccionarioAumentos
from .rejilla_build import DatosCarta, RejillaBuild
from .estilo_c import (
    BotonC,
    DesplegableC,
    EtiquetaC,
    Insignia,
    PanelC,
    Pedestal,
    Rombo,
    SubPestanasC,
    Tecla,
    columna,
    fila,
    hex_de,
    px,
    transparente,
)

log = obtener("ui.builds")

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
    "Misc": "Arma exaltada",
}
# Lo que se puede elegir a mano: lo que tiene builds en Overframe.
CATEGORIAS_ELEGIBLES = tuple(sorted(builds_overframe.CATEGORIAS))
# Tipos de esas categorias que no son un equipo con build (piezas, recursos de mascota).
TIPOS_NO_ELEGIBLES = ("Pet Parts", "Pet Resource", "Zaw Component", "Kitgun Component", "Componente")
# Glifos (Segoe Fluent/MDL2) de los botones del equipo.
GLIFO_BUILD = ""
GLIFO_EVALUAR = ""
GLIFO_BASICA = ""


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
        self.con: sqlite3.Connection | None = None
        self.categorias: dict[int, str] = {}
        self.nombres_en: dict[int, str] = {}
        self.nombres_es: dict[int, str] = {}
        self.imagenes: dict[int, str] = {}
        self.unicos: dict[int, str] = {}
        self._elegibles: dict[str, int] = {}
        # Equipo elegido a mano en el buscador; manda sobre el leido hasta la proxima lectura.
        self.equipo_manual: int | None = None
        self.evaluacion: evaluar_build.Evaluacion | None = None
        self.basica: evaluar_build.BuildBasica | None = None
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
        # Buscador para elegir el warframe o el arma a mano (si no se reconocio o sin leer).
        self.selector = QLineEdit()
        self.selector.setClearButtonEnabled(True)
        self.completador = QCompleter(QStringListModel([], self), self.selector)
        self.completador.setCaseSensitivity(Qt.CaseInsensitive)
        self.completador.setFilterMode(Qt.MatchContains)
        self.completador.setMaxVisibleItems(12)
        self.selector.setCompleter(self.completador)
        self.completador.activated[str].connect(self._elegido_en_buscador)
        self.selector.returnPressed.connect(lambda: self._elegido_en_buscador(self.selector.text()))
        self._estilo_selector()
        # Siempre a la vista: sin equipo, llevan al buscador.
        self.boton_overframe = BotonC(icono=GLIFO_BUILD, tam=11)
        self.boton_overframe.clicked.connect(self._abrir_overframe)
        self.boton_ficha = BotonC(icono="derecha", tam=11)
        self.boton_ficha.clicked.connect(self._abrir_equipo)
        self.boton_ficha.hide()
        self.boton_basica = BotonC(icono=GLIFO_BASICA, tam=11)
        self.boton_basica.clicked.connect(self.mostrar_basica)
        self.panel_equipo.capa.addLayout(fila(None, self.pedestal, None))
        self.panel_equipo.capa.addWidget(self.nombre_equipo)
        self.panel_equipo.capa.addWidget(self.estado)
        self.panel_equipo.capa.addWidget(self.selector)
        self.panel_equipo.capa.addLayout(fila(None, self.boton_overframe, self.boton_ficha, None, espacio=px(8, False)))
        self.panel_equipo.capa.addLayout(fila(None, self.boton_basica, None))

        self.panel_como = PanelC(t("Cómo se usa"), remate=False)
        self.nota = EtiquetaC("", "pequeno", envolver=True)
        self.panel_como.capa.addWidget(self.nota)
        # En que idioma se ensenan los nombres de mods y arcanos: el del juego (se deduce
        # de lo leido) o el que se elija aqui.
        self.rotulo_idioma = EtiquetaC("", "pequeno", envolver=True)
        self.selector_idioma = DesplegableC()
        self.selector_idioma.currentIndexChanged.connect(self._idioma_elegido)
        self.panel_como.capa.addWidget(self.rotulo_idioma)
        self.panel_como.capa.addLayout(fila(self.selector_idioma, None))

        # -- derecha: mods, evaluacion, build basica, arcanos, coleccion y lo no reconocido --
        self.panel_mods = PanelC(t("Mods equipados"))
        # Los mods y los arcanos, con la disposicion de la pantalla de mejoras del juego.
        self.rejilla = RejillaBuild()
        self.rejilla.abrir_item.connect(lambda i: self.abrir_item.emit(int(i)))
        self.panel_mods.capa.addWidget(self.rejilla)
        self.colocacion = None
        # Lo que se sabe de los aumentos que lleva la build: sindicato, rango y coste.
        self.capa_aumentos = columna(espacio=px(4, False))
        self.panel_mods.capa.addLayout(self.capa_aumentos)
        self.boton_evaluar = BotonC(principal=True, icono=GLIFO_EVALUAR, tam=11)
        self.boton_evaluar.clicked.connect(self.mostrar_evaluacion)
        self.boton_evaluar.hide()
        self.panel_mods.capa.addLayout(fila(None, self.boton_evaluar))

        self.panel_evaluacion = PanelC(t("¿Está bien tu build?"))
        self.capa_bien = columna(espacio=px(6, False))
        self.capa_mal = columna(espacio=px(6, False))
        self.titulo_bien = EtiquetaC("", "fuerte", tinta="ok")
        self.titulo_mal = EtiquetaC("", "fuerte", tinta="aviso")
        dos = QHBoxLayout()
        dos.setSpacing(px(16, False))
        dos.addLayout(columna(self.titulo_bien, self.capa_bien, None, espacio=px(6, False)), 1)
        dos.addLayout(columna(self.titulo_mal, self.capa_mal, None, espacio=px(6, False)), 1)
        self.panel_evaluacion.capa.addLayout(dos)
        self.nota_evaluacion = EtiquetaC("", "pequeno", envolver=True)
        self.panel_evaluacion.capa.addWidget(self.nota_evaluacion)

        self.panel_basica = PanelC(t("Build básica"))
        self.capa_basica = QGridLayout()
        self.capa_basica.setHorizontalSpacing(px(12, False))
        self.capa_basica.setVerticalSpacing(px(6, False))
        self.panel_basica.capa.addLayout(self.capa_basica)
        self.nota_basica = EtiquetaC("", "pequeno", envolver=True)
        self.panel_basica.capa.addWidget(self.nota_basica)

        self.panel_arcanos = PanelC(t("Arcanos"), remate=False)
        self.panel_coleccion = PanelC(t("En la colección (abajo)"), remate=False)
        self.panel_sueltos = PanelC(t("Se leyó pero no se reconoció"), remate=False)
        self.capa_arcanos = columna(espacio=px(6, False))
        self.capa_coleccion = columna(espacio=px(6, False))
        self.capa_sueltos = columna(espacio=px(6, False))
        self.panel_arcanos.capa.addLayout(self.capa_arcanos)
        self.panel_coleccion.capa.addLayout(self.capa_coleccion)
        self.panel_sueltos.capa.addLayout(self.capa_sueltos)
        # Los tres paneles miden lo que el mas alto: su contenido, arriba.
        for panel in (self.panel_arcanos, self.panel_coleccion, self.panel_sueltos):
            panel.capa.addStretch(1)
        abajo = QHBoxLayout()
        abajo.setSpacing(px(12, False))
        for panel, peso in ((self.panel_arcanos, 4), (self.panel_coleccion, 4), (self.panel_sueltos, 3)):
            abajo.addWidget(panel, peso)
        for panel in (self.panel_mods, self.panel_evaluacion, self.panel_basica, self.panel_arcanos,
                      self.panel_coleccion, self.panel_sueltos):
            panel.hide()

        izquierda = columna(self.panel_equipo, self.panel_como, None, espacio=px(12, False))
        derecha = columna(self.panel_mods, self.panel_evaluacion, self.panel_basica, abajo, None,
                          espacio=px(12, False))
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(px(16, False))
        # La columna del equipo no crece mas de lo que necesita: el sitio es para la
        # rejilla, que con la ventana maximizada llega al tamano real del juego.
        for panel in (self.panel_equipo, self.panel_como):
            panel.setMaximumWidth(px(400, False))
        cuerpo.addLayout(izquierda, 4)
        cuerpo.addLayout(derecha, 9)
        contenido = transparente(QWidget())
        caja_contenido = QVBoxLayout(contenido)
        caja_contenido.setContentsMargins(0, px(4, False), px(4, False), 0)
        caja_contenido.addLayout(cuerpo)
        caja_contenido.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(contenido)
        # Dos vistas: la build leida y el diccionario de aumentos.
        self.vistas = SubPestanasC([("build", t("Mi build")), ("aumentos", t("Aumentos y sindicatos"))])
        self.vistas.cambiada.connect(self.ver)
        self.diccionario = DiccionarioAumentos()
        self.diccionario.abrir_item.connect(lambda i: self.abrir_item.emit(int(i)))
        self.pila = QStackedWidget()
        transparente(self.pila)
        self.pila.addWidget(area)
        self.pila.addWidget(self.diccionario)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(px(6, False))
        caja.addWidget(self.vistas)
        caja.addWidget(self.pila, 1)
        self.vistas.poner_activa("build")
        self.retraducir()

    def ver(self, clave: str) -> None:
        """Cambia entre la build leida ("build") y el diccionario de aumentos ("aumentos")."""
        self.vistas.poner_activa(clave)
        self.pila.setCurrentIndex(1 if clave == "aumentos" else 0)
        if clave == "aumentos":
            self.diccionario.cargar()

    def _idioma_elegido(self) -> None:
        codigo = self.selector_idioma.currentData()
        if not codigo or codigo == nombres_juego.elegido():
            return
        nombres_juego.elegir(codigo)
        self._idioma_cambiado()

    def _idioma_cambiado(self) -> None:
        """Los nombres del juego pasan a otro idioma: se vuelve a escribir todo lo que los lleva."""
        evaluar_build.olvidar_cache()
        self._poner_idiomas()
        if self.categorias:
            self._cargar_elegibles_seguro()
        if self.build is not None:
            self._pintar_de_nuevo()
        else:
            self._poner_equipo_visible()
        if self.diccionario._cargado:
            self.diccionario.retraducir()

    def _pintar_de_nuevo(self) -> None:
        evaluacion, basica = self.evaluacion, self.basica
        self.mostrar_build(self.build)
        if evaluacion is not None:
            self.mostrar_evaluacion()
        if basica is not None:
            self.mostrar_basica()

    def _poner_idiomas(self) -> None:
        self.rotulo_idioma.setText(t("Idioma de los nombres de mods y arcanos:"))
        self.selector_idioma.blockSignals(True)
        self.selector_idioma.clear()
        visto = nombres_juego.NOMBRE_IDIOMA.get(self.config.get("idioma_juego_visto") or "", "")
        auto = t("El del juego ({idioma})", idioma=visto) if visto else t("El del juego")
        self.selector_idioma.addItem(auto, nombres_juego.AUTOMATICO)
        for codigo in nombres_juego.IDIOMAS:
            self.selector_idioma.addItem(nombres_juego.NOMBRE_IDIOMA[codigo], codigo)
        self.selector_idioma.setCurrentIndex(max(0, self.selector_idioma.findData(nombres_juego.elegido())))
        self.selector_idioma.setToolTip(t(
            "Farmadex deduce el idioma del juego de lo que lee en la pantalla de mejoras. Si se equivoca, "
            "elígelo aquí."))
        self.selector_idioma.blockSignals(False)

    def _estilo_selector(self) -> None:
        self.selector.setStyleSheet(
            f"QLineEdit {{ background: {hex_de('panel2')}; color: {hex_de('texto')}; border: none;"
            f" border-bottom: 1px solid {hex_de('acento')}; padding: {px(6, False)}px {px(8, False)}px;"
            f" font-size: {px(13)}px; }}"
        )

    def conectar_indice(self, con) -> None:
        """Categorias, nombres e imagenes por id, para agrupar lo reconocido, para las builds
        de Overframe, para el buscador del equipo, para la evaluacion y para las casillas
        (se llama con el indice listo)."""
        self.con = con
        evaluar_build.olvidar_cache()
        nombres_juego.olvidar_cache()
        aumentos.olvidar_cache()
        self.diccionario.conectar_indice(con)
        # Auras y posturas: van en su hueco propio de la pantalla de mejoras.
        try:
            self.posturas = {i for (i,) in con.execute(
                "SELECT id FROM items WHERE categoria = 'Mods' AND tipo = 'Stance Mod'")}
        except Exception:  # noqa: BLE001
            self.posturas = set()
        try:
            self.auras = {i for (i,) in con.execute(
                "SELECT item_id FROM detalles WHERE datos LIKE '%\"compat\": \"AURA\"%'")}
        except Exception:  # noqa: BLE001 - indice sin detalles: no se distinguen
            self.auras = set()
        try:
            filas = list(con.execute("SELECT id, categoria, nombre_en FROM items"))
        except Exception:  # noqa: BLE001 - sin categorias se lista todo junto
            filas = []
        self.categorias = {fila_i[0]: fila_i[1] for fila_i in filas}
        self.nombres_en = {fila_i[0]: fila_i[2] or "" for fila_i in filas}
        try:
            self.nombres_es = {i: es or "" for i, es in con.execute("SELECT id, nombre_es FROM items")}
        except Exception:  # noqa: BLE001 - indice sin castellano: se usa el ingles
            self.nombres_es = {}
        try:
            self.unicos = {i: u for i, u in con.execute("SELECT id, unique_name FROM items")}
        except Exception:  # noqa: BLE001
            self.unicos = {}
        try:
            self.imagenes = {i: img for i, img in con.execute("SELECT id, imagen FROM items WHERE imagen IS NOT NULL")}
        except Exception:  # noqa: BLE001 - un indice sin imagenes: casillas con su rombo
            self.imagenes = {}
        self._cargar_elegibles(con)

    def _cargar_elegibles(self, con) -> None:
        """Los warframes, armas, archwings y companeros del buscador: "Nombre (Tipo)"."""
        marcas = ", ".join("?" for _ in CATEGORIAS_ELEGIBLES)
        try:
            filas = list(con.execute(
                f"SELECT id, categoria, tipo FROM items WHERE categoria IN ({marcas}) AND padre_id IS NULL",
                CATEGORIAS_ELEGIBLES))
        except Exception:  # noqa: BLE001 - indice minimo (pruebas): sin tipo ni padre
            filas = [(i, c, "") for i, c in self.categorias.items() if c in CATEGORIAS_ELEGIBLES]
        self._elegibles = {}
        for item_id, categoria, tipo in filas:
            if tipo in TIPOS_NO_ELEGIBLES or "/Recipes/" in (self.unicos.get(item_id) or ""):
                continue
            etiqueta = f"{self.nombre_de(item_id)} ({t(CATEGORIA_ES.get(categoria, categoria))})"
            self._elegibles.setdefault(etiqueta, item_id)
        self.completador.model().setStringList(sorted(self._elegibles, key=str.lower))

    def nombre_de(self, item_id: int | None, respaldo: str = "") -> str:
        """El nombre en el idioma del juego (datos/nombres_juego.py): el lector puede haber
        casado otro idioma, y la interfaz puede estar en uno distinto al del juego."""
        if not item_id:
            return respaldo
        es, en = self.nombres_es.get(item_id), self.nombres_en.get(item_id)
        if self.con is not None:
            try:
                return nombres_juego.nombre(self.con, item_id, es or en or respaldo)
            except Exception:  # noqa: BLE001 - conexion cerrada: lo que haya en memoria
                pass
        if es_castellano():
            return es or en or respaldo
        return en or es or respaldo

    def retraducir(self) -> None:
        crudo = self.config.get("hotkey_build", "")
        atajo = texto_legible(crudo) if crudo else ""
        self.boton.setText(t("Leer la pantalla de mejoras"))
        self.boton.setToolTip(
            t("Leer la pantalla de mejoras ({atajo})", atajo=atajo) if atajo else t("Leer la pantalla de mejoras")
        )
        self.tecla_atajo.setText(texto_tecla(crudo) if crudo else "")
        self.tecla_atajo.setVisible(bool(atajo))
        self.nota.setText(t(
            "En el juego, abre Arsenal > Mejorar de la warframe o el arma que quieras y pulsa el botón "
            "o el atajo. Farmadex lee los nombres de los mods de la pantalla y te deja pulsar cada uno "
            "para ver de dónde sale. Lo que no reconozca con seguridad lo deja aparte."
        ))
        for panel, titulo in ((self.panel_equipo, "Equipo"), (self.panel_como, "Cómo se usa"),
                              (self.panel_mods, "Mods equipados"), (self.panel_arcanos, "Arcanos"),
                              (self.panel_coleccion, "En la colección (abajo)"),
                              (self.panel_sueltos, "Se leyó pero no se reconoció"),
                              (self.panel_evaluacion, "¿Está bien tu build?")):
            panel.poner_titulo(t(titulo))
        self.vistas.poner_texto("build", t("Mi build"))
        self.vistas.poner_texto("aumentos", t("Aumentos y sindicatos"))
        self._poner_idiomas()
        self.diccionario.retraducir()
        self.selector.setPlaceholderText(t("Elegir warframe o arma a mano…"))
        self.selector.setToolTip(t("Escribe parte del nombre y elige de la lista."))
        self.boton_overframe.setText(t("Builds en Overframe"))
        self.boton_overframe.setToolTip(t("Abre Overframe, la web de builds de la comunidad, con este "
                                          "warframe o arma, dentro de Farmadex (pestaña Web)."))
        self.boton_ficha.setText(t("Abrir ficha"))
        self.boton_ficha.setToolTip(t("Abrir la ficha en Buscar"))
        self.boton_evaluar.setText(t("¿Está bien mi build?"))
        self.boton_evaluar.setToolTip(t("Revisa la build leída con reglas de sentido común."))
        self.titulo_bien.setText(t("Lo que está bien"))
        self.titulo_mal.setText(t("Lo que falta o sobra"))
        self.nota_evaluacion.setText(t(
            "Es una guía orientativa hecha con reglas sencillas sobre los datos del juego, no una "
            "verdad absoluta: hay builds buenas que se saltan estas reglas a propósito."))
        self._poner_texto_basica()
        # En otro idioma cambian los nombres del buscador.
        if self.categorias:
            self._cargar_elegibles_seguro()
        if self.build is not None:
            self.mostrar_build(self.build)
        else:
            self.estado.setText(t("Todavía no has leído ninguna build. Abre la pantalla de mejoras en el "
                                  "juego y pulsa el botón de arriba, o elige el equipo a mano."))
            self._poner_equipo_visible()
        if self.evaluacion is not None:
            self.mostrar_evaluacion()
        if self.basica is not None:
            self.mostrar_basica()

    def _cargar_elegibles_seguro(self) -> None:
        if self.con is not None:
            try:
                self._cargar_elegibles(self.con)
            except Exception:  # noqa: BLE001 - conexion cerrada: el buscador se queda como estaba
                log.debug("No se pudo recargar el buscador de equipo", exc_info=True)

    def repintar(self) -> None:
        self._estilo_selector()
        self.diccionario.repintar()
        if self.build is not None:
            self.mostrar_build(self.build)

    # -- el equipo: leido o elegido a mano -------------------------------------------------

    def equipo_actual(self) -> int | None:
        """El id del warframe o arma: el elegido a mano, si lo hay; si no, el leido."""
        if self.equipo_manual:
            return self.equipo_manual
        equipo = self.build.equipo if self.build is not None else None
        return int(equipo.item_id) if equipo is not None else None

    def elegir_equipo(self, item_id: int | None) -> None:
        """Pone el equipo a mano (el buscador lo llama; las pruebas tambien)."""
        self.equipo_manual = int(item_id) if item_id else None
        self.evaluacion = None
        self.basica = None
        self.panel_evaluacion.hide()
        self.panel_basica.hide()
        self._poner_equipo_visible()
        if self.equipo_manual:
            self.estado.setText(t("Elegido a mano: {nombre}. Ya puedes abrir sus builds en Overframe o pedir "
                                  "una build básica.", nombre=self.nombre_de(self.equipo_manual)))

    def _elegido_en_buscador(self, texto: str) -> None:
        texto = (texto or "").strip()
        item_id = self._elegibles.get(texto)
        if item_id is None and texto:
            # Escrito sin elegir de la lista: si solo hay uno que lo contenga, ese.
            posibles = [v for k, v in self._elegibles.items() if texto.lower() in k.lower()]
            item_id = posibles[0] if len(set(posibles)) == 1 else None
        if item_id is None:
            return
        self.elegir_equipo(item_id)

    def _poner_equipo_visible(self) -> None:
        """Nombre, imagen y botones segun el equipo actual (leido o elegido)."""
        item_id = self.equipo_actual()
        self.boton_ficha.setVisible(item_id is not None)
        self.boton_overframe.setVisible(True)
        hay_web = bool(self.url_overframe())
        self.boton_overframe.setToolTip(
            t("Abre Overframe, la web de builds de la comunidad, con este warframe o arma, dentro de "
              "Farmadex (pestaña Web).") if hay_web else
            t("Primero elige un warframe o arma en el buscador de arriba."))
        clase = evaluar_build.clase_de_equipo(self.categorias.get(item_id), self._tipo_de(item_id)) if item_id else "otro"
        self.boton_basica.setVisible(True)
        self.boton_basica.setEnabled(item_id is None or clase != "otro")
        self._poner_texto_basica()
        if item_id is not None and self.equipo_manual:
            self.nombre_equipo.setText(self.nombre_de(item_id))
            self.nombre_equipo.show()
            self.pedestal.poner_imagen(None)
            self._pixmap(self.imagenes.get(item_id), 256, self.pedestal.poner_imagen)
        self._actualizar_boton_evaluar()

    def _tipo_de(self, item_id: int | None) -> str:
        if not item_id or self.con is None:
            return ""
        try:
            fila_t = self.con.execute("SELECT tipo FROM items WHERE id = ?", (item_id,)).fetchone()
        except Exception:  # noqa: BLE001
            return ""
        return (fila_t[0] or "") if fila_t else ""

    def _poner_texto_basica(self) -> None:
        item_id = self.equipo_actual()
        if item_id:
            self.boton_basica.setText(t("Build básica para {nombre}", nombre=self.nombre_de(item_id)))
            self.boton_basica.setToolTip(t("Una build de inicio con mods comunes y fáciles de conseguir."))
        else:
            self.boton_basica.setText(t("Build básica para…"))
            self.boton_basica.setToolTip(t("Primero elige un warframe o arma en el buscador de arriba."))
        self.panel_basica.poner_titulo(t("Build básica para {nombre}", nombre=self.nombre_de(item_id))
                                       if item_id else t("Build básica"))

    def _actualizar_boton_evaluar(self) -> None:
        hay_mods = self.build is not None and bool(self.build.equipados)
        self.boton_evaluar.setVisible(hay_mods)

    # -- resultado -----------------------------------------------------------------

    def url_overframe(self) -> str:
        """Builds en Overframe del equipo actual; vacio sin equipo o si no tiene builds."""
        item_id = self.equipo_actual()
        if item_id is None or not builds_overframe.tiene_builds(self.categorias.get(item_id)):
            return ""
        return builds_overframe.url_builds(self.nombres_en.get(item_id))

    def _abrir_overframe(self) -> None:
        url = self.url_overframe()
        if url:
            self.abrir_web.emit(url)
            return
        # Sin equipo (o sin builds): se lleva al buscador para elegirlo.
        self.selector.setFocus()
        self.estado.setText(t("Elige el warframe o el arma en el buscador y vuelve a pulsar."))

    def _abrir_equipo(self) -> None:
        item_id = self.equipo_actual()
        if item_id is not None:
            self.abrir_item.emit(int(item_id))

    def _vaciar(self) -> None:
        self._entradas = []
        self._sueltos = []
        self._imagenes_pedidas.clear()
        self.rejilla.vaciar()
        for capa in (self.capa_aumentos, self.capa_arcanos, self.capa_coleccion, self.capa_sueltos):
            _vaciar_capa(capa)
        for panel in (self.panel_mods, self.panel_arcanos, self.panel_coleccion, self.panel_sueltos):
            panel.hide()

    def mostrar_build(self, build: Build) -> None:
        inicio = time.perf_counter()
        try:
            self._mostrar_build(build)
        finally:
            log.info("Build pintada en %.0f ms", (time.perf_counter() - inicio) * 1000)

    def _mostrar_build(self, build: Build) -> None:
        nueva = build is not self.build
        self.build = build
        if nueva:
            self._apuntar_idioma(build)
            # Una lectura nueva manda: si reconocio el equipo, se olvida el elegido a mano.
            if build.equipo is not None:
                self.equipo_manual = None
            self.evaluacion = None
            self.basica = None
            self.panel_evaluacion.hide()
            self.panel_basica.hide()
        self._vaciar()
        self.pedestal.poner_imagen(None)
        if build.equipo is not None and not self.equipo_manual:
            nombre = self.nombre_de(build.equipo.item_id, build.equipo.nombre)
            self.nombre_equipo.setText(nombre)
            self._entradas.append(_Entrada(build.equipo.item_id, nombre,
                                           self._categoria(build.equipo.item_id), build.equipo.puntuacion,
                                           self.panel_equipo))
            self._pixmap(self.imagenes.get(build.equipo.item_id), 256, self.pedestal.poner_imagen)
        elif build.equipo_texto and not self.equipo_manual:
            self.nombre_equipo.setText(t("\"{texto}\" (sin identificar)", texto=build.equipo_texto))
            self._sueltos.append(build.equipo_texto)
        elif not self.equipo_manual:
            self.nombre_equipo.setText("")
        self.nombre_equipo.setVisible(bool(self.nombre_equipo.texto_completo()))
        self._poner_equipo_visible()

        if build.vacia:
            self.estado.setText(t(
                "No se ha reconocido nada. Comprueba que la pantalla de mejoras está abierta y a la vista."
            ))
            self._pintar_sueltos(build.sin_identificar)
            return
        partes = []
        if build.equipo is not None:
            partes.append(self.nombre_de(build.equipo.item_id, build.equipo.nombre))
        partes.append(t("{n} mods", n=len(build.equipados) + len(build.coleccion)))
        if build.arcanos:
            partes.append(t("{n} arcanos", n=len(build.arcanos)))
        texto = t("Leído: {resumen}. Pulsa cualquiera para ver de dónde sale.", resumen=", ".join(partes))
        if build.equipo is None and not self.equipo_manual:
            texto += " " + t("No se reconoció el equipo: elígelo a mano en el buscador.")
        self.estado.setText(texto)

        self._pintar_rejilla(build)
        self.panel_mods.setVisible(bool(build.equipados or build.arcanos))
        self._actualizar_boton_evaluar()
        self.panel_arcanos.hide()  # los arcanos van en la rejilla, en su sitio
        for r in build.coleccion:
            self.capa_coleccion.addWidget(self._fila_item(r.item_id, self.nombre_de(r.item_id, r.nombre), r.puntuacion))
        self.panel_coleccion.setVisible(bool(build.coleccion))
        self._pintar_sueltos(build.sin_identificar)

    # -- la rejilla, como en el juego ----------------------------------------------------

    def _apuntar_idioma(self, build: Build) -> None:
        """Deduce el idioma del juego de lo leido y lo apunta; si cambia, se nota en todo."""
        if self.con is None:
            return
        try:
            leidos = [(r.texto_ocr, r.item_id) for r in build.equipados + build.coleccion + build.arcanos]
            visto = nombres_juego.detectar(self.con, leidos, getattr(build, "idioma", "") or "")
            if visto and nombres_juego.apuntar_visto(visto):
                log.info("Idioma del juego visto en la pantalla de mejoras: %s", visto)
                evaluar_build.olvidar_cache()
                self._poner_idiomas()
                self._cargar_elegibles_seguro()
        except Exception:  # noqa: BLE001 - sin idioma deducido se sigue con el que hubiera
            log.debug("No se pudo deducir el idioma del juego", exc_info=True)

    def clase_de_disposicion(self) -> str:
        """La plantilla de huecos del equipo actual ("warframe", "arma", "cuerpo" o "")."""
        item_id = self.equipo_actual()
        if not item_id:
            return ""
        return disposicion_build.plantilla_de(self.categorias.get(item_id), self._tipo_de(item_id))

    def _rareza(self, item_id: int) -> str:
        if self.con is None:
            return ""
        try:
            datos = evaluar_build._detalles(self.con, int(item_id))
        except Exception:  # noqa: BLE001
            return ""
        return ((datos.get("mod") or datos.get("arcano") or {}).get("rareza")) or ""

    def _tipo_de_mod(self, item_id: int) -> str:
        if item_id in getattr(self, "auras", ()):
            return "aura"
        if item_id in getattr(self, "posturas", ()):
            return "postura"
        return "mod"

    def _pintar_rejilla(self, build: Build) -> None:
        ancho, alto = getattr(build, "ancho", 0), getattr(build, "alto", 0)
        puntos = [disposicion_build.punto_de(r.caja, ancho, alto, self._tipo_de_mod(r.item_id))
                  for r in build.equipados]
        puntos_arcanos = [disposicion_build.punto_de(r.caja, ancho, alto, "arcano") for r in build.arcanos]
        self.colocacion = disposicion_build.colocar(self.clase_de_disposicion(), puntos, puntos_arcanos)
        rangos = None
        cartas_mods, cartas_arcanos = [], []
        for lista, salida, es_arcano in ((build.equipados, cartas_mods, False), (build.arcanos, cartas_arcanos, True)):
            for r in lista:
                nombre = self.nombre_de(r.item_id, r.nombre)
                ayuda = ""
                if not es_arcano and aumentos.de(self.con, r.item_id) is not None:
                    if rangos is None:
                        rangos = aumentos.rangos_del_perfil()
                    lineas = aumentos.lineas(self.con, r.item_id, rangos)
                    ayuda = "\n".join(texto for texto, _tinta in lineas)
                    self._fila_aumento(nombre, lineas)
                salida.append(DatosCarta(int(r.item_id), nombre, self._rareza(r.item_id), None, r.puntuacion,
                                         es_arcano, ayuda))
        self.rejilla.poner(self.colocacion, cartas_mods, cartas_arcanos)
        for lista in (build.equipados, build.arcanos):
            for r in lista:
                carta = self.rejilla.carta_de(r.item_id)
                if carta is None:
                    continue
                self._entradas.append(_Entrada(r.item_id, carta.datos.nombre, self._categoria(r.item_id),
                                               r.puntuacion, carta))
                self._pixmap(self.imagenes.get(r.item_id), 256, carta.poner_imagen)

    def _fila_aumento(self, nombre: str, lineas: list[tuple[str, str]]) -> None:
        """Debajo de la rejilla: de quien es el aumento y donde se compra."""
        self.capa_aumentos.addWidget(EtiquetaC(f"{nombre}: {lineas[0][0]}", "fuerte", envolver=True))
        for texto, tinta in lineas[1:]:
            self.capa_aumentos.addWidget(EtiquetaC(texto, "pequeno", tinta=tinta or None, envolver=True))

    # -- ¿esta bien mi build? ------------------------------------------------------------

    def mostrar_evaluacion(self) -> None:
        """Evalua la build leida con el equipo actual y lo pinta."""
        if self.con is None or self.build is None:
            return
        try:
            self.evaluacion = evaluar_build.evaluar(
                self.con, self.equipo_actual(), [int(r.item_id) for r in self.build.equipados],
                [int(r.item_id) for r in self.build.arcanos], self.build.capacidad)
        except Exception:  # noqa: BLE001 - un indice raro no puede tumbar la pestana
            log.exception("Fallo evaluando la build")
            return
        _vaciar_capa(self.capa_bien)
        _vaciar_capa(self.capa_mal)
        for punto in self.evaluacion.bien:
            self.capa_bien.addWidget(self._fila_punto(punto, "ok"))
        for punto in self.evaluacion.mal:
            self.capa_mal.addWidget(self._fila_punto(punto, "aviso"))
        if not self.evaluacion.bien:
            self.capa_bien.addWidget(EtiquetaC(t("Nada que destacar todavía."), "pequeno", envolver=True))
        if not self.evaluacion.mal:
            self.capa_mal.addWidget(EtiquetaC(t("No veo nada que falte ni que sobre."), "pequeno", envolver=True))
        self.panel_evaluacion.show()

    def _fila_punto(self, punto: evaluar_build.Punto, tinta: str) -> QWidget:
        caja = transparente(QWidget())
        capa = QHBoxLayout(caja)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(px(8, False))
        capa.addWidget(Rombo(7, tinta), 0, Qt.AlignTop)
        textos = columna(espacio=px(2, False))
        textos.addWidget(EtiquetaC(punto.texto, "normal", envolver=True))
        if punto.porque:
            textos.addWidget(EtiquetaC(punto.porque, "pequeno", envolver=True))
        capa.addLayout(textos, 1)
        return caja

    # -- build basica ---------------------------------------------------------------------

    def mostrar_basica(self) -> None:
        """Propone una build de inicio para el equipo actual y marca lo que ya tienes."""
        item_id = self.equipo_actual()
        if item_id is None:
            self.selector.setFocus()
            self.estado.setText(t("Elige el warframe o el arma en el buscador y vuelve a pulsar."))
            return
        if self.con is None:
            return
        tengo, objetivos = self._poseidos()
        try:
            self.basica = evaluar_build.build_basica(self.con, item_id, tengo, objetivos)
        except Exception:  # noqa: BLE001
            log.exception("Fallo proponiendo la build basica")
            return
        _vaciar_capa(self.capa_basica)
        self._poner_texto_basica()
        if self.basica.sin_datos or not self.basica.huecos:
            aviso = (t("Faltan los datos de los mods: actualiza los datos del juego en Ajustes > Datos.")
                     if self.basica.sin_datos else
                     t("Para este tipo de equipo todavía no hay build básica."))
            self.capa_basica.addWidget(EtiquetaC(aviso, "normal", envolver=True), 0, 0, 1, 3)
        for fila_i, hueco in enumerate(self.basica.huecos):
            rol = EtiquetaC(hueco.rol, "pequeno")
            rol.setToolTip(hueco.porque)
            self.capa_basica.addWidget(rol, fila_i, 0)
            if hueco.mod is None:
                self.capa_basica.addWidget(EtiquetaC(t("No encuentro un mod sencillo para esto."), "pequeno"),
                                           fila_i, 1)
                continue
            casilla = self._fila_item(hueco.mod.item_id, self.nombre_de(hueco.mod.item_id, hueco.mod.nombre), 100.0,
                                      apuntar=False)
            casilla.setToolTip(f"{hueco.porque}\n{t('Pulsa para ver de dónde sale.')}")
            self.capa_basica.addWidget(casilla, fila_i, 1)
            if hueco.tienes:
                marca = EtiquetaC(t("La tienes"), "pequeno", tinta="ok")
            elif hueco.en_objetivos:
                marca = EtiquetaC(t("En tus objetivos"), "pequeno", tinta="acento")
            else:
                marca = EtiquetaC(t("Te falta"), "pequeno", tinta="aviso")
            self.capa_basica.addWidget(marca, fila_i, 2)
        self.capa_basica.setColumnStretch(1, 1)
        self.nota_basica.setText(t(
            "Mods comunes y fáciles de conseguir, elegidos según las estadísticas de tu equipo. \"La tienes\" "
            "sale de lo que Farmadex ha leído en pantalla y de tu inventario. Pulsa un mod para ver dónde se "
            "consigue. Es una guía orientativa para empezar, no la mejor build posible."))
        self.panel_basica.show()

    def _poseidos(self) -> tuple[set[int], set[int]]:
        """Los mods que sabes que tienes (los leidos en pantalla y el inventario leido) y los
        que estan en tus objetivos. Solo se lee: nada se escribe."""
        tengo: set[int] = set()
        if self.build is not None:
            tengo |= {int(r.item_id) for r in self.build.equipados + self.build.coleccion}
        objetivos: set[int] = set()
        por_unico = {u: i for i, u in self.unicos.items() if u}
        try:
            from ..estado import usuario_db

            ruta = usuario_db.RUTA_USUARIO_DB
            if not ruta.exists():
                return tengo, objetivos
            usuario = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
            try:
                try:
                    for (unico,) in usuario.execute("SELECT unique_name FROM inventario_lecturas WHERE cantidad > 0"):
                        if unico in por_unico:
                            tengo.add(por_unico[unico])
                except sqlite3.Error:
                    pass
                try:
                    for (unico,) in usuario.execute(
                            "SELECT item_unique_name FROM objetivos WHERE completado_en IS NULL"):
                        if unico in por_unico:
                            objetivos.add(por_unico[unico])
                except sqlite3.Error:
                    pass
            finally:
                usuario.close()
        except Exception:  # noqa: BLE001 - sin datos del usuario, solo lo leido en pantalla
            log.debug("No se pudo leer el inventario para la build basica", exc_info=True)
        return tengo, objetivos

    # -- piezas ----------------------------------------------------------------------------

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

    def _fila_item(self, item_id: int, nombre: str, puntuacion: float, apuntar: bool = True) -> PanelC:
        """Fila de un arcano o de un mod de la coleccion: imagen pequena, nombre y tipo.
        Con `apuntar`, entra en lo listado (las de la build basica no: no se leyeron)."""
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
        if apuntar:
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


def _vaciar_capa(capa) -> None:
    while capa.count():
        hijo = capa.takeAt(0)
        if hijo.widget() is not None:
            hijo.widget().deleteLater()
        elif hijo.layout() is not None:
            _vaciar_capa(hijo.layout())
