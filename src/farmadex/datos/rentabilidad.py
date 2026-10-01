"""Lista de rentabilidad ("que merece la pena vender"), calculada con la foto diaria de precios.

Todo sale de `online/precios_diarios.py` (fichero local, sin red): para cada objeto se
mira cuanto se vende de verdad (operaciones cerradas de los ultimos 30 dias segun
warframe.market), a que precio y, en mods y arcanos, a que rango conviene venderlo.

La formula (la misma que se explica en la pantalla):

    rapidez = ventas al dia (30 dias) / VENTAS_DIA_TOPE, con tope en 1
    puntos  = precio habitual (mediana de las ventas cerradas de 30 dias) x rapidez

"Puntos" es, mas o menos, el platino que se saca al dia por tener uno a la venta: algo
caro que casi nadie compra puntua poco, y algo que vuela pero vale 1 de platino tambien.
El nivel (S, A, B, C, D) sale de `UMBRALES` sobre esos puntos. Los dos niveles altos piden
ademas que se venda rapido de verdad (`VENTAS_DIA_MIN`: 5 ventas al dia para S, 2 para A):
lo que da los puntos pero no llega a ese ritmo se queda en el primer nivel que si cumpla.

Nunca se inventa nada:
- sin ventas cerradas o sin precio habitual, el objeto no entra en la lista;
- con menos de `MIN_VENTAS` ventas o de `MIN_DIAS` dias con venta en el mes, entra SIN
  nivel y marcado como "pocos datos" (dos ventas a 5.000 no hacen un nivel S);
- el margen solo aparece si en la foto habia a la vez vendedores y compradores conectados.

Rango al que conviene vender:
- arcanos: subir uno al maximo gasta (r+1)(r+2)/2 copias (21 para rango 5, 10 para
  rango 3). Se compara el precio al maximo con lo que dan esas copias sueltas.
- mods: subirlos cuesta endo (10 x rareza x (2^rango - 1)), que no tiene precio en
  platino. Solo se comparan precios (gana el rango con mas puntos) y se dice el endo.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

DIAS = 30
# A partir de tantas ventas al dia, lo que pongas a la venta sale el mismo dia.
VENTAS_DIA_TOPE = 10.0
# Menos que esto en 30 dias = "pocos datos": se ensena, pero sin nivel.
MIN_VENTAS = 15
MIN_DIAS = 7
# Puntos minimos de cada nivel (de mejor a peor); por debajo del ultimo, D.
UMBRALES = (("S", 60.0), ("A", 25.0), ("B", 10.0), ("C", 4.0))
# Ventas al dia que piden ademas los niveles altos ("que se venda rapido"): algo caro que
# sale una vez al dia puede dar los puntos, pero no es lo que se entiende por nivel S.
VENTAS_DIA_MIN = {"S": 5.0, "A": 2.0}
NIVELES = ("S", "A", "B", "C", "D")
SIN_NIVEL = ""

TIPOS = ("mods", "arcanos", "sets_prime", "piezas_prime", "reliquias", "otros")

# Multiplicador del endo segun la rareza del mod.
_ENDO_RAREZA = {"common": 1, "uncommon": 2, "rare": 3, "legendary": 4}


def tipo_de(etiquetas) -> str:
    """El tipo de la lista segun las etiquetas de warframe.market."""
    e = set(etiquetas or ())
    if "mod" in e:
        return "mods"
    if "arcane_enhancement" in e:
        return "arcanos"
    if "relic" in e:
        return "reliquias"
    if "prime" in e and "set" in e:
        return "sets_prime"
    if "prime" in e and ("component" in e or "blueprint" in e):
        return "piezas_prime"
    return "otros"


def copias_para_rango(rango: int) -> int:
    """Copias de un arcano que hacen falta para tenerlo a ese rango (21 para rango 5)."""
    return (rango + 1) * (rango + 2) // 2


def endo_para_rango(rango: int, etiquetas) -> int | None:
    """Endo para subir un mod de 0 a `rango`; None si no se sabe su rareza."""
    for etiqueta in etiquetas or ():
        if etiqueta in _ENDO_RAREZA:
            return 10 * _ENDO_RAREZA[etiqueta] * (2 ** rango - 1)
    return None


def nivel_de(puntos: float, ventas_dia: float | None = None) -> str:
    """El nivel de esos puntos. Con `ventas_dia`, S y A exigen ademas su ritmo minimo de
    ventas: si no llega, baja al primer nivel que si cumpla."""
    for nivel, minimo in UMBRALES:
        if puntos < minimo:
            continue
        if ventas_dia is not None and ventas_dia < VENTAS_DIA_MIN.get(nivel, 0.0):
            continue
        return nivel
    return "D"


def normalizar(texto: str) -> str:
    """Minusculas y sin tildes, para buscar por nombre."""
    plano = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in plano if unicodedata.category(c) != "Mn").lower()


@dataclass(slots=True)
class Venta:
    """Como se vende un objeto a un rango (o variante) concreto."""

    rango: int | None
    subtipo: str | None
    precio: float                 # mediana (o media) de las ventas cerradas de 30 dias
    ventas_30d: int
    dias_30d: int | None
    ventas_48h: int | None
    venta_min: float | None       # el vendedor conectado mas barato en la foto
    compra_max: float | None      # el comprador conectado que mas paga en la foto
    min_30d: float | None
    max_30d: float | None

    @property
    def ventas_dia(self) -> float:
        return self.ventas_30d / DIAS

    @property
    def ventas_dia_48h(self) -> float | None:
        return None if self.ventas_48h is None else self.ventas_48h / 2

    @property
    def rapidez(self) -> float:
        return min(1.0, self.ventas_dia / VENTAS_DIA_TOPE)

    @property
    def puntos(self) -> float:
        return self.precio * self.rapidez

    @property
    def pocos_datos(self) -> bool:
        return self.ventas_30d < MIN_VENTAS or (self.dias_30d is not None and self.dias_30d < MIN_DIAS)

    @property
    def margen(self) -> float | None:
        """Lo que separa al mejor comprador del vendedor mas barato (None si falta uno)."""
        if self.venta_min is None or self.compra_max is None:
            return None
        return self.venta_min - self.compra_max


@dataclass(slots=True)
class Fila:
    """Una linea de la lista: el objeto, vendido al rango que mas conviene."""

    slug: str
    nombre_en: str
    tipo: str
    venta: Venta                       # al rango recomendado
    nivel: str                         # S/A/B/C/D o "" (pocos datos)
    rango_max: int | None = None
    otra: Venta | None = None          # el otro rango (R0 si se recomienda el maximo y al reves)
    # Por que ese rango: "" (no tiene rangos), "unico" (solo hay datos de uno),
    # "arcano_max" / "arcano_suelto" (cuentan las copias), "mod_precio" (solo precios).
    motivo_rango: str = ""
    copias: int | None = None          # arcanos: copias para el rango maximo
    endo: int | None = None            # mods: endo para el rango maximo
    boveda: bool | None = None         # None = no se sabe
    ducados: int | None = None
    # Lo rellena la interfaz con el indice (nombre en el idioma del jugador y ficha).
    nombre: str = ""
    item_id: int | None = None
    clave_busqueda: str = ""

    @property
    def puntos(self) -> float:
        return self.venta.puntos

    @property
    def pocos_datos(self) -> bool:
        return self.nivel == SIN_NIVEL


def _venta(precio, rango, subtipo) -> Venta | None:
    """La venta de un `Precio` de la foto, o None si no hay ventas cerradas con precio."""
    if precio is None:
        return None
    habitual = precio.mediana_30d if precio.mediana_30d is not None else precio.media_30d
    volumen = precio.volumen_30d
    if not habitual or not volumen or habitual <= 0 or volumen <= 0:
        return None
    return Venta(
        rango=rango, subtipo=subtipo, precio=float(habitual), ventas_30d=int(volumen),
        dias_30d=precio.dias_30d, ventas_48h=precio.volumen_48h, venta_min=precio.venta_min,
        compra_max=precio.compra_max, min_30d=precio.min_30d, max_30d=precio.max_30d,
    )


def _orden_fiable(v: Venta) -> tuple:
    return (not v.pocos_datos, v.puntos, v.ventas_30d)


def fila_de(slug: str, objeto: dict, fotos) -> Fila | None:
    """La fila de un objeto de la foto, o None si no tiene ventas con las que calcular."""
    etiquetas = objeto.get("t") or ()
    tipo = tipo_de(etiquetas)
    rango_max = objeto.get("r") or None
    subtipos = list(objeto.get("s") or ()) or [None]
    if tipo == "mods":
        # Las variantes raras de un mod no tienen ventas propias: solo cuenta la normal.
        subtipos = subtipos[:1]
    mejor: Venta | None = None
    otra: Venta | None = None
    motivo, copias, endo = "", None, None
    if rango_max:
        subtipo = subtipos[0]
        base = _venta(fotos.buscar(slug, 0, subtipo), 0, subtipo)
        tope = _venta(fotos.buscar(slug, rango_max, subtipo), rango_max, subtipo)
        if tipo == "arcanos":
            copias = copias_para_rango(rango_max)
        elif tipo == "mods":
            endo = endo_para_rango(rango_max, etiquetas)
        if base is None and tope is None:
            return None
        if base is None or tope is None:
            mejor, motivo = (base or tope), "unico"
        elif base.pocos_datos != tope.pocos_datos:
            # Solo uno de los dos rangos tiene ventas suficientes: ese manda.
            mejor, otra = (tope, base) if base.pocos_datos else (base, tope)
            motivo = "unico"
        elif copias:
            if tope.precio >= copias * base.precio:
                mejor, otra, motivo = tope, base, "arcano_max"
            else:
                mejor, otra, motivo = base, tope, "arcano_suelto"
        else:
            # Al maximo solo si de verdad se saca mas: a igual precio, subirlo es tirar el endo.
            sube = tope.puntos > base.puntos and tope.precio > base.precio
            mejor, otra = (tope, base) if sube else (base, tope)
            motivo = "mod_precio"
    else:
        ventas = [v for v in (_venta(fotos.buscar(slug, None, s), None, s) for s in subtipos) if v is not None]
        if not ventas:
            return None
        mejor = max(ventas, key=_orden_fiable)
    nivel = SIN_NIVEL if mejor.pocos_datos else nivel_de(mejor.puntos, mejor.ventas_dia)
    boveda = objeto.get("v")
    return Fila(
        slug=slug, nombre_en=str(objeto.get("n") or slug), tipo=tipo, venta=mejor, nivel=nivel,
        rango_max=rango_max, otra=otra, motivo_rango=motivo, copias=copias, endo=endo,
        boveda=bool(boveda) if boveda is not None else None, ducados=objeto.get("d"),
    )


def calcular(fotos) -> list[Fila]:
    """Todas las filas de la foto `fotos` (un `PreciosDiarios`), por nivel y, dentro de cada
    nivel, de mas a menos puntos.

    Las de pocos datos van al final. Es trabajo de fondo: no llamar desde la interfaz.
    """
    filas = []
    for slug, objeto in list(fotos.objetos().items()):
        if not isinstance(objeto, dict):
            continue
        fila = fila_de(slug, objeto, fotos)
        if fila is not None:
            filas.append(fila)
    filas.sort(key=orden_por_defecto)
    return filas


def orden_por_defecto(fila: Fila) -> tuple:
    puesto = NIVELES.index(fila.nivel) if fila.nivel in NIVELES else len(NIVELES)
    return (fila.pocos_datos, puesto, -fila.puntos, -fila.venta.ventas_30d, fila.slug)


def poner_nombres(filas: list[Fila], con, castellano: bool) -> int:
    """Rellena nombre (en el idioma del jugador), ficha y boveda con el indice local.

    `con` es una conexion sqlite al indice (o None: se queda el nombre en ingles de la
    foto). Devuelve cuantas filas se han podido enlazar con su ficha.
    """
    por_slug: dict[str, tuple] = {}
    if con is not None:
        try:
            for item_id, slug, en, es, vaulted, padre_en, padre_es in con.execute(
                "SELECT i.id, i.market_slug, i.nombre_en, i.nombre_es, i.vaulted, p.nombre_en, p.nombre_es "
                "FROM items i LEFT JOIN items p ON p.id = i.padre_id "
                "WHERE i.market_slug IS NOT NULL AND i.market_slug <> ''"
            ):
                if padre_en:
                    # Las piezas se llaman "Hoja" a secas en el indice: delante va de que son.
                    es = f"{padre_es or padre_en}: {es or en}"
                    en = f"{padre_en}: {en}"
                por_slug[slug] = (item_id, en, es, vaulted)
        except Exception:  # noqa: BLE001 - un indice viejo o a medias no rompe la lista
            por_slug = {}
    enlazadas = 0
    for fila in filas:
        dato = por_slug.get(fila.slug)
        en, es = fila.nombre_en, ""
        if dato is not None:
            fila.item_id = dato[0]
            en, es = dato[1] or fila.nombre_en, dato[2] or ""
            if fila.boveda is None and dato[3] is not None and fila.tipo in ("sets_prime", "piezas_prime"):
                fila.boveda = bool(dato[3])
            enlazadas += 1
            if fila.tipo == "sets_prime":
                # En el indice el set es el propio objeto ("Loki Prime"): aqui se vende el set.
                en = en if "set" in en.lower().split() else f"{en} (set)"
                es = es and (es if "set" in es.lower().split() else f"{es} (set)")
        fila.nombre = (es or en) if castellano else (en or es)
        # Se busca en los dos idiomas: mucha gente conoce el nombre ingles del mercado.
        fila.clave_busqueda = normalizar(f"{es} {en} {fila.nombre_en}")
    return enlazadas


def filtrar(filas: list[Fila], tipo: str = "", boveda: str = "", texto: str = "",
            con_pocos_datos: bool = True) -> list[Fila]:
    """`tipo`: uno de TIPOS o "" (todos). `boveda`: "" (da igual), "si" o "no"."""
    palabras = normalizar(texto).split()
    salida = []
    for fila in filas:
        if tipo and fila.tipo != tipo:
            continue
        if boveda == "si" and fila.boveda is not True:
            continue
        if boveda == "no" and fila.boveda is not False:
            continue
        if not con_pocos_datos and fila.pocos_datos:
            continue
        if palabras and not all(p in fila.clave_busqueda for p in palabras):
            continue
        salida.append(fila)
    return salida
