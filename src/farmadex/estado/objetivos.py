"""Objetivos de farmeo: que quiere conseguir el usuario y como va."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from ..datos import relaciones
from ..registro_log import obtener

log = obtener("objetivos")


@dataclass
class Objetivo:
    id: int
    unique_name: str
    nombre: str
    objetivo: int
    actual: int
    completado: bool

    @property
    def porcentaje(self) -> int:
        if self.objetivo <= 0:
            return 100
        return min(100, int(self.actual * 100 / self.objetivo))


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def listar(usuario: sqlite3.Connection) -> list[Objetivo]:
    filas = usuario.execute(
        "SELECT id, item_unique_name, nombre, cantidad_objetivo, cantidad_actual, completado_en "
        "FROM objetivos ORDER BY completado_en IS NOT NULL, COALESCE(orden, id)"
    ).fetchall()
    return [Objetivo(f[0], f[1], f[2], f[3], f[4], bool(f[5])) for f in filas]


def anadir(
    usuario: sqlite3.Connection, unique_name: str, nombre: str, cantidad: int = 1
) -> int:
    """Alta idempotente: si ya estaba, solo sube la cantidad pedida."""
    existente = usuario.execute(
        "SELECT id, cantidad_objetivo FROM objetivos WHERE item_unique_name = ?", (unique_name,)
    ).fetchone()
    if existente:
        if cantidad > existente[1]:
            usuario.execute(
                "UPDATE objetivos SET cantidad_objetivo = ? WHERE id = ?", (cantidad, existente[0])
            )
            usuario.commit()
        return existente[0]
    cursor = usuario.execute(
        "INSERT INTO objetivos (item_unique_name, nombre, cantidad_objetivo, cantidad_actual, "
        "creado_en) VALUES (?, ?, ?, 0, ?)",
        (unique_name, nombre, max(1, cantidad), _ahora()),
    )
    usuario.commit()
    return cursor.lastrowid


def anadir_set(usuario: sqlite3.Connection, indice: sqlite3.Connection, item_id: int) -> list[int]:
    """Anade todas las piezas de un objeto construible, cada una con su cantidad."""
    fila = indice.execute(
        "SELECT id, unique_name, nombre_en, nombre_es, padre_id FROM items WHERE id = ?", (item_id,)
    ).fetchone()
    if not fila:
        return []
    padre_id = fila[4] or fila[0]
    padre = indice.execute(
        "SELECT unique_name, nombre_en, nombre_es FROM items WHERE id = ?", (padre_id,)
    ).fetchone()
    componentes = indice.execute(
        "SELECT unique_name, nombre_en, nombre_es, item_count FROM items WHERE padre_id = ?",
        (padre_id,),
    ).fetchall()

    nombre_padre = padre[2] or padre[1]
    if not componentes:
        return [anadir(usuario, padre[0], nombre_padre, 1)]
    return [
        anadir(
            usuario,
            unico,
            f"{nombre_padre}: {nombre_es or nombre_en}",
            cantidad or 1,
        )
        for unico, nombre_en, nombre_es, cantidad in componentes
    ]


def sumar(
    usuario: sqlite3.Connection, objetivo_id: int, cantidad: int = 1, origen: str = "manual",
    detalle: str = "",
) -> Objetivo | None:
    fila = usuario.execute(
        "SELECT cantidad_objetivo, cantidad_actual FROM objetivos WHERE id = ?", (objetivo_id,)
    ).fetchone()
    if not fila:
        return None
    nuevo = max(0, fila[1] + cantidad)
    completado = _ahora() if nuevo >= fila[0] else None
    usuario.execute(
        "UPDATE objetivos SET cantidad_actual = ?, completado_en = ? WHERE id = ?",
        (nuevo, completado, objetivo_id),
    )
    usuario.execute(
        "INSERT INTO progreso_eventos (objetivo_id, origen, cantidad, detalle, creado_en) "
        "VALUES (?, ?, ?, ?, ?)",
        (objetivo_id, origen, cantidad, detalle, _ahora()),
    )
    usuario.commit()
    return next((o for o in listar(usuario) if o.id == objetivo_id), None)


def sumar_por_item(
    usuario: sqlite3.Connection, unique_name: str, cantidad: int = 1, origen: str = "ocr"
) -> Objetivo | None:
    """Suma a un objetivo a partir del objeto, si es que ese objeto esta en la lista."""
    fila = usuario.execute(
        "SELECT id FROM objetivos WHERE item_unique_name = ?", (unique_name,)
    ).fetchone()
    if not fila:
        return None
    return sumar(usuario, fila[0], cantidad, origen=origen, detalle=unique_name)


def borrar(usuario: sqlite3.Connection, objetivo_id: int) -> None:
    usuario.execute("DELETE FROM progreso_eventos WHERE objetivo_id = ?", (objetivo_id,))
    usuario.execute("DELETE FROM objetivos WHERE id = ?", (objetivo_id,))
    usuario.commit()


def ruta_de(indice: sqlite3.Connection, unique_name: str) -> dict | None:
    """Por donde conseguir ese objetivo ahora mismo."""
    fila = indice.execute("SELECT id FROM items WHERE unique_name = ?", (unique_name,)).fetchone()
    if not fila:
        return None
    return relaciones.mejor_ruta(indice, fila[0])


def eras_necesarias(indice: sqlite3.Connection, usuario: sqlite3.Connection) -> dict[str, list[str]]:
    """Que eras de reliquia hacen falta para lo que queda por farmear.

    Sirve para marcar en la pestana Mundo las fisuras que te interesan.
    """
    salida: dict[str, list[str]] = {}
    for objetivo in listar(usuario):
        if objetivo.completado:
            continue
        ruta = ruta_de(indice, objetivo.unique_name)
        # Lo que no cae de reliquia (jefes, bounties...) no pide ninguna era.
        if not ruta or ruta.get("tipo", "reliquia") != "reliquia" or not ruta.get("reliquia"):
            continue
        if ruta["solo_en_boveda"]:
            continue
        era = (ruta["reliquia"]["nombre_en"] or "").split(" ")[0]
        if era:
            salida.setdefault(era, []).append(objetivo.nombre)
    return salida
