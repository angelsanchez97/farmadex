"""Pestana Mundo: que hago ahora mismo.

No es una lista de todo lo que existe: lo que cruza con tus objetivos arriba y
marcado, lo que caduca pronto en naranja, lo terminado fuera, y el resto en
bloques plegables. Dos disposiciones a elegir: `lista` (una columna por orden
de prioridad) y `tablero` (fisuras a la izquierda, el dia a la derecha).
"""

from __future__ import annotations

import html
import unicodedata
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..idiomas import t
from ..online.worldstate import Fisura, Mundo, restante
from ..registro_log import obtener
from . import glosario
from .widgets import PALETA

log = obtener("mundo")

# Claves internas de los filtros; lo que se ensena es su traduccion.
ERAS = ("Todas", "Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia")
MODOS = ("Todas", "Normal", "Camino de Acero", "Tormenta del Vacio")
TITULOS = {
    "ahora": "Ahora",
    "objetivos": "Para tus objetivos",
    "fisuras": "Fisuras del Vacio",
    "acero": "Fisuras del Camino de Acero",
    "tormentas": "Tormentas del Vacio",
    "ciclos": "Ciclos",
    "invasiones": "Invasiones y alertas",
    "sortie": "Incursion y arcontes",
    "baro": "Baro Ki'Teer",
    "nightwave": "Nightwave y Camino de Acero",
}
DISENOS = ("lista", "tablero")
DISENO_POR_DEFECTO = "lista"
# Por debajo de estos minutos la cuenta atras se pinta en naranja.
MINUTOS_URGENTE = 10
# Bloques que nacen plegados: se abren con un clic y se quedan asi hasta cerrar.
PLEGADAS_POR_DEFECTO = {"acero": True, "tormentas": True, "invasiones": True, "nightwave": True}
# Cuantas lineas ensena cada bloque antes de resumir el resto.
MAX_INVASIONES = 5
MAX_NIGHTWAVE = 6
MAX_BARO = 12
# En "Para tus objetivos" solo las mas rapidas de cada era; el resto queda abajo, marcado.
MAX_POR_ERA_OBJETIVOS = 2
# Misiones rapidas primero: lo que se acaba en tres minutos por delante de lo sin fin.
RAPIDEZ = {
    "capture": 0, "captura": 0,
    "extermination": 1, "exterminate": 1, "exterminio": 1,
    "rescue": 2, "rescate": 2,
    "sabotage": 3, "sabotaje": 3,
    "spy": 4, "espionaje": 4,
    "mobile defense": 5, "defensa movil": 5,
    "assassination": 6, "asesinato": 6, "hijack": 6, "secuestro": 6,
    "disruption": 7, "disrupcion": 7,
    "excavation": 8, "excavacion": 8,
    "defense": 9, "defensa": 9, "survival": 9, "supervivencia": 9,
    "interception": 10, "intercepcion": 10,
}


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def rapidez(mision: str) -> int:
    """0 = se hace en tres minutos; 10 = sin fin. Desconocidas, en medio."""
    return RAPIDEZ.get(_sin_tildes(mision or "").lower().strip(), 6)


def minutos_restantes(expira: datetime | None, ahora: datetime | None = None) -> float | None:
    if not expira:
        return None
    ahora = ahora or datetime.now(timezone.utc)
    return (expira - ahora).total_seconds() / 60


def _restante(expira) -> str:
    """La cuenta atras, en naranja si queda poco; con palabra cuando ya ha pasado."""
    texto = restante(expira)
    if texto == "terminado":
        return t("terminado")
    minutos = minutos_restantes(expira)
    if minutos is not None and minutos < MINUTOS_URGENTE:
        return f"<span style='color:{PALETA['aviso']};font-weight:bold'>{texto}</span>"
    return texto


def _terminado(expira) -> bool:
    return expira is not None and restante(expira) == "terminado"


class Seccion(QFrame):
    """Un bloque del mundo, plegable por su titulo. Guarda las cuentas atras para refrescarlas."""

    def __init__(self, titulo: str, clave: str, plegadas: dict[str, bool], parent=None):
        super().__init__(parent)
        self.clave = clave
        self._plegadas = plegadas
        self._titulo = titulo
        self.setObjectName("seccion")
        p = PALETA
        self.setStyleSheet(
            f"#seccion {{ background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: 10px; }}"
        )

        self.boton = QToolButton()
        self.boton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.boton.setCursor(Qt.PointingHandCursor)
        self.boton.setAutoRaise(True)
        self.boton.setStyleSheet(
            f"QToolButton {{ color: {p['acento']}; font-weight: 600; font-size: 13px;"
            " letter-spacing: 1px; border: none; padding: 2px 4px; background: transparent; }"
            f" QToolButton:hover {{ color: {p['texto']}; }}"
        )
        self.boton.clicked.connect(self._alternar)
        # A la derecha del titulo: un contador, o la cuenta atras del bloque.
        self.extra = QLabel()
        self.extra.setTextFormat(Qt.RichText)
        self.extra.setStyleSheet(f"color: {p['suave']}; font-size: 13px;")
        cabecera = QHBoxLayout()
        cabecera.setContentsMargins(6, 4, 10, 0)
        cabecera.addWidget(self.boton)
        cabecera.addStretch(1)
        cabecera.addWidget(self.extra)

        self.cuerpo = QWidget()
        self.caja = QVBoxLayout(self.cuerpo)
        self.caja.setContentsMargins(12, 2, 12, 8)
        self.caja.setSpacing(3)

        todo = QVBoxLayout(self)
        todo.setContentsMargins(0, 0, 0, 0)
        todo.setSpacing(0)
        todo.addLayout(cabecera)
        todo.addWidget(self.cuerpo)

        self.relojes: list[tuple[QLabel, str, object]] = []
        self.extra_expira = None
        # Que hacer con un enlace que no es del glosario (item:...): lo pone la pestana.
        self.al_activar = None
        self.setTitle(titulo)
        self._aplicar_pliegue()

    def _preparar(self, etiqueta: QLabel) -> None:
        etiqueta.setTextFormat(Qt.RichText)
        etiqueta.linkHovered.connect(lambda url: glosario.mostrar(url, etiqueta) if url else None)
        etiqueta.linkActivated.connect(self._activar)

    def _activar(self, url: str) -> None:
        if glosario.mostrar(url, self):
            return
        if self.al_activar:
            self.al_activar(url)

    # -- titulo y pliegue ----------------------------------------------------

    def title(self) -> str:
        return self._titulo

    def setTitle(self, texto: str) -> None:  # noqa: N802 - mismo nombre que QGroupBox
        self._titulo = texto
        self.boton.setText(texto.upper())

    def plegada(self) -> bool:
        return bool(self._plegadas.get(self.clave, False))

    def _alternar(self) -> None:
        self._plegadas[self.clave] = not self.plegada()
        self._aplicar_pliegue()

    def _aplicar_pliegue(self) -> None:
        plegada = self.plegada()
        self.cuerpo.setVisible(not plegada)
        self.boton.setArrowType(Qt.RightArrow if plegada else Qt.DownArrow)

    # -- contenido ----------------------------------------------------------------

    def limpiar(self) -> None:
        self.relojes.clear()
        self.extra_expira = None
        self.extra.setText("")
        while self.caja.count():
            elemento = self.caja.takeAt(0)
            if elemento.widget():
                elemento.widget().deleteLater()
            elif elemento.layout():
                _vaciar_layout(elemento.layout())

    def contador(self, n: int) -> None:
        self.extra.setText(str(n))

    def cuenta_atras(self, expira, prefijo: str = "") -> None:
        """La cuenta atras del bloque entero (la incursion, Baro) al lado del titulo."""
        self.extra_expira = (prefijo, expira)
        self._pintar_extra()

    def _pintar_extra(self) -> None:
        if self.extra_expira is None:
            return
        prefijo, expira = self.extra_expira
        texto = _restante(expira)
        self.extra.setText(f"{html.escape(prefijo)} {texto}".strip() if texto else html.escape(prefijo))

    def linea(self, texto_html: str, expira=None, marcada: bool = False) -> QLabel:
        etiqueta = QLabel()
        self._preparar(etiqueta)
        etiqueta.setWordWrap(True)
        etiqueta.setText(texto_html if expira is None else f"{texto_html} · {_restante(expira)}")
        if marcada:
            p = PALETA
            etiqueta.setStyleSheet(
                f"background: {p['panel2']}; border-left: 3px solid {p['ok']};"
                " border-radius: 4px; padding: 3px 6px;"
            )
        self.caja.addWidget(etiqueta)
        if expira is not None:
            self.relojes.append((etiqueta, texto_html, expira))
        return etiqueta

    def subtitulo(self, texto_html: str) -> None:
        etiqueta = QLabel(texto_html)
        self._preparar(etiqueta)
        etiqueta.setStyleSheet(f"color: {PALETA['suave']}; margin-top: 4px;")
        self.caja.addWidget(etiqueta)

    def vacia(self, texto: str) -> None:
        self.linea(f"<span style='color:{PALETA['suave']}'>{html.escape(texto)}</span>")

    def rejilla(self, celdas: list[tuple[str, object]], columnas: int = 3) -> None:
        """Varias cosas cortas en filas de `columnas` (los ciclos, por ejemplo)."""
        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(14)
        rejilla.setVerticalSpacing(2)
        for i, (texto_html, expira) in enumerate(celdas):
            etiqueta = QLabel()
            self._preparar(etiqueta)
            etiqueta.setText(texto_html if expira is None else f"{texto_html} · {_restante(expira)}")
            rejilla.addWidget(etiqueta, i // columnas, i % columnas)
            if expira is not None:
                self.relojes.append((etiqueta, texto_html, expira))
        self.caja.addLayout(rejilla)

    def refrescar_relojes(self) -> None:
        for etiqueta, base, expira in self.relojes:
            if _terminado(expira):
                # Lo que ha caducado desaparece sin esperar al siguiente refresco.
                etiqueta.hide()
                continue
            etiqueta.setText(f"{base} · {_restante(expira)}")
        self._pintar_extra()


def _vaciar_layout(layout) -> None:
    while layout.count():
        elemento = layout.takeAt(0)
        if elemento.widget():
            elemento.widget().deleteLater()
        elif elemento.layout():
            _vaciar_layout(elemento.layout())


# Compatibilidad con quien importaba la tarjeta antigua.
Tarjeta = Seccion


class PestanaMundo(QWidget):
    # Un objeto de Baro pinchado: la ventana abre su ficha en Buscar.
    abrir_item = Signal(int)

    def __init__(self, parent=None, diseno: str = DISENO_POR_DEFECTO):
        super().__init__(parent)
        self.diseno = diseno if diseno in DISENOS else DISENO_POR_DEFECTO
        self.mundo: Mundo | None = None
        self._motivo_fallo: str | None = None
        # Para cruzar las fisuras con los objetivos: conexiones que pasa la ventana.
        self.indice = None
        self.usuario = None
        self._eras_necesarias: dict[str, list[str]] = {}
        self._plegadas: dict[str, bool] = dict(PLEGADAS_POR_DEFECTO)
        p = PALETA

        self.filtro_era = QComboBox()
        for era in ERAS:
            self.filtro_era.addItem(t(era), era)
        self.filtro_era.currentIndexChanged.connect(lambda _: self.pintar())
        glosario.aplicar(self.filtro_era, "era")
        self.filtro_modo = QComboBox()
        for modo in MODOS:
            self.filtro_modo.addItem(t(modo), modo)
        self.filtro_modo.currentIndexChanged.connect(lambda _: self.pintar())
        glosario.aplicar(self.filtro_modo, "camino_de_acero")
        self.aviso = QLabel(t("Consultando el estado del mundo..."))
        self.aviso.setStyleSheet(f"color: {p['suave']};")

        self.etiqueta_fisuras = QLabel(t("Fisuras:"))
        glosario.aplicar(self.etiqueta_fisuras, "fisura")
        filtros = QHBoxLayout()
        filtros.addWidget(self.etiqueta_fisuras)
        filtros.addWidget(self.filtro_era)
        filtros.addWidget(self.filtro_modo)
        filtros.addWidget(self.aviso, 1)

        self.tarjetas = {clave: Seccion(t(titulo), clave, self._plegadas) for clave, titulo in TITULOS.items()}
        for seccion in self.tarjetas.values():
            seccion.al_activar = self._enlace
        glosario.aplicar(self.tarjetas["fisuras"].boton, "fisura")
        glosario.aplicar(self.tarjetas["acero"].boton, "camino_de_acero")
        glosario.aplicar(self.tarjetas["tormentas"].boton, "tormenta")
        glosario.aplicar(self.tarjetas["baro"].boton, "baro")

        contenido = QWidget()
        if self.diseno == "tablero":
            rejilla = QGridLayout(contenido)
            rejilla.setHorizontalSpacing(10)
            rejilla.setVerticalSpacing(8)
            izquierda, derecha = QVBoxLayout(), QVBoxLayout()
            for clave in ("objetivos", "fisuras", "acero", "tormentas"):
                izquierda.addWidget(self.tarjetas[clave])
            izquierda.addStretch(1)
            for clave in ("ciclos", "baro", "sortie", "invasiones", "nightwave"):
                derecha.addWidget(self.tarjetas[clave])
            derecha.addStretch(1)
            rejilla.addLayout(izquierda, 0, 0)
            rejilla.addLayout(derecha, 0, 1)
            rejilla.setColumnStretch(0, 3)
            rejilla.setColumnStretch(1, 2)
            self.tarjetas["ahora"].hide()
        else:
            columna = QVBoxLayout(contenido)
            columna.setSpacing(8)
            for clave in ("ahora", "objetivos", "fisuras", "acero", "tormentas", "sortie", "baro",
                          "invasiones", "nightwave"):
                columna.addWidget(self.tarjetas[clave])
            columna.addStretch(1)
            self.tarjetas["ciclos"].hide()

        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(contenido)

        caja = QVBoxLayout(self)
        caja.addLayout(filtros)
        caja.addWidget(desplazable, 1)

        self._reloj = QTimer(self)
        self._reloj.timeout.connect(self._tic)
        self._reloj.start(1000)

    def _enlace(self, url: str) -> None:
        if url.startswith("item:"):
            self.abrir_item.emit(int(url.removeprefix("item:")))

    # -- idioma -------------------------------------------------------------

    def retraducir(self) -> None:
        for i, era in enumerate(ERAS):
            self.filtro_era.setItemText(i, t(era))
        for i, modo in enumerate(MODOS):
            self.filtro_modo.setItemText(i, t(modo))
        self.etiqueta_fisuras.setText(t("Fisuras:"))
        for clave, titulo in TITULOS.items():
            self.tarjetas[clave].setTitle(t(titulo))
        for clave, termino in (("fisuras", "fisura"), ("acero", "camino_de_acero"),
                               ("tormentas", "tormenta"), ("baro", "baro")):
            glosario.aplicar(self.tarjetas[clave].boton, termino)
        glosario.aplicar(self.filtro_era, "era")
        glosario.aplicar(self.filtro_modo, "camino_de_acero")
        glosario.aplicar(self.etiqueta_fisuras, "fisura")
        if self.mundo is None and self._motivo_fallo is None:
            self.aviso.setText(t("Consultando el estado del mundo..."))
        elif self._motivo_fallo is not None:
            self.marcar_desactualizado(self._motivo_fallo)
        self.pintar()

    # -- datos -------------------------------------------------------------

    def conectar_objetivos(self, indice, usuario) -> None:
        """Con el indice y la BD del usuario se sabe que eras de reliquia hacen falta."""
        self.indice = indice
        self.usuario = usuario
        self.refrescar_objetivos()

    def refrescar_objetivos(self) -> None:
        """Tras anadir o completar un objetivo: las fisuras marcadas cambian."""
        self._eras_necesarias = self._calcular_eras()
        self.pintar()

    def _calcular_eras(self) -> dict[str, list[str]]:
        if self.indice is None or self.usuario is None:
            return {}
        from ..estado import objetivos as estado_objetivos

        try:
            return estado_objetivos.eras_necesarias(self.indice, self.usuario)
        except Exception:  # noqa: BLE001 - un fallo aqui no puede dejar Mundo en blanco
            log.warning("No se pudieron calcular las eras de los objetivos", exc_info=True)
            return {}

    def actualizar(self, mundo: Mundo) -> None:
        self.mundo = mundo
        self._motivo_fallo = None
        if self.indice is not None:
            self._eras_necesarias = self._calcular_eras()
        self.aviso.setText("")
        self.aviso.setStyleSheet(f"color: {PALETA['suave']};")
        self.pintar()

    def marcar_desactualizado(self, motivo: str) -> None:
        self._motivo_fallo = motivo
        if self.mundo is None:
            self.aviso.setText(t("Sin conexion con el estado del mundo ({motivo})", motivo=motivo))
        else:
            self.aviso.setText(t("Datos del mundo sin actualizar; se muestra lo ultimo conocido"))
        self.aviso.setStyleSheet(f"color: {PALETA['aviso']};")

    def _tic(self) -> None:
        for tarjeta in self.tarjetas.values():
            tarjeta.refrescar_relojes()

    # -- pintado -------------------------------------------------------------

    def pintar(self) -> None:
        mundo = self.mundo
        for tarjeta in self.tarjetas.values():
            tarjeta.limpiar()
        if mundo is None:
            return
        self._pintar_ahora(mundo)
        abiertas = self._fisuras_abiertas(mundo)
        para_objetivos = self._pintar_objetivos(abiertas)
        self._pintar_fisuras(abiertas, ya_pintadas=para_objetivos)
        self._pintar_ciclos(mundo)
        self._pintar_invasiones(mundo)
        self._pintar_sortie(mundo)
        self._pintar_nightwave(mundo)
        self._pintar_baro(mundo)

    # Fisuras ------------------------------------------------------------

    def _fisuras_abiertas(self, mundo: Mundo) -> list[Fisura]:
        """Las que no han terminado y pasan el filtro, de la mas rapida a la mas larga."""
        era = self.filtro_era.currentData()
        modo = self.filtro_modo.currentData()
        salida = []
        for f in mundo.fisuras:
            if _terminado(f.expira):
                continue
            if era != "Todas" and f.era != era:
                continue
            if modo == "Normal" and (f.acero or f.tormenta):
                continue
            if modo == "Camino de Acero" and not f.acero:
                continue
            if modo == "Tormenta del Vacio" and not f.tormenta:
                continue
            salida.append(f)
        # Rapidas primero; a igual rapidez, la que mas tiempo deja.
        salida.sort(key=lambda f: (rapidez(f.mision), -(minutos_restantes(f.expira) or 0)))
        return salida

    def _objetivos_de(self, f: Fisura) -> list[str]:
        return self._eras_necesarias.get(f.era, [])

    def _html_fisura(self, f: Fisura, con_era: bool = True) -> str:
        p = PALETA
        partes = []
        if con_era:
            partes.append(glosario.enlace("era", f.era, p["acento"], negrita=True))
        partes.append(f"<b>{html.escape(f.nodo)}</b>")
        if f.mision:
            partes.append(html.escape(f.mision))
        if f.enemigo:
            partes.append(f"<span style='color:{p['suave']}'>{html.escape(f.enemigo)}</span>")
        if f.acero:
            partes.append(glosario.enlace("camino_de_acero", t("Acero"), p["aviso"]))
        if f.tormenta:
            partes.append(glosario.enlace("tormenta", t("Tormenta"), p["aviso"]))
        texto = " · ".join(partes)
        objetivos = self._objetivos_de(f)
        if objetivos:
            texto += (
                f" <span style='color:{p['ok']}'>&rarr; "
                f"{html.escape(', '.join(dict.fromkeys(objetivos)))}</span>"
            )
        return texto

    def _pintar_objetivos(self, abiertas: list[Fisura]) -> set[int]:
        """Arriba del todo, las fisuras que sirven para lo que estas farmeando."""
        seccion = self.tarjetas["objetivos"]
        if not self._eras_necesarias:
            seccion.hide()
            return set()
        seccion.show()
        # Para leer de reojo: las dos mas rapidas de cada era que hace falta. Las de
        # Acero y Tormenta solo si el filtro las pide; el resto sigue abajo, marcado.
        modo = self.filtro_modo.currentData()
        candidatas = [
            f for f in abiertas
            if self._objetivos_de(f) and (modo != "Todas" or not (f.acero or f.tormenta))
        ]
        por_era: dict[str, int] = {}
        utiles = []
        for f in candidatas:
            if por_era.get(f.era, 0) < MAX_POR_ERA_OBJETIVOS:
                por_era[f.era] = por_era.get(f.era, 0) + 1
                utiles.append(f)
        for f in utiles:
            seccion.linea(self._html_fisura(f), f.expira, marcada=True)
        total = sum(1 for f in abiertas if self._objetivos_de(f))
        if utiles:
            seccion.extra.setText(
                t("{n} de {total}", n=len(utiles), total=total) if total > len(utiles) else str(total)
            )
        else:
            eras = ", ".join(
                f"{glosario.enlace('era', era, PALETA['acento'], negrita=True)} "
                f"<span style='color:{PALETA['suave']}'>({html.escape(', '.join(dict.fromkeys(nombres)))})</span>"
                for era, nombres in self._eras_necesarias.items()
            )
            seccion.linea(
                f"<span style='color:{PALETA['suave']}'>"
                + html.escape(t("Ninguna fisura abierta sirve ahora mismo. Necesitas:"))
                + f"</span> {eras}"
            )
        return {id(f) for f in utiles}

    def _pintar_fisuras(self, abiertas: list[Fisura], ya_pintadas: set[int]) -> None:
        grupos = {"fisuras": [], "acero": [], "tormentas": []}
        for f in abiertas:
            if id(f) in ya_pintadas:
                continue
            clave = "tormentas" if f.tormenta else ("acero" if f.acero else "fisuras")
            grupos[clave].append(f)
        for clave, fisuras in grupos.items():
            seccion = self.tarjetas[clave]
            seccion.contador(len(fisuras))
            if not fisuras:
                if clave == "fisuras":
                    seccion.show()
                    seccion.vacia(t("No hay fisuras abiertas con ese filtro"))
                else:
                    seccion.hide()
                continue
            seccion.show()
            if self.diseno == "tablero":
                self._pintar_fisuras_por_era(seccion, fisuras)
            else:
                for f in fisuras:
                    seccion.linea(self._html_fisura(f), f.expira)

    def _pintar_fisuras_por_era(self, seccion: Seccion, fisuras: list[Fisura]) -> None:
        """Tablero: agrupadas por era, con la era como cabecera y las lineas cortas."""
        p = PALETA
        orden = {era: i for i, era in enumerate(ERAS)}
        por_era: dict[str, list[Fisura]] = {}
        for f in fisuras:
            por_era.setdefault(f.era, []).append(f)
        for era in sorted(por_era, key=lambda e: orden.get(e, 99)):
            lista = por_era[era]
            seccion.subtitulo(
                glosario.enlace("era", era, p["acento"], negrita=True)
                + f" <span style='color:{p['suave']}'>&middot; {len(lista)}</span>"
            )
            for f in lista:
                seccion.linea(self._html_fisura(f, con_era=False), f.expira)

    # El resto del mundo ---------------------------------------------------

    def _pintar_ahora(self, mundo: Mundo) -> None:
        """Lista: una franja con los ciclos y Baro, para leer de reojo."""
        seccion = self.tarjetas["ahora"]
        if self.diseno != "lista":
            return
        celdas = [(f"<b>{html.escape(c.nombre)}</b>: {html.escape(c.estado)}", c.expira) for c in mundo.ciclos]
        if celdas:
            seccion.rejilla(celdas, columnas=3)
        baro = getattr(mundo, "baro_detalle", None)
        if baro is not None:
            seccion.linea(self._html_baro_cabecera(baro), baro.expira if baro.activo else baro.llegada)
        elif mundo.baro_cabecera:
            seccion.linea(f"<b>{html.escape(mundo.baro_cabecera)}</b>")
        if not celdas and baro is None and not mundo.baro_cabecera:
            seccion.vacia(t("Sin datos de ciclos"))

    def _pintar_ciclos(self, mundo: Mundo) -> None:
        seccion = self.tarjetas["ciclos"]
        for c in mundo.ciclos:
            seccion.linea(f"<b>{html.escape(c.nombre)}</b>: {html.escape(c.estado)}", c.expira)
        if not mundo.ciclos:
            seccion.vacia(t("Sin datos de ciclos"))

    def _pintar_invasiones(self, mundo: Mundo) -> None:
        p = PALETA
        seccion = self.tarjetas["invasiones"]
        total = len(mundo.invasiones) + len(mundo.alertas) + (1 if mundo.arbitracion else 0)
        seccion.contador(total)
        for a in mundo.alertas:
            seccion.linea(f"<b>{t('Alerta')}</b> {html.escape(a.texto)}", a.expira)
        if mundo.arbitracion:
            seccion.linea(
                f"<b>{t('Arbitracion')}</b> {html.escape(mundo.arbitracion.texto)} "
                f"<span style='color:{p['suave']}'>{html.escape(mundo.arbitracion.detalle)}</span>",
                mundo.arbitracion.expira,
            )
        for i in mundo.invasiones[:MAX_INVASIONES]:
            bandos = (
                " (" + t("{atacante} contra {defensor}", atacante=i.atacante, defensor=i.defensor) + ")"
                if i.atacante and i.defensor
                else ""
            )
            seccion.linea(
                f"<b>{html.escape(i.nodo)}</b> · {html.escape(i.descripcion + bandos)}"
                + (f" · {html.escape(i.recompensas)}" if i.recompensas else "")
                + f" · {abs(i.porcentaje):.0f}%"
            )
        sobran = len(mundo.invasiones) - MAX_INVASIONES
        if sobran > 0:
            seccion.vacia(t("y {n} invasiones mas", n=sobran))
        if not total:
            seccion.vacia(t("No hay invasiones ni alertas activas"))

    def _pintar_sortie(self, mundo: Mundo) -> None:
        p = PALETA
        seccion = self.tarjetas["sortie"]
        if mundo.sortie:
            seccion.cuenta_atras(mundo.sortie[0].expira)
            seccion.subtitulo(f"<b>{t('Incursion del dia')}</b>")
            for r in mundo.sortie:
                seccion.linea(
                    f"&nbsp;&nbsp;{html.escape(r.texto)}"
                    + (f" <span style='color:{p['suave']}'>{html.escape(r.detalle)}</span>" if r.detalle else "")
                )
        if mundo.arcontes:
            seccion.subtitulo(f"<b>{t('Caza de arcontes')}</b> · {_restante(mundo.arcontes[0].expira)}")
            for r in mundo.arcontes:
                seccion.linea(f"&nbsp;&nbsp;{html.escape(r.texto)}")
        if not (mundo.sortie or mundo.arcontes):
            seccion.vacia(t("Sin incursion ni caza de arcontes"))

    def _pintar_nightwave(self, mundo: Mundo) -> None:
        p = PALETA
        seccion = self.tarjetas["nightwave"]
        seccion.contador(len(mundo.nightwave) + len(mundo.acero))
        for r in mundo.acero:
            seccion.linea(
                glosario.enlace("camino_de_acero", t("Camino de Acero"), p["texto"], negrita=True)
                + f": {html.escape(r.texto)} <span style='color:{p['suave']}'>{html.escape(r.detalle)}</span>",
                r.expira,
            )
        for r in mundo.nightwave[:MAX_NIGHTWAVE]:
            seccion.linea(
                f"{html.escape(r.texto)} <span style='color:{p['suave']}'>{html.escape(r.detalle)}</span>",
                r.expira,
            )
        sobran = len(mundo.nightwave) - MAX_NIGHTWAVE
        if sobran > 0:
            seccion.vacia(t("y {n} retos mas", n=sobran))
        if not (mundo.nightwave or mundo.acero):
            seccion.vacia(t("Sin retos activos"))

    def _html_baro_cabecera(self, baro) -> str:
        p = PALETA
        nombre = glosario.enlace("baro", baro.personaje or "Baro Ki'Teer", p["texto"], negrita=True)
        if baro.activo:
            return f"{nombre} {html.escape(t('en'))} <b>{html.escape(baro.lugar)}</b>"
        return f"{nombre} {html.escape(t('llega a {lugar}', lugar=baro.lugar) if baro.lugar else t('llega pronto'))}"

    def _pintar_baro(self, mundo: Mundo) -> None:
        p = PALETA
        seccion = self.tarjetas["baro"]
        baro = getattr(mundo, "baro_detalle", None)
        if baro is None:
            # Datos antiguos: solo la cabecera en texto y la lista tal cual.
            seccion.linea(f"<b>{html.escape(mundo.baro_cabecera)}</b>", mundo.baro[0].expira if mundo.baro else None)
            for o in mundo.baro[:MAX_BARO]:
                seccion.linea(f"&nbsp;&nbsp;{html.escape(o.texto)} <span style='color:{p['suave']}'>{html.escape(o.detalle)}</span>")
            if not mundo.baro:
                seccion.vacia(t("Vuelve a un relevo cuando llegue"))
            return
        if baro.activo:
            seccion.cuenta_atras(baro.expira, t("se va en"))
            seccion.linea(self._html_baro_cabecera(baro))
            # Lo que cubre un objetivo, primero y marcado; luego por ducados.
            inventario = sorted(baro.inventario, key=lambda o: (not o.objetivo, -(o.ducados or 0)))
            for o in inventario[:MAX_BARO]:
                precio = []
                if o.ducados:
                    precio.append(glosario.enlace("ducados", t("{n} ducados", n=o.ducados), p["suave"]))
                if o.creditos:
                    precio.append(f"<span style='color:{p['suave']}'>{o.creditos:,} cr</span>".replace(",", "."))
                nombre = html.escape(o.nombre_mostrar)
                if o.item_id:
                    nombre = f"<a style='color:{p['texto']};text-decoration:none' href='item:{o.item_id}'>{nombre}</a>"
                texto = f"{nombre} · {' · '.join(precio)}" if precio else nombre
                if o.objetivo:
                    texto += f" <span style='color:{p['ok']}'>&rarr; {html.escape(t('cubre un objetivo'))}</span>"
                seccion.linea(texto, marcada=bool(o.objetivo))
            sobran = len(baro.inventario) - MAX_BARO
            if sobran > 0:
                seccion.vacia(t("y {n} objetos mas", n=sobran))
            if not baro.inventario:
                seccion.vacia(t("Inventario todavia sin publicar"))
        else:
            seccion.cuenta_atras(baro.llegada, t("llega en"))
            seccion.linea(self._html_baro_cabecera(baro), baro.llegada)
            seccion.vacia(t("Guarda piezas Prime repetidas para cambiarlas por ducados cuando llegue"))
