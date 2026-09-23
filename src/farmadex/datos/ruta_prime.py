"""Cuanto se tarda en conseguir una pieza prime, contando reliquia, mision y fisura.

`eficiencia.py` dice cuanto se tarda en que caiga una reliquia en una mision. Pero
lo que el jugador quiere es la PIEZA, y la reliquia hay que abrirla, a veces varias
veces. El modelo, para una mision (o rotacion) concreta a la que se va a farmear:

    cada intento en la mision cuesta m minutos (eficiencia.minutos_por_intento) y
    suelta la reliquia r con probabilidad q_r (varias reliquias utiles a la vez en
    la misma rotacion se suman: es "alguna de estas reliquias", como en la web);
    cada reliquia util que cae se abre en una fisura de F minutos
    (eficiencia.FISURA) y da la pieza con probabilidad P_r por fisura.

    minutos hasta la pieza = (m + F * sum(q_r)) / sum(q_r * P_r)

que con una sola reliquia es exactamente "reliquias que hay que abrir de media
(1/P) x (tiempo de conseguir una reliquia, m/q, + una fisura, F)". Es un proceso de
renovacion: el numerador es lo que cuesta de media un intento y el denominador la
probabilidad de que ese intento acabe dando la pieza.

P_r depende del refinamiento y de como se abre:

- En solitario, P = p (la probabilidad de la pieza en esa reliquia y refinamiento).
- En escuadra de 4 compartiendo reliquia ("radshare"): los cuatro llevan la misma
  reliquia con el mismo refinamiento y cada uno elige entre las cuatro recompensas
  que salen. Cada fisura te cuesta UNA reliquia tuya y te da cuatro tiradas, asi
  que P = 1 - (1 - p)^4. Supuesto: los otros tres ponen su propia reliquia (la han
  farmeado ellos) y te dejan elegir la pieza si sale en la suya.

Con varias piezas marcadas, p es la suma de las probabilidades de todas las que
faltan en esa reliquia (las recompensas de una reliquia son excluyentes), y el
tiempo es el de conseguir la SIGUIENTE pieza cualquiera. Se eligio asi porque es
lo que el jugador vive: farmea, le cae algo, lo desmarca y el orden se recalcula.
El tiempo de completarlo todo es un problema de coleccionista que depende de
cuando cambies de mision; sumar tiempos sueltos contaria dos veces las rotaciones
que dan reliquias de varias piezas.

Lo que no entra en el tiempo, a proposito:
- Refinar cuesta Trazas del Vacio (100 para Radiante) que salen de las propias
  fisuras; convertirlas en minutos exigiria inventar un ritmo de trazas.
- Las reliquias en boveda no caen en ninguna mision: se listan aparte y no
  entran en el orden (solo por intercambio, Baro Ki'Teer o Prime Resurgence).
"""

from __future__ import annotations

import sqlite3

from . import eficiencia, relaciones

REFINAMIENTO_POR_DEFECTO = "Radiant"
ESCUADRA_POR_DEFECTO = 4  # como wf.xuerian.net: Radiante en escuadra de 4
ESCUADRAS = (1, 4)
CLAVE_REFINAMIENTO = "primes_refinamiento"
CLAVE_ESCUADRA = "primes_escuadra"


def preferencias() -> tuple[str, int]:
    """(refinamiento, escuadra) que el usuario eligio en la pestana Primes."""
    try:
        from ..config import cargar

        config = cargar()
    except Exception:  # noqa: BLE001 - sin configuracion legible valen los de por defecto
        config = {}
    refinamiento = config.get(CLAVE_REFINAMIENTO) or REFINAMIENTO_POR_DEFECTO
    if refinamiento not in relaciones.REFINAMIENTOS:
        refinamiento = REFINAMIENTO_POR_DEFECTO
    try:
        escuadra = int(config.get(CLAVE_ESCUADRA) or ESCUADRA_POR_DEFECTO)
    except (TypeError, ValueError):
        escuadra = ESCUADRA_POR_DEFECTO
    return refinamiento, escuadra if escuadra in ESCUADRAS else ESCUADRA_POR_DEFECTO


def probabilidad_por_fisura(probabilidad: float, escuadra: int = 1) -> float:
    """Probabilidad (0..1) de llevarte la pieza en una fisura; `probabilidad` en %."""
    p = max(0.0, min(float(probabilidad or 0), 100.0)) / 100
    return 1 - (1 - p) ** max(1, int(escuadra))


def reliquias_necesarias(probabilidad: float, escuadra: int = 1) -> float | None:
    """Reliquias tuyas que hay que abrir de media hasta que salga la pieza."""
    por_fisura = probabilidad_por_fisura(probabilidad, escuadra)
    return 1 / por_fisura if por_fisura > 0 else None


def minutos_pieza(
    minutos_intento: float, probabilidades: list[tuple[float, float]], escuadra: int = 1,
    fisura: float | None = None,
) -> float | None:
    """Minutos medios hasta la pieza farmeando en un sitio.

    `probabilidades` son pares (q, p) en %: probabilidad de que el intento suelte
    cada reliquia util y probabilidad de lo marcado dentro de esa reliquia. Sin
    `fisura`, la de eficiencia al ritmo de juego de Ajustes.
    """
    if fisura is None:
        fisura = eficiencia.minutos_fisura()
    cae = sum(min(q, 100.0) / 100 for q, _ in probabilidades)
    acierta = sum(min(q, 100.0) / 100 * probabilidad_por_fisura(p, escuadra) for q, p in probabilidades)
    if acierta <= 0:
        return None
    return (minutos_intento + fisura * min(cae, 1.0)) / acierta


def reliquias_para(con: sqlite3.Connection, item_ids, refinamiento: str = REFINAMIENTO_POR_DEFECTO) -> list[dict]:
    """Las reliquias que contienen alguna de esas piezas, con su probabilidad en el refinamiento.

    Cada fila: reliquia_id, nombre_en, nombre_es, vaulted, `piezas` (item_id -> %),
    `probabilidad` (la de sacar alguna de ellas, suma en %) y `probabilidades` por
    refinamiento de ese mismo conjunto. Primero lo que se puede farmear, y dentro,
    lo mas probable.
    """
    ids = sorted({int(i) for i in item_ids})
    if not ids:
        return []
    marcas = ",".join("?" * len(ids))
    anterior = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        filas = con.execute(
            f"""
            SELECT rr.reliquia_id, rr.refinamiento, rr.item_id, rr.probabilidad,
                   r.nombre_en, r.nombre_es, r.vaulted
              FROM reliquia_recompensas rr JOIN items r ON r.id = rr.reliquia_id
             WHERE rr.item_id IN ({marcas})
            """,
            ids,
        ).fetchall()
    finally:
        con.row_factory = anterior
    reliquias: dict[int, dict] = {}
    for f in filas:
        r = reliquias.setdefault(
            f["reliquia_id"],
            {
                "reliquia_id": f["reliquia_id"],
                "nombre_en": f["nombre_en"],
                "nombre_es": f["nombre_es"],
                "vaulted": bool(f["vaulted"]),
                "piezas": {},
                "probabilidades": {},
            },
        )
        prob = float(f["probabilidad"] or 0)
        r["probabilidades"][f["refinamiento"]] = round(r["probabilidades"].get(f["refinamiento"], 0) + prob, 4)
        if f["refinamiento"] == refinamiento:
            r["piezas"][f["item_id"]] = prob
    salida = []
    for r in reliquias.values():
        r["probabilidad"] = round(sum(r["piezas"].values()), 4)
        if r["probabilidad"] > 0:
            salida.append(r)
    salida.sort(key=lambda r: (r["vaulted"], -r["probabilidad"], r["nombre_en"]))
    return salida


def _misiones(con: sqlite3.Connection, reliquia_id: int, cache: dict | None) -> list[dict]:
    # Las filas llevan `minutos_intento` al ritmo de juego del momento: si el ritmo
    # cambia en Ajustes, lo guardado ya no vale.
    if cache is not None and cache.get("_ritmo") != eficiencia.ritmo():
        cache.clear()
        cache["_ritmo"] = eficiencia.ritmo()
    if cache is not None and reliquia_id in cache:
        return cache[reliquia_id]
    filas = relaciones.misiones_de(con, reliquia_id)
    if cache is not None:
        cache[reliquia_id] = filas
    return filas


def misiones_para(
    con: sqlite3.Connection, reliquias: list[dict], escuadra: int = ESCUADRA_POR_DEFECTO,
    fisura: float | None = None, cache: dict | None = None,
) -> list[dict]:
    """Los sitios donde farmear esas reliquias, de menos a mas tiempo hasta la pieza.

    Las reliquias en boveda no entran. Cada fila es un sitio (nodo y rotacion, o
    etapa de contrato) con lo de `relaciones.misiones_de` mas: `probabilidad` (en %,
    la de que el intento suelte alguna de las reliquias utiles), `reliquias` (las
    que caen ahi, cada una con `probabilidad_mision` y su `probabilidad` de pieza,
    de la que mas aporta a la que menos), `minutos` (hasta la pieza, con fisuras),
    `minutos_reliquia` (hasta que cae una reliquia util) y `sitios` (los nodos con
    exactamente la misma tabla, rotacion y duracion: Io, Paimon, Helena... son la
    misma Defensa de nivel 18-23 y se ensenan como una sola fila).
    """
    if fisura is None:
        fisura = eficiencia.minutos_fisura()  # al ritmo de juego de Ajustes
    utiles = {r["reliquia_id"]: r for r in reliquias if not r["vaulted"] and r["probabilidad"] > 0}
    fuentes: dict[tuple, dict] = {}
    for reliquia_id in utiles:
        for f in _misiones(con, reliquia_id, cache):
            if f.get("minutos_intento") is None or not f.get("probabilidad"):
                continue
            clave = (f["tipo"], f["origen_texto"], (f.get("rotacion") or "").upper(), f.get("etapa") or "")
            entrada = fuentes.setdefault(clave, {"fila": f, "reliquias": {}})
            q = min(float(f["probabilidad"]), 100.0)
            entrada["reliquias"][reliquia_id] = max(entrada["reliquias"].get(reliquia_id, 0.0), q)

    grupos: dict[tuple, dict] = {}
    for entrada in fuentes.values():
        f = entrada["fila"]
        pares = [(q, utiles[rid]["probabilidad"]) for rid, q in entrada["reliquias"].items()]
        minutos = minutos_pieza(f["minutos_intento"], pares, escuadra, fisura)
        if minutos is None:
            continue
        firma = (
            f["tipo"], f.get("modo") or "", (f.get("rotacion") or "").upper(), f.get("etapa") or "",
            round(f["minutos_intento"], 3), tuple(sorted(entrada["reliquias"].items())),
        )
        grupo = grupos.get(firma)
        if grupo is not None:
            grupo["_filas"].append(f)
            continue
        cae = min(sum(q for q, _ in pares), 100.0)
        lista = sorted(
            (
                {
                    "reliquia_id": rid,
                    "nombre_en": utiles[rid]["nombre_en"],
                    "nombre_es": utiles[rid]["nombre_es"],
                    "probabilidad": utiles[rid]["probabilidad"],
                    "piezas": utiles[rid]["piezas"],
                    "probabilidad_mision": q,
                    "_aporta": q * probabilidad_por_fisura(utiles[rid]["probabilidad"], escuadra),
                }
                for rid, q in entrada["reliquias"].items()
            ),
            key=lambda r: (-r["_aporta"], r["nombre_en"]),
        )
        for r in lista:
            del r["_aporta"]
        grupos[firma] = {
            "_filas": [f],
            "tipo": f["tipo"],
            "modo": f.get("modo") or "",
            "mision": f.get("mision") or "",
            "rotacion": f.get("rotacion"),
            "etapa": f.get("etapa"),
            "minutos_intento": f["minutos_intento"],
            "probabilidad": round(cae, 2),
            "reliquias": lista,
            "minutos": round(minutos, 1),
            "minutos_reliquia": round(f["minutos_intento"] / (cae / 100), 1) if cae > 0 else None,
        }
    salida = []
    for grupo in grupos.values():
        filas = sorted(
            grupo.pop("_filas"),
            key=lambda f: (f["nivel_min"] if f.get("nivel_min") is not None else 999, f.get("donde") or ""),
        )
        primera = filas[0]
        grupo.update(
            {
                "donde": primera.get("donde") or "",
                "origen_texto": primera.get("origen_texto"),
                "nodo_en": primera.get("nodo_en"),
                "nodo_es": primera.get("nodo_es"),
                "planeta_en": primera.get("planeta_en"),
                "planeta_es": primera.get("planeta_es"),
                "nivel_min": primera.get("nivel_min"),
                "nivel_max": primera.get("nivel_max"),
                "sitios": [f.get("donde") or "" for f in filas],
            }
        )
        salida.append(grupo)
    salida.sort(
        key=lambda g: (
            g["minutos"],
            -g["probabilidad"],
            g["nivel_min"] if g["nivel_min"] is not None else 999,
            g["donde"],
        )
    )
    return salida


def ruta_pieza(
    con: sqlite3.Connection, item_ids, refinamiento: str | None = None, escuadra: int | None = None,
    cache: dict | None = None,
) -> dict | None:
    """La mejor ruta completa hasta una pieza (o la siguiente de varias).

    Claves: `refinamiento`, `escuadra`, `reliquias` (todas, las de boveda al final),
    `mision` (el mejor sitio de `misiones_para`, None si no hay ninguno), `misiones`
    (los cinco mejores), `reliquia` (la que mas aporta en ese sitio o, sin sitio, la
    mejor que haya), `minutos` (hasta la pieza, None sin sitio), `solo_en_boveda`
    (todas sus reliquias estan en boveda) y `sin_mision` (hay reliquias fuera de
    boveda pero ninguna cae en una mision que se pueda estimar: Requiem, eventos).
    None si ninguna reliquia contiene nada de eso.
    """
    if isinstance(item_ids, int):
        item_ids = [item_ids]
    ref_config, esc_config = preferencias()
    refinamiento = refinamiento or ref_config
    escuadra = escuadra or esc_config
    reliquias = reliquias_para(con, item_ids, refinamiento)
    if not reliquias:
        return None
    disponibles = [r for r in reliquias if not r["vaulted"]]
    misiones = misiones_para(con, disponibles, escuadra, cache=cache) if disponibles else []
    mejor = misiones[0] if misiones else None
    if mejor:
        reliquia = next(r for r in reliquias if r["reliquia_id"] == mejor["reliquias"][0]["reliquia_id"])
    else:
        reliquia = (disponibles or reliquias)[0]
    return {
        "refinamiento": refinamiento,
        "escuadra": escuadra,
        "reliquias": reliquias,
        "reliquia": reliquia,
        "mision": mejor,
        "misiones": misiones[:5],
        "minutos": mejor["minutos"] if mejor else None,
        "solo_en_boveda": not disponibles,
        "sin_mision": bool(disponibles) and not misiones,
    }


def catalogo(con: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    """Lo que sale de reliquias, para la rejilla: (objetos prime con sus piezas, sueltos).

    Cada objeto: id, unique_name, nombre_en, nombre_es, categoria, `en_boveda` (todas
    sus piezas lo estan) y `piezas` (id, unique_name, nombre_en, nombre_es,
    item_count, en_boveda). Los sueltos (Forma, Kuva, mods de Requiem...) son piezas
    sin objeto padre. Solo entran piezas que salen de alguna reliquia.
    """
    anterior = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        piezas = [
            dict(f)
            for f in con.execute(
                """
                SELECT i.id, i.unique_name, i.nombre_en, i.nombre_es, i.item_count, i.padre_id,
                       MIN(COALESCE(r.vaulted, 0)) AS boveda
                  FROM reliquia_recompensas rr
                  JOIN items i ON i.id = rr.item_id
                  JOIN items r ON r.id = rr.reliquia_id
                 GROUP BY i.id
                """
            )
        ]
        padres_ids = sorted({p["padre_id"] for p in piezas if p["padre_id"]})
        padres: dict[int, dict] = {}
        for i in range(0, len(padres_ids), 500):
            trozo = padres_ids[i:i + 500]
            for f in con.execute(
                f"SELECT id, unique_name, nombre_en, nombre_es, categoria FROM items "
                f"WHERE id IN ({','.join('?' * len(trozo))})",
                trozo,
            ):
                padres[f["id"]] = {**dict(f), "piezas": []}
    finally:
        con.row_factory = anterior
    sueltos = []
    for p in piezas:
        p["en_boveda"] = bool(p.pop("boveda"))
        padre = padres.get(p["padre_id"]) if p["padre_id"] else None
        if padre is None:
            sueltos.append(p)
        else:
            padre["piezas"].append(p)
    objetos = []
    for o in padres.values():
        # El plano primero, luego el resto por nombre, como en el juego y en la web.
        o["piezas"].sort(key=lambda p: (not p["unique_name"].endswith("Blueprint"), p["nombre_en"]))
        o["en_boveda"] = all(p["en_boveda"] for p in o["piezas"])
        objetos.append(o)
    objetos.sort(key=lambda o: o["nombre_en"])
    sueltos.sort(key=lambda p: p["nombre_en"])
    return objetos, sueltos
