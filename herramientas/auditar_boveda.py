"""Comprueba que todo Farmadex dice lo mismo sobre la boveda.

La boveda se ve en la ficha, en las tarjetas de reliquia, en Primes y en el panel de
recompensas, y cada sitio la leia de un dato distinto (reliquia, pieza, prime entero).
El 2026-09-24 la Lith S19 salia "en boveda" recien salida. Reglas:
  1. una reliquia esta en boveda si no sale en ninguna mision (salvo las Requiem);
  2. una pieza prime, si ninguna reliquia fuera de boveda la da;
  3. un prime, si todas sus piezas lo estan;
  4. la ficha de cada pieza (sus reliquias) dice lo mismo que la pieza.

Uso: python herramientas/auditar_boveda.py [ruta/indice.sqlite]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmadex.datos import relaciones, ruta_prime  # noqa: E402


def incoherencias(con: sqlite3.Connection) -> list[tuple]:
    fallos = []
    for n, v, nf in con.execute(
        "SELECT nombre_en, vaulted, (SELECT COUNT(*) FROM fuentes f WHERE f.item_id = i.id) "
        "FROM items i WHERE categoria = 'Relics' AND nombre_en NOT LIKE 'Requiem%'"
    ):
        if bool(v) != (nf == 0):
            fallos.append(("reliquia", n, v, nf))
    vaulted = dict(con.execute("SELECT id, vaulted FROM items"))
    objetos, _ = ruta_prime.catalogo(con)
    for o in objetos:
        if vaulted[o["id"]] is not None and bool(vaulted[o["id"]]) != o["en_boveda"]:
            fallos.append(("prime", o["nombre_en"], vaulted[o["id"]], o["en_boveda"]))
        for p in o["piezas"]:
            nombre = f"{o['nombre_en']} {p['nombre_en']}"
            if bool(vaulted[p["id"]]) != p["en_boveda"]:
                fallos.append(("pieza", nombre, vaulted[p["id"]], p["en_boveda"]))
            disponible = any(not r["vaulted"] for r in relaciones.reliquias_de(con, p["id"]))
            if disponible == bool(vaulted[p["id"]]):
                fallos.append(("ficha", nombre, vaulted[p["id"]], disponible))
    return fallos


def main() -> None:
    from farmadex.datos import indice

    ruta = sys.argv[1] if len(sys.argv) > 1 else str(indice.RUTA_INDICE)
    con = sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro", uri=True)
    fallos = incoherencias(con)
    print(f"Incoherencias de boveda: {len(fallos)}")
    for f in fallos[:40]:
        print("  ", f)


if __name__ == "__main__":
    main()
