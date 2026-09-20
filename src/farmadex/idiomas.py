"""Textos de la interfaz en varios idiomas.

La clave de cada texto es el propio castellano, tal y como esta escrito en el
codigo: si falta una traduccion sale el castellano, nunca una clave interna.
Los catalogos son JSON planos en `recursos/idiomas/<codigo>.json`, editables a
mano, sin compilar nada.

Los nombres de los objetos del juego no pasan por aqui: vienen del indice, que
trae castellano e ingles. `nombre()` elige entre los dos segun el idioma.
"""

from __future__ import annotations

import json
import locale
import sys
from pathlib import Path

from .registro_log import obtener

log = obtener("idiomas")

# Codigo -> nombre en su propio idioma (asi cada uno reconoce el suyo en la lista).
IDIOMAS = {
    "es": "Español",
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "pt": "Português (Brasil)",
}
POR_DEFECTO = "es"
# Valor de `idioma_ui` que significa "el de Windows".
AUTOMATICO = "auto"

# Identificador primario de idioma de Windows (LANGID & 0x3FF).
_LANGID = {0x0A: "es", 0x09: "en", 0x0C: "fr", 0x07: "de", 0x16: "pt"}
_PREFIJOS = {"es": "es", "spanish": "es", "en": "en", "english": "en", "fr": "fr", "french": "fr",
             "de": "de", "german": "de", "pt": "pt", "portuguese": "pt"}

_catalogo: dict[str, str] = {}
_actual = POR_DEFECTO


def dir_catalogos() -> Path:
    """`recursos/idiomas` junto al codigo, o dentro del paquete de PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "recursos" / "idiomas"


def idioma_windows() -> str:
    """El idioma de la interfaz de Windows, si es uno de los nuestros; castellano si no."""
    try:
        import ctypes

        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return _LANGID.get(langid & 0x3FF, POR_DEFECTO)
    except Exception:  # noqa: BLE001 - fuera de Windows o sin ctypes: se mira el locale
        pass
    nombre = (locale.getlocale()[0] or "").lower()
    for prefijo, codigo in _PREFIJOS.items():
        if nombre.startswith(prefijo):
            return codigo
    return POR_DEFECTO


def resolver(codigo: str | None) -> str:
    """Convierte lo guardado en config (`auto`, vacio, desconocido...) en un codigo valido."""
    if not codigo or codigo == AUTOMATICO:
        codigo = idioma_windows()
    return codigo if codigo in IDIOMAS else POR_DEFECTO


def cargar(codigo: str | None) -> str:
    """Activa un idioma y devuelve el codigo que ha quedado en uso."""
    global _actual
    _actual = resolver(codigo)
    _catalogo.clear()
    if _actual == POR_DEFECTO:
        return _actual
    ruta = dir_catalogos() / f"{_actual}.json"
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("No se pudo leer el catalogo %s: %s", ruta, e)
        datos = {}
    # Las claves que empiezan por "_" son comentarios del catalogo.
    _catalogo.update(
        {k: v for k, v in datos.items() if isinstance(v, str) and v and not k.startswith("_")}
    )
    return _actual


def actual() -> str:
    return _actual


def es_castellano() -> bool:
    return _actual == POR_DEFECTO


def t(texto: str, **valores) -> str:
    """Traduce un texto de la interfaz. Los huecos `{asi}` se rellenan con `valores`."""
    traducido = _catalogo.get(texto, texto)
    if not valores:
        return traducido
    try:
        return traducido.format(**valores)
    except (KeyError, IndexError, ValueError):
        # Un catalogo editado a mano con un hueco mal escrito no puede romper la interfaz.
        log.warning("Huecos incorrectos en la traduccion de %r", texto)
        return texto.format(**valores)


def _campo(fila, clave: str):
    try:
        return fila[clave]
    except (KeyError, IndexError):
        return None


def nombre(fila, base: str = "nombre") -> str:
    """Nombre de un objeto del indice segun el idioma: castellano si toca, ingles en el resto.

    El indice solo trae `<base>_es` y `<base>_en`; para frances, aleman y
    portugues se ensena el ingles, que es lo que hoy hay.
    """
    es, en = _campo(fila, f"{base}_es"), _campo(fila, f"{base}_en")
    if es_castellano():
        return es or en or ""
    return en or es or ""


def glosa(es: str, en: str | None) -> str:
    """Un termino del glosario del indice (que solo esta en castellano).

    En castellano se devuelve tal cual; en otro idioma, la traduccion del
    catalogo si la tiene y, si no, el ingles original del juego.
    """
    if es_castellano() or not en:
        return es
    return _catalogo.get(es) or en
