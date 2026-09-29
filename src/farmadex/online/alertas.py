"""Alertas de precio: avisar cuando alguien vende un objeto a tu precio o menos.

El usuario elige un objeto (desde su ficha o desde Mis metas) y un precio. Un
vigilante en segundo plano pregunta a warframe.market, de uno en uno y con
calma, por las ventas de jugadores conectados (`/orders/item/<slug>/top`, que
solo trae gente en el juego u online) y, si alguna esta a ese precio o menos,
avisa con el vendedor y el mensaje "/w" listo para pegar en el chat del juego.

Reglas que importan:

- No machacar la API: una peticion como mucho cada `SEPARACION_S`, cada alerta
  como mucho cada `INTERVALO_ALERTA_S`, y ante un fallo (429, caida) se espera
  cada vez mas (`ESPERA_MIN_S` .. `ESPERA_MAX_S`) antes de volver a probar.
- No repetir: el mismo vendedor al mismo precio para la misma alerta avisa una
  vez; se recuerda (en disco) durante `AVISO_CADUCA_S`.
- Nada viejo como si fuera de ahora: el ultimo dato de cada alerta lleva la hora
  a la que se vio y no se guarda en disco; tras un fallo se ensena el fallo.

Aqui no hay Qt: el hilo y la ventana estan en ui/pestana_alertas.py.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import DIR_BASE
from ..ficheros import escribir_texto
from ..registro_log import obtener

log = obtener("alertas")

FICHERO = "alertas_precio.json"
MAX_ALERTAS = 50
# Cada alerta se mira como mucho cada 3 minutos, y entre dos peticiones del
# vigilante pasan al menos 20 s (el limite publicado de warframe.market son 3 por
# segundo; esto se queda muy por debajo aunque haya muchas alertas).
INTERVALO_ALERTA_S = 180.0
SEPARACION_S = 20.0
ESPERA_MIN_S = 60.0
ESPERA_MAX_S = 30 * 60.0
AVISO_CADUCA_S = 24 * 3600.0
ESTADOS_CONECTADO = ("ingame", "online")


@dataclass
class Alerta:
    slug: str
    nombre: str  # como lo llama la interfaz (idioma del usuario)
    precio: int  # avisar a este precio o menos
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    unique_name: str = ""
    nombre_en: str = ""  # como lo nombra warframe.market (para el /w)
    rango: int | None = None  # None: cualquier rango
    rango_max: int | None = None
    activa: bool = True
    creada: float = field(default_factory=time.time)

    @classmethod
    def desde(cls, datos: dict) -> "Alerta | None":
        try:
            precio = int(datos["precio"])
            slug = str(datos["slug"])
        except (KeyError, TypeError, ValueError):
            return None
        if not slug or precio <= 0:
            return None
        rango = datos.get("rango")
        rango_max = datos.get("rango_max")
        return cls(
            slug=slug,
            nombre=str(datos.get("nombre") or slug),
            precio=precio,
            id=str(datos.get("id") or uuid.uuid4().hex[:12]),
            unique_name=str(datos.get("unique_name") or ""),
            nombre_en=str(datos.get("nombre_en") or ""),
            rango=int(rango) if isinstance(rango, (int, float)) else None,
            rango_max=int(rango_max) if isinstance(rango_max, (int, float)) else None,
            activa=bool(datos.get("activa", True)),
            creada=float(datos.get("creada") or time.time()),
        )


@dataclass
class Coincidencia:
    """Una venta que cumple una alerta."""

    alerta_id: str
    vendedor: str
    platino: int
    estado: str
    mensaje: str  # "/w vendedor Hi! ..." para pegar en el chat del juego


@dataclass
class Estado:
    """Lo ultimo que se sabe de una alerta en esta sesion (no se guarda en disco)."""

    cuando: float | None = None  # time.time() de la ultima consulta que salio bien
    mejor: int | None = None  # venta mas barata de gente conectada, en esa consulta
    vendedor: str = ""
    coincidencias: list[Coincidencia] = field(default_factory=list)
    error: str = ""
    cuando_error: float | None = None
    proxima: float = 0.0  # monotonic a partir del cual toca mirarla otra vez


def mensaje_w(vendedor: str, nombre_en: str, platino: int, rango: int | None = None) -> str:
    """El susurro con el formato que usa warframe.market en su boton de comprar."""
    nombre = nombre_en or "?"
    if rango is not None:
        nombre = f"{nombre} (rank {rango})"
    return f'/w {vendedor} Hi! I want to buy: "{nombre}" for {platino} platinum. (warframe.market)'


def coincidencias(alerta: Alerta, precios) -> list[Coincidencia]:
    """Ventas de jugadores conectados a `alerta.precio` o menos, la mas barata primero."""
    salida = []
    for orden in getattr(precios, "ventas", []) or []:
        if orden.estado not in ESTADOS_CONECTADO or not orden.usuario:
            continue
        if orden.platino <= 0 or orden.platino > alerta.precio:
            continue
        if alerta.rango is not None and orden.rango is not None and orden.rango != alerta.rango:
            continue
        rango = orden.rango if orden.rango is not None else alerta.rango
        salida.append(Coincidencia(
            alerta_id=alerta.id, vendedor=orden.usuario, platino=orden.platino, estado=orden.estado,
            mensaje=mensaje_w(orden.usuario, alerta.nombre_en, orden.platino, rango),
        ))
    # En el juego antes que online (se le puede susurrar ya), y luego por precio.
    salida.sort(key=lambda c: (c.estado != "ingame", c.platino))
    return salida


def clave_aviso(c: Coincidencia) -> str:
    return f"{c.alerta_id}|{c.vendedor.lower()}|{c.platino}"


class Almacen:
    """Las alertas y los avisos ya dados, en un JSON junto a config.json. Seguro entre hilos."""

    def __init__(self, ruta: Path | None = None):
        self.ruta = Path(ruta) if ruta else DIR_BASE / FICHERO
        self._cerrojo = threading.RLock()
        self.alertas: list[Alerta] = []
        self.avisados: dict[str, float] = {}
        self.cargar()

    def cargar(self) -> None:
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            datos = {}
        except (OSError, ValueError) as e:
            log.warning("No se pudo leer %s: %s", self.ruta, e)
            datos = {}
        if not isinstance(datos, dict):
            datos = {}
        alertas = [Alerta.desde(a) for a in datos.get("alertas") or [] if isinstance(a, dict)]
        avisados = datos.get("avisados") if isinstance(datos.get("avisados"), dict) else {}
        with self._cerrojo:
            self.alertas = [a for a in alertas if a is not None][:MAX_ALERTAS]
            self.avisados = {str(k): float(v) for k, v in avisados.items() if isinstance(v, (int, float))}

    def guardar(self) -> None:
        with self._cerrojo:
            datos = {"alertas": [asdict(a) for a in self.alertas], "avisados": dict(self.avisados)}
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            escribir_texto(self.ruta, json.dumps(datos, ensure_ascii=False, indent=1))
        except OSError as e:
            log.warning("No se pudieron guardar las alertas de precio: %s", e)

    # -- cambios hechos desde la ventana --

    def lista(self) -> list[Alerta]:
        with self._cerrojo:
            return list(self.alertas)

    def anadir(self, alerta: Alerta) -> bool:
        with self._cerrojo:
            if len(self.alertas) >= MAX_ALERTAS:
                return False
            # La misma alerta (objeto, rango) no se duplica: se actualiza el precio.
            for existente in self.alertas:
                if existente.slug == alerta.slug and existente.rango == alerta.rango:
                    existente.precio = alerta.precio
                    existente.activa = True
                    existente.nombre = alerta.nombre or existente.nombre
                    existente.nombre_en = alerta.nombre_en or existente.nombre_en
                    break
            else:
                self.alertas.append(alerta)
        self.guardar()
        return True

    def borrar(self, alerta_id: str) -> None:
        with self._cerrojo:
            self.alertas = [a for a in self.alertas if a.id != alerta_id]
            self.avisados = {k: v for k, v in self.avisados.items() if not k.startswith(alerta_id + "|")}
        self.guardar()

    def pausar(self, alerta_id: str, pausada: bool) -> None:
        with self._cerrojo:
            for a in self.alertas:
                if a.id == alerta_id:
                    a.activa = not pausada
        self.guardar()

    def completar_nombre(self, alerta_id: str, nombre_en: str, rango_max: int | None) -> None:
        with self._cerrojo:
            for a in self.alertas:
                if a.id == alerta_id:
                    a.nombre_en = nombre_en or a.nombre_en
                    a.rango_max = rango_max if rango_max is not None else a.rango_max
        self.guardar()

    # -- avisos ya dados --

    def nuevas(self, lista: list[Coincidencia], ahora: float | None = None) -> list[Coincidencia]:
        """Las que aun no se han avisado (y las apunta como avisadas)."""
        ahora = time.time() if ahora is None else ahora
        salida = []
        with self._cerrojo:
            self.avisados = {k: v for k, v in self.avisados.items() if ahora - v < AVISO_CADUCA_S}
            for c in lista:
                clave = clave_aviso(c)
                if clave in self.avisados:
                    continue
                self.avisados[clave] = ahora
                salida.append(c)
        if salida:
            self.guardar()
        return salida


class Vigilante:
    """Decide que alerta toca mirar y la mira. Sin hilos: lo mueve un temporizador.

    `consultar(slug, rango)` devuelve un `market.Precios` (con `error` si fallo) y
    `ficha(slug)` el nombre en ingles y el rango maximo (o None). Se inyectan para
    poder probarlo sin red.
    """

    def __init__(self, almacen: Almacen, consultar, ficha=None, reloj=time.monotonic):
        self.almacen = almacen
        self.consultar = consultar
        self.ficha = ficha
        self.reloj = reloj
        self.estados: dict[str, Estado] = {}
        self._ultima_peticion = -1e18
        self._fallos_seguidos = 0
        self.espera_hasta = 0.0  # monotonic: hasta aqui no se pregunta nada (tras un fallo)
        self.ultimo_error = ""
        self._cerrojo = threading.Lock()

    def estado(self, alerta_id: str) -> Estado:
        with self._cerrojo:
            return self.estados.setdefault(alerta_id, Estado())

    def siguiente(self) -> Alerta | None:
        """La alerta activa que mas tiempo lleva sin mirarse, si ya toca; si no, None."""
        ahora = self.reloj()
        if ahora < self.espera_hasta or ahora - self._ultima_peticion < SEPARACION_S:
            return None
        candidatas = [a for a in self.almacen.lista() if a.activa]
        candidatas = [a for a in candidatas if self.estado(a.id).proxima <= ahora]
        if not candidatas:
            return None
        return min(candidatas, key=lambda a: self.estado(a.id).proxima)

    def comprobar(self, alerta: Alerta) -> list[Coincidencia]:
        """Mira una alerta. Devuelve las coincidencias NUEVAS (las que hay que avisar)."""
        ahora = self.reloj()
        self._ultima_peticion = ahora
        estado = self.estado(alerta.id)
        if not alerta.nombre_en and self.ficha is not None:
            ficha = self.ficha(alerta.slug)
            if ficha:
                self.almacen.completar_nombre(alerta.id, ficha.get("nombre_en", ""), ficha.get("rango_max"))
                alerta.nombre_en = ficha.get("nombre_en", "") or alerta.nombre_en
        precios = self.consultar(alerta.slug, alerta.rango)
        if getattr(precios, "error", ""):
            self._fallos_seguidos += 1
            espera = min(ESPERA_MAX_S, ESPERA_MIN_S * 2 ** (self._fallos_seguidos - 1))
            self.espera_hasta = ahora + espera
            self.ultimo_error = precios.error
            estado.error = precios.error
            estado.cuando_error = time.time()
            estado.coincidencias = []
            estado.proxima = ahora + espera
            log.info("Alertas de precio: warframe.market falla (%s); se espera %.0f s", precios.error, espera)
            return []
        self._fallos_seguidos = 0
        self.ultimo_error = ""
        todas = coincidencias(alerta, precios)
        conectadas = [o for o in precios.ventas if o.estado in ESTADOS_CONECTADO and o.platino > 0
                      and (alerta.rango is None or o.rango in (None, alerta.rango))]
        mas_barata = min(conectadas, key=lambda o: o.platino) if conectadas else None
        estado.cuando = time.time()
        estado.error = ""
        estado.mejor = mas_barata.platino if mas_barata else None
        estado.vendedor = mas_barata.usuario if mas_barata else ""
        estado.coincidencias = todas
        estado.proxima = ahora + INTERVALO_ALERTA_S
        return self.almacen.nuevas(todas)

    def olvidar(self, alerta_id: str) -> None:
        with self._cerrojo:
            self.estados.pop(alerta_id, None)

    def mirar_pronto(self, alerta_id: str) -> None:
        """Una alerta recien creada o reanudada se mira en la siguiente vuelta."""
        self.estado(alerta_id).proxima = 0.0


def texto_aviso(alerta: Alerta, c: Coincidencia, t) -> str:
    """El globo de la bandeja: que, por cuanto, quien y el mensaje para copiar."""
    return t(
        "{nombre}: {vendedor} lo vende por {precio} platino (tu alerta: {tope} o menos). "
        "Pulsa aquí para copiar el mensaje: {mensaje}",
        nombre=alerta.nombre, vendedor=c.vendedor, precio=c.platino, tope=alerta.precio, mensaje=c.mensaje,
    )
