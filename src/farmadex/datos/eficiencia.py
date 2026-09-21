"""Cuanto se tarda, de media, en conseguir algo en cada sitio.

Las tablas de drops dicen la probabilidad por partida (o por rotacion), pero no
cuanto dura la partida. Un 20 % en una mision de 40 minutos es peor que un 10 %
en una de 10: en esos 40 minutos la segunda da cuatro intentos, un 34 % en total.
Este modulo estima la duracion de cada tipo de mision y convierte cada fuente en
"minutos de media hasta conseguirlo":

    minutos_medios = minutos por intento / probabilidad

que es lo que en realidad le interesa a quien farmea. Las duraciones NO estan en
los datos: son estimaciones para un jugador medio, todas en las tablas de abajo,
y por eso la interfaz las ensena con "~".

Lo que no se puede medir asi no se inventa: un enemigo comun tiene probabilidad
por muerte y depende de cuantos aparezcan, un sindicato cuesta reputacion, una
incursion es una al dia. Esas fuentes se quedan sin estimacion (`minutos_medios`
= None) y `motivo` dice por que.
"""

from __future__ import annotations

import re

# Minutos de cargar la mision, volver al orbitador y entrar a la siguiente. Se paga
# una vez por partida, aparte de lo que dure la mision en si.
CARGA = 1.5

# Misiones con un solo premio al terminar: minutos que tarda un jugador medio en
# completarlas, sin contar la carga. Si tienen rotacion (Rescate, Escaramuza), la
# rotacion la decide la partida y no cuesta mas tiempo.
UNA_VEZ = {
    "Capture": 3.0,
    "Exterminate": 6.0,
    "Extermination": 6.0,
    "Sabotage": 7.0,
    "Assassination": 8.0,
    "Mobile Defense": 8.0,
    "Hijack": 8.0,
    "Rescue": 6.0,
    "Arena": 6.0,
    "Pursuit": 5.0,
    "Rush": 5.0,
    "Skirmish": 12.0,  # Railjack: contando llegar a la nave y volver
    "Volatile": 10.0,
    "Orphix": 12.0,
    "Shrine Defense": 10.0,
    "Ascension": 12.0,
    "Netracells": 15.0,
    # Duviri, "Endless: Tier N" en las tablas: cada tramo del Circuito es un premio.
    "Normal": 5.0,
    "Hard": 5.0,
    "The Perita Rebellion": 10.0,
    "Follie's Hunt": 10.0,
    "Relay": 5.0,
}
DURACION_DESCONOCIDA = 8.0  # un modo que no esta en ninguna tabla

# Misiones sin fin: minutos por rotacion (5 oleadas de Defensa, 5 minutos de
# Supervivencia, una excavadora, una ronda de Intercepcion...). Las recompensas van
# A, A, B, C: la primera C llega en la cuarta rotacion.
SIN_FIN = {
    "Survival": 5.0,
    "Defense": 5.0,
    "Excavation": 2.5,
    "Interception": 3.5,
    "Disruption": 4.0,
    "Defection": 6.0,
    "Infested Salvage": 3.5,
    "Sanctuary Onslaught": 2.5,
    "Alchemy": 3.5,
    "Legacyte Harvest": 5.0,
    "Void Flood": 4.0,
    "Void Cascade": 4.0,
    "Void Armageddon": 4.0,
    "The Circuit": 5.0,
}
# Cuantas rotaciones hay que jugar para ver la primera de cada letra, y cuantas de esa
# letra se llevan al salir en ese momento (A, A, B, C: saliendo tras la segunda A se
# llevan dos A en dos rotaciones).
ROTACIONES_SIN_FIN = {"A": (2, 2), "B": (3, 1), "C": (4, 1)}

# Misiones donde A, B y C caen una vez cada una en la misma partida, en este orden:
# minuto en el que se cobra cada rotacion (Espionaje: una boveda por rotacion;
# Sabotaje con cofres: un cofre por rotacion).
POR_TRAMOS = {
    "Spy": {"A": 3.0, "B": 5.5, "C": 8.0},
    "Caches": {"A": 6.0, "B": 9.0, "C": 12.0},
}

# Modos que no se pueden estimar: Conclave es PvP y depende de la partida.
NO_ESTIMABLES = {"Conclave"}

# Contratos (bounties): minutos de una tanda entera de 5 etapas. Las recompensas
# rotan A, B, C con cada contrato completado, asi que una rotacion dada solo vuelve
# cada tres contratos: cada etapa se cobra una vez por ciclo de tres tandas.
BOUNTY_BASE = 10.0
BOUNTY_ESPECIALES = (
    (re.compile(r"Isolation Vault", re.I), 15.0),
    (re.compile(r"PROFIT-TAKER", re.I), 10.0),
    (re.compile(r"Level\s+100\b", re.I), 15.0),
    (re.compile(r"Level\s+\d+\s*-\s*(1\d|2\d|30)\b", re.I), 8.0),  # hasta nivel 30
)
BOUNTY_CICLO = 3

# Recompensas especiales (transientRewards): (clase, dato). Las que no estan aqui se
# tratan como una partida suelta de DURACION_TRANSITORIA minutos.
TRANSITORIAS = {
    "Arbitrations": ("sin_fin", 10.0),  # rotaciones de 10 minutos / 10 oleadas
    "Granum Void": ("tramos", {"A": 2.0, "B": 3.0, "C": 4.0}),
    "Extended Granum Void": ("tramos", {"A": 2.0, "B": 3.0, "C": 4.0}),
    "Nightmare Granum Void": ("tramos", {"A": 2.0, "B": 3.0, "C": 4.0}),
    "Nightmare Mode Rewards": ("una_vez", 8.0),
    "Derelict Vault": ("una_vez", 10.0),
    "Phorid Assassination": ("una_vez", 8.0),
    "Razorback": ("una_vez", 10.0),
    "Fomorian Sabotage": ("una_vez", 10.0),
    "Duviri Full Experience": ("una_vez", 40.0),
    "Duviri Circuit": ("una_vez", 20.0),
}
DURACION_TRANSITORIA = 10.0
RE_VOID_STORM = re.compile(r"^Void Storm", re.I)
# Archimedea (Deep, Temporal): una tanda a la semana. Estimarla como una partida
# suelta de 10 minutos la ponia por delante de cualquier mision de verdad.
RE_SEMANAL = re.compile(r"Archimedea", re.I)
# Contenido que solo existe durante un evento (Ghoul Purge, Plague Star...). Las
# tablas de drops lo mantienen todo el ano, y medido como un contrato normal salia
# como la ruta principal de la Nitaina aunque la mayor parte del ano no se puede hacer.
RE_EVENTO = re.compile(r"Ghoul Bounty|Plague Star|Galleon Of Ghouls", re.I)

# Jefes de asesinato: donde estan y si sueltan al morir el recurso del planeta.
# Los datos no traen el nodo del jefe (ni warframe-items ni las tablas de drops de
# WFCD, ni solNodes), asi que esta tabla es a mano; el porcentaje de "Region
# Resource" si sale de resourceByAvatar.json (tomado el 2026-09-21). Las variantes
# (Raptor Mt, Hyena Pb...) son el mismo combate.
JEFES: dict[str, tuple[str, float | None]] = {
    "Captain Vor": ("Tolstoj", 97.42),
    "Jackal": ("Fossa", 97.42),
    "Councilor Vay Hek": ("Oro", 97.42),
    "Lt Lech Kril": ("War", 97.42),
    "The Sergeant": ("Iliad", 97.42),
    "Alad V": ("Themisto", 97.42),
    "Raptor": ("Naamah", 50.0),
    "Raptor Mt": ("Naamah", None),
    "Raptor Ns": ("Naamah", None),
    "Raptor Rv": ("Naamah", None),
    "Raptor Rx": ("Naamah", None),
    "General Sargas Ruk": ("Tethys", 97.42),
    "Tyl Regor": ("Titania", 97.42),
    "Hyena Ng": ("Psamathe", 97.42),
    "Hyena Pb": ("Psamathe", 97.42),
    "Hyena Th": ("Psamathe", 97.42),
    "Hyena Ln2": ("Psamathe", 97.42),
    "Ambulas": ("Hades", 48.71),
    "Kela De Thaym": ("Merrow", 97.42),
    "Lephantis": ("Magnacidium", 97.42),
    "Zealoid Prelate": ("Effervo", 4.87),
    "Ropalolyst": ("The Ropalolyst", None),
    "H-09 Efervon Tank": ("Assassinate: H-09 Tank", None),
}

# El "Region Resource" que suelta un jefe es el recurso raro de su planeta (Alad V
# suelta Sensores neuronales, no Placas de aleacion aunque tambien caigan en Jupiter).
# Los datos no dicen cual es el raro de cada planeta: tabla a mano segun la wiki, solo
# con los planetas de los que se esta seguro. Venus y Sedna quedan fuera a proposito.
RECURSO_RARO = {
    "Mercury": "Morphics",
    "Earth": "Neurodes",
    "Mars": "Gallium",
    "Phobos": "Morphics",
    "Ceres": "Orokin Cell",
    "Jupiter": "Neural Sensors",
    "Europa": "Control Module",
    "Saturn": "Orokin Cell",
    "Uranus": "Gallium",
    "Neptune": "Control Module",
    "Pluto": "Morphics",
    "Eris": "Neurodes",
    "Deimos": "Neurodes",
}


def duracion_bounty(origen_texto: str) -> float:
    for patron, minutos in BOUNTY_ESPECIALES:
        if patron.search(origen_texto or ""):
            return minutos
    return BOUNTY_BASE


def _sin_fin(minutos_rotacion: float, rotacion: str | None) -> float:
    """Minutos por oportunidad en una mision sin fin, saliendo en el mejor momento."""
    rotaciones, premios = ROTACIONES_SIN_FIN.get((rotacion or "").upper(), (2, 1))
    return (rotaciones * minutos_rotacion + CARGA) / premios


def _tramos(minutos: dict[str, float], rotacion: str | None) -> float:
    clave = (rotacion or "").upper()
    return (minutos.get(clave) or max(minutos.values())) + CARGA


def minutos_por_intento(f: dict) -> tuple[float | None, str]:
    """Minutos que cuesta cada oportunidad de que salga el objeto, y un motivo.

    El motivo es 'estimado' cuando hay numero; si no, dice por que no lo hay:
    'por_muerte' (enemigo comun), 'reputacion', 'diaria' (incursion), 'semanal'
    (Archimedea), 'evento' (solo durante un evento), 'pvp' o 'desconocido'.
    """
    tipo = f.get("tipo")
    rotacion = f.get("rotacion")
    if tipo == "enemigo":
        if f.get("jefe"):
            return UNA_VEZ["Assassination"] + CARGA, "estimado"
        return None, "por_muerte"
    if tipo == "sindicato":
        return None, "reputacion"
    if tipo == "sortie":
        return None, "diaria"
    if RE_EVENTO.search(f.get("origen_texto") or ""):
        return None, "evento"
    if tipo == "bounty":
        return BOUNTY_CICLO * (duracion_bounty(f.get("origen_texto") or "") + CARGA), "estimado"
    if tipo == "transitoria":
        origen = f.get("origen_texto") or ""
        if RE_VOID_STORM.match(origen):
            return UNA_VEZ["Skirmish"] + CARGA, "estimado"
        if RE_SEMANAL.search(origen):
            return None, "semanal"
        clase, dato = TRANSITORIAS.get(origen, ("una_vez", DURACION_TRANSITORIA))
        if clase == "sin_fin":
            return _sin_fin(dato, rotacion), "estimado"
        if clase == "tramos":
            return _tramos(dato, rotacion), "estimado"
        return dato + CARGA, "estimado"
    if tipo in ("mision", "llave"):
        modo = f.get("modo") or f.get("mision_en") or ""
        if modo in NO_ESTIMABLES:
            return None, "pvp"
        if modo in POR_TRAMOS:
            return _tramos(POR_TRAMOS[modo], rotacion), "estimado"
        if modo in SIN_FIN:
            return _sin_fin(SIN_FIN[modo], rotacion), "estimado"
        return UNA_VEZ.get(modo, DURACION_DESCONOCIDA) + CARGA, "estimado"
    return None, "desconocido"


def minutos_medios(minutos_intento: float | None, probabilidad: float | None) -> float | None:
    """Tiempo medio hasta que salga: minutos por intento entre la probabilidad (en %)."""
    if minutos_intento is None or not probabilidad or probabilidad <= 0:
        return None
    # Las tablas traen mas del 100 % en cajas que sueltan varias unidades; hasta la
    # primera no se tarda menos de un intento.
    return round(minutos_intento / (min(float(probabilidad), 100.0) / 100), 1)


def estimar(f: dict) -> None:
    """Anade a la fila `minutos_intento`, `minutos_medios` y `motivo`."""
    intento, motivo = minutos_por_intento(f)
    f["minutos_intento"] = intento
    f["minutos_medios"] = minutos_medios(intento, f.get("probabilidad_efectiva", f.get("probabilidad")))
    f["motivo"] = motivo


def clave_orden(f: dict) -> tuple:
    """Lo estimado, de menos a mas tiempo; lo que no se puede estimar, detras."""
    minutos = f.get("minutos_medios")
    return (0, minutos) if minutos is not None else (1, 0.0)


def texto_minutos(minutos: float | None) -> str:
    """'~35 min', '~2.5 h' o '~3 d'; vacio si no hay estimacion."""
    if minutos is None:
        return ""
    if minutos < 90:
        return f"~{round(minutos):d} min"
    horas = minutos / 60
    if horas < 48:
        return f"~{horas:.1f} h".replace(".0 h", " h")
    return f"~{horas / 24:.0f} d"
