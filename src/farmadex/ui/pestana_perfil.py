"""Pestana Perfil: importa el JSON de perfil de warframe.com y ensena que falta por dominar.

La capa de datos vive en `farmadex.perfil`; aqui solo se elige el fichero, se
lee en segundo plano (el guardado y el casado van en el hilo principal, que es
el dueno de las conexiones SQLite) y se pinta el resultado en paneles del estilo C:
tu maestria, la maestria por categoria, lo que falta por dominar, el mapa estelar,
intrinsecos, sindicatos y nodos pendientes.
"""

from __future__ import annotations

import html
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QTextDocumentFragment
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import perfil as datos_perfil
from ..estado import usuario_db
from ..idiomas import glosa, nombre as nombre_idioma, t
from ..perfil import A_MEDIAS, DOMINADO, SIN_TOCAR, PerfilInvalido
from ..registro_log import obtener
from .estilo_c import (
    TITULAR,
    BarraFina,
    BotonC,
    EtiquetaC,
    InterruptorTexto,
    PanelC,
    Rombo,
    columna,
    fila,
    hex_de,
    px,
    transparente,
)
from .pestana_buscador import categoria_es
from .widgets import BarraProgreso

log = obtener("perfil_ui")

# Nombres oficiales en castellano de los sindicatos, por su etiqueta del perfil.
SINDICATOS = {
    "SteelMeridianSyndicate": "Meridiano de Acero",
    "ArbitersSyndicate": "Árbitros de Hexis",
    "CephalonSudaSyndicate": "Cefalon Suda",
    "PerrinSyndicate": "Secuencia Perrin",
    "RedVeilSyndicate": "Velo Rojo",
    "NewLokaSyndicate": "Nueva Loka",
    "CetusSyndicate": "Ostrones",
    "QuillsSyndicate": "Los Quills",
    "SolarisSyndicate": "Solaris Unidos",
    "VoxSyndicate": "Vox Solaris",
    "VentKidsSyndicate": "Ventkids",
    "EntratiSyndicate": "Entrati",
    "NecraloidSyndicate": "Necraloid",
    "ZarimanSyndicate": "Los Holdfasts",
    "EntratiLabSyndicate": "Cavia",
    "HexSyndicate": "Los Hex",
    "KahlSyndicate": "Guarnición de Kahl",
    "ConclaveSyndicate": "Conclave",
}
# Color de cada sindicato de facciones (el de su emblema en el juego); el resto, acento.
COLOR_SINDICATO = {
    "SteelMeridianSyndicate": "#e0a060",
    "ArbitersSyndicate": "#6fd6c9",
    "CephalonSudaSyndicate": "#8fb4e0",
    "PerrinSyndicate": "#c9a0e0",
    "RedVeilSyndicate": "#e07070",
    "NewLokaSyndicate": "#8fd28f",
}

# Intrinsecos: los de Railjack y los del Errante, en el orden del juego.
INTRINSECOS = {
    "LPS_PILOTING": "Pilotaje",
    "LPS_GUNNERY": "Artillería",
    "LPS_TACTICAL": "Táctica",
    "LPS_ENGINEERING": "Ingeniería",
    "LPS_COMMAND": "Mando",
    "LPS_DRIFT_RIDING": "Monta",
    "LPS_DRIFT_COMBAT": "Combate",
    "LPS_DRIFT_OPPORTUNITY": "Oportunidad",
    "LPS_DRIFT_ENDURANCE": "Resistencia",
}
_INTRINSECOS_RAILJACK = ("LPS_PILOTING", "LPS_GUNNERY", "LPS_TACTICAL", "LPS_ENGINEERING", "LPS_COMMAND")

# La descarga del perfil desde warframe.com (getProfileViewingData.php) dejo de estar
# abierta en septiembre de 2026: devuelve 403 tambien con la sesion iniciada. La
# importacion desde fichero se queda por si DE la reabre o llega otra fuente (OCR).
_PREFIJOS_NODO = ("SolNode", "ClanNode", "SettlementNode")
# Cuantos objetos "por dominar" y planetas con nodos pendientes caben en el resumen.
MAX_RESUMEN_DOMINAR = 8
MAX_RESUMEN_PLANETAS = 6


class _LectorPerfil(QThread):
    """Lee y valida el fichero fuera del hilo de la interfaz. No toca ninguna BD."""

    leido = Signal(object)
    fallo = Signal(str)

    def __init__(self, ruta: Path, parent=None):
        super().__init__(parent)
        self.ruta = ruta

    def run(self) -> None:
        try:
            self.leido.emit(datos_perfil.cargar(self.ruta))
        except PerfilInvalido as e:
            self.fallo.emit(str(e))
        except Exception:  # noqa: BLE001 - un fichero raro no puede tumbar la ventana
            log.exception("Error leyendo el perfil %s", self.ruta)
            self.fallo.emit(t("No se pudo leer el fichero; mira el registro para el detalle"))


def _vaciar(capa) -> None:
    while capa.count():
        elemento = capa.takeAt(0)
        w = elemento.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif elemento.layout() is not None:
            _vaciar(elemento.layout())


class PestanaPerfil(QWidget):
    perfil_cambiado = Signal()
    abrir_item = Signal(int)

    def __init__(self, usuario: sqlite3.Connection | None = None, parent=None):
        super().__init__(parent)
        transparente(self)
        self.usuario: sqlite3.Connection = usuario if usuario is not None else usuario_db.conectar()
        self.indice: sqlite3.Connection | None = None
        self._lector: _LectorPerfil | None = None
        self._ruta_en_curso: Path | None = None
        self._abiertos: set[str] = set()  # "dominar" / "nodos": listas enteras desplegadas
        self.rango: EtiquetaC | None = None

        # -- cabecera (a la derecha de las sub-pestanas si la pagina va en MIS METAS)
        self.boton = BotonC("", principal=True, icono="importar")
        self.boton.clicked.connect(self.elegir_fichero)
        self.filtro_acero = InterruptorTexto("")
        self.filtro_acero.toggled.connect(lambda _: self.pintar())
        self.controles_cabecera = transparente(QWidget(self))
        self.controles_cabecera.setLayout(fila(self.filtro_acero, px(8, False), self.boton, espacio=px(8, False)))

        self.progreso = BarraProgreso()
        self.estado = EtiquetaC("", "pequeno", envolver=True)
        self.estado.setTextFormat(Qt.PlainText)
        self._pintar_estado("")

        self.contenido = transparente(QWidget())
        self.capa_contenido = QVBoxLayout(self.contenido)
        self.capa_contenido.setContentsMargins(0, 0, px(6, False), px(6, False))
        self.capa_contenido.setSpacing(px(12, False))
        self.desplazable = QScrollArea()
        self.desplazable.setWidgetResizable(True)
        self.desplazable.setFrameShape(QScrollArea.NoFrame)
        transparente(self.desplazable)
        transparente(self.desplazable.viewport())
        self.desplazable.setWidget(self.contenido)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(px(4, False), px(6, False), px(4, False), px(4, False))
        caja.setSpacing(px(10, False))
        # Suelta (sin MIS METAS, en los tests) la cabecera va aqui; la seccion se la lleva.
        caja.addWidget(self.controles_cabecera, 0, Qt.AlignRight)
        caja.addWidget(self.progreso)
        caja.addWidget(self.estado)
        caja.addWidget(self.desplazable, 1)
        self.retraducir()

    # -- ciclo de vida -----------------------------------------------------------

    def conectar_indice(self, con: sqlite3.Connection | None) -> None:
        self.indice = con
        self.pintar()

    def retraducir(self) -> None:
        self.boton.setText(t("Importar perfil (JSON)..."))
        self.filtro_acero.setText(t("Nodos pendientes del Camino de Acero"))
        self._pintar_estado("")  # el aviso de la ultima importacion era de un solo uso
        self.pintar()

    def repintar(self) -> None:
        """Tras cambiar de tema: se rehacen los paneles (algunos textos llevan color)."""
        self._pintar_estado(self.estado.text(), error=self.estado.property("error") or False)
        self.pintar()

    def hay_perfil(self) -> bool:
        return datos_perfil.hay_perfil(self.usuario)

    def texto_plano(self) -> str:
        """Todo el texto de la pagina (tambien lo plegado), sin formato: para los tests
        y para buscar dentro."""
        trozos = []
        for etiqueta in self.contenido.findChildren(QLabel):
            texto = etiqueta.texto_completo() if hasattr(etiqueta, "texto_completo") else etiqueta.text()
            if etiqueta.textFormat() == Qt.RichText or "<" in texto:
                texto = QTextDocumentFragment.fromHtml(texto).toPlainText()
            trozos.append(texto)
        return "\n".join(trozos)

    # -- importar ----------------------------------------------------------------

    def elegir_fichero(self) -> None:
        inicio = Path.home() / "Downloads"
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            t("Elige el JSON de tu perfil"),
            str(inicio if inicio.is_dir() else Path.home()),
            t("Perfil de Warframe (*.json);;Todos los ficheros (*)"),
        )
        if ruta:
            self.importar(Path(ruta))

    def importar(self, ruta: Path | str, en_segundo_plano: bool = True) -> None:
        """Lee el fichero (en su hilo, salvo que se pida lo contrario) y lo guarda."""
        ruta = Path(ruta)
        if self._lector is not None and self._lector.isRunning():
            return
        self._ruta_en_curso = ruta
        self._pintar_estado(t("Leyendo {fichero}...", fichero=ruta.name))
        if not en_segundo_plano:
            try:
                self._leido(datos_perfil.cargar(ruta))
            except PerfilInvalido as e:
                self._fallo(str(e))
            return
        self.boton.setEnabled(False)
        self.progreso.actualizar(t("Importando el perfil..."), 0, 0)
        self._lector = _LectorPerfil(ruta, self)
        self._lector.leido.connect(self._leido)
        self._lector.fallo.connect(self._fallo)
        self._lector.finished.connect(self._terminado)
        self._lector.start()

    def _terminado(self) -> None:
        self.boton.setEnabled(True)
        self.progreso.ocultar()

    def _leido(self, perfil) -> None:
        datos_perfil.guardar(self.usuario, perfil, self._ruta_en_curso)
        mensaje = t(
            "Perfil de {nombre} importado: rango de maestría {rango}, {objetos} objetos con XP y {nodos} nodos",
            nombre=perfil.nombre, rango=perfil.rango, objetos=len(perfil.xp), nodos=len(perfil.nodos),
        )
        if self.indice is not None:
            casado = datos_perfil.casar_con_catalogo(self.usuario, self.indice)
            if casado.sin_catalogo:
                mensaje += " " + t(
                    "({n} objetos del perfil no están en el catálogo; probablemente son del último parche)",
                    n=len(casado.sin_catalogo),
                )
                log.info("Sin catalogo: %s", ", ".join(casado.sin_catalogo[:20]))
        self._pintar_estado(mensaje)
        self.pintar()
        self.perfil_cambiado.emit()

    def _fallo(self, motivo: str) -> None:
        # El motivo viene del lector en castellano y ya es claro; no hace falta dialogo.
        self._pintar_estado(t("No se ha importado: {motivo}", motivo=motivo), error=True)

    def _pintar_estado(self, texto: str, error: bool = False) -> None:
        self.estado.setProperty("error", error)
        self.estado.poner_tinta("aviso" if error else "suave")
        self.estado.setText(texto)
        self.estado.setVisible(bool(texto))

    def _enlace(self, url) -> None:
        texto = url.toString() if isinstance(url, QUrl) else str(url)
        if texto.startswith("item:"):
            self.abrir_item.emit(int(texto[5:]))
        elif texto.startswith("http"):
            import webbrowser

            webbrowser.open(texto)

    def _alternar(self, clave: str) -> None:
        if clave in self._abiertos:
            self._abiertos.discard(clave)
        else:
            self._abiertos.add(clave)
        self.pintar()

    # -- pintar ------------------------------------------------------------------

    def pintar(self) -> None:
        posicion = self.desplazable.verticalScrollBar().value()
        _vaciar(self.capa_contenido)
        self.rango = None
        if self.indice is None:
            self.filtro_acero.setVisible(False)
            self.capa_contenido.addWidget(EtiquetaC(t("Preparando los datos..."), "normal", tinta="suave"))
            self.capa_contenido.addStretch(1)
            return
        if not self.hay_perfil():
            self.filtro_acero.setVisible(False)
            self._pintar_sin_perfil()
            self.capa_contenido.addStretch(1)
            return
        self.filtro_acero.setVisible(True)
        self._pintar_perfil()
        self.capa_contenido.addStretch(1)
        self.desplazable.verticalScrollBar().setValue(posicion)

    def _pintar_sin_perfil(self) -> None:
        panel = PanelC(t("Perfil del jugador: preparado, pero hoy sin fuente de datos"))
        panel.capa.addWidget(EtiquetaC(t(
            "Digital Extremes no publica ahora mismo los datos del perfil: la descarga desde "
            "warframe.com que usaba esta pestaña devuelve acceso denegado, también con la sesión iniciada."
        ), "normal", envolver=True))
        panel.capa.addWidget(EtiquetaC(t(
            "Si consigues un fichero de perfil válido (por ejemplo, uno guardado antes), "
            "puedes importarlo con {boton}. Se está estudiando leer el perfil directamente "
            "de tus propias pantallas del juego.",
            boton=f"<b>{html.escape(t('Importar perfil (JSON)...'))}</b>",
        ), "normal", envolver=True))
        panel.capa.addWidget(EtiquetaC(t(
            "Con el perfil, la ficha de cada objeto en Buscar dice si ya lo has dominado, "
            "y aquí verás lo que te falta por categoría y los nodos que no has completado. "
            "Farmadex no pide nada a Digital Extremes: solo lee el fichero que tú le das."
        ), "pequeno", envolver=True))
        self.capa_contenido.addWidget(panel)

    def _pintar_perfil(self) -> None:
        usuario, indice = self.usuario, self.indice
        meta = datos_perfil.resumen(usuario) or {}
        conteo = datos_perfil.resumen_maestria(usuario, indice)
        acero = self.filtro_acero.isChecked()
        pendientes_normal = datos_perfil.nodos_pendientes(usuario, indice, camino_acero=False)
        pendientes_acero = datos_perfil.nodos_pendientes(usuario, indice, camino_acero=True)
        total_nodos = self._total_nodos()

        izquierda = columna(espacio=px(12, False))
        izquierda.addWidget(self._panel_maestria(meta, conteo))
        izquierda.addWidget(self._panel_categorias(conteo))
        izquierda.addWidget(self._panel_dominar(datos_perfil.pendientes_por_categoria(usuario, indice)))
        izquierda.addStretch(1)
        derecha = columna(espacio=px(12, False))
        derecha.addWidget(self._panel_mapa(total_nodos, len(pendientes_normal), len(pendientes_acero)))
        intrinsecos = self._panel_intrinsecos(meta.get("intrinsecos") or {})
        if intrinsecos is not None:
            derecha.addWidget(intrinsecos)
        sindicatos = self._panel_sindicatos(meta.get("sindicatos") or [])
        if sindicatos is not None:
            derecha.addWidget(sindicatos)
        derecha.addWidget(self._panel_nodos(pendientes_acero if acero else pendientes_normal, acero))
        derecha.addStretch(1)
        columnas = QHBoxLayout()
        columnas.setSpacing(px(16, False))
        columnas.addLayout(izquierda, 3)
        columnas.addLayout(derecha, 2)
        self.capa_contenido.addLayout(columnas)
        self.capa_contenido.addWidget(self._panel_origen())

    # -- paneles ---------------------------------------------------------------------

    def _panel_maestria(self, meta: dict, conteo: dict[str, dict]) -> PanelC:
        panel = PanelC(t("Tu maestría"))
        rotulo = EtiquetaC(t("Rango de maestría"), "pequeno", mayus=True)
        self.rango = EtiquetaC(str(meta.get("rango", 0)), "portada")
        self.rango.setStyleSheet(
            f"color: {hex_de('acento')}; font-family: '{TITULAR}'; font-size: {px(56)}px; font-weight: 600;"
            " background: transparent;")
        self.rango.setToolTip(t("Rango de maestría {n}", n=meta.get("rango", 0)))
        izquierda = columna(rotulo, self.rango, None, espacio=0)

        dominados = sum(c[DOMINADO] for c in conteo.values())
        a_medias = sum(c[A_MEDIAS] for c in conteo.values())
        total = sum(c["total"] for c in conteo.values())
        detalles = []
        if meta.get("clan"):
            detalles.append(t("Clan {clan}", clan=meta["clan"]))
        if meta.get("plataformas"):
            detalles.append(", ".join(meta["plataformas"]))
        importado = _fecha_local(meta.get("importado_en"))
        if importado:
            detalles.append(t("Importado el {fecha}", fecha=importado))
        if meta.get("fichero"):
            detalles.append(Path(meta["fichero"]).name)
        derecha = columna(
            EtiquetaC(meta.get("nombre") or "", "seccion", recortar=True),
            EtiquetaC(t("Dominas {d} de {total} objetos que dan maestría", d=dominados, total=total), "normal"),
            BarraFina(dominados / total if total else 0, tinta="acento", alto=5),
            EtiquetaC(" · ".join(detalles), "pequeno", envolver=True),
            espacio=px(6, False),
        )
        if a_medias:
            derecha.addWidget(EtiquetaC(
                t("Lo más rápido: subir a 30 lo que ya tienes a medias ({n}).", n=a_medias), "pequeno",
                envolver=True))
        derecha.addStretch(1)
        panel.capa.addLayout(fila(izquierda, px(24, False), derecha, espacio=px(8, False)))
        return panel

    def _panel_categorias(self, conteo: dict[str, dict]) -> PanelC:
        panel = PanelC(t("Maestría por categoría"))
        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(px(14, False))
        rejilla.setVerticalSpacing(px(5, False))
        for columna_i, (texto, tinta) in enumerate(
            ((t("Dominados"), "ok"), (t("A medias"), "acento"), (t("Sin tocar"), "suave"), (t("Total"), "suave")),
            start=2,
        ):
            cabecera = EtiquetaC(texto, "pequeno", tinta=tinta, mayus=True)
            cabecera.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rejilla.addWidget(cabecera, 0, columna_i)
        total = {"total": 0, DOMINADO: 0, A_MEDIAS: 0, SIN_TOCAR: 0}
        filas = sorted(conteo.items(), key=lambda par: categoria_es(par[0]))
        for i, (categoria, c) in enumerate(filas, start=1):
            for clave in total:
                total[clave] += c.get(clave, 0)
            self._fila_categoria(rejilla, i, categoria_es(categoria), c)
        self._fila_categoria(rejilla, len(filas) + 1, t("Total"), total, negrita=True)
        rejilla.setColumnStretch(1, 1)
        panel.capa.addLayout(rejilla)
        return panel

    @staticmethod
    def _fila_categoria(rejilla: QGridLayout, i: int, etiqueta: str, c: dict, negrita: bool = False) -> None:
        nombre = EtiquetaC(etiqueta, "fuerte" if negrita else "normal", tinta="acento" if negrita else None)
        barra = BarraFina(c[DOMINADO] / c["total"] if c["total"] else 0, tinta="ok", alto=4)
        barra.setMinimumWidth(px(80, False))
        rejilla.addWidget(nombre, i, 0)
        rejilla.addWidget(barra, i, 1, Qt.AlignVCenter)
        for columna_i, (valor, tinta) in enumerate(
            ((c[DOMINADO], "ok"), (c[A_MEDIAS], "acento"), (c[SIN_TOCAR], "suave"), (c["total"], "suave")),
            start=2,
        ):
            numero = EtiquetaC(str(valor), "dato", tinta=tinta)
            numero.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rejilla.addWidget(numero, i, columna_i)

    def _panel_dominar(self, grupos: dict[str, list[dict]]) -> PanelC:
        panel = PanelC(t("Por dominar"), remate=False)
        if not grupos:
            panel.capa.addWidget(EtiquetaC(t("Lo tienes todo dominado. Enhorabuena, Tenno."), "normal", tinta="ok"))
            return panel
        todas = [f for filas in grupos.values() for f in filas]
        # Primero lo empezado (lo mas rapido de dominar), luego lo demas por nombre.
        todas.sort(key=lambda f: (f["estado"] != A_MEDIAS, -f["xp"], nombre_idioma(f)))
        acento = hex_de("acento")
        enlaces = [
            f"<span style='color:{acento}'>&#9670;</span>&nbsp;{self._enlace_item(f)}"
            for f in todas[:MAX_RESUMEN_DOMINAR]
        ]
        resumen = EtiquetaC(" &nbsp; ".join(enlaces), "normal", envolver=True)
        resumen.linkActivated.connect(self._enlace)
        abierto = "dominar" in self._abiertos
        boton = BotonC(t("Ocultar") if abierto else t("Ver todos ({n})", n=len(todas)), icono="derecha", tam=11)
        boton.clicked.connect(lambda: self._alternar("dominar"))
        panel.capa.addLayout(fila(resumen, boton, espacio=px(12, False)))
        if len(todas) > MAX_RESUMEN_DOMINAR and not abierto:
            panel.capa.addWidget(EtiquetaC(t("y {n} más", n=len(todas) - MAX_RESUMEN_DOMINAR), "pequeno"))
        if abierto:
            panel.capa.addWidget(self._lista_dominar(grupos))
        return panel

    def _enlace_item(self, f: dict) -> str:
        texto = (f"<a style='color:{hex_de('texto')};text-decoration:none' href='item:{f['item_id']}'>"
                 f"{html.escape(nombre_idioma(f))}</a>")
        if f["estado"] == A_MEDIAS and f.get("umbral"):
            pct = min(100, int(100 * f["xp"] / f["umbral"]))
            texto += f" <span style='color:{hex_de('aviso')}'>{pct} %</span>"
        return texto

    def _lista_dominar(self, grupos: dict[str, list[dict]]) -> QWidget:
        partes = []
        suave = hex_de("suave")
        for categoria, filas in sorted(grupos.items(), key=lambda par: categoria_es(par[0])):
            empezados = sum(1 for f in filas if f["estado"] == A_MEDIAS)
            resumen = t("{n} pendientes", n=len(filas))
            if empezados:
                resumen += " · " + t("{n} a medias", n=empezados)
            partes.append(
                f"<div style='margin-top:8px'><b>{html.escape(categoria_es(categoria))}</b> "
                f"<span style='color:{suave}'>&middot; {html.escape(resumen)}</span></div>"
                f"<div style='margin-left:12px'>{' &nbsp;·&nbsp; '.join(self._enlace_item(f) for f in filas)}</div>"
            )
        lista = EtiquetaC("".join(partes), "normal", envolver=True)
        lista.linkActivated.connect(self._enlace)
        return lista

    def _panel_mapa(self, total: int, pendientes: int, pendientes_acero: int) -> PanelC:
        panel = PanelC(t("Mapa estelar"))
        hechos = max(0, total - pendientes)
        hechos_acero = max(0, total - pendientes_acero)
        cifra = EtiquetaC(f"{hechos} / {total}", "portada", tinta="texto")
        panel.capa.addLayout(fila(cifra, None, EtiquetaC(t("normal"), "pequeno")))
        panel.capa.addWidget(BarraFina(hechos / total if total else 0, tinta="secundario", alto=5))
        panel.capa.addSpacing(px(4, False))
        panel.capa.addLayout(fila(EtiquetaC(f"{hechos_acero} / {total}", "seccion", tinta="suave"), None,
                                  EtiquetaC(t("Camino de Acero"), "pequeno")))
        panel.capa.addWidget(BarraFina(hechos_acero / total if total else 0, tinta="acento_tenue", alto=4))
        return panel

    def _panel_intrinsecos(self, valores: dict[str, int]) -> PanelC | None:
        if not any(clave in valores for clave in INTRINSECOS):
            return None
        panel = PanelC(t("Intrínsecos"), remate=False)
        grupos = (
            (t("Railjack"), [k for k in INTRINSECOS if k in _INTRINSECOS_RAILJACK]),
            (t("Errante"), [k for k in INTRINSECOS if k not in _INTRINSECOS_RAILJACK]),
        )
        texto = hex_de("texto")
        for titulo, claves in grupos:
            trozos = [
                f"{html.escape(t(INTRINSECOS[k]))} <b style='color:{texto}'>{int(valores.get(k, 0))}</b>"
                for k in claves if k in valores
            ]
            if trozos:
                panel.capa.addWidget(EtiquetaC(titulo, "rotulo", mayus=True))
                panel.capa.addWidget(EtiquetaC(" &nbsp; ".join(trozos), "pequeno", envolver=True))
        return panel

    def _panel_sindicatos(self, sindicatos: list[dict]) -> PanelC | None:
        if not sindicatos:
            return None
        panel = PanelC(t("Sindicatos"), remate=False)
        for s in sindicatos:
            nombre = t(SINDICATOS.get(s["tag"], s["tag"].removesuffix("Syndicate")))
            titulo = s["titulo"]
            if titulo < 0:
                rango = EtiquetaC(t("en contra ({n})", n=titulo), "pequeno", tinta="aviso")
            else:
                rango = EtiquetaC(t("rango {n}", n=titulo).capitalize(), "pequeno")
            linea = transparente(QWidget())
            linea.setLayout(fila(Rombo(8, COLOR_SINDICATO.get(s["tag"], "acento")),
                                 EtiquetaC(nombre, "fuerte", recortar=True), None, rango, espacio=px(8, False)))
            linea.setToolTip(t("Reputación: {n}", n=_miles(s["standing"])))
            panel.capa.addWidget(linea)
        return panel

    def _panel_nodos(self, pendientes: list[dict], acero: bool) -> PanelC:
        titulo = t("Nodos pendientes del Camino de Acero") if acero else t("Nodos pendientes")
        panel = PanelC(titulo, remate=False)
        if not pendientes:
            panel.capa.addWidget(EtiquetaC(t("Mapa completo: no te falta ningún nodo."), "normal", tinta="ok"))
            return panel
        nombres = self._nombres_nodos()
        # El indice trae el mismo planeta con y sin tilde segun el nodo ("Pluton" y
        # "Pluton" con acento): se agrupa sin acentos y se ensena el primer nombre visto.
        por_planeta: dict[str, list[str]] = {}
        etiquetas: dict[str, str] = {}
        suave = hex_de("suave")
        for n in pendientes:
            datos = nombres.get(n["unique_name"], {})
            planeta = nombre_idioma(datos, "planeta") or n["planeta"] or "?"
            nombre = nombre_idioma(datos) or n["nombre"] or n["unique_name"]
            mision = glosa(n["mision"], datos.get("mision_en")) if n["mision"] else ""
            texto = html.escape(nombre)
            if mision:
                texto += f" <span style='color:{suave}'>({html.escape(mision)})</span>"
            clave = _sin_acentos(planeta)
            etiquetas.setdefault(clave, planeta)
            por_planeta.setdefault(clave, []).append(texto)
        orden = sorted(por_planeta, key=lambda c: (c == "?", c))  # sin planeta conocido, al final
        resumen = " · ".join(f"{etiquetas[c]} {len(por_planeta[c])}" for c in orden[:MAX_RESUMEN_PLANETAS])
        if len(orden) > MAX_RESUMEN_PLANETAS:
            resumen += " · " + t("y {n} más", n=len(orden) - MAX_RESUMEN_PLANETAS)
        abierto = "nodos" in self._abiertos
        boton = BotonC(t("Ocultar") if abierto else t("Ver cuáles"), icono="derecha", tam=11)
        boton.clicked.connect(lambda: self._alternar("nodos"))
        panel.capa.addLayout(fila(EtiquetaC(resumen, "normal", envolver=True), boton, espacio=px(10, False)))
        # La lista entera se monta siempre (tambien sirve para buscar), pero plegada.
        lineas = [
            f"<div style='margin-top:4px'><b>{html.escape(etiquetas[c])}</b> "
            f"<span style='color:{suave}'>({len(por_planeta[c])})</span>: " + ", ".join(por_planeta[c]) + "</div>"
            for c in orden
        ]
        detalle = EtiquetaC("".join(lineas), "pequeno", envolver=True)
        detalle.setVisible(abierto)
        panel.capa.addWidget(detalle)
        return panel

    def _panel_origen(self) -> PanelC:
        panel = PanelC(t("De dónde sale esto"), remate=False)
        panel.capa.addWidget(EtiquetaC(t(
            "Hoy el juego no deja descargar el perfil solo: si tienes tu perfil en un fichero JSON, "
            "impórtalo con el botón de arriba. Además, la maestría se marca sola cuando abres "
            "Perfil > Equipamiento en el juego: Farmadex solo mira la pantalla."
        ), "pequeno", envolver=True))
        return panel

    # -- consultas auxiliares al indice --------------------------------------------

    def _total_nodos(self) -> int:
        condicion = " OR ".join("unique_name LIKE ?" for _ in _PREFIJOS_NODO)
        return self.indice.execute(
            f"SELECT COUNT(*) FROM nodos WHERE {condicion}", tuple(f"{p}%" for p in _PREFIJOS_NODO)
        ).fetchone()[0]

    def _nombres_nodos(self) -> dict[str, dict]:
        """Nombres de nodo y planeta en los dos idiomas del indice, para elegir segun la interfaz."""
        return {
            fila_nodo[0]: {
                "nombre_en": fila_nodo[1], "nombre_es": fila_nodo[2],
                "planeta_en": fila_nodo[3], "planeta_es": fila_nodo[4], "mision_en": fila_nodo[5],
            }
            for fila_nodo in self.indice.execute(
                "SELECT unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_en "
                "FROM nodos WHERE unique_name IS NOT NULL"
            )
        }


# -- utilidades ------------------------------------------------------------------------


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _fecha_local(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        momento = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if momento.tzinfo is not None:
        momento = momento.astimezone()
    else:
        momento = momento.replace(tzinfo=timezone.utc).astimezone()
    return momento.strftime("%d/%m/%Y %H:%M")
