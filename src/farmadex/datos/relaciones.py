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
from . import eficiencia
from .items import normalizar
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


# Las tablas de WFCD traen casi todos los premios de reliquia como "Uncommon" (Neo Z5:
# seis premios, seis Uncommon; el Axi A7 en boveda marca los Sistemas de Ash Prime al
# 10 % como poco comunes). La rareza real la fija la probabilidad de cada refinamiento:
# en Radiante el 10 % es la pieza rara, el 20 % las poco comunes y el 16,7 % las comunes.
RAREZA_POR_PROBABILIDAD = {
    "Intact": ((2.0, "Rare"), (11.0, "Uncommon"), (25.33, "Common")),
    "Exceptional": ((4.0, "Rare"), (13.0, "Uncommon"), (23.33, "Common")),
    "Flawless": ((6.0, "Rare"), (17.0, "Uncommon"), (20.0, "Common")),
    "Radiant": ((10.0, "Rare"), (20.0, "Uncommon"), (16.67, "Common")),
}


def rareza_reliquia(refinamiento: str | None, probabilidad, rareza_tabla: str | None = None) -> str | None:
    """La rareza de un premio de reliquia por su probabilidad; la de la tabla solo si no cuadra."""
    umbrales = RAREZA_POR_PROBABILIDAD.get(refinamiento or "")
    if umbrales and probabilidad is not None:
        for umbral, rareza in umbrales:
            if abs(float(probabilidad) - umbral) < 0.5:
                return rareza
    return rareza_tabla


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
        entrada["rareza"] = rareza_reliquia(f["refinamiento"], f["probabilidad"], entrada["rareza"] or f["rareza"])

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
    """Anade 'donde', 'mision' y 'modo' legibles a filas de la tabla de fuentes.

    Un enemigo que es jefe de asesinato (Alad V, el Chacal) se completa con su nodo:
    las tablas de drops solo traen el nombre, y sin el nodo no se sabe donde matarlo.
    """
    for f in filas:
        f["modo"] = _extra(f).get("modo") or f.get("mision_en") or ""
        f["jefe"] = False
        if f["tipo"] == "enemigo":
            _completar_jefe(con, f)
        if f.get("jefe"):
            f["donde"] = f"{f['origen_texto']} ({nombre(f, 'nodo')}, {nombre(f, 'planeta')})"
        elif f["nodo_en"]:
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


def _nodo_por_nombre(con: sqlite3.Connection, nombre_en: str) -> dict | None:
    filas = _filas(
        con,
        """
        SELECT nombre_en AS nodo_en, nombre_es AS nodo_es, planeta_en, planeta_es, mision_en,
               nivel_min, nivel_max,
               (SELECT es FROM glosario WHERE dominio='mision' AND en = nodos.mision_en) AS mision_es
          FROM nodos WHERE nombre_en = ? AND planeta_en NOT IN ('', 'Event') LIMIT 1
        """,
        (nombre_en,),
    )
    return filas[0] if filas else None


def _completar_jefe(con: sqlite3.Connection, f: dict) -> None:
    """Si el enemigo es un jefe conocido, la fila pasa a llevar su nodo y su mision."""
    jefe = eficiencia.JEFES.get(RE_SUFIJO.sub("", f["origen_texto"] or "").strip())
    if not jefe:
        return
    nodo = _nodo_por_nombre(con, jefe[0])
    if not nodo:
        return
    f.update(nodo)
    f["jefe"] = True
    f["modo"] = nodo["mision_en"] or "Assassination"


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
    _decorar(con, filas)
    for f in filas:
        _puntuar(f)
    # De menos a mas tiempo medio; a igual tiempo, mas probable y de nivel mas bajo.
    filas.sort(
        key=lambda f: (
            eficiencia.clave_orden(f),
            -f["puntuacion"],
            f["nivel_min"] if f["nivel_min"] is not None else 999,
        )
    )
    return filas


def fuentes_de(con: sqlite3.Connection, item_id: int) -> list[dict]:
    """Todas las fuentes que no son reliquia, de mejor a peor.

    Cada fila trae lo mismo que `misiones_de` mas `probabilidad_efectiva` (en un
    enemigo, probabilidad de que suelte algo por probabilidad de que sea esto),
    `grado` (0 = se farmea en el mapa ... 3 = Conclave y rarezas), `puntuacion`,
    y la estimacion de `eficiencia`: `minutos_medios` (None si no se puede
    estimar) y `motivo`. Van ordenadas por grado y, dentro, por tiempo medio; lo
    que no tiene estimacion va detras, por puntuacion. Las filas de tipo 'otro'
    que repiten una mision ya conocida se quitan. Si el objeto es un recurso de
    planeta, entran tambien los jefes de esos planetas que lo sueltan al morir.
    """
    filas = _filas(
        con,
        _SQL_FUENTES.format(
            tipos="'mision','llave','bounty','transitoria','enemigo','sortie','sindicato','otro'"
        ),
        (item_id,),
    )
    _decorar(con, filas)
    planeta = recurso_de_planeta(con, item_id)
    if planeta:
        # Si el jefe ya esta en las tablas de este objeto con mas probabilidad (el
        # Raptor con Sensores neuronales al 50 %), manda la tabla; si esta con menos
        # (Sargas Ruk con Celula orokin al 2.58 %, aparte del recurso del planeta),
        # la fila del recurso del planeta sustituye a esa.
        for j in planeta["jefes"]:
            reales = [
                f for f in filas
                if f["tipo"] == "enemigo" and RE_SUFIJO.sub("", f["origen_texto"] or "").strip() == j["origen_texto"]
            ]
            if any(float(f["probabilidad"] or 0) >= j["probabilidad"] for f in reales):
                continue
            filas = [f for f in filas if f not in reales] + [j]
    for f in filas:
        if f["tipo"] == "otro":
            rotacion = RE_ROTACION.search(f["origen_texto"] or "")
            if rotacion and not f["rotacion"]:
                f["rotacion"] = rotacion.group(1).upper()
        _puntuar(f)
    vistas: set[tuple] = set()
    salida: list[dict] = []
    # Primero lo tipado, para que 'otro' solo entre si no repite nada; y dentro, lo
    # mejor primero: las variantes de un jefe (Raptor y Raptor Mt, ambos en Naamah)
    # son el mismo sitio y tiene que quedarse la que mas suelta, no la primera.
    for f in sorted(filas, key=lambda f: (f["tipo"] == "otro", eficiencia.clave_orden(f), -f["puntuacion"])):
        # "Eidolon Hydrolyst (Special)" y "Eidolon Hydrolyst" son el mismo sitio.
        sitio = RE_SUFIJO.sub("", f["donde"]).strip().lower()
        clave = (sitio, (f["rotacion"] or "").upper(), f.get("etapa") or "")
        if clave in vistas:
            continue
        vistas.add(clave)
        salida.append(f)
    salida.sort(
        key=lambda f: (
            f["grado"],
            eficiencia.clave_orden(f),
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
    eficiencia.estimar(f)


# Palabras que pueden acompanar a los planetas en "Ubicacion: Ceres, Saturno y Deimos"
# o "Misiones en el Vacio" sin que deje de ser una lista de planetas.
_RELLENO_UBICACION = {"y", "e", "o", "el", "la", "los", "las", "de", "del", "en", "misiones", "mision"}
RE_UBICACION = re.compile(r"Ubicaci[o\u00f3]n\s*:\s*(.+)", re.IGNORECASE)
MISIONES_RAPIDAS = ("Capture", "Exterminate", "Extermination", "Sabotage", "Rescue")


def planetas_de_descripcion(con: sqlite3.Connection, descripcion: str | None) -> list[str]:
    """Planetas (nombre en ingles) de la linea "Ubicacion: ..." de un recurso.

    Solo vale si la linea es una lista de planetas: "Ubicacion: Madrigueras de kubrow
    en la Tierra" no convierte al huevo en recurso de planeta.
    """
    m = RE_UBICACION.search(descripcion or "")
    if not m:
        return []
    texto = normalizar(m.group(1).rstrip("."))
    planetas = _filas(con, "SELECT en, es FROM glosario WHERE dominio = 'planeta'")
    encontrados: list[tuple[int, str]] = []
    for p in planetas:
        for candidato in {p["es"], p["en"]}:
            clave = normalizar(candidato)
            hit = re.search(rf"\b{re.escape(clave)}\b", texto)
            if hit:
                encontrados.append((hit.start(), p["en"]))
                texto = texto.replace(clave, " " * len(clave))
                break
    if not encontrados:
        return []
    if any(palabra not in _RELLENO_UBICACION for palabra in texto.split()):
        return []
    vistos: list[str] = []
    for _, en in sorted(encontrados):
        if en not in vistos:
            vistos.append(en)
    return vistos


def recurso_de_planeta(con: sqlite3.Connection, item_id: int) -> dict | None:
    """Si el objeto cae en cualquier mision de ciertos planetas, donde farmearlo.

    Claves: `planetas` (filas con planeta_en/planeta_es), `nodos` (las misiones mas
    cortas de esos planetas, con 'donde', 'mision' y 'minutos') y `jefes` (fuentes
    de tipo 'enemigo' con `jefe`, una por jefe de esos planetas cuyo recurso raro es
    este objeto; la probabilidad sale de las tablas de WFCD, el planeta -> recurso
    raro de `eficiencia.RECURSO_RARO`).
    """
    fila = con.execute("SELECT descripcion_es, nombre_en FROM items WHERE id = ?", (item_id,)).fetchone()
    if not fila:
        return None
    planetas = planetas_de_descripcion(con, fila[0])
    nombre_en = fila[1]
    if not planetas:
        return None
    marcas = ",".join("?" * len(planetas))
    rapidas = ",".join("?" * len(MISIONES_RAPIDAS))
    nodos = _filas(
        con,
        f"""
        SELECT nombre_en AS nodo_en, nombre_es AS nodo_es, planeta_en, planeta_es, mision_en,
               nivel_min, nivel_max,
               (SELECT es FROM glosario WHERE dominio='mision' AND en = nodos.mision_en) AS mision_es
          FROM nodos WHERE planeta_en IN ({marcas}) AND mision_en IN ({rapidas})
        """,
        (*planetas, *MISIONES_RAPIDAS),
    )
    for n in nodos:
        n["donde"] = f"{nombre(n, 'nodo')}, {nombre(n, 'planeta')}"
        n["mision"] = glosa(n["mision_es"], n["mision_en"]) if n["mision_es"] else n["mision_en"]
        n["minutos"] = eficiencia.UNA_VEZ.get(n["mision_en"], eficiencia.DURACION_DESCONOCIDA)
    nodos.sort(key=lambda n: (n["minutos"], n["nivel_min"] if n["nivel_min"] is not None else 999))
    jefes: list[dict] = []
    for enemigo, (nodo_en, probabilidad) in eficiencia.JEFES.items():
        if not probabilidad:
            continue
        nodo = _nodo_por_nombre(con, nodo_en)
        if not nodo or nodo["planeta_en"] not in planetas:
            continue
        # Solo si este objeto es el recurso raro de ese planeta: es el que suelta el jefe.
        if eficiencia.RECURSO_RARO.get(nodo["planeta_en"]) != nombre_en:
            continue
        f = {
            "tipo": "enemigo", "origen_texto": enemigo, "rotacion": None, "etapa": None,
            "probabilidad": probabilidad, "rareza": None, "refinamiento": None,
            "probabilidad_enemigo": None, "standing": None,
            "datos_extra": json.dumps({"recurso_planeta": True}),
            "nodo_en": None, "nodo_es": None, "planeta_en": None, "planeta_es": None,
            "mision_en": None, "nivel_min": None, "nivel_max": None, "mision_es": None,
        }
        _decorar(con, [f])
        f["recurso_planeta"] = True
        jefes.append(f)
    return {
        "planetas": [{"planeta_en": p, "planeta_es": _glosa_planeta(con, p)} for p in planetas],
        "nodos": nodos[:4],
        "jefes": jefes,
    }


def _glosa_planeta(con: sqlite3.Connection, en: str) -> str:
    fila = con.execute("SELECT es FROM glosario WHERE dominio = 'planeta' AND en = ?", (en,)).fetchone()
    return fila[0] if fila else en


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
    filas = _filas(
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
    for f in filas:
        f["rareza"] = rareza_reliquia(refinamiento, f["probabilidad"], f["rareza"])
    return filas


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
    efectiva en el resto), `minutos_medios` (tiempo medio estimado hasta que caiga
    en el sitio elegido: el de la reliquia, sin contar abrirla) y `alternativas`
    (los otros sitios, sin el elegido).
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
            "minutos_medios": misiones[0]["minutos_medios"] if misiones else None,
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
        "minutos_medios": mejor["minutos_medios"],
        "alternativas": fuentes[1:5],
    }
