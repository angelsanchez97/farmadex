"""Lo que se ensena de precio de un objeto, sacado SOLO del snapshot local (sin red).

El snapshot lo mantiene `online.precios_diarios` (zona "precios"): se importa de forma
perezosa y, si aun no existe o falla, todo dice "sin datos" en vez de inventar.
Contrato: `precios().buscar(slug, rango) -> Precio | None`, `.rangos(slug) -> list[int]`,
`.fecha`, `.al_actualizar(callback)`; `Precio` con venta_min, venta_mediana, compra_max
(ordenes en vivo al hacer el snapshot), min_30d, max_30d, media_30d, volumen_30d
(operaciones cerradas en 30 dias) y fecha.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..idiomas import t
from ..registro_log import obtener

log = obtener("chat.precios")


def _precios():
    """El snapshot local (`PreciosDiarios`) o None si el modulo no esta o no carga."""
    try:
        from ..online import precios_diarios  # type: ignore[attr-defined]
    except ImportError:
        return None
    try:
        snapshot = precios_diarios.precios()
    except Exception:  # noqa: BLE001 - sin snapshot se dice "sin datos"
        log.exception("No se pudo abrir el snapshot de precios")
        return None
    # `precios()` siempre devuelve la foto comun, aunque aun este vacia (sin descargar, o
    # de otra plataforma): eso cuenta como "sin precios descargados", nunca como dato.
    return snapshot if getattr(snapshot, "disponible", True) else None


@dataclass
class Fila:
    """Una fila de precio: un rango concreto (o None si el objeto no tiene rangos)."""

    rango: int | None
    precio: object | None  # Precio del contrato o None = sin datos


def rangos_a_ensenar(snapshot, slug: str, rango_pedido: int | None = None,
                     solo_maximo: bool = False) -> list[int | None]:
    """R0 y R maximo si el objeto tiene rangos; el pedido si se pidio uno; [None] si no tiene."""
    try:
        rangos = sorted(int(r) for r in (snapshot.rangos(slug) if snapshot else []) or [])
    except Exception:  # noqa: BLE001
        rangos = []
    if rango_pedido is not None:
        if rangos and rango_pedido > rangos[-1]:
            rango_pedido = rangos[-1]  # "R10" de un arcano de R5: su maximo
        return [rango_pedido] if rangos else [None]
    if not rangos:
        return [None]
    if solo_maximo:
        return [rangos[-1]]
    return list(dict.fromkeys((rangos[0], rangos[-1])))


def filas(slug: str | None, rango_pedido: int | None = None, snapshot=None,
          solo_maximo: bool = False) -> list[Fila]:
    if not slug:
        return []
    snapshot = snapshot if snapshot is not None else _precios()
    if snapshot is None:
        return [Fila(rango_pedido, None)]
    salida = []
    for rango in rangos_a_ensenar(snapshot, slug, rango_pedido, solo_maximo):
        try:
            precio = snapshot.buscar(slug, rango)
        except Exception:  # noqa: BLE001
            precio = None
        salida.append(Fila(rango, precio))
    return salida


def fecha_snapshot(snapshot=None) -> datetime | None:
    snapshot = snapshot if snapshot is not None else _precios()
    return getattr(snapshot, "fecha", None) if snapshot is not None else None


# -- textos -------------------------------------------------------------------------


def plat(valor) -> str:
    if valor is None:
        return "—"
    try:
        return f"{float(valor):.0f}"
    except (TypeError, ValueError):
        return "—"


def texto_rango(rango: int | None) -> str:
    return "" if rango is None else t("R{rango}", rango=rango)


def texto_30d(precio) -> str:
    """'8–12 p' con las operaciones cerradas en 30 dias; 'sin datos' si no hay."""
    if precio is None:
        return t("sin datos")
    bajo, alto = getattr(precio, "min_30d", None), getattr(precio, "max_30d", None)
    if bajo is None and alto is None:
        return t("sin datos")
    if bajo is None or alto is None or plat(bajo) == plat(alto):
        return t("{p} p", p=plat(bajo if bajo is not None else alto))
    return t("{bajo}–{alto} p", bajo=plat(bajo), alto=plat(alto))


def texto_ahora(precio) -> str:
    """'vende 10 · compra 8' con las ordenes en vivo del snapshot."""
    if precio is None:
        return t("sin datos")
    venta, compra = getattr(precio, "venta_min", None), getattr(precio, "compra_max", None)
    if venta is None and compra is None:
        return t("sin órdenes")
    return t("venden desde {venta} · compran hasta {compra}", venta=plat(venta), compra=plat(compra))


def texto_fecha(fecha) -> str:
    """'warframe.market · precios del 30/09 00:00 UTC' o 'Sin precios descargados'."""
    if not isinstance(fecha, datetime):
        return t("Sin precios descargados todavía")
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return t("warframe.market · precios del {fecha} UTC", fecha=fecha.astimezone(timezone.utc).strftime("%d/%m %H:%M"))
