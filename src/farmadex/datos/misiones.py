"""Buscar una mision por su nodo ("Hepit", "Olimpo") o por su tipo ("supervivencia").

El buscador solo encontraba objetos, y quien escribe "Hepit" quiere saber que suelta
ese nodo y como se juega. Los nodos ya estan en la tabla `nodos` del indice y los tipos
de mision en modos_mision, asi que se buscan al vuelo, sin tocar la tabla de busqueda
(son unos quinientos nodos: compararlos todos cuesta menos de un milisegundo) y sin
obligar a reconstruir el indice.

Los resultados usan los mismos niveles que indice.buscar (0 exacto, 1 empieza por lo
escrito, 2 todas las palabras son principio de otras): el buscador los pone delante de
los objetos solo si casan mejor que el mejor objeto. "Hepit" solo es nodo y sale el
primero; "captura" casa con las escenas de Captura y los objetos siguen delante.
"""

from __future__ import annotations

import sqlite3

from ..idiomas import glosa, nombre as nombre_idioma
from . import modos_mision
from .items import normalizar

# Modos de modos_mision que no son un tipo de mision que se busque: las tablas del
# Circuito por nivel (Normal, Hard) y el sabotaje con escondites, que es un Sabotaje.
MODOS_NO_BUSCABLES = {"Normal", "Hard", "Caches"}
# Nodos que no son una mision que se farmee: los relevos y el Conclave (PvP, siete
# nodos que se llaman igual).
MISIONES_NO_BUSCABLES = {"Relay", "Conclave"}
# Con menos letras solo vale la coincidencia exacta: "io" es el nodo Io, pero "de" no
# puede traer todos los nodos que empiezan por "De".
MINIMO_PREFIJO = 3
MAX_RESULTADOS = 10


def _nivel(consulta: str, texto: str) -> int | None:
    """0 exacto, 1 empieza por lo escrito, 2 cada palabra empieza una del texto; None si no."""
    if not texto:
        return None
    if texto == consulta:
        return 0
    if len(consulta) < MINIMO_PREFIJO:
        return None
    if texto.startswith(consulta):
        return 1
    palabras = texto.split()
    if all(any(p.startswith(q) for p in palabras) for q in consulta.split()):
        return 2
    return None


def _mejor(consulta: str, textos) -> int | None:
    niveles = [n for n in (_nivel(consulta, normalizar(x or "")) for x in textos) if n is not None]
    return min(niveles) if niveles else None


def nodos(con: sqlite3.Connection) -> list[dict]:
    """Los nodos que son una mision conocida, uno por nombre, planeta y tipo."""
    try:
        filas = con.execute(
            "SELECT id, nombre_en, nombre_es, planeta_en, planeta_es, mision_en, mision_es,"
            " faccion_en, faccion_es, nivel_min, nivel_max FROM nodos ORDER BY planeta_en, nombre_en"
        ).fetchall()
    except sqlite3.Error:
        return []
    columnas = ("id", "nodo_en", "nodo_es", "planeta_en", "planeta_es", "mision_en", "mision_es",
                "faccion_en", "faccion_es", "nivel_min", "nivel_max")
    salida, vistos = [], set()
    for fila in filas:
        n = dict(zip(columnas, fila))
        modo = modos_mision.normalizar(n["mision_en"])
        if not modo or modo in MISIONES_NO_BUSCABLES:
            continue
        clave = (n["nodo_en"], n["planeta_en"], modo)
        if clave in vistos:
            continue
        vistos.add(clave)
        n["modo"] = modo
        salida.append(n)
    return salida


def buscar(con: sqlite3.Connection | None, texto: str, limite: int = MAX_RESULTADOS) -> list[dict]:
    """Nodos y tipos de mision que casan con lo escrito, mejores primero.

    Cada resultado lleva `clave` ('nodo:<id>' o 'modo:<Survival>'), `nivel` y lo que
    el buscador necesita para pintarlo; `item_id` es None para no confundirlo con un objeto.
    """
    consulta = normalizar(texto)
    if con is None or not consulta:
        return []
    resultados = []
    for modo, (es, en, _, _) in modos_mision.MODOS.items():
        if modo in MODOS_NO_BUSCABLES:
            continue
        alias = [a for a, destino in modos_mision.ALIAS.items() if destino == modo]
        alias += modos_mision.NOMBRES_ANTERIORES.get(modo, ())
        nivel = _mejor(consulta, [es, en, modo, glosa(es, en), *alias])
        if nivel is not None:
            resultados.append({"item_id": None, "clave": f"modo:{modo}", "tipo_resultado": "modo",
                               "modo": modo, "nivel": nivel, "orden": (nivel, 0, es)})
    for n in nodos(con):
        nivel = _mejor(consulta, [n["nodo_en"], n["nodo_es"]])
        if nivel is not None:
            resultados.append({**n, "item_id": None, "clave": f"nodo:{n['id']}", "tipo_resultado": "nodo",
                               "nivel": nivel, "orden": (nivel, 1, n["nodo_en"])})
    resultados.sort(key=lambda r: r["orden"])
    return resultados[:limite]


def nodo(con: sqlite3.Connection, nodo_id: int) -> dict | None:
    return next((n for n in nodos(con) if n["id"] == nodo_id), None)


def recompensas_de_nodo(con: sqlite3.Connection, nodo_id: int) -> dict[str, list[dict]]:
    """Lo que suelta el nodo al terminar o por rotacion: {'A': [...], 'B': [...], '': [...]}.

    Cada fila: `item_id`, nombres del objeto y de su padre, `rareza` y `probabilidad`,
    de mas a menos probable. La clave '' es el premio de las misiones sin rotaciones.
    """
    filas = con.execute(
        """
        SELECT f.rotacion, f.item_id, i.nombre_en, i.nombre_es, p.nombre_en, p.nombre_es,
               f.rareza, f.probabilidad
          FROM fuentes f JOIN items i ON i.id = f.item_id LEFT JOIN items p ON p.id = i.padre_id
         WHERE f.tipo = 'mision' AND f.origen_id = ?
         ORDER BY f.rotacion, f.probabilidad DESC, i.nombre_en
        """,
        (nodo_id,),
    ).fetchall()
    salida: dict[str, list[dict]] = {}
    vistos: set[tuple] = set()
    for rot, item_id, nombre_en, nombre_es, padre_en, padre_es, rareza, prob in filas:
        # Las tablas traen algunos nodos dos veces (Hepit: cada reliquia salia repetida).
        if (rot, item_id, prob) in vistos:
            continue
        vistos.add((rot, item_id, prob))
        salida.setdefault((rot or "").upper(), []).append({
            "item_id": item_id, "nombre_en": nombre_en, "nombre_es": nombre_es,
            "padre_en": padre_en, "padre_es": padre_es, "rareza": rareza, "probabilidad": prob,
        })
    return salida


def nodos_de_modo(con: sqlite3.Connection, modo_en: str) -> list[dict]:
    """Los nodos de un tipo de mision, por planeta."""
    modo = modos_mision.normalizar(modo_en)
    return [n for n in nodos(con) if n["modo"] == modo] if modo else []


def titulo_nodo(n: dict) -> str:
    """'Hepit' o 'Olimpo', en el idioma de la interfaz."""
    return nombre_idioma(n, "nodo")
