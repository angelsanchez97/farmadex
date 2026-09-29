"""Ayuda de maestria: que te falta por dominar y donde se consigue, de lo mas facil a lo mas dificil.

Que tienes dominado sale de lo que Farmadex ya guarda del perfil (BD del usuario):

- `perfil_xp`: la XP de cada objeto. Con un perfil importado desde el JSON de DE es la
  lista completa (lo que no esta, no lo has usado nunca). Con lo leido por OCR en
  Perfil > Equipamiento (el lector pasivo) solo esta lo que se ha visto en pantalla.
- `perfil_ocr_lecturas`: lo visto en pantalla sin poder leer el rango ("no dominado" o
  "desconocido").
- `maestria_manual` (tabla propia de este modulo): lo que el usuario marca a mano o
  importa pegando una lista de nombres. Manda sobre lo demas: es su palabra.

Lo que no se sabe no se supone: con un perfil solo de OCR, un objeto que nunca se ha
visto en pantalla sale como "sin datos", no como "te falta".

Donde se consigue, con los datos del indice y los JSON de WFCD que ya se descargan:

- `creditos`: el plano se compra con creditos (campo `bpCost` de WFCD). Puede ser el
  Mercado o el laboratorio del dojo; WFCD no distingue, y el texto lo dice asi.
- `drop`: alguna pieza cae en misiones, enemigos o contratos (tabla `fuentes`).
- `sindicato`: por reputacion de sindicato.
- `fundicion`: se fabrica con otras armas u objetos que dan maestria (tabla `recetas`:
  el Akbolto pide dos Bolto).
- `reliquia`: piezas prime en reliquias fuera de la boveda.
- `otro`: eventos, Conclave, Duviri y demas fuentes sin tipo claro.
- `platino`: sin otra fuente conocida, se vende en el Mercado por platino (`marketCost`).
- `boveda`: solo en reliquias en boveda (intercambio, Baro, Prime Resurgence).
- `desconocido`: el indice no dice de donde sale (liches, algunas recompensas de
  misiones de historia...). Se dice, con el enlace a la wiki.

Un objeto va en el grupo de su pieza mas dificil (Rhino: plano por creditos pero
piezas de jefe -> `drop`). Lo que ya tienes a medias va primero: solo hay que subirlo.

Nada de Qt aqui: `leer_usuario` va en el hilo de la ventana (la conexion del usuario no
se comparte) y `calcular` puede ir en un hilo aparte con su propia conexion al indice.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..idiomas import nombre as nombre_idioma
from ..perfil import maestria
from . import relaciones
from .items import normalizar

# -- facilidad -------------------------------------------------------------------------------

A_MEDIAS = "a_medias"
CREDITOS = "creditos"
DROP = "drop"
SINDICATO = "sindicato"
FUNDICION = "fundicion"
RELIQUIA = "reliquia"
OTRO = "otro"
PLATINO = "platino"
BOVEDA = "boveda"
DESCONOCIDO = "desconocido"
FACILIDAD = (A_MEDIAS, CREDITOS, DROP, SINDICATO, FUNDICION, RELIQUIA, OTRO, PLATINO, BOVEDA, DESCONOCIDO)
_RANGO = {clave: i for i, clave in enumerate(FACILIDAD)}

# Tipos de fuente que se farmean en el mapa (los de `relaciones.ACCESIBILIDAD` de grado 0).
_TIPOS_DROP = frozenset(k for k, (grado, _f) in relaciones.ACCESIBILIDAD.items() if grado == 0)

# -- estado de maestria ------------------------------------------------------------------------

PENDIENTE = "pendiente"    # se sabe que no esta dominado
SIN_DATOS = "sin_datos"    # no se sabe (perfil de OCR que aun no lo ha visto, o sin perfil)
DOMINADO = maestria.DOMINADO

# -- grupos del filtro -------------------------------------------------------------------------

GRUPOS = ("warframes", "primarias", "secundarias", "cuerpo", "archwing", "companeros", "modulares", "necramechs")
NOMBRES_GRUPO = {
    "warframes": "Warframes",
    "primarias": "Primarias",
    "secundarias": "Secundarias",
    "cuerpo": "Cuerpo a cuerpo",
    "archwing": "Archwing",
    "companeros": "Compañeros",
    "modulares": "Modulares (amps, zaws, kitguns, K-Drives)",
    "necramechs": "Necramechs",
}
# Los JSON de WFCD donde estan los objetos que dan maestria (para el precio del plano).
FICHEROS_WFCD = ("Warframes", "Primary", "Secondary", "Melee", "Archwing", "Arch-Gun", "Arch-Melee",
                 "Sentinels", "SentinelWeapons", "Pets", "Misc")

ESQUEMA_MANUAL = """
CREATE TABLE IF NOT EXISTS maestria_manual (
  item_type TEXT PRIMARY KEY,
  dominado INTEGER NOT NULL,
  marcado_en TEXT NOT NULL
);
"""


def grupo_de(categoria: str | None, tipo: str | None) -> str:
    if tipo == "Necramech":
        return "necramechs"
    return {
        "Warframes": "warframes",
        "Primary": "primarias",
        "Secondary": "secundarias",
        "Melee": "cuerpo",
        "Archwing": "archwing",
        "Arch-Gun": "archwing",
        "Arch-Melee": "archwing",
        "Sentinels": "companeros",
        "Pets": "companeros",
        "Misc": "modulares",
    }.get(categoria or "", "modulares")


# -- marcas a mano -----------------------------------------------------------------------------


def preparar(usuario: sqlite3.Connection) -> None:
    usuario.executescript(ESQUEMA_MANUAL)


def marcas(usuario: sqlite3.Connection) -> dict[str, bool]:
    preparar(usuario)
    return {u: bool(d) for u, d in usuario.execute("SELECT item_type, dominado FROM maestria_manual")}


def marcar(usuario: sqlite3.Connection, unique_names, dominado: bool = True) -> int:
    """Apunta a mano que esos objetos estan (o no) dominados. Devuelve cuantos."""
    preparar(usuario)
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    filas = [(u, int(bool(dominado)), ahora) for u in dict.fromkeys(unique_names) if u]
    with usuario:
        usuario.executemany(
            "INSERT OR REPLACE INTO maestria_manual (item_type, dominado, marcado_en) VALUES (?, ?, ?)", filas
        )
    return len(filas)


def quitar_marca(usuario: sqlite3.Connection, unique_names) -> int:
    preparar(usuario)
    nombres = [u for u in dict.fromkeys(unique_names) if u]
    with usuario:
        usuario.executemany("DELETE FROM maestria_manual WHERE item_type = ?", [(u,) for u in nombres])
    return len(nombres)


def casar_lista(indice: sqlite3.Connection, texto: str) -> tuple[list[dict], list[str]]:
    """Casa una lista pegada (un nombre por linea, o separados por comas o punto y coma)
    con los objetos que dan maestria, por nombre exacto en castellano, ingles u otro idioma
    del juego, sin mayusculas ni tildes. Devuelve (casados, lineas que no casan). No
    adivina: un nombre que no es exactamente el de un objeto no se marca."""
    trozos = [x.strip() for linea in (texto or "").splitlines() for x in linea.replace(";", ",").split(",")]
    trozos = [x for x in trozos if x]
    if not trozos:
        return [], []
    por_nombre: dict[str, dict] = {}
    for item in _masterizables(indice):
        for n in (item["nombre_en"], item["nombre_es"]):
            if n:
                por_nombre.setdefault(normalizar(n), item)
    try:
        otros = indice.execute("SELECT item_id, nombre FROM items_nombres").fetchall()
    except sqlite3.Error:
        otros = []
    por_id = {i["item_id"]: i for i in por_nombre.values()}
    for item_id, n in otros:
        if item_id in por_id and n:
            por_nombre.setdefault(normalizar(n), por_id[item_id])
    casados, fallos = {}, []
    for trozo in trozos:
        item = por_nombre.get(normalizar(trozo))
        if item is None:
            fallos.append(trozo)
        else:
            casados[item["unique_name"]] = item
    return list(casados.values()), fallos


# -- lo que hace falta de la BD del usuario ------------------------------------------------------


@dataclass
class DatosUsuario:
    origen: str | None = None           # "json", "ocr", "mixto" o None sin perfil
    xp: dict[str, int] = field(default_factory=dict)
    ocr: dict[str, str] = field(default_factory=dict)  # item_type -> estado leido sin rango
    manual: dict[str, bool] = field(default_factory=dict)
    vistos_ocr: int = 0

    @property
    def lista_completa(self) -> bool:
        """La XP guardada es la lista entera (perfil JSON): lo que falta, no lo has usado."""
        return self.origen in ("json", "mixto")


def leer_usuario(usuario: sqlite3.Connection) -> DatosUsuario:
    from .. import perfil as datos_perfil

    datos = DatosUsuario(manual=marcas(usuario))
    if not datos_perfil.hay_perfil(usuario):
        return datos
    meta = dict(usuario.execute("SELECT clave, valor FROM perfil_meta").fetchall())
    datos.origen = meta.get("origen") or "json"
    datos.xp = datos_perfil.xp_guardada(usuario)
    for item_type, estado in usuario.execute("SELECT item_type, estado FROM perfil_ocr_lecturas"):
        datos.ocr[item_type] = estado
    datos.vistos_ocr = len(set(datos.ocr) | {k for k in datos.xp if datos.origen == "ocr"})
    return datos


# -- precio del plano (WFCD) -----------------------------------------------------------------------

_cache_precios: tuple[tuple, dict[str, dict]] = ((), {})


def creditos_de_planos(dir_datos: Path | None = None) -> dict[str, int]:
    """unique_name -> creditos del plano (`bpCost` de WFCD)."""
    return {u: p["creditos"] for u, p in precios_mercado(dir_datos).items() if p.get("creditos")}


def precios_mercado(dir_datos: Path | None = None) -> dict[str, dict]:
    """unique_name -> {"creditos": precio del plano (`bpCost`), "platino": precio en el
    Mercado (`marketCost`)}, de los JSON de WFCD ya descargados.

    Se guarda en memoria mientras los ficheros no cambien. Sin ficheros, vacio: el precio
    "no se sabe" y el objeto se clasifica por lo demas.
    """
    global _cache_precios
    if dir_datos is None:
        from ..config import DIR_DATOS

        dir_datos = DIR_DATOS
    rutas = [Path(dir_datos) / f"{n}.json" for n in FICHEROS_WFCD]
    firma = tuple((str(r), r.stat().st_mtime_ns) for r in rutas if r.is_file())
    if firma and firma == _cache_precios[0]:
        return _cache_precios[1]
    salida: dict[str, dict] = {}
    for ruta in rutas:
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for obj in datos if isinstance(datos, list) else []:
            if not isinstance(obj, dict):
                continue
            unico = obj.get("uniqueName")
            precios = {clave: int(v) for clave, v in (("creditos", obj.get("bpCost")), ("platino", obj.get("marketCost")))
                       if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}
            if unico and precios:
                salida[str(unico)] = precios
    _cache_precios = (firma, salida)
    return salida


# -- el calculo -------------------------------------------------------------------------------------


def _masterizables(con: sqlite3.Connection) -> list[dict]:
    salida = []
    for item_id, unico, en, es, categoria, tipo, wiki in con.execute(
        "SELECT id, unique_name, nombre_en, nombre_es, categoria, tipo, wiki_url FROM items "
        "WHERE padre_id IS NULL AND (categoria IN (%s) OR categoria = 'Misc')"
        % ",".join("?" * len(maestria.CATEGORIAS_MASTERIZABLES)),
        tuple(sorted(maestria.CATEGORIAS_MASTERIZABLES)),
    ):
        umbral = maestria.umbral_xp(categoria, tipo, en, unico)
        if umbral is None:
            continue
        salida.append({"item_id": item_id, "unique_name": unico, "nombre_en": en, "nombre_es": es or en,
                       "categoria": categoria, "tipo": tipo, "wiki_url": wiki, "umbral": umbral})
    return salida


@dataclass
class Resultado:
    filas: list[dict] = field(default_factory=list)   # lo que falta (y lo sin datos), ordenado
    marcados: list[dict] = field(default_factory=list)  # dominados a mano, para poder quitar la marca
    total: int = 0
    dominados: int = 0
    pendientes: int = 0
    sin_datos: int = 0
    origen: str | None = None
    hay_creditos: bool = False  # se han podido leer los precios de los planos


def _estado(item: dict, datos: DatosUsuario) -> tuple[str, int]:
    """(estado, xp) de un objeto segun lo guardado; ver el docstring del modulo."""
    unico = item["unique_name"]
    manual = datos.manual.get(unico)
    xp = int(datos.xp.get(unico, 0) or 0)
    if manual is True or xp >= item["umbral"]:
        return DOMINADO, xp
    if 0 < xp:
        return A_MEDIAS, xp
    if manual is False or datos.ocr.get(unico) == maestria.NO_DOMINADO:
        return PENDIENTE, 0
    if datos.lista_completa:
        return PENDIENTE, 0
    return SIN_DATOS, 0


def _piezas(con: sqlite3.Connection, ids: list[int]) -> dict[int, list[dict]]:
    """padre -> sus piezas (plano, chasis...)."""
    salida: dict[int, list[dict]] = {}
    for i in range(0, len(ids), 500):
        trozo = ids[i:i + 500]
        for item_id, padre, unico, en, es in con.execute(
            "SELECT id, padre_id, unique_name, nombre_en, nombre_es FROM items "
            f"WHERE padre_id IN ({','.join('?' * len(trozo))})", trozo,
        ):
            salida.setdefault(padre, []).append({"item_id": item_id, "unique_name": unico,
                                                 "nombre_en": en, "nombre_es": es})
    return salida


_COLUMNAS_FUENTE = """
    f.id AS fuente_id, f.item_id, f.tipo, f.origen_id, f.origen_texto, f.rotacion, f.etapa, f.probabilidad,
    f.rareza, f.refinamiento, f.probabilidad_enemigo, f.standing, f.datos_extra,
    n.nombre_en AS nodo_en, n.nombre_es AS nodo_es, n.planeta_en, n.planeta_es, n.mision_en,
    n.nivel_min, n.nivel_max,
    (SELECT es FROM glosario WHERE dominio='mision' AND en = n.mision_en) AS mision_es
"""


def _fuentes(con: sqlite3.Connection, ids: set[int]) -> dict[int, dict]:
    """item_id -> resumen de sus fuentes: mejor fila farmeable por tipo y reliquias."""
    resumen: dict[int, dict] = {}
    for fuente_id, item_id, tipo, prob, prob_enemigo, extra, vaulted, reliquia_en in con.execute(
        "SELECT f.id, f.item_id, f.tipo, f.probabilidad, f.probabilidad_enemigo, f.datos_extra, r.vaulted, "
        "r.nombre_en FROM fuentes f LEFT JOIN items r ON (f.tipo = 'reliquia' AND r.id = f.origen_id)"
    ):
        if item_id not in ids:
            continue
        r = resumen.setdefault(item_id, {"mejor": {}, "reliquias": set(), "boveda": set()})
        if tipo == "reliquia":
            if reliquia_en:
                (r["boveda"] if vaulted else r["reliquias"]).add(reliquia_en)
            continue
        efectiva = float(prob or 0)
        if tipo == "enemigo" and prob_enemigo:
            efectiva *= float(prob_enemigo) / 100
        evento = False
        if extra and "evento" in extra:
            try:
                evento = bool(json.loads(extra).get("evento"))
            except (ValueError, AttributeError):
                evento = False
        clase = OTRO if evento else (DROP if tipo in _TIPOS_DROP else SINDICATO if tipo == "sindicato" else OTRO)
        actual = r["mejor"].get(clase)
        if actual is None or efectiva > actual[1]:
            r["mejor"][clase] = (fuente_id, efectiva)
    return resumen


def _clase_pieza(pieza: dict, es_plano: bool, creditos: int | None, fuentes: dict | None) -> tuple[str, int | None]:
    """(clase, fuente_id) de UNA pieza: lo mas facil por donde se puede conseguir."""
    if es_plano and creditos:
        return CREDITOS, None
    fuentes = fuentes or {"mejor": {}, "reliquias": set(), "boveda": set()}
    for clase in (DROP, SINDICATO):
        if clase in fuentes["mejor"]:
            return clase, fuentes["mejor"][clase][0]
    if fuentes["reliquias"]:
        return RELIQUIA, None
    if OTRO in fuentes["mejor"]:
        return OTRO, fuentes["mejor"][OTRO][0]
    if fuentes["boveda"]:
        return BOVEDA, None
    return DESCONOCIDO, None


def _es_plano(pieza: dict) -> bool:
    return (pieza.get("unique_name") or "").endswith("Blueprint") or pieza.get("nombre_en") == "Blueprint"


def calcular(con: sqlite3.Connection, datos: DatosUsuario, precios: dict[str, dict] | None = None) -> Resultado:
    """Todo lo que da maestria, con su estado y donde conseguirlo, ordenado por facilidad.

    `precios` es lo de `precios_mercado` (sin ello, nada se da por comprable)."""
    precios = precios if precios is not None else {}
    items = _masterizables(con)
    resultado = Resultado(total=len(items), origen=datos.origen, hay_creditos=bool(precios))
    pendientes = []
    for item in items:
        estado, xp = _estado(item, datos)
        item["estado"], item["xp"] = estado, xp
        item["grupo"] = grupo_de(item["categoria"], item["tipo"])
        item["nombre"] = nombre_idioma(item)
        if estado == DOMINADO:
            resultado.dominados += 1
            if datos.manual.get(item["unique_name"]) is True:
                resultado.marcados.append(item)
            continue
        if estado == SIN_DATOS:
            resultado.sin_datos += 1
        else:
            resultado.pendientes += 1
        pendientes.append(item)
    if not pendientes:
        resultado.marcados.sort(key=lambda f: f["nombre"])
        return resultado

    ids = [i["item_id"] for i in pendientes]
    piezas = _piezas(con, ids)
    todos = set(ids) | {p["item_id"] for lista in piezas.values() for p in lista}
    fuentes = _fuentes(con, todos)
    ingredientes = _ingredientes(con, ids)
    elegidas: dict[int, int] = {}  # item_id del objeto -> fuente_id que se ensena

    for item in pendientes:
        precio = precios.get(item["unique_name"]) or {}
        coste = precio.get("creditos")
        propias = piezas.get(item["item_id"]) or [item]
        clases = []
        for pieza in propias:
            clase, fuente_id = _clase_pieza(pieza, _es_plano(pieza) or pieza is item, coste, fuentes.get(pieza["item_id"]))
            clases.append((clase, fuente_id, pieza))
        conocidas = [c for c in clases if c[0] != DESCONOCIDO]
        if conocidas:
            peor = max(conocidas, key=lambda c: _RANGO[c[0]])
            facilidad, fuente_id, pieza = peor
            item["piezas_sin_datos"] = len(clases) - len(conocidas)
        elif precio.get("platino"):
            facilidad, fuente_id, pieza = PLATINO, None, None
            item["piezas_sin_datos"] = 0
        else:
            facilidad, fuente_id, pieza = DESCONOCIDO, None, None
            item["piezas_sin_datos"] = 0
        item["creditos"] = coste
        item["platino"] = precio.get("platino")
        item["reliquias"] = sorted({r for p in propias for r in (fuentes.get(p["item_id"]) or {}).get("reliquias", ())},
                                   key=_orden_reliquia)
        item["ingredientes"] = ingredientes.get(item["item_id"], [])
        if item["ingredientes"] and _RANGO[facilidad] < _RANGO[FUNDICION]:
            facilidad = FUNDICION
        item["facilidad"] = A_MEDIAS if item["estado"] == A_MEDIAS else facilidad
        item["como"] = facilidad  # de donde sale, aunque ya lo tengas a medias
        item["pieza"] = nombre_idioma(pieza) if pieza is not None and pieza is not item else ""
        item["donde"] = None
        if fuente_id is not None:
            elegidas[item["item_id"]] = fuente_id

    _poner_donde(con, pendientes, elegidas)
    pendientes.sort(key=lambda f: (
        _RANGO[f["facilidad"]],
        f["estado"] == SIN_DATOS,
        -f["xp"],
        f["nombre"].lower(),
    ))
    resultado.filas = pendientes
    resultado.marcados.sort(key=lambda f: f["nombre"])
    return resultado


def _orden_reliquia(nombre: str) -> tuple:
    era = nombre.split(" ")[0]
    return ({"Lith": 0, "Meso": 1, "Neo": 2, "Axi": 3, "Requiem": 4}.get(era, 9), nombre)


def _ingredientes(con: sqlite3.Connection, ids: list[int]) -> dict[int, list[str]]:
    """Objetos que dan maestria y que pide la receta (el Bolto del Akbolto)."""
    salida: dict[int, list[str]] = {}
    try:
        filas = con.execute(
            "SELECT r.padre_id, r.cantidad, i.nombre_en, i.nombre_es, i.categoria, i.tipo, i.unique_name "
            "FROM recetas r JOIN items i ON i.id = r.item_id WHERE i.padre_id IS NULL"
        ).fetchall()
    except sqlite3.Error:
        return salida  # indice de antes de la tabla recetas
    buscados = set(ids)
    for padre, cantidad, en, es, categoria, tipo, unico in filas:
        if padre not in buscados or not maestria.es_masterizable(categoria, tipo, unico):
            continue
        texto = nombre_idioma({"nombre_en": en, "nombre_es": es})
        if cantidad and cantidad > 1:
            texto = f"{cantidad} × {texto}"
        salida.setdefault(padre, []).append(texto)
    return salida


def _poner_donde(con: sqlite3.Connection, items: list[dict], elegidas: dict[int, int]) -> None:
    """Texto "donde" (nodo, planeta y mision, o el sitio legible) de la fuente elegida."""
    ids = sorted(set(elegidas.values()))
    filas: dict[int, dict] = {}
    anterior = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        for i in range(0, len(ids), 500):
            trozo = ids[i:i + 500]
            for f in con.execute(
                f"SELECT {_COLUMNAS_FUENTE} FROM fuentes f LEFT JOIN nodos n ON n.id = f.origen_id "
                f"WHERE f.id IN ({','.join('?' * len(trozo))})", trozo,
            ):
                filas[f["fuente_id"]] = dict(f)
    finally:
        con.row_factory = anterior
    relaciones._decorar(con, list(filas.values()))
    for item in items:
        f = filas.get(elegidas.get(item["item_id"], -1))
        if f is None:
            continue
        item["donde"] = {
            "donde": f.get("donde") or "",
            "mision": f.get("mision") or "",
            "rotacion": f.get("rotacion"),
            "probabilidad": f.get("probabilidad"),
            "tipo": f.get("tipo"),
        }


def filtrar(filas: list[dict], grupo: str | None = None, texto: str = "", incluir_sin_datos: bool = True) -> list[dict]:
    """Filtro de la lista por grupo y por nombre (sin tildes ni mayusculas)."""
    buscado = normalizar(texto)
    salida = []
    for f in filas:
        if grupo and f["grupo"] != grupo:
            continue
        if not incluir_sin_datos and f["estado"] == SIN_DATOS:
            continue
        if buscado and buscado not in normalizar(f["nombre"]) and buscado not in normalizar(f["nombre_en"]):
            continue
        salida.append(f)
    return salida
