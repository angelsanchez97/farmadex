"""Nombres de mods, arcanos y equipo en el idioma del JUEGO, no en el de la interfaz.

Quien juega en espanol con el Windows en ingles veia los mods de su build en ingles: la
interfaz elegia el idioma de los nombres por el idioma de Farmadex. Aqui se decide por
el del juego:

1. lo que el usuario haya puesto en `idioma_juego` (si no es "auto");
2. el idioma de la ultima pantalla de mejoras leida (`idioma_juego_visto`), que se
   deduce de los propios nombres leidos y de la cabecera (`detectar`);
3. si aun no se sabe, el idioma de la interfaz.

El indice trae espanol e ingles en `items` y frances, aleman, portugues, italiano y
polaco en `items_nombres`. Si un nombre no esta en el idioma pedido, se ensena el
ingles (que es lo que el propio juego hace con lo que no tiene traducido).
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata

from .. import config as config_mod
from .. import idiomas

IDIOMAS = ("es", "en", "fr", "de", "pt", "it", "pl")
NOMBRE_IDIOMA = {"es": "Español", "en": "English", "fr": "Français", "de": "Deutsch", "pt": "Português",
                 "it": "Italiano", "pl": "Polski"}
AUTOMATICO = "auto"

_TABLAS: dict[tuple[int, str], dict[int, str]] = {}


def idioma() -> str:
    """El idioma en que se ensenan los nombres del juego ahora mismo."""
    try:
        cfg = config_mod.cargar()
    except Exception:  # noqa: BLE001 - sin configuracion, el de la interfaz
        cfg = {}
    elegido = cfg.get("idioma_juego")
    if elegido in IDIOMAS:
        return elegido
    visto = cfg.get("idioma_juego_visto")
    if visto in IDIOMAS:
        return visto
    return idiomas.actual()


def elegido() -> str:
    """Lo que hay en Ajustes: "auto" o un idioma."""
    try:
        valor = config_mod.cargar().get("idioma_juego")
    except Exception:  # noqa: BLE001
        valor = None
    return valor if valor in IDIOMAS else AUTOMATICO


def elegir(codigo: str) -> None:
    """Fija el idioma a mano ("auto" para que vuelva a deducirse)."""
    cfg = config_mod.cargar()
    nuevo = codigo if codigo in IDIOMAS else AUTOMATICO
    if cfg.get("idioma_juego") != nuevo:
        cfg["idioma_juego"] = nuevo
        config_mod.guardar(cfg)


def apuntar_visto(codigo: str | None) -> bool:
    """Apunta el idioma visto en la ultima lectura. True si ha cambiado."""
    if codigo not in IDIOMAS:
        return False
    cfg = config_mod.cargar()
    if cfg.get("idioma_juego_visto") == codigo:
        return False
    cfg["idioma_juego_visto"] = codigo
    config_mod.guardar(cfg)
    return True


def olvidar_cache() -> None:
    _TABLAS.clear()


def tabla(con: sqlite3.Connection, codigo: str) -> dict[int, str]:
    """id -> nombre en ese idioma (solo los que lo tienen). Se lee una vez por indice."""
    clave = (id(con), codigo)
    if clave in _TABLAS:
        return _TABLAS[clave]
    try:
        if codigo == "en":
            filas = con.execute("SELECT id, nombre_en FROM items WHERE nombre_en IS NOT NULL")
        elif codigo == "es":
            filas = con.execute("SELECT id, nombre_es FROM items WHERE nombre_es IS NOT NULL")
        else:
            filas = con.execute("SELECT item_id, nombre FROM items_nombres WHERE idioma = ?", (codigo,))
        datos = {int(i): n for i, n in filas if n}
    except sqlite3.Error:
        datos = {}
    if len(_TABLAS) > 24:
        _TABLAS.clear()
    _TABLAS[clave] = datos
    return datos


def nombre(con: sqlite3.Connection | None, item_id: int | None, respaldo: str = "", codigo: str | None = None) -> str:
    """El nombre de un objeto en el idioma del juego; si no lo hay, en ingles; si no, en
    espanol; si no, `respaldo`."""
    if not item_id or con is None:
        return respaldo
    codigo = codigo or idioma()
    item_id = int(item_id)
    return (tabla(con, codigo).get(item_id) or tabla(con, "en").get(item_id)
            or tabla(con, "es").get(item_id) or respaldo)


def nombres(con: sqlite3.Connection | None, item_id: int | None) -> dict[str, str]:
    """{idioma: nombre} con todos los idiomas en que el indice lo trae."""
    if not item_id or con is None:
        return {}
    salida = {}
    for codigo in IDIOMAS:
        valor = tabla(con, codigo).get(int(item_id))
        if valor:
            salida[codigo] = valor
    return salida


def _plano(texto: str) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", sin.lower())


def detectar(con: sqlite3.Connection | None, leidos: list[tuple[str, int]], cabecera: str = "") -> str:
    """El idioma del juego segun lo leido: `leidos` son (texto del OCR, id casado).

    Manda la palabra de la cabecera ("MEJORAS", "AMÉLIORATIONS"...), salvo "UPGRADES",
    que tambien la pone el juego en aleman. Sin ella, cada nombre vota por los idiomas
    en que se escribe como se leyo (los que se escriben igual en todos no votan): hacen
    falta dos votos y mayoria clara. Devuelve "" si no se sabe: no se supone.
    """
    if cabecera in IDIOMAS and cabecera != "en":
        return cabecera
    votos = dict.fromkeys(IDIOMAS, 0)
    if con is not None:
        for texto, item_id in leidos:
            plano = _plano(texto)
            if not plano or not item_id:
                continue
            coinciden = []
            con_nombre = 0
            ingles = _plano(tabla(con, "en").get(int(item_id), ""))
            for codigo in IDIOMAS:
                valor = _plano(tabla(con, codigo).get(int(item_id), ""))
                if not valor or (codigo != "en" and valor == ingles):
                    # Sin traducir en ese idioma (el indice repite el ingles): no dice nada de el.
                    continue
                con_nombre += 1
                if valor == plano or (len(valor) >= 6 and valor in plano):
                    coinciden.append(codigo)
            if coinciden and len(coinciden) < con_nombre:
                for codigo in coinciden:
                    votos[codigo] += 1
    orden = sorted(votos.items(), key=lambda par: -par[1])
    if orden[0][1] >= 2 and orden[0][1] > orden[1][1]:
        return orden[0][0]
    if cabecera == "en" and orden[0][1] >= 1 and orden[0][0] == "en" and orden[1][1] == 0:
        return "en"
    return ""
