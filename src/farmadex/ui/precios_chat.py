"""Precios al instante encima del juego: enlaces del chat y listas de venta copiadas.

- `TarjetaPrecio`: junto al cursor, al pasar el raton por un enlace del chat. No coge el
  foco ni el raton (como la tarjeta de reliquias).
- `ListaVenta`: en la esquina derecha, con lo que se acaba de copiar si parece una lista
  de venta. No coge el foco; se cierra con un clic o sola al rato.
- `ServicioChat`: lo junta todo (lector del chat en su hilo, portapapeles por evento,
  historial, agrietados en segundo plano) para que la ventana solo tenga que crearlo.

Todo lo que se pinta sale del snapshot local de precios (`chat/precios.py`); la unica red
es la horquilla de agrietados, en segundo plano. Sin dato se dice "sin datos".
"""

from __future__ import annotations

import html
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..chat import nombres, precios, rivens, texto as texto_chat
from ..chat.enlace import HoverChat, LectorEnlaceChat
from ..chat.historial import HistorialChat
from ..idiomas import t
from ..registro_log import obtener
from .estilo_c import color, fuente, hex_de, px, ruta_chaflan
from .tooltip_reliquia import colocar

log = obtener("precios_chat")

CONFIANZA_MINIMA = 0.50  # del OCR del enlace; por debajo no se ensena nada
SEGUNDOS_LISTA = 45
MAXIMO_FILAS_LISTA = 24


# -- contenido (sin Qt: se prueba solo) ----------------------------------------------------


def contenido_enlace(entrada, snapshot=None, horquilla=None, sin_snapshot: bool = False) -> dict:
    """{'titulo', 'sub', 'filas': [(rango, 30 dias, ahora)], 'pie'} de un enlace del chat."""
    if entrada.riven is not None:
        return {
            "titulo": t("Agrietado: {nombre}", nombre=entrada.nombre()),
            "sub": rivens.nombres_estadisticas(entrada.riven.estadisticas),
            "filas": [],
            "nota": rivens.texto_horquilla(horquilla),
            "pie": t("Subastas abiertas de warframe.market con esas mismas estadísticas"),
        }
    titulo = entrada.nombre() + (" · " + t("set completo") if entrada.es_set else "")
    if not entrada.slug:
        return {"titulo": titulo, "sub": "", "filas": [], "pie": "",
                "nota": t("No se vende entre jugadores") if not entrada.es_set else t("sin datos")}
    snapshot = None if sin_snapshot else (snapshot if snapshot is not None else precios._precios())
    filas = []
    for fila in precios.filas(entrada.slug, entrada.rango, snapshot, entrada.rango_max):
        filas.append((precios.texto_rango(fila.rango), precios.texto_30d(fila.precio),
                      precios.texto_ahora(fila.precio)))
    return {"titulo": titulo, "sub": "", "filas": filas, "nota": "",
            "pie": precios.texto_fecha(precios.fecha_snapshot(snapshot) if snapshot is not None else None)}


def precio_resumido(entrada, snapshot=None) -> str:
    """Una linea para el historial: 'R0 8–12 p · R5 140–180 p'."""
    if entrada.riven is not None or not entrada.slug:
        return ""
    trozos = []
    for fila in precios.filas(entrada.slug, entrada.rango, snapshot, entrada.rango_max):
        trozos.append((precios.texto_rango(fila.rango) + " " + precios.texto_30d(fila.precio)).strip())
    return " · ".join(trozos)


def filas_lista(entradas: list, snapshot=None, horquillas: dict | None = None) -> list[dict]:
    """Una fila por objeto de la lista: nombre, columnas [(etiqueta, 30 dias, ahora)] y lo pedido."""
    snapshot = snapshot if snapshot is not None else precios._precios()
    horquillas = horquillas or {}
    salida = []
    for e in entradas[:MAXIMO_FILAS_LISTA]:
        fila = {"nombre": e.nombre(), "columnas": [], "nota": "", "pedido": e.precio_pedido, "reconocido": e.reconocido}
        if not e.reconocido:
            fila["nombre"] = e.texto.strip("[] ")
            fila["nota"] = t("no reconocido")
        elif e.riven is not None:
            clave = rivens.ServicioRivens.clave(e.riven.arma, e.riven.estadisticas)
            fila["nota"] = rivens.texto_horquilla(horquillas.get(clave))
        elif not e.slug:
            fila["nota"] = t("sin datos") if e.es_set else t("No se vende entre jugadores")
        else:
            if e.es_set:
                fila["nombre"] += " · " + t("set")
            for f in precios.filas(e.slug, e.rango, snapshot, e.rango_max):
                ahora = getattr(f.precio, "venta_min", None) if f.precio is not None else None
                fila["columnas"].append((precios.texto_rango(f.rango), precios.texto_30d(f.precio),
                                         "" if ahora is None else precios.plat(ahora)))
        salida.append(fila)
    return salida


# -- ventanas ------------------------------------------------------------------------------


class _Flotante(QWidget):
    """Panel achaflanado encima de todo, sin foco. Con `raton=False` tampoco coge el raton."""

    def __init__(self, raton: bool, parent=None):
        banderas = Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        if not raton:
            banderas |= Qt.WindowTransparentForInput
        super().__init__(parent, banderas)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        if not raton:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.cuerpo = QLabel(self)
        self.cuerpo.setTextFormat(Qt.RichText)
        self.cuerpo.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        caja = QVBoxLayout(self)
        m = px(12, False)
        caja.setContentsMargins(m, m, m, m)
        caja.addWidget(self.cuerpo)

    def poner_html(self, cuerpo: str) -> None:
        self.cuerpo.setFont(fuente("normal", tam=13))
        self.cuerpo.setText(cuerpo)
        self.adjustSize()
        self.update()

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        camino = ruta_chaflan(r, px(10, False))
        p.fillPath(camino, color("panel"))
        p.setPen(QPen(color("acento_tenue"), 1))
        p.drawPath(camino)
        p.setPen(QPen(color("acento"), 2))
        p.drawLine(QPointF(r.left() + px(10, False), r.top() + 1), QPointF(r.left() + px(52, False), r.top() + 1))


def _e(valor) -> str:
    return html.escape(str(valor))


def html_enlace(c: dict) -> str:
    suave, acento, texto = hex_de("suave"), hex_de("acento"), hex_de("texto")
    partes = [f"<div style='color:{acento}; font-weight:600; font-size:{px(15)}px'>{_e(c['titulo'])}</div>"]
    if c.get("sub"):
        partes.append(f"<div style='color:{suave}'>{_e(c['sub'])}</div>")
    if c["filas"]:
        partes.append("<table cellspacing='0' cellpadding='2' style='margin-top:4px'>")
        for rango, dias, ahora in c["filas"]:
            partes.append(
                f"<tr><td style='color:{acento}; padding-right:8px'>{_e(rango)}</td>"
                f"<td style='color:{texto}; padding-right:10px'><b>{_e(dias)}</b> "
                f"<span style='color:{suave}'>{_e(t('en 30 días'))}</span></td>"
                f"<td style='color:{suave}'>{_e(t('ahora'))}: {_e(ahora)}</td></tr>")
        partes.append("</table>")
    if c.get("nota"):
        partes.append(f"<div style='color:{texto}; margin-top:4px'>{_e(c['nota'])}</div>")
    if c.get("pie"):
        partes.append(f"<div style='color:{suave}; font-size:{px(11)}px; margin-top:4px'>{_e(c['pie'])}</div>")
    return "".join(partes)


def html_lista(filas: list[dict], pie: str, sobran: int = 0) -> str:
    suave, acento, texto, aviso = hex_de("suave"), hex_de("acento"), hex_de("texto"), hex_de("aviso")
    partes = [f"<div style='color:{acento}; font-weight:600; font-size:{px(15)}px'>"
              f"{_e(t('Lo que has copiado'))}</div>",
              f"<div style='color:{suave}; font-size:{px(11)}px'>{_e(t('Precio más bajo y más alto de los últimos 30 días'))}</div>",
              "<table cellspacing='0' cellpadding='2' style='margin-top:4px'>"]
    for f in filas:
        celdas = ""
        for etiqueta, dias, ahora in f["columnas"]:
            extra = f" <span style='color:{suave}'>({_e(t('ahora'))} {_e(ahora)})</span>" if ahora else ""
            marca = f"<span style='color:{acento}'>{_e(etiqueta)}</span> " if etiqueta else ""
            celdas += f"<td style='color:{texto}; padding-right:10px'>{marca}<b>{_e(dias)}</b>{extra}</td>"
        if f["nota"]:
            tinta = aviso if not f["reconocido"] else suave
            celdas += f"<td colspan='2' style='color:{tinta}'>{_e(f['nota'])}</td>"
        pedido = (f"<td style='color:{suave}'>{_e(t('pides {p} p', p=f['pedido']))}</td>"
                  if f.get("pedido") is not None else "<td></td>")
        partes.append(f"<tr><td style='color:{texto}; padding-right:12px'>{_e(f['nombre'])}</td>{celdas}{pedido}</tr>")
    partes.append("</table>")
    if sobran > 0:
        partes.append(f"<div style='color:{suave}'>{_e(t('… y {n} más', n=sobran))}</div>")
    partes.append(f"<div style='color:{suave}; font-size:{px(11)}px; margin-top:4px'>{_e(pie)} · "
                  f"{_e(t('clic para cerrar'))}</div>")
    return "".join(partes)


class TarjetaPrecio(_Flotante):
    def __init__(self, parent=None):
        super().__init__(raton=False, parent=parent)


class ListaVenta(_Flotante):
    cerrada = Signal()

    def __init__(self, parent=None):
        super().__init__(raton=True, parent=parent)
        self._reloj = QTimer(self)
        self._reloj.setSingleShot(True)
        self._reloj.timeout.connect(self.hide)

    def mostrar_en_esquina(self) -> None:
        pantalla = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        zona = pantalla.availableGeometry() if pantalla is not None else QRect(0, 0, 1920, 1080)
        margen = px(16, False)
        self.move(zona.x() + zona.width() - self.width() - margen, zona.y() + margen + zona.height() // 8)
        self.show()
        self.raise_()
        self._reloj.start(SEGUNDOS_LISTA * 1000)

    def mousePressEvent(self, _evento):  # noqa: N802
        self.hide()
        self.cerrada.emit()


# -- servicio ------------------------------------------------------------------------------


class ServicioChat(QObject):
    """Enlaces del chat + portapapeles + historial. Vive en el hilo de la interfaz."""

    _lista_analizada = Signal(object, object, float)  # texto, entradas | None, t0

    def __init__(self, config: dict, sobre_farmadex: Callable[[int, int], bool] | None = None,
                 se_puede_pintar: Callable[[], bool] | None = None, motor_ocr: str = "auto", parent=None):
        super().__init__(parent)
        self.config = config
        self._se_puede_pintar = se_puede_pintar or (lambda: True)
        self.tarjeta: TarjetaPrecio | None = None
        self.lista: ListaVenta | None = None
        self.historial = HistorialChat(activo=bool(config.get("historial_chat", False)))
        self.rivens = rivens.ServicioRivens(parent=self)
        self.rivens.lista.connect(self._horquilla_lista)
        self._entrada_visible = None
        self._entradas_lista: list | None = None
        self._horquillas: dict = {}
        self.latencias_enlace: list[float] = []
        self.latencias_lista: list[float] = []
        self.portapapeles_activo = bool(config.get("portapapeles_ventas", False))
        self._fondo = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat-lista")
        self._lista_analizada.connect(self._lista_lista)
        self._ultimo_texto = ""

        self.lector = LectorEnlaceChat(motor_ocr)
        self.lector.con_usuario = self.historial.activo
        self.hilo = QThread(self)
        self.hilo.setObjectName("chat-enlaces")
        self.lector.moveToThread(self.hilo)
        self.hover = HoverChat(self._mostrar_enlace, self._ocultar_enlace,
                               activo=bool(config.get("precio_enlaces_chat", True)),
                               sobre_farmadex=sobre_farmadex, parent=self)
        self.hover.pedir_lectura.connect(self.lector.leer)
        self.lector.leida.connect(self.hover.leida)
        self._portapapeles = None
        self._conectado = False

    # -- arranque y cierre --

    def iniciar(self) -> None:
        self.hilo.start()
        self.hover.iniciar()
        if self.hover.activo or self.portapapeles_activo:
            self._preparar()
        portapapeles = QGuiApplication.clipboard()
        if portapapeles is not None:
            self._portapapeles = portapapeles
            portapapeles.dataChanged.connect(self._portapapeles_cambiado)
            self._conectado = True

    def _preparar(self) -> None:
        """Lo que tarda la primera vez (nombres del indice, motor OCR), fuera del primer uso."""
        nombres.precargar_en_segundo_plano()
        if self.hover.activo:
            QTimer.singleShot(0, lambda: self._fondo.submit(self._calentar_ocr))

    def _calentar_ocr(self) -> None:
        try:
            import numpy as np

            from ..agrietados import grados  # noqa: F401 - su importacion tarda la primera vez
            from ..chat.enlace import leer_recorte

            leer_recorte(self.lector._motor(), np.full((40, 200, 3), 255, np.uint8))
        except Exception:  # noqa: BLE001
            log.exception("No se pudo precalentar el OCR del chat")

    def cerrar(self) -> None:
        self.hover.parar()
        if self._portapapeles is not None and self._conectado:
            self._conectado = False
            try:
                self._portapapeles.dataChanged.disconnect(self._portapapeles_cambiado)
            except (RuntimeError, TypeError):
                pass
        self.rivens.cerrar()
        self._fondo.shutdown(wait=False, cancel_futures=True)
        self.hilo.quit()
        self.hilo.wait(3000)
        for ventana in (self.tarjeta, self.lista):
            if ventana is not None:
                ventana.hide()
                ventana.deleteLater()

    # -- ajustes --

    def activar_enlaces(self, activo: bool) -> None:
        self.hover.activar(activo)
        if activo:
            self._preparar()

    def activar_portapapeles(self, activo: bool) -> None:
        self.portapapeles_activo = bool(activo)
        if activo:
            nombres.precargar_en_segundo_plano()
        elif self.lista is not None:
            self.lista.hide()

    def activar_historial(self, activo: bool) -> None:
        self.historial.activo = bool(activo)
        self.lector.con_usuario = bool(activo)

    def cambiar_motor(self, motor: str) -> None:
        self.lector.cambiar_motor(motor)

    def ventanas(self) -> list[QWidget]:
        return [v for v in (self.tarjeta, self.lista) if v is not None]

    # -- enlaces del chat --

    def _mostrar_enlace(self, lectura) -> bool:
        if not self._se_puede_pintar() or lectura.confianza < CONFIANZA_MINIMA:
            return False
        res = nombres.resolutor()
        if res is None:
            return False
        entrada = texto_chat.interpretar_enlace(lectura.texto, res)
        if entrada is None:
            log.debug("Enlace del chat sin casar: %r", lectura.texto)
            return False
        horquilla = None
        if entrada.riven is not None:
            horquilla = self.rivens.pedir(entrada.riven.arma, entrada.riven.estadisticas)
        self._entrada_visible = entrada
        if self.tarjeta is None:
            self.tarjeta = TarjetaPrecio()
        snapshot = precios._precios()
        self.tarjeta.poner_html(html_enlace(contenido_enlace(entrada, snapshot, horquilla)))
        punto = QCursor.pos()
        pantalla = QGuiApplication.screenAt(punto) or QGuiApplication.primaryScreen()
        zona = pantalla.availableGeometry() if pantalla is not None else QRect(0, 0, 1920, 1080)
        x, y = colocar((self.tarjeta.width(), self.tarjeta.height()), (punto.x(), punto.y()),
                       (zona.x(), zona.y(), zona.width(), zona.height()), separacion=px(26, False))
        self.tarjeta.move(x, y)
        self.tarjeta.show()
        self.tarjeta.raise_()
        latencia = self.hover.latencia_ms(lectura.numero)
        if latencia is not None:
            self.latencias_enlace.append(latencia)
            del self.latencias_enlace[:-200]
        log.info("Enlace del chat: %r -> %s (OCR %.0f ms, del raton quieto al dato %.0f ms)",
                 lectura.texto, entrada.slug or entrada.nombre(), lectura.ms, latencia or -1)
        self.historial.apuntar(entrada.nombre(), entrada.slug, precio_resumido(entrada, snapshot), lectura.usuario)
        return True

    def _ocultar_enlace(self) -> None:
        self._entrada_visible = None
        if self.tarjeta is not None:
            self.tarjeta.hide()

    def _horquilla_lista(self, clave: str, horquilla) -> None:
        self._horquillas[clave] = horquilla
        e = self._entrada_visible
        if (e is not None and e.riven is not None and self.tarjeta is not None and self.tarjeta.isVisible()
                and rivens.ServicioRivens.clave(e.riven.arma, e.riven.estadisticas) == clave):
            self.tarjeta.poner_html(html_enlace(contenido_enlace(e, None, horquilla)))
        if self._entradas_lista and self.lista is not None and self.lista.isVisible():
            self._pintar_lista()

    # -- portapapeles --

    def _portapapeles_cambiado(self) -> None:
        if not self.portapapeles_activo or self._portapapeles is None:
            return
        t0 = time.perf_counter()
        try:
            if QGuiApplication.applicationState() == Qt.ApplicationActive:
                return  # lo ha copiado Farmadex (o el usuario dentro de Farmadex)
            datos = self._portapapeles.mimeData()
            if datos is None or not datos.hasText():
                return
            texto = datos.text()
        except Exception:  # noqa: BLE001 - otro programa tiene el portapapeles cogido
            return
        self.analizar_texto(texto, t0)

    def analizar_texto(self, texto: str, t0: float | None = None) -> bool:
        """Manda a analizar un texto copiado. False si se descarta sin mirar."""
        t0 = time.perf_counter() if t0 is None else t0
        if not texto or len(texto) > texto_chat.LARGO_MAXIMO or len(texto.strip()) < 4:
            return False
        if texto.lstrip().lower().startswith("/w "):
            return False  # el susurro que copia el propio Farmadex
        self._ultimo_texto = texto
        self._fondo.submit(self._analizar, texto, t0)
        return True

    def _analizar(self, texto: str, t0: float) -> None:
        try:
            res = nombres.resolutor()
            entradas = texto_chat.analizar_lista(texto, res) if res is not None else None
        except Exception:  # noqa: BLE001
            log.exception("Fallo analizando lo copiado")
            entradas = None
        try:
            self._lista_analizada.emit(texto, entradas, t0)
        except RuntimeError:
            pass

    def _lista_lista(self, texto: str, entradas, t0: float) -> None:
        if texto != self._ultimo_texto or not self.portapapeles_activo:
            return
        if not entradas:
            return
        if not self._se_puede_pintar():
            return
        self._entradas_lista = entradas
        for e in entradas:
            if e.riven is not None:
                h = self.rivens.pedir(e.riven.arma, e.riven.estadisticas)
                if h is not None:
                    self._horquillas[rivens.ServicioRivens.clave(e.riven.arma, e.riven.estadisticas)] = h
        if self.lista is None:
            self.lista = ListaVenta()
        self._pintar_lista()
        self.lista.mostrar_en_esquina()
        ms = (time.perf_counter() - t0) * 1000
        self.latencias_lista.append(ms)
        del self.latencias_lista[:-200]
        log.info("Lista copiada: %d objetos (%d sin reconocer), de copiar al dato %.0f ms",
                 len(entradas), sum(1 for e in entradas if not e.reconocido), ms)

    def _pintar_lista(self) -> None:
        snapshot = precios._precios()
        filas = filas_lista(self._entradas_lista or [], snapshot, self._horquillas)
        pie = precios.texto_fecha(precios.fecha_snapshot(snapshot) if snapshot is not None else None)
        self.lista.poner_html(html_lista(filas, pie, len(self._entradas_lista or []) - len(filas)))
