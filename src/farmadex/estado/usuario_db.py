"""Base de datos del usuario: nunca se regenera, solo se migra."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import RUTA_USUARIO_DB, crear_carpetas
from ..registro_log import obtener

log = obtener("usuario_db")

VERSION = 2

ESQUEMA = """
CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);

CREATE TABLE IF NOT EXISTS objetivos (
  id INTEGER PRIMARY KEY,
  item_unique_name TEXT NOT NULL,
  nombre TEXT NOT NULL,
  cantidad_objetivo INTEGER NOT NULL DEFAULT 1,
  cantidad_actual INTEGER NOT NULL DEFAULT 0,
  creado_en TEXT NOT NULL,
  completado_en TEXT,
  notas TEXT,
  orden INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_objetivos_item ON objetivos(item_unique_name);

CREATE TABLE IF NOT EXISTS progreso_eventos (
  id INTEGER PRIMARY KEY,
  objetivo_id INTEGER REFERENCES objetivos(id) ON DELETE CASCADE,
  origen TEXT NOT NULL,
  cantidad INTEGER NOT NULL,
  detalle TEXT,
  creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS historial_recompensas (
  id INTEGER PRIMARY KEY,
  leido_en TEXT NOT NULL,
  textos_ocr TEXT NOT NULL,
  items_json TEXT NOT NULL,
  elegido_unique_name TEXT,
  mejor_unique_name TEXT,
  valor_platino REAL,
  ducados INTEGER
);

-- Lo que EE.log cuenta del dia: reliquias abiertas y misiones terminadas.
CREATE TABLE IF NOT EXISTS historial_eventos (
  id INTEGER PRIMARY KEY,
  evento TEXT NOT NULL,
  ocurrido_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_historial_eventos_fecha ON historial_eventos(ocurrido_en);

CREATE TABLE IF NOT EXISTS calibracion_ocr (
  resolucion TEXT PRIMARY KEY,
  regiones_json TEXT NOT NULL
);
"""


def conectar(ruta: Path = RUTA_USUARIO_DB) -> sqlite3.Connection:
    crear_carpetas()
    con = sqlite3.connect(ruta)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(ESQUEMA)
    _migrar(con)
    return con


def _migrar(con: sqlite3.Connection) -> None:
    fila = con.execute("SELECT valor FROM meta WHERE clave = 'esquema_version'").fetchone()
    actual = int(fila[0]) if fila else 0
    if actual == VERSION:
        return
    if actual < 2:
        # v2: el historial guarda que se recomendo y cuanto valia, para el resumen del dia.
        _anadir_columna(con, "historial_recompensas", "mejor_unique_name", "TEXT")
        _anadir_columna(con, "historial_recompensas", "valor_platino", "REAL")
        _anadir_columna(con, "historial_recompensas", "ducados", "INTEGER")
    con.execute(
        "INSERT OR REPLACE INTO meta (clave, valor) VALUES ('esquema_version', ?)", (str(VERSION),)
    )
    con.commit()
    if actual:
        log.info("Base de datos del usuario migrada de la version %d a la %d", actual, VERSION)


def _anadir_columna(con: sqlite3.Connection, tabla: str, columna: str, tipo: str) -> None:
    """ALTER TABLE ADD COLUMN solo si falta (las bases nuevas ya la traen del esquema)."""
    existentes = {fila[1] for fila in con.execute(f"PRAGMA table_info({tabla})")}
    if columna not in existentes:
        con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
