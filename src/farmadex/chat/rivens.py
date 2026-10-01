"""Precio de agrietados parecidos al que se nombra en el chat o en una lista, en segundo plano.

Del nombre ("Rubico Critacan") salen el arma y las estadisticas positivas; con eso se
piden las subastas abiertas de warframe.market de esa arma con esas mismas positivas
(`agrietados.mercado`, lo mismo que usa la pestana de Agrietados) y se da la horquilla
de siempre: cuartiles si hay al menos `UMBRAL_HORQUILLA` subastas, y si no, se dice
cuantas hay y no se inventa nada. El nombre no dice si lleva negativa: no se filtra por
ella. Es la unica parte de `chat` que usa la red, y nunca en el hilo de la interfaz.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from ..datos.items import normalizar
from ..idiomas import t
from ..registro_log import obtener

log = obtener("chat.rivens")


def nombres_estadisticas(slugs: list[str]) -> str:
    """'Prob. crítica + Multidisparo' en el idioma de la interfaz."""
    from ..agrietados.grados import POR_SLUG
    from ..idiomas import es_castellano

    nombres = []
    for slug in slugs:
        a = POR_SLUG.get(slug)
        nombres.append((a.nombre_es if es_castellano() else a.nombre_en) if a else slug)
    return " + ".join(nombres)


def calcular(arma_en: str, positivos: list[str], mercado=None):
    """Horquilla de parecidos (bloquea: red). Devuelve `Horquilla` (con `error` si no se pudo)."""
    from ..agrietados import mercado as m

    mercado = mercado or m.compartido()
    clave = normalizar(arma_en)
    arma = next((a for a in mercado.armas() if normalizar(a.nombre_en) == clave), None)
    if arma is None:
        return m.Horquilla(arma=arma_en, error="arma sin agrietado")
    try:
        resumen = mercado.subastas(arma.slug, sorted(positivos), None, limite=500)
    except Exception as e:  # noqa: BLE001
        return m.Horquilla(arma=arma.slug, error=str(e) or type(e).__name__)
    if resumen.error:
        return m.Horquilla(arma=arma.slug, error=resumen.error)
    # `subastas` cae a "cualquier agrietado del arma" si el filtro no da nada: eso no son
    # parecidos. Solo cuentan las que llevan todas las positivas pedidas.
    pedidas = set(positivos)
    precios = [s.precio for s in resumen.subastas
               if s.precio and pedidas <= {slug for slug, _v, negativo in s.atributos if not negativo}]
    return m.calcular_horquilla(arma.slug, precios, "positivas")


def texto_horquilla(h) -> str:
    """Lo que se ensena: horquilla, 'pocos parecidos' o 'sin datos'. Nunca un numero inventado."""
    if h is None:
        return t("buscando parecidos…")
    if h.error:
        return t("sin datos de parecidos")
    if h.suficiente:
        return t("parecidos a la venta: {bajo}–{alto} p ({n} subastas)", bajo=h.bajo, alto=h.alto, n=h.n)
    if h.n:
        return t("solo {n} parecidos a la venta (desde {minimo} p): pocos para dar un precio",
                 n=h.n, minimo=h.minimo)
    return t("ningún parecido a la venta ahora")


class ServicioRivens(QObject):
    """Pide horquillas en un hilo y avisa (en el hilo de la interfaz) con `lista`."""

    lista = Signal(str, object)  # clave "arma|stat,stat", Horquilla

    def __init__(self, calcular_fn=calcular, parent=None):
        super().__init__(parent)
        self._calcular = calcular_fn
        self._hilos = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat-rivens")
        self._hechas: dict[str, object] = {}
        self._pendientes: set[str] = set()

    @staticmethod
    def clave(arma: str, positivos: list[str]) -> str:
        return f"{arma}|{','.join(sorted(positivos))}"

    def pedir(self, arma: str, positivos: list[str]):
        """La horquilla si ya se tiene; si no, None y llegara por `lista`."""
        clave = self.clave(arma, positivos)
        if clave in self._hechas:
            return self._hechas[clave]
        if clave not in self._pendientes:
            self._pendientes.add(clave)
            self._hilos.submit(self._trabajo, clave, arma, list(positivos))
        return None

    def _trabajo(self, clave: str, arma: str, positivos: list[str]) -> None:
        try:
            h = self._calcular(arma, positivos)
        except Exception as e:  # noqa: BLE001
            log.warning("Sin horquilla para %s: %s", clave, e)
            from ..agrietados.mercado import Horquilla

            h = Horquilla(arma=arma, error=str(e) or type(e).__name__)
        if not getattr(h, "error", ""):
            self._hechas[clave] = h
        self._pendientes.discard(clave)
        try:
            self.lista.emit(clave, h)
        except RuntimeError:  # la ventana ya se cerro
            pass

    def cerrar(self) -> None:
        self._hilos.shutdown(wait=False, cancel_futures=True)
