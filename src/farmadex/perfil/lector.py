"""Lectura y validacion del JSON de perfil que el jugador descarga a mano.

El fichero sale de `api.warframe.com/cdn/getProfileViewingData.php?playerId=...`,
abierto por el usuario en su navegador con su propia sesion. Farmadex solo lee el
fichero que el le da: aqui no hay peticiones a DE ni credenciales.

Estructura (confirmada contra los fixtures publicos de @wfcd/profile-parser):
cinco claves de primer nivel, `Results` (lista con el perfil), `Stats`,
`TechProjects`, `XpComponents` y `XpCacheExpiryDate`. Todo lo que no sea
`Results[0].DisplayName`, `PlayerLevel` y `LoadOutInventory.XPInfo` se trata como
opcional: DE no documenta el formato y ya lo ha cambiado varias veces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Un perfil real pesa 600-625 KB. Con 50 MB sobra y evitamos cargar cualquier cosa.
TAMANO_MAXIMO = 50 * 1024 * 1024


class PerfilInvalido(ValueError):
    """El fichero no es un perfil de Warframe legible."""


@dataclass(frozen=True)
class EntradaXP:
    item_type: str  # uniqueName `/Lotus/...`, el mismo que usa el catalogo
    xp: int


@dataclass(frozen=True)
class NodoJugado:
    tag: str  # SolNode123, ClanNode4, SettlementNode10, junctions, hubs...
    completes: int
    # Tier 1 = Camino de Acero. En los fixtures cada Tag aparece una sola vez, con
    # el Tier mas alto alcanzado; se asume que Tier 1 implica el nodo normal hecho.
    camino_acero: bool


@dataclass(frozen=True)
class Sindicato:
    tag: str  # SteelMeridianSyndicate, CetusSyndicate...
    standing: int
    titulo: int  # rango dentro del sindicato; negativo si esta en contra


@dataclass
class Perfil:
    nombre: str
    account_id: str | None
    rango: int  # rango de maestria (PlayerLevel)
    creado: datetime | None
    clan: str | None
    clan_nivel: int | None
    plataformas: list[str]
    operador_desbloqueado: bool | None
    xp: list[EntradaXP]
    nodos: list[NodoJugado]
    intrinsecos: dict[str, int]  # PlayerSkills: LPS_PILOTING, LPS_DRIFT_RIDING...
    sindicatos: list[Sindicato]
    reputacion_diaria: dict[str, int]  # DailyAffiliation* y DailyFocus
    desafios: dict[str, int]  # ChallengeProgress: nombre -> progreso
    estadisticas: dict[str, int | float | str]  # solo los contadores escalares de Stats
    estadisticas_listas: dict[str, list] = field(default_factory=dict)  # Weapons, Enemies...
    cache_expira: datetime | None = None
    # "json" (fichero de DE: sustituye todo) u "ocr" (pantallas del juego: se fusiona).
    origen: str = "json"

    @property
    def xp_por_item(self) -> dict[str, int]:
        return {e.item_type: e.xp for e in self.xp}


def cargar(ruta: Path | str) -> Perfil:
    """Lee el fichero y devuelve el perfil. Lanza PerfilInvalido si no sirve."""
    ruta = Path(ruta)
    if not ruta.is_file():
        raise PerfilInvalido(f"No existe el fichero {ruta}")
    tamano = ruta.stat().st_size
    if tamano == 0:
        raise PerfilInvalido("El fichero esta vacio")
    if tamano > TAMANO_MAXIMO:
        raise PerfilInvalido(f"El fichero pesa {tamano // 1024} KB; un perfil ronda los 600 KB")
    try:
        texto = ruta.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise PerfilInvalido("El fichero no es texto UTF-8; no parece un JSON de perfil") from e
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as e:
        raise PerfilInvalido(
            f"El JSON esta recortado o corrupto (linea {e.lineno}, columna {e.colno}). "
            "Vuelve a guardar la pagina completa desde el navegador"
        ) from e
    return interpretar(datos)


def interpretar(datos: object) -> Perfil:
    """Convierte el JSON ya decodificado en un Perfil, validando lo imprescindible."""
    if not isinstance(datos, dict):
        raise PerfilInvalido("El JSON no es un objeto; no es un perfil de jugador")
    resultados = datos.get("Results")
    if not isinstance(resultados, list) or not resultados or not isinstance(resultados[0], dict):
        pistas = ", ".join(sorted(str(k) for k in datos)[:6])
        raise PerfilInvalido(
            f"Falta la clave 'Results' con el perfil (claves encontradas: {pistas or 'ninguna'}). "
            "Este JSON no viene de getProfileViewingData.php"
        )
    r = resultados[0]

    nombre = _limpiar_nombre(r.get("DisplayName"))
    if not nombre:
        raise PerfilInvalido("El perfil no tiene 'DisplayName'")
    rango = _entero(r.get("PlayerLevel"))
    if rango is None:
        raise PerfilInvalido("El perfil no tiene 'PlayerLevel' (rango de maestria)")

    inventario = r.get("LoadOutInventory")
    if not isinstance(inventario, dict) or not isinstance(inventario.get("XPInfo"), list):
        raise PerfilInvalido("El perfil no tiene 'LoadOutInventory.XPInfo' (experiencia por objeto)")

    xp: list[EntradaXP] = []
    for e in inventario["XPInfo"]:
        if not isinstance(e, dict):
            continue
        item = e.get("ItemType")
        valor = _entero(e.get("XP"))
        if isinstance(item, str) and item and valor is not None:
            xp.append(EntradaXP(item, valor))

    nodos: list[NodoJugado] = []
    for m in r.get("Missions") or []:
        if not isinstance(m, dict) or not isinstance(m.get("Tag"), str):
            continue
        nodos.append(
            NodoJugado(m["Tag"], _entero(m.get("Completes")) or 0, _entero(m.get("Tier")) == 1)
        )

    intrinsecos = {
        str(k): v for k, v in (r.get("PlayerSkills") or {}).items() if _entero(v) is not None
    }

    sindicatos: list[Sindicato] = []
    for a in r.get("Affiliations") or []:
        if isinstance(a, dict) and isinstance(a.get("Tag"), str):
            sindicatos.append(
                Sindicato(a["Tag"], _entero(a.get("Standing")) or 0, _entero(a.get("Title")) or 0)
            )

    reputacion_diaria = {
        k: _entero(v)
        for k, v in r.items()
        if (k.startswith("DailyAffiliation") or k == "DailyFocus") and _entero(v) is not None
    }

    desafios = {}
    for d in r.get("ChallengeProgress") or []:
        if isinstance(d, dict) and isinstance(d.get("Name"), str):
            desafios[d["Name"]] = _entero(d.get("Progress")) or 0

    escalares: dict[str, int | float | str] = {}
    listas: dict[str, list] = {}
    stats = datos.get("Stats")
    if isinstance(stats, dict):
        for k, v in stats.items():
            if isinstance(v, (int, float, str)) and not isinstance(v, bool):
                escalares[str(k)] = v
            elif isinstance(v, list):
                listas[str(k)] = v

    plataformas = [
        _limpiar_nombre(p) for p in (r.get("PlatformNames") or []) if isinstance(p, str)
    ]

    return Perfil(
        nombre=nombre,
        account_id=_oid(r.get("AccountId")),
        rango=rango,
        creado=_fecha(r.get("Created")),
        clan=_texto(r.get("GuildName")),
        clan_nivel=_entero(r.get("GuildTier")),
        plataformas=[p for p in plataformas if p],
        operador_desbloqueado=(
            bool(r["UnlockedOperator"]) if "UnlockedOperator" in r else None
        ),
        xp=xp,
        nodos=nodos,
        intrinsecos=intrinsecos,
        sindicatos=sindicatos,
        reputacion_diaria=reputacion_diaria,
        desafios=desafios,
        estadisticas=escalares,
        estadisticas_listas=listas,
        cache_expira=_fecha(datos.get("XpCacheExpiryDate")),
    )


# --- ayudas de formato -----------------------------------------------------------


def _limpiar_nombre(valor) -> str:
    """Quita el glifo de plataforma (U+E000-U+F8FF) que DE pega al final del nombre."""
    if not isinstance(valor, str):
        return ""
    return "".join(c for c in valor if not 0xE000 <= ord(c) <= 0xF8FF).strip()


def _texto(valor) -> str | None:
    if isinstance(valor, str):
        valor = valor.strip()
        return valor or None
    return None


def _entero(valor) -> int | None:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float) and valor.is_integer():
        return int(valor)
    if isinstance(valor, str) and valor.strip().lstrip("-").isdigit():
        return int(valor)
    if isinstance(valor, dict):  # {"$numberLong": "123"} o {"$numberInt": "5"}
        for clave in ("$numberLong", "$numberInt"):
            if clave in valor:
                return _entero(valor[clave])
    return None


def _oid(valor) -> str | None:
    """AccountId viene como {"$oid": "24 hex"}; se acepta tambien la cadena suelta."""
    if isinstance(valor, dict):
        valor = valor.get("$oid")
    return _texto(valor)


def _fecha(valor) -> datetime | None:
    """Fechas en formato Mongo extendido: {"$date": {"$numberLong": "ms"}} o {"$date": ms}."""
    if isinstance(valor, dict) and "$date" in valor:
        valor = valor["$date"]
    ms = _entero(valor)
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
