"""Tiempo por etapas de las lecturas por OCR: donde se va el tiempo en cada una.

Para cada lectura (Build, agrietado, bajo el cursor, perfil, fila y franja de
recompensas) cronometra por separado preparar la imagen, el detector (donde hay
texto), los recortes, el reconocedor (que pone) y el casado con el catalogo, la
PRIMERA vez que ve una imagen (en frio, lo que nota el usuario) y repitiendola (en
caliente). Usa pantallas sinteticas (tests/sintetico_builds.py) a 1080p, 1440p y 4K,
las capturas de tests/fixtures y, con `--capturas carpeta`, las imagenes que haya
ahi (se leen como pantalla de mejoras).

Uso: .venv/Scripts/python.exe herramientas/perfil_ocr.py [--capturas carpeta] [--solo build,cursor,...]
Hace falta el indice real construido (la app lo crea la primera vez). No se toca:
se copia a una carpeta temporal con FARMADEX_DATOS, igual que banco_builds.py.
En el registro de la app (farmadex.log) cada lectura deja ya una linea con estas
mismas etapas; esta herramienta sirve para medir antes y despues de un cambio.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "herramientas"))
from banco_builds import preparar_indice  # noqa: E402  (apunta FARMADEX_DATOS a una copia)

preparar_indice()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from farmadex.agrietados import mercado  # noqa: E402
from farmadex.agrietados.lector import ArmaConocida, LectorTarjeta  # noqa: E402
from farmadex.captura import agrietados as AG  # noqa: E402
from farmadex.captura import builds as B  # noqa: E402
from farmadex.captura import ocr as O  # noqa: E402
from farmadex.captura import perfil_equipo as PE  # noqa: E402
from farmadex.captura import recompensas_rapidas as RR  # noqa: E402
from farmadex.captura import reliquias as REL  # noqa: E402
from farmadex.datos import indice  # noqa: E402
import sintetico_builds as SINT  # noqa: E402

ETAPAS = ("preparar", "detector", "recortes", "reconocedor", "casado")
T: dict[str, float] = {}


def cron(nombre, f):
    def envuelta(*a, **k):
        inicio = time.perf_counter()
        try:
            return f(*a, **k)
        finally:
            T[nombre] = T.get(nombre, 0.0) + time.perf_counter() - inicio
    return envuelta


class Proxy:
    def __init__(self, obj, nombre):
        self._o, self._n = obj, nombre

    def __call__(self, *a, **k):
        return cron(self._n, self._o)(*a, **k)

    def __getattr__(self, a):
        return getattr(self._o, a)


def casos(capturas: str | None, rng: random.Random, mods: list[str]):
    fixtures = RAIZ / "tests" / "fixtures"
    for nombre, (w, h) in (("1080p", (1920, 1080)), ("1440p", (2560, 1440)), ("4K", (3840, 2160))):
        for k in range(2):
            yield "build", f"sint {nombre} #{k}", SINT.pintar_arsenal(
                rng.choice(["Excalibur", "Mesa", "Nova"]), rng.sample(mods, 9), rng.sample(mods, 16),
                ancho=w, alto=h, semilla=10 + k)
    for k, (w, h) in enumerate(((1920, 1080), (2560, 1440))):
        e = h / 1080
        tarjeta = SINT.pintar_tarjeta_agrietado(
            "Rubico", "Crita-visitox", [("+", 120.5, "Critical Damage"), ("+", 98.1, "Multishot"), ("-", 30.2, "Zoom")],
            maestria=12, variado=3, ancho=int(316 * e), alto=int(400 * e), semilla=k)
        caja = np.full((int(AG.ALTO_TARJETA * e), int(AG.ANCHO_TARJETA * e), 3), 20, np.uint8)
        y0, x0 = (caja.shape[0] - tarjeta.shape[0]) // 2, (caja.shape[1] - tarjeta.shape[1]) // 2
        caja[y0:y0 + tarjeta.shape[0], x0:x0 + tarjeta.shape[1]] = tarjeta
        yield "riven", f"sint caja {h}p", caja
    arsenal = SINT.pintar_arsenal("Excalibur", ["Vitality", "Redirection", "Intensify"], ["Flow", "Rush"], semilla=4)
    for x, y in ((712, 399), (960, 885)):
        yield "cursor", f"sint 620x170 @{x},{y}", np.ascontiguousarray(arsenal[y - 85:y + 85, x - 310:x + 310])
    for f in sorted(glob.glob(str(fixtures / "capturas_perfil" / "*.jpg")))[:3]:
        yield "perfil", Path(f).name, cv2.imread(f)
    for f in sorted(glob.glob(str(fixtures / "capturas_reliquias" / "*.jpg")))[:2]:
        img = cv2.imread(f)
        alto, ancho = img.shape[:2]
        x0, y0, x1, y1 = (int(RR.FILA_NOMBRES[0] * ancho), int(RR.FILA_NOMBRES[1] * alto),
                          int(RR.FILA_NOMBRES[2] * ancho), int(RR.FILA_NOMBRES[3] * alto))
        yield "fila", Path(f).name, np.ascontiguousarray(img[y0:y1, x0:x1])
        yield "franja", Path(f).name, np.ascontiguousarray(img[int(alto * .3):int(alto * .72)])
    if capturas:
        for f in sorted(Path(capturas).iterdir()):
            img = cv2.imread(str(f)) if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") else None
            if img is not None:
                yield "build", f.name[:24], img


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--capturas")
    parser.add_argument("--solo", help="tipos separados por comas: build,riven,cursor,perfil,fila,franja")
    args = parser.parse_args()
    solo = set(args.solo.split(",")) if args.solo else None

    O.preparar = cron("preparar", O.preparar)
    O.Casador.casar = cron("casado", O.Casador.casar)
    con = indice.conectar()
    indice.crear_esquema(con)
    casador_b = B.crear_casador(con)
    casador_g = O.Casador(con)
    casador_pe = PE.casador_equipamiento(con)
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    armas = mercado.analizar_armas(json.load(open(RAIZ / "tests" / "fixtures" / "market_riven_weapons.json",
                                                  encoding="utf-8")))
    lector_riven = LectorTarjeta([ArmaConocida(a.slug, a.nombre_en, a.nombre_en) for a in armas])
    mods = [r[0] for r in con.execute(
        "SELECT DISTINCT nombre_en FROM items WHERE categoria='Mods' AND tipo='Warframe Mod' AND padre_id IS NULL")]

    motor = O.MotorOCR()
    inicio = time.perf_counter()
    motor.precalentar()
    RR.precalentar(motor)
    print(f"Precalentado (lo que hace la app al arrancar): {(time.perf_counter() - inicio) * 1000:.0f} ms")
    rapid = motor._cargar()
    rapid.text_detector = Proxy(rapid.text_detector, "detector")
    rapid.text_recognizer = Proxy(rapid.text_recognizer, "reconocedor")
    rapid.get_crop_img_list = cron("recortes", rapid.get_crop_img_list)

    def correr(tipo, img):
        if tipo == "build":
            B.leer_build(img, motor, casador_b, categorias)
        elif tipo == "riven":
            AG.leer_tarjeta(img, motor, lector_riven)
        elif tipo == "cursor":
            O.reconocer(img, motor, casador_g, umbral=85)
        elif tipo == "perfil":
            PE.leer_pagina(img, motor, casador_pe, con)
        elif tipo == "fila":
            RR.leer_fila(img, motor)
        elif tipo == "franja":
            REL.leer_franja(img, motor, casador_g, None, 70, {})

    print(f"{'lectura':7} {'imagen':24} {'tamano':10} {'FRIO':>6}  [" + " ".join(e[:5] for e in ETAPAS)
          + f"]  {'CALIENTE':>8}  [" + " ".join(e[:5] for e in ETAPAS) + "]  (ms)")
    for tipo, nombre, img in casos(args.capturas, random.Random(3), mods):
        if solo and tipo not in solo:
            continue
        T.clear()
        inicio = time.perf_counter()
        correr(tipo, img)
        frio, t_frio = time.perf_counter() - inicio, dict(T)
        calientes = []
        for _ in range(2):
            T.clear()
            inicio = time.perf_counter()
            correr(tipo, img)
            calientes.append((time.perf_counter() - inicio, dict(T)))
        caliente, t_cal = min(calientes, key=lambda c: c[0])
        tamano = f"{img.shape[1]}x{img.shape[0]}"
        print(f"{tipo:7} {nombre[:24]:24} {tamano:10} {frio * 1000:6.0f}  ["
              + " ".join(f"{t_frio.get(e, 0) * 1000:5.0f}" for e in ETAPAS) + f"]  {caliente * 1000:8.0f}  ["
              + " ".join(f"{t_cal.get(e, 0) * 1000:5.0f}" for e in ETAPAS) + "]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
