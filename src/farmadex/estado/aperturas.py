"""Historial de aperturas de reliquias: que salio, que te llevaste (si se sabe) y cuanto vale.

Vive en `usuario.sqlite` (la base del usuario, que no se regenera), en tablas
propias de este modulo con CREATE TABLE IF NOT EXISTS: no toca el esquema
versionado de `usuario_db.py`.

Lo que se guarda y lo que NO
----------------------------
Cada apertura guarda la hora, de donde vino (aviso de EE.log o atajo), las
opciones que habia en pantalla (1-4 piezas, por su ruta del juego) y, SOLO si se
sabe con seguridad, la pieza que te llevaste. Se sabe en dos casos:

- **EE.log en solitario**: mision con 0 jugadores remotos y exactamente UNA linea
  "gets reward" (la misma regla que `registro/botin.py`). Si el OCR leyo otra
  pieza distinta, hay contradiccion y no se apunta ninguna.
- **Lo dice el usuario** desde el historial ("Me quedé esta").

En escuadra el juego no dice cual elegiste: la apertura se guarda con sus opciones
y queda marcada como "sin confirmar". Nunca se apunta una pieza dudosa como
obtenida. De EE.log no se copia nada mas que la ruta del objeto: ni el id de
jugador de la linea "gets reward", ni correo, ni IP.

La reliquia y su refinamiento salen del dialogo de equipar del juego
(`registro/eelog.reliquia_equipada`). Solo se guardan si cuadran: la pieza
obtenida (o alguna de las opciones) tiene que salir de esa reliquia; si no, se
descarta (el dialogo podia ser de otra mision, o se cancelo).

Suerte
------
Solo cuentan las aperturas en las que la pieza obtenida es el sorteo de TU
reliquia (solitario, `sorteo_propio`) y se conoce el refinamiento: en escuadra la
pieza se elige entre cuatro, y eso no es un sorteo. Con pocas aperturas se dice
que la muestra es pequena en vez de sacar conclusiones.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from ..idiomas import t
from ..registro_log import obtener

log = obtener("aperturas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS aperturas (
  id INTEGER PRIMARY KEY,
  abierta_en TEXT NOT NULL,
  fuente TEXT NOT NULL,
  reliquia TEXT,
  refinamiento TEXT,
  en_solitario INTEGER,
  opciones_json TEXT NOT NULL,
  obtenida TEXT,
  obtenida_nombre TEXT,
  como TEXT,
  sorteo_propio INTEGER NOT NULL DEFAULT 0,
  rareza_obtenida TEXT
);
CREATE INDEX IF NOT EXISTS ix_aperturas_fecha ON aperturas(abierta_en);

CREATE TABLE IF NOT EXISTS precios_vistos (
  unique_name TEXT PRIMARY KEY,
  slug TEXT,
  platino INTEGER,
  vendedores INTEGER,
  compradores INTEGER,
  visto_en TEXT NOT NULL
);
"""

FUENTE_EELOG = "eelog"
FUENTE_ATAJO = "atajo"
COMO_EELOG = "eelog_solitario"
COMO_USUARIO = "usuario"

RAREZAS = ("Common", "Uncommon", "Rare")
# Probabilidad de cada rareza por refinamiento (suma de las piezas de esa rareza):
# 3 comunes, 2 poco comunes y 1 rara por reliquia, en porcentaje.
PROB_RAREZA = {
    "Intact": {"Common": 3 * 25.33, "Uncommon": 2 * 11.0, "Rare": 2.0},
    "Exceptional": {"Common": 3 * 23.33, "Uncommon": 2 * 13.0, "Rare": 4.0},
    "Flawless": {"Common": 3 * 20.0, "Uncommon": 2 * 17.0, "Rare": 6.0},
    "Radiant": {"Common": 3 * 16.67, "Uncommon": 2 * 20.0, "Rare": 10.0},
}
REFINAMIENTOS = tuple(PROB_RAREZA)
# Por debajo de esto no se saca ninguna conclusion de la suerte.
MUESTRA_MINIMA = 30
# Aperturas del atajo sobre la misma pantalla: se juntan en una sola.
VENTANA_MISMA_PANTALLA_S = 90


def preparar(usuario: sqlite3.Connection) -> None:
    usuario.executescript(ESQUEMA)


def _ahora() -> datetime:
    return datetime.now().replace(microsecond=0)


# -- modelo ---------------------------------------------------------------------------


@dataclass
class Opcion:
    unique_name: str
    nombre: str
    ducados: int | None = None
    rareza: str | None = None  # "Common"/"Uncommon"/"Rare" en SU reliquia, si se sabe
    platino: int | None = None  # el que habia al abrir (vendedor mas barato), si se supo

    def como_dict(self) -> dict:
        return {"unique_name": self.unique_name, "nombre": self.nombre, "ducados": self.ducados,
                "rareza": self.rareza, "platino": self.platino}


@dataclass
class Apertura:
    id: int | None
    abierta_en: str
    fuente: str
    opciones: list[Opcion] = field(default_factory=list)
    reliquia: str | None = None
    refinamiento: str | None = None
    en_solitario: bool | None = None
    obtenida: str | None = None
    obtenida_nombre: str | None = None
    como: str | None = None
    sorteo_propio: bool = False
    rareza_obtenida: str | None = None

    @property
    def confirmada(self) -> bool:
        return bool(self.obtenida)


def _opcion_de_dict(d: dict) -> Opcion:
    return Opcion(d.get("unique_name") or "", d.get("nombre") or "", d.get("ducados"), d.get("rareza"),
                  d.get("platino"))


def _de_fila(f) -> Apertura:
    try:
        opciones = [_opcion_de_dict(d) for d in json.loads(f[6] or "[]") if isinstance(d, dict)]
    except (TypeError, ValueError):
        opciones = []
    return Apertura(
        id=f[0], abierta_en=f[1], fuente=f[2], reliquia=f[3], refinamiento=f[4],
        en_solitario=None if f[5] is None else bool(f[5]), opciones=opciones, obtenida=f[7],
        obtenida_nombre=f[8], como=f[9], sorteo_propio=bool(f[10]), rareza_obtenida=f[11],
    )


_COLUMNAS = ("id, abierta_en, fuente, reliquia, refinamiento, en_solitario, opciones_json, obtenida, "
             "obtenida_nombre, como, sorteo_propio, rareza_obtenida")


# -- escritura ------------------------------------------------------------------------


def guardar(usuario: sqlite3.Connection, a: Apertura) -> int:
    """Inserta (id None) o reescribe una apertura; devuelve su id."""
    preparar(usuario)
    if a.obtenida and a.obtenida not in {o.unique_name for o in a.opciones}:
        # La obtenida siempre esta entre las opciones: si no, se anade (EE.log la dio exacta).
        a.opciones.append(Opcion(a.obtenida, a.obtenida_nombre or a.obtenida))
    valores = (
        a.abierta_en, a.fuente, a.reliquia, a.refinamiento,
        None if a.en_solitario is None else int(a.en_solitario),
        json.dumps([o.como_dict() for o in a.opciones], ensure_ascii=False),
        a.obtenida, a.obtenida_nombre, a.como, int(bool(a.sorteo_propio)), a.rareza_obtenida,
    )
    if a.id is None:
        cursor = usuario.execute(
            "INSERT INTO aperturas (abierta_en, fuente, reliquia, refinamiento, en_solitario, opciones_json, "
            "obtenida, obtenida_nombre, como, sorteo_propio, rareza_obtenida) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            valores,
        )
        a.id = cursor.lastrowid
    else:
        usuario.execute(
            "UPDATE aperturas SET abierta_en=?, fuente=?, reliquia=?, refinamiento=?, en_solitario=?, "
            "opciones_json=?, obtenida=?, obtenida_nombre=?, como=?, sorteo_propio=?, rareza_obtenida=? "
            "WHERE id=?",
            (*valores, a.id),
        )
    usuario.commit()
    return a.id


def marcar_obtenida(usuario: sqlite3.Connection, apertura_id: int, unique_name: str | None) -> bool:
    """El usuario dice cual se llevo (o None para quitarlo). Solo vale una de las opciones.

    Lo que dijo EE.log en solitario tambien se puede corregir: manda el usuario. Pero
    entonces deja de contar para la suerte, porque ya no se sabe si fue el sorteo propio.
    """
    a = obtener_apertura(usuario, apertura_id)
    if a is None:
        return False
    if unique_name is None:
        a.obtenida = a.obtenida_nombre = a.como = a.rareza_obtenida = None
        a.sorteo_propio = False
        guardar(usuario, a)
        return True
    opcion = next((o for o in a.opciones if o.unique_name == unique_name), None)
    if opcion is None:
        return False
    if a.obtenida == unique_name:
        return True
    a.obtenida, a.obtenida_nombre, a.como = unique_name, opcion.nombre, COMO_USUARIO
    a.sorteo_propio = False
    a.rareza_obtenida = opcion.rareza
    guardar(usuario, a)
    return True


def borrar_todo(usuario: sqlite3.Connection) -> int:
    preparar(usuario)
    n = usuario.execute("DELETE FROM aperturas").rowcount
    usuario.commit()
    log.info("Historial de aperturas borrado (%d)", n)
    return n


def guardar_precios(usuario: sqlite3.Connection, precios: list[tuple], visto_en: str | None = None,
                    commit: bool = True) -> None:
    """[(unique_name, slug, platino, vendedores, compradores)] vistos ahora mismo."""
    if not precios:
        return
    preparar(usuario)
    cuando = visto_en or _ahora().isoformat()
    usuario.executemany(
        "INSERT OR REPLACE INTO precios_vistos (unique_name, slug, platino, vendedores, compradores, visto_en) "
        "VALUES (?,?,?,?,?,?)",
        [(u, s, p, v, c, cuando) for u, s, p, v, c in precios if u and p is not None],
    )
    if commit:
        usuario.commit()


# -- lectura --------------------------------------------------------------------------


def obtener_apertura(usuario: sqlite3.Connection, apertura_id: int) -> Apertura | None:
    preparar(usuario)
    f = usuario.execute(f"SELECT {_COLUMNAS} FROM aperturas WHERE id = ?", (apertura_id,)).fetchone()
    return _de_fila(f) if f else None


def listar(usuario: sqlite3.Connection, limite: int | None = 200) -> list[Apertura]:
    """Las mas recientes primero."""
    preparar(usuario)
    sql = f"SELECT {_COLUMNAS} FROM aperturas ORDER BY abierta_en DESC, id DESC"
    if limite:
        sql += f" LIMIT {int(limite)}"
    return [_de_fila(f) for f in usuario.execute(sql)]


@dataclass
class PrecioVisto:
    platino: int
    vendedores: int | None
    compradores: int | None
    visto_en: str

    def edad_s(self, ahora: datetime | None = None) -> float | None:
        try:
            return ((ahora or _ahora()) - datetime.fromisoformat(self.visto_en)).total_seconds()
        except ValueError:
            return None


def precios(usuario: sqlite3.Connection, unique_names) -> dict[str, PrecioVisto]:
    preparar(usuario)
    salida = {}
    for u in set(unique_names):
        f = usuario.execute(
            "SELECT platino, vendedores, compradores, visto_en FROM precios_vistos WHERE unique_name = ?", (u,)
        ).fetchone()
        if f and f[0] is not None:
            salida[u] = PrecioVisto(f[0], f[1], f[2], f[3])
    return salida


# -- estadisticas ---------------------------------------------------------------------


@dataclass
class SuerteRareza:
    rareza: str
    obtenidas: int
    esperadas: float


@dataclass
class Suerte:
    muestra: int  # aperturas que cuentan (sorteo propio con refinamiento conocido)
    por_rareza: list[SuerteRareza]
    veredicto: str  # "poca_muestra", "mas", "normal", "menos"

    @property
    def poca_muestra(self) -> bool:
        return self.veredicto == "poca_muestra"


def suerte(aperturas: list[Apertura]) -> Suerte:
    """Obtenido frente a esperado por rareza, solo con los sorteos de tu reliquia."""
    validas = [a for a in aperturas if a.sorteo_propio and a.refinamiento in PROB_RAREZA
               and a.rareza_obtenida in RAREZAS]
    por = []
    for rareza in RAREZAS:
        obtenidas = sum(1 for a in validas if a.rareza_obtenida == rareza)
        esperadas = sum(PROB_RAREZA[a.refinamiento][rareza] / 100 for a in validas)
        por.append(SuerteRareza(rareza, obtenidas, esperadas))
    if len(validas) < MUESTRA_MINIMA:
        return Suerte(len(validas), por, "poca_muestra")
    # Se mira la rara, que es la que importa: desviacion en unidades de su error tipico
    # (binomial: suma de p(1-p)). Solo se habla de suerte a partir de dos errores tipicos.
    probs = [PROB_RAREZA[a.refinamiento]["Rare"] / 100 for a in validas]
    rara = por[2]
    sigma = math.sqrt(sum(p * (1 - p) for p in probs)) or 1.0
    z = (rara.obtenidas - rara.esperadas) / sigma
    veredicto = "mas" if z >= 2 else "menos" if z <= -2 else "normal"
    return Suerte(len(validas), por, veredicto)


@dataclass
class Totales:
    aperturas: int = 0
    confirmadas: int = 0
    sin_confirmar: int = 0
    ducados: int = 0
    platino: int = 0  # estimado, con el precio de mercado mas reciente que se tenga
    sin_precio: int = 0  # obtenidas cuyo precio no se conoce (o es viejo)
    precio_mas_viejo: str | None = None


def totales(usuario: sqlite3.Connection, aperturas: list[Apertura], edad_maxima_s: float,
            ahora: datetime | None = None) -> Totales:
    """Ducados y platino de lo que SE SABE que te llevaste (lo sin confirmar no suma)."""
    tot = Totales(aperturas=len(aperturas))
    obtenidas = [a for a in aperturas if a.obtenida]
    tot.confirmadas = len(obtenidas)
    tot.sin_confirmar = tot.aperturas - tot.confirmadas
    vistos = precios(usuario, [a.obtenida for a in obtenidas])
    for a in obtenidas:
        opcion = next((o for o in a.opciones if o.unique_name == a.obtenida), None)
        tot.ducados += int((opcion.ducados if opcion else 0) or 0)
        precio = vistos.get(a.obtenida)
        edad = precio.edad_s(ahora) if precio else None
        if precio is None or edad is None or edad > edad_maxima_s:
            tot.sin_precio += 1
            continue
        tot.platino += precio.platino
        if tot.precio_mas_viejo is None or precio.visto_en < tot.precio_mas_viejo:
            tot.precio_mas_viejo = precio.visto_en
    return tot


@dataclass
class Falta:
    unique_name: str
    nombre: str
    reliquia: str  # la mejor reliquia para sacarla
    reliquia_vaulted: bool
    refinamiento: str
    probabilidad: float  # % por apertura con ese refinamiento
    aperturas_solo: float  # media de aperturas tu solo
    rondas_escuadra: float  # media de rondas en escuadra de 4 con la misma reliquia


def refinamiento_habitual(aperturas: list[Apertura]) -> str | None:
    """El refinamiento que mas usas (de lo que se sabe); None con menos de 3 datos."""
    conocidos = [a.refinamiento for a in aperturas if a.refinamiento in PROB_RAREZA]
    if len(conocidos) < 3:
        return None
    return max(REFINAMIENTOS, key=conocidos.count)


def aperturas_que_faltan(indice_con: sqlite3.Connection, usuario: sqlite3.Connection,
                         refinamiento: str = "Intact", nombre_de: Callable[[int], str] | None = None) -> list[Falta]:
    """Para cada pieza pendiente de tus metas que sale de reliquias: la mejor reliquia
    (primero las que se consiguen hoy, fuera de la boveda) y cuantas aperturas hacen
    falta de media. La media de una probabilidad p por apertura es 1/p; en escuadra de
    cuatro con la misma reliquia salen cuatro sorteos por ronda: 1/(1-(1-p)^4)."""
    pendientes = usuario.execute(
        "SELECT item_unique_name, nombre FROM objetivos WHERE completado_en IS NULL"
    ).fetchall()
    salida: list[Falta] = []
    for unico, nombre_meta in pendientes:
        fila = indice_con.execute("SELECT id FROM items WHERE unique_name = ?", (unico,)).fetchone()
        if not fila:
            continue
        candidatas = indice_con.execute(
            "SELECT r.unique_name, r.vaulted, rr.probabilidad FROM reliquia_recompensas rr "
            "JOIN items r ON r.id = rr.reliquia_id WHERE rr.item_id = ? AND rr.refinamiento = ? "
            "AND rr.probabilidad > 0",
            (fila[0], refinamiento),
        ).fetchall()
        if not candidatas:
            continue
        mejor = min(candidatas, key=lambda c: (bool(c[1]), -float(c[2])))
        p = float(mejor[2]) / 100
        nombre = nombre_de(fila[0]) if nombre_de else nombre_meta
        salida.append(Falta(
            unico, nombre or nombre_meta, (mejor[0] or "").removeprefix("RELIQUIA/"), bool(mejor[1]),
            refinamiento, float(mejor[2]), 1 / p, 1 / (1 - (1 - p) ** 4),
        ))
    return sorted(salida, key=lambda f: (f.reliquia_vaulted, f.aperturas_solo))


# -- grabador: une EE.log, el OCR y el comparador ---------------------------------------


def _misma_pantalla(a: set[str], b: set[str]) -> bool:
    """Dos lecturas seguidas son de la misma pantalla si comparten al menos la mitad de
    las piezas (una lectura parcial y otra completa). Compartir solo el plano de Forma
    de dos reliquias distintas no basta."""
    comunes = len(a & b)
    return comunes > 0 and comunes * 2 >= max(len(a), len(b))


class Grabador:
    """Sigue una apertura de principio a fin y la guarda al cerrarse. Sin Qt.

    La ventana le pasa: los eventos y pistas de `VigilanteEELog` (`evento`, `pista`),
    cada lectura del OCR ya completada (`leidas`: de ahi salen las opciones) y cada
    veredicto del comparador (`veredicto`: solo precios y ducados de lo ya conocido).
    Con EE.log escribe al cerrarse la pantalla; con el atajo, justo despues de pintar.

    - `usuario`: conexion a usuario.sqlite (la de la ventana, en su hilo).
    - `rareza_en(reliquia, unique_name)`: rareza de esa pieza en esa reliquia, o
      None si no sale de ella (para validar la reliquia del dialogo).
    - `resolver(ruta)`: (unique_name del indice, nombre para mostrar) de una ruta que
      dio EE.log, o None si el indice no la conoce. EE.log escribe la ruta de tienda y
      el indice puede guardarla con otra forma: sin esto la misma pieza leida por OCR
      y por EE.log pareceria dos distintas.
    """

    def __init__(self, usuario: sqlite3.Connection, rareza_en: Callable[[str, str], str | None] | None = None,
                 resolver: Callable[[str], tuple[str, str] | None] | None = None, activo: bool = True,
                 reloj: Callable[[], datetime] = _ahora):
        self.usuario = usuario
        self.rareza_en = rareza_en or (lambda _r, _u: None)
        self.resolver = resolver or (lambda _u: None)
        self.activo = activo
        self.reloj = reloj
        self.remotos: int | None = None
        self.equipada: tuple[str, str | None] | None = None  # (reliquia, refinamiento)
        self._abierta: datetime | None = None
        self._candidatas: list[str] = []  # rutas "gets reward" de esta pantalla (ya del indice)
        self._nombres: dict[str, str] = {}
        self._opciones: dict[str, Opcion] = {}
        self._precios: dict[str, tuple] = {}
        self._ultima: Apertura | None = None  # para juntar lecturas tardias o repetidas
        self._ultima_en: datetime | None = None
        self.cambios = 0  # cuantas veces se ha escrito algo (la vista se refresca con esto)

    # -- entradas ------------------------------------------------------------------

    def evento(self, nombre: str) -> None:
        if nombre == "reliquia_abierta":
            self._cerrar()  # una anterior sin cierre (el juego se cerro a medias)
            self._empezar()
        elif nombre == "reliquia_recompensas" and self._abierta is None:
            self._empezar()  # "Relic rewards initialized" no llego
        elif nombre == "reliquia_cerrada":
            self._cerrar()

    def pista(self, tipo: str, valor: str) -> None:
        if tipo == "remotos":
            try:
                self.remotos = int(valor)
            except ValueError:
                self.remotos = None
        elif tipo == "recompensa" and self._abierta is not None:
            resuelta = self.resolver(valor)
            unico, nombre = resuelta if resuelta else (valor, "")
            if unico not in self._candidatas:
                self._candidatas.append(unico)
                self._nombres[unico] = nombre or unico
        elif tipo == "reliquia_equipada":
            reliquia, _barra, refinamiento = valor.partition("|")
            self.equipada = (reliquia.strip(), refinamiento.strip() or None) if reliquia.strip() else None

    @staticmethod
    def _opciones_de(recompensas: list) -> dict[str, Opcion]:
        nuevas = {}
        for r in recompensas:
            unico = getattr(r, "unique_name", "") or ""
            if not unico or not getattr(r, "item_id", 0):
                continue  # sin identificar: no se guarda nada inventado
            nuevas[unico] = Opcion(unico, getattr(r, "nombre", "") or unico, getattr(r, "ducados", None),
                                   None, getattr(r, "platino", None))
        return nuevas

    def leidas(self, recompensas: list) -> None:
        """Lo que el OCR acaba de leer en pantalla (ya completado con el indice).

        Llega en orden con los eventos de EE.log, asi que es de ESTA pantalla: de aqui
        salen las opciones. El veredicto del comparador puede llegar segundos despues
        (precios) y ya con otra pantalla abierta, por eso solo completa datos."""
        nuevas = self._opciones_de(recompensas)
        if not nuevas:
            return
        if self._abierta is not None:
            self._fusionar(self._opciones, nuevas)
            return
        # Sin apertura en curso: atajo, o una lectura que llega tarde de la ultima.
        if not self.activo:
            return
        ahora = self.reloj()
        ultima = self._ultima
        if (ultima is not None and self._ultima_en is not None
                and (ahora - self._ultima_en).total_seconds() < VENTANA_MISMA_PANTALLA_S
                and _misma_pantalla(set(nuevas), {o.unique_name for o in ultima.opciones})):
            opciones = {o.unique_name: o for o in ultima.opciones}
            antes = set(opciones)
            self._fusionar(opciones, nuevas)
            if set(opciones) != antes:
                ultima.opciones = list(opciones.values())
                self._escribir(ultima)
            return
        a = Apertura(None, ahora.isoformat(), FUENTE_ATAJO, list(nuevas.values()))
        self._escribir(a)
        self._ultima, self._ultima_en = a, ahora

    def veredicto(self, recompensas: list, _veredicto=None) -> None:
        """Precios y ducados del comparador: completan las opciones que ya se conocen
        (la apertura en curso o la ultima guardada). Nunca anaden piezas: el veredicto
        puede ser de una pantalla anterior que tardo en valorarse."""
        for r in recompensas:
            unico = getattr(r, "unique_name", "") or ""
            platino = getattr(r, "platino", None)
            if unico and platino is not None and getattr(r, "item_id", 0):
                self._precios[unico] = (unico, getattr(r, "market_slug", "") or None, platino,
                                        getattr(r, "vendedores", None) or None, getattr(r, "compradores", None))
        nuevas = self._opciones_de(recompensas)
        if not nuevas:
            return
        if self._abierta is not None:
            for unico, o in nuevas.items():
                if unico in self._opciones:
                    self._fusionar(self._opciones, {unico: o})
            return
        ultima = self._ultima
        if ultima is None or not self.activo:
            return
        cambiado = False
        for opcion in ultima.opciones:
            o = nuevas.get(opcion.unique_name)
            if o is None:
                continue
            if o.platino is not None and o.platino != opcion.platino:
                opcion.platino, cambiado = o.platino, True
            if opcion.ducados is None and o.ducados is not None:
                opcion.ducados, cambiado = o.ducados, True
        if cambiado:
            self._escribir(ultima)

    def cerrar(self) -> None:
        """Al salir de Farmadex: lo que este a medias se guarda, y los precios vistos."""
        self._cerrar()
        if self._precios and self.activo:
            try:
                guardar_precios(self.usuario, list(self._precios.values()))
                self._precios = {}
            except sqlite3.Error:
                log.exception("No se pudieron guardar los precios vistos")

    # -- interno ------------------------------------------------------------------

    @staticmethod
    def _fusionar(destino: dict[str, Opcion], nuevas: dict[str, Opcion]) -> None:
        for unico, o in nuevas.items():
            previa = destino.get(unico)
            if previa is None:
                destino[unico] = o
            else:
                previa.ducados = previa.ducados if previa.ducados is not None else o.ducados
                previa.platino = o.platino if o.platino is not None else previa.platino

    def _empezar(self) -> None:
        self._abierta = self.reloj()
        self._candidatas = []
        self._nombres = {}
        self._opciones = {}

    def _cerrar(self) -> None:
        if self._abierta is None:
            return
        abierta, candidatas, opciones = self._abierta, list(self._candidatas), dict(self._opciones)
        self._abierta, self._candidatas, self._opciones = None, [], {}
        equipada, self.equipada = self.equipada, None  # el dialogo vale para UNA apertura
        if not self.activo:
            return
        for ruta in candidatas:
            if ruta not in opciones:
                opciones[ruta] = Opcion(ruta, self._nombres.get(ruta) or ruta)
        if not opciones:
            return  # ni EE.log ni el OCR dieron nada: no hay apertura que contar
        a = Apertura(None, abierta.isoformat(), FUENTE_EELOG, list(opciones.values()),
                     en_solitario=None if self.remotos is None else self.remotos == 0)
        # Obtenida segura: solitario y una sola "gets reward", sin que el OCR lea otra cosa.
        if self.remotos == 0 and len(candidatas) == 1:
            ruta = candidatas[0]
            otras = [u for u in opciones if u != ruta]
            if otras:
                log.info("Apertura en solitario con lecturas que no cuadran con EE.log: sin confirmar")
            else:
                a.obtenida, a.obtenida_nombre, a.como = ruta, opciones[ruta].nombre, COMO_EELOG
                a.sorteo_propio = True
        self._validar_reliquia(a, equipada)
        self._escribir(a)
        self._ultima, self._ultima_en = a, self.reloj()

    def _validar_reliquia(self, a: Apertura, equipada) -> None:
        """La reliquia del dialogo solo se apunta si cuadra con lo que salio."""
        if not equipada:
            return  # sin reliquia no hay rareza ni suerte que medir (la obtenida sigue valiendo)
        reliquia, refinamiento = equipada
        rarezas = {o.unique_name: self.rareza_en(reliquia, o.unique_name) for o in a.opciones}
        if a.obtenida:
            rareza = rarezas.get(a.obtenida)
            if rareza is None:
                log.info("La reliquia del dialogo (%s) no suelta la pieza obtenida: no se apunta", reliquia)
                a.sorteo_propio = False
                return
            a.rareza_obtenida = rareza
        elif not any(rarezas.values()):
            log.info("Ninguna opcion sale de la reliquia del dialogo (%s): no se apunta", reliquia)
            return
        a.reliquia, a.refinamiento = reliquia, refinamiento
        for o in a.opciones:
            o.rareza = rarezas.get(o.unique_name)

    def _escribir(self, a: Apertura) -> None:
        try:
            guardar(self.usuario, a)
            if self._precios:
                guardar_precios(self.usuario, list(self._precios.values()))
                self._precios = {}
            self.cambios += 1
        except sqlite3.Error:
            log.exception("No se pudo guardar la apertura de reliquia")
