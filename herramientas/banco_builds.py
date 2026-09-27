"""Banco de pruebas del lector de la pantalla de mejoras (pestana Build).

Pinta pantallas sinteticas (tests/sintetico_builds.py) con mods reales del indice, en
ingles y castellano y a 720p, 1080p, 1440p y 4K, las pasa por el lector y cuenta:
mods reconocidos, mods inventados (los peores: casan con otro mod), el equipo de la
cabecera y el tiempo. Con `--capturas carpeta` lee tambien capturas reales con un
`verdad.json` al lado: {"fichero.png": {"equipo": "Excalibur", "mods": ["Vitality", ...]}}
(nombres en ingles del indice). Esas capturas no van en el repositorio.

Uso: .venv/Scripts/python.exe herramientas/banco_builds.py [--n 8] [--capturas carpeta] [--guardar carpeta]
                                                            [--alto-deteccion N]
`--alto-deteccion` cambia el alto al que busca texto el detector (0: a tamano real) para medir.
`--solo-capturas` se salta las sinteticas; `--json fichero` guarda el resultado por captura.

El `verdad.json` detallado separa lo que se ve en cada parte de la pantalla, con los
nombres tal y como salen en el juego (ingles o castellano, se buscan en el indice):
{"f.png": {"equipo": "Mesa Prime", "equipados": [...], "coleccion": [...], "arcanos": [...],
           "ignorar": [...]}}. "ignorar" son mods medio tapados que no cuentan ni como
acierto ni como inventados. Por cada captura dice aciertos por parte, los mods que caen
en la parte equivocada, los inventados (casan con algo que no esta en la pantalla) y,
por cada mod que falta, lo que leyo el OCR mas parecido, para saber por que no caso.
Hace falta el indice real construido (la app lo crea la primera vez). No se toca: se
copia a una carpeta temporal con FARMADEX_DATOS.

Los nombres de la verdad pueden ir en cualquier idioma que traiga el indice (ingles,
castellano, frances, aleman, portugues, italiano, polaco). `"no_legible": true` marca las
capturas que el lector no puede leer (el juego en ruso): de esas solo cuenta que no
invente nada. `"idioma"` dice el idioma del juego si el nombre del fichero no empieza
por el ("uw_3440_...": ultrapanoramica en ingles). Al final saca una tabla por idioma y
otra por resolucion.

`--variantes` lee ademas cada captura con verdad transformada como la veria otro
jugador: reescalada a resoluciones menores (720p, 1366x768, 900p, 1080p, 1440p), en
16:10 y en 21:9 (rellenando con el fondo), con la escala de menu del juego al 75 % y
como ventana dentro del escritorio con su barra de titulo (lo que se captura si no se
encuentra la ventana del juego). `--src carpeta` usa el codigo de otra copia de `src`
(para comparar antes y despues).
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
_SRC = next((sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a == "--src"), None)
sys.path.insert(0, _SRC or str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

import cv2  # noqa: E402

from farmadex.captura import builds as B  # noqa: E402
from farmadex.captura.ocr import MotorOCR  # noqa: E402
from farmadex.datos import indice  # noqa: E402
import sintetico_builds as SINT  # noqa: E402


PARTES = ("equipados", "coleccion", "arcanos")


def _normal(texto: str) -> str:
    import unicodedata
    texto = unicodedata.normalize("NFKD", texto or "")
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).lower().split())


_NOMBRES: dict[str, set[int]] = {}


def ids_por_nombre(con, nombre: str) -> set[int]:
    """Todos los ids cuyo nombre (en cualquier idioma del indice) es ese, sin tildes ni mayusculas."""
    if not _NOMBRES:
        for item_id, en, es in con.execute("SELECT id, nombre_en, nombre_es FROM items"):
            for n in (en, es):
                if n:
                    _NOMBRES.setdefault(_normal(n), set()).add(item_id)
        try:
            for item_id, n in con.execute("SELECT item_id, nombre FROM items_nombres"):
                if n:
                    _NOMBRES.setdefault(_normal(n), set()).add(item_id)
        except Exception:  # noqa: BLE001 - indice viejo sin otros idiomas
            pass
    return _NOMBRES.get(_normal(nombre), set())


def _parecida(nombre: str, lineas) -> str:
    """La linea del OCR que mas se parece a un nombre (para saber por que no caso)."""
    from rapidfuzz import fuzz
    mejor, puntos = "", 0.0
    for linea in lineas:
        p = fuzz.partial_ratio(_normal(nombre), _normal(linea.texto))
        if p > puntos:
            mejor, puntos = linea.texto, p
    return f"{mejor!r} ({puntos:.0f})" if mejor else "nada"


def medir_detallado(con, nombre_fichero: str, v: dict, build, ms: float) -> dict:
    """Aciertos por parte (equipados, coleccion, arcanos), mal colocados e inventados."""
    from collections import Counter
    leidos = {"equipados": build.equipados, "coleccion": build.coleccion, "arcanos": build.arcanos}
    ignorar: set[int] = set()
    for n in v.get("ignorar", []):
        ignorar |= ids_por_nombre(con, n)
    en_pantalla: set[int] = set(ignorar)
    for parte in PARTES:
        for n in v.get(parte, []):
            ids = ids_por_nombre(con, n)
            if not ids:
                print(f"  !! {nombre_fichero}: '{n}' no esta en el indice (revisa verdad.json)")
            en_pantalla |= ids
    salida = {"fichero": nombre_fichero, "ms": round(ms), "partes": {}, "fallos": [], "inventados": [],
              "mal_colocados": []}
    equipo_esperado = ids_por_nombre(con, v.get("equipo", ""))
    salida["equipo_ok"] = bool(build.equipo is not None and build.equipo.item_id in equipo_esperado)
    salida["equipo_leido"] = build.equipo.nombre if build.equipo else (build.equipo_texto or "")
    for parte in PARTES:
        esperados = [ids_por_nombre(con, n) for n in v.get(parte, [])]
        disponibles = Counter(r.item_id for r in leidos[parte])
        aciertos = 0
        for n, ids in zip(v.get(parte, []), esperados):
            elegido = next((i for i in ids if disponibles[i] > 0), None)
            if elegido is not None:
                disponibles[elegido] -= 1
                aciertos += 1
                continue
            otra = next((p for p in PARTES if p != parte and any(r.item_id in ids for r in leidos[p])), None)
            if otra:
                salida["mal_colocados"].append(f"{n} ({parte} -> {otra})")
            else:
                salida["fallos"].append(f"{parte}: {n} <- OCR {_parecida(n, getattr(build, 'lineas', []))}")
        salida["partes"][parte] = [aciertos, len(esperados)]
    for parte in PARTES:
        for r in leidos[parte]:
            if r.item_id not in en_pantalla:
                salida["inventados"].append(f"{parte}: {r.texto_ocr!r} -> {r.nombre!r} ({r.puntuacion:.0f})")
    salida["sin_identificar"] = list(build.sin_identificar)
    salida["no_legible"] = bool(v.get("no_legible"))
    salida["aviso"] = getattr(build, "aviso", "")
    p = salida["partes"]
    equipo = "OK" if salida["equipo_ok"] else f"NO ({salida['equipo_leido']})"
    print(f"  {nombre_fichero:28s} {ms:5.0f} ms equipo={equipo}"
          f"  equipados {p['equipados'][0]}/{p['equipados'][1]}  coleccion {p['coleccion'][0]}/{p['coleccion'][1]}"
          f"  arcanos {p['arcanos'][0]}/{p['arcanos'][1]}  mal colocados {len(salida['mal_colocados'])}"
          f"  inventados {len(salida['inventados'])}  sin identificar {len(build.sin_identificar)}")
    for linea in salida["fallos"]:
        print(f"      FALTA {linea}")
    for linea in salida["inventados"]:
        print(f"      INVENTADO {linea}")
    if salida["mal_colocados"]:
        print(f"      MAL COLOCADOS {len(salida['mal_colocados'])}: {', '.join(salida['mal_colocados'][:4])}...")
    if build.sin_identificar:
        print(f"      SIN IDENTIFICAR {build.sin_identificar}")
    return salida


def _grupo_idioma(r: dict) -> str:
    return r.get("idioma") or r["fichero"].split("_")[0]


def tabla(resultados: list[dict], clave, titulo: str) -> None:
    """Aciertos por grupo (idioma o resolucion): mods bien leidos y colocados, equipo,
    inventados. Las capturas no legibles solo suman inventados."""
    grupos: dict[str, list[dict]] = {}
    for r in resultados:
        grupos.setdefault(clave(r), []).append(r)
    print(f"\n== Por {titulo}")
    print(f"  {'grupo':14s} {'capturas':>8s} {'mods':>11s} {'%':>6s} {'equipo':>7s} {'inventados':>10s}")
    for g in sorted(grupos):
        rs = grupos[g]
        legibles = [r for r in rs if not r.get("no_legible")]
        ok = sum(r["partes"][p][0] for r in legibles for p in PARTES)
        tot = sum(r["partes"][p][1] for r in legibles for p in PARTES)
        equipo = f"{sum(r['equipo_ok'] for r in legibles)}/{len(legibles)}" if legibles else "-"
        pct = f"{100 * ok / tot:.1f}" if tot else "-"
        mods = f"{ok}/{tot}" if legibles else "no legible"
        print(f"  {g:14s} {len(rs):8d} {mods:>11s} {pct:>6s} {equipo:>7s} {sum(len(r['inventados']) for r in rs):10d}")


def resumir(resultados: list[dict]) -> None:
    ilegibles = [r for r in resultados if r.get("no_legible")]
    if ilegibles:
        print(f"\n== No legibles ({len(ilegibles)}): inventados {sum(len(r['inventados']) for r in ilegibles)};"
              f" con aviso {sum(1 for r in ilegibles if r.get('aviso'))}/{len(ilegibles)};"
              f" sin identificar {sum(len(r['sin_identificar']) for r in ilegibles)}")
    resultados = [r for r in resultados if not r.get("no_legible")]
    n = len(resultados)
    tot = {p: [sum(r["partes"][p][0] for r in resultados), sum(r["partes"][p][1] for r in resultados)] for p in PARTES}
    mods_ok = sum(tot[p][0] for p in PARTES)
    mods_total = sum(tot[p][1] for p in PARTES)
    mal = sum(len(r["mal_colocados"]) for r in resultados)
    inventados = sum(len(r["inventados"]) for r in resultados)
    print(f"\n== Resumen capturas reales ({n}): equipo {sum(r['equipo_ok'] for r in resultados)}/{n};"
          f" reconocidos y bien colocados {mods_ok}/{mods_total} ({100 * mods_ok / max(1, mods_total):.1f} %)"
          f" [equipados {tot['equipados'][0]}/{tot['equipados'][1]}, coleccion {tot['coleccion'][0]}/{tot['coleccion'][1]},"
          f" arcanos {tot['arcanos'][0]}/{tot['arcanos'][1]}]; mal colocados {mal}; inventados {inventados};"
          f" sin identificar {sum(len(r['sin_identificar']) for r in resultados)}")


RESOLUCIONES_VARIANTES = ((1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440))


def _fondo(imagen, ancho: int, alto: int):
    """El fondo de relleno: la propia captura estirada y muy borrosa (como el hangar que
    se ve detras de la interfaz), no negro."""
    import cv2
    return cv2.GaussianBlur(cv2.resize(imagen, (ancho, alto), interpolation=cv2.INTER_AREA), (0, 0), 25)


def variantes(imagen):
    """(nombre, imagen) de la captura como la veria otro jugador. Solo se reduce, nunca se
    amplia (ampliar no da la letra nitida de una pantalla grande de verdad)."""
    import cv2
    import numpy as np
    alto, ancho = imagen.shape[:2]
    salida = []
    if abs(ancho / alto - 16 / 9) < 0.02:
        for a, h in RESOLUCIONES_VARIANTES:
            if h < alto:
                salida.append((f"{a}x{h}", cv2.resize(imagen, (a, h), interpolation=cv2.INTER_AREA)))
        # 16:10 con el mismo ancho: la interfaz igual y mas fondo arriba y abajo.
        alto_1610 = ancho * 10 // 16
        lienzo = _fondo(imagen, ancho, alto_1610)
        y0 = (alto_1610 - alto) // 2
        lienzo[y0:y0 + alto] = imagen
        salida.append((f"16:10_{ancho}x{alto_1610}", lienzo))
        # 21:9 con el mismo alto: mas fondo a los lados.
        ancho_219 = alto * 21 // 9
        lienzo = _fondo(imagen, ancho_219, alto)
        x0 = (ancho_219 - ancho) // 2
        lienzo[:, x0:x0 + ancho] = imagen
        salida.append((f"21:9_{ancho_219}x{alto}", lienzo))
    # Escala de menu del juego al 75 %: la interfaz mas pequena, centrada.
    a75, h75 = ancho * 3 // 4, alto * 3 // 4
    lienzo = _fondo(imagen, ancho, alto)
    y0, x0 = (alto - h75) // 2, (ancho - a75) // 2
    lienzo[y0:y0 + h75, x0:x0 + a75] = cv2.resize(imagen, (a75, h75), interpolation=cv2.INTER_AREA)
    salida.append((f"menu75_{ancho}x{alto}", lienzo))
    # Ventana con marco y barra de titulo dentro del escritorio (captura de la pantalla
    # entera cuando no se encuentra la ventana del juego): el juego a un 80 %, desplazado.
    escritorio = np.full((alto, ancho, 3), (96, 72, 40), dtype=np.uint8)
    a80, h80 = ancho * 4 // 5, alto * 4 // 5
    barra = max(24, alto // 36)
    x0, y0 = ancho // 20, alto // 20 + barra
    escritorio[y0 - barra:y0, x0 - 1:x0 + a80 + 1] = (240, 240, 240)
    cv2.putText(escritorio, "Warframe", (x0 + 8, y0 - barra // 4), cv2.FONT_HERSHEY_SIMPLEX, barra / 40, (20, 20, 20), 1)
    escritorio[y0:y0 + h80, x0:x0 + a80] = cv2.resize(imagen, (a80, h80), interpolation=cv2.INTER_AREA)
    salida.append((f"ventana_{ancho}x{alto}", escritorio))
    return salida


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--semilla", type=int, default=7)
    parser.add_argument("--capturas")
    parser.add_argument("--guardar")
    parser.add_argument("--alto-deteccion", type=int)
    parser.add_argument("--solo-capturas", action="store_true")
    parser.add_argument("--json")
    parser.add_argument("--variantes", action="store_true")
    parser.add_argument("--src")
    args = parser.parse_args()
    if args.alto_deteccion is not None:
        B.ALTO_DETECCION = args.alto_deteccion or None
    print(f"Alto de deteccion: {getattr(B, 'ALTO_DETECCION', None) or 'tamano real'}")

    con = indice.conectar()
    indice.crear_esquema(con)  # un indice viejo puede no tener las tablas de idiomas
    casador = B.crear_casador(con)
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    motor = MotorOCR()
    motor.precalentar()  # como la app al arrancar: la primera pantalla no paga la carga del modelo
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
    n_sinteticas = 0 if args.solo_capturas else args.n
    print(f"== {n_sinteticas} pantallas sinteticas")
    for i in range(n_sinteticas):
        idioma = "en" if i % 2 == 0 else "es"
        equipo = rng.choice(frames)
        equipados = rng.sample(mods, 9)
        coleccion = rng.sample(mods, 16)
        traducir = (lambda n: nombre_es.get(n) or n) if idioma == "es" else (lambda n: n)
        ancho, alto = [(1920, 1080), (2560, 1440), (1280, 720), (3840, 2160)][i % 4]
        imagen = SINT.pintar_arsenal(equipo, [traducir(n) for n in equipados], [traducir(n) for n in coleccion],
                                     ancho=ancho, alto=alto, idioma=idioma, semilla=i, desenfoque=0.6 if i % 5 == 4 else 0)
        if guardar is not None:
            cv2.imwrite(str(guardar / f"arsenal_{i:02d}_{idioma}_{alto}p.png"), imagen)
        inicio = time.monotonic()
        build = B.leer_build(imagen, motor, casador, categorias)
        ms = (time.monotonic() - inicio) * 1000
        tiempos.append(ms)
        # Por nombre, no por id: hay mods con el mismo nombre y varios ids ("Bane Of Corpus").
        nombres_pintados = list(dict.fromkeys(equipados + coleccion))
        ids_por = {n: ids_por_nombre(con, n) for n in nombres_pintados}
        esperados = set().union(*ids_por.values())
        vistos = {r.item_id for r in build.equipados + build.coleccion}
        aciertos = sum(1 for n in nombres_pintados if ids_por[n] & vistos)
        faltan = [n for n in nombres_pintados if not ids_por[n] & vistos]
        inventados = [r for r in build.equipados + build.coleccion if r.item_id not in esperados]
        equipo_ok = build.equipo is not None and build.equipo.nombre.lower() in (equipo.lower(),)
        total += len(nombres_pintados)
        ok += aciertos
        falsos += len(inventados)
        equipos_ok += equipo_ok
        print(f"  {idioma} {ancho}x{alto} {ms:5.0f} ms  equipo={'OK' if equipo_ok else build.equipo.nombre if build.equipo else '-'}"
              f"  mods {aciertos}/{len(nombres_pintados)}  inventados {len(inventados)}  sin identificar {len(build.sin_identificar)}")
        if faltan:
            print(f"     FALTAN: {[traducir(n) for n in faltan]}")
        for r in inventados:
            print(f"     INVENTADO: {r.texto_ocr!r} -> {r.nombre!r} ({r.puntuacion:.0f})")
    if n_sinteticas:
        print(f"\n== Resumen sinteticas: mods {ok}/{total} ({100 * ok / max(1, total):.1f} %), inventados {falsos},"
              f" equipo {equipos_ok}/{n_sinteticas}, tiempo medio {sum(tiempos) / max(1, len(tiempos)):.0f} ms")

    if args.capturas:
        carpeta = Path(args.capturas)
        verdad = {}
        if (carpeta / "verdad.json").exists():
            verdad = json.load(open(carpeta / "verdad.json", encoding="utf-8"))
        print(f"\n== capturas reales de {carpeta}")
        resultados = []
        resultados_variantes: list[dict] = []
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
            if "equipados" in v:
                r = medir_detallado(con, fichero.name, v, build, ms)
                r["idioma"] = v.get("idioma") or fichero.name.split("_")[0]
                r["resolucion"] = f"{imagen.shape[1]}x{imagen.shape[0]}"
                resultados.append(r)
                if args.variantes and not v.get("no_legible"):
                    for nombre_v, imagen_v in variantes(imagen):
                        inicio = time.monotonic()
                        build_v = B.leer_build(imagen_v, motor, casador, categorias)
                        r_v = medir_detallado(con, f"{fichero.stem}@{nombre_v}", v, build_v,
                                              (time.monotonic() - inicio) * 1000)
                        r_v["idioma"], r_v["variante"] = r["idioma"], nombre_v.split("_")[0]
                        r_v["resolucion"] = f"{imagen_v.shape[1]}x{imagen_v.shape[0]}"
                        resultados_variantes.append(r_v)
                continue
            esperados = ids_de(v.get("mods", []))
            vistos = {r.item_id for r in build.equipados + build.coleccion}
            inventados = [r.nombre for r in build.equipados + build.coleccion if r.item_id not in esperados]
            equipo_ok = build.equipo is not None and build.equipo.nombre.lower() == str(v.get("equipo", "")).lower()
            print(f"  {fichero.name}: {ms:.0f} ms equipo={'OK' if equipo_ok else '-'} mods {len(esperados & vistos)}/{len(esperados)}"
                  f" inventados {inventados}")
        if resultados:
            resumir(resultados)
            tabla(resultados, _grupo_idioma, "idioma del juego")
            tabla(resultados, lambda r: r["resolucion"], "resolucion")
        if resultados_variantes:
            print("\n== VARIANTES")
            resumir(resultados_variantes)
            tabla(resultados_variantes, lambda r: r["variante"], "variante")
            tabla(resultados_variantes, _grupo_idioma, "idioma (variantes)")
        if args.json and (resultados or resultados_variantes):
            Path(args.json).write_text(json.dumps({"reales": resultados, "variantes": resultados_variantes},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
