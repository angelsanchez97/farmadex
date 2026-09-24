"""Enlaces a la wiki oficial de Warframe (https://wiki.warframe.com) desde la ficha.

La ficha ya tenia "Abrir en la wiki" para los objetos que traen su `wiki_url`, pero
las reliquias no la traen, ni los nodos ni los tipos de mision. Aqui se construyen
esas direcciones a partir del nombre ingles del juego, que es el titulo de la pagina
en la wiki, y se pintan como enlaces http normales: la ficha los abre en el navegador
solo cuando el usuario pulsa (los `glosa:` siguen siendo solo tooltip y los `item:`
navegan dentro de Farmadex).

Los enlaces van con el mismo color que el texto que ya habia y sin subrayado: el
aspecto de las filas no cambia, solo aparece la mano al pasar el raton.
"""

from __future__ import annotations

import html
from urllib.parse import quote, quote_plus

from ..datos import modos_mision
from ..idiomas import nombre as nombre_idioma, t

BASE = "https://wiki.warframe.com"

# Nodos cuyo nombre es tambien el de otra pagina (War es la espada de Stalker, Oro y
# Titania son un recurso y un warframe...): la wiki les pone " (Node)". Sacado de la
# categoria "Mission Node" de la wiki el 2026-09-24; el resto de nodos se titulan tal cual.
NODOS_DESAMBIGUADOS = {"Caliban", "Isos", "Lex", "Oro", "Titania", "War"}

# Tipos de mision cuya pagina no se llama como el modo en los datos (segun la pagina
# "Mission" de la wiki, 2026-09-24). Los demas usan el nombre ingles de modos_mision.
PAGINAS_MODO = {
    "Arbitration": "Arbitrations",
    "Arena": "Rathuum",
    "Orphix": "Orphix (Mission)",
    "Rush": "Rush (Archwing)",
    "Conjunction Survival": "Survival",
    "Caches": "Sabotage",
    "Normal": "The Circuit",
    "Hard": "The Circuit",
}


def url_pagina(titulo: str) -> str:
    """Direccion de una pagina de la wiki por su titulo ('Lith S19' -> .../w/Lith_S19)."""
    return f"{BASE}/w/" + quote(titulo.strip().replace(" ", "_"), safe="_()'-.,:")


def url_busqueda(texto: str) -> str:
    """Busqueda en la wiki; si el texto es el titulo exacto de una pagina, la wiki va a ella."""
    return f"{BASE}/?search=" + quote_plus(texto.strip())


def url_reliquia(nombre_en: str | None) -> str:
    """'Lith S19 Relic' -> .../w/Lith_S19 (la pagina de la reliquia no lleva 'Relic')."""
    titulo = (nombre_en or "").strip().removesuffix(" Relic").strip()
    return url_pagina(titulo) if titulo else ""


def url_nodo(nodo_en: str | None) -> str:
    nodo = (nodo_en or "").strip()
    if not nodo:
        return ""
    return url_pagina(f"{nodo} (Node)" if nodo in NODOS_DESAMBIGUADOS else nodo)


def url_modo(modo_en: str | None) -> str:
    """Pagina del tipo de mision; vacio si el modo no se conoce (mejor sin enlace que a ciegas)."""
    modo = modos_mision.normalizar(modo_en)
    if not modo:
        return ""
    return url_pagina(PAGINAS_MODO.get(modo, modos_mision.MODOS[modo][1]))


def url_item(item: dict) -> str:
    """La pagina de un objeto de la ficha: su wiki_url, o la de la reliquia si lo es."""
    if item.get("wiki_url"):
        return item["wiki_url"]
    if item.get("categoria") == "Relics":
        return url_reliquia(item.get("nombre_en"))
    return ""


def enlace(url: str, cuerpo_html: str, color: str) -> str:
    """`cuerpo_html` (ya escapado) como enlace a la wiki, sin cambiar su aspecto."""
    if not url:
        return cuerpo_html
    return f"<a href='{html.escape(url)}' style='color:{color};text-decoration:none'>{cuerpo_html}</a>"


def donde(fila: dict, color: str) -> str:
    """'Hepit, Vacio' (escapado) con el nombre del nodo enlazado a su pagina.

    Solo si `donde` empieza por el nodo: en un contrato o un jefe el texto es otro
    ('Alad V (Temisto, Jupiter)') y se deja tal cual.
    """
    texto = fila.get("donde") or ""
    nodo = nombre_idioma(fila, "nodo") if fila.get("nodo_en") else ""
    url = url_nodo(fila.get("nodo_en"))
    if not nodo or not url or not texto.startswith(nodo):
        return html.escape(texto)
    return enlace(url, html.escape(nodo), color) + html.escape(texto[len(nodo):])


def linea(filas, color_texto: str, color_enlace: str) -> str:
    """'En la wiki: Supervivencia · Defensa · Hepit' con los modos y nodos de esas filas.

    Los tipos de mision ya son un enlace del glosario (su tooltip), asi que su pagina
    de la wiki va aqui, en una linea aparte al final de la seccion. Vacio si no hay nada.
    """
    modos: dict[str, str] = {}
    nodos: dict[str, str] = {}
    for f in filas:
        modo = f.get("modo") or f.get("mision_en")
        url = url_modo(modo)
        if url:
            modos.setdefault(modos_mision.nombre(modo), url)
        url = url_nodo(f.get("nodo_en"))
        if url:
            nodos.setdefault(nombre_idioma(f, "nodo"), url)
    trozos = [enlace(url, html.escape(visible), color_enlace) for visible, url in (*modos.items(), *nodos.items())]
    if not trozos:
        return ""
    return (
        f"<div style='color:{color_texto};font-size:12px;margin:4px 0 6px 4px'>"
        f"{html.escape(t('En la wiki:'))} {' &middot; '.join(trozos)}</div>"
    )
