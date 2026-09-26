"""Sistema de grados de los agrietados.

La formula (wiki oficial, "Riven Mods > Attribute Value Formula", y la guia de
agrietados en castellano de Feedbackwav, 17/11/2024):

    valor = base(atributo, clase) x disposicion x multiplicador(positivos, negativos) x azar

con `azar` entre 0.9 y 1.1. El grado dice donde cayo el azar dentro de ese margen:
S es el 9.5-11 % por encima del centro y F el 9.5-11 % por debajo. En los negativos
la escala se invierte: cuanto menos quita, mejor grado.

Todo lo de aqui es aritmetica pura, sin red ni Qt, para poder probarlo con numeros.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..datos.items import normalizar

# Clases de arma con valores base propios. Los kitguns usan la de pistola (los
# secundarios; los primarios, la de rifle), los zaws la de cuerpo a cuerpo y las
# armas de centinela la de su tipo (Sweeper = escopeta, Deconstructor = melee).
CLASES = ("rifle", "shotgun", "pistol", "archgun", "melee")

NOMBRES_CLASE = {
    "rifle": "Rifle",
    "shotgun": "Escopeta",
    "pistol": "Secundaria",
    "archgun": "Archgun",
    "melee": "Cuerpo a cuerpo",
}

# (positivos, negativos) -> (multiplicador de los positivos, multiplicador del negativo)
MULTIPLICADORES = {
    (2, 0): (0.99, 0.0),
    (2, 1): (1.2375, -0.495),
    (3, 0): (0.75, 0.0),
    (3, 1): (0.9375, -0.75),
}

AZAR_MIN, AZAR_MAX = 0.9, 1.1

# Grados de la guia: (grado, desde, hasta) en % de desviacion respecto al centro.
# Los tramos van de -11 a 11 y no de -10 a 10 porque el juego redondea lo que ensena
# y una lectura en el borde no debe quedarse sin grado.
GRADOS = (
    ("S", 9.5, 11.0),
    ("A+", 7.5, 9.5),
    ("A", 5.5, 7.5),
    ("A-", 3.5, 5.5),
    ("B+", 1.5, 3.5),
    ("B", -1.5, 1.5),
    ("B-", -3.5, -1.5),
    ("C+", -5.5, -3.5),
    ("C", -7.5, -5.5),
    ("C-", -9.5, -7.5),
    ("F", -11.0, -9.5),
)

# Color por grado para la interfaz (verde arriba, rojo abajo).
COLOR_GRADO = {
    "S": "#7ee08a", "A+": "#8ccf6f", "A": "#9ccf6f", "A-": "#b5cf6f",
    "B+": "#d2d26f", "B": "#e2c455", "B-": "#e2a855",
    "C+": "#e8904a", "C": "#e8783c", "C-": "#e8603c", "F": "#e8456a",
}


@dataclass(frozen=True)
class Atributo:
    """Una estadistica que puede salir en un agrietado."""

    slug: str  # el url_name de warframe.market, que sirve de clave en todas partes
    nombre_en: str
    nombre_es: str
    prefijo: str
    sufijo: str
    # Valor base por clase; None si esa clase no puede tener el atributo.
    base: dict[str, float | None]
    unidad: str = "%"  # "%", "m", "s" o "" (numero a secas)
    solo_positivo: bool = False
    # Otras formas de escribirlo (lo que el juego pone en la tarjeta, en varios idiomas).
    alias: tuple[str, ...] = ()

    def base_en(self, clase: str) -> float | None:
        return self.base.get(clase)


def _b(rifle=None, shotgun=None, pistol=None, archgun=None, melee=None) -> dict[str, float | None]:
    return {"rifle": rifle, "shotgun": shotgun, "pistol": pistol, "archgun": archgun, "melee": melee}


# Valores base de la wiki (ExportUpgrades del Public Export de DE). El dano por faccion
# es x0.45 en la wiki, que en la tarjeta se ensena como +45 %.
ATRIBUTOS: tuple[Atributo, ...] = (
    Atributo("base_damage_/_melee_damage", "Damage", "Daño", "Visi", "Ata",
             _b(165, 164.7, 219.6, 99.9, 164.7),
             alias=("Melee Damage", "Daño cuerpo a cuerpo", "Daño base", "de daño")),
    Atributo("multishot", "Multishot", "Multidisparo", "Sati", "Can",
             _b(90, 119.7, 119.7, 60.3, None)),
    Atributo("critical_chance", "Critical Chance", "Probabilidad crítica", "Crita", "Cron",
             _b(149.99, 90, 149.99, 99.9, 180),
             alias=("Critical Chance (x2 for Heavy Attacks)", "Probabilidad de crítico",
                    "Probabilidad crítica (x2 para ataques pesados)")),
    Atributo("critical_damage", "Critical Damage", "Daño crítico", "Acri", "Tis",
             _b(120, 90, 90, 80.1, 90), alias=("Multiplicador crítico",)),
    Atributo("status_chance", "Status Chance", "Probabilidad de estado", "Hexa", "Dex",
             _b(90, 90, 90, 60.3, 90), alias=("Probabilidad de efecto de estado",)),
    Atributo("status_duration", "Status Duration", "Duración de estado", "Deci", "Des",
             _b(99.99, 99.99, 99.99, 99.99, 99.99), alias=("Duración del estado",)),
    Atributo("fire_rate_/_attack_speed", "Fire Rate", "Cadencia de fuego", "Croni", "Dra",
             _b(60.03, 90, 74.7, 60.03, 54.9),
             alias=("Fire Rate (x2 for Bows)", "Attack Speed", "Velocidad de ataque", "Cadencia",
                    "Cadencia de fuego (x2 para arcos)")),
    Atributo("magazine_capacity", "Magazine Capacity", "Capacidad del cargador", "Arma", "Tin",
             _b(50, 50, 50, 60.3, None), alias=("Capacidad de cargador", "Cargador")),
    Atributo("reload_speed", "Reload Speed", "Velocidad de recarga", "Feva", "Tak",
             _b(50, 50, 50, 99.9, None), alias=("Recarga",)),
    Atributo("ammo_maximum", "Ammo Maximum", "Munición máxima", "Ampi", "Bin",
             _b(49.95, 90, 90, 99.9, None), alias=("Máximo de munición", "Munición")),
    Atributo("punch_through", "Punch Through", "Atravesar", "Lexi", "Nok",
             _b(2.7, 2.7, 2.7, 2.7, None), unidad="m", solo_positivo=True,
             alias=("Penetración", "Perforación de objetivos")),
    Atributo("recoil", "Weapon Recoil", "Retroceso", "Zeti", "Mag",
             _b(90, 90, 90, 90, None), alias=("Retroceso del arma", "Recoil")),
    Atributo("zoom", "Zoom", "Zoom", "Hera", "Lis", _b(59.99, None, 80.1, 59.99, None)),
    Atributo("projectile_speed", "Projectile Speed", "Velocidad de proyectil", "Conci", "Nak",
             _b(90, 90, 90, None, None),
             alias=("Flight Speed", "Velocidad de vuelo", "Velocidad del proyectil")),
    Atributo("impact_damage", "Impact", "Impacto", "Magna", "Ton",
             _b(119.97, 119.97, 119.97, 90, 119.7), alias=("Impact Damage", "Daño de impacto")),
    Atributo("puncture_damage", "Puncture", "Perforación", "Insi", "Cak",
             _b(119.97, 119.97, 119.97, 90, 119.7), alias=("Puncture Damage", "Daño de perforación")),
    Atributo("slash_damage", "Slash", "Cortante", "Sci", "Sus",
             _b(119.97, 119.97, 119.97, 90, 119.7), alias=("Slash Damage", "Daño cortante", "Daño de corte")),
    Atributo("cold_damage", "Cold", "Frío", "Geli", "Do",
             _b(90, 90, 90, 119.7, 90), solo_positivo=True, alias=("Cold Damage", "Daño de frío", "Hielo")),
    Atributo("heat_damage", "Heat", "Calor", "Igni", "Pha",
             _b(90, 90, 90, 119.7, 90), solo_positivo=True, alias=("Heat Damage", "Daño de calor", "Fuego")),
    Atributo("electric_damage", "Electricity", "Electricidad", "Vexi", "Tio",
             _b(90, 90, 90, 119.7, 90), solo_positivo=True,
             alias=("Electric Damage", "Electricity Damage", "Daño eléctrico", "Daño de electricidad")),
    Atributo("toxin_damage", "Toxin", "Toxina", "Toxi", "Tox",
             _b(90, 90, 90, 119.7, 90), solo_positivo=True, alias=("Toxin Damage", "Daño de toxina", "Veneno")),
    Atributo("damage_vs_grineer", "Damage to Grineer", "Daño a Grineer", "Argi", "Con",
             _b(45, 45, 45, 45, 45),
             alias=("Damage vs Grineer", "Daño contra Grineer", "Daño contra los Grineer", "de daño a Grineer")),
    Atributo("damage_vs_corpus", "Damage to Corpus", "Daño a Corpus", "Manti", "Tron",
             _b(45, 45, 45, 45, 45),
             alias=("Damage vs Corpus", "Daño contra Corpus", "Daño contra los Corpus", "de daño a Corpus")),
    Atributo("damage_vs_infested", "Damage to Infested", "Daño a Infestados", "Pura", "Ada",
             _b(45, 45, 45, 45, 45),
             alias=("Damage vs Infested", "Daño contra Infestados", "Daño contra los Infestados",
                    "Daño a los Infestados", "de daño a Infestados")),
    # Solo cuerpo a cuerpo.
    Atributo("range", "Range", "Alcance", "Locti", "Tor", _b(melee=1.94), unidad="m"),
    Atributo("combo_duration", "Combo Duration", "Duración de combo", "Tempi", "Nem",
             _b(melee=8.1), unidad="s", alias=("Duración del combo",)),
    Atributo("channeling_damage", "Initial Combo", "Combo inicial", "Para", "Um",
             _b(melee=24.5), unidad=""),
    Atributo("channeling_efficiency", "Heavy Attack Efficiency", "Eficiencia de ataque pesado",
             "Forti", "Us", _b(melee=73.44), alias=("Eficiencia de ataques pesados",)),
    Atributo("finisher_damage", "Finisher Damage", "Daño de remate", "Exi", "Cta",
             _b(melee=119.7), alias=("Daño de remates", "Daño de finalizador")),
    Atributo("critical_chance_on_slide_attack", "Critical Chance for Slide Attack",
             "Probabilidad crítica al deslizarse", "Pleci", "Nent", _b(melee=120),
             alias=("Critical Chance on Slide Attack", "Probabilidad crítica en ataques deslizantes",
                    "Probabilidad crítica en deslizamiento")),
    Atributo("chance_to_gain_extra_combo_count", "Additional Combo Count Chance",
             "Probabilidad de combo adicional", "Laci", "Nus", _b(melee=58.77),
             alias=("Chance to Gain Combo Count", "Probabilidad de ganar combo",
                    "Probabilidad adicional de adquirir combo")),
)

POR_SLUG: dict[str, Atributo] = {a.slug: a for a in ATRIBUTOS}
PREFIJOS: dict[str, str] = {a.prefijo.lower(): a.slug for a in ATRIBUTOS}
SUFIJOS: dict[str, str] = {a.sufijo.lower(): a.slug for a in ATRIBUTOS}


def nombres_para_casar() -> list[tuple[str, str]]:
    """(texto normalizado, slug) de todos los nombres y alias, para casar lo leido."""
    salida = []
    for a in ATRIBUTOS:
        for texto in (a.nombre_en, a.nombre_es, *a.alias):
            clave = normalizar(texto)
            if clave:
                salida.append((clave, a.slug))
    return salida


def clase_de(tipo_market: str, grupo: str = "") -> str:
    """Clase de valores base a partir de lo que dice warframe.market del arma.

    `rivenType` vale rifle/shotgun/pistol/melee/zaw/kitgun y `group` distingue
    archgun y sentinel. Un kitgun se trata como pistola (la version secundaria es
    la que tiene agrietados desde el principio; la primaria usa valores de rifle
    y no se distingue aqui: se avisa en la interfaz).
    """
    if grupo == "archgun":
        return "archgun"
    tipo = (tipo_market or "").lower()
    if tipo == "zaw":
        return "melee"
    if tipo == "kitgun":
        return "pistol"
    return tipo if tipo in CLASES else "rifle"


def rango(slug: str, clase: str, disposicion: float, positivos: int, negativos: int,
          negativo: bool = False) -> tuple[float, float] | None:
    """(minimo, maximo) que puede ensenar esa estadistica en esa arma, o None si no aplica.

    Para un negativo devuelve los dos valores negativos, el mas cercano a cero primero
    en magnitud... es decir, (mas negativo, menos negativo) ordenado de menor a mayor.
    """
    atributo = POR_SLUG.get(slug)
    if atributo is None:
        return None
    base = atributo.base_en(clase)
    if base is None:
        return None
    multiplicadores = MULTIPLICADORES.get((positivos, negativos))
    if multiplicadores is None:
        return None
    factor = multiplicadores[1] if negativo else multiplicadores[0]
    if factor == 0:
        return None
    centro = base * disposicion * factor
    a, b = centro * AZAR_MIN, centro * AZAR_MAX
    return (min(a, b), max(a, b))


def desviacion(valor: float, minimo: float, maximo: float) -> float:
    """En que % del centro del rango cae `valor` (0 = justo en medio, +10 = el tope)."""
    centro = (minimo + maximo) / 2
    if centro == 0:
        return 0.0
    return (abs(valor) / abs(centro) - 1.0) * 100.0


def grado(valor: float, minimo: float, maximo: float, negativo: bool = False) -> str | None:
    """Letra del grado, o None si el valor queda fuera de lo posible (arma o lectura mal)."""
    # Redondeado a centesimas: 109.5 sobre 100 es +9.5 exacto, no 9.4999.
    desv = round(desviacion(valor, minimo, maximo), 2)
    if negativo:
        desv = -desv  # un negativo que quita menos es mejor
    for letra, desde, hasta in GRADOS:
        if desde <= desv <= hasta:
            return letra
    return None


def posicion(valor: float, minimo: float, maximo: float, negativo: bool = False) -> float:
    """0..1 de peor a mejor dentro del rango, para pintar una barra. Se recorta a 0..1."""
    desv = desviacion(valor, minimo, maximo)
    if negativo:
        desv = -desv
    return max(0.0, min(1.0, (desv + 10.0) / 20.0))


@dataclass
class Evaluacion:
    slug: str
    valor: float
    negativo: bool
    minimo: float | None
    maximo: float | None
    grado: str | None
    posicion: float | None

    @property
    def atributo(self) -> Atributo | None:
        return POR_SLUG.get(self.slug)

    @property
    def fuera_de_rango(self) -> bool:
        return self.minimo is not None and self.grado is None


def evaluar(estadisticas: list[tuple[str, float, bool]], clase: str, disposicion: float) -> list[Evaluacion]:
    """Evalua todas las estadisticas de un agrietado a la vez.

    `estadisticas` son (slug, valor, negativo). El numero de positivos y negativos
    sale de la propia lista, que es lo que fija el multiplicador.
    """
    positivos = sum(1 for _, _, n in estadisticas if not n)
    negativos = sum(1 for _, _, n in estadisticas if n)
    salida = []
    for slug, valor, negativo in estadisticas:
        tramo = rango(slug, clase, disposicion, positivos, negativos, negativo)
        if tramo is None:
            salida.append(Evaluacion(slug, valor, negativo, None, None, None, None))
            continue
        minimo, maximo = tramo
        salida.append(Evaluacion(
            slug, valor, negativo, minimo, maximo,
            grado(valor, minimo, maximo, negativo), posicion(valor, minimo, maximo, negativo),
        ))
    return salida


def descomponer_nombre(nombre: str) -> list[str] | None:
    """Slugs que forman el nombre del agrietado ("Hexa-scidra" -> estado, cortante, cadencia).

    El juego monta el nombre con los prefijos de las estadisticas mejores y el sufijo
    de la peor: prefijo-prefijo+sufijo con tres, prefijo+sufijo con dos. Devuelve None
    si no cuadra con ningun prefijo/sufijo conocido: entonces lo leido no es un nombre
    de agrietado (o esta mal leido).
    """
    limpio = "".join(c for c in (nombre or "").lower() if c.isalpha())
    if len(limpio) < 4:
        return None
    for sufijo, slug_sufijo in SUFIJOS.items():
        if not limpio.endswith(sufijo):
            continue
        resto = limpio[: -len(sufijo)]
        partes = _partir_prefijos(resto)
        if partes is not None:
            return partes + [slug_sufijo]
    return None


def _partir_prefijos(texto: str) -> list[str] | None:
    if not texto:
        return []
    for prefijo, slug in PREFIJOS.items():
        if texto.startswith(prefijo):
            resto = _partir_prefijos(texto[len(prefijo):])
            if resto is not None and len(resto) <= 1:
                return [slug] + resto
    return None


def formatear_valor(slug: str, valor: float) -> str:
    """Como lo escribe el juego: '+116%', '-2.4', '+2.7m', '+8.1s'."""
    atributo = POR_SLUG.get(slug)
    unidad = atributo.unidad if atributo else "%"
    signo = "+" if valor >= 0 else "-"
    numero = f"{abs(valor):.1f}".rstrip("0").rstrip(".")
    return f"{signo}{numero}{unidad}"
