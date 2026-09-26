"""Banco de pruebas del lector de tarjetas de agrietado: cuanto acierta y en que falla.

Dos fuentes:
  - Tarjetas sinteticas (tests/sintetico_builds.py), con la verdad conocida: arma,
    estadisticas con signo y valor, maestria y veces variado. En ingles y castellano,
    a varios tamanos, con y sin desenfoque.
  - Capturas reales (`--capturas carpeta`): imagenes de tarjetas bajadas de internet
    (la wiki oficial, por ejemplo) con un `verdad.json` al lado:
        {"fichero.png": {"arma": "aklex", "stats": [["puncture_damage", 116, false], ...],
                         "mr": 8, "variado": null, "velado": false}}
    Las que no esten en verdad.json solo se listan. No van en el repositorio (derechos
    de terceros); se guardan en el scratchpad o en tests/fixtures/capturas_internet/
    (carpeta ignorada por git).

Se mide por separado: arma acertada, estadistica exacta (atributo + valor + signo),
signo acertado, tarjetas "fiables" (el lector no pide revision) y, lo que mas importa,
tarjetas fiables PERO mal (falsa seguridad).

Uso: .venv/Scripts/python.exe herramientas/banco_agrietados.py [--n 40] [--capturas carpeta]
                                                              [--guardar carpeta] [--armas fichero.json]
Sin `--armas`, la lista de armas con agrietado se pide a warframe.market (se guarda en
disco un dia). Con el fichero (respuesta de /v2/riven/weapons) no hace falta red.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import cv2  # noqa: E402

from farmadex.agrietados import grados, mercado  # noqa: E402
from farmadex.agrietados.lector import ArmaConocida, LectorTarjeta  # noqa: E402
from farmadex.captura.agrietados import leer_tarjeta  # noqa: E402
from farmadex.captura.ocr import MotorOCR  # noqa: E402
import sintetico_builds as SINT  # noqa: E402


def cargar_armas(fichero: str | None) -> list[mercado.Arma]:
    if fichero:
        return mercado.analizar_armas(json.load(open(fichero, encoding="utf-8")))
    return mercado.compartido().armas()


def caso_sintetico(rng: random.Random, armas: list[mercado.Arma], i: int):
    arma = rng.choice(armas)
    posibles = [a for a in grados.ATRIBUTOS if a.base_en(arma.clase) is not None]
    n_pos = rng.choice([2, 3])
    con_negativo = rng.random() < 0.6
    elegidos = rng.sample(posibles, n_pos + (1 if con_negativo else 0))
    positivos = elegidos[:n_pos]
    negativo = elegidos[n_pos] if con_negativo else None
    if negativo is not None and negativo.solo_positivo:
        negativo = None
    if len(positivos) == 2:
        nombre = positivos[0].prefijo + positivos[1].sufijo.lower()
    else:
        nombre = positivos[0].prefijo + "-" + positivos[1].prefijo.lower() + positivos[2].sufijo.lower()
    idioma = "en" if i % 2 == 0 else "es"
    stats, verdad, unidades = [], [], {}
    for atributo in positivos:
        tramo = grados.rango(atributo.slug, arma.clase, arma.disposicion, len(positivos), 1 if negativo else 0)
        valor = round(rng.uniform(*tramo), 1) if tramo else 10.0
        texto = atributo.nombre_es if idioma == "es" else atributo.nombre_en
        stats.append(("+", valor, texto))
        verdad.append([atributo.slug, valor, False])
        unidades[texto] = atributo.unidad
    if negativo is not None:
        tramo = grados.rango(negativo.slug, arma.clase, arma.disposicion, len(positivos), 1, negativo=True)
        valor = round(abs(rng.uniform(*tramo)), 1) if tramo else 10.0
        texto = negativo.nombre_es if idioma == "es" else negativo.nombre_en
        stats.append(("-", valor, texto))
        verdad.append([negativo.slug, valor, True])
        unidades[texto] = negativo.unidad
    ancho = rng.choice([250, 316, 400])
    mr, variado = rng.randint(8, 16), rng.choice([None, 0, 3, 12])
    imagen = SINT.pintar_tarjeta_agrietado(
        arma.nombre_en, nombre, stats, maestria=mr, variado=variado, ancho=ancho, alto=int(ancho * 1.27),
        semilla=i, en_dos_lineas=(i % 3 == 0), unidades=unidades, desenfoque=0.6 if i % 5 == 4 else 0,
    )
    return f"sintetica_{i:02d}_{idioma}_{ancho}px", imagen, {"arma": arma.slug, "stats": verdad, "mr": mr, "variado": variado, "velado": False}


def evaluar(nombre: str, imagen, verdad: dict | None, motor, lector, cuentas: dict, guardar: Path | None) -> None:
    inicio = time.monotonic()
    tarjeta = leer_tarjeta(imagen, motor, lector)
    ms = (time.monotonic() - inicio) * 1000
    cuentas["tiempos"].append(ms)
    if guardar is not None:
        cv2.imwrite(str(guardar / f"{nombre}.png"), imagen)
    leidas = [[e.slug, e.valor, e.negativo] for e in tarjeta.estadisticas]
    if verdad is None:
        print(f"  {nombre:36} (sin verdad) arma={tarjeta.arma_slug} {leidas} fiable={tarjeta.fiable}")
        return
    cuentas["tarjetas"] += 1
    if verdad.get("velado"):
        ok = tarjeta.velado
        cuentas["velado_ok"] += ok
        print(f"  {nombre:36} velada: {'OK' if ok else 'MAL'}")
        return
    arma_ok = tarjeta.arma_slug == verdad["arma"]
    cuentas["arma_ok"] += arma_ok
    for v in verdad["stats"]:
        cuentas["stats"] += 1
        exacta = any(l[0] == v[0] and abs((l[1] or 0) - v[1]) < 0.05 and l[2] == v[2] for l in leidas)
        cuentas["stats_ok"] += exacta
        cuentas["signo_ok"] += any(l[0] == v[0] and l[2] == v[2] for l in leidas)
    stats_ok = len(leidas) == len(verdad["stats"]) and all(
        any(l[0] == v[0] and abs((l[1] or 0) - v[1]) < 0.05 and l[2] == v[2] for l in leidas) for v in verdad["stats"]
    )
    todo_ok = arma_ok and stats_ok
    cuentas["tarjeta_ok"] += todo_ok
    cuentas["fiables"] += tarjeta.fiable
    if tarjeta.fiable and not todo_ok:
        cuentas["falsa_seguridad"] += 1
    if verdad.get("mr") is not None:
        cuentas["mr"] += 1
        cuentas["mr_ok"] += tarjeta.maestria == verdad["mr"]
    if verdad.get("variado") is not None:
        cuentas["variado"] += 1
        cuentas["variado_ok"] += tarjeta.variado == verdad["variado"]
    marca = "OK " if todo_ok else ("!! " if tarjeta.fiable else "?? ")
    print(f"  {marca}{nombre:34} {ms:4.0f} ms arma={tarjeta.arma_slug or '-'} fiable={tarjeta.fiable}")
    if not todo_ok:
        print(f"       leido : {leidas}")
        print(f"       verdad: {verdad['stats']}")
        for aviso in tarjeta.avisos:
            print(f"       ! {aviso}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=40, help="tarjetas sinteticas (0 para saltarlas)")
    parser.add_argument("--semilla", type=int, default=3)
    parser.add_argument("--capturas", help="carpeta con capturas reales y su verdad.json")
    parser.add_argument("--guardar", help="carpeta donde dejar las tarjetas sinteticas generadas")
    parser.add_argument("--armas", help="respuesta de /v2/riven/weapons guardada (sin red)")
    args = parser.parse_args()

    armas = cargar_armas(args.armas)
    if not armas:
        print("No hay lista de armas con agrietado (sin red y sin fichero).")
        return 1
    lector = LectorTarjeta([ArmaConocida(a.slug, a.nombre_en, a.nombre_en) for a in armas])
    motor = MotorOCR()
    guardar = Path(args.guardar) if args.guardar else None
    if guardar is not None:
        guardar.mkdir(parents=True, exist_ok=True)

    def cuentas_nuevas() -> dict:
        return {"tarjetas": 0, "arma_ok": 0, "stats": 0, "stats_ok": 0, "signo_ok": 0, "tarjeta_ok": 0,
                "fiables": 0, "falsa_seguridad": 0, "mr": 0, "mr_ok": 0, "variado": 0, "variado_ok": 0,
                "velado_ok": 0, "tiempos": []}

    bloques = []
    if args.n:
        rng = random.Random(args.semilla)
        cuentas = cuentas_nuevas()
        print(f"== {args.n} tarjetas sinteticas")
        for i in range(args.n):
            nombre, imagen, verdad = caso_sintetico(rng, armas, i)
            evaluar(nombre, imagen, verdad, motor, lector, cuentas, guardar)
        bloques.append(("sinteticas", cuentas))
    if args.capturas:
        carpeta = Path(args.capturas)
        verdad_todas = {}
        if (carpeta / "verdad.json").exists():
            verdad_todas = json.load(open(carpeta / "verdad.json", encoding="utf-8"))
        cuentas = cuentas_nuevas()
        print(f"== capturas reales de {carpeta}")
        for fichero in sorted(carpeta.iterdir()):
            if fichero.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            imagen = cv2.imread(str(fichero))
            if imagen is None:
                continue
            evaluar(fichero.name, imagen, verdad_todas.get(fichero.name), motor, lector, cuentas, None)
        bloques.append(("reales", cuentas))

    for etiqueta, c in bloques:
        if not c["tarjetas"]:
            continue
        print(f"\n== Resumen {etiqueta}: {c['tarjetas']} tarjetas con verdad")
        print(f"   arma acertada        {c['arma_ok']}/{c['tarjetas']}")
        print(f"   estadistica exacta   {c['stats_ok']}/{c['stats']}  (signo bien {c['signo_ok']}/{c['stats']})")
        print(f"   tarjeta entera bien  {c['tarjeta_ok']}/{c['tarjetas']}")
        print(f"   marcadas fiables     {c['fiables']}/{c['tarjetas']}   de ellas MAL (falsa seguridad): {c['falsa_seguridad']}")
        if c["mr"]:
            print(f"   maestria             {c['mr_ok']}/{c['mr']}")
        if c["variado"]:
            print(f"   veces variado        {c['variado_ok']}/{c['variado']}")
        if c["tiempos"]:
            print(f"   tiempo medio         {sum(c['tiempos']) / len(c['tiempos']):.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
