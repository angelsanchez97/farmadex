"""Builds de Overframe (https://overframe.gg) para un warframe, un arma o un companero.

Overframe es la web de builds de la comunidad. Sus condiciones de uso
(wearemoba.com/terms-of-service) prohiben el acceso automatizado y reutilizar su
contenido, y no tiene API publica. Por eso Farmadex NO descarga, NO lee y NO muestra
nada de Overframe: solo arma una direccion y la abre en la pestana Web (ui/reproductor.py,
PanelWeb) para que el usuario la navegue como en su navegador.

Las fichas de Overframe van por un numero suyo (/items/arsenal/<id>/<nombre>/) que
Farmadex no tiene y no se va a sacar recorriendo su web. Tampoco hay una busqueda por
nombre que se pueda comprobar sin acceso automatizado (su web responde 403 a todo lo que
no es un navegador). Asi que se abre una busqueda web limitada a overframe.gg con el
nombre ingles del objeto, que es el que usa Overframe: el primer resultado suele ser la
ficha del objeto con sus builds, y el usuario la elige ahi mismo. DuckDuckGo porque no
pide aceptar cookies antes de ensenar los resultados.
"""

from __future__ import annotations

from urllib.parse import quote_plus

SITIO = "overframe.gg"
BASE_BUSQUEDA = "https://duckduckgo.com/?q="

# Lo que tiene builds en Overframe: warframes, armas (tambien las de archwing y las de
# companero), archwings y companeros. Mods, arcanos, reliquias o recursos no.
CATEGORIAS = frozenset({
    "Warframes", "Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee", "Archwing",
    "Sentinels", "SentinelWeapons", "Pets",
})


def tiene_builds(categoria: str | None) -> bool:
    return (categoria or "") in CATEGORIAS


def nombre_con_builds(item: dict | None, padre: dict | None = None) -> str:
    """Nombre ingles de lo que tiene builds: el objeto, o su padre si es una pieza.

    'Ash Prime Systems' -> 'Ash Prime' (las builds son del warframe, no de la pieza).
    Vacio si ni el objeto ni su padre tienen builds (un mod, una reliquia...).
    """
    for candidato in (padre, item):
        if candidato and tiene_builds(candidato.get("categoria")):
            nombre = (candidato.get("nombre_en") or "").strip()
            if nombre:
                return nombre
    return ""


def url_builds(nombre_en: str | None) -> str:
    """Busqueda 'site:overframe.gg Ash Prime'; vacio sin nombre."""
    nombre = " ".join((nombre_en or "").split())
    if not nombre:
        return ""
    return BASE_BUSQUEDA + quote_plus(f"site:{SITIO} {nombre}")
