"""Codigos de canje de los glifos, desde la wiki oficial de Warframe.

WFCD no trae los codigos: los glifos de creadores de contenido y de promociones se
consiguen escribiendo un codigo en warframe.com/promocode (o en el Mercado del juego) y
ese dato no esta en ningun fichero del juego. La unica lista mantenida es la de la wiki
oficial (https://wiki.warframe.com/w/Glyph, secciones "Promo Code/Drop Glyphs" y
"Creator Glyphs"), que la propia wiki avisa de que puede estar incompleta y tener codigos
que ya no funcionan. Por eso la ficha lo dice al ensenarlo.

Se lee el texto de la pagina con la API de MediaWiki (sin claves, JSON publico) y se
buscan las plantillas {{GlyphBoxPromo|imagen|nombre|codigo}}; si falta el tercer campo,
el segundo es a la vez nombre y codigo (asi van casi todos los de creadores). La copia
se guarda en la carpeta de datos: sin red se usa la ultima que se bajo.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

import httpx

from ..config import DIR_DATOS, USER_AGENT
from ..registro_log import obtener
from . import detalles

log = obtener("glifos")

URL_WIKI = "https://wiki.warframe.com/api.php?action=parse&page=Glyph&prop=wikitext&format=json"
URL_CANJE = "https://www.warframe.com/promocode?code={codigo}"
NOMBRE_FICHERO = "glifos_codigos.json"

RE_PLANTILLA = re.compile(r"\{\{\s*GlyphBoxPromo\s*\|([^{}]*)\}\}", re.IGNORECASE)
# Un codigo de verdad: letras, numeros y poco mas, sin espacios ni marcas de la wiki.
RE_CODIGO = re.compile(r"^[A-Za-z0-9_.\-]{2,40}$")


def clave(nombre: str) -> str:
    """'13angTV Glyph' y '13angtv' dan lo mismo: minusculas, solo letras y numeros."""
    return re.sub(r"[^a-z0-9]", "", (nombre or "").lower())


def _sin_glifo(nombre: str) -> str:
    return re.sub(r"\s*(glyph|glifo)\s*$", "", nombre or "", flags=re.IGNORECASE).strip()


def leer_wikitext(texto: str) -> list[tuple[str, str]]:
    """Pares (nombre del glifo, codigo) de las plantillas GlyphBoxPromo de la pagina."""
    pares: list[tuple[str, str]] = []
    for argumentos in RE_PLANTILLA.findall(texto or ""):
        campos = [c.strip() for c in argumentos.split("|")]
        # Los parametros con nombre (clave=valor) no son de esta plantilla: se ignoran.
        campos = [c for c in campos if "=" not in c]
        if len(campos) < 2 or not campos[1]:
            continue
        nombre = campos[1]
        codigo = campos[2] if len(campos) > 2 and campos[2] else campos[1]
        if RE_CODIGO.match(codigo) and (nombre, codigo) not in pares:
            pares.append((nombre, codigo))
    return pares


def descargar(cliente: httpx.Client | None = None, carpeta: Path | None = None) -> list[tuple[str, str]]:
    """Baja la lista de la wiki y la guarda; si falla, la ultima copia guardada (o nada)."""
    ruta = (carpeta or DIR_DATOS) / NOMBRE_FICHERO
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT},
                                      follow_redirects=True)
    try:
        r = cliente.get(URL_WIKI)
        r.raise_for_status()
        texto = ((r.json().get("parse") or {}).get("wikitext") or {}).get("*") or ""
        pares = leer_wikitext(texto)
        if pares:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(
                json.dumps({"fecha": time.strftime("%Y-%m-%d"), "glifos": pares}, ensure_ascii=False),
                encoding="utf-8",
            )
            return pares
        log.warning("La pagina de glifos de la wiki no trae codigos; se usa la copia guardada")
    except (httpx.HTTPError, ValueError, AttributeError, OSError) as e:
        log.warning("No se pudieron bajar los codigos de glifos de la wiki: %s", e)
    finally:
        if propio:
            cliente.close()
    return guardados(ruta)


def guardados(ruta: Path | None = None) -> list[tuple[str, str]]:
    ruta = ruta or DIR_DATOS / NOMBRE_FICHERO
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return [(str(n), str(c)) for n, c in datos.get("glifos") or []]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def aplicar(con: sqlite3.Connection, pares: list[tuple[str, str]]) -> int:
    """Apunta el codigo en los detalles de cada glifo del indice que case por nombre.

    La wiki nombra los de creadores por su nick ("13angTV") y WFCD como "13angtv Glyph":
    se comparan sin mayusculas, espacios ni signos y sin la palabra "Glyph". Devuelve
    cuantos glifos han recibido codigo.
    """
    codigos: dict[str, str] = {}
    for nombre, codigo in pares:
        for k in (clave(nombre), clave(_sin_glifo(nombre))):
            if k:
                codigos.setdefault(k, codigo)
    if not codigos:
        return 0
    puestos = 0
    for item_id, nombre_en in con.execute(
        "SELECT id, nombre_en FROM items WHERE categoria = 'Glyphs' AND padre_id IS NULL"
    ).fetchall():
        codigo = codigos.get(clave(nombre_en)) or codigos.get(clave(_sin_glifo(nombre_en)))
        if codigo:
            detalles.guardar(con, item_id, {"glifo": {"codigo": codigo}})
            puestos += 1
    log.info("Glifos con codigo de canje (wiki): %d de %d codigos conocidos", puestos, len(pares))
    return puestos


def url_canje(codigo: str) -> str:
    return URL_CANJE.format(codigo=codigo)
