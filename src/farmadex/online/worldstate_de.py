"""Respaldo del estado del mundo: el worldState.php oficial de DE, en crudo.

api.warframestat.us se queda a veces horas publicando un estado viejo (el dia
del parche, o cuando su parser se cae). DE sirve el mismo estado sin procesar en
api.warframe.com/cdn/worldState.php, con ids internos en vez de nombres. Aqui se
convierte ese crudo a la forma que ya entiende `worldstate.analizar`, para que
el resto del programa no sepa de donde vino.

Lo que se cubre: fisuras (con Camino de Acero y tormentas), Baro, incursion,
caza de arcontes, invasiones y los ciclos (Tierra, Cetus, Valle, Cambion,
Zariman, Duviri). Nightwave, alertas, arbitraje y la rotacion del Camino de
Acero no se traducen: el crudo los trae como claves de idioma del juego.

Las formulas de los ciclos son las del parser de WFCD (lib/models/*Cycle.ts),
comprobadas contra una respuesta real de warframestat el 2026-09-22.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..registro_log import obtener

log = obtener("worldstate_de")

URL_DE = "https://api.warframe.com/cdn/worldState.php"

ERAS = {"VoidT1": "Lith", "VoidT2": "Meso", "VoidT3": "Neo", "VoidT4": "Axi", "VoidT5": "Requiem", "VoidT6": "Omnia"}
MISIONES = {
    "MT_EXTERMINATION": "Extermination", "MT_CAPTURE": "Capture", "MT_SURVIVAL": "Survival",
    "MT_DEFENSE": "Defense", "MT_MOBILE_DEFENSE": "Mobile Defense", "MT_INTEL": "Spy",
    "MT_RESCUE": "Rescue", "MT_SABOTAGE": "Sabotage", "MT_TERRITORY": "Interception",
    "MT_EXCAVATE": "Excavation", "MT_ARTIFACT": "Disruption", "MT_ASSASSINATION": "Assassination",
    "MT_HIVE": "Hive", "MT_RETRIEVAL": "Hijack", "MT_ARENA": "Arena", "MT_PVP": "Conclave",
    "MT_ASSAULT": "Assault", "MT_EVACUATION": "Defection", "MT_ALCHEMY": "Alchemy",
    "MT_VOID_CASCADE": "Void Cascade", "MT_CORRUPTION": "Void Flood", "MT_ARMAGEDDON": "Void Armageddon",
    "MT_ENDLESS_EXTERMINATION": "Sanctuary Onslaught", "MT_LANDSCAPE": "Free Roam",
    "MT_RAILJACK": "Skirmish", "MT_VAULTS": "Isolation Vault", "MT_JUNCTION": "Junction",
    "MT_PURSUIT": "Pursuit", "MT_RACE": "Rush", "MT_VOLATILE": "Volatile", "MT_ASCENSION": "Ascension",
}
FACCIONES = {
    "FC_GRINEER": "Grineer", "FC_CORPUS": "Corpus", "FC_INFESTATION": "Infested",
    "FC_OROKIN": "Orokin", "FC_SENTIENT": "Sentient", "FC_NARMER": "Narmer", "FC_MITW": "Murmur",
}
RELEVOS = {
    "MercuryHUB": "Larunda Relay (Mercury)", "VenusHUB": "Vesper Relay (Venus)",
    "EarthHUB": "Strata Relay (Earth)", "SaturnHUB": "Kronia Relay (Saturn)",
    "ErisHUB": "Kuiper Relay (Eris)", "EuropaHUB": "Leonov Relay (Europa)", "PlutoHUB": "Orcus Relay (Pluto)",
}

# Ciclos: constantes del parser de WFCD.
SEGUNDOS_TIERRA = 28800  # 4 h de dia + 4 h de noche
SEGUNDOS_NOCHE_CETUS = 3000  # los ultimos 50 min del ciclo de contratos (150 min)
INICIO_VALLE = datetime(2026, 2, 4, 19, 46, 48, tzinfo=timezone.utc)
SEGUNDOS_VALLE, SEGUNDOS_CALOR_VALLE = 1600, 400
CORPUS_ZARIMAN_MS = 1655182800000
MS_ESTADO_ZARIMAN = 9000000  # 2 h 30 min por bando
ESTADOS_DUVIRI = ("sorrow", "fear", "joy", "anger", "envy")
SEGUNDOS_ESTADO_DUVIRI, DESFASE_DUVIRI = 7200, 52


class ErrorCrudo(RuntimeError):
    """El crudo de DE no tiene la forma esperada."""


def comprobar_crudo(datos) -> dict:
    if not isinstance(datos, dict):
        raise ErrorCrudo("el worldState de DE no es un objeto")
    if "Time" not in datos or "ActiveMissions" not in datos:
        raise ErrorCrudo("el worldState de DE no trae Time ni ActiveMissions")
    return datos


def _fecha(valor) -> datetime | None:
    """{"$date": {"$numberLong": "ms"}} o un epoch en segundos."""
    if isinstance(valor, dict):
        valor = (valor.get("$date") or {}).get("$numberLong") if isinstance(valor.get("$date"), dict) else valor.get("$date")
        try:
            return datetime.fromtimestamp(int(valor) / 1000, timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    try:
        return datetime.fromtimestamp(int(valor), timezone.utc) if valor is not None else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _iso(momento: datetime | None) -> str | None:
    return momento.strftime("%Y-%m-%dT%H:%M:%S.000Z") if momento else None


def _lista(valor) -> list[dict]:
    return [x for x in valor if isinstance(x, dict)] if isinstance(valor, list) else []


def _mision(clave) -> str:
    clave = str(clave or "")
    return MISIONES.get(clave) or clave.removeprefix("MT_").replace("_", " ").title()


def _faccion(clave) -> str:
    clave = str(clave or "")
    return FACCIONES.get(clave) or clave.removeprefix("FC_").replace("_", " ").title()


def _modificador(clave) -> str:
    return str(clave or "").removeprefix("SORTIE_MODIFIER_").replace("_", " ").title()


def _jefe(clave) -> str:
    return str(clave or "").removeprefix("SORTIE_BOSS_").replace("_", " ").title()


def _objeto(ruta) -> str:
    return str(ruta or "").rsplit("/", 1)[-1]


def _premio(bloque) -> dict:
    """AttackerReward / DefenderReward -> {countedItems: [{count, type}], credits}."""
    bloque = bloque if isinstance(bloque, dict) else {}
    salida: dict = {
        "countedItems": [
            {"count": c.get("ItemCount", 1), "type": _objeto(c.get("ItemType")), "key": c.get("ItemType")}
            for c in _lista(bloque.get("countedItems"))
        ]
    }
    if bloque.get("credits"):
        salida["credits"] = bloque["credits"]
    return salida


def _fin_contratos(datos: dict, etiqueta: str) -> datetime | None:
    """Cuando acaba el ciclo de contratos de un sindicato; marca los ciclos de dia/noche."""
    for m in _lista(datos.get("SyndicateMissions")):
        if m.get("Tag") == etiqueta:
            return _fecha(m.get("Expiry"))
    return None


def _ciclo_cetus(fin: datetime | None, ahora: datetime, dia: str, noche: str) -> dict | None:
    if not fin:
        return None
    fin = fin.replace(second=0, microsecond=0)
    faltan = round((fin - ahora).total_seconds())
    es_dia = faltan > SEGUNDOS_NOCHE_CETUS
    restante = faltan - SEGUNDOS_NOCHE_CETUS if es_dia else faltan
    return {"state": dia if es_dia else noche, "expiry": _iso(ahora + timedelta(seconds=restante))}


def _ciclo_tierra(ahora: datetime) -> dict:
    pasado = int(ahora.timestamp()) % SEGUNDOS_TIERRA
    mitad = SEGUNDOS_TIERRA // 2
    return {
        "state": "day" if pasado < mitad else "night",
        "expiry": _iso(ahora + timedelta(seconds=mitad - pasado % mitad)),
    }


def _ciclo_valle(ahora: datetime) -> dict:
    desde = (ahora - INICIO_VALLE).total_seconds() % SEGUNDOS_VALLE
    hasta_vuelta = SEGUNDOS_VALLE - desde
    frio = SEGUNDOS_VALLE - SEGUNDOS_CALOR_VALLE
    calor = hasta_vuelta > frio
    restante = hasta_vuelta - frio if calor else hasta_vuelta
    return {"state": "warm" if calor else "cold", "expiry": _iso(ahora + timedelta(seconds=restante))}


def _ciclo_zariman(fin: datetime | None, ahora: datetime) -> dict | None:
    if not fin:
        return None
    fin = fin.replace(second=0, microsecond=0)
    ciclo = 2 * MS_ESTADO_ZARIMAN
    pasado = (int(fin.timestamp() * 1000) - CORPUS_ZARIMAN_MS) % ciclo
    corpus = ciclo - pasado > MS_ESTADO_ZARIMAN
    return {"state": "corpus" if corpus else "grineer", "expiry": _iso(fin)}


def _ciclo_duviri(ahora: datetime) -> dict:
    delta = (int(ahora.timestamp()) - DESFASE_DUVIRI) % (SEGUNDOS_ESTADO_DUVIRI * len(ESTADOS_DUVIRI))
    indice = delta // SEGUNDOS_ESTADO_DUVIRI
    restante = SEGUNDOS_ESTADO_DUVIRI - delta % SEGUNDOS_ESTADO_DUVIRI
    return {"state": ESTADOS_DUVIRI[indice], "expiry": _iso(ahora + timedelta(seconds=restante))}


def normalizar(crudo: dict, traductor, ahora: datetime | None = None) -> dict:
    """Convierte el worldState.php de DE a la forma de api.warframestat.us."""
    crudo = comprobar_crudo(crudo)
    ahora = ahora or datetime.now(timezone.utc)
    nodo = traductor.clave_nodo
    salida: dict = {"timestamp": _iso(_fecha(crudo.get("Time")))}

    fisuras = []
    for m in _lista(crudo.get("ActiveMissions")):
        info = traductor.datos_nodo(m.get("Node"))
        fisuras.append({
            "activation": _iso(_fecha(m.get("Activation"))),
            "expiry": _iso(_fecha(m.get("Expiry"))),
            "node": nodo(m.get("Node")),
            "missionType": _mision(m.get("MissionType")),
            "enemy": info.get("faccion_en") or "",
            "tier": ERAS.get(str(m.get("Modifier")), str(m.get("Modifier") or "")),
            "isHard": bool(m.get("Hard")),
            "isStorm": False,
        })
    for m in _lista(crudo.get("VoidStorms")):
        info = traductor.datos_nodo(m.get("Node"))
        fisuras.append({
            "activation": _iso(_fecha(m.get("Activation"))),
            "expiry": _iso(_fecha(m.get("Expiry"))),
            "node": nodo(m.get("Node")),
            "missionType": info.get("mision_en") or "Skirmish",
            "enemy": info.get("faccion_en") or "",
            "tier": ERAS.get(str(m.get("ActiveMissionTier")), str(m.get("ActiveMissionTier") or "")),
            "isHard": False,
            "isStorm": True,
        })
    salida["fissures"] = fisuras

    baros = _lista(crudo.get("VoidTraders"))
    if baros:
        b = baros[0]
        salida["voidTrader"] = {
            "activation": _iso(_fecha(b.get("Activation"))),
            "expiry": _iso(_fecha(b.get("Expiry"))),
            "character": "Baro Ki'Teer",
            "location": RELEVOS.get(str(b.get("Node")), str(b.get("Node") or "")),
            "inventory": [
                {
                    "item": _objeto(o.get("ItemType")),
                    "uniqueName": o.get("ItemType"),
                    "ducats": o.get("PrimePrice"),
                    "credits": o.get("RegularPrice"),
                }
                for o in _lista(b.get("Manifest"))
            ],
        }

    def _incursion(clave_crudo: str, clave_variantes: str, arconte: bool) -> dict | None:
        bloques = _lista(crudo.get(clave_crudo))
        if not bloques:
            return None
        s = bloques[0]
        jefe = _jefe(s.get("Boss"))
        return {
            "activation": _iso(_fecha(s.get("Activation"))),
            "expiry": _iso(_fecha(s.get("Expiry"))),
            "boss": f"Archon {jefe}" if arconte else jefe,
            "variants": [
                {
                    "node": nodo(v.get("node")),
                    "missionType": _mision(v.get("missionType")),
                    "modifier": _modificador(v.get("modifierType")),
                }
                for v in _lista(s.get(clave_variantes))
            ],
        }

    if sortie := _incursion("Sorties", "Variants", arconte=False):
        salida["sortie"] = sortie
    if arcontes := _incursion("LiteSorties", "Missions", arconte=True):
        salida["archonHunt"] = arcontes

    salida["invasions"] = [
        {
            "node": nodo(i.get("Node")),
            "desc": "",
            "attacker": {"faction": _faccion(i.get("Faction")), "reward": _premio(i.get("AttackerReward"))},
            "defender": {"faction": _faccion(i.get("DefenderFaction")), "reward": _premio(i.get("DefenderReward"))},
            "completed": bool(i.get("Completed")),
            "completion": 100 * abs(float(i.get("Count") or 0)) / float(i.get("Goal") or 1),
        }
        for i in _lista(crudo.get("Invasions"))
    ]

    salida["earthCycle"] = _ciclo_tierra(ahora)
    if cetus := _ciclo_cetus(_fin_contratos(crudo, "CetusSyndicate"), ahora, "day", "night"):
        salida["cetusCycle"] = cetus
    salida["vallisCycle"] = _ciclo_valle(ahora)
    if cambion := _ciclo_cetus(_fin_contratos(crudo, "EntratiSyndicate"), ahora, "fass", "vome"):
        salida["cambionCycle"] = cambion
    if zariman := _ciclo_zariman(_fin_contratos(crudo, "ZarimanSyndicate"), ahora):
        salida["zarimanCycle"] = zariman
    salida["duviriCycle"] = _ciclo_duviri(ahora)
    return salida
