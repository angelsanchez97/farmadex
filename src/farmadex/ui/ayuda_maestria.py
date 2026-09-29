"""Panel "Qué te falta por dominar" de MIS METAS > Perfil: la lista de `datos.ayuda_maestria`.

Filtros por tipo y busqueda por nombre, de lo mas facil de conseguir a lo mas dificil, y
en cada fila de donde sale. Si el perfil no dice que tienes dominado (sin perfil, o solo
lo leido en pantalla), se dice claro y se ofrece marcarlo a mano ("Ya lo tengo") o pegar
la lista de lo que ya tienes. El calculo va en un hilo aparte con su propia conexion al
indice; la BD del usuario se lee aqui, en el hilo de la ventana.
"""

from __future__ import annotations

import html
import sqlite3

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QInputDialog, QLineEdit, QVBoxLayout

from ..datos import ayuda_maestria as datos_ayuda
from ..idiomas import t
from ..registro_log import obtener
from .busqueda_fondo import BusquedaEnFondo
from .estilo_c import BotonC, DesplegableC, EtiquetaC, PanelC, fila, hex_de, px

log = obtener("ayuda_maestria")

POR_PAGINA = 60

# Rotulo corto de cada grupo de facilidad y su tinta.
ROTULOS = {
    datos_ayuda.A_MEDIAS: ("Ya lo tienes a medias", "acento"),
    datos_ayuda.CREDITOS: ("Con créditos", "ok"),
    datos_ayuda.DROP: ("Cae en misiones", "ok"),
    datos_ayuda.SINDICATO: ("Sindicato", "secundario"),
    datos_ayuda.FUNDICION: ("Fundición", "secundario"),
    datos_ayuda.RELIQUIA: ("Reliquias", "acento"),
    datos_ayuda.OTRO: ("Otras fuentes", "suave"),
    datos_ayuda.PLATINO: ("Mercado (platino)", "aviso"),
    datos_ayuda.BOVEDA: ("En la bóveda", "aviso"),
    datos_ayuda.DESCONOCIDO: ("No se sabe", "suave"),
}


def _vaciar(capa) -> None:
    while capa.count():
        elemento = capa.takeAt(0)
        if elemento.widget() is not None:
            elemento.widget().hide()
            elemento.widget().deleteLater()
        elif elemento.layout() is not None:
            _vaciar(elemento.layout())


def _miles(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _pct(valor) -> str:
    valor = float(valor or 0)
    return f"{valor:.0f} %" if valor >= 10 or valor == int(valor) else f"{valor:.2g} %"


def texto_donde(f: dict) -> str:
    """De donde sale, en una frase (texto plano)."""
    como = f.get("como") or f["facilidad"]
    partes = []
    if f.get("ingredientes"):
        partes.append(t("Se fabrica con {cosas}", cosas=", ".join(f["ingredientes"])))
    if como in (datos_ayuda.CREDITOS, datos_ayuda.FUNDICION) and f.get("creditos"):
        partes.append(t("plano por {n} créditos (Mercado o laboratorio del dojo)", n=_miles(f["creditos"])))
    elif como in (datos_ayuda.DROP, datos_ayuda.SINDICATO, datos_ayuda.OTRO) and f.get("donde"):
        d = f["donde"]
        sitio = d.get("donde") or ""
        if d.get("mision"):
            sitio += f" ({d['mision']})"
        if d.get("rotacion"):
            sitio += " " + t("rotación {r}", r=d["rotacion"])
        if d.get("probabilidad") and d.get("tipo") != "sindicato":
            sitio += f" · {_pct(d['probabilidad'])}"
        partes.append(f"{f['pieza']}: {sitio}" if f.get("pieza") else sitio)
        if f.get("creditos"):
            partes.append(t("plano por {n} créditos", n=_miles(f["creditos"])))
    elif como == datos_ayuda.RELIQUIA:
        nombres = [r[:-6] if r.endswith(" Relic") else r for r in f.get("reliquias", [])]
        extra = t(" y {n} más", n=len(nombres) - 3) if len(nombres) > 3 else ""
        partes.append(t("Reliquias fuera de la bóveda: {lista}", lista=", ".join(nombres[:3]) + extra))
    elif como == datos_ayuda.PLATINO:
        partes.append(t("Se vende en el Mercado por {n} de platino", n=f.get("platino")))
    elif como == datos_ayuda.BOVEDA:
        partes.append(t("Solo por intercambio, Baro Ki'Teer o Prime Resurgence"))
    elif como == datos_ayuda.DESCONOCIDO:
        partes.append(t("Farmadex no tiene el dato de dónde sale"))
    if f.get("piezas_sin_datos"):
        partes.append(t("de {n} pieza(s) no hay datos", n=f["piezas_sin_datos"]))
    return " · ".join(p for p in partes if p)


def texto_estado(f: dict) -> str:
    if f["estado"] == datos_ayuda.A_MEDIAS and f.get("umbral"):
        pct = min(99, int(100 * f["xp"] / f["umbral"]))
        return t("a medias, {pct} %", pct=pct)
    if f["estado"] == datos_ayuda.SIN_DATOS:
        return t("sin datos")
    return ""


def texto_aviso(r: datos_ayuda.Resultado, vistos: int) -> str:
    """De donde sale lo que se sabe de tu maestria, dicho claro."""
    if r.origen is None:
        return t("No sé qué tienes dominado: ahora mismo DE no deja descargar el perfil. Abre en el juego "
                 "Perfil > Equipamiento con Farmadex abierto para que lo lea solo, marca aquí lo que ya "
                 "tengas con «Ya lo tengo» o pega tu lista con «Pegar mi lista». Mientras tanto, todo sale "
                 "como «sin datos».")
    if r.origen == "ocr":
        return t("Según lo que Farmadex ha leído en tus pantallas de Perfil > Equipamiento ({n} objetos). "
                 "Lo que aún no ha visto sale como «sin datos»: ábrelo en el juego o márcalo aquí.", n=vistos)
    return t("Según tu perfil importado. Si ya dominas algo que sale aquí, márcalo con «Ya lo tengo».")


class PanelAyudaMaestria(PanelC):
    abrir_item = Signal(int)
    maestria_cambiada = Signal()  # algo marcado a mano: la ficha y el perfil deben repintar

    def __init__(self, parent=None):
        super().__init__(t("Qué te falta por dominar y dónde conseguirlo"), parent=parent)
        self.indice: sqlite3.Connection | None = None
        self.usuario: sqlite3.Connection | None = None
        self.resultado: datos_ayuda.Resultado | None = None
        self._vistos = 0
        self._mostrados = POR_PAGINA
        self._sucio = True
        self._ultimo_marcado: list[str] = []
        self._hilo = BusquedaEnFondo(self)

        self.caja = QLineEdit()
        self.caja.setObjectName("cajaC")
        self.caja.setClearButtonEnabled(True)
        self.caja.textChanged.connect(self._filtro_cambiado)
        self.grupo = DesplegableC(tam=11)
        self.grupo.currentIndexChanged.connect(self._filtro_cambiado)
        self.vista = DesplegableC(tam=11)
        self.vista.currentIndexChanged.connect(self._filtro_cambiado)
        self.boton_pegar = BotonC("", tam=11, icono="importar")
        self.boton_pegar.clicked.connect(self._pedir_lista)
        self.capa.addLayout(fila(self.caja, self.grupo, self.vista, self.boton_pegar, espacio=px(8, False)))

        self.aviso = EtiquetaC("", "pequeno", tinta="suave", envolver=True)
        self.resumen = EtiquetaC("", "normal", envolver=True)
        self.estado = EtiquetaC("", "pequeno", tinta="acento", envolver=True)
        self.estado.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.estado.linkActivated.connect(self._enlace)
        self.estado.hide()
        self.capa.addWidget(self.aviso)
        self.capa.addWidget(self.resumen)
        self.capa.addWidget(self.estado)
        self.capa_filas = QVBoxLayout()
        self.capa_filas.setSpacing(px(6, False))
        self.capa.addLayout(self.capa_filas)
        self.boton_mas = BotonC("", tam=11)
        self.boton_mas.clicked.connect(self._mas)
        self.capa.addLayout(fila(None, self.boton_mas))

        self._diferido = QTimer(self)
        self._diferido.setSingleShot(True)
        self._diferido.setInterval(150)
        self._diferido.timeout.connect(self.recalcular)
        self.retraducir()

    # -- ciclo de vida --------------------------------------------------------------------

    def conectar(self, indice: sqlite3.Connection | None, usuario: sqlite3.Connection | None) -> None:
        self.indice, self.usuario = indice, usuario
        self.marcar_sucio()

    def marcar_sucio(self) -> None:
        self._sucio = True
        if self.isVisible():
            self._diferido.start()

    def showEvent(self, evento):  # noqa: N802 - firma de Qt
        super().showEvent(evento)
        if self._sucio:
            self._diferido.start()

    def retraducir(self) -> None:
        self.poner_titulo(t("Qué te falta por dominar y dónde conseguirlo"))
        self.caja.setPlaceholderText(t("Buscar por nombre"))
        self.boton_pegar.setText(t("Pegar mi lista"))
        self.boton_pegar.setToolTip(t("Pega los nombres de lo que ya tienes dominado (uno por línea) "
                                      "y Farmadex los marca."))
        actual_grupo, actual_vista = self.grupo.currentData(), self.vista.currentData()
        for combo in (self.grupo, self.vista):
            combo.blockSignals(True)
            combo.clear()
        self.grupo.addItem(t("Todos los tipos"), "")
        for clave in datos_ayuda.GRUPOS:
            self.grupo.addItem(t(datos_ayuda.NOMBRES_GRUPO[clave]), clave)
        self.vista.addItem(t("Lo que me falta"), "falta")
        self.vista.addItem(t("Marcados a mano"), "marcados")
        for combo, actual in ((self.grupo, actual_grupo), (self.vista, actual_vista)):
            i = combo.findData(actual) if actual is not None else 0
            combo.setCurrentIndex(max(0, i))
            combo.blockSignals(False)
        self.marcar_sucio()
        self._pintar()

    # -- calculo --------------------------------------------------------------------------

    def recalcular(self, en_segundo_plano: bool = True) -> None:
        self._sucio = False
        if self.indice is None or self.usuario is None:
            self.resultado = None
            self._pintar()
            return
        try:
            datos = datos_ayuda.leer_usuario(self.usuario)
        except sqlite3.Error:
            log.warning("No se pudo leer la maestria guardada", exc_info=True)
            datos = datos_ayuda.DatosUsuario()
        self._vistos = datos.vistos_ocr

        def trabajo(con: sqlite3.Connection):
            return datos_ayuda.calcular(con, datos, datos_ayuda.precios_mercado())

        if en_segundo_plano:
            self._hilo.pedir(self.indice, trabajo, self._recibir)
        else:
            self._recibir(trabajo(self.indice))

    def _recibir(self, resultado: datos_ayuda.Resultado) -> None:
        self.resultado = resultado
        self._pintar()

    # -- acciones ---------------------------------------------------------------------------

    def _filtro_cambiado(self, *_):
        self._mostrados = POR_PAGINA
        self._pintar()

    def _mas(self) -> None:
        self._mostrados += POR_PAGINA
        self._pintar()

    def _enlace(self, href: str) -> None:
        if href.startswith("item:"):
            self.abrir_item.emit(int(href.split(":", 1)[1]))
        elif href.startswith("marcar:"):
            self.marcar([href.split(":", 1)[1]], True)
        elif href.startswith("quitar:"):
            self.quitar([href.split(":", 1)[1]])
        elif href == "deshacer":
            self.quitar(self._ultimo_marcado)
        elif href.startswith("http"):
            QDesktopServices.openUrl(QUrl(href))

    def marcar(self, unique_names: list[str], dominado: bool = True) -> int:
        if self.usuario is None or not unique_names:
            return 0
        n = datos_ayuda.marcar(self.usuario, unique_names, dominado)
        self._ultimo_marcado = list(unique_names)
        self._avisar(t("Marcado como dominado: {n}.", n=n) + " "
                     f"<a style='color:{hex_de('acento')}' href='deshacer'>{html.escape(t('Deshacer'))}</a>")
        self.maestria_cambiada.emit()
        self.recalcular()
        return n

    def quitar(self, unique_names: list[str]) -> int:
        if self.usuario is None or not unique_names:
            return 0
        n = datos_ayuda.quitar_marca(self.usuario, unique_names)
        self._ultimo_marcado = []
        self._avisar(t("Marca quitada: {n}.", n=n))
        self.maestria_cambiada.emit()
        self.recalcular()
        return n

    def importar_texto(self, texto: str) -> tuple[int, list[str]]:
        """Marca como dominado lo que case por nombre exacto; devuelve (marcados, sin casar)."""
        if self.indice is None or self.usuario is None:
            return 0, []
        casados, fallos = datos_ayuda.casar_lista(self.indice, texto)
        n = datos_ayuda.marcar(self.usuario, [c["unique_name"] for c in casados], True) if casados else 0
        self._ultimo_marcado = [c["unique_name"] for c in casados]
        mensaje = t("Marcados como dominados: {n}.", n=n)
        if fallos:
            muestra = ", ".join(fallos[:5]) + ("…" if len(fallos) > 5 else "")
            mensaje += " " + t("No reconozco {n}: {nombres}. Escríbelos como salen en el juego.",
                               n=len(fallos), nombres=muestra)
        if n:
            mensaje += f" <a style='color:{hex_de('acento')}' href='deshacer'>{html.escape(t('Deshacer'))}</a>"
            self.maestria_cambiada.emit()
        self._avisar(mensaje if n else html.escape(mensaje))
        self.recalcular()
        return n, fallos

    def _pedir_lista(self) -> None:
        texto, ok = QInputDialog.getMultiLineText(
            self, t("Pegar mi lista"),
            t("Nombres de lo que ya tienes dominado, uno por línea (como salen en el juego, en cualquier idioma):"))
        if ok and texto.strip():
            self.importar_texto(texto)

    def _avisar(self, texto: str) -> None:
        self.estado.setText(texto)
        self.estado.setVisible(bool(texto))

    # -- pintado ------------------------------------------------------------------------------

    def filas_visibles(self) -> list[dict]:
        r = self.resultado
        if r is None:
            return []
        if self.vista.currentData() == "marcados":
            return datos_ayuda.filtrar(r.marcados, self.grupo.currentData() or None, self.caja.text())
        return datos_ayuda.filtrar(r.filas, self.grupo.currentData() or None, self.caja.text())

    def _pintar(self) -> None:
        _vaciar(self.capa_filas)
        r = self.resultado
        if r is None:
            self.aviso.setText("")
            self.resumen.setText(t("Preparando la lista...") if self.indice is not None else t("Preparando los datos..."))
            self.boton_mas.hide()
            return
        self.aviso.setText(texto_aviso(r, self._vistos))
        resumen = t("Dominas {d} de {total}.", d=r.dominados, total=r.total)
        if r.pendientes:
            resumen += " " + t("Te faltan {n}.", n=r.pendientes)
        if r.sin_datos:
            resumen += " " + t("De {n} no hay datos.", n=r.sin_datos)
        if not r.hay_creditos:
            resumen += " " + t("(Sin los precios del Mercado: aún no se han descargado los datos.)")
        self.resumen.setText(resumen)
        filas = self.filas_visibles()
        marcados = self.vista.currentData() == "marcados"
        if not filas:
            if marcados:
                texto = t("No has marcado nada a mano.")
            elif not r.filas:
                texto = t("Lo tienes todo dominado. Enhorabuena, Tenno.")
            else:
                texto = t("Nada coincide con el filtro.")
            self.capa_filas.addWidget(EtiquetaC(texto, "normal", tinta="suave", envolver=True))
            self.boton_mas.hide()
            return
        grupo_anterior = None
        for f in filas[:self._mostrados]:
            if not marcados and f["facilidad"] != grupo_anterior:
                grupo_anterior = f["facilidad"]
                rotulo, tinta = ROTULOS[grupo_anterior]
                self.capa_filas.addWidget(EtiquetaC(t(rotulo), "rotulo", tinta=tinta, mayus=True))
            self.capa_filas.addWidget(self._fila(f, marcados))
        sobran = len(filas) - self._mostrados
        self.boton_mas.setVisible(sobran > 0)
        self.boton_mas.setText(t("Ver {n} más", n=min(POR_PAGINA, sobran)))

    def _fila(self, f: dict, marcados: bool) -> EtiquetaC:
        suave, acento = hex_de("suave"), hex_de("acento")
        nombre = (f"<a style='color:{hex_de('texto')};text-decoration:none' href='item:{f['item_id']}'>"
                  f"<b>{html.escape(f['nombre'])}</b></a>")
        partes = [nombre, f"<span style='color:{suave}'>{html.escape(t(datos_ayuda.NOMBRES_GRUPO[f['grupo']]))}</span>"]
        # Sin perfil todo es "sin datos": repetirlo en cada fila solo mete ruido.
        estado = texto_estado(f) if not marcados and self.resultado.origen is not None else ""
        if estado:
            tinta = hex_de("aviso") if f["estado"] == datos_ayuda.A_MEDIAS else suave
            partes.append(f"<span style='color:{tinta}'>{html.escape(estado)}</span>")
        if marcados:
            accion = f"<a style='color:{acento}' href='quitar:{html.escape(f['unique_name'])}'>{html.escape(t('Quitar marca'))}</a>"
            detalle = t("Marcado a mano como dominado")
        else:
            accion = f"<a style='color:{acento}' href='marcar:{html.escape(f['unique_name'])}'>{html.escape(t('Ya lo tengo'))}</a>"
            detalle = texto_donde(f)
        linea2 = html.escape(detalle[:1].upper() + detalle[1:])
        if not marcados and f.get("como") == datos_ayuda.DESCONOCIDO and f.get("wiki_url"):
            linea2 += f" · <a style='color:{acento}' href='{html.escape(f['wiki_url'])}'>{html.escape(t('Mírala en la wiki'))}</a>"
        texto = (" &nbsp;·&nbsp; ".join(partes) + f" &nbsp; {accion}"
                 + f"<br><span style='color:{suave}'>{linea2}</span>")
        etiqueta = EtiquetaC(texto, "normal", envolver=True)
        etiqueta.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        etiqueta.linkActivated.connect(self._enlace)
        return etiqueta

    def texto_plano(self) -> str:
        from PySide6.QtGui import QTextDocumentFragment
        from PySide6.QtWidgets import QLabel

        trozos = []
        for etiqueta in self.findChildren(QLabel):
            if etiqueta.isHidden():
                continue
            texto = etiqueta.texto_completo() if hasattr(etiqueta, "texto_completo") else etiqueta.text()
            if "<" in texto:
                texto = QTextDocumentFragment.fromHtml(texto).toPlainText()
            trozos.append(texto)
        return "\n".join(trozos)
