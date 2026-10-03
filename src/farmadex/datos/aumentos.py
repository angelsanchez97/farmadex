"""Diccionario de mods de aumento: de que warframe o arma son, como se llaman en cada
idioma y en que sindicato se compran, a que rango y por cuanto.

Todo sale del indice (datos de WFCD y de la tabla oficial de botin), nada escrito a mano
salvo el orden de los rangos de cada sindicato:

- Un aumento es un mod cuyo campo "compat" es el nombre de UN warframe o de UN arma
  concretos ("Rhino", "Hek"), no una clase ("WARFRAME", "Rifle"). El campo `isAugment`
  de WFCD no vale: marca tambien mods corrientes como Adaptation.
- Donde se compra sale de las fuentes de tipo "sindicato": el sindicato, lo que cuesta
  y el titulo del rango ("Steel Meridian, General").
- El numero de rango sale del titulo. Los titulos de los seis sindicatos y del Conclave
  son los del juego (wiki oficial, pagina Syndicates: los aumentos de warframe se venden
  al rango 5 y los de arma al rango 4, y coincide con los titulos de los datos). Si un
  titulo no esta en la lista, el rango queda en None y se ensena "no se sabe".

Si el perfil leido trae el rango del jugador en ese sindicato, `puede_comprar` dice si
llega; si no lo trae, devuelve None y no se supone nada.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from ..idiomas import es_castellano, t
from . import nombres_juego

# Titulos de los rangos 1 a 5, en el orden del juego.
RANGOS = {
    "Steel Meridian": ("Brave", "Defender", "Valiant", "Protector", "General"),
    "Arbiters of Hexis": ("Principled", "Authentic", "Lawful", "Crusader", "Maxim"),
    "Cephalon Suda": ("Competent", "Intriguing", "Intelligent", "Wise", "Genius"),
    "The Perrin Sequence": ("Associate", "Senior Associate", "Executive", "Senior Executive", "Partner"),
    "Red Veil": ("Respected", "Honored", "Esteemed", "Revered", "Exalted"),
    "New Loka": ("Humane", "Bountiful", "Benevolent", "Pure", "Flawless"),
    "Conclave": ("Mistral", "Whirlwind", "Tempest", "Hurricane", "Typhoon"),
}
# La etiqueta de cada sindicato en el perfil del jugador (perfil/lector.py).
ETIQUETA_PERFIL = {
    "Steel Meridian": "SteelMeridianSyndicate",
    "Arbiters of Hexis": "ArbitersSyndicate",
    "Cephalon Suda": "CephalonSudaSyndicate",
    "The Perrin Sequence": "PerrinSyndicate",
    "Red Veil": "RedVeilSyndicate",
    "New Loka": "NewLokaSyndicate",
    "Conclave": "ConclaveSyndicate",
}
# Nombres oficiales en castellano (los mismos que ensena la pestana Perfil).
NOMBRE_ES = {
    "Steel Meridian": "Meridiano de Acero",
    "Arbiters of Hexis": "Árbitros de Hexis",
    "Cephalon Suda": "Cefalon Suda",
    "The Perrin Sequence": "Secuencia Perrin",
    "Red Veil": "Velo Rojo",
    "New Loka": "Nueva Loka",
    "Cephalon Simaris": "Cefalon Simaris",
    "Kahl's Garrison": "Guarnición de Kahl",
}
CATEGORIAS_WARFRAME = ("Warframes",)
CATEGORIAS_ARMA = ("Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee")

_CACHE: dict[int, list["Aumento"]] = {}
_POR_ID: dict[int, dict[int, "Aumento"]] = {}
_SUELTOS: dict[int, dict[int, "Aumento | None"]] = {}  # mirados de uno en uno
_EQUIPOS: dict[int, dict[str, tuple[int, str]]] = {}


@dataclass
class Venta:
    sindicato: str            # nombre en ingles, como en los datos
    titulo: str = ""          # titulo del rango en los datos ("General"); "" si no lo trae
    rango: int | None = None  # 1..5, o None si no se sabe
    coste: int | None = None  # reputacion; None si no se sabe


@dataclass
class Aumento:
    item_id: int
    nombre_en: str
    para: str                 # nombre en ingles del warframe o arma ("Rhino", "Hek")
    para_id: int | None
    clase: str                # "warframe" o "arma"
    ventas: list[Venta] = field(default_factory=list)


def nombre_sindicato(sindicato: str) -> str:
    if es_castellano():
        return NOMBRE_ES.get(sindicato, sindicato)
    return sindicato


def _rango_de(sindicato: str, titulo: str) -> int | None:
    titulos = RANGOS.get(sindicato)
    if not titulos or not titulo:
        return None
    for i, nombre in enumerate(titulos):
        if nombre.lower() == titulo.strip().lower():
            return i + 1
    return None


def _ventas(con: sqlite3.Connection, item_id: int | None = None) -> dict[int, list[Venta]]:
    """Las ventas de los sindicatos por objeto; con `item_id`, solo las de ese objeto."""
    salida: dict[int, list[Venta]] = {}
    consulta = "SELECT item_id, origen_texto, standing, datos_extra FROM fuentes WHERE tipo = 'sindicato'"
    try:
        if item_id is None:
            filas = con.execute(consulta).fetchall()
        else:
            filas = con.execute(consulta + " AND item_id = ?", (int(item_id),)).fetchall()
    except sqlite3.Error:
        return salida
    for item_id, sindicato, standing, extra in filas:
        sindicato = (sindicato or "").strip()
        titulo = ""
        try:
            lugar = (json.loads(extra) if extra else {}).get("lugar") or ""
        except (TypeError, ValueError):
            lugar = ""
        if "," in lugar:
            titulo = lugar.rsplit(",", 1)[1].strip()
        rango = _rango_de(sindicato, titulo)
        if rango is None:
            titulo = ""  # no es un titulo de rango conocido ("Complete The Sacrifice")
        venta = Venta(sindicato, titulo, rango, int(standing) if standing else None)
        lista = salida.setdefault(int(item_id), [])
        if not any(v.sindicato == venta.sindicato and v.rango == venta.rango and v.coste == venta.coste for v in lista):
            lista.append(venta)
    for lista in salida.values():
        lista.sort(key=lambda v: (v.sindicato not in RANGOS, v.sindicato))
    return salida


def _equipos(con: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    """Nombre en ingles (en minusculas) -> (id, "warframe"/"arma") de los warframes y armas.
    Es una consulta corta (sin JSON): se guarda por conexion."""
    clave = id(con)
    if clave in _EQUIPOS:
        return _EQUIPOS[clave]
    equipos: dict[str, tuple[int, str]] = {}
    marcas = ", ".join("?" for _ in CATEGORIAS_WARFRAME + CATEGORIAS_ARMA)
    for item_id, nombre_en, categoria in con.execute(
            f"SELECT id, nombre_en, categoria FROM items WHERE categoria IN ({marcas}) AND padre_id IS NULL"
            " ORDER BY length(unique_name) DESC", CATEGORIAS_WARFRAME + CATEGORIAS_ARMA):
        equipos[(nombre_en or "").strip().lower()] = (
            int(item_id), "warframe" if categoria in CATEGORIAS_WARFRAME else "arma")
    _EQUIPOS[clave] = equipos
    return equipos


def _aumento_de_fila(item_id, nombre_en, tipo, datos, equipos: dict[str, tuple[int, str]],
                     ventas: dict[int, list[Venta]]) -> Aumento | None:
    """El aumento de una fila (id, nombre, tipo, detalles) del indice, o None si no lo es."""
    if tipo and "Riven" in tipo:
        return None
    try:
        compat = ((json.loads(datos).get("mod") or {}).get("compat") or "").strip()
    except (TypeError, ValueError, AttributeError):
        return None
    equipo = equipos.get(compat.lower()) if compat else None
    if equipo is None:
        return None
    return Aumento(int(item_id), nombre_en or "", compat, equipo[0], equipo[1], ventas.get(int(item_id), []))


_CONSULTA_MODS = ("SELECT i.id, i.nombre_en, i.tipo, d.datos FROM items i JOIN detalles d ON d.item_id = i.id"
                  " WHERE i.categoria = 'Mods'")


def cargar(con: sqlite3.Connection) -> list[Aumento]:
    """Todos los aumentos del indice, por orden alfabetico del ingles. Se calcula una vez
    (lee el detalle de todos los mods: es para el diccionario, no para pintar una build)."""
    clave = id(con)
    if clave in _CACHE:
        return _CACHE[clave]
    try:
        equipos = _equipos(con)
        filas = con.execute(_CONSULTA_MODS).fetchall()
    except sqlite3.Error:
        equipos, filas = {}, []
    ventas = _ventas(con) if filas else {}
    salida = [a for a in (_aumento_de_fila(*fila, equipos, ventas) for fila in filas) if a is not None]
    salida.sort(key=lambda a: a.nombre_en.lower())
    for otra in [c for c in _SUELTOS if c != clave]:
        del _SUELTOS[otra]
    _CACHE.clear()
    _CACHE[clave] = salida
    _POR_ID.clear()
    _POR_ID[clave] = {a.item_id: a for a in salida}
    return salida


def olvidar_cache() -> None:
    _CACHE.clear()
    _POR_ID.clear()
    _SUELTOS.clear()
    _EQUIPOS.clear()


def de(con: sqlite3.Connection | None, item_id: int | None) -> Aumento | None:
    """El aumento con ese id, o None si ese objeto no es un aumento.

    Si el diccionario entero no esta cargado, se mira SOLO ese mod (su detalle y sus
    ventas): pintar la primera build de la sesion no puede pagar leer el detalle de todos
    los mods del indice en el hilo de la ventana (la ventana se quedaba parada ~0,6 s)."""
    if con is None or not item_id:
        return None
    clave, item_id = id(con), int(item_id)
    if clave in _POR_ID:
        return _POR_ID[clave].get(item_id)
    sueltos = _SUELTOS.setdefault(clave, {})
    if item_id in sueltos:
        return sueltos[item_id]
    aumento = None
    try:
        fila = con.execute(_CONSULTA_MODS + " AND i.id = ?", (item_id,)).fetchone()
        if fila is not None:
            aumento = _aumento_de_fila(*fila, _equipos(con), {})
            if aumento is not None:
                aumento.ventas = _ventas(con, item_id).get(item_id, [])
    except sqlite3.Error:
        aumento = None
    sueltos[item_id] = aumento
    return aumento


def rangos_del_perfil(usuario: sqlite3.Connection | None = None) -> dict[str, tuple[int, int]]:
    """{etiqueta del sindicato: (rango, reputacion)} del perfil guardado; vacio si no hay
    perfil. Sin `usuario` se abre la base del usuario en solo lectura."""
    cerrar = False
    if usuario is None:
        try:
            from ..estado import usuario_db

            ruta = usuario_db.RUTA_USUARIO_DB
            if not ruta.exists():
                return {}
            usuario = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
            cerrar = True
        except Exception:  # noqa: BLE001 - sin perfil no se sabe, y ya esta
            return {}
    try:
        return {tag: (int(titulo), int(standing))
                for tag, standing, titulo in usuario.execute("SELECT tag, standing, titulo FROM perfil_sindicatos")}
    except sqlite3.Error:
        return {}
    finally:
        if cerrar:
            usuario.close()


def puede_comprar(venta: Venta, rangos: dict[str, tuple[int, int]] | None) -> bool | None:
    """True/False si se sabe el rango que pide la venta y el del jugador; None si no."""
    etiqueta = ETIQUETA_PERFIL.get(venta.sindicato)
    if not rangos or venta.rango is None or etiqueta not in rangos:
        return None
    return rangos[etiqueta][0] >= venta.rango


def texto_venta(venta: Venta) -> str:
    """"Meridiano de Acero · rango 5 (General) · 25.000 de reputación"; lo que falte, "no se sabe"."""
    if venta.rango is not None:
        rango = t("rango {n} ({titulo})", n=venta.rango, titulo=venta.titulo)
    else:
        rango = t("rango: no se sabe")
    if venta.coste is not None:
        coste = t("{n} de reputación", n=f"{venta.coste:,}".replace(",", "."))
    else:
        coste = t("coste: no se sabe")
    return f"{nombre_sindicato(venta.sindicato)} · {rango} · {coste}"


def texto_puedes(venta: Venta, rangos: dict[str, tuple[int, int]] | None) -> tuple[str, str]:
    """(texto, tinta) sobre si el jugador puede comprarlo; ("", "") si no se sabe."""
    puede = puede_comprar(venta, rangos)
    if puede is None:
        return "", ""
    rango, _reputacion = rangos[ETIQUETA_PERFIL[venta.sindicato]]
    if puede:
        return t("Según tu perfil eres rango {n}: ya puedes comprarlo.", n=rango), "ok"
    return t("Según tu perfil eres rango {n}: todavía no llegas.", n=rango), "aviso"


def lineas(con: sqlite3.Connection | None, item_id: int | None,
           rangos: dict[str, tuple[int, int]] | None = None) -> list[tuple[str, str]]:
    """Lo que hay que decir de un aumento en su ficha o en el recuadro: [(texto, tinta)].
    Lista vacia si el objeto no es un aumento."""
    aumento = de(con, item_id)
    if aumento is None:
        return []
    para = nombres_juego.nombre(con, aumento.para_id, aumento.para)
    salida = [(t("Aumento de {equipo}", equipo=para), "")]
    if not aumento.ventas:
        salida.append((t("Según los datos no lo vende ningún sindicato: mira en su ficha de dónde sale."), "suave"))
        return salida
    for venta in aumento.ventas:
        salida.append((texto_venta(venta), ""))
        texto, tinta = texto_puedes(venta, rangos)
        if texto:
            salida.append((texto, tinta))
    return salida
