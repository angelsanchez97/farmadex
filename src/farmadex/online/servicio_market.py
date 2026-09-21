"""Consultas de precio en su propio hilo, para que la ventana no se quede parada."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from ..idiomas import t
from ..registro_log import obtener
from .market import Market, Precios, compartido

log = obtener("servicio_market")


class ServicioMarket(QObject):
    """Recibe peticiones de precio y devuelve el resultado por senal."""

    listo = Signal(str, object)  # slug, Precios

    def __init__(self, parent=None):
        super().__init__(parent)
        self.market: Market | None = None
        self._ultima_peticion: str = ""

    @Slot()
    def iniciar(self) -> None:
        # El mismo Market que usa el comparador: un solo limitador y una sola cache.
        self.market = compartido()

    @Slot(str)
    def anotar(self, slug: str) -> None:
        """Apunta cual es la peticion mas reciente, en el hilo de quien la hace.

        Se conecta en directo (no en cola), asi que se entera en el acto aunque el
        hilo del servicio siga ocupado con una peticion anterior. Asignar una
        cadena es atomico en Python: no hace falta cerrojo.
        """
        self._pendiente = slug

    def pedir(self, slug: str) -> None:
        if not slug:
            return
        # Las peticiones llegan en cola. Si mientras se atendia otra el usuario ha
        # seguido escribiendo o ha cambiado de objeto, esta ya no la quiere nadie:
        # antes se pedian todas igual, una detras de otra, al ritmo del limitador,
        # y el precio que si interesaba llegaba el ultimo.
        pendiente = getattr(self, "_pendiente", None)
        if pendiente is not None and slug != pendiente:
            return
        self._ultima_peticion = slug
        if self.market is None:
            self.iniciar()
        precios = self.market.precios(slug)
        # Si el usuario ya se ha ido a otro objeto, el resultado se descarta.
        if slug == self._ultima_peticion:
            self.listo.emit(slug, precios)

    @Slot()
    def cerrar(self) -> None:
        if self.market:
            self.market.cerrar()


def resumen(precios: Precios) -> str:
    """Una linea legible con lo que interesa: por cuanto se vende y por cuanto se compra."""
    if precios.error:
        return t("Mercado: no disponible ({error})", error=precios.error)
    if not precios.ventas and not precios.compras and not precios.por_rango:
        return t("Mercado: nadie lo vende ahora mismo")
    partes = []
    if precios.mejor_venta is not None:
        vendedores = ", ".join(
            f"{o.platino}p" for o in precios.ventas[:5]
        )
        partes.append(
            t(
                "se vende desde <b>{n} platino</b> (mediana {mediana}p; top: {top})",
                n=precios.mejor_venta,
                mediana=f"{precios.mediana_venta:.0f}",
                top=vendedores,
            )
        )
    if precios.mejor_compra is not None:
        partes.append(t("te lo compran por {n}p", n=precios.mejor_compra))
    texto = " · ".join(partes)
    if precios.con_rango:
        # Un mod sin rango vale otra cosa: se dice de que rango es el precio.
        etiqueta = (
            t("rango maximo ({n})", n=precios.rango)
            if precios.rango_max is not None and precios.rango == precios.rango_max
            else t("rango {n}", n=precios.rango)
        )
        texto = f"<b>{etiqueta}</b>: {texto}" if texto else f"<b>{etiqueta}</b>"
        otros = [
            t("rango {n} desde {p}p", n=r, p=o.mejor_venta)
            for r, o in sorted(precios.por_rango.items())
            if o.mejor_venta is not None
        ]
        if otros:
            texto += " · " + ", ".join(otros)
    if not texto:
        return t("Mercado: nadie lo vende ahora mismo")
    return t("Mercado: {resumen}", resumen=texto)
