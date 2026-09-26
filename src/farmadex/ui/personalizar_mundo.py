"""La pagina "Personalizar" de la pestana Mundo: que bloques se ven y que avisa Farmadex.

Vive dentro de la propia pestana (no en Ajustes ni en una ventana aparte): lo que
cambia aqui afecta solo a Mundo, asi que es donde uno lo busca. Cada casilla se
guarda al momento en la configuracion.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..config import cargar, guardar
from ..idiomas import glosa, t
from ..online import avisos_mundo
from .widgets import PALETA

CLAVE_OCULTAS = "mundo_secciones_ocultas"

# Los bloques que se pueden esconder, con una frase que diga que son.
SECCIONES = (
    ("ahora", "Ahora: ciclos y Baro de un vistazo (disposicion en lista)"),
    ("ciclos", "Ciclos (disposicion en tablero)"),
    ("objetivos", "Fisuras para tus objetivos"),
    ("fisuras", "Fisuras del Vacio"),
    ("acero", "Fisuras del Camino de Acero"),
    ("tormentas", "Tormentas del Vacio"),
    ("sortie", "Incursion y arcontes"),
    ("baro", "Baro Ki'Teer"),
    ("invasiones", "Invasiones y alertas"),
    ("nightwave", "Nightwave y Camino de Acero"),
)

# Avisos de una sola casilla (clave de avisos_mundo.POR_DEFECTO -> texto).
AVISOS_VENDEDORES = (
    ("baro", "Llega Baro Ki'Teer"),
    ("baro_objetivo", "Baro Ki'Teer trae algo que tienes en tus objetivos"),
    ("teshin_kuva", "Teshin (Camino de Acero) ofrece Kuva esta semana"),
    ("teshin_umbra", "Teshin (Camino de Acero) ofrece Forma Umbra esta semana"),
    ("teshin_cambio", "Cada semana, lo que ofrece Teshin (sea lo que sea)"),
    ("palladino", "Cada semana: recordatorio de la Kuva de Palladino en Estela de Hierro"),
)
AVISOS_OTROS = (
    ("alertas", "Alertas nuevas"),
    ("incursion", "Incursion nueva (cada dia)"),
    ("arcontes", "Caza de arcontes nueva (cada semana)"),
    ("noche_cetus", "Se hace de noche en las Llanuras de Eidolon (Cetus)"),
)


def ocultas(config: dict) -> set[str]:
    valor = config.get(CLAVE_OCULTAS) or []
    return {str(x) for x in valor} if isinstance(valor, (list, tuple)) else set()


def _contenedor() -> QWidget:
    """Un hueco sin fondo propio: dentro de un recuadro, se ve el color del recuadro."""
    caja = QWidget()
    caja.setObjectName("sinFondo")
    caja.setAttribute(Qt.WA_StyledBackground, True)
    caja.setStyleSheet("#sinFondo { background: transparent; }")
    return caja


class _Grupo(QFrame):
    """Un recuadro con titulo, como las secciones de la pestana."""

    def __init__(self, titulo: str, parent=None):
        super().__init__(parent)
        self.setObjectName("grupoMundo")
        p = PALETA
        self.setStyleSheet(
            f"#grupoMundo {{ background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: 10px; }}"
        )
        self.caja = QVBoxLayout(self)
        self.caja.setContentsMargins(12, 8, 12, 10)
        self.caja.setSpacing(4)
        cabecera = QLabel(titulo.upper())
        cabecera.setStyleSheet(f"color: {p['acento']}; font-weight: 600; letter-spacing: 1px;")
        self.caja.addWidget(cabecera)

    def nota(self, texto: str) -> QLabel:
        etiqueta = QLabel(texto)
        etiqueta.setWordWrap(True)
        etiqueta.setStyleSheet(f"color: {PALETA['suave']};")
        self.caja.addWidget(etiqueta)
        return etiqueta


class PanelPersonalizar(QWidget):
    volver = Signal()
    secciones_cambiadas = Signal()
    avisos_cambiados = Signal()
    probar_aviso = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = cargar()
        self.casillas_secciones: dict[str, QCheckBox] = {}
        self.casillas: dict[str, QCheckBox] = {}
        self.tipos_fisura: dict[str, QCheckBox] = {}
        self.eras: dict[str, QCheckBox] = {}
        self.tipos_arbitraje: dict[str, QCheckBox] = {}
        self._construir()

    # -- construccion ------------------------------------------------------------

    def _construir(self) -> None:
        p = PALETA
        prefs = avisos_mundo.normalizar(self.config.get(avisos_mundo.CLAVE_CONFIG))
        escondidas = ocultas(self.config)

        self.boton_volver = QPushButton(t("Volver a Mundo"))
        self.boton_volver.setObjectName("principal")
        self.boton_volver.clicked.connect(self.volver.emit)
        titulo = QLabel(t("Personaliza la pestana Mundo"))
        titulo.setStyleSheet(f"color: {p['texto']}; font-size: 15px; font-weight: 600;")
        arriba = QHBoxLayout()
        arriba.addWidget(titulo)
        arriba.addStretch(1)
        arriba.addWidget(self.boton_volver)

        # -- bloques visibles
        bloques = _Grupo(t("Que bloques ensenar"))
        bloques.nota(t("Quita la marca de lo que no te interese y desaparecera de la pestana."))
        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(16)
        for i, (clave, texto) in enumerate(SECCIONES):
            casilla = QCheckBox(t(texto))
            casilla.setChecked(clave not in escondidas)
            casilla.toggled.connect(self._guardar_secciones)
            self.casillas_secciones[clave] = casilla
            rejilla.addWidget(casilla, i // 2, i % 2)
        bloques.caja.addLayout(rejilla)

        # -- avisos
        avisos = _Grupo(t("Avisos de Windows"))
        avisos.nota(t(
            "Farmadex te avisa con una notificacion de Windows cuando pase algo de lo que marques, "
            "aunque tengas la ventana cerrada. Todo viene apagado y cada aviso sale una sola vez."
        ))

        # Fisuras
        self.casillas["fisuras"] = self._casilla(avisos.caja, "fisuras", prefs,
                                                 t("Fisuras de estos tipos de mision:"))
        self.caja_fisuras = _contenedor()
        detalle = QVBoxLayout(self.caja_fisuras)
        detalle.setContentsMargins(22, 0, 0, 4)
        detalle.setSpacing(3)
        tipos = QGridLayout()
        tipos.setHorizontalSpacing(14)
        tipos.setVerticalSpacing(1)
        for i, (clave, texto) in enumerate(avisos_mundo.TIPOS_FISURA):
            casilla = QCheckBox(glosa(texto, clave))
            casilla.setChecked(clave in prefs["fisuras_tipos"])
            casilla.toggled.connect(self._guardar_avisos)
            self.tipos_fisura[clave] = casilla
            tipos.addWidget(casilla, i // 3, i % 3)
        detalle.addLayout(tipos)
        linea_eras = QHBoxLayout()
        linea_eras.addWidget(QLabel(t("Eras (ninguna marcada = todas):")))
        for era in avisos_mundo.ERAS_AVISO:
            casilla = QCheckBox(era)
            casilla.setChecked(era in prefs["fisuras_eras"])
            casilla.toggled.connect(self._guardar_avisos)
            self.eras[era] = casilla
            linea_eras.addWidget(casilla)
        linea_eras.addStretch(1)
        detalle.addLayout(linea_eras)
        linea_dificultad = QHBoxLayout()
        self.dificultad = QComboBox()
        for clave, texto in avisos_mundo.DIFICULTADES:
            self.dificultad.addItem(t(texto), clave)
        self.dificultad.setCurrentIndex(max(0, self.dificultad.findData(prefs["fisuras_dificultad"])))
        self.dificultad.currentIndexChanged.connect(self._guardar_avisos)
        linea_dificultad.addWidget(self.dificultad)
        self.solo_facciones = QCheckBox(t("Solo de las facciones que tengas elegidas en el filtro"))
        self.solo_facciones.setChecked(prefs["fisuras_solo_facciones"])
        self.solo_facciones.toggled.connect(self._guardar_avisos)
        linea_dificultad.addWidget(self.solo_facciones)
        linea_dificultad.addStretch(1)
        detalle.addLayout(linea_dificultad)
        avisos.caja.addWidget(self.caja_fisuras)

        # Baro, Teshin, Palladino
        for clave, texto in AVISOS_VENDEDORES:
            self.casillas[clave] = self._casilla(avisos.caja, clave, prefs, t(texto))

        # Arbitrajes
        self.casillas["arbitraje"] = self._casilla(avisos.caja, "arbitraje", prefs,
                                                   t("Arbitrajes de estos tipos (ninguno marcado = todos):"))
        self.caja_arbitraje = _contenedor()
        rejilla_arb = QGridLayout(self.caja_arbitraje)
        rejilla_arb.setContentsMargins(22, 0, 0, 4)
        rejilla_arb.setHorizontalSpacing(14)
        rejilla_arb.setVerticalSpacing(1)
        for i, (clave, texto) in enumerate(avisos_mundo.TIPOS_ARBITRAJE):
            casilla = QCheckBox(glosa(texto, clave))
            casilla.setChecked(clave in prefs["arbitraje_tipos"])
            casilla.toggled.connect(self._guardar_avisos)
            self.tipos_arbitraje[clave] = casilla
            rejilla_arb.addWidget(casilla, i // 3, i % 3)
        avisos.caja.addWidget(self.caja_arbitraje)

        # Invasiones
        self.casillas["invasiones"] = self._casilla(
            avisos.caja, "invasiones", prefs, t("Invasiones cuya recompensa contenga alguna de estas palabras:"))
        self.palabras = QLineEdit(prefs["invasiones_palabras"])
        self.palabras.setPlaceholderText(t("Separadas por comas, p. ej. Orokin, Forma, Exilus"))
        self.palabras.editingFinished.connect(self._guardar_avisos)
        self.caja_invasiones = _contenedor()
        linea_inv = QHBoxLayout(self.caja_invasiones)
        linea_inv.setContentsMargins(22, 0, 0, 4)
        linea_inv.addWidget(self.palabras)
        avisos.caja.addWidget(self.caja_invasiones)

        for clave, texto in AVISOS_OTROS:
            self.casillas[clave] = self._casilla(avisos.caja, clave, prefs, t(texto))

        self.boton_probar = QPushButton(t("Probar un aviso"))
        self.boton_probar.setToolTip(t("Manda un aviso de prueba para ver como se ve en tu Windows"))
        self.boton_probar.clicked.connect(self.probar_aviso.emit)
        linea_probar = QHBoxLayout()
        linea_probar.addWidget(self.boton_probar)
        linea_probar.addStretch(1)
        avisos.caja.addLayout(linea_probar)

        interior = QWidget()
        caja = QVBoxLayout(interior)
        caja.setContentsMargins(0, 0, 6, 0)
        caja.setSpacing(8)
        caja.addLayout(arriba)
        caja.addWidget(bloques)
        caja.addWidget(avisos)
        caja.addStretch(1)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QFrame.NoFrame)
        desplazable.setWidget(interior)
        todo = QVBoxLayout(self)
        todo.setContentsMargins(0, 0, 0, 0)
        todo.addWidget(desplazable)
        self._habilitar()

    def _casilla(self, caja, clave: str, prefs: dict, texto: str) -> QCheckBox:
        casilla = QCheckBox(texto)
        casilla.setChecked(bool(prefs.get(clave)))
        casilla.setStyleSheet("QCheckBox { font-weight: 600; }")
        casilla.toggled.connect(self._guardar_avisos)
        caja.addWidget(casilla)
        return casilla

    def _habilitar(self) -> None:
        self.caja_fisuras.setEnabled(self.casillas["fisuras"].isChecked())
        self.caja_arbitraje.setEnabled(self.casillas["arbitraje"].isChecked())
        self.caja_invasiones.setEnabled(self.casillas["invasiones"].isChecked())

    # -- guardado ----------------------------------------------------------------

    def preferencias(self) -> dict:
        prefs = {clave: casilla.isChecked() for clave, casilla in self.casillas.items()}
        prefs["fisuras_tipos"] = [c for c, casilla in self.tipos_fisura.items() if casilla.isChecked()]
        prefs["fisuras_eras"] = [e for e, casilla in self.eras.items() if casilla.isChecked()]
        prefs["fisuras_dificultad"] = self.dificultad.currentData() or "cualquiera"
        prefs["fisuras_solo_facciones"] = self.solo_facciones.isChecked()
        prefs["arbitraje_tipos"] = [c for c, casilla in self.tipos_arbitraje.items() if casilla.isChecked()]
        prefs["invasiones_palabras"] = self.palabras.text()
        return avisos_mundo.normalizar(prefs)

    def _guardar_avisos(self, *_):
        self._habilitar()
        self.config[avisos_mundo.CLAVE_CONFIG] = self.preferencias()
        guardar(self.config)
        self.avisos_cambiados.emit()

    def _guardar_secciones(self, *_):
        self.config[CLAVE_OCULTAS] = [c for c, casilla in self.casillas_secciones.items() if not casilla.isChecked()]
        guardar(self.config)
        self.secciones_cambiadas.emit()

    def sincronizar(self) -> None:
        """Vuelve a leer la configuracion (otra parte de la ventana puede haberla cambiado)."""
        escondidas = ocultas(self.config)
        for clave, casilla in self.casillas_secciones.items():
            casilla.blockSignals(True)
            casilla.setChecked(clave not in escondidas)
            casilla.blockSignals(False)

