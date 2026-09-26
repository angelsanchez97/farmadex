"""Modo juego: tarjetas tipo HUD y un buscador rapido, para consultar sin salir de la partida.

Pensado para mirarse de reojo sin tapar la partida ni ensenarle al espectador una
ventana entera (rediseno C, maqueta `propuesta_C_compacto.png`):

- Arriba, dos tarjetas pequenas que flotan sobre el juego: "Siguiente pieza" (de tus
  metas, la que antes se consigue, con su reliquia, la mision y el tiempo) y, si hay
  una abierta, la fisura que te sirve para ella. Son los mismos calculos que el Tablero
  (`pestana_tablero.pasos_pendientes` y `fisuras_utiles`) y comparten su cache de rutas.
  Se pueden quitar con el boton "Tarjetas" y queda solo el buscador, como antes.
- Debajo, la barra de busqueda. Al escribir, las tarjetas dejan sitio a los resultados:
  arriba y abajo se cambia de resultado, al pulsar uno se despliegan sus detalles y
  con Enter se abre la ficha completa. Al borrar lo escrito vuelven las tarjetas.

La ventana es la de siempre (la chincheta "Fijar", el arrastre, Ctrl+M y la tecla
global viven en `overlay.py`); en este modo su fondo es transparente para que las
tarjetas floten sobre la partida.
"""

from __future__ import annotations

import html
import sqlite3

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from ..datos import indice, items, relaciones
from ..idiomas import es_castellano, glosa, nombre as nombre_idioma, t
from ..registro_log import obtener
from . import ficha_detalles, glosario
from .estilo_c import BotonC, EtiquetaC, PanelC, Rombo, Tecla, fila, icono, px, transparente
from .pestana_buscador import PestanaBuscador, _con_padre, _etiqueta, categoria_es, era_de
from .resultados_desplegables import ResultadosDesplegables
from .widgets import COLOR_BOVEDA, COLOR_DISPONIBLE, PALETA, color_rareza

log = obtener("modo_juego")

# Tamano por defecto: la cabecera, las dos tarjetas y la barra de busqueda caben sin recortar.
ANCHO = 540
ALTO = 340

# Minimo antes de que se corte: cabecera, la tarjeta de la siguiente pieza y la barra
# (la de la fisura se esconde sola si no cabe). Mas pequeno que el de la vista completa.
ANCHO_MINIMO = 420
ALTO_MINIMO = 250

# Cada cuanto se repintan las tarjetas con la ventana a la vista (tiempos de las fisuras).
REFRESCO_HUD_MS = 30_000
CLAVE_TARJETAS = "modo_juego_tarjetas"
ATAJO_POR_DEFECTO = "Ctrl+Alt+W"


class TarjetaHUD(PanelC):
    """Tarjeta pequena del HUD: rotulo con rombo y un dato a la derecha, un nombre grande
    y una linea de detalle. Con `clicable`, un clic emite `pulsado` (y no arrastra)."""

    def __init__(self, tinta: str, remate: bool, clicable: bool = False, parent=None):
        super().__init__(remate=remate, fondo="panel", borde="acento_tenue" if remate else "borde",
                         clicable=clicable, parent=parent)
        self.tinta = tinta
        self.capa.setContentsMargins(px(16, False), px(9, False), px(16, False), px(11, False))
        self.capa.setSpacing(px(2, False))
        self.rombo = Rombo(8, tinta)
        self.rotulo = EtiquetaC("", "rotulo", tinta=tinta, mayus=True)
        self.dato = EtiquetaC("", "seccion", tinta=tinta, mayus=True)
        self.capa.addLayout(fila(self.rombo, self.rotulo, None, self.dato, espacio=px(6, False)))
        self.nombre = EtiquetaC("", "destacado", recortar=True)
        self.detalle = EtiquetaC("", "pequeno", tinta="suave")
        self.capa.addWidget(self.nombre)
        self.capa.addWidget(self.detalle)

    def poner(self, rotulo: str, dato: str, nombre: str, detalle: str) -> None:
        self.rotulo.setText(rotulo)
        self.dato.setText(dato)
        self.dato.setVisible(bool(dato))
        self.nombre.setText(nombre)
        self.detalle.setText(detalle)
        self.detalle.setVisible(bool(detalle))

    def poner_dato_suave(self, suave: bool) -> None:
        """El tiempo de la fisura, en pequeno y apagado como en la maqueta."""
        self.dato.setProperty("rolC", "normal" if suave else "seccion")
        self.dato.poner_tinta("suave" if suave else self.tinta)

    def mousePressEvent(self, evento):  # noqa: N802 - firma de Qt
        # Si no se acepta, el clic sube a la ventana, que empieza a arrastrarse y se come
        # la suelta: la tarjeta no llegaria a enterarse del clic.
        if self._clicable and evento.button() == Qt.LeftButton:
            evento.accept()
            return
        super().mousePressEvent(evento)


class VistaCompacta(QWidget):
    pedir_precios = Signal(str)
    # El usuario quiere ver la ficha entera de este objeto: la ventana cambia a completo.
    abrir_completo = Signal(int)

    def __init__(self, buscador: PestanaBuscador, parent=None):
        super().__init__(parent)
        transparente(self)
        # El indice y el perfil se comparten con la pestana Buscar (misma conexion).
        self.buscador = buscador
        self._resultados: list[dict] = []
        self._indice_actual = -1
        self._datos: dict | None = None
        self._slug_actual = ""
        self._precio_html = ""
        self._sin_resultados: str | None = None
        # Datos del HUD: el Tablero (metas, rutas en cache y estado del mundo) y la config.
        self.tablero = None
        self.config: dict = {}
        self._item_pieza: int | None = None
        self._hay_fisura = False
        p = PALETA

        # -- tarjetas del HUD --
        self.tarjeta_pieza = TarjetaHUD("acento", remate=True, clicable=True)
        self.tarjeta_pieza.pulsado.connect(self._abrir_pieza)
        self.tarjeta_fisura = TarjetaHUD("secundario", remate=False)
        self.tarjeta_fisura.poner_dato_suave(True)
        self.tarjeta_fisura.hide()
        self.hud = transparente(QWidget())
        capa_hud = QVBoxLayout(self.hud)
        capa_hud.setContentsMargins(0, 0, 0, 0)
        capa_hud.setSpacing(px(8, False))
        capa_hud.addWidget(self.tarjeta_pieza)
        capa_hud.addWidget(self.tarjeta_fisura)

        # -- barra de busqueda --
        self.caja = QLineEdit()
        self.caja.setClearButtonEnabled(True)
        self.caja.setMinimumHeight(36)
        self.caja.installEventFilter(self)
        self.boton_tarjetas = BotonC(t("Tarjetas"), tam=11)
        self.boton_tarjetas.setCheckable(True)
        self.boton_tarjetas.setChecked(True)
        self.boton_tarjetas.toggled.connect(self._tarjetas_cambiadas)
        self.tecla = Tecla(ATAJO_POR_DEFECTO)
        self.tecla.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.barra = PanelC(remate=False, fondo="panel", borde="borde", chaflan=10)
        self.barra.capa.setContentsMargins(px(12, False), px(2, False), px(10, False), px(2, False))
        self.barra.capa.addLayout(fila(icono("buscar", 14, "acento"), self.caja, self.boton_tarjetas, self.tecla,
                                       espacio=px(8, False)))

        # -- resultados (se ven al buscar) --
        self.resumen = QLabel()
        self.resumen.setTextFormat(Qt.RichText)
        self.resumen.setWordWrap(True)
        self.resumen.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.resumen.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.resumen.linkActivated.connect(self._enlace)
        glosario.conectar_etiqueta(self.resumen)
        # Los resultados en lista: al pulsar uno se despliegan sus detalles debajo, sin
        # cambiar de vista (resultados_desplegables.py). El resumen de arriba queda para
        # los avisos y para lo que se abre desde fuera (lector del cursor, un enlace).
        self.lista = ResultadosDesplegables()
        self.lista.elegida.connect(self._mostrar)
        self.lista.enlace.connect(self._enlace)
        self.lista.hide()

        self.pie = QLabel()
        self.pie.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        self.posicion = QLabel()
        self.posicion.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        pie = QHBoxLayout()
        pie.addWidget(self.pie, 1)
        pie.addWidget(self.posicion, 0, Qt.AlignRight)

        self.panel_resultados = PanelC(remate=False, fondo="fondo", borde="borde", chaflan=10)
        self.panel_resultados.capa.setContentsMargins(px(10, False), px(8, False), px(10, False), px(6, False))
        self.panel_resultados.capa.setSpacing(px(6, False))
        self.panel_resultados.capa.addWidget(self.resumen, 1)
        self.panel_resultados.capa.addWidget(self.lista, 1)
        self.panel_resultados.capa.addLayout(pie)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 2, 0, 0)
        caja.setSpacing(px(8, False))
        caja.addWidget(self.hud)
        caja.addWidget(self.barra)
        caja.addWidget(self.panel_resultados, 1)
        caja.addStretch(0)
        self._capa = caja

        # Misma espera que la pestana Buscar: sin ella cada tecla buscaba y pedia precio al
        # mercado, y "ash prime systems" escrito a mano encolaba 13 consultas de red seguidas
        # (medido); el precio del objeto bueno llegaba el ultimo, varios segundos despues.
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(180)
        self._temporizador.timeout.connect(lambda: self._buscar(self.caja.text()))
        self.caja.textChanged.connect(lambda _: self._temporizador.start())
        # Al escribir, las tarjetas dejan sitio en el acto (sin esperar a la busqueda).
        self.caja.textChanged.connect(lambda _: self._colocar())
        self._reloj_hud = QTimer(self)
        self._reloj_hud.setInterval(REFRESCO_HUD_MS)
        self._reloj_hud.timeout.connect(self.refrescar_hud)
        self.retraducir()

    # -- HUD ------------------------------------------------------------------

    def usar_tablero(self, tablero, config: dict | None = None) -> None:
        """De donde salen las tarjetas: el Tablero (metas, rutas y mundo) y la config
        compartida de la ventana (ahi se guarda si se ensenan o no las tarjetas)."""
        self.tablero = tablero
        if config is not None:
            self.config = config
            self.boton_tarjetas.blockSignals(True)
            self.boton_tarjetas.setChecked(bool(config.get(CLAVE_TARJETAS, True)))
            self.boton_tarjetas.blockSignals(False)
        self._poner_tecla()
        self.marcar_sucio()

    def _poner_tecla(self) -> None:
        self.tecla.setText(str(self.config.get("hotkey_overlay") or ATAJO_POR_DEFECTO).upper())

    def tarjetas_activas(self) -> bool:
        return self.boton_tarjetas.isChecked()

    def _tarjetas_cambiadas(self, activas: bool) -> None:
        if self.config:
            self.config[CLAVE_TARJETAS] = bool(activas)
            try:
                from ..config import guardar

                guardar(self.config)
            except OSError:
                log.warning("No se pudo guardar la eleccion de las tarjetas", exc_info=True)
        log.info("Modo juego: tarjetas %s", "a la vista" if activas else "escondidas")
        if activas:
            self.refrescar_hud()
        self._colocar()

    def marcar_sucio(self) -> None:
        """Han cambiado las metas, el mundo o el indice: se recalcula si esta a la vista
        (si no, al ensenarse)."""
        if self.isVisible():
            QTimer.singleShot(0, self.refrescar_hud)

    def showEvent(self, evento):  # noqa: N802 - firma de Qt
        super().showEvent(evento)
        self._reloj_hud.start()
        self.refrescar_hud()

    def hideEvent(self, evento):  # noqa: N802
        super().hideEvent(evento)
        self._reloj_hud.stop()

    def resizeEvent(self, evento):  # noqa: N802
        super().resizeEvent(evento)
        self._colocar()

    def _en_busqueda(self) -> bool:
        """Hay algo escrito o abierto: los resultados mandan sobre las tarjetas."""
        return bool(self.caja.text().strip()) or self._datos is not None or self._sin_resultados is not None

    def hud_visible(self) -> bool:
        return self.tarjetas_activas() and not self._en_busqueda()

    def _colocar(self) -> None:
        """Tarjetas o resultados; la de la fisura solo si hay una y si cabe."""
        con_hud = self.hud_visible()
        self.hud.setVisible(con_hud)
        # Sin tarjetas y sin busqueda, se ve la ayuda de siempre ("Escribe el nombre...").
        self.panel_resultados.setVisible(not con_hud)
        if con_hud:
            hueco = px(8, False)
            disponible = self.height() - self.barra.sizeHint().height() - hueco - 2
            cabe = self.tarjeta_pieza.sizeHint().height() + hueco + self.tarjeta_fisura.sizeHint().height()
            self.tarjeta_fisura.setVisible(self._hay_fisura and cabe <= disponible)
        # Con las tarjetas, todo arriba y el hueco de abajo transparente.
        self._capa.setStretch(self._capa.count() - 1, 1 if con_hud else 0)

    def refrescar_hud(self) -> None:
        """Recalcula la siguiente pieza y la fisura que sirve (mismos calculos que el Tablero)."""
        from .pestana_tablero import fisuras_utiles, pasos_pendientes, restante, texto_tiempo

        pasos = []
        tablero = self.tablero
        indice_vivo = tablero._indice_vivo() if tablero is not None else None
        if tablero is not None and tablero.usuario is not None and indice_vivo is not None:
            try:
                pasos = pasos_pendientes(indice_vivo, tablero.usuario, tablero._rutas)
            except sqlite3.Error:
                log.warning("No se pudieron calcular las metas del modo juego", exc_info=True)
        self._item_pieza = None
        if pasos:
            paso = pasos[0]
            self._item_pieza = paso.item["id"] if paso.item else None
            self.tarjeta_pieza.poner(t("Siguiente pieza"), texto_tiempo(paso.minutos), paso.nombre,
                                     self._detalle_paso(paso))
        elif indice_vivo is None:
            self.tarjeta_pieza.poner(t("Siguiente pieza"), "", t("Preparando los datos..."), "")
        else:
            self.tarjeta_pieza.poner(t("Siguiente pieza"), "", t("Sin metas todavia"),
                                     t("Anade objetivos en Mis metas y aqui veras tu siguiente pieza."))
        self.tarjeta_pieza.setToolTip(t("Abrir su ficha") if self._item_pieza else "")
        self.tarjeta_pieza.setCursor(Qt.PointingHandCursor if self._item_pieza else Qt.ArrowCursor)

        utiles = fisuras_utiles(getattr(tablero, "mundo", None), pasos) if tablero is not None else []
        self._hay_fisura = bool(utiles)
        if utiles:
            f, paso = utiles[0]
            lugar = " · ".join(x for x in (f.nodo, f.mision) if x)
            self.tarjeta_fisura.poner(t("Fisura {era} abierta", era=t(f.era)), restante(f.expira), lugar,
                                      t("Te sirve para {nombre}", nombre=paso.nombre))
        self._colocar()

    def _detalle_paso(self, paso) -> str:
        """'Reliquia Lith S19 · Captura en Hepit, Vacio' (o donde se consigue si no es de reliquia)."""
        p = PALETA
        trozos = []
        if paso.es_reliquia:
            trozos.append(t("Reliquia {reliquia}", reliquia=f"<b style='color:{p['secundario']}'>"
                            f"{html.escape(paso.reliquia)}</b>"))
        if paso.boveda:
            trozos.append(html.escape(t("Solo en boveda: hay que comprarla a otro jugador")))
        else:
            mision = paso.mision
            if mision.get("donde"):
                lugar = html.escape(mision["donde"])
                trozos.append(t("{mision} en {lugar}", mision=html.escape(mision["mision"]), lugar=lugar)
                              if mision.get("mision") else lugar)
        return " · ".join(trozos)

    def _abrir_pieza(self) -> None:
        if self._item_pieza is not None:
            self.abrir_completo.emit(self._item_pieza)

    # -- idioma y tema --------------------------------------------------------

    def retraducir(self) -> None:
        self.caja.setPlaceholderText(t("Busca algo (Enter: ficha completa)"))
        self.pie.setText(t("↑↓ otro resultado · Enter ficha completa · Ctrl+M vista completa"))
        self.boton_tarjetas.setText(t("Tarjetas"))
        self.boton_tarjetas.setToolTip(
            t("Ensena u oculta las tarjetas de tu siguiente pieza y de la fisura que te sirve"))
        self._poner_tecla()
        self.tecla.setToolTip(t("Con esta tecla se abre y se esconde Farmadex desde el juego"))
        # Los nombres vienen del indice en el idioma de la interfaz: se recalcula despues de
        # que el Tablero olvide sus rutas, y solo si el modo juego esta a la vista.
        self.marcar_sucio()
        self.repintar()

    def repintar(self) -> None:
        p = PALETA
        self.pie.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        self.posicion.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        self.caja.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; color: {p['texto']}; font-size: {px(14)}px; }}"
        )
        self.tecla.refrescar_estilo()
        en_lista = self._en_lista()
        self.lista.setVisible(en_lista)
        self.resumen.setVisible(not en_lista)
        if en_lista:
            self.lista.repintar()
            item = self._datos["item"]
            self.lista.desplegar(
                self._indice_actual,
                self._html(self._datos, con_nombre=False)
                + ficha_detalles.html_detalles(self.con, item, compacto=True)
                + ficha_detalles.bloque_fuentes_compacto(self.con, item["id"]),
            )
        elif self._datos:
            self.resumen.setText(self._html(self._datos))
        elif self._sin_resultados is not None:
            self.resumen.setText(self._html_sin_resultados(self._sin_resultados))
        else:
            self.resumen.setText(
                f"<span style='color:{p['suave']}'>"
                + html.escape(t("Escribe el nombre de un objeto, una pieza, un mod o una reliquia."))
                + "</span>"
            )
        self._colocar()

    def _en_lista(self) -> bool:
        """Si lo abierto es uno de los resultados de la lista (y no algo abierto desde fuera)."""
        return bool(
            self._datos and 0 <= self._indice_actual < len(self._resultados)
            and self._resultados[self._indice_actual].get("item_id") == self._datos["item"]["id"]
        )

    # -- teclas ----------------------------------------------------------------

    def eventFilter(self, objeto, evento):  # noqa: N802 - firma de Qt
        if objeto is self.caja and evento.type() == QEvent.KeyPress:
            tecla = evento.key()
            if tecla == Qt.Key_Down:
                self._mover(1)
                return True
            if tecla == Qt.Key_Up:
                self._mover(-1)
                return True
            if tecla in (Qt.Key_Return, Qt.Key_Enter) and self._datos:
                self.abrir_completo.emit(self._datos["item"]["id"])
                return True
        return super().eventFilter(objeto, evento)

    def _mover(self, paso: int) -> None:
        if not self._resultados:
            return
        self._mostrar(max(0, min(len(self._resultados) - 1, self._indice_actual + paso)))

    # -- busqueda ----------------------------------------------------------------

    @property
    def con(self):
        return self.buscador.con

    def _buscar(self, texto: str) -> None:
        texto = texto.strip()
        self._resultados = []
        self._indice_actual = -1
        self._datos = None
        self._sin_resultados = None
        self._slug_actual = ""
        self.posicion.setText("")
        if not self.con or len(texto) < 2:
            self.repintar()
            return
        self._resultados = indice.buscar(self.con, texto)
        self.lista.poner(self._resultados)
        if self._resultados:
            self._mostrar(0)
        else:
            self._sin_resultados = texto
            self.repintar()

    def _mostrar(self, posicion: int) -> None:
        self._indice_actual = posicion
        self.posicion.setText(f"{posicion + 1}/{len(self._resultados)}")
        self.abrir(self._resultados[posicion]["item_id"])

    def abrir(self, item_id: int) -> None:
        """Ensena un objeto concreto (desde la lista o desde el lector del cursor)."""
        if not self.con:
            return
        datos = items.ficha(self.con, item_id)
        if not datos:
            return
        self._datos = datos
        self._sin_resultados = None
        self._precio_html = ""
        slug = datos["item"].get("market_slug") or ""
        self._slug_actual = slug
        if slug:
            self._precio_html = (
                f"<span style='color:{PALETA['suave']}'>{html.escape(t('Mercado: consultando...'))}</span>"
            )
            self.pedir_precios.emit(slug)
        self.repintar()

    def mostrar_precios(self, slug: str, precios) -> None:
        if slug != self._slug_actual:
            return
        p = PALETA
        if getattr(precios, "error", None):
            texto = f"<span style='color:{p['suave']}'>{html.escape(t('Mercado: no disponible'))}</span>"
        elif precios.mejor_venta is None and precios.mejor_compra is None:
            texto = f"<span style='color:{p['suave']}'>{html.escape(t('Mercado: nadie lo vende ahora mismo'))}</span>"
        else:
            partes = []
            if precios.mejor_venta is not None:
                partes.append(t("se vende desde <b>{n}p</b>", n=precios.mejor_venta))
            if precios.mejor_compra is not None:
                partes.append(t("te lo compran por <b>{n}p</b>", n=precios.mejor_compra))
            texto = html.escape(t("Mercado:")) + " " + " &middot; ".join(partes)
        self._precio_html = texto
        self.repintar()

    def _enlace(self, url: str) -> None:
        if glosario.mostrar(url, self.resumen):
            return
        if url.startswith("item:"):
            self.abrir(int(url.removeprefix("item:")))
        elif url.startswith("buscar:"):
            self.caja.setText(url.removeprefix("buscar:"))

    # -- pintado ------------------------------------------------------------------

    def _html(self, datos: dict, con_nombre: bool = True) -> str:
        p = PALETA
        item, padre = datos["item"], datos["padre"]
        nombre = html.escape(nombre_idioma(item))
        if padre:
            nombre = _con_padre(nombre, html.escape(nombre_idioma(padre)))
        otro = item["nombre_en"] if es_castellano() else (item["nombre_es"] or "")
        es_reliquia = item["categoria"] == "Relics"

        etiquetas = []
        clave_categoria = "reliquia" if es_reliquia else ("pieza" if item["tipo"] == "Componente" else None)
        etiquetas.append(_etiqueta(categoria_es(item["categoria"], item["tipo"]), p["panel"], p["suave"], clave_categoria))
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
        maestria = self.buscador._etiqueta_maestria(item["id"])
        if maestria:
            etiquetas.append(maestria)

        lineas = [
            f"<div><span style='font-size:17px;font-weight:bold'>{nombre}</span>"
            + (f" <span style='color:{p['suave']};font-size:12px'>{html.escape(otro)}</span>" if otro and otro != nombre_idioma(item) else "")
            + "</div>",
            f"<div style='margin-top:3px'>{' '.join(etiquetas)}</div>",
            f"<div style='margin-top:6px'>{self._donde(datos)}</div>",
        ]
        if not con_nombre:  # desplegado en la lista: el nombre ya esta en su cabecera
            lineas.pop(0)
        if self._precio_html:
            lineas.append(f"<div style='margin-top:4px'>{self._precio_html}</div>")
        return "".join(lineas)

    def _donde(self, datos: dict) -> str:
        """Una sola linea: la mejor forma de conseguirlo hoy."""
        p = PALETA
        con = self.con
        item = datos["item"]
        if item["categoria"] == "Relics":
            return self._donde_reliquia(item["id"])
        ruta = relaciones.mejor_ruta(con, item["id"])
        if ruta and (ruta.get("tipo") != "reliquia" or not ruta["reliquia"]):
            # Sin reliquia de por medio: el mejor sitio y de que tipo es.
            if not ruta["mision"]:
                ruta = None
            else:
                tipo = glosa(indice.traducir(con, "tipo_fuente", ruta.get("tipo")), ruta.get("tipo"))
                return self._mision(ruta["mision"]) + (
                    f" <span style='color:{p['suave']}'>({html.escape(tipo)})</span>" if tipo else ""
                )
        if ruta:
            reliquia = ruta["reliquia"]
            prob = reliquia["probabilidades"].get("Radiant") or max(list(reliquia["probabilidades"].values()) or [0])
            # El nombre ya dice "Reliquia Neo N5"; no se repite la palabra delante.
            texto = (
                f"<a style='color:{p['acento']};text-decoration:none' href='item:{reliquia['reliquia_id']}'>"
                f"<b>{html.escape(nombre_idioma(reliquia))}</b></a> "
                + glosario.enlace("refinamiento", t("({prob}% en Radiante)", prob=f"{prob:.1f}"), p["suave"])
            )
            if ruta["solo_en_boveda"]:
                return texto + "<br>" + glosario.enlace(
                    "boveda", t("Solo en boveda: hay que comprarla a otro jugador"), COLOR_BOVEDA
                )
            if ruta["mision"]:
                return texto + "<br>" + self._mision(ruta["mision"])
            return texto
        fuentes = [f for f in datos["fuentes"] if f["tipo"] != "reliquia"]
        if fuentes:
            f = max(fuentes, key=lambda x: x["probabilidad"] or 0)
            if f["nodo_en"]:
                donde = f"{nombre_idioma(f, 'nodo')}, {nombre_idioma(f, 'planeta')}".strip(", ")
                mision = glosa(indice.traducir(con, "mision", f["mision_en"]), f["mision_en"])
                if mision:
                    donde += f" - {mision}"
            else:
                from ..datos.nodos import nombre_bonito

                donde = nombre_bonito(con, f["origen_texto"])
            extra = []
            if f["rotacion"]:
                extra.append(glosario.enlace("rotacion", glosa(indice.traducir(con, "rotacion", f["rotacion"]), f["rotacion"]), p["suave"]))
            if f["rareza"]:
                extra.append(glosario.enlace("rareza", glosa(indice.traducir(con, "rareza", f["rareza"]), f["rareza"]), color_rareza(f["rareza"])))
            if f["probabilidad"] is not None:
                extra.append(f"<b>{f['probabilidad']:.1f}%</b>")
            return f"<b>{html.escape(donde)}</b>" + (" &middot; " + " &middot; ".join(extra) if extra else "")
        if datos["componentes"]:
            piezas = ", ".join(
                f"<a style='color:{p['acento']};text-decoration:none' href='item:{c['id']}'>{html.escape(nombre_idioma(c))}</a>"
                for c in datos["componentes"]
            )
            return f"{glosario.enlace('pieza', t('Se construye con'), p['suave'])}: {piezas}"
        return (
            f"<span style='color:{p['suave']}'>"
            + html.escape(t("Sin fuentes registradas: puede venir de una mision de historia, del mercado, "
                            "de un evento o de un sindicato."))
            + "</span>"
        )

    def _donde_reliquia(self, reliquia_id: int) -> str:
        p = PALETA
        misiones = relaciones.misiones_de(self.con, reliquia_id)
        partes = []
        if misiones:
            partes.append(html.escape(t("Cae en")) + " " + self._mision(misiones[0]))
        else:
            partes.append(f"<span style='color:{p['suave']}'>{html.escape(t('No cae en ninguna mision activa'))}</span>")
        # La pieza rara es la menos probable; la columna de rareza no es fiable en las tablas.
        contenido = relaciones.contenido_de(self.con, reliquia_id, "Radiant")
        if contenido:
            c = min(contenido, key=lambda x: x["probabilidad"] or 100)
            partes.append(
                glosario.enlace("rareza", t("Rara"), color_rareza("Rare")) + ": "
                f"<a style='color:{p['texto']};text-decoration:none' href='item:{c['item_id']}'>"
                f"<b>{html.escape(_con_padre(nombre_idioma(c), nombre_idioma(c, 'padre')))}</b></a>"
                f" <span style='color:{p['suave']}'>{c['probabilidad']:.1f}%</span>"
            )
        return "<br>".join(partes)

    def _mision(self, m: dict) -> str:
        p = PALETA
        trozos = [f"<b>{html.escape(m.get('donde') or '')}</b>"]
        if m.get("mision"):
            trozos.append(html.escape(m["mision"]))
        if m.get("rotacion"):
            trozos.append(glosario.enlace(
                "rotacion", glosa(indice.traducir(self.con, "rotacion", m["rotacion"]), m["rotacion"]), p["suave"]
            ))
        prob = m.get("probabilidad_efectiva") or m.get("probabilidad")
        if prob:
            trozos.append(f"{prob:.1f}%")
        return " &middot; ".join(trozos)

    def _html_sin_resultados(self, texto: str) -> str:
        p = PALETA
        salida = [
            f"<div style='font-size:15px;font-weight:bold'>"
            f"{html.escape(t('No he encontrado nada para «{busqueda}»', busqueda=texto))}</div>"
        ]
        parecidos = self.buscador.sugerencias(texto)
        if parecidos:
            enlaces = " &middot; ".join(
                f"<a style='color:{p['acento']};text-decoration:none' href='item:{r['item_id']}'>"
                f"{html.escape(_con_padre(nombre_idioma(r), nombre_idioma(r, 'padre')))}</a>"
                for r in parecidos
            )
            salida.append(f"<div style='margin-top:4px;color:{p['suave']}'>{html.escape(t('Quiza buscabas:'))} {enlaces}</div>")
        return "".join(salida)

