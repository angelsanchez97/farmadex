"""Banco de pruebas de la pantalla de recompensas: acierto y tiempo por camino.

Recorre todas las pantallas de recompensas reales con verdad anotada a mano
(`tests/fixtures/capturas_reliquias/verdad.json`, propias, y
`tests/fixtures/capturas_internet/reliquias/verdad.json`, bajadas de internet y
fuera del repositorio) y mide, para cada una y para cada camino:

- acierto: tarjetas con el objeto correcto (por posicion, de izquierda a
  derecha) y recompensas inventadas (objetos que no estan en pantalla);
- tiempo desde que se tiene la imagen hasta tener las etiquetas (captura de
  pantalla aparte, que es la misma para los dos caminos), mediana de N vueltas.

Caminos: "actual" es la franja entera (`leer_franja` + `elegir_fila`, lo que
habia hasta la 0.2.5) y "nuevo" es `recompensas_rapidas.leer_pantalla`, la fila
de nombres con la franja de respaldo. A los dos se les dice cuantas tarjetas
hay, como hace EE.log.

Uso: .venv/Scripts/python.exe herramientas/banco_recompensas.py [--vueltas 3]
       [--carga 0] [--indice ruta] [--json salida.json] [--solo nombre]
`--carga N` lanza N procesos que se comen un nucleo cada uno mientras se mide,
para ver que pasa con el juego peleando por la CPU. Hace falta el indice real
(la aplicacion lo construye la primera vez); se abre solo para leer.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("FARMADEX_DATOS", str(Path(os.environ.get("TEMP", ".")) / "farmadex-banco"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

RAIZ = Path(__file__).resolve().parents[1]
VERDADES = (
    RAIZ / "tests" / "fixtures" / "capturas_reliquias" / "verdad.json",
    RAIZ / "tests" / "fixtures" / "capturas_internet" / "reliquias" / "verdad.json",
)


def indice_real() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Farmadex" / "db" / "indice.sqlite"


def copia_de_trabajo(ruta_indice: Path) -> sqlite3.Connection:
    """El indice del usuario, copiado en memoria: no se escribe en el suyo, y un indice
    de un esquema anterior recibe las tablas que le falten (vacias) para que el Casador
    de la version en desarrollo pueda construirse."""
    origen = sqlite3.connect(f"file:{ruta_indice.as_posix()}?mode=ro", uri=True)
    con = sqlite3.connect(":memory:")
    origen.backup(con)
    origen.close()
    esquema = (RAIZ / "src" / "farmadex" / "datos" / "esquema.sql").read_text(encoding="utf-8")
    con.executescript(esquema)  # todo es CREATE ... IF NOT EXISTS
    return con


@dataclass
class Caso:
    ruta: Path
    tarjetas: list[str]
    fila: tuple[float, float, float, float] | None  # proporciones, solo recortes
    franja: tuple[float, float, float, float] | None
    nota: str = ""


def cargar_casos(solo: str | None = None) -> list[Caso]:
    import cv2

    casos = []
    for verdad in VERDADES:
        if not verdad.exists():
            continue
        datos = json.loads(verdad.read_text(encoding="utf-8"))
        for nombre, info in datos.items():
            if nombre.startswith("_") or (solo and solo not in nombre):
                continue
            ruta = verdad.parent / nombre
            if not ruta.exists():
                continue
            imagen = cv2.imread(str(ruta))
            if imagen is None:
                continue
            alto, ancho = imagen.shape[:2]

            def prop(px):
                return (px[0] / ancho, px[1] / alto, px[2] / ancho, px[3] / alto) if px else None

            casos.append(Caso(ruta, list(info["tarjetas"]), prop(info.get("fila")),
                              prop(info.get("franja")), info.get("nota", "")))
    return casos


@dataclass
class Resultado:
    aciertos: int
    inventadas: int
    ms: float
    via: str
    leidas: list[str]


def puntuar(encontradas, esperadas_ids: list[int]) -> tuple[int, int]:
    """(aciertos por posicion, inventadas). Sin identificar no acierta ni inventa."""
    ids = [r.item_id for r in encontradas]
    aciertos = sum(1 for a, b in zip(ids, esperadas_ids) if a == b)
    pendientes = list(esperadas_ids)
    inventadas = 0
    for i in ids:
        if i in pendientes:
            pendientes.remove(i)
        elif i:
            inventadas += 1
    return aciertos, inventadas


class Banco:
    def __init__(self, ruta_indice: Path, vueltas: int = 3, hilos: int | None = None):
        from farmadex.captura.ocr import HILOS_OCR, Casador, MotorOCR
        from farmadex.captura.reliquias import CATEGORIAS_RECOMPENSA
        from farmadex.captura import recompensas_rapidas as rapidas

        self.vueltas = vueltas
        self.con = copia_de_trabajo(ruta_indice)
        self.casador = Casador(self.con, CATEGORIAS_RECOMPENSA)
        ids = rapidas.ids_reliquias(self.con)
        self.reliquias = self.casador.restringido(ids) if ids else None
        self.piezas = rapidas.catalogo_de_piezas(self.casador, self.con)
        self.motor = MotorOCR("rapidocr", hilos or HILOS_OCR)
        self.motor.precalentar()
        rapidas.precalentar(self.motor)

    def ids_de(self, nombres: list[str]) -> list[int]:
        salida = []
        for nombre in nombres:
            item_id, _, puntos = self.casador.casar(nombre, 90)
            if not item_id:
                raise ValueError(f"la verdad {nombre!r} no esta en el catalogo")
            salida.append(item_id)
        return salida

    def _capturar(self, imagen):
        def capturar(region):
            return imagen[region.y:region.y + region.alto, region.x:region.x + region.ancho].copy()
        return capturar

    def actual(self, imagen, caso: Caso, esperadas: int):
        from farmadex.captura.pantalla import Region
        from farmadex.captura.reliquias import FRANJA, elegir_fila, leer_franja
        from farmadex.captura import recompensas_rapidas as rapidas

        alto, ancho = imagen.shape[:2]
        ventana = Region(0, 0, ancho, alto)
        capturar = self._capturar(imagen)

        def lento(ventana, tiempos):
            region = ventana.recortar(*(caso.franja or FRANJA))
            encontrados = leer_franja(capturar(region), self.motor, self.casador, None, 70, tiempos)
            fila = elegir_fila(encontrados, tiempos.pop("_lineas", []), maximo=esperadas)
            return [rapidas.desplazar(r, region.x, region.y) for r in fila]

        return lento, ventana, capturar

    def medir(self, caso: Caso) -> tuple[Resultado, Resultado]:
        import cv2
        from farmadex.captura import recompensas_rapidas as rapidas

        imagen = cv2.imread(str(caso.ruta))
        esperadas_ids = self.ids_de(caso.tarjetas)
        esperadas = len(caso.tarjetas)
        lento, ventana, capturar = self.actual(imagen, caso, esperadas)
        escalonado = rapidas.CasadorEscalonado(self.piezas, self.reliquias, None)
        fila = caso.fila or rapidas.FILA_NOMBRES

        def camino_actual():
            return lento(ventana, {}), "franja"

        def camino_nuevo():
            lectura = rapidas.leer_pantalla(capturar, ventana, self.motor, escalonado, esperadas, lento, {}, fila)
            return lectura.recompensas, lectura.via

        salida = []
        for camino in (camino_actual, camino_nuevo):
            tiempos = []
            for _ in range(self.vueltas):
                t0 = time.perf_counter()
                encontradas, via = camino()
                tiempos.append((time.perf_counter() - t0) * 1000)
            aciertos, inventadas = puntuar(encontradas, esperadas_ids)
            salida.append(Resultado(aciertos, inventadas, statistics.median(tiempos), via,
                                    [r.nombre or f"?{r.texto_ocr}" for r in encontradas]))
        return salida[0], salida[1]


def cargar_cpu(n: int) -> list[subprocess.Popen]:
    """N procesos propios comiendose un nucleo cada uno; se matan por su PID al terminar."""
    return [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(n)]


def correr(vueltas: int, carga: int, ruta_indice: Path, solo: str | None = None) -> list[dict]:
    casos = cargar_casos(solo)
    if not casos:
        print("No hay capturas con verdad anotada.")
        return []
    banco = Banco(ruta_indice, vueltas)
    procesos = cargar_cpu(carga)
    try:
        if procesos:
            time.sleep(0.5)
        filas = []
        for caso in casos:
            try:
                actual, nuevo = banco.medir(caso)
            except ValueError as e:
                print(f"  {caso.ruta.name}: {e}")
                continue
            filas.append({
                "captura": caso.ruta.name, "tarjetas": len(caso.tarjetas),
                "actual": vars(actual), "nuevo": vars(nuevo),
            })
    finally:
        for p in procesos:
            p.kill()
    return filas


def imprimir(filas: list[dict], carga: int) -> None:
    print(f"\n{'captura':38} n  | actual: ok inv    ms | nuevo: ok inv    ms via     (carga {carga})")
    tot = {"n": 0, "a_ok": 0, "a_inv": 0, "n_ok": 0, "n_inv": 0}
    for f in filas:
        a, n = f["actual"], f["nuevo"]
        print(f"{f['captura']:38} {f['tarjetas']}  | {a['aciertos']:9} {a['inventadas']:3} {a['ms']:5.0f} "
              f"| {n['aciertos']:8} {n['inventadas']:3} {n['ms']:5.0f} {n['via']}")
        if n["aciertos"] < f["tarjetas"] or n["inventadas"]:
            print(f"{'':38}    nuevo leyo: {n['leidas']}")
        if a["aciertos"] < f["tarjetas"] or a["inventadas"]:
            print(f"{'':38}    actual leyo: {a['leidas']}")
        tot["n"] += f["tarjetas"]; tot["a_ok"] += a["aciertos"]; tot["a_inv"] += a["inventadas"]
        tot["n_ok"] += n["aciertos"]; tot["n_inv"] += n["inventadas"]
    if filas:
        ma = statistics.median(f["actual"]["ms"] for f in filas)
        mn = statistics.median(f["nuevo"]["ms"] for f in filas)
        print(f"{'TOTAL':38} {tot['n']:2} | {tot['a_ok']:9} {tot['a_inv']:3} {ma:5.0f} | {tot['n_ok']:8} {tot['n_inv']:3} {mn:5.0f} (medianas)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vueltas", type=int, default=3)
    parser.add_argument("--carga", type=int, default=0, help="procesos ocupando la CPU mientras se mide")
    parser.add_argument("--indice", type=Path, default=indice_real())
    parser.add_argument("--json", type=Path, default=None, help="guardar los resultados")
    parser.add_argument("--solo", default=None, help="solo las capturas cuyo nombre contenga esto")
    args = parser.parse_args()
    if not args.indice.exists():
        print(f"No hay indice en {args.indice}")
        return 1
    filas = correr(args.vueltas, args.carga, args.indice, args.solo)
    imprimir(filas, args.carga)
    if args.json:
        args.json.write_text(json.dumps({"carga": args.carga, "vueltas": args.vueltas, "filas": filas},
                                        indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
