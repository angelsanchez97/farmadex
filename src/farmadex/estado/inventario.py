"""Lo que el jugador tiene, leido en pantalla: cantidades de recursos, piezas y planos.

Cada objeto se guarda con la fecha de su ultima lectura y nunca se borra lo que
no sale en la pagina que se acaba de leer: el inventario se ve por paginas y la
lectura es incremental. La tabla es propia de este modulo (CREATE TABLE IF NOT
EXISTS) y no toca el esquema versionado de `usuario_db.py`.

Los objetivos se sincronizan hacia arriba solamente: si el inventario dice que
tienes 3 y el objetivo lleva 1, pasa a 3 (origen "inventario"); si dice menos, no
se baja nada, porque una cifra mal leida no debe deshacer lo apuntado a mano.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from ..registro_log import obtener
from . import objetivos as estado_objetivos

log = obtener("inventario")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS inventario_lecturas (
  item_type TEXT PRIMARY KEY,
  cantidad INTEGER NOT NULL,
  nombre TEXT,
  pantalla TEXT,
  confianza REAL NOT NULL DEFAULT 0,
  leido_en TEXT NOT NULL,
  veces INTEGER NOT NULL DEFAULT 1
);
"""

ORIGEN = "inventario"


@dataclass(frozen=True)
class Lectura:
    unique_name: str
    cantidad: int
    nombre: str = ""
    pantalla: str = ""
    confianza: float = 0.0
    leido_en: str = ""
    veces: int = 1


def preparar(usuario: sqlite3.Connection) -> None:
    usuario.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def guardar(usuario: sqlite3.Connection, lecturas, pantalla: str = "") -> int:
    """Fusiona las cantidades leidas en una pagina; devuelve cuantas entraron.

    `lecturas` son objetos con `unique_name`, `cantidad` y, opcionalmente,
    `nombre` y `confianza` (las `Cantidad` de `captura.inventario` valen).
    """
    preparar(usuario)
    ahora = _ahora()
    n = 0
    with usuario:
        for l in lecturas:
            cantidad = getattr(l, "cantidad", None)
            if cantidad is None or cantidad < 0 or not getattr(l, "unique_name", ""):
                continue
            veces = usuario.execute(
                "SELECT veces FROM inventario_lecturas WHERE item_type = ?", (l.unique_name,)
            ).fetchone()
            usuario.execute(
                "INSERT OR REPLACE INTO inventario_lecturas "
                "(item_type, cantidad, nombre, pantalla, confianza, leido_en, veces) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    l.unique_name, int(cantidad), getattr(l, "nombre", "") or None,
                    pantalla or getattr(l, "pantalla", "") or None,
                    float(getattr(l, "confianza", 0.0) or 0.0), ahora,
                    (veces[0] + 1) if veces else 1,
                ),
            )
            n += 1
    return n


def cantidad_de(usuario: sqlite3.Connection, unique_name: str) -> Lectura | None:
    preparar(usuario)
    fila = usuario.execute(
        "SELECT item_type, cantidad, nombre, pantalla, confianza, leido_en, veces "
        "FROM inventario_lecturas WHERE item_type = ?",
        (unique_name,),
    ).fetchone()
    return Lectura(fila[0], fila[1], fila[2] or "", fila[3] or "", fila[4], fila[5], fila[6]) if fila else None


def listar(usuario: sqlite3.Connection) -> list[Lectura]:
    preparar(usuario)
    return [
        Lectura(f[0], f[1], f[2] or "", f[3] or "", f[4], f[5], f[6])
        for f in usuario.execute(
            "SELECT item_type, cantidad, nombre, pantalla, confianza, leido_en, veces "
            "FROM inventario_lecturas ORDER BY nombre"
        )
    ]


def hay_lecturas(usuario: sqlite3.Connection) -> bool:
    preparar(usuario)
    return usuario.execute("SELECT 1 FROM inventario_lecturas LIMIT 1").fetchone() is not None


def sincronizar_objetivos(usuario: sqlite3.Connection) -> list[tuple[str, int, int]]:
    """Sube cada objetivo hasta la cantidad leida en el inventario (nunca la baja).

    Devuelve [(unique_name, antes, despues)] de los objetivos que han cambiado.
    """
    preparar(usuario)
    cambios = []
    for objetivo in estado_objetivos.listar(usuario):
        lectura = cantidad_de(usuario, objetivo.unique_name)
        # El contador de un objetivo no pasa de su meta: tener 900 de 500 lo deja en 500.
        tope = min(lectura.cantidad, objetivo.objetivo) if lectura is not None else 0
        if lectura is None or tope <= objetivo.actual:
            continue
        estado_objetivos.sumar(
            usuario, objetivo.id, tope - objetivo.actual, origen=ORIGEN,
            detalle=f"inventario: {lectura.cantidad}",
        )
        cambios.append((objetivo.unique_name, objetivo.actual, tope))
    if cambios:
        log.info("Objetivos puestos al dia con el inventario: %d", len(cambios))
    return cambios
