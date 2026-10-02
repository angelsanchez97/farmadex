"""Autoprueba: Farmadex recorrido como lo usaria un jugador, sin ventanas visibles.

Sirve para dar el visto bueno antes de publicar una version (y para compararla con la
anterior): arranca la ventana de verdad con el indice completo, le pone delante capturas
reales del juego (se inyectan en `captura.pantalla`, como si fueran la pantalla) y recorre
los flujos reales apuntando aciertos, tiempos y cualquier fallo:

- leer una build, las recompensas de una reliquia (por atajo y por aviso de EE.log), un
  agrietado, lo que hay bajo el cursor y la tabla de una reliquia al pasar el raton;
- buscar tecla a tecla en Buscar, desde el Tablero y en el modo juego;
- abrir fichas grandes, cambiar de seccion, minimizar y restaurar, bienvenida y guia;
- actualizar al abrir con la red simulada (sin red, colgada, version nueva).

Uso:
    Farmadex.exe --autoprueba <carpeta> [opciones]
    python -m farmadex.autoprueba <carpeta> [opciones]

Opciones:
    --indice RUTA          indice.sqlite completo (se copia; el original no se toca)
    --datos RUTA           carpeta "Farmadex" de datos con datos/ (catalogos): con ellos la
                           red simulada contesta "datos al dia" y el arranque es el normal
    --capturas CARPETA     (se puede repetir) capturas reales con su verdad.json; el tipo
                           (recompensas, build o agrietado) sale del formato de cada entrada
    --hover CARPETA        (se puede repetir) capturas con reliquias a la vista (inventario)
    --vista CARPETA        banco de lo que sale solo sin atajo: positivos/tooltip_inventario (con
                           verdad.json) y negativos/ (pantallas donde no tiene que salir nada)
    --red-fixtures CARPETA respuestas guardadas (worldstate, market...) de la red simulada
    --nucleos N            limita el proceso a N nucleos (simula un PC normal)
    --carga N              N procesos que se comen un nucleo cada uno mientras se prueba
    --solo a,b             solo esos flujos (ver FLUJOS)
    --etiqueta TEXTO       nombre de esta pasada en el informe
    --perfil FLUJO         perfila (cProfile) ese flujo y deja perfil_<flujo>.txt
    --depurar              registro con todo el detalle (DEBUG)
    --sin-red              toda la pasada sin conexion (arrancar sin internet)
    --precios-reales       antes de cortar la red, baja la foto diaria de precios de la release
                           de verdad (unica salida a internet de la pasada); luego se buscan
                           precios en ella ya sin red (flujo precios_reales)
    --precios-base URL     de donde bajarla (un servidor local de pruebas) en vez de GitHub
    --vigia-ms N           apunta las paradas de la ventana de mas de N ms (120 por defecto)

Todo lo que escribe va dentro de <carpeta>: los datos (FARMADEX_DATOS, con su propio
candado de instancia), el registro, resultado.json, informe.txt y las capturas PNG. Nunca
toca el Farmadex abierto del usuario, ni su carpeta de datos, ni la red de verdad (todas las
peticiones las contesta la red simulada) ni el EE.log del juego. Sale con 0 si todo cumple.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import sqlite3
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path

ARGUMENTO = "--autoprueba"
ARGUMENTO_CARGA = "--autoprueba-carga"

FLUJOS = (
    "instancia", "actualizar_al_abrir", "precios_reales", "arranque", "recompensas", "cursor", "build", "agrietado",
    "hover", "vista_precio", "vista_riven", "vista_build", "vista_reposo", "tarjeta_app", "rafagas", "buscar", "fichas", "secciones", "modo_juego", "refrescos", "minimizar",
    "bienvenida", "guia", "cierre",
)

# Criterios del visto bueno (ms). "Tecla" es lo que la ventana tarda en atender una
# pulsacion; "resultados", desde la ultima tecla hasta ver la lista.
CRITERIOS = {
    "build_ms": 1000,
    # Lo que sale solo (precio, agrietado, build): de aparecer en pantalla a verse el dato.
    "vista_ms": 1000,
    "recompensas_ms": 500,
    # Una tecla "al instante": la ventana no puede quedarse sin atender el teclado mas de
    # 0,1 s (el umbral clasico de respuesta instantanea) y en 9 de cada 10 busquedas, ni 50 ms.
    "tecla_ms": 100,
    "tecla_p90_ms": 50,
    "resultados_ms": 150,
    "ficha_ms": 200,
    "seccion_ms": 200,
    "refresco_ms": 100,
    # Ventana parada (sin atender teclas ni raton) por cualquier motivo durante los flujos.
    "congelacion_ms": 200,
}

EXTENSIONES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

# Busquedas tecla a tecla: (texto, lo que tiene que salir primero en ingles o None si
# no tiene que salir nada). Mezcla castellano, ingles, erratas y nodos.
CONSULTAS = (
    ("ash prime systems", "Ash Prime Systems"),
    ("serracion", "Serration"),
    ("citrine prime", "Citrine Prime"),
    ("axi a1", "Axi A1 Relic"),
    ("hepit", None),
    ("supervivencia", None),
    ("rhino neuroptics", "Rhino"),
    ("forma", "Forma"),
    ("celula orokin", "Orokin Cell"),
    ("ahs prime", "Ash Prime"),
    ("qwxz ptlk", ""),
)


# -- entorno (antes de importar nada de farmadex que lea rutas) --------------------


def _leer_argumentos(argv: list[str]) -> dict:
    opciones: dict = {"capturas": [], "hover": [], "solo": None, "nucleos": 0, "carga": 0,
                      "indice": None, "datos": None, "red_fixtures": None, "etiqueta": "", "perfil": None,
                      "vigia_ms": 120, "sin_red": False, "vista": None,
                      "precios_reales": False, "precios_base": None}
    resto = [a for a in argv if a != ARGUMENTO]
    i = 0
    carpeta = None
    while i < len(resto):
        a = resto[i]
        valor = resto[i + 1] if i + 1 < len(resto) else None
        if a in ("--capturas", "--hover"):
            opciones[a[2:]].append(valor)
            i += 2
        elif a in ("--indice", "--datos", "--red-fixtures", "--etiqueta", "--perfil", "--vista", "--precios-base"):
            opciones[a[2:].replace("-", "_")] = valor
            i += 2
        elif a in ("--nucleos", "--carga", "--vigia-ms"):
            opciones[a[2:].replace("-", "_")] = int(valor or 0)
            i += 2
        elif a == "--sin-pasivo":
            opciones["sin_pasivo"] = True
            i += 1
        elif a == "--depurar":
            opciones["depurar"] = True
            i += 1
        elif a == "--sin-red":
            opciones["sin_red"] = True
            i += 1
        elif a == "--precios-reales":
            opciones["precios_reales"] = True
            i += 1
        elif a == "--solo":
            opciones["solo"] = set((valor or "").split(","))
            i += 2
        elif not a.startswith("--") and carpeta is None:
            carpeta = a
            i += 1
        else:
            i += 1
    if carpeta is None:
        raise SystemExit("Falta la carpeta de la autoprueba: --autoprueba <carpeta>")
    opciones["carpeta"] = Path(carpeta).resolve()
    return opciones


def _mascara_nucleos(n: int) -> int:
    """N nucleos fisicos distintos (los logicos pares: con SMT los impares son sus gemelos)."""
    total = os.cpu_count() or n
    paso = 2 if total >= 2 * n else 1
    mascara = 0
    for k in range(n):
        mascara |= 1 << ((k * paso) % total)
    return mascara


def _fijar_afinidad(mascara: int, manejador=None) -> bool:
    if os.name != "nt":
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    h = manejador if manejador is not None else kernel32.GetCurrentProcess()
    return bool(kernel32.SetProcessAffinityMask(ctypes.c_void_p(int(h)), ctypes.c_size_t(mascara)))


def preparar_entorno(opciones: dict) -> None:
    """Carpeta de datos propia, sin pantalla y, si se pide, con los nucleos de un PC normal."""
    carpeta: Path = opciones["carpeta"]
    datos = carpeta / "datos"
    if datos.exists():
        shutil.rmtree(datos, ignore_errors=True)
    (datos / "Farmadex" / "db").mkdir(parents=True, exist_ok=True)
    os.environ["FARMADEX_DATOS"] = str(datos)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["FARMADEX_SIN_BIENVENIDA"] = "1"
    # Sin pantalla Qt no encuentra las fuentes: con las de Windows el texto se maqueta como
    # en la ventana de verdad (tiempos reales) y las capturas PNG se pueden leer.
    fuentes = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if fuentes.is_dir():
        os.environ.setdefault("QT_QPA_FONTDIR", str(fuentes))
    opciones["cpus_reales"] = os.cpu_count() or 1
    if opciones["nucleos"]:
        n = opciones["nucleos"]
        _fijar_afinidad(_mascara_nucleos(n))
        # Un PC de N nucleos se lo dice a quien pregunte (el OCR decide sus hilos por esto).
        os.cpu_count = lambda: n  # type: ignore[assignment]


def copiar_indice(origen: Path, destino: Path) -> None:
    """Copia coherente (API de copia de SQLite) aunque el original este abierto."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    fuente = sqlite3.connect(f"file:{origen.as_posix()}?mode=ro", uri=True)
    try:
        copia = sqlite3.connect(destino)
        try:
            fuente.backup(copia)
        finally:
            copia.close()
    finally:
        fuente.close()


def catalogo_market_de(indice: Path) -> bytes | None:
    """Respuesta de `/v2/items` de warframe.market rehecha con el emparejado del indice
    (slug, id y uniqueName como gameRef). None si el indice no tiene emparejado."""
    import sqlite3

    try:
        con = sqlite3.connect(f"file:{indice}?mode=ro", uri=True)
        try:
            filas = con.execute(
                "SELECT unique_name, market_slug, market_id, nombre_en FROM items "
                "WHERE market_slug IS NOT NULL AND market_slug <> ''"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not filas:
        return None
    datos = [{"id": mid, "slug": slug, "gameRef": un, "i18n": {"en": {"name": nombre or ""}}}
             for un, slug, mid, nombre in filas]
    return json.dumps({"apiVersion": "0.0.0", "data": datos, "error": None}).encode("utf-8")


def buscar_indice(opciones: dict) -> Path | None:
    if opciones.get("indice"):
        return Path(opciones["indice"])
    if opciones.get("datos"):
        ruta = Path(opciones["datos"]) / "db" / "indice.sqlite"
        if ruta.exists():
            return ruta
    return None


# -- procesos que cargan la CPU ------------------------------------------------------


def lanzar_carga(n: int, mascara: int | None) -> list:
    import subprocess

    procesos = []
    for _ in range(n):
        if getattr(sys, "frozen", False):
            orden = [sys.executable, ARGUMENTO_CARGA]
        else:
            orden = [sys.executable, "-c", "while True: pass"]
        p = subprocess.Popen(orden, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if mascara:
            _fijar_afinidad(mascara, p._handle)  # noqa: SLF001 - el manejador de Windows del hijo
        procesos.append(p)
    return procesos


def parar_carga(procesos: list) -> None:
    for p in procesos:  # solo los que lanzo esta autoprueba, por su PID
        try:
            p.kill()
            p.wait(5)
        except Exception:  # noqa: BLE001
            pass


def bucle_carga() -> int:  # pragma: no cover - proceso de relleno
    while True:
        pass


# -- red simulada ------------------------------------------------------------------------


class RedSimulada:
    """Contesta todas las peticiones HTTP sin salir del PC.

    Se engancha a `httpx.Client` (lo usan todas las descargas de Farmadex) y ademas cierra
    los sockets hacia fuera por si algo intentara saltarsela. `modo`: "normal" (datos al
    dia, sin version nueva), "sin_red", "colgada" (no contesta) o "version_nueva".
    """

    def __init__(self, fixtures: Path | None, estado_datos: dict, version_actual: str):
        self.fixtures = fixtures
        self.estado = estado_datos
        self.version_actual = version_actual
        self.modo = "normal"
        self.peticiones: list[str] = []
        self.retraso_s = 0.05
        self.instalador = b""
        self.huella = ""
        # Catalogo /v2/items de warframe.market (JSON), sacado del indice de origen: al
        # reconstruir el indice (cambio de esquema) el emparejado de precios sale igual que
        # en el indice real en vez de perderse.
        self.catalogo_market: bytes | None = None
        self._cerrojo = threading.Lock()

    def _fixture(self, nombre: str):
        if self.fixtures is None:
            return None
        ruta = self.fixtures / nombre
        return ruta.read_bytes() if ruta.exists() else None

    def responder(self, peticion):
        import httpx

        url = str(peticion.url)
        with self._cerrojo:
            self.peticiones.append(f"{peticion.method} {url}")
        if self.modo == "sin_red":
            raise httpx.ConnectError("sin red (simulada)", request=peticion)
        if self.modo == "colgada":
            time.sleep(8.0)
            raise httpx.ReadTimeout("red colgada (simulada)", request=peticion)
        time.sleep(self.retraso_s)

        def js(datos, estado=200):
            return httpx.Response(estado, json=datos, request=peticion)

        def crudo(datos: bytes | None, tipo="application/json"):
            if datos is None:
                return httpx.Response(404, request=peticion)
            return httpx.Response(200, content=datos, headers={"content-type": tipo}, request=peticion)

        if "api.github.com/repos/WFCD/warframe-items/commits" in url:
            return js([{"sha": self.estado.get("items_sha", "x"),
                        "commit": {"committer": {"date": self.estado.get("items_fecha", "")}}}])
        if url.endswith("/info.json") and ("warframe-drop-data" in url or "drops.warframestat.us" in url):
            return js({"hash": self.estado.get("drops_hash", "x"), "modified": self.estado.get("drops_modified", "")})
        if "releases/latest" in url:
            if self.modo == "version_nueva":
                return js({
                    "tag_name": "v9.9.9", "html_url": "https://github.com/angelsanchez97/farmadex/releases/tag/v9.9.9",
                    "body": "prueba",
                    "assets": [{
                        "name": "Farmadex-9.9.9-setup.exe", "size": len(self.instalador),
                        "digest": f"sha256:{self.huella}",
                        "browser_download_url":
                            "https://github.com/angelsanchez97/farmadex/releases/download/v9.9.9/Farmadex-9.9.9-setup.exe",
                    }],
                })
            return js({"tag_name": f"v{self.version_actual}", "assets": [], "body": ""})
        if "/releases/download/" in url and url.endswith(".exe"):
            return httpx.Response(200, content=self.instalador,
                                  headers={"content-length": str(len(self.instalador))}, request=peticion)
        if peticion.method == "HEAD":
            version = self.estado.get("oficial_version")
            if version:
                return httpx.Response(200, headers={"etag": version}, request=peticion)
            return httpx.Response(404, request=peticion)
        if "worldState.php" in url:
            return crudo(self._fixture("worldstate_de.json"))
        if "api.warframestat.us" in url:
            return crudo(self._fixture("worldstate.json"))
        if "weeklyRivens" in url:
            return crudo(self._fixture("de_weekly_rivens.txt"))
        if "warframe.market" in url:
            if url.split("?")[0].rstrip("/").endswith("/v2/items"):
                return crudo(self.catalogo_market)
            if "riven/weapons" in url or "riven/items" in url:
                return crudo(self._fixture("market_riven_weapons.json"))
            if "auctions" in url:
                return crudo(self._fixture("market_riven_auctions.json"))
            return crudo(self._fixture("market_top.json"))
        if "cdn.warframestat.us/img" in url:
            return crudo(_png_minimo(), "image/png")
        return httpx.Response(404, request=peticion)

    def instalar(self) -> None:
        import socket

        import httpx

        red = self
        transporte = httpx.MockTransport(self.responder)
        original = httpx.Client.__init__

        def iniciar(cliente, *a, **kw):
            kw["transport"] = kw.get("transport") or transporte
            original(cliente, *a, **kw)

        httpx.Client.__init__ = iniciar  # type: ignore[method-assign]

        conectar = socket.socket.connect

        def solo_local(sock, direccion, *resto):
            host = direccion[0] if isinstance(direccion, tuple) else str(direccion)
            if host not in ("127.0.0.1", "::1", "localhost"):
                with red._cerrojo:
                    red.peticiones.append(f"SOCKET BLOQUEADO {direccion}")
                raise OSError("red real bloqueada por la autoprueba")
            return conectar(sock, direccion, *resto)

        socket.socket.connect = solo_local  # type: ignore[method-assign]


_PNG: bytes | None = None


def _png_minimo() -> bytes:
    global _PNG
    if _PNG is None:
        import cv2
        import numpy as np

        _PNG = bytes(cv2.imencode(".png", np.full((64, 64, 3), 90, np.uint8))[1])
    return _PNG


# -- pantalla simulada ---------------------------------------------------------------------


class PantallaSimulada:
    """Sustituye la pantalla y la ventana del juego por una imagen (BGR) y un cursor."""

    HWND = 424242

    def __init__(self):
        self.imagen = None
        self.cursor = (0, 0)
        self.capturas = 0

    def poner(self, imagen, cursor: tuple[int, int] | None = None) -> None:
        self.imagen = imagen
        if cursor is not None:
            self.cursor = cursor
        elif imagen is not None:
            self.cursor = (imagen.shape[1] // 2, imagen.shape[0] // 2)

    def region(self):
        from .captura import pantalla

        if self.imagen is None:
            return pantalla.Region(0, 0, 1920, 1080)
        return pantalla.Region(0, 0, self.imagen.shape[1], self.imagen.shape[0])

    def recortar(self, region):
        import numpy as np

        self.capturas += 1
        if self.imagen is None or region.ancho <= 0 or region.alto <= 0:
            return None
        alto, ancho = self.imagen.shape[:2]
        salida = np.zeros((region.alto, region.ancho, 3), np.uint8)
        x0, y0 = max(0, region.x), max(0, region.y)
        x1, y1 = min(ancho, region.x + region.ancho), min(alto, region.y + region.alto)
        if x1 > x0 and y1 > y0:
            salida[y0 - region.y:y1 - region.y, x0 - region.x:x1 - region.x] = self.imagen[y0:y1, x0:x1]
        return np.ascontiguousarray(salida)

    def instalar(self) -> None:
        from .captura import pantalla

        sim = self
        hay = lambda: sim.imagen is not None  # noqa: E731
        pantalla.ventana_juego = lambda: sim.HWND if hay() else None
        pantalla.region_ventana = lambda hwnd: sim.region() if hwnd else None
        if hasattr(pantalla, "region_marco"):
            pantalla.region_marco = lambda hwnd: sim.region() if hwnd else None
        pantalla.region_objetivo = lambda: sim.region()
        pantalla.region_juego = lambda: sim.region() if hay() else None
        pantalla.region_pantalla_completa = lambda: sim.region()
        pantalla._escritorio_virtual = lambda: sim.region()
        pantalla._posicion_cursor = lambda: sim.cursor
        pantalla._ventana_activa = lambda: sim.HWND
        if hasattr(pantalla, "monitor_de"):
            pantalla.monitor_de = lambda hwnd: sim.region()
        if hasattr(pantalla, "modo_pantalla"):
            pantalla.modo_pantalla = lambda hwnd=None: pantalla.MODO_SIN_BORDES
        if hasattr(pantalla, "escala_fisica_logica"):
            pantalla.escala_fisica_logica = lambda hwnd=None: 1.0
        if hasattr(pantalla, "_capturar_crudo"):
            pantalla._capturar_crudo = sim.recortar  # capturar() sigue escondiendo Farmadex antes
        else:  # versiones sin ocultador (0.6.1): capturar hacia la captura directamente
            pantalla.capturar = sim.recortar
        if hasattr(pantalla, "capturar_sin_ocultar") and not hasattr(pantalla, "_capturar_crudo"):
            pantalla.capturar_sin_ocultar = sim.recortar


# -- utilidades de medida ----------------------------------------------------------------------


def _ms(segundos: float) -> float:
    return round(segundos * 1000, 1)


def _resumen_tiempos(valores: list[float]) -> dict:
    valores = [v for v in valores if v is not None]
    if not valores:
        return {"n": 0}
    ordenados = sorted(valores)
    p90 = ordenados[min(len(ordenados) - 1, int(round(0.9 * (len(ordenados) - 1))))]
    return {"n": len(valores), "mediana": round(statistics.median(valores), 1), "p90": round(p90, 1),
            "max": round(max(valores), 1)}


def _normal(texto: str) -> str:
    import unicodedata

    texto = unicodedata.normalize("NFKD", texto or "")
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).lower().split())


class VigiaCongelaciones:
    """Apunta cada vez que el hilo de la ventana se queda parado mas de `umbral_ms`, con la
    pila de lo que estaba haciendo: asi se sabe QUE congela, no solo que algo congela."""

    def __init__(self, app, umbral_ms: float = 120.0):
        from PySide6.QtCore import QTimer

        self.umbral = umbral_ms / 1000.0
        self.latido = time.perf_counter()
        self.congelaciones: list[dict] = []
        self._hilo_principal = threading.main_thread().ident
        self._parado = False
        self._temporizador = QTimer()
        self._temporizador.setInterval(10)
        self._temporizador.timeout.connect(self._latir)
        self._temporizador.start()
        self._vigia = threading.Thread(target=self._vigilar, name="autoprueba-vigia", daemon=True)
        self._vigia.start()
        self.flujo = ""

    def _latir(self) -> None:
        self.latido = time.perf_counter()

    def _vigilar(self) -> None:
        apuntada = None
        while not self._parado:
            time.sleep(0.02)
            parada = time.perf_counter() - self.latido
            if parada < self.umbral:
                if apuntada is not None:
                    apuntada["ms"] = max(apuntada["ms"], _ms(parada))
                apuntada = None
                continue
            if apuntada is None:
                marco = sys._current_frames().get(self._hilo_principal)
                pila = traceback.extract_stack(marco)[-14:] if marco is not None else []
                # Si lo ultimo que corre es la propia autoprueba (preparar una captura,
                # esperar), no es la ventana la que esta parada.
                propia = bool(pila) and "autoprueba" in pila[-1].filename
                apuntada = {"flujo": "(autoprueba)" if propia else self.flujo, "ms": _ms(parada),
                            "pila": [f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in pila
                                     if "autoprueba" not in f.filename]}
                # Lo que hacian los demas hilos en ese momento (quien tenia el GIL o el cerrojo).
                nombres = {h.ident: h.name for h in threading.enumerate()}
                otros = {}
                for ident, marco_otro in sys._current_frames().items():
                    if ident in (self._hilo_principal, threading.get_ident()):
                        continue
                    arriba = traceback.extract_stack(marco_otro)[-3:]
                    otros[nombres.get(ident, str(ident))] = [f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in arriba]
                apuntada["otros_hilos"] = otros
                self.congelaciones.append(apuntada)
            else:
                apuntada["ms"] = _ms(parada)

    def parar(self) -> None:
        self._parado = True
        self._temporizador.stop()


class Sondas:
    """Envuelve metodos de la ventana (antes de crearla) para saber cuando acaba cada cosa."""

    def __init__(self):
        self.llamadas: dict[str, list[tuple[float, tuple]]] = {}

    def poner(self, clase, nombre: str) -> bool:
        original = getattr(clase, nombre, None)
        if original is None or getattr(original, "_sonda", False):
            return False
        sondas = self
        clave = f"{clase.__name__}.{nombre}"

        def envoltura(objeto, *a, **kw):
            resultado = original(objeto, *a, **kw)
            sondas.llamadas.setdefault(clave, []).append((time.perf_counter(), a))
            return resultado

        # `functools.update_wrapper` y no solo `__name__`: si el metodo era un @Slot, la
        # envoltura tiene que parecerselo del todo (`__qualname__`, `__module__` y `_slots`).
        # Medido con PySide6 6.11: una senal de un objeto de otro hilo conectada a un metodo
        # que FUE @Slot pero que Qt ya no reconoce (porque esta sonda lo sustituyo por una
        # funcion normal con el mismo nombre) se entrega EN EL HILO DEL EMISOR, no en el de la
        # ventana. Asi `mostrar_precio` y `leyendo_precio` tocaban widgets y temporizadores
        # desde el hilo del vigia de vistas ("QObject::startTimer: Timers cannot be started
        # from another thread", unas 60 veces por pasada) y de vez en cuando tumbaban el
        # proceso (access violation). Bien disfrazada, Qt la encola al hilo del receptor.
        functools.update_wrapper(envoltura, original)
        envoltura._sonda = True  # type: ignore[attr-defined]
        setattr(clase, nombre, envoltura)
        return True

    def n(self, clave: str) -> int:
        return len(self.llamadas.get(clave, []))

    def desde(self, clave: str, t0: float) -> list[tuple[float, tuple]]:
        return [c for c in self.llamadas.get(clave, []) if c[0] >= t0]


# -- la autoprueba ----------------------------------------------------------------------------



def memoria_mb() -> float | None:
    """Memoria del proceso en uso (working set, lo que el Administrador de tareas llama
    memoria), en MB; None fuera de Windows o si no se puede leer."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _Contadores(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        contadores = _Contadores()
        contadores.cb = ctypes.sizeof(contadores)
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Contadores), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(contadores), contadores.cb):
            return None
        return round(contadores.WorkingSetSize / 2**20, 1)
    except Exception:  # noqa: BLE001 - la medida es informativa
        return None

class Autoprueba:
    def __init__(self, opciones: dict):
        self.op = opciones
        self.carpeta: Path = opciones["carpeta"]
        self.dir_png = self.carpeta / "capturas"
        self.dir_png.mkdir(parents=True, exist_ok=True)
        self.resultado: dict = {
            "etiqueta": opciones.get("etiqueta") or "",
            "inicio": time.strftime("%Y-%m-%d %H:%M:%S"),
            "flujos": {},
            "excepciones": [],
            "avisos_qt": [],
        }
        self.excepciones: list[str] = []
        self.ventana = None
        self.app = None
        self.sim = PantallaSimulada()
        self.sondas = Sondas()
        self.red: RedSimulada | None = None
        self.con = None
        self._nombres: dict[str, set[int]] = {}
        self._leidas_recompensas: list[tuple[float, list]] = []
        self.vigia: VigiaCongelaciones | None = None

    # -- guardado ----------------------------------------------------------------------

    def guardar(self) -> None:
        self.resultado["excepciones"] = list(self.excepciones)
        ruta = self.carpeta / "resultado.json"
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.resultado, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        tmp.replace(ruta)

    def flujo(self, nombre: str, datos: dict) -> None:
        self.resultado["flujos"][nombre] = datos
        self.guardar()

    def png(self, nombre: str, widget=None) -> None:
        try:
            with self.sin_vigia():
                widget = widget or self.ventana
                widget.grab().save(str(self.dir_png / f"{nombre}.png"))
        except Exception:  # noqa: BLE001 - una foto que falla no invalida la prueba
            pass

    # -- bombeo de eventos ----------------------------------------------------------------

    def _atender(self) -> None:
        """Una vuelta del bucle de eventos como la de `app.exec()`: `processEvents()` solo NO
        entrega los `deleteLater()`, asi que sin esto cada ficha o pestana rehecha se
        quedaba viva y la autoprueba media fugas y cambios de tema que la app real no tiene."""
        from PySide6.QtCore import QEvent

        self.app.processEvents()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def bombear(self, segundos: float) -> float:
        """Atiende eventos durante `segundos`; devuelve el mayor hueco sin atenderlos (congelada)."""
        fin = time.perf_counter() + segundos
        ultimo = time.perf_counter()
        hueco = 0.0
        while True:
            self._atender()
            ahora = time.perf_counter()
            hueco = max(hueco, ahora - ultimo)
            ultimo = ahora
            if ahora >= fin:
                return hueco
            time.sleep(0.001)

    def esperar(self, condicion, maximo: float) -> float | None:
        """Segundos hasta que se cumple `condicion` (atendiendo eventos), o None."""
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < maximo:
            self._atender()
            try:
                if condicion():
                    return time.perf_counter() - t0
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.002)
        return None

    # -- indice ---------------------------------------------------------------------------

    def ids_por_nombre(self, nombre: str) -> set[int]:
        if not self._nombres:
            for item_id, en, es in self.con.execute("SELECT id, nombre_en, nombre_es FROM items"):
                for n in (en, es):
                    if n:
                        self._nombres.setdefault(_normal(n), set()).add(item_id)
            try:
                for item_id, n in self.con.execute("SELECT item_id, nombre FROM items_nombres"):
                    if n:
                        self._nombres.setdefault(_normal(n), set()).add(item_id)
            except sqlite3.Error:
                pass
        return self._nombres.get(_normal(nombre), set())

    def nombre_en(self, item_id: int) -> str:
        """Nombre en ingles con el de su padre delante si es una pieza ("Ash Prime Systems")."""
        fila = self.con.execute(
            "SELECT i.nombre_en, p.nombre_en FROM items i LEFT JOIN items p ON p.id = i.padre_id WHERE i.id = ?",
            (item_id,)).fetchone()
        if not fila:
            return ""
        return f"{fila[1]} {fila[0]}" if fila[1] and not fila[0].startswith(fila[1]) else fila[0]

    class _SinVigia:
        """Lo que hace la propia autoprueba (verdades, fotos) no cuenta como congelacion."""

        def __init__(self, prueba):
            self.prueba = prueba

        def __enter__(self):
            if self.prueba.vigia is not None:
                self.prueba.vigia.flujo_real, self.prueba.vigia.flujo = self.prueba.vigia.flujo, "(autoprueba)"

        def __exit__(self, *_):
            if self.prueba.vigia is not None:
                self.prueba.vigia.flujo = self.prueba.vigia.flujo_real
                self.prueba.vigia.latido = time.perf_counter()

    def sin_vigia(self):
        return Autoprueba._SinVigia(self)

    def ids_recompensa(self, nombre: str) -> set[int]:
        """La verdad de las recompensas va como la conoce el casador ("Fang Prime Blueprint")."""
        if getattr(self, "_casador_verdad", None) is None:
            # El mismo casador con el que se anoto la verdad (herramientas/banco_recompensas.py).
            from .captura.ocr import Casador
            from .captura.reliquias import CATEGORIAS_RECOMPENSA
            from .datos import indice

            con = indice.conectar()
            try:
                self._casador_verdad = Casador(con, CATEGORIAS_RECOMPENSA)
            finally:
                con.close()
        item_id, _etiqueta, _puntos = self._casador_verdad.casar(nombre, 90)
        ids = {item_id} if item_id else set(self.ids_por_nombre(nombre))
        # "Forma" en la verdad y "Forma Blueprint" (su plano, pieza de Forma) en la tabla de
        # reliquias del indice nuevo de WFCD son la misma tarjeta: se aceptan los dos.
        for i in list(ids):
            ids |= {r[0] for r in self.con.execute(
                "SELECT id FROM items WHERE padre_id = ? AND nombre_en = 'Blueprint'", (i,))}
        return ids

    # -- capturas ---------------------------------------------------------------------------

    def casos(self) -> dict[str, list[tuple[Path, dict]]]:
        """Los casos de todas las carpetas, separados por tipo segun el formato de su verdad."""
        salida: dict[str, list[tuple[Path, dict]]] = {"recompensas": [], "build": [], "agrietado": []}
        for carpeta in self.op["capturas"]:
            carpeta = Path(carpeta)
            verdad = carpeta / "verdad.json"
            if not verdad.exists():
                continue
            datos = json.loads(verdad.read_text(encoding="utf-8"))
            for nombre, info in datos.items():
                if nombre.startswith("_") or not isinstance(info, dict):
                    continue
                ruta = carpeta / nombre
                if not ruta.exists():
                    continue
                if "tarjetas" in info:
                    salida["recompensas"].append((ruta, info))
                elif "equipo" in info or "equipados" in info or "no_legible" in info:
                    salida["build"].append((ruta, info))
                elif "arma" in info or "velado" in info:
                    salida["agrietado"].append((ruta, info))
        return salida

    def imagen(self, ruta: Path):
        import cv2
        import numpy as np

        with self.sin_vigia():  # cargar una captura de 4K es trabajo de la autoprueba
            datos = np.fromfile(str(ruta), dtype=np.uint8)
            return cv2.imdecode(datos, cv2.IMREAD_COLOR)

    # -- arranque ---------------------------------------------------------------------------------

    def ejecutar(self) -> int:
        ok = True
        procesos_carga = []
        try:
            self._preparar()
            if self.op["carga"]:
                mascara = _mascara_nucleos(self.op["nucleos"]) if self.op["nucleos"] else None
                procesos_carga = lanzar_carga(self.op["carga"], mascara)
                self.resultado["carga"] = {"procesos": self.op["carga"], "pids": [p.pid for p in procesos_carga]}
            for nombre in FLUJOS:
                if self.op["solo"] and nombre not in self.op["solo"] and nombre not in ("arranque", "cierre"):
                    continue
                metodo = getattr(self, f"flujo_{nombre}")
                if self.vigia is not None:
                    self.vigia.flujo = nombre
                rss_antes = memoria_mb()
                t0 = time.perf_counter()
                perfil = None
                if self.op.get("perfil") == nombre:
                    import cProfile

                    perfil = cProfile.Profile()
                    perfil.enable()
                try:
                    metodo()
                except Exception:  # noqa: BLE001 - un flujo roto se apunta y se sigue con el resto
                    texto = traceback.format_exc()
                    self.excepciones.append(f"[{nombre}] {texto}")
                    datos = self.resultado["flujos"].setdefault(nombre, {})
                    datos["roto"] = texto.strip().splitlines()[-1]
                if perfil is not None:
                    import io
                    import pstats

                    perfil.disable()
                    salida = io.StringIO()
                    pstats.Stats(perfil, stream=salida).sort_stats("tottime").print_stats(40)
                    pstats.Stats(perfil, stream=salida).sort_stats("cumulative").print_stats(60)
                    (self.carpeta / f"perfil_{nombre}.txt").write_text(salida.getvalue(), encoding="utf-8")
                datos_flujo = self.resultado["flujos"].setdefault(nombre, {})
                datos_flujo["segundos"] = round(time.perf_counter() - t0, 2)
                # Memoria del proceso (RSS) antes y despues del flujo: lo que crece y no baja
                # de un flujo a otro es una fuga.
                datos_flujo["rss_mb"] = [rss_antes, memoria_mb()]
                self.guardar()
        finally:
            parar_carga(procesos_carga)
            if self.vigia is not None:
                self.vigia.parar()
                self.resultado["congelaciones"] = self.vigia.congelaciones
            self._errores_registro()
            self.resultado["fin"] = time.strftime("%Y-%m-%d %H:%M:%S")
            ok = self._veredicto()
            self.guardar()
            self._informe()
        return 0 if ok else 1

    def _preparar(self) -> None:
        from . import NOMBRE_APP, VERSION

        self.resultado["version"] = VERSION
        self.resultado["frozen"] = bool(getattr(sys, "frozen", False))
        self.resultado["nucleos"] = self.op["nucleos"] or (os.cpu_count() or 0)
        base = Path(os.environ["FARMADEX_DATOS"]) / NOMBRE_APP
        origen = buscar_indice(self.op)
        if origen is None or not origen.exists():
            raise SystemExit("Hace falta el indice completo: --indice <indice.sqlite> o --datos <carpeta Farmadex>")
        t0 = time.perf_counter()
        copiar_indice(origen, base / "db" / "indice.sqlite")
        estado = {}
        if self.op.get("datos"):
            origen_datos = Path(self.op["datos"]) / "datos"
            if origen_datos.exists():
                shutil.copytree(origen_datos, base / "datos", dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("img"))
                ruta_estado = base / "datos" / "estado_datos.json"
                if ruta_estado.exists():
                    estado = json.loads(ruta_estado.read_text(encoding="utf-8"))
        self.resultado["preparar_s"] = round(time.perf_counter() - t0, 2)
        # EE.log propio y vacio: el del juego (el usuario puede estar jugando) no se lee.
        eelog = self.carpeta / "EE.log"
        eelog.write_text("", encoding="utf-8")
        config = {
            "idioma_ui": "es", "ruta_eelog": str(eelog), "bienvenida_vista": True, "guia_vista": True,
            "guia_aviso_visto": True, "iniciar_con_windows": False, "overlay_modo": "completo",
            "comprobar_actualizaciones_app": True, "actualizar_automaticamente": True,
        }
        if self.op.get("sin_pasivo"):
            config.update({"perfil_pasivo": False, "inventario_pasivo": False})
        (base / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

        fixtures = Path(self.op["red_fixtures"]) if self.op.get("red_fixtures") else None
        if fixtures is None:
            candidata = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
            fixtures = candidata if candidata.exists() else None
        self.red = RedSimulada(fixtures, estado, VERSION)
        self.red.catalogo_market = catalogo_market_de(origen)
        self.red.modo_base = "sin_red" if self.op.get("sin_red") else "normal"
        self.red.modo = self.red.modo_base
        self.resultado["red"] = self.red.modo_base
        if self.op.get("precios_reales"):
            self._bajar_precios_reales()  # lo unico que sale a internet, antes de cortar la red
        self.red.instalar()
        self._blindar()

        from . import config as config_modulo
        from .registro_log import configurar, instalar_gancho_excepciones

        config_modulo.POR_DEFECTO["ruta_eelog"] = str(eelog)
        import logging

        configurar(logging.DEBUG if self.op.get("depurar") else logging.INFO)
        instalar_gancho_excepciones(lambda texto: self.excepciones.append(f"[gancho] {texto}"))
        # Las excepciones de los hilos de Python tambien cuentan (el gancho las manda al log).
        gancho_hilos = threading.excepthook

        def hilos(argumentos):
            self.excepciones.append(f"[hilo {getattr(argumentos.thread, 'name', '?')}] "
                                    f"{argumentos.exc_type.__name__}: {argumentos.exc_value}")
            gancho_hilos(argumentos)

        threading.excepthook = hilos

        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([sys.argv[0]])
        from .ui.widgets import HOJA_ESTILOS

        self.app.setStyleSheet(HOJA_ESTILOS)
        self.app.setQuitOnLastWindowClosed(False)
        self.vigia = VigiaCongelaciones(self.app, float(self.op.get("vigia_ms") or 120))
        self.sim.instalar()
        if self.op["nucleos"]:
            # La carga de CPU que mide Farmadex es la de todo el equipo; aqui los procesos de
            # carga van en los mismos N nucleos, asi que se reparte como la veria un PC de N.
            from .captura import carga

            original = carga.uso_ajeno
            proporcion = self.op["cpus_reales"] / self.op["nucleos"]
            carga.uso_ajeno = lambda: (lambda u: None if u is None else min(1.0, u * proporcion))(original())
        self.con = sqlite3.connect(f"file:{(base / 'db' / 'indice.sqlite').as_posix()}?mode=ro", uri=True)

    def _blindar(self) -> None:
        """Nada de ventanas externas, registro de Windows ni instaladores de verdad."""
        import subprocess

        if hasattr(os, "startfile"):
            os.startfile = lambda *a, **k: None  # type: ignore[attr-defined]
        popen = subprocess.Popen

        class PopenVigilado(popen):  # type: ignore[misc, valid-type]
            def __init__(self, args, *resto, **kw):
                programa = str(args[0] if isinstance(args, (list, tuple)) else args).lower()
                if "explorer" in programa or programa.endswith("setup.exe"):
                    raise OSError(f"la autoprueba no abre {programa}")
                super().__init__(args, *resto, **kw)

        subprocess.Popen = PopenVigilado  # type: ignore[misc]
        try:
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl = staticmethod(lambda *a, **k: True)
        except ImportError:
            pass
        from . import arranque

        arranque._escribir_run = lambda *a, **k: None
        arranque._borrar_run = lambda *a, **k: None
        try:
            from .actualizador import instalacion

            instalacion.instalar_silencioso = lambda *a, **k: False
        except ImportError:
            pass

    # -- flujos -----------------------------------------------------------------------------------

    def flujo_instancia(self) -> None:
        from . import instancia_unica

        datos: dict = {}
        if not hasattr(instancia_unica, "_sufijo_datos"):
            datos["nota"] = "esta version no tiene candado aparte con FARMADEX_DATOS: no se toca el candado"
            self.flujo("instancia", datos)
            return
        datos["mutex"] = instancia_unica.MUTEX_INSTANCIA
        datos["aparte"] = instancia_unica.MUTEX_INSTANCIA != "FarmadexInstanciaUnica"
        instancia = instancia_unica.InstanciaUnica()
        datos["adquirida"] = bool(instancia.adquirir())
        instancia.soltar()
        datos["ok"] = datos["aparte"] and datos["adquirida"]
        self.flujo("instancia", datos)

    def _bajar_precios_reales(self) -> None:
        """Baja la foto diaria con el descargador de verdad (el mismo codigo que usa la app)."""
        from .online import precios_diarios as pd

        datos: dict = {}
        try:
            foto = pd.PreciosDiarios()
            foto.cargar_local()  # como al abrir la app: primero lo que haya en disco (nada)
            descargador = pd.Descargador(foto, base=self.op.get("precios_base") or None)
            datos["url"] = descargador.base
            t0 = time.perf_counter()
            tarea = descargador.actualizar(manual=True)
            datos["resultado"] = tarea.esperar(120)
            datos["detalle"] = str(getattr(tarea, "detalle", "") or "")[:200]
            datos["descarga_s"] = round(time.perf_counter() - t0, 2)
            datos["fichero_bytes"] = foto.ruta.stat().st_size if foto.ruta.exists() else 0
        except Exception as e:  # noqa: BLE001 - se apunta y el flujo lo da por fallido
            datos["roto_descarga"] = f"{type(e).__name__}: {e}"
        self._precios_reales = datos

    def flujo_precios_reales(self) -> None:
        """Con la red ya cortada: la foto bajada se carga del disco y contesta al instante."""
        datos = dict(getattr(self, "_precios_reales", None) or {})
        if not datos:
            self.flujo("precios_reales", {"nota": "sin --precios-reales: no se sale a internet"})
            return
        from .chat import precios as chat_precios
        from .online import precios_diarios as pd
        from .ui import vista_objeto

        pd._reiniciar_para_pruebas(None)  # como al abrir Farmadex otra vez: del disco, sin red
        red_antes = len(self.red.peticiones)
        t0 = time.perf_counter()
        foto = pd.precios()
        foto.cargado.wait(20)
        datos["carga_ms"] = _ms(time.perf_counter() - t0)
        datos["disponible"] = bool(foto.disponible)
        datos["objetos"] = len(foto)
        datos["fecha"] = str(foto.fecha)
        slugs = [s for s in ("arcane_energize", "serration", "primed_continuity", "loki_prime_set",
                             "rhino_prime_set", "lith_a1_relic", "galvanized_chamber", "molt_augmented")
                 if s in foto] or list(foto.objetos())[:8]
        tiempos, vistos, vacios = [], [], 0
        for slug in slugs:
            t1 = time.perf_counter()
            filas_chat = chat_precios.filas(slug, None)
            objeto = vista_objeto.ObjetoVisto(item_id=0, slug=slug, nombre=slug)
            filas_vista = vista_objeto.filas_precio(objeto, vista_objeto._precios())
            tiempos.append(_ms(time.perf_counter() - t1))
            precio = foto.buscar(slug, foto.rango_max(slug))
            if precio is None or not any(f.precio is not None for f in filas_chat):
                vacios += 1
            texto = " ".join(str(x) for fila in filas_vista for x in fila[1:])
            vistos.append({"slug": slug, "venta_min": getattr(precio, "venta_min", None),
                           "min_30d": getattr(precio, "min_30d", None), "max_30d": getattr(precio, "max_30d", None),
                           "dice_fuente": "warframe.market" in texto})
        # Lo que la foto no trae no sale: ni en el chat ni en el recuadro.
        falso = "objeto_que_no_existe_en_el_mercado"
        inventados = int(foto.buscar(falso) is not None) + sum(
            1 for f in chat_precios.filas(falso, None) if f.precio is not None)
        pie = chat_precios.texto_fecha(chat_precios.fecha_snapshot())
        datos.update({
            "buscados": len(slugs), "con_precio": len(slugs) - vacios, "inventados": inventados,
            "tiempos": _resumen_tiempos(tiempos), "muestra": vistos[:4], "pie_chat": pie,
            "peticiones_red_durante": len(self.red.peticiones) - red_antes,
        })
        datos["ok"] = bool(
            datos.get("resultado") in ("nuevo", "al_dia", "aun_no_hay") and datos.get("fichero_bytes") and datos["disponible"] and datos["objetos"] > 1000
            and slugs and not vacios and not inventados and "warframe.market" in pie
            and all(v["dice_fuente"] for v in vistos) and datos["peticiones_red_durante"] == 0
            and datos["tiempos"].get("max", 9999) <= 50)
        self.flujo("precios_reales", datos)

    def flujo_actualizar_al_abrir(self) -> None:
        try:
            from .actualizador import al_abrir
            from .actualizador.app import ComprobadorApp
        except ImportError:
            self.flujo("actualizar_al_abrir", {"nota": "esta version no actualiza al abrir"})
            return
        import hashlib

        instalados: list = []

        def instalar(ruta, etiqueta, en_bandeja=False):
            instalados.append((str(ruta), etiqueta))
            return True

        escenarios = {}
        config = {"actualizar_automaticamente": True, "actualizar_al_abrir": True,
                  "comprobar_actualizaciones_app": True}
        self.red.instalador = os.urandom(3 * 1024 * 1024)
        self.red.huella = hashlib.sha256(self.red.instalador).hexdigest()
        for modo, esperado in (("sin_red", False), ("colgada", False), ("normal", False),
                               ("version_nueva", True), ("huella_mala", False)):
            carpeta = self.carpeta / "datos" / f"descargas_{modo}"
            shutil.rmtree(carpeta, ignore_errors=True)
            self.red.modo = "version_nueva" if modo == "huella_mala" else modo
            huella_buena = self.red.huella
            if modo == "huella_mala":
                self.red.huella = "0" * 64
            antes = len(instalados)
            t0 = time.perf_counter()
            devuelto = al_abrir.actualizar_al_abrir(
                config, [], es_instalada=lambda: True, carpeta=carpeta, comprobador=ComprobadorApp(),
                instalar=instalar, plazo=al_abrir.PLAZO_CONSULTA_S,
            )
            segundos = time.perf_counter() - t0
            self.red.huella = huella_buena
            for w in self.app.topLevelWidgets():  # la ventanita de progreso no puede quedarse
                if type(w).__name__ == "VentanaActualizando" and w.isVisible():
                    escenarios.setdefault(modo, {})["ventana_abierta"] = True
            escenarios[modo] = {
                **escenarios.get(modo, {}),
                "devuelve": devuelto, "esperado": esperado, "segundos": round(segundos, 2),
                "instalador_lanzado": len(instalados) > antes,
                "ok": devuelto == esperado and segundos < 6.0 and (len(instalados) > antes) == esperado,
            }
        self.red.modo = self.red.modo_base
        self.flujo("actualizar_al_abrir", {"escenarios": escenarios,
                                           "ok": all(e["ok"] for e in escenarios.values())})

    def flujo_arranque(self) -> None:
        from .ui import overlay as modulo_overlay

        V = modulo_overlay.VentanaOverlay
        for nombre in ("_pintar_recompensas", "_build_leida", "_agrietado_leido", "_abrir_desde_cursor",
                       "_mostrar_reliquia_juego", "_datos_listos", "_lectura_cursor_terminada"):
            self.sondas.poner(V, nombre)
        from .ui import pestana_buscador, vista_compacta

        for clase, nombre in ((pestana_buscador.PestanaBuscador, "_aplicar_busqueda"),
                              (pestana_buscador.PestanaBuscador, "abrir"),
                              (vista_compacta.VistaCompacta, "_buscar")):
            self.sondas.poner(clase, nombre)
        if not hasattr(pestana_buscador.PestanaBuscador, "_aplicar_busqueda"):
            self.sondas.poner(pestana_buscador.PestanaBuscador, "_buscar")
        try:  # lo que sale solo sin atajo (versiones que lo tienen)
            from .ui import vista_objeto

            for nombre in ("mostrar_precio", "mostrar_riven", "sin_precio", "leyendo_precio"):
                self.sondas.poner(vista_objeto.ControladorVistas, nombre)
            self.sondas.poner(V, "_build_vista_sola")
        except ImportError:
            pass

        datos: dict = {}
        t0 = time.perf_counter()
        self.ventana = V()
        datos["construir_ms"] = _ms(time.perf_counter() - t0)
        self.ventana.resize(1400, 900)
        self.ventana.mostrar()
        datos["mostrar_ms"] = _ms(time.perf_counter() - t0)
        listo = self.esperar(lambda: self.sondas.n("VentanaOverlay._datos_listos") > 0, 120)
        datos["datos_listos_ms"] = _ms(time.perf_counter() - t0) if listo is not None else None
        datos["estado"] = self.ventana.estado.text()

        def lectores_listos():
            lr = getattr(self.ventana, "lector_recompensas", None)
            lb = getattr(self.ventana, "lector_build", None)
            return (lr is not None and lr.casador is not None and getattr(lr, "_casador_reliquias", 1) is not None
                    and lb is not None and lb.casador is not None)

        preparado = self.esperar(lectores_listos, 120)
        datos["lectores_listos_ms"] = _ms(time.perf_counter() - t0) if preparado is not None else None
        self.bombear(1.0)  # que el mundo y los precios (red simulada) lleguen y se pinten
        datos["peticiones_red"] = len(self.red.peticiones)
        import gc

        # Una pasada completa del recolector de basura para ver lo que puede llegar a
        # congelar la ventana (el recolector para todos los hilos mientras recorre).
        datos["objetos_python"] = len(gc.get_objects())
        datos["objetos_congelados"] = gc.get_freeze_count()
        t_gc = time.perf_counter()
        gc.collect()
        datos["recolector_ms"] = _ms(time.perf_counter() - t_gc)
        datos["ok"] = listo is not None and preparado is not None
        # El vigia de lo que sale solo se apaga fuera de sus flujos: los demas miden las
        # lecturas por atajo, y una lectura sola a la vez cambiaria sus tiempos.
        self._vigia_vistas(False, False, False)
        self.png("arranque")
        self.flujo("arranque", datos)

    # recompensas --------------------------------------------------------------------------

    def _conectar_leidas(self) -> None:
        lector = self.ventana.lector_recompensas
        if getattr(self, "_leidas_conectadas", False):
            return
        from PySide6.QtCore import Qt

        lector.leidas.connect(lambda lista: self._leidas_recompensas.append((time.perf_counter(), list(lista))),
                              Qt.DirectConnection)
        self._leidas_conectadas = True

    def _puntuar_recompensas(self, leidas: list, esperadas: list[set[int]]) -> tuple[int, int]:
        ids = [getattr(r, "item_id", 0) for r in leidas]
        aciertos = sum(1 for leido, ok in zip(ids, esperadas) if leido in ok)
        pendientes = [set(e) for e in esperadas]
        inventadas = 0
        for i in ids:
            hueco = next((p for p in pendientes if i in p), None)
            if hueco is not None:
                pendientes.remove(hueco)
            elif i and i > 0:
                inventadas += 1
        return aciertos, inventadas

    def flujo_recompensas(self) -> None:
        """Dos tandas: por atajo, pantalla tras pantalla y sin EE.log (quien no lo tiene, o lo
        tiene con retraso), y por aviso de EE.log, como la lee Farmadex solo."""
        self._conectar_leidas()
        v = self.ventana
        filas: dict[str, dict] = {}
        self._cursor_casos = []
        preparados = []
        for ruta, info in self.casos()["recompensas"]:
            if info.get("fila") or info.get("franja"):
                filas[ruta.name] = {"fichero": ruta.name, "saltado": "recorte (no es la ventana entera)"}
                continue
            imagen = self.imagen(ruta)
            if imagen is None:
                continue
            with self.sin_vigia():
                esperadas = [self.ids_recompensa(n) for n in info["tarjetas"]]
            filas[ruta.name] = {"fichero": ruta.name, "resolucion": f"{imagen.shape[1]}x{imagen.shape[0]}",
                                "tarjetas": len(esperadas)}
            preparados.append((ruta, imagen, esperadas))
        for modo in ("atajo", "eelog"):
            for ruta, imagen, esperadas in preparados:
                fila = filas[ruta.name]
                self.sim.poner(imagen, cursor=(5, 5))
                n_pint = self.sondas.n("VentanaOverlay._pintar_recompensas")
                self._leidas_recompensas.clear()
                t0 = time.perf_counter()
                if modo == "atajo":
                    v.leer_recompensas()
                else:
                    v.vigilante.evento.emit("reliquia_abierta")
                    v.vigilante.pista.emit("remotos", str(len(esperadas) - 1))

                def completas():
                    pintadas = self.sondas.desde("VentanaOverlay._pintar_recompensas", t0)
                    return any(len(a[0]) >= len(esperadas) for _t, a in pintadas if a)

                tiempo = self.esperar(completas, 5.0)
                if tiempo is None:  # nunca llegaron todas: lo que haya
                    self.esperar(lambda: self.sondas.n("VentanaOverlay._pintar_recompensas") > n_pint, 0.5)
                primera = self.sondas.desde("VentanaOverlay._pintar_recompensas", t0)
                if modo == "eelog":
                    v.vigilante.evento.emit("reliquia_recompensas")
                    self.bombear(1.6)  # confirmaciones (dos miradas mas)
                else:
                    self.bombear(0.3)
                ultima = self._leidas_recompensas[-1][1] if self._leidas_recompensas else []
                aciertos, inventadas = self._puntuar_recompensas(ultima, esperadas)
                fila[modo] = {
                    "ms": _ms(tiempo) if tiempo is not None else None,
                    "primera_pintada_ms": _ms(primera[0][0] - t0) if primera else None,
                    "aciertos": aciertos, "inventadas": inventadas,
                    "leidas": [getattr(r, "nombre", "?") for r in ultima],
                    "etiquetas_visibles": bool(v.etiquetas.isVisible()),
                }
                if modo == "atajo":
                    self._cursor_casos.append((ruta, imagen, list(ultima), esperadas))
                    self.png(f"recompensas_{ruta.stem}_etiquetas", v.etiquetas)
                else:
                    v.vigilante.evento.emit("reliquia_cerrada")
                    self.bombear(0.2)
        usados = [f for f in filas.values() if "atajo" in f]
        datos = {"casos": list(filas.values())}
        for modo in ("atajo", "eelog"):
            datos[modo] = {
                "tiempos": _resumen_tiempos([f[modo]["ms"] for f in usados if f[modo]["ms"] is not None]),
                "aciertos": sum(f[modo]["aciertos"] for f in usados),
                "total": sum(f["tarjetas"] for f in usados),
                "inventadas": sum(f[modo]["inventadas"] for f in usados),
                "sin_completar": sum(1 for f in usados if f[modo]["ms"] is None),
            }
        self.sim.poner(None)
        self.flujo("recompensas", datos)

    def flujo_cursor(self) -> None:
        """Lectura bajo el cursor sobre las tarjetas de las pantallas de recompensas."""
        v = self.ventana
        filas = []
        for ruta, imagen, leidas, esperadas in getattr(self, "_cursor_casos", []):
            for posicion, (r, ok) in enumerate(zip(leidas, esperadas)):
                caja = getattr(r, "caja", None)
                if not caja or not ok:
                    continue
                x, y = int(caja[0] + caja[2] / 2), int(caja[1] + caja[3] / 2)
                self.sim.poner(imagen, cursor=(x, y))
                self.bombear(0.85)  # el atajo deja 0,8 s entre lecturas (TurnoLecturas)
                t0 = time.perf_counter()
                v.leer_cursor()
                fin = self.esperar(lambda: self.sondas.desde("VentanaOverlay._lectura_cursor_terminada", t0), 5.0)
                abiertos = self.sondas.desde("VentanaOverlay._abrir_desde_cursor", t0)
                item = abiertos[-1][1][0] if abiertos else None
                filas.append({
                    "fichero": ruta.name, "tarjeta": posicion + 1,
                    "ms": _ms(abiertos[-1][0] - t0) if abiertos else None,
                    "terminada_ms": _ms(fin) if fin is not None else None,
                    "leido": self.nombre_en(item) if item else None,
                    "acierto": bool(item in ok) if item else False,
                    "inventado": bool(item and item not in ok),
                })
        self.png("cursor_ficha")
        self.sim.poner(None)
        self.flujo("cursor", {
            "casos": filas,
            "tiempos": _resumen_tiempos([f["ms"] for f in filas if f["ms"] is not None]),
            "aciertos": sum(f["acierto"] for f in filas), "total": len(filas),
            "inventados": sum(f["inventado"] for f in filas),
        })

    # build ------------------------------------------------------------------------------------

    def _evaluar_build(self, info: dict, build) -> dict:
        from collections import Counter

        partes = ("equipados", "coleccion", "arcanos")
        leidos = {p: list(getattr(build, p, []) or []) for p in partes}
        en_pantalla: set[int] = set()
        for n in info.get("ignorar", []):
            en_pantalla |= self.ids_por_nombre(n)
        for p in partes:
            for n in info.get(p, []):
                en_pantalla |= self.ids_por_nombre(n)
        salida = {"partes": {}, "inventados": [], "faltan": []}
        equipo = getattr(build, "equipo", None)
        # "equipo_no_legible": el rotulo esta tapado de verdad (la camara del streamer, una
        # tarjeta): no se exige el equipo, pero uno equivocado sigue siendo inventado.
        esperado = self.ids_por_nombre(info.get("equipo", "")) if info.get("equipo") else set()
        salida["equipo_ok"] = bool(equipo is not None and getattr(equipo, "item_id", None) in esperado) \
            if esperado and not info.get("equipo_no_legible") else None
        if esperado and equipo is not None and getattr(equipo, "item_id", None) not in esperado:
            # Un equipo que no es el de la pantalla es un dato inventado, como un mod que no esta.
            salida["inventados"].append(f"equipo: {getattr(equipo, 'nombre', '?')}")
        for p in partes:
            disponibles = Counter(r.item_id for r in leidos[p])
            aciertos = 0
            for n in info.get(p, []):
                ids = self.ids_por_nombre(n)
                elegido = next((i for i in ids if disponibles[i] > 0), None)
                if elegido is not None:
                    disponibles[elegido] -= 1
                    aciertos += 1
                else:
                    salida["faltan"].append(f"{p}: {n}")
            salida["partes"][p] = [aciertos, len(info.get(p, []))]
        for p in partes:
            for r in leidos[p]:
                if r.item_id not in en_pantalla:
                    salida["inventados"].append(f"{p}: {getattr(r, 'texto_ocr', '')!r} -> {getattr(r, 'nombre', '')!r}")
        salida["aciertos"] = sum(a for a, _t in salida["partes"].values())
        salida["total"] = sum(t for _a, t in salida["partes"].values())
        # La unidad que importa al usuario: la LECTURA COMPLETA. Una build cuenta como buena
        # solo si salen el equipo, todos los mods equipados y los arcanos, sin ninguno de
        # mas. La coleccion de abajo se mide aparte (no es la build).
        salida["no_leidos"] = len(getattr(build, "no_leidos", []) or [])
        inventados_build = [i for i in salida["inventados"] if not i.startswith("coleccion")]
        faltan_build = [x for x in salida["faltan"] if not x.startswith("coleccion")]
        salida["completa"] = (salida["equipo_ok"] is not False and not inventados_build and not faltan_build)
        return salida

    def flujo_build(self) -> None:
        v = self.ventana
        filas = []
        for ruta, info in self.casos()["build"]:
            imagen = self.imagen(ruta)
            if imagen is None:
                continue
            self.sim.poner(imagen, cursor=(5, 5))
            v.ir_a("tablero")
            self.bombear(0.05)
            t0 = time.perf_counter()
            v.leer_build()
            tiempo = self.esperar(lambda: self.sondas.desde("VentanaOverlay._build_leida", t0), 10.0)
            llamadas = self.sondas.desde("VentanaOverlay._build_leida", t0)
            fila = {"fichero": ruta.name, "resolucion": f"{imagen.shape[1]}x{imagen.shape[0]}",
                    "ms": _ms(tiempo) if tiempo is not None else None, "no_legible": bool(info.get("no_legible"))}
            if llamadas:
                build = llamadas[-1][1][0]
                fila.update(self._evaluar_build(info, build))
                fila["pestana"] = v.ruta_actual() if hasattr(v, "ruta_actual") else None
            self.png(f"build_{ruta.stem}")
            filas.append(fila)
        legibles = [f for f in filas if not f["no_legible"] and "aciertos" in f]
        self.sim.poner(None)
        self.flujo("build", {
            "casos": filas,
            "tiempos": _resumen_tiempos([f["ms"] for f in filas if f["ms"] is not None]),
            "aciertos": sum(f["aciertos"] for f in legibles), "total": sum(f["total"] for f in legibles),
            "equipo": [sum(1 for f in legibles if f.get("equipo_ok")),
                       sum(1 for f in legibles if f.get("equipo_ok") is not None)],
            "inventados": sum(len(f.get("inventados", [])) for f in filas),
            "sin_leer": sum(1 for f in filas if f["ms"] is None),
            # Builds completas (equipo, todos los mods y arcanos, nada de mas) entre las legibles.
            "completas": sum(1 for f in legibles if f.get("completa")),
            "legibles": len([f for f in filas if not f["no_legible"]]),
            "incompletas": [f["fichero"] for f in legibles if not f.get("completa")]
            + [f["fichero"] for f in filas if not f["no_legible"] and "aciertos" not in f],
            "no_leidos": sum(f.get("no_leidos", 0) for f in filas),
        })

    # agrietado -----------------------------------------------------------------------------------

    def flujo_agrietado(self) -> None:
        import numpy as np

        from .captura import agrietados as modulo

        v = self.ventana
        ancho_t, alto_t = getattr(modulo, "ANCHO_TARJETA", 560), getattr(modulo, "ALTO_TARJETA", 760)
        filas = []
        for ruta, info in self.casos()["agrietado"]:
            imagen = self.imagen(ruta)
            if imagen is None:
                continue
            h, w = imagen.shape[:2]
            # La tarjeta (recorte) en medio de una pantalla del juego del tamano que le toca,
            # como mucho 4K: una captura mas grande se reduce a lo que mediria en 4K. Antes
            # salian "pantallas" de 6400x3600 que ningun jugador tiene, y los lectores que
            # miran la pantalla entera disparaban la memoria (1 GB de mas en este flujo).
            alto = int(max(1080, 1080 * max(w / ancho_t, h / alto_t) * 1.05))
            if alto > 2160:
                import cv2

                factor = 2160 / alto
                imagen = cv2.resize(imagen, (max(1, int(w * factor)), max(1, int(h * factor))),
                                    interpolation=cv2.INTER_AREA)
                h, w = imagen.shape[:2]
                alto = 2160
            ancho = alto * 16 // 9
            lienzo = np.full((alto, ancho, 3), 18, np.uint8)
            y0, x0 = (alto - h) // 2, (ancho - w) // 2
            lienzo[y0:y0 + h, x0:x0 + w] = imagen
            self.sim.poner(lienzo, cursor=(ancho // 2, alto // 2))
            t0 = time.perf_counter()
            v.leer_agrietado()
            tiempo = self.esperar(lambda: self.sondas.desde("VentanaOverlay._agrietado_leido", t0), 10.0)
            llamadas = self.sondas.desde("VentanaOverlay._agrietado_leido", t0)
            fila = {"fichero": ruta.name, "ms": _ms(tiempo) if tiempo is not None else None,
                    "rss_mb": memoria_mb()}
            if llamadas:
                tarjeta = llamadas[-1][1][0]
                leidas = [[e.slug, e.valor, e.negativo] for e in tarjeta.estadisticas]
                if info.get("velado"):
                    fila["ok"] = bool(tarjeta.velado)
                    fila["falsa_seguridad"] = False
                else:
                    arma_ok = tarjeta.arma_slug == info.get("arma")
                    stats_ok = len(leidas) == len(info.get("stats", [])) and all(
                        any(l[0] == s[0] and abs((l[1] or 0) - s[1]) < 0.05 and l[2] == s[2] for l in leidas)
                        for s in info.get("stats", []))
                    fila["arma_ok"] = arma_ok
                    fila["ok"] = arma_ok and stats_ok
                    fila["fiable"] = bool(tarjeta.fiable)
                    fila["falsa_seguridad"] = bool(tarjeta.fiable and not fila["ok"])
            filas.append(fila)
        self.png("agrietado")
        self.sim.poner(None)
        self.flujo("agrietado", {
            "casos": filas,
            "tiempos": _resumen_tiempos([f["ms"] for f in filas if f["ms"] is not None]),
            "aciertos": sum(1 for f in filas if f.get("ok")), "total": len(filas),
            "armas": sum(1 for f in filas if f.get("arma_ok")),
            "inventados": sum(1 for f in filas if f.get("falsa_seguridad")),
        })

    # hover de reliquias -----------------------------------------------------------------------

    def flujo_hover(self) -> None:
        import random

        from .captura import reliquia_hover as RH
        from .captura.ocr import MotorOCR

        v = self.ventana
        hover = getattr(v, "hover_reliquias", None)
        if hover is None:
            self.flujo("hover", {"nota": "esta version no tiene la tabla de reliquia al pasar el raton"})
            return
        nombres = RH.nombres_de_reliquias(self.con)
        inverso = {i: n for n, i in nombres.items()}
        pantalla_reliquias = next((p for p in ("reliquias", "?Relics", "?RelicScreen")
                                   if RH.es_pantalla_de_reliquias(p)), "reliquias")
        hover.activar(True)
        # Jugando, Farmadex esta escondido: si no, el raton "esta encima de Farmadex" y no se lee.
        v.ocultar()
        motor = MotorOCR()
        random.seed(7)
        filas = []
        fotos = []
        for carpeta in self.op["hover"]:
            fotos += sorted(p for p in Path(carpeta).iterdir() if p.suffix.lower() in EXTENSIONES)
        for ruta in fotos:
            imagen = self.imagen(ruta)
            if imagen is None:
                continue
            h, w = imagen.shape[:2]
            verdad = []
            with self.sin_vigia():
                lineas_verdad = motor.leer(imagen)
            for linea in lineas_verdad:
                for nombre, _r in RH.reliquias_en_texto(linea.texto):
                    if nombre in nombres:
                        verdad.append((nombre, linea.x + linea.ancho // 2, linea.y + linea.alto // 2))
            if not verdad:
                continue
            sondas = random.sample(verdad, min(5, len(verdad)))
            negativas = []
            while len(negativas) < 2:
                x, y = random.randrange(w), random.randrange(h)
                if all(((x - a) ** 2 + (y - b) ** 2) ** 0.5 > 0.15 * h for _n, a, b in verdad):
                    negativas.append((None, x, y))
            for nombre, x, y in sondas + negativas:
                hover.pantalla_juego("abierta", pantalla_reliquias)
                self.sim.poner(imagen, cursor=(max(0, x - 200), max(0, y - 200)))
                self.bombear(0.25)
                self.sim.cursor = (x, y)
                t0 = time.perf_counter()
                tiempo = self.esperar(lambda: self.sondas.desde("VentanaOverlay._mostrar_reliquia_juego", t0),
                                      2.5 if nombre else 1.5)
                mostradas = self.sondas.desde("VentanaOverlay._mostrar_reliquia_juego", t0)
                leida = inverso.get(mostradas[-1][1][0]) if mostradas else None
                filas.append({"fichero": ruta.name, "verdad": nombre, "leida": leida,
                              "ms": _ms(tiempo) if tiempo is not None else None,
                              "acierto": bool(nombre and leida == nombre),
                              "inventada": bool(leida and leida != nombre)})
                if mostradas:
                    self.png(f"hover_{ruta.stem}", v.tarjeta_reliquia.tarjeta
                             if hasattr(v.tarjeta_reliquia, "tarjeta") else None)
        hover.pantalla_juego("cerrada", "")
        self.sim.poner(None)
        v.mostrar()
        positivas = [f for f in filas if f["verdad"]]
        self.flujo("hover", {
            "casos": filas,
            "tiempos": _resumen_tiempos([f["ms"] for f in positivas if f["ms"] is not None]),
            "aciertos": sum(f["acierto"] for f in positivas), "total": len(positivas),
            "inventados": sum(f["inventada"] for f in filas),
            "nota": "el tiempo incluye los 0,3 s de raton quieto que espera antes de leer",
        })

    # lo que sale solo sin atajo ---------------------------------------------------------------

    def _vigia_vistas(self, precio: bool, rivens: bool, builds: bool):
        vigia = getattr(self.ventana, "vigia_vistas", None)
        if vigia is not None:
            from .captura import vista

            # El cursor de verdad es el del PC donde corre la prueba: aqui manda el simulado.
            vista.cursor_visible = lambda: not getattr(self, "_cursor_escondido", False)
            vigia.activo_precio, vigia.activo_rivens, vigia.activo_builds = precio, rivens, builds
            vigia.franja_build.olvidar()
            vigia.franja_centro.olvidar()
            vigia._build_a_la_vista = False
        return vigia

    def _fondo_neutro(self, alto: int = 1080, ancho: int = 1920):
        import numpy as np

        return np.full((alto, ancho, 3), 22, np.uint8)

    def _fotos_vista(self, sub: str) -> list[Path]:
        if not self.op.get("vista"):
            return []
        carpeta = Path(self.op["vista"]) / sub
        if not carpeta.exists():
            return []
        return sorted(p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES and not p.name.startswith("_"))

    def _precios_de_prueba(self) -> None:
        """Sin el fichero diario de precios (lo trae otra zona), uno falso: el recuadro se
        pinta entero y se mide lo mismo que con el de verdad (una busqueda en memoria)."""
        from .ui import vista_objeto

        if vista_objeto._precios() is not None:
            return
        from datetime import datetime, timezone
        from types import SimpleNamespace

        fecha = datetime.now(timezone.utc)

        class Falso:
            def __init__(self):
                self.fecha = fecha

            def rangos(self, slug):
                return []

            def buscar(self, slug, rango=None):
                n = sum(slug.encode()) % 90 + 5
                return SimpleNamespace(slug=slug, rango=rango, venta_min=n, venta_mediana=n + 2, compra_max=n - 3,
                                       min_30d=n - 4, max_30d=n + 9, media_30d=n + 1, volumen_30d=120, fecha=fecha)

        falso = Falso()
        vista_objeto._precios = lambda: falso

    def flujo_vista_precio(self) -> None:
        import random

        v = self.ventana
        vigia = self._vigia_vistas(True, False, False)
        positivos = self._fotos_vista("positivos/tooltip_inventario")
        if vigia is None or not positivos:
            self.flujo("vista_precio", {"nota": "sin vigia de vistas o sin banco (--vista)"})
            return
        self._precios_de_prueba()
        verdad = json.loads((Path(self.op["vista"]) / "positivos/tooltip_inventario/verdad.json").read_text("utf-8"))
        v.ocultar()
        random.seed(11)
        filas = []
        clave = "ControladorVistas.mostrar_precio"
        for ruta in positivos:
            info = verdad.get(ruta.name)
            imagen = self.imagen(ruta)
            if info is None or imagen is None:
                continue
            h, w = imagen.shape[:2]
            ix, iy = info["icono"]
            destino = (max(5, ix - int(0.45 * h)), min(h - 5, iy + int(0.12 * h)))
            # El raton llega y se para sobre el objeto, y en ese momento el juego saca su
            # recuadro: hasta entonces, una pantalla sin nada.
            self.sim.poner(self._fondo_neutro(h, w), cursor=(min(w - 5, destino[0] + 300), max(5, destino[1] - 200)))
            self.bombear(0.3)
            t0 = time.perf_counter()
            self.sim.poner(imagen, cursor=destino)
            tiempo = self.esperar(lambda: self.sondas.desde(clave, t0), 2.0)
            mostradas = self.sondas.desde(clave, t0)
            slug = mostradas[-1][1][0].slug if mostradas else None
            filas.append({"fichero": ruta.name, "resolucion": f"{w}x{h}", "verdad": info.get("slug"), "leido": slug,
                          "ms": _ms(tiempo) if tiempo is not None else None,
                          "acierto": bool(slug and slug == info.get("slug")),
                          "inventado": bool(slug and slug != info.get("slug")),
                          "opcional": bool(info.get("opcional"))})
            if mostradas:
                self.png(f"vista_precio_{ruta.stem}", v.vistas.caja_precio)
            self.sim.cursor = (5, 5)
            self.bombear(0.15)
        # Negativos: pantallas sin recuadro de objeto, el raton parado en sitios al azar.
        negativas = []
        fondos = self._fotos_vista("negativos") + [r for r, _i in self.casos()["build"]][:12]
        for ruta in fondos:
            imagen = self.imagen(ruta)
            if imagen is None or imagen.shape[0] < 600 or ruta.name == "es_1440_reguladoras.png":
                continue
            h, w = imagen.shape[:2]
            self.sim.poner(imagen, cursor=(5, 5))
            for _ in range(2):
                self.bombear(0.12)
                t0 = time.perf_counter()
                self.sim.cursor = (random.randrange(20, w - 20), random.randrange(20, h - 20))
                self.bombear(0.6)
                mostradas = self.sondas.desde(clave, t0)
                negativas.append({"fichero": ruta.name, "inventado": bool(mostradas),
                                  "leido": mostradas[-1][1][0].slug if mostradas else None})
        self.sim.poner(None)
        self.bombear(0.2)
        v.vistas.esconder_precio()
        v.mostrar()
        self._vigia_vistas(False, False, False)
        obligadas = [f for f in filas if not f["opcional"]]
        tiempos = _resumen_tiempos([f["ms"] for f in filas if f["ms"] is not None and f["acierto"]])
        self.flujo("vista_precio", {
            "casos": filas, "negativos": len(negativas),
            "tiempos": tiempos,
            "aciertos": sum(f["acierto"] for f in obligadas), "total": len(obligadas),
            "inventados": sum(f["inventado"] for f in filas) + sum(f["inventado"] for f in negativas),
            "inventados_detalle": [f for f in filas + negativas if f["inventado"]],
            "ok": tiempos.get("max", 0) <= CRITERIOS["vista_ms"],
            "nota": "de parar el raton sobre el objeto a ver el recuadro de precio; incluye la espera de raton quieto",
        })

    def flujo_vista_riven(self) -> None:
        import numpy as np

        from .captura import agrietados as modulo

        v = self.ventana
        vigia = self._vigia_vistas(False, True, False)
        casos = self.casos()["agrietado"]
        if vigia is None or not casos:
            self.flujo("vista_riven", {"nota": "sin vigia de vistas o sin capturas de agrietados"})
            return
        v.ocultar()
        clave = "ControladorVistas.mostrar_riven"
        ancho_t, alto_t = modulo.ANCHO_TARJETA, modulo.ALTO_TARJETA
        filas = []
        for n, (ruta, info) in enumerate(casos):
            imagen = self.imagen(ruta)
            if imagen is None:
                continue
            h, w = imagen.shape[:2]
            # La tarjeta abierta en medio de la pantalla, a 1080p, 1440p y 4K por turnos.
            alto = (1080, 1440, 2160)[n % 3]
            if h < 700:  # un recorte de tarjeta: al tamano que tiene abierta (~0,42 del alto)
                import cv2

                factor = 0.42 * alto / h
                imagen = cv2.resize(imagen, (max(1, int(w * factor)), max(1, int(h * factor))),
                                    interpolation=cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA)
                h, w = imagen.shape[:2]
                ancho = alto * 16 // 9
                lienzo = np.full((alto, ancho, 3), 18, np.uint8)
                y0, x0 = (alto - h) // 2, (ancho - w) // 2
                lienzo[y0:y0 + h, x0:x0 + w] = imagen[:alto, :ancho]
            else:
                lienzo = imagen
            self.sim.poner(self._fondo_neutro(lienzo.shape[0], lienzo.shape[1]), cursor=(5, 5))
            self.bombear(0.5)
            t0 = time.perf_counter()
            self.sim.poner(lienzo, cursor=(5, 5))
            tiempo = self.esperar(lambda: self.sondas.desde(clave, t0), 2.5)
            llamadas = self.sondas.desde(clave, t0)
            fila = {"fichero": ruta.name, "resolucion": f"{lienzo.shape[1]}x{lienzo.shape[0]}",
                    "ms": _ms(tiempo) if tiempo is not None else None, "visto": bool(llamadas)}
            if llamadas:
                tarjeta = llamadas[-1][1][0]
                leidas = [[e.slug, e.valor, e.negativo] for e in tarjeta.estadisticas]
                if info.get("velado"):
                    fila["ok"] = bool(tarjeta.velado)
                    fila["inventado"] = False
                else:
                    arma_ok = tarjeta.arma_slug == info.get("arma")
                    stats_ok = len(leidas) == len(info.get("stats", [])) and all(
                        any(l[0] == s[0] and abs((l[1] or 0) - s[1]) < 0.05 and l[2] == s[2] for l in leidas)
                        for s in info.get("stats", []))
                    fila["ok"] = arma_ok and stats_ok
                    fila["fiable"] = bool(tarjeta.fiable)
                    # Solo se evalua (nota, precio) lo que el lector da por fiable.
                    fila["inventado"] = bool(tarjeta.fiable and not fila["ok"])
                if len(filas) < 6:
                    self.bombear(0.4)  # que llegue la red simulada y se pinte el panel entero
                    self.png(f"vista_riven_{ruta.stem}", v.vistas.caja_riven)
            filas.append(fila)
        # Negativos: pantallas sin agrietado abierto.
        negativas = []
        fondos = self._fotos_vista("negativos") + [r for r, _i in self.casos()["build"]]
        for ruta in fondos:
            imagen = self.imagen(ruta)
            if imagen is None or imagen.shape[0] < 600:
                continue
            self.sim.poner(self._fondo_neutro(imagen.shape[0], imagen.shape[1]), cursor=(5, 5))
            self.bombear(0.45)
            t0 = time.perf_counter()
            self.sim.poner(imagen, cursor=(5, 5))
            self.bombear(1.0)
            negativas.append({"fichero": ruta.name, "inventado": bool(self.sondas.desde(clave, t0))})
        self.sim.poner(None)
        self.bombear(0.3)
        v.vistas.esconder_riven()
        v.mostrar()
        self._vigia_vistas(False, False, False)
        vistos = [f for f in filas if f["visto"]]
        tiempos = _resumen_tiempos([f["ms"] for f in vistos if f["ms"] is not None])
        por_res = {}
        for f in vistos:
            por_res.setdefault(f["resolucion"].split("x")[1], []).append(f["ms"])
        self.flujo("vista_riven", {
            "casos": filas, "negativos": len(negativas),
            "tiempos": tiempos,
            "por_alto": {k: _resumen_tiempos(val) for k, val in por_res.items()},
            "vistos": len(vistos), "total": len(filas),
            "aciertos": sum(1 for f in vistos if f.get("ok")),
            "inventados": sum(1 for f in filas if f.get("inventado")) + sum(f["inventado"] for f in negativas),
            "inventados_detalle": [f for f in filas + negativas if f.get("inventado")],
            "ok": tiempos.get("max", 0) <= CRITERIOS["vista_ms"],
            "nota": "de aparecer la tarjeta en pantalla a verse el panel con la nota (el precio llega despues, por red)",
        })

    def flujo_vista_build(self) -> None:
        v = self.ventana
        vigia = self._vigia_vistas(False, False, True)
        casos = self.casos()["build"]
        if vigia is None or not casos:
            self.flujo("vista_build", {"nota": "sin vigia de vistas o sin capturas de builds"})
            return
        filas = []
        for ruta, info in casos:
            imagen = self.imagen(ruta)
            if imagen is None:
                continue
            v.ir_a("tablero")
            v.ocultar()
            self.sim.poner(self._fondo_neutro(imagen.shape[0], imagen.shape[1]), cursor=(5, 5))
            self.bombear(0.5)
            t0 = time.perf_counter()
            self.sim.poner(imagen, cursor=(5, 5))
            detectada = self.esperar(lambda: self.sondas.desde("VentanaOverlay._build_vista_sola", t0), 1.5)
            fila = {"fichero": ruta.name, "resolucion": f"{imagen.shape[1]}x{imagen.shape[0]}",
                    "detectada_ms": _ms(detectada) if detectada is not None else None, "ms": None,
                    "no_legible": bool(info.get("no_legible"))}
            if detectada is not None:
                self.esperar(lambda: self.sondas.desde("VentanaOverlay._build_leida", t0), 10.0)
                llamadas = self.sondas.desde("VentanaOverlay._build_leida", t0)
                if llamadas:
                    fila["ms"] = _ms(llamadas[0][0] - t0)
                    fila.update(self._evaluar_build(info, llamadas[0][1][0]))
            filas.append(fila)
        negativas = []
        fondos = self._fotos_vista("negativos") + self._fotos_vista("positivos/tooltip_inventario")
        for ruta in fondos:
            imagen = self.imagen(ruta)
            if imagen is None or imagen.shape[0] < 600 or ruta.name.endswith("es_arsenal.png"):
                continue
            v.ocultar()
            self.sim.poner(self._fondo_neutro(imagen.shape[0], imagen.shape[1]), cursor=(5, 5))
            self.bombear(0.45)
            t0 = time.perf_counter()
            self.sim.poner(imagen, cursor=(5, 5))
            self.bombear(0.9)
            negativas.append({"fichero": ruta.name, "inventado": bool(self.sondas.desde("VentanaOverlay._build_vista_sola", t0))})
        self.sim.poner(None)
        self.bombear(0.3)
        v.mostrar()
        self._vigia_vistas(False, False, False)
        leidas = [f for f in filas if f["ms"] is not None]
        legibles = [f for f in leidas if not f["no_legible"] and "aciertos" in f]
        tiempos = _resumen_tiempos([f["ms"] for f in leidas])
        self.flujo("vista_build", {
            "casos": filas, "negativos": len(negativas),
            "tiempos": tiempos,
            "deteccion": _resumen_tiempos([f["detectada_ms"] for f in filas if f["detectada_ms"] is not None]),
            "detectadas": len(leidas), "total": len(filas),
            "aciertos": sum(f["aciertos"] for f in legibles), "total_mods": sum(f["total"] for f in legibles),
            "inventados": sum(len(f.get("inventados", [])) for f in filas) + sum(f["inventado"] for f in negativas),
            "falsas_detecciones": [f["fichero"] for f in negativas if f["inventado"]],
            "ok": tiempos.get("max", 0) <= CRITERIOS["vista_ms"],
            "nota": "de aparecer la pantalla de mejoras a tener la build leida, sin atajo",
        })

    def flujo_vista_reposo(self) -> None:
        """Lo que cuesta tener el vigia encendido: con una pantalla quieta y jugando (imagen que no para)."""
        import numpy as np

        v = self.ventana
        vigia = getattr(v, "vigia_vistas", None)
        if vigia is None:
            self.flujo("vista_reposo", {"nota": "esta version no tiene vigia de vistas"})
            return
        v.ocultar()
        import cv2

        # Una pantalla de menu de verdad a 4K, quieta; y "jugando": la misma imagen
        # desplazandose sin parar, como la camara en una partida.
        casos = self.casos()["build"]
        base = self.imagen(casos[0][0]) if casos else None
        if base is None:
            base = self._fondo_neutro(2160, 3840)
        quieta = cv2.resize(base, (3840, 2160), interpolation=cv2.INTER_LINEAR)
        fotogramas = [np.ascontiguousarray(np.roll(quieta, (k * 277, k * 431), axis=(0, 1))) for k in range(1, 7)]
        menu = False
        nucleos = max(1, self.resultado.get("nucleos") or 1)

        def medir(encendido: bool, jugando: bool, segundos: float = 10.0, menu: bool = False) -> dict:
            self._vigia_vistas(encendido, encendido, encendido)
            self.sim.poner(quieta, cursor=(900, 700))
            self.bombear(2.5)  # lo que se lea al aparecer la pantalla no es reposo
            lecturas0 = dict(vigia.lecturas)
            sondeos0 = vigia.sondeos
            cpu0, t0 = time.process_time(), time.perf_counter()
            k = 0
            while time.perf_counter() - t0 < segundos:
                self._cursor_escondido = jugando and not menu
                if jugando:
                    k += 1
                    self.sim.poner(fotogramas[k % len(fotogramas)], cursor=(900 + (k * 37) % 400, 700))
                self.bombear(0.03 if jugando else 0.1)  # ~30 imagenes por segundo
            pared = time.perf_counter() - t0
            cpu = time.process_time() - cpu0
            return {"cpu_pct_de_un_nucleo": round(100 * cpu / pared, 2),
                    "lecturas_ocr": sum(vigia.lecturas.values()) - sum(lecturas0.values()),
                    "sondeos": vigia.sondeos - sondeos0}

        with self.sin_vigia():
            datos = {
                "apagado_quieto": medir(False, False), "encendido_quieto": medir(True, False),
                "apagado_jugando": medir(False, True), "encendido_jugando": medir(True, True),
                # Un menu que no para quieto (fondo animado), con el cursor a la vista: el peor caso.
                "encendido_menu_animado": medir(True, True, menu=True),
            }
        self._cursor_escondido = False
        self._vigia_vistas(False, False, False)
        self.sim.poner(None)
        v.mostrar()
        datos["coste_quieto_pct"] = round(datos["encendido_quieto"]["cpu_pct_de_un_nucleo"]
                                          - datos["apagado_quieto"]["cpu_pct_de_un_nucleo"], 2)
        datos["coste_jugando_pct"] = round(datos["encendido_jugando"]["cpu_pct_de_un_nucleo"]
                                           - datos["apagado_jugando"]["cpu_pct_de_un_nucleo"], 2)
        datos["nucleos"] = nucleos
        datos["nota"] = ("% de un nucleo que gasta de mas el proceso con el vigia encendido, a 4K; la captura "
                         "simulada es una copia en memoria (mas cara en CPU que la real de Windows)")
        datos["ok"] = datos["encendido_jugando"]["lecturas_ocr"] == 0
        self.flujo("vista_reposo", datos)

    def flujo_tarjeta_app(self) -> None:
        """La tabla de una reliquia dentro de Farmadex (enlace o texto de una reliquia)."""
        from PySide6.QtCore import QPoint

        v = self.ventana
        servicio = getattr(v, "tarjeta_reliquia", None)
        if servicio is None:
            self.flujo("tarjeta_app", {"nota": "sin tabla de reliquia en esta version"})
            return
        ids = [r[0] for r in self.con.execute(
            "SELECT id FROM items WHERE categoria = 'Relics' ORDER BY id LIMIT 400")][::40]
        tiempos = []
        mostradas = 0
        for rid in ids:
            t0 = time.perf_counter()
            ok = servicio.mostrar(rid, QPoint(300, 300))
            self.app.processEvents()
            tiempos.append(_ms(time.perf_counter() - t0))
            mostradas += bool(ok)
            servicio.ocultar()
        self.flujo("tarjeta_app", {"tiempos": _resumen_tiempos(tiempos), "mostradas": mostradas,
                                   "total": len(ids)})

    # atajos en rafaga ----------------------------------------------------------------------------

    RAFAGA_N = 40

    def _disparar(self, nombre: str) -> None:
        """Lo mismo que hace la aplicacion al recibir un atajo (app.Aplicacion._hotkey)."""
        v = self.ventana
        metodo = {"overlay": "alternar", "reliquias": "leer_recompensas", "cursor": "leer_cursor",
                  "build": "leer_build", "agrietado": "leer_agrietado"}[nombre]
        getattr(v, metodo)()

    def flujo_rafagas(self) -> None:
        """Cada atajo pulsado muchas veces seguidas, y todos mezclados: nada peta, no se
        encolan decenas de lecturas y, al acabar, una pulsacion normal sigue funcionando."""
        import random

        v = self.ventana
        casos = self.casos()
        imagen_de = {}
        for tipo in ("build", "agrietado", "recompensas"):
            for ruta, info in casos.get(tipo, []):
                if info.get("fila") or info.get("franja") or info.get("no_legible"):
                    continue
                img = self.imagen(ruta)
                if img is not None:
                    imagen_de[tipo] = img
                    break
        sondas = {"build": "VentanaOverlay._build_leida", "agrietado": "VentanaOverlay._agrietado_leido",
                  "reliquias": "VentanaOverlay._pintar_recompensas",
                  "cursor": "VentanaOverlay._lectura_cursor_terminada"}
        imagen_para = {"build": "build", "agrietado": "agrietado", "reliquias": "recompensas",
                       "cursor": "recompensas"}
        capturas_antes = self.sim.capturas
        excepciones_antes = len(self.excepciones)
        filas = []

        def calmarse(claves: list[str], maximo: float, calma: float = 1.5) -> float:
            """Espera a que no llegue ninguna lectura mas en `calma` s; devuelve cuando llego la ultima."""
            t_fin = time.perf_counter() + maximo
            previas, ultima_t = sum(self.sondas.n(c) for c in claves), time.perf_counter()
            while time.perf_counter() < t_fin:
                self.bombear(0.05)
                n = sum(self.sondas.n(c) for c in claves)
                if n != previas:
                    previas, ultima_t = n, time.perf_counter()
                elif time.perf_counter() - ultima_t > calma:
                    break
            return ultima_t

        for nombre, clave in sondas.items():
            img = imagen_de.get(imagen_para[nombre])
            if img is None:
                continue
            self.sim.poner(img)
            self.bombear(1.0)
            n0 = self.sondas.n(clave)
            t0 = time.perf_counter()
            hueco = 0.0
            for _ in range(self.RAFAGA_N):
                self._disparar(nombre)
                hueco = max(hueco, self.bombear(0.01))
            ultima = calmarse([clave], 90.0)
            lecturas = self.sondas.n(clave) - n0
            # Despues de la rafaga, una pulsacion normal tiene que leer.
            self.bombear(1.0)
            t1 = time.perf_counter()
            self._disparar(nombre)
            despues = self.esperar(lambda: self.sondas.desde(clave, t1), 15.0)
            filas.append({"atajo": nombre, "pulsaciones": self.RAFAGA_N, "lecturas": lecturas,
                          "hasta_calmarse_ms": _ms(ultima - t0),
                          "despues_ms": _ms(despues) if despues is not None else None,
                          "congelada_ms": _ms(hueco)})
            self.bombear(0.5)
            if nombre == "reliquias":
                v.etiquetas.hide()
        # Todo mezclado, como quien aporrea el teclado (con el de ensenar/esconder incluido).
        random.seed(11)
        nombres = ("overlay", "reliquias", "cursor", "build", "agrietado")
        self.sim.poner(imagen_de.get("build") if imagen_de.get("build") is not None
                       else imagen_de.get("recompensas"))
        t0 = time.perf_counter()
        hueco = 0.0
        for _ in range(150):
            self._disparar(random.choice(nombres))
            hueco = max(hueco, self.bombear(random.choice((0.0, 0.002, 0.01, 0.03))))
        ultima_t = calmarse(list(sondas.values()), 120.0, calma=2.0)
        mezcla = {"pulsaciones": 150, "hasta_calmarse_ms": _ms(ultima_t - t0), "congelada_ms": _ms(hueco)}
        if not v.isVisible():
            v.mostrar()
        # Y otra vez una lectura normal de cada cosa (con el recuadro "Leyendo...", si lo hay).
        normales = {}
        recuadro = {}
        aviso = getattr(v, "aviso_lectura", None)
        for nombre, clave in sondas.items():
            img = imagen_de.get(imagen_para[nombre])
            if img is None:
                continue
            self.sim.poner(img)
            self.bombear(1.0)
            t1 = time.perf_counter()
            self._disparar(nombre)
            al_pulsar = bool(aviso is not None and aviso.visible() and aviso.estado == "leyendo")
            r = self.esperar(lambda: self.sondas.desde(clave, t1), 15.0)
            normales[nombre] = _ms(r) if r is not None else None
            if aviso is not None:
                self.bombear(0.05)
                recuadro[nombre] = {"sale_al_pulsar": al_pulsar, "pintar_ms": round(aviso.ultimo_ms, 1),
                                    "al_acabar": aviso.estado or "escondido"}
        self.bombear(0.5)
        v.etiquetas.hide()
        self.sim.poner(None)
        nuevas = self.excepciones[excepciones_antes:]
        ok = (not nuevas and all(f["despues_ms"] is not None for f in filas)
              and all(x is not None for x in normales.values())
              and all(f["lecturas"] <= self.RAFAGA_MAX_LECTURAS for f in filas))
        if recuadro:
            # Sin exclusion de capturas (offscreen, Windows antiguo) la build va sin recuadro.
            excluida = bool(aviso.caja is not None and aviso.caja.excluida)
            ok = ok and all((r["sale_al_pulsar"] or (n == "build" and not excluida)) and r["al_acabar"] != "leyendo"
                            for n, r in recuadro.items())
        self.flujo("rafagas", {"atajos": filas, "mezcla": mezcla, "despues_de_la_mezcla_ms": normales,
                               "recuadro": recuadro,
                               "capturas": self.sim.capturas - capturas_antes,
                               "excepciones": len(nuevas), "ok": ok})

    # Una rafaga de 40 pulsaciones en medio segundo: como mucho la lectura en curso y una
    # mas (la ultima pulsacion), con margen para los reintentos propios de cada lector.
    RAFAGA_MAX_LECTURAS = 6

    # busqueda tecla a tecla ---------------------------------------------------------------------

    def _teclear(self, caja, texto: str, intervalo: float) -> tuple[list[float], float, float]:
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        teclas, hueco = [], 0.0
        t_ultima = time.perf_counter()
        for ch in texto:
            destino = caja() if callable(caja) else caja
            t0 = time.perf_counter()
            tecla = Qt.Key_Space if ch == " " else (Qt.Key(ord(ch.upper())) if ch.isalnum() and ch.isascii() else 0)
            for tipo in (QEvent.KeyPress, QEvent.KeyRelease):
                self.app.sendEvent(destino, QKeyEvent(tipo, tecla, Qt.NoModifier, ch))
            dt = time.perf_counter() - t0
            teclas.append(dt)
            hueco = max(hueco, dt)
            t_ultima = t0
            hueco = max(hueco, self.bombear(intervalo))
        return teclas, hueco, t_ultima

    def _resultados_desde(self, claves: list[str], t0: float, texto: str) -> float | None:
        mejores = []
        for clave in claves:
            for t, args in self.sondas.desde(clave, t0):
                primero = args[0] if args else None
                if isinstance(primero, str) and primero.strip() != texto.strip():
                    continue
                mejores.append(t)
        return (min(mejores) - t0) if mejores else None

    def _primer_resultado(self, resultados: list) -> str:
        if not resultados:
            return ""
        r = resultados[0]
        if isinstance(r, dict) and r.get("item_id"):
            return self.nombre_en(r["item_id"]) or r.get("nombre", "")
        if isinstance(r, dict):
            return str(r.get("nombre") or r.get("nombre_en") or r.get("clave") or "mision")
        return str(r)

    def flujo_buscar(self) -> None:
        v = self.ventana
        intervalo = 0.12  # alguien que escribe rapido
        filas = []
        claves_buscar = ["PestanaBuscador._aplicar_busqueda", "PestanaBuscador._buscar"]

        def prep_buscar():
            v.ir_a("buscar")
            v.buscador.caja.clear()
            v.buscador.caja.setFocus()
            self.bombear(0.3)

        def prep_tablero():
            v.buscador.caja.clear()
            v.ir_a("tablero")
            v.tablero.caja.setFocus()
            self.bombear(0.3)

        def caja_tablero():
            return v.buscador.caja if v.buscador.caja.text() else v.tablero.caja

        for donde, prep, caja in (("Buscar", prep_buscar, lambda: v.buscador.caja),
                                  ("Tablero", prep_tablero, caja_tablero)):
            for texto, esperado in CONSULTAS:
                prep()
                teclas, hueco, t_ultima = self._teclear(caja, texto, intervalo)
                self.bombear(1.0)
                resultado_ms = self._resultados_desde(claves_buscar, t_ultima, texto)
                primero = self._primer_resultado(getattr(v.buscador, "_resultados", []))
                acierto = None
                if esperado is not None:
                    acierto = (not primero) if esperado == "" else _normal(esperado) in _normal(primero)
                filas.append({"donde": donde, "texto": texto, "tecla_max_ms": _ms(max(teclas)),
                              "congelada_max_ms": _ms(hueco),
                              "resultados_ms": _ms(resultado_ms) if resultado_ms is not None else None,
                              "primero": primero, "acierto": acierto,
                              "texto_en_caja": v.buscador.caja.text()})
        self.png("buscar")
        self.flujo("buscar", self._resumen_busquedas(filas))

    def _resumen_busquedas(self, filas: list[dict]) -> dict:
        con_esperado = [f for f in filas if f["acierto"] is not None]
        return {
            "casos": filas,
            "tecla": _resumen_tiempos([f["tecla_max_ms"] for f in filas]),
            "congelada": _resumen_tiempos([f["congelada_max_ms"] for f in filas]),
            "resultados": _resumen_tiempos([f["resultados_ms"] for f in filas if f["resultados_ms"] is not None]),
            "sin_resultados_a_tiempo": sum(1 for f in filas if f["resultados_ms"] is None and f.get("primero")),
            "aciertos": sum(1 for f in con_esperado if f["acierto"]), "total": len(con_esperado),
            "texto_perdido": sum(1 for f in filas if f.get("texto_en_caja") not in (None, f["texto"])
                                 and f["donde"] != "Modo juego"),
        }

    def flujo_modo_juego(self) -> None:
        v = self.ventana
        filas = []
        t0 = time.perf_counter()
        v.aplicar_modo("compacto")
        self.app.processEvents()
        cambio_ms = _ms(time.perf_counter() - t0)
        for texto, esperado in CONSULTAS:
            v.compacta.caja.clear()
            v.compacta.caja.setFocus()
            self.bombear(0.3)
            teclas, hueco, t_ultima = self._teclear(v.compacta.caja, texto, 0.12)
            self.bombear(1.0)
            resultado_ms = self._resultados_desde(["VistaCompacta._buscar"], t_ultima, texto)
            primero = self._primer_resultado(getattr(v.compacta, "_resultados", []))
            acierto = None
            if esperado is not None:
                acierto = (not primero) if esperado == "" else _normal(esperado) in _normal(primero)
            filas.append({"donde": "Modo juego", "texto": texto, "tecla_max_ms": _ms(max(teclas)),
                          "congelada_max_ms": _ms(hueco),
                          "resultados_ms": _ms(resultado_ms) if resultado_ms is not None else None,
                          "primero": primero, "acierto": acierto, "texto_en_caja": v.compacta.caja.text()})
        self.png("modo_juego")
        t0 = time.perf_counter()
        v.aplicar_modo("completo")
        self.app.processEvents()
        datos = self._resumen_busquedas(filas)
        datos["cambiar_modo_ms"] = [cambio_ms, _ms(time.perf_counter() - t0)]
        self.flujo("modo_juego", datos)

    # fichas y secciones ----------------------------------------------------------------------------

    def flujo_fichas(self) -> None:
        v = self.ventana
        v.ir_a("buscar")
        self.bombear(0.2)
        ids: list[tuple[str, int]] = []
        for (item_id,) in self.con.execute(
                "SELECT item_id FROM fuentes GROUP BY item_id ORDER BY COUNT(*) DESC LIMIT 6"):
            ids.append(("mas fuentes", item_id))
        for nombre in ("Ash Prime", "Forma Blueprint", "Axi A1 Relic", "Serration", "Orokin Cell", "Rhino Prime",
                       "Neurodes", "Arcane Energize"):
            fila = self.con.execute("SELECT id FROM items WHERE nombre_en = ? ORDER BY id LIMIT 1", (nombre,)).fetchone()
            if fila:
                ids.append((nombre, fila[0]))
        filas = []
        for motivo, item_id in ids:
            t0 = time.perf_counter()
            v.buscador.abrir(item_id)
            v.grab()  # pintarla entera: es lo que ve el usuario
            dt = time.perf_counter() - t0
            filas.append({"objeto": self.nombre_en(item_id), "motivo": motivo, "ms": _ms(dt),
                          "abierta": getattr(v.buscador, "_actual", item_id) == item_id})
            self.png(f"ficha_{item_id}")
        # Fichas de mision (nodo y tipo) si esta version las tiene.
        if hasattr(v.buscador, "abrir_mision"):
            for clave in ("modo:Survival", "modo:Defense"):
                try:
                    t0 = time.perf_counter()
                    v.buscador.abrir_mision(clave)
                    v.grab()
                    filas.append({"objeto": clave, "motivo": "mision", "ms": _ms(time.perf_counter() - t0),
                                  "abierta": True})
                except Exception as e:  # noqa: BLE001
                    filas.append({"objeto": clave, "motivo": "mision", "ms": None, "abierta": False,
                                  "fallo": f"{type(e).__name__}: {e}"})
        self.flujo("fichas", {"casos": filas,
                              "tiempos": _resumen_tiempos([f["ms"] for f in filas if f["ms"] is not None]),
                              "abiertas": sum(1 for f in filas if f["abierta"]), "total": len(filas)})

    def flujo_secciones(self) -> None:
        from .ui import overlay as modulo

        v = self.ventana
        rutas = []
        for clave, _titulo in modulo.SECCIONES:
            subs = getattr(modulo, "SUBSECCIONES", {}).get(clave)
            rutas += [f"{clave}/{s}" for s, _t in subs] if subs else [clave]
        filas = []
        for vuelta in range(2):  # la primera vez construye; la segunda es lo que se nota a diario
            for ruta in rutas:
                t0 = time.perf_counter()
                v.ir_a(ruta)
                v.grab()
                dt = time.perf_counter() - t0
                filas.append({"ruta": ruta, "vuelta": vuelta + 1, "ms": _ms(dt),
                              "llega": (v.ruta_actual() == ruta) if hasattr(v, "ruta_actual") else None})
                if vuelta == 0:
                    self.png(f"seccion_{ruta.replace('/', '_')}")
        self.flujo("secciones", {
            "casos": filas,
            "primera": _resumen_tiempos([f["ms"] for f in filas if f["vuelta"] == 1]),
            "tiempos": _resumen_tiempos([f["ms"] for f in filas if f["vuelta"] == 2]),
            "no_llega": sum(1 for f in filas if f["llega"] is False),
        })

    def flujo_refrescos(self) -> None:
        """Lo que la ventana hace sola cada rato (mundo, relojes, tarjetas del modo juego):
        si tarda, congela lo que el usuario este haciendo en ese momento."""
        v = self.ventana
        filas = []

        def medir(nombre: str, accion, vueltas: int = 3) -> None:
            tiempos = []
            for _ in range(vueltas):
                self.bombear(0.05)
                t0 = time.perf_counter()
                accion()
                self.app.processEvents()
                tiempos.append(_ms(time.perf_counter() - t0))
            filas.append({"que": nombre, "tiempos": _resumen_tiempos(tiempos)})

        servicio = getattr(v, "servicio_mundo", None)
        mundo = getattr(servicio, "ultimo", None) if servicio is not None else None
        for modo in ("completo", "compacto"):
            v.aplicar_modo(modo)
            v.ir_a("tablero") if modo == "completo" else None
            self.bombear(0.5)
            if mundo is not None:
                medir(f"mundo actualizado ({modo})", lambda: servicio.actualizado.emit(mundo))
            if modo == "completo" and hasattr(v.tablero, "_relojes"):
                medir("relojes del tablero", v.tablero._relojes.timeout.emit)
            if modo == "compacto" and hasattr(v.compacta, "_reloj_hud"):
                medir("tarjetas del modo juego", v.compacta._reloj_hud.timeout.emit)
        v.aplicar_modo("completo")
        self.bombear(0.2)
        self.flujo("refrescos", {"casos": filas,
                                 "tiempos": _resumen_tiempos([f["tiempos"]["max"] for f in filas if f["tiempos"].get("n")])})

    def flujo_minimizar(self) -> None:
        v = self.ventana
        if not hasattr(v, "minimizar"):
            self.flujo("minimizar", {"nota": "esta version no tiene boton de minimizar"})
            return
        v.ir_a("tablero")
        v.mostrar()
        self.bombear(0.1)
        t0 = time.perf_counter()
        v.minimizar()
        self.bombear(0.2)
        minimizada = v.isMinimized()
        v.alternar()  # el atajo: tiene que volver
        self.bombear(0.2)
        vuelve_atajo = v.isVisible() and not v.isMinimized()
        v.minimizar()
        self.bombear(0.2)
        v.mostrar()  # la bandeja
        self.bombear(0.2)
        vuelve_bandeja = v.isVisible() and not v.isMinimized()
        v.alternar()  # esconder
        self.bombear(0.1)
        escondida = not v.isVisible()
        v.alternar()
        self.bombear(0.1)
        self.flujo("minimizar", {
            "minimizada": minimizada, "vuelve_con_atajo": vuelve_atajo, "vuelve_con_bandeja": vuelve_bandeja,
            "atajo_esconde": escondida, "visible_al_final": v.isVisible(),
            "ms": _ms(time.perf_counter() - t0),
            "ok": minimizada and vuelve_atajo and vuelve_bandeja and escondida and v.isVisible(),
            "nota": "sin pantalla (offscreen) Qt solo cambia el estado de la ventana; el efecto real en la "
                    "barra de tareas de Windows no se ve",
        })

    def flujo_bienvenida(self) -> None:
        v = self.ventana
        t0 = time.perf_counter()
        v.mostrar_bienvenida()
        self.app.processEvents()
        capa = getattr(v, "_bienvenida", None)
        if capa is None:
            self.flujo("bienvenida", {"ok": False, "nota": "no se abrio"})
            return
        abrir_ms = _ms(time.perf_counter() - t0)
        paginas = capa.paginas.count() if hasattr(capa, "paginas") else 0
        tiempos = []
        for i in range(paginas):
            t0 = time.perf_counter()
            capa._ir_a(i)
            v.grab()
            tiempos.append(_ms(time.perf_counter() - t0))
            self.png(f"bienvenida_{i + 1}")
        capa.terminar(False)
        self.bombear(0.1)
        self.flujo("bienvenida", {"abrir_ms": abrir_ms, "paginas": paginas, "tiempos": _resumen_tiempos(tiempos),
                                  "cerrada": getattr(v, "_bienvenida", None) is None,
                                  "ok": paginas > 0 and getattr(v, "_bienvenida", None) is None})

    def flujo_guia(self) -> None:
        v = self.ventana
        v.mostrar_guia()
        self.app.processEvents()
        capa = getattr(v, "_guia", None)
        if capa is None:
            self.flujo("guia", {"ok": False, "nota": "no se abrio"})
            return
        pasos = len(getattr(capa, "_pasos", []))
        tiempos = []
        for i in range(pasos + 2):
            if getattr(v, "_guia", None) is None:
                break
            self.png(f"guia_{i + 1}")
            t0 = time.perf_counter()
            capa.siguiente()
            v.grab()
            tiempos.append(_ms(time.perf_counter() - t0))
        self.bombear(0.1)
        self.flujo("guia", {"pasos": pasos, "tiempos": _resumen_tiempos(tiempos),
                            "cerrada": getattr(v, "_guia", None) is None,
                            "ok": pasos > 0 and getattr(v, "_guia", None) is None})

    def flujo_cierre(self) -> None:
        v = self.ventana
        if v is None:
            return
        t0 = time.perf_counter()
        v.cerrar_de_verdad()
        self.bombear(0.3)
        vivos = [h.name for h in threading.enumerate() if h is not threading.current_thread()
                 and not h.daemon and h.is_alive()]
        self.flujo("cierre", {"ms": _ms(time.perf_counter() - t0), "hilos_sin_cerrar": vivos,
                              "capturas_inyectadas": self.sim.capturas,
                              "peticiones_red": len(self.red.peticiones),
                              "red_real_intentada": [p for p in self.red.peticiones if p.startswith("SOCKET")]})

    # -- veredicto e informe ----------------------------------------------------------------

    def _errores_registro(self) -> None:
        from .registro_log import RUTA_LOG

        lineas = []
        try:
            for linea in RUTA_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
                if " ERROR " in linea or " CRITICAL " in linea or "Traceback" in linea:
                    lineas.append(linea[:300])
        except OSError:
            pass
        self.resultado["errores_registro"] = lineas

    def _veredicto(self) -> bool:
        f = self.resultado["flujos"]
        fallos = []

        def falla(texto: str) -> None:
            fallos.append(texto)

        if self.excepciones:
            falla(f"{len(self.excepciones)} excepciones")
        if self.resultado.get("errores_registro"):
            falla(f"{len(self.resultado['errores_registro'])} errores en el registro")
        for nombre, datos in f.items():
            if datos.get("roto"):
                falla(f"flujo {nombre} roto: {datos['roto']}")
            if datos.get("ok") is False:
                falla(f"flujo {nombre} no cumple")
            if datos.get("inventados") or datos.get("inventadas"):
                falla(f"{nombre}: {datos.get('inventados') or datos.get('inventadas')} inventados")
        r = f.get("recompensas", {})
        for modo in ("atajo", "eelog"):
            m = r.get(modo, {})
            if m.get("inventadas"):
                falla(f"recompensas ({modo}): {m['inventadas']} inventadas")
            if m.get("tiempos", {}).get("max", 0) > CRITERIOS["recompensas_ms"]:
                falla(f"recompensas ({modo}) max {m['tiempos']['max']} ms > {CRITERIOS['recompensas_ms']}")
            if m.get("sin_completar"):
                falla(f"recompensas ({modo}): {m['sin_completar']} pantallas sin todas las tarjetas")
        b = f.get("build", {})
        if b.get("tiempos", {}).get("max", 0) > CRITERIOS["build_ms"]:
            falla(f"build max {b['tiempos']['max']} ms > {CRITERIOS['build_ms']}")
        if b.get("incompletas"):
            # Una build con un mod de menos (o de mas) es una build inutil: cada pantalla
            # legible tiene que salir entera.
            falla(f"build: {len(b['incompletas'])} de {b.get('legibles', 0)} pantallas legibles sin la build completa"
                  f" ({', '.join(b['incompletas'][:6])})")
        for nombre in ("buscar", "modo_juego"):
            d = f.get(nombre, {})
            if d.get("congelada", {}).get("max", 0) > CRITERIOS["tecla_ms"]:
                falla(f"{nombre}: la ventana se congela {d['congelada']['max']} ms al teclear")
            if d.get("congelada", {}).get("p90", 0) > CRITERIOS["tecla_p90_ms"]:
                falla(f"{nombre}: la ventana se para {d['congelada']['p90']} ms al teclear en 1 de cada 10 busquedas")
            if d.get("resultados", {}).get("max", 0) > CRITERIOS["resultados_ms"]:
                falla(f"{nombre}: resultados en {d['resultados']['max']} ms > {CRITERIOS['resultados_ms']}")
            if d.get("texto_perdido"):
                falla(f"{nombre}: se pierde lo tecleado en {d['texto_perdido']} busquedas")
            if d.get("total") and d.get("aciertos", 0) < d["total"]:
                falla(f"{nombre}: {d['total'] - d['aciertos']} busquedas con el primer resultado equivocado")
        fi = f.get("fichas", {})
        if fi.get("tiempos", {}).get("max", 0) > CRITERIOS["ficha_ms"]:
            falla(f"fichas max {fi['tiempos']['max']} ms > {CRITERIOS['ficha_ms']}")
        rf = f.get("refrescos", {})
        if rf.get("tiempos", {}).get("max", 0) > CRITERIOS["refresco_ms"]:
            falla(f"refrescos: la ventana se para {rf['tiempos']['max']} ms al refrescarse sola")
        se = f.get("secciones", {})
        if se.get("tiempos", {}).get("max", 0) > CRITERIOS["seccion_ms"]:
            falla(f"secciones max {se['tiempos']['max']} ms > {CRITERIOS['seccion_ms']}")
        if se.get("no_llega"):
            falla(f"secciones: {se['no_llega']} no llegan")
        if f.get("cierre", {}).get("red_real_intentada"):
            falla("se intento salir a la red de verdad")
        reales = [c for c in self.resultado.get("congelaciones", []) if c["flujo"] != "(autoprueba)"
                  and c["flujo"] not in ("arranque", "cierre", "actualizar_al_abrir")]
        graves = [c for c in reales if c["ms"] > CRITERIOS["congelacion_ms"]]
        if graves:
            falla(f"{len(graves)} congelaciones de la ventana de mas de {CRITERIOS['congelacion_ms']} ms "
                  f"(la peor {max(c['ms'] for c in graves)} ms en {graves[0]['flujo']})")
        self.resultado["fallos"] = fallos
        self.resultado["ok"] = not fallos
        return not fallos

    def _informe(self) -> None:
        f = self.resultado["flujos"]
        l = [f"Autoprueba Farmadex {self.resultado.get('version', '?')} "
             f"{'(exe)' if self.resultado.get('frozen') else '(codigo)'} {self.resultado.get('etiqueta', '')}",
             f"Nucleos: {self.resultado.get('nucleos')}  carga: {self.op['carga']}  "
             f"{self.resultado['inicio']} -> {self.resultado.get('fin', '')}", ""]

        def tiempos(d: dict | None) -> str:
            if not d or not d.get("n"):
                return "-"
            return f"mediana {d['mediana']} / p90 {d['p90']} / max {d['max']} ms (n={d['n']})"

        a = f.get("arranque", {})
        l.append(f"arranque: ventana {a.get('construir_ms')} ms, datos listos {a.get('datos_listos_ms')} ms, "
                 f"lectores listos {a.get('lectores_listos_ms')} ms")
        r = f.get("recompensas", {})
        for modo in ("atajo", "eelog"):
            m = r.get(modo, {})
            l.append(f"recompensas {modo}: {m.get('aciertos')}/{m.get('total')} tarjetas, inventadas "
                     f"{m.get('inventadas')}, sin completar {m.get('sin_completar')}; {tiempos(m.get('tiempos'))}")
        for nombre in ("cursor", "build", "agrietado", "hover"):
            d = f.get(nombre, {})
            extra = f" equipo {d['equipo'][0]}/{d['equipo'][1]}" if nombre == "build" and d.get("equipo") else ""
            if nombre == "build" and d.get("legibles") is not None:
                extra += (f", builds completas {d.get('completas')}/{d.get('legibles')}"
                          f", huecos ocupados sin leer {d.get('no_leidos', 0)}")
            l.append(f"{nombre}: {d.get('aciertos')}/{d.get('total')}{extra}, inventados {d.get('inventados')}; "
                     f"{tiempos(d.get('tiempos'))}{'  ' + d['nota'] if d.get('nota') and not d.get('total') else ''}")
        d = f.get("vista_precio", {})
        if d.get("total"):
            l.append(f"precio solo (objeto a la vista): {d.get('aciertos')}/{d.get('total')}, inventados "
                     f"{d.get('inventados')} ({d.get('negativos')} paradas sin objeto); {tiempos(d.get('tiempos'))}")
        d = f.get("vista_riven", {})
        if d.get("total"):
            l.append(f"agrietado solo: vistos {d.get('vistos')}/{d.get('total')}, bien {d.get('aciertos')}, inventados "
                     f"{d.get('inventados')} ({d.get('negativos')} pantallas sin agrietado); {tiempos(d.get('tiempos'))}")
        d = f.get("vista_build", {})
        if d.get("total"):
            l.append(f"build sola: detectadas {d.get('detectadas')}/{d.get('total')}, mods {d.get('aciertos')}/"
                     f"{d.get('total_mods')}, inventados {d.get('inventados')} ({d.get('negativos')} pantallas que no son); "
                     f"deteccion {tiempos(d.get('deteccion'))}; hasta la build leida {tiempos(d.get('tiempos'))}")
        d = f.get("vista_reposo", {})
        if "coste_quieto_pct" in d:
            l.append(f"vigia de vistas en reposo: +{d['coste_quieto_pct']} % de un nucleo con la pantalla quieta, "
                     f"+{d['coste_jugando_pct']} % jugando; lecturas OCR jugando {d['encendido_jugando']['lecturas_ocr']}")
        t = f.get("tarjeta_app", {})
        l.append(f"tarjeta de reliquia en la app: {t.get('mostradas')}/{t.get('total')}; {tiempos(t.get('tiempos'))}")
        for nombre in ("buscar", "modo_juego"):
            d = f.get(nombre, {})
            l.append(f"{nombre}: primer resultado bien {d.get('aciertos')}/{d.get('total')}; tecla "
                     f"{tiempos(d.get('tecla'))}; congelada {tiempos(d.get('congelada'))}; resultados "
                     f"{tiempos(d.get('resultados'))}")
        d = f.get("fichas", {})
        l.append(f"fichas: {d.get('abiertas')}/{d.get('total')}; {tiempos(d.get('tiempos'))}")
        d = f.get("secciones", {})
        l.append(f"secciones: primera vez {tiempos(d.get('primera'))}; despues {tiempos(d.get('tiempos'))}")
        for caso in f.get("refrescos", {}).get("casos", []):
            l.append(f"refresco {caso['que']}: {tiempos(caso['tiempos'])}")
        for nombre in ("minimizar", "bienvenida", "guia", "instancia", "actualizar_al_abrir", "precios_reales", "cierre"):
            d = {k: v for k, v in f.get(nombre, {}).items() if k not in ("casos",)}
            l.append(f"{nombre}: {json.dumps(d, ensure_ascii=False, default=str)[:400]}")
        congelaciones = [c for c in self.resultado.get("congelaciones", []) if c["flujo"] != "(autoprueba)"]
        memoria = [(n, d["rss_mb"]) for n, d in f.items() if isinstance(d, dict) and d.get("rss_mb")]
        if memoria:
            l.append("memoria (RSS MB antes -> despues): " + ", ".join(
                f"{n} {a}->{b}" for n, (a, b) in memoria if a is not None and b is not None))
        l.append(f"congelaciones de la ventana (>{self.op.get('vigia_ms') or 120} ms): {len(congelaciones)}")
        for c in sorted(congelaciones, key=lambda c: -c["ms"])[:8]:
            l.append(f"  {c['ms']} ms en {c['flujo']}: {' < '.join(reversed(c['pila'][-4:]))}")
        l.append("")
        l.append("VEREDICTO: " + ("TODO BIEN" if self.resultado.get("ok") else "FALLA"))
        for fallo in self.resultado.get("fallos", []):
            l.append(f"  - {fallo}")
        for e in self.excepciones[:10]:
            l.append("EXCEPCION: " + e[-800:])
        for e in self.resultado.get("errores_registro", [])[:20]:
            l.append("REGISTRO: " + e)
        (self.carpeta / "informe.txt").write_text("\n".join(l) + "\n", encoding="utf-8")


def _cerrar_qt() -> None:
    """Deshace la aplicacion de Qt antes de `os._exit`.

    `os._exit` mata los hilos a medias y luego Windows descarga las DLL: con la
    QApplication aun viva, al descargar Qt se limpiaban datos de hilos ya muertos y
    el proceso reventaba (acceso a memoria no valida, salida 139 en bash) en una de
    cada seis salidas desde el codigo, despues de haber escrito el informe. Cerrada
    aqui, como la cierra Python al acabar por las buenas: 0 de 40 (antes 8 de 50).
    """
    try:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        for ventana in app.topLevelWidgets():
            ventana.close()
            ventana.deleteLater()
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.shutdown()
    except Exception:  # noqa: BLE001 - se sale igual
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if ARGUMENTO_CARGA in argv:
        return bucle_carga()
    opciones = _leer_argumentos(argv)
    preparar_entorno(opciones)
    prueba = Autoprueba(opciones)
    codigo = prueba.ejecutar()
    if not getattr(sys, "frozen", False):
        print((opciones["carpeta"] / "informe.txt").read_text(encoding="utf-8"))
    # Los hilos del programa (mundo, market, captura) no esperan a nadie: se sale ya.
    sys.stdout.flush()
    _cerrar_qt()
    os._exit(codigo)


if __name__ == "__main__":  # pragma: no cover
    main()
