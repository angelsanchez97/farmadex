"""Pestana Ajustes: atajos, aspecto, idioma, datos, version y salida."""

from __future__ import annotations

import os
import subprocess
import sqlite3
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import NOMBRE_APP, VERSION, idiomas
from ..config import DIR_BASE, cargar, guardar
from ..datos import eficiencia, indice
from ..hotkeys import parsear
from ..idiomas import t
from .acerca_de import abrir_acerca_de, texto_autor
from .pestana_mundo import DISENO_POR_DEFECTO
from .widgets import PALETA, TEMA_POR_DEFECTO, TEMAS


class PestanaAjustes(QWidget):
    reconstruir = Signal()
    salir = Signal()
    hotkeys_cambiadas = Signal(dict)
    opacidad_cambiada = Signal(float)
    tema_cambiado = Signal(str)
    idioma_cambiado = Signal(str)
    diseno_mundo_cambiado = Signal(str)
    ritmo_cambiado = Signal(str)
    comprobar_version = Signal()
    instalar_version = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = cargar()
        p = PALETA
        # Textos fijos que hay que volver a escribir al cambiar de idioma:
        # (funcion que pone el texto, clave en castellano).
        self._fijos: list[tuple[Callable[[str], None], str]] = []
        self._notas: list[QLabel] = []
        # Color de la linea de version ("suave" normal, "aviso" si hay version nueva).
        self._color_version = "suave"

        # -- atajos --------------------------------------------------------------
        self.campos_hotkey = {
            "overlay": QLineEdit(self.config["hotkey_overlay"]),
            "cursor": QLineEdit(self.config["hotkey_cursor"]),
            "reliquias": QLineEdit(self.config["hotkey_reliquias"]),
        }
        formulario = QFormLayout()
        formulario.setHorizontalSpacing(16)
        formulario.setVerticalSpacing(8)
        self._fila(formulario, "Abrir y cerrar el overlay", self.campos_hotkey["overlay"])
        self._fila(formulario, "Leer el objeto bajo el cursor", self.campos_hotkey["cursor"])
        self._fila(formulario, "Leer las recompensas de reliquia", self.campos_hotkey["reliquias"])
        self.aviso_hotkey = QLabel("")
        self.aviso_hotkey.setStyleSheet(f"color: {p['aviso']};")
        if hasattr(self, "autor"):  # repintar tambien corre a mitad del __init__
            self.autor.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
            self.autor.setText(texto_autor())  # el enlace lleva el color de acento del tema
        boton_hotkeys = self._boton("Aplicar atajos")
        boton_hotkeys.clicked.connect(self._aplicar_hotkeys)
        fila_hotkeys = QHBoxLayout()
        fila_hotkeys.addWidget(boton_hotkeys)
        fila_hotkeys.addWidget(self.aviso_hotkey, 1)
        formulario.addRow(fila_hotkeys)
        grupo_atajos = self._grupo("Atajos de teclado")
        grupo_atajos.setLayout(formulario)

        # -- aspecto e idioma ------------------------------------------------------
        self.tema = QComboBox()
        for clave, tema in TEMAS.items():
            self.tema.addItem(t(tema["titulo"]), clave)
        actual = self.config.get("tema") or TEMA_POR_DEFECTO
        self.tema.setCurrentIndex(max(0, self.tema.findData(actual)))
        self.tema.currentIndexChanged.connect(self._cambiar_tema)

        # Los nombres de los idiomas van cada uno en su idioma, no se traducen.
        self.idioma = QComboBox()
        self.idioma.addItem(t("Automatico (el de Windows)"), idiomas.AUTOMATICO)
        for codigo, nombre in idiomas.IDIOMAS.items():
            self.idioma.addItem(nombre, codigo)
        guardado = self.config.get("idioma_ui") or idiomas.AUTOMATICO
        self.idioma.setCurrentIndex(max(0, self.idioma.findData(guardado)))
        self.idioma.currentIndexChanged.connect(self._cambiar_idioma)

        self.diseno_mundo = QComboBox()
        self.diseno_mundo.addItem(t("Lista"), "lista")
        self.diseno_mundo.addItem(t("Tablero"), "tablero")
        diseno_guardado = self.config.get("diseno_mundo") or DISENO_POR_DEFECTO
        self.diseno_mundo.setCurrentIndex(max(0, self.diseno_mundo.findData(diseno_guardado)))
        self.diseno_mundo.currentIndexChanged.connect(self._cambiar_diseno_mundo)

        self.opacidad = QSlider(Qt.Horizontal)
        self.opacidad.setRange(50, 100)
        self.opacidad.setValue(int(float(self.config["overlay_opacidad"]) * 100))
        self.opacidad.valueChanged.connect(self._cambiar_opacidad)
        self.estilo_recompensas = QComboBox()
        self.estilo_recompensas.addItem(t("Etiquetas pequenas junto a cada tarjeta"), "etiquetas")
        self.estilo_recompensas.addItem(t("Panel con una tarjeta por recompensa"), "panel")
        self.estilo_recompensas.setCurrentIndex(
            max(0, self.estilo_recompensas.findData(self.config.get("estilo_recompensas") or "etiquetas"))
        )
        self.estilo_recompensas.currentIndexChanged.connect(self._cambiar_estilo_recompensas)
        self.ocr_auto = QCheckBox()
        self._fijo(self.ocr_auto.setText, "Leer sola la pantalla de recompensas de reliquia")
        self.ocr_auto.setChecked(bool(self.config["ocr_reliquias_auto"]))
        self.ocr_auto.toggled.connect(lambda v: self._guardar("ocr_reliquias_auto", v))
        self.perfil_pasivo = QCheckBox()
        self._fijo(self.perfil_pasivo.setText, "Leer sola la maestria al abrir Perfil > Equipamiento")
        self.perfil_pasivo.setChecked(bool(self.config.get("perfil_pasivo", True)))
        self.perfil_pasivo.toggled.connect(lambda v: self._guardar("perfil_pasivo", v))
        self.inventario_pasivo = QCheckBox()
        self._fijo(self.inventario_pasivo.setText, "Leer solas las cantidades del Inventario y la Fundicion (experimental)")
        self.inventario_pasivo.setChecked(bool(self.config.get("inventario_pasivo", False)))
        self.inventario_pasivo.toggled.connect(lambda v: self._guardar("inventario_pasivo", v))
        self.botin_eelog = QCheckBox()
        self._fijo(self.botin_eelog.setText, "Sumar a los objetivos la recompensa de reliquia de las misiones en solitario (EE.log)")
        self.botin_eelog.setChecked(bool(self.config.get("botin_eelog_auto", True)))
        self.botin_eelog.toggled.connect(lambda v: self._guardar("botin_eelog_auto", v))

        aspecto = QFormLayout()
        aspecto.setHorizontalSpacing(16)
        aspecto.setVerticalSpacing(8)
        self._fila(aspecto, "Tema de color", self.tema)
        self._fila(aspecto, "Idioma", self.idioma)
        self._fila(aspecto, "Disposicion de Mundo", self.diseno_mundo)
        self._fila(aspecto, "Opacidad del fondo", self.opacidad)
        self._fila(aspecto, "Recompensas de reliquia", self.estilo_recompensas)
        aspecto.addRow(self.ocr_auto)
        aspecto.addRow(self.perfil_pasivo)
        aspecto.addRow(self.inventario_pasivo)
        aspecto.addRow(self.botin_eelog)
        aspecto.addRow(self._nota(
            "Las lecturas solas solo miran la pantalla cuando Warframe esta delante y se ha "
            "quedado quieta; F9 en la herramienta de escaneo sigue valiendo."
        ))
        nota = self._nota(
            "Warframe tiene que estar en Ventana sin bordes (o en DX12). En pantalla "
            "completa exclusiva el overlay no se ve."
        )
        aspecto.addRow(nota)
        # Lo que se ha detectado del juego: se rellena cuando la ventana lo mira.
        self._modo_pantalla: str | None = None
        self.estado_juego = QLabel("")
        self.estado_juego.setWordWrap(True)
        self.estado_juego.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        aspecto.addRow(self.estado_juego)
        aspecto.addRow(self._nota("El menu de la bandeja cambia de idioma al reiniciar Farmadex."))
        grupo_aspecto = self._grupo("Overlay")
        grupo_aspecto.setLayout(aspecto)

        # -- datos del juego -----------------------------------------------------
        # Ritmo de juego: multiplica las duraciones estimadas (eficiencia.RITMOS), no las
        # probabilidades. Un desplegable de tres y no un deslizador: el factor exacto no
        # dice nada a quien juega, "Rapido" o "Tranquilo" si.
        self.ritmo = QComboBox()
        for clave in eficiencia.RITMOS:
            self.ritmo.addItem("", clave)
        self._textos_ritmo()
        ritmo_guardado = self.config.get(eficiencia.CLAVE_RITMO) or eficiencia.RITMO_POR_DEFECTO
        self.ritmo.setCurrentIndex(max(0, self.ritmo.findData(ritmo_guardado)))
        self.ritmo.currentIndexChanged.connect(self._cambiar_ritmo)
        ritmo = QFormLayout()
        ritmo.setHorizontalSpacing(16)
        self._fila(ritmo, "Ritmo de juego", self.ritmo)
        ritmo.addRow(self._nota(
            "Ajusta los tiempos estimados de la ficha a como juegas. No cambia las probabilidades "
            "ni el orden de los sitios."
        ))

        self.estado_datos = QLabel("")
        self.estado_datos.setWordWrap(True)
        self.estado_datos.setStyleSheet(f"color: {p['suave']};")
        boton_datos = self._boton("Reconstruir el indice")
        boton_datos.clicked.connect(self.reconstruir.emit)
        boton_carpeta = self._boton("Abrir la carpeta de datos")
        boton_carpeta.clicked.connect(self._abrir_carpeta)
        botones = QHBoxLayout()
        botones.addWidget(boton_datos)
        botones.addWidget(boton_carpeta)
        botones.addStretch(1)
        self._texto_parche: str | None = None
        self.aviso_parche = QLabel("")
        self.aviso_parche.setWordWrap(True)
        self.aviso_parche.setStyleSheet(f"color: {p['aviso']};")
        self.aviso_parche.hide()
        datos = QVBoxLayout()
        datos.setSpacing(8)
        datos.addLayout(ritmo)
        datos.addWidget(self.estado_datos)
        datos.addWidget(self.aviso_parche)
        datos.addStretch(1)
        datos.addLayout(botones)
        grupo_datos = self._grupo("Datos del juego")
        grupo_datos.setLayout(datos)

        # -- version (siempre visible) -------------------------------------------
        self.etiqueta_version = QLabel(f"{NOMBRE_APP} <b>{VERSION}</b>")
        self.etiqueta_version.setTextFormat(Qt.RichText)
        self.etiqueta_version.setStyleSheet("font-size: 16px;")
        self.aviso_version = QLabel(t("Estas en la ultima version"))
        self.aviso_version.setWordWrap(True)
        self.aviso_version.setOpenExternalLinks(True)
        self.aviso_version.setStyleSheet(f"color: {p['suave']};")
        self.boton_comprobar = self._boton("Comprobar ahora")
        self.boton_comprobar.clicked.connect(self._pedir_comprobacion)
        self.boton_instalar = self._boton("Instalar la version nueva")
        self.boton_instalar.setObjectName("principal")
        self.boton_instalar.setVisible(False)
        # Para la actualizacion ya descargada y comprobada por la propia app.
        self.boton_reiniciar = self._boton("Reiniciar y actualizar")
        self.boton_reiniciar.setObjectName("principal")
        self.boton_reiniciar.setVisible(False)
        self.auto_actualizar = QCheckBox()
        self._fijo(self.auto_actualizar.setText, "Actualizar automaticamente (se instala al cerrar Farmadex)")
        self.auto_actualizar.setChecked(bool(self.config.get("actualizar_automaticamente", True)))
        self.auto_actualizar.toggled.connect(lambda v: self._guardar("actualizar_automaticamente", v))
        self.iniciar_windows = QCheckBox()
        self._fijo(self.iniciar_windows.setText, "Iniciar con Windows (escondido en la bandeja)")
        self.iniciar_windows.setChecked(bool(self.config.get("iniciar_con_windows", False)))
        self.iniciar_windows.toggled.connect(self._cambiar_arranque)
        self.aviso_arranque = QLabel("")
        self.aviso_arranque.setWordWrap(True)
        self.aviso_arranque.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        self._pintar_aviso_arranque()
        botones_version = QHBoxLayout()
        botones_version.addWidget(self.boton_comprobar)
        botones_version.addWidget(self.boton_instalar)
        botones_version.addWidget(self.boton_reiniciar)
        botones_version.addStretch(1)
        version = QVBoxLayout()
        version.setSpacing(8)
        version.addWidget(self.etiqueta_version)
        version.addWidget(self.aviso_version)
        version.addWidget(self.auto_actualizar)
        version.addWidget(self.iniciar_windows)
        version.addWidget(self.aviso_arranque)
        version.addStretch(1)
        version.addLayout(botones_version)
        grupo_version = self._grupo("Version")
        grupo_version.setLayout(version)

        # -- salida ---------------------------------------------------------------
        boton_salir = QPushButton()
        self._fijo(lambda s: boton_salir.setText(s.format(app=NOMBRE_APP)), "Salir de {app}")
        boton_salir.clicked.connect(self.salir.emit)
        # Que es Farmadex y que dice DE de los programas de terceros (ui/acerca_de.py).
        self.boton_acerca = QPushButton()
        self._fijo(lambda s: self.boton_acerca.setText(s.format(app=NOMBRE_APP)), "Acerca de {app}")
        self.boton_acerca.clicked.connect(lambda: abrir_acerca_de(self.window()))

        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(12)
        rejilla.setVerticalSpacing(12)
        rejilla.addWidget(grupo_atajos, 0, 0)
        rejilla.addWidget(grupo_aspecto, 0, 1)
        rejilla.addWidget(grupo_datos, 1, 0)
        rejilla.addWidget(grupo_version, 1, 1)
        rejilla.setColumnStretch(0, 1)
        rejilla.setColumnStretch(1, 1)

        contenido = QWidget()
        dentro = QVBoxLayout(contenido)
        dentro.setContentsMargins(0, 0, 0, 0)
        dentro.addLayout(rejilla)
        dentro.addStretch(1)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(contenido)

        pie = QHBoxLayout()
        creditos = self._nota("Datos de WFCD y Digital Extremes")
        creditos.setWordWrap(False)  # en el pie hay sitio de sobra; partido queda raro
        pie.addWidget(creditos)
        pie.addStretch(1)
        self.autor = QLabel()
        self.autor.setTextFormat(Qt.RichText)
        self.autor.setOpenExternalLinks(True)
        self.autor.setStyleSheet(f"color: {PALETA['suave']}; font-size: 12px;")
        self._fijo(lambda _s: self.autor.setText(texto_autor()), "Creado por {autor}")
        pie.addWidget(self.autor)
        pie.addWidget(self.boton_acerca)
        pie.addWidget(boton_salir)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 8, 4, 4)
        caja.addWidget(desplazable, 1)
        caja.addLayout(pie)

        self.refrescar_estado()

    # -- textos fijos y su retraduccion -------------------------------------------

    def _fijo(self, poner: Callable[[str], None], clave: str) -> None:
        poner(t(clave))
        self._fijos.append((poner, clave))

    def _boton(self, clave: str) -> QPushButton:
        boton = QPushButton()
        self._fijo(boton.setText, clave)
        return boton

    def _grupo(self, clave: str) -> QGroupBox:
        grupo = QGroupBox()
        self._fijo(grupo.setTitle, clave)
        return grupo

    def _nota(self, clave: str) -> QLabel:
        nota = QLabel()
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color: {PALETA['suave']}; font-size: 12px;")
        self._fijo(nota.setText, clave)
        self._notas.append(nota)
        return nota

    def repintar(self) -> None:
        """Tras cambiar de tema: las etiquetas llevan el color puesto a mano en su hoja."""
        p = PALETA
        for nota in self._notas:
            nota.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        self.aviso_hotkey.setStyleSheet(f"color: {p['aviso']};")
        self.estado_datos.setStyleSheet(f"color: {p['suave']};")
        alerta = getattr(self, "_aviso_parche_es_alerta", True)
        self.aviso_parche.setStyleSheet(f"color: {p['aviso' if alerta else 'suave']};")
        self.aviso_version.setStyleSheet(f"color: {p[self._color_version]};")
        if self._modo_pantalla is not None:
            self.mostrar_modo_pantalla(self._modo_pantalla)

    def _fila(self, formulario: QFormLayout, clave: str, campo: QWidget) -> None:
        etiqueta = QLabel()
        self._fijo(etiqueta.setText, clave)
        formulario.addRow(etiqueta, campo)

    def retraducir(self) -> None:
        """Vuelve a escribir todo lo fijo en el idioma activo; lo dinamico se refresca."""
        for poner, clave in self._fijos:
            poner(t(clave))
        for i, tema in enumerate(TEMAS.values()):
            self.tema.setItemText(i, t(tema["titulo"]))
        self.idioma.setItemText(0, t("Automatico (el de Windows)"))
        self.diseno_mundo.setItemText(0, t("Lista"))
        self.diseno_mundo.setItemText(1, t("Tablero"))
        self._textos_ritmo()
        self.estilo_recompensas.setItemText(0, t("Etiquetas pequenas junto a cada tarjeta"))
        self.estilo_recompensas.setItemText(1, t("Panel con una tarjeta por recompensa"))
        self.aviso_hotkey.setText("")
        self.estado_version(t("Estas en la ultima version"))
        self.refrescar_estado()
        if self._modo_pantalla is not None:
            self.mostrar_modo_pantalla(self._modo_pantalla)

    # -- lo detectado del juego ---------------------------------------------------

    MODOS_PANTALLA = {
        "ventana": "Ventana",
        "sin_bordes": "Ventana sin bordes",
        "exclusivo": "Pantalla completa exclusiva (el overlay no puede verse encima)",
        "desconocido": "Warframe no esta abierto",
    }

    def mostrar_modo_pantalla(self, modo: str) -> None:
        """La ventana lo llama cada vez que mira en que modo esta el juego."""
        self._modo_pantalla = modo
        etiqueta = t(self.MODOS_PANTALLA.get(modo, self.MODOS_PANTALLA["desconocido"]))
        self.estado_juego.setText(t("Modo de pantalla detectado: {modo}", modo=etiqueta))
        color = PALETA["aviso"] if modo == "exclusivo" else PALETA["suave"]
        self.estado_juego.setStyleSheet(f"color: {color}; font-size: 12px;")

    def avisar_parche(self, texto: str | None, aviso: bool = True) -> None:
        """Aviso de que los datos son anteriores al parche del juego; None lo quita.

        Con `aviso` en False va en color neutro: los datos son lo ultimo publicado y
        solo se informa de que DE no ha actualizado sus tablas desde el parche.
        """
        self._texto_parche = texto
        self._aviso_parche_es_alerta = aviso
        self.aviso_parche.setStyleSheet(f"color: {PALETA['aviso' if aviso else 'suave']};")
        self.aviso_parche.setText(texto or "")
        self.aviso_parche.setVisible(bool(texto))

    # -- acciones ----------------------------------------------------------

    def _guardar(self, clave: str, valor) -> None:
        self.config[clave] = valor
        guardar(self.config)

    estilo_recompensas_cambiado = Signal(str)

    def _cambiar_estilo_recompensas(self, _indice: int) -> None:
        estilo = self.estilo_recompensas.currentData()
        self._guardar("estilo_recompensas", estilo)
        self.estilo_recompensas_cambiado.emit(estilo)

    def _cambiar_opacidad(self, valor: int) -> None:
        self._guardar("overlay_opacidad", valor / 100)
        self.opacidad_cambiada.emit(valor / 100)

    def _cambiar_tema(self, _indice: int) -> None:
        clave = self.tema.currentData() or TEMA_POR_DEFECTO
        self._guardar("tema", clave)
        self.tema_cambiado.emit(clave)

    def _cambiar_idioma(self, _indice: int) -> None:
        codigo = self.idioma.currentData() or idiomas.AUTOMATICO
        self._guardar("idioma_ui", codigo)
        self.idioma_cambiado.emit(codigo)

    def _cambiar_diseno_mundo(self, _indice: int) -> None:
        clave = self.diseno_mundo.currentData() or DISENO_POR_DEFECTO
        self._guardar("diseno_mundo", clave)
        self.diseno_mundo_cambiado.emit(clave)

    RITMOS = {
        "rapido": "Rapido: veterano con buen equipo (x{factor})",
        "normal": "Normal: jugador medio (x{factor})",
        "tranquilo": "Tranquilo: empezando o explorando (x{factor})",
    }

    def _textos_ritmo(self) -> None:
        for i in range(self.ritmo.count()):
            clave = self.ritmo.itemData(i)
            self.ritmo.setItemText(i, t(self.RITMOS[clave], factor=f"{eficiencia.RITMOS[clave]:g}"))

    def _cambiar_ritmo(self, _indice: int) -> None:
        clave = self.ritmo.currentData() or eficiencia.RITMO_POR_DEFECTO
        self._guardar(eficiencia.CLAVE_RITMO, clave)
        self.ritmo_cambiado.emit(clave)

    def _cambiar_arranque(self, activo: bool) -> None:
        """Alta o baja en HKCU\\...\\Run; si no se puede (codigo sin congelar), se desmarca."""
        from .. import arranque

        if arranque.sincronizar(activo):
            self._guardar("iniciar_con_windows", activo)
        elif activo:
            self.iniciar_windows.blockSignals(True)
            self.iniciar_windows.setChecked(False)
            self.iniciar_windows.blockSignals(False)
            self._guardar("iniciar_con_windows", False)
        self._pintar_aviso_arranque()

    def _pintar_aviso_arranque(self) -> None:
        from .. import arranque

        if arranque.comando_arranque() is None:
            self.aviso_arranque.setText(t("Solo disponible en la version instalada o portable (.exe)."))
        elif arranque.es_portable():
            self.aviso_arranque.setText(
                t("Version portable: si mueves o borras el .exe, el arranque dejara de funcionar.")
            )
        else:
            self.aviso_arranque.setText("")

    def _aplicar_hotkeys(self) -> None:
        nuevas = {}
        for nombre, campo in self.campos_hotkey.items():
            texto = campo.text().strip()
            try:
                parsear(texto)
            except ValueError as e:
                self.aviso_hotkey.setText(f"{texto or t('(vacio)')}: {e}")
                return
            nuevas[nombre] = texto
        for nombre, texto in nuevas.items():
            self._guardar(f"hotkey_{nombre}", texto)
        self.aviso_hotkey.setText(t("Atajos aplicados."))
        self.hotkeys_cambiadas.emit(nuevas)

    def _abrir_carpeta(self) -> None:
        if os.name == "nt":
            os.startfile(DIR_BASE)  # noqa: S606 - abrir el explorador es la intencion
        else:  # pragma: no cover - solo para desarrollo fuera de Windows
            subprocess.Popen(["xdg-open", str(DIR_BASE)])

    # -- version ----------------------------------------------------------------

    def _pedir_comprobacion(self) -> None:
        self.estado_version(t("Comprobando..."))
        self.comprobar_version.emit()

    def estado_version(self, texto: str) -> None:
        """Lo escribe quien hace la comprobacion: 'Estas en la ultima version', etc."""
        self.aviso_version.setText(texto)
        self._color_version = "suave"
        self.aviso_version.setStyleSheet(f"color: {PALETA['suave']};")

    def anunciar_version(self, version, local: bool = False, lista: bool = False) -> None:
        """Avisa de una version nueva.

        `local`: compilacion en la carpeta del PC, se instala con el boton.
        `lista`: ya descargada y comprobada por la app; se instala al cerrar o con
        "Reiniciar y actualizar". Sin ninguna de las dos, solo el enlace de descarga.
        """
        cabecera = t("Hay una version nueva: <b>{version}</b>.", version=version.etiqueta)
        self.boton_reiniciar.setVisible(lista)
        if lista:
            self.aviso_version.setText(
                cabecera + " " + t(
                    "Ya esta descargada y comprobada: se instala sola al cerrar Farmadex, "
                    "o ahora mismo con el boton. Tus objetivos y ajustes se conservan."
                )
            )
            self.boton_instalar.setVisible(False)
            try:
                self.boton_reiniciar.clicked.disconnect()
            except RuntimeError:
                pass
            self.boton_reiniciar.clicked.connect(lambda: self.instalar_version.emit(version))
        elif local:
            self.aviso_version.setText(
                cabecera + " " + t("Al instalarla se cierra Farmadex; tus objetivos y ajustes se conservan.")
            )
            self.boton_instalar.setVisible(True)
            try:
                self.boton_instalar.clicked.disconnect()
            except RuntimeError:
                pass
            self.boton_instalar.clicked.connect(lambda: self.instalar_version.emit(version))
        else:
            self.aviso_version.setText(
                f'{cabecera} <a style="color:{PALETA["acento"]}" href="{version.url}">'
                f"{t('Descargarla')}</a>"
            )
        self._color_version = "aviso"
        self.aviso_version.setStyleSheet(f"color: {PALETA['aviso']};")

    # -- datos ------------------------------------------------------------------

    def refrescar_estado(self) -> None:
        if not indice.hay_indice():
            self.estado_datos.setText(t("Todavia no hay indice construido."))
            return
        try:
            con = indice.conectar()
            meta = dict(con.execute("SELECT clave, valor FROM meta").fetchall())
            objetos = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            con.close()
        except sqlite3.Error as e:
            self.estado_datos.setText(t("No se pudo leer el indice: {error}", error=e))
            return
        self.estado_datos.setText(
            t("<b>{n}</b> objetos en el catalogo", n=objetos) + "<br>"
            + t("Catalogo del {fecha}", fecha=meta.get("items_fecha", "?")[:10]) + " &middot; "
            + t("tablas de drops del {fecha}", fecha=_fecha(meta.get("drops_modified"))) + "<br>"
            + t("Indice construido el {fecha}",
                fecha=meta.get("construido_en", "?")[:16].replace("T", " "))
        )


def _fecha(valor: str | None) -> str:
    """drop-data da la fecha en milisegundos desde 1970; el resto ya viene legible."""
    if not valor:
        return "?"
    if valor.isdigit():
        from datetime import datetime

        return datetime.fromtimestamp(int(valor) / 1000).strftime("%Y-%m-%d %H:%M")
    return valor[:16].replace("T", " ")
