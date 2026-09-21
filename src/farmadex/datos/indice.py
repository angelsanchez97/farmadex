"""Construccion del indice SQLite y busqueda de objetos."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from rapidfuzz import fuzz, process as rf_process

from ..config import DIR_DATOS, DIR_RECURSOS, RUTA_INDICE, crear_carpetas
from ..registro_log import obtener
from .descargas import CATEGORIAS_ITEMS, Descargador
from . import nodos
from .drops import UMBRAL_SIN_CASAR, ImportadorDrops
from .items import ImportadorItems, normalizar

log = obtener("indice")

# Subirla obliga a reconstruir el indice (sin volver a descargar) en el siguiente arranque.
# 2: indice (item_id, tipo) en fuentes, nodos de Railjack desde las tablas de drops.
# 3: los recursos dejan de ser "piezas" de la primera warframe que los usaba.
# 4: ingrediente de 3+ recetas = recurso aunque no tenga ficha propia; los de Misc pasan a Resources.
# 5: nodos que DE no publica (Railjack, eventos, Duviri, retirados) desde solNodes.json de WFCD.
# 6: nombres sin etiquetas de icono, alias propio de las piezas con nombre unico, el plano de
#    un recurso va en su categoria, y probabilidades siempre numericas.
VERSION_ESQUEMA = "6"

def conectar(ruta: Path = RUTA_INDICE) -> sqlite3.Connection:
    con = sqlite3.connect(ruta)
    con.execute("PRAGMA foreign_keys=ON")
    return con


def hay_indice(ruta: Path = RUTA_INDICE) -> bool:
    if not ruta.exists():
        return False
    try:
        con = conectar(ruta)
    except sqlite3.Error:
        return False
    try:
        meta = dict(con.execute("SELECT clave, valor FROM meta"))
        tiene_items = con.execute("SELECT 1 FROM items LIMIT 1").fetchone()
        return bool(
            meta.get("construido_en")
            and tiene_items
            and meta.get("esquema_version") == VERSION_ESQUEMA
        )
    except sqlite3.Error:
        return False
    finally:
        con.close()


def crear_esquema(con: sqlite3.Connection) -> None:
    con.executescript((DIR_RECURSOS / "esquema.sql").read_text(encoding="utf-8"))


def importar_glosario(con: sqlite3.Connection) -> None:
    datos = json.loads((DIR_RECURSOS / "glosario_es.json").read_text(encoding="utf-8"))
    for dominio, pares in datos.items():
        con.executemany(
            "INSERT OR REPLACE INTO glosario (dominio, en, es) VALUES (?, ?, ?)",
            [(dominio, en, es) for en, es in pares.items()],
        )


def leer_meta(ruta: Path = RUTA_INDICE) -> dict:
    """La tabla meta del indice (versiones de los datos); vacio si no hay indice."""
    if not hay_indice(ruta):
        return {}
    con = conectar(ruta)
    try:
        return dict(con.execute("SELECT clave, valor FROM meta").fetchall())
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def fecha_de_meta(valor: str | None):
    """items_fecha viene en ISO; drops_modified en milisegundos desde 1970. Devuelve date o None."""
    from datetime import date, datetime, timezone

    if not valor:
        return None
    valor = str(valor).strip()
    try:
        if valor.isdigit():
            segundos = int(valor) / (1000 if len(valor) > 10 else 1)
            return datetime.fromtimestamp(segundos, tz=timezone.utc).date()
        return date.fromisoformat(valor[:10])
    except (ValueError, OverflowError, OSError):
        return None


# Dias tras un parche en los que el desfase se anuncia en grande. Pasados, si WFCD y DE
# siguen sin publicar es que ese parche no toco los drops (las tablas de DE pueden
# quedarse meses sin cambiar): el dato se deja en Ajustes y no se molesta mas.
DIAS_PARCHE_RECIENTE = 14


def parche_reciente(fecha_build, hoy=None, dias: int = DIAS_PARCHE_RECIENTE) -> bool:
    """True si el build del juego es de los ultimos `dias` (o de hoy o del futuro)."""
    from datetime import date

    if not fecha_build:
        return False
    hoy = hoy or date.today()
    return (hoy - fecha_build).days <= dias


def desfase_con_el_juego(meta: dict, fecha_build) -> list[tuple[str, str]]:
    """Que fuentes de datos son anteriores al parche que tiene instalado el juego.

    Devuelve pares (fuente, fecha) de lo que va por detras; vacio si todo esta al dia
    o si no se puede saber. Las horas o dias siguientes a un parche WFCD y DE aun no
    han publicado, y esto es lo que permite avisar en vez de ensenar datos viejos.
    """
    if not fecha_build or not meta:
        return []
    atrasadas = []
    for clave, fuente in (("items_fecha", "catalogo de objetos"), ("drops_modified", "tablas de drops")):
        fecha = fecha_de_meta(meta.get(clave))
        if fecha and fecha < fecha_build:
            atrasadas.append((fuente, fecha.isoformat()))
    return atrasadas


def traducir(con: sqlite3.Connection, dominio: str, en: str | None) -> str:
    if not en:
        return ""
    fila = con.execute(
        "SELECT es FROM glosario WHERE dominio = ? AND en = ?", (dominio, en)
    ).fetchone()
    return fila[0] if fila else en


def poblar_busqueda(con: sqlite3.Connection) -> int:
    """Una fila por nombre buscable. Los componentes llevan tambien el nombre del padre."""
    con.execute("DELETE FROM busqueda")
    filas = con.execute(
        """
        SELECT i.id, i.nombre_en, i.nombre_es, i.categoria,
               p.nombre_en AS padre_en, p.nombre_es AS padre_es
          FROM items i LEFT JOIN items p ON i.padre_id = p.id
        """
    ).fetchall()
    lote = []
    for iid, nombre_en, nombre_es, categoria, padre_en, padre_es in filas:
        textos = set()
        if padre_en:
            textos.add((normalizar(f"{padre_en} {nombre_en}"), "en"))
            if nombre_es:
                textos.add((normalizar(f"{padre_es or padre_en} {nombre_es}"), "es"))
        else:
            textos.add((normalizar(nombre_en), "en"))
            if nombre_es:
                textos.add((normalizar(nombre_es), "es"))
        for texto, idioma in textos:
            if texto:
                lote.append((texto, iid, idioma, categoria))
    con.executemany(
        "INSERT INTO busqueda (texto, item_id, idioma, categoria) VALUES (?, ?, ?, ?)", lote
    )
    return len(lote)


def construir(progreso=None, forzar: bool = False) -> dict:
    """Descarga lo que falte y reconstruye el indice entero. Devuelve un resumen."""
    crear_carpetas()
    inicio = time.time()

    def avisar(texto, hechos=0, total=0):
        if progreso:
            progreso(texto, hechos, total)

    descargador = Descargador(progreso=avisar)
    try:
        cambios = descargador.sincronizar(forzar=forzar)
    finally:
        descargador.cerrar()

    if not cambios and hay_indice() and not forzar:
        log.info("Datos al dia y el indice ya existe; no se reconstruye")
        avisar("Datos al dia", 1, 1)
        return {"reconstruido": False}

    tmp = RUTA_INDICE.with_suffix(".nuevo")
    tmp.unlink(missing_ok=True)
    con = conectar(tmp)
    try:
        crear_esquema(con)
        importar_glosario(con)

        avisar("Cargando traducciones al espanol", 0, 0)
        ruta_i18n = DIR_DATOS / "i18n_es.json"
        i18n = json.loads(ruta_i18n.read_text(encoding="utf-8")) if ruta_i18n.exists() else {}

        importador = ImportadorItems(con, i18n)
        total = len(CATEGORIAS_ITEMS)
        objetos = 0
        for i, categoria in enumerate(CATEGORIAS_ITEMS, start=1):
            ruta = DIR_DATOS / f"{categoria}.json"
            avisar(f"Importando objetos: {categoria} ({i}/{total})", i - 1, total)
            if not ruta.exists():
                log.warning("Falta el catalogo %s", categoria)
                continue
            objetos += importador.importar_categoria(ruta)
        recursos = importador.promocionar_ingredientes()
        log.info("Ingredientes de receta tratados como recurso: %d", recursos)
        log.info(
            "Piezas con alias propio: %d", importador.registrar_piezas_con_nombre_propio()
        )
        con.commit()

        avisar("Enlazando reliquias", 0, 0)
        enlazadas = importador.enlazar_reliquias()

        avisar("Traduciendo el mapa estelar", 0, 0)
        try:
            nodos.sincronizar(con)
        except Exception:  # noqa: BLE001 - sin traduccion se sigue en ingles
            log.exception("No se pudo sincronizar el mapa estelar de DE")
        con.commit()

        rutas_drops = {
            f.stem: f for f in (DIR_DATOS / "drops").glob("*.json")
        }
        idrops = ImportadorDrops(con, importador.alias)
        idrops.importar_todo(rutas_drops, progreso=avisar)
        avisar("Completando el mapa con los nodos que DE no publica", 0, 0)
        try:
            # Despues de los drops: asi los nodos que estos dieron de alta por nombre
            # reciben su identificador de verdad en vez de duplicarse.
            nodos.completar_solnodes(con)
        except Exception:  # noqa: BLE001 - sin esto el mapa se queda como estaba
            log.exception("No se pudieron completar los nodos con WFCD")
        avisar("Enlazando misiones con el mapa", 0, 0)
        reenlace = nodos.reenlazar_fuentes(con)
        con.commit()

        avisar("Emparejando con warframe.market", 0, 0)
        try:
            # La instancia compartida: el catalogo /items queda en cache para el
            # buscador y el comparador, y no se cierra aqui porque ellos la usan.
            from ..online.market import compartido

            compartido().emparejar(con)
        except Exception:  # noqa: BLE001 - sin precios la aplicacion sigue entera
            log.exception("No se pudo emparejar con warframe.market")

        avisar("Construyendo el indice de busqueda", 0, 0)
        entradas = poblar_busqueda(con)

        estado = descargador.estado
        con.executemany(
            "INSERT OR REPLACE INTO meta (clave, valor) VALUES (?, ?)",
            [
                ("esquema_version", VERSION_ESQUEMA),
                ("items_sha", estado.items_sha),
                ("items_fecha", estado.items_fecha),
                ("drops_hash", estado.drops_hash),
                ("drops_modified", estado.drops_modified),
                ("construido_en", time.strftime("%Y-%m-%dT%H:%M:%S")),
            ],
        )
        con.commit()
        # Sin estadisticas el planificador elegia mal los indices de 'fuentes'.
        con.execute("ANALYZE")
        con.execute("VACUUM")
    finally:
        con.close()

    # Intercambio atomico: el indice viejo solo se sustituye si el nuevo acabo bien.
    for sufijo in ("-wal", "-shm"):
        Path(str(RUTA_INDICE) + sufijo).unlink(missing_ok=True)
    RUTA_INDICE.unlink(missing_ok=True)
    tmp.replace(RUTA_INDICE)

    resumen = {
        "reconstruido": True,
        "objetos": objetos,
        "reliquias_enlazadas": enlazadas,
        "entradas_busqueda": entradas,
        "misiones_enlazadas": reenlace["enlazadas"],
        "misiones_sin_nodo": reenlace["sin_nodo"],
        "sin_casar": len(idrops.sin_casar),
        "segundos": round(time.time() - inicio, 1),
    }
    log.info("Indice construido: %s", resumen)
    avisar("Indice listo", 1, 1)
    return resumen


# -- busqueda -----------------------------------------------------------


# Lo que el jugador busca de verdad va delante de lo cosmetico, que llena el catalogo.
GRUPO_CATEGORIA = {
    **dict.fromkeys(("Warframes", "Primary", "Secondary", "Melee", "Archwing", "Arch-Gun",
                     "Arch-Melee", "Sentinels", "SentinelWeapons", "Pets", "Mods", "Arcanes",
                     "Resources", "Relics"), 0),
    **dict.fromkeys(("Misc", "Gear", "Railjack", "Fish", "Quests"), 1),
    **dict.fromkeys(("Skins", "Glyphs", "Sigils", "Honoria"), 2),
}
GRUPO_COSMETICO = 2

# Dentro de lo farmeable, a igualdad de todo lo demas: "argon" es antes el cristal
# que el mod "Mira de argon".
ORDEN_CATEGORIA = {
    "Warframes": 0, "Primary": 1, "Secondary": 1, "Melee": 1, "Resources": 2, "Relics": 2,
    "Mods": 3, "Arcanes": 3,
}

# Por debajo de esto un resultado difuso es ruido ("erra" para "serracion").
CORTE_DIFUSO = 72

# "chasis de mesa prime", "plano del rhino": los nombres indexados no llevan estas
# particulas, y con ellas la busqueda caia en el difuso y devolvia el chasis de otra.
PALABRAS_VACIAS = frozenset({"de", "del", "la", "el", "los", "las", "of", "the"})


def _nivel(normal: str, palabras: list[str], texto: str) -> int:
    """0 exacto, 1 empieza por lo escrito, 2 tiene todas las palabras enteras,
    3 tiene todas las palabras como principio de otras, 4 solo se parece."""
    if texto == normal:
        return 0
    if texto.startswith(normal + " "):
        return 1
    enteras = set(texto.split())
    if all(p in enteras for p in palabras):
        return 2
    if all(any(t.startswith(p) for t in enteras) for p in palabras):
        return 3
    return 4


def buscar(con: sqlite3.Connection, texto: str, limite: int = 40) -> list[dict]:
    """Busca por nombre en espanol o ingles, ordenado por probabilidad de ser lo buscado.

    Orden: coincidencia exacta > empieza por lo escrito > contiene todas las
    palabras > parecido (erratas). A igualdad, lo que se farmea (warframes,
    armas, piezas, mods, arcanos, recursos, reliquias) por delante de los
    adornos, y lo que tiene alguna fuente de obtencion por delante de lo que no.
    La busqueda difusa entra siempre que FTS no de nada bueno (exacto o que
    empiece por lo escrito), y las dos listas se fusionan.
    """
    palabras = normalizar(texto).split()
    if not palabras:
        return []
    # Las particulas se quitan salvo que sean todo lo escrito ("the", "de").
    palabras = [p for p in palabras if p not in PALABRAS_VACIAS] or palabras
    normal = " ".join(palabras)

    # candidatos: item_id -> (mejor nivel, mejor parecido, texto, idioma)
    candidatos: dict[int, tuple[int, float, str, str]] = {}

    def anotar(item_id, nivel, parecido, texto_indexado, idioma):
        previo = candidatos.get(item_id)
        if previo is None or (nivel, -parecido) < (previo[0], -previo[1]):
            candidatos[item_id] = (nivel, parecido, texto_indexado, idioma)

    consulta = " ".join(f'"{p}"*' for p in palabras)
    filas = con.execute(
        """
        SELECT b.item_id, b.idioma, b.texto FROM busqueda b
         WHERE busqueda MATCH ? ORDER BY bm25(busqueda) LIMIT ?
        """,
        (consulta, max(200, limite * 5)),
    ).fetchall()
    if not filas and len(palabras) > 1:
        # "wu kong" por "wukong": el difuso ordena las palabras y no lo ve.
        pegado = "".join(palabras)
        filas = con.execute(
            "SELECT b.item_id, b.idioma, b.texto FROM busqueda b WHERE busqueda MATCH ?"
            " ORDER BY bm25(busqueda) LIMIT ?",
            (f'"{pegado}"*', max(200, limite * 5)),
        ).fetchall()
        if filas:
            normal, palabras = pegado, [pegado]
    for item_id, idioma, texto_indexado in filas:
        nivel = _nivel(normal, palabras, texto_indexado)
        # Cuanto menos texto sobre, mas se parece: "forma" antes que "forma plano".
        parecido = 100.0 * len(normal) / max(len(texto_indexado), 1)
        anotar(item_id, nivel, parecido, texto_indexado, idioma)

    mejor_nivel = min((c[0] for c in candidatos.values()), default=9)
    if mejor_nivel > 1 or len(candidatos) < 3:
        textos, ids, idiomas = _candidatos_difusos(con)
        # token_sort_ratio: mismos aciertos que WRatio con las faltas tipicas, en un
        # tercio del tiempo, y no prefiere 'erra' a 'serration' para 'serracion'.
        for _, puntos, i in rf_process.extract(
            normal, textos, scorer=fuzz.token_sort_ratio, limit=limite * 3,
            score_cutoff=CORTE_DIFUSO,
        ):
            anotar(ids[i], 4, float(puntos), textos[i], idiomas[i])
    if not candidatos:
        return []

    con_fuentes = _items_con_fuentes(con)
    marcas = ",".join("?" * len(candidatos))
    filas = con.execute(
        f"""
        SELECT i.id, i.nombre_en, i.nombre_es, i.categoria, i.tipo, i.vaulted, i.padre_id,
               p.nombre_en, p.nombre_es, i.imagen
          FROM items i LEFT JOIN items p ON p.id = i.padre_id
         WHERE i.id IN ({marcas})
        """,
        list(candidatos),
    ).fetchall()

    salida = []
    for (iid, nombre_en, nombre_es, categoria, tipo, vaulted, padre_id, padre_en, padre_es,
         imagen) in filas:
        nivel, parecido, texto_indexado, idioma = candidatos[iid]
        grupo = GRUPO_CATEGORIA.get(categoria, 1)
        tiene_fuentes = iid in con_fuentes or (padre_id in con_fuentes if padre_id else False)
        if grupo == GRUPO_COSMETICO and not (padre_id and tiene_fuentes):
            # Un adorno solo gana a lo farmeable si lo escrito es exactamente su
            # nombre y ningun objeto farmeable contiene esas palabras. La pieza de un
            # adorno que se farmea (Kavasa Prime Band sale de reliquias) no se castiga;
            # el adorno entero si, porque 625 tienen alguna fuente (paletas, sigilos)
            # y "orokin" volvia a dar la paleta de colores antes que la celula.
            nivel = min(nivel + 2, 4)
        salida.append({
            "item_id": iid,
            "peso": (nivel, grupo, 0 if tiene_fuentes else 1, ORDEN_CATEGORIA.get(categoria, 4),
                     -parecido, 0 if idioma == "es" else 1, len(texto_indexado)),
            "nivel": nivel,
            "parecido": parecido,
            "nombre_en": nombre_en,
            "nombre_es": nombre_es,
            "categoria": categoria,
            "tipo": tipo,
            "vaulted": vaulted,
            "padre_id": padre_id,
            "padre_en": padre_en,
            "padre_es": padre_es,
            "imagen": imagen,
        })
    salida.sort(key=lambda r: r["peso"])

    # Los mods Beginner/Expert repiten nombre: uno solo en la lista, el mejor.
    vistos: set[tuple] = set()
    unicos = []
    for r in salida:
        etiqueta = (normalizar(r["nombre_es"] or r["nombre_en"]),
                    normalizar(r["padre_es"] or r["padre_en"] or ""))
        if etiqueta in vistos:
            continue
        vistos.add(etiqueta)
        unicos.append(r)
        if len(unicos) >= limite:
            break
    return unicos


# Objetos con alguna fuente de obtencion (propia o de sus piezas), por indice.
_CACHE_FUENTES: dict[str, tuple[str, frozenset]] = {}


def _version_indice(con: sqlite3.Connection) -> tuple[str, str]:
    ruta = con.execute("PRAGMA database_list").fetchone()[2] or ""
    fila = con.execute("SELECT valor FROM meta WHERE clave = 'construido_en'").fetchone()
    return ruta, (fila[0] if fila else "")


def _items_con_fuentes(con: sqlite3.Connection) -> frozenset:
    ruta, version = _version_indice(con)
    guardado = _CACHE_FUENTES.get(ruta) if ruta else None
    if guardado is None or guardado[0] != version:
        filas = con.execute(
            """
            SELECT DISTINCT item_id FROM fuentes
            UNION SELECT DISTINCT i.padre_id FROM items i
             WHERE i.padre_id IS NOT NULL
               AND EXISTS (SELECT 1 FROM fuentes f WHERE f.item_id = i.id)
            """
        ).fetchall()
        guardado = (version, frozenset(f[0] for f in filas))
        if ruta:
            _CACHE_FUENTES[ruta] = guardado
    return guardado[1]


# Textos de la tabla 'busqueda' por fichero de indice: (construido_en, textos, ids, idiomas).
# Cargarlos y normalizarlos en cada busqueda difusa costaba 80-90 ms; cacheados, 15.
_CACHE_DIFUSO: dict[str, tuple[str, list[str], list[int], list[str]]] = {}


def _candidatos_difusos(con: sqlite3.Connection) -> tuple[list[str], list[int], list[str]]:
    ruta, version = _version_indice(con)
    guardado = _CACHE_DIFUSO.get(ruta) if ruta else None
    if guardado is None or guardado[0] != version:
        filas = con.execute("SELECT texto, item_id, idioma FROM busqueda").fetchall()
        guardado = (version, [f[0] for f in filas], [f[1] for f in filas], [f[2] for f in filas])
        if ruta:
            _CACHE_DIFUSO[ruta] = guardado
    return guardado[1], guardado[2], guardado[3]
