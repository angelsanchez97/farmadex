"""Reglas de maestria: que objetos del catalogo dan rango y cuanta XP hace falta.

La XP de `XPInfo` es acumulada de por vida (un Excalibur puede llevar 4 millones),
asi que "dominado" es simplemente XP >= la que pide el rango maximo del objeto:

- Warframes, necramechs, archwings, companeros y K-Drives: 1000 * rango^2
  (900.000 a rango 30; 1.600.000 a rango 40 para los necramechs).
- Armas, amps, zaws, kitguns y armas de companero: 500 * rango^2
  (450.000 a rango 30; 800.000 a rango 40 para Kuva, Tenet, Coda y Paracesis).

Pendiente de confirmar con el fichero real: la curva de los K-Drives (se asume la
de warframe) y si algun arma con tope 40 se escapa del filtro por nombre.
"""

from __future__ import annotations

import re

DOMINADO = "dominado"
A_MEDIAS = "a_medias"
SIN_TOCAR = "sin_tocar"
NO_APLICA = "no_aplica"  # el objeto no da maestria (componente, mod, recurso...)
DESCONOCIDO = "desconocido"  # visto en pantalla (OCR) pero sin poder leer su rango
NO_DOMINADO = "no_dominado"  # visto en pantalla (OCR) sin linea de rango: a medias o sin tocar

XP_WARFRAME_30 = 1000 * 30 * 30
XP_WARFRAME_40 = 1000 * 40 * 40
XP_ARMA_30 = 500 * 30 * 30
XP_ARMA_40 = 500 * 40 * 40

# Categorias del catalogo cuyas fichas principales dan maestria.
CATEGORIAS_MASTERIZABLES = frozenset(
    {"Warframes", "Primary", "Secondary", "Melee", "Archwing", "Arch-Gun", "Arch-Melee",
     "Sentinels", "Pets"}
)
# Dentro de Misc, solo estos tipos dan maestria.
TIPOS_MISC_MASTERIZABLES = frozenset(
    {"Amp", "Zaw Component", "Kitgun Component", "K-Drive Component"}
)
# Tipos que siguen la curva de warframe (1000 * rango^2).
TIPOS_CURVA_WARFRAME = frozenset(
    {"Warframe", "Necramech", "Archwing", "Sentinel", "Pets", "K-Drive Component"}
)
TIPOS_TOPE_40 = frozenset({"Necramech"})
# Tipos que nunca dan maestria aunque esten en una categoria masterizable.
TIPOS_EXCLUIDOS = frozenset({"Componente", "Pet Parts", "Pet Resource", "Exalted Weapon"})

_ARMA_TOPE_40 = re.compile(r"(^|\s)(Kuva|Tenet|Coda)\s|Paracesis", re.IGNORECASE)

# En los modulares solo una pieza lleva la XP: la hoja del zaw (Tip), la camara del
# kitgun y el prisma del amp (Barrel) y la tabla del K-Drive (Deck). Las demas piezas
# estan en el catalogo con el mismo tipo pero no cuentan.
_PIEZA_MODULAR_CON_XP = {
    "Zaw Component": re.compile(r"/Tips?/(?!PvPVariant)"),
    "Kitgun Component": re.compile(r"/Barrel/"),
    "Amp": re.compile(r"/Barrel/|Barrel"),
    "K-Drive Component": re.compile(r"Deck$"),
}


def es_masterizable(categoria: str | None, tipo: str | None, unique_name: str = "") -> bool:
    """True si la ficha del catalogo es un objeto que da rango de maestria por si mismo."""
    if tipo in TIPOS_EXCLUIDOS:
        return False
    if categoria == "Misc":
        if tipo not in TIPOS_MISC_MASTERIZABLES:
            return False
    elif categoria not in CATEGORIAS_MASTERIZABLES:
        return False
    patron = _PIEZA_MODULAR_CON_XP.get(tipo or "")
    if patron and not patron.search(unique_name or ""):
        return False
    return True


def umbral_xp(categoria: str | None, tipo: str | None, nombre_en: str | None,
              unique_name: str = "") -> int | None:
    """XP necesaria para dominar el objeto, o None si no da maestria."""
    if not es_masterizable(categoria, tipo, unique_name):
        return None
    if tipo in TIPOS_CURVA_WARFRAME:
        return XP_WARFRAME_40 if tipo in TIPOS_TOPE_40 else XP_WARFRAME_30
    if nombre_en and _ARMA_TOPE_40.search(nombre_en):
        return XP_ARMA_40
    return XP_ARMA_30


def estado_por_xp(xp: int | None, umbral: int | None) -> str:
    if umbral is None:
        return NO_APLICA
    if not xp:
        return SIN_TOCAR
    return DOMINADO if xp >= umbral else A_MEDIAS


def tope_rango(umbral: int | None) -> int | None:
    """Rango maximo del objeto (30 o 40) segun su umbral de XP, o None si no da maestria."""
    if umbral is None:
        return None
    return 40 if umbral in (XP_WARFRAME_40, XP_ARMA_40) else 30


def estado_por_rango(rango: int | None, tope: int | None) -> str:
    """Estado a partir del rango leido directamente (OCR), sin pasar por XP.

    Un rango por encima del tope es una lectura mal hecha ("38" por "30"), y un
    rango sin leer no se adivina: los dos salen como DESCONOCIDO.
    """
    if tope is None:
        return NO_APLICA
    if rango is None or rango < 0 or rango > tope:
        return DESCONOCIDO
    return DOMINADO if rango >= tope else A_MEDIAS


def xp_sintetica(rango: int, umbral: int) -> int:
    """XP acumulada minima que corresponde al rango leido; `rango_actual` la invierte exacta.

    Vale para "a medias" y para "dominado" (rango == tope -> umbral); no es la XP real.
    """
    tope = tope_rango(umbral) or 30
    por_rango = umbral // (tope * tope)
    return por_rango * max(0, min(rango, tope)) ** 2


def rango_actual(xp: int, umbral: int) -> int:
    """Rango aproximado del objeto (0-30 o 0-40) a partir de su XP acumulada."""
    tope = 40 if umbral in (XP_WARFRAME_40, XP_ARMA_40) else 30
    por_rango = umbral // (tope * tope)
    rango = int((max(xp, 0) / por_rango) ** 0.5)
    return min(rango, tope)
