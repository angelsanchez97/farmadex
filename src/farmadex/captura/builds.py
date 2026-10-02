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
from ..datos.difuso import Levenshtein, fuzz

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
    normalizar,
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
    rf"(?i)^\W*(?:{_PALABRA_CABECERA})\s*(?:[/:]\s*)?(?:[|!]\s*)?([^\W_].+?)"
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
    # Validacion cruzada (captura/huecos_build.py): los huecos de la rejilla que se ven
    # ocupados pero de los que no salio ningun mod, para pintarlos como "no he podido leer
    # este mod" en vez de dejarlos vacios; la colocacion de lo leido en los huecos del
    # equipo (None si el equipo no tiene plantilla); y cuantos huecos se vieron ocupados.
    no_leidos: list = field(default_factory=list)
    colocacion: object = None
    huecos_vistos: int = 0

    @property
    def vacia(self) -> bool:
        return self.equipo is None and not self.equipados and not self.coleccion and not self.arcanos


def _filtro_build(categoria: str, tipo: str | None, unique_name: str) -> bool:
    """Deja fuera lo que no puede salir en la pantalla de mejoras.

    Las piezas de receta (chasis, canon...) tienen padre y el Casador ya las etiqueta
    con el; aqui no interesan, ni los agrietados genericos ("Rifle Riven Mod").
    """
    # Solo el ultimo tramo de la ruta: las armas de MOA viven en ".../MoaPetComponents/
    # TazronWeapon" y se quedaban fuera, y "TAZICOR" acababa casando con otra cosa.
    if "/Recipes/" in unique_name or "Component" in unique_name.rsplit("/", 1)[-1]:
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
    palabra = _palabra_de_cabecera(compacta)
    return f"{palabra}/{detras}" if palabra else texto


# Cuantas letras ajenas se admiten delante de la palabra de la cabecera ("165MEJORAS").
MAXIMO_BASURA_CABECERA = 6


def _palabra_de_cabecera(compacta: str) -> str | None:
    """La palabra de la cabecera que es `compacta` (lo leido, en mayusculas y sin signos), o None.

    Vale con erratas ("MEJ0RAS", "MEORAS", "MESJORAS") y con algo ajeno pegado delante: un
    medidor de rendimiento pintado encima de la esquina (RivaTuner, el contador de FPS de
    Steam) deja "165MEJORAS" o "WESJORAS" (captura real de un jugador). Tiene que parecerse
    mucho y conservar el principio o el final de la palabra: "MEJORAS" no sale de "RAS"."""
    for palabra in PALABRAS_CABECERA:
        # Las 3 primeras letras tienen que estar: "MEJORAS" no puede salir de "RAS".
        if compacta[:3] == palabra[:3] and fuzz.ratio(compacta, palabra) >= 80:
            return palabra
    for palabra in PALABRAS_CABECERA:
        for inicio in range(0, min(MAXIMO_BASURA_CABECERA, max(0, len(compacta) - len(palabra) + 2)) + 1):
            trozo = compacta[inicio:]
            if len(trozo) < len(palabra) - 1:
                break
            if (trozo[:3] == palabra[:3] or trozo[-4:] == palabra[-4:]) and fuzz.ratio(trozo, palabra) >= 80:
                return palabra
    return None


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
    # Leida aparte ("MESJORAS" en su caja, el nombre en otra) o sin nada detras.
    sola = _palabra_de_cabecera(compacta.translate(_CIFRAS_POR_LETRAS)) if 5 <= len(compacta) <= 20 else None
    return PALABRAS_CABECERA[sola] if sola else None


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
    return _palabra_de_cabecera(compacta) is not None


# Restos del rango y de las formas pegados detras del nombre: "HAALVU3O", "HAALVU303OI",
# "HAALVU3O 3OI", "HAALVU3013=". Empiezan por una cifra (o un borde de corchete).
RE_RANGO_PEGADO = re.compile(r"(?<=[A-Za-z])(?:\s|[\[\(=|])*\d[\s\dOIl|=\-\]\[)(]*$")
# "UNRANKED HYDROID" (sin rango) delante, "NIDUS RANK 29" detras (interfaz vieja), y lo
# mismo en cada idioma: "NYXPRIMERANG30", "GYRE GRADO 30", "OBERON PRIME RANGA ZERO",
# "ZEPHYR PRIME NIVEAU" (el numero cortado). El rango puede salir con letras por cifras:
# "LIMBO PRIME RANGO 3O".
RE_SIN_RANGO = re.compile(
    rf"(?i)^(?:UNRANKED|SIN\s*RANGO|RANGA\s*ZERO)\s*|\s*(?:{_PALABRA_RANGO})\s*(?:\d[\dOIl|]*|Z[EÉ]RO)?\s*$")


# El rango sin su corchete de abrir: "INAROS PRIME 30]", "INAROS PRIME 3O)".
RE_RANGO_SIN_ABRIR = re.compile(r"\s*(?:\d[\dOIl|]?|[OIl|]\d)\s*[\]\)】）］](?:\s*\S{1,2})?\s*$")
# Lo menos que tiene que quedar de un nombre al quitarle fichas sueltas de delante.
MINIMO_NOMBRE_SIN_FICHAS = 5


def _sin_fichas_sueltas(nombre: str) -> str:
    """"Y TNAROS PRIME" -> "TNAROS PRIME": la barra de la cabecera ("MEJORAS / INAROS
    PRIME") sale a veces leida como una letra suelta ("Y", "I", "|", "7") pegada delante
    del nombre. Se quitan hasta dos fichas de una o dos letras del principio, si lo que
    queda sigue pareciendo un nombre; si no, devuelve el nombre tal cual."""
    return _quitar_fichas(nombre)[0]


# Como sale la barra "/" de la cabecera cuando el OCR la toma por una letra o un signo.
FICHAS_DE_BARRA = frozenset("YyIl1|/!7Jj")


def _quitar_fichas(nombre: str) -> tuple[str, list[str]]:
    """(nombre sin las fichas sueltas de delante, las fichas quitadas). Solo se quita lo que
    puede ser la barra mal leida (una o dos fichas de un signo): "DA SPOROTHRIX" es un
    "CODA SPOROTHRIX" cortado, no un Sporothrix con basura delante."""
    palabras = nombre.split()
    quitadas: list[str] = []
    while len(palabras) > 1 and len(quitadas) < 2 and len(palabras[0]) == 1 and palabras[0] in FICHAS_DE_BARRA:
        quitadas.append(palabras[0])
        palabras = palabras[1:]
    resto = " ".join(palabras)
    if quitadas and len(resto.replace(" ", "")) >= MINIMO_NOMBRE_SIN_FICHAS:
        return resto, quitadas
    return nombre, []


def _nombres_de_equipo(nombre: str) -> list[str]:
    """Lo leido en la cabecera y, detras, lo mismo sin los restos del rango que el OCR
    pega al nombre: "HAALVU I[22]" (una letra suelta), "HAALVU[3O]3" o "HAALV U [2 2 ]"
    (el corchete), "HAALVU3O" (sin corchete), "INAROS PRIME 30]" (sin el corchete de
    abrir). Al final, lo mismo sin las fichas sueltas de delante (`_sin_fichas_sueltas`).
    Se prueban en orden."""
    return _con_fichas_quitadas(_nombres_de_equipo_base(nombre))


RE_PRIME_MAL_LEIDO = re.compile(r"(?i)\bPR[Il1|!]ME\b")


def _con_fichas_quitadas(intentos: list[str]) -> list[str]:
    for base in list(intentos):
        # "NYX PRlME", "MAG PR1ME": la I de "PRIME" leida como ele, uno o barra.
        arreglado = RE_PRIME_MAL_LEIDO.sub("PRIME", base)
        if arreglado not in intentos:
            intentos.append(arreglado)
    for base in list(intentos):
        limpio = _sin_fichas_sueltas(base)
        if limpio not in intentos:
            intentos.append(limpio)
    return intentos


RE_ARMA_DE_LICH = re.compile(r"(?i)\b(KUVA|TENET|CODA)\s+\S")
RE_ARMA_DE_LICH_ES = re.compile(r"(?i)^(\S+\s+(?:KUVA|TENET|CODA))\s+DE\s+\S")
RE_ARMA_DE_LICH_PEGADA = re.compile(r"(?i)^([A-Z]{3,}(?:KUVA|TENET|CODA))DE[A-Z]{3,}")


def nombres_de_arma_de_lich(nombre: str) -> list[str]:
    """El nombre del arma dentro del rotulo de un arma de lich, que lleva pegado el nombre
    del lich: "SITT VORGRO KUVA ZARR RANG 34" (captura real en aleman: el equipo empieza en
    KUVA/TENET/CODA), "NUKOR KUVA DE EKK RABRAS RANGO 40" (en castellano el lich va detras
    de "DE") o todo pegado por el OCR, "CHAKKHURRKUVADEPOGONTMAHIFFNIVEAU40" (en frances).
    Lo que sale esta acotado por los dos lados (la barra y el lich): cuenta como entero."""
    salida: list[str] = []
    m = RE_ARMA_DE_LICH.search(nombre)
    if m and m.start() > 0:
        salida.append(nombre[m.start():])
    m = RE_ARMA_DE_LICH_ES.match(nombre)
    if m:
        salida.append(m.group(1))
    m = RE_ARMA_DE_LICH_PEGADA.match(nombre)
    if m and m.group(1) not in salida:
        salida.append(m.group(1))
    return salida


def _nombres_de_equipo_base(nombre: str) -> list[str]:
    intentos = [nombre]
    intentos += [n for n in nombres_de_arma_de_lich(nombre) if n not in intentos]
    # El laurel de la maestria detras del rango leido como una letra: "TAZICOR RANGO 30 L"
    # (captura real, interfaz antigua). Sin esa ficha, el rango de detras se quita como siempre.
    palabras = nombre.split()
    if len(palabras) >= 3 and RE_FICHA_TRAS_RANGO.match(palabras[-1]) and RE_CIFRAS_DE_RANGO.match(palabras[-2]):
        nombre = " ".join(palabras[:-1])
        intentos.append(nombre)
    sin_cola = RE_RANGO_SIN_ABRIR.sub("", nombre).strip()
    if sin_cola and sin_cola != nombre and not re.search(r"[\[\(【（［]", nombre):
        intentos.append(sin_cola)
        nombre = sin_cola
    limpio = RE_SIN_RANGO.sub("", nombre).strip()
    if limpio and limpio != nombre:
        intentos.append(limpio)
        # Sin rango no hay numero detras del nombre, y el laurel de la maestria sale pegado
        # como letras: "UNRANKED NUNCHASA PSS" (captura real). Tambien sin esa ficha.
        palabras = limpio.split()
        if RE_SIN_TOPE_DE_RANGO.match(nombre) and len(palabras) >= 2 and re.fullmatch(r"[A-Za-z|!]{1,3}", palabras[-1]) \
                and len(palabras[-2]) >= 4:
            intentos.append(" ".join(palabras[:-1]))
        nombre = limpio
    corte = re.split(r"[\[\(【（［]", nombre, maxsplit=1)[0].strip()
    if corte and corte != nombre:
        intentos.append(corte)
        nombre = corte
    sin_guion = nombre.rstrip(" -–—_.,;:'\"")
    if sin_guion and sin_guion != nombre:
        intentos.append(sin_guion)
    for base in [i for i in intentos if not re.search(r"[\[\(【（［]", i)]:
        sin_rango = RE_RANGO_PEGADO.sub("", base).strip()
        if sin_rango and sin_rango not in intentos:
            intentos.append(sin_rango)
    for base in list(intentos):
        palabras = base.split()
        # Solo si la letra suelta puede ser el borde del corchete: "HAALVU I[22]".
        if len(palabras) > 1 and palabras[-1] in ("I", "l", "|", "1"):
            intentos.append(" ".join(palabras[:-1]))
        # El rango entero leido como letras: "HAALVU LUJ" por "HAALVU [30]" (captura real a
        # 4K). Solo fichas hechas de las letras en que se convierten los corchetes y las
        # cifras, y sin vocal de verdad salvo la U del "[3O]".
        elif len(palabras) > 1 and RE_RANGO_COMO_LETRAS.match(palabras[-1]):
            intentos.append(" ".join(palabras[:-1]))
    return intentos


RE_RANGO_COMO_LETRAS = re.compile(r"^[LlIi1|JjUuCc\[\]()]{2,3}$")
RE_FICHA_TRAS_RANGO = re.compile(r"^[A-Za-z|!]{1,2}$")
RE_CIFRAS_DE_RANGO = re.compile(r"^[\dOIl]{1,2}$")


def es_rotulo_buscar(texto: str) -> bool:
    """Si la linea es el rotulo de la caja de busqueda ("BUSCAR...", "|BUSCAR."). El juego lo
    escribe en mayusculas; "Buscar" con minusculas es el mod de companero Scavenge en
    castellano (captura real de un kubrow: se tiraba como si fuera la caja y faltaba un mod)."""
    texto = texto.strip()
    if not RE_BUSCAR.match(texto):
        return False
    letras = [c for c in texto if c.isalpha()]
    return all(c.isupper() for c in letras)


def linea_buscar(lineas: list[Leido], ancho: int) -> Leido | None:
    """La caja de busqueda, que separa lo equipado (arriba) de la coleccion (abajo).

    Va a la izquierda de la pantalla; puede haber otro "BUSCAR" (la ayuda del mando, abajo
    en el centro), y si se tomaba ese toda la coleccion contaba como equipada. Si no hay
    ninguno a la izquierda se usa el ultimo, como antes.
    """
    candidatas = [l for l in lineas if es_rotulo_buscar(l.texto)]
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
        bordes = []
        for l in lineas:
            if not (l is capacidad or _misma_fila(l, capacidad)) or l.x >= ancho * 0.45:
                continue
            m = RE_NUMEROS_CAPACIDAD.search(l.texto)
            if m is None:
                continue
            # El borde de los NUMEROS, no de la linea: en la interfaz anterior el OCR pega
            # "4/74" con el rotulo "RANG-BONI" de al lado ("4/74 RANG-BONI") y el panel se
            # alargaba hasta comerse la primera columna de tarjetas (captura real en aleman).
            bordes.append(l.x + l.ancho * m.end() / max(1, len(l.texto)))
        if bordes:
            borde = max(bordes)
            if ancho * 0.12 < borde < ancho * 0.4:
                return borde + ancho * 0.01
    return ancho * 0.25


def _en_panel(caja, limite: float) -> bool:
    """Si el centro del texto cae dentro del panel de estadisticas."""
    x, a = (caja.x, caja.ancho) if isinstance(caja, Leido) else (caja[0], caja[2])
    return x + a / 2 < limite


# Los huecos vacios rotulados: "EMPTY ARCANE SLOT", "RANURA DE ARCANO VACIA"...
RE_HUECO_VACIO = re.compile(r"(?i)EMPTY|\bVAC[IÍ][AO]\b|\bVIDE\b|\bLEER\b|\bVAZI[AO]\b|\bVUOT[AO]\b|PUSTE\s*GNIAZDO"
                            # La ranura de arcano bloqueada ("Requires Secondary Arcane Adapter",
                            # "Benotigt Sekundar Arkana-Adapter"): tampoco lleva nada.
                            # Palabras enteras: "Adaptation" / "Adaptacion" es un mod y casaba aqui.
                            r"|ADAPT(?:ER|ADOR|ATEUR)|ADATTATORE"
                            # Y el hueco de exilus sin adaptador: "Requires Exilus Adapter",
                            # "Wymaga Adapter Exilus", "Requiere...", "Benotigt...", "Necessite...".
                            r"|\bREQUIRES?\b|\bREQUIERE\b|\bWYMAGA\b|\bBEN[OÖ]TIGT\b|\bN[EÉ]CESSITE\b|\bRICHIEDE\b|\bREQUER\b")
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
        elif _solo_arriba(reconocidos, categorias, panel, alto):
            # No hay coleccion a la vista (la pantalla esta recortada por debajo de las
            # tarjetas, un montaje de video) y todos los mods caen donde solo va lo equipado
            # (por encima del 62 % del alto; la coleccion empieza siempre despues del 65 %).
            build.separador = "arriba"
            y_buscar = int((alto or 1080) * 0.62)
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
        if es_rotulo_buscar(texto) or es_cabecera(texto):
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
            # de su ayuda abierta ("FORTIFICADOR SECUNDARIO"). El titulo va en mayusculas y
            # el nombre bajo el icono no: el titulo nunca vale (si no, se quedaba con la
            # posicion de la ayuda, en medio de los mods, y la rejilla no cuadraba).
            if _todo_mayusculas(texto):
                continue
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
        elif (build.equipo is None and linea_cabecera is None and r.puntuacion >= 100
              and (alto is None or r.caja[1] < alto * 0.15)):
            # Sin cabecera legible, el primer objeto que no es mod hace de equipo: solo si
            # es su nombre exacto y esta arriba, donde va la cabecera. "mesPrime" (la cola
            # de un "Pies firmes Prime" tapado, en medio de las tarjetas) daba Mesa Prime.
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


def _solo_arriba(reconocidos: list[Reconocido], categorias: dict[int, str], panel: float, alto: int | None) -> bool:
    """Si todos los mods leidos (fuera del panel) estan en la zona de lo equipado y no son
    mas de los que caben."""
    if not alto:
        return False
    mods = [r for r in reconocidos if categorias.get(r.item_id) == "Mods" and not _en_panel(r.caja, panel)]
    return 0 < len(mods) <= MAXIMO_EQUIPADOS and all(r.caja[1] + r.caja[3] < alto * 0.62 for r in mods)


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
        self._tipos_hueco = None

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
            from .huecos_build import cargar_tipos_de_hueco

            self._tipos_hueco = cargar_tipos_de_hueco(con)
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
            build = leer_build(imagen, self.motor, self.casador, self._categorias, self._tipos_hueco)
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            self.leida.emit(Build())
            return
        build.tiempos["captura"] = capturado - inicio
        build.milisegundos = int((time.perf_counter() - inicio) * 1000)
        log.info("Build leida en %d ms (%s): equipo=%s, %d equipados, %d en coleccion, %d arcanos, %d sin identificar,"
                 " %d huecos ocupados sin leer",
                 build.milisegundos, resumen_etapas(build.tiempos),
                 build.equipo.nombre if build.equipo else build.equipo_texto or "?",
                 len(build.equipados), len(build.coleccion), len(build.arcanos), len(build.sin_identificar),
                 len(build.no_leidos))
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
              ("captura", "preparar", "detector", "reconocedor", "casado", "reparto", "huecos") if etapa in tiempos]
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


def leer_build(imagen, motor, casador: Casador, categorias: dict[int, str], tipos_hueco=None) -> Build:
    """OCR de la captura entera y reparto en equipo, mods y arcanos.

    El texto se busca en la captura reducida (`alto_de_deteccion`) y se lee a tamano
    real (los nombres de las tarjetas miden ~20 px a 1080p). Deja en `build.tiempos`
    lo que costo cada etapa. `tipos_hueco` (huecos_build.TiposDeHueco) dice que mods son
    auras o posturas y el tipo de cada equipo, para la validacion cruzada de los huecos;
    sin el se valida igual, pero solo con la categoria del equipo.
    """
    # La confianza se filtra ANTES de unir filas: un garabato de baja confianza pegado a
    # la cabecera ("UPGRADES/EXCALIBUR[30] 美") se la llevaba por delante al unirse.
    lineas = unir_filas([l for l in motor.leer_tira(imagen, alto_deteccion=alto_de_deteccion(imagen.shape[0]))
                         if l.confianza >= MINIMO_CONFIANZA])
    tiempos = dict(getattr(motor, "tiempos", None) or {})
    inicio = time.perf_counter()
    reconocidos = casar_lineas(lineas, casador, UMBRAL_MODS, subbloques=True)
    reconocidos += _casar_limpios(lineas, reconocidos, casador, categorias)
    reconocidos += _tarjetas_ampliadas(lineas, reconocidos, casador, categorias)
    reconocidos = _nombres_a_dos_lineas(lineas, reconocidos, casador, categorias)
    nombre_equipo, linea = cabecera(lineas)
    equipo = _casar_equipo(nombre_equipo, linea, casador, categorias)
    if equipo is None:
        # La barra leida como una letra y el principio tapado: "ASI NEKROS PRIME [30]".
        for l in lineas:
            if l.y >= imagen.shape[0] * 0.12:
                continue
            for texto in nombres_ante_el_rango(l.texto):
                equipo = _casar_equipo(texto, l, casador, categorias, entero=False)
                if equipo is not None:
                    nombre_equipo, linea = texto, l
                    break
            if equipo is not None:
                break
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
    build.lineas = lineas
    build.alto, build.ancho = int(imagen.shape[0]), int(imagen.shape[1])
    # Validacion cruzada: los huecos que se ven ocupados y de los que no salio ningun mod se
    # releen aparte y, si aun asi no se leen, se dicen (nunca se dejan vacios en silencio).
    repartido = time.perf_counter()
    try:
        from .huecos_build import completar_huecos

        completar_huecos(imagen, build, motor, casador, categorias, tipos_hueco, UMBRAL_MODS, limpiar_nombre_tarjeta)
    except ErrorMotorOCR:
        raise
    except Exception:  # noqa: BLE001 - la validacion nunca tumba la lectura
        log.exception("Fallo en la validacion cruzada de los huecos")
    build.idioma = idioma_de_cabecera(linea.texto) if linea is not None else ""
    try:
        # Un nombre que es parte de otro mas largo, en una tarjeta que puede estar tapada, no
        # se afirma: se relee y, si sigue sin saberse, sale como dudoso.
        from .huecos_build import apartar_dudosos

        apartar_dudosos(imagen, build, motor, casador, categorias, UMBRAL_MODS, limpiar_nombre_tarjeta)
    except ErrorMotorOCR:
        raise
    except Exception:  # noqa: BLE001 - la comprobacion nunca tumba la lectura
        log.exception("Fallo al comprobar los nombres que son parte de otro")
    tiempos["huecos"] = time.perf_counter() - repartido
    build.tiempos = tiempos
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
RE_CIRILICO_LEIDO = re.compile(r"[A-Z]b\b|[A-Za-z]b[A-Z]|[A-Z]b[il]\b|bI")


def parece_cirilico(lineas: list[Leido]) -> bool:
    """Si la pantalla parece cirilico leido con letras latinas (cuatro lineas o mas)."""
    return sum(1 for l in lineas if RE_CIRILICO_LEIDO.search(l.texto)) >= 4


def _casar_equipo(nombre_equipo: str, linea: Leido | None, casador: Casador,
                  categorias: dict[int, str], entero: bool | None = None) -> Reconocido | None:
    """El warframe o el arma que dice la cabecera (nunca un mod ni un arcano).

    Solo dos formas de acertar, las dos sin margen para inventar: lo leido ES el nombre de
    un equipo (letra por letra, sin contar espacios ni tildes), o se parece a uno solo con
    las reglas de `equipo_parecido`. El parecido general del casador (el de los mods) no
    vale aqui: con el principio del rotulo tapado daba "ENANT PRIME" por "Venka Prime".

    `entero` dice si el nombre se leyo con sus dos topes: la barra de la cabecera delante y
    el rango detras ("MEJORAS/ NEKROS [30]"). Sin ellos pudo quedar cortado, y un equipo
    que tiene hermanos de variante (Nekros / Nekros Prime, Bubonico / Bubonico Coda) no se
    identifica: "NEKROS" a secas puede ser un "NEKROS PRIME" al que le falta el final. Por
    defecto se deduce de la linea (que traiga la barra y el rango)."""
    if not nombre_equipo:
        return None
    if entero is None:
        entero = linea is not None and nombre_con_topes(linea.texto)
    caja = (linea.x, linea.y, linea.ancho, linea.alto) if linea is not None else (0, 0, 0, 0)
    intentos = _nombres_de_equipo(nombre_equipo)
    pelados = _intentos_pelados(intentos)
    # Lo sacado del rotulo de un arma de lich esta acotado por el lich: entero aunque el
    # rango no se haya leido ("CHAKKHURRKUVADEPOGONTMAHIFFNIVEAU4OLT").
    de_lich = set(nombres_de_arma_de_lich(nombre_equipo))
    for nombre in intentos:
        entero_i = entero or nombre in de_lich
        item_id, etiqueta, puntos = casador.casar(nombre, UMBRAL_MODS)
        if not item_id or categorias.get(item_id) in ("Mods", "Arcanes", None):
            continue
        if not _es_el_nombre(nombre, casador, item_id, con_espacios=not entero_i):
            continue
        # Sin los dos topes, o quitandole fichas sueltas, el nombre pudo quedar cortado: si
        # es el principio o el final del de otro equipo, no se sabe cual de los dos es.
        if (not entero_i or nombre in pelados) and _tiene_hermanos(item_id, casador, categorias):
            continue
        return Reconocido(nombre, item_id, etiqueta, 100.0, caja)
    # Nombre cortado por el juego con puntos suspensivos ("NISSAIA MUR TENET ARCA P... [40]":
    # el arma de lich con el nombre del lich delante no cabe en la cabecera): vale si lo que
    # queda es el principio de UN solo equipo del catalogo.
    for nombre in intentos:
        if "..." in nombre or "…" in nombre:
            hallado = _equipo_por_prefijo(nombre, casador, categorias)
            if hallado is not None:
                item_id, etiqueta = hallado
                return Reconocido(nombre, item_id, etiqueta, 97.0, caja)
    if not entero:
        return None  # sin topes solo vale el nombre exacto: nada de parecidos
    for nombre in intentos:
        hallado = equipo_parecido(nombre, casador, categorias)
        if hallado is None or (nombre in pelados and _tiene_hermanos(hallado[0], casador, categorias)):
            continue
        item_id, etiqueta, puntos = hallado
        return Reconocido(nombre, item_id, etiqueta, puntos, caja)
    return None


MINIMO_PREFIJO_EQUIPO = 8


def _equipo_por_prefijo(nombre: str, casador: Casador, categorias: dict[int, str]) -> tuple[int, str] | None:
    """(id, etiqueta) del unico equipo cuyo nombre empieza por lo leido antes de los puntos
    suspensivos; None si no hay ninguno o hay varios."""
    prefijo = normalizar(re.split(r"\.\.\.|…", nombre, maxsplit=1)[0]).replace(" ", "")
    if len(prefijo) < MINIMO_PREFIJO_EQUIPO:
        return None
    hallados: dict[int, str] = {}
    for clave, (item_id, etiqueta) in casador.candidatos.items():
        if categorias.get(item_id) in ("Mods", "Arcanes", None):
            continue
        if clave.replace(" ", "").startswith(prefijo):
            hallados.setdefault(item_id, etiqueta)
    if len(hallados) == 1:
        return next(iter(hallados.items()))
    return None


def _intentos_pelados(intentos: list[str]) -> set[str]:
    """Los intentos que salen de quitarle a otro una ficha suelta de delante (la barra mal
    leida) o de detras (el borde del corchete)."""
    pelados = set()
    partidos = [i.split() for i in intentos]
    for intento, palabras in zip(intentos, partidos):
        for otras in partidos:
            sobran = len(otras) - len(palabras)
            if sobran <= 0:
                continue
            # Solo fichas de una o dos letras: "UNRANKED" o "RANGO 30" no son fichas sueltas.
            if otras[sobran:] == palabras and all(len(f) <= 2 for f in otras[:sobran]):
                pelados.add(intento)
            elif otras[:len(palabras)] == palabras and all(len(f) <= 2 and not f.isdigit() for f in otras[len(palabras):]):
                pelados.add(intento)
    return pelados


# "UNRANKED HYDROID" (sin rango, va delante) y "OBERON PRIME RANGA ZERO": tambien cierran el nombre.
RE_SIN_TOPE_DE_RANGO = re.compile(rf"(?i)(?:UNRANKED|SIN\s*RANGO)\s|(?:{_PALABRA_RANGO})\s*Z[EÉ]RO\W*$")


def nombre_con_topes(texto_linea: str) -> bool:
    """Si la linea de la cabecera trae la barra (o los dos puntos) delante del nombre y el
    rango detras: entonces el nombre esta entero."""
    delante = bool(re.search(r"[/:]", texto_linea)) or es_cabecera(texto_linea) is not None
    detras = bool(RE_RANGO_CABECERA.search(texto_linea) or RE_RANGO_SIN_ABRIR.search(texto_linea)
                  or RE_RANGO_PEGADO.search(texto_linea) or RE_SIN_TOPE_DE_RANGO.search(texto_linea))
    return delante and detras


def _tiene_hermanos(item_id: int, casador: Casador, categorias: dict[int, str]) -> bool:
    """Si el nombre de este equipo es el principio o el final del de otro: Nekros y Nekros
    Prime, Bubonico y Bubonico Coda, pero tambien Bronco y Akbronco o Bo y Limbo. Leido sin
    sus dos topes, no se sabe cual de los dos es."""
    hechas = casador.__dict__.get("_con_hermanos")
    if hechas is None:
        de_equipo: dict[str, set[int]] = {}
        for clave, (iid, _etiqueta) in casador.candidatos.items():
            if categorias.get(iid) not in ("Mods", "Arcanes", None):
                de_equipo.setdefault(clave.replace(" ", ""), set()).add(iid)
        hechas = set()
        for compacta, ids in de_equipo.items():
            for corte in range(2, len(compacta)):
                for trozo in (compacta[:corte], compacta[-corte:]):
                    for otro in de_equipo.get(trozo, ()):
                        if otro not in ids:
                            hechas.add(otro)
        casador._con_hermanos = hechas
    return item_id in hechas


def _es_el_nombre(nombre: str, casador: Casador, item_id: int, con_espacios: bool = False) -> bool:
    """Si lo leido es, letra por letra, uno de los nombres de ese objeto. Los espacios no
    cuentan (el OCR los pone y los quita: "HAALV U", "NYXPRIME") salvo con `con_espacios`."""
    leido = normalizar(nombre)
    if not leido:
        return False
    if con_espacios:
        return casador.candidatos.get(leido, (None,))[0] == item_id
    return leido.replace(" ", "") in _compactas_por_id(casador).get(item_id, ())


def _compactas_por_id(casador: Casador) -> dict[int, set[str]]:
    hechas = casador.__dict__.get("_compactas_por_id")
    if hechas is None:
        hechas = {}
        for clave, valor in casador.candidatos.items():
            hechas.setdefault(valor[0], set()).add(clave.replace(" ", ""))
        casador._compactas_por_id = hechas
    return hechas


# Casado del equipo con alguna letra mal leida ("TNAROS" por "INAROS"): solo contra
# warframes, armas y companeros, y con reglas duras, porque un equipo equivocado con
# apariencia de seguro es lo peor que puede pasar (la 0.6.10 dio "Pride" por un "PRINE [30]"
# que era el final de "NEKROS PRIME [30]"):
# - Las palabras de variante ("prime", "umbra", "kuva", "coda"...) no son el nombre: se
#   apartan de lo leido y del catalogo, y tienen que coincidir exactamente. Un token que
#   se parece a una de ellas ("PRINE", "PRlME") cuenta como esa variante, nunca como nombre.
# - El nombre propio que queda tiene que tener letras suficientes, medir casi lo mismo y
#   diferir en una letra (dos si es largo).
# - Y ningun otro equipo puede quedar cerca: si lo hay, no se elige.
PALABRAS_VARIANTE = frozenset({
    "prime", "umbra", "wraith", "vandal", "prisma", "kuva", "tenet", "coda", "dex", "mk1", "mara", "rakta",
    "sancti", "secura", "synoid", "telos", "vaykor", "carmine", "ceti", "dual", "dobles", "doble", "twin",
    "gemelas", "gemelos", "duplas", "duplos", "doubles", "doppel", "jumelles", "jumeaux",
})
VARIANTE_DUDOSA = "?"  # no coincide con ninguna del catalogo: con ella no se identifica nada
MINIMO_LETRAS_EQUIPO = 6
LETRAS_NOMBRE_LARGO = 10
MARGEN_LETRAS_EQUIPO = 2


def _variante_de(palabra: str) -> str | None:
    """La palabra de variante que es `palabra`, tambien con una letra mal leida."""
    if palabra in PALABRAS_VARIANTE:
        return palabra
    if len(palabra) >= 4:
        cerca = [v for v in PALABRAS_VARIANTE
                 if len(v) >= 4 and abs(len(v) - len(palabra)) <= 1 and Levenshtein.distance(palabra, v) <= 1]
        if len(cerca) == 1:
            return cerca[0]
        if cerca:
            return VARIANTE_DUDOSA  # a una letra de dos variantes ("PRIMA": prime o prisma)
    return None


def _partes_de_equipo(clave: str, exacto: bool = False) -> tuple[frozenset[str], str]:
    """(variantes, nombre propio sin espacios) de un nombre normalizado. Con `exacto` (los
    nombres del catalogo) las variantes solo valen bien escritas y sueltas; en lo leido
    tambien con una letra cambiada o pegadas al nombre ("NYXPRIME")."""
    variantes, propio = set(), []
    for palabra in clave.split():
        if exacto:
            variante = palabra if palabra in PALABRAS_VARIANTE else None
        else:
            variante = _variante_de(palabra)
            if variante is None:
                for v in PALABRAS_VARIANTE:
                    if len(v) >= 4 and len(palabra) >= len(v) + 2 and (palabra.endswith(v) or palabra.startswith(v)):
                        variantes.add(v)
                        palabra = palabra[:-len(v)] if palabra.endswith(v) else palabra[len(v):]
                        break
        if variante:
            variantes.add(variante)
        else:
            propio.append(palabra)
    return frozenset(variantes), "".join(propio)


def _sin_prime(clave: str) -> tuple[bool, str]:
    palabras = clave.split()
    return "prime" in palabras, " ".join(p for p in palabras if p != "prime")


def _claves_de_equipo(casador: Casador, categorias: dict[int, str]) -> list[tuple[frozenset[str], str, int, str]]:
    """(variantes, nombre propio, id, etiqueta) de las claves del casador que son un equipo
    (se calculan una vez por casador)."""
    hechas = casador.__dict__.get("_claves_equipo")
    if hechas is None:
        hechas = []
        for clave, (item_id, etiqueta) in casador.candidatos.items():
            if categorias.get(item_id) in ("Mods", "Arcanes", None):
                continue
            variantes, propio = _partes_de_equipo(clave, exacto=True)
            if propio:
                hechas.append((variantes, propio, item_id, etiqueta))
        casador._claves_equipo = hechas
    return hechas


# Letras que el OCR confunde entre si por la forma: con ellas igualadas, "lVARA" es "IVARA".
_MISMA_FORMA = str.maketrans({"l": "i", "1": "i", "|": "i", "!": "i", "0": "o", "5": "s", "8": "b"})


def _misma_forma(propio: str) -> str:
    return propio.translate(_MISMA_FORMA)


def equipo_parecido(texto: str, casador: Casador, categorias: dict[int, str]) -> tuple[int, str, float] | None:
    """(id, etiqueta, puntos) del unico equipo que es `texto` con alguna letra mal leida, o
    None si no hay ninguno o no esta claro cual."""
    variantes, propio = _partes_de_equipo(normalizar(texto))
    if len(propio) < 3:
        return None
    # Lo mismo salvo letras de igual forma (I, l, 1; O, 0...): vale tambien en nombres cortos,
    # si solo hay un equipo asi.
    forma = _misma_forma(propio)
    iguales = {(iid, etiqueta) for v, p, iid, etiqueta in _claves_de_equipo(casador, categorias)
               if v == variantes and len(p) == len(propio) and _misma_forma(p) == forma}
    if len({iid for iid, _e in iguales}) == 1:
        iid, etiqueta = sorted(iguales)[0]
        return iid, etiqueta, 96.0
    if iguales or len(propio) < MINIMO_LETRAS_EQUIPO:
        return None
    permitido = 2 if len(propio) >= LETRAS_NOMBRE_LARGO else 1
    tope = permitido + MARGEN_LETRAS_EQUIPO
    cerca: dict[int, tuple[int, str]] = {}
    rivales: dict[int, int] = {}
    for variantes_clave, propio_clave, item_id, etiqueta in _claves_de_equipo(casador, categorias):
        if variantes_clave != variantes or abs(len(propio_clave) - len(propio)) > tope:
            continue
        distancia = Levenshtein.distance(propio, propio_clave, score_cutoff=tope)
        if distancia > tope:
            continue
        rivales[item_id] = min(distancia, rivales.get(item_id, distancia))
        if len(propio) != len(propio_clave) and (propio[0] != propio_clave[0] or propio[-1] != propio_clave[-1]
                                                  or abs(len(propio) - len(propio_clave)) > 1):
            # Una letra comida o repetida en medio vale; un nombre mas largo o mas corto por
            # una punta es otro nombre cortado ("A SPOROTHRIX", "NEKROSP").
            distancia = max(distancia, permitido + 1)
        if item_id not in cerca or distancia < cerca[item_id][0]:
            cerca[item_id] = (distancia, etiqueta)
    if not cerca:
        return None
    orden = sorted(cerca.items(), key=lambda par: par[1][0])
    item_id, (distancia, etiqueta) = orden[0]
    if distancia > permitido:
        return None
    if any(otro != item_id and d < distancia + MARGEN_LETRAS_EQUIPO for otro, d in rivales.items()):
        return None  # otro equipo casi igual de cerca: no se elige
    return item_id, etiqueta, 100.0 - 8.0 * distancia


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
    recortes = recortes_de_cabecera(lineas_pantalla, ancho, alto)
    try:
        # El reconocedor lee la linea entera de una vez y el resultado cambia con el
        # recorte (medido: con un recorte "RHINO PRIME", con otro "RNOPRIME"). Se
        # prueban unos pocos, de mas a menos probable, hasta que uno case.
        leer_tira = getattr(motor, "leer_tira", None) if getattr(imagen, "ndim", 0) == 3 else None
        for numero, (y0, y1, x0, x1) in enumerate(recortes):
            franja = imagen[y0:y1, x0:x1]
            try:
                leidos = leer(franja)
            except ErrorMotorOCR:
                return "", None
            nombre, equipo = _equipo_de_franja(leidos, casador, categorias)
            if equipo is not None:
                return nombre, equipo
            primero = primero or nombre
            # Nada: el jugador puede tener la interfaz del juego con otro tema de colores (el
            # nombre en rojo vivo sobre azul oscuro apenas tiene luz y el OCR lo pierde). Se
            # relee la franja convertida a "el canal mas fuerte de cada punto", que no
            # depende del color, tal cual y en negativo. Solo en los primeros recortes y solo
            # cuando la lectura normal de la franja ha fallado.
            if leer_tira is None or numero >= RECORTES_SIN_COLOR:
                continue
            for sin_color in franjas_sin_color(franja):
                try:
                    leidos = leer_tira(sin_color)
                except ErrorMotorOCR:
                    return primero, None
                nombre, equipo = _equipo_de_franja(leidos, casador, categorias)
                if equipo is not None:
                    return nombre, equipo
                primero = primero or nombre
    finally:
        if hasattr(motor, "tiempos"):
            motor.tiempos = tiempos  # los de la lectura grande son los que van al registro
    return primero, None


# Cuantos recortes de la cabecera se releen sin color (cada uno, dos lecturas mas).
RECORTES_SIN_COLOR = 2
# Lo que va tras la ultima barra de una linea, sin rango ni restos: "WESJORAS/TORXICAS DOBLESCOEN".
RE_TRAS_BARRA_SUELTA = re.compile(r"[/:]\s*([^/:]{3,})$")


# Lo que la barra de la cabecera deja cuando el OCR la lee como una letra.
_BARRA_LEIDA = "Il1|/YJ7!"


def nombres_ante_el_rango(texto: str) -> list[str]:
    """De "ASI NEKROS PRIME [30]" o "ASINEKRDS PRIME [30]" (lo que queda de "MEJORAS/ NEKROS
    PRIME [30]" con el principio tapado y la barra leida como una I), los textos que pueden
    ser el nombre: lo que va delante del rango, quitando por delante un resto de la palabra
    de la cabecera y de la barra. Quien llama solo los acepta si casan con un equipo."""
    m = RE_RANGO_CABECERA.search(texto)
    if m is None or re.search(r"[/:]", texto[:m.start()]):
        return []
    delante = texto[:m.start()].strip(" -–—_.,;'\"")
    if len(delante) < 4:
        return []
    salida = []
    mayus = unicodedata.normalize("NFKD", delante).upper()
    for corte in range(1, min(len(delante) - 3, MAXIMO_BASURA_CABECERA + 2)):
        resto_cabecera = re.sub(r"[^A-Z0-9|/!]", "", mayus[:corte])
        if not resto_cabecera:
            continue
        cola, barra = (resto_cabecera[:-1], resto_cabecera[-1]) if resto_cabecera[-1] in _BARRA_LEIDA else (resto_cabecera, "")
        es_resto = any(p.endswith(cola) for p in PALABRAS_CABECERA) if cola else bool(barra)
        if es_resto and (barra or delante[corte:corte + 1] == " "):
            nombre = delante[corte:].strip()
            if len(nombre) >= 4 and nombre not in salida:
                salida.append(nombre)
    return salida


def es_resto_de_cabecera(texto: str) -> bool:
    """Si la linea es lo que queda de la cabecera con el principio tapado y la barra leida
    como una letra: "ASI NEKROS PRIME [30]", "RASINEKROS PRIME [30]". Hacen falta dos letras
    o mas del final de la palabra ("AS" de "MEJORAS"), la barra y el rango entre corchetes."""
    m = RE_RANGO_CABECERA.search(texto)
    if m is None or not any(c in m.group(0) for c in "[(【（［"):
        m = RE_RANGO_SIN_ABRIR.search(texto)  # "...PRIME3O]": sin el corchete de abrir
    if m is None:
        return False
    mayus = re.sub(r"[^A-Z0-9|/!]", "", unicodedata.normalize("NFKD", texto[:m.start()]).upper())
    for corte in range(3, min(len(mayus) - 3, MAXIMO_BASURA_CABECERA + 2)):
        cola, barra = mayus[:corte - 1], mayus[corte - 1]
        if barra in _BARRA_LEIDA.upper() and any(p.endswith(cola) for p in PALABRAS_CABECERA):
            return True
    return False


def franjas_sin_color(franja):
    """La franja en gris "canal mas fuerte" (un rojo, un verde o un azul vivos quedan tan
    claros como un blanco) y su negativo, las dos en BGR como espera el motor."""
    import numpy as np

    fuerte = np.ascontiguousarray(franja.max(axis=2))
    return [np.dstack([fuerte] * 3), np.dstack([255 - fuerte] * 3)]


def _equipo_de_franja(leidos, casador: Casador, categorias: dict[int, str]) -> tuple[str, Reconocido | None]:
    """El equipo que dicen las lineas de una franja de cabecera: (texto del nombre, equipo).
    Sin equipo, el primer texto que parecia el nombre (para ensenarlo como "sin identificar")."""
    lineas = unir_filas([l for l in leidos if l.confianza >= MINIMO_CONFIANZA])
    nombre, linea = cabecera(lineas)
    candidatos = [(nombre, linea)] if nombre else []
    for l in lineas:
        m = RE_TRAS_BARRA.search(l.texto)
        if m:
            candidatos.append((m.group(1).strip(), l))
    # Ultimo recurso: lo que va tras la barra aunque la palabra de delante no se
    # reconozca y no haya rango. Solo vale si casa con un equipo del catalogo.
    dudosos = []
    for l in lineas:
        m = RE_TRAS_BARRA_SUELTA.search(l.texto.strip())
        if m and m.group(1).strip() not in [c[0] for c in candidatos]:
            dudosos.append((m.group(1).strip(), l))
        for texto in nombres_ante_el_rango(l.texto):
            if texto not in [c[0] for c in candidatos + dudosos]:
                dudosos.append((texto, l))
    for texto, l in candidatos:
        equipo = _casar_equipo(texto, l, casador, categorias)
        if equipo is not None:
            return texto, equipo
    for texto, l in dudosos:
        equipo = _casar_equipo(texto, l, casador, categorias, entero=False)
        if equipo is not None:
            return texto, equipo
    return (candidatos[0][0] if candidatos else ""), None


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

# Restos que el OCR pega a los nombres de las tarjetas: el rango de arriba ("16Y "), un
# borde o un destello leido como signo ("Caparazon de'Saxum"), y detras una ficha de una o
# dos letras o cifras que es el icono de polaridad o el borde de la tarjeta ("Saxum 1",
# "Saxum J", "Saxum !"). Con ellos el casado se quedaba en un 88 % ("parecido 88 %") o por
# debajo del umbral, y el mod desaparecia (captura real del usuario, Grendel Prime).
RE_SIGNOS_DENTRO = re.compile(r"[\'\"`´‘’“”|]")
RE_FICHA_DETRAS = re.compile(r"\s+[\dOIl|!J\]\)\[\(\-=]{1,2}$")
RE_FICHA_DELANTE = re.compile(r"^(?:[\dOIl|!J\]\)\[\(\-=]{1,3}\s+){1,2}(?=[^\W\d_])")


def limpiar_nombre_tarjeta(texto: str) -> list[str]:
    """Las variantes de lo leido en una tarjeta sin los restos que no son nombre, de la
    menos a la mas limpia (sin el texto original). Vacio si no hay nada que limpiar."""
    salida: list[str] = []
    texto = texto.strip()
    base = RE_RANGO_DELANTE.sub("", texto)

    def anadir(t: str, quitado_delante: bool) -> None:
        t = " ".join(t.split())
        # Quitar algo de delante y quedarse con una sola palabra es peligroso: "1 Fury" era
        # un "Primed Fury" tapado por la camara del streamer ("d Fury"), no un "Fury"
        # (captura real). Con dos palabras o mas el nombre que queda es el que es.
        if quitado_delante and len(t.split()) < 2:
            return
        if t and t != texto and t not in salida and len(re.sub(r"[^A-Za-zÀ-ɏ]", "", t)) >= 4:
            salida.append(t)

    anadir(base, base != texto)
    sin_signos = RE_SIGNOS_DENTRO.sub(" ", base)
    anadir(sin_signos, base != texto)
    sin_delante = RE_FICHA_DELANTE.sub("", sin_signos)
    anadir(sin_delante, sin_delante != texto and sin_delante != sin_signos or base != texto)
    sin_detras = RE_FICHA_DETRAS.sub("", sin_delante)
    anadir(sin_detras, sin_delante != sin_signos or base != texto)
    anadir(RE_FICHA_DETRAS.sub("", sin_detras), sin_delante != sin_signos or base != texto)
    return salida


def _casar_limpios(lineas: list[Leido], reconocidos: list[Reconocido], casador: Casador,
                   categorias: dict[int, str]) -> list[Reconocido]:
    """Segunda pasada sobre las lineas que no casaron: sin los restos del rango y los signos
    que el OCR pega al nombre (`limpiar_nombre_tarjeta`). Solo mods y arcanos, y con el
    mismo umbral que la primera pasada: no es relajar el casado, es casar lo mismo limpio."""
    cubiertas = [r.caja for r in reconocidos]

    def cubierta(l: Leido) -> bool:
        cx, cy = l.x + l.ancho / 2, l.y + l.alto / 2
        return any(x <= cx <= x + a and y <= cy <= y + h for x, y, a, h in cubiertas)

    salida = []
    for l in lineas:
        if cubierta(l) or _todo_mayusculas(l.texto) or _es_frase(RE_RANGO_DELANTE.sub("", l.texto.strip())):
            continue
        for intento in limpiar_nombre_tarjeta(l.texto):
            item_id, etiqueta, puntos = casador.casar(intento, UMBRAL_MODS)
            if item_id and categorias.get(item_id) in ("Mods", "Arcanes"):
                salida.append(Reconocido(l.texto, item_id, etiqueta, puntos, (l.x, l.y, l.ancho, l.alto)))
                break
    # Lo que caso con restos ("parecido 88 %" por "Caparazon de'Saxum 1"): si limpio es el
    # mismo mod con mas seguridad, se apunta la seguridad buena. El usuario desconfia de un
    # "parecido 88 %" en un mod que esta escrito tal cual en la pantalla.
    for r in reconocidos:
        if r.puntuacion >= 100 or categorias.get(r.item_id) not in ("Mods", "Arcanes"):
            continue
        for intento in limpiar_nombre_tarjeta(r.texto_ocr):
            item_id, _etiqueta, puntos = casador.casar(intento, UMBRAL_MODS)
            if item_id == r.item_id and puntos > r.puntuacion:
                r.puntuacion = puntos
                break
    return salida


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
        elif r.puntuacion >= 100 and _parece_descripcion(vecina.texto):
            # La vecina es la primera linea de la descripcion de la tarjeta ampliada
            # ("Sentinel prevents Status", "Almorir, revive"), no media palabra de un nombre:
            # el nombre exacto de arriba ("Negate", "Cordon", "Reactivar") vale tal cual.
            # Capturas reales de companeros con la tarjeta bajo el cursor: se tiraba el mod.
            salida.append(r)
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


def _parece_descripcion(texto: str) -> bool:
    """Una frase de descripcion y no un trozo de nombre: tres palabras o mas, o signos de
    puntuacion por dentro ("Almorir, revive")."""
    limpio = _media_linea(texto) or texto
    return len(limpio.split()) >= 3 or bool(re.search(r"[,.;:]\s*\S", limpio))


def _caja_de(*lineas_caja: Leido) -> tuple[int, int, int, int]:
    x0, y0 = min(l.x for l in lineas_caja), min(l.y for l in lineas_caja)
    x1 = max(l.x + l.ancho for l in lineas_caja)
    y1 = max(l.y + l.alto for l in lineas_caja)
    return x0, y0, x1 - x0, y1 - y0
