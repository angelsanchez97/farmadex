"""Guardado del perfil en `usuario.sqlite` y consultas encima del catalogo.

Las tablas `perfil_*` son propias de este paquete y se crean aqui con
CREATE TABLE IF NOT EXISTS; no tocan el esquema de `estado/usuario_db.py`.
El perfil es una instantanea: cada importacion sustituye la anterior entera.

Se guarda el `uniqueName` y no el id del catalogo porque el indice se regenera
entero con cada actualizacion de datos y sus ids no son estables.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import maestria
from .lector import Perfil

ESQUEMA = """
CREATE TABLE IF NOT EXISTS perfil_meta (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS perfil_xp (
  item_type TEXT PRIMARY KEY,
  xp INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS perfil_nodos (
  tag TEXT PRIMARY KEY,
  completes INTEGER NOT NULL,
  camino_acero INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS perfil_intrinsecos (clave TEXT PRIMARY KEY, valor INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS perfil_sindicatos (
  tag TEXT PRIMARY KEY,
  standing INTEGER NOT NULL,
  titulo INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS perfil_reputacion_diaria (clave TEXT PRIMARY KEY, valor INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS perfil_desafios (nombre TEXT PRIMARY KEY, progreso INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS perfil_estadisticas (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS perfil_ocr_lecturas (
  item_type TEXT PRIMARY KEY,
  rango INTEGER,
  estado TEXT NOT NULL,
  confianza REAL NOT NULL DEFAULT 0,
  nombre TEXT,
  pantalla TEXT,
  leido_en TEXT NOT NULL,
  veces INTEGER NOT NULL DEFAULT 1
);
"""

# Columnas anadidas a perfil_xp despues de la primera version: se crean si faltan.
_COLUMNAS_XP = (
    ("origen", "TEXT NOT NULL DEFAULT 'json'"),
    ("leido_en", "TEXT"),
)

# Prefijos de nodo que existen en el catalogo (tabla nodos) y por tanto se pueden
# marcar como pendientes. Junctions, hubs, Railjack (CrewBattleNode) y eventos no.
_PREFIJOS_NODO_MAPA = ("SolNode", "ClanNode", "SettlementNode")


@dataclass(frozen=True)
class EstadoItem:
    estado: str  # maestria.DOMINADO / A_MEDIAS / SIN_TOCAR / NO_APLICA
    xp: int
    umbral: int | None
    rango: int | None  # rango aproximado del objeto (0-30 o 0-40)

    @property
    def dominado(self) -> bool:
        return self.estado == maestria.DOMINADO

    @property
    def porcentaje(self) -> float:
        if not self.umbral:
            return 0.0
        return min(100.0, 100.0 * self.xp / self.umbral)


@dataclass
class Casado:
    """Resultado de casar el perfil con el catalogo."""

    total: int = 0
    casan: int = 0
    sin_catalogo: list[str] = field(default_factory=list)
    nodos_total: int = 0
    nodos_casan: int = 0
    nodos_sin_catalogo: list[str] = field(default_factory=list)

    @property
    def porcentaje(self) -> float:
        return 100.0 * self.casan / self.total if self.total else 0.0


def preparar(usuario: sqlite3.Connection) -> None:
    usuario.executescript(ESQUEMA)
    existentes = {fila[1] for fila in usuario.execute("PRAGMA table_info(perfil_xp)")}
    for columna, definicion in _COLUMNAS_XP:
        if columna not in existentes:
            usuario.execute(f"ALTER TABLE perfil_xp ADD COLUMN {columna} {definicion}")


def hay_perfil(usuario: sqlite3.Connection) -> bool:
    preparar(usuario)
    return usuario.execute("SELECT 1 FROM perfil_meta WHERE clave = 'nombre'").fetchone() is not None


def guardar(
    usuario: sqlite3.Connection, perfil: Perfil, ruta: Path | str | None = None,
    origen: str | None = None,
) -> None:
    """Guarda el perfil en una sola transaccion.

    Con origen "json" (el fichero de DE) sustituye todo lo anterior. Con origen
    "ocr" fusiona: solo toca los objetos que traiga este perfil y deja el resto
    (otras categorias escaneadas otro dia, nodos, sindicatos) como estaba.
    """
    preparar(usuario)
    origen = origen or getattr(perfil, "origen", "json")
    if origen == "ocr":
        _fusionar_ocr(usuario, perfil)
        return
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {
        "origen": "json",
        "nombre": perfil.nombre,
        "account_id": perfil.account_id,
        "rango": str(perfil.rango),
        "creado": perfil.creado.isoformat(timespec="seconds") if perfil.creado else None,
        "clan": perfil.clan,
        "clan_nivel": str(perfil.clan_nivel) if perfil.clan_nivel is not None else None,
        "plataformas": json.dumps(perfil.plataformas, ensure_ascii=False),
        "operador_desbloqueado": (
            None if perfil.operador_desbloqueado is None else str(int(perfil.operador_desbloqueado))
        ),
        "cache_expira": (
            perfil.cache_expira.isoformat(timespec="seconds") if perfil.cache_expira else None
        ),
        "importado_en": ahora,
        "fichero": str(ruta) if ruta else None,
        "fichero_modificado": _mtime(ruta),
        "objetos_xp": str(len(perfil.xp)),
        "nodos": str(len(perfil.nodos)),
    }
    with usuario:
        for tabla in ("perfil_meta", "perfil_xp", "perfil_nodos", "perfil_intrinsecos",
                      "perfil_sindicatos", "perfil_reputacion_diaria", "perfil_desafios",
                      "perfil_estadisticas", "perfil_ocr_lecturas"):
            usuario.execute(f"DELETE FROM {tabla}")
        usuario.executemany(
            "INSERT INTO perfil_meta (clave, valor) VALUES (?, ?)",
            [(k, v) for k, v in meta.items() if v is not None],
        )
        usuario.executemany(
            "INSERT OR REPLACE INTO perfil_xp (item_type, xp, origen, leido_en) "
            "VALUES (?, ?, 'json', ?)",
            [(e.item_type, e.xp, ahora) for e in perfil.xp],
        )
        usuario.executemany(
            "INSERT OR REPLACE INTO perfil_nodos (tag, completes, camino_acero) VALUES (?, ?, ?)",
            [(n.tag, n.completes, int(n.camino_acero)) for n in perfil.nodos],
        )
        usuario.executemany(
            "INSERT OR REPLACE INTO perfil_intrinsecos (clave, valor) VALUES (?, ?)",
            list(perfil.intrinsecos.items()),
        )
        usuario.executemany(
            "INSERT OR REPLACE INTO perfil_sindicatos (tag, standing, titulo) VALUES (?, ?, ?)",
            [(s.tag, s.standing, s.titulo) for s in perfil.sindicatos],
        )
        usuario.executemany(
            "INSERT OR REPLACE INTO perfil_reputacion_diaria (clave, valor) VALUES (?, ?)",
            list(perfil.reputacion_diaria.items()),
        )
        usuario.executemany(
            "INSERT OR REPLACE INTO perfil_desafios (nombre, progreso) VALUES (?, ?)",
            list(perfil.desafios.items()),
        )
        filas = [(k, json.dumps(v, ensure_ascii=False)) for k, v in perfil.estadisticas.items()]
        filas += [(k, json.dumps(v, ensure_ascii=False)) for k, v in perfil.estadisticas_listas.items()]
        usuario.executemany(
            "INSERT OR REPLACE INTO perfil_estadisticas (clave, valor) VALUES (?, ?)", filas
        )


def _fusionar_ocr(usuario: sqlite3.Connection, perfil: Perfil) -> None:
    """Actualiza solo los objetos leidos por OCR; lo demas se conserva."""
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta_previa = dict(usuario.execute("SELECT clave, valor FROM perfil_meta").fetchall())
    meta = {
        "origen": "ocr" if meta_previa.get("origen", "ocr") == "ocr" else "mixto",
        "ocr_ultimo_en": ahora,
        "importado_en": meta_previa.get("importado_en") or ahora,
    }
    if perfil.nombre:
        meta["nombre"] = perfil.nombre
    elif "nombre" not in meta_previa:
        meta["nombre"] = "Tenno"  # hay_perfil pregunta por el nombre
    if perfil.rango:
        meta["rango"] = str(perfil.rango)
    elif "rango" not in meta_previa:
        meta["rango"] = "0"
    with usuario:
        usuario.executemany(
            "INSERT OR REPLACE INTO perfil_xp (item_type, xp, origen, leido_en) "
            "VALUES (?, ?, 'ocr', ?)",
            [(e.item_type, e.xp, ahora) for e in perfil.xp],
        )
        total = usuario.execute("SELECT COUNT(*) FROM perfil_xp").fetchone()[0]
        meta["objetos_xp"] = str(total)
        if "nodos" not in meta_previa:
            meta["nodos"] = "0"
        usuario.executemany(
            "INSERT OR REPLACE INTO perfil_meta (clave, valor) VALUES (?, ?)", list(meta.items())
        )


def registrar_lecturas_ocr(usuario: sqlite3.Connection, lecturas) -> None:
    """Apunta cada objeto visto en pantalla, con o sin rango leido.

    Una lectura desconocida nunca pisa una anterior con rango: solo suma una vez
    mas que se vio. Asi la lista de "no pude leerlo" se limpia sola cuando una
    pasada posterior lo lee bien.
    """
    preparar(usuario)
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previas = {
        fila[0]: fila[1]
        for fila in usuario.execute("SELECT item_type, estado FROM perfil_ocr_lecturas")
    }
    with usuario:
        for l in lecturas:
            conocida = l.estado in (maestria.DOMINADO, maestria.A_MEDIAS) and l.rango is not None
            previa = previas.get(l.unique_name)
            # Una lectura sin rango no pisa una con rango; "no dominado" si pisa "desconocido".
            if previa is not None and not conocida and previa not in (maestria.DESCONOCIDO, maestria.NO_DOMINADO):
                usuario.execute(
                    "UPDATE perfil_ocr_lecturas SET veces = veces + 1 WHERE item_type = ?",
                    (l.unique_name,),
                )
                continue
            veces = usuario.execute(
                "SELECT veces FROM perfil_ocr_lecturas WHERE item_type = ?", (l.unique_name,)
            ).fetchone()
            usuario.execute(
                "INSERT OR REPLACE INTO perfil_ocr_lecturas "
                "(item_type, rango, estado, confianza, nombre, pantalla, leido_en, veces) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (l.unique_name, l.rango if conocida else None,
                 l.estado if (conocida or l.estado == maestria.NO_DOMINADO) else maestria.DESCONOCIDO,
                 float(l.confianza or 0.0), l.nombre or None, l.pantalla or None, ahora,
                 (veces[0] + 1) if veces else 1),
            )


def guardar_completados_ocr(usuario: sqlite3.Connection, completados: dict) -> None:
    """Fusiona el contador COMPLETADO x/y por categoria de pantalla en perfil_meta."""
    preparar(usuario)
    previos = completados_ocr(usuario)
    previos.update({k: list(v) for k, v in completados.items()})
    with usuario:
        usuario.execute(
            "INSERT OR REPLACE INTO perfil_meta (clave, valor) VALUES ('ocr_completado', ?)",
            (json.dumps(previos, ensure_ascii=False),),
        )


def completados_ocr(usuario: sqlite3.Connection) -> dict[str, list[int]]:
    """{categoria de pantalla: [dominados, total]} segun el contador del juego."""
    preparar(usuario)
    fila = usuario.execute("SELECT valor FROM perfil_meta WHERE clave = 'ocr_completado'").fetchone()
    return json.loads(fila[0]) if fila else {}


def lecturas_ocr(usuario: sqlite3.Connection) -> list[dict]:
    """Todo lo visto por OCR, con su estado y cuando se leyo."""
    preparar(usuario)
    columnas = ("item_type", "rango", "estado", "confianza", "nombre", "pantalla", "leido_en", "veces")
    return [
        dict(zip(columnas, fila))
        for fila in usuario.execute(
            f"SELECT {', '.join(columnas)} FROM perfil_ocr_lecturas ORDER BY pantalla, nombre"
        )
    ]


def desconocidos_ocr(usuario: sqlite3.Connection) -> list[dict]:
    """Objetos vistos en pantalla cuyo rango no se pudo leer y de los que no hay XP."""
    return [
        l for l in lecturas_ocr(usuario)
        if l["estado"] == maestria.DESCONOCIDO
        and usuario.execute("SELECT 1 FROM perfil_xp WHERE item_type = ?", (l["item_type"],)).fetchone() is None
    ]


def resumen(usuario: sqlite3.Connection) -> dict | None:
    """Metadatos del perfil guardado (nombre, rango, fechas, conteos) o None si no hay."""
    if not hay_perfil(usuario):
        return None
    meta = dict(usuario.execute("SELECT clave, valor FROM perfil_meta").fetchall())
    for clave in ("rango", "clan_nivel", "objetos_xp", "nodos", "operador_desbloqueado"):
        if clave in meta:
            meta[clave] = int(meta[clave])
    meta["plataformas"] = json.loads(meta.get("plataformas") or "[]")
    meta["intrinsecos"] = dict(usuario.execute("SELECT clave, valor FROM perfil_intrinsecos"))
    meta["sindicatos"] = [
        {"tag": t, "standing": s, "titulo": ti}
        for t, s, ti in usuario.execute(
            "SELECT tag, standing, titulo FROM perfil_sindicatos ORDER BY standing DESC"
        )
    ]
    return meta


def estadistica(usuario: sqlite3.Connection, clave: str):
    """Un contador de Stats (MissionsCompleted, TimePlayedSec, Weapons...) o None."""
    preparar(usuario)
    fila = usuario.execute("SELECT valor FROM perfil_estadisticas WHERE clave = ?", (clave,)).fetchone()
    return json.loads(fila[0]) if fila else None


# --- casar con el catalogo ---------------------------------------------------------


def xp_guardada(usuario: sqlite3.Connection) -> dict[str, int]:
    preparar(usuario)
    return dict(usuario.execute("SELECT item_type, xp FROM perfil_xp").fetchall())


def casar_con_catalogo(usuario: sqlite3.Connection, indice: sqlite3.Connection) -> Casado:
    """Cuenta cuantos objetos y nodos del perfil existen en el catalogo."""
    xp = xp_guardada(usuario)
    resultado = Casado(total=len(xp))
    catalogo = _unique_names(indice)
    for item_type in xp:
        if item_type in catalogo:
            resultado.casan += 1
        else:
            resultado.sin_catalogo.append(item_type)

    tags = [t for (t,) in usuario.execute("SELECT tag FROM perfil_nodos")]
    nodos = {u for (u,) in indice.execute("SELECT unique_name FROM nodos WHERE unique_name IS NOT NULL")}
    resultado.nodos_total = len(tags)
    for tag in tags:
        if tag in nodos:
            resultado.nodos_casan += 1
        else:
            resultado.nodos_sin_catalogo.append(tag)
    return resultado


def estado_de(usuario: sqlite3.Connection, indice: sqlite3.Connection, item_id: int) -> EstadoItem:
    """Estado de maestria de una ficha del catalogo: dominado, a medias, sin tocar o no aplica."""
    fila = indice.execute(
        "SELECT unique_name, categoria, tipo, nombre_en FROM items WHERE id = ?", (item_id,)
    ).fetchone()
    if fila is None:
        return EstadoItem(maestria.NO_APLICA, 0, None, None)
    unique_name, categoria, tipo, nombre_en = fila
    preparar(usuario)
    xp = usuario.execute("SELECT xp FROM perfil_xp WHERE item_type = ?", (unique_name,)).fetchone()
    return _estado(xp[0] if xp else 0, categoria, tipo, nombre_en, unique_name)


def estado_por_unique_name(
    usuario: sqlite3.Connection, indice: sqlite3.Connection, unique_name: str
) -> EstadoItem:
    fila = indice.execute(
        "SELECT id FROM items WHERE unique_name = ?", (unique_name,)
    ).fetchone()
    if fila is None:
        return EstadoItem(maestria.NO_APLICA, 0, None, None)
    return estado_de(usuario, indice, fila[0])


def estados_de_todos(usuario: sqlite3.Connection, indice: sqlite3.Connection) -> list[dict]:
    """Una fila por objeto masterizable del catalogo con su estado. Base de las demas consultas."""
    xp = xp_guardada(usuario)
    # Vistos por OCR sin poder leer el rango: no se adivina, se dice "desconocido".
    desconocidos = {
        fila[0] for fila in usuario.execute(
            "SELECT item_type FROM perfil_ocr_lecturas WHERE estado = ?", (maestria.DESCONOCIDO,)
        )
    } - set(xp)
    filas = []
    for item_id, unique_name, nombre_en, nombre_es, categoria, tipo in indice.execute(
        "SELECT id, unique_name, nombre_en, nombre_es, categoria, tipo FROM items "
        "WHERE padre_id IS NULL AND (categoria IN (%s) OR categoria = 'Misc')"
        % ",".join("?" * len(maestria.CATEGORIAS_MASTERIZABLES)),
        tuple(sorted(maestria.CATEGORIAS_MASTERIZABLES)),
    ):
        umbral = maestria.umbral_xp(categoria, tipo, nombre_en, unique_name)
        if umbral is None:
            continue
        estado = _estado(xp.get(unique_name, 0), categoria, tipo, nombre_en, unique_name)
        if unique_name in desconocidos:
            estado = EstadoItem(maestria.DESCONOCIDO, 0, umbral, None)
        filas.append(
            {
                "item_id": item_id,
                "unique_name": unique_name,
                "nombre_en": nombre_en,
                "nombre_es": nombre_es or nombre_en,
                "categoria": categoria,
                "tipo": tipo,
                "xp": estado.xp,
                "umbral": umbral,
                "rango": estado.rango,
                "estado": estado.estado,
            }
        )
    return filas


def pendientes_por_categoria(
    usuario: sqlite3.Connection, indice: sqlite3.Connection
) -> dict[str, list[dict]]:
    """Objetos aun no dominados, agrupados por categoria y con los empezados primero."""
    grupos: dict[str, list[dict]] = {}
    for fila in estados_de_todos(usuario, indice):
        if fila["estado"] == maestria.DOMINADO:
            continue
        grupos.setdefault(fila["categoria"], []).append(fila)
    for filas in grupos.values():
        filas.sort(key=lambda f: (-f["xp"], f["nombre_es"]))
    return dict(sorted(grupos.items()))


def resumen_maestria(usuario: sqlite3.Connection, indice: sqlite3.Connection) -> dict[str, dict]:
    """Por categoria: total masterizable, dominados, a medias y sin tocar."""
    conteo: dict[str, dict] = {}
    for fila in estados_de_todos(usuario, indice):
        c = conteo.setdefault(
            fila["categoria"],
            {"total": 0, maestria.DOMINADO: 0, maestria.A_MEDIAS: 0, maestria.SIN_TOCAR: 0},
        )
        c["total"] += 1
        c[fila["estado"]] = c.get(fila["estado"], 0) + 1  # DESCONOCIDO solo aparece si hay
    return dict(sorted(conteo.items()))


def nodos_pendientes(
    usuario: sqlite3.Connection, indice: sqlite3.Connection, camino_acero: bool = False
) -> list[dict]:
    """Nodos del catalogo que el jugador no ha completado (en normal o en Camino de Acero)."""
    preparar(usuario)
    hechos = {
        tag: (completes, bool(acero))
        for tag, completes, acero in usuario.execute(
            "SELECT tag, completes, camino_acero FROM perfil_nodos"
        )
    }
    pendientes = []
    for unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_es in indice.execute(
        "SELECT unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_es FROM nodos "
        "WHERE unique_name IS NOT NULL"
    ):
        if not unique_name.startswith(_PREFIJOS_NODO_MAPA):
            continue
        completes, acero = hechos.get(unique_name, (0, False))
        hecho = acero if camino_acero else (completes > 0 or acero)
        if hecho:
            continue
        pendientes.append(
            {
                "unique_name": unique_name,
                "nombre": nombre_es or nombre_en,
                "planeta": planeta_es or planeta_en,
                "mision": mision_es,
                "completes": completes,
            }
        )
    pendientes.sort(key=lambda n: (n["planeta"] or "", n["nombre"] or ""))
    return pendientes


def nodo_hecho(usuario: sqlite3.Connection, unique_name: str) -> tuple[bool, bool]:
    """(hecho en normal, hecho en Camino de Acero) para un nodo por su uniqueName."""
    preparar(usuario)
    fila = usuario.execute(
        "SELECT completes, camino_acero FROM perfil_nodos WHERE tag = ?", (unique_name,)
    ).fetchone()
    if fila is None:
        return False, False
    return (fila[0] > 0 or bool(fila[1])), bool(fila[1])


# --- internos -----------------------------------------------------------------------


def _estado(xp: int, categoria, tipo, nombre_en, unique_name) -> EstadoItem:
    umbral = maestria.umbral_xp(categoria, tipo, nombre_en, unique_name)
    estado = maestria.estado_por_xp(xp, umbral)
    rango = maestria.rango_actual(xp, umbral) if umbral else None
    return EstadoItem(estado, xp, umbral, rango)


def _unique_names(indice: sqlite3.Connection) -> set[str]:
    return {u for (u,) in indice.execute("SELECT unique_name FROM items")}


def _mtime(ruta: Path | str | None) -> str | None:
    if not ruta:
        return None
    try:
        ts = Path(ruta).stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
