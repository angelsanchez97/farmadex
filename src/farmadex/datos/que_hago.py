"""¿Que hago ahora?: cruza tus metas con las fisuras abiertas y las reliquias que las tienen.

Para cada fisura abierta ahora mismo se mira que reliquias de su era contienen alguna
pieza de tus metas pendientes (Omnia vale para todas las eras) y cuanto se tarda, de
media, en llevarte una de esas piezas jugando esa fisura con esa reliquia:

    minutos = (fisura + conseguir la reliquia) / probabilidad de la pieza por fisura

- `fisura` es lo que dura ESA fisura segun su tipo de mision (una Captura ~3 min, una
  Supervivencia una rotacion), con las mismas tablas y el mismo ritmo de juego que el
  resto de Farmadex (`eficiencia`).
- `conseguir la reliquia` es cero si el inventario leido dice que la tienes; si no, lo
  que tarda en caer en su mejor sitio (`ruta_prime.misiones_para`, `minutos_reliquia`).
  Una reliquia en boveda solo entra si la tienes: no cae en ninguna mision.
- La probabilidad es la de la pieza en esa reliquia con el refinamiento y la escuadra
  de la pestana Primes (`ruta_prime.probabilidad_por_fisura`), sumando las piezas de tus
  metas que haya en la misma reliquia.

Todo sale del indice (reliquias, probabilidades, misiones) y del estado del mundo; si
algo no se sabe no se inventa: una reliquia sin sitio donde farmearla y que no tienes no
se recomienda, y "la tienes" solo se dice si el inventario lo ha leido.

Este modulo no sabe de Qt ni de la BD del usuario: `leer_usuario` saca en el hilo de la
ventana lo poco que hace falta de ella, y `recomendar` puede ir en un hilo aparte con
su propia conexion al indice.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..idiomas import es_castellano, nombre as nombre_idioma
from . import eficiencia, ruta_prime

MAX_CONSEJOS = 5
ERA_COMODIN = "Omnia"  # fisuras que aceptan reliquias de cualquier era
PREFIJO_RELIQUIA = "RELIQUIA/"  # unique_name de las reliquias en el indice

# Estados del resultado.
OK = "ok"
SIN_INDICE = "sin_indice"
SIN_METAS = "sin_metas"          # no hay metas pendientes
SIN_RELIQUIAS = "sin_reliquias"  # hay metas, pero ninguna sale de reliquias
SOLO_BOVEDA = "solo_boveda"      # salen de reliquias, todas en boveda y no tienes ninguna
SIN_MUNDO = "sin_mundo"          # no se sabe que fisuras hay abiertas
SIN_FISURA = "sin_fisura"        # ninguna fisura abierta sirve ahora


@dataclass(frozen=True)
class Meta:
    """Una meta pendiente, lo justo para cruzarla (se lee en el hilo de la ventana)."""

    unique_name: str
    nombre: str
    faltan: int = 1


@dataclass
class Pieza:
    item_id: int
    nombre: str        # "Braton Prime Receptor", en el idioma de la interfaz
    probabilidad: float  # % en la reliquia con el refinamiento elegido


@dataclass
class Consejo:
    fisura: object           # online.worldstate.Fisura
    reliquia_id: int
    reliquia: str            # "Lith A5", en el idioma de la interfaz
    vaulted: bool
    piezas: list[Pieza]
    probabilidad: float      # % de alguna pieza de tus metas por reliquia abierta
    por_fisura: float        # 0..1, con la escuadra elegida
    minutos_fisura: float
    minutos: float           # de media hasta la pieza jugando esta fisura
    tienes: int | None       # reliquias leidas en el inventario; None = no se sabe
    minutos_reliquia: float | None = None  # hasta conseguir la reliquia si no la tienes
    sitio_reliquia: dict | None = None     # donde cae: donde, mision, rotacion
    otras_fisuras: int = 0                 # otras fisuras abiertas donde esta reliquia tambien vale

    @property
    def la_tienes(self) -> bool:
        return bool(self.tienes)


@dataclass
class Recomendacion:
    estado: str
    consejos: list[Consejo] = field(default_factory=list)
    refinamiento: str = ruta_prime.REFINAMIENTO_POR_DEFECTO
    escuadra: int = ruta_prime.ESCUADRA_POR_DEFECTO
    eras: list[str] = field(default_factory=list)  # eras de reliquia que te sirven
    # Sin consejo: la mejor ruta real (ruta_prime.ruta_pieza) para lo que sale de reliquias,
    # o `relaciones.mejor_ruta` de la meta mas rapida si nada sale de reliquias.
    alternativa: dict | None = None
    # Por que se descarto cada fisura abierta de una era que te sirve (sin consejo, para
    # explicarlo): "cierra" = se cierra antes de que de tiempo a terminarla; "sin_reliquia"
    # = ninguna reliquia de esa era se tiene ni se sabe donde farmear.
    descartes: dict[str, int] = field(default_factory=dict)
    fisuras_de_tus_eras: int = 0  # abiertas ahora de alguna era que te sirve
    meta_alternativa: str = ""   # nombre de la meta a la que se refiere la alternativa


# -- lo que hace falta de la BD del usuario ----------------------------------------------


def leer_usuario(usuario: sqlite3.Connection) -> tuple[list[Meta], dict[str, int], bool]:
    """(metas pendientes, reliquias leidas en el inventario por unique_name, si consta que
    tienes el Camino de Acero: algun nodo completado en Acero segun el perfil guardado).

    Barato y en el hilo de la ventana: la conexion del usuario no se comparte entre hilos.
    """
    from ..estado import inventario as estado_inventario
    from ..estado import objetivos as estado_objetivos

    metas = [
        Meta(o.unique_name, o.nombre_completo, max(1, o.objetivo - o.actual))
        for o in estado_objetivos.listar(usuario) if not o.completado
    ]
    tienes: dict[str, int] = {}
    try:
        estado_inventario.preparar(usuario)
        for lectura in estado_inventario.listar(usuario):
            if lectura.unique_name.startswith(PREFIJO_RELIQUIA):
                tienes[lectura.unique_name] = int(lectura.cantidad)
    except sqlite3.Error:
        tienes = {}
    try:
        acero = usuario.execute("SELECT 1 FROM perfil_nodos WHERE camino_acero = 1 LIMIT 1").fetchone() is not None
    except sqlite3.Error:
        acero = False  # sin perfil guardado: no consta
    return metas, tienes, acero


# -- tiempos --------------------------------------------------------------------------------


def minutos_fisura_de(modo: str, ritmo: str | None = None) -> float:
    """Minutos de abrir UNA reliquia en una fisura de ese tipo de mision, al ritmo de juego.

    Mision de un premio: la mision, reunir el reactivo y la carga (una Captura da lo
    mismo que `eficiencia.FISURA`). Sin fin: una rotacion, mas entrar y salir. Un tipo que
    no esta en ninguna tabla, la duracion desconocida de `eficiencia`.
    """
    if modo in eficiencia.UNA_VEZ:
        base = eficiencia.UNA_VEZ[modo] + eficiencia.FISURA_REACTIVO + eficiencia.CARGA
    elif modo in eficiencia.POR_TRAMOS:
        # Espionaje: la reliquia se cobra al terminar la mision entera (las tres bovedas).
        base = max(eficiencia.POR_TRAMOS[modo].values()) + eficiencia.FISURA_REACTIVO + eficiencia.CARGA
    elif modo in eficiencia.SIN_FIN:
        base = eficiencia.SIN_FIN[modo] + eficiencia.ENTRADA_SALIDA_SIN_FIN + eficiencia.CARGA
    else:
        base = eficiencia.DURACION_DESCONOCIDA + eficiencia.FISURA_REACTIVO + eficiencia.CARGA
    factor = eficiencia.RITMOS.get(ritmo or eficiencia.ritmo(), 1.0)
    return base * factor


def _era(nombre_en: str | None) -> str:
    return (nombre_en or "").split(" ")[0]


def _abierta(f, ahora: datetime) -> bool:
    expira = getattr(f, "expira", None)
    return not (expira and expira <= ahora)


def _minutos_que_quedan(f, ahora: datetime) -> float | None:
    expira = getattr(f, "expira", None)
    if not expira:
        return None
    return (expira - ahora).total_seconds() / 60


# -- la recomendacion ------------------------------------------------------------------------


def _ids(con: sqlite3.Connection, metas: list[Meta]) -> dict[int, Meta]:
    por_nombre = {m.unique_name: m for m in metas}
    salida: dict[int, Meta] = {}
    nombres = list(por_nombre)
    for i in range(0, len(nombres), 500):
        trozo = nombres[i:i + 500]
        for item_id, unico in con.execute(
            f"SELECT id, unique_name FROM items WHERE unique_name IN ({','.join('?' * len(trozo))})", trozo
        ):
            salida[item_id] = por_nombre[unico]
    return salida


def _nombres(con: sqlite3.Connection, ids) -> dict[int, dict]:
    """item_id -> {nombre, unique_name}: "Braton Prime Receptor" o "Reliquia Lith A5"."""
    ids = sorted({int(i) for i in ids})
    salida: dict[int, dict] = {}
    for i in range(0, len(ids), 500):
        trozo = ids[i:i + 500]
        for item_id, unico, en, es, padre_en, padre_es in con.execute(
            "SELECT i.id, i.unique_name, i.nombre_en, i.nombre_es, p.nombre_en, p.nombre_es "
            f"FROM items i LEFT JOIN items p ON p.id = i.padre_id WHERE i.id IN ({','.join('?' * len(trozo))})",
            trozo,
        ):
            propio = nombre_idioma({"nombre_en": en, "nombre_es": es})
            if padre_en or padre_es:
                padre = nombre_idioma({"nombre_en": padre_en, "nombre_es": padre_es})
                propio = propio if propio.startswith(padre) else f"{padre} {propio}"
            salida[item_id] = {"nombre": propio, "unique_name": unico}
    return salida


def _nombre_reliquia(fila: dict) -> str:
    """"Lith A5" sin la palabra "Reliquia"/"Relic", que ya dice la frase."""
    texto = fila.get("nombre_en") or ""
    return texto[:-6] if texto.endswith(" Relic") else texto


def recomendar(
    con: sqlite3.Connection | None,
    metas: list[Meta],
    tienes: dict[str, int] | None,
    fisuras: list | None,
    ahora: datetime | None = None,
    refinamiento: str | None = None,
    escuadra: int | None = None,
    ritmo: str | None = None,
    cache: dict | None = None,
    maximo: int = MAX_CONSEJOS,
    acero: bool = False,
) -> Recomendacion:
    """Lo mejor que puedes hacer ahora con las fisuras abiertas, de lo mas util a lo menos.

    `fisuras` = None si no se sabe el estado del mundo. `tienes` son las reliquias leidas
    en el inventario (unique_name -> cantidad); lo que no esta ahi es "no se sabe".
    `acero`: consta que tienes el Camino de Acero. Si no consta, sus fisuras van detras de
    todas las normales (no todo el mundo lo tiene desbloqueado).
    Para cada fisura, la reliquia que antes da la pieza en ella; luego una fila por
    reliquia, en su mejor fisura (las demas se cuentan en `otras_fisuras`). En caso de
    empate, antes las fisuras normales que las de Camino de Acero o Tormenta.
    """
    if refinamiento is None or escuadra is None:
        ref_config, esc_config = ruta_prime.preferencias()
        refinamiento = refinamiento or ref_config
        escuadra = escuadra or esc_config
    ritmo = ritmo or eficiencia.ritmo()
    salida = Recomendacion(SIN_METAS, refinamiento=refinamiento, escuadra=escuadra)
    if con is None:
        salida.estado = SIN_INDICE
        return salida
    if not metas:
        return salida
    ahora = ahora or datetime.now(timezone.utc)
    tienes = tienes or {}

    por_id = _ids(con, metas)
    reliquias = ruta_prime.reliquias_para(con, por_id, refinamiento)
    if not reliquias:
        salida.estado = SIN_RELIQUIAS
        salida.alternativa, salida.meta_alternativa = _mejor_sin_reliquias(con, por_id)
        return salida
    nombres = _nombres(con, [r["reliquia_id"] for r in reliquias] + list(por_id))
    # En castellano la pieza se llama como en tus metas ("Receptor de Braton Prime"); en los
    # demas idiomas, el nombre del indice (las metas guardan el nombre con el que se crearon).
    for item_id, meta in (por_id.items() if es_castellano() else ()):
        if meta.nombre and item_id in nombres:
            nombres[item_id]["nombre"] = meta.nombre
    for r in reliquias:
        r["unique_name"] = nombres.get(r["reliquia_id"], {}).get("unique_name", "")
        r["tienes"] = tienes.get(r["unique_name"]) if r["unique_name"] in tienes else None
    usables = [r for r in reliquias if not r["vaulted"] or (r["tienes"] or 0) > 0]
    salida.eras = sorted({_era(r["nombre_en"]) for r in usables if _era(r["nombre_en"])},
                         key=lambda e: (ruta_prime_orden(e), e))
    if not usables:
        salida.estado = SOLO_BOVEDA
        salida.alternativa = ruta_prime.ruta_pieza(con, list(por_id), refinamiento, escuadra, cache=cache)
        return salida

    if fisuras is None:
        salida.estado = SIN_MUNDO
    else:
        salida.consejos = _consejos(con, usables, nombres, fisuras, ahora, refinamiento, escuadra, ritmo,
                                    cache, maximo, acero, salida)
        salida.estado = OK if salida.consejos else SIN_FISURA
    if not salida.consejos:
        # Sin fisura util (o sin saber cuales hay): donde farmear la reliquia que antes da una pieza.
        salida.alternativa = ruta_prime.ruta_pieza(con, list(por_id), refinamiento, escuadra, cache=cache)
    return salida


def ruta_prime_orden(era: str) -> int:
    return {"Lith": 0, "Meso": 1, "Neo": 2, "Axi": 3, "Requiem": 4}.get(era, 9)


def _consejos(con, usables, nombres, fisuras, ahora, refinamiento, escuadra, ritmo, cache, maximo,
              acero: bool = False, salida: Recomendacion | None = None) -> list[Consejo]:
    # Lo que cuesta conseguir cada reliquia que no tienes: una vez por reliquia.
    farmeo: dict[int, dict | None] = {}

    def conseguir(r: dict) -> dict | None:
        if r["reliquia_id"] not in farmeo:
            sitios = ruta_prime.misiones_para(con, [r], escuadra, cache=cache) if not r["vaulted"] else []
            mejor = min((s for s in sitios if s.get("minutos_reliquia")), key=lambda s: s["minutos_reliquia"],
                        default=None)
            farmeo[r["reliquia_id"]] = mejor
        return farmeo[r["reliquia_id"]]

    consejos: list[Consejo] = []
    for f in fisuras:
        if not _abierta(f, ahora):
            continue
        era_fisura = getattr(f, "era", "")
        candidatas = [r for r in usables if era_fisura == ERA_COMODIN or _era(r["nombre_en"]) == era_fisura]
        if not candidatas:
            continue
        if salida is not None:
            salida.fisuras_de_tus_eras += 1
        minutos_fisura = minutos_fisura_de(getattr(f, "modo", "") or "", ritmo)
        quedan = _minutos_que_quedan(f, ahora)
        if quedan is not None and quedan < minutos_fisura:
            if salida is not None:  # se cierra antes de que te de tiempo a terminarla
                salida.descartes["cierra"] = salida.descartes.get("cierra", 0) + 1
            continue
        mejor: Consejo | None = None
        for r in candidatas:
            por_fisura = ruta_prime.probabilidad_por_fisura(r["probabilidad"], escuadra)
            if por_fisura <= 0:
                continue
            minutos_reliquia = sitio = None
            if not (r["tienes"] or 0) > 0:
                sitio = conseguir(r)
                if sitio is None:
                    continue  # ni la tienes ni se sabe donde farmearla: no se recomienda
                minutos_reliquia = float(sitio["minutos_reliquia"])
            minutos = (minutos_fisura + (minutos_reliquia or 0.0)) / por_fisura
            if mejor is not None and minutos >= mejor.minutos:
                continue
            piezas = sorted(
                (Pieza(item_id, nombres.get(item_id, {}).get("nombre", ""), prob)
                 for item_id, prob in r["piezas"].items()),
                key=lambda p: (-p.probabilidad, p.nombre),
            )
            mejor = Consejo(
                fisura=f, reliquia_id=r["reliquia_id"], reliquia=_nombre_reliquia(r), vaulted=r["vaulted"],
                piezas=piezas, probabilidad=r["probabilidad"], por_fisura=por_fisura,
                minutos_fisura=round(minutos_fisura, 1), minutos=round(minutos, 1), tienes=r["tienes"],
                minutos_reliquia=round(minutos_reliquia, 1) if minutos_reliquia is not None else None,
                sitio_reliquia=_sitio(sitio),
            )
        if mejor is not None:
            consejos.append(mejor)
        elif salida is not None:
            salida.descartes["sin_reliquia"] = salida.descartes.get("sin_reliquia", 0) + 1
    consejos.sort(key=lambda c: (
        bool(getattr(c.fisura, "acero", False)) and not acero,
        c.minutos,
        bool(getattr(c.fisura, "acero", False)),
        bool(getattr(c.fisura, "tormenta", False)),
        getattr(c.fisura, "nodo", ""),
    ))
    # Una fila por reliquia (en su mejor fisura): tres veces "abre Axi A21" en tres fisuras
    # no ayuda a decidir; las demas fisuras donde vale se cuentan.
    por_reliquia: dict[int, Consejo] = {}
    for c in consejos:
        if c.reliquia_id in por_reliquia:
            por_reliquia[c.reliquia_id].otras_fisuras += 1
        else:
            por_reliquia[c.reliquia_id] = c
    return list(por_reliquia.values())[:maximo]


def _sitio(sitio: dict | None) -> dict | None:
    if not sitio:
        return None
    return {
        "donde": sitio.get("donde") or "",
        "mision": sitio.get("mision") or "",
        "rotacion": sitio.get("rotacion"),
        "etapa": sitio.get("etapa"),
        "minutos_reliquia": sitio.get("minutos_reliquia"),
    }


def _mejor_sin_reliquias(con: sqlite3.Connection, por_id: dict[int, Meta], limite: int = 12) -> tuple[dict | None, str]:
    """La meta que antes se consigue fuera de reliquias (jefe, mision, contrato...)."""
    from . import relaciones

    mejor: tuple[float, dict, str] | None = None
    sin_tiempo: tuple[dict, str] | None = None
    for item_id, meta in list(por_id.items())[:limite]:
        ruta = relaciones.mejor_ruta(con, item_id)
        if not ruta or not ruta.get("mision"):
            continue
        minutos = ruta.get("minutos_medios")
        if minutos is None:
            sin_tiempo = sin_tiempo or (ruta, meta.nombre)
            continue
        if mejor is None or minutos < mejor[0]:
            mejor = (minutos, ruta, meta.nombre)
    if mejor:
        return mejor[1], mejor[2]
    return sin_tiempo if sin_tiempo else (None, "")


def firma_fisuras(fisuras: list | None) -> tuple:
    """Lo que identifica el conjunto de fisuras: si no cambia, la recomendacion tampoco."""
    if fisuras is None:
        return ("sin_mundo",)
    return tuple(sorted(
        (getattr(f, "era", ""), getattr(f, "nodo", ""), getattr(f, "modo", ""), bool(getattr(f, "acero", False)),
         str(getattr(f, "expira", "")))
        for f in fisuras
    ))
