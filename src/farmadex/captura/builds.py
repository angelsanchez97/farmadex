"""Lectura de la pantalla de mejoras del arsenal: que warframe o arma es y que mods lleva.

Se captura la ventana del juego entera, se lee con el OCR sin reescalar (los
nombres de las tarjetas de mod miden ~20 px a 1080p y el reescalado normal del
detector se los come) y cada linea se casa con el catalogo. La cabecera
("MEJORAS / EXCALIBUR [30]") da el equipo; las tarjetas de arriba son los mods
equipados y las de abajo, bajo el buscador, la coleccion.

Solo se ensena lo que casa con seguridad. Lo que se leyo pero no se reconocio
se devuelve aparte, para que el usuario vea que no se ha ignorado.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field

from PySide6.QtCore import Signal, Slot
from ..datos.difuso import fuzz

from ..idiomas import t
from ..registro_log import obtener
from . import pantalla
from .ocr import (
    RE_RANGO_TARJETA,
    Casador,
    ErrorMotorOCR,
    Leido,
    Reconocido,
    agrupar_bloques,
    casar_lineas,
    unir_filas,
)
from .reliquias import LectorBase

log = obtener("builds")

CATEGORIAS_BUILD = (
    "Warframes",
    "Primary",
    "Secondary",
    "Melee",
    "Arch-Gun",
    "Arch-Melee",
    "Archwing",
    "Sentinels",
    "SentinelWeapons",
    "Pets",
    "Mods",
    "Arcanes",
    # Las armas exaltadas (Reguladoras, Espada exaltada...) tienen su propia pantalla de
    # mejoras; en el indice van en "Misc" con tipo "Exalted Weapon" (el resto de "Misc" no).
    "Misc",
)
TIPOS_MISC_BUILD = ("Exalted Weapon",)

# La palabra de la cabecera en cada idioma del juego y el idioma que delata. Comprobado
# con capturas reales de YouTube de jugadores de cada pais: el aleman dice "UPGRADES"
# como el ingles (no "VERBESSERUNGEN"), el portugues "APRIMORAMENTOS", el italiano
# "POTENZIAMENTI" y el polaco "ULEPSZENIA". El ruso ("УЛУЧШЕНИЯ") no esta: el OCR no
# lee cirilico (ver `parece_cirilico`).
PALABRAS_CABECERA = {
    "UPGRADES": "en", "MEJORAS": "es", "AMELIORATIONS": "fr", "VERBESSERUNGEN": "de",
    "MELHORIAS": "pt", "APRIMORAMENTOS": "pt", "POTENZIAMENTI": "it", "ULEPSZENIA": "pl",
}
# Enteras: sin la "S" opcional, "MEJORAS /" se partia en "MEJORA" + un nombre "S /". Si el
# OCR se come una letra, `_arreglar_cabecera` la repone.
_PALABRA_CABECERA = r"UPGRADES|MEJORAS|AM[EÉ]LIORATIONS|VERBESSERUNGEN|MELHORIAS|APRIMORAMENTOS|POTENZIAMENTI|ULEPSZENIA"
# Como pone cada idioma el rango detras del nombre: "[30]" (interfaz nueva), "RANK 30",
# "RANG 30" (aleman), "RANGO 30", "NIVEAU 30" (frances), "(NÍVEL 30)" (portugues),
# "GRADO 30" (italiano), "RANGA 30" y "RANGA ZERO" (polaco, sin rango). El OCR cambia
# ceros por oes y a veces lo pega todo: "POTENZIAMENTIGYREGRADO30", "SYAM(NIVEL3O)".
_PALABRA_RANGO = r"RANK|RANGA|RANGO?|NIVEAU|N[IÍ]VEL|GRADO|STUFE"
_CIFRAS_RANGO = r"[\dOIL|]+"
_RANGO_FINAL = (rf"(?:[\[［(（]\s*(?:(?:{_PALABRA_RANGO})\s*)?{_CIFRAS_RANGO}\s*[\]］)）]?"
                rf"|(?:{_PALABRA_RANGO})\s*(?:{_CIFRAS_RANGO}|Z[EÉ]RO))")
# La cabecera de la pantalla: "UPGRADES / EXCALIBUR [30]", "MEJORAS / EXCALIBUR [30]",
# "AMÉLIORATIONS ZEPHYR PRIME NIVEAU 30"... El OCR suele pegarlo todo:
# "UPGRADES/EXCALIBUR[30]", a veces con el boton "+" de al lado delante, el rango con
# una O por cero y el laurel de la maestria leido como garabatos detras:
# "+UPGRADES/EXCALIBUR [3O] 美美". La interfaz anterior a 2025 ponia dos puntos
# ("UPGRADES: UNRANKED HYDROID") y en frances e italiano no lleva separador.
RE_CABECERA = re.compile(
    rf"(?i)^\W*(?:{_PALABRA_CABECERA})\s*(?:[/:]\s*)?([^\W_].+?)"
    rf"\s*(?:{_RANGO_FINAL})?(?:\s*[^\x00-ɏ]+)*\s*$"
)
# La caja de busqueda separa lo equipado (arriba) de la coleccion (abajo). Con la caja
# activa, el cursor de texto va delante y el OCR lo lee como una letra: "|BUSCAR...",
# "IBUSCAR." (capturas reales de YouTube a 1440p en castellano). En cada idioma, leido
# en capturas reales: "CHERCHER...", "SUCHE...", "PROCURAR...", "CERCA...",
# "WYSZUKIWANIE...".
RE_BUSCAR = re.compile(
    r"(?i)^[|Il!\[(]?\s*(?:SEARCH|BUSCAR|RECHERCHER|CHERCHER|SUCHE|PESQUISAR|PROCURAR|CERCA\b|WYSZUKIWANIE|SZUKAJ)")
# Si la caja no se ve (la tapa la camara del streamer, una ayuda abierta, o con mando va
# sin texto), la separacion sale de lo que va en su misma fila a la derecha: el orden
# ("DRENAJE", "NOMBRE", "RANK", "SORTUJ WG: RANGA"...) o, justo encima, el filtro de
# polaridad ("TODOS", "TUTTO", "WSZYSTKIE").
RE_ORDEN = re.compile(
    r"(?i)^\W*(?:(?:SORT(?:\s*BY)?|ORDENAR(?:\s*POR)?|TRIER(?:\s*PAR)?|SORTIEREN(?:\s*NACH)?|ORDINA(?:\s*PER)?|"
    r"SORTUJ(?:\s*WG)?)\s*:?\s*)?"
    r"(?:DRAIN|DRENAJE|NAME|NOMBRE|RANK|RANGO|POLARITY|POLARIDAD|RARITY|RAREZA|TYPE|TIPO|"
    r"NOM|RANG|RARET[EÉ]|POLARIT[EÉ]|CO[UÛ]T|KOSTEN|SELTENHEIT|POLARIT[AÄ]T|NOME|RARIDADE|POLARIDADE|"
    r"CUSTO|DRENO|N[IÍ]VEL|RARIT[AÀ]|GRADO|COSTO|POLARIT[AÀ]|RANGA|NAZWA|KOSZT|RZADKO[SŚ][CĆ]|POLARYZACJA|TYP)\W*$")
# El filtro: "TODOS" y compania. El icono del infinito de delante sale a veces como
# "CO" ("CO TODOS", "CO ALLE"). Los nombres de polaridad solo valen si en la misma fila
# hay algo mas del buscador (ver `linea_separadora`): "AURA" tambien es la etiqueta de
# la tarjeta de aura ampliada, y tomarla por el filtro mandaba a la coleccion la mitad
# de lo equipado (captura real en italiano con mando).
RE_FILTRO = re.compile(r"(?i)^\W*(?:[A-Z0-9]{1,2}\s+)?(?:ALL|TODOS|TOUS|TOUT|ALLE|TUDO|TUTTO|TUTTI|WSZYSTKIE)\W*$")
RE_FILTRO_POLARIDAD = re.compile(
    r"(?i)^\W*(?:[A-Z0-9]{1,2}\s+)?(?:MADURAI|VAZARIN|NARAMON|ZENURIK|UNAIRU|PENJAGA|UMBRA|AURA|EXILUS)\W*$")
# La barra de capacidad ("CAPACIDAD 5/74"): en su fila, a la derecha, van los nombres de
# las configuraciones, que pone el jugador ("Alcance", "Torreta SG", "ZASIEG",
# "POSZUKIWACZ"...) y no son mods aunque se llamen igual que uno.
RE_CAPACIDAD = re.compile(
    r"(?i)^\W*(?:CAPACITY|CAPACIDAD|CAPACIT[EÉAÀ]|KAPAZIT[AÄ]T|CAPACIDADE|POJEMNO[SŚ][CĆ])(?![A-Z])")
RE_NUMEROS_CAPACIDAD = re.compile(r"(-?\d{1,3})\s*/\s*(\d{2,3})\b")
UMBRAL_MODS = 85
MINIMO_CONFIANZA = 0.5
# El detector (donde hay texto) mira la captura reducida a este alto; el
# reconocedor (que pone) sigue leyendo cada recorte a tamano real. El detector
# cuesta segun los pixeles: a 1440p eran ~320 ms y a 4K ~800 ms solo en buscar.
# No se baja de 1080: medido con capturas reales de la wiki (interfaces viejas con
# letra pequena, la pantalla de artefactos de tektolito), buscar a 810 o 900 perdia
# mods que a 1080 se leen. Cualquier captura mas alta (1440p, 4K, 21:9) se busca a
# 1080: el juego escala la interfaz con la resolucion, asi que reducida a 1080 es la
# misma pantalla que a 1080p (la resolucion con la que esta medido todo lo demas).
ALTO_DETECCION = 1080


def alto_de_deteccion(alto: int) -> int | None:
    """A que alto se busca el texto: 1080 (las mas pequenas no se amplian).

    Antes una de 4K se buscaba a 1620 (tres cuartos) por miedo a perder nombres; medido
    de nuevo con todas las capturas reales de 4K del banco (seis, en cinco idiomas), a
    1080 salen exactamente los mismos mods y el equipo, y el detector tarda menos de la
    mitad: era lo que hacia pasar de 1 s la lectura a 4K con la CPU cargada.
    """
    if not ALTO_DETECCION:
        return None
    return ALTO_DETECCION


@dataclass
class Build:
    """Lo leido en la pantalla de mejoras. Los ids son del indice."""

    equipo: Reconocido | None = None
    equipo_texto: str = ""
    equipados: list[Reconocido] = field(default_factory=list)
    # (libre, total) de la barra "CAPACIDAD 5/74", si se leyo; None si no.
    capacidad: tuple[int, int] | None = None
    coleccion: list[Reconocido] = field(default_factory=list)
    arcanos: list[Reconocido] = field(default_factory=list)
    sin_identificar: list[str] = field(default_factory=list)
    milisegundos: int = 0
    # Segundos por etapa de la ultima lectura (captura, preparar, detector,
    # reconocedor, casado, reparto) y datos de la imagen, para el registro.
    tiempos: dict = field(default_factory=dict)
    # Las lineas que leyo el OCR (ya unidas), para el banco de pruebas y el registro.
    lineas: list[Leido] = field(default_factory=list, repr=False)
    # Idioma del juego segun la cabecera ("es", "fr", "pt"...; "ru" si la pantalla esta en
    # cirilico) o "" si no se sabe. Y, si no se pudo leer por algo que el usuario puede
    # arreglar, el aviso que se le ensena (texto sin traducir, pasa por t()).
    idioma: str = ""
    aviso: str = ""
    # De donde salio el corte entre lo equipado y la coleccion: "buscar" (la caja de
    # busqueda, el orden o el filtro), "huecos" (la geometria de las filas de tarjetas) o
    # "" si no se supo: entonces todo va a la coleccion y no se evalua.
    separador: str = ""
    # Tamano de la captura leida (0 si no se sabe): con el y con la caja de cada nombre
    # se sabe en que hueco de la pantalla va cada mod (datos/disposicion_build.py).
    ancho: int = 0
    alto: int = 0

    @property
    def vacia(self) -> bool:
        return self.equipo is None and not self.equipados and not self.coleccion and not self.arcanos


def _filtro_build(categoria: str, tipo: str | None, unique_name: str) -> bool:
    """Deja fuera lo que no puede salir en la pantalla de mejoras.

    Las piezas de receta (chasis, canon...) tienen padre y el Casador ya las etiqueta
    con el; aqui no interesan, ni los agrietados genericos ("Rifle Riven Mod").
    """
    if "/Recipes/" in unique_name or "Component" in unique_name:
        return False
    if tipo and "Riven" in tipo:
        return False
    if categoria == "Misc":
        return tipo in TIPOS_MISC_BUILD
    return True


def crear_casador(con) -> Casador:
    return Casador(con, CATEGORIAS_BUILD, filtro=_filtro_build)


# La palabra de la cabecera (PALABRAS_CABECERA, arriba) se reconoce aunque el OCR la lea
# con erratas: la letra del juego es muy espaciada y sale "ME JORAS", "MEJ0RAS", "UPGRAOES".
_CIFRAS_POR_LETRAS = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "|": "I"})


def _arreglar_pegada(texto: str) -> str:
    """"POTENZIAMENTIGYRE GRADO 30" con erratas en la palabra ("P0TENZIAMENTIGYRE"): sin
    separador, se compara el principio de lo leido (tantas letras como la palabra) con la
    palabra de cada idioma y, si se parece mucho, se reescribe con una barra detras."""
    for palabra in PALABRAS_CABECERA:
        letras, corte = 0, None
        for i, c in enumerate(texto):
            if c.isalnum() or c == "|":
                letras += 1
                if letras == len(palabra):
                    corte = i + 1
                    break
        if corte is None:
            continue
        delante = unicodedata.normalize("NFKD", texto[:corte]).upper().translate(_CIFRAS_POR_LETRAS)
        compacta = re.sub(r"[^A-Z|]", "", delante).translate(_CIFRAS_POR_LETRAS)
        if compacta[:3] == palabra[:3] and fuzz.ratio(compacta, palabra) >= 85 and texto[corte:].strip():
            return f"{palabra}/{texto[corte:]}"
    return texto


def _arreglar_cabecera(texto: str) -> str:
    """"ME JORAS / HAALVU [22]" -> "MEJORAS/ HAALVU [22]": arregla la palabra de delante de la
    barra si se parece mucho a la de la cabecera en algun idioma; si no, lo deja tal cual."""
    separador = re.search(r"[/:]", texto)
    if separador is None:
        return _arreglar_pegada(texto)
    delante, detras = texto[:separador.start()], texto[separador.end():]
    compacta = re.sub(r"[^A-Z0-9|]", "", unicodedata.normalize("NFKD", delante).upper().translate(_CIFRAS_POR_LETRAS))
    compacta = compacta.translate(_CIFRAS_POR_LETRAS)
    if not compacta:
        return texto
    for palabra in PALABRAS_CABECERA:
        # Las 3 primeras letras tienen que estar: "MEJORAS" no puede salir de "RAS".
        if compacta[:3] == palabra[:3] and fuzz.ratio(compacta, palabra) >= 80:
            return f"{palabra}/{detras}"
    return texto


def es_cabecera(texto: str):
    """El `re.Match` de la cabecera ("UPGRADES / EXCALIBUR [30]") o None."""
    texto = texto.strip()
    return RE_CABECERA.match(texto) or RE_CABECERA.match(_arreglar_cabecera(texto))


def idioma_de_cabecera(texto: str) -> str | None:
    """"es", "fr", "pt"... segun la palabra de la cabecera ("MEJORAS / ..."); None si no se
    sabe. "UPGRADES" dice "en", pero el juego en aleman tambien la pone."""
    if not texto:
        return None
    compacta = re.sub(r"[^A-Z]", "", unicodedata.normalize("NFKD", _arreglar_cabecera(texto.strip())).upper())
    for palabra, idioma in PALABRAS_CABECERA.items():
        if compacta.startswith(palabra) or (palabra == "UPGRADES" and compacta.startswith("UPGRADE")):
            return idioma
    return None


def cabecera(lineas: list[Leido]) -> tuple[str, Leido | None]:
    """El nombre del equipo segun la cabecera ("UPGRADES / EXCALIBUR [30]") y su linea."""
    for linea in lineas:
        m = es_cabecera(linea.texto)
        if m:
            return m.group(1).strip(), linea
    # La letra de la cabecera es muy espaciada: a veces el OCR la parte en dos cajas
    # ("MEJORAS /" y "EXCALIBUR [30]", o "MEJORAS" y "/EXCALIBUR [30]") con un hueco
    # mayor del que `unir_filas` junta. Se prueba cada palabra de cabecera con lo que
    # tiene a su derecha en la misma fila.
    for linea in lineas:
        if not _es_palabra_cabecera(linea.texto):
            continue
        derecha = [l for l in lineas if l is not linea and l.x >= linea.x + linea.ancho * 0.5
                   and min(l.y + l.alto, linea.y + linea.alto) - max(l.y, linea.y) >= 0.5 * min(l.alto, linea.alto)]
        if not derecha:
            continue
        vecina = min(derecha, key=lambda l: l.x)
        texto = f"{linea.texto.strip()} {vecina.texto.strip()}"
        if not re.search(r"[/:]", texto):
            texto = f"{linea.texto.strip()} / {vecina.texto.strip()}"
        m = es_cabecera(texto)
        if m:
            x0, y0 = min(linea.x, vecina.x), min(linea.y, vecina.y)
            x1 = max(linea.x + linea.ancho, vecina.x + vecina.ancho)
            y1 = max(linea.y + linea.alto, vecina.y + vecina.alto)
            return m.group(1).strip(), Leido(texto, x0, y0, x1 - x0, y1 - y0, min(linea.confianza, vecina.confianza))
    return "", None


def _es_palabra_cabecera(texto: str) -> bool:
    """"MEJORAS", "MEJORAS /", "+UPGRADES:" (con erratas): la palabra de la cabecera sola."""
    compacta = re.sub(r"[^A-Z0-9|]", "", unicodedata.normalize("NFKD", texto).upper()).translate(_CIFRAS_POR_LETRAS)
    if len(compacta) < 5:
        return False
    return any(compacta[:3] == p[:3] and fuzz.ratio(compacta, p) >= 80 for p in PALABRAS_CABECERA)


# Restos del rango y de las formas pegados detras del nombre: "HAALVU3O", "HAALVU303OI",
# "HAALVU3O 3OI", "HAALVU3013=". Empiezan por una cifra (o un borde de corchete).
RE_RANGO_PEGADO = re.compile(r"(?<=[A-Za-z])(?:\s|[\[\(=|])*\d[\s\dOIl|=\-\]\[)(]*$")
# "UNRANKED HYDROID" (sin rango) delante, "NIDUS RANK 29" detras (interfaz vieja), y lo
# mismo en cada idioma: "NYXPRIMERANG30", "GYRE GRADO 30", "OBERON PRIME RANGA ZERO",
# "ZEPHYR PRIME NIVEAU" (el numero cortado). El rango puede salir con letras por cifras:
# "LIMBO PRIME RANGO 3O".
RE_SIN_RANGO = re.compile(
    rf"(?i)^(?:UNRANKED|SIN\s*RANGO)\s*|\s*(?:{_PALABRA_RANGO})\s*(?:\d[\dOIl|]*|Z[EÉ]RO)?\s*$")


def _nombres_de_equipo(nombre: str) -> list[str]:
    """Lo leido en la cabecera y, detras, lo mismo sin los restos del rango que el OCR
    pega al nombre: "HAALVU I[22]" (una letra suelta), "HAALVU[3O]3" o "HAALV U [2 2 ]"
    (el corchete), "HAALVU3O" (sin corchete). Se prueban en orden."""
    intentos = [nombre]
    limpio = RE_SIN_RANGO.sub("", nombre).strip()
    if limpio and limpio != nombre:
        intentos.append(limpio)
        nombre = limpio
    corte = re.split(r"[\[\(【（［]", nombre, maxsplit=1)[0].strip()
    if corte and corte != nombre:
        intentos.append(corte)
    for base in [i for i in intentos if not re.search(r"[\[\(【（［]", i)]:
        sin_rango = RE_RANGO_PEGADO.sub("", base).strip()
        if sin_rango and sin_rango not in intentos:
            intentos.append(sin_rango)
    for base in list(intentos):
        palabras = base.split()
        # Solo si la letra suelta puede ser el borde del corchete: "HAALVU I[22]".
        if len(palabras) > 1 and palabras[-1] in ("I", "l", "|", "1"):
            intentos.append(" ".join(palabras[:-1]))
    return intentos


def linea_buscar(lineas: list[Leido], ancho: int) -> Leido | None:
    """La caja de busqueda, que separa lo equipado (arriba) de la coleccion (abajo).

    Va a la izquierda de la pantalla; puede haber otro "BUSCAR" (la ayuda del mando, abajo
    en el centro), y si se tomaba ese toda la coleccion contaba como equipada. Si no hay
    ninguno a la izquierda se usa el ultimo, como antes.
    """
    candidatas = [l for l in lineas if RE_BUSCAR.match(l.texto.strip())]
    izquierda = [l for l in candidatas if l.x < ancho * 0.35]
    if izquierda:
        return min(izquierda, key=lambda l: l.y)
    return candidatas[-1] if candidatas else None


def linea_separadora(lineas: list[Leido], ancho: int, alto: int | None = None) -> int | None:
    """Donde empieza la coleccion (su y), o None si no hay nada que lo diga.

    Primero la caja de busqueda; si no se ve, el orden de la derecha ("DRENAJE"), que va
    en la misma fila; y si tampoco, el filtro de polaridad del centro ("TODOS"), que va
    justo encima (se toma su borde de abajo). Solo por debajo del primer tercio.
    """
    buscar = linea_buscar(lineas, ancho)
    if buscar is not None:
        return buscar.y
    if alto is None:
        alto = max((l.y + l.alto for l in lineas), default=1080)
    orden = [l for l in lineas if RE_ORDEN.match(l.texto.strip()) and l.x > ancho * 0.55 and l.y > alto * 0.3]
    if orden:
        return min(orden, key=lambda l: l.y).y
    filtro = [l for l in lineas if l.y > alto * 0.3 and ancho * 0.3 < l.x + l.ancho / 2 < ancho * 0.75
              and (RE_FILTRO.match(l.texto.strip())
                   or (RE_FILTRO_POLARIDAD.match(l.texto.strip()) and _con_compania(l, lineas, ancho)))]
    if filtro:
        linea = min(filtro, key=lambda l: l.y)
        return linea.y + linea.alto
    return None


def _con_compania(linea: Leido, lineas: list[Leido], ancho: int) -> bool:
    """Si en la fila de esa linea hay otro rotulo en mayusculas lejos de ella (el orden de
    la derecha o la caja de busqueda): asi va el filtro de verdad, y no la etiqueta "AURA"
    de una tarjeta ampliada, que tiene debajo o al lado texto de descripcion."""
    for otra in lineas:
        if otra is linea or not _misma_fila(otra, linea) or abs(otra.x - linea.x) < ancho * 0.15:
            continue
        letras = [c for c in otra.texto if c.isalpha()]
        if len(letras) >= 3 and all(c.isupper() for c in letras) and len(otra.texto.split()) <= 4:
            return True
    return False


def fila_de_capacidad(lineas: list[Leido], ancho: int) -> tuple[Leido | None, tuple[int, int] | None]:
    """La linea "CAPACIDAD" (a la izquierda) y los numeros "libre/total" de su fila."""
    candidatas = [l for l in lineas if RE_CAPACIDAD.match(l.texto.strip()) and l.x < ancho * 0.4]
    if not candidatas:
        return None, None
    linea = min(candidatas, key=lambda l: l.y)
    numeros = None
    for otra in sorted(lineas, key=lambda l: l.x):
        if otra is not linea and not _misma_fila(otra, linea):
            continue
        if otra.x + otra.ancho < linea.x or otra.x > ancho * 0.45:
            continue
        m = RE_NUMEROS_CAPACIDAD.search(otra.texto)
        if m and int(m.group(2)) >= 30:
            numeros = (int(m.group(1)), int(m.group(2)))
            break
    return linea, numeros


def _misma_fila(caja: Leido | tuple, linea: Leido) -> bool:
    """Si la caja (Leido o (x, y, ancho, alto)) cae en la fila de esa linea."""
    y, a = (caja.y, caja.alto) if isinstance(caja, Leido) else (caja[1], caja[3])
    centro = y + a / 2
    return linea.y - linea.alto * 0.5 <= centro <= linea.y + linea.alto * 1.5


def _en_fila_de_configuraciones(caja, capacidad: Leido | None) -> bool:
    """En la fila de "CAPACIDAD", a su derecha: los nombres de las configuraciones. En la
    interfaz anterior las pestanas iban un poco mas altas que "CAPACIDAD" (captura real
    en polaco: "ZASIEG", "SILA", "EIDOLONY" encima de "POJEMNOSC")."""
    if capacidad is None:
        return False
    x, y, a = (caja.x, caja.y, caja.alto) if isinstance(caja, Leido) else (caja[0], caja[1], caja[3])
    centro = y + a / 2
    en_fila = capacidad.y - capacidad.alto * 1.2 <= centro <= capacidad.y + capacidad.alto * 1.5
    return en_fila and x > capacidad.x + capacidad.ancho


def limite_panel(lineas: list[Leido], capacidad: Leido | None, ancho: int) -> float:
    """La x donde acaba el panel de estadisticas de la izquierda.

    Sale del borde derecho de los numeros de "CAPACIDAD 7/74", que van al final del panel
    (a 3440x1440 el panel va mas a la derecha que a 16:9). Sin esa fila, un cuarto del ancho.
    Antes era un 28 % fijo mirando donde EMPIEZA el texto, y los nombres largos de la
    primera columna de tarjetas ("Overextended", "Condition Overload", "Augur Message")
    empezaban antes y se tiraban como si fueran del panel (capturas reales a 1440p y 4K).
    """
    if capacidad is not None:
        fila = [l for l in lineas if (l is capacidad or _misma_fila(l, capacidad))
                and RE_NUMEROS_CAPACIDAD.search(l.texto) and l.x < ancho * 0.45]
        if fila:
            borde = max(l.x + l.ancho for l in fila)
            if ancho * 0.12 < borde < ancho * 0.4:
                return borde + ancho * 0.01
    return ancho * 0.25


def _en_panel(caja, limite: float) -> bool:
    """Si el centro del texto cae dentro del panel de estadisticas."""
    x, a = (caja.x, caja.ancho) if isinstance(caja, Leido) else (caja[0], caja[2])
    return x + a / 2 < limite


# Los huecos vacios rotulados: "EMPTY ARCANE SLOT", "RANURA DE ARCANO VACIA"...
RE_HUECO_VACIO = re.compile(r"(?i)EMPTY|\bVAC[IÍ][AO]\b|\bVIDE\b|\bLEER\b|\bVAZI[AO]\b|\bVUOT[AO]\b|PUSTE\s*GNIAZDO")
RE_RANGO_DELANTE = re.compile(r"^[\^\-~=?C(]?\d{1,2}\W?[A-Za-z]?\W?\s+(?=[A-ZÁÉÍÓÚÑ])")
RE_CORTADO_DELANTE = re.compile(r"^[a-zñ][a-zñáéíóú']{1,4}\s")
# Lo mismo con las palabras pegadas por el OCR: "rnedFeverStrike" (de "Primed Fever Strike").
RE_CORTADO_PEGADO = re.compile(r"^[a-zñ][a-zñáéíóú']{1,5}(?=[A-ZÁÉÍÓÚÑ])")


def _cortado_por_delante(r: Reconocido) -> bool:
    """"ned Cryo Rounds" -> "Cryo Rounds": la tarjeta asoma tapada por delante y el nombre
    real era otro ("Primed Cryo Rounds"). Si lo leido empieza por un trozo en minusculas
    que es una palabra DE MAS (no el final de la primera palabra del nombre casado, como
    "ocus Energy" -> "Focus Energy", donde el OCR solo perdio la primera letra), no se da
    por bueno: seria inventar."""
    texto = RE_RANGO_DELANTE.sub("", r.texto_ocr.strip())  # sin el rango "16r "
    m = RE_CORTADO_DELANTE.match(texto) or RE_CORTADO_PEGADO.match(texto)
    if not m:
        return False
    trozo = _sin_tildes(m.group(0).strip()).lower()
    primera = (_sin_tildes(r.nombre).lower().split() or [""])[0]
    return not (primera.endswith(trozo) or primera.startswith(trozo))


def _todo_mayusculas(texto: str) -> bool:
    """"POSZUKIWACZ", "ZASIEG": cinco letras o mas y todas en mayusculas (sin contar el
    rango de la tarjeta pegado delante, "16V")."""
    letras = [c for c in RE_RANGO_DELANTE.sub("", texto.strip()) if c.isalpha()]
    return len(letras) >= 5 and all(c.isupper() for c in letras)


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def separar_build(
    lineas: list[Leido],
    reconocidos: list[Reconocido],
    categorias: dict[int, str],
    equipo: Reconocido | None = None,
    ancho: int | None = None,
    alto: int | None = None,
) -> Build:
    """Reparte lo reconocido en equipo, mods equipados, coleccion y arcanos.

    `categorias` es item_id -> categoria del indice; `equipo` es lo que caso el
    nombre de la cabecera (lo casa `leer_build`, que tiene el casador). Lo que no
    case queda en `sin_identificar` (texto tal cual), sin las lineas de la interfaz.
    """
    build = Build(equipo=equipo)
    build.equipo_texto, linea_cabecera = cabecera(lineas)
    if ancho is None:
        ancho = max((l.x + l.ancho for l in lineas), default=1920)
    y_buscar = linea_separadora(lineas, ancho)
    capacidad, build.capacidad = fila_de_capacidad(lineas, ancho)
    panel = limite_panel(lineas, capacidad, ancho)
    sin_separador = False
    if y_buscar is not None:
        build.separador = "buscar"
    else:
        # La caja de busqueda, el orden y el filtro tapados (la ayuda de un mod, el chat,
        # otra ventana): sin nada que diga donde empieza la coleccion, TODO acababa en
        # "equipados" y la evaluacion hablaba de 22 mods equipados. Se busca el corte
        # por la geometria de las filas de tarjetas; si no sale claro, todo va a la
        # coleccion y se avisa, en vez de inventar que esta equipado.
        y_buscar = corte_por_filas(reconocidos, categorias, capacidad, panel, alto)
        if y_buscar is not None:
            build.separador = "huecos"
        else:
            sin_separador = True
            y_buscar = -1  # todo por debajo: a la coleccion
    reconocidas_cajas = {r.caja for r in reconocidos}
    vistos_equipados: set[int] = set()
    vistos_arcanos: set[int] = set()
    cortados: list[Reconocido] = []
    for r in sorted(reconocidos, key=lambda r: (r.caja[1], r.caja[0])):
        categoria = categorias.get(r.item_id, "")
        texto = r.texto_ocr.strip()
        if RE_BUSCAR.match(texto) or es_cabecera(texto):
            continue
        if _en_fila_de_configuraciones(r.caja, capacidad):
            continue  # el nombre de una configuracion ("Alcance"), no un mod
        if RE_HUECO_VACIO.search(texto):
            continue  # "EMPTY ARCANE SLOT" casaba con "Arcane Tempo"
        if _cortado_por_delante(r):
            cortados.append(r)
            continue
        # El panel de estadisticas de la izquierda ("Alcance", "Salud"...) no lleva
        # tarjetas: lo que case ahi es una palabra de la interfaz, no un mod.
        en_panel_izquierdo = _en_panel(r.caja, panel) and (sin_separador or r.caja[1] < y_buscar)
        if en_panel_izquierdo and (not sin_separador
                                   or r.caja[1] < (lineas and max(l.y for l in lineas) or 0) * 0.6):
            continue
        if categoria == "Arcanes":
            # El juego no deja llevar el mismo arcano dos veces: el segundo es el titulo
            # de su ayuda abierta ("FORTIFICADOR SECUNDARIO").
            if r.item_id not in vistos_arcanos:
                vistos_arcanos.add(r.item_id)
                build.arcanos.append(r)
        elif categoria == "Mods":
            if _todo_mayusculas(texto):
                # Los nombres de las tarjetas van con mayusculas y minusculas; en mayusculas
                # solo van rotulos: las pestanas de configuracion que nombra el jugador
                # ("ZASIEG", "POSZUKIWACZ" en una captura real en polaco), etiquetas...
                continue
            if y_buscar is not None and r.caja[1] > y_buscar:
                build.coleccion.append(r)
            elif r.item_id not in vistos_equipados:
                # Tampoco el mismo mod dos veces equipado (en la coleccion si puede haber
                # varias copias): el repetido es su ayuda o la tarjeta ampliada.
                vistos_equipados.add(r.item_id)
                build.equipados.append(r)
        elif build.equipo is None and linea_cabecera is None:
            # Sin cabecera legible, el primer objeto que no es mod hace de equipo.
            build.equipo = r
    for linea in lineas:
        # Sin el rango de la tarjeta pegado delante ("16Y Fortalezatransitoria").
        texto = RE_RANGO_DELANTE.sub("", linea.texto.strip())
        if (linea.x, linea.y, linea.ancho, linea.alto) in reconocidas_cajas:
            continue
        if _es_interfaz(texto) or not _puede_ser_nombre(texto):
            continue
        if linea_cabecera is not None and texto in linea_cabecera.texto:
            continue  # media cabecera partida en dos cajas
        if _en_fila_de_configuraciones(linea, capacidad) or (capacidad is not None and linea is capacidad):
            continue
        # El panel de estadisticas de la izquierda ("Cadencia De Fuego", "Muy alta"), por
        # encima de la busqueda: ahi no hay tarjetas.
        if not sin_separador and _en_panel(linea, panel) and linea.y < y_buscar:
            continue
        if _es_frase(texto):
            continue
        # Solo nombres: dos letras seguidas como minimo y no un numero.
        if len(re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", texto)) >= 4 and not es_cabecera(texto):
            build.sin_identificar.append(texto)
    # Las cajas de los bloques (nombres a dos lineas) no coinciden con las de las lineas:
    # se quitan de "sin identificar" los textos que ya forman parte de algo reconocido.
    reconocidos_texto = " ".join(r.texto_ocr for r in reconocidos if r not in cortados).lower()
    build.sin_identificar = [s for s in build.sin_identificar if s.lower() not in reconocidos_texto]
    # Lo leido de una tarjeta tapada no se da por reconocido, pero tampoco se esconde.
    build.sin_identificar += [r.texto_ocr.strip() for r in cortados if r.texto_ocr.strip() not in build.sin_identificar]
    if sin_separador and build.coleccion and not build.aviso:
        build.aviso = AVISO_SIN_SEPARADOR
    return build


AVISO_SIN_SEPARADOR = ("No se ve dónde acaban tus mods equipados (la barra de buscar está tapada): "
                       "los mods se muestran todos juntos y no se evalúa la build. Cierra lo que tape "
                       "la pantalla y vuelve a leer.")
# El juego lleva 8 huecos de mod mas aura y exilus: por encima de 10 no es lo equipado.
MAXIMO_EQUIPADOS = 10


def corte_por_filas(reconocidos: list[Reconocido], categorias: dict[int, str], capacidad: Leido | None,
                    panel: float, alto: int | None = None) -> int | None:
    """La y donde empieza la coleccion, sacada de las filas de tarjetas; None si no sale claro.

    Lo equipado son como mucho tres filas (aura y exilus, y dos filas de cuatro) por
    debajo de "CAPACIDAD"; entre la ultima y la coleccion va la barra de buscar, asi que
    ese hueco es claramente mayor que el paso entre filas. Los nombres se alinean por
    abajo (los de dos lineas crecen hacia arriba), asi que las filas se agrupan por el
    borde de abajo. Se exige: el mayor hueco al menos 1,3 veces el paso entre filas, que
    por encima queden 10 mods o menos, y que el corte caiga en la mitad de abajo.
    """
    mods = [r for r in reconocidos if categorias.get(r.item_id) == "Mods"
            and (capacidad is None or r.caja[1] > capacidad.y + capacidad.alto)
            and not _en_panel(r.caja, panel)]
    if len(mods) < 2:
        return None
    altos = sorted(r.caja[3] for r in mods)
    tolerancia = max(6, altos[0] * 0.8)
    filas: list[list[Reconocido]] = []
    for r in sorted(mods, key=lambda r: r.caja[1] + r.caja[3]):
        abajo = r.caja[1] + r.caja[3]
        if filas and abajo - (filas[-1][-1].caja[1] + filas[-1][-1].caja[3]) <= tolerancia:
            filas[-1].append(r)
        else:
            filas.append([r])
    if len(filas) < 2:
        return None
    bordes = [sum(r.caja[1] + r.caja[3] for r in f) / len(f) for f in filas]
    huecos = [bordes[i + 1] - bordes[i] for i in range(len(bordes) - 1)]
    if alto is None:
        alto = int(max(r.caja[1] + r.caja[3] for r in reconocidos) * 1.1)
    candidatos = []
    encima = 0
    for i, hueco in enumerate(huecos):
        encima += len(filas[i])
        # Mas de 10 mods, o una fila por debajo del 60 % del alto: ya es la coleccion
        # (medido en capturas reales de 1080p a 4K y 21:9, lo equipado acaba antes del
        # 55 % y la coleccion empieza despues del 65 %).
        if encima > MAXIMO_EQUIPADOS or bordes[i] > alto * 0.6:
            break
        candidatos.append((hueco, i))
    if not candidatos:
        return None
    hueco, i = max(candidatos)
    # El hueco de la barra de buscar se compara con el paso entre filas de lo equipado y
    # con el de la primera fila de la coleccion a la siguiente.
    otros = huecos[:i] + huecos[i + 1:i + 2]
    if otros and hueco < 1.3 * max(otros):
        return None
    if bordes[i + 1] < alto * 0.5:
        return None  # la coleccion nunca empieza en la mitad de arriba
    return int(min(r.caja[1] for r in filas[i + 1])) - 1


_PALABRAS_INTERFAZ = {
    "capacity", "capacidad", "config", "health", "salud", "shield", "escudo", "armor", "armadura",
    "energy", "energia", "energía", "sprint", "ability", "habilidad", "duration", "duracion",
    "duración", "efficiency", "eficiencia", "range", "alcance", "strength", "fuerza", "rank",
    "bonuses", "rango", "bonificaciones", "all", "todos", "todo", "drain", "consumo", "search",
    "buscar", "actions", "acciones", "mods", "remove", "quitar", "back", "atras", "atrás",
    "upgrades", "mejoras", "damage", "daño", "dano", "speed", "velocidad", "critical", "critico",
    "crítico", "status", "estado", "chance", "probabilidad", "fire", "rate", "cadencia", "magazine",
    "cargador", "reload", "recarga", "accuracy", "precision", "precisión", "noise", "ruido",
    "trigger", "gatillo", "multishot", "multidisparo", "ammo", "municion", "munición", "total",
    "impact", "impacto", "puncture", "perforacion", "perforación", "slash", "cortante", "polarity",
    "polaridad", "exilus", "aura", "arcane", "arcano", "arcanes", "arcanos", "riven", "agrietado",
    "disposition", "disposicion", "disposición", "sort", "ordenar", "by", "por", "name", "nombre",
    # Palabras de enlace de los rotulos ("VELOCIDAD AL CORRER", "MAX. DE ENERGIA").
    "de", "del", "al", "la", "el", "los", "las", "of", "the", "max", "correr", "tutorial", "drenaje",
    # El panel y los botones en frances, aleman, portugues, italiano y polaco (leidos en
    # capturas reales de jugadores de esos paises).
    "sante", "bouclier", "armure", "vitesse", "course", "pouvoir", "duree", "efficacite", "portee",
    "puissance", "rang", "chercher", "tout", "retour", "retirer", "gesundheit", "schild", "rustung",
    "energie", "sprintgeschwindigkeit", "fahigkeit", "dauer", "effizienz", "reichweite", "starke",
    "boni", "suche", "alle", "kapazitat", "aktionen", "zuruck", "ausbauen", "vida", "velocidade",
    "corrida", "habilidade", "duracao", "forca", "nivel", "procurar", "custo", "capacidade", "voltar",
    "salute", "scudo", "armatura", "velocita", "scatto", "abilita", "durata", "efficienza", "portata",
    "potenza", "bonus", "grado", "cerca", "tutto", "rarita", "capacita", "azioni", "indietro",
    "rimuovi", "pancerz", "szybkosc", "sprintu", "tarcza", "zycie", "czas", "trwania", "sila",
    "wydajnosc", "zasieg", "rangi", "wyszukiwanie", "wszystkie", "sortuj", "wg", "ranga", "pojemnosc",
    "mody", "wstecz", "du", "des", "der", "die", "und", "da", "do", "di",
}
_PALABRAS_INTERFAZ_SIN_TILDES = {"".join(c for c in unicodedata.normalize("NFKD", p) if not unicodedata.combining(c))
                                 for p in _PALABRAS_INTERFAZ}


RE_ESTADISTICA = re.compile(r"%|^[+\-]\s*\d")


def _es_frase(texto: str) -> bool:
    """Un trozo de la descripcion de una ayuda abierta, no un nombre: acaba en punto,
    coma o dos puntos, empieza en minuscula o lleva cifras ("Gana 1 Sobreguardia por")."""
    texto = texto.strip()
    if not texto:
        return True
    if texto[-1] in ".,:;" or texto[0].islower():
        return True
    return bool(re.search(r"\d", texto))


def _puede_ser_nombre(texto: str) -> bool:
    """Si una linea sin reconocer puede ser el nombre de un mod (para "sin identificar").

    Los nombres de las tarjetas van con mayusculas y minusculas ("Continuidad Prime");
    los rotulos de la interfaz, en mayusculas ("BONIFICACIONES DE RANGO", "TUTORIAL",
    "ORDENAR POR: DRENAJE"). Tampoco son nombres las estadisticas ("+50% MAX. DE
    ENERGIA") ni las frases de ayuda (mas de seis palabras).
    """
    if RE_ESTADISTICA.search(texto):
        return False
    letras = [c for c in texto if c.isalpha()]
    if letras and all(c.isupper() for c in letras):
        return False
    return len(texto.split()) <= 6


def _es_interfaz(texto: str) -> bool:
    # Las letras sueltas ("CONFIG A") no cuentan como palabra.
    palabras = [p for p in re.split(r"[^a-z]+", _sin_tildes(texto).lower().replace("ł", "l")) if len(p) > 1]
    if not palabras:
        return True
    return all(p in _PALABRAS_INTERFAZ_SIN_TILDES for p in palabras)


class LectorBuild(LectorBase):
    """Captura la ventana del juego y devuelve la build reconocida por senal."""

    leida = Signal(object)  # Build

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(motor_ocr, CATEGORIAS_BUILD, parent)
        self._categorias: dict[int, str] = {}

    @Slot()
    def iniciar(self) -> None:
        from ..datos import indice

        self._precalentar()
        if not indice.hay_indice():
            self.casador = None
            return
        con = indice.conectar()
        try:
            self.casador = crear_casador(con)
            # Una vez al arrancar, en el hilo de captura: la primera lectura ya no lo paga.
            self.casador.calentar()
            marcas = ", ".join("?" for _ in CATEGORIAS_BUILD)
            self._categorias = dict(
                con.execute(f"SELECT id, categoria FROM items WHERE categoria IN ({marcas})", CATEGORIAS_BUILD)
            )
        finally:
            con.close()
        pantalla.declarar_dpi()

    @Slot()
    def leer_ahora(self) -> None:
        if self._ocupado:
            return
        self._ocupado = True
        try:
            self._leer()
        except Exception:  # noqa: BLE001 - nunca un dialogo de error
            log.exception("Fallo inesperado leyendo la build")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            self.leida.emit(Build())
        finally:
            self._ocupado = False

    def _leer(self) -> None:
        if not self._preparado():
            self.leida.emit(Build())
            return
        self.estado.emit(t("Leyendo la pantalla de mejoras..."))
        inicio = time.perf_counter()
        region = pantalla.region_objetivo()
        imagen = pantalla.capturar(region)
        if imagen is None:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.leida.emit(Build())
            return
        capturado = time.perf_counter()
        try:
            build = leer_build(imagen, self.motor, self.casador, self._categorias)
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            self.leida.emit(Build())
            return
        build.tiempos["captura"] = capturado - inicio
        build.milisegundos = int((time.perf_counter() - inicio) * 1000)
        log.info("Build leida en %d ms (%s): equipo=%s, %d equipados, %d en coleccion, %d arcanos, %d sin identificar",
                 build.milisegundos, resumen_etapas(build.tiempos),
                 build.equipo.nombre if build.equipo else build.equipo_texto or "?",
                 len(build.equipados), len(build.coleccion), len(build.arcanos), len(build.sin_identificar))
        if build.aviso:
            self.estado.emit(t(build.aviso))
        elif build.vacia:
            self.estado.emit(t("No se reconoció nada: abre la pantalla de mejoras del arsenal y vuelve a probar"))
        else:
            self.estado.emit(t("Build leída"))
        self.leida.emit(build)


def resumen_etapas(tiempos: dict) -> str:
    """"captura 20, preparar 3, detector 60, ... ms; imagen 2560x1440 buscada a 1440x810, 80 cajas"."""
    etapas = [f"{etapa} {tiempos[etapa] * 1000:.0f}" for etapa in
              ("captura", "preparar", "detector", "reconocedor", "casado", "reparto") if etapa in tiempos]
    texto = ", ".join(etapas) + " ms" if etapas else "sin tiempos"
    if tiempos.get("entrada"):
        texto += f"; imagen {tiempos['entrada']}"
        if tiempos.get("deteccion") and tiempos["deteccion"] != tiempos["entrada"]:
            texto += f" buscada a {tiempos['deteccion']}"
    if "cajas" in tiempos:
        texto += f", {tiempos['cajas']} cajas"
    if tiempos.get("motor"):
        texto += f", motor {tiempos['motor']}"
    return texto


def leer_build(imagen, motor, casador: Casador, categorias: dict[int, str]) -> Build:
    """OCR de la captura entera y reparto en equipo, mods y arcanos.

    El texto se busca en la captura reducida (`alto_de_deteccion`) y se lee a tamano
    real (los nombres de las tarjetas miden ~20 px a 1080p). Deja en `build.tiempos`
    lo que costo cada etapa.
    """
    # La confianza se filtra ANTES de unir filas: un garabato de baja confianza pegado a
    # la cabecera ("UPGRADES/EXCALIBUR[30] 美") se la llevaba por delante al unirse.
    lineas = unir_filas([l for l in motor.leer_tira(imagen, alto_deteccion=alto_de_deteccion(imagen.shape[0]))
                         if l.confianza >= MINIMO_CONFIANZA])
    tiempos = dict(getattr(motor, "tiempos", None) or {})
    inicio = time.perf_counter()
    reconocidos = casar_lineas(lineas, casador, UMBRAL_MODS, subbloques=True)
    reconocidos += _tarjetas_ampliadas(lineas, reconocidos, casador, categorias)
    reconocidos = _nombres_a_dos_lineas(lineas, reconocidos, casador, categorias)
    nombre_equipo, linea = cabecera(lineas)
    equipo = _casar_equipo(nombre_equipo, linea, casador, categorias)
    texto_releido = ""
    parece_mejoras = any(categorias.get(r.item_id) == "Mods" for r in reconocidos) or any(
        l.y < imagen.shape[0] * 0.1 and RE_RANGO_CABECERA.search(l.texto) for l in lineas)
    if equipo is None and parece_mejoras:
        # La cabecera no se leyo (tapada en parte por algo, o el OCR la junto con lo de
        # al lado): se relee sola la franja de arriba, que al ir aparte sale entera.
        texto_releido, equipo = _releer_cabecera(imagen, motor, casador, categorias, lineas)
    casado = time.perf_counter()
    build = separar_build(lineas, reconocidos, categorias, equipo, ancho=imagen.shape[1], alto=imagen.shape[0])
    if texto_releido and not build.equipo_texto:
        build.equipo_texto = texto_releido
    tiempos["casado"] = casado - inicio
    tiempos["reparto"] = time.perf_counter() - casado
    build.tiempos = tiempos
    build.lineas = lineas
    build.alto, build.ancho = int(imagen.shape[0]), int(imagen.shape[1])
    build.idioma = idioma_de_cabecera(linea.texto) if linea is not None else ""
    if not build.equipados and not build.coleccion and not build.arcanos and parece_cirilico(lineas):
        # El OCR no lee cirilico: lo que sale son letras latinas parecidas
        # ("BMECTWMOCTb" por "ВМЕСТИМОСТЬ"). No se casa nada (bien: no inventa), pero
        # ensenar esos garabatos como "sin identificar" no ayuda; se explica por que.
        build.idioma = "ru"
        build.aviso = AVISO_CIRILICO
        build.sin_identificar = []
    return build


AVISO_CIRILICO = ("No se puede leer: el juego está en un idioma con otras letras (como el ruso). "
                  "El lector entiende el juego en inglés, español, francés, alemán, portugués, "
                  "italiano y polaco.")
# Lo que deja el OCR (hecho para letras latinas) al leer ruso: la "ь" sale como "b"
# detras de mayusculas ("BMECTWMOCTb", "CekpeTbl", "MbiWneHwe", "HenpepbIBHocTb").
# Medido en capturas reales de YouTube en ruso a 1080p, 1440p y 4K.
RE_CIRILICO_LEIDO = re.compile(r"[A-Z]b|[A-Za-z]b[A-Z]|[A-Z]b[il]|bI")


def parece_cirilico(lineas: list[Leido]) -> bool:
    """Si la pantalla parece cirilico leido con letras latinas (cuatro lineas o mas)."""
    return sum(1 for l in lineas if RE_CIRILICO_LEIDO.search(l.texto)) >= 4


def _casar_equipo(nombre_equipo: str, linea: Leido | None, casador: Casador,
                  categorias: dict[int, str]) -> Reconocido | None:
    """El warframe o el arma que dice la cabecera (nunca un mod ni un arcano)."""
    for nombre in _nombres_de_equipo(nombre_equipo) if nombre_equipo else []:
        item_id, etiqueta, puntos = casador.casar(nombre, UMBRAL_MODS)
        if item_id and categorias.get(item_id) not in ("Mods", "Arcanes", None):
            caja = (linea.x, linea.y, linea.ancho, linea.alto) if linea is not None else (0, 0, 0, 0)
            return Reconocido(nombre, item_id, etiqueta, puntos, caja)
    return None


# Lo que va entre la barra y el rango en la cabecera: "...RAS/RHINO PRIME [30]" (la
# palabra de delante puede salir tapada o rota: "FehaRAS/", "E[30]").
RE_RANGO_CABECERA = re.compile(r"[\[\(【（［]\s*(?:N[IÍ]VEL\s*)?[\dOIl|]{1,2}\s*[\]\)】）］]"
                               r"|(?:RANK|RANGA|RANGO?|NIVEAU|GRADO)\s*[\dOIl|]{1,2}\s*$")
RE_TRAS_BARRA = re.compile(rf"[/:]\s*([^/:\[\(【（［]{{2,}}?)\s*{_RANGO_FINAL}")
# (alto, ancho) de las franjas de arriba, en proporcion de la captura, donde va la cabecera.
FRANJAS_CABECERA = ((0.085, 0.5), (0.1, 0.6), (0.07, 0.45))


def recortes_de_cabecera(lineas: list[Leido] | None, ancho: int, alto: int) -> list[tuple[int, int, int, int]]:
    """(y0, y1, x0, x1) donde releer la cabecera: las franjas de arriba a la izquierda de
    siempre y, detras, las que salen de lo que si se leyo cerca de ella.

    Con la escala de menu del juego por debajo del 100 %, en 16:10 (mas fondo arriba) o
    con la ventana del juego dentro de una captura del escritorio entero, la cabecera no
    cae en las franjas fijas. Se usa de ancla un trozo de cabecera ("E[30]", "RANK 30") o,
    si no, la fila de "CAPACIDAD", que va justo debajo.
    """
    recortes = [(0, max(1, int(alto * fa)), 0, max(1, int(ancho * fw))) for fa, fw in FRANJAS_CABECERA]
    anclas = []
    for l in lineas or []:
        if l.y < alto * 0.35 and (RE_RANGO_CABECERA.search(l.texto) or _es_palabra_cabecera(l.texto)):
            anclas.append((l.y - l.alto, l.y + l.alto * 2, l.x + l.ancho))
    capacidad, _ = fila_de_capacidad(lineas or [], ancho)
    if capacidad is not None and capacidad.y < alto * 0.4:
        anclas.append((capacidad.y - capacidad.alto * 3.5, capacidad.y - capacidad.alto * 0.3, ancho * 0.75))
    for y0, y1, derecha in anclas:
        y0, y1 = max(0, int(y0)), min(alto, int(y1))
        x1 = min(ancho, int(max(derecha + ancho * 0.05, ancho * 0.45)))
        if y1 - y0 >= 8 and (y0, y1, 0, x1) not in recortes:
            recortes.append((y0, y1, 0, x1))
    return recortes


def _releer_cabecera(imagen, motor, casador: Casador, categorias: dict[int, str],
                     lineas_pantalla: list[Leido] | None = None) -> tuple[str, Reconocido | None]:
    """Relee la franja de la cabecera por separado y casa lo que va tras la barra.

    Medido con capturas reales de YouTube: con el rotulo del streamer tapando
    "MEJORAS", el OCR de la pantalla entera solo sacaba "E[30]"; la franja sola da
    "FehaRAS/MESA PRIME [30]". Solo se acepta lo que va entre "/" y el rango "[30]" y
    casa con un warframe o un arma del catalogo: nunca se adivina.
    """
    leer = getattr(motor, "leer", None)
    if leer is None or imagen is None or getattr(imagen, "ndim", 0) < 2:
        return "", None
    alto, ancho = imagen.shape[:2]
    tiempos = dict(getattr(motor, "tiempos", None) or {})
    primero = ""
    try:
        # El reconocedor lee la linea entera de una vez y el resultado cambia con el
        # recorte (medido: con un recorte "RHINO PRIME", con otro "RNOPRIME"). Se
        # prueban unos pocos, de mas a menos probable, hasta que uno case.
        for y0, y1, x0, x1 in recortes_de_cabecera(lineas_pantalla, ancho, alto):
            franja = imagen[y0:y1, x0:x1]
            try:
                leidos = leer(franja)
            except ErrorMotorOCR:
                return "", None
            lineas = unir_filas([l for l in leidos if l.confianza >= MINIMO_CONFIANZA])
            nombre, linea = cabecera(lineas)
            candidatos = [(nombre, linea)] if nombre else []
            for l in lineas:
                m = RE_TRAS_BARRA.search(l.texto)
                if m:
                    candidatos.append((m.group(1).strip(), l))
            for nombre, l in candidatos:
                equipo = _casar_equipo(nombre, l, casador, categorias)
                if equipo is not None:
                    return nombre, equipo
            if candidatos and not primero:
                primero = candidatos[0][0]
    finally:
        if hasattr(motor, "tiempos"):
            motor.tiempos = tiempos  # los de la lectura grande son los que van al registro
    return primero, None


def _tarjetas_ampliadas(lineas: list[Leido], reconocidos: list[Reconocido], casador: Casador,
                        categorias: dict[int, str]) -> list[Reconocido]:
    """Nombres a dos lineas encima de un texto: la tarjeta ampliada al pasar el raton.

    La tarjeta ampliada pone el nombre ("Deconstruccion de" / "sintetizador") y debajo
    su descripcion; el bloque entero no casa y cada linea sola tampoco. Aqui se prueban
    las dos primeras lineas del bloque (sin el rango de arriba) y solo valen si casan
    con un mod con mucha seguridad.
    """
    cubiertas = [r.caja for r in reconocidos]

    def cubierta(l: Leido) -> bool:
        cx, cy = l.x + l.ancho / 2, l.y + l.alto / 2
        return any(x <= cx <= x + a and y <= cy <= y + h for x, y, a, h in cubiertas)

    libres = [l for l in lineas if not cubierta(l)]
    salida = []
    for bloque in agrupar_bloques(libres):
        while bloque and RE_RANGO_TARJETA.match(bloque[0].texto.strip()):
            bloque = bloque[1:]
        if len(bloque) < 3:
            continue  # los de dos lineas ya los probo casar_lineas
        primera, segunda = bloque[0], bloque[1]
        if not primera.texto[:1].isupper() or _es_interfaz(primera.texto):
            continue
        if RE_ESTADISTICA.search(primera.texto) or RE_ESTADISTICA.search(segunda.texto):
            continue
        texto = f"{primera.texto} {segunda.texto}"
        item_id, etiqueta, puntos = casador.casar(texto, UMBRAL_AMPLIADA)
        if item_id and categorias.get(item_id) == "Mods":
            x0, y0 = min(primera.x, segunda.x), primera.y
            x1 = max(primera.x + primera.ancho, segunda.x + segunda.ancho)
            salida.append(Reconocido(texto, item_id, etiqueta, puntos, (x0, y0, x1 - x0, segunda.y + segunda.alto - y0)))
    return salida


UMBRAL_AMPLIADA = 90


def _media_linea(texto: str) -> str | None:
    """Lo que puede ser media linea del nombre de una tarjeta ("Mroczna", "Przejsciowe"),
    sin el rango pegado delante; None si es un numero, una frase de ayuda, una estadistica
    o un rotulo de la interfaz."""
    texto = RE_RANGO_DELANTE.sub("", texto.strip())
    # "164 Intensyfikacja": el rango "16" con el icono de polaridad leido como cifra.
    texto = re.sub(r"^\d{1,3}\S?\s+(?=[^\W\d_])", "", texto)
    letras = [c for c in texto if c.isalpha()]
    if len(letras) < 3 or not texto[:1].isupper() or len(texto.split()) > 3:
        return None
    if all(c.isupper() for c in letras) or _es_frase(texto) or RE_ESTADISTICA.search(texto) or _es_interfaz(texto):
        return None
    return texto


def _dentro(l: Leido, caja) -> bool:
    x, y, a, h = caja
    cx, cy = l.x + l.ancho / 2, l.y + l.alto / 2
    return x <= cx <= x + a and y <= cy <= y + h


def _pegadas(arriba: Leido, abajo: Leido, lineas: list[Leido] = ()) -> bool:
    """Si dos lineas son las dos mitades de un nombre en la misma tarjeta: una justo
    encima de la otra, centradas, con letra del mismo tamano (la descripcion de una
    tarjeta ampliada va con letra mas pequena) y sin nada leido en medio ("Vigilante
    Fervor", "+4 Fire Rate (x2 for", "Bows)": el nombre no sigue en "Bows)")."""
    alto = min(arriba.alto, abajo.alto)
    if abs(arriba.alto - abajo.alto) > 0.25 * max(arriba.alto, abajo.alto):
        return False
    if abs(arriba.x + arriba.ancho / 2 - (abajo.x + abajo.ancho / 2)) > 0.3 * max(arriba.ancho, abajo.ancho):
        return False
    if not -0.5 * alto <= abajo.y - (arriba.y + arriba.alto) <= 0.9 * alto:
        return False
    x0, x1 = min(arriba.x, abajo.x), max(arriba.x + arriba.ancho, abajo.x + abajo.ancho)
    for l in lineas:
        if l is arriba or l is abajo:
            continue
        centro = l.y + l.alto / 2
        if arriba.y + arriba.alto * 0.75 < centro < abajo.y + abajo.alto * 0.25 and l.x < x1 and l.x + l.ancho > x0:
            return False
    return True


def _nombres_a_dos_lineas(lineas: list[Leido], reconocidos: list[Reconocido], casador: Casador,
                          categorias: dict[int, str]) -> list[Reconocido]:
    """Nombres a dos lineas que el casado de bloques no junto.

    A 720p y 768p (capturas reales de 1080p en polaco reducidas) las dos lineas del nombre
    salian separadas: "Mroczna" / "Intensyfikacja" casaba solo la de abajo, con otro mod
    ("Intensyfikacja" a secas), y se inventaba; "Przejsciowe" / "Wzmocnienie" no casaba
    ninguna. Si pegada a la linea de un mod casado hay otra sin casar que parece medio
    nombre, se prueban juntas: si casan, vale lo junto; si no, no se da por bueno ninguno
    (mejor "sin identificar" que un mod que no esta). Y dos lineas sin casar pegadas se
    prueban juntas.
    """
    def usada(l: Leido) -> bool:
        texto = l.texto.strip()
        return any(texto and texto in r.texto_ocr and _dentro(l, r.caja) for r in reconocidos)

    libres = [l for l in lineas if not usada(l) and _media_linea(l.texto)]
    if not libres:
        return reconocidos
    salida = []
    gastadas: set[int] = set()
    for r in reconocidos:
        if categorias.get(r.item_id) != "Mods":
            salida.append(r)
            continue
        propias = [l for l in lineas if _dentro(l, r.caja) and l.texto.strip() in r.texto_ocr and _media_linea(l.texto)]
        if len(propias) != 1:
            salida.append(r)  # ya casado a dos lineas, o sin linea propia que mirar
            continue
        linea = propias[0]
        vecina = next((l for l in libres if id(l) not in gastadas
                       and (_pegadas(l, linea, lineas) or _pegadas(linea, l, lineas))), None)
        if vecina is None:
            salida.append(r)
            continue
        gastadas.add(id(vecina))
        arriba, abajo = (vecina, linea) if vecina.y < linea.y else (linea, vecina)
        texto = f"{_media_linea(arriba.texto)} {_media_linea(abajo.texto)}"
        item_id, etiqueta, puntos = casador.casar(texto, UMBRAL_MODS)
        # Lo junto tiene que explicar las dos lineas: "Qwerty Intensyfikacja" casa a duras
        # penas con el mismo "Intensyfikacja" de antes, y la otra media linea no se explica.
        explica = item_id != r.item_id or puntos >= 95
        if item_id and categorias.get(item_id) == "Mods" and explica:
            salida.append(Reconocido(texto, item_id, etiqueta, puntos, _caja_de(arriba, abajo)))
        else:
            log.debug("Nombre a medias, no se da por bueno: %r junto a %r", r.texto_ocr, vecina.texto)
    for arriba in libres:
        if id(arriba) in gastadas:
            continue
        abajo = next((l for l in libres if l is not arriba and id(l) not in gastadas and _pegadas(arriba, l, lineas)), None)
        if abajo is None:
            continue
        texto = f"{_media_linea(arriba.texto)} {_media_linea(abajo.texto)}"
        # Dos lineas que no casaban solas: se pide mas seguridad que al casado normal.
        item_id, etiqueta, puntos = casador.casar(texto, UMBRAL_AMPLIADA)
        if item_id and categorias.get(item_id) == "Mods":
            gastadas.update((id(arriba), id(abajo)))
            salida.append(Reconocido(texto, item_id, etiqueta, puntos, _caja_de(arriba, abajo)))
    return salida


def _caja_de(*lineas_caja: Leido) -> tuple[int, int, int, int]:
    x0, y0 = min(l.x for l in lineas_caja), min(l.y for l in lineas_caja)
    x1 = max(l.x + l.ancho for l in lineas_caja)
    y1 = max(l.y + l.alto for l in lineas_caja)
    return x0, y0, x1 - x0, y1 - y0
