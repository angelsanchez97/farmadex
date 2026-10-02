"""Auditoria de los nombres del indice contra lo que publica Digital Extremes.

Baja el "Public Export" entero (todos los manifiestos con nombres, ~10 MB por idioma) a
una carpeta de cache y, objeto por objeto (por su uniqueName), mira si el nombre que
pinta el juego en ese idioma casa EXACTO con ese mismo objeto en el indice, que es lo
que le hace falta al lector de pantalla. Sirve para saber si WFCD se ha separado de DE
(un nombre recortado, un parche sin volcar) antes de que lo note nadie.

Clases:
  exacto     el nombre del juego da de lleno con su objeto.
  homonimo   da de lleno con OTRO objeto que el juego llama igual (no es un fallo de datos).
  parecido   casa con su objeto, pero no exacto: el nombre del indice no es el del juego.
  otro       casa con un objeto que no es. Grave.
  no_casa    no se reconoce.

Uso: python herramientas/auditar_nombres.py [indice.sqlite] [--cache carpeta] [--idiomas es,fr] [--detalle]
Sin indice usa el de FARMADEX_DATOS. Devuelve 1 si hay algun "otro" o "parecido".
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from farmadex.captura.ocr import Casador  # noqa: E402
from farmadex.config import RUTA_INDICE, USER_AGENT  # noqa: E402
from farmadex.datos import nombres_oficiales  # noqa: E402

# Lo que se lee en pantalla; los adornos (Skins, Glyphs...) no se auditan.
CATEGORIAS = ("Warframes", "Archwing", "Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee", "Sentinels",
              "SentinelWeapons", "Pets", "Mods", "Arcanes", "Relics", "Resources", "Misc", "Gear", "Fish")


def plano(texto: str) -> str:
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", texto.lower().replace("-", " "))).strip()


def bajar(cache: Path, idiomas) -> dict[str, dict[str, str]]:
    cliente = httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}, follow_redirects=True)

    def descargar(url: str, destino: Path) -> None:
        respuesta = cliente.get(url)
        if respuesta.status_code != 200:
            raise RuntimeError(f"{respuesta.status_code} en {url}")
        destino.write_bytes(respuesta.content)

    try:
        estado = nombres_oficiales.sincronizar(
            descargar, cache, idiomas=idiomas, manifiestos=nombres_oficiales.MANIFIESTOS_CON_NOMBRES,
            progreso=lambda texto, hechos, total: print(f"  {texto}", file=sys.stderr),
        )
    finally:
        cliente.close()
    sin = sorted(i for i, e in estado.items() if e == "sin_datos")
    if sin:
        print(f"Sin datos de DE para: {', '.join(sin)}", file=sys.stderr)
    return nombres_oficiales.cargar(cache, idiomas)


def auditar(con: sqlite3.Connection, oficiales: dict[str, dict[str, str]], detalle: bool = False) -> int:
    marcas = ", ".join("?" * len(CATEGORIAS))
    items = {u: (i, c, p) for i, u, c, p in con.execute(
        f"SELECT id, unique_name, categoria, padre_id FROM items WHERE categoria IN ({marcas})", CATEGORIAS)}
    por_id = {v[0]: u for u, v in items.items()}
    en_indice = {"es", "en"} | {i for (i,) in con.execute("SELECT DISTINCT idioma FROM items_nombres")}
    casador = Casador(con, CATEGORIAS)
    malos = 0
    print(f"{'idioma':7}{'objetos':>8}{'exacto':>8}{'%':>8}{'homon.':>8}{'parecido':>9}{'otro':>6}{'no casa':>8}")
    for idioma, nombres in oficiales.items():
        pares = [(u, n) for u, n in nombres.items() if u in items]
        if idioma not in en_indice:
            print(f"{idioma:7}{len(pares):8}   el indice no tiene este idioma")
            continue
        casador.precasar([n for _, n in pares], 80)
        cuenta: Counter = Counter()
        ejemplos = defaultdict(list)
        for unico, nombre in pares:
            iid, etiqueta, puntos = casador.casar(nombre, 80)
            if iid is None:
                clase = "no_casa"
            elif iid == items[unico][0]:
                clase = "exacto" if puntos >= 100 else "parecido"
            elif puntos >= 100 and any(plano(o.get(por_id.get(iid, ""), "")) == plano(nombre)
                                       for o in oficiales.values()):
                clase = "homonimo"
            else:
                clase = "otro"
            cuenta[clase] += 1
            if clase not in ("exacto", "homonimo"):
                ejemplos[clase].append(f"{nombre!r} -> {etiqueta!r} ({puntos:.0f}) [{unico.rsplit('/', 1)[-1]}]")
        total = len(pares)
        print(f"{idioma:7}{total:8}{cuenta['exacto']:8}{100 * cuenta['exacto'] / max(total, 1):8.2f}"
              f"{cuenta['homonimo']:8}{cuenta['parecido']:9}{cuenta['otro']:6}{cuenta['no_casa']:8}")
        malos += cuenta["parecido"] + cuenta["otro"]
        for clase, lista in ejemplos.items():
            for linea in lista if detalle else lista[:5]:
                print(f"        {clase}: {linea}")
    return malos


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("indice", nargs="?", default=str(RUTA_INDICE))
    parser.add_argument("--cache", default=str(Path(tempfile.gettempdir()) / "farmadex-public-export"))
    parser.add_argument("--idiomas", default=",".join(nombres_oficiales.IDIOMAS))
    parser.add_argument("--detalle", action="store_true")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    idiomas = tuple(i for i in args.idiomas.split(",") if i)
    oficiales = bajar(Path(args.cache), idiomas)
    con = sqlite3.connect(f"file:{Path(args.indice).as_posix()}?mode=ro", uri=True)
    try:
        return 1 if auditar(con, oficiales, args.detalle) else 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
