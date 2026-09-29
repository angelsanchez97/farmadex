"""Herramientas > Alertas: avisar cuando alguien vende un objeto a tu precio o menos.

Las alertas se crean desde la ficha de un objeto (Buscar) o desde una meta (Mis
metas): Farmadex trae aqui el objeto, se elige el precio y se crea. Mientras
Farmadex esta abierto (tambien escondido en la bandeja) un hilo aparte mira
warframe.market con calma (online/alertas.py) y, si alguien conectado lo vende a
ese precio o menos, sale un aviso de Windows con el vendedor; al pulsarlo se
copia el mensaje "/w" para pegarlo en el chat del juego.

Lo que se ensena de cada alerta lleva siempre la hora a la que se vio; si
warframe.market falla, se dice, y no se ensena ningun precio de antes como si
fuera de ahora.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget

from ..idiomas import t
from ..online import alertas as logica
from ..registro_log import obtener
from .estilo_c import BotonC, BotonGlifo, DesplegableC, EtiquetaC, PanelC, columna, fila, px, transparente

log = obtener("ui.alertas")

TICK_MS = 2000  # cada cuanto mira el hilo si ya toca consultar alguna alerta
REFRESCO_MS = 15000  # cada cuanto se repintan las edades ("hace 3 min")
NOMBRES_PLATAFORMA = {"pc": "PC", "ps4": "PlayStation", "xbox": "Xbox", "switch": "Switch", "mobile": "móvil"}


def edad(segundos: float) -> str:
    """'hace menos de un minuto', 'hace 5 min', 'hace 2 h'."""
    if segundos < 60:
        return t("hace menos de un minuto")
    if segundos < 3600:
        return t("hace {n} min", n=int(segundos // 60))
    return t("hace {n} h", n=int(segundos // 3600))


def texto_estado(alerta: logica.Alerta, estado: logica.Estado | None, ahora: float | None = None) -> str:
    """Lo que se sabe de una alerta, siempre con su hora. Tras un fallo, solo el fallo."""
    ahora = time.time() if ahora is None else ahora
    if not alerta.activa:
        return t("En pausa.")
    if estado is None or (estado.cuando is None and not estado.error):
        return t("Aún sin comprobar: se mira en unos segundos.")
    if estado.error:
        return t("No se pudo comprobar ({error}). Farmadex lo vuelve a intentar solo.", error=estado.error)
    cuando = edad(ahora - (estado.cuando or ahora))
    if estado.coincidencias:
        c = estado.coincidencias[0]
        return t("¡A tu precio! {vendedor} lo vende por {precio}p ({estado}, visto {cuando}).",
                 vendedor=c.vendedor, precio=c.platino,
                 estado=t("en el juego") if c.estado == "ingame" else t("conectado"), cuando=cuando)
    if estado.mejor is not None:
        return t("Nadie conectado lo vende a tu precio; lo más barato ahora es {precio}p (visto {cuando}).",
                 precio=estado.mejor, cuando=cuando)
    return t("Nadie conectado lo vende ahora mismo (visto {cuando}).", cuando=cuando)


class _Trabajador(QObject):
    """En su hilo: el temporizador que mueve al vigilante y la consulta al crear una alerta."""

    nuevas = Signal(list)  # [(Alerta, Coincidencia)]
    actualizado = Signal()
    preparado = Signal(str, object, object)  # slug, ficha (dict o None), Precios

    def __init__(self, almacen: logica.Almacen):
        super().__init__()
        self.almacen = almacen
        self.vigilante: logica.Vigilante | None = None
        self.reloj: QTimer | None = None

    def _market(self):
        from ..online.market import compartido

        return compartido()

    @Slot()
    def iniciar(self) -> None:
        self.vigilante = logica.Vigilante(
            self.almacen,
            consultar=lambda slug, rango: self._market().ventas_ahora(slug, rango),
            ficha=lambda slug: self._market().ficha(slug),
        )
        self.reloj = QTimer(self)
        self.reloj.setInterval(TICK_MS)
        self.reloj.timeout.connect(self.tick)
        self.reloj.start()

    @Slot()
    def tick(self) -> None:
        if self.vigilante is None:
            return
        alerta = self.vigilante.siguiente()
        if alerta is None:
            return
        try:
            nuevas = self.vigilante.comprobar(alerta)
        except Exception:  # noqa: BLE001 - un fallo raro no para la vigilancia
            log.exception("Fallo comprobando la alerta de %s", alerta.slug)
            return
        if nuevas:
            self.nuevas.emit([(alerta, c) for c in nuevas])
        self.actualizado.emit()

    @Slot(str)
    def preparar(self, slug: str) -> None:
        try:
            m = self._market()
            ficha = m.ficha(slug)
            precios = m.ventas_ahora(slug, None)
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo preparar la alerta de %s: %s", slug, e)
            from ..online.market import Precios

            ficha, precios = None, Precios(slug=slug, error=str(e))
        self.preparado.emit(slug, ficha, precios)

    @Slot(str)
    def mirar_pronto(self, alerta_id: str) -> None:
        if self.vigilante is not None:
            self.vigilante.mirar_pronto(alerta_id)

    @Slot()
    def parar(self) -> None:
        if self.reloj is not None:
            self.reloj.stop()


def _parar_hilo(hilo) -> None:
    try:
        if hilo.isRunning():
            hilo.quit()
            hilo.wait(3000)
    except RuntimeError:
        pass


class FilaAlerta(PanelC):
    """Una alerta: que, a que precio, como va y sus botones."""

    def __init__(self, alerta: logica.Alerta, parent=None):
        super().__init__(remate=False, fondo="panel2", chaflan=10, parent=parent)
        self.alerta = alerta
        self.titulo = EtiquetaC(alerta.nombre, "fuerte", recortar=True)
        self.tope = EtiquetaC("", "dato", tinta="acento")
        self.estado = EtiquetaC("", "pequeno", tinta="suave", envolver=True)
        self.boton_copiar = BotonC(t("Copiar /w"), tam=10)
        self.boton_copiar.setToolTip(t("Copia el mensaje para pegarlo en el chat del juego"))
        self.boton_copiar.hide()
        self.boton_pausa = BotonC("", tam=10)
        self.boton_borrar = BotonGlifo("cerrar", t("Borrar alerta"))
        self.boton_borrar.setToolTip(t("Borrar alerta"))
        textos = columna(fila(self.titulo, self.tope, None, espacio=px(10, False)), self.estado, espacio=px(2, False))
        self.capa.addLayout(fila(textos, self.boton_copiar, self.boton_pausa, self.boton_borrar,
                                 espacio=px(8, False)))
        self.pintar(None)

    def pintar(self, estado: logica.Estado | None) -> None:
        a = self.alerta
        rango = ""
        if a.rango is not None:
            rango = "  " + (t("rango máximo ({n})", n=a.rango) if a.rango == a.rango_max else t("rango {n}", n=a.rango))
        self.tope.setText(t("a {precio}p o menos", precio=a.precio) + rango)
        self.estado.setText(texto_estado(a, estado))
        self.estado.poner_tinta("aviso" if estado and estado.error and a.activa else
                                "ok" if estado and estado.coincidencias and a.activa else "suave")
        self.boton_copiar.setVisible(bool(a.activa and estado and estado.coincidencias and not estado.error))
        self.boton_pausa.setText(t("Reanudar") if not a.activa else t("Pausar"))


class PestanaAlertas(QWidget):
    # Globo de la bandeja: texto y mensaje "/w" que se copia al pulsarlo.
    aviso = Signal(str, str)
    _pedir_preparar = Signal(str)
    _pedir_mirar = Signal(str)
    _pedir_parar = Signal()

    def __init__(self, parent=None, con_red: bool = True, almacen: logica.Almacen | None = None):
        super().__init__(parent)
        transparente(self)
        self.almacen = almacen or logica.Almacen()
        self._nueva: dict | None = None  # objeto elegido para la alerta que se esta creando
        self.filas: dict[str, FilaAlerta] = {}

        # -- nueva alerta --------------------------------------------------------------------
        self.panel_nueva = PanelC(t("Nueva alerta"))
        self.nombre_nueva = EtiquetaC("", "destacado", recortar=True)
        self.info_nueva = EtiquetaC("", "pequeno", tinta="suave", envolver=True)
        self.rotulo_precio = EtiquetaC("", "rotulo", tinta="suave", mayus=True)
        self.precio = QSpinBox()
        self.precio.setRange(1, 99999)
        self.precio.setSuffix(" p")
        self.precio.setFixedWidth(px(110, False))
        self.rango = DesplegableC()
        self.rango.hide()
        self.boton_crear = BotonC(principal=True, icono="mas", tam=11)
        self.boton_crear.clicked.connect(self.crear)
        self.boton_cancelar = BotonC(tam=11)
        self.boton_cancelar.clicked.connect(self.cancelar)
        self.panel_nueva.capa.addWidget(self.nombre_nueva)
        self.panel_nueva.capa.addWidget(self.info_nueva)
        self.panel_nueva.capa.addLayout(fila(self.rotulo_precio, self.precio, self.rango, None,
                                             self.boton_cancelar, self.boton_crear, espacio=px(10, False)))
        self.panel_nueva.hide()

        # -- lista ---------------------------------------------------------------------------
        self.panel_lista = PanelC(t("Tus alertas"))
        self.estado_red = EtiquetaC("", "pequeno", tinta="suave", envolver=True)
        self.vacio = EtiquetaC("", "normal", tinta="suave", envolver=True)
        self.caja_filas = QVBoxLayout()
        self.caja_filas.setSpacing(px(6, False))
        self.panel_lista.capa.addWidget(self.estado_red)
        self.panel_lista.capa.addWidget(self.vacio)
        self.panel_lista.capa.addLayout(self.caja_filas)

        self.nota = EtiquetaC("", "pequeno", tinta="tenue", envolver=True)

        contenido = transparente(QWidget())
        caja = QVBoxLayout(contenido)
        caja.setContentsMargins(0, px(4, False), px(4, False), 0)
        caja.setSpacing(px(12, False))
        caja.addWidget(self.panel_nueva)
        caja.addWidget(self.panel_lista)
        caja.addWidget(self.nota)
        caja.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        transparente(area)
        transparente(area.viewport())
        area.setWidget(contenido)
        exterior = QHBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        exterior.addWidget(area)

        self._refresco = QTimer(self)
        self._refresco.setInterval(REFRESCO_MS)
        self._refresco.timeout.connect(self._repintar_estados)
        self._refresco.start()

        # -- hilo de red ---------------------------------------------------------------------
        self.hilo: QThread | None = None
        self.trabajador: _Trabajador | None = None
        if con_red:
            self.hilo = QThread(self)
            self.hilo.setObjectName("alertas-precio")
            self.trabajador = _Trabajador(self.almacen)
            self.trabajador.moveToThread(self.hilo)
            self.hilo.started.connect(self.trabajador.iniciar)
            self.trabajador.nuevas.connect(self._nuevas)
            self.trabajador.actualizado.connect(self._repintar_estados)
            self.trabajador.preparado.connect(self._preparado)
            self._pedir_preparar.connect(self.trabajador.preparar)
            self._pedir_mirar.connect(self.trabajador.mirar_pronto)
            self._pedir_parar.connect(self.trabajador.parar)
            self.hilo.start()
            app = QCoreApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.cerrar)
            hilo = self.hilo
            self.destroyed.connect(lambda *_: _parar_hilo(hilo))
        self.repintar()
        self.retraducir()

    # -- ciclo de vida -------------------------------------------------------------------------

    def cerrar(self) -> None:
        if self.hilo is not None:
            self._pedir_parar.emit()
            _parar_hilo(self.hilo)
            self.hilo = None

    def repintar(self) -> None:
        """Tras cambiar de tema o de tamano: el campo del precio lleva su hoja propia."""
        from .widgets import PALETA
        from .estilo_c import TITULAR

        p = PALETA
        self.precio.setStyleSheet(
            f"QSpinBox {{ background: {p['panel2']}; border: 1px solid {p['borde']};"
            f" padding: {px(4, False)}px {px(8, False)}px; font-family: '{TITULAR}'; font-weight: 600;"
            f" font-size: {px(13)}px; }}"
            f" QSpinBox:focus {{ border-color: {p['acento']}; }}"
        )

    def retraducir(self) -> None:
        from ..online.market import plataforma_configurada

        self.panel_nueva.poner_titulo(t("Nueva alerta"))
        self.panel_lista.poner_titulo(t("Tus alertas"))
        self.rotulo_precio.setText(t("Avisar a"))
        self.boton_crear.setText(t("Crear alerta"))
        self.boton_cancelar.setText(t("Cancelar"))
        self.vacio.setText(t("Aún no tienes alertas. Abre un objeto en Buscar o una meta en Mis metas y pulsa "
                             "«Avisarme de precio»."))
        plataforma = NOMBRES_PLATAFORMA.get(plataforma_configurada(), plataforma_configurada())
        self.nota.setText(t(
            "Mientras Farmadex está abierto (también escondido en la bandeja), mira warframe.market cada pocos "
            "minutos, sin agobiar a la web. Si alguien conectado vende el objeto a tu precio o menos, te sale un "
            "aviso de Windows con su nombre; al pulsarlo se copia el mensaje para pegarlo en el chat del juego. "
            "Precios de jugadores de {plataforma}.", plataforma=plataforma))
        for f in self.filas.values():
            f.boton_copiar.setText(t("Copiar /w"))
        self._pintar_lista()

    # -- nueva alerta ----------------------------------------------------------------------------

    def preparar_alerta(self, slug: str, nombre: str, unique_name: str = "") -> None:
        """Trae el objeto al formulario y pide en segundo plano su precio de ahora."""
        if not slug:
            self._nueva = None
            self.panel_nueva.show()
            self.nombre_nueva.setText(nombre)
            self.info_nueva.setText(t("Este objeto no se vende en warframe.market: no se le puede poner alerta."))
            self.info_nueva.poner_tinta("aviso")
            self.boton_crear.setEnabled(False)
            self.precio.setEnabled(False)
            self.rango.hide()
            return
        self._nueva = {"slug": slug, "nombre": nombre, "unique_name": unique_name, "nombre_en": "", "rango_max": None}
        self.panel_nueva.show()
        self.nombre_nueva.setText(nombre)
        self.info_nueva.poner_tinta("suave")
        self.precio.setEnabled(True)
        self.boton_crear.setEnabled(True)
        self.rango.hide()
        self.rango.clear()
        existente = next((a for a in self.almacen.lista() if a.slug == slug), None)
        if existente is not None:
            self.precio.setValue(existente.precio)
        if self.trabajador is not None:
            self.info_nueva.setText(t("Mirando cuánto piden ahora en warframe.market..."))
            self._pedir_preparar.emit(slug)
        else:
            self.info_nueva.setText("")

    @Slot(str, object, object)
    def _preparado(self, slug: str, ficha, precios) -> None:
        if not self._nueva or self._nueva["slug"] != slug:
            return
        if ficha:
            self._nueva["nombre_en"] = ficha.get("nombre_en") or ""
            self._nueva["rango_max"] = ficha.get("rango_max")
        rango_max = self._nueva["rango_max"]
        self.rango.clear()
        if rango_max:
            self.rango.addItem(t("Cualquier rango"), None)
            self.rango.addItem(t("Rango máximo ({n})", n=rango_max), rango_max)
            self.rango.addItem(t("Rango {n}", n=0), 0)
            self.rango.show()
        if precios is None or precios.error:
            error = precios.error if precios is not None else "?"
            self.info_nueva.setText(t("warframe.market no responde ahora ({error}). Puedes crear la alerta igual: "
                                      "se mirará cuando vuelva.", error=error))
            self.info_nueva.poner_tinta("aviso")
            return
        conectadas = [o for o in precios.ventas if o.estado in logica.ESTADOS_CONECTADO and o.platino > 0]
        if conectadas:
            barata = min(o.platino for o in conectadas)
            self.info_nueva.setText(t("Ahora mismo, lo más barato de jugadores conectados es {precio}p. "
                                      "Elige a qué precio quieres que te avise.", precio=barata))
            if not any(a.slug == slug for a in self.almacen.lista()):
                self.precio.setValue(max(1, barata - 1))
        else:
            self.info_nueva.setText(t("Ahora mismo no lo vende nadie conectado. Elige a qué precio quieres que te avise."))

    def crear(self) -> None:
        if not self._nueva:
            return
        alerta = logica.Alerta(
            slug=self._nueva["slug"], nombre=self._nueva["nombre"], precio=int(self.precio.value()),
            unique_name=self._nueva["unique_name"], nombre_en=self._nueva["nombre_en"],
            rango=self.rango.currentData() if not self.rango.isHidden() and self.rango.count() else None,
            rango_max=self._nueva["rango_max"],
        )
        if not self.almacen.anadir(alerta):
            self.info_nueva.setText(t("Ya tienes {n} alertas, que es el máximo. Borra alguna para crear otra.",
                                      n=logica.MAX_ALERTAS))
            self.info_nueva.poner_tinta("aviso")
            return
        guardada = next((a for a in self.almacen.lista() if a.slug == alerta.slug and a.rango == alerta.rango), alerta)
        if self.trabajador is not None:
            self._pedir_mirar.emit(guardada.id)
        self.cancelar()
        self._pintar_lista()

    def cancelar(self) -> None:
        self._nueva = None
        self.panel_nueva.hide()

    # -- lista -----------------------------------------------------------------------------------

    def _estado(self, alerta_id: str) -> logica.Estado | None:
        vigilante = self.trabajador.vigilante if self.trabajador is not None else None
        if vigilante is None:
            return None
        return vigilante.estados.get(alerta_id)

    def _pintar_lista(self) -> None:
        while self.caja_filas.count():
            elemento = self.caja_filas.takeAt(0)
            if elemento.widget() is not None:
                elemento.widget().deleteLater()
        self.filas = {}
        alertas = self.almacen.lista()
        self.vacio.setVisible(not alertas)
        for alerta in alertas:
            f = FilaAlerta(alerta)
            f.boton_pausa.clicked.connect(lambda _=False, a=alerta: self.pausar(a.id, a.activa))
            f.boton_borrar.clicked.connect(lambda _=False, a=alerta: self.borrar(a.id))
            f.boton_copiar.clicked.connect(lambda _=False, a=alerta: self.copiar(a.id))
            self.caja_filas.addWidget(f)
            self.filas[alerta.id] = f
        self._repintar_estados()

    @Slot()
    def _repintar_estados(self) -> None:
        for alerta_id, f in self.filas.items():
            f.pintar(self._estado(alerta_id))
        vigilante = self.trabajador.vigilante if self.trabajador is not None else None
        activas = sum(1 for a in self.almacen.lista() if a.activa)
        if vigilante is not None and vigilante.ultimo_error and vigilante.espera_hasta > time.monotonic():
            minutos = max(1, int((vigilante.espera_hasta - time.monotonic() + 59) // 60))
            self.estado_red.setText(t("warframe.market no responde ahora ({error}). Se vuelve a probar en {n} min.",
                                      error=vigilante.ultimo_error, n=minutos))
            self.estado_red.poner_tinta("aviso")
        elif activas == 1:
            self.estado_red.setText(t("Vigilando 1 alerta."))
            self.estado_red.poner_tinta("suave")
        elif activas:
            self.estado_red.setText(t("Vigilando {n} alertas.", n=activas))
            self.estado_red.poner_tinta("suave")
        else:
            self.estado_red.setText("")
        self.estado_red.setVisible(bool(self.estado_red.text()))

    def pausar(self, alerta_id: str, pausar: bool) -> None:
        self.almacen.pausar(alerta_id, pausar)
        if not pausar and self.trabajador is not None:
            self._pedir_mirar.emit(alerta_id)
        self._pintar_lista()

    def borrar(self, alerta_id: str) -> None:
        self.almacen.borrar(alerta_id)
        if self.trabajador is not None and self.trabajador.vigilante is not None:
            self.trabajador.vigilante.olvidar(alerta_id)
        self._pintar_lista()

    def copiar(self, alerta_id: str) -> str:
        estado = self._estado(alerta_id)
        if not estado or not estado.coincidencias:
            return ""
        mensaje = estado.coincidencias[0].mensaje
        QGuiApplication.clipboard().setText(mensaje)
        return mensaje

    @Slot(list)
    def _nuevas(self, pares: list) -> None:
        # Un solo globo por alerta y vuelta: el mas barato (los demas estan en la lista).
        vistas = set()
        for alerta, c in pares:
            if alerta.id in vistas:
                continue
            vistas.add(alerta.id)
            texto = logica.texto_aviso(alerta, c, t)
            log.info("Alerta de precio cumplida: %s a %sp (tope %sp)", alerta.slug, c.platino, alerta.precio)
            self.aviso.emit(texto, c.mensaje)
        self._repintar_estados()
