"""Lo mas nuevo del juego: los objetos de la ultima actualizacion, segun WFCD.

WFCD trae por objeto `releaseDate` y `introduced` ({name: "Update 44.0", date:
"2026-09-23"}); el indice los guarda en items.fecha_salida y items.actualizacion
(esquema 12). "La ultima actualizacion" es la del objeto con la fecha mas reciente, y
con ella van todos los objetos de ese mismo numero: "Update 44.0" y sus "Hotfix 44.0.x",
que a veces sacan un prime unos dias despues.

Un indice de antes del esquema 12 no tiene esas columnas: aqui se tolera y se devuelve
None, y la interfaz dice que faltan los datos en vez de fallar.
"""

from __future__ import annotations

import re
import sqlite3

from ..idiomas import t

# Filtro (consultas.intencion_novedad) -> condicion SQL sobre items. Solo objetos de
# verdad (sin padre): las piezas no traen fecha.
ARMAS = ("Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee")
FILTROS = {
    "todo": "1 = 1",
    "warframe": "categoria = 'Warframes'",
    "warframe prime": "categoria = 'Warframes' AND es_prime = 1",
    "arma": "categoria IN ({})".format(", ".join(f"'{c}'" for c in ARMAS)),
    "arma prime": "categoria IN ({}) AND es_prime = 1".format(", ".join(f"'{c}'" for c in ARMAS)),
    # Los mods "Primed" tambien llevan es_prime (el nombre tiene "Prime"), pero no son
    # "un prime": solo equipo (warframes, armas, companeros, archwing).
    "prime": "es_prime = 1 AND categoria IN ('Warframes', {}, 'Sentinels', 'SentinelWeapons', "
             "'Pets', 'Archwing')".format(", ".join(f"'{c}'" for c in ARMAS)),
}
_NUMERO = re.compile(r"\d+(?:\.\d+)?")


def numero(actualizacion: str | None) -> str:
    """'44.0' de 'Update 44.0' o de 'Hotfix 44.0.3'; vacio si no lleva numero."""
    encontrado = _NUMERO.search(actualizacion or "")
    return encontrado.group(0) if encontrado else ""


def _de_la_misma(actualizacion: str | None, referencia: str) -> bool:
    """Si 'Hotfix 44.0.3' es de la 44.0 (y 'Update 44.1' no)."""
    otro = re.search(r"\d+(?:\.\d+)*", actualizacion or "")
    if not otro:
        return False
    return otro.group(0) == referencia or otro.group(0).startswith(referencia + ".")


def ultima(con: sqlite3.Connection | None, filtro: str = "todo") -> dict | None:
    """La ultima actualizacion con objetos de ese filtro, y esos objetos.

    {'actualizacion': 'Update 44.0', 'numero': '44.0', 'fecha': '2026-09-23',
     'items': [{item_id, nombre_en, nombre_es, categoria, tipo, es_prime, imagen,
                padre_en, padre_es, fecha_salida, actualizacion}, ...]}
    None si no hay datos de fecha (indice viejo o sin nada de ese filtro).
    """
    if con is None:
        return None
    condicion = FILTROS.get(filtro, FILTROS["todo"])
    try:
        filas = con.execute(
            f"""
            SELECT id, nombre_en, nombre_es, categoria, tipo, es_prime, imagen, fecha_salida, actualizacion
              FROM items
             WHERE padre_id IS NULL AND fecha_salida IS NOT NULL AND {condicion}
             ORDER BY fecha_salida DESC, nombre_en
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return None  # indice de antes del esquema 12: sin columnas de fecha
    if not filas:
        return None
    columnas = ("item_id", "nombre_en", "nombre_es", "categoria", "tipo", "es_prime", "imagen",
                "fecha_salida", "actualizacion")
    todas = [dict(zip(columnas, f), padre_en=None, padre_es=None) for f in filas]
    mas_nueva = todas[0]
    referencia = numero(mas_nueva["actualizacion"])
    if referencia:
        grupo = [f for f in todas if _de_la_misma(f["actualizacion"], referencia)]
        # Si una actualizacion vieja se quedo sin numero reconocible, al menos la mas nueva.
        grupo = grupo or [mas_nueva]
    else:
        grupo = [f for f in todas if f["actualizacion"] == mas_nueva["actualizacion"]
                 and f["actualizacion"]] or [f for f in todas if f["fecha_salida"] == mas_nueva["fecha_salida"]]
    # Delante lo que se pidio: warframes, luego armas, luego el resto; los primes detras.
    orden = {"Warframes": 0, **dict.fromkeys(ARMAS, 1)}
    grupo.sort(key=lambda f: (orden.get(f["categoria"], 2), f["es_prime"], f["nombre_en"]))
    return {
        "actualizacion": mas_nueva["actualizacion"] or "",
        "numero": referencia,
        "fecha": min(f["fecha_salida"] for f in grupo),
        "items": grupo,
    }


def titulo(datos: dict) -> str:
    """'Actualizacion 44.0' en el idioma de la interfaz (o el nombre tal cual si no hay numero)."""
    if datos.get("numero"):
        return t("Actualizacion {n}", n=datos["numero"])
    return datos.get("actualizacion") or ""


def fecha_legible(fecha: str | None) -> str:
    """'2026-09-23' -> '23/09/2026' (o el formato del idioma de la interfaz)."""
    partes = (fecha or "").split("-")
    if len(partes) != 3:
        return fecha or ""
    anio, mes, dia = partes
    return t("{dia}/{mes}/{anio}", dia=dia, mes=mes, anio=anio)
