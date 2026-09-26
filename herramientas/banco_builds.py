"""Banco de pruebas del lector de la pantalla de mejoras (pestana Build).

Pinta pantallas sinteticas (tests/sintetico_builds.py) con mods reales del indice, en
ingles y castellano y a 720p, 1080p y 1440p, las pasa por el lector y cuenta:
mods reconocidos, mods inventados (los peores: casan con otro mod), el equipo de la
cabecera y el tiempo. Con `--capturas carpeta` lee tambien capturas reales con un
`verdad.json` al lado: {"fichero.png": {"equipo": "Excalibur", "mods": ["Vitality", ...]}}
(nombres en ingles del indice). Esas capturas no van en el repositorio.

Uso: .venv/Scripts/python.exe herramientas/banco_builds.py [--n 6] [--capturas carpeta] [--guardar carpeta]
Hace falta el indice real construido (la app lo crea la primera vez). No se toca: se
copia a una carpeta temporal con FARMADEX_DATOS.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def preparar_indice() -> None:
    """Copia el indice real a un temporal y apunta FARMADEX_DATOS ahi (antes de importar farmadex)."""
    if os.environ.get("FARMADEX_DATOS"):
        return
    real = Path(os.environ.get("LOCALAPPDATA", "")) / "Farmadex" / "db" / "indice.sqlite"
    if not real.exists():
        sys.exit("No hay indice real construido; abre la app una vez primero.")
    raiz = Path(tempfile.gettempdir()) / "farmadex_banco_builds"
    destino = raiz / "Farmadex" / "db" / "indice.sqlite"
    destino.parent.mkdir(parents=True, exist_ok=True)
    if not destino.exists() or destino.stat().st_size != real.stat().st_size:
        shutil.copy2(real, destino)
    os.environ["FARMADEX_DATOS"] = str(raiz)


preparar_indice()
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

import cv2  # noqa: E402

from farmadex.captura import builds as B  # noqa: E402
from farmadex.captura.ocr import MotorOCR  # noqa: E402
from farmadex.datos import indice  # noqa: E402
import sintetico_builds as SINT  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=6)
    parser.add_argument("--semilla", type=int, default=7)
    parser.add_argument("--capturas")
    parser.add_argument("--guardar")
    args = parser.parse_args()

    con = indice.conectar()
    indice.crear_esquema(con)  # un indice viejo puede no tener las tablas de idiomas
    casador = B.crear_casador(con)
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    motor = MotorOCR()
    guardar = Path(args.guardar) if args.guardar else None
    if guardar is not None:
        guardar.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.semilla)
    mods = [r[0] for r in con.execute(
        "SELECT DISTINCT nombre_en FROM items WHERE categoria='Mods' AND tipo='Warframe Mod' AND padre_id IS NULL"
    )]
    nombre_es = dict(con.execute("SELECT nombre_en, nombre_es FROM items WHERE categoria='Mods'"))
    frames = [r[0] for r in con.execute(
        "SELECT nombre_en FROM items WHERE categoria='Warframes' AND padre_id IS NULL AND tipo='Warframe'"
    )]

    def ids_de(nombres: list[str]) -> set[int]:
        salida = set()
        for n in nombres:
            fila = con.execute("SELECT id FROM items WHERE nombre_en=? AND categoria='Mods' ORDER BY id LIMIT 1", (n,)).fetchone()
            if fila:
                salida.add(fila[0])
        return salida

    total = ok = falsos = equipos_ok = 0
    tiempos = []
    print(f"== {args.n} pantallas sinteticas")
    for i in range(args.n):
        idioma = "en" if i % 2 == 0 else "es"
        equipo = rng.choice(frames)
        equipados = rng.sample(mods, 9)
        coleccion = rng.sample(mods, 16)
        traducir = (lambda n: nombre_es.get(n) or n) if idioma == "es" else (lambda n: n)
        ancho, alto = [(1920, 1080), (2560, 1440), (1280, 720)][i % 3]
        imagen = SINT.pintar_arsenal(equipo, [traducir(n) for n in equipados], [traducir(n) for n in coleccion],
                                     ancho=ancho, alto=alto, idioma=idioma, semilla=i, desenfoque=0.6 if i % 5 == 4 else 0)
        if guardar is not None:
            cv2.imwrite(str(guardar / f"arsenal_{i:02d}_{idioma}_{alto}p.png"), imagen)
        inicio = time.monotonic()
        build = B.leer_build(imagen, motor, casador, categorias)
        ms = (time.monotonic() - inicio) * 1000
        tiempos.append(ms)
        esperados = ids_de(equipados + coleccion)
        vistos = {r.item_id for r in build.equipados + build.coleccion}
        aciertos = len(esperados & vistos)
        inventados = [r for r in build.equipados + build.coleccion if r.item_id not in esperados]
        equipo_ok = build.equipo is not None and build.equipo.nombre.lower() in (equipo.lower(),)
        total += len(esperados)
        ok += aciertos
        falsos += len(inventados)
        equipos_ok += equipo_ok
        print(f"  {idioma} {ancho}x{alto} {ms:5.0f} ms  equipo={'OK' if equipo_ok else build.equipo.nombre if build.equipo else '-'}"
              f"  mods {aciertos}/{len(esperados)}  inventados {len(inventados)}  sin identificar {len(build.sin_identificar)}")
        for r in inventados:
            print(f"     INVENTADO: {r.texto_ocr!r} -> {r.nombre!r} ({r.puntuacion:.0f})")
    print(f"\n== Resumen sinteticas: mods {ok}/{total} ({100 * ok / max(1, total):.1f} %), inventados {falsos},"
          f" equipo {equipos_ok}/{args.n}, tiempo medio {sum(tiempos) / max(1, len(tiempos)):.0f} ms")

    if args.capturas:
        carpeta = Path(args.capturas)
        verdad = {}
        if (carpeta / "verdad.json").exists():
            verdad = json.load(open(carpeta / "verdad.json", encoding="utf-8"))
        print(f"\n== capturas reales de {carpeta}")
        for fichero in sorted(carpeta.iterdir()):
            if fichero.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            imagen = cv2.imread(str(fichero))
            if imagen is None:
                continue
            inicio = time.monotonic()
            build = B.leer_build(imagen, motor, casador, categorias)
            ms = (time.monotonic() - inicio) * 1000
            v = verdad.get(fichero.name)
            nombres = [r.nombre for r in build.equipados + build.coleccion]
            if v is None:
                print(f"  {fichero.name}: {ms:.0f} ms equipo={build.equipo.nombre if build.equipo else '-'} mods={nombres}"
                      f" sin identificar={build.sin_identificar}")
                continue
            esperados = ids_de(v.get("mods", []))
            vistos = {r.item_id for r in build.equipados + build.coleccion}
            inventados = [r.nombre for r in build.equipados + build.coleccion if r.item_id not in esperados]
            equipo_ok = build.equipo is not None and build.equipo.nombre.lower() == str(v.get("equipo", "")).lower()
            print(f"  {fichero.name}: {ms:.0f} ms equipo={'OK' if equipo_ok else '-'} mods {len(esperados & vistos)}/{len(esperados)}"
                  f" inventados {inventados}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
