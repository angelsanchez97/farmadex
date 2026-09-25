"""Guias en YouTube de una mision o un objeto, en el idioma de la interfaz.

Quien juega con un solo monitor quiere ver como se hace una mision sin salir del
juego. Farmadex no descarga nada de YouTube ni usa su API: arma la direccion de la
busqueda ("warframe Hepit Captura"), ordenada por visitas, y el reproductor de
Farmadex (ui/reproductor.py) la abre para que el usuario elija el video ahi mismo.

Punto de extension (NO implementado): con una clave de la YouTube Data API v3 puesta
algun dia en Ajustes (config[CLAVE_API]), `url_guia` podria pedir `search.list` con
`q=<consulta>&order=viewCount&type=video&relevanceLanguage=<idioma>` y devolver
directamente `https://www.youtube.com/embed/<videoId>` del primero. Hoy la clave se
ignora y siempre se abre la busqueda; asi no hay ninguna llamada de red desde aqui.
"""

from __future__ import annotations

from urllib.parse import quote_plus


# Filtro de YouTube "ordenar por numero de visualizaciones" (sp=CAM= ya codificado).
ORDEN_POR_VISITAS = "CAM%253D"
BASE_BUSQUEDA = "https://www.youtube.com/results?search_query="
# Clave de config reservada para la YouTube Data API (ver el punto de extension arriba).
CLAVE_API = "youtube_api_clave"


def consulta(tema: str) -> str:
    """'warframe Citrine Prime', 'warframe Hepit Captura': solo el juego y el tema.

    Antes se anadia "guia"/"guide" en el idioma de la interfaz, y el usuario vio que
    "warframe Citrine Prime guia" no daba nada mientras que "warframe Citrine Prime"
    si: la palabra de mas filtraba justo los videos buenos, que no la llevan en el titulo.
    """
    return " ".join(f"warframe {tema.strip()}".split())


def url_busqueda(texto: str) -> str:
    return f"{BASE_BUSQUEDA}{quote_plus(texto)}&sp={ORDEN_POR_VISITAS}"


def url_guia(tema: str, clave_api: str | None = None) -> str:
    """Lo que abre el boton "Guias en YouTube" para ese tema.

    `clave_api` es el punto de extension para la Data API: hoy no se usa.
    """
    del clave_api  # reservado: ver el docstring del modulo
    return url_busqueda(consulta(tema)) if tema.strip() else ""
