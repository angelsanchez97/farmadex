"""Comprobacion de aceptacion de la fase 1, sin interfaz.

Descarga los datos, construye el indice y busca un par de cosas conocidas.
Uso: python herramientas/comprobar_fase1.py [--forzar]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmadex.datos import indice, items  # noqa: E402

_ultimo = ""


def progreso(texto: str, hechos: int, total: int) -> None:
    global _ultimo
    if texto != _ultimo:
        print(f"  {texto}", flush=True)
        _ultimo = texto


def main() -> int:
    resumen = indice.construir(progreso=progreso, forzar="--forzar" in sys.argv)
    print("RESUMEN:", resumen)

    con = indice.conectar()
    fallos = []
    # (consulta, tipo de fuente que debe tener el primero, categoria que debe tener)
    for consulta, esperado, categoria in (
        ("sistemas ash prime", "reliquia", "Warframes"),
        ("ash prime systems", "reliquia", "Warframes"),
        ("neurodos", "mision", "Resources"),
        ("crioptica", "mision", "Resources"),
        ("nitain", None, "Resources"),
        ("celula orokin", "mision", "Resources"),
        ("argon", "mision", "Resources"),
        ("axi a7", None, "Relics"),
        ("serracion", None, "Mods"),
    ):
        resultados = indice.buscar(con, consulta, limite=5)
        if not resultados:
            fallos.append(f"sin resultados para '{consulta}'")
            continue
        primero = resultados[0]
        etiqueta = f"{primero['padre_es'] or primero['padre_en'] or ''} " \
                   f"{primero['nombre_es'] or primero['nombre_en']}".strip()
        datos = items.ficha(con, primero["item_id"])
        tipos = sorted({f["tipo"] for f in datos["fuentes"]})
        print(f"'{consulta}' -> {etiqueta} [{primero['categoria']}] fuentes={tipos}")
        if esperado and esperado not in tipos:
            fallos.append(f"'{consulta}' sin fuentes de tipo {esperado}")
        if primero["categoria"] != categoria or (
            categoria == "Resources" and primero.get("padre_id") is not None
        ):
            fallos.append(f"'{consulta}' -> {etiqueta} no es un {categoria} suelto")

    total_items, total_fuentes, total_reliquias, total_nodos = con.execute(
        "SELECT (SELECT COUNT(*) FROM items), (SELECT COUNT(*) FROM fuentes),"
        " (SELECT COUNT(*) FROM items WHERE categoria='Relics'), (SELECT COUNT(*) FROM nodos)"
    ).fetchone()
    print(
        f"items={total_items} fuentes={total_fuentes} reliquias={total_reliquias} "
        f"nodos={total_nodos}"
    )
    sin_enlazar = con.execute(
        "SELECT COUNT(*) FROM fuentes WHERE tipo='reliquia' AND origen_id IS NULL"
    ).fetchone()[0]
    print(f"fuentes de reliquia sin enlazar: {sin_enlazar}")

    if fallos:
        print("FALLOS:", "; ".join(fallos))
        return 1
    print("FASE 1 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
