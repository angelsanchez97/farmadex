"""Nodos del mapa estelar en espanol, desde el Public Export de Digital Extremes.

DE publica un indice comprimido con LZMA por idioma; dentro esta el manifiesto
`ExportRegions_<idioma>.json`, que trae cada nodo con el nombre del planeta ya
traducido. Se descargan el ingles (para casar con las tablas de drops, que van
en ingles) y el espanol (para ensenarlo).
"""

from __future__ import annotations

import json
import lzma
import re
import sqlite3

import httpx

from ..config import USER_AGENT
from ..idiomas import glosa
from ..registro_log import obtener
from .items import normalizar

log = obtener("nodos")

INDICE = "https://origin.warframe.com/PublicExport/index_{idioma}.txt.lzma"
INDICE_ESPEJO = "https://content.warframe.com/PublicExport/index_{idioma}.txt.lzma"
MANIFIESTO = "https://content.warframe.com/PublicExport/Manifest/{fichero}"
# El ExportRegions de DE solo trae los 269 nodos del mapa estelar normal. Los de
# Railjack (CrewBattleNode), eventos (EventNode), Duviri y los retirados o
# escondidos (unos 80 SolNode mas) existen igual en el perfil del jugador y en el
# estado del mundo; WFCD los mantiene aqui con su nombre en ingles.
SOLNODES = "https://raw.githubusercontent.com/WFCD/warframe-worldstate-data/master/data/solNodes.json"

RE_SUFIJO = re.compile(r"\s*\([^)]*\)\s*$")
RE_NOMBRE_PLANETA = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")
PLANETA_POR_PREFIJO = (("EventNode", "Event"), ("PvpNode", "Conclave"))


def _descomprimir(datos: bytes) -> str:
    """LZMA 'alone' sin marca de fin: hay que ir por trozos y aceptar el corte final."""
    # Hay que alimentarlo a trozos pequenos: de una sentada, el decodificador
    # llega al final sin marca de fin y revienta sin devolver nada de lo leido.
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    salida = bytearray()
    try:
        for i in range(0, len(datos), 64):
            salida += dec.decompress(datos[i : i + 64])
    except lzma.LZMAError as e:
        if not salida:
            raise
        log.debug("Fin abrupto del LZMA tras %d bytes (%s)", len(salida), e)
    return salida.decode("utf-8", errors="replace")


def _regiones(cliente: httpx.Client, idioma: str) -> list[dict]:
    texto_indice = ""
    for plantilla in (INDICE, INDICE_ESPEJO):
        try:
            r = cliente.get(plantilla.format(idioma=idioma))
            r.raise_for_status()
            texto_indice = _descomprimir(r.content)
            break
        except (httpx.HTTPError, lzma.LZMAError) as e:
            log.warning("No se pudo leer el indice %s de DE: %s", idioma, e)
    if not texto_indice:
        return []

    fichero = next(
        (l for l in texto_indice.splitlines() if l.startswith("ExportRegions")), ""
    )
    if not fichero:
        log.warning("El indice de DE no trae ExportRegions (%s)", idioma)
        return []

    r = cliente.get(MANIFIESTO.format(fichero=fichero))
    r.raise_for_status()
    # DE deja a veces saltos de linea sin escapar dentro de las cadenas.
    try:
        datos = json.loads(r.text, strict=False)
    except json.JSONDecodeError:
        datos = json.loads(r.text.replace("\r", " ").replace("\n", " "), strict=False)
    return datos.get("ExportRegions") or []


def sincronizar(con: sqlite3.Connection, cliente: httpx.Client | None = None) -> dict:
    """Completa la tabla de nodos con nombres en ingles y en espanol."""
    propio = cliente is None
    cliente = cliente or httpx.Client(
        timeout=60.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    )
    try:
        en = {r["uniqueName"]: r for r in _regiones(cliente, "en") if r.get("uniqueName")}
        es = {r["uniqueName"]: r for r in _regiones(cliente, "es") if r.get("uniqueName")}
    finally:
        if propio:
            cliente.close()

    if not en and not es:
        log.warning("Sin datos de regiones; los nodos se quedan solo en ingles")
        return {"nodos": 0}

    tocados = 0
    for unico, region in (en or es).items():
        traducida = es.get(unico, {})
        nombre_en = region.get("name") or traducida.get("name") or ""
        planeta_en = region.get("systemName") or ""
        if not nombre_en:
            continue
        con.execute(
            """
            INSERT INTO nodos (unique_name, nombre_en, nombre_es, planeta_en, planeta_es,
                               nivel_min, nivel_max, clave_drops)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(unique_name) DO UPDATE SET
                 nombre_es = excluded.nombre_es,
                 planeta_es = excluded.planeta_es,
                 nivel_min = COALESCE(excluded.nivel_min, nodos.nivel_min),
                 nivel_max = COALESCE(excluded.nivel_max, nodos.nivel_max)
            """,
            (
                unico,
                nombre_en,
                traducida.get("name") or nombre_en,
                planeta_en,
                traducida.get("systemName") or planeta_en,
                region.get("minEnemyLevel"),
                region.get("maxEnemyLevel"),
                f"{planeta_en}/{nombre_en}",
            ),
        )
        tocados += 1

    # Los planetas que DE no traduzca se completan con el glosario.
    con.execute(
        """
        UPDATE nodos SET planeta_es = COALESCE(
            (SELECT es FROM glosario WHERE dominio = 'planeta' AND en = nodos.planeta_en),
            planeta_es, planeta_en)
        WHERE planeta_es IS NULL OR planeta_es = planeta_en
        """
    )
    log.info("Nodos sincronizados con el Public Export: %d", tocados)
    return {"nodos": tocados}


def _solnodes(cliente: httpx.Client) -> dict:
    try:
        r = cliente.get(SOLNODES)
        r.raise_for_status()
        datos = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("No se pudo leer solNodes.json de WFCD: %s", e)
        return {}
    if not isinstance(datos, dict):
        log.warning("solNodes.json ya no es un diccionario; se ignora")
        return {}
    return datos


def completar_solnodes(con: sqlite3.Connection, cliente: httpx.Client | None = None) -> dict:
    """Anade los nodos que DE no publica, con los nombres que mantiene WFCD."""
    propio = cliente is None
    cliente = cliente or httpx.Client(
        timeout=60.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    )
    try:
        datos = _solnodes(cliente)
    finally:
        if propio:
            cliente.close()
    return aplicar_solnodes(con, datos)


def aplicar_solnodes(con: sqlite3.Connection, datos: dict) -> dict:
    """Vuelca solNodes.json en la tabla: `{"SolNode3": {"value": "Cordelia (Uranus)",
    "enemy": "Grineer", "type": "Sabotage"}, ...}`.

    - Un nodo que ya existe por su uniqueName no se toca (DE manda).
    - Si las tablas de drops ya lo habian dado de alta por nombre ("DROPS/Uranus/Cordelia"),
      esa fila recibe su uniqueName de verdad: las fuentes siguen colgando del mismo id y
      el perfil del jugador ya lo encuentra.
    - Lo demas se inserta nuevo. Sin planeta entre parentesis (eventos, hubs) el planeta
      queda vacio o con la etiqueta del prefijo, y `nombre_bonito` lo pinta sin coma.
    """
    existentes = {u for (u,) in con.execute("SELECT unique_name FROM nodos WHERE unique_name IS NOT NULL")}
    por_clave = {
        normalizar(clave): (nid, unico)
        for nid, clave, unico in con.execute(
            "SELECT id, clave_drops, unique_name FROM nodos WHERE clave_drops IS NOT NULL"
        )
    }
    anadidos = enlazados = descartados = 0
    for unico, info in datos.items():
        if not isinstance(unico, str) or unico in existentes or not isinstance(info, dict):
            continue
        valor = info.get("value")
        if not isinstance(valor, str) or not valor.strip() or valor == unico:
            descartados += 1  # "SolNode0": {"value": "SolNode0"}: WFCD tampoco sabe que es
            continue
        m = RE_NOMBRE_PLANETA.match(valor)
        nombre, planeta = (m.group(1).strip(), m.group(2).strip()) if m else (valor.strip(), "")
        if not planeta:
            planeta = next((p for prefijo, p in PLANETA_POR_PREFIJO if unico.startswith(prefijo)), "")
        mision = info.get("type") if isinstance(info.get("type"), str) else None
        faccion = info.get("enemy") if isinstance(info.get("enemy"), str) else None
        clave = f"{planeta}/{nombre}" if planeta else None
        ocupada = por_clave.get(normalizar(clave)) if clave else None

        if ocupada and ocupada[1] and ocupada[1].startswith("DROPS/"):
            con.execute(
                "UPDATE nodos SET unique_name = ?, mision_en = COALESCE(mision_en, ?),"
                " faccion_en = COALESCE(faccion_en, ?) WHERE id = ?",
                (unico, mision, faccion, ocupada[0]),
            )
            por_clave[normalizar(clave)] = (ocupada[0], unico)
            enlazados += 1
            continue
        if ocupada:
            clave = None  # ya hay un nodo de DE con ese nombre y planeta: este es otro id
        cur = con.execute(
            "INSERT OR IGNORE INTO nodos (unique_name, nombre_en, planeta_en, mision_en, faccion_en,"
            " clave_drops) VALUES (?, ?, ?, ?, ?, ?)",
            (unico, nombre, planeta, mision, faccion, clave),
        )
        if cur.rowcount:
            anadidos += 1
            if clave:
                por_clave[normalizar(clave)] = (cur.lastrowid, unico)
        existentes.add(unico)

    con.execute(
        """
        UPDATE nodos SET planeta_es = COALESCE(
            (SELECT es FROM glosario WHERE dominio = 'planeta' AND en = nodos.planeta_en),
            planeta_es, planeta_en)
        WHERE planeta_es IS NULL OR planeta_es = planeta_en
        """
    )
    con.execute(
        """
        UPDATE nodos SET mision_es = COALESCE(
            (SELECT es FROM glosario WHERE dominio = 'mision' AND en = nodos.mision_en), mision_en)
        WHERE mision_en IS NOT NULL AND mision_es IS NULL
        """
    )
    con.execute(
        """
        UPDATE nodos SET faccion_es = COALESCE(
            (SELECT es FROM glosario WHERE dominio = 'faccion' AND en = nodos.faccion_en), faccion_en)
        WHERE faccion_en IS NOT NULL AND faccion_es IS NULL
        """
    )
    log.info(
        "Nodos de WFCD (solNodes): %d anadidos, %d de las tablas de drops con su id de verdad, %d sin nombre",
        anadidos, enlazados, descartados,
    )
    return {"anadidos": anadidos, "enlazados": enlazados, "descartados": descartados}


def reenlazar_fuentes(con: sqlite3.Connection) -> dict:
    """Asigna nodo a las fuentes de mision que quedaron sin enlazar.

    Las tablas de drops usan claves como 'Venus/Bifrost Echo (Caches)'; se prueba
    con el sufijo quitado y, si aun asi no hay nodo, la fuente se queda con su
    texto original en vez de perderse.
    """
    por_clave = {
        normalizar(clave): nid
        for nid, clave in con.execute(
            "SELECT id, clave_drops FROM nodos WHERE clave_drops IS NOT NULL"
        )
    }
    por_nombre = {
        normalizar(nombre): nid for nid, nombre in con.execute("SELECT id, nombre_en FROM nodos")
    }

    # Los contratos ('bounty') no tienen nodo: contarlos aqui inflaba 'sin_nodo'.
    pendientes = con.execute(
        "SELECT id, origen_texto FROM fuentes "
        "WHERE origen_id IS NULL AND tipo IN ('mision','llave')"
    ).fetchall()

    enlazadas = 0
    for fid, texto in pendientes:
        if "/" not in (texto or ""):
            continue
        planeta, _, nodo = texto.partition("/")
        nodo_limpio = RE_SUFIJO.sub("", nodo).strip()
        destino = por_clave.get(normalizar(f"{planeta}/{nodo_limpio}")) or por_nombre.get(
            normalizar(nodo_limpio)
        )
        if destino:
            con.execute("UPDATE fuentes SET origen_id = ? WHERE id = ?", (destino, fid))
            enlazadas += 1

    sin_nodo = len(pendientes) - enlazadas
    log.info("Fuentes de mision reenlazadas: %d (sin nodo conocido: %d)", enlazadas, sin_nodo)
    return {"enlazadas": enlazadas, "sin_nodo": sin_nodo}


def nombre_bonito(con: sqlite3.Connection, origen_texto: str) -> str:
    """'Venus/Bifrost Echo (Caches)' -> 'Bifrost Echo (Caches), Venus'.

    El planeta se traduce con el glosario en castellano; en otro idioma de la
    interfaz se deja el ingles del juego (o la traduccion del catalogo si la hay).
    """
    if "/" not in (origen_texto or ""):
        return origen_texto
    planeta, _, nodo = origen_texto.partition("/")
    fila = con.execute(
        "SELECT es FROM glosario WHERE dominio = 'planeta' AND en = ?", (planeta,)
    ).fetchone()
    return f"{nodo}, {glosa(fila[0], planeta) if fila else planeta}"
