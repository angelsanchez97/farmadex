"""Estado del mundo de Warframe (api.warframestat.us), traducido al espanol.

El parseo es defensivo a proposito: una clave que cambie de forma no puede
dejar la pestana entera en blanco, asi que cada bloque va por separado y lo que
falle se registra y se omite.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer, Signal

from ..config import PLATAFORMA
from ..idiomas import t
from ..registro_log import obtener
from .http import Cliente

log = obtener("worldstate")

# Sin "?language=": la API lo retiro y con ese parametro responde 404 siempre.
# Los nombres se traducen aqui con el indice y el glosario, que es mas fiable.
URL = "https://api.warframestat.us/{plataforma}"
RE_NODO = re.compile(r"^(.*?)\s*\((.*)\)\s*$")
# Pasados estos minutos desde el 'timestamp' de la respuesta, el estado del mundo se
# da por viejo: el dia del parche la API sigue contestando, pero con lo de antes.
MINUTOS_VIEJO = 15
ERAS_CONOCIDAS = ("Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia")
_eras_avisadas: set[str] = set()


# -- modelos -------------------------------------------------------------


@dataclass
class Fisura:
    era: str
    nodo: str
    mision: str
    enemigo: str
    expira: datetime | None
    acero: bool = False
    tormenta: bool = False


@dataclass
class Ciclo:
    nombre: str
    estado: str
    expira: datetime | None


@dataclass
class Invasion:
    nodo: str
    descripcion: str
    atacante: str
    defensor: str
    recompensas: str
    porcentaje: float


@dataclass
class Recompensa:
    texto: str
    expira: datetime | None = None
    detalle: str = ""


@dataclass
class ObjetoBaro:
    """Una linea del inventario de Baro, casada con el indice cuando se puede."""

    nombre: str  # como lo manda la API (ingles)
    unique_name: str  # ya sin el prefijo /Lotus/StoreItems/, como en el indice
    ducados: int | None
    creditos: int | None
    item_id: int | None = None
    nombre_es: str = ""
    categoria: str = ""
    market_slug: str | None = None
    # Lo rellena `marcar_objetivos`: el objeto es (o forma parte de) un objetivo.
    objetivo: bool = False

    @property
    def nombre_mostrar(self) -> str:
        return self.nombre_es or self.nombre

    @property
    def en_indice(self) -> bool:
        return self.item_id is not None


@dataclass
class Baro:
    personaje: str
    lugar: str  # ya traducido: "Larunda, Mercurio"
    activo: bool
    llegada: datetime | None
    expira: datetime | None
    inventario: list[ObjetoBaro] = field(default_factory=list)

    def cuenta_atras(self, ahora: datetime | None = None) -> str:
        """Lo que le queda si esta, o lo que falta para que llegue."""
        return restante(self.expira if self.activo else self.llegada, ahora)

    def cabecera(self, ahora: datetime | None = None) -> str:
        tiempo = self.cuenta_atras(ahora)
        if self.activo:
            texto = t("{personaje} en {lugar}", personaje=self.personaje, lugar=self.lugar)
            return f"{texto} · {t('se va en {tiempo}', tiempo=tiempo)}" if tiempo else texto
        if tiempo and tiempo != "terminado":
            texto = t("{personaje} llega en {tiempo}", personaje=self.personaje, tiempo=tiempo)
            return f"{texto} ({self.lugar})" if self.lugar else texto
        return t("{personaje} todavia no ha llegado", personaje=self.personaje)

    def objetivos(self) -> list[ObjetoBaro]:
        return [o for o in self.inventario if o.objetivo]


def marcar_objetivos(baro: Baro | None, unique_names) -> list[ObjetoBaro]:
    """Marca que objetos de Baro cubren un objetivo del usuario y los devuelve.

    `unique_names` son los `item_unique_name` de la tabla de objetivos (los
    mismos unique_name del indice).
    """
    if baro is None:
        return []
    buscados = {_sin_tienda(u) for u in unique_names if u}
    for o in baro.inventario:
        o.objetivo = o.unique_name in buscados
    return baro.objetivos()


def _sin_tienda(unique_name: str) -> str:
    # La API manda la referencia de la tienda; el indice guarda la del objeto.
    return (unique_name or "").replace("/Lotus/StoreItems/", "/Lotus/", 1)


@dataclass
class Mundo:
    momento: datetime | None = None
    fisuras: list[Fisura] = field(default_factory=list)
    ciclos: list[Ciclo] = field(default_factory=list)
    invasiones: list[Invasion] = field(default_factory=list)
    alertas: list[Recompensa] = field(default_factory=list)
    arbitracion: Recompensa | None = None
    sortie: list[Recompensa] = field(default_factory=list)
    arcontes: list[Recompensa] = field(default_factory=list)
    nightwave: list[Recompensa] = field(default_factory=list)
    baro: list[Recompensa] = field(default_factory=list)
    baro_cabecera: str = ""
    baro_detalle: Baro | None = None
    acero: list[Recompensa] = field(default_factory=list)
    error: str = ""
    # De donde salio: "warframestat" (la API de siempre) o "de" (el crudo oficial, de respaldo).
    fuente: str = "warframestat"
    # Claves de primer nivel que la API manda y este codigo no conoce (para el log).
    claves_nuevas: list[str] = field(default_factory=list)

    def minutos_de_antiguedad(self, ahora: datetime | None = None) -> float | None:
        if not self.momento:
            return None
        ahora = ahora or datetime.now(timezone.utc)
        return max(0.0, (ahora - self.momento).total_seconds() / 60)

    def esta_viejo(self, ahora: datetime | None = None) -> bool:
        minutos = self.minutos_de_antiguedad(ahora)
        return minutos is not None and minutos > MINUTOS_VIEJO


# -- traduccion -----------------------------------------------------------


class Traductor:
    """Convierte 'Oceanum (Pluto)' en 'Oceanum, Pluton' usando el indice."""

    def __init__(self, con: sqlite3.Connection | None):
        self.con = con
        self.nodos: dict[tuple[str, str], tuple[str, str]] = {}
        # Por id de DE ("SolNode48"): lo que hace falta para leer el worldState crudo.
        self.por_id: dict[str, dict] = {}
        self.glosario: dict[tuple[str, str], str] = {}
        if con is None:
            return
        try:
            for unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_en, faccion_en in con.execute(
                "SELECT unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_en, faccion_en FROM nodos"
            ):
                self.nodos[(nombre_en, planeta_en)] = (
                    nombre_es or nombre_en,
                    planeta_es or planeta_en,
                )
                if unique_name:
                    self.por_id[unique_name] = {
                        "nombre_en": nombre_en, "planeta_en": planeta_en,
                        "mision_en": mision_en, "faccion_en": faccion_en,
                    }
            for dominio, en, es in con.execute("SELECT dominio, en, es FROM glosario"):
                self.glosario[(dominio, en)] = es
        except sqlite3.Error as e:  # pragma: no cover - indice a medio construir
            log.warning("Sin traducciones para el mundo: %s", e)

    def termino(self, dominio: str, en: str | None) -> str:
        if not en:
            return ""
        return self.glosario.get((dominio, en), en)

    def datos_nodo(self, unique_name) -> dict:
        return self.por_id.get(str(unique_name or ""), {})

    def clave_nodo(self, unique_name) -> str:
        """'SolNode48' -> 'Hydron (Sedna)', la forma que usa warframestat; si no se conoce, el id."""
        info = self.datos_nodo(unique_name)
        if info.get("nombre_en") and info.get("planeta_en"):
            return f"{info['nombre_en']} ({info['planeta_en']})"
        return str(unique_name or "")

    def nodo(self, texto: str | None) -> str:
        if not texto:
            return ""
        m = RE_NODO.match(texto)
        if not m:
            return texto
        nodo, planeta = m.group(1), m.group(2)
        traducido = self.nodos.get((nodo, planeta))
        if traducido:
            return f"{traducido[0]}, {traducido[1]}"
        return f"{nodo}, {self.termino('planeta', planeta)}"

    def objeto(self, unique_name: str, nombre_en: str) -> dict | None:
        """Busca un objeto del indice por unique_name y, si no, por nombre en ingles."""
        if self.con is None:
            return None
        sql = "SELECT id, nombre_es, categoria, market_slug, ducados FROM items WHERE {} LIMIT 1"
        try:
            fila = None
            if unique_name:
                fila = self.con.execute(sql.format("unique_name = ?"), (unique_name,)).fetchone()
            if not fila and nombre_en:
                fila = self.con.execute(sql.format("nombre_en = ?"), (nombre_en,)).fetchone()
        except sqlite3.Error as e:  # pragma: no cover - indice a medio construir
            log.warning("No se pudo casar '%s' con el indice: %s", nombre_en, e)
            return None
        if not fila:
            return None
        return dict(zip(("id", "nombre_es", "categoria", "market_slug", "ducados"), fila))


# -- parseo ----------------------------------------------------------------


def _momento(texto) -> datetime | None:
    if not texto or not isinstance(texto, str):
        return None
    try:
        momento = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Sin zona horaria no se puede comparar con "ahora": se asume UTC, que es lo que manda la API.
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def restante(expira: datetime | None, ahora: datetime | None = None) -> str:
    """'2h 5m' de lo que queda; vacio si ya paso o no se sabe."""
    if not expira:
        return ""
    ahora = ahora or datetime.now(timezone.utc)
    segundos = int((expira - ahora).total_seconds())
    if segundos <= 0:
        return "terminado"
    dias, resto = divmod(segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, segs = divmod(resto, 60)
    if dias:
        return f"{dias}d {horas}h"
    if horas:
        return f"{horas}h {minutos}m"
    if minutos:
        return f"{minutos}m {segs}s"
    return f"{segs}s"


def _bandera(valor) -> bool | None:
    """Un campo booleano de la API. Presente pero nulo (o de otro tipo) es "no se sabe".

    El 2026-09-22 warframestat mando todas las fisuras con "active": null y
    "expired": null; leerlos con bool() vaciaba la pestana entera.
    """
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int) and valor in (0, 1):
        return bool(valor)
    if isinstance(valor, str) and valor.strip().lower() in ("true", "false"):
        return valor.strip().lower() == "true"
    return None


def _dic(valor) -> dict:
    """La API ha llegado a mandar cadenas donde se esperaba un objeto."""
    return valor if isinstance(valor, dict) else {}


def _dicts(valor) -> list[dict]:
    """Solo los elementos que son objetos; una lista de cadenas no tumba el bloque."""
    return [x for x in valor if isinstance(x, dict)] if isinstance(valor, list) else []


def _faccion(bando) -> str:
    bando = _dic(bando)
    return bando.get("factionKey") or bando.get("faction") or ""


def _premio(recompensa) -> str:
    """El texto de una recompensa; la API no siempre trae 'asString'."""
    recompensa = _dic(recompensa)
    if not recompensa:
        return ""
    if recompensa.get("asString"):
        return recompensa["asString"]
    partes = [str(x) for x in (recompensa.get("items") or [])]
    partes += [
        f"{c.get('count', 1)}x {c.get('type') or c.get('key') or ''}".strip()
        for c in _dicts(recompensa.get("countedItems"))
    ]
    if recompensa.get("credits"):
        partes.append(t("{n} creditos", n=recompensa["credits"]))
    return " + ".join(p for p in partes if p)


def _bloque(nombre: str, funcion, *args):
    """Ejecuta el parseo de una clave; si revienta, devuelve vacio y lo anota."""
    try:
        return funcion(*args)
    except Exception:  # noqa: BLE001 - una clave rota no tumba el resto
        log.exception("No se pudo leer el bloque '%s' del estado del mundo", nombre)
        return None


# Claves de primer nivel que se leen o se conocen; el resto se anota como novedad.
CLAVES_CONOCIDAS = frozenset({
    "timestamp", "fissures", "invasions", "alerts", "arbitration", "sortie", "archonHunt",
    "nightwave", "voidTrader", "steelPath", "news", "events", "syndicateMissions",
    "flashSales", "globalUpgrades", "dailyDeals", "simaris", "conclaveChallenges",
    "persistentEnemies", "kuva", "constructionProgress", "vaultTrader", "voidTraders",
    "sentientOutposts", "deepArchimedea", "temporalArchimedea", "calendar", "kinepage",
    "duviriCycle", "earthCycle", "cetusCycle", "vallisCycle", "cambionCycle", "zarimanCycle",
})

# Ciclos que se conocen con su nombre; los demas (*Cycle) se ensenan con la clave limpia.
CICLOS = {
    "earthCycle": "Tierra",
    "cetusCycle": "Cetus",
    "vallisCycle": "Valle del Orbe",
    "cambionCycle": "Llanuras de Cambion",
    "zarimanCycle": "Zariman",
    "duviriCycle": "Duviri",
}
ESTADOS_CICLO = {
    "day": "dia",
    "night": "noche",
    "warm": "calor",
    "cold": "frio",
    "fass": "Fass",
    "vome": "Vome",
    "grineer": "Grineer",
    "corpus": "Corpus",
    "joy": "alegria",
    "anger": "ira",
    "envy": "envidia",
    "sorrow": "tristeza",
    "fear": "miedo",
}


def _nombre_ciclo(clave: str) -> str:
    """'hollvaniaCycle' -> 'Hollvania': algo legible mientras no tenga traduccion."""
    base = clave[: -len("Cycle")] if clave.endswith("Cycle") else clave
    return base[:1].upper() + base[1:]


def _avisar_era(era: str) -> None:
    if era and era not in ERAS_CONOCIDAS and era not in _eras_avisadas:
        _eras_avisadas.add(era)
        log.warning("Era de fisura desconocida en el estado del mundo: %r (se ensena igual)", era)


class ErrorMundo(RuntimeError):
    """La API contesto, pero con un error en vez de con el estado del mundo."""


def comprobar_respuesta(datos) -> dict:
    """Distingue un estado del mundo de verdad de un error disfrazado de JSON.

    warframestat.us devuelve 404 con cuerpo {"message": "WorldState Not Found",
    "error": ..., "statusCode": 404} cuando no consigue leer el estado de DE, y
    pasa cada dos por tres. Sin esta comprobacion la pestana se quedaba vacia y
    parecia que no hay fisuras, que es peor que decir que no se ha podido mirar.
    """
    if not isinstance(datos, dict):
        raise ErrorMundo("la respuesta no es un objeto")
    if datos.get("error") or datos.get("statusCode"):
        raise ErrorMundo(str(datos.get("message") or datos.get("error")))
    if "timestamp" not in datos and "fissures" not in datos:
        raise ErrorMundo("la respuesta no trae el estado del mundo")
    return datos


def analizar(datos: dict, traductor: Traductor) -> Mundo:
    if not isinstance(datos, dict):
        log.warning("El estado del mundo no es un objeto JSON (%s)", type(datos).__name__)
        datos = {}
    mundo = Mundo(momento=_momento(datos.get("timestamp")))
    mundo.claves_nuevas = sorted(k for k in datos if k not in CLAVES_CONOCIDAS)
    if mundo.claves_nuevas:
        log.info("Claves nuevas en el estado del mundo (se ignoran): %s", mundo.claves_nuevas)

    def fisuras():
        salida = []
        for f in _dicts(datos.get("fissures")):
            # "expired" nulo no es "abierta": se decide por la fecha de fin (lo hace la
            # pestana, con su reloj, para que la lista no se congele entre consultas).
            if _bandera(f.get("expired")) is True:
                continue
            _avisar_era(str(f.get("tier") or ""))
            nodo = str(f.get("nodeKey") or f.get("node") or "")
            tormenta = _bandera(f.get("isStorm"))
            if tormenta is None:
                # Nodos de Railjack; se mira el nombre y la clave, que no siempre coinciden.
                crudo = f"{f.get('node') or ''} {f.get('nodeKey') or ''}"
                tormenta = "Proxima" in crudo or "Veil" in crudo
            salida.append(
                Fisura(
                    era=str(f.get("tier") or ""),
                    nodo=traductor.nodo(nodo),
                    mision=traductor.termino("mision", f.get("missionTypeKey") or f.get("missionType")),
                    enemigo=traductor.termino("faccion", f.get("enemyKey") or f.get("enemy")),
                    expira=_momento(f.get("expiry")),
                    acero=_bandera(f.get("isHard")) or False,
                    tormenta=tormenta,
                )
            )
        orden = {"Lith": 0, "Meso": 1, "Neo": 2, "Axi": 3, "Requiem": 4, "Omnia": 5}
        return sorted(salida, key=lambda x: (orden.get(x.era, 9), x.acero, x.nodo))

    def ciclos():
        # Los conocidos por su nombre y, detras, cualquier "*Cycle" nuevo que traiga la API.
        claves = list(CICLOS) + sorted(
            k for k in datos if k.endswith("Cycle") and k not in CICLOS and isinstance(datos[k], dict)
        )
        salida = []
        for clave in claves:
            c = _dic(datos.get(clave))
            estado = c.get("state") or c.get("active") or ""
            if not estado or not isinstance(estado, (str, int, float)):
                continue
            etiqueta = t(CICLOS[clave]) if clave in CICLOS else _nombre_ciclo(clave)
            estado_es = ESTADOS_CICLO.get(str(estado).lower())
            salida.append(
                Ciclo(etiqueta, t(estado_es) if estado_es else str(estado), _momento(c.get("expiry")))
            )
        return salida

    def invasiones():
        salida = []
        for i in _dicts(datos.get("invasions")):
            completada = _bandera(i.get("completed"))
            if completada is None:
                try:
                    completada = abs(float(i.get("completion") or 0)) >= 100
                except (TypeError, ValueError):
                    completada = False
            if completada:
                continue
            premios = []
            for bando in ("attacker", "defender"):
                premio = _premio(_dic(i.get(bando)).get("reward"))
                if premio:
                    premios.append(premio)
            salida.append(
                Invasion(
                    nodo=traductor.nodo(i.get("nodeKey") or i.get("node")),
                    descripcion=i.get("desc") or "",
                    atacante=traductor.termino("faccion", _faccion(i.get("attacker"))),
                    defensor=traductor.termino("faccion", _faccion(i.get("defender"))),
                    recompensas=" / ".join(premios),
                    porcentaje=float(i.get("completion") or 0),
                )
            )
        return salida

    def alertas():
        salida = []
        for a in _dicts(datos.get("alerts")):
            mision = _dic(a.get("mission"))
            premio = _premio(mision.get("reward"))
            salida.append(
                Recompensa(
                    texto=f"{traductor.nodo(mision.get('node'))} - {premio}".strip(" -"),
                    expira=_momento(a.get("expiry")),
                    detalle=traductor.termino("mision", mision.get("typeKey") or mision.get("type")),
                )
            )
        return salida

    def arbitracion():
        a = _dic(datos.get("arbitration"))
        nodo = a.get("nodeKey") or a.get("node") or ""
        if not nodo or nodo.startswith("SolNode000"):
            return None
        return Recompensa(
            texto=traductor.nodo(nodo),
            expira=_momento(a.get("expiry")),
            detalle=" - ".join(
                x
                for x in (
                    traductor.termino("mision", a.get("typeKey") or a.get("type")),
                    traductor.termino("faccion", a.get("enemy")),
                )
                if x
            ),
        )

    def variantes(clave: str):
        bloque = _dic(datos.get(clave))
        expira = _momento(bloque.get("expiry"))
        salida = []
        for v in _dicts(bloque.get("variants") or bloque.get("missions")):
            tipo = v.get("missionTypeKey") or v.get("missionType") or v.get("typeKey") or v.get("type")
            salida.append(
                Recompensa(
                    texto=f"{traductor.nodo(v.get('nodeKey') or v.get('node'))} - "
                    f"{traductor.termino('mision', tipo)}".strip(" -"),
                    expira=expira,
                    detalle=v.get("modifier") or "",
                )
            )
        return salida

    def nightwave():
        n = _dic(datos.get("nightwave"))
        salida = []
        for r in _dicts(n.get("activeChallenges")):
            etiqueta = t("diario") if r.get("isDaily") else (t("elite") if r.get("isElite") else t("semanal"))
            salida.append(
                Recompensa(
                    texto=f"[{etiqueta}] {r.get('title') or r.get('desc') or ''}",
                    expira=_momento(r.get("expiry")),
                    detalle=t("{standing} de reputacion", standing=r.get("reputation") or 0),
                )
            )
        return sorted(salida, key=lambda r: (r.expira or datetime.max.replace(tzinfo=timezone.utc)))

    def baro():
        detalle = analizar_baro(datos.get("voidTrader"), traductor)
        if detalle is None:
            return None
        objetos = [
            Recompensa(
                texto=o.nombre_mostrar,
                detalle=" ".join(
                    x
                    for x in (
                        t("{n} ducados", n=o.ducados) if o.ducados else "",
                        t("{n} creditos", n=o.creditos) if o.creditos else "",
                    )
                    if x
                ),
                expira=detalle.expira,
            )
            for o in detalle.inventario
        ]
        return detalle.cabecera(), objetos, detalle

    def acero():
        s = _dic(datos.get("steelPath"))
        actual = _dic(s.get("currentReward"))
        if not actual:
            return []
        return [
            Recompensa(
                texto=str(actual.get("name") or ""),
                detalle=t("{n} de esencia", n=actual.get("cost", "?")),
                expira=_momento(s.get("expiry")),
            )
        ]

    mundo.fisuras = _bloque("fissures", fisuras) or []
    mundo.ciclos = _bloque("cycles", ciclos) or []
    mundo.invasiones = _bloque("invasions", invasiones) or []
    mundo.alertas = _bloque("alerts", alertas) or []
    mundo.arbitracion = _bloque("arbitration", arbitracion)
    mundo.sortie = _bloque("sortie", variantes, "sortie") or []
    mundo.arcontes = _bloque("archonHunt", variantes, "archonHunt") or []
    mundo.nightwave = _bloque("nightwave", nightwave) or []
    cabecera_baro = _bloque("voidTrader", baro)
    if cabecera_baro:
        mundo.baro_cabecera, mundo.baro, mundo.baro_detalle = cabecera_baro
    mundo.acero = _bloque("steelPath", acero) or []
    return mundo


def analizar_baro(crudo, traductor: Traductor) -> Baro | None:
    """El bloque voidTrader de warframestat.us, casado con el indice.

    `active` lo manda la API; si falta, se deduce de las fechas o de que haya
    inventario. Cada objeto se busca en el indice por su unique_name (quitando
    el prefijo de la tienda) o por nombre, para tener nombre en castellano,
    slug de market y ducados propios.
    """
    v = _dic(crudo)
    if not v:
        return None
    llegada = _momento(v.get("activation"))
    expira = _momento(v.get("expiry"))
    activo = _bandera(v.get("active"))
    if activo is None:
        ahora = datetime.now(timezone.utc)
        activo = bool(v.get("inventory")) or bool(llegada and expira and llegada <= ahora < expira)
    inventario = []
    for o in _dicts(v.get("inventory")):
        nombre_en = str(o.get("item") or "")
        unique_name = _sin_tienda(str(o.get("uniqueName") or ""))
        objeto = ObjetoBaro(
            nombre=nombre_en,
            unique_name=unique_name,
            ducados=_entero(o.get("ducats")),
            creditos=_entero(o.get("credits")),
        )
        fila = traductor.objeto(unique_name, nombre_en)
        if fila:
            objeto.item_id = fila["id"]
            objeto.nombre_es = fila["nombre_es"] or ""
            objeto.categoria = fila["categoria"] or ""
            objeto.market_slug = fila["market_slug"]
            if objeto.ducados is None and fila["ducados"]:
                objeto.ducados = fila["ducados"]
        inventario.append(objeto)
    inventario.sort(key=lambda o: (-(o.ducados or 0), o.nombre_mostrar))
    return Baro(
        personaje=str(v.get("character") or "Baro Ki'Teer"),
        lugar=traductor.nodo(v.get("location")),
        activo=activo,
        llegada=llegada,
        expira=expira,
        inventario=inventario,
    )


def _entero(valor) -> int | None:
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


# -- servicio --------------------------------------------------------------


class ServicioMundo(QObject):
    """Pide el estado del mundo cada minuto mientras el overlay este visible."""

    actualizado = Signal(object)  # Mundo
    fallo = Signal(str)

    SEGUNDOS_VISIBLE = 60
    SEGUNDOS_OCULTO = 300

    def __init__(self, con: sqlite3.Connection | None = None, parent=None):
        super().__init__(parent)
        self.traductor = Traductor(con)
        self.cliente = Cliente(por_segundo=1.0)
        self.ultimo: Mundo | None = None
        self.temporizador: QTimer | None = None

    def iniciar(self) -> None:
        """Se llama ya dentro de su hilo: las peticiones no pueden bloquear la ventana."""
        self.temporizador = QTimer(self)
        self.temporizador.timeout.connect(self.refrescar)
        self.temporizador.start(self.SEGUNDOS_VISIBLE * 1000)
        self.refrescar()

    def cadencia(self, visible: bool) -> None:
        if self.temporizador:
            self.temporizador.setInterval(
                (self.SEGUNDOS_VISIBLE if visible else self.SEGUNDOS_OCULTO) * 1000
            )

    def _respaldo(self) -> Mundo | None:
        """El worldState crudo de DE, solo si esta al dia; si no, None y se anota."""
        from . import worldstate_de

        try:
            crudo = worldstate_de.comprobar_crudo(self.cliente.json(worldstate_de.URL_DE, segundos_cache=30))
            mundo = analizar(worldstate_de.normalizar(crudo, self.traductor), self.traductor)
        except (RuntimeError, worldstate_de.ErrorCrudo) as e:
            log.warning("El respaldo de DE tampoco sirve: %s", e)
            return None
        if mundo.momento is None or mundo.esta_viejo():
            log.warning("El respaldo de DE tambien esta desfasado (%s)", mundo.momento)
            return None
        mundo.fuente = "de"
        return mundo

    def refrescar(self) -> None:
        error = ""
        mundo: Mundo | None = None
        try:
            datos = comprobar_respuesta(
                self.cliente.json(URL.format(plataforma=PLATAFORMA), segundos_cache=30)
            )
            mundo = analizar(datos, self.traductor)
        except (RuntimeError, ErrorMundo) as e:
            error = str(e)
            log.warning("Estado del mundo no disponible: %s", e)
        # Si warframestat falla o publica un estado viejo (las horas siguientes a un
        # parche), se prueba el crudo oficial de DE; solo vale si esta al dia.
        if mundo is None or mundo.esta_viejo() or mundo.momento is None:
            respaldo = self._respaldo()
            if respaldo is not None:
                if mundo is not None:
                    log.info("warframestat desfasado; se usa el worldState de DE")
                mundo = respaldo
        if mundo is None:
            self.fallo.emit(error)
            return
        self.ultimo = mundo
        self.actualizado.emit(mundo)
        # Sin respaldo, los datos viejos se ensenan marcados como tales en vez de
        # dejarlos pasar por buenos.
        if mundo.esta_viejo():
            minutos = int(mundo.minutos_de_antiguedad() or 0)
            log.warning("El estado del mundo tiene %d minutos de antiguedad", minutos)
            self.fallo.emit(t("la API devuelve datos de hace {n} min", n=minutos))
        elif mundo.momento is None:
            self.fallo.emit(t("la API no dice de cuando son sus datos"))

    def cerrar(self) -> None:
        if self.temporizador:
            self.temporizador.stop()
        self.cliente.cerrar()
