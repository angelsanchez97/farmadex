"""Mide, etapa por etapa, lo que tarda el camino de abrir una reliquia.

Recorre lo mismo que hace la aplicacion cuando EE.log avisa de la pantalla de
recompensas: el camino real (`recompensas_rapidas.leer_pantalla`: fila de nombres,
casado escalonado y, si hace falta, la franja entera), `completar`, precios de
warframe.market, `puntuar` y pintado de las etiquetas. La espera antes de leer es
la de verdad (`DisparadorAutomatico.ESPERA_MS`). Saca una tabla en milisegundos
por etapa, con la primera vuelta (en frio) separada del resto; la franja entera
se sigue midiendo aparte, como respaldo.

No hay capturas reales de la pantalla de recompensas en el repositorio, asi que
se genera una pantalla sintetica a 1920x1080 con cuatro tarjetas y los nombres
tal y como los pinta el juego (mayusculas, blanco roto sobre azul oscuro), del
mismo tamano que la franja real. La captura de pantalla si es real (mss sobre el
escritorio): lo que haya en pantalla no cambia lo que tarda.

Uso: .venv/Scripts/python.exe herramientas/medir_reliquia.py [--vueltas 3]
                              [--sin-red] [--guardar carpeta] [--nombres A B C D]
Hace falta el indice real construido (la app lo crea la primera vez).
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmadex.captura import ocr, pantalla  # noqa: E402
from farmadex.captura import recompensas_rapidas as rapidas  # noqa: E402
from farmadex.captura.comparador import puntuar  # noqa: E402
from farmadex.captura.ocr import Casador, MotorOCR, reconocer  # noqa: E402
from farmadex.captura.reliquias import (  # noqa: E402
    CATEGORIAS_RECOMPENSA,
    FRANJA,
    DisparadorAutomatico,
    Recompensa,
    _quitar_repetidos,
    completar,
)
from farmadex.datos import indice  # noqa: E402

# Lo que se ve en una pantalla tipica: cuatro piezas prime, con su "PLANO" debajo
# cuando toca, en espanol como lo escribe el juego.
NOMBRES_POR_DEFECTO = (
    "SISTEMAS DE ASH PRIME\nPLANO",
    "CANON DE BRATON PRIME",
    "RECEPTOR DE AKBOLTO PRIME",
    "ENLACE DE AKBOLTO PRIME",
)
OTRAS_PANTALLAS = (
    ("NEUROPTICA DE ASH PRIME", "CULATA DE BRATON PRIME", "PLANO DE AKBOLTO PRIME", "CHASIS DE ASH PRIME\nPLANO"),
    ("RECEPTOR DE BRATON PRIME", "PLANO DE ASH PRIME", "CANON DE AKBOLTO PRIME", "FORMA"),
    ("SISTEMAS DE ASH PRIME", "FORMA", "FORMA", "ENLACE DE AKBOLTO PRIME"),
)
FONDO = (12, 16, 22)
TEXTO = (232, 236, 245)
FUENTES = ("seguisb.ttf", "segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf")
PANTALLA = (1920, 1080)
SALTO = chr(10)


def _fuente(tamano: int) -> ImageFont.FreeTypeFont:
    for nombre in FUENTES:
        try:
            return ImageFont.truetype(nombre, tamano)
        except OSError:
            continue
    return ImageFont.load_default()


def _partir_en_lineas(dibujo, texto: str, fuente, ancho_max: float) -> list[str]:
    """Como el juego: el nombre que no cabe en la tarjeta baja a una segunda linea."""
    lineas: list[str] = []
    for parrafo in texto.split(SALTO):
        actual = ""
        for palabra in parrafo.split():
            prueba = f"{actual} {palabra}".strip()
            caja = dibujo.textbbox((0, 0), prueba, font=fuente)
            if actual and caja[2] - caja[0] > ancho_max:
                lineas.append(actual)
                actual = palabra
            else:
                actual = prueba
        lineas.append(actual)
    return lineas


def pantalla_sintetica(nombres, tamano=PANTALLA, letra=None):
    """Pantalla entera del juego, en BGR, con las tarjetas donde las pone el juego.

    Tarjetas centradas del ancho medido (`rapidas.ranuras`) y el nombre en la fila
    de nombres (una linea en el 41 % del alto; dos, del 39 % al 42 %).
    """
    ancho, alto = tamano
    img = Image.new("RGB", tamano, FONDO)
    dibujo = ImageDraw.Draw(img)
    letra = letra or max(10, round(alto * 0.017))
    fuente = _fuente(letra)
    huecos = rapidas.ranuras(pantalla.Region(0, 0, ancho, alto), len(nombres))
    for (x0, x1), nombre in zip(huecos, nombres):
        cx = (x0 + x1) / 2
        dibujo.rounded_rectangle((x0 + 6, alto * 0.22, x1 - 6, alto * 0.47), 10, outline=(60, 70, 90), width=3)
        lineas = _partir_en_lineas(dibujo, nombre, fuente, (x1 - x0) * 0.85) if nombre else []
        paso = letra + 4
        y = alto * 0.41 - len(lineas) * paso / 2
        for j, linea in enumerate(lineas):
            caja = dibujo.textbbox((0, 0), linea, font=fuente)
            w = caja[2] - caja[0]
            dibujo.text((cx - w / 2, y + j * paso), linea, fill=TEXTO, font=fuente)
    return np.array(img)[:, :, ::-1].copy()


def recortar(imagen, region_total: pantalla.Region, region: pantalla.Region):
    x = region.x - region_total.x
    y = region.y - region_total.y
    return np.ascontiguousarray(imagen[y : y + region.alto, x : x + region.ancho])


class _Cronometro:
    def __init__(self):
        self.tiempos: dict[str, list[float]] = {}

    def medir(self, etapa: str, funcion, *args, **kwargs):
        inicio = time.perf_counter()
        resultado = funcion(*args, **kwargs)
        self.tiempos.setdefault(etapa, []).append((time.perf_counter() - inicio) * 1000)
        return resultado

    def anotar(self, etapa: str, ms: float) -> None:
        self.tiempos.setdefault(etapa, []).append(ms)

    def tabla(self) -> str:
        filas = [f"{'etapa':<44}{'1a (frio)':>12}{'resto (mediana)':>18}{'n':>4}"]
        for etapa, valores in self.tiempos.items():
            resto = statistics.median(valores[1:]) if len(valores) > 1 else float("nan")
            filas.append(f"{etapa:<44}{valores[0]:>12.1f}{resto:>18.1f}{len(valores):>4}")
        return "\n".join(filas)


class _MotorCacheado:
    """Devuelve lo que ya leyo el motor de verdad: sirve para medir solo el casado."""

    def __init__(self, leidos):
        self.leidos = leidos

    def leer(self, imagen):
        return list(self.leidos)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vueltas", type=int, default=3, help="repeticiones (la primera es en frio)")
    ap.add_argument("--sin-red", action="store_true", help="no consultar warframe.market")
    ap.add_argument("--guardar", type=Path, help="carpeta donde dejar la pantalla sintetica")
    ap.add_argument("--nombres", nargs="+", help="1-4 nombres tal y como salen en pantalla")
    ap.add_argument("--sin-precalentar", action="store_true", help="como antes: la 1a lectura paga la 1a inferencia")
    args = ap.parse_args()

    if not indice.hay_indice():
        print("No hay indice construido: arranca la aplicacion una vez.", file=sys.stderr)
        return 1

    nombres = args.nombres or list(NOMBRES_POR_DEFECTO)
    crono = _Cronometro()
    total_pantalla = pantalla.Region(0, 0, *PANTALLA)
    franja = total_pantalla.recortar(*FRANJA)
    pantalla_entera = pantalla_sintetica(nombres)
    imagen_franja = recortar(pantalla_entera, total_pantalla, franja)
    if args.guardar:
        args.guardar.mkdir(parents=True, exist_ok=True)
        Image.fromarray(pantalla_entera[:, :, ::-1]).save(args.guardar / "pantalla_sintetica.png")
        Image.fromarray(imagen_franja[:, :, ::-1]).save(args.guardar / "franja_sintetica.png")
    print(f"Franja: {franja.ancho}x{franja.alto} px de una pantalla de {PANTALLA[0]}x{PANTALLA[1]}")

    # -- arranque: lo que hace LectorBase.iniciar y lo que NO hace (cargar el motor) --
    MotorOCR.descargar()
    motor = MotorOCR("rapidocr")
    con = indice.conectar()
    casador = crono.medir("arranque: construir Casador (indice real)", Casador, con, CATEGORIAS_RECOMPENSA)
    crono.medir("arranque: cargar modelo OCR", motor._cargar)
    if not args.sin_precalentar:
        crono.medir("arranque: precalentar (lectura de prueba)", motor.precalentar)

    # -- captura real de la pantalla (lo que haya) ---------------------------------
    pantalla.declarar_dpi()
    region_real = pantalla.region_pantalla_completa().recortar(*FRANJA)
    for _ in range(args.vueltas):
        capturada = crono.medir("captura: mss de la franja", pantalla.capturar, region_real)
    if capturada is None:
        print("Aviso: no se pudo capturar la pantalla; se sigue con la sintetica", file=sys.stderr)

    # -- OCR y casado sobre la franja sintetica -----------------------------------
    leidos = None
    reconocidos = None
    for _ in range(args.vueltas):
        crono.medir("ocr: preparar (gris + contraste)", ocr.preparar, imagen_franja)
        leidos = crono.medir("ocr: motor.leer (deteccion + reconocimiento)", motor.leer, imagen_franja)
        reconocidos = crono.medir(
            "emparejado: unir_filas + agrupar + casar", reconocer, imagen_franja, _MotorCacheado(leidos), casador, 80
        )
    # Lo realista: cada reliquia trae nombres distintos, y ONNX Runtime paga una
    # planificacion de memoria por cada ancho de texto nuevo. Repetir la misma
    # imagen da un numero optimista; esto mide pantallas distintas.
    for nombres_nuevos in OTRAS_PANTALLAS:
        otra = recortar(pantalla_sintetica(nombres_nuevos), total_pantalla, franja)
        crono.medir("ocr: motor.leer, pantalla con nombres nuevos", motor.leer, otra)
    print("\nOCR leyo:", " | ".join(f"{l.texto!r} ({l.confianza:.2f})" for l in leidos))
    unicos = _quitar_repetidos(reconocidos)
    print("Casado:  ", " | ".join(f"{r.texto_ocr!r} -> {r.nombre} ({r.puntuacion:.0f})" for r in unicos))
    if len(unicos) != len(nombres):
        print(f"AVISO: se esperaban {len(nombres)} recompensas y se casaron {len(unicos)}")

    # -- el camino real: leer_pantalla (fila de nombres + casado escalonado) ------------
    piezas = rapidas.catalogo_de_piezas(casador, con)
    escalonado = rapidas.CasadorEscalonado(piezas, casador.restringido(rapidas.ids_reliquias(con)), None)
    lectura = None
    pantallas = [nombres] * args.vueltas + [list(p) for p in OTRAS_PANTALLAS]
    for k, nombres_pantalla in enumerate(pantallas):
        entera = pantalla_sintetica(nombres_pantalla)

        def capturar(region, entera=entera):
            return recortar(entera, total_pantalla, region)

        etiqueta = "camino real: leer_pantalla" if k < args.vueltas else "camino real: leer_pantalla, nombres nuevos"
        res = crono.medir(etiqueta, rapidas.leer_pantalla, capturar, total_pantalla, motor, escalonado,
                          len(nombres_pantalla), None, {})
        if k == 0:
            lectura = res
    if lectura is not None:
        print("Camino real (" + lectura.via + "):",
              " | ".join(f"{r.texto_ocr!r} -> {r.nombre} ({r.puntuacion:.0f})" for r in lectura.recompensas))
        if len(lectura.recompensas) != len(nombres):
            print(f"AVISO: el camino real caso {len(lectura.recompensas)} de {len(nombres)}")

    # -- el camino de respaldo: nada en la franja -> ventana entera -----------------
    vacia = pantalla_sintetica(["" for _ in nombres])
    for _ in range(args.vueltas):
        crono.medir("respaldo: OCR de la ventana entera 1920x1080", motor.leer, vacia)
        crono.medir("respaldo: OCR de la franja vacia", motor.leer, recortar(vacia, total_pantalla, franja))

    # -- completar + pintado (nombres en pantalla) ---------------------------------
    def _recompensas():
        return [
            Recompensa(r.item_id, r.nombre, r.texto_ocr, (franja.x + r.caja[0], franja.y + r.caja[1], r.caja[2], r.caja[3]))
            for r in unicos
        ]

    from PySide6.QtWidgets import QApplication

    from farmadex.ui.etiquetas import EtiquetasRecompensas

    app = QApplication.instance() or QApplication([])
    etiquetas = EtiquetasRecompensas()
    for _ in range(args.vueltas):
        recompensas = _recompensas()
        crono.medir("completar: indice (ducados, boveda, slug)", completar, recompensas, con)

        def _pintar():
            etiquetas.mostrar(recompensas)
            app.processEvents()
            etiquetas.grab()  # fuerza paintEvent

        crono.medir("pintado: etiquetas.mostrar + paintEvent", _pintar)

    # -- precios y veredicto -------------------------------------------------------
    recompensas = _recompensas()
    completar(recompensas, con)
    slugs = [r.market_slug for r in recompensas if r.market_slug]
    print(f"\nSlugs con precio que pedir: {slugs}")
    if args.sin_red:
        for _ in range(args.vueltas):
            crono.medir("comparador: puntuar sin red", puntuar, _recompensas(), con, None)
    else:
        from farmadex.online.market import Market

        market = crono.medir("precios: crear Market (cliente http)", Market)
        for vuelta in range(args.vueltas):
            etiqueta = "precios: 4 slugs en serie, EN FRIO (sin cache)" if vuelta == 0 else "precios: 4 slugs en serie, EN CALIENTE (cache)"
            inicio = time.perf_counter()
            for slug in slugs:
                t0 = time.perf_counter()
                p = market.precios(slug)
                ms = (time.perf_counter() - t0) * 1000
                crono.anotar(f"  precios: {slug} ({'frio' if vuelta == 0 else 'caliente'})", ms)
                if p.error:
                    print(f"  {slug}: error {p.error}")
            crono.anotar(etiqueta, (time.perf_counter() - inicio) * 1000)
        for _ in range(args.vueltas):
            crono.medir("comparador: puntuar con precios en cache", puntuar, _recompensas(), con, market.precios)
        # Veredicto en frio: cliente nuevo, cache vacia, igual que la primera reliquia de la sesion.
        crono.medir("comparador: puntuar EN FRIO (Market nuevo)", puntuar, _recompensas(), con, Market().precios)
        market.cerrar()

    # -- veredicto pintado encima ------------------------------------------------------
    def _marcar():
        etiquetas.marcar_veredicto(recompensas, type("V", (), {"seguro": True})())
        app.processEvents()
        etiquetas.grab()

    for _ in range(args.vueltas):
        crono.medir("pintado: marcar_veredicto + paintEvent", _marcar)

    con.close()
    print("\n" + crono.tabla())

    t = {k: v for k, v in crono.tiempos.items()}

    def _frio(k):
        return t[k][0] if k in t else 0.0

    def _cal(k):
        return statistics.median(t[k][1:]) if k in t and len(t[k]) > 1 else _frio(k)

    def _nuevo(k):  # mediana de todas las vueltas: cada una es una pantalla distinta
        return statistics.median(t[k]) if k in t else 0.0

    espera = DisparadorAutomatico.ESPERA_MS
    # La captura de la fila es mas pequena que la de la franja: la de la franja es cota alta.
    hasta_nombre_frio = (
        espera + (_frio("arranque: cargar modelo OCR") if args.sin_precalentar else 0) + _frio("captura: mss de la franja")
        + _frio("camino real: leer_pantalla")
        + _frio("completar: indice (ducados, boveda, slug)") + _frio("pintado: etiquetas.mostrar + paintEvent")
    )
    hasta_nombre_cal = (
        espera + _cal("captura: mss de la franja") + _nuevo("camino real: leer_pantalla, nombres nuevos")
        + _cal("completar: indice (ducados, boveda, slug)") + _cal("pintado: etiquetas.mostrar + paintEvent")
    )
    print(SALTO + f"Estimacion desde el aviso de EE.log (camino real, incluye ESPERA_MS = {espera}):")
    print(f"  hasta ver los NOMBRES:  1a reliquia {hasta_nombre_frio:.0f} ms | siguientes {hasta_nombre_cal:.0f} ms")
    if not args.sin_red:
        print(
            f"  hasta el VEREDICTO:     1a reliquia {hasta_nombre_frio + _frio('comparador: puntuar EN FRIO (Market nuevo)'):.0f} ms"
            f" | siguientes (cache 10 min) {hasta_nombre_cal + _cal('comparador: puntuar con precios en cache'):.0f} ms"
            f" | siguientes sin cache ~{hasta_nombre_cal + _frio('precios: 4 slugs en serie, EN FRIO (sin cache)'):.0f} ms"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
