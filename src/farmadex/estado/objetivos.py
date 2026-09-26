"""Objetivos de farmeo: que quiere conseguir el usuario y como va.

Reglas del contador (lo pidio un tester: "el contador se pasa de la meta"):
- La meta es un entero entre 1 y `MAX_CANTIDAD`; lo conseguido, entre 0 y la meta.
- Sumar nunca pasa de la meta. Para seguir hay que ampliar la meta a proposito
  (`ampliar_meta`), que en la interfaz va con confirmacion.
- Al crear un objetivo se tiene en cuenta lo que el inventario leido dice que ya tienes.

Para la pestana, los objetivos se juntan en "entradas": un objetivo suelto o un set
(varias piezas del mismo objeto), que se pinta como un solo panel desplegable.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from ..datos import relaciones
from ..registro_log import obtener

log = obtener("objetivos")

MAX_CANTIDAD = 999_999
POR_PAGINA = 10

# Estados de la pestana, en el orden de sus pestanas.
SIN_EMPEZAR, EN_PROGRESO, COMPLETADOS = "sin_empezar", "en_progreso", "completados"
ESTADOS = (SIN_EMPEZAR, EN_PROGRESO, COMPLETADOS)

# Categorias del filtro. Se guardan en la BD del usuario con estas claves.
SETS, WARFRAMES, ARMAS, RECURSOS, OTROS = "sets", "warframes", "armas", "recursos", "otros"
CATEGORIAS = (SETS, WARFRAMES, ARMAS, RECURSOS, OTROS)
_CATEGORIAS_ARMA = frozenset(
    {"Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee", "SentinelWeapons"}
)


@dataclass
class Objetivo:
    id: int
    unique_name: str
    nombre: str
    objetivo: int
    actual: int
    completado: bool
    creado_en: str = ""
    categoria: str | None = None
    grupo: str | None = None
    grupo_nombre: str | None = None
    # Recursos de fabricacion con algo marcado: cuenta como "en progreso".
    recursos_empezados: int = 0

    @property
    def porcentaje(self) -> int:
        if self.objetivo <= 0:
            return 100
        return min(100, int(self.actual * 100 / self.objetivo))

    @property
    def estado(self) -> str:
        if self.completado:
            return COMPLETADOS
        if self.actual > 0 or self.recursos_empezados:
            return EN_PROGRESO
        return SIN_EMPEZAR


@dataclass
class Entrada:
    """Lo que ocupa una fila en la pestana: un objetivo o un set con sus piezas."""

    clave: str
    nombre: str
    objetivos: list[Objetivo] = field(default_factory=list)
    es_set: bool = False

    @property
    def categoria(self) -> str:
        if self.es_set:
            return SETS
        return self.objetivos[0].categoria or OTROS

    @property
    def creado_en(self) -> str:
        return max(o.creado_en for o in self.objetivos)

    @property
    def ultimo_id(self) -> int:
        return max(o.id for o in self.objetivos)

    @property
    def hechas(self) -> int:
        return sum(1 for o in self.objetivos if o.completado)

    @property
    def estado(self) -> str:
        if all(o.completado for o in self.objetivos):
            return COMPLETADOS
        if any(o.estado != SIN_EMPEZAR for o in self.objetivos):
            return EN_PROGRESO
        return SIN_EMPEZAR


@dataclass
class Recurso:
    """Un recurso de fabricacion de un objetivo (750 Ferrita de la Magistar)."""

    unique_name: str
    nombre_en: str
    nombre_es: str | None
    necesario: int
    actual: int
    en_inventario: int | None = None

    @property
    def completado(self) -> bool:
        return self.actual >= self.necesario


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def validar_cantidad(valor, minimo: int = 1, maximo: int = MAX_CANTIDAD) -> int:
    """Entero entre `minimo` y `maximo`. Lo que no es un entero da ValueError.

    Acepta "500" o " 1.000 " (con puntos de miles) porque es lo que escribe la gente.
    Lo que se sale del rango se lleva al borde: nada de numeros que desaparecen.
    """
    if isinstance(valor, bool):
        raise ValueError("no es una cantidad")
    if isinstance(valor, str):
        texto = valor.strip().replace(".", "").replace(" ", "")
        if not texto.lstrip("-").isdigit():
            raise ValueError(f"no es un numero entero: {valor!r}")
        valor = int(texto)
    if isinstance(valor, float):
        if not valor.is_integer():
            raise ValueError(f"no es un numero entero: {valor!r}")
        valor = int(valor)
    if not isinstance(valor, int):
        raise ValueError(f"no es una cantidad: {valor!r}")
    return max(minimo, min(maximo, valor))


# -- consultas ----------------------------------------------------------------

_COLUMNAS = (
    "o.id, o.item_unique_name, o.nombre, o.cantidad_objetivo, o.cantidad_actual, o.completado_en, "
    "o.creado_en, o.categoria, o.grupo, o.grupo_nombre, "
    "(SELECT COUNT(*) FROM objetivo_recursos r WHERE r.objetivo_id = o.id AND r.cantidad_actual > 0)"
)


def _objetivo(f) -> Objetivo:
    return Objetivo(f[0], f[1], f[2], f[3], f[4], bool(f[5]), f[6] or "", f[7], f[8], f[9], f[10] or 0)


def listar(usuario: sqlite3.Connection) -> list[Objetivo]:
    filas = usuario.execute(
        f"SELECT {_COLUMNAS} FROM objetivos o "
        "ORDER BY o.completado_en IS NOT NULL, COALESCE(o.orden, o.id)"
    ).fetchall()
    return [_objetivo(f) for f in filas]


def obtener_objetivo(usuario: sqlite3.Connection, objetivo_id: int) -> Objetivo | None:
    fila = usuario.execute(
        f"SELECT {_COLUMNAS} FROM objetivos o WHERE o.id = ?", (objetivo_id,)
    ).fetchone()
    return _objetivo(fila) if fila else None


def entradas(
    usuario: sqlite3.Connection, estado: str | None = None, categoria: str | None = None
) -> list[Entrada]:
    """Objetivos juntados por set, los mas recientes primero, con los filtros aplicados."""
    grupos: dict[str, list[Objetivo]] = {}
    sueltos: list[Objetivo] = []
    for objetivo in listar(usuario):
        if objetivo.grupo:
            grupos.setdefault(objetivo.grupo, []).append(objetivo)
        else:
            sueltos.append(objetivo)

    lista: list[Entrada] = [Entrada(f"o:{o.id}", o.nombre, [o]) for o in sueltos]
    for grupo, piezas in grupos.items():
        if len(piezas) == 1:
            # Una sola pieza del set: fila normal, no hace falta desplegar nada.
            lista.append(Entrada(f"o:{piezas[0].id}", piezas[0].nombre, piezas))
            continue
        piezas.sort(key=lambda o: o.nombre)
        nombre = piezas[0].grupo_nombre or piezas[0].nombre.split(":")[0]
        lista.append(Entrada(f"g:{grupo}", nombre, piezas, es_set=True))

    if estado:
        lista = [e for e in lista if e.estado == estado]
    if categoria:
        lista = [e for e in lista if e.categoria == categoria]
    lista.sort(key=lambda e: (e.creado_en, e.ultimo_id), reverse=True)
    return lista


def contar_por_estado(lista: list[Entrada]) -> dict[str, int]:
    cuenta = dict.fromkeys(ESTADOS, 0)
    for entrada in lista:
        cuenta[entrada.estado] += 1
    return cuenta


def paginar(lista: list, pagina: int, por_pagina: int = POR_PAGINA) -> tuple[list, int, int]:
    """(trozo, pagina de verdad, total de paginas). Paginas desde 0; nunca se sale de rango."""
    total = max(1, -(-len(lista) // por_pagina))
    pagina = max(0, min(pagina, total - 1))
    return lista[pagina * por_pagina:(pagina + 1) * por_pagina], pagina, total


# -- categoria y set a partir del indice -----------------------------------------


def categoria_de(categoria_indice: str | None, tiene_padre: bool) -> str:
    if tiene_padre:
        return SETS
    if categoria_indice == "Warframes":
        return WARFRAMES
    if categoria_indice in _CATEGORIAS_ARMA:
        return ARMAS
    if categoria_indice == "Resources":
        return RECURSOS
    return OTROS


def datos_del_item(indice: sqlite3.Connection, unique_name: str) -> tuple[str, str | None, str | None] | None:
    """(categoria, grupo, nombre del grupo) de un objeto, o None si el indice no lo tiene."""
    fila = indice.execute(
        "SELECT i.categoria, i.padre_id, p.unique_name, p.nombre_en, p.nombre_es "
        "FROM items i LEFT JOIN items p ON p.id = i.padre_id WHERE i.unique_name = ?",
        (unique_name,),
    ).fetchone()
    if not fila:
        return None
    categoria_indice, padre_id, padre_unico, padre_en, padre_es = fila
    if not padre_id:
        return categoria_de(categoria_indice, False), None, None
    return SETS, padre_unico, padre_es or padre_en


def completar_datos(usuario: sqlite3.Connection, indice: sqlite3.Connection) -> int:
    """Rellena categoria y set de los objetivos que no los tienen (los de antes de la v3)."""
    pendientes = usuario.execute(
        "SELECT id, item_unique_name FROM objetivos WHERE categoria IS NULL"
    ).fetchall()
    cambiados = 0
    for objetivo_id, unico in pendientes:
        try:
            datos = datos_del_item(indice, unico)
        except sqlite3.Error:
            return cambiados  # indice a medio reconstruir: otra vez sera
        categoria, grupo, grupo_nombre = datos or (OTROS, None, None)
        usuario.execute(
            "UPDATE objetivos SET categoria = ?, grupo = ?, grupo_nombre = ? WHERE id = ?",
            (categoria, grupo, grupo_nombre, objetivo_id),
        )
        cambiados += 1
    if cambiados:
        usuario.commit()
        log.info("Objetivos clasificados por categoria: %d", cambiados)
    return cambiados


def _cantidad_inventario(usuario: sqlite3.Connection, unique_name: str) -> int | None:
    """Lo que el inventario leido en pantalla dice que tienes (sin crear tablas)."""
    try:
        fila = usuario.execute(
            "SELECT cantidad FROM inventario_lecturas WHERE item_type = ?", (unique_name,)
        ).fetchone()
    except sqlite3.Error:
        return None
    return fila[0] if fila and fila[0] is not None else None


# -- altas ------------------------------------------------------------------------


def anadir(
    usuario: sqlite3.Connection,
    unique_name: str,
    nombre: str,
    cantidad: int = 1,
    *,
    indice: sqlite3.Connection | None = None,
    categoria: str | None = None,
    grupo: str | None = None,
    grupo_nombre: str | None = None,
) -> int:
    """Alta idempotente: si ya estaba, solo sube la meta si se pide mas."""
    cantidad = validar_cantidad(cantidad or 1)
    if categoria is None and indice is not None:
        try:
            datos = datos_del_item(indice, unique_name)
        except sqlite3.Error:
            datos = None
        if datos:
            categoria, grupo_indice, nombre_indice = datos
            grupo = grupo or grupo_indice
            grupo_nombre = grupo_nombre or nombre_indice
    existente = usuario.execute(
        "SELECT id, cantidad_objetivo, cantidad_actual, categoria FROM objetivos "
        "WHERE item_unique_name = ?",
        (unique_name,),
    ).fetchone()
    if existente:
        objetivo_id, meta, actual, categoria_vieja = existente
        if cantidad > meta:
            # Meta mas alta: si ya estaba completado, vuelve a estar pendiente.
            usuario.execute(
                "UPDATE objetivos SET cantidad_objetivo = ?, "
                "completado_en = CASE WHEN ? >= ? THEN completado_en END WHERE id = ?",
                (cantidad, actual, cantidad, objetivo_id),
            )
        if categoria_vieja is None and categoria is not None:
            usuario.execute(
                "UPDATE objetivos SET categoria = ?, grupo = ?, grupo_nombre = ? WHERE id = ?",
                (categoria, grupo, grupo_nombre, objetivo_id),
            )
        usuario.commit()
        return objetivo_id

    ahora = _ahora()
    ya_tienes = _cantidad_inventario(usuario, unique_name)
    actual = min(cantidad, max(0, ya_tienes or 0))
    cursor = usuario.execute(
        "INSERT INTO objetivos (item_unique_name, nombre, cantidad_objetivo, cantidad_actual, "
        "creado_en, completado_en, categoria, grupo, grupo_nombre) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (unique_name, nombre, cantidad, actual, ahora, ahora if actual >= cantidad else None,
         categoria, grupo, grupo_nombre),
    )
    if actual:
        usuario.execute(
            "INSERT INTO progreso_eventos (objetivo_id, origen, cantidad, detalle, creado_en) "
            "VALUES (?, 'inventario', ?, ?, ?)",
            (cursor.lastrowid, actual, f"inventario: {ya_tienes}", ahora),
        )
    usuario.commit()
    return cursor.lastrowid


def anadir_set(usuario: sqlite3.Connection, indice: sqlite3.Connection, item_id: int) -> list[int]:
    """Anade todas las piezas de un objeto construible, cada una con su cantidad."""
    fila = indice.execute(
        "SELECT id, unique_name, nombre_en, nombre_es, padre_id FROM items WHERE id = ?", (item_id,)
    ).fetchone()
    if not fila:
        return []
    padre_id = fila[4] or fila[0]
    padre = indice.execute(
        "SELECT unique_name, nombre_en, nombre_es, categoria FROM items WHERE id = ?", (padre_id,)
    ).fetchone()
    componentes = indice.execute(
        "SELECT unique_name, nombre_en, nombre_es, item_count FROM items WHERE padre_id = ?",
        (padre_id,),
    ).fetchall()

    nombre_padre = padre[2] or padre[1]
    if not componentes:
        return [anadir(usuario, padre[0], nombre_padre, 1, categoria=categoria_de(padre[3], False))]
    return [
        anadir(
            usuario,
            unico,
            f"{nombre_padre}: {nombre_es or nombre_en}",
            cantidad or 1,
            categoria=SETS,
            grupo=padre[0],
            grupo_nombre=nombre_padre,
        )
        for unico, nombre_en, nombre_es, cantidad in componentes
    ]


# -- progreso ---------------------------------------------------------------------


def _guardar_progreso(
    usuario: sqlite3.Connection, objetivo_id: int, meta: int, nuevo: int, antes: int,
    completado_en: str | None, origen: str, detalle: str,
) -> None:
    completado = (completado_en or _ahora()) if nuevo >= meta else None
    usuario.execute(
        "UPDATE objetivos SET cantidad_objetivo = ?, cantidad_actual = ?, completado_en = ? "
        "WHERE id = ?",
        (meta, nuevo, completado, objetivo_id),
    )
    if nuevo != antes:
        usuario.execute(
            "INSERT INTO progreso_eventos (objetivo_id, origen, cantidad, detalle, creado_en) "
            "VALUES (?, ?, ?, ?, ?)",
            (objetivo_id, origen, nuevo - antes, detalle, _ahora()),
        )
    usuario.commit()


def sumar(
    usuario: sqlite3.Connection, objetivo_id: int, cantidad: int = 1, origen: str = "manual",
    detalle: str = "",
) -> Objetivo | None:
    """Suma (o resta, en negativo) sin salirse de 0..meta."""
    fila = usuario.execute(
        "SELECT cantidad_objetivo, cantidad_actual, completado_en FROM objetivos WHERE id = ?",
        (objetivo_id,),
    ).fetchone()
    if not fila:
        return None
    meta, antes, completado_en = fila
    nuevo = max(0, min(meta, antes + int(cantidad)))
    _guardar_progreso(usuario, objetivo_id, meta, nuevo, antes, completado_en, origen, detalle)
    return obtener_objetivo(usuario, objetivo_id)


def fijar(
    usuario: sqlite3.Connection, objetivo_id: int, meta=None, actual=None, origen: str = "manual",
) -> Objetivo | None:
    """Pone la meta y/o lo conseguido a mano. Lo conseguido nunca queda por encima de la meta."""
    fila = usuario.execute(
        "SELECT cantidad_objetivo, cantidad_actual, completado_en FROM objetivos WHERE id = ?",
        (objetivo_id,),
    ).fetchone()
    if not fila:
        return None
    meta_vieja, antes, completado_en = fila
    meta = validar_cantidad(meta) if meta is not None else meta_vieja
    nuevo = validar_cantidad(actual, 0, meta) if actual is not None else min(antes, meta)
    _guardar_progreso(usuario, objetivo_id, meta, nuevo, antes, completado_en, origen, "")
    return obtener_objetivo(usuario, objetivo_id)


def ampliar_meta(usuario: sqlite3.Connection, objetivo_id: int, extra: int) -> Objetivo | None:
    """Sube la meta en `extra` (lo que se hace, con confirmacion, al pasar del 100%)."""
    objetivo = obtener_objetivo(usuario, objetivo_id)
    if objetivo is None:
        return None
    return fijar(usuario, objetivo_id, meta=objetivo.objetivo + validar_cantidad(extra))


def completar(
    usuario: sqlite3.Connection, objetivo_id: int, indice: sqlite3.Connection | None = None
) -> Objetivo | None:
    """Da el objetivo por conseguido entero (y sus recursos de fabricacion, si tiene)."""
    objetivo = obtener_objetivo(usuario, objetivo_id)
    if objetivo is None:
        return None
    for recurso in recursos_de(usuario, indice, objetivo):
        fijar_recurso(usuario, objetivo, recurso, recurso.necesario)
    return fijar(usuario, objetivo_id, actual=objetivo.objetivo)


def sumar_por_item(
    usuario: sqlite3.Connection, unique_name: str, cantidad: int = 1, origen: str = "ocr"
) -> Objetivo | None:
    """Suma a un objetivo a partir del objeto, si es que ese objeto esta en la lista."""
    fila = usuario.execute(
        "SELECT id FROM objetivos WHERE item_unique_name = ?", (unique_name,)
    ).fetchone()
    if not fila:
        return None
    return sumar(usuario, fila[0], cantidad, origen=origen, detalle=unique_name)


def borrar(usuario: sqlite3.Connection, objetivo_id: int) -> None:
    usuario.execute("DELETE FROM progreso_eventos WHERE objetivo_id = ?", (objetivo_id,))
    usuario.execute("DELETE FROM objetivo_recursos WHERE objetivo_id = ?", (objetivo_id,))
    usuario.execute("DELETE FROM objetivos WHERE id = ?", (objetivo_id,))
    usuario.commit()


def borrar_varios(usuario: sqlite3.Connection, ids) -> int:
    ids = list(dict.fromkeys(int(i) for i in ids))
    for objetivo_id in ids:
        usuario.execute("DELETE FROM progreso_eventos WHERE objetivo_id = ?", (objetivo_id,))
        usuario.execute("DELETE FROM objetivo_recursos WHERE objetivo_id = ?", (objetivo_id,))
        usuario.execute("DELETE FROM objetivos WHERE id = ?", (objetivo_id,))
    usuario.commit()
    return len(ids)


# -- recursos de fabricacion ------------------------------------------------------


def receta_de(indice: sqlite3.Connection | None, unique_name: str) -> list[tuple[str, str, str | None, int]]:
    """[(unique_name, nombre_en, nombre_es, cantidad)] de lo que pide fabricar el objeto.

    Sale de la tabla `recetas` del indice (desde la version 14). Con un indice mas viejo
    solo se conocen las piezas propias (las que no son recursos compartidos).
    """
    if indice is None:
        return []
    try:
        fila = indice.execute("SELECT id FROM items WHERE unique_name = ?", (unique_name,)).fetchone()
        if not fila:
            return []
        try:
            filas = indice.execute(
                "SELECT i.unique_name, i.nombre_en, i.nombre_es, r.cantidad FROM recetas r "
                "JOIN items i ON i.id = r.item_id WHERE r.padre_id = ? ORDER BY i.nombre_en",
                (fila[0],),
            ).fetchall()
        except sqlite3.OperationalError:  # indice sin la tabla recetas
            filas = []
        if not filas:
            filas = indice.execute(
                "SELECT unique_name, nombre_en, nombre_es, item_count FROM items "
                "WHERE padre_id = ? ORDER BY nombre_en",
                (fila[0],),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [(u, en, es, max(1, c or 1)) for u, en, es, c in filas]


def tiene_recursos(indice: sqlite3.Connection | None, unique_name: str) -> bool:
    """Si merece la pena abrir sus recursos: pide algo mas que el plano."""
    return len(receta_de(indice, unique_name)) >= 2


def recursos_de(
    usuario: sqlite3.Connection, indice: sqlite3.Connection | None, objetivo: Objetivo
) -> list[Recurso]:
    """Recursos de fabricacion del objetivo con lo marcado de cada uno.

    Lo necesario se multiplica por la meta (dos Magistar piden el doble de Ferrita).
    Lo que no se ha tocado a mano arranca con lo que diga el inventario leido.
    """
    guardados = {
        f[0]: f[1:]
        for f in usuario.execute(
            "SELECT item_unique_name, nombre, cantidad_objetivo, cantidad_actual "
            "FROM objetivo_recursos WHERE objetivo_id = ?",
            (objetivo.id,),
        )
    }
    salida = []
    receta = receta_de(indice, objetivo.unique_name)
    if receta:
        for unico, nombre_en, nombre_es, cantidad in receta:
            necesario = min(MAX_CANTIDAD, cantidad * max(1, objetivo.objetivo))
            inventario = _cantidad_inventario(usuario, unico)
            if unico in guardados:
                actual = guardados[unico][2]
            else:
                actual = inventario or 0
            salida.append(Recurso(unico, nombre_en, nombre_es, necesario,
                                  max(0, min(necesario, actual)), inventario))
    else:
        # Sin indice: lo que ya se habia marcado, tal cual.
        for unico, (nombre, necesario, actual) in sorted(guardados.items(), key=lambda x: x[1][0]):
            salida.append(Recurso(unico, nombre, nombre, necesario, min(actual, necesario),
                                  _cantidad_inventario(usuario, unico)))
    return salida


def fijar_recurso(usuario: sqlite3.Connection, objetivo: Objetivo, recurso: Recurso, actual) -> Recurso:
    """Guarda lo conseguido de un recurso (0..necesario) y lo devuelve al dia."""
    actual = validar_cantidad(actual, 0, recurso.necesario)
    usuario.execute(
        "INSERT INTO objetivo_recursos (objetivo_id, item_unique_name, nombre, cantidad_objetivo, "
        "cantidad_actual) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(objetivo_id, item_unique_name) DO UPDATE SET "
        "cantidad_objetivo = excluded.cantidad_objetivo, cantidad_actual = excluded.cantidad_actual",
        (objetivo.id, recurso.unique_name, recurso.nombre_es or recurso.nombre_en,
         recurso.necesario, actual),
    )
    usuario.commit()
    recurso.actual = actual
    return recurso


def sumar_recurso(usuario: sqlite3.Connection, objetivo: Objetivo, recurso: Recurso, cantidad: int) -> Recurso:
    return fijar_recurso(
        usuario, objetivo, recurso, max(0, min(recurso.necesario, recurso.actual + int(cantidad)))
    )


# -- rutas ----------------------------------------------------------------------


def ruta_de(indice: sqlite3.Connection, unique_name: str) -> dict | None:
    """Por donde conseguir ese objetivo ahora mismo."""
    fila = indice.execute("SELECT id FROM items WHERE unique_name = ?", (unique_name,)).fetchone()
    if not fila:
        return None
    return relaciones.mejor_ruta(indice, fila[0])


def eras_necesarias(indice: sqlite3.Connection, usuario: sqlite3.Connection) -> dict[str, list[str]]:
    """Que eras de reliquia hacen falta para lo que queda por farmear.

    Sirve para marcar en la pestana Mundo las fisuras que te interesan.
    """
    salida: dict[str, list[str]] = {}
    for objetivo in listar(usuario):
        if objetivo.completado:
            continue
        ruta = ruta_de(indice, objetivo.unique_name)
        # Lo que no cae de reliquia (jefes, bounties...) no pide ninguna era.
        if not ruta or ruta.get("tipo", "reliquia") != "reliquia" or not ruta.get("reliquia"):
            continue
        if ruta["solo_en_boveda"]:
            continue
        era = (ruta["reliquia"]["nombre_en"] or "").split(" ")[0]
        if era:
            salida.setdefault(era, []).append(objetivo.nombre)
    return salida
