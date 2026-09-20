"""La cadena de farmeo: pieza -> reliquias -> misiones, y el contenido de cada reliquia.

Lo que no sale de reliquias (Rhino en Fossa, un mod de un enemigo, un plano de
un contrato) tiene su propia ruta en `fuentes_de`, ordenada por lo probable y
lo accesible que sea cada sitio.
"""

from __future__ import annotations

import json
import re
import sqlite3

from ..idiomas import glosa, nombre
from .nodos import nombre_bonito

REFINAMIENTOS = ("Intact", "Exceptional", "Flawless", "Radiant")

# Cuanto vale cada tipo de fuente frente a los demas, de mas a menos accesible.
# `grado` separa lo que se farmea en el mapa (0) de lo que exige un sortie (1),
# reputacion de sindicato (2) o algo raro como Conclave (3). Dentro del grado
# manda la probabilidad efectiva, corregida por `factor`: una mision normal con
# un 10 % gana a un enemigo con un 10 % porque al enemigo hay que encontrarlo.
ACCESIBILIDAD = {
    "mision": (0, 1.0),
    "bounty": (0, 0.9),
    "enemigo": (0, 0.8),
    "llave": (0, 0.6),
    "transitoria": (0, 0.6),
    "sortie": (1, 1.0),
    "sindicato": (2, 1.0),
    "otro": (3, 1.0),
}
FACTOR_EVENTO = 0.3  # un nodo de evento no siempre esta disponible
RE_SUFIJO = re.compile(r"\s*\((.*?)\)\s*$")
RE_ROTACION = re.compile(r",\s*Rotation\s+([A-Z])\s*$", re.IGNORECASE)


def _filas(con: sqlite3.Connection, sql: str, parametros: tuple = ()) -> list[dict]:
    anterior = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        return [dict(f) for f in con.execute(sql, parametros).fetchall()]
    finally:
        con.row_factory = anterior


def reliquias_de(con: sqlite3.Connection, item_id: int, incluir_vaulted: bool = True) -> list[dict]:
    """Reliquias que sueltan esa pieza, con sus probabilidades por refinamiento."""
    filas = _filas(
        con,
        """
        SELECT f.origen_id AS reliquia_id, f.refinamiento, f.probabilidad, f.rareza,
               r.nombre_en, r.nombre_es, r.vaulted
          FROM fuentes f JOIN items r ON r.id = f.origen_id
         WHERE f.item_id = ? AND f.tipo = 'reliquia' AND f.origen_id IS NOT NULL
        """,
        (item_id,),
    )
    agrupadas: dict[int, dict] = {}
    for f in filas:
        entrada = agrupadas.setdefault(
            f["reliquia_id"],
            {
                "reliquia_id": f["reliquia_id"],
                "nombre_en": f["nombre_en"],
                "nombre_es": f["nombre_es"],
                "vaulted": bool(f["vaulted"]),
                "rareza": f["rareza"],
                "probabilidades": {},
            },
        )
        if f["refinamiento"]:
            entrada["probabilidades"][f["refinamiento"]] = f["probabilidad"]
        entrada["rareza"] = entrada["rareza"] or f["rareza"]

    salida = [r for r in agrupadas.values() if incluir_vaulted or not r["vaulted"]]
    # Primero lo que se puede farmear hoy, y dentro, lo mas probable en Radiante.
    return sorted(
        salida,
        key=lambda r: (r["vaulted"], -(r["probabilidades"].get("Radiant") or 0)),
    )


_SQL_FUENTES = """
    SELECT f.tipo, f.origen_texto, f.rotacion, f.etapa, f.probabilidad, f.rareza,
           f.refinamiento, f.probabilidad_enemigo, f.standing, f.datos_extra,
           n.nombre_en AS nodo_en, n.nombre_es AS nodo_es,
           n.planeta_en, n.planeta_es, n.mision_en, n.nivel_min, n.nivel_max,
           (SELECT es FROM glosario WHERE dominio='mision' AND en = n.mision_en) AS mision_es
      FROM fuentes f LEFT JOIN nodos n ON n.id = f.origen_id
     WHERE f.item_id = ? AND f.tipo IN ({tipos})
     ORDER BY f.probabilidad DESC
"""


def _decorar(con: sqlite3.Connection, filas: list[dict]) -> list[dict]:
    """Anade 'donde' y 'mision' legibles a filas de la tabla de fuentes."""
    for f in filas:
        if f["nodo_en"]:
            # Nodo y planeta siguen al idioma de la interfaz (castellano o ingles).
            f["donde"] = f"{nombre(f, 'nodo')}, {nombre(f, 'planeta')}".strip(", ")
        else:
            f["donde"] = _donde_texto(con, f)
        f["mision"] = glosa(f["mision_es"], f["mision_en"]) if f["mision_es"] else (f["mision_en"] or "")
        if not f["mision"]:
            # Los nodos de Railjack no estan en el mapa que publica DE; el tipo de
            # mision se recupera del gameMode que guardo la tabla de drops.
            f["mision"] = _modo_traducido(con, f.get("datos_extra"))
    return filas


def _extra(f: dict) -> dict:
    try:
        datos = json.loads(f.get("datos_extra") or "{}")
    except json.JSONDecodeError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _donde_texto(con: sqlite3.Connection, f: dict) -> str:
    texto = f["origen_texto"] or ""
    if f["tipo"] == "sindicato":
        # drops.py guardo "Red Veil, Respected" en datos_extra.
        return _extra(f).get("lugar") or texto
    if f["tipo"] == "otro":
        texto = RE_ROTACION.sub("", texto)
        texto = RE_SUFIJO.sub("", texto)
    return nombre_bonito(con, texto)


def misiones_de(con: sqlite3.Connection, reliquia_id: int) -> list[dict]:
    """Donde cae una reliquia: nodo, planeta, tipo de mision, rotacion y probabilidad."""
    filas = _filas(
        con,
        _SQL_FUENTES.format(tipos="'mision','llave','bounty','transitoria'"),
        (reliquia_id,),
    )
    return _decorar(con, filas)


def fuentes_de(con: sqlite3.Connection, item_id: int) -> list[dict]:
    """Todas las fuentes que no son reliquia, de mejor a peor.

    Cada fila trae lo mismo que `misiones_de` mas `probabilidad_efectiva` (en un
    enemigo, probabilidad de que suelte algo por probabilidad de que sea esto),
    `grado` (0 = se farmea en el mapa ... 3 = Conclave y rarezas) y `puntuacion`,
    que es por lo que van ordenadas. Las filas de tipo 'otro' que repiten una
    mision ya conocida se quitan.
    """
    filas = _filas(
        con,
        _SQL_FUENTES.format(
            tipos="'mision','llave','bounty','transitoria','enemigo','sortie','sindicato','otro'"
        ),
        (item_id,),
    )
    _decorar(con, filas)
    vistas: set[tuple] = set()
    salida: list[dict] = []
    # Primero lo tipado, para que 'otro' solo entre si no repite nada.
    for f in sorted(filas, key=lambda f: f["tipo"] == "otro"):
        if f["tipo"] == "otro":
            rotacion = RE_ROTACION.search(f["origen_texto"] or "")
            if rotacion and not f["rotacion"]:
                f["rotacion"] = rotacion.group(1).upper()
        # "Eidolon Hydrolyst (Special)" y "Eidolon Hydrolyst" son el mismo sitio.
        sitio = RE_SUFIJO.sub("", f["donde"]).strip().lower()
        clave = (sitio, (f["rotacion"] or "").upper(), f.get("etapa") or "")
        if clave in vistas:
            continue
        vistas.add(clave)
        _puntuar(f)
        salida.append(f)
    salida.sort(
        key=lambda f: (
            f["grado"],
            -f["puntuacion"],
            f["nivel_min"] if f["nivel_min"] is not None else 999,
            f["donde"],
        )
    )
    return salida


def _puntuar(f: dict) -> None:
    prob = float(f["probabilidad"] or 0)
    if f["tipo"] == "enemigo" and f["probabilidad_enemigo"]:
        prob = prob * float(f["probabilidad_enemigo"]) / 100
    f["probabilidad_efectiva"] = round(prob, 4)
    grado, factor = ACCESIBILIDAD.get(f["tipo"], (3, 1.0))
    if _extra(f).get("evento"):
        factor *= FACTOR_EVENTO
    f["grado"] = grado
    f["puntuacion"] = round(prob * factor, 4)


def _modo_traducido(con: sqlite3.Connection, datos_extra: str | None) -> str:
    if not datos_extra:
        return ""
    try:
        modo = json.loads(datos_extra).get("modo") or ""
    except json.JSONDecodeError:
        return ""
    if not modo:
        return ""
    fila = con.execute(
        "SELECT es FROM glosario WHERE dominio = 'mision' AND en = ?", (modo,)
    ).fetchone()
    return glosa(fila[0], modo) if fila else modo


def contenido_de(con: sqlite3.Connection, reliquia_id: int, refinamiento: str = "Radiant") -> list[dict]:
    """Que sale de una reliquia con un refinamiento dado, de mas raro a mas comun."""
    return _filas(
        con,
        """
        SELECT rr.item_id, rr.rareza, rr.probabilidad,
               i.nombre_en, i.nombre_es, i.categoria,
               p.nombre_en AS padre_en, p.nombre_es AS padre_es
          FROM reliquia_recompensas rr
          JOIN items i ON i.id = rr.item_id
          LEFT JOIN items p ON p.id = i.padre_id
         WHERE rr.reliquia_id = ? AND rr.refinamiento = ?
         ORDER BY rr.probabilidad
        """,
        (reliquia_id, refinamiento),
    )


def mejor_ruta(con: sqlite3.Connection, item_id: int) -> dict | None:
    """La forma mas razonable de conseguir una pieza hoy.

    Si sale de reliquias, se queda con la disponible (no en boveda) de mayor
    probabilidad en Radiante y con la mision que mas veces la suelta; si todo
    esta en boveda, la mejor de las que hay, avisando de ello. Si no sale de
    ninguna reliquia (Rhino, un mod, un plano de contrato), la mejor fuente de
    `fuentes_de`.

    Claves: `tipo` ('reliquia', 'mision', 'enemigo', 'bounty', 'sindicato'...),
    `reliquia` (None si no es de reliquia), `solo_en_boveda`, `mision` (el sitio
    elegido, con 'donde', 'mision', 'rotacion', 'probabilidad'), `misiones` (los
    cinco mejores sitios), `probabilidad` (la de la ruta: Radiante en reliquia,
    efectiva en el resto) y `alternativas` (los otros sitios, sin el elegido).
    """
    reliquias = reliquias_de(con, item_id)
    if reliquias:
        disponibles = [r for r in reliquias if not r["vaulted"]]
        mejor = (disponibles or reliquias)[0]
        misiones = misiones_de(con, mejor["reliquia_id"])
        return {
            "tipo": "reliquia",
            "reliquia": mejor,
            "solo_en_boveda": not disponibles,
            "mision": misiones[0] if misiones else None,
            "misiones": misiones[:5],
            "probabilidad": mejor["probabilidades"].get("Radiant")
            or max(list(mejor["probabilidades"].values()) or [0]),
            "alternativas": misiones[1:5],
        }
    fuentes = fuentes_de(con, item_id)
    if not fuentes:
        return None
    mejor = fuentes[0]
    return {
        "tipo": mejor["tipo"],
        "reliquia": None,
        "solo_en_boveda": False,
        "mision": mejor,
        "misiones": fuentes[:5],
        "probabilidad": mejor["probabilidad_efectiva"],
        "alternativas": fuentes[1:5],
    }
