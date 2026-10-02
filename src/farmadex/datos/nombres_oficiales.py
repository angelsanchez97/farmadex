"""Nombres de los objetos tal como los publica Digital Extremes (el "Public Export").

De ahi salen los textos que pinta el juego en cada idioma, objeto por objeto (por su
`uniqueName`). WFCD (warframe-items) construye sus traducciones a partir de lo mismo, y
comparado nombre a nombre el 2026-10-02 coincide en todo... menos en las piezas: en
frances, aleman, portugues, italiano y polaco les quita el nombre del arma o del
warframe ("Ash Prime - Neuroptiques" se queda en "- Neuroptiques") y en ingles no trae
el nombre completo. Con solo eso el indice tenia que recomponer el nombre con un
glosario propio, que no dice lo mismo que el juego ("Neuroptique", "Poignee") o no
existe (italiano, polaco). Aqui se baja el nombre entero de donde lo publica DE.

Como esta publicado:
  - `index_<idioma>.txt.lzma`: medio KB comprimido con LZMA; cada linea es el nombre de
    un manifiesto y su version, "ExportResources_es.json!00_b04Iyow6...".
  - `Manifest/<esa linea>`: el manifiesto, un JSON sin comprimir.

Solo se baja lo que hace falta (`MANIFIESTOS`): las piezas y los recursos
(ExportResources, 1 MB por idioma) y el equipo, que es lo que encabeza una build: armas,
warframes y companeros (otro MB entre los tres). En el equipo WFCD tambien coincide,
salvo en lo que ademas es ingrediente de otra receta ("War Brisée" se queda en "Brisée"
porque Broken War es ingrediente de War). Los mods, los arcanos y las reliquias los trae
WFCD identicos (comprobado con `herramientas/auditar_nombres.py`, que si lo baja todo) y
bajarlos tambien serian otros 6,5 MB por idioma para no cambiar ni un nombre.

Lo descargado se guarda ya reducido a {uniqueName: nombre} en `datos/oficial/`, con la
version de cada manifiesto: mientras DE no publique otra (solo cambia con los parches del
juego) no se vuelve a bajar. Si algo falla (sin red, un idioma sin manifiesto, un
manifiesto roto) se sigue con lo guardado de antes y, si no hay, con los nombres de
WFCD como hasta ahora: esto nunca impide construir el indice.
"""

from __future__ import annotations

import json
import lzma
import re
from pathlib import Path
from typing import Callable

from ..ficheros import reemplazar, temporal_de
from ..registro_log import obtener

log = obtener("nombres")

URL_BASE = "https://content.warframe.com/PublicExport/"
# El mismo contenido sin pasar por la cache de la red de distribucion: es a donde va
# WFCD cuando el indice de `content` se queda atras o no contesta.
URL_ORIGEN = "https://origin.warframe.com/PublicExport/"

# Idiomas que conoce el indice (los del casador: ver descargas.IDIOMAS_EXTRA).
IDIOMAS = ("es", "en", "fr", "de", "pt", "it", "pl")
# Todos los que publica DE; solo los usa la herramienta de auditoria.
IDIOMAS_DEL_JUEGO = ("de", "en", "es", "fr", "it", "ja", "ko", "pl", "pt", "ru", "tc", "th", "tr", "uk", "zh")

# Manifiestos que se bajan al construir el indice. Ver la cabecera del modulo.
MANIFIESTOS = ("ExportResources", "ExportWeapons", "ExportWarframes", "ExportSentinels")
# Los que llevan nombres de algo que el indice conoce (para la auditoria).
MANIFIESTOS_CON_NOMBRES = (
    "ExportResources", "ExportWeapons", "ExportWarframes", "ExportSentinels", "ExportUpgrades",
    "ExportRelicArcane", "ExportGear", "ExportCustoms", "ExportFlavour", "ExportKeys", "ExportDrones",
)

NOMBRE_CARPETA = "oficial"
VERSION_CACHE = 1
# Un manifiesto de verdad trae cientos de nombres; con menos de esto es que ha llegado
# otra cosa (una pagina de error, un JSON cortado que por casualidad se deja leer).
MINIMO_NOMBRES = 5

RE_ETIQUETA = re.compile(r"<[^<>]*>")
RE_LINEA = re.compile(r"^(Export[A-Za-z]+?)(?:_([a-z]{2}))?\.json!(\S+)$")

# descargar(url, destino): deja el fichero en `destino` o lanza RuntimeError/OSError.
Descargar = Callable[[str, Path], None]


class ManifiestoRoto(ValueError):
    """Lo descargado no es un manifiesto que se pueda leer."""


def limpiar(nombre) -> str:
    """El nombre como se lee en pantalla: sin etiquetas de icono ("<ARCHWING> Amesha",
    "Kinemantik<RETRO_TM> A/V Receiver") ni saltos de linea ('Tema de Gauss Prime\\r\\n
    "Redline"'), con un solo espacio entre palabras. Es lo mismo que hace el lector con
    lo que lee. Lo que no es un nombre (vacio, o una ruta interna sin traducir) da ""."""
    if not isinstance(nombre, str):
        return ""
    limpio = " ".join(RE_ETIQUETA.sub("", nombre).split())
    if not limpio or limpio.startswith("/Lotus/"):
        return ""
    return limpio


def descomprimir_indice(datos: bytes) -> str:
    """El texto de un `index_<idioma>.txt.lzma`.

    DE lo comprime en LZMA "a solas" (13 bytes de cabecera: propiedades, diccionario y
    tamano) y declara el tamano exacto, pero su compresor pone ademas una marca de final
    que con tamano declarado no se espera: Python lo da por corrupto. Diciendo en la
    cabecera que el tamano no se sabe (ocho 0xFF), que es el caso en que la marca si se
    espera, se lee bien. Si un dia lo publican como es debido, vale la primera forma.
    """
    if len(datos) < 14:
        raise ManifiestoRoto("indice vacio o cortado")
    ultimo: Exception | None = None
    for cabecera in (datos[:13], datos[:5] + b"\xff" * 8):
        try:
            texto = lzma.LZMADecompressor(lzma.FORMAT_ALONE).decompress(cabecera + datos[13:])
        except lzma.LZMAError as e:
            ultimo = e
            continue
        if texto:
            return texto.decode("utf-8", errors="replace")
    raise ManifiestoRoto(f"indice ilegible: {ultimo}")


def leer_indice(texto: str) -> dict[str, str]:
    """{"ExportResources": "ExportResources_es.json!00_b04I..."} de un indice ya descomprimido."""
    salida: dict[str, str] = {}
    for linea in texto.split():
        m = RE_LINEA.match(linea.strip())
        if m:
            salida[m.group(1)] = linea.strip()
    return salida


def leer_manifiesto(datos: bytes | str) -> dict[str, str]:
    """{uniqueName: nombre limpio} de un manifiesto, este donde este cada objeto dentro.

    Los manifiestos traen a veces saltos de linea sin escapar dentro de los textos (por
    eso `strict=False`). Lanza ManifiestoRoto si no es JSON o no trae nombres.
    """
    if isinstance(datos, bytes):
        datos = datos.decode("utf-8", errors="replace")
    try:
        arbol = json.loads(datos, strict=False)
    except ValueError as e:
        raise ManifiestoRoto(f"no es JSON: {e}") from e
    if not isinstance(arbol, dict):
        raise ManifiestoRoto("no es un manifiesto (se esperaba un objeto)")
    nombres: dict[str, str] = {}
    pendientes: list = [arbol]
    while pendientes:
        nodo = pendientes.pop()
        if isinstance(nodo, dict):
            unico = nodo.get("uniqueName")
            if isinstance(unico, str) and unico:
                nombre = limpiar(nodo.get("name"))
                if nombre:
                    nombres.setdefault(unico, nombre)
            pendientes.extend(v for v in nodo.values() if isinstance(v, (dict, list)))
        elif isinstance(nodo, list):
            pendientes.extend(v for v in nodo if isinstance(v, (dict, list)))
    if len(nombres) < MINIMO_NOMBRES:
        raise ManifiestoRoto(f"solo trae {len(nombres)} nombres")
    return nombres


def ruta_idioma(carpeta: Path, idioma: str) -> Path:
    return Path(carpeta) / f"nombres_{idioma}.json"


def _leer_cache(ruta: Path) -> dict:
    """Lo guardado de un idioma, o {} si no hay o no se deja leer."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(datos, dict) or datos.get("version") != VERSION_CACHE:
        return {}
    if not isinstance(datos.get("nombres"), dict) or not isinstance(datos.get("manifiestos"), dict):
        return {}
    return datos


def cargar(carpeta: Path, idiomas=IDIOMAS) -> dict[str, dict[str, str]]:
    """{idioma: {uniqueName: nombre}} con lo que haya guardado. Un idioma sin fichero, o
    con el fichero estropeado, sencillamente no esta: el indice usa para el los de WFCD."""
    salida: dict[str, dict[str, str]] = {}
    for idioma in idiomas:
        nombres = _leer_cache(ruta_idioma(carpeta, idioma)).get("nombres") or {}
        nombres = {u: n for u, n in nombres.items() if isinstance(u, str) and isinstance(n, str) and n}
        if nombres:
            salida[idioma] = nombres
    return salida


def sincronizar(descargar: Descargar, carpeta: Path, idiomas=IDIOMAS, manifiestos=MANIFIESTOS,
                progreso=None, forzar: bool = False, seguir: Callable[[], bool] | None = None) -> dict[str, str]:
    """Deja al dia `carpeta` y devuelve que ha pasado con cada idioma:

    "nuevo" (se ha bajado una version nueva), "al_dia" (ya se tenia la publicada),
    "anterior" (ha fallado y se sigue con lo guardado) o "sin_datos" (ha fallado y no
    habia nada: ese idioma ira con los nombres de WFCD). Nunca lanza.

    `seguir()` deja de devolver True cuando ya no merece la pena insistir (sin red).
    """
    carpeta = Path(carpeta)
    resultado: dict[str, str] = {}
    for i, idioma in enumerate(idiomas):
        ruta = ruta_idioma(carpeta, idioma)
        guardado = _leer_cache(ruta)
        de_antes = "anterior" if guardado.get("nombres") else "sin_datos"
        if seguir is not None and not seguir():
            resultado[idioma] = de_antes
            continue
        if progreso:
            progreso(f"Comprobando los nombres del juego ({idioma})", i, len(idiomas))
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            publicado = _indice_publicado(descargar, carpeta, idioma)
            faltan = [m for m in manifiestos if m not in publicado]
            if faltan:
                raise ManifiestoRoto(f"el indice de DE no trae {', '.join(faltan)}")
            versiones = {m: publicado[m] for m in manifiestos}
            if not forzar and guardado and guardado.get("manifiestos") == versiones:
                resultado[idioma] = "al_dia"
                continue
            nombres: dict[str, str] = {}
            for manifiesto in manifiestos:
                if progreso:
                    progreso(f"Descargando los nombres del juego ({idioma})", i, len(idiomas))
                crudo = carpeta / f"{manifiesto}_{idioma}.descarga"
                try:
                    descargar(URL_BASE + "Manifest/" + versiones[manifiesto], crudo)
                    leidos = leer_manifiesto(crudo.read_bytes())
                finally:
                    crudo.unlink(missing_ok=True)
                for unico, nombre in leidos.items():
                    nombres.setdefault(unico, nombre)
            tmp = temporal_de(ruta)
            tmp.write_text(
                json.dumps({"version": VERSION_CACHE, "manifiestos": versiones, "nombres": nombres},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            reemplazar(tmp, ruta)
            log.info("Nombres oficiales en %s: %d", idioma, len(nombres))
            resultado[idioma] = "nuevo"
        except (RuntimeError, OSError, ValueError) as e:
            # ManifiestoRoto es un ValueError; los fallos de descarga, RuntimeError.
            log.warning("Nombres oficiales en %s sin actualizar (%s); %s", idioma, e,
                        "se usan los guardados" if de_antes == "anterior" else "ese idioma va con los de WFCD")
            resultado[idioma] = de_antes
    return resultado


def _indice_publicado(descargar: Descargar, carpeta: Path, idioma: str) -> dict[str, str]:
    """Las versiones que DE tiene publicadas para ese idioma."""
    crudo = carpeta / f"index_{idioma}.descarga"
    ultimo: Exception | None = None
    try:
        for base in (URL_BASE, URL_ORIGEN):
            try:
                descargar(f"{base}index_{idioma}.txt.lzma", crudo)
                publicado = leer_indice(descomprimir_indice(crudo.read_bytes()))
                if publicado:
                    return publicado
                ultimo = ManifiestoRoto("indice sin manifiestos")
            except (RuntimeError, OSError, ValueError) as e:
                ultimo = e
    finally:
        crudo.unlink(missing_ok=True)
    raise ManifiestoRoto(f"no se pudo leer el indice de DE para '{idioma}': {ultimo}")
