"""Que destacar al abrir una reliquia: preajustes de prioridad y el motivo de cada tarjeta.

Un jugador pidio poder decirle al overlay que le importa (piezas que le faltan,
platino, sets a medio completar) porque con todo al mismo tamano costaba ver de un
vistazo lo importante. En vez de una lista ordenable, que nadie toca en los 15 s de
la cuenta atras, hay cuatro preajustes con nombre claro. Cada uno es un ORDEN DE
CRITERIOS: se compara criterio a criterio y el primero que distingue dos
recompensas decide. El mismo orden da el motivo grande de cada tarjeta: el primer
criterio que se cumple en ella.

Criterios, todos sacados de datos que ya existen:

- ``falta``: la pieza es un objetivo pendiente. Las marcas de la pestana Primes
  son objetivos, asi que tambien cuentan.
- ``set``: pieza de un objeto del que ya tienes otras piezas (inventario leido u
  objetivo completado) y esta todavia no. Gana la que deja el set mas cerca de
  completarse ("3/4" frente a "2/4").
- ``nueva``: segun el perfil, el objeto al que pertenece no lo has usado nunca
  (maestria sin tocar), o el inventario dice que tienes 0. "A medias" no cuenta a
  proposito: si lo estas subiendo de rango ya lo tienes construido y la pieza no
  te hace falta.
- ``platino``: el precio. Dos precios a menos de un 10 % se consideran empate y
  decide el siguiente criterio: 12p contra 11p no es razon para dejar pasar una
  pieza que te falta.
- ``ducados``: los ducados de Baro.

Sin datos para un criterio (no hay perfil, no hay objetivos, no se leyo el
inventario) ese criterio vale 0 en todas y se pasa al siguiente: no se inventa
nada. "Equilibrado" es el comportamiento de siempre (objetivo y luego el mayor
de platino o ducados/10) y lo sigue resolviendo `comparador.decidir`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..idiomas import t

ME_FALTA = "me_falta"
PLATINO = "platino"
DUCADOS = "ducados"
EQUILIBRADO = "equilibrado"
PRIORIDAD_POR_DEFECTO = ME_FALTA

# (clave, texto del desplegable, tooltip de una linea). El orden es el del desplegable.
PREAJUSTES: tuple[tuple[str, str, str], ...] = (
    (ME_FALTA, "Lo que me falta",
     "Primero las piezas de tus objetivos y marcas, luego las que completan un set y lo que aun no tienes; despues el platino."),
    (PLATINO, "Mas platino",
     "La que mas platino vale; si dos cuestan casi lo mismo, la que te falta."),
    (DUCADOS, "Mas ducados",
     "La que mas ducados da para Baro Ki'Teer; a igualdad, la de mas platino."),
    (EQUILIBRADO, "Equilibrado",
     "Tus objetivos y luego el mayor valor entre platino y ducados, como hasta ahora."),
)
CLAVES = tuple(clave for clave, _texto, _ayuda in PREAJUSTES)

# Margen por debajo del cual dos precios se consideran empate (igual que comparador.EMPATE).
EMPATE_PLATINO = 0.10

ORDEN_RAREZA = {"comun": 0, "poco comun": 1, "rara": 2}

# El orden de criterios de cada preajuste (salvo equilibrado, que va por su camino).
CRITERIOS: dict[str, tuple[str, ...]] = {
    ME_FALTA: ("falta", "set", "nueva", "platino", "ducados", "rareza"),
    PLATINO: ("platino", "falta", "set", "nueva", "ducados", "rareza"),
    DUCADOS: ("ducados", "platino", "falta", "set", "nueva", "rareza"),
}
# Los que responden a "te hace falta": deciden con seguridad, no dependen del mercado.
CRITERIOS_DE_FALTA = ("falta", "set", "nueva")


def normalizar(prioridad: str | None) -> str:
    """Una clave valida; lo desconocido (config vieja, a mano) cae al valor por defecto."""
    return prioridad if prioridad in CLAVES else PRIORIDAD_POR_DEFECTO


# -- valor de cada criterio ----------------------------------------------------
#
# Todo funciona igual sobre una `Recompensa` que sobre una `Puntuacion`: se leen
# los mismos atributos con getattr, para que la interfaz pueda pintar el motivo en
# cuanto llega el OCR, antes del veredicto (que trae los precios).


def tiene_la_pieza(r) -> bool:
    tienes = getattr(r, "tienes", None)
    return tienes is not None and tienes >= 1


def valor_falta(r) -> float:
    return 1.0 if getattr(r, "objetivo", "") else 0.0


def progreso_set(r) -> tuple[int, int] | None:
    """(piezas que tendrias al cogerla, total) si completa un set empezado; None si no aplica."""
    tengo, total = getattr(r, "set_tengo", 0) or 0, getattr(r, "set_total", 0) or 0
    if tengo < 1 or total < 2 or tiene_la_pieza(r):
        return None
    return min(tengo + 1, total), total


def valor_set(r) -> float:
    progreso = progreso_set(r)
    return progreso[0] / progreso[1] if progreso else 0.0


def motivo_nueva(r) -> str:
    """"sin_dominar", "no_la_tienes" o "" si no aplica o no se sabe."""
    if tiene_la_pieza(r):
        return ""
    if getattr(r, "maestria_estado", None) == "sin_tocar":
        return "sin_dominar"
    if getattr(r, "tienes", None) == 0:
        return "no_la_tienes"
    return ""


def valor_nueva(r) -> float:
    return 1.0 if motivo_nueva(r) else 0.0


def valor_platino(r) -> float:
    platino = getattr(r, "platino", None)
    return float(platino) if platino is not None else -1.0


def valor_ducados(r) -> float:
    return float(getattr(r, "ducados", None) or 0)


def valor_rareza(r) -> float:
    return float(ORDEN_RAREZA.get(getattr(r, "rareza", None) or "", -1))


VALORES = {
    "falta": valor_falta, "set": valor_set, "nueva": valor_nueva,
    "platino": valor_platino, "ducados": valor_ducados, "rareza": valor_rareza,
}


def comparar_en(criterio: str, a, b) -> int:
    """1 si `a` gana en ese criterio, -1 si gana `b`, 0 si empatan."""
    va, vb = VALORES[criterio](a), VALORES[criterio](b)
    if criterio == "platino" and va >= 0 and vb >= 0:
        mayor = max(va, vb)
        if mayor == 0 or abs(va - vb) / mayor < EMPATE_PLATINO:
            return 0
    return (va > vb) - (va < vb)


def comparar(a, b, prioridad: str) -> int:
    for criterio in CRITERIOS[prioridad]:
        resultado = comparar_en(criterio, a, b)
        if resultado:
            return resultado
    return 0


def criterio_decisivo(a, b, prioridad: str) -> str | None:
    """El primer criterio en que `a` supera a `b`; None si empatan en todos."""
    for criterio in CRITERIOS[prioridad]:
        resultado = comparar_en(criterio, a, b)
        if resultado:
            return criterio if resultado > 0 else None
    return None


def cumple(criterio: str, r) -> bool:
    """Si la recompensa tiene algo que decir en ese criterio (para su motivo grande)."""
    if criterio == "platino":
        return getattr(r, "platino", None) is not None
    if criterio == "rareza":
        return False  # la rareza desempata, pero no es un motivo que ensenar en grande
    return VALORES[criterio](r) > 0


# -- el motivo grande de cada tarjeta --------------------------------------------


@dataclass(frozen=True)
class Motivo:
    clave: str  # falta, set, nueva, platino, ducados, boveda, sin_valor, sin_precio, sin_identificar
    texto: str  # ya traducido, en minusculas: la interfaz decide si lo pone en mayusculas


def texto_criterio(criterio: str, r) -> str:
    if criterio == "falta":
        return t("Te falta")
    if criterio == "set":
        tengo, total = progreso_set(r) or (0, 0)
        return t("Completa set {progreso}", progreso=f"{tengo}/{total}")
    if criterio == "nueva":
        return t("Sin dominar") if motivo_nueva(r) == "sin_dominar" else t("No lo tienes")
    if criterio == "platino":
        return t("{n} platino", n=getattr(r, "platino", None))
    if criterio == "ducados":
        return t("{n} ducados", n=getattr(r, "ducados", None))
    return ""


def motivo_principal(r, prioridad: str | None) -> Motivo:
    """Lo que se pinta en grande arriba de la tarjeta segun el preajuste."""
    if getattr(r, "item_id", 1) == 0:  # reliquias.SIN_IDENTIFICAR, sin importar el modulo
        return Motivo("sin_identificar", t("Sin identificar"))
    prioridad = normalizar(prioridad)
    if prioridad == EQUILIBRADO:
        # El de siempre: objetivo y luego lo que mas vale, platino o ducados/10.
        orden: tuple[str, ...] = ("falta",)
        platino, ducados = getattr(r, "platino", None), getattr(r, "ducados", None) or 0
        if platino is not None and platino >= ducados / 10:
            orden += ("platino", "ducados")
        else:
            orden += ("ducados", "platino")
    else:
        orden = CRITERIOS[prioridad]
    for criterio in orden:
        if cumple(criterio, r):
            return Motivo(criterio, texto_criterio(criterio, r))
    if getattr(r, "vaulted", False):
        return Motivo("boveda", t("En boveda"))
    if not getattr(r, "comerciable", True) and not getattr(r, "ducados", None):
        return Motivo("sin_valor", t("Sin valor"))
    return Motivo("sin_precio", t("Sin precio"))
