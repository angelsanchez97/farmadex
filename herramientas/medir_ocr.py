"""Medida repetible de la calidad del OCR y del casado con el catalogo.

Genera imagenes sinteticas parecidas a la pantalla de recompensas (texto en
mayusculas, con acentos, a varios tamanos, con ruido y con poco contraste) para
un puñado de objetos reales del indice, y cuenta cuantos se reconocen bien,
cuantos no se reconocen y, lo peor, cuantos se reconocen como OTRO objeto.

Uso: .venv/Scripts/python.exe herramientas/medir_ocr.py [--n 40] [--semilla 7]
                                                        [--guardar carpeta]
Hace falta el indice real construido (la app lo crea la primera vez).
"""

from __future__ import annotations

import argparse
import ctypes
import re
import random
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmadex.captura.ocr import Casador, MotorOCR, reconocer  # noqa: E402
from farmadex.captura.reliquias import CATEGORIAS_RECOMPENSA  # noqa: E402
from farmadex.datos import indice  # noqa: E402
from farmadex.datos.items import normalizar  # noqa: E402

FUENTES = ("segoeuib.ttf", "seguisb.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf")

# Fondo y texto tal y como los pinta el juego: azul muy oscuro y blanco roto.
FONDO = (12, 16, 22)
TEXTO = (232, 236, 245)

# Cada condicion: (nombre, tamano de letra, ruido, contraste bajo, desenfoque).
CONDICIONES = (
    ("grande", 44, 0, False, 0),
    ("normal", 32, 0, False, 0),
    ("pequena", 22, 0, False, 0),
    ("ruido", 32, 18, False, 0),
    ("contraste", 32, 0, True, 0),
    ("borrosa", 30, 8, False, 1),
    ("todo_mal", 22, 14, True, 1),
)


def fuente(tamano: int) -> ImageFont.FreeTypeFont:
    for nombre in FUENTES:
        try:
            return ImageFont.truetype(nombre, tamano)
        except OSError:
            continue
    return ImageFont.load_default()  # pragma: no cover


def pintar(textos: list[str], tamano: int, ruido: int, contraste: bool, desenfoque: int,
           semilla: int, alto: int = 200) -> np.ndarray:
    """Una imagen con las etiquetas repartidas en horizontal, como las tarjetas."""
    tipografia = fuente(tamano)
    ancho = 1536
    fondo = (70, 72, 78) if contraste else FONDO
    tinta = (120, 122, 128) if contraste else TEXTO
    img = Image.new("RGB", (ancho, alto), fondo)
    dibujo = ImageDraw.Draw(img)
    columna = ancho // max(1, len(textos))
    for i, texto in enumerate(textos):
        lineas = partir(texto, tipografia, dibujo, columna - 24)
        y = alto // 2 - (len(lineas) * int(tamano * 1.25)) // 2
        for linea in lineas:
            caja = dibujo.textbbox((0, 0), linea, font=tipografia)
            x = i * columna + max(4, (columna - (caja[2] - caja[0])) // 2)
            dibujo.text((x, y), linea, fill=tinta, font=tipografia)
            y += int(tamano * 1.25)
    if desenfoque:
        img = img.filter(ImageFilter.GaussianBlur(desenfoque))
    arr = np.array(img).astype(np.int16)
    if ruido:
        generador = np.random.default_rng(semilla)
        arr += generador.normal(0, ruido, arr.shape).astype(np.int16)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return arr[:, :, ::-1].copy()  # BGR, como mss


def partir(texto: str, tipografia, dibujo, ancho_max: int) -> list[str]:
    """El juego parte los nombres largos en dos lineas centradas bajo la tarjeta."""
    if dibujo.textlength(texto, font=tipografia) <= ancho_max:
        return [texto]
    palabras = texto.split()
    mejor = None
    for corte in range(1, len(palabras)):
        arriba, abajo = " ".join(palabras[:corte]), " ".join(palabras[corte:])
        peor = max(dibujo.textlength(arriba, font=tipografia),
                   dibujo.textlength(abajo, font=tipografia))
        if mejor is None or peor < mejor[0]:
            mejor = (peor, [arriba, abajo])
    return mejor[1] if mejor else [texto]


def etiqueta_del_juego(nombre_es, nombre_en, padre_es, padre_en, idioma: str) -> str:
    """Como escribe el juego el nombre: 'Chasis de Ash Prime' / 'Ash Prime Chassis'."""
    if idioma == "es":
        nombre, padre = nombre_es or nombre_en, padre_es or padre_en
        texto = f"{nombre} de {padre}" if padre else nombre
    else:
        nombre, padre = nombre_en, padre_en
        texto = f"{padre} {nombre}" if padre else nombre
    return " ".join(re.sub(r"<[^>]*>", " ", texto).split()).upper()


def elegir_objetos(con, n: int, semilla: int) -> list[tuple]:
    """Mezcla real: piezas Prime, mods, recursos y armas, siempre la misma con la semilla."""
    marcas = ", ".join("?" for _ in CATEGORIAS_RECOMPENSA)
    filas = con.execute(
        f"""
        SELECT i.id, i.nombre_es, i.nombre_en, p.nombre_es, p.nombre_en, i.categoria
          FROM items i LEFT JOIN items p ON p.id = i.padre_id
         WHERE i.categoria IN ({marcas}) AND i.nombre_en != ''
           AND (i.padre_id IS NULL OR p.es_prime = 1)
        """,
        CATEGORIAS_RECOMPENSA,
    ).fetchall()
    azar = random.Random(semilla)
    piezas = [f for f in filas if f[3]]
    sueltos = [f for f in filas if not f[3] and f[1]]
    azar.shuffle(piezas)
    azar.shuffle(sueltos)
    elegidos = piezas[: n // 2] + sueltos[: n - n // 2]
    azar.shuffle(elegidos)
    return elegidos


def memoria_mb() -> float:
    """Memoria residente del proceso, en MB (solo Windows; 0 en otro sitio)."""
    try:
        class Contadores(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        c = Contadores()
        c.cb = ctypes.sizeof(c)
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return 0.0
        return c.WorkingSetSize / 1024 / 1024
    except (AttributeError, OSError):
        return 0.0


def medir(n: int = 40, semilla: int = 7, guardar: Path | None = None, silencioso=False
          ) -> dict:
    con = indice.conectar()
    objetos = elegir_objetos(con, n, semilla)
    por_id = {o[0]: o for o in objetos}
    casador = Casador(con, CATEGORIAS_RECOMPENSA)
    nombres_validos = {
        o[0]: {normalizar(etiqueta_del_juego(o[1], o[2], o[3], o[4], "es")),
               normalizar(etiqueta_del_juego(o[1], o[2], o[3], o[4], "en")),
               normalizar(f"{o[4]} {o[2]}" if o[4] else o[2]),
               normalizar(f"{o[3] or o[4]} {o[1] or o[2]}" if o[3] or o[4] else (o[1] or o[2]))}
        for o in objetos
    }
    con.close()

    motor = MotorOCR()
    mem_antes = memoria_mb()
    motor.leer(pintar(["FORMA"], 32, 0, False, 0, 0))  # carga los modelos
    mem_cargado = memoria_mb()

    totales = Counter()
    por_condicion: dict[str, Counter] = {}
    tiempos = []
    fallos = []
    if guardar:
        guardar.mkdir(parents=True, exist_ok=True)

    for idioma in ("es", "en"):
        etiquetas = [(o[0], etiqueta_del_juego(o[1], o[2], o[3], o[4], idioma)) for o in objetos]
        for nombre_cond, tamano, ruido, contraste, desenfoque in CONDICIONES:
            cuenta = por_condicion.setdefault(nombre_cond, Counter())
            # De tres en tres, como las tarjetas de una reliquia abierta en grupo.
            for i in range(0, len(etiquetas), 3):
                grupo = etiquetas[i:i + 3]
                imagen = pintar([t for _, t in grupo], tamano, ruido, contraste, desenfoque,
                                semilla + i)
                inicio = time.perf_counter()
                reconocidos = reconocer(imagen, motor, casador, umbral=80)
                tiempos.append(time.perf_counter() - inicio)
                if guardar:
                    Image.fromarray(imagen[:, :, ::-1]).save(
                        guardar / f"{idioma}_{nombre_cond}_{i:02d}.png"
                    )
                # A cada etiqueta le corresponde el reconocido cuya caja cae en su columna.
                columna = imagen.shape[1] / len(grupo)
                for j, (esperado, texto) in enumerate(grupo):
                    en_columna = [
                        r for r in reconocidos
                        if j * columna <= r.caja[0] + r.caja[2] / 2 < (j + 1) * columna
                    ]
                    ids = {r.item_id for r in en_columna}
                    validos = nombres_validos[esperado]
                    mismo_nombre = all(
                        r.item_id == esperado or normalizar(r.nombre) in validos for r in en_columna
                    )
                    if ids and mismo_nombre:
                        veredicto = "bien"
                    elif not ids:
                        veredicto = "nada"
                    else:
                        veredicto = "OTRO"
                        fallos.append((idioma, nombre_cond, texto,
                                       [(r.texto_ocr, r.nombre) for r in en_columna
                                        if r.item_id != esperado
                                        and normalizar(r.nombre) not in validos]))
                    cuenta[veredicto] += 1
                    totales[veredicto] += 1

    franja = []
    cuatro = [etiqueta_del_juego(o[1], o[2], o[3], o[4], "es") for o in objetos[:4]]
    for _ in range(5):
        imagen = pintar(cuatro, 30, 6, False, 0, semilla, alto=453)
        inicio = time.perf_counter()
        reconocer(imagen, motor, casador, umbral=80)
        franja.append(time.perf_counter() - inicio)
    mem_despues = memoria_mb()
    resultado = {
        "ms_franja": 1000 * sum(franja) / len(franja),
        "objetos": len(objetos),
        "lecturas": sum(totales.values()),
        "bien": totales["bien"],
        "nada": totales["nada"],
        "otro": totales["OTRO"],
        "por_condicion": {k: dict(v) for k, v in por_condicion.items()},
        "ms_media": 1000 * sum(tiempos) / len(tiempos),
        "ms_max": 1000 * max(tiempos),
        "mem_mb_base": mem_antes,
        "mem_mb_cargado": mem_cargado,
        "mem_mb_final": mem_despues,
        "fallos": fallos,
        "nombres": {i: por_id[i][2] for i in por_id},
    }
    if not silencioso:
        imprimir(resultado)
    return resultado


def imprimir(r: dict) -> None:
    total = r["lecturas"]
    print(f"Objetos: {r['objetos']}  Lecturas: {total}")
    print(f"  bien: {r['bien']} ({100 * r['bien'] / total:.1f} %)")
    print(f"  nada: {r['nada']} ({100 * r['nada'] / total:.1f} %)")
    print(f"  OTRO: {r['otro']} ({100 * r['otro'] / total:.1f} %)  <- falsos positivos")
    for cond, c in r["por_condicion"].items():
        print(f"    {cond:10s} bien={c.get('bien', 0):3d} nada={c.get('nada', 0):3d} "
              f"OTRO={c.get('OTRO', 0):3d}")
    print(f"Tiempo por lectura (1536x200, 3 nombres): media {r['ms_media']:.0f} ms, "
          f"max {r['ms_max']:.0f} ms")
    print(f"Franja real (1536x453, 4 nombres): media {r['ms_franja']:.0f} ms")
    print(f"Memoria: base {r['mem_mb_base']:.0f} MB, con modelos {r['mem_mb_cargado']:.0f} MB, "
          f"al final {r['mem_mb_final']:.0f} MB")
    for idioma, cond, texto, vistos in r["fallos"]:
        print(f"  FALSO [{idioma}/{cond}] {texto!r} -> {vistos}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--semilla", type=int, default=7)
    p.add_argument("--guardar", type=Path, default=None)
    args = p.parse_args()
    if not indice.hay_indice():
        print("No hay indice construido; abre la app una vez o usa comprobar_fase1.py")
        return 2
    medir(args.n, args.semilla, args.guardar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
