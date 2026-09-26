"""La pagina "Personalizar y avisos" de la pestana Mundo: que bloques se ven y que avisa Farmadex.

Vive dentro de la propia pestana (no en Ajustes ni en una ventana aparte): lo que
cambia aqui afecta solo a Mundo, asi que es donde uno lo busca. Cada interruptor se
guarda al momento en la configuracion. Tres columnas, como en la maqueta C: que
bloques ensenar, de que avisar y los detalles de esos avisos (tipos de fisura, eras,
palabras de las invasiones, tipos de arbitraje).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QFrame,
    QLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..config import cargar, guardar
from ..idiomas import glosa, t
from ..online import avisos_mundo
from .estilo_c import (
    COLOR_ERA,
    ICONOS,
    BotonC,
    EtiquetaC,
    Interruptor,
    PanelC,
    columna,
    fila,
    hex_de,
    icono,
    px,
    transparente,
)

CLAVE_OCULTAS = "mundo_secciones_ocultas"

# Los bloques que se pueden esconder, con una frase que diga que son. La clave "ahora"
# era la franja de un vistazo de la disposicion en lista; en el diseno C es el panel HOY.
SECCIONES = (
    ("ahora", "Hoy de un vistazo: incursión, arcontes, onda nocturna y arbitraje"),
    ("ciclos", "Ciclos"),
    ("objetivos", "Fisuras para tus metas"),
    ("fisuras", "Fisuras del Vacío"),
    ("acero", "Fisuras del Camino de Acero"),
    ("tormentas", "Tormentas del Vacío"),
    ("sortie", "Incursión y arcontes"),
    ("baro", "Baro Ki'Teer"),
    ("teshin", "Teshin · Camino de Acero"),
    ("invasiones", "Invasiones y alertas"),
    ("nightwave", "Onda nocturna"),
)

# Glifos de la fuente de iconos de Windows para cada aviso (misma posicion en Fluent y MDL2).
_RAYO, _TIENDA, _ESTRELLA, _RELOJ, _GRUPO, _INFO, _LUNA = (
    "", "", "", "", "", "", "")

# Avisos de una sola casilla (clave de avisos_mundo.POR_DEFECTO -> texto, icono).
AVISOS_VENDEDORES = (
    ("baro", "Llegue Baro Ki'Teer", _TIENDA),
    ("baro_objetivo", "Baro traiga algo de mis metas", _TIENDA),
    ("teshin_kuva", "Teshin ofrezca Kuva esta semana", _ESTRELLA),
    ("teshin_umbra", "Teshin ofrezca Forma Umbra esta semana", _ESTRELLA),
    ("teshin_cambio", "Cada semana, lo que ofrezca Teshin", _ESTRELLA),
    ("palladino", "Recordatorio semanal: Kuva de Palladino", _RELOJ),
)
AVISOS_OTROS = (
    ("alertas", "Alertas nuevas", _INFO),
    ("incursion", "Incursión nueva (cada día)", _INFO),
    ("arcontes", "Caza de arcontes nueva (cada semana)", _INFO),
    ("noche_cetus", "Se haga de noche en Cetus", _LUNA),
)
# Por debajo de este ancho las tres columnas se ponen una debajo de otra.
ANCHO_TRES_COLUMNAS = 980


def ocultas(config: dict) -> set[str]:
    valor = config.get(CLAVE_OCULTAS) or []
    return {str(x) for x in valor} if isinstance(valor, (list, tuple)) else set()


class Flujo(QLayout):
    """Coloca las piezas en filas y salta de linea cuando no caben (las etiquetas de tipos)."""

    def __init__(self, parent=None, espacio: int = 5):
        super().__init__(parent)
        self._piezas = []
        self._espacio = espacio
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 - firma de Qt
        self._piezas.append(item)

    def count(self):
        return len(self._piezas)

    def itemAt(self, i):  # noqa: N802
        return self._piezas[i] if 0 <= i < len(self._piezas) else None

    def takeAt(self, i):  # noqa: N802
        return self._piezas.pop(i) if 0 <= i < len(self._piezas) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, ancho):  # noqa: N802
        return self._colocar(QRect(0, 0, ancho, 0), probar=True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._colocar(rect, probar=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        tam = QSize()
        for item in self._piezas:
            tam = tam.expandedTo(item.minimumSize())
        return tam

    def _colocar(self, rect: QRect, probar: bool) -> int:
        x, y, alto_fila = rect.x(), rect.y(), 0
        for item in self._piezas:
            hint = item.sizeHint()
            siguiente = x + hint.width() + self._espacio
            if siguiente - self._espacio > rect.right() + 1 and alto_fila > 0:
                x, y = rect.x(), y + alto_fila + self._espacio
                siguiente = x + hint.width() + self._espacio
                alto_fila = 0
            if not probar:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = siguiente
            alto_fila = max(alto_fila, hint.height())
        return y + alto_fila - rect.y()


def _ficha(texto: str, tinta: str = "acento") -> BotonC:
    """Una etiqueta que se marca y desmarca (un tipo de mision, una era)."""
    boton = BotonC(texto, tam=10, tinta=tinta)
    boton.setCheckable(True)
    return boton


class _Eleccion(QWidget):
    """Varios botones de los que solo vale uno (la dificultad de las fisuras)."""

    def __init__(self, opciones: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        transparente(self)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self.botones: dict[str, BotonC] = {}
        capa = fila(espacio=px(5, False))
        self.setLayout(capa)
        for clave, texto in opciones:
            boton = _ficha(texto)
            self._grupo.addButton(boton)
            self.botones[clave] = boton
            capa.addWidget(boton)
        capa.addStretch(1)

    def valor(self) -> str:
        return next((c for c, b in self.botones.items() if b.isChecked()), "")

    def poner(self, clave: str) -> None:
        boton = self.botones.get(clave) or next(iter(self.botones.values()))
        boton.setChecked(True)

    def al_cambiar(self, funcion) -> None:
        for boton in self.botones.values():
            boton.toggled.connect(lambda marcado, f=funcion: f() if marcado else None)


class _FilaAviso(PanelC):
    """Una regla de "Avisame cuando...": icono, texto e interruptor, en su recuadro."""

    def __init__(self, texto: str, glifo: str, con_detalle: bool, marcado: bool):
        super().__init__(remate=False, fondo="panel2", borde="borde", chaflan=7)
        m = px(4, False)
        self.capa.setContentsMargins(px(12, False), m, px(10, False), m)
        self.interruptor = Interruptor(marcado)
        self.icono = icono(glifo, 14)
        self.texto = EtiquetaC(texto, "normal", recortar=True)
        piezas = [self.icono, self.texto, None]
        if con_detalle:
            # Apunta a la columna de la derecha, donde se eligen los detalles.
            flecha = icono("derecha", 11)
            flecha.setToolTip(t("Los detalles de este aviso se eligen en la columna de la derecha"))
            piezas.append(flecha)
        piezas.append(self.interruptor)
        self.capa.addLayout(fila(*piezas, espacio=px(8, False)))
        self.interruptor.toggled.connect(self._pintar)
        self._pintar()

    def _pintar(self, *_):
        marcado = self.interruptor.isChecked()
        self._borde = "acento_tenue" if marcado else "borde"
        self.texto.setProperty("rolC", "fuerte" if marcado else "normal")
        self.texto.poner_tinta("texto" if marcado else "suave")
        self.icono.setStyleSheet(f"color: {hex_de('acento' if marcado else 'tenue')}; background: transparent;"
                                 f" font-family: '{ICONOS[0]}'; font-size: {px(14)}px;")
        self.update()


class PanelPersonalizar(QWidget):
    volver = Signal()
    secciones_cambiadas = Signal()
    avisos_cambiados = Signal()
    probar_aviso = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        transparente(self)
        self.config = cargar()
        self.casillas_secciones: dict[str, Interruptor] = {}
        self.textos_secciones: dict[str, EtiquetaC] = {}
        self.casillas: dict[str, Interruptor] = {}
        self.filas_aviso: dict[str, _FilaAviso] = {}
        self.tipos_fisura: dict[str, BotonC] = {}
        self.eras: dict[str, BotonC] = {}
        self.tipos_arbitraje: dict[str, BotonC] = {}
        self._construir()

    # -- construccion ------------------------------------------------------------

    def _rotulo(self, texto: str) -> EtiquetaC:
        return EtiquetaC(texto, "rotulo", mayus=True)

    def _construir(self) -> None:
        prefs = avisos_mundo.normalizar(self.config.get(avisos_mundo.CLAVE_CONFIG))
        escondidas = ocultas(self.config)

        self.boton_volver = BotonC(t("Volver a Mundo"), icono="", tam=11)
        self.boton_volver.clicked.connect(self.volver.emit)
        self.titulo = EtiquetaC(t("Personalizar y avisos"), "titulo", mayus=True)
        self.subtitulo = EtiquetaC(t("Todo viene apagado. Cada aviso sale una sola vez, como aviso de Windows."),
                                   "normal", tinta="suave", envolver=True)
        arriba = fila(self.titulo, px(16, False), self.subtitulo, None, self.boton_volver, espacio=0)

        # -- 1. bloques visibles
        self.panel_bloques = PanelC(t("Qué bloques enseñar"))
        for clave, texto in SECCIONES:
            casilla = Interruptor(clave not in escondidas)
            etiqueta = EtiquetaC(t(texto), "normal", envolver=True)
            casilla.toggled.connect(self._guardar_secciones)
            self.casillas_secciones[clave] = casilla
            self.textos_secciones[clave] = etiqueta
            self.panel_bloques.capa.addLayout(fila(etiqueta, None, casilla, espacio=px(8, False)))
        self.panel_bloques.capa.addStretch(1)
        self.panel_bloques.capa.addWidget(
            EtiquetaC(t("Lo que apagues desaparece de la pestaña Mundo."), "pequeno", envolver=True))
        self._pintar_secciones()

        # -- 2. avisos
        self.panel_avisos = PanelC(t("Avisame cuando..."))
        self.panel_avisos.capa.setSpacing(px(5, False))
        self._fila_aviso("fisuras", t("Salga una fisura como estas"), _RAYO, prefs, detalle=True)
        for clave, texto, glifo in AVISOS_VENDEDORES:
            self._fila_aviso(clave, t(texto), glifo, prefs)
        self._fila_aviso("arbitraje", t("Arbitrajes de estos tipos"), _GRUPO, prefs, detalle=True)
        self._fila_aviso("invasiones", "", _GRUPO, prefs, detalle=True)
        for clave, texto, glifo in AVISOS_OTROS:
            self._fila_aviso(clave, t(texto), glifo, prefs)
        self.panel_avisos.capa.addStretch(1)

        # -- 3. detalles
        self.panel_detalles = PanelC(t("Fisuras: de qué tipo"))
        self.panel_detalles.capa.setSpacing(px(7, False))
        self.caja_fisuras = transparente(QWidget())
        detalle = columna(espacio=px(7, False))
        self.caja_fisuras.setLayout(detalle)
        detalle.addWidget(self._rotulo(t("Tipo de misión")))
        flujo = Flujo(espacio=px(5, False))
        for clave, texto in avisos_mundo.TIPOS_FISURA:
            ficha = _ficha(glosa(texto, clave))
            ficha.setChecked(clave in prefs["fisuras_tipos"])
            ficha.toggled.connect(self._guardar_avisos)
            self.tipos_fisura[clave] = ficha
            flujo.addWidget(ficha)
        detalle.addLayout(flujo)
        detalle.addWidget(self._rotulo(t("Eras (ninguna = todas)")))
        flujo_eras = Flujo(espacio=px(5, False))
        for era in avisos_mundo.ERAS_AVISO:
            ficha = _ficha(era, tinta=COLOR_ERA.get(era, "acento"))
            ficha.setChecked(era in prefs["fisuras_eras"])
            ficha.toggled.connect(self._guardar_avisos)
            self.eras[era] = ficha
            flujo_eras.addWidget(ficha)
        detalle.addLayout(flujo_eras)
        detalle.addWidget(self._rotulo(t("Dificultad")))
        self.dificultad = _Eleccion([(c, t(texto)) for c, texto in avisos_mundo.DIFICULTADES])
        self.dificultad.poner(prefs["fisuras_dificultad"])
        self.dificultad.al_cambiar(self._guardar_avisos)
        detalle.addWidget(self.dificultad)
        self.solo_facciones = Interruptor(prefs["fisuras_solo_facciones"])
        self.solo_facciones.toggled.connect(self._guardar_avisos)
        detalle.addLayout(fila(EtiquetaC(t("Solo de las facciones elegidas en el filtro"), "normal", tinta="suave",
                                         envolver=True), None, self.solo_facciones, espacio=px(6, False)))
        self.panel_detalles.capa.addWidget(self.caja_fisuras)
        separador = transparente(QFrame())
        separador.setFixedHeight(1)
        separador.setStyleSheet("background: rgba(128,128,128,70);")
        separador.setProperty("transparenteC", False)
        self.panel_detalles.capa.addWidget(separador)

        self.caja_invasiones = transparente(QWidget())
        self.caja_invasiones.setLayout(columna(espacio=px(5, False)))
        self.caja_invasiones.layout().addWidget(self._rotulo(t("Invasiones cuya recompensa diga")))
        marco = PanelC(remate=False, fondo="panel2", borde="acento_tenue", chaflan=7)
        marco.capa.setContentsMargins(px(10, False), px(2, False), px(10, False), px(2, False))
        self.palabras = QLineEdit(prefs["invasiones_palabras"])
        self.palabras.setFrame(False)
        self.palabras.setStyleSheet("background: transparent; border: none;")
        self.palabras.setPlaceholderText(t("Separadas por comas, p. ej. Orokin, Forma, Exilus"))
        self.palabras.editingFinished.connect(self._guardar_avisos)
        marco.capa.addWidget(self.palabras)
        self.caja_invasiones.layout().addWidget(marco)
        self.panel_detalles.capa.addWidget(self.caja_invasiones)

        self.caja_arbitraje = transparente(QWidget())
        self.caja_arbitraje.setLayout(columna(espacio=px(5, False)))
        self.caja_arbitraje.layout().addWidget(self._rotulo(t("Arbitrajes de estos tipos (ninguno = todos)")))
        flujo_arb = Flujo(espacio=px(5, False))
        for clave, texto in avisos_mundo.TIPOS_ARBITRAJE:
            ficha = _ficha(glosa(texto, clave))
            ficha.setChecked(clave in prefs["arbitraje_tipos"])
            ficha.toggled.connect(self._guardar_avisos)
            self.tipos_arbitraje[clave] = ficha
            flujo_arb.addWidget(ficha)
        self.caja_arbitraje.layout().addLayout(flujo_arb)
        self.panel_detalles.capa.addWidget(self.caja_arbitraje)
        self.panel_detalles.capa.addStretch(1)
        self.boton_probar = BotonC(t("Probar un aviso"), icono="reloj", tam=11)
        self.boton_probar.setToolTip(t("Manda un aviso de prueba para ver cómo se ve en tu Windows"))
        self.boton_probar.clicked.connect(self.probar_aviso.emit)
        self.panel_detalles.capa.addWidget(self.boton_probar)

        self.columnas = QBoxLayout(QBoxLayout.LeftToRight)
        self.columnas.setSpacing(px(14, False))
        self.columnas.addWidget(self.panel_bloques, 4)
        self.columnas.addWidget(self.panel_avisos, 5)
        self.columnas.addWidget(self.panel_detalles, 5)

        interior = transparente(QWidget())
        caja = QVBoxLayout(interior)
        caja.setContentsMargins(0, 0, px(6, False), 0)
        caja.setSpacing(px(12, False))
        caja.addLayout(arriba)
        caja.addLayout(self.columnas, 1)
        desplazable = QScrollArea()
        transparente(desplazable)
        transparente(desplazable.viewport())
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QFrame.NoFrame)
        desplazable.setWidget(interior)
        todo = QVBoxLayout(self)
        todo.setContentsMargins(0, 0, 0, 0)
        todo.addWidget(desplazable)
        self._texto_invasiones()
        self._habilitar()

    def _fila_aviso(self, clave: str, texto: str, glifo: str, prefs: dict, detalle: bool = False) -> None:
        fila_aviso = _FilaAviso(texto, glifo, detalle, bool(prefs.get(clave)))
        fila_aviso.interruptor.toggled.connect(self._guardar_avisos)
        self.casillas[clave] = fila_aviso.interruptor
        self.filas_aviso[clave] = fila_aviso
        self.panel_avisos.capa.addWidget(fila_aviso)

    def _texto_invasiones(self) -> None:
        palabras = ", ".join(p.strip() for p in self.palabras.text().replace(";", ",").split(",") if p.strip())
        texto = t("Invasiones con: {palabras}", palabras=palabras) if palabras else t("Invasiones con estas palabras")
        self.filas_aviso["invasiones"].texto.setText(texto)

    def _pintar_secciones(self) -> None:
        for clave, casilla in self.casillas_secciones.items():
            etiqueta = self.textos_secciones[clave]
            etiqueta.setProperty("rolC", "fuerte" if casilla.isChecked() else "normal")
            etiqueta.poner_tinta("texto" if casilla.isChecked() else "suave")

    def _habilitar(self) -> None:
        self.caja_fisuras.setEnabled(self.casillas["fisuras"].isChecked())
        self.caja_arbitraje.setEnabled(self.casillas["arbitraje"].isChecked())
        self.caja_invasiones.setEnabled(self.casillas["invasiones"].isChecked())

    def resizeEvent(self, evento):  # noqa: N802 - firma de Qt
        super().resizeEvent(evento)
        direccion = QBoxLayout.LeftToRight if self.width() >= px(ANCHO_TRES_COLUMNAS, False) else QBoxLayout.TopToBottom
        if self.columnas.direction() != direccion:
            self.columnas.setDirection(direccion)

    # -- guardado ----------------------------------------------------------------

    def preferencias(self) -> dict:
        prefs = {clave: casilla.isChecked() for clave, casilla in self.casillas.items()}
        prefs["fisuras_tipos"] = [c for c, ficha in self.tipos_fisura.items() if ficha.isChecked()]
        prefs["fisuras_eras"] = [e for e, ficha in self.eras.items() if ficha.isChecked()]
        prefs["fisuras_dificultad"] = self.dificultad.valor() or "cualquiera"
        prefs["fisuras_solo_facciones"] = self.solo_facciones.isChecked()
        prefs["arbitraje_tipos"] = [c for c, ficha in self.tipos_arbitraje.items() if ficha.isChecked()]
        prefs["invasiones_palabras"] = self.palabras.text()
        return avisos_mundo.normalizar(prefs)

    def _guardar_avisos(self, *_):
        self._habilitar()
        self._texto_invasiones()
        self.config[avisos_mundo.CLAVE_CONFIG] = self.preferencias()
        guardar(self.config)
        self.avisos_cambiados.emit()

    def _guardar_secciones(self, *_):
        self._pintar_secciones()
        self.config[CLAVE_OCULTAS] = [c for c, casilla in self.casillas_secciones.items() if not casilla.isChecked()]
        guardar(self.config)
        self.secciones_cambiadas.emit()

    def sincronizar(self) -> None:
        """Vuelve a leer la configuracion (otra parte de la ventana puede haberla cambiado,
        como los botones "Avisarme" de la propia pestana Mundo)."""
        escondidas = ocultas(self.config)
        for clave, casilla in self.casillas_secciones.items():
            casilla.blockSignals(True)
            casilla.setChecked(clave not in escondidas)
            casilla.blockSignals(False)
        self._pintar_secciones()
        prefs = avisos_mundo.normalizar(self.config.get(avisos_mundo.CLAVE_CONFIG))
        for clave, casilla in self.casillas.items():
            casilla.blockSignals(True)
            casilla.setChecked(bool(prefs.get(clave)))
            casilla.blockSignals(False)
            self.filas_aviso[clave]._pintar()
        self._habilitar()
