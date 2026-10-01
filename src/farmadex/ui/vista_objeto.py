"""Lo que sale solo encima del juego al ver un objeto comerciable o abrir un agrietado.

- Precio de un objeto (`filas_precio`): cuando `captura/vista.py` ve el recuadro de un
  objeto comerciable (mod, arcano, pieza o plano prime...) y casa su nombre con
  seguridad, sale un recuadro con lo que piden y ofrecen ahora y el minimo y maximo de
  30 dias, por rango si lo tiene (R0, el maximo y el que se lea en pantalla). Todo sale
  del fichero diario de precios (`online.precios_diarios`, sin red en el momento); si
  un dato no esta, pone "sin datos" y nunca un numero inventado.
- Panel de agrietado (`filas_riven`): a media altura a la izquierda, la nota (grados),
  la horquilla de parecidos, las subastas de warframe.market con las que se ha hecho y
  la comparacion de tu tirada con la de esas subastas (`agrietados/analisis.py`).

Las funciones de contenido no pintan nada: devuelven filas para `CajaJuego`, asi se
prueban con datos falsos. El controlador (`ControladorVistas`) vive en el hilo de la
ventana y la red del agrietado va en su propio hilo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QRect, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ..idiomas import t
from ..registro_log import obtener
from .caja_juego import CajaJuego

log = obtener("vista_objeto")

SEGUNDOS_RECUADRO = 12.0  # si el juego no dice nada (raton quieto), el recuadro se va solo
SUBASTAS_EN_PANEL = 6


def _precios():
    """El fichero diario de precios (contrato `online.precios_diarios`), o None si no esta.

    Se importa tarde: la zona de precios lo anade aparte y, sin el, el recuadro dice
    "sin datos" en vez de romper nada.
    """
    try:
        from ..online import precios_diarios
    except Exception:  # noqa: BLE001 - modulo aun sin integrar o roto: sin precios
        return None
    try:
        return precios_diarios.precios()
    except Exception:  # noqa: BLE001 - fichero ilegible: sin precios, se dice
        log.exception("No se pudo abrir el fichero diario de precios")
        return None


@dataclass
class ObjetoVisto:
    """Un objeto comerciable reconocido en pantalla (lo manda `captura/vista.py`)."""

    item_id: int
    slug: str
    nombre: str
    rango: int | None = None  # el que se ha leido en pantalla, si se ha podido
    slug_set: str | None = None  # el set al que pertenece (piezas prime)
    caja: tuple[int, int, int, int] | None = None  # recuadro del juego en pantalla (x, y, ancho, alto)
    cursor: tuple[int, int] | None = None
    t_visto: float = 0.0  # monotonic de cuando se vio la pantalla por primera vez
    via: str = "icono"  # "icono" o "prime" (plano sin icono de comerciable)


def _p(valor) -> str:
    return t("sin datos") if valor is None else f"{int(round(valor))} p"


def _fecha(fecha) -> str:
    if not isinstance(fecha, datetime):
        return ""
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return fecha.astimezone().strftime("%d/%m %H:%M")


def rangos_a_ensenar(rangos: list[int], leido: int | None) -> list[int]:
    """R0, el maximo y el leido en pantalla (si es otro), en orden; vacio sin rangos."""
    if not rangos:
        return []
    salida = {min(rangos), max(rangos)}
    if leido is not None and leido in rangos:
        salida.add(leido)
    return sorted(salida)


def filas_precio(objeto: ObjetoVisto, pd) -> list[tuple]:
    """Las filas del recuadro de precio. `pd` es `precios_diarios.precios()` (o None)."""
    filas: list[tuple] = [("titulo", objeto.nombre, "acento")]
    if pd is None:
        filas.append(("texto", t("Todavía no hay precios descargados. Se bajan solos una vez al día "
                                 "cuando hay conexión."), "aviso"))
        return filas
    try:
        rangos = list(pd.rangos(objeto.slug) or [])
    except Exception:  # noqa: BLE001 - un fichero raro no puede tumbar el recuadro
        rangos = []
    mostrar = rangos_a_ensenar(rangos, objeto.rango)
    fecha = None
    if mostrar:
        precios = [pd.buscar(objeto.slug, r) for r in mostrar]
        if objeto.rango is not None and objeto.rango in rangos:
            filas.append(("sub", t("Rango que se ve: {r}", r=objeto.rango)))
        else:
            filas.append(("sub", t("Precio por rango")))
        if all(p is None for p in precios):
            filas.append(("texto", t("warframe.market no tiene datos de este objeto."), "aviso"))
        else:
            cabecera = [""] + [f"R{r}" for r in mostrar]
            tintas = [""] + ["acento" if r == objeto.rango else "suave" for r in mostrar]
            filas.append(("cols", cabecera, tintas))
            filas.append(("cols", [t("Venden desde")] + [_p(getattr(p, "venta_min", None)) for p in precios]))
            filas.append(("cols", [t("Compran hasta")] + [_p(getattr(p, "compra_max", None)) for p in precios]))
            filas.append(("cols", [t("30 días mín.")] + [_p(getattr(p, "min_30d", None)) for p in precios]))
            filas.append(("cols", [t("30 días máx.")] + [_p(getattr(p, "max_30d", None)) for p in precios]))
            fecha = next((p.fecha for p in precios if p is not None and getattr(p, "fecha", None)), None)
    else:
        p = pd.buscar(objeto.slug, None)
        if p is None:
            filas.append(("texto", t("warframe.market no tiene datos de este objeto."), "aviso"))
        else:
            filas.append(("fila", t("Venden desde"), _p(p.venta_min), "acento" if p.venta_min is not None else "tenue"))
            filas.append(("fila", t("Compran hasta"), _p(p.compra_max)))
            filas.append(("fila", t("30 días: mínimo"), _p(p.min_30d)))
            filas.append(("fila", t("30 días: máximo"), _p(p.max_30d)))
            if getattr(p, "volumen_30d", None):
                filas.append(("fila", t("Ventas en 30 días"), str(p.volumen_30d)))
            fecha = getattr(p, "fecha", None)
    if objeto.slug_set and objeto.slug_set != objeto.slug:
        s = pd.buscar(objeto.slug_set, None)
        if s is not None and s.venta_min is not None:
            filas.append(("fila", t("Set completo"), _p(s.venta_min)))
    fecha = fecha or getattr(pd, "fecha", None)
    filas.append(("sep",))
    if fecha:
        filas.append(("texto", t("warframe.market · datos del {fecha}. Lo de 30 días son ventas cerradas.",
                                 fecha=_fecha(fecha))))
    else:
        filas.append(("texto", t("warframe.market · sin fecha del dato")))
    return filas


# -- agrietados ---------------------------------------------------------------------------


@dataclass
class DatosRiven:
    """Todo lo que ensena el panel de un agrietado; lo que falta aun se pinta "consultando"."""

    tarjeta: object  # agrietados.lector.TarjetaLeida
    arma: object | None = None  # agrietados.mercado.Arma
    evaluaciones: list = field(default_factory=list)
    horquilla: object | None = None
    subastas: list = field(default_factory=list)
    comparacion: object | None = None
    consultando: bool = False


def _nombre_stat(slug: str) -> str:
    from ..agrietados import grados

    atributo = grados.POR_SLUG.get(slug)
    return atributo.nombre_es if atributo else slug


def _stats_cortas(atributos) -> str:
    from ..agrietados import grados

    partes = []
    for slug, valor, negativo in atributos:
        texto = grados.formatear_valor(slug, valor)
        partes.append(f"{texto} {_nombre_stat(slug)}")
    return ", ".join(partes)


def filas_riven(d: DatosRiven) -> list[tuple]:
    from ..agrietados import grados, mercado
    from .pestana_agrietados import titular_de

    tarjeta = d.tarjeta
    arma_nombre = getattr(tarjeta, "arma_nombre", "") or getattr(tarjeta, "arma_texto", "") or t("Agrietado")
    filas: list[tuple] = [("titulo", f"{arma_nombre} {getattr(tarjeta, 'nombre', '')}".strip(), "acento")]
    if getattr(tarjeta, "velado", False):
        filas.append(("texto", t("La tarjeta está velada: no tiene estadísticas hasta que hagas su desafío.")))
        return filas
    if not getattr(tarjeta, "fiable", False) or d.arma is None:
        filas.append(("texto", t("No se ha podido leer entera. Pulsa el atajo de agrietados con el ratón "
                                 "encima de la tarjeta para revisarla."), "aviso"))
        return filas
    # Nota: grado de cada estadistica.
    fuera = False
    for ev in d.evaluaciones:
        nombre = _nombre_stat(ev.slug) + (f" ({t('negativa')})" if ev.negativo else "")
        valor = grados.formatear_valor(ev.slug, ev.valor)
        if ev.grado:
            filas.append(("fila", f"{valor} {nombre}", ev.grado, grados.COLOR_GRADO.get(ev.grado.split("–")[0], "texto")))
        else:
            fuera = True
            filas.append(("fila", f"{valor} {nombre}", "?", "aviso"))
    titular = titular_de(d.evaluaciones)
    if fuera:
        filas.append(("texto", t("Algún valor no cuadra con esta arma: revisa la lectura antes de fiarte."), "aviso"))
    elif titular:
        filas.append(("sub", titular))
    if fuera:
        # Con un valor imposible, el arma o la lectura estan mal: el precio de "parecidos"
        # seria el de otro agrietado. No se pide ni se ensena.
        return filas
    filas.append(("sep",))
    # Horquilla de parecidos.
    h = d.horquilla
    if h is None:
        filas.append(("texto", t("Precio de parecidos: consultando warframe.market…")))
    elif h.error:
        filas.append(("texto", t("warframe.market no responde ahora: sin precio de parecidos."), "aviso"))
    elif h.suficiente:
        filas.append(("fila", t("Parecidos piden"), f"{h.bajo}–{h.alto} p", "acento"))
        filas.append(("fila", t("Mediana"), f"{h.mediana} p"))
        filas.append(("sub", t("{n} subastas con las mismas positivas", n=h.n) if h.nivel == "positivas"
                      else t("{n} subastas con las mismas estadísticas", n=h.n)))
    elif h.n:
        filas.append(("texto", t("Solo hay {n} subastas parecidas (hacen falta {umbral} para dar un precio). "
                                 "La más barata pide {minimo} p.", n=h.n, umbral=mercado.UMBRAL_HORQUILLA,
                                 minimo=h.minimo)))
    else:
        filas.append(("texto", t("No hay subastas parecidas abiertas ahora mismo.")))
    # Comparacion con los parecidos.
    c = d.comparacion
    if c is not None:
        filas.append(("sep",))
        if c.suficiente:
            dif = abs(c.diferencia or 0.0)
            clave = {"encima": "Tu tirada está por encima de la media de los parecidos ({dif:.0f} puntos de 100).",
                     "debajo": "Tu tirada está por debajo de la media de los parecidos ({dif:.0f} puntos de 100).",
                     "igual": "Tu tirada está en la media de los parecidos."}[c.posicion]
            filas.append(("texto", t(clave, dif=dif), "texto"))
            filas.append(("texto", t("Tira mejor que {n} de {total} subastas parecidas.", n=c.por_encima,
                                     total=c.muestras)))
            if c.precio_mejores is not None:
                filas.append(("fila", t("Los que tiran como el tuyo o mejor"),
                              t("{p} p ({n})", p=c.precio_mejores, n=c.n_mejores), "acento"))
            if c.precio_peores is not None:
                filas.append(("fila", t("Los que tiran peor"), t("{p} p ({n})", p=c.precio_peores, n=c.n_peores)))
        elif c.muestras:
            filas.append(("texto", t("Pocas subastas comparables ({n}) para decir si el tuyo está por encima "
                                     "o por debajo.", n=c.muestras)))
    # Listado de subastas.
    if d.subastas:
        filas.append(("sep",))
        filas.append(("sub", t("Subastas parecidas (compra directa)")))
        for s in d.subastas[:SUBASTAS_EN_PANEL]:
            estado = {"ingame": t("en juego"), "online": t("conectado")}.get(s.estado, t("desconectado"))
            filas.append(("fila", _stats_cortas(s.atributos)[:46], f"{s.precio} p",
                          "acento" if s.estado == "ingame" else "texto"))
            filas.append(("sub", f"{s.vendedor} · {estado} · R{s.rango} · {t('{n} variados', n=s.variado)}"))
    filas.append(("sep",))
    filas.append(("texto", t("warframe.market · subastas abiertas ahora. Es lo que piden, no lo que se paga.")))
    return filas


# -- red del agrietado (su hilo) ------------------------------------------------------


class _RedRiven(QObject):
    listo = Signal(str, object, list)  # clave, Horquilla, subastas

    @Slot(str, str, list, str)
    def pedir(self, clave: str, slug: str, positivos: list, negativo: str) -> None:
        from ..agrietados import mercado

        try:
            h, lista = mercado.compartido().parecidos(slug, list(positivos), negativo or None)
        except Exception as e:  # noqa: BLE001 - el hilo de red no se cae por esto
            log.warning("Sin parecidos de %s: %s", slug, e)
            h, lista = mercado.Horquilla(arma=slug, error=str(e) or type(e).__name__), []
        self.listo.emit(clave, h, list(lista))


# -- colocacion ------------------------------------------------------------------------


def colocar_precio(tam: tuple[int, int], caja: tuple[int, int, int, int] | None, cursor: tuple[int, int] | None,
                   zona: tuple[int, int, int, int]) -> tuple[int, int]:
    """El recuadro de precio junto al del juego sin taparlo: debajo, encima o al lado."""
    ancho, alto = tam
    zx, zy, zw, zh = zona
    sep = 8
    if caja is not None:
        x, y, w, h = caja
        opciones = ((x, y + h + sep), (x, y - alto - sep), (x + w + sep, y), (x - ancho - sep, y))
    elif cursor is not None:
        cx, cy = cursor
        opciones = ((cx - ancho - 24, cy + 24), (cx - ancho - 24, cy - alto - 24), (cx + 24, cy + 24))
    else:
        opciones = ((zx + zw - ancho - 24, zy + zh // 4),)
    for ox, oy in opciones:
        if zx <= ox and ox + ancho <= zx + zw and zy <= oy and oy + alto <= zy + zh:
            return ox, oy
    ox, oy = opciones[0]
    return max(zx, min(ox, zx + zw - ancho)), max(zy, min(oy, zy + zh - alto))


def colocar_panel_riven(tam: tuple[int, int], zona: tuple[int, int, int, int]) -> tuple[int, int]:
    """A media altura en el borde izquierdo del juego."""
    ancho, alto = tam
    zx, zy, zw, zh = zona
    margen = max(8, zw // 80)
    return zx + margen, max(zy, zy + (zh - alto) // 2)


class ControladorVistas(QObject):
    """Ensena y quita los recuadros; vive en el hilo de la ventana."""

    _pedir_parecidos = Signal(str, str, list, str)
    mostrado = Signal(str, float)  # "precio"/"riven", ms desde que se vio la pantalla
    _precios_nuevos = Signal()  # llego un fichero de precios nuevo (puede avisar otro hilo)

    def __init__(self, aviso=None, zona_juego=None, con_red: bool = True, parent=None):
        super().__init__(parent)
        self.aviso = aviso  # ui.aviso_lectura.AvisoLectura (el "Leyendo…")
        self._zona_juego = zona_juego  # () -> QRect | None
        self.caja_precio: CajaJuego | None = None
        self.caja_riven: CajaJuego | None = None
        self.objeto: ObjetoVisto | None = None
        self.riven: DatosRiven | None = None
        self._clave_riven = ""
        self._t_riven = 0.0
        self.ultimo_ms: dict[str, float] = {}
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self.esconder_precio)
        self._precios_nuevos.connect(self.repintar_precio)
        self._observar_precios()
        self.hilo: QThread | None = None
        self.red: _RedRiven | None = None
        if con_red:
            self.hilo = QThread(self)
            self.red = _RedRiven()
            self.red.moveToThread(self.hilo)
            self._pedir_parecidos.connect(self.red.pedir)
            self.red.listo.connect(self._parecidos_listos)
            self.hilo.start(QThread.LowPriority)

    def _observar_precios(self) -> None:
        """Se apunta al aviso de "precios nuevos" del fichero diario, si ya esta en el programa."""
        try:
            from ..online import precios_diarios
        except Exception:  # noqa: BLE001 - la zona de precios aun no esta: sin aviso
            return
        observar = getattr(precios_diarios, "al_actualizar", None)
        try:
            if observar is None:
                observar = getattr(precios_diarios.precios(), "al_actualizar", None)
            if observar is not None:
                observar(self._precios_nuevos.emit)
        except Exception:  # noqa: BLE001 - sin aviso, el recuadro se rehace la proxima vez
            log.debug("No se pudo observar el fichero diario de precios")

    def _zona(self) -> tuple[int, int, int, int]:
        r = self._zona_juego() if self._zona_juego else None
        if r is None or (hasattr(r, "isEmpty") and r.isEmpty()):
            pantalla = QGuiApplication.primaryScreen()
            r = pantalla.geometry() if pantalla is not None else QRect(0, 0, 1920, 1080)
        if isinstance(r, QRect):
            return r.x(), r.y(), r.width(), r.height()
        return r

    # -- precio --

    @Slot(object)
    def leyendo_precio(self, punto) -> None:
        """Se ha visto el icono de comerciable: "Leyendo…" al instante junto al cursor."""
        if self.aviso is None:
            return
        try:
            from PySide6.QtCore import QPoint

            self.aviso.leyendo("precio", QPoint(*punto) if punto else None)
        except Exception:  # noqa: BLE001 - el recuadro nunca impide leer
            log.exception("No se pudo ensenar el recuadro de lectura")

    @Slot(object)
    def mostrar_precio(self, objeto: ObjetoVisto) -> None:
        if self.caja_precio is None:
            self.caja_precio = CajaJuego(300)
        self.objeto = objeto
        self.caja_precio.poner(filas_precio(objeto, _precios()))
        x, y = colocar_precio((self.caja_precio.width(), self.caja_precio.height()), objeto.caja, objeto.cursor,
                              self._zona())
        self.caja_precio.move(x, y)
        if self.aviso is not None:
            self.aviso.listo("precio")
        self.caja_precio.show()
        self.caja_precio.raise_()
        self._temporizador.start(int(SEGUNDOS_RECUADRO * 1000))
        self._medir("precio", objeto.t_visto)

    @Slot(str)
    def sin_precio(self, motivo: str) -> None:
        """Habia icono pero el nombre no casa con seguridad (o no se vende en warframe.market):
        sin precio. El "Leyendo…" se quita sin mas: avisar de un fallo cada vez que el raton
        pasa por un pez o un adorno seria mas ruido que ayuda."""
        if self.aviso is not None and self.aviso.tipo == "precio":
            if motivo:
                self.aviso.fallo("precio", motivo)
            else:
                self.aviso.esconder()

    @Slot()
    def esconder_precio(self) -> None:
        self._temporizador.stop()
        self.objeto = None
        if self.caja_precio is not None and self.caja_precio.isVisible():
            self.caja_precio.hide()
        if self.aviso is not None and self.aviso.tipo == "precio":
            self.aviso.esconder()

    def repintar_precio(self) -> None:
        """Llego un fichero de precios nuevo: el recuadro abierto se rehace con el."""
        if self.objeto is not None and self.caja_precio is not None and self.caja_precio.isVisible():
            self.caja_precio.poner(filas_precio(self.objeto, _precios()))

    # -- agrietado --

    @Slot(object, float)
    def mostrar_riven(self, tarjeta, t_visto: float = 0.0) -> None:
        from ..agrietados import grados, mercado

        arma = None
        if getattr(tarjeta, "arma_slug", None):
            try:
                arma = mercado.compartido().arma_por_slug(tarjeta.arma_slug)
            except Exception:  # noqa: BLE001 - sin lista de armas: se dice en el panel
                arma = None
        d = DatosRiven(tarjeta=tarjeta, arma=arma)
        stats = [(e.slug, e.valor, e.negativo) for e in getattr(tarjeta, "estadisticas", []) if e.entendida]
        if arma is not None and getattr(tarjeta, "fiable", False):
            d.evaluaciones = grados.evaluar(stats, arma.clase, arma.disposicion)
        if d.evaluaciones and all(ev.minimo is not None and ev.grado for ev in d.evaluaciones):
            positivos = [s for s, _v, n in stats if not n]
            negativo = next((s for s, _v, n in stats if n), "")
            clave = f"{arma.slug}|{','.join(sorted(positivos))}|{negativo}"
            if clave != self._clave_riven or self.riven is None or self.riven.horquilla is None:
                self._clave_riven = clave
                d.consultando = True
                if self.red is not None:
                    self._pedir_parecidos.emit(clave, arma.slug, positivos, negativo)
            else:
                # El mismo agrietado otra vez: lo que ya habia llegado de la red vale.
                d.horquilla, d.subastas, d.comparacion = self.riven.horquilla, self.riven.subastas, self.riven.comparacion
        self.riven = d
        self._t_riven = t_visto
        self._pintar_riven()
        self._medir("riven", t_visto)

    def _pintar_riven(self) -> None:
        if self.riven is None:
            return
        if self.caja_riven is None:
            self.caja_riven = CajaJuego(360)
        self.caja_riven.poner(filas_riven(self.riven))
        x, y = colocar_panel_riven((self.caja_riven.width(), self.caja_riven.height()), self._zona())
        self.caja_riven.move(x, y)
        self.caja_riven.show()
        self.caja_riven.raise_()

    @Slot(str, object, list)
    def _parecidos_listos(self, clave: str, h, subastas: list) -> None:
        if clave != self._clave_riven or self.riven is None:
            return  # de un agrietado anterior
        from ..agrietados import analisis

        d = self.riven
        d.horquilla, d.subastas, d.consultando = h, subastas, False
        if d.arma is not None and not getattr(h, "error", ""):
            stats = [(e.slug, e.valor, e.negativo) for e in d.tarjeta.estadisticas if e.entendida]
            d.comparacion = analisis.comparar(stats, d.arma.clase, d.arma.disposicion, subastas)
        if self.caja_riven is not None and self.caja_riven.isVisible():
            self._pintar_riven()

    @Slot()
    def esconder_riven(self) -> None:
        if self.caja_riven is not None and self.caja_riven.isVisible():
            self.caja_riven.hide()

    # -- comun --

    def _medir(self, tipo: str, t_visto: float) -> None:
        if t_visto:
            ms = (time.monotonic() - t_visto) * 1000
            self.ultimo_ms[tipo] = ms
            log.info("Recuadro %s en pantalla %.0f ms despues de verse", tipo, ms)
            self.mostrado.emit(tipo, ms)

    def rectangulos(self) -> list[QRect]:
        return [c.geometry() for c in (self.caja_precio, self.caja_riven) if c is not None and c.isVisible()]

    def cerrar(self) -> None:
        self.esconder_precio()
        self.esconder_riven()
        for caja in (self.caja_precio, self.caja_riven):
            if caja is not None:
                caja.deleteLater()
        self.caja_precio = self.caja_riven = None
        if self.hilo is not None:
            self.hilo.quit()
            self.hilo.wait(2000)
            self.hilo = None
