"""Regla ducados contra platino: que hacer con una pieza prime que sobra.

Los datos ya estan en el indice (`items.ducados`) y en warframe.market (precio
en platino). Aqui solo vive la decision, con umbral configurable, para que la
ficha y la etiqueta de recompensas digan lo mismo.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# Destinos posibles de una pieza.
DUCADOS = "ducados"  # a Baro: vale poco en platino y bastante en ducados
PLATINO = "platino"  # a venderla: alguien paga por ella
INDIFERENTE = "indiferente"  # vale poco en los dos; da igual
SIN_DATOS = "sin_datos"  # no hay precio, o no es una pieza prime


@dataclass(frozen=True)
class Umbral:
    """Por debajo de `platino_max` platino y con `ducados_min` ducados o mas, a Baro."""

    platino_max: int = 5
    ducados_min: int = 45


POR_DEFECTO = Umbral()
CLAVE_PLATINO = "ducados_umbral_platino"
CLAVE_DUCADOS = "ducados_umbral_ducados"


def umbral_de(config: dict | None) -> Umbral:
    """El umbral que haya en la configuracion del usuario, o el de fabrica."""
    config = config or {}
    return Umbral(
        platino_max=_entero(config.get(CLAVE_PLATINO), POR_DEFECTO.platino_max),
        ducados_min=_entero(config.get(CLAVE_DUCADOS), POR_DEFECTO.ducados_min),
    )


def _entero(valor, por_defecto: int) -> int:
    try:
        return int(valor) if valor is not None else por_defecto
    except (TypeError, ValueError):
        return por_defecto


@dataclass
class Veredicto:
    destino: str
    ducados: int | None
    platino: int | None
    umbral: Umbral
    # Ducados que da cada platino que se deja de ganar; alto = mejor para Baro.
    ducados_por_platino: float | None = None

    @property
    def a_baro(self) -> bool:
        return self.destino == DUCADOS

    @property
    def a_vender(self) -> bool:
        return self.destino == PLATINO


def decidir(ducados: int | None, platino: int | float | None, umbral: Umbral | None = None) -> Veredicto:
    """'Esto por ducados, esto por platino', con el umbral dado.

    `platino` es el precio de venta mas bajo que hay ahora (lo que sacarias tu).
    Sin ducados no es pieza prime: se vende si tiene precio. Sin precio no se
    decide. Por debajo del umbral de platino, a Baro si llega a los ducados
    minimos y, si no, da igual.
    """
    umbral = umbral or POR_DEFECTO
    ratio = None
    if ducados and platino:
        ratio = round(ducados / float(platino), 1)
    if not ducados:
        destino = PLATINO if platino else SIN_DATOS
    elif platino is None:
        destino = SIN_DATOS
    elif platino < umbral.platino_max:
        destino = DUCADOS if ducados >= umbral.ducados_min else INDIFERENTE
    else:
        destino = PLATINO
    return Veredicto(
        destino=destino,
        ducados=ducados or None,
        platino=int(platino) if platino is not None else None,
        umbral=umbral,
        ducados_por_platino=ratio,
    )


def ducados_de(con: sqlite3.Connection, item_id: int) -> int | None:
    fila = con.execute("SELECT ducados FROM items WHERE id = ?", (item_id,)).fetchone()
    return fila[0] if fila and fila[0] else None


def valorar(
    con: sqlite3.Connection,
    item_id: int,
    precios,
    umbral: Umbral | None = None,
) -> Veredicto:
    """Veredicto para un objeto del indice con sus `Precios` de market (o None)."""
    platino = None
    if precios is not None and not getattr(precios, "error", ""):
        platino = precios.mejor_venta
    return decidir(ducados_de(con, item_id), platino, umbral)
