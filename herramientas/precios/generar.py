"""Genera la foto diaria de precios de warframe.market (precios.json.gz).

Lo ejecuta cada dia a las 00:00 UTC el workflow .github/workflows/precios.yml y
publica el resultado como adjunto de la release fija "precios". Farmadex baja ese
fichero una vez al dia y contesta cualquier consulta de precio al instante, sin
pedir nada a warframe.market mientras el jugador mira la pantalla.

Solo usa la biblioteca estandar de Python (3.10+): en GitHub Actions no hay que
instalar nada.

De donde sale cada dato (API publica de warframe.market, comprobado 2026-09-30):

- Catalogo: GET https://api.warframe.market/v2/items  -> slug, maxRank, subtypes,
  tags, ducats, vaulted, nombre en ingles.
- Ordenes en vivo: GET https://api.warframe.market/v2/orders/item/{slug}  -> todas
  las ordenes visibles con 'rank'/'subtype' y el estado del usuario. Solo cuentan
  las de jugadores "ingame" u "online" en el momento de la foto (lo mismo que
  ensena /top). Una sola peticion trae todos los rangos a la vez.
- Estadisticas de operaciones cerradas: GET
  https://api.warframe.market/v1/items/{slug}/statistics  -> 'statistics_closed'
  ['90days'] (una fila por dia y por rango/subtipo) y ['48hours'] (por horas).
  La v2 aun no tiene estadisticas (404); la v1 esta "deprecated" pero contesta.
  De las filas diarias de los ultimos 30 dias salen min, max, media ponderada
  por volumen, mediana y volumen.

Reglas de la API (docs.warframe.market/docs/rules/overview): como mucho 3
peticiones por segundo, User-Agent propio que identifique el proyecto y nada de
disfrazarse de navegador. Aqui se va a 2.5 por segundo con un limitador comun a
todos los hilos, y un 429 o un 5xx frena a todos con espera exponencial.

Uso:
    python generar.py --salida precios.json.gz          # pasada completa (~50 min)
    python generar.py --salida p.json.gz --limite 50     # prueba corta
    python generar.py --validar precios.json.gz          # comprobar antes de publicar
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import json
import os
import random
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

FORMATO = 1
HOST = "api.warframe.market"
USER_AGENT = "Farmadex-precios/1 (+https://github.com/angelsanchez97/farmadex)"
POR_SEGUNDO = 2.5
HILOS = 3
INTENTOS = 6
DIAS = 30
# Orden de los valores de cada entrada de "p". El cliente lee este mismo campo
# del fichero, asi que anadir campos al final no rompe versiones viejas.
CAMPOS = [
    "venta_min",        # orden de venta mas barata de un jugador conectado
    "venta_mediana",    # mediana de las 5 ventas mas baratas de conectados
    "compra_max",       # orden de compra mas alta de un jugador conectado
    "vendedores",       # ordenes de venta de conectados
    "compradores",      # ordenes de compra de conectados
    "cantidad_venta",   # unidades en venta entre conectados
    "min_30d",          # precio minimo de operaciones cerradas, ultimos 30 dias
    "max_30d",          # precio maximo, ultimos 30 dias
    "media_30d",        # media ponderada por volumen, ultimos 30 dias
    "volumen_30d",      # unidades vendidas en 30 dias
    "mediana_30d",      # mediana (ponderada por volumen) de las medianas diarias
    "dias_30d",         # dias de los ultimos 30 con alguna venta (rapidez de venta)
    "volumen_48h",      # unidades vendidas en las ultimas 48 h
]
# Minimos para dar por bueno un fichero (se comprueban antes de publicar).
MIN_OBJETOS = 3000
MIN_FRACCION_CATALOGO = 0.95
MIN_FRACCION_ESTADISTICAS = 0.5
TESTIGOS = {"arcane_energize": 5}  # objeto -> rango que siempre tiene ventas


# -- red -----------------------------------------------------------------------


class Limitador:
    """Reparte las peticiones de todos los hilos a un ritmo fijo; un 429 frena a todos."""

    def __init__(self, por_segundo: float):
        self.intervalo = 1.0 / por_segundo
        self._siguiente = 0.0
        self._cerrojo = threading.Lock()

    def esperar(self) -> None:
        with self._cerrojo:
            ahora = time.monotonic()
            turno = max(ahora, self._siguiente)
            self._siguiente = turno + self.intervalo
        if turno > ahora:
            time.sleep(turno - ahora)

    def frenar(self, segundos: float) -> None:
        with self._cerrojo:
            self._siguiente = max(self._siguiente, time.monotonic() + segundos)


class Red:
    """GET JSON con conexion persistente por hilo, gzip, limitador y reintentos."""

    def __init__(self, por_segundo: float = POR_SEGUNDO, plataforma: str = "pc"):
        self.limitador = Limitador(por_segundo)
        self.plataforma = plataforma
        self._local = threading.local()
        self.peticiones = 0
        self.reintentos = 0
        self.bytes = 0
        self._cuenta = threading.Lock()

    def _conexion(self, nueva: bool = False) -> http.client.HTTPSConnection:
        con = getattr(self._local, "con", None)
        if con is None or nueva:
            if con is not None:
                con.close()
            con = http.client.HTTPSConnection(HOST, timeout=30)
            self._local.con = con
        return con

    def json(self, ruta: str):
        """El JSON de `ruta`, o None si el objeto no existe (404). Lanza si no hay forma."""
        ultimo = ""
        for intento in range(INTENTOS):
            self.limitador.esperar()
            try:
                con = self._conexion(nueva=intento > 0)
                con.request("GET", ruta, headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "Platform": self.plataforma,
                    "Language": "en",
                })
                r = con.getresponse()
                cuerpo = r.read()
                with self._cuenta:
                    self.peticiones += 1
                    self.bytes += len(cuerpo)
                if r.status == 200:
                    if r.getheader("Content-Encoding", "") == "gzip":
                        cuerpo = gzip.decompress(cuerpo)
                    return json.loads(cuerpo)
                if r.status == 404:
                    return None
                ultimo = f"HTTP {r.status}"
                if r.status == 429 or r.status >= 500:
                    espera = min(60.0, 2.0 * 2**intento) + random.uniform(0, 1)
                    self.limitador.frenar(espera)
                else:
                    break  # 400, 403...: insistir no lo arregla
            except (OSError, http.client.HTTPException, ValueError) as e:
                ultimo = f"{type(e).__name__}: {e}"
                time.sleep(min(30.0, 1.0 * 2**intento) + random.uniform(0, 0.5))
            with self._cuenta:
                self.reintentos += 1
        raise RuntimeError(f"{ruta}: {ultimo}")


# -- calculo -------------------------------------------------------------------


def _clave(rango, subtipo) -> str:
    """"5", "" (sin rango), "|intact" o "3|radiant": la clave de cada mercado del objeto."""
    r = "" if rango is None else str(int(rango))
    return f"{r}|{subtipo}" if subtipo else r


def _num(valor):
    if valor is None:
        return None
    valor = float(valor)
    return int(valor) if valor.is_integer() else round(valor, 1)


def resumir_ordenes(ordenes: list) -> dict[str, dict]:
    """Por mercado (rango/subtipo): lo que ofrecen ahora los jugadores conectados."""
    grupos: dict[str, dict] = {}
    for o in ordenes or []:
        if not isinstance(o, dict) or o.get("visible") is False:
            continue
        usuario = o.get("user") if isinstance(o.get("user"), dict) else {}
        if usuario.get("status") not in ("ingame", "online"):
            continue
        try:
            platino = float(o.get("platinum"))
            cantidad = int(o.get("quantity") or 1)
        except (TypeError, ValueError):
            continue
        g = grupos.setdefault(_clave(o.get("rank"), o.get("subtype")), {"sell": [], "buy": [], "cant": 0})
        if o.get("type") == "sell":
            g["sell"].append(platino)
            g["cant"] += cantidad
        elif o.get("type") == "buy":
            g["buy"].append(platino)
    salida = {}
    for clave, g in grupos.items():
        ventas = sorted(g["sell"])
        salida[clave] = {
            "venta_min": _num(ventas[0]) if ventas else None,
            "venta_mediana": _num(statistics.median(ventas[:5])) if ventas else None,
            "compra_max": _num(max(g["buy"])) if g["buy"] else None,
            "vendedores": len(ventas),
            "compradores": len(g["buy"]),
            "cantidad_venta": g["cant"],
        }
    return salida


def _mediana_ponderada(pares: list[tuple[float, float]]):
    pares = sorted((v, p) for v, p in pares if v is not None and p > 0)
    total = sum(p for _, p in pares)
    if not total:
        return None
    acumulado = 0.0
    for valor, peso in pares:
        acumulado += peso
        if acumulado >= total / 2:
            return valor
    return pares[-1][0]


def _fecha(texto: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None


def resumir_estadisticas(datos: dict, hoy: datetime) -> dict[str, dict]:
    """Por mercado: operaciones cerradas de los ultimos 30 dias y de las ultimas 48 h."""
    cerradas = ((datos or {}).get("payload") or {}).get("statistics_closed") or {}
    desde = hoy - timedelta(days=DIAS)
    grupos: dict[str, list[dict]] = {}
    for fila in cerradas.get("90days") or []:
        if not isinstance(fila, dict):
            continue
        cuando = _fecha(fila.get("datetime"))
        if cuando is None or cuando < desde or cuando >= hoy:
            continue
        grupos.setdefault(_clave(fila.get("mod_rank"), fila.get("subtype")), []).append(fila)
    horas: dict[str, int] = {}
    for fila in cerradas.get("48hours") or []:
        if isinstance(fila, dict):
            clave = _clave(fila.get("mod_rank"), fila.get("subtype"))
            horas[clave] = horas.get(clave, 0) + int(fila.get("volume") or 0)
    salida = {}
    for clave in set(grupos) | set(horas):
        filas = [f for f in grupos.get(clave, []) if int(f.get("volume") or 0) > 0]
        volumen = sum(int(f["volume"]) for f in filas)
        entrada = {"volumen_48h": horas.get(clave, 0), "volumen_30d": volumen, "dias_30d": len(filas)}
        if filas:
            entrada.update(
                min_30d=_num(min(float(f["min_price"]) for f in filas)),
                max_30d=_num(max(float(f["max_price"]) for f in filas)),
                media_30d=_num(sum(float(f["avg_price"]) * int(f["volume"]) for f in filas) / volumen),
                mediana_30d=_num(_mediana_ponderada([(f.get("median"), int(f["volume"])) for f in filas])),
            )
        salida[clave] = entrada
    return salida


def combinar(ordenes: dict[str, dict], estadisticas: dict[str, dict]) -> dict[str, list]:
    salida = {}
    for clave in sorted(set(ordenes) | set(estadisticas)):
        junto = {**estadisticas.get(clave, {}), **ordenes.get(clave, {})}
        salida[clave] = [junto.get(c) for c in CAMPOS]
    return salida


# -- pasada completa -------------------------------------------------------------


def _objeto_base(entrada: dict) -> dict:
    nombre = ((entrada.get("i18n") or {}).get("en") or {}).get("name") or ""
    base = {"n": nombre, "r": entrada.get("maxRank"), "t": entrada.get("tags") or []}
    if entrada.get("subtypes"):
        base["s"] = entrada["subtypes"]
    if entrada.get("ducats"):
        base["d"] = entrada["ducats"]
    if entrada.get("vaulted") is not None:
        base["v"] = bool(entrada["vaulted"])
    return base


def generar(salida: Path, limite: int | None = None, por_segundo: float = POR_SEGUNDO,
            hilos: int = HILOS, plataforma: str = "pc") -> dict:
    inicio = time.monotonic()
    ahora = datetime.now(timezone.utc).replace(microsecond=0)
    hoy = ahora.replace(hour=0, minute=0, second=0)
    red = Red(por_segundo, plataforma)
    catalogo = (red.json("/v2/items") or {}).get("data")
    if not isinstance(catalogo, list) or not catalogo:
        raise RuntimeError("catalogo de warframe.market vacio o con otra forma")
    catalogo = [e for e in catalogo if isinstance(e, dict) and e.get("slug")]
    if limite:
        # Muestra repartida por todo el catalogo (mods, arcanos, reliquias, primes...).
        paso = max(1, len(catalogo) // limite)
        catalogo = catalogo[::paso][:limite]
        if not any(e["slug"] in TESTIGOS for e in catalogo):
            catalogo += [e for e in (red.json("/v2/items") or {}).get("data", []) if e.get("slug") in TESTIGOS]

    objetos: dict[str, dict] = {}
    fallos: list[str] = []
    con_ordenes = con_estadisticas = 0

    def uno(entrada: dict):
        slug = entrada["slug"]
        ordenes = red.json(f"/v2/orders/item/{slug}")
        est = red.json(f"/v1/items/{slug}/statistics")
        return slug, entrada, (ordenes or {}).get("data") or [], est

    total = len(catalogo)
    hechos = 0
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        futuros = [pool.submit(uno, e) for e in catalogo]
        for futuro in as_completed(futuros):
            hechos += 1
            try:
                slug, entrada, ordenes, est = futuro.result()
            except Exception as e:  # noqa: BLE001 - un objeto roto no para la pasada
                fallos.append(str(e))
                continue
            o = resumir_ordenes(ordenes)
            s = resumir_estadisticas(est, hoy) if est else {}
            con_ordenes += bool(o)
            con_estadisticas += any(v.get("volumen_30d") for v in s.values())
            objeto = _objeto_base(entrada)
            objeto["p"] = combinar(o, s)
            objetos[slug] = objeto
            if hechos % 100 == 0 or hechos == total:
                pasado = time.monotonic() - inicio
                falta = pasado / hechos * (total - hechos)
                barra = "#" * int(30 * hechos / total)
                print(f"[{barra:<30}] {hechos}/{total} ({100 * hechos / total:.0f}%)"
                      f"  {pasado / 60:.1f} min, faltan ~{falta / 60:.1f} min, fallos {len(fallos)}",
                      flush=True)

    doc = {
        "formato": FORMATO,
        "fecha": ahora.isoformat().replace("+00:00", "Z"),
        "plataforma": plataforma,
        "fuente": "warframe.market",
        "dias": DIAS,
        "campos": CAMPOS,
        "resumen": {
            "catalogo": total,
            "objetos": len(objetos),
            "con_ordenes": con_ordenes,
            "con_estadisticas": con_estadisticas,
            "fallos": len(fallos),
            "peticiones": red.peticiones,
            "reintentos": red.reintentos,
            "segundos": round(time.monotonic() - inicio),
        },
        "objetos": dict(sorted(objetos.items())),
    }
    crudo = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    comprimido = gzip.compress(crudo, compresslevel=9, mtime=0)
    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    tmp = salida.with_name(salida.name + ".tmp")
    tmp.write_bytes(comprimido)
    os.replace(tmp, salida)
    version = {
        "formato": FORMATO,
        "fecha": doc["fecha"],
        "plataforma": plataforma,
        "objetos": len(objetos),
        "bytes": len(comprimido),
        "sha256": hashlib.sha256(comprimido).hexdigest(),
    }
    ruta_version = salida.with_name("precios_version.json")
    ruta_version.write_text(json.dumps(version, indent=1), encoding="utf-8")
    for f in fallos[:20]:
        print("FALLO", f, file=sys.stderr)
    print(json.dumps({**doc["resumen"], "bytes_gz": len(comprimido), "bytes_json": len(crudo),
                      "descargado_mb": round(red.bytes / 1e6, 1)}), flush=True)
    return doc


# -- validacion ------------------------------------------------------------------


def validar(ruta: Path, completo: bool = True) -> list[str]:
    """Lista de problemas del fichero; vacia si se puede publicar."""
    problemas: list[str] = []
    ruta = Path(ruta)
    try:
        doc = json.loads(gzip.decompress(ruta.read_bytes()))
    except Exception as e:  # noqa: BLE001
        return [f"no se puede leer: {e}"]
    if doc.get("formato") != FORMATO:
        problemas.append(f"formato {doc.get('formato')!r} en vez de {FORMATO}")
    fecha = _fecha(doc.get("fecha") or "")
    if fecha is None or fecha.tzinfo is None:
        problemas.append("fecha ausente o sin zona")
    elif abs((datetime.now(timezone.utc) - fecha).total_seconds()) > 36 * 3600:
        problemas.append(f"fecha {doc.get('fecha')} demasiado lejos de hoy")
    campos = doc.get("campos")
    if not isinstance(campos, list) or campos[: len(CAMPOS)] != CAMPOS:
        problemas.append("campos distintos de los esperados")
    objetos = doc.get("objetos")
    if not isinstance(objetos, dict):
        return problemas + ["falta 'objetos'"]
    for slug, o in list(objetos.items())[:50]:
        p = o.get("p") if isinstance(o, dict) else None
        if not isinstance(p, dict) or any(not isinstance(v, list) or len(v) != len(campos or []) for v in p.values()):
            problemas.append(f"entrada mal formada: {slug}")
            break
    resumen = doc.get("resumen") or {}
    if completo:
        n = len(objetos)
        if n < MIN_OBJETOS:
            problemas.append(f"solo {n} objetos (minimo {MIN_OBJETOS})")
        if n < MIN_FRACCION_CATALOGO * (resumen.get("catalogo") or 0):
            problemas.append(f"{n} objetos de {resumen.get('catalogo')} del catalogo")
        if (resumen.get("con_estadisticas") or 0) < MIN_FRACCION_ESTADISTICAS * n:
            problemas.append(f"pocos objetos con ventas en 30 dias: {resumen.get('con_estadisticas')}")
    for slug, rango in TESTIGOS.items():
        valores = ((objetos.get(slug) or {}).get("p") or {}).get(str(rango))
        if not valores or not valores[CAMPOS.index("volumen_30d")]:
            problemas.append(f"el testigo {slug} rango {rango} no tiene ventas en 30 dias")
    return problemas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", type=Path, default=Path("precios.json.gz"))
    ap.add_argument("--limite", type=int, default=None, help="solo N objetos (pruebas)")
    ap.add_argument("--por-segundo", type=float, default=POR_SEGUNDO)
    ap.add_argument("--hilos", type=int, default=HILOS)
    ap.add_argument("--validar", type=Path, default=None, help="solo comprobar este fichero")
    args = ap.parse_args(argv)
    if args.validar:
        problemas = validar(args.validar)
        for p in problemas:
            print("NO VALIDO:", p)
        print("OK" if not problemas else f"{len(problemas)} problemas")
        return 1 if problemas else 0
    generar(args.salida, args.limite, min(args.por_segundo, 3.0), args.hilos)
    problemas = validar(args.salida, completo=not args.limite)
    for p in problemas:
        print("NO VALIDO:", p)
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
