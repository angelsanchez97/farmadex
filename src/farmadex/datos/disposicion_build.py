"""En que hueco de la pantalla de mejoras va cada mod leido, sin inventarlo.

La pantalla de mejoras del juego es una rejilla: los 8 huecos de mod en dos filas de
cuatro; encima, el aura y el exilus (warframes) o la postura y el exilus (cuerpo a
cuerpo); a la derecha, los arcanos (y el exilus de las armas de fuego). Medido sobre 34
capturas reales (1080p, 1440p, 4K y 21:9, en siete idiomas), la rejilla cambia de sitio
y de tamano con la escala de la interfaz y con la relacion de aspecto, asi que no vale
una posicion fija en pantalla: lo que SI es constante es la forma. El paso entre
columnas va de 0,20 a 0,26 veces el alto de la pantalla y el paso entre filas es siempre
0,553 veces el de columnas.

`colocar` busca el paso y el desplazamiento con los que los nombres leidos caen sobre
los huecos de la plantilla del equipo. Si dos colocaciones distintas explican igual de
bien lo leido (pocos mods, una columna entera vacia), NO se elige una: se devuelve
`segura = False` y la interfaz ensena los mods en el orden leido, diciendolo. Un mod que
no cae en ningun hueco (su tarjeta estaba ampliada bajo el cursor) queda en `sueltos`.

Las medidas van en fracciones del alto de la captura: x = centro del nombre respecto al
centro de la pantalla, y = borde de abajo del nombre.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Paso entre filas / paso entre columnas (medido: 0,543 a 0,563 en todas las capturas).
RELACION_FILAS = 0.553
# Paso entre columnas en fracciones del alto de la pantalla (medido: 0,206 a 0,254).
PASO_MIN, PASO_MAX = 0.17, 0.28
# Cuanto puede desviarse un nombre de su hueco, en pasos (los nombres largos se cortan y
# su centro se mueve; los de dos lineas bajan un poco).
TOL_X, TOL_Y = 0.22, 0.34
# Tamano de la tarjeta de mod del juego respecto a los pasos (medido a 1440p: tarjeta de
# 300 x 124 px con pasos de 328 x 181 px), y del bloque de un arcano (icono y nombre).
ANCHO_CARTA, ALTO_CARTA = 0.915, 0.685
ANCHO_ARCANO, ALTO_ARCANO = 0.9, 0.95
# El paso de columnas del juego con la interfaz a su escala normal, en altos de pantalla
# (mediana de las capturas a escala 100 %): con esto se pinta la copia a tamano real.
PASO_REAL = 0.228


@dataclass(frozen=True)
class Hueco:
    clave: str  # "mod1".."mod8", "aura", "exilus", "postura", "arcano1", "arcano2"
    tipo: str   # "mod", "aura", "exilus", "postura" o "arcano"
    x: float    # columna (en pasos de columna)
    y: float    # fila (en pasos de fila); la de los nombres leidos


def _ocho() -> list[Hueco]:
    return [Hueco(f"mod{fila * 4 + col + 1}", "mod", float(col), float(fila + 1))
            for fila in range(2) for col in range(4)]


# Los huecos de cada clase de equipo, como en el juego.
PLANTILLAS: dict[str, list[Hueco]] = {
    "warframe": [Hueco("aura", "aura", 1.0, 0.0), Hueco("exilus", "exilus", 2.0, 0.0)] + _ocho()
    + [Hueco("arcano1", "arcano", 3.97, 0.1), Hueco("arcano2", "arcano", 3.97, 1.7)],
    "arma": _ocho() + [Hueco("exilus", "exilus", 4.0, 1.5), Hueco("arcano1", "arcano", 3.97, 0.6)],
    "cuerpo": [Hueco("postura", "postura", 1.0, 0.0), Hueco("exilus", "exilus", 2.0, 0.0)] + _ocho()
    + [Hueco("arcano1", "arcano", 3.97, 0.21)],
}

# Que acepta cada tipo de hueco: el aura solo va en el suyo y la postura en el suyo
# (regla del juego); el exilus acepta un mod normal (no sabemos cuales son exilus).
_ACEPTA = {"mod": {"mod"}, "exilus": {"mod"}, "aura": {"aura"}, "postura": {"postura"}, "arcano": {"arcano"}}


def plantilla_de(categoria: str | None, tipo: str | None = None) -> str:
    """"warframe", "arma", "cuerpo" o "" (sin plantilla: companeros, archwing...)."""
    categoria, tipo = categoria or "", tipo or ""
    if categoria == "Warframes":
        return "warframe" if tipo in ("Warframe", "") else ""
    if categoria in ("Primary", "Secondary"):
        return "" if tipo == "Companion Weapon" else "arma"
    if categoria == "Melee":
        return "cuerpo" if tipo in ("Melee", "") else ""
    return ""


@dataclass(frozen=True)
class Punto:
    """Un nombre leido: `tipo` es "mod", "aura", "postura" o "arcano"."""

    tipo: str
    x: float
    y: float


@dataclass
class Disposicion:
    clase: str = ""                                   # plantilla usada ("" si ninguna)
    huecos: list[Hueco] = field(default_factory=list)  # los huecos a pintar
    mods: dict[str, int] = field(default_factory=dict)      # clave de hueco -> indice del mod
    arcanos: dict[str, int] = field(default_factory=dict)   # clave de hueco -> indice del arcano
    sueltos_mods: list[int] = field(default_factory=list)   # sin hueco conocido, en el orden leido
    sueltos_arcanos: list[int] = field(default_factory=list)
    segura: bool = False
    # Por que no se sabe: "sin_medidas" (no hay posiciones), "pocos" (no da para medir la
    # rejilla), "ambigua" (dos colocaciones igual de buenas), "no_encaja" o "".
    motivo: str = ""


def _pasos_candidatos(puntos: list[Punto]) -> list[float]:
    """Pasos de columna posibles: las distancias entre nombres, enteras o partidas en 2, 3 o 4."""
    vistos: dict[int, float] = {}
    for i, a in enumerate(puntos):
        for b in puntos[i + 1:]:
            distancia = abs(a.x - b.x)
            for n in (1, 2, 3, 4):
                paso = distancia / n
                if PASO_MIN <= paso <= PASO_MAX:
                    vistos.setdefault(round(paso / 0.003), paso)
    return list(vistos.values())


def _asignar(puntos: list[Punto], huecos: list[Hueco], paso: float, x0: float, y0: float):
    """(indice del punto -> hueco, error total) con ese paso y ese origen."""
    fila = paso * RELACION_FILAS
    mejores: dict[str, tuple[float, int]] = {}
    for i, p in enumerate(puntos):
        elegido = None
        for h in huecos:
            if p.tipo not in _ACEPTA[h.tipo]:
                continue
            dx = abs(p.x - (x0 + h.x * paso)) / paso
            dy = abs(p.y - (y0 + h.y * fila)) / fila
            if dx <= TOL_X and dy <= TOL_Y:
                error = dx + dy
                if elegido is None or error < elegido[0]:
                    elegido = (error, h.clave)
        if elegido is None:
            continue
        error, clave = elegido
        # Dos nombres en el mismo hueco: se queda el que mejor cae; el otro, suelto.
        if clave not in mejores or error < mejores[clave][0]:
            mejores[clave] = (error, i)
    asignacion = {i: clave for clave, (_e, i) in mejores.items()}
    return asignacion, sum(e for e, _i in mejores.values())


def colocar(clase: str, mods: list[Punto | None], arcanos: list[Punto | None]) -> Disposicion:
    """Reparte los mods y arcanos leidos en los huecos de la plantilla `clase`.

    `mods` y `arcanos` van en el orden leido; None donde no hay medida. Sin plantilla
    (`clase` vacia) se usa `colocar_libre`.
    """
    huecos = PLANTILLAS.get(clase)
    if not huecos:
        return colocar_libre(mods, arcanos)
    salida = Disposicion(clase=clase, huecos=list(huecos))
    todos = list(range(len(mods)))
    todos_arcanos = list(range(len(arcanos)))
    if not mods and not arcanos:
        salida.segura = True
        return salida
    if any(p is None for p in mods) or any(p is None for p in arcanos):
        salida.sueltos_mods, salida.sueltos_arcanos, salida.motivo = todos, todos_arcanos, "sin_medidas"
        return salida
    puntos: list[Punto] = list(mods) + list(arcanos)
    pasos = _pasos_candidatos(puntos)
    if not pasos:
        salida.sueltos_mods, salida.sueltos_arcanos, salida.motivo = todos, todos_arcanos, "pocos"
        return salida
    soluciones: list[tuple[int, float, dict[int, str]]] = []
    for paso in pasos:
        fila = paso * RELACION_FILAS
        # Si la colocacion buena existe, alguno de los tres primeros nombres cae en su hueco.
        for ancla in puntos[:3]:
            for h in huecos:
                if ancla.tipo not in _ACEPTA[h.tipo]:
                    continue
                asignacion, error = _asignar(puntos, huecos, paso, ancla.x - h.x * paso, ancla.y - h.y * fila)
                soluciones.append((len(asignacion), error, asignacion))
    mejor = max(n for n, _e, _a in soluciones)
    # Casi todo lo leido tiene que caer en un hueco (se admite alguna tarjeta ampliada).
    if mejor < 2 or mejor < len(puntos) - max(1, len(puntos) // 4):
        salida.sueltos_mods, salida.sueltos_arcanos, salida.motivo = todos, todos_arcanos, "no_encaja"
        return salida
    empatadas = [a for n, _e, a in soluciones if n == mejor]
    if any(a != empatadas[0] for a in empatadas[1:]):
        salida.sueltos_mods, salida.sueltos_arcanos, salida.motivo = todos, todos_arcanos, "ambigua"
        return salida
    asignacion = min((s for s in soluciones if s[0] == mejor), key=lambda s: s[1])[2]
    for i in todos:
        if i in asignacion:
            salida.mods[asignacion[i]] = i
        else:
            salida.sueltos_mods.append(i)
    for j in todos_arcanos:
        clave = asignacion.get(len(mods) + j)
        if clave:
            salida.arcanos[clave] = j
        else:
            salida.sueltos_arcanos.append(j)
    salida.segura = True
    return salida


def _grupos(valores: list[float], hueco: float) -> list[float]:
    """Centros de los grupos de valores separados por mas de `hueco`."""
    centros: list[list[float]] = []
    for v in sorted(valores):
        if centros and v - centros[-1][-1] <= hueco:
            centros[-1].append(v)
        else:
            centros.append([v])
    return [sum(g) / len(g) for g in centros]


def colocar_libre(mods: list[Punto | None], arcanos: list[Punto | None]) -> Disposicion:
    """Sin plantilla (companeros, archwing, equipo sin reconocer): los mods se ponen en la
    misma fila y columna en que se leyeron, sin decir que huecos hay ni cuales estan vacios.
    Los arcanos, aparte y en el orden leido."""
    salida = Disposicion(sueltos_arcanos=list(range(len(arcanos))))
    todos = list(range(len(mods)))
    if not mods:
        salida.segura = True
        return salida
    if any(p is None for p in mods):
        salida.sueltos_mods, salida.motivo = todos, "sin_medidas"
        return salida
    columnas = _grupos([p.x for p in mods], 0.08)
    pasos = [b - a for a, b in zip(columnas, columnas[1:])]
    paso = min((p for p in pasos if PASO_MIN <= p <= PASO_MAX), default=None)
    if paso is None:
        salida.sueltos_mods, salida.motivo = todos, "pocos"
        return salida
    fila = paso * RELACION_FILAS
    x0, y0 = min(p.x for p in mods), min(p.y for p in mods)
    ocupados: dict[tuple[int, int], int] = {}
    for i, p in enumerate(mods):
        col, fil = (p.x - x0) / paso, (p.y - y0) / fila
        # Medias filas existen (el exilus de un arma va entre las dos filas).
        fil_r = round(fil * 2) / 2
        if abs(col - round(col)) > TOL_X or abs(fil - fil_r) > TOL_Y / 2 or (round(col), fil_r) in ocupados:
            salida.sueltos_mods.append(i)
            continue
        ocupados[(round(col), fil_r)] = i
    if len(ocupados) < 2:
        salida.mods, salida.huecos, salida.sueltos_mods, salida.motivo = {}, [], todos, "no_encaja"
        return salida
    for n, ((col, fil), i) in enumerate(sorted(ocupados.items(), key=lambda par: (par[0][1], par[0][0]))):
        clave = f"leido{n + 1}"
        salida.huecos.append(Hueco(clave, "mod", float(col), float(fil)))
        salida.mods[clave] = i
    salida.segura = True
    return salida


def punto_de(caja, ancho: int | None, alto: int | None, tipo: str) -> Punto | None:
    """El punto de una caja (x, y, ancho, alto) leida en una captura de `ancho` x `alto`."""
    if not caja or not ancho or not alto:
        return None
    x, y, w, h = caja
    return Punto(tipo, (x + w / 2 - ancho / 2) / alto, (y + h) / alto)
