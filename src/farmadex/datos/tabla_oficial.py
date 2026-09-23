"""La tabla oficial de drops de Digital Extremes (warframe.com/droptables).

warframe-drop-data de WFCD es un volcado a JSON de esta misma pagina, pero puede pasar
meses sin regenerarse: en septiembre de 2026 seguia en junio y no conocia Citrine Prime
ni sus reliquias (Neo C11...), que DE ya habia publicado. Aqui se lee la pagina de DE
directamente y se deja con la misma forma que los JSON de WFCD (relics.json y
missionRewards.json), para que ImportadorDrops la trate igual.

Que se usa de aqui y que de WFCD:
  - Reliquias: se suman las que WFCD no tiene; si la tabla de DE es mas nueva, sus
    datos mandan en las que estan en las dos.
  - Misiones: si la tabla de DE es mas nueva y esta completa, sustituye entera a la de
    WFCD (una reliquia nueva hay que saber donde se farmea).
  - Piezas y reliquias que no estan en el catalogo de warframe-items: se crean objetos
    sinteticos (unique_name "/Farmadex/DE/..."; las reliquias, "RELIQUIA/...", como ya
    hace el catalogo) con su padre. Solo si ningun objeto de WFCD tiene ese nombre en
    ingles: cuando WFCD se pone al dia, gana su objeto y el sintetico no llega a existir.

Si la pagina no esta, no se entiende o sale incompleta se registra un aviso y todo sigue
como si no existiera.
"""

from __future__ import annotations

import html
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..registro_log import obtener
from .items import REFINAMIENTOS, normalizar

log = obtener("tabla_oficial")

# La URL a la que enlaza warframe.com/droptables. Es fija desde hace anos: warframe-drop-data
# descarga esta misma.
URL_TABLA_OFICIAL = (
    "https://warframe-web-assets.nyc3.cdn.digitaloceanspaces.com/uploads/cms/"
    "hnfvc0o3jnfvc873njb03enrf56.html"
)
NOMBRE_FICHERO = "tabla_oficial.html"

PREFIJO_SINTETICO = "/Farmadex/DE/"

# Por debajo de esta proporcion de nodos de WFCD, la tabla de misiones de DE se da por
# incompleta (pagina cortada, formato cambiado a medias) y no sustituye a nada.
PROPORCION_MINIMA_MISIONES = 0.8

_MESES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
RE_FECHA = re.compile(
    r"Last Update:\s*</b>\s*(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", re.IGNORECASE
)
RE_SECCION = re.compile(r'<h3 id="([^"]+)">')
RE_FILA = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
RE_CELDA = re.compile(r"<(th|td)[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
RE_ETIQUETA_HTML = re.compile(r"<[^>]+>")
# "Uncommon (25.33%)"
RE_RAREZA = re.compile(r"^(.*?)\s*\(\s*([\d.,]+)\s*%\s*\)$")
# "Neo C11 Relic (Intact)"
RE_CABECERA_RELIQUIA = re.compile(
    r"^([A-Za-z]+)\s+(\S+)\s+Relic\s+\((" + "|".join(REFINAMIENTOS) + r")\)$"
)
# "Event: Venus/Vesper Relay (Follie's Hunt) Extra": planeta, nodo, modo y si es la tabla
# "Extra". WFCD lo guarda como nodo "Vesper Relay (Extra)" con gameMode "Follie's Hunt",
# y los alijos como nodo "Terminus (Caches)" con gameMode "Caches".
RE_CABECERA_MISION = re.compile(
    r"^(?P<evento>Event:\s*)?(?P<planeta>[^/]+)/(?P<nodo>.+?)\s+\((?P<modo>[^()]+)\)(?P<extra>\s+Extra)?$"
)
RE_ROTACION = re.compile(r"^Rotation\s+(\S+)$", re.IGNORECASE)


class FormatoDesconocido(ValueError):
    """La pagina no tiene la forma que se espera: mejor no usarla que usarla mal."""


@dataclass
class TablaOficial:
    fecha: date | None
    # Con la forma de relics.json de WFCD: {"tier", "relicName", "state", "rewards": [...]}.
    reliquias: list[dict] = field(default_factory=list)
    # Con la forma de missionRewards.json: {planeta: {nodo: {"gameMode", "isEvent", "rewards"}}}.
    misiones: dict = field(default_factory=dict)


# -- lectura ------------------------------------------------------------------


def _texto_celda(crudo: str) -> str:
    return " ".join(html.unescape(RE_ETIQUETA_HTML.sub(" ", crudo)).split())


def _filas(seccion: str) -> list[tuple[str, list[str]]]:
    """Cada fila como ('th', [texto]) o ('td', [texto, texto]); las vacias se saltan."""
    salida = []
    for fila in RE_FILA.findall(seccion):
        celdas = RE_CELDA.findall(fila)
        if not celdas:
            continue
        textos = [_texto_celda(c[1]) for c in celdas]
        if not any(textos):
            continue  # fila separadora
        salida.append((celdas[0][0].lower(), textos))
    return salida


def _premio(textos: list[str]) -> dict | None:
    if len(textos) < 2 or not textos[0]:
        return None
    m = RE_RAREZA.match(textos[1])
    if not m:
        return None
    try:
        probabilidad = float(m.group(2).replace(",", "."))
    except ValueError:
        return None
    return {"itemName": textos[0], "rarity": m.group(1).strip(), "chance": probabilidad}


def fecha_publicacion(texto: str) -> date | None:
    """La fecha de "Last Update" de la cabecera; None si no esta o no se entiende."""
    m = RE_FECHA.search(texto[:20_000])
    if not m:
        return None
    mes = _MESES.get(m.group(2).lower())
    if not mes:
        return None
    try:
        return date(int(m.group(3)), mes, int(m.group(1)))
    except ValueError:
        return None


def _secciones(texto: str) -> dict[str, str]:
    marcas = list(RE_SECCION.finditer(texto))
    return {
        m.group(1): texto[m.end(): marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)]
        for i, m in enumerate(marcas)
    }


def _leer_reliquias(seccion: str) -> list[dict]:
    reliquias: list[dict] = []
    actual = None
    raras = 0
    for tipo, textos in _filas(seccion):
        if tipo == "th":
            m = RE_CABECERA_RELIQUIA.match(textos[0])
            if not m:
                raras += 1
                actual = None
                continue
            actual = {"tier": m.group(1), "relicName": m.group(2), "state": m.group(3), "rewards": []}
            reliquias.append(actual)
        elif actual is not None:
            premio = _premio(textos)
            if premio:
                actual["rewards"].append(premio)
            else:
                raras += 1
    reliquias = [r for r in reliquias if r["rewards"]]
    if not reliquias:
        raise FormatoDesconocido("la seccion de reliquias no trae ninguna reliquia")
    if raras > len(reliquias) * 0.05:
        raise FormatoDesconocido(f"{raras} filas de reliquias con forma desconocida")
    return reliquias


def _leer_misiones(seccion: str) -> dict:
    misiones: dict[str, dict] = {}
    info = None
    rotacion = None
    raras = 0
    for tipo, textos in _filas(seccion):
        if tipo == "th":
            rot = RE_ROTACION.match(textos[0])
            if rot and info is not None:
                rotacion = rot.group(1)
                if not isinstance(info["rewards"], dict):
                    # Premios antes de la primera rotacion: no pasa en la tabla real.
                    info["rewards"] = {"": info["rewards"]} if info["rewards"] else {}
                info["rewards"].setdefault(rotacion, [])
                continue
            m = RE_CABECERA_MISION.match(textos[0])
            if not m:
                raras += 1
                info = None
                continue
            # Mismos nombres de nodo que WFCD, comprobado contra su missionRewards.json:
            # "(Variant) Annihilation" -> "Variant Annihilation"; alijos y tablas "Extra"
            # con su sufijo; y un nodo repetido (Duviri Normal/Hard) lleva el modo detras.
            nodo = " ".join(re.sub(r"^\((\w+)\)\s*", r"\1 ", m.group("nodo")).split())
            modo = m.group("modo").strip()
            if modo == "Caches":
                nodo += " (Caches)"
            if m.group("extra"):
                nodo += " (Extra)"
            planeta = misiones.setdefault(m.group("planeta").strip(), {})
            if nodo in planeta:
                nodo += f" ({modo})"
            rotacion = None
            if nodo in planeta:
                # La misma cabecera otra vez (eventos): sus premios se suman al nodo.
                info = planeta[nodo]
                continue
            info = {"gameMode": modo, "isEvent": bool(m.group("evento")), "rewards": []}
            planeta[nodo] = info
        elif info is not None:
            premio = _premio(textos)
            if not premio:
                raras += 1
                continue
            if rotacion is None:
                info["rewards"].append(premio)
            else:
                info["rewards"][rotacion].append(premio)
    total = sum(len(n) for n in misiones.values())
    if not total:
        raise FormatoDesconocido("la seccion de misiones no trae ningun nodo")
    if raras > total * 0.05:
        raise FormatoDesconocido(f"{raras} filas de misiones con forma desconocida")
    return misiones


def leer(texto: str) -> TablaOficial:
    """Convierte la pagina de DE. FormatoDesconocido si no tiene la forma de siempre."""
    secciones = _secciones(texto)
    if "relicRewards" not in secciones or "missionRewards" not in secciones:
        raise FormatoDesconocido("faltan las secciones de reliquias o de misiones")
    return TablaOficial(
        fecha=fecha_publicacion(texto),
        reliquias=_leer_reliquias(secciones["relicRewards"]),
        misiones=_leer_misiones(secciones["missionRewards"]),
    )


def cargar(ruta: Path) -> TablaOficial | None:
    """Lee el fichero descargado; None (con aviso en el log) si falta o no se entiende."""
    if not ruta.exists() or ruta.stat().st_size == 0:
        log.info("No hay tabla oficial de DE descargada; se usa solo WFCD")
        return None
    try:
        tabla = leer(ruta.read_text(encoding="utf-8", errors="replace"))
    except FormatoDesconocido as e:
        log.warning("La tabla oficial de DE ha cambiado de formato, se ignora: %s", e)
        return None
    except Exception:  # noqa: BLE001 - la tabla de DE es un extra, nunca un requisito
        log.exception("No se pudo leer la tabla oficial de DE, se ignora")
        return None
    log.info(
        "Tabla oficial de DE del %s: %d reliquias (por refinamiento), %d nodos",
        tabla.fecha or "?", len(tabla.reliquias), sum(len(n) for n in tabla.misiones.values()),
    )
    return tabla


# -- decision entre WFCD y DE ---------------------------------------------------


def es_mas_nueva(tabla: TablaOficial, fecha_wfcd: date | None) -> bool:
    """True si la tabla de DE es posterior a lo que publico WFCD (o WFCD no tiene fecha)."""
    if tabla.fecha is None:
        return False
    return fecha_wfcd is None or tabla.fecha > fecha_wfcd


def _clave_reliquia(r: dict) -> tuple[str, str, str]:
    return (
        str(r.get("tier", "")).lower(), str(r.get("relicName", "")).lower(),
        str(r.get("state") or "Intact").lower(),
    )


def combinar_reliquias(wfcd: list[dict], de: list[dict], de_manda: bool) -> tuple[list[dict], int]:
    """Las reliquias de las dos fuentes, sin repetir. Devuelve (lista, cuantas solo en DE).

    Nunca se quita nada: una reliquia que solo tenga una de las dos se queda. En las
    que estan en ambas manda DE si es mas nueva.
    """
    de_por_clave = {_clave_reliquia(r): r for r in de}
    wfcd_claves = {_clave_reliquia(r) for r in wfcd}
    salida = [de_por_clave.get(_clave_reliquia(r), r) if de_manda else r for r in wfcd]
    nuevas = [r for k, r in de_por_clave.items() if k not in wfcd_claves]
    return salida + nuevas, len(nuevas)


def misiones_completas(de: dict, wfcd: dict | None) -> bool:
    total_de = sum(len(n) for n in de.values())
    total_wfcd = sum(len(n) for n in (wfcd or {}).values() if isinstance(n, dict))
    return total_de > 0 and total_de >= total_wfcd * PROPORCION_MINIMA_MISIONES


# -- objetos que el catalogo aun no tiene ------------------------------------------


# Nombre de pieza en las tablas -> (componente del catalogo, lleva " Blueprint" en la tabla).
# Las piezas de warframe salen como plano ("X Prime Chassis Blueprint"); las de arma, tal cual.
COMPONENTES_WARFRAME = ("Chassis", "Neuroptics", "Systems")
COMPONENTES_ARMA = (
    "Barrel", "Receiver", "Stock", "Blade", "Handle", "Hilt", "Guard", "Grip", "Gauntlet",
    "Lower Limb", "Upper Limb", "String", "Link", "Pouch", "Stars", "Ornament", "Head",
    "Disc", "Boot", "Chain", "Blades", "Barrels", "Receivers",
)
COMPONENTES_COMPANERO = ("Carapace", "Cerebrum", "Systems", "Harness", "Wings")
# Por las piezas se sabe que es el padre; un arma de piezas ambiguas va a Primary,
# que es donde el Casador y la busqueda la buscan igual que a una secundaria.
CATEGORIA_POR_PIEZA = {
    **dict.fromkeys(COMPONENTES_WARFRAME, "Warframes"),
    **dict.fromkeys(("Blade", "Handle", "Hilt", "Guard", "Grip", "Gauntlet", "Head", "Disc",
                     "Boot", "Chain", "Blades", "Ornament"), "Melee"),
    **dict.fromkeys(("Lower Limb", "Upper Limb", "String", "Stock", "Barrel", "Receiver",
                     "Barrels", "Receivers"), "Primary"),
    **dict.fromkeys(("Link", "Pouch", "Stars"), "Secondary"),
    **dict.fromkeys(("Carapace", "Cerebrum", "Harness", "Wings"), "Sentinels"),
}
TIPO_POR_CATEGORIA = {
    "Warframes": "Warframe", "Primary": "Primary", "Secondary": "Secondary", "Melee": "Melee",
    "Sentinels": "Sentinel",
}
_COMPONENTES = sorted(
    set(COMPONENTES_WARFRAME) | set(COMPONENTES_ARMA) | set(COMPONENTES_COMPANERO),
    key=len, reverse=True,
)
RE_PIEZA_PRIME = re.compile(
    r"^(?P<padre>.+?\bPrime)\s+(?:(?P<comp>" + "|".join(re.escape(c) for c in _COMPONENTES)
    + r")(?:\s+Blueprint)?|Blueprint)$"
)


def _categoria_por_piezas(componentes: list[str]) -> str:
    """Warframe si tiene chasis, neuropticas o sistemas (salvo piezas de companero)."""
    piezas = set(componentes)
    if piezas & {"Carapace", "Cerebrum", "Harness", "Wings"}:
        return "Sentinels"
    if piezas & set(COMPONENTES_WARFRAME):
        return "Warframes"
    return next((CATEGORIA_POR_PIEZA[c] for c in componentes if c in CATEGORIA_POR_PIEZA), "Primary")


def _camel(texto: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[^A-Za-z0-9]+", texto) if p)


def _casa(alias: dict[str, int], nombre: str) -> int | None:
    """Lo mismo que ImportadorDrops sin el difuso: nombre exacto, o sin " Blueprint".

    Sin " Blueprint" solo para piezas ("X Prime Chassis Blueprint" -> "x prime chassis"):
    el plano principal ("X Prime Blueprint") sin esa palabra es el objeto padre, no el plano.
    """
    clave = normalizar(nombre)
    if clave in alias:
        return alias[clave]
    m = RE_PIEZA_PRIME.match(nombre)
    if clave.endswith(" blueprint") and m and m.group("comp"):
        return alias.get(clave.removesuffix(" blueprint"))
    return None


class CreadorSinteticos:
    """Da de alta lo que la tabla de DE nombra y el catalogo de WFCD aun no tiene."""

    def __init__(self, con: sqlite3.Connection, importador):
        self.con = con
        self.imp = importador
        self.creados: list[str] = []

    def _imagen_de(self, sql: str, *args) -> str | None:
        fila = self.con.execute(sql, args).fetchone()
        return fila[0] if fila else None

    def reliquias(self, reliquias: list[dict], en_misiones: set[str]) -> int:
        """Una reliquia por nombre canonico que no este ya en el catalogo."""
        antes = len(self.creados)
        for r in reliquias:
            canonico = f"{str(r.get('tier', '')).title()} {str(r.get('relicName', '')).upper()}".strip()
            if not canonico or normalizar(canonico) in self.imp.reliquias:
                continue
            era = canonico.split()[0]
            imagen = self._imagen_de(
                "SELECT imagen FROM items WHERE categoria = 'Relics' AND nombre_en LIKE ? "
                "AND imagen IS NOT NULL GROUP BY imagen ORDER BY count(*) DESC LIMIT 1",
                f"{era} %",
            )
            # _importar_reliquia es quien sabe dar de alta una reliquia: se le pasa lo que
            # daria el catalogo, sin premios (esos llegan de la tabla de DE).
            self.imp._importar_reliquia({
                "name": f"{canonico} Intact",
                "uniqueName": f"{PREFIJO_SINTETICO}Relic/{canonico}",
                "tradable": True,
                "imageName": imagen,
                "vaulted": 0 if normalizar(f"{canonico} Relic") in en_misiones else None,
            })
            self.creados.append(f"{canonico} Relic")
        return len(self.creados) - antes

    def piezas(self, nombres: list[str]) -> int:
        """Piezas prime ("Citrine Prime Chassis Blueprint") y, si hace falta, su padre."""
        antes = len(self.creados)
        pendientes: dict[str, list[tuple[str, str]]] = {}
        for nombre in nombres:
            if _casa(self.imp.alias, nombre):
                continue
            m = RE_PIEZA_PRIME.match(nombre)
            if not m:
                continue
            pendientes.setdefault(m.group("padre"), []).append((nombre, m.group("comp") or "Blueprint"))
        for padre_en, piezas in sorted(pendientes.items()):
            padre_id = self._padre(padre_en, [c for _, c in piezas])
            for nombre, componente in piezas:
                if _casa(self.imp.alias, nombre):
                    continue  # repetida en la lista
                self._pieza(padre_id, padre_en, componente, nombre)
        return len(self.creados) - antes

    def _padre(self, padre_en: str, componentes: list[str]) -> int:
        existente = _casa(self.imp.alias, padre_en)
        if existente:
            return existente
        # La version normal (Citrine, Corufell) suele estar ya en el catalogo y dice que
        # es; si no, se deduce por las piezas.
        base = self.con.execute(
            "SELECT categoria, tipo FROM items WHERE nombre_en = ? AND padre_id IS NULL "
            "AND categoria IN ('Warframes', 'Primary', 'Secondary', 'Melee', 'Sentinels', "
            "'SentinelWeapons', 'Archwing', 'Arch-Gun', 'Arch-Melee', 'Pets') LIMIT 1",
            (padre_en.removesuffix(" Prime").strip(),),
        ).fetchone()
        categoria = base[0] if base else _categoria_por_piezas(componentes)
        item_id = self.imp._insertar({
            "unique_name": f"{PREFIJO_SINTETICO}{_camel(padre_en)}",
            "nombre_en": padre_en,
            # Los nombres propios (Citrine Prime) no se traducen en ningun idioma.
            "nombre_es": padre_en,
            "categoria": categoria,
            "tipo": base[1] if base and base[1] else TIPO_POR_CATEGORIA.get(categoria, categoria),
            "es_prime": 1,
            "comerciable": 0,
            "vaulted": 0,
        })
        self.imp._registrar_alias(padre_en, item_id)
        self.creados.append(padre_en)
        return item_id

    def _pieza(self, padre_id: int, padre_en: str, componente: str, nombre: str) -> None:
        fila = self.con.execute(
            "SELECT nombre_es, categoria FROM items WHERE id = ?", (padre_id,)
        ).fetchone()
        padre_es, categoria = fila if fila else (padre_en, "Primary")
        # La imagen generica que usan las demas piezas prime con ese nombre.
        imagen = self._imagen_de(
            "SELECT imagen FROM items WHERE nombre_en = ? AND es_prime = 1 AND tipo = 'Componente' "
            "AND imagen IS NOT NULL GROUP BY imagen ORDER BY count(*) DESC LIMIT 1",
            componente,
        )
        sufijo = "Blueprint" if componente == "Blueprint" else _camel(componente)
        if componente in COMPONENTES_WARFRAME and categoria == "Warframes":
            sufijo += "Component"
        item_id = self.imp._insertar({
            "unique_name": f"{PREFIJO_SINTETICO}{_camel(padre_en)}{sufijo}",
            "nombre_en": componente,
            "nombre_es": self.imp.componentes_es.get(componente),
            "categoria": categoria,
            "tipo": "Componente",
            "es_prime": 1,
            "comerciable": 1,
            "imagen": imagen,
            "padre_id": padre_id,
            "item_count": 1,
        })
        nombres_idioma = {
            idioma: palabras[componente]
            for idioma, palabras in self.imp.componentes_extra.items()
            if palabras.get(componente)
        }
        self.imp._guardar_nombres_idioma(item_id, nombres_idioma)
        self.imp._registrar_alias(f"{padre_en} {componente}", item_id)
        if componente != "Blueprint":
            self.imp._registrar_alias(f"{padre_en} {componente} Blueprint", item_id)
        self.imp._registrar_alias(nombre, item_id)
        self.creados.append(nombre)


def _nombres_premio(reliquias: list[dict]) -> list[str]:
    vistos: dict[str, None] = {}
    for r in reliquias:
        for p in r.get("rewards") or []:
            if isinstance(p, dict) and isinstance(p.get("itemName"), str):
                vistos.setdefault(p["itemName"], None)
    return list(vistos)


def _nombres_en_misiones(misiones: dict) -> set[str]:
    salida = set()
    for nodos in misiones.values():
        for info in (nodos or {}).values():
            premios = info.get("rewards") if isinstance(info, dict) else None
            grupos = premios.values() if isinstance(premios, dict) else [premios or []]
            for lista in grupos:
                for p in lista:
                    if isinstance(p, dict) and isinstance(p.get("itemName"), str):
                        salida.add(normalizar(p["itemName"]))
    return salida


def preparar(
    con: sqlite3.Connection,
    importador,
    tabla: TablaOficial | None,
    wfcd_reliquias: list[dict] | None,
    wfcd_misiones: dict | None,
    fecha_wfcd: date | None,
) -> dict:
    """Decide que se importa de DE y crea los objetos que falten en el catalogo.

    Devuelve {clave de drops: datos} para ImportadorDrops.importar_todo: solo con lo
    que cambia respecto a los ficheros de WFCD ("relics", "missionRewards"). Vacio si
    no hay tabla o algo falla, y en ese caso no se deja nada a medias en el indice.
    """
    if tabla is None:
        return {}
    de_manda = es_mas_nueva(tabla, fecha_wfcd)
    try:
        con.commit()
        con.execute("SAVEPOINT tabla_oficial")
        alias_antes = dict(importador.alias)
        reliquias_antes = dict(importador.reliquias)
        try:
            reliquias, solo_de = combinar_reliquias(wfcd_reliquias or [], tabla.reliquias, de_manda)
            datos: dict = {"relics": reliquias} if (solo_de or de_manda) else {}
            usar_misiones = de_manda and misiones_completas(tabla.misiones, wfcd_misiones)
            if de_manda and not usar_misiones:
                log.warning("La tabla de misiones de DE parece incompleta; se sigue con la de WFCD")
            misiones = tabla.misiones if usar_misiones else (wfcd_misiones or {})
            if usar_misiones:
                datos["missionRewards"] = {"missionRewards": tabla.misiones}

            creador = CreadorSinteticos(con, importador)
            n_reliquias = creador.reliquias(tabla.reliquias, _nombres_en_misiones(misiones))
            n_piezas = creador.piezas(_nombres_premio(tabla.reliquias))
            con.execute("RELEASE SAVEPOINT tabla_oficial")
        except Exception:
            con.execute("ROLLBACK TO SAVEPOINT tabla_oficial")
            con.execute("RELEASE SAVEPOINT tabla_oficial")
            importador.alias.clear()
            importador.alias.update(alias_antes)
            importador.reliquias.clear()
            importador.reliquias.update(reliquias_antes)
            raise
        con.commit()
    except Exception:  # noqa: BLE001 - sin la tabla de DE se sigue con WFCD, como siempre
        log.exception("No se pudo usar la tabla oficial de DE; se sigue solo con WFCD")
        return {}
    log.info(
        "Tabla oficial de DE %s: %d reliquias que WFCD no tiene, misiones de %s, "
        "%d reliquias y %d objetos sinteticos%s",
        "mas nueva que WFCD" if de_manda else "no mas nueva que WFCD",
        solo_de, "DE" if "missionRewards" in datos else "WFCD", n_reliquias, n_piezas,
        (": " + ", ".join(creador.creados[:20])) if creador.creados else "",
    )
    return datos
