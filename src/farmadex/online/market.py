"""Precios de warframe.market (API v2).

La API esta por debajo de la version 1.0, asi que el parseo vive aqui aislado y
cubierto por pruebas con capturas: si cambian el contrato, falla un test, no la
aplicacion entera. warframe.market exige un User-Agent que identifique a la
aplicacion; si no hay contacto configurado el modulo se niega a pedir nada.
"""

from __future__ import annotations

import sqlite3
import statistics
import threading
from dataclasses import dataclass, field

from .. import NOMBRE_APP, URL_CONTACTO, VERSION
from ..config import PLATAFORMA
from ..datos.items import normalizar
from ..registro_log import obtener
from .http import Cliente

log = obtener("market")

BASE = "https://api.warframe.market/v2"
# Dos peticiones por segundo: el limite publicado son tres.
POR_SEGUNDO = 2.0
CACHE_SEGUNDOS = 600


@dataclass
class Orden:
    platino: int
    cantidad: int
    usuario: str
    estado: str
    # Rango del mod o arcano; None en lo que no se sube de rango (piezas prime).
    rango: int | None = None


@dataclass
class Precios:
    """Ordenes de un objeto, ya filtradas al rango que se ensena.

    Un mod a rango 0 y el mismo mod a rango maximo son dos mercados distintos
    (Energizar Arcano: 8p contra 150p). `ventas` y `compras` son solo las del
    `rango` elegido; el resto de rangos vistos queda en `por_rango`, para que
    la interfaz pueda ensenar "rango 0 desde 8p" al lado.
    """

    slug: str
    ventas: list[Orden] = field(default_factory=list)
    compras: list[Orden] = field(default_factory=list)
    error: str = ""
    rango: int | None = None
    rango_max: int | None = None
    por_rango: dict[int, "Precios"] = field(default_factory=dict)

    @property
    def con_rango(self) -> bool:
        return self.rango is not None

    def en_rango(self, rango: int) -> "Precios | None":
        if rango == self.rango:
            return self
        return self.por_rango.get(rango)

    @property
    def mejor_venta(self) -> int | None:
        return self.ventas[0].platino if self.ventas else None

    @property
    def mediana_venta(self) -> float | None:
        if not self.ventas:
            return None
        return statistics.median(o.platino for o in self.ventas[:5])

    @property
    def mejor_compra(self) -> int | None:
        return self.compras[0].platino if self.compras else None


class Market:
    def __init__(self, idioma: str = "es"):
        self.disponible = True
        contacto = URL_CONTACTO or "herramienta personal, aun sin publicar"
        if not URL_CONTACTO:
            log.info(
                "warframe.market: falta URL_CONTACTO. Funciona igual, pero antes de "
                "publicar hay que poner una URL o un correo en farmadex/__init__.py."
            )
        self.cliente = Cliente(
            por_segundo=POR_SEGUNDO,
            cabeceras={
                "User-Agent": f"{NOMBRE_APP}/{VERSION} (+{contacto})",
                "Language": idioma,
                "Platform": PLATAFORMA,
                "Accept": "application/json",
            },
        )

    # -- catalogo ----------------------------------------------------------

    def items(self) -> list[dict]:
        datos = self.cliente.json(f"{BASE}/items", segundos_cache=86400)
        return datos.get("data") or []

    def emparejar(self, con: sqlite3.Connection) -> int:
        """Guarda el slug de warframe.market en cada objeto del indice.

        Se casa por `gameRef`, que es el mismo uniqueName del catalogo; lo que no
        casa asi se intenta por nombre en ingles, probando tambien el nombre
        completo de las piezas ("Ash Prime Systems") y sus planos, que es como
        el mercado nombra lo que en el catalogo son solo componentes ("Systems").
        Un nombre que case con mas de un objeto se deja sin emparejar: mejor no
        casar que casar mal.
        """
        if not self.disponible:
            return 0
        try:
            lista = self.items()
        except RuntimeError as e:
            log.warning("No se pudo leer el catalogo de warframe.market: %s", e)
            return 0

        candidatos = _candidatos_por_nombre(con)
        casados = 0
        ambiguos = 0
        for entrada in lista:
            slug = entrada.get("slug")
            if not slug:
                continue
            referencia = entrada.get("gameRef")
            fila = None
            if referencia:
                fila = con.execute(
                    "SELECT id FROM items WHERE unique_name = ?", (referencia,)
                ).fetchone()
            item_id = fila[0] if fila else None
            if item_id is None:
                nombre_en = ((entrada.get("i18n") or {}).get("en") or {}).get("name") or ""
                ids = candidatos.get(normalizar(nombre_en), ())
                if len(ids) == 1:
                    item_id = next(iter(ids))
                elif len(ids) > 1:
                    ambiguos += 1
                    log.warning(
                        "Nombre de warframe.market ambiguo, no se empareja: %r casa con %d objetos del indice",
                        nombre_en, len(ids),
                    )
            if not item_id:
                continue
            con.execute(
                "UPDATE items SET market_slug = ?, market_id = ? WHERE id = ?",
                (slug, entrada.get("id"), item_id),
            )
            casados += 1
        log.info(
            "Objetos emparejados con warframe.market: %d (%d nombres ambiguos descartados)",
            casados, ambiguos,
        )
        return casados

    # -- precios -------------------------------------------------------------

    def precios(self, slug: str, rango: int | None = None) -> Precios:
        """Precios del objeto; en mods y arcanos, los del rango maximo (o del pedido).

        `/top` sin filtro mezcla rangos: devuelve las ventas mas baratas (rango 0)
        y las compras mas altas (rango maximo). Si la respuesta trae rangos, se
        pide el rango maximo del objeto (segun su ficha) con `?rank=` y se guarda
        ademas lo visto a rango 0, que es lo que se acaba de farmear.
        """
        if not self.disponible:
            return Precios(slug=slug, error="Falta configurar el contacto del User-Agent")
        try:
            datos = self.cliente.json(
                f"{BASE}/orders/item/{slug}/top", segundos_cache=CACHE_SEGUNDOS
            )
        except RuntimeError as e:
            return Precios(slug=slug, error=str(e))
        try:
            mezclado = analizar_ordenes(slug, datos)
        except Exception as e:  # noqa: BLE001 - un cambio de contrato de la API no tumba el hilo
            log.warning("Respuesta de warframe.market con un formato inesperado para %s: %s", slug, e)
            return Precios(slug=slug, error="respuesta con formato inesperado")
        if not mezclado.con_rango:
            return mezclado
        objetivo = rango if rango is not None else self.rango_maximo(slug)
        if objetivo is None:
            objetivo = mezclado.rango
        if objetivo == mezclado.rango and _completo(mezclado):
            return mezclado
        try:
            datos_rango = self.cliente.json(
                f"{BASE}/orders/item/{slug}/top?rank={objetivo}", segundos_cache=CACHE_SEGUNDOS
            )
            precios = analizar_ordenes(slug, datos_rango, rango=objetivo)
        except Exception as e:  # noqa: BLE001
            log.warning("Sin ordenes de %s a rango %s: %s", slug, objetivo, e)
            return mezclado
        if rango is None:
            precios.rango_max = max(objetivo, mezclado.rango_max or 0)
        # Lo visto sin filtro (rango 0 sobre todo) se conserva como referencia.
        for r, otro in list(mezclado.por_rango.items()) + [(mezclado.rango, mezclado)]:
            if r is not None and r != objetivo and r not in precios.por_rango:
                otro.por_rango = {}
                precios.por_rango[r] = otro
        return precios

    def rango_maximo(self, slug: str) -> int | None:
        """maxRank de la ficha del objeto (cacheado un dia); None si no se sabe."""
        try:
            datos = self.cliente.json(f"{BASE}/items/{slug}", segundos_cache=86400)
        except RuntimeError as e:
            log.info("Sin ficha de warframe.market para %s: %s", slug, e)
            return None
        return rango_maximo_de(datos)

    def cerrar(self) -> None:
        if self is _instancia:
            # La comparte el buscador y el comparador: que uno se cierre no puede
            # dejar al otro sin mercado. Se cierra con `cerrar_compartido()`.
            return
        self.cliente.cerrar()


# -- instancia compartida ------------------------------------------------------
#
# El buscador y el comparador consultan warframe.market cada uno desde su hilo.
# Con un Market por cabeza tenian dos limitadores (hasta 4 peticiones/s entre
# los dos, por encima del limite publicado) y dos caches (la misma pieza se
# pedia dos veces). httpx.Client, el limitador y la cache ya son seguros entre
# hilos, asi que basta con que todos usen el mismo objeto.
_instancia: Market | None = None
_cerrojo = threading.Lock()


def compartido(idioma: str = "es") -> Market:
    """El Market comun a toda la aplicacion; se crea la primera vez que se pide."""
    global _instancia
    with _cerrojo:
        if _instancia is None:
            _instancia = Market(idioma)
        return _instancia


def cerrar_compartido() -> None:
    """Cierra de verdad la instancia comun (al salir del programa o en las pruebas)."""
    global _instancia
    with _cerrojo:
        instancia, _instancia = _instancia, None
    if instancia is not None:
        instancia.cliente.cerrar()


def _completo(precios: Precios) -> bool:
    return bool(precios.ventas) and bool(precios.compras)


def _candidatos_por_nombre(con: sqlite3.Connection) -> dict[str, set[int]]:
    """Nombre normalizado -> ids de items que warframe.market podria llamar asi.

    Cada objeto aporta su nombre a secas. Los componentes (piezas y planos)
    aportan ademas "<padre> <pieza>" y, si la pieza no es ya un plano, la misma
    variante con "Blueprint" al final, que es como el mercado nombra los planos
    ("Ash Prime Systems" y "Ash Prime Chassis Blueprint"). Es la misma idea que
    el alias de datos/items.py, no una nueva.
    """
    candidatos: dict[str, set[int]] = {}

    def _anadir(clave: str, item_id: int) -> None:
        if clave:
            candidatos.setdefault(clave, set()).add(item_id)

    filas = con.execute(
        "SELECT i.id, i.nombre_en, p.nombre_en FROM items i"
        " LEFT JOIN items p ON p.id = i.padre_id"
    )
    for item_id, nombre_en, padre_en in filas:
        nombre_en = nombre_en or ""
        _anadir(normalizar(nombre_en), item_id)
        if padre_en:
            _anadir(normalizar(f"{padre_en} {nombre_en}"), item_id)
            if not nombre_en.lower().endswith("blueprint"):
                _anadir(normalizar(f"{padre_en} {nombre_en} Blueprint"), item_id)
    return candidatos


def rango_maximo_de(datos: dict) -> int | None:
    """Lee maxRank de la respuesta de /items/<slug>."""
    cuerpo = datos.get("data") if isinstance(datos, dict) else None
    if not isinstance(cuerpo, dict):
        return None
    valor = cuerpo.get("maxRank")
    if valor is None:
        valor = cuerpo.get("mod_max_rank")
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _rango(orden: dict) -> int | None:
    # v2 manda 'rank'; la v1 lo llamaba 'mod_rank'. Se aceptan los dos.
    valor = orden.get("rank", orden.get("mod_rank"))
    if valor is None:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def analizar_ordenes(slug: str, datos: dict, rango: int | None = None) -> Precios:
    """Convierte la respuesta de /orders/item/<slug>/top en algo util.

    Las ordenes se separan por rango. Se devuelve el rango pedido o, si no se
    pide, el mas alto que aparezca (el que se comercia); los demas rangos
    quedan colgados en `por_rango`. Sin rangos, todo va junto.
    """
    cuerpo = datos.get("data") if isinstance(datos, dict) else None
    if not isinstance(cuerpo, dict):
        raise ValueError("falta 'data' o no es un objeto")
    ventas: list[Orden] = []
    compras: list[Orden] = []
    for clave, destino in (("sell", ventas), ("buy", compras)):
        ordenes = cuerpo.get(clave) or []
        if not isinstance(ordenes, list):
            raise ValueError(f"'{clave}' no es una lista")
        for orden in ordenes:
            if not isinstance(orden, dict):
                continue
            usuario = orden.get("user")
            usuario = usuario if isinstance(usuario, dict) else {}
            estado = str(usuario.get("status") or "offline")
            destino.append(
                Orden(
                    platino=int(float(orden.get("platinum") or 0)),
                    cantidad=int(float(orden.get("quantity") or 1)),
                    usuario=str(usuario.get("ingameName") or ""),
                    estado=estado,
                    rango=_rango(orden),
                )
            )
    rangos = sorted({o.rango for o in ventas + compras if o.rango is not None})
    if not rangos:
        return _ordenar(Precios(slug=slug, ventas=ventas, compras=compras))
    elegido = rango if rango is not None else rangos[-1]
    por_rango = {
        r: _ordenar(
            Precios(
                slug=slug,
                ventas=[o for o in ventas if o.rango == r],
                compras=[o for o in compras if o.rango == r],
                rango=r,
                rango_max=rangos[-1],
            )
        )
        for r in rangos
    }
    precios = por_rango.pop(elegido, None) or Precios(slug=slug, rango=elegido, rango_max=rangos[-1])
    precios.por_rango = por_rango
    return precios


def _ordenar(precios: Precios) -> Precios:
    # Vender: lo mas barato primero. Comprar: lo que mas pagan primero.
    # Los que estan en el juego valen mas que los que estan desconectados.
    prioridad = {"ingame": 0, "online": 1, "offline": 2}
    precios.ventas.sort(key=lambda o: (prioridad.get(o.estado, 3), o.platino))
    precios.compras.sort(key=lambda o: (prioridad.get(o.estado, 3), -o.platino))
    return precios
