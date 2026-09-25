"""Construccion del indice SQLite y busqueda de objetos."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path

from rapidfuzz import fuzz, process as rf_process

from ..config import DIR_DATOS, DIR_RECURSOS, RUTA_INDICE, crear_carpetas
from ..registro_log import obtener
from .descargas import (
    CATALOGO_PIEZAS, CATEGORIAS_ESENCIALES, CATEGORIAS_ITEMS, IDIOMAS_EXTRA, Descargador,
    FuenteCambiada,
)
from . import nodos, tabla_oficial
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
# 7: nombres de objetos en fr/de/pt/it/pl (tabla items_nombres) y glosario de componentes
#    en esos idiomas (glosario_idiomas), para casar y buscar con el juego en esos idiomas.
# 8: reliquias, misiones y piezas nuevas desde la tabla oficial de DE cuando WFCD va por
#    detras (tabla_oficial.py): objetos sinteticos "/Farmadex/DE/..." hasta que WFCD los tenga.
# 9: formato nuevo de WFCD (2026-09-24): piezas por referencia a Components.json y
#    traducciones por idioma. El indice queda igual, pero los que tengan uno construido con
#    un volcado a medias (la descarga fallaba con un 404) lo rehacen entero.
VERSION_ESQUEMA = "13"  # 13: nombres de piezas del juego (WFCD i18n), no del glosario
# 12: fecha de salida y actualizacion de cada objeto (items.fecha_salida, items.actualizacion),
#     para "lo nuevo" del buscador. Un indice de antes se sigue pudiendo leer: el codigo
#     que usa esas columnas (datos/novedades.py) tolera que falten y lo dice.
# Versiones cuyo indice el codigo actual sabe leer (misma estructura de tablas). Si la
# reconstruccion falla (sin red, la fuente cambio de formato...), con un indice de estas
# se sigue trabajando en vez de enseñar "Error preparando los datos". Al cambiar la
# ESTRUCTURA de las tablas, dejar aqui solo la version nueva.
ESQUEMAS_COMPATIBLES = {"8", "9", "10", "11", "12", "13"}

# Piezas de receta que pueden quedarse sin completar (referencias a objetos que no estan en
# ningun catalogo) antes de dar el volcado por roto. Con el de hoy son un punado de
# ingredientes raros; si falta Components.json son cientos y no se construye nada.
UMBRAL_PIEZAS_PERDIDAS = 50

# Idiomas con glosario de componentes propio (glosario_<idioma>.json): lo que WFCD no
# traduce (Chassis, Systems...) se completa a mano, igual que ya se hacia con el espanol.
IDIOMAS_GLOSARIO = ("fr", "de", "pt")

def instalar_indice(nuevo: Path, destino: Path) -> None:
    """Pone el indice recien construido en el sitio del viejo, aunque este abierto.

    Antes se borraban `indice.sqlite`, `-wal` y `-shm` y se renombraba el nuevo.
    Con el propio Farmadex leyendo el indice (lector de reliquias, pestanas...),
    Windows no deja borrar un fichero abierto y la actualizacion de datos moria
    con "[WinError 32] ... indice.sqlite-wal" justo tras actualizar el programa,
    que es cuando un esquema nuevo obliga a reconstruir. Ahora el contenido se
    copia DENTRO de la base abierta con la copia de seguridad de SQLite: es una
    sola transaccion (o todo o nada), respeta los bloqueos de los demas y las
    conexiones abiertas ven los datos nuevos en su siguiente consulta.
    """
    if not destino.exists():
        nuevo.replace(destino)
        return
    origen = sqlite3.connect(nuevo)
    try:
        for intento in range(3):
            viejo = sqlite3.connect(destino, timeout=30)
            try:
                origen.backup(viejo)
                break
            except sqlite3.OperationalError as ocupado:
                # "database is locked": alguien escribe o lee largo; se espera y reintenta.
                if intento == 2:
                    raise RuntimeError(
                        "No se pudo cambiar el indice de datos porque esta ocupado. "
                        "Se volvera a intentar la proxima vez que abras Farmadex."
                    ) from ocupado
                log.warning("Indice ocupado al instalar el nuevo (%s); reintento", ocupado)
                time.sleep(2)
            finally:
                viejo.close()
    except RuntimeError:
        raise
    except sqlite3.DatabaseError as error:
        # El viejo esta roto (no es una base de datos): ahi si se sustituye el fichero.
        log.warning("Indice viejo ilegible (%s); se sustituye el fichero", error)
        origen.close()
        try:
            for sufijo in ("-wal", "-shm"):
                Path(str(destino) + sufijo).unlink(missing_ok=True)
            destino.unlink(missing_ok=True)
        except OSError as bloqueo:
            raise RuntimeError(
                "No se pudo cambiar el indice de datos porque esta en uso. "
                "Cierra Farmadex del todo y vuelve a abrirlo."
            ) from bloqueo
        nuevo.replace(destino)
        return
    finally:
        origen.close()
    for sufijo in ("", "-wal", "-shm"):
        try:
            Path(str(nuevo) + sufijo).unlink(missing_ok=True)
        except OSError:  # un temporal que sobra no puede tumbar la actualizacion
            log.warning("No se pudo borrar el temporal %s%s", nuevo, sufijo)


def conectar(ruta: Path = RUTA_INDICE) -> sqlite3.Connection:
    con = sqlite3.connect(ruta)
    con.execute("PRAGMA foreign_keys=ON")
    return con


def variantes_ruta(ruta: str) -> list[str]:
    """Las rutas con las que una recompensa de EE.log puede figurar en `items`.

    El juego nombra las piezas de warframe como plano
    (".../WarframeRecipes/CalibanPrimeChassisBlueprint") y el catalogo de WFCD
    como componente (".../CalibanPrimeChassisComponent"): visto en un EE.log
    real, donde la recompensa propia no se encontraba por eso.
    """
    salida = [ruta]
    if "/WarframeRecipes/" in ruta and ruta.endswith("Blueprint"):
        salida.append(ruta[: -len("Blueprint")] + "Component")
    return salida


def fila_por_ruta(con: sqlite3.Connection, ruta: str, columnas: str = "id"):
    """Fila de `items` (las `columnas` pedidas) para una ruta del juego, o None."""
    for candidata in variantes_ruta(ruta):
        fila = con.execute(f"SELECT {columnas} FROM items WHERE unique_name = ?", (candidata,)).fetchone()
        if fila:
            return fila
    for candidata in _rutas_sinteticas(con, ruta):
        fila = con.execute(f"SELECT {columnas} FROM items WHERE unique_name = ?", (candidata,)).fetchone()
        if fila:
            return fila
    return None


RE_RUTA_PRIME = re.compile(r"^([A-Z][A-Za-z]*?)Prime([A-Z][A-Za-z]*)?$")
# El juego llama "Helmet" a las neuropticas en sus rutas.
PIEZA_EN_RUTA = {"Helmet": "Neuroptics"}


def _rutas_sinteticas(con: sqlite3.Connection, ruta: str) -> list[str]:
    """Rutas `/Farmadex/DE/...` que puede tener la recompensa de EE.log de un prime recien salido.

    Lo que solo esta en la tabla oficial de DE lleva una ruta inventada, porque no se
    sabe la real: sin esto la recompensa propia no se reconocia por el registro del
    juego (dos chasis de Citrine Prime acabaron leidos como su plano). La ruta del
    juego puede usar el nombre interno del warframe (Citrine es "Geode"), asi que se
    prueba tambien el nombre comercial del objeto normal con esa ruta.
    """
    tramo = ruta.rstrip("/").rsplit("/", 1)[-1]
    m = RE_RUTA_PRIME.match(tramo)
    if not m:
        return []
    base, resto = m.group(1), m.group(2) or ""
    pieza = resto
    for sufijo in ("Blueprint", "Component"):
        if pieza.endswith(sufijo) and pieza != sufijo:
            pieza = pieza.removesuffix(sufijo)
            break
    if not pieza:
        return []
    pieza = PIEZA_EN_RUTA.get(pieza, pieza)
    nombres = [base]
    for (nombre,) in con.execute(
        "SELECT nombre_en FROM items WHERE unique_name LIKE ? AND unique_name NOT LIKE '/Farmadex/%'",
        (f"%/{base}",),
    ):
        nombres.append(nombre.replace(" ", ""))
    salida = []
    for nombre in nombres:
        salida += [f"/Farmadex/DE/{nombre}Prime{pieza}", f"/Farmadex/DE/{nombre}Prime{pieza}Component"]
    return salida


def hay_indice(ruta: Path = RUTA_INDICE) -> bool:
    """Si hay un indice que se puede USAR (de esta version o de una compatible)."""
    return _esquema_del_indice(ruta) in ESQUEMAS_COMPATIBLES


def indice_al_dia(ruta: Path = RUTA_INDICE) -> bool:
    """Si el indice es de la version actual; si no, toca reconstruirlo."""
    return _esquema_del_indice(ruta) == VERSION_ESQUEMA


def _esquema_del_indice(ruta: Path) -> str | None:
    """`esquema_version` de un indice completo y utilizable, o None."""
    if not ruta.exists():
        return None
    try:
        con = conectar(ruta)
    except sqlite3.Error:
        return None
    try:
        meta = dict(con.execute("SELECT clave, valor FROM meta"))
        tiene_items = con.execute("SELECT 1 FROM items LIMIT 1").fetchone()
        if meta.get("construido_en") and tiene_items:
            return meta.get("esquema_version")
        return None
    except sqlite3.Error:
        return None
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


def importar_glosario_idiomas(con: sqlite3.Connection) -> None:
    """Glosario de componentes en fr/de/pt: lo que WFCD no trae traducido."""
    for idioma in IDIOMAS_GLOSARIO:
        ruta = DIR_RECURSOS / f"glosario_{idioma}.json"
        if not ruta.exists():
            continue
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        for dominio, pares in datos.items():
            con.executemany(
                "INSERT OR REPLACE INTO glosario_idiomas (dominio, idioma, en, valor) "
                "VALUES (?, ?, ?, ?)",
                [(dominio, idioma, en, valor) for en, valor in pares.items()],
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
        if clave == "drops_modified":
            # Si el indice uso la tabla oficial de DE, las tablas son de esa fecha.
            oficial = fecha_de_meta(meta.get("oficial_fecha"))
            if oficial and (fecha is None or oficial > fecha):
                fecha = oficial
        if fecha and fecha < fecha_build:
            atrasadas.append((fuente, fecha.isoformat()))
    return atrasadas


def texto_desfase(atrasadas, pendientes, build: str, fecha_build, reciente: bool) -> tuple[str, bool]:
    """El aviso de Ajustes para datos anteriores al parche y si va en tono de alerta.

    `pendientes` es el subconjunto de `atrasadas` con algo mas nuevo publicado y sin
    descargar (descargas.fuentes_pendientes). Si esta vacio, lo que hay es lo ultimo que
    WFCD y DE han publicado: no es un fallo nuestro, y solo se dice en tono de aviso los
    dias siguientes al parche, cuando de verdad puede faltar contenido.
    """
    from ..idiomas import t

    if pendientes:
        detalle = ", ".join(t("{fuente} del {fecha}", fuente=t(f), fecha=fecha) for f, fecha in pendientes)
        return t(
            "Warframe se ha actualizado (build {build}) y los datos van por detras: {detalle}. "
            "Puede faltar lo nuevo del parche; se volveran a descargar cuando WFCD y DE los publiquen.",
            build=build or "?",
            detalle=detalle,
        ), True
    detalle = ", ".join(t("{fuente} del {fecha}", fuente=t(f), fecha=fecha) for f, fecha in atrasadas)
    return t(
        "Tienes lo mas reciente que han publicado WFCD y DE ({detalle}). El juego se actualizo "
        "despues ({fecha_build}); si ese parche cambio algo, aparecera cuando publiquen sus tablas.",
        detalle=detalle,
        fecha_build=fecha_build.isoformat() if fecha_build else "?",
    ), reciente


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
        SELECT i.id, i.nombre_en, i.nombre_es, i.categoria, i.padre_id,
               p.nombre_en AS padre_en, p.nombre_es AS padre_es
          FROM items i LEFT JOIN items p ON i.padre_id = p.id
        """
    ).fetchall()
    # Nombres en fr/de/pt/it/pl, por item: {item_id: {idioma: nombre}}.
    nombres_extra: dict[int, dict[str, str]] = {}
    for iid, idioma, nombre in con.execute("SELECT item_id, idioma, nombre FROM items_nombres"):
        nombres_extra.setdefault(iid, {})[idioma] = nombre

    lote = []
    for iid, nombre_en, nombre_es, categoria, padre_id, padre_en, padre_es in filas:
        textos = set()
        if padre_en:
            textos.add((normalizar(f"{padre_en} {nombre_en}"), "en"))
            if nombre_es:
                textos.add((normalizar(f"{padre_es or padre_en} {nombre_es}"), "es"))
        else:
            textos.add((normalizar(nombre_en), "en"))
            if nombre_es:
                textos.add((normalizar(nombre_es), "es"))
        extra_item = nombres_extra.get(iid, {})
        extra_padre = nombres_extra.get(padre_id, {}) if padre_id else {}
        for idioma, nombre_i in extra_item.items():
            if padre_id:
                padre_i = extra_padre.get(idioma) or padre_es or padre_en
                textos.add((normalizar(f"{padre_i} {nombre_i}"), idioma))
            else:
                textos.add((normalizar(nombre_i), idioma))
        for texto, idioma in textos:
            if texto:
                lote.append((texto, iid, idioma, categoria))
    con.executemany(
        "INSERT INTO busqueda (texto, item_id, idioma, categoria) VALUES (?, ?, ?, ?)", lote
    )
    return len(lote)


def comprobar_piezas(importador: ImportadorItems) -> None:
    """Para la construccion si las recetas nombran piezas que no se han podido completar.

    Pasa con el formato nuevo de WFCD si falta Components.json (o cambia otra vez de
    sitio): cada objeto traeria solo referencias y el indice se quedaria sin piezas prime.
    """
    perdidas = sorted(importador.referencias_sin_resolver)
    if not perdidas:
        return
    log.warning("Piezas de receta sin completar: %d de %d referencias (p. ej. %s)",
                len(perdidas), importador.referencias_vistas, ", ".join(perdidas[:5]))
    if len(perdidas) > max(UMBRAL_PIEZAS_PERDIDAS, importador.referencias_vistas // 20):
        raise FuenteCambiada(
            f"{len(perdidas)} piezas de receta no estan en ningun catalogo (falta o ha cambiado "
            f"{CATALOGO_PIEZAS}.json)"
        )


def corregir_boveda(con: sqlite3.Connection) -> int:
    """Una reliquia esta en boveda si y solo si no sale en ninguna tabla de drops actual.

    El "vaulted" de WFCD se queda atras con lo recien salido: el 2026-09-24 marcaba en
    boveda la Neo C11 y la Lith S19, que salian en 153 misiones, y como las piezas de
    Citrine Prime solo estaban en reliquias "en boveda", la pestana Primes la escondia.
    Las tablas de drops son las que mandan: lo que se puede farmear no esta en boveda.
    Devuelve cuantas reliquias ha cambiado.
    """
    hay_drops = con.execute(
        "SELECT 1 FROM fuentes f JOIN items i ON i.id = f.item_id WHERE i.categoria = 'Relics' LIMIT 1"
    ).fetchone()
    if not hay_drops:  # sin tablas de reliquias no hay con que corregir: se deja lo de WFCD
        return 0
    # Las Requiem salen de Sifones y Diluvios Kuva, que no estan en las tablas de drops.
    cambiadas = con.execute(
        """
        UPDATE items SET vaulted = CASE
               WHEN EXISTS (SELECT 1 FROM fuentes f WHERE f.item_id = items.id) THEN 0 ELSE 1 END
         WHERE categoria = 'Relics' AND nombre_en NOT LIKE 'Requiem%'
           AND COALESCE(vaulted, -1) != CASE
               WHEN EXISTS (SELECT 1 FROM fuentes f WHERE f.item_id = items.id) THEN 0 ELSE 1 END
        """
    ).rowcount
    # Y en cascada, para que la ficha, el panel de recompensas y Primes digan lo mismo:
    # una pieza prime esta en boveda si ninguna reliquia fuera de boveda la da, y un
    # prime entero si todas sus piezas lo estan. El "vaulted" de WFCD de piezas y primes
    # faltaba o iba desfasado (la Neo C11 salia disponible pero su pieza "en boveda").
    piezas = con.execute(
        """
        UPDATE items SET vaulted = CASE WHEN EXISTS (
                   SELECT 1 FROM reliquia_recompensas rr JOIN items r ON r.id = rr.reliquia_id
                    WHERE rr.item_id = items.id AND r.vaulted = 0) THEN 0 ELSE 1 END
         WHERE id IN (SELECT item_id FROM reliquia_recompensas)
           AND (es_prime = 1 OR padre_id IN (SELECT id FROM items WHERE es_prime = 1))
           AND COALESCE(vaulted, -1) != CASE WHEN EXISTS (
                   SELECT 1 FROM reliquia_recompensas rr JOIN items r ON r.id = rr.reliquia_id
                    WHERE rr.item_id = items.id AND r.vaulted = 0) THEN 0 ELSE 1 END
        """
    ).rowcount
    padres = con.execute(
        """
        UPDATE items SET vaulted = CASE WHEN EXISTS (
                   SELECT 1 FROM items h WHERE h.padre_id = items.id AND h.vaulted = 0
                      AND h.id IN (SELECT item_id FROM reliquia_recompensas)) THEN 0 ELSE 1 END
         WHERE es_prime = 1
           AND id IN (SELECT padre_id FROM items WHERE id IN (SELECT item_id FROM reliquia_recompensas))
           AND COALESCE(vaulted, -1) != CASE WHEN EXISTS (
                   SELECT 1 FROM items h WHERE h.padre_id = items.id AND h.vaulted = 0
                      AND h.id IN (SELECT item_id FROM reliquia_recompensas)) THEN 0 ELSE 1 END
        """
    ).rowcount
    if cambiadas or piezas or padres:
        log.info("Boveda corregida con las tablas de drops: %d reliquias, %d piezas, %d primes",
                 cambiadas, piezas, padres)
    return cambiadas + piezas + padres


def comprobar_indice(con: sqlite3.Connection) -> None:
    """Ultima comprobacion antes de instalar el indice nuevo: que tenga lo esencial.

    Si WFCD cambia el formato de algo de una forma que el importador no reconoce, lo normal
    es que no falle sino que importe cero objetos de esa categoria. Instalar ese indice
    dejaria al usuario sin piezas o sin reliquias; mejor seguir con el anterior.
    """
    vacias = [
        c for c in CATEGORIAS_ESENCIALES
        if not con.execute("SELECT 1 FROM items WHERE categoria = ? LIMIT 1", (c,)).fetchone()
    ]
    if not con.execute(
        "SELECT 1 FROM items WHERE padre_id IS NOT NULL AND es_prime = 1 LIMIT 1"
    ).fetchone():
        vacias.append("piezas prime")
    if not con.execute("SELECT 1 FROM reliquia_recompensas LIMIT 1").fetchone():
        vacias.append("recompensas de reliquia")
    if vacias:
        raise FuenteCambiada("El indice nuevo saldria sin: " + ", ".join(vacias))


def _leer_json(ruta: Path | None):
    if not ruta or not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def usar_tabla_oficial(con: sqlite3.Connection, importador: ImportadorItems,
                       rutas_drops: dict[str, Path], estado) -> tuple[dict, str]:
    """Lo que se toma de la tabla oficial de DE para este indice.

    Devuelve (datos para ImportadorDrops.importar_todo, fecha de la tabla si se uso algo).
    Cualquier fallo deja ({}, ""): el indice se construye con WFCD como siempre.
    """
    try:
        tabla = tabla_oficial.cargar(DIR_DATOS / "drops" / tabla_oficial.NOMBRE_FICHERO)
        if tabla is None:
            return {}, ""
        reliquias = _leer_json(rutas_drops.get("relics"))
        reliquias = reliquias.get("relics") if isinstance(reliquias, dict) else reliquias
        misiones = _leer_json(rutas_drops.get("missionRewards"))
        misiones = misiones.get("missionRewards") if isinstance(misiones, dict) else misiones
        datos = tabla_oficial.preparar(
            con, importador, tabla,
            [r for r in reliquias if isinstance(r, dict)] if isinstance(reliquias, list) else [],
            misiones if isinstance(misiones, dict) else None,
            fecha_de_meta(getattr(estado, "drops_modified", "")),
        )
    except Exception:  # noqa: BLE001 - la tabla de DE es un extra
        log.exception("No se pudo usar la tabla oficial de DE")
        return {}, ""
    usada = bool(datos) and "missionRewards" in datos and tabla.fecha
    return datos, tabla.fecha.isoformat() if usada else ""


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

    if not cambios and indice_al_dia() and not forzar:
        log.info("Datos al dia y el indice ya existe; no se reconstruye")
        avisar("Datos al dia", 1, 1)
        return {"reconstruido": False}

    faltan = [c for c in CATEGORIAS_ESENCIALES if not (DIR_DATOS / f"{c}.json").exists()]
    if faltan:
        raise FuenteCambiada(f"Faltan catalogos imprescindibles: {', '.join(faltan)}")

    tmp = RUTA_INDICE.with_suffix(".nuevo")
    try:
        tmp.unlink(missing_ok=True)
    except OSError:  # un resto de otra vez que Windows aun tiene cogido
        tmp = RUTA_INDICE.with_suffix(f".nuevo{os.getpid()}")
        tmp.unlink(missing_ok=True)
    con = conectar(tmp)
    terminado = False
    try:
        crear_esquema(con)
        importar_glosario(con)
        importar_glosario_idiomas(con)

        avisar("Cargando traducciones al espanol", 0, 0)
        ruta_i18n = DIR_DATOS / "i18n_es.json"
        i18n = json.loads(ruta_i18n.read_text(encoding="utf-8")) if ruta_i18n.exists() else {}

        idiomas_extra = {}
        for idioma in IDIOMAS_EXTRA:
            ruta = DIR_DATOS / f"i18n_{idioma}.json"
            if ruta.exists():
                idiomas_extra[idioma] = json.loads(ruta.read_text(encoding="utf-8"))

        importador = ImportadorItems(con, i18n, idiomas_extra)
        piezas = _leer_json(DIR_DATOS / f"{CATALOGO_PIEZAS}.json")
        if isinstance(piezas, list):
            # Formato nuevo: las recetas solo nombran sus piezas y hay que completarlas.
            avisar("Cargando el catalogo de piezas", 0, 0)
            importador.cargar_referencias(
                piezas, [DIR_DATOS / f"{c}.json" for c in CATEGORIAS_ITEMS]
            )
        total = len(CATEGORIAS_ITEMS)
        objetos = 0
        for i, categoria in enumerate(CATEGORIAS_ITEMS, start=1):
            ruta = DIR_DATOS / f"{categoria}.json"
            avisar(f"Importando objetos: {categoria} ({i}/{total})", i - 1, total)
            if not ruta.exists():
                log.warning("Falta el catalogo %s", categoria)
                continue
            objetos += importador.importar_categoria(ruta)
        comprobar_piezas(importador)
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
        avisar("Comparando con la tabla oficial de DE", 0, 0)
        # Antes de ImportadorDrops: los objetos que se creen aqui tienen que estar ya en
        # el mapa de alias para que las tablas los casen.
        datos_oficiales, fecha_oficial = usar_tabla_oficial(
            con, importador, rutas_drops, descargador.estado
        )
        idrops = ImportadorDrops(con, importador.alias)
        idrops.importar_todo(rutas_drops, progreso=avisar, datos=datos_oficiales)
        avisar("Completando el mapa con los nodos que DE no publica", 0, 0)
        try:
            # Despues de los drops: asi los nodos que estos dieron de alta por nombre
            # reciben su identificador de verdad en vez de duplicarse.
            nodos.completar_solnodes(con)
        except Exception:  # noqa: BLE001 - sin esto el mapa se queda como estaba
            log.exception("No se pudieron completar los nodos con WFCD")
        avisar("Enlazando misiones con el mapa", 0, 0)
        reenlace = nodos.reenlazar_fuentes(con)
        corregir_boveda(con)
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
                # Fecha de la tabla oficial de DE si sus misiones sustituyeron a las de WFCD.
                ("oficial_fecha", fecha_oficial),
                ("construido_en", time.strftime("%Y-%m-%dT%H:%M:%S")),
            ],
        )
        comprobar_indice(con)
        con.commit()
        # Sin estadisticas el planificador elegia mal los indices de 'fuentes'.
        con.execute("ANALYZE")
        con.execute("VACUUM")
        terminado = True
    finally:
        con.close()
        if not terminado:
            # Un indice a medias no se instala nunca; tampoco se deja en disco.
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                log.debug("No se pudo borrar el indice a medias %s", tmp, exc_info=True)

    # El indice viejo solo se sustituye si el nuevo acabo bien.
    instalar_indice(tmp, RUTA_INDICE)

    resumen = {
        "reconstruido": True,
        "objetos": objetos,
        "reliquias_enlazadas": enlazadas,
        "entradas_busqueda": entradas,
        "misiones_enlazadas": reenlace["enlazadas"],
        "misiones_sin_nodo": reenlace["sin_nodo"],
        "sin_casar": len(idrops.sin_casar),
        "tabla_oficial": sorted(datos_oficiales),
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
# Con fr/de/pt/it en la busqueda hacen falta tambien sus articulos y preposiciones
# ("chassis de caliban prime", "plan du chassis"...).
PALABRAS_VACIAS = frozenset({
    "de", "del", "la", "el", "los", "las", "of", "the",
    "du", "des", "le", "les", "l",  # fr
    "der", "die", "das", "dem", "den", "von", "fur",  # de (sin diacriticos: normalizar())
    "do", "da", "dos", "das", "o", "a",  # pt
    "di", "il", "lo", "gli",  # it
})


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
