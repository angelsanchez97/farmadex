"""Escanea por OCR la maestria del jugador desde Perfil > Equipamiento, paso a paso.

Uso: .venv/Scripts/python.exe herramientas/escanear_perfil.py [opciones]

  (sin opciones)     modo guiado: abre Perfil > Equipamiento, ve pasando categorias y
                     paginas y pulsa F9 en cada pantalla a la vista; F7 termina y guarda.
                     La categoria se lee de la propia pantalla, no hay que declararla.
  --auto             ademas de F9, captura solo cuando la pantalla cambia y se queda
                     quieta un momento (el usuario solo pasa paginas)
  --desde CARPETA    en vez de capturar, lee los PNG de una carpeta (capturas guardadas
                     o tests/fixtures/capturas_perfil) y los procesa igual
  --guardar CARPETA  donde dejar cada captura en PNG (por defecto junto a la BD del
                     usuario, en capturas_perfil/); --sin-guardar-capturas lo evita
  --solo-leer        ensena el resumen pero no toca la base de datos
  --db RUTA          base de datos del usuario (por defecto la real)
  --indice RUTA      indice del catalogo (por defecto el real; la app lo crea)
  --escala N         reescalado de la captura antes del OCR (1 = tal cual; 1.5 ayuda a 1080p)
  --motor rapidocr|winocr

El OCR de cada captura tarda unos 2 s y corre en segundo plano: se puede pasar
pagina y pulsar F9 sin esperar. Lo que no se lee con confianza queda como
"desconocido" y el resumen final lo lista; y el contador "COMPLETADO x/y" de cada
categoria se compara con lo leido para avisar cuando falten tarjetas.
"""

from __future__ import annotations

import argparse
import ctypes
import queue
import sys
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmadex import perfil as P  # noqa: E402
from farmadex.captura import pantalla  # noqa: E402
from farmadex.captura import perfil_equipo as PE  # noqa: E402
from farmadex.captura.ocr import ErrorMotorOCR, MotorOCR  # noqa: E402
from farmadex.config import RUTA_INDICE, RUTA_USUARIO_DB  # noqa: E402
from farmadex.datos import indice as modulo_indice  # noqa: E402
from farmadex.estado import usuario_db  # noqa: E402

# Clave de categoria (la que lee PE.leer_cabecera) -> como se llama en el menu del juego.
CATEGORIAS = (
    ("warframes", "WARFRAME"),
    ("primarias", "PRIMARIA"),
    ("secundarias", "SECUNDARIA"),
    ("cuerpo_a_cuerpo", "CUERPO A CUERPO"),
    ("roboticos", "ROBOTICO (centinelas, MOAs, sabuesos)"),
    ("companeros", "COMPANERO (kubrows, kavats...)"),
    ("vehiculos", "VEHICULO (archwings, necramechs, K-Drives)"),
    ("archcanones", "ARCHCANON"),
    ("archmelee", "ARCHMELEE"),
    ("amps", "AMP"),
)

VK = {"F7": 0x76, "F9": 0x78}
TECLA_CAPTURA, TECLA_FIN = "F9", "F7"


class Escaneo:
    """Acumula lo leido en todas las paginas y lo vuelca al final."""

    def __init__(self, indice, escala: float, motor: str, mostrar=print):
        self.indice = indice
        self.escala = escala
        self.motor = MotorOCR(motor)
        self.casador = PE.casador_equipamiento(indice)
        self.lecturas: list[P.LecturaOCR] = []
        self.rango_maestria: int | None = None
        self.completados: dict[str, tuple[int, int]] = {}
        self.sin_casar: Counter = Counter()
        self.paginas = 0
        self.paginas_sin_cabecera = 0
        self.mostrar = mostrar
        self._candado = threading.Lock()

    def procesar(self, imagen, pantalla_clave: str = "") -> PE.PaginaLeida:
        t = time.perf_counter()
        pagina = PE.leer_pagina(imagen, self.motor, self.casador, self.indice, escala=self.escala)
        categoria = pagina.categoria or pantalla_clave or "?"
        with self._candado:
            self.paginas += 1
            n = self.paginas
            if pagina.rango_maestria is not None:
                self.rango_maestria = pagina.rango_maestria
            if pagina.completado and pagina.categoria:
                self.completados[pagina.categoria] = pagina.completado
            if pagina.tarjetas and pagina.cabecera_en_y is None:
                self.paginas_sin_cabecera += 1
            self.lecturas.extend(P.desde_tarjetas(pagina.tarjetas, categoria))
            self.sin_casar.update(pagina.sin_casar)
        texto = (f"  pagina {n} [{categoria}]: {len(pagina.tarjetas)} objetos "
                 f"({len(pagina.dominadas)} dominados, {len(pagina.no_dominadas)} sin dominar, "
                 f"{len(pagina.a_medias)} a medias, {len(pagina.desconocidas)} sin leer) "
                 f"en {time.perf_counter() - t:.1f} s")
        if pagina.rango_maestria is not None:
            texto += f"  MR {pagina.rango_maestria}"
        if pagina.tarjetas and pagina.cabecera_en_y is None:
            texto += "  AVISO: no se ve la barra COMPLETADO; captura con la barra a la vista"
        self.mostrar(texto)
        for tarj in pagina.desconocidas:
            self.mostrar(f"    ? {tarj.nombre}: {tarj.motivo}")
        return pagina

    def finales(self) -> dict[str, P.LecturaOCR]:
        return P.desde_ocr.fusionar_lecturas(self.lecturas)

    def categorias_vistas(self) -> set[str]:
        return {l.pantalla for l in self.lecturas if l.pantalla and l.pantalla != "?"}

    def resumen(self) -> str:
        finales = list(self.finales().values())
        dominadas = [l for l in finales if l.estado == P.DOMINADO]
        medias = [l for l in finales if l.estado == P.A_MEDIAS]
        no_dom = [l for l in finales if l.estado == P.NO_DOMINADO]
        desconocidas = [l for l in finales if l.estado == P.DESCONOCIDO]
        lineas = [
            "",
            f"Paginas leidas: {self.paginas}",
            f"Objetos reconocidos: {len(finales)}   dominados: {len(dominadas)}   a medias: {len(medias)}   "
            f"sin dominar: {len(no_dom)}   sin leer el rango: {len(desconocidas)}",
        ]
        if self.rango_maestria is not None:
            lineas.append(f"Rango de maestria leido: {self.rango_maestria}")
        if self.completados:
            lineas.append("Comprobacion contra el contador del juego (COMPLETADO x/y):")
            for clave, (hechos, total) in sorted(self.completados.items()):
                vistos = [l for l in finales if l.pantalla == clave]
                dom = sum(1 for l in vistos if l.estado == P.DOMINADO)
                marca = "OK" if (dom == hechos and len(vistos) == total) else "FALTAN"
                lineas.append(f"  {marca} {clave}: {dom} dominados de los {hechos} que dice el juego; "
                              f"{len(vistos)} tarjetas de {total}")
        vistas = self.categorias_vistas()
        pendientes = [nombre for clave, nombre in CATEGORIAS if clave not in vistas]
        if pendientes:
            lineas.append("Categorias sin escanear: " + ", ".join(pendientes))
        if desconocidas:
            lineas.append("No se pudo leer el rango de (repite esa pagina para arreglarlo):")
            lineas += [f"  - {l.nombre}  [{l.pantalla}]" for l in sorted(desconocidas, key=lambda l: l.nombre)]
        ruido = [t for t, _ in self.sin_casar.most_common(15) if len(t) >= 4]
        if ruido:
            lineas.append("Textos leidos que no son ningun objeto del catalogo (los 15 mas vistos):")
            lineas.append("  " + " | ".join(ruido))
        return "\n".join(lineas)


# --- teclado y captura ------------------------------------------------------------------


def _pulsada(nombre: str) -> bool:
    """Flanco de pulsacion de una tecla global (GetAsyncKeyState, bit 0 = "desde la ultima vez")."""
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK[nombre]) & 0x0001)


def _pitar(ok: bool = True) -> None:
    try:
        import winsound

        winsound.Beep(1200 if ok else 400, 120)
    except Exception:  # noqa: BLE001 - sin altavoz no pasa nada
        pass


def _capturar_juego():
    region = pantalla.region_juego() or pantalla.region_pantalla_completa()
    return pantalla.capturar(region)


def _guardar_png(imagen, carpeta: Path, n: int) -> None:
    try:
        import cv2

        carpeta.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(carpeta / f"captura_{n:03d}_{time.strftime('%Y%m%d_%H%M%S')}.png"), imagen)
    except Exception as e:  # noqa: BLE001
        print(f"  (no se pudo guardar la captura: {e})")


def modo_guiado(escaneo: Escaneo, guardar_en: Path | None, auto: bool) -> None:
    for tecla in VK:
        ctypes.windll.user32.GetAsyncKeyState(VK[tecla])  # limpia flancos previos
    pantalla.declarar_dpi()
    print("Abre en el juego: menu (Esc) > PERFIL. Con la portada a la vista pulsa F9 una vez")
    print("(lee tu rango de maestria). Luego EQUIPAMIENTO y, categoria por categoria:")
    for _, nombre in CATEGORIAS:
        print(f"    - {nombre}")
    print(f"En cada pagina a la vista pulsa {TECLA_CAPTURA} (pitido agudo = capturada; grave = fallo)."
          + (" Modo automatico: tambien captura solo al pasar pagina." if auto else ""))
    print(f"Deja siempre a la vista la barra COMPLETADO x/y. Al terminar, {TECLA_FIN}.\n")

    cola: queue.Queue = queue.Queue()

    def trabajador():
        while True:
            imagen = cola.get()
            if imagen is None:
                return
            try:
                escaneo.procesar(imagen)
            except Exception as e:  # noqa: BLE001 - una captura mala no tira la sesion
                print(f"  ERROR leyendo una captura: {e}")
            finally:
                cola.task_done()

    hilo = threading.Thread(target=trabajador, daemon=True)
    hilo.start()
    detector = PE.DetectorPagina(quietas=3) if auto else None
    n = 0
    try:
        while True:
            time.sleep(0.05 if not auto else 0.3)
            if _pulsada(TECLA_FIN):
                break
            capturar = _pulsada(TECLA_CAPTURA)
            if not (auto or capturar):
                continue
            imagen = _capturar_juego()
            if imagen is None:
                if capturar:
                    _pitar(False)
                    print("  No se pudo capturar la pantalla.")
                continue
            if not capturar and detector is not None and not detector.observar(imagen):
                continue
            n += 1
            _pitar(True)
            if guardar_en is not None:
                _guardar_png(imagen, guardar_en, n)
            cola.put(imagen)
    finally:
        pendientes = cola.qsize()
        if pendientes:
            print(f"Terminando de leer {pendientes} capturas pendientes...")
        cola.join()
        cola.put(None)


def modo_carpeta(escaneo: Escaneo, carpeta: Path) -> int:
    import cv2

    rutas = sorted(p for p in carpeta.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"))
    if not rutas:
        print(f"No hay imagenes en {carpeta}")
        return 0
    for ruta in rutas:
        imagen = cv2.imread(str(ruta), cv2.IMREAD_COLOR)
        if imagen is None:
            print(f"  {ruta.name}: no se pudo leer")
            continue
        print(f"{ruta.name}:")
        # El nombre del fichero sirve de categoria si la pantalla no la trae ("warframes_01.png").
        escaneo.procesar(imagen, ruta.stem.split("_")[0].lower())
    return len(rutas)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--desde", type=Path)
    ap.add_argument("--guardar", type=Path, default=RUTA_USUARIO_DB.parent / "capturas_perfil")
    ap.add_argument("--sin-guardar-capturas", action="store_true")
    ap.add_argument("--solo-leer", action="store_true")
    ap.add_argument("--db", type=Path, default=RUTA_USUARIO_DB)
    ap.add_argument("--indice", type=Path, default=RUTA_INDICE)
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--motor", default="rapidocr")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not args.indice.exists():
        print(f"No existe el indice {args.indice}: abre Farmadex una vez para que lo construya.")
        return 2
    indice = modulo_indice.conectar(args.indice)
    escaneo = Escaneo(indice, args.escala, args.motor)
    try:
        escaneo.motor.leer(None)
    except ErrorMotorOCR as e:
        print(f"El motor OCR no arranca: {e}")
        return 2

    if args.desde:
        if modo_carpeta(escaneo, args.desde) == 0:
            return 1
    else:
        if sys.platform != "win32":
            print("La captura en vivo solo funciona en Windows; usa --desde CARPETA.")
            return 2
        modo_guiado(escaneo, None if args.sin_guardar_capturas else args.guardar, args.auto)

    print(escaneo.resumen())
    if not escaneo.lecturas and escaneo.rango_maestria is None:
        print("No se reconocio ningun objeto: no se guarda nada.")
        return 1
    if args.solo_leer:
        print("Solo lectura: no se ha guardado nada.")
        return 0
    usuario = usuario_db.conectar(args.db)
    resultado = P.guardar_desde_ocr(usuario, indice, escaneo.lecturas, escaneo.rango_maestria,
                                    completados=escaneo.completados)
    total = P.resumen(usuario) or {}
    print(f"Guardado en {args.db}: {resultado.guardadas} objetos con rango de esta pasada; "
          f"el perfil acumula {total.get('objetos_xp', '?')} objetos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
