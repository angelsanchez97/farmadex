"""¿Esta bien mi build? y "build basica": reglas de sentido comun sobre los datos de WFCD.

No se copia ninguna build de Overframe ni de otras webs (sus condiciones lo prohiben):
todo sale de las estadisticas del indice (critico, estado y tipo del arma; salud,
escudo y armadura del warframe) y del efecto de cada mod, con reglas que explica la
wiki oficial para quien empieza (https://wiki.warframe.com/w/Mod, /w/Damage,
/w/Critical_Hit, /w/Status_Effect, /w/Mod#Mod_Capacity):

- Un arma casi siempre quiere un mod de dano base (Sierra, Golpe de avispon, Punto de
  presion...) y, si dispara, uno de multidisparo.
- Los elementos se combinan de dos en dos en el orden de los huecos: calor + frio =
  explosion, calor + electricidad = radiacion, calor + toxina = gas, frio +
  electricidad = magnetico, frio + toxina = viral, electricidad + toxina = corrosivo.
- Los mods de critico rinden si el arma tiene critico alto; los de estado, si tiene
  estado alto. Con critico o estado bajos rinden poco.
- Un mod y su version Prime, Umbral, Arconte, Amalgama o Galvanizada no se pueden
  llevar a la vez.
- Un hueco vacio es fuerza que no se aprovecha; la capacidad que sobra se puede usar.
- Un warframe necesita algo para aguantar (salud, escudo, armadura o resistencias), y
  el aura da capacidad ademas de su efecto.

La salida es sencilla: lo que esta bien, lo que falta o sobra con el porque en una
frase, y una nota de que es una guia orientativa. Nada de esto toca el juego.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from ..idiomas import es_castellano, t
from . import nombres_juego

# -- que hace cada mod, leido de su efecto al rango maximo (en ingles, el texto de WFCD) --

ELEMENTOS = ("Heat", "Cold", "Electricity", "Toxin")
# Combinaciones de dos elementos (wiki: Damage#Elemental_Damage).
COMBINACIONES = {
    frozenset({"Heat", "Cold"}): "Blast",
    frozenset({"Heat", "Electricity"}): "Radiation",
    frozenset({"Heat", "Toxin"}): "Gas",
    frozenset({"Cold", "Electricity"}): "Magnetic",
    frozenset({"Cold", "Toxin"}): "Viral",
    frozenset({"Electricity", "Toxin"}): "Corrosive",
}
NOMBRE_ELEMENTO = {
    "Heat": "Calor", "Cold": "Frío", "Electricity": "Electricidad", "Toxin": "Toxina",
    "Blast": "Explosión", "Radiation": "Radiación", "Gas": "Gas", "Magnetic": "Magnético",
    "Viral": "Viral", "Corrosive": "Corrosivo",
}

RE_LINEA = re.compile(r"^([+-])\s*[\d.,]+\s*%?\s+(.+)$")
RE_DANO_BASE = re.compile(r"^(?:Melee\s+|Direct\s+)?Damage\b(?!\s+(?:to|on|Resistance|taken))", re.I)
RE_FACCION = re.compile(r"^Damage to (?:Grineer|Corpus|Infested|Corrupted|Orokin|The Murmur|Murmur|Sentients?)", re.I)

REGLAS_CLASE = (
    ("multidisparo", re.compile(r"^Multishot\b", re.I)),
    ("crit_prob", re.compile(r"^Critical Chance\b", re.I)),
    ("crit_dano", re.compile(r"^Critical Damage\b", re.I)),
    ("estado", re.compile(r"^Status Chance\b", re.I)),
    ("cadencia", re.compile(r"^(?:Fire Rate|Attack Speed)\b", re.I)),
    ("fisico", re.compile(r"^(?:Impact|Puncture|Slash)\b", re.I)),
    ("salud", re.compile(r"^Health\b(?!\s+(?:Orb|Regen|Conversion))", re.I)),
    ("escudo", re.compile(r"^Shield Capacity\b", re.I)),
    ("armadura", re.compile(r"^Armor\b", re.I)),
    ("fuerza", re.compile(r"^Ability Strength\b", re.I)),
    ("duracion", re.compile(r"^Ability Duration\b", re.I)),
    ("eficiencia", re.compile(r"^Ability Efficiency\b", re.I)),
    ("alcance_hab", re.compile(r"^Ability Range\b", re.I)),
    ("energia", re.compile(r"^Energy Max\b", re.I)),
)
SUPERVIVENCIA = frozenset({"salud", "escudo", "armadura", "resistencia", "aguante"})
HABILIDAD = frozenset({"fuerza", "duracion", "eficiencia", "alcance_hab"})

# Versiones de un mismo mod que el juego no deja llevar juntas (wiki de cada mod: "cannot
# be equipped alongside..."): el prefijo fuera da la familia; y estas, sin prefijo comun.
PREFIJOS_FAMILIA = ("Primed ", "Umbral ", "Archon ", "Amalgam ", "Galvanized ", "Flawed ")
FAMILIAS_EXTRA = {
    "Umbral Fiber": "Steel Fiber",
    "Galvanized Chamber": "Split Chamber",
    "Galvanized Diffusion": "Barrel Diffusion",
    "Galvanized Hell": "Hell's Chamber",
}
# Lo que no entra en una build basica: versiones caras o raras de conseguir.
PREFIJOS_NO_BASICOS = PREFIJOS_FAMILIA + ("Spectral ", "Vigilante ", "Augur ", "Gladiator ", "Hunter ",
                                          "Mecha ", "Synth ", "Tek ", "Strain ", "Sacrificial ", "Motus ",
                                          "Proton ", "Aero ", "Carnis ", "Jugulus ", "Saxum ")
RAREZAS_BASICAS = {"Common": 0, "Uncommon": 1, "Rare": 2}

# Con que mods se modifica cada tipo de equipo (campo "compat" de WFCD).
COMPAT = {
    "rifle": {"Rifle", "PRIMARY"},
    "escopeta": {"Shotgun", "PRIMARY"},
    "pistola": {"Pistol"},
    "cuerpo": {"Melee"},
    "archgun": {"Archgun"},
    "archmelee": {"Archmelee"},
    "warframe": {"WARFRAME", "AURA"},
}
# Huecos normales de mod (sin aura, exilus ni postura): 8 en todo lo que se evalua.
HUECOS = 8
# Critico o estado "alto" y "bajo" (wiki Critical_Hit / Status_Effect: por debajo del
# 10 % los mods de ese tipo apenas suben nada; del 20 % para arriba el arma vive de eso).
ALTO = 0.20
BAJO = 0.10


@dataclass
class Mod:
    item_id: int
    nombre_en: str
    nombre: str
    compat: str = ""
    rareza: str = ""
    polaridad: str = ""
    drenaje: float | None = None
    efecto: str = ""
    clases: set[str] = field(default_factory=set)
    elementos: list[str] = field(default_factory=list)
    corrupto: bool = False
    lineas: int = 0
    fuentes: int = 0

    @property
    def familia(self) -> str:
        return familia(self.nombre_en)


@dataclass
class Equipo:
    item_id: int
    nombre_en: str
    nombre: str
    categoria: str
    tipo: str = ""
    arma: dict = field(default_factory=dict)
    warframe: dict = field(default_factory=dict)

    @property
    def clase(self) -> str:
        return clase_de_equipo(self.categoria, self.tipo)


@dataclass
class Punto:
    """Una linea del resultado: que pasa y por que, y los mods de los que habla."""

    texto: str
    porque: str = ""
    ids: list[int] = field(default_factory=list)


@dataclass
class Evaluacion:
    equipo: Equipo | None
    bien: list[Punto] = field(default_factory=list)
    mal: list[Punto] = field(default_factory=list)
    sin_datos: bool = False


@dataclass
class Hueco:
    rol: str          # "Daño base", "Multidisparo"... (ya traducido)
    porque: str       # por que va ese mod, en una frase (ya traducido)
    mod: Mod | None
    tienes: bool = False
    en_objetivos: bool = False


@dataclass
class BuildBasica:
    equipo: Equipo | None
    huecos: list[Hueco] = field(default_factory=list)
    sin_datos: bool = False


def familia(nombre_en: str) -> str:
    """"Primed Continuity" y "Archon Continuity" -> "Continuity"; "Umbral Fiber" -> "Steel Fiber"."""
    nombre = " ".join((nombre_en or "").split())
    if nombre in FAMILIAS_EXTRA:
        return FAMILIAS_EXTRA[nombre].lower()
    for prefijo in PREFIJOS_FAMILIA:
        if nombre.lower().startswith(prefijo.lower()):
            return nombre[len(prefijo):].lower()
    return nombre.lower()


def clase_de_equipo(categoria: str | None, tipo: str | None) -> str:
    """"rifle", "escopeta", "pistola", "cuerpo", "archgun", "archmelee", "warframe" u "otro"."""
    categoria, tipo = categoria or "", tipo or ""
    if categoria == "Warframes":
        return "warframe" if tipo in ("Warframe", "") else "otro"
    if categoria == "Primary":
        if tipo == "Shotgun":
            return "escopeta"
        # Las armas de companero (robóticas) llevan mods de rifle.
        return "rifle" if tipo in ("Rifle", "Sniper", "Bow", "Launcher", "Companion Weapon", "") else "otro"
    if categoria == "Secondary":
        return "pistola"
    if categoria == "Melee":
        return "cuerpo" if tipo in ("Melee", "") else "otro"
    if categoria == "Arch-Gun":
        return "archgun"
    if categoria == "Arch-Melee":
        return "archmelee"
    return "otro"


def analizar_efecto(texto: str) -> tuple[set[str], list[str], bool, int]:
    """(clases, elementos en orden, corrupto, lineas) del efecto al rango maximo."""
    clases: set[str] = set()
    elementos: list[str] = []
    corrupto = False
    lineas = [l.strip() for l in (texto or "").split("\n") if l.strip()]
    for linea in lineas:
        m = RE_LINEA.match(linea)
        if not m:
            bajo = linea.lower()
            if "resistance to" in bajo or "damage resistance" in bajo:
                clases.add("resistencia")
            elif any(p in bajo for p in ("lethal damage", "damage on health to energy", "invulnerable",
                                         "health orbs grant")):
                clases.add("aguante")
            continue
        signo, resto = m.groups()
        if signo == "-":
            corrupto = True
            for clase, regla in REGLAS_CLASE:
                if regla.match(resto):
                    clases.add("menos_" + clase)
            continue
        if RE_FACCION.match(resto):
            clases.add("faccion")
            continue
        if RE_DANO_BASE.match(resto):
            clases.add("dano_base")
            continue
        elemento = next((e for e in ELEMENTOS if re.match(rf"^{e}\b", resto, re.I)), None)
        if elemento:
            clases.add("elemento")
            elementos.append(elemento)
            continue
        if re.search(r"Damage Resistance|Resistance to", resto, re.I):
            clases.add("resistencia")
            continue
        for clase, regla in REGLAS_CLASE:
            if regla.match(resto):
                clases.add(clase)
                break
    return clases, elementos, corrupto, len(lineas)


# -- lectura del indice ----------------------------------------------------------------------

def _detalles(con: sqlite3.Connection, item_id: int) -> dict:
    try:
        fila = con.execute("SELECT datos FROM detalles WHERE item_id = ?", (item_id,)).fetchone()
    except sqlite3.Error:
        return {}
    if not fila:
        return {}
    try:
        datos = json.loads(fila[0])
    except (TypeError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _nombre(nombre_es: str | None, nombre_en: str | None, con: sqlite3.Connection | None = None,
            item_id: int | None = None) -> str:
    """El nombre como lo ensena el juego: con `con` e `item_id`, en el idioma del juego
    (datos/nombres_juego.py); sin ellos, castellano o ingles segun la interfaz."""
    if es_castellano():
        respaldo = nombre_es or nombre_en or ""
    else:
        respaldo = nombre_en or nombre_es or ""
    if con is not None and item_id:
        return nombres_juego.nombre(con, item_id, respaldo)
    return respaldo


def _mod_desde(item_id: int, nombre_en: str, nombre_es: str | None, datos: dict, fuentes: int = 0,
               con: sqlite3.Connection | None = None) -> Mod:
    info = datos.get("mod") or datos.get("arcano") or {}
    efectos = (info.get("efecto") or {}).get("en") or []
    efecto = efectos[-1] if efectos else ""
    clases, elementos, corrupto, lineas = analizar_efecto(efecto)
    compat = info.get("compat") or ""
    if compat == "AURA":
        clases.add("aura")
    return Mod(item_id=item_id, nombre_en=nombre_en or "", nombre=_nombre(nombre_es, nombre_en, con, item_id), compat=compat,
               rareza=info.get("rareza") or "", polaridad=info.get("polaridad") or "", drenaje=info.get("drenaje"),
               efecto=efecto, clases=clases, elementos=elementos, corrupto=corrupto, lineas=lineas, fuentes=fuentes)


def cargar_mod(con: sqlite3.Connection, item_id: int) -> Mod | None:
    try:
        fila = con.execute("SELECT nombre_en, nombre_es FROM items WHERE id = ?", (item_id,)).fetchone()
    except sqlite3.Error:
        return None
    if not fila:
        return None
    return _mod_desde(item_id, fila[0], fila[1], _detalles(con, item_id), con=con)


def cargar_equipo(con: sqlite3.Connection, item_id: int) -> Equipo | None:
    try:
        fila = con.execute("SELECT nombre_en, nombre_es, categoria, tipo FROM items WHERE id = ?",
                           (item_id,)).fetchone()
    except sqlite3.Error:
        return None
    if not fila:
        return None
    datos = _detalles(con, item_id)
    return Equipo(item_id=item_id, nombre_en=fila[0] or "", nombre=_nombre(fila[1], fila[0], con, item_id), categoria=fila[2] or "",
                  tipo=fila[3] or "", arma=datos.get("arma") or {}, warframe=datos.get("warframe") or {})


# -- ¿esta bien mi build? ---------------------------------------------------------------------

def _lista(mods: list[Mod]) -> str:
    return ", ".join(m.nombre for m in mods)


def _con(mods: list[Mod], clase: str) -> list[Mod]:
    return [m for m in mods if clase in m.clases]


def combinar_elementos(mods: list[Mod]) -> list[tuple[str, list[str]]]:
    """Los elementos de los mods en el orden de los huecos, combinados de dos en dos como
    hace el juego: el primero se junta con el siguiente distinto que pueda combinarse.
    Devuelve [("Viral", ["Cold", "Toxin"]), ("Heat", ["Heat"])]."""
    orden: list[str] = []
    for m in mods:
        for e in m.elementos:
            if e not in orden:
                orden.append(e)
    salida: list[tuple[str, list[str]]] = []
    usados: set[int] = set()
    for i, e in enumerate(orden):
        if i in usados:
            continue
        pareja = next((j for j in range(i + 1, len(orden)) if j not in usados), None)
        if pareja is not None:
            usados.update({i, pareja})
            salida.append((COMBINACIONES[frozenset({e, orden[pareja]})], [e, orden[pareja]]))
        else:
            usados.add(i)
            salida.append((e, [e]))
    return salida


def _texto_elementos(combinados: list[tuple[str, list[str]]]) -> str:
    partes = []
    for resultado, origen in combinados:
        nombre = t(NOMBRE_ELEMENTO[resultado])
        if len(origen) == 2:
            partes.append(f"{nombre} ({t(NOMBRE_ELEMENTO[origen[0]])} + {t(NOMBRE_ELEMENTO[origen[1]])})")
        else:
            partes.append(nombre)
    return ", ".join(partes)


def evaluar(con: sqlite3.Connection, equipo_id: int | None, mods_ids: list[int], arcanos_ids: list[int] | None = None,
            capacidad: tuple[int, int] | None = None) -> Evaluacion:
    """Evalua la build leida: `mods_ids` son los mods equipados en el orden de los huecos."""
    equipo = cargar_equipo(con, equipo_id) if equipo_id else None
    ev = Evaluacion(equipo=equipo)
    mods = [m for m in (cargar_mod(con, i) for i in mods_ids) if m is not None]
    if equipo is None:
        ev.mal.append(Punto(t("No sé qué warframe o arma es."),
                            t("Elígelo a mano en el buscador de la izquierda y vuelve a pulsar.")))
        return ev
    if mods and not any(m.efecto for m in mods):
        ev.sin_datos = True
        ev.mal.append(Punto(t("Faltan los datos de los mods."),
                            t("Actualiza los datos del juego en Ajustes > Datos y vuelve a probar.")))
        return ev
    _reglas_comunes(ev, mods, capacidad)
    clase = equipo.clase
    if clase == "warframe":
        _reglas_warframe(con, ev, equipo, mods, arcanos_ids or [])
    elif clase in ("rifle", "escopeta", "pistola", "archgun"):
        _reglas_arma(con, ev, equipo, mods, dispara=True)
    elif clase in ("cuerpo", "archmelee"):
        _reglas_arma(con, ev, equipo, mods, dispara=False)
    return ev


def _reglas_comunes(ev: Evaluacion, mods: list[Mod], capacidad: tuple[int, int] | None) -> None:
    # Versiones del mismo mod: el juego no deja llevarlas juntas, asi que casi seguro es
    # que Farmadex leyo mal una de las dos.
    vistos: dict[str, Mod] = {}
    for m in mods:
        otro = vistos.get(m.familia)
        if otro is not None and otro.item_id != m.item_id:
            ev.mal.append(Punto(t("{a} y {b} no se pueden llevar a la vez.", a=otro.nombre, b=m.nombre),
                                t("Son versiones del mismo mod. Si en el juego no lo ves así, Farmadex leyó mal uno."),
                                [otro.item_id, m.item_id]))
        vistos.setdefault(m.familia, m)
    normales = [m for m in mods if "aura" not in m.clases]
    if 0 < len(normales) < HUECOS:
        ev.mal.append(Punto(t("Farmadex ve {n} mods; caben {huecos}.", n=len(normales), huecos=HUECOS),
                            t("Si tienes huecos vacíos, rellénalos: un hueco vacío es fuerza que no aprovechas.")))
    elif len(normales) >= HUECOS:
        ev.bien.append(Punto(t("Tienes todos los huecos ocupados.")))
    if capacidad is not None:
        libre, total = capacidad
        if libre < 0:
            ev.mal.append(Punto(t("Te pasas de capacidad."), t("El juego no deja guardar así: quita o baja algún mod.")))
        elif libre >= 6 and total > 0:
            ev.mal.append(Punto(t("Te sobran {n} puntos de capacidad.", n=libre),
                                t("Puedes subir de rango algún mod o poner uno más fuerte.")))
        elif total > 0:
            ev.bien.append(Punto(t("Aprovechas casi toda la capacidad.")))
        if 0 < total < 60:
            ev.mal.append(Punto(t("La capacidad total es baja ({total}).", total=total),
                                t("Si aún no lleva un reactor o catalizador Orokin, con uno la duplicas.")))


def nombres_de(con: sqlite3.Connection, nombres_en: list[str]) -> str:
    """"Vitalidad, Redireccion, Fibra de acero": los nombres del juego en el idioma de la
    interfaz (del indice, no escritos a mano: asi coinciden con lo que se ve en el juego)."""
    salida = []
    for nombre_en in nombres_en:
        try:
            fila = con.execute("SELECT nombre_es, id FROM items WHERE nombre_en = ? AND categoria = 'Mods' "
                               "ORDER BY (nombre_es IS NULL) LIMIT 1", (nombre_en,)).fetchone()
        except sqlite3.Error:
            fila = None
        salida.append(_nombre(fila[0] if fila else None, nombre_en, con, fila[1] if fila else None))
    return ", ".join(salida)


def _reglas_warframe(con: sqlite3.Connection, ev: Evaluacion, equipo: Equipo, mods: list[Mod],
                     arcanos_ids: list[int]) -> None:
    aguante = [m for m in mods if m.clases & SUPERVIVENCIA]
    if aguante:
        ev.bien.append(Punto(t("Llevas mods para aguantar: {mods}.", mods=_lista(aguante)),
                             t("Salud, escudo, armadura o resistencias hacen que no caigas enseguida."),
                             [m.item_id for m in aguante]))
    else:
        ev.mal.append(Punto(t("No llevas nada para aguantar."),
                            t("Pon alguno de estos: {mods}. Sin ellos caerás enseguida.",
                              mods=nombres_de(con, ["Vitality", "Redirection", "Steel Fiber", "Adaptation"]))))
    habilidad = [m for m in mods if m.clases & HABILIDAD]
    if habilidad:
        ev.bien.append(Punto(t("Llevas mods para tus habilidades: {mods}.", mods=_lista(habilidad)),
                             t("Fuerza, duración, alcance y eficiencia son lo que hace fuertes tus poderes."),
                             [m.item_id for m in habilidad]))
    else:
        ev.mal.append(Punto(t("No llevas mods de habilidad."),
                            t("Estos hacen más fuertes tus poderes: {mods}.",
                              mods=nombres_de(con, ["Intensify", "Continuity", "Stretch", "Streamline"]))))
    menos_eficiencia = [m for m in mods if "menos_eficiencia" in m.clases]
    mas_eficiencia = [m for m in mods if "eficiencia" in m.clases]
    if menos_eficiencia and not mas_eficiencia:
        ev.mal.append(Punto(t("{mods} te quita eficiencia y no la compensas.", mods=_lista(menos_eficiencia)),
                            t("Tus poderes gastarán mucha energía: añade {mod} u otro mod que dé eficiencia.",
                              mod=nombres_de(con, ["Streamline"])),
                            [m.item_id for m in menos_eficiencia]))
    if any("aura" in m.clases for m in mods):
        aura = next(m for m in mods if "aura" in m.clases)
        ev.bien.append(Punto(t("Llevas aura ({mod}).", mod=aura.nombre),
                             t("El aura ayuda a todo el equipo y además te da capacidad."), [aura.item_id]))
    else:
        ev.mal.append(Punto(t("No veo ningún aura."),
                            t("El hueco de aura de arriba te da capacidad extra además de su efecto.")))
    if not arcanos_ids:
        ev.mal.append(Punto(t("No veo arcanos."),
                            t("Un warframe tiene dos huecos de arcano; si tienes alguno, póntelo.")))


def _reglas_arma(con: sqlite3.Connection, ev: Evaluacion, equipo: Equipo, mods: list[Mod], dispara: bool) -> None:
    arma = equipo.arma or {}
    # Sin el dato (arma nueva o incompleta en el indice) no se sabe si es de critico o de
    # estado: esas reglas se saltan en vez de decir "tiene poco critico" con un 0 inventado.
    critico = float(arma["critico"]) if arma.get("critico") is not None else None
    estado = float(arma["estado"]) if arma.get("estado") is not None else None
    base = _con(mods, "dano_base")
    if base:
        ev.bien.append(Punto(t("Llevas daño base: {mods}.", mods=_lista(base)),
                             t("Es el mod que más sube el daño de cualquier arma."), [m.item_id for m in base]))
    else:
        ejemplo = nombres_de(con, [{"pistola": "Hornet Strike", "cuerpo": "Pressure Point", "archmelee": "Pressure Point",
                                    "escopeta": "Point Blank", "archgun": "Rubedo-Lined Barrel"}.get(equipo.clase, "Serration")])
        ev.mal.append(Punto(t("Falta un mod de daño base (por ejemplo, {mod}).", mod=ejemplo),
                            t("Es el mod que más sube el daño de cualquier arma.")))
    if dispara:
        multi = _con(mods, "multidisparo")
        if multi:
            ev.bien.append(Punto(t("Llevas multidisparo: {mods}.", mods=_lista(multi)),
                                 t("Cada disparo sale doble o más: más daño sin gastar más munición."),
                                 [m.item_id for m in multi]))
        else:
            ev.mal.append(Punto(t("Falta un mod de multidisparo."),
                                t("Hace que cada disparo salga doble o más; es de lo que más daño da.")))
    con_elemento = _con(mods, "elemento")
    if con_elemento:
        combinados = combinar_elementos(con_elemento)
        ev.bien.append(Punto(t("Tus elementos quedan así: {elementos}.", elementos=_texto_elementos(combinados)),
                             t("Los elementos se juntan de dos en dos según el orden de los huecos."),
                             [m.item_id for m in con_elemento]))
    else:
        ev.mal.append(Punto(t("No llevas ningún mod de elemento."),
                            t("Calor, frío, electricidad o toxina suman mucho daño; dos juntos dan un elemento más fuerte.")))
    de_critico = [m for m in mods if m.clases & {"crit_prob", "crit_dano"}]
    if critico is None:
        pass
    elif critico >= ALTO:
        if de_critico:
            ev.bien.append(Punto(t("Tu arma es de crítico y llevas mods de crítico: {mods}.", mods=_lista(de_critico)),
                                 t("Con crítico alto, estos mods multiplican el daño."), [m.item_id for m in de_critico]))
        else:
            ev.mal.append(Punto(t("Tu arma es de crítico ({valor} %) y no llevas mods de crítico.", valor=round(critico * 100)),
                                t("Con crítico alto, subir la probabilidad y el daño crítico multiplica el daño.")))
    elif critico < BAJO and de_critico:
        ev.mal.append(Punto(t("Sobra: {mods} (tu arma tiene poco crítico, {valor} %).", mods=_lista(de_critico),
                              valor=round(critico * 100)),
                            t("Subir un crítico tan bajo apenas se nota; ese hueco rinde más con otro mod."),
                            [m.item_id for m in de_critico]))
    de_estado = [m for m in mods if "estado" in m.clases]
    solo_estado = [m for m in de_estado if "elemento" not in m.clases]
    if estado is None:
        pass
    elif estado >= ALTO:
        if de_estado or len(con_elemento) >= 2:
            ev.bien.append(Punto(t("Tu arma es de estado y la aprovechas."),
                                 t("Con estado alto, los elementos y la probabilidad de estado aplican más efectos.")))
        else:
            ev.mal.append(Punto(t("Tu arma es de estado ({valor} %) y casi no llevas elementos ni estado.",
                                  valor=round(estado * 100)),
                                t("Con estado alto, cada elemento aplica efectos que debilitan al enemigo.")))
    elif estado < BAJO and solo_estado:
        ev.mal.append(Punto(t("Sobra: {mods} (tu arma tiene poco estado, {valor} %).", mods=_lista(solo_estado),
                              valor=round(estado * 100)),
                            t("Con un estado tan bajo, subirlo apenas se nota."), [m.item_id for m in solo_estado]))


# -- build basica ------------------------------------------------------------------------------

_CACHE_MODS: dict[int, list[Mod]] = {}


def _todos_los_mods(con: sqlite3.Connection) -> list[Mod]:
    # Los nombres van dentro: otro idioma del juego es otra lista.
    clave = (id(con), nombres_juego.idioma())
    if clave in _CACHE_MODS:
        return _CACHE_MODS[clave]
    fuentes: dict[int, int] = {}
    try:
        fuentes = dict(con.execute("SELECT item_id, COUNT(*) FROM fuentes GROUP BY item_id"))
    except sqlite3.Error:
        pass
    mods = []
    try:
        filas = con.execute(
            "SELECT i.id, i.nombre_en, i.nombre_es, i.tipo, d.datos FROM items i JOIN detalles d ON d.item_id = i.id"
            " WHERE i.categoria = 'Mods'").fetchall()
    except sqlite3.Error:
        filas = []
    for item_id, nombre_en, nombre_es, tipo, datos in filas:
        if tipo and "Riven" in tipo:
            continue
        try:
            d = json.loads(datos)
        except (TypeError, ValueError):
            continue
        mods.append(_mod_desde(item_id, nombre_en, nombre_es, d if isinstance(d, dict) else {}, fuentes.get(item_id, 0),
                               con=con))
    _CACHE_MODS.clear()
    _CACHE_MODS[clave] = mods
    return mods


def olvidar_cache() -> None:
    _CACHE_MODS.clear()


def es_basico(m: Mod) -> bool:
    """Un mod comun y facil de conseguir: sin versiones Prime/Umbral/Arconte..., sin
    efectos negativos, de rareza comun, poco comun o rara y que salga en algun sitio."""
    if m.rareza not in RAREZAS_BASICAS or m.corrupto or m.fuentes <= 0:
        return False
    return not any(m.nombre_en.lower().startswith(p.lower()) for p in PREFIJOS_NO_BASICOS)


def _elegir(candidatos: list[Mod], clase: str, compat: set[str], elemento: str | None = None,
            puro: bool = True, excluir: set[str] | None = None) -> Mod | None:
    excluir = excluir or set()
    validos = [m for m in candidatos
               if m.compat in compat and clase in m.clases and es_basico(m) and m.familia not in excluir
               and (not puro or m.lineas == 1)
               and (elemento is None or m.elementos == [elemento])]
    if not validos:
        return None
    # El mas facil: rareza mas baja y, a igualdad, el que sale en mas sitios.
    return min(validos, key=lambda m: (RAREZAS_BASICAS[m.rareza], -m.fuentes, m.nombre_en))


def build_basica(con: sqlite3.Connection, equipo_id: int, tengo: set[int] | None = None,
                 en_objetivos: set[int] | None = None) -> BuildBasica:
    """Una build de inicio con mods comunes para ese warframe o arma, segun sus estadisticas."""
    tengo, en_objetivos = tengo or set(), en_objetivos or set()
    equipo = cargar_equipo(con, equipo_id)
    salida = BuildBasica(equipo=equipo)
    if equipo is None:
        return salida
    mods = _todos_los_mods(con)
    if not mods:
        salida.sin_datos = True
        return salida
    clase = equipo.clase
    compat = COMPAT.get(clase)
    if not compat:
        return salida
    elegidos: list[tuple[str, str, Mod | None]] = []
    familias: set[str] = set()

    def poner(rol: str, porque: str, clase_mod: str, elemento: str | None = None, puro: bool = True) -> None:
        m = _elegir(mods, clase_mod, compat, elemento, puro, familias)
        if m is None and puro:
            m = _elegir(mods, clase_mod, compat, elemento, False, familias)
        if m is not None:
            familias.add(m.familia)
        elegidos.append((rol, porque, m))

    if clase == "warframe":
        wf = equipo.warframe or {}
        escudo, armadura = float(wf.get("escudo") or 0), float(wf.get("armadura") or 0)
        aura = _elegir_aura(mods)
        elegidos.append((t("Aura"), t("Ayuda a todo el equipo y te da capacidad extra."), aura))
        if aura:
            familias.add(aura.familia)
        poner(t("Salud"), t("Más vida para aguantar."), "salud")
        if escudo > 0 and armadura < 300:
            poner(t("Escudo"), t("Tu warframe tiene escudo: más escudo, más aguante."), "escudo")
        else:
            poner(t("Armadura"), t("Tu warframe tiene mucha armadura o nada de escudo: la armadura rinde más."), "armadura")
        poner(t("Fuerza"), t("Tus poderes hacen más."), "fuerza")
        poner(t("Duración"), t("Tus poderes duran más."), "duracion")
        poner(t("Alcance"), t("Tus poderes llegan más lejos."), "alcance_hab")
        poner(t("Eficiencia"), t("Tus poderes gastan menos energía."), "eficiencia")
        poner(t("Energía"), t("Más energía para usar poderes."), "energia")
        if escudo > 0 and armadura < 300:
            poner(t("Armadura"), t("Menos daño en la vida."), "armadura")
        else:
            poner(t("Escudo"), t("Algo de escudo extra."), "escudo")
    else:
        arma = equipo.arma or {}
        critico, estado = float(arma.get("critico") or 0), float(arma.get("estado") or 0)
        dispara = clase in ("rifle", "escopeta", "pistola", "archgun")
        poner(t("Daño base"), t("El que más sube el daño."), "dano_base")
        if dispara:
            poner(t("Multidisparo"), t("Cada disparo sale doble o más."), "multidisparo")
        else:
            poner(t("Velocidad de ataque"), t("Golpeas más rápido."), "cadencia")
        if critico >= ALTO:
            poner(t("Probabilidad crítica"), t("Tu arma es de crítico: más críticos."), "crit_prob")
            poner(t("Daño crítico"), t("Tu arma es de crítico: críticos más fuertes."), "crit_dano")
        # Viral (frio + toxina) mas calor: una combinacion que sirve contra casi todo.
        poner(t("Frío"), t("Con Toxina hace Viral, que sirve contra casi todo."), "elemento", "Cold")
        poner(t("Toxina"), t("Con Frío hace Viral, que sirve contra casi todo."), "elemento", "Toxin")
        poner(t("Calor"), t("Un elemento más que quema y debilita la armadura."), "elemento", "Heat")
        if estado >= ALTO:
            poner(t("Probabilidad de estado"), t("Tu arma es de estado: aplica más efectos."), "estado")
        huecos_libres = HUECOS - len(elegidos)
        if huecos_libres > 0 and dispara:
            poner(t("Cadencia"), t("Disparas más rápido."), "cadencia")
        huecos_libres = HUECOS - len(elegidos)
        if huecos_libres > 0:
            poner(t("Electricidad"), t("Un elemento más."), "elemento", "Electricity")
        huecos_libres = HUECOS - len(elegidos)
        if huecos_libres > 0 and critico < ALTO:
            poner(t("Probabilidad de estado"), t("Más efectos de los elementos."), "estado")
    for rol, porque, m in elegidos[:HUECOS + (1 if clase == "warframe" else 0)]:
        salida.huecos.append(Hueco(rol=rol, porque=porque, mod=m,
                                   tienes=bool(m and (m.item_id in tengo or _misma_familia_en(m, tengo, mods))),
                                   en_objetivos=bool(m and m.item_id in en_objetivos)))
    return salida


def _misma_familia_en(m: Mod, tengo: set[int], mods: list[Mod]) -> bool:
    """Si tienes el mismo mod con otro id (WFCD repite algunos, "Bane Of Corpus")."""
    return any(o.item_id in tengo and o.nombre_en == m.nombre_en for o in mods)


def _elegir_aura(mods: list[Mod]) -> Mod | None:
    """Un aura facil que sirve a cualquiera: regeneracion de energia o de salud del equipo."""
    auras = [m for m in mods if "aura" in m.clases and es_basico(m)]
    for patron in (r"Energy Regen", r"Health Regen"):
        buenas = [m for m in auras if re.search(patron, m.efecto, re.I)]
        if buenas:
            return max(buenas, key=lambda m: (m.fuentes, m.nombre_en))
    return max(auras, key=lambda m: (m.fuentes, m.nombre_en)) if auras else None
