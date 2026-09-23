"""Batida del casado de recompensas: cada objeto que sale de reliquias, con erratas de OCR.

Genera el nombre tal como lo pinta el juego (castellano e ingles) y variantes con
los fallos tipicos del OCR (una letra perdida, dos palabras pegadas, letras que se
confunden), las pasa por el MISMO casador escalonado que usa el programa y cuenta:

- MAL: sale otro objeto. Es lo grave: una etiqueta segura y falsa.
- NADA: no se reconoce ("Sin identificar"). Molesta, pero no engana.

Uso: python herramientas/auditar_casado.py [ruta/indice.sqlite] [--detalle]
Sin ruta usa el indice de FARMADEX_DATOS (o el del usuario, en solo lectura).
"""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmadex.captura import recompensas_rapidas as rapidas  # noqa: E402
from farmadex.captura.ocr import Casador  # noqa: E402

CONFUSIONES = [("i", "l"), ("l", "i"), ("rn", "m"), ("m", "rn"), ("o", "0"), ("u", "v"), ("e", "c"), ("n", "h")]


def formas(con: sqlite3.Connection, iid: int) -> list[str]:
    """Nombres como los escribe el juego en pantalla, en castellano e ingles."""
    fila = con.execute(
        "SELECT i.nombre_en, i.nombre_es, p.nombre_en, p.nombre_es FROM items i "
        "LEFT JOIN items p ON p.id = i.padre_id WHERE i.id = ?", (iid,)
    ).fetchone()
    en, es, pen, pes = fila
    es = es or en
    pes = pes or pen
    salida = []
    if pen:
        if en.lower() == "blueprint":
            salida += [f"Plano De {pes}", f"{pen} Blueprint"]
        else:
            comp_en = en.removesuffix(" Blueprint")
            comp_es = es.removesuffix(" Plano").removeprefix("Plano De ").removeprefix("Plano de ")
            salida += [f"{comp_es} De {pes}", f"{pen} {comp_en}"]
            if en.endswith("Blueprint") or con.execute(
                "SELECT categoria FROM items WHERE id = (SELECT padre_id FROM items WHERE id = ?)", (iid,)
            ).fetchone()[0] in ("Warframes", "Archwing"):
                salida += [f"Plano De {comp_es} De {pes}", f"{pen} {comp_en} Blueprint"]
    else:
        salida.append(en)
        if es.endswith(" Plano"):
            salida.append("Plano De " + es.removesuffix(" Plano"))
        elif es != en:
            salida.append(es)
    return [" ".join(s.title().split()) for s in salida]


def erratas(texto: str) -> list[tuple[str, str]]:
    salida = [("exacto", texto), ("mayusculas", texto.upper())]
    for i, c in enumerate(texto):
        if c != " ":
            salida.append(("sin_letra", texto[:i] + texto[i + 1:]))
    for i, c in enumerate(texto):
        if c == " ":
            salida.append(("pegado", texto[:i] + texto[i + 1:]))
    bajo = texto.lower()
    for a, b in CONFUSIONES:
        pos = bajo.find(a)
        while pos != -1:
            salida.append((f"{a}>{b}", texto[:pos] + b + texto[pos + len(a):]))
            pos = bajo.find(a, pos + 1)
    return salida


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    detalle = "--detalle" in sys.argv
    if args:
        ruta = args[0]
    else:
        from farmadex.datos import indice

        ruta = str(indice.RUTA_INDICE) if hasattr(indice, "RUTA_INDICE") else ""
    con = sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro", uri=True)
    casador = Casador(con)
    ids = rapidas.ids_reliquias(con)
    escalonado = rapidas.CasadorEscalonado(
        rapidas.catalogo_de_piezas(casador, con), casador.restringido(ids), None
    )
    nombres = dict(con.execute("SELECT id, nombre_en FROM items"))
    nombres.update({iid: etiqueta for iid, etiqueta in casador.candidatos.values()})
    totales = Counter()
    por_tipo = defaultdict(Counter)
    malos = defaultdict(list)
    nadas = defaultdict(list)
    for iid in sorted(ids):
        for forma in formas(con, iid):
            for tipo, texto in erratas(forma):
                sale = escalonado.casar(texto)[0]
                clase = "bien" if sale == iid else ("nada" if sale is None else "mal")
                totales[clase] += 1
                por_tipo[tipo.split(">")[0] if ">" not in tipo else "confusion"][clase] += 1
                if clase == "mal":
                    malos[iid].append((texto, nombres.get(sale)))
                elif clase == "nada" and tipo in ("exacto", "mayusculas", "pegado"):
                    nadas[iid].append(texto)
    total = sum(totales.values())
    print(f"{len(ids)} objetos, {total} lecturas: " + ", ".join(
        f"{k} {v} ({100 * v / total:.2f} %)" for k, v in totales.most_common()))
    for tipo, c in sorted(por_tipo.items()):
        n = sum(c.values())
        print(f"  {tipo:12} mal {c['mal']:5}  nada {c['nada']:5}  de {n}")
    print(f"\nObjetos con alguna lectura MAL: {len(malos)}")
    for iid, casos in sorted(malos.items(), key=lambda x: -len(x[1]))[: None if detalle else 40]:
        ejemplos = "; ".join(f"{t!r}->{s}" for t, s in casos[:3])
        print(f"  {nombres[iid]} ({len(casos)}): {ejemplos}")
    print(f"\nObjetos que no se reconocen ni bien escritos / pegados: {len(nadas)}")
    for iid, casos in sorted(nadas.items(), key=lambda x: -len(x[1]))[: None if detalle else 40]:
        print(f"  {nombres[iid]}: {casos[:3]}")


if __name__ == "__main__":
    main()
