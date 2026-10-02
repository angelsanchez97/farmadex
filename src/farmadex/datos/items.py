"""Importacion del catalogo de warframe-items y consultas de ficha."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from ..registro_log import obtener
from . import detalles

log = obtener("items")

REFINAMIENTOS = ("Intact", "Exceptional", "Flawless", "Radiant")

# "Axi B1 Relic (Radiant)" / "Meso N11 Relic". La era no se limita a las conocidas:
# cuando DE saca una nueva (Requiem, Omnia, Vanguard...) tiene que entrar igual.
RE_RELIQUIA_DROP = re.compile(
    r"^([A-Za-z]+)\s+(\S+)\s+Relic"
    r"(?:\s+\((Intact|Exceptional|Flawless|Radiant)\))?$",
    re.IGNORECASE,
)
ERAS_CONOCIDAS = ("Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia", "Vanguard")
_eras_avisadas: set[str] = set()


def _texto(valor) -> str | None:
    """Algunas descripciones vienen como lista de parrafos o como numero."""
    if valor is None or isinstance(valor, str):
        return valor
    if isinstance(valor, (list, tuple)):
        return "\n".join(_texto(v) or "" for v in valor).strip() or None
    return str(valor)


# "<ARCHWING> Agkuza", "<Shard_red_simple> Crimson Archon Shard": el juego mete etiquetas
# de icono en 75 nombres del catalogo. Sin quitarlas la ficha las ensena tal cual y las
# tablas de drops ("Crimson Archon Shard") no casan.
RE_ETIQUETA = re.compile(r"<[^<>]*>\s*")
RE_ETIQUETA_SOLA = re.compile(r"<[^<>]*>")


def _nombre(valor) -> str | None:
    """El nombre como se lee en pantalla: sin etiquetas de icono y en una sola linea.

    Se quita la etiqueta y nada mas: al llevarse tambien el espacio de detras,
    "File-a-Style<RETRO_TM> Notepad" se quedaba en "File-a-StyleNotepad" en los idiomas
    que la llevan en medio. Y algunos nombres traen un salto de linea dentro (el tema de
    Gauss Prime, antes de "Redline"): los espacios y saltos seguidos quedan en uno.
    """
    texto = _texto(valor)
    if not texto:
        return texto
    limpio = " ".join(RE_ETIQUETA_SOLA.sub("", texto).split())
    return limpio or texto


def _numero(valor) -> float | None:
    """chance/standing: numero, o texto con el numero ("25.33", "25%"), o basura (None)."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, str):
        valor = valor.strip().rstrip("%").replace(",", ".")
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _bandera(valor) -> int | None:
    """vaulted/tradable llegan como bool, pero un volcado los ha traido como texto."""
    if valor is None:
        return None
    if isinstance(valor, str):
        return int(valor.strip().lower() in ("1", "true", "yes", "si"))
    try:
        return int(bool(valor))
    except (TypeError, ValueError):
        return None


def _fecha_salida(obj: dict) -> str | None:
    """'2026-09-23' de `releaseDate` o, si falta, de `introduced.date`; None si no hay.

    WFCD trae `introduced` como diccionario ({name, date, url, parent...}) y, en volcados
    viejos, a veces solo como texto con el nombre; se aceptan los dos.
    """
    fecha = _texto(obj.get("releaseDate"))
    introducido = obj.get("introduced")
    if not fecha and isinstance(introducido, dict):
        fecha = _texto(introducido.get("date"))
    fecha = (fecha or "")[:10]
    return fecha if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha) else None


def _actualizacion(obj: dict) -> str | None:
    """'Update 44.0' (o 'Hotfix 44.0.1'): en que actualizacion salio el objeto."""
    introducido = obj.get("introduced")
    if isinstance(introducido, dict):
        return _texto(introducido.get("name"))
    return _texto(introducido) if isinstance(introducido, str) else None


def _entero(valor) -> int | None:
    """ducats/itemCount: numero, o texto con el numero, o basura (None)."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def _lista(valor) -> list:
    """Solo los elementos que son objetos: una lista de cadenas no tumba la importacion."""
    if isinstance(valor, dict):
        valor = list(valor.values())
    return [v for v in valor if isinstance(v, dict)] if isinstance(valor, list) else []


def _avisar_era(era: str) -> None:
    if era.title() not in ERAS_CONOCIDAS and era not in _eras_avisadas:
        _eras_avisadas.add(era)
        log.warning("Era de reliquia nueva en los datos: %r (se importa igual)", era)


def normalizar(texto: str) -> str:
    """Minusculas, sin diacriticos ni signos, espacios colapsados."""
    import unicodedata

    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace("-", " ")
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def es_variante_menor(unique_name: str | None) -> bool:
    """Mod de principiante o intermedio ("Flawed Serration" en el juego) que en WFCD se
    llama igual que el mod de verdad."""
    return bool(unique_name) and ("/Beginner/" in unique_name or "/Intermediate/" in unique_name)


def nombre_canonico_reliquia(nombre: str) -> tuple[str, str] | None:
    """'Axi A7 Exceptional' -> ('Axi A7', 'Exceptional')."""
    partes = nombre.split()
    if len(partes) >= 2 and partes[-1] in REFINAMIENTOS:
        return " ".join(partes[:-1]), partes[-1]
    if len(partes) == 2:
        return nombre, "Intact"
    return None


# Las categorias con las que se ha probado la aplicacion. Una nueva no rompe nada:
# se importa y se avisa en el log, para decidir luego si es farmeable o adorno.
CATEGORIAS_CONOCIDAS = frozenset({
    "Warframes", "Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee", "Archwing",
    "Sentinels", "SentinelWeapons", "Pets", "Mods", "Arcanes", "Relics", "Resources", "Misc",
    "Gear", "Quests", "Skins", "Sigils", "Glyphs", "Fish", "Railjack", "Node", "Honoria",
})

# Una pieza de verdad ("Systems", "Barrel") pertenece a una sola receta; un recurso
# (Cryotic, Neurodes) es ingrediente de decenas. A partir de este numero de recetas
# distintas el "componente" se trata como recurso, tenga o no ficha propia.
UMBRAL_RECETAS_RECURSO = 3

# Lo que se guarda de los objetos de los demas catalogos para poder usarlos como
# ingrediente de una receta del formato nuevo (ver cargar_referencias). Solo lo que lee
# _importar_componente: guardar los objetos enteros eran cientos de MB para nada.
CAMPOS_INGREDIENTE = (
    "uniqueName", "name", "description", "imageName", "tradable", "ducats",
    "primeSellingPrice", "drops",
)
# Categorias cuyos objetos nunca son ingrediente de nada y no hace falta apuntar.
CATEGORIAS_SIN_INGREDIENTES = frozenset({"Relics", "Node"})


# Palabras que unen pieza y padre en los nombres del juego: "Pala superior de Daikyu
# Prime", "Chassis d'Ash Prime", "Telaio di ...", "Chassi do ...".
_UNIONES = ("de", "del", "d'", "du", "des", "di", "da", "do", "dos", "das", "von", "der")


# Signos con los que el juego separa el objeto de su pieza segun el idioma: "Ash Prime -
# Chassis" (frances, italiano), "Ash Prime: Chassis" (aleman, portugues, polaco) y
# "Equinox (Aspecto Noturno)".
_SEPARADORES = " -–—:,;"


def _suelto(texto: str | None) -> str | None:
    """La pieza a secas de lo que queda al quitar el objeto: "- Neuroptiques" ->
    "Neuroptiques", "(Aspecto Noturno)" -> "Aspecto Noturno". None si no queda nada."""
    parte = (texto or "").strip(_SEPARADORES)
    if parte.startswith("(") and parte.endswith(")"):
        parte = parte[1:-1].strip(_SEPARADORES)
    return parte or None


def _sin_padre(texto: str, *padres: str | None) -> str | None:
    """La parte de la pieza en un nombre completo: "Pala superior de Daikyu Prime" -> "Pala superior".

    Vale con el padre delante o detras ("Daikyu Prime Oberer Wurfarm") y con los signos
    que pone el juego entre los dos ("Ash Prime - Chassis", "Ash Prime: Chassis"). Si al
    quitarlo no queda nada, None (se usara el glosario).
    """
    for padre in padres:
        if not padre:
            continue
        # Como palabra entera si se puede: "War" no es el principio de "Warframe".
        m = re.search(r"(?<!\w)" + re.escape(padre) + r"(?!\w)", texto, re.IGNORECASE)
        pos = m.start() if m else texto.lower().find(padre.lower())
        if pos == -1:
            continue
        resto = _suelto(texto[:pos] + " " + texto[pos + len(padre):]) or ""
        palabras = resto.replace("’", "'").split()
        while palabras and palabras[-1].lower() in _UNIONES:
            palabras.pop()
        while palabras and palabras[0].lower() in _UNIONES:
            palabras.pop(0)
        if palabras and palabras[-1].lower().endswith("d'"):
            palabras[-1] = palabras[-1][:-2]
        parte = _suelto(" ".join(p for p in palabras if p))
        return parte[:1].upper() + parte[1:] if parte else None
    return None


# Las particulas que el lector de pantalla quita de lo leido antes de buscarlo (las
# mismas que PALABRAS_VACIAS de captura/ocr.py; aqui no se importa para no dar vueltas).
_VACIAS_DEL_LECTOR = frozenset({
    "de", "del", "la", "el", "los", "las", "of", "the", "du", "des", "le", "les", "l",
    "der", "die", "das", "dem", "den", "von", "fur", "do", "da", "dos", "o", "a", "di", "il", "lo", "gli",
})


def _se_lee_igual(completo: str, compuesto: str) -> bool:
    """Si el lector, al leer `completo` en pantalla ("Chasis de Ash Prime"), da de lleno
    con el nombre que el indice compone juntando padre y pieza ("Ash Prime Chasis").

    El lector quita las particulas de lo leido (menos la primera palabra y lo que va
    detras de "de") y compara sin importar el orden, pero el nombre compuesto las lleva
    todas: "Motor del Mazo del Lobo" no da con "Mazo del Lobo Motor". Cuando no se leen
    igual, el nombre completo se guarda aparte (tabla items_alias) para que case exacto.
    """
    palabras = normalizar(completo).split()
    leido = palabras[:1] + [
        p for i, p in enumerate(palabras[1:], 1)
        if p not in _VACIAS_DEL_LECTOR or palabras[i - 1] in ("de", "du", "des", "von")
    ]
    return sorted(leido) == sorted(normalizar(compuesto).split())


class ImportadorItems:
    """Vuelca warframe-items en las tablas items / nodos / reliquia_recompensas."""

    def __init__(self, con: sqlite3.Connection, i18n: dict, idiomas_extra: dict[str, dict] | None = None,
                 oficiales: dict[str, dict[str, str]] | None = None):
        self.con = con
        self.i18n = i18n
        # Nombres en otros idiomas (fr, de, pt, it, pl): {idioma: {unique_name: {"name": ...}}}.
        # Van a la tabla items_nombres, aparte de nombre_en/nombre_es que no se tocan.
        self.idiomas_extra = idiomas_extra or {}
        # Nombres tal como los publica DE (nombres_oficiales.py): {idioma: {unique_name:
        # nombre}}. Donde los hay mandan sobre los de WFCD; sin ellos todo va como antes.
        self.oficiales = oficiales or {}
        # De donde ha salido el nombre de cada objeto, por idioma, para saber cuantos NO
        # son el oficial: {"fr": {"oficial": 880, "wfcd": 16000, "glosario": 3, "sin": 40}}.
        self.origen_nombres: dict[str, dict[str, int]] = {}
        # Piezas ya importadas: item_id -> si llevan el nombre de su padre (True), el de
        # otro objeto (False: "Volt Neuroptics" dentro de la receta de Chroma) o no se sabe.
        self.pieza_de_su_padre: dict[int, bool | None] = {}
        # Palabras con las que el juego nombra las piezas en cada idioma extra, y en cuantos
        # objetos distintos sale cada una: {"it": {"Canna": {id, id...}}}.
        self.palabras_de_pieza: dict[str, dict[str, set[int]]] = {}
        self._hay_tabla_alias = bool(con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'items_alias'"
        ).fetchone())
        # El catalogo no traduce los nombres de las piezas ("Systems", "Barrel"):
        # se completan con el glosario para que la busqueda en espanol las encuentre.
        self.componentes_es = {
            en: es for en, es in con.execute("SELECT en, es FROM glosario WHERE dominio = 'componente'")
        }
        # Lo mismo para los idiomas extra: {idioma: {en: traducido}}, de glosario_idiomas.
        self.componentes_extra: dict[str, dict[str, str]] = {}
        for dominio, idioma, en, valor in con.execute(
            "SELECT dominio, idioma, en, valor FROM glosario_idiomas WHERE dominio = 'componente'"
        ):
            self.componentes_extra.setdefault(idioma, {})[en] = valor
        # nombre normalizado -> item_id, para que drop-data pueda casar por texto
        self.alias: dict[str, int] = {}
        # nombre canonico de reliquia normalizado -> item_id
        self.reliquias: dict[str, int] = {}
        # uniqueName de cada variante de reliquia -> (item_id canonico, refinamiento)
        self.variantes_reliquia: dict[str, tuple[int, str]] = {}
        # uniqueName de cada componente -> ids de las recetas que lo piden
        self.recetas_por_ingrediente: dict[str, set[int]] = {}
        # nombre de componente -> ids, para dar alias propio a los que no se repiten
        self.componentes_por_nombre: dict[str, list[int]] = {}
        # item_id -> {idioma: nombre}, para que un componente pueda nombrar a su padre
        # en su mismo idioma aunque el padre ya se haya insertado antes.
        self.nombres_extra_por_item: dict[int, dict[str, str]] = {}
        # Ids de los mods de principiante/intermedio que repiten el nombre del de verdad.
        self.variantes_menores: set[int] = set()
        # Formato nuevo de WFCD (2026-09-24): catalogo de piezas (Components.json) y el
        # resto de objetos, por uniqueName, para completar las referencias de las recetas.
        self.catalogo_piezas: dict[str, dict] = {}
        self.otros_objetos: dict[str, dict] = {}
        # Cuantas piezas han llegado como referencia y cuales no se han podido completar.
        self.referencias_vistas = 0
        self.referencias_sin_resolver: set[str] = set()

    # -- formato nuevo: piezas por referencia ----------------------------

    def cargar_referencias(self, piezas, rutas_catalogo=()) -> None:
        """Prepara lo necesario para leer las recetas del formato nuevo de WFCD.

        Desde el 2026-09-24 cada objeto ya no repite sus piezas enteras: solo trae
        {"uniqueName", "itemCount"} y el resto esta en Components.json (`piezas`). Los
        ingredientes que no son piezas (Celula orokin, la Bronco de la Akbronco) tampoco
        estan ahi sino en su categoria, asi que se apuntan tambien los objetos de los
        demas catalogos (`rutas_catalogo`). Con el formato antiguo no hace falta llamarla:
        las piezas llegan completas y no se consulta nada de esto.
        """
        for obj in _lista(piezas):
            unico = _texto(obj.get("uniqueName"))
            if unico:
                self.catalogo_piezas[unico] = obj
        for ruta in rutas_catalogo:
            if ruta.stem in CATEGORIAS_SIN_INGREDIENTES or not ruta.exists():
                continue
            try:
                with ruta.open(encoding="utf-8") as f:
                    objetos = json.load(f)
            except (OSError, ValueError) as e:
                log.warning("No se pudo leer %s para completar recetas: %s", ruta.name, e)
                continue
            for obj in _lista(objetos):
                unico = _texto(obj.get("uniqueName"))
                if unico and unico not in self.otros_objetos:
                    self.otros_objetos[unico] = {c: obj[c] for c in CAMPOS_INGREDIENTE if c in obj}

    def _pieza_completa(self, comp: dict) -> dict | None:
        """La pieza con todos sus datos, venga entera (formato antiguo) o por referencia.

        Se decide por contenido y pieza a pieza: si trae nombre es que viene entera. Asi
        valen los dos formatos y hasta una mezcla (un catalogo recien bajado y otro que se
        quedo de la vez anterior porque fallo su descarga).
        """
        if comp.get("name"):
            return comp
        unico = _texto(comp.get("uniqueName"))
        if not unico:
            return None
        self.referencias_vistas += 1
        base = self.catalogo_piezas.get(unico) or self.otros_objetos.get(unico)
        if base is None:
            self.referencias_sin_resolver.add(unico)
            return None
        # Lo de la receta (itemCount) manda sobre lo del catalogo.
        return {**base, **comp}

    @staticmethod
    def _nombra_al_padre(texto: str, *padres: str | None) -> bool:
        """"Chasis de Ash Prime" nombra a su padre; "Chasis" o "Celula orokin" no."""
        hueco = f" {normalizar(texto)} "
        return any(p and f" {normalizar(p)} " in hueco for p in padres)

    # -- utilidades -----------------------------------------------------

    def _oficial(self, unique_name: str, idioma: str) -> str | None:
        """El nombre que publica DE para ese objeto en ese idioma, si se tiene."""
        return _nombre((self.oficiales.get(idioma) or {}).get(unique_name)) or None

    def _wfcd(self, unique_name: str, idioma: str) -> str | None:
        """El nombre que trae WFCD en ese idioma (castellano o uno de los extra)."""
        datos = self.i18n if idioma == "es" else self.idiomas_extra.get(idioma) or {}
        entrada = datos.get(unique_name)
        return (_nombre(entrada.get("name")) or None) if isinstance(entrada, dict) else None

    def _idiomas(self) -> list[str]:
        """Los idiomas con tabla propia (items_nombres): todos menos castellano e ingles."""
        return [i for i in dict.fromkeys([*self.idiomas_extra, *self.oficiales]) if i not in ("es", "en")]

    def _contar(self, idioma: str, origen: str) -> None:
        cuenta = self.origen_nombres.setdefault(idioma, {})
        cuenta[origen] = cuenta.get(origen, 0) + 1

    def _mejor(self, unique_name: str, idioma: str, anteriores: list | None = None) -> str | None:
        """El nombre de un objeto en un idioma: el de DE si se tiene; si no, el de WFCD.
        Si los dos existen y no dicen lo mismo, el de WFCD se apunta en `anteriores`."""
        oficial, wfcd = self._oficial(unique_name, idioma), self._wfcd(unique_name, idioma)
        self._contar(idioma, "oficial" if oficial else "wfcd" if wfcd else "sin")
        if oficial and wfcd and anteriores is not None and normalizar(oficial) != normalizar(wfcd):
            anteriores.append((idioma, wfcd))
        return oficial or wfcd

    def _es(self, unique_name: str) -> tuple[str | None, str | None]:
        trad = self.i18n.get(unique_name)
        trad = trad if isinstance(trad, dict) else {}
        return self._mejor(unique_name, "es"), _texto(trad.get("description"))

    def _extra(self, unique_name: str, anteriores: list | None = None) -> dict[str, str]:
        """Nombre de este objeto en cada idioma extra que lo traiga."""
        salida = {}
        for idioma in self._idiomas():
            nombre = self._mejor(unique_name, idioma, anteriores)
            if nombre:
                salida[idioma] = nombre
        return salida

    def _guardar_alias(self, item_id: int, idioma: str, nombre: str, origen: str) -> None:
        """Otro nombre del objeto (tabla items_alias): "oficial" es como lo pinta el juego
        cuando no sale de juntar padre y pieza; "anterior", el que tenia el indice antes."""
        if self._hay_tabla_alias and nombre:
            self.con.execute(
                "INSERT OR IGNORE INTO items_alias (item_id, idioma, nombre, origen) VALUES (?, ?, ?, ?)",
                (item_id, idioma, nombre, origen),
            )

    def _guardar_nombres_idioma(self, item_id: int, nombres: dict[str, str]) -> None:
        self.nombres_extra_por_item[item_id] = nombres
        for idioma, nombre in nombres.items():
            if nombre:
                self.con.execute(
                    "INSERT OR REPLACE INTO items_nombres (item_id, idioma, nombre) VALUES (?, ?, ?)",
                    (item_id, idioma, nombre),
                )

    def _registrar_alias(self, nombre: str, item_id: int) -> None:
        clave = normalizar(nombre)
        if not clave:
            return
        previo = self.alias.get(clave)
        if previo is None or (previo in self.variantes_menores and item_id not in self.variantes_menores):
            # "Serration" es a la vez la Sierra defectuosa (Beginner, sale antes en Mods.json)
            # y la de verdad: las tablas de drops hablan de la de verdad.
            self.alias[clave] = item_id

    def _insertar(self, fila: dict) -> int:
        columnas = ", ".join(fila)
        marcas = ", ".join("?" for _ in fila)
        # Las fuentes traen a veces listas o diccionarios donde se espera texto.
        valores = tuple(
            _texto(v) if isinstance(v, (list, tuple, dict)) else v for v in fila.values()
        )
        cur = self.con.execute(
            f"INSERT OR IGNORE INTO items ({columnas}) VALUES ({marcas})", valores
        )
        if cur.lastrowid and cur.rowcount:
            return cur.lastrowid
        fila_existente = self.con.execute(
            "SELECT id, padre_id FROM items WHERE unique_name = ?", (fila["unique_name"],)
        ).fetchone()
        item_id, padre_actual = fila_existente
        if padre_actual is not None and fila.get("padre_id") is None:
            # Un recurso (Celula orokin, Neurodos, Nitain) aparece antes como
            # ingrediente de la receta de una warframe que como objeto propio en
            # Resources.json. Al llegar su ficha de verdad se le quita el padre y
            # pasa a su categoria; si no, "nitain" sale como pieza de Vauban Prime.
            columnas = [c for c in fila if c != "unique_name"]
            asignaciones = ", ".join(f"{c} = ?" for c in columnas)
            claves = list(fila)
            self.con.execute(
                f"UPDATE items SET {asignaciones}, padre_id = NULL, item_count = NULL"
                " WHERE id = ?",
                tuple(valores[claves.index(c)] for c in columnas) + (item_id,),
            )
        return item_id

    # -- importacion ----------------------------------------------------

    def importar_categoria(self, ruta: Path) -> int:
        with ruta.open(encoding="utf-8") as f:
            objetos = json.load(f)
        if not isinstance(objetos, list):
            return 0

        cuenta = 0
        categorias_vistas: set[str] = set()
        for obj in _lista(objetos):
            unico = _texto(obj.get("uniqueName"))
            nombre_wfcd = _nombre(obj.get("name"))
            if not unico or not nombre_wfcd:
                continue
            categoria = _texto(obj.get("category")) or ruta.stem
            categorias_vistas.add(categoria)

            if categoria == "Node":
                self._importar_nodo(obj)
                continue
            if categoria == "Relics":
                self._importar_reliquia(obj)
                cuenta += 1
                continue

            # El nombre en ingles de WFCD es el del juego con las mayusculas cambiadas y,
            # en algunos, la etiqueta quitada sin dejar el espacio ("KinemantikA/V
            # Receiver"); si DE da el suyo, es ese. El de WFCD sigue valiendo para casar
            # las tablas de drops y para buscar.
            anteriores: list[tuple[str, str]] = []
            oficial_en = self._oficial(unico, "en")
            nombre = oficial_en or nombre_wfcd
            self._contar("en", "oficial" if oficial_en else "wfcd")
            if normalizar(nombre) != normalizar(nombre_wfcd):
                anteriores.append(("en", nombre_wfcd))
            trad = self.i18n.get(unico)
            desc_es = _texto(trad.get("description")) if isinstance(trad, dict) else None
            nombre_es = self._mejor(unico, "es", anteriores)
            item_id = self._insertar(
                {
                    "unique_name": unico,
                    "nombre_en": nombre,
                    "nombre_es": nombre_es,
                    "descripcion_es": desc_es,
                    "categoria": categoria,
                    "tipo": _texto(obj.get("type")),
                    "es_prime": int(bool(obj.get("isPrime")) or "Prime" in nombre),
                    "comerciable": _bandera(obj.get("tradable")) or 0,
                    "vaulted": _bandera(obj.get("vaulted")),
                    "vault_fecha": _texto(obj.get("vaultDate") or obj.get("estimatedVaultDate")),
                    "imagen": _texto(obj.get("imageName")),
                    "wiki_url": _texto(obj.get("wikiaUrl")),
                    "ducados": _entero(obj.get("ducats") or obj.get("primeSellingPrice")),
                    "fecha_salida": _fecha_salida(obj),
                    "actualizacion": _actualizacion(obj),
                }
            )
            if es_variante_menor(unico):
                self.variantes_menores.add(item_id)
            self._registrar_alias(nombre, item_id)
            if nombre_wfcd != nombre:
                self._registrar_alias(nombre_wfcd, item_id)
            self._guardar_nombres_idioma(item_id, self._extra(unico, anteriores))
            for idioma, anterior in anteriores:
                self._guardar_alias(item_id, idioma, anterior, "anterior")
            # Estadisticas, efecto por rango y habilidades: solo para la ficha.
            detalles.guardar(self.con, item_id, detalles.extraer(obj, categoria, self.i18n.get(unico)))
            cuenta += 1

            for drop in _lista(obj.get("drops")):
                self._guardar_drop(item_id, drop)

            for comp in _lista(obj.get("components")):
                pieza = self._pieza_completa(comp)
                if pieza is not None:
                    self._importar_componente(pieza, item_id, nombre, nombre_es, categoria)

        nuevas = categorias_vistas - CATEGORIAS_CONOCIDAS
        if nuevas:
            # Se importan igual; la busqueda las trata como "lo demas" hasta que se
            # decida donde van. Queda anotado para el siguiente ajuste.
            log.warning("Categorias nuevas en %s (se importan igual): %s", ruta.name, sorted(nuevas))
        return cuenta

    def _nombres_de_pieza(self, unico: str, nombre: str, padre_id: int, padre_en: str,
                          padre_es: str | None, del_catalogo: bool, compartida: bool) -> dict:
        """Como se llama una pieza en cada idioma, dentro de la receta de ese padre.

        El juego pinta el nombre entero ("Chasis de Ash Prime", "Ash Prime - Châssis",
        "Ash Prime: Powłoka") y el indice guarda solo la parte de la pieza ("Chasis",
        "Châssis", "Powłoka"), porque la busqueda, el lector y la interfaz le anteponen
        el padre. El nombre entero sale de DE (`oficiales`) y, en castellano, tambien de
        WFCD; en los demas idiomas WFCD lo trae ya sin el objeto ("- Châssis"), que es
        justo la parte. Solo si no hay ni lo uno ni lo otro se usa el glosario propio,
        que no siempre dice lo que el juego ("Neuroptique" por "Neuroptiques").

        Devuelve {"es": parte, "extra": {idioma: parte}, "alias": [(idioma, nombre,
        origen)], "del_padre": True/False/None, "completo_en": nombre entero en ingles}.
        """
        padre_en_idioma = {"en": padre_en, "es": padre_es, **self.nombres_extra_por_item.get(padre_id, {})}
        idiomas = self._idiomas()
        completos: dict[str, str] = {}
        for idioma in ("en", "es", *idiomas):
            completo = self._oficial(unico, idioma)
            if not completo and idioma == "es" and del_catalogo:
                completo = self._wfcd(unico, "es")  # en castellano WFCD lo deja entero
            if completo:
                completos[idioma] = completo

        def nombra(idioma: str) -> bool | None:
            if idioma not in completos:
                return None
            return self._nombra_al_padre(completos[idioma], padre_en, padre_en_idioma.get(idioma))

        # Si la pieza lleva el nombre de este padre. No lo lleva la de otro objeto que
        # tambien entra en esta receta ("Volt Neuroptics" en la de Chroma) ni la que tiene
        # nombre propio ("War Blade" de Broken War, "Decurion Barrel" de Dual Decurion).
        vistos = [v for v in (nombra("es"), nombra("en")) if v is not None]
        del_padre = True if any(vistos) else False if vistos else None
        propio = del_padre is False and not compartida

        partes: dict[str, str | None] = {}
        alias: list[tuple[str, str, str]] = []
        for idioma in ("es", *idiomas):
            wfcd = self._wfcd(unico, idioma)
            texto = completos.get(idioma) or wfcd
            padre_l = padre_en_idioma.get(idioma)
            parte = None
            if texto and self._nombra_al_padre(texto, padre_en, padre_l):
                parte = _sin_padre(texto, padre_l, padre_en)
            elif texto and (not del_catalogo or propio):
                parte = texto
            elif idioma != "es" and wfcd and wfcd != completos.get(idioma) and del_padre is not False:
                parte = _suelto(wfcd)  # WFCD ya le quito el objeto: "- Neuroptiques"
            origen = "oficial" if self._oficial(unico, idioma) else "wfcd"
            glosario = self.componentes_es.get(nombre) if idioma == "es" else (
                self.componentes_extra.get(idioma) or {}).get(nombre)
            if not parte and glosario:
                parte, origen = glosario, "glosario"
            elif (parte and glosario and idioma != "es" and del_catalogo
                  and normalizar(parte) != normalizar(glosario)):
                # Lo que el indice decia hasta ahora: se sigue reconociendo y buscando.
                alias.append((idioma, f"{padre_l or padre_es or padre_en} {glosario}", "anterior"))
            self._contar(idioma, origen if parte else "sin")
            partes[idioma] = parte
            if parte and idioma != "es" and del_catalogo and del_padre and origen != "glosario":
                self.palabras_de_pieza.setdefault(idioma, {}).setdefault(parte, set()).add(padre_id)
            if propio and parte and origen != "glosario":
                completos.setdefault(idioma, parte)  # con nombre propio, la parte ES el nombre entero
        self._contar("en", "oficial" if "en" in completos else "wfcd")
        if propio:
            completos.setdefault("en", nombre)

        # El nombre entero, cuando el lector no daria con el juntando padre y pieza. Solo
        # el de una pieza de verdad con su nombre de verdad: una palabra suelta ("Chasis")
        # como nombre de un objeto concreto haria casar cualquier "Chasis" con el.
        if del_catalogo and not (compartida and del_padre is False):
            for idioma, completo in completos.items():
                if len(normalizar(completo).split()) < 2:
                    continue
                if idioma == "en":
                    compuesto = f"{padre_en} {nombre}"
                elif idioma == "es":
                    compuesto = f"{padre_es} {partes['es']}" if padre_es and partes["es"] else partes["es"]
                else:
                    compuesto = (f"{padre_en_idioma.get(idioma) or padre_es or padre_en} {partes[idioma]}"
                                 if partes[idioma] else None)
                if not compuesto or not _se_lee_igual(completo, compuesto):
                    alias.append((idioma, completo, "oficial"))
        return {"es": partes.pop("es"), "extra": {i: p for i, p in partes.items() if p}, "alias": alias,
                "del_padre": del_padre, "completo_en": self._oficial(unico, "en")}

    def _importar_componente(
        self, comp: dict, padre_id: int, padre_en: str, padre_es: str | None, categoria: str
    ) -> None:
        unico = _texto(comp.get("uniqueName"))
        nombre = _nombre(comp.get("name"))
        if not unico or not nombre:
            return
        trad = self.i18n.get(unico)
        desc_es = _texto(trad.get("description")) if isinstance(trad, dict) else None
        # Desde el formato nuevo WFCD traduce tambien las piezas con el nombre entero que
        # pinta el juego ("Pala superior de Daikyu Prime"). La pieza lleva solo su parte
        # porque la busqueda, el OCR y la interfaz le anteponen el padre, asi que se le
        # quita el padre ("Pala superior"). Antes se tiraba y se usaba el glosario propio
        # ("Extremidad superior", "Agarre"), que no es lo que dice el juego: el OCR leia
        # "Pala Superior De Daikyu Prime" y no lo reconocia.
        del_catalogo = unico in self.catalogo_piezas
        padres = comp.get("parentUniqueNames")
        compartida = isinstance(padres, list) and len(padres) > 1
        nombres = self._nombres_de_pieza(unico, nombre, padre_id, padre_en, padre_es, del_catalogo, compartida)
        recetas = self.recetas_por_ingrediente.setdefault(unico, set())
        primera_vez = not recetas
        recetas.add(padre_id)
        if primera_vez:
            self.componentes_por_nombre.setdefault(nombre, [])
        item_id = self._insertar(
            {
                "unique_name": unico,
                "nombre_en": nombre,
                "nombre_es": nombres["es"],
                "descripcion_es": desc_es,
                "categoria": categoria,
                "tipo": "Componente",
                "es_prime": int("Prime" in padre_en),
                "comerciable": _bandera(comp.get("tradable")) or 0,
                "imagen": _texto(comp.get("imageName")),
                "padre_id": padre_id,
                "item_count": _entero(comp.get("itemCount")),
                "ducados": _entero(comp.get("ducats") or comp.get("primeSellingPrice")),
            }
        )
        # Un objeto con ficha propia que ademas es ingrediente (el Fragmento de inyector de
        # antisuero, Broken War para War) conserva sus nombres: los de pieza son solo la
        # parte ("Fragment") y pisaban el entero en los idiomas de items_nombres.
        es_pieza = self.con.execute("SELECT padre_id FROM items WHERE id = ?", (item_id,)).fetchone()[0] is not None
        guardar_nombres = primera_vez and es_pieza
        if primera_vez:
            self.componentes_por_nombre[nombre].append(item_id)
            self.pieza_de_su_padre[item_id] = nombres["del_padre"]
        elif (compartida and del_catalogo and nombres["del_padre"]
              and self.pieza_de_su_padre.get(item_id) is False):
            # La pieza se vio antes en la receta de otro objeto y se quedo colgando de el:
            # las Neuropticas de Volt salian como pieza de Chroma y la Hoja de Wrath como
            # "Pride Hoja". Su padre es el objeto del que lleva el nombre.
            cambiada = self.con.execute(
                "UPDATE items SET padre_id = ?, nombre_es = ?, es_prime = ?, categoria = ?"
                " WHERE id = ? AND padre_id IS NOT NULL AND tipo = 'Componente'",
                (padre_id, nombres["es"], int("Prime" in padre_en), categoria, item_id),
            ).rowcount
            if cambiada:
                self.con.execute("DELETE FROM items_nombres WHERE item_id = ?", (item_id,))
                if self._hay_tabla_alias:
                    self.con.execute("DELETE FROM items_alias WHERE item_id = ?", (item_id,))
                self.pieza_de_su_padre[item_id] = True
                guardar_nombres = True
        # La receta se apunta aparte: si luego el ingrediente pasa a recurso pierde el padre.
        self.con.execute(
            "INSERT OR REPLACE INTO recetas (padre_id, item_id, cantidad) VALUES (?, ?, ?)",
            (padre_id, item_id, _entero(comp.get("itemCount"))),
        )
        if guardar_nombres:
            self._guardar_nombres_idioma(item_id, nombres["extra"])
            for idioma, texto, origen in nombres["alias"]:
                self._guardar_alias(item_id, idioma, texto, origen)
        # Alias con los que drop-data nombra las piezas: "Ash Prime Chassis Blueprint". El
        # nombre entero de DE va primero; el compuesto solo si la pieza es de este padre
        # ("Wrath Blade" es de Wrath aunque tambien entre en la receta de Pride: con el
        # compuesto, "Wrath Blade" acababa apuntando a la hoja de Pride).
        if nombres["completo_en"]:
            self._registrar_alias(nombres["completo_en"], item_id)
            if not nombres["completo_en"].lower().endswith("blueprint"):
                self._registrar_alias(f"{nombres['completo_en']} Blueprint", item_id)
        if nombres["del_padre"] is not False or not del_catalogo:
            self._registrar_alias(f"{padre_en} {nombre}", item_id)
            if not nombre.lower().endswith("blueprint"):
                # Con el componente "Blueprint" saldria "Equinox Blueprint Blueprint", y a ese
                # alias se le pegaban por parecido las piezas de Equinox que no existen aqui.
                self._registrar_alias(f"{padre_en} {nombre} Blueprint", item_id)

        if not primera_vez:
            # El catalogo repite la misma lista de drops en cada receta que pide el
            # ingrediente: Celula orokin acumulaba 43.000 fuentes para 262 distintas.
            return
        for drop in _lista(comp.get("drops")):
            if isinstance(drop.get("type"), str):
                self._registrar_alias(drop["type"], item_id)
            self._guardar_drop(item_id, drop)

    def promocionar_ingredientes(self, umbral: int = UMBRAL_RECETAS_RECURSO) -> int:
        """Saca de las piezas lo que en realidad es un recurso.

        Se llama al terminar de importar todos los catalogos. Un componente que piden
        `umbral` o mas recetas distintas no es exclusivo de ninguna: se le quita el padre
        y pasa a la categoria Resources (Cryotic llegaba como pieza de una primaria y
        Nitain como pieza de Vauban Prime). Los que ya tenian ficha propia en Misc
        (Cryotic, Neurodes) tambien pasan a Resources para que la busqueda los ponga por
        delante de los mods y adornos. Sus fuentes no se tocan: cuelgan del mismo id.
        Devuelve cuantos objetos se han cambiado.
        """
        cambiados = 0
        for unico, recetas in self.recetas_por_ingrediente.items():
            if len(recetas) < umbral:
                continue
            fila = self.con.execute(
                "SELECT id, padre_id, categoria, tipo FROM items WHERE unique_name = ?", (unico,)
            ).fetchone()
            if fila is None:
                continue
            item_id, padre_id, categoria, tipo = fila
            if padre_id is None and categoria != "Misc":
                # Ficha propia en su categoria de verdad (Resources, Gear, Melee): nada que hacer.
                continue
            self.con.execute(
                "UPDATE items SET padre_id = NULL, item_count = NULL, categoria = 'Resources',"
                " tipo = ? WHERE id = ?",
                ("Resource" if tipo == "Componente" else tipo, item_id),
            )
            # Su plano (Orokin Cell Blueprint) se quedaba en Misc mientras el recurso
            # pasaba a Resources: la busqueda lo ponia en otro grupo que a su padre.
            self.con.execute(
                "UPDATE items SET categoria = 'Resources' WHERE padre_id = ?", (item_id,)
            )
            cambiados += 1
        return cambiados

    def registrar_palabras_de_pieza(self, minimo: int = 2) -> int:
        """Apunta en `glosario_idiomas` las palabras con que el juego nombra las piezas en
        cada idioma ("Canna", "Castello", "Lufa", "Neuroptiques"...).

        El lector de pantalla saca de ahi las palabras que no identifican a ningun objeto
        por si solas (las de pieza de cada idioma). Antes solo conocia las del glosario
        propio, que en italiano y polaco no existe: con "Lama" como palabra cualquiera,
        un "Llama Prime" mal leido se parecia lo bastante a "Gram Prime Lama". Solo
        entran las que salen en `minimo` objetos o mas: una pieza unica no es generica.
        Las del glosario propio no se tocan (van con otra clave). Devuelve cuantas.
        """
        apuntadas = 0
        for idioma, palabras in self.palabras_de_pieza.items():
            for parte, padres in palabras.items():
                if len(padres) >= minimo:
                    apuntadas += self.con.execute(
                        "INSERT OR IGNORE INTO glosario_idiomas (dominio, idioma, en, valor)"
                        " VALUES ('componente', ?, ?, ?)",
                        (idioma, f"~{parte}", parte),
                    ).rowcount
        return apuntadas

    def registrar_piezas_con_nombre_propio(self) -> int:
        """Alias a secas para las piezas cuyo nombre ya identifica al objeto.

        Las tablas de drops dicen "Kavasa Prime Band" o "War Blade", no "Kavasa Prime
        Kubrow Collar Kavasa Prime Band" ni "Broken War War Blade", que es el unico
        alias que tenian. Solo se da a los nombres de mas de una palabra que no repite
        ninguna otra pieza ("Upper Limb" lo tienen todos los arcos) y que ningun objeto
        con ficha propia use ya. Se llama al terminar todos los catalogos y devuelve
        cuantos alias ha anadido.
        """
        anadidos = 0
        for nombre, ids in self.componentes_por_nombre.items():
            if len(ids) != 1 or " " not in nombre.strip():
                continue
            for texto in (nombre, f"{nombre} Blueprint"):
                clave = normalizar(texto)
                if clave and clave not in self.alias:
                    self.alias[clave] = ids[0]
                    anadidos += 1
        return anadidos

    def _importar_reliquia(self, obj: dict) -> None:
        """Las 4 variantes de refinamiento se colapsan en un unico objeto 'reliquia'."""
        partido = nombre_canonico_reliquia(_nombre(obj.get("name")) or "")
        if not partido:
            return
        canonico, refinamiento = partido
        if canonico.endswith(" Relic"):
            # "Requiem Relic": el comodin de "una Requiem al azar" que trae WFCD. Salia en
            # Buscar como "Requiem Relic Relic" con premios mezclados; no es una reliquia.
            return
        _avisar_era(canonico.split()[0])
        clave = normalizar(canonico)
        vaulted = _bandera(obj.get("vaulted"))

        item_id = self.reliquias.get(clave)
        if item_id is None:
            # El nombre del juego en cada idioma, que viene en cada variante ("Reliquia
            # Réquiem I", "Relique Lith A1", "Lith-Relikt: A1"). Solo se acepta si nombra
            # esta misma reliquia (lleva su codigo); en castellano, ademas, el compuesto
            # de siempre se conserva si el del juego dijera otra cosa.
            variante = _texto(obj.get("uniqueName")) or ""
            codigo = normalizar(canonico.split()[-1])
            nombre_es = f"Reliquia {canonico}"
            es_juego = self._mejor(variante, "es")
            if es_juego and normalizar(es_juego) == normalizar(nombre_es):
                nombre_es = es_juego
            en_otros = {
                idioma: texto for idioma, texto in self._extra(variante).items()
                if codigo in normalizar(texto).split()
            }
            item_id = self._insertar(
                {
                    "unique_name": f"RELIQUIA/{canonico}",
                    "nombre_en": f"{canonico} Relic",
                    "nombre_es": nombre_es,
                    "categoria": "Relics",
                    "tipo": "Relic",
                    "comerciable": _bandera(obj.get("tradable")) or 0,
                    "vaulted": vaulted,
                    "vault_fecha": _texto(obj.get("vaultDate")),
                    "imagen": _texto(obj.get("imageName")),
                    "wiki_url": _texto(obj.get("wikiaUrl")),
                }
            )
            self.reliquias[clave] = item_id
            self._registrar_alias(f"{canonico} Relic", item_id)
            self._registrar_alias(canonico, item_id)
            self._guardar_nombres_idioma(item_id, en_otros)
            if es_juego and normalizar(es_juego) != normalizar(nombre_es) and codigo in normalizar(es_juego).split():
                self._guardar_alias(item_id, "es", es_juego, "oficial")
        elif vaulted is not None:
            self.con.execute(
                "UPDATE items SET vaulted = COALESCE(vaulted, ?) WHERE id = ?",
                (vaulted, item_id),
            )

        self.variantes_reliquia[_texto(obj.get("uniqueName")) or ""] = (item_id, refinamiento)

        for premio in _lista(obj.get("rewards")):
            info = premio.get("item")
            if not isinstance(info, dict) or not isinstance(info.get("uniqueName"), str):
                continue
            self.con.execute(
                "INSERT OR REPLACE INTO reliquia_recompensas "
                "(reliquia_id, refinamiento, item_id, rareza, probabilidad) "
                "SELECT ?, ?, id, ?, ? FROM items WHERE unique_name = ?",
                (
                    item_id,
                    refinamiento,
                    _texto(premio.get("rarity")),
                    _numero(premio.get("chance")),
                    info["uniqueName"],
                ),
            )

    def _guardar_drop(self, item_id: int, drop: dict) -> None:
        """Convierte un drop de warframe-items en una fila de 'fuentes'."""
        lugar = (_texto(drop.get("location")) or "").strip()
        if not lugar:
            return
        m = RE_RELIQUIA_DROP.match(lugar)
        if m:
            _avisar_era(m.group(1))
            canonico = f"{m.group(1).title()} {m.group(2).upper()}"
            self.con.execute(
                "INSERT INTO fuentes (item_id, tipo, origen_texto, refinamiento, rareza, "
                "probabilidad, datos_extra) VALUES (?, 'reliquia', ?, ?, ?, ?, ?)",
                (
                    item_id,
                    lugar,
                    (m.group(3) or "Intact").title(),
                    _texto(drop.get("rarity")),
                    _numero(drop.get("chance")),
                    json.dumps({"reliquia": canonico}),
                ),
            )
            return
        self.con.execute(
            "INSERT INTO fuentes (item_id, tipo, origen_texto, rotacion, rareza, probabilidad) "
            "VALUES (?, 'otro', ?, ?, ?, ?)",
            (item_id, lugar, _texto(drop.get("rotation")), _texto(drop.get("rarity")),
             _numero(drop.get("chance"))),
        )

    def _importar_nodo(self, obj: dict) -> None:
        nombre = _texto(obj.get("name")) or ""
        planeta = _texto(obj.get("systemName")) or ""
        # En algunos volcados el nombre ya viene como "Abaddon (Europa)".
        m = re.match(r"^(.*)\s+\((.*)\)$", nombre)
        if m:
            nombre, planeta = m.group(1), planeta or m.group(2)
        self.con.execute(
            "INSERT OR IGNORE INTO nodos (unique_name, nombre_en, planeta_en, nivel_min, "
            "nivel_max, clave_drops) VALUES (?, ?, ?, ?, ?, ?)",
            (
                obj.get("uniqueName"),
                nombre,
                planeta,
                obj.get("minEnemyLevel"),
                obj.get("maxEnemyLevel"),
                f"{planeta}/{nombre}",
            ),
        )

    def enlazar_reliquias(self) -> int:
        """Resuelve origen_id de las fuentes de tipo reliquia usando el nombre canonico."""
        pendientes = self.con.execute(
            "SELECT id, datos_extra FROM fuentes WHERE tipo = 'reliquia' AND origen_id IS NULL"
        ).fetchall()
        enlazadas = 0
        for fid, extra in pendientes:
            try:
                canonico = json.loads(extra or "{}").get("reliquia", "")
            except json.JSONDecodeError:
                continue
            destino = self.reliquias.get(normalizar(canonico))
            if destino:
                self.con.execute("UPDATE fuentes SET origen_id = ? WHERE id = ?", (destino, fid))
                enlazadas += 1
        # Lo que sigue sin reliquia nombra una que no existe en el catalogo
        # ("Requiem undefined Relic"): en la ficha solo saldria como hueco.
        huerfanas = self.con.execute(
            "DELETE FROM fuentes WHERE tipo = 'reliquia' AND origen_id IS NULL"
        ).rowcount
        if huerfanas:
            log.warning("Descartadas %d fuentes que nombran reliquias inexistentes", huerfanas)
        return enlazadas


# -- consultas para la interfaz -----------------------------------------


def ficha(con: sqlite3.Connection, item_id: int) -> dict:
    """Devuelve el objeto, su padre, sus componentes y sus fuentes agrupadas."""
    anterior = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        return _ficha(con, item_id)
    finally:
        # La conexion se comparte con la busqueda, que espera tuplas.
        con.row_factory = anterior


def _ficha(con: sqlite3.Connection, item_id: int) -> dict:
    item = con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        return {}
    item = dict(item)

    padre = None
    if item["padre_id"]:
        fila = con.execute("SELECT * FROM items WHERE id = ?", (item["padre_id"],)).fetchone()
        padre = dict(fila) if fila else None

    componentes = [
        dict(f)
        for f in con.execute(
            "SELECT * FROM items WHERE padre_id = ? ORDER BY nombre_en", (item_id,)
        )
    ]

    fuentes = [
        dict(f)
        for f in con.execute(
            """
            SELECT f.*, r.nombre_en AS reliquia_en, r.nombre_es AS reliquia_es,
                   r.vaulted AS reliquia_vaulted,
                   n.nombre_en AS nodo_en, n.nombre_es AS nodo_es,
                   n.planeta_en, n.planeta_es, n.mision_en, n.mision_es
              FROM fuentes f
              LEFT JOIN items r ON f.tipo = 'reliquia' AND r.id = f.origen_id
              LEFT JOIN nodos n ON f.tipo IN ('mision','llave','bounty') AND n.id = f.origen_id
             WHERE f.item_id = ?
             ORDER BY f.tipo, f.probabilidad DESC
            """,
            (item_id,),
        )
    ]

    return {"item": item, "padre": padre, "componentes": componentes, "fuentes": fuentes}
