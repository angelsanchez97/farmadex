"""Pestana Build: lee la pantalla de mejoras del arsenal y lista lo que lleva.

Cada mod, arcano o equipo reconocido es una fila; al pulsarla se abre su ficha
en Buscar (de donde sale). Lo que el lector leyo pero no supo casar se ensena
aparte como "sin identificar", sin inventar nada.

Si se reconoce la warframe o el arma, "Builds en Overframe" abre las builds de la
comunidad de ese equipo en la pestana Web (ui/builds_overframe.py: solo se abre su web).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..captura.builds import Build
from ..config import cargar
from ..idiomas import t
from . import builds_overframe
from .widgets import PALETA

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
    "Pets": "Companero",
    "Mods": "Mod",
    "Arcanes": "Arcano",
}


class PestanaBuilds(QWidget):
    abrir_item = Signal(int)
    pedir_lectura = Signal()
    # Direccion para ensenar dentro de Farmadex (pestana Web): las builds de Overframe.
    abrir_web = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = cargar()
        self.build: Build | None = None
        self.categorias: dict[int, str] = {}
        self.nombres_en: dict[int, str] = {}

        self.boton = QPushButton()
        self.boton.setObjectName("principal")
        self.boton.setCursor(Qt.PointingHandCursor)
        self.boton.clicked.connect(self.pedir_lectura.emit)
        self.nota = QLabel()
        self.nota.setWordWrap(True)
        self.nota.setStyleSheet(f"color: {PALETA['suave']};")
        self.estado = QLabel("")
        self.estado.setWordWrap(True)
        # Solo se ve con una warframe o un arma reconocida.
        self.boton_overframe = QPushButton()
        self.boton_overframe.setCursor(Qt.PointingHandCursor)
        self.boton_overframe.clicked.connect(self._abrir_overframe)
        self.boton_overframe.hide()
        self.lista = QListWidget()
        self.lista.itemClicked.connect(self._pulsado)

        fila = QHBoxLayout()
        fila.addWidget(self.boton)
        fila.addStretch(1)
        fila.addWidget(self.boton_overframe)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 8, 4, 4)
        caja.setSpacing(8)
        caja.addLayout(fila)
        caja.addWidget(self.nota)
        caja.addWidget(self.estado)
        caja.addWidget(self.lista, 1)
        self.retraducir()

    def conectar_indice(self, con) -> None:
        """Categorias y nombres ingleses por id, para agrupar lo reconocido y para las builds
        de Overframe (se llama con el indice listo)."""
        try:
            filas = list(con.execute("SELECT id, categoria, nombre_en FROM items"))
        except Exception:  # noqa: BLE001 - sin categorias se lista todo junto
            filas = []
        self.categorias = {fila[0]: fila[1] for fila in filas}
        self.nombres_en = {fila[0]: fila[2] or "" for fila in filas}

    def retraducir(self) -> None:
        atajo = self.config.get("hotkey_build", "")
        self.boton.setText(t("Leer la pantalla de mejoras ({atajo})", atajo=atajo) if atajo else t("Leer la pantalla de mejoras"))
        self.nota.setText(t(
            "En el juego, abre Arsenal > Mejorar de la warframe o el arma que quieras y pulsa el boton "
            "o el atajo. Farmadex lee los nombres de los mods de la pantalla y te deja pulsar cada uno "
            "para ver de donde sale. Lo que no reconozca con seguridad lo deja aparte."
        ))
        self.boton_overframe.setText(t("Builds en Overframe"))
        self.boton_overframe.setToolTip(t("Abre Overframe, la web de builds de la comunidad, con este "
                                          "warframe o arma, dentro de Farmadex (pestana Web)."))
        if self.build is not None:
            self.mostrar_build(self.build)

    def repintar(self) -> None:
        self.nota.setStyleSheet(f"color: {PALETA['suave']};")
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

    def mostrar_build(self, build: Build) -> None:
        self.build = build
        self.boton_overframe.setVisible(bool(self.url_overframe()))
        self.lista.clear()
        if build.vacia:
            self.estado.setText(t(
                "No se ha reconocido nada. Comprueba que la pantalla de mejoras esta abierta y a la vista."
            ))
            if build.sin_identificar:
                self._seccion(t("Se leyo pero no se reconocio"))
                for texto in build.sin_identificar:
                    self._fila_texto(texto)
            return
        partes = []
        if build.equipo is not None:
            partes.append(build.equipo.nombre)
        partes.append(t("{n} mods", n=len(build.equipados) + len(build.coleccion)))
        if build.arcanos:
            partes.append(t("{n} arcanos", n=len(build.arcanos)))
        self.estado.setText(t("Leido: {resumen}. Pulsa una fila para ver de donde sale.", resumen=", ".join(partes)))

        if build.equipo is not None:
            self._seccion(t("Equipo"))
            self._fila_item(build.equipo.item_id, build.equipo.nombre, build.equipo.puntuacion)
        elif build.equipo_texto:
            self._seccion(t("Equipo"))
            self._fila_texto(t("\"{texto}\" (sin identificar)", texto=build.equipo_texto))
        if build.equipados:
            self._seccion(t("Mods equipados"))
            for r in build.equipados:
                self._fila_item(r.item_id, r.nombre, r.puntuacion)
        if build.arcanos:
            self._seccion(t("Arcanos"))
            for r in build.arcanos:
                self._fila_item(r.item_id, r.nombre, r.puntuacion)
        if build.coleccion:
            self._seccion(t("En la coleccion (abajo)"))
            for r in build.coleccion:
                self._fila_item(r.item_id, r.nombre, r.puntuacion)
        if build.sin_identificar:
            self._seccion(t("Se leyo pero no se reconocio"))
            for texto in build.sin_identificar:
                self._fila_texto(texto)

    def _seccion(self, titulo: str) -> None:
        fila = QListWidgetItem(titulo)
        fila.setFlags(Qt.NoItemFlags)
        fila.setForeground(Qt.GlobalColor.white)
        fuente = fila.font()
        fuente.setBold(True)
        fila.setFont(fuente)
        self.lista.addItem(fila)

    def _fila_item(self, item_id: int, nombre: str, puntuacion: float) -> None:
        categoria = CATEGORIA_ES.get(self.categorias.get(item_id, ""), "")
        texto = f"  {nombre}" + (f"   ({t(categoria)})" if categoria else "")
        if puntuacion < 100:
            texto += f"   {t('parecido')} {puntuacion:.0f}%"
        fila = QListWidgetItem(texto)
        fila.setData(Qt.UserRole, item_id)
        fila.setToolTip(t("Abrir la ficha en Buscar"))
        self.lista.addItem(fila)

    def _fila_texto(self, texto: str) -> None:
        fila = QListWidgetItem(f"  {texto}")
        fila.setFlags(Qt.ItemIsEnabled)
        fila.setForeground(Qt.GlobalColor.gray)
        self.lista.addItem(fila)

    def _pulsado(self, fila: QListWidgetItem) -> None:
        item_id = fila.data(Qt.UserRole)
        if item_id:
            self.abrir_item.emit(int(item_id))

    def ids_listados(self) -> list[int]:
        """Los ids con ficha, en orden (para las pruebas y para la guia)."""
        salida = []
        for i in range(self.lista.count()):
            dato = self.lista.item(i).data(Qt.UserRole)
            if dato:
                salida.append(int(dato))
        return salida
