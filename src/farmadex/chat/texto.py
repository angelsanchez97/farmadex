"""Que objetos, rangos, sets, precios y agrietados hay en un texto de comercio.

Dos usos:
- `interpretar_enlace(texto)`: lo leido de UN enlace del chat ("[Arcane Grace]",
  "[Loki Prime Set]", "[Rubico Critacan]"), con parecidos por si el OCR falla una letra.
- `analizar_lista(texto)`: un mensaje copiado ("WTS [Loki Prime] set 100p | Arcane
  Grace R5 300p"); None si no parece una lista de venta.

Reglas (sin distinguir mayusculas, en ingles y en espanol, y con las palabras de los
otros idiomas del indice cuando son baratas de anadir):
- "set" antes o despues del nombre ("Set de Loki Prime", "[Loki Prime Set]",
  "[Valkyr Prime] SET") -> precio del set completo.
- rango explicito ("R5", "rank 5", "rango 5", "5/5") -> ese rango; "max", "maxed",
  "rango máximo" -> el maximo; "unranked", "sin rango" -> R0. Sin rango en un mod o un
  arcano se ensenan los dos: R0 y R maximo.
- agrietado ("Rubico Critacan", "Tiberon Manti-armacron"): arma + nombre del agrietado;
  las estadisticas salen del nombre (`agrietados.grados.descomponer_nombre`).
- lo que no casa con ningun objeto -> "no reconocido". Nunca se inventa.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..datos.items import normalizar
from .nombres import Objeto, Resolutor

# -- vocabulario -------------------------------------------------------------------------

_P = r"(?<![a-z0-9])"
_F = r"(?![a-z0-9])"
PALABRAS_VENTA = ("wts", "selling", "sell", "vendo", "vendiendo", "vende", "venta", "vends", "vend",
                  "verkaufe", "verkauf", "vk", "sprzedam", "vendesi", "vds", "wtt")
PALABRAS_COMPRA = ("wtb", "buying", "compro", "compra", "achete", "kaufe", "kupie")
RE_VENTA = re.compile(_P + r"(?:" + "|".join(PALABRAS_VENTA) + r"|s>|h>)" + _F)
RE_COMPRA = re.compile(_P + r"(?:" + "|".join(PALABRAS_COMPRA) + r"|b>)" + _F)
RE_RANGO = re.compile(_P + r"(?:r|rank|rango|rang|rg|lvl|nivel|niveau|stufe|ranga|rk)\s*[:.]?\s*(\d{1,2})" + _F)
RE_RANGO_FRACCION = re.compile(r"(?<![\d/])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])")
RE_MAX = re.compile(_P + r"(?:max(?:ed|xed|imo|ima|imizad[oa]|imise|imiert|ymalny)?|maxi|full\s*rank|r\s*max"
                    r"|rango\s*max(?:imo)?|rank\s*max|max\s*rank|max\s*rango)" + _F)
RE_CERO = re.compile(_P + r"(?:unranked|unrank|sin\s*rango|sin\s*subir|ohne\s*rang|non\s*classe)" + _F)
RE_SET = re.compile(_P + r"(?:sets?|conjuntos?|ensembles?|satz|zestaw|komplett|completos?)" + _F)
# Cabecera "PRIME SETS: Banshee, Braton...": los nombres de detras son sets prime.
RE_PRIME_SETS = re.compile(_P + r"(?:prime\s*sets|sets\s*(?:de\s*)?primes?)" + _F)
# Precio con unidad ("100p", "100 plat", "140:platinum:", "3k") o numero suelto justo tras un enlace.
_UNIDAD = r"(?:p|pl|plat|plats|platinum|platino|platine|platin|platyna|:platinum:)"
RE_PRECIO = re.compile(_P + r"(\d{1,5}(?:[.,]\d{1,3})?)\s*(k)?\s*" + _UNIDAD + _F + r"|"
                       + _P + r"(\d{1,3}(?:[.,]\d)?)\s*k" + _F)
RE_NUMERO_INICIAL = re.compile(r"^\s*[:=\-]?\s*(\d{1,5}(?:[.,]\d)?)\s*(k)?" + _F)
RE_ENLACE = re.compile(r"\[([^\[\]]{2,70})\]")
RE_HORA = re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s*$")
RE_CABECERA_CHAT = re.compile(r"^\s*(?:\[\d{1,2}:\d{2}(?::\d{2})?\]\s*)?([^\s:\[\]]{2,24})\s*:\s+")
RE_SEPARADOR = re.compile(r"\s*(?:[|,;\n•]|/(?!\d)|\s-\s|\s+(?:and|y|e|et|und|i)\s+)\s*")
RE_CANTIDAD = re.compile(_P + r"(?:x\s*\d{1,3}|\d{1,3}\s*x)" + _F)
RELLENO_LISTA = frozenset("""
pm me dm msg mp md w each ea cu c u cada uno una unos all todo todos cheap barato baratos baratas
offer offers oferta ofertas obo price prices precio precios pls plz please por favor for a an the
my mi mis only solo just have tengo also tambien and y or o with con pc ps xbox switch h b
ask pregunta preguntar negociable neg nego cualquiera any priced pro poner
""".split())


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def _bajo(texto: str) -> str:
    """Minusculas y sin tildes, conservando signos (corchetes, dos puntos) para las reglas."""
    return _sin_tildes(texto or "").lower()


# -- resultado ---------------------------------------------------------------------------


@dataclass
class Riven:
    arma: str  # nombre en ingles del arma ("Rubico")
    nombre: str  # "Critacan", "Manti-armacron"
    estadisticas: list[str]  # slugs de atributo de warframe.market (mejores primero)


@dataclass
class Entrada:
    texto: str  # tal como estaba escrito
    objeto: Objeto | None = None
    slug: str | None = None  # el que se consulta en el snapshot (el del set si toca)
    es_set: bool = False
    rango: int | None = None  # pedido de forma explicita
    rango_max: bool = False  # pidio "max"/"maxed"
    precio_pedido: int | None = None
    riven: Riven | None = None
    enlace: bool = False  # venia entre corchetes

    @property
    def reconocido(self) -> bool:
        return self.objeto is not None or self.riven is not None

    def nombre(self) -> str:
        if self.riven:
            return f"{self.riven.arma} {self.riven.nombre}"
        if self.objeto:
            return self.objeto.nombre()
        return self.texto.strip()


@dataclass
class Modificadores:
    rango: int | None = None
    rango_max: bool = False
    es_set: bool = False
    precio: int | None = None
    usados: list[tuple[int, int]] = field(default_factory=list)

    def vacio(self) -> bool:
        return self.rango is None and not self.rango_max and not self.es_set


def _a_platino(numero: str, k: str | None) -> int | None:
    try:
        valor = float(numero.replace(",", "."))
    except ValueError:
        return None
    if k:
        valor *= 1000
    return int(round(valor)) if 0 < valor < 1_000_000 else None


def modificadores(texto: str) -> Modificadores:
    """Rango, set y precio escritos en un trozo de texto (ya en minusculas y sin tildes)."""
    m = Modificadores()
    for r in RE_RANGO.finditer(texto):
        m.rango = int(r.group(1))
        m.usados.append(r.span())
    if m.rango is None:
        for r in RE_RANGO_FRACCION.finditer(texto):
            a, b = int(r.group(1)), int(r.group(2))
            if 0 <= a <= b <= 10:
                m.rango = a
                m.usados.append(r.span())
    for r in RE_MAX.finditer(texto):
        m.rango_max = True
        m.usados.append(r.span())
    for r in RE_CERO.finditer(texto):
        if m.rango is None:
            m.rango = 0
        m.usados.append(r.span())
    for r in RE_SET.finditer(texto):
        m.es_set = True
        m.usados.append(r.span())
    for r in RE_PRECIO.finditer(texto):
        if m.precio is None:
            m.precio = _a_platino(r.group(1) or r.group(3), r.group(2) or ("k" if r.group(3) else None))
        m.usados.append(r.span())
    if m.rango_max and m.rango == 0:
        m.rango = None
    return m


def _quitar(texto: str, tramos: list[tuple[int, int]]) -> str:
    trozos, previo = [], 0
    for a, b in sorted(tramos):
        if a < previo:
            a = previo
        trozos.append(texto[previo:a])
        previo = max(previo, b)
    trozos.append(texto[previo:])
    return " ".join("".join(trozos).split())


# -- un nombre -----------------------------------------------------------------------------


def _riven(texto: str, res: Resolutor, difuso: bool = False) -> Riven | None:
    """'Rubico Critacan' / 'Tiberon Manti-armacron' -> arma + estadisticas; None si no lo es."""
    from ..agrietados.grados import descomponer_nombre

    palabras = normalizar(texto).split()
    if len(palabras) < 2:
        return None
    arma = res.arma_al_principio(palabras)
    if arma is None and difuso:
        arma = res.arma_parecida(palabras)
    if arma is None:
        return None
    nombre_arma, largo = arma
    resto = palabras[largo:]
    # "Rubico Prime Critacan": el agrietado es del arma base.
    while resto and resto[0] in ("prime", "vandal", "wraith", "prisma", "mk1", "kuva", "tenet", "coda"):
        resto = resto[1:]
    # El nombre es una palabra, a veces con guion ("manti armacron" tras normalizar).
    if not resto or len(resto) > 2:
        return None
    stats = descomponer_nombre("".join(resto))
    if not stats:
        return None
    # Como estaba escrito: los ultimos trozos del original que suman esas palabras.
    tokens = texto.split()
    cola, cuenta = [], 0
    while tokens and cuenta < len(resto):
        token = tokens.pop()
        cola.insert(0, token)
        cuenta += len(normalizar(token).split())
    bonito = " ".join(cola).strip("[]()") if cuenta == len(resto) else "-".join(resto)
    return Riven(nombre_arma, bonito[:1].upper() + bonito[1:], stats)


def _con_set(entrada: Entrada, res: Resolutor) -> None:
    obj = entrada.objeto
    if obj is None:
        return
    slug_set = res.slug_de_set(obj)
    if entrada.es_set:
        entrada.slug = slug_set  # sin set conocido: None -> "sin datos", nunca el de la pieza
    else:
        entrada.slug = obj.slug
        if obj.slug and obj.slug.endswith("_set"):
            entrada.es_set = True  # "Loki Prime" en el mercado ES el set


def interpretar(nombre: str, mods: Modificadores, res: Resolutor, difuso: bool = False,
                texto: str | None = None, enlace: bool = False) -> Entrada:
    """Una entrada a partir del nombre (sin modificadores) y lo que se dijo alrededor."""
    entrada = Entrada(texto=texto if texto is not None else nombre, rango=mods.rango,
                      rango_max=mods.rango_max, es_set=mods.es_set, precio_pedido=mods.precio, enlace=enlace)
    limpio = nombre.strip()
    if not limpio:
        return entrada
    obj = res.buscar(limpio)
    if obj is None:
        # "[Loki Prime Set]": la palabra set dentro del propio nombre.
        dentro = modificadores(_bajo(limpio))
        if not dentro.vacio():
            sin = _quitar(_bajo(limpio), dentro.usados)
            obj = res.buscar(sin) if sin else None
            if obj is not None:
                entrada.es_set = entrada.es_set or dentro.es_set
                if dentro.rango is not None and entrada.rango is None:
                    entrada.rango = dentro.rango
                entrada.rango_max = entrada.rango_max or dentro.rango_max
    if obj is None:
        riven = _riven(limpio, res, difuso)
        if riven is not None:
            entrada.riven = riven
            entrada.es_set = False
            entrada.rango = None
            entrada.rango_max = False
            return entrada
    if obj is None and difuso:
        obj = res.buscar_difuso(limpio)
    entrada.objeto = obj
    _con_set(entrada, res)
    if obj is not None and not obj.es_mod_o_arcano:
        entrada.rango, entrada.rango_max = None, False
    return entrada


def interpretar_enlace(texto_ocr: str, res: Resolutor) -> Entrada | None:
    """Lo leido de un enlace del chat -> entrada reconocida, o None si no casa con nada."""
    texto = (texto_ocr or "").strip()
    dentro = RE_ENLACE.search(texto)
    if dentro:
        texto = dentro.group(1)
    texto = texto.strip(" []|(){}")
    if len(texto) < 2:
        return None
    # El OCR lee a veces el corchete como "l", "1", "I", "J" o "r": se prueba tal cual y,
    # si no casa, sin esa letra en los extremos ("Kohm Arai-lexidexl", "lSupra Vandal").
    pruebas = [texto]
    sin_extremos = texto
    if sin_extremos[-1:] in ("l", "1", "I", "J", "|"):
        sin_extremos = sin_extremos[:-1]
    if sin_extremos[:1] in ("l", "1", "I", "J", "|", "r") and len(sin_extremos) > 3:
        sin_extremos = sin_extremos[1:]
    if sin_extremos != texto:
        pruebas.append(sin_extremos.strip())
    for difuso in (False, True):
        for prueba in pruebas:
            entrada = interpretar(prueba, Modificadores(), res, difuso=difuso, texto=prueba, enlace=True)
            if entrada.reconocido:
                return entrada
    return None


# -- listas ---------------------------------------------------------------------------------


def es_lista_de_venta(texto: str, entradas: list[Entrada]) -> bool:
    bajo = _bajo(texto)
    venta = bool(RE_VENTA.search(bajo))
    if venta and entradas:
        return True
    if RE_COMPRA.search(bajo) and not venta:
        return False
    con_precio = [e for e in entradas if e.precio_pedido is not None and (e.reconocido or e.enlace)]
    return len([e for e in entradas if e.reconocido]) >= 2 and len(con_precio) >= 1


def _linea_sin_cabecera(linea: str) -> str:
    """Quita "[15:00] Usuario: " de una linea copiada del chat."""
    cab = RE_CABECERA_CHAT.match(linea)
    if cab and not RE_VENTA.fullmatch(_bajo(cab.group(1))):
        return linea[cab.end():]
    return linea


def _entradas_con_corchetes(linea: str, res: Resolutor) -> list[Entrada]:
    bajo = _bajo(linea)
    enlaces = [m for m in RE_ENLACE.finditer(linea) if not RE_HORA.match(m.group(1))]
    if not enlaces:
        return []
    # Lo de delante del primer enlace vale para todos ("WTS Maxed ... [A][B]", "PRIME SETS: [A]").
    cabecera = modificadores(bajo[: enlaces[0].start()])
    cabecera.precio = None
    trozos_antes: list[str] = [""] * len(enlaces)
    trozos_despues: list[str] = [""] * len(enlaces)
    for i, m in enumerate(enlaces):
        fin = enlaces[i + 1].start() if i + 1 < len(enlaces) else len(linea)
        hueco = bajo[m.end():fin]
        if i + 1 == len(enlaces):
            trozos_despues[i] = hueco
            continue
        # El hueco entre dos enlaces se reparte en el primer precio o separador: lo de antes
        # es del enlace anterior ("140p") y lo de despues del siguiente ("r0 [Arcane...]").
        corte = None
        precio = RE_PRECIO.search(hueco) or RE_NUMERO_INICIAL.search(hueco)
        separador = RE_SEPARADOR.search(hueco)
        if precio:
            corte = precio.end()
        if separador and (corte is None or separador.start() < corte):
            corte = separador.end() if corte is None else corte
        if corte is None:
            corte = len(hueco) if not RE_RANGO.search(hueco) and not RE_SET.search(hueco) else 0
            # "[Valkyr Prime] SET [Otra]": set pegado detras es del anterior.
            if RE_SET.match(hueco.strip()):
                corte = len(hueco)
        trozos_despues[i] = hueco[:corte]
        trozos_antes[i + 1] = hueco[corte:]
    salida = []
    for i, m in enumerate(enlaces):
        nombre = m.group(1)
        mods = modificadores(trozos_antes[i] + " " + trozos_despues[i])
        inicial = RE_NUMERO_INICIAL.match(trozos_despues[i])
        if mods.precio is None and inicial:
            mods.precio = _a_platino(inicial.group(1), inicial.group(2))
        if mods.rango is None and not mods.rango_max:
            mods.rango, mods.rango_max = cabecera.rango, cabecera.rango_max
        mods.es_set = mods.es_set or cabecera.es_set
        salida.append(interpretar(nombre, mods, res, difuso=True, texto=m.group(0), enlace=True))
    return salida


def _entradas_sin_corchetes(linea: str, res: Resolutor, prime_sets: bool) -> list[Entrada]:
    bajo = _bajo(linea)
    # Tras cada precio empieza otro objeto ("Loki Prime set 100p Arcane Grace R5 300p").
    bajo = RE_PRECIO.sub(lambda m: m.group(0) + " | ", bajo)
    bajo = RE_PRIME_SETS.sub(" ", bajo) if prime_sets else bajo
    salida = []
    for trozo in RE_SEPARADOR.split(bajo):
        trozo = trozo.strip(" :>-*.!")
        if not trozo:
            continue
        mods = modificadores(trozo)
        resto = _quitar(trozo, mods.usados + [m.span() for m in RE_VENTA.finditer(trozo)]
                        + [m.span() for m in RE_COMPRA.finditer(trozo)] + [m.span() for m in RE_CANTIDAD.finditer(trozo)])
        palabras = [p for p in normalizar(resto).split() if p not in RELLENO_LISTA and not p.isdigit()]
        if not palabras:
            continue
        nombre = " ".join(palabras)
        entrada = Entrada(texto=nombre)
        if prime_sets and "prime" not in palabras:
            # "PRIME SETS: Banshee": primero el set prime; "Banshee" a secas no se vende.
            mods_set = Modificadores(mods.rango, mods.rango_max, True, mods.precio)
            entrada = interpretar(nombre + " prime", mods_set, res, difuso=True, texto=nombre)
            if not entrada.slug:
                entrada = Entrada(texto=nombre)
        if not entrada.reconocido:
            entrada = interpretar(nombre, mods, res, difuso=False, texto=nombre)
        if not entrada.reconocido and len(palabras) <= 6:
            entrada = interpretar(nombre, mods, res, difuso=True, texto=nombre)
        if entrada.reconocido:
            salida.append(entrada)
            continue
        # Varias cosas sin separar: se buscan nombres exactos dentro, de izquierda a derecha.
        encontrados = _nombres_dentro(palabras, mods, res)
        if encontrados:
            salida.extend(encontrados)
        elif len(palabras) <= 5 and sum(len(p) for p in palabras) >= 3:
            salida.append(entrada)  # parece un objeto, pero no se sabe cual: "no reconocido"
    return salida


def _nombres_dentro(palabras: list[str], mods: Modificadores, res: Resolutor) -> list[Entrada]:
    salida, i = [], 0
    while i < len(palabras):
        for largo in range(min(6, len(palabras) - i), 0, -1):
            trozo = " ".join(palabras[i:i + largo])
            if largo == 1 and len(trozo) < 5:
                continue
            obj = res.buscar(trozo)
            if obj is not None and obj.slug:
                salida.append(interpretar(trozo, mods, res, texto=trozo))
                i += largo
                break
        else:
            i += 1
    return salida


LARGO_MAXIMO = 4000


def analizar_lista(texto: str, res: Resolutor) -> list[Entrada] | None:
    """Entradas de una lista de venta copiada; None si el texto no parece una."""
    if not texto or len(texto) > LARGO_MAXIMO:
        return None
    entradas: list[Entrada] = []
    prime_sets = bool(RE_PRIME_SETS.search(_bajo(texto)))
    for linea in texto.splitlines():
        linea = _linea_sin_cabecera(linea)
        if not linea.strip():
            continue
        con = _entradas_con_corchetes(linea, res)
        entradas.extend(con if con else _entradas_sin_corchetes(linea, res, prime_sets))
    if not es_lista_de_venta(texto, entradas):
        return None
    return entradas
