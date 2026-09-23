"""Importacion de las tablas de drops oficiales (WFCD/warframe-drop-data).

Todos los nombres de esas tablas vienen en ingles. Se casan contra el mapa de
alias que deja el importador de warframe-items; lo que no casa se cuenta y se
registra en el log en vez de romper la importacion.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from rapidfuzz import fuzz, process as rf_process

from ..registro_log import obtener
from .items import _numero, _texto, normalizar
from .relaciones import rareza_reliquia

log = obtener("drops")

RE_SUFIJO_PLANETA = re.compile(r"\s+\([^)]*\)$")
# "200X Cubic Diodes": la cantidad va pegada al nombre en las tablas de recursos.
RE_CANTIDAD = re.compile(r"^\d+\s*X\s+", re.IGNORECASE)
RE_PARENTESIS = re.compile(r"\s*\([^)]*\)$")
# Recompensas que no son objetos del catalogo y no tiene sentido intentar casar.
RE_NO_ES_OBJETO = re.compile(
    r"^(\d+X\s+)?("
    r"[\d,.]+\s*(Endo|Credits( Cache)?|Kuva|H.llars( Cache)?)"  # "2X 3,000 Credits Cache"
    r"|Region Resource"
    r"|Return:\s*[\d,.]+"  # el credito que devuelve el Circuito
    r"|(\d+\s*Day\s+)?\w+(\s+Drop\s+Chance)?\s+Booster"  # "3 Day Affinity Booster"
    r")$",
    re.IGNORECASE,
)
# "Lith Q3 Relic (Radiant)": el nombre del objeto lleva pegado el refinamiento.
RE_RELIQUIA_REFINADA = re.compile(
    r"^(.*\bRelic)\s*\((Intact|Exceptional|Flawless|Radiant)\)$", re.IGNORECASE
)
# Con los datos al dia quedan sin casar unas decenas de nombres (Endo, creditos,
# recursos regionales). Por encima de esto, las tablas y el catalogo van desfasados.
UMBRAL_SIN_CASAR = 400


def _dicts(valor) -> list[dict]:
    """Solo los elementos que son objetos: una entrada rara no tumba la tabla entera."""
    if isinstance(valor, dict):
        valor = list(valor.values())
    return [v for v in valor if isinstance(v, dict)] if isinstance(valor, list) else []


def _nombre(premio: dict, *claves: str) -> str:
    for clave in claves:
        valor = premio.get(clave)
        if isinstance(valor, str) and valor:
            return valor
    return ""


class ImportadorDrops:
    def __init__(self, con: sqlite3.Connection, alias: dict[str, int]):
        self.con = con
        self.alias = alias
        self.claves_alias = list(alias.keys())
        self.sin_casar: dict[str, int] = {}
        # Un mismo nombre ("400 Endo") aparece cientos de veces; sin memoria,
        # cada aparicion repetia la busqueda difusa sobre 40.000 alias.
        self._memoria: dict[tuple[str, bool], int | None] = {}
        self.casados_difusos: dict[str, str] = {}
        self.nodos_creados = 0
        self.nodos = {
            normalizar(clave): nid
            for nid, clave in con.execute(
                "SELECT id, clave_drops FROM nodos WHERE clave_drops IS NOT NULL"
            )
        }
        self.nodos_por_nombre = {
            normalizar(nombre): nid
            for nid, nombre in con.execute("SELECT id, nombre_en FROM nodos")
        }

    # -- casado de nombres ----------------------------------------------

    def item_con_refinamiento(self, nombre: str) -> tuple[int | None, str | None]:
        """Separa '... Relic (Radiant)' en el objeto reliquia y su refinamiento."""
        m = RE_RELIQUIA_REFINADA.match(nombre or "")
        if m:
            return self.item_id(m.group(1), difuso=False), m.group(2).title()
        # Una reliquia que no esta en el catalogo no se casa por parecido: "Neo C10 Relic"
        # acababa como Neo C11, y la ruta de farmeo mandaba a sitios donde no sale.
        return self.item_id(nombre, difuso=not (nombre or "").endswith(" Relic")), None

    def item_id(self, nombre: str, difuso: bool = True) -> int | None:
        if not nombre or RE_NO_ES_OBJETO.match(nombre):
            return None
        clave_memoria = (nombre, difuso)
        if clave_memoria in self._memoria:
            destino = self._memoria[clave_memoria]
            if destino is None:
                self.sin_casar[nombre] = self.sin_casar.get(nombre, 0) + 1
            return destino
        destino = self._resolver_item(nombre, difuso)
        self._memoria[clave_memoria] = destino
        return destino

    def _resolver_item(self, nombre: str, difuso: bool) -> int | None:
        m = RE_RELIQUIA_REFINADA.match(nombre)
        if m:
            nombre = m.group(1)
        base = RE_CANTIDAD.sub("", nombre)
        clave = normalizar(base)
        # Los sindicatos escriben "Seeking Shuriken (Ash)" o "Vicious Bond (Companion)":
        # el parentesis sobra para casar. Y muchas tablas escriben "X Blueprint"
        # donde el catalogo dice solo "X".
        candidatas = [clave]
        sin_parentesis = normalizar(RE_PARENTESIS.sub("", base))
        if sin_parentesis and sin_parentesis != clave:
            candidatas.append(sin_parentesis)
        candidatas += [c.removesuffix(" blueprint") for c in candidatas if c.endswith(" blueprint")]
        for candidata in candidatas:
            destino = self.alias.get(candidata)
            if destino:
                return destino
        if difuso and len(clave) > 6:
            # token_sort_ratio y no WRatio: este casaba por trozos y daba por buena
            # "Equinox Day Chassis Blueprint" contra un alias de Equinox a secas.
            mejor = rf_process.extractOne(
                clave, self.claves_alias, scorer=fuzz.token_sort_ratio, score_cutoff=92
            )
            if mejor:
                self.casados_difusos[nombre] = mejor[0]
                return self.alias[mejor[0]]
        self.sin_casar[nombre] = self.sin_casar.get(nombre, 0) + 1
        return None

    def nodo_id(self, planeta: str, nodo: str) -> int | None:
        nodo_limpio = RE_SUFIJO_PLANETA.sub("", nodo).strip()
        return self.nodos.get(normalizar(f"{planeta}/{nodo_limpio}")) or self.nodos_por_nombre.get(
            normalizar(nodo_limpio)
        )

    def crear_nodo(self, planeta: str, nodo: str, modo: str | None) -> int | None:
        """Da de alta un nodo que DE no publica (Railjack, Duviri, Santuario...).

        Se queda con lo que dice la propia tabla de drops: nombre, planeta y modo
        de mision. El nombre en espanol no existe; el planeta se traduce al final.
        """
        nodo_limpio = RE_SUFIJO_PLANETA.sub("", nodo).strip()
        if not nodo_limpio or not planeta:
            return None
        clave = f"{planeta}/{nodo_limpio}"
        cur = self.con.execute(
            "INSERT OR IGNORE INTO nodos (unique_name, nombre_en, planeta_en, mision_en, "
            "clave_drops) VALUES (?, ?, ?, ?, ?)",
            (f"DROPS/{clave}", nodo_limpio, planeta, modo, clave),
        )
        if cur.rowcount:
            nid = cur.lastrowid
            self.nodos_creados += 1
        else:
            nid = self.con.execute(
                "SELECT id FROM nodos WHERE clave_drops = ?", (clave,)
            ).fetchone()[0]
        self.nodos[normalizar(clave)] = nid
        self.nodos_por_nombre.setdefault(normalizar(nodo_limpio), nid)
        return nid

    def traducir_nodos(self) -> None:
        """Rellena planeta_es y mision_es con el glosario; lo que no tenga traduccion queda en ingles."""
        self.con.execute(
            """
            UPDATE nodos SET planeta_es = COALESCE(
                (SELECT es FROM glosario WHERE dominio = 'planeta' AND en = nodos.planeta_en),
                planeta_es, planeta_en)
            WHERE planeta_es IS NULL OR planeta_es = planeta_en
            """
        )
        self.con.execute(
            """
            UPDATE nodos SET mision_es = COALESCE(
                (SELECT es FROM glosario WHERE dominio = 'mision' AND en = nodos.mision_en),
                mision_en)
            WHERE mision_en IS NOT NULL
            """
        )

    # Columnas numericas y de texto de 'fuentes': un "25%" o una lista donde se espera
    # un numero no debe colarse tal cual, porque la ficha hace float() sobre ello.
    _NUMERICAS = frozenset({"probabilidad", "probabilidad_enemigo", "standing"})
    _TEXTUALES = frozenset({"refinamiento", "rotacion", "etapa", "rareza"})

    def _fuente(self, item_id: int, tipo: str, origen_texto: str, **campos) -> None:
        for clave in list(campos):
            if clave in self._NUMERICAS:
                campos[clave] = _numero(campos[clave])
            elif clave in self._TEXTUALES:
                campos[clave] = _texto(campos[clave])
        columnas = ["item_id", "tipo", "origen_texto", *campos]
        valores = [item_id, tipo, origen_texto, *campos.values()]
        marcas = ", ".join("?" for _ in columnas)
        self.con.execute(
            f"INSERT INTO fuentes ({', '.join(columnas)}) VALUES ({marcas})", valores
        )

    # -- ficheros --------------------------------------------------------

    def mission_rewards(self, ruta: Path, tipo: str = "mision") -> None:
        datos = _leer(ruta)
        raiz = datos.get("missionRewards") if isinstance(datos, dict) else None
        raiz = raiz if isinstance(raiz, dict) else datos
        if not isinstance(raiz, dict):
            return
        for planeta, nodos in raiz.items():
            if not isinstance(nodos, dict):
                continue
            for nodo, info in nodos.items():
                if not isinstance(info, dict):
                    continue
                modo = info.get("gameMode")
                # "Terminus (Caches)" trae gameMode 'Caches': el modo del nodo solo
                # se toma de su entrada principal, sin sufijo.
                modo_nodo = modo if not RE_SUFIJO_PLANETA.search(nodo) else None
                nid = self.nodo_id(planeta, nodo) or self.crear_nodo(planeta, nodo, modo_nodo)
                if nid and modo_nodo:
                    self.con.execute(
                        "UPDATE nodos SET mision_en = COALESCE(mision_en, ?) WHERE id = ?",
                        (modo_nodo, nid),
                    )
                premios = info.get("rewards")
                grupos = premios.items() if isinstance(premios, dict) else [(None, premios or [])]
                for rotacion, lista in grupos:
                    for premio in _dicts(lista):
                        iid, refinamiento = self.item_con_refinamiento(
                            _nombre(premio, "itemName", "item")
                        )
                        if not iid:
                            continue
                        self._fuente(
                            iid,
                            tipo,
                            f"{planeta}/{nodo}",
                            origen_id=nid,
                            refinamiento=refinamiento,
                            rotacion=rotacion,
                            rareza=premio.get("rarity"),
                            probabilidad=premio.get("chance"),
                            datos_extra=json.dumps(
                                {"modo": modo, "evento": bool(info.get("isEvent"))}
                            ),
                        )

    def relics(self, ruta: Path) -> None:
        datos = _leer(ruta)
        lista = datos.get("relics") if isinstance(datos, dict) else datos
        for reliquia in _dicts(lista):
            nombre = f"{_nombre(reliquia, 'tier')} {_nombre(reliquia, 'relicName')}".strip()
            rid = self.item_id(f"{nombre} Relic", difuso=False)
            if not rid:
                continue
            refinamiento = _nombre(reliquia, "state") or "Intact"
            for premio in _dicts(reliquia.get("rewards")):
                iid = self.item_id(_nombre(premio, "itemName", "item"))
                if not iid:
                    continue
                # La columna "rarity" de WFCD viene casi siempre en "Uncommon": manda la probabilidad.
                rareza = rareza_reliquia(
                    refinamiento, _numero(premio.get("chance")), _texto(premio.get("rarity"))
                )
                self.con.execute(
                    "INSERT OR IGNORE INTO reliquia_recompensas "
                    "(reliquia_id, refinamiento, item_id, rareza, probabilidad) VALUES (?,?,?,?,?)",
                    (rid, refinamiento, iid, rareza, _numero(premio.get("chance"))),
                )
                existe = self.con.execute(
                    "SELECT 1 FROM fuentes WHERE item_id=? AND tipo='reliquia' AND origen_id=? "
                    "AND refinamiento=?",
                    (iid, rid, refinamiento),
                ).fetchone()
                if not existe:
                    self._fuente(
                        iid,
                        "reliquia",
                        f"{nombre} Relic ({refinamiento})",
                        origen_id=rid,
                        refinamiento=refinamiento,
                        rareza=rareza,
                        probabilidad=premio.get("chance"),
                    )

    def enemigos(self, ruta: Path, clave_item: str, clave_lista: str, clave_prob: str) -> None:
        """modLocations / blueprintLocations: item -> lista de enemigos."""
        datos = _leer(ruta)
        lista = datos.get(ruta.stem) if isinstance(datos, dict) else datos
        for fila in _dicts(lista):
            iid = self.item_id(_nombre(fila, clave_item))
            if not iid:
                continue
            for enemigo in _dicts(fila.get(clave_lista)):
                self._fuente(
                    iid,
                    "enemigo",
                    _nombre(enemigo, "enemyName") or "?",
                    probabilidad=enemigo.get("chance"),
                    probabilidad_enemigo=enemigo.get(clave_prob),
                )

    def bounties(self, ruta: Path, etiqueta: str) -> None:
        datos = _leer(ruta)
        lista = datos.get(ruta.stem) if isinstance(datos, dict) else datos
        for nivel in _dicts(lista):
            nombre_nivel = _nombre(nivel, "bountyLevel")
            premios = nivel.get("rewards") or {}
            grupos = premios.items() if isinstance(premios, dict) else [(None, premios)]
            for rotacion, entradas in grupos:
                for premio in _dicts(entradas):
                    iid = self.item_id(_nombre(premio, "itemName", "item"))
                    if not iid:
                        continue
                    self._fuente(
                        iid,
                        "bounty",
                        f"{etiqueta} {nombre_nivel}".strip(),
                        rotacion=rotacion,
                        etapa=premio.get("stage"),
                        rareza=premio.get("rarity"),
                        probabilidad=premio.get("chance"),
                    )

    def transitorias(self, ruta: Path) -> None:
        datos = _leer(ruta)
        lista = datos.get("transientRewards") if isinstance(datos, dict) else datos
        for objetivo in _dicts(lista):
            nombre = _nombre(objetivo, "objectiveName") or "?"
            for premio in _dicts(objetivo.get("rewards")):
                iid = self.item_id(_nombre(premio, "itemName", "item"))
                if not iid:
                    continue
                self._fuente(
                    iid,
                    "transitoria",
                    nombre,
                    rotacion=premio.get("rotation"),
                    rareza=premio.get("rarity"),
                    probabilidad=premio.get("chance"),
                )

    def recursos_por_enemigo(self, ruta: Path) -> None:
        """resourceByAvatar: cada enemigo/contenedor y los recursos que suelta."""
        datos = _leer(ruta)
        lista = datos.get(ruta.stem) if isinstance(datos, dict) else datos
        for fila in _dicts(lista):
            origen = _nombre(fila, "source", "enemyName") or "?"
            for premio in _dicts(fila.get("items")):
                iid = self.item_id(_nombre(premio, "item", "itemName"))
                if not iid:
                    continue
                self._fuente(
                    iid,
                    "enemigo",
                    origen,
                    rareza=premio.get("rarity"),
                    probabilidad=premio.get("chance"),
                )

    def sortie(self, ruta: Path) -> None:
        datos = _leer(ruta)
        lista = datos.get("sortieRewards") if isinstance(datos, dict) else datos
        for premio in _dicts(lista):
            iid = self.item_id(_nombre(premio, "itemName", "item"))
            if not iid:
                continue
            self._fuente(
                iid,
                "sortie",
                "Incursion (Sortie)",
                rareza=premio.get("rarity"),
                probabilidad=premio.get("chance"),
            )

    def sindicatos(self, ruta: Path) -> None:
        datos = _leer(ruta)
        raiz = datos.get("syndicate") or datos.get("syndicates") or datos
        if not isinstance(raiz, dict):
            return
        for sindicato, entradas in raiz.items():
            for entrada in _dicts(entradas):
                iid = self.item_id(_nombre(entrada, "item", "itemName"))
                if not iid:
                    continue
                self._fuente(
                    iid,
                    "sindicato",
                    sindicato,
                    rareza=entrada.get("rarity"),
                    probabilidad=entrada.get("chance"),
                    standing=entrada.get("standing"),
                    datos_extra=json.dumps({"lugar": entrada.get("place")}),
                )

    # -- orquestacion -----------------------------------------------------

    def importar_todo(self, rutas: dict[str, Path], progreso=None, datos: dict | None = None) -> None:
        """Importa cada tabla desde su fichero, o desde `datos[clave]` si viene ahi: lo
        que se toma de la tabla oficial de DE (ver tabla_oficial.preparar) ya leido."""
        datos = datos or {}
        pasos = [
            ("missionRewards", lambda r: self.mission_rewards(r), "Misiones"),
            ("keyRewards", lambda r: self.mission_rewards(r, tipo="llave"), "Llaves"),
            ("relics", lambda r: self.relics(r), "Reliquias"),
            (
                "modLocations",
                lambda r: self.enemigos(r, "modName", "enemies", "enemyModDropChance"),
                "Mods por enemigo",
            ),
            (
                "blueprintLocations",
                lambda r: self.enemigos(r, "itemName", "enemies", "enemyItemDropChance"),
                "Planos por enemigo",
            ),
            ("cetusBountyRewards", lambda r: self.bounties(r, "Contratos de Cetus"), "Cetus"),
            (
                "solarisBountyRewards",
                lambda r: self.bounties(r, "Contratos del Valle"),
                "Valle del Orbe",
            ),
            ("deimosRewards", lambda r: self.bounties(r, "Contratos de Deimos"), "Deimos"),
            (
                "entratiLabRewards",
                lambda r: self.bounties(r, "Laboratorio Entrati"),
                "Laboratorio Entrati",
            ),
            ("zarimanRewards", lambda r: self.bounties(r, "Contratos del Zariman"), "Zariman"),
            ("hexRewards", lambda r: self.bounties(r, "Contratos de Hollvania"), "Hollvania"),
            (
                "resourceByAvatar",
                lambda r: self.recursos_por_enemigo(r),
                "Recursos por enemigo",
            ),
            ("transientRewards", lambda r: self.transitorias(r), "Recompensas especiales"),
            ("sortieRewards", lambda r: self.sortie(r), "Incursion"),
            ("syndicates", lambda r: self.sindicatos(r), "Sindicatos"),
        ]
        total = len(pasos)
        for i, (clave, funcion, etiqueta) in enumerate(pasos, start=1):
            ruta = rutas.get(clave)
            if progreso:
                progreso(f"Importando drops: {etiqueta} ({i}/{total})", i - 1, total)
            if datos.get(clave) is not None:
                # Si falla a mitad se deshace lo suyo, y entra el fichero de WFCD sin
                # duplicar nada.
                nodos, por_nombre = dict(self.nodos), dict(self.nodos_por_nombre)
                self.con.execute("SAVEPOINT drops_de")
                try:
                    funcion(datos[clave])
                    self.con.execute("RELEASE SAVEPOINT drops_de")
                    continue
                except Exception:  # noqa: BLE001 - se prueba con el fichero de WFCD
                    self.con.execute("ROLLBACK TO SAVEPOINT drops_de")
                    self.con.execute("RELEASE SAVEPOINT drops_de")
                    self.nodos, self.nodos_por_nombre = nodos, por_nombre
                    log.exception("Fallo importando %s de la tabla oficial de DE; se usa WFCD", clave)
            if not ruta or not ruta.exists():
                log.warning("Falta el fichero de drops %s", clave)
                continue
            try:
                funcion(ruta)
            except Exception:  # noqa: BLE001 - una tabla rota no debe tumbar el indice
                log.exception("Fallo importando %s", clave)

        self.traducir_nodos()
        if self.nodos_creados:
            log.info("Nodos dados de alta desde las tablas de drops: %d", self.nodos_creados)
        if self.casados_difusos:
            ejemplos = list(self.casados_difusos.items())[:15]
            log.info(
                "Nombres casados por parecido: %d. Ejemplos: %s",
                len(self.casados_difusos),
                "; ".join(f"{a} -> {b}" for a, b in ejemplos),
            )
        if self.sin_casar:
            peores = sorted(self.sin_casar.items(), key=lambda p: -p[1])[:15]
            # El dia del parche las tablas de DE nombran objetos que WFCD aun no tiene:
            # con muchos sin casar se avisa mas alto, que es la senal de ese desfase.
            aviso = log.warning if len(self.sin_casar) > UMBRAL_SIN_CASAR else log.info
            aviso(
                "Nombres de drop-data sin casar: %d distintos. Ejemplos: %s",
                len(self.sin_casar),
                ", ".join(n for n, _ in peores),
            )


def _leer(ruta):
    """El JSON de un fichero, o los datos tal cual si ya vienen leidos (tabla de DE)."""
    if not isinstance(ruta, Path):
        return ruta
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)
