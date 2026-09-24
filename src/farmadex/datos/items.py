"""Importacion del catalogo de warframe-items y consultas de ficha."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from ..registro_log import obtener

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


def _nombre(valor) -> str | None:
    texto = _texto(valor)
    if not texto:
        return texto
    limpio = RE_ETIQUETA.sub("", texto).strip()
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


class ImportadorItems:
    """Vuelca warframe-items en las tablas items / nodos / reliquia_recompensas."""

    def __init__(self, con: sqlite3.Connection, i18n: dict, idiomas_extra: dict[str, dict] | None = None):
        self.con = con
        self.i18n = i18n
        # Nombres en otros idiomas (fr, de, pt, it, pl): {idioma: {unique_name: {"name": ...}}}.
        # Van a la tabla items_nombres, aparte de nombre_en/nombre_es que no se tocan.
        self.idiomas_extra = idiomas_extra or {}
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

    def _es(self, unique_name: str) -> tuple[str | None, str | None]:
        trad = self.i18n.get(unique_name) or {}
        return _nombre(trad.get("name")), _texto(trad.get("description"))

    def _extra(self, unique_name: str) -> dict[str, str]:
        """Nombre de este objeto en cada idioma de IDIOMAS_EXTRA que lo traiga."""
        salida = {}
        for idioma, datos in self.idiomas_extra.items():
            nombre = _nombre((datos.get(unique_name) or {}).get("name"))
            if nombre:
                salida[idioma] = nombre
        return salida

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
        if clave and clave not in self.alias:
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
            nombre = _nombre(obj.get("name"))
            if not unico or not nombre:
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

            nombre_es, desc_es = self._es(unico)
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
            self._registrar_alias(nombre, item_id)
            self._guardar_nombres_idioma(item_id, self._extra(unico))
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

    def _importar_componente(
        self, comp: dict, padre_id: int, padre_en: str, padre_es: str | None, categoria: str
    ) -> None:
        unico = _texto(comp.get("uniqueName"))
        nombre = _nombre(comp.get("name"))
        if not unico or not nombre:
            return
        nombre_es, desc_es = self._es(unico)
        # Desde el formato nuevo WFCD traduce tambien las piezas, pero con el nombre entero
        # ("Chasis de Ash Prime"). Aqui la pieza lleva solo su parte ("Chasis") porque la
        # busqueda, el OCR y la interfaz le anteponen el padre; con el nombre entero saldria
        # "Ash Prime Chasis de Ash Prime". Se queda el del glosario, como antes.
        del_catalogo = unico in self.catalogo_piezas
        if nombre_es and (del_catalogo or self._nombra_al_padre(nombre_es, padre_en, padre_es)):
            nombre_es = None
        nombre_es = nombre_es or self.componentes_es.get(nombre)
        recetas = self.recetas_por_ingrediente.setdefault(unico, set())
        primera_vez = not recetas
        recetas.add(padre_id)
        if primera_vez:
            self.componentes_por_nombre.setdefault(nombre, [])
        item_id = self._insertar(
            {
                "unique_name": unico,
                "nombre_en": nombre,
                "nombre_es": nombre_es,
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
        if primera_vez:
            self.componentes_por_nombre[nombre].append(item_id)
        # Nombre en fr/de/pt/it/pl: primero el de WFCD si lo trae (raro en piezas),
        # si no el del glosario de componentes de ese idioma ("Chassis" -> "Châssis").
        padre_idioma = self.nombres_extra_por_item.get(padre_id, {})
        nombres_idioma = {
            idioma: texto
            for idioma, texto in self._extra(unico).items()
            if not del_catalogo and not self._nombra_al_padre(texto, padre_en, padre_idioma.get(idioma))
        }
        for idioma, palabras in self.componentes_extra.items():
            if idioma not in nombres_idioma and palabras.get(nombre):
                nombres_idioma[idioma] = palabras[nombre]
        self._guardar_nombres_idioma(item_id, nombres_idioma)
        # Alias con los que drop-data nombra las piezas: "Ash Prime Chassis Blueprint".
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
        _avisar_era(canonico.split()[0])
        clave = normalizar(canonico)
        vaulted = _bandera(obj.get("vaulted"))

        item_id = self.reliquias.get(clave)
        if item_id is None:
            item_id = self._insertar(
                {
                    "unique_name": f"RELIQUIA/{canonico}",
                    "nombre_en": f"{canonico} Relic",
                    "nombre_es": f"Reliquia {canonico}",
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
