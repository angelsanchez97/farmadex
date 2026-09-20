"""Lectura por OCR de la pantalla Perfil > Equipamiento del propio jugador.

Lo que se ve en las capturas reales (2560x1440, juego en espanol), de arriba abajo:

1. Nombre de cuenta y pestanas (PERFIL, EQUIPAMIENTO, ESTADISTICAS...).
2. Fila "MAS USADO": nueve objetos con su porcentaje de uso. Repiten lo de abajo
   y se descartan: todo lo que quede por encima de la barra de categoria se ignora.
3. Barra de categoria: "COMPLETADO 108/116", el nombre de la categoria en grande
   (WARFRAME, PRIMARIA, SECUNDARIA...) y "ORDENAR POR: NOMBRE". El contador es la
   verdad contra la que se comprueba el recuento por OCR.
4. Rejilla de 8 columnas de tarjetas. Bajo el nombre de las dominadas hay una
   segunda linea, "RANGO MAXIMO"; las no dominadas no llevan segunda linea y su
   nombre queda un poco mas abajo, centrado en la placa.

La senal de "dominado" es por tanto un TEXTO (la linea de rango), no un icono ni
un color, y el OCR la lee sin problema. Regla de honestidad: DOMINADO solo con
esa linea (o "RANGO n" igual al tope del catalogo); NO_DOMINADO cuando falta la
linea y la barra de categoria se ha localizado (si no, la fila MAS USADO podria
colarse y se deja en DESCONOCIDO); DESCONOCIDO ante cualquier duda.

Solo se procesan pixeles ya capturados: este modulo no toca el juego.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ..datos.items import normalizar
from ..perfil import maestria
from ..registro_log import obtener
from .ocr import Casador, Leido, MotorOCR, _caja_union, agrupar_bloques, unir_filas

log = obtener("perfil_ocr")

# Segunda linea de la tarjeta: "RANGO MAXIMO" (dominado) o "RANGO 14" (a medias).
RE_LINEA_RANGO = re.compile(
    r"^(?:rango|rank|nivel|level|lvl|r)\s*[:.]?\s*(?:(m[aá]x(?:imo|ima|\.)?|max\s*rank|maximum)|(\d{1,2}))"
    r"(?:\s*/\s*(\d{1,2}))?$",
    re.IGNORECASE,
)
# Cifra suelta ("30", "30/30") por si alguna pantalla la pinta sin etiqueta.
RE_CIFRA = re.compile(r"^(\d{1,2})(?:\s*/\s*(\d{1,2}))?$")
# Contador de la barra de categoria: "108/116".
RE_CONTADOR = re.compile(r"^(\d{1,3})\s*/\s*(\d{1,3})$")
ETIQUETAS_COMPLETADO = ("completado", "completed", "completo")
PALABRAS_DOMINADO = {"dominado", "dominada", "mastered", "rango maximo", "max rank"}
# Cabecera del perfil: "Rango de maestria 21" / "Mastery Rank 21" / "MR 21".
RE_RANGO_MAESTRIA = re.compile(
    r"(?:rango\s*de\s*maestr[ií]a|mastery\s*rank|\bMR)\s*[:.]?\s*(\d{1,2})\b", re.IGNORECASE
)
# El OCR a veces pega las palabras ("RANGODEMAESTRIA"): los espacios son opcionales.
RE_ETIQUETA_MAESTRIA = re.compile(r"rango\s*de\s*maestr[ií]?a|mastery\s*rank", re.IGNORECASE)
# En la portada la cifra del rango va dentro de un emblema que el OCR no lee; el TITULO
# si se lee ("MAESTRO VERDADERO", "SIGUIENTE RANGO: LEGENDARIO 1") y equivale a un rango.
RE_LEGENDARIO = re.compile(r"legendari[o0a]\s*(\d{1,2})|legendary\s*(\d{1,2})", re.IGNORECASE)
RE_SIGUIENTE = re.compile(r"siguiente\s*rango|next\s*rank", re.IGNORECASE)
TITULOS_BASE = {  # palabra del titulo -> rango de bronce; plata +1, oro +2
    "iniciado": 0, "initiate": 0, "novato": 3, "novice": 3, "discipulo": 6, "disciple": 6,
    "buscador": 9, "seeker": 9, "cazador": 12, "hunter": 12, "aguila": 15, "eagle": 15,
    "tigre": 18, "tiger": 18, "dragon": 21, "sabio": 24, "sage": 24, "maestro": 27, "master": 27,
}
TITULOS_GRADO = {"plata": 1, "plateado": 1, "silver": 1, "oro": 2, "dorado": 2, "gold": 2}
# Texto que sale en las capturas y no es del juego ni del catalogo: medidor de rendimiento
# (RTX, FPS, MHz), avisos de Windows al capturar, el recuadro al pasar el raton, el chat.
RE_RUIDO = re.compile(
    r"\bfps\b|\d\s*ms\b|\bmhz\b|\brtx\b|ryzen|\bram\b|vram|\d\s*mb\b|\bgpu\b|recortes|portapapeles|"
    r"capturas? de pantalla|marcado y uso|^usado\b|^px\b|asesinatos|asistencias|^escribe /|^frame rate",
    re.IGNORECASE,
)

# Nombre de la categoria en la barra -> clave interna. Espanol e ingles.
CATEGORIAS_PANTALLA = {
    "warframe": "warframes", "warframes": "warframes",
    "primaria": "primarias", "primarias": "primarias", "primary": "primarias",
    "secundaria": "secundarias", "secundarias": "secundarias", "secondary": "secundarias",
    "cuerpo a cuerpo": "cuerpo_a_cuerpo", "melee": "cuerpo_a_cuerpo",
    "robotico": "roboticos", "roboticos": "roboticos", "robotic": "roboticos", "robotics": "roboticos",
    "companero": "companeros", "companeros": "companeros", "companion": "companeros",
    "companions": "companeros",
    "vehiculo": "vehiculos", "vehiculos": "vehiculos", "vehicle": "vehiculos", "vehicles": "vehiculos",
    "archcanon": "archcanones", "archcanones": "archcanones", "archgun": "archcanones",
    "arch gun": "archcanones",
    "archmelee": "archmelee", "arch melee": "archmelee",
    "amp": "amps", "amps": "amps",
}

_LETRAS_A_CIFRAS = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1",
                                  "|": "1", "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})

# Por debajo de esta confianza del OCR la linea de rango no decide nada.
CONFIANZA_MINIMA_RANGO = 0.60
# La linea de rango va justo debajo del nombre: entre -0.3 y 2.5 alturas de hueco.
HUECO_MAXIMO = 2.5

CATEGORIAS_EQUIPAMIENTO = tuple(sorted(maestria.CATEGORIAS_MASTERIZABLES)) + ("Misc",)


def casador_equipamiento(indice: sqlite3.Connection) -> Casador:
    """Casador restringido a lo que da maestria: sin componentes, mods ni recursos."""
    return Casador(indice, CATEGORIAS_EQUIPAMIENTO, filtro=maestria.es_masterizable)


@dataclass
class Tarjeta:
    texto_ocr: str
    item_id: int
    unique_name: str
    nombre: str
    puntuacion: float  # parecido del nombre con el catalogo (0-100)
    caja: tuple[int, int, int, int]
    tope: int | None  # 30 o 40 segun el catalogo; None si el objeto no da maestria
    rango: int | None = None
    confianza_rango: float = 0.0
    estado: str = maestria.DESCONOCIDO
    motivo: str = ""

    @property
    def dominada(self) -> bool:
        return self.estado == maestria.DOMINADO


@dataclass
class PaginaLeida:
    tarjetas: list[Tarjeta] = field(default_factory=list)
    sin_casar: list[str] = field(default_factory=list)
    rango_maestria: int | None = None
    categoria: str | None = None  # clave de CATEGORIAS_PANTALLA leida en la barra
    completado: tuple[int, int] | None = None  # (dominados, total) segun el juego
    cabecera_en_y: int | None = None  # borde inferior de la barra de categoria
    lineas: int = 0

    @property
    def dominadas(self) -> list[Tarjeta]:
        return [t for t in self.tarjetas if t.estado == maestria.DOMINADO]

    @property
    def a_medias(self) -> list[Tarjeta]:
        return [t for t in self.tarjetas if t.estado == maestria.A_MEDIAS]

    @property
    def no_dominadas(self) -> list[Tarjeta]:
        return [t for t in self.tarjetas if t.estado == maestria.NO_DOMINADO]

    @property
    def desconocidas(self) -> list[Tarjeta]:
        return [t for t in self.tarjetas if t.estado == maestria.DESCONOCIDO]


@dataclass
class _LineaRango:
    linea: Leido
    rango: int | None  # None cuando la linea dice "RANGO MAXIMO"
    tope_declarado: int | None
    maximo: bool = False
    ilegible: bool = False  # "RANGO MI": hay linea de rango pero no se lee que dice


# --- lectura -------------------------------------------------------------------------


def leer_pagina(
    imagen,
    motor: MotorOCR,
    casador: Casador,
    indice: sqlite3.Connection,
    umbral: int = 82,
    minimo_confianza: float = 0.4,
    escala: float = 1.0,
) -> PaginaLeida:
    """Lee una captura de Perfil > Equipamiento y devuelve sus tarjetas con estado.

    `escala` > 1 reescala la captura antes del OCR para pantallas pequenas
    (a 1440p no hace falta; ver la medida en los tests).
    """
    if imagen is None:
        return PaginaLeida()
    if escala != 1.0:
        imagen = _reescalar(imagen, escala)
    lineas = [l for l in unir_filas(motor.leer(imagen)) if l.confianza >= minimo_confianza]
    if escala != 1.0:
        for l in lineas:
            l.x, l.y = int(l.x / escala), int(l.y / escala)
            l.ancho, l.alto = int(l.ancho / escala), int(l.alto / escala)
    return interpretar_lineas(lineas, casador, indice, umbral)


def interpretar_lineas(
    lineas: list[Leido], casador: Casador, indice: sqlite3.Connection, umbral: int = 82
) -> PaginaLeida:
    """Parte pura: de las lineas leidas a las tarjetas. Probable sin OCR."""
    pagina = PaginaLeida(lineas=len(lineas))
    pagina.rango_maestria = leer_rango_maestria(lineas)
    leer_cabecera(lineas, pagina)
    if pagina.cabecera_en_y is not None:
        # Todo lo que queda por encima de la barra (MAS USADO, pestanas) no es la rejilla.
        lineas = [l for l in lineas if l.y >= pagina.cabecera_en_y]

    textos, rangos = separar_lineas_de_rango(lineas)
    fichas: dict[int, tuple] = {}
    for bloque in agrupar_bloques(textos):
        if len(bloque) > 1:
            texto = " ".join(l.texto for l in bloque)
            item_id, nombre, puntos = _casar(casador, texto, umbral, min(l.confianza for l in bloque))
            if item_id:
                _anadir(fichas, item_id, texto, nombre, puntos, _caja_union(bloque), indice)
                continue
        for linea in bloque:
            item_id, nombre, puntos = _casar(casador, linea.texto, umbral, linea.confianza)
            if item_id:
                _anadir(fichas, item_id, linea.texto, nombre, puntos,
                        (linea.x, linea.y, linea.ancho, linea.alto), indice)
            elif not _es_texto_de_cabecera(linea.texto) and not RE_RUIDO.search(linea.texto):
                pagina.sin_casar.append(linea.texto)

    pagina.tarjetas = [Tarjeta(*valores) for valores in fichas.values()]
    emparejar_rangos(pagina.tarjetas, rangos)
    for t in pagina.tarjetas:
        _decidir(t, pagina.cabecera_en_y is not None)
    pagina.tarjetas.sort(key=lambda t: (t.caja[1], t.caja[0]))
    return pagina


def leer_cabecera(lineas: list[Leido], pagina: PaginaLeida) -> None:
    """Localiza la barra de categoria: contador COMPLETADO x/y y nombre de la categoria."""
    etiqueta = None
    for l in lineas:
        clave = normalizar(l.texto)
        if any(fuzz.ratio(clave, e) >= 80 for e in ETIQUETAS_COMPLETADO):
            etiqueta = l
            break
    contador = None
    if etiqueta is not None:
        banda = [l for l in lineas if abs((l.y + l.alto / 2) - (etiqueta.y + etiqueta.alto / 2)) <= 2 * etiqueta.alto]
        for l in sorted(banda, key=lambda l: abs(l.x - (etiqueta.x + etiqueta.ancho))):
            m = RE_CONTADOR.match(l.texto.translate(_LETRAS_A_CIFRAS).replace(" ", ""))
            if m and int(m.group(1)) <= int(m.group(2)):
                contador = (int(m.group(1)), int(m.group(2)))
                break
    else:
        # Sin etiqueta legible, vale un "x/y" solo si hay un nombre de categoria a su altura.
        banda = []
        for l in lineas:
            m = RE_CONTADOR.match(l.texto.replace(" ", ""))
            if m and int(m.group(1)) <= int(m.group(2)) and int(m.group(2)) >= 5:
                banda = [o for o in lineas if abs((o.y + o.alto / 2) - (l.y + l.alto / 2)) <= 2 * l.alto]
                if any(_categoria_de(o.texto) for o in banda):
                    etiqueta = l
                    contador = (int(m.group(1)), int(m.group(2)))
                    break
    if etiqueta is None:
        return
    pagina.completado = contador
    pagina.cabecera_en_y = max(l.y + l.alto for l in banda) if banda else etiqueta.y + etiqueta.alto
    for l in banda:
        categoria = _categoria_de(l.texto)
        if categoria:
            pagina.categoria = categoria
            break


def _casar(casador: Casador, texto: str, umbral: int, confianza: float) -> tuple[int | None, str, float]:
    """`Casador.casar` mas dos casos propios de esta pantalla.

    - Nombres de dos letras ("BO"): el casador los rechaza por cortos; aqui valen
      si coinciden exactos con el catalogo y el OCR los leyo con confianza.
    - Los archwings llevan un icono delante del nombre que el OCR lee como una
      letra pegada ("WITZAL", "WODONATA"): si no casa entero, se reintenta sin la
      primera letra, y solo se acepta un parecido alto.
    """
    item_id, nombre, puntos = casador.casar(texto, umbral)
    if item_id:
        return item_id, nombre, puntos
    clave = normalizar(texto)
    if 1 <= len(clave) <= 2 and confianza >= CONFIANZA_MINIMA_RANGO:
        exacto = casador.candidatos.get(clave)
        if exacto:
            return exacto[0], exacto[1], 100.0
    if re.match(r"^[A-Za-z][A-Z][A-Z\- ]{3,}$", texto.strip()):
        item_id, nombre, puntos = casador.casar(texto.strip()[1:], max(umbral, 90))
        if item_id:
            return item_id, nombre, puntos
    return None, "", 0.0


def _categoria_de(texto: str) -> str | None:
    clave = normalizar(texto)
    if not clave or len(clave) < 3:
        return None
    if clave in CATEGORIAS_PANTALLA:
        return CATEGORIAS_PANTALLA[clave]
    mejor = max(CATEGORIAS_PANTALLA, key=lambda c: fuzz.ratio(clave, c))
    return CATEGORIAS_PANTALLA[mejor] if fuzz.ratio(clave, mejor) >= 85 else None


def _es_texto_de_cabecera(texto: str) -> bool:
    clave = normalizar(texto)
    return bool(
        RE_ETIQUETA_MAESTRIA.search(texto)
        or any(fuzz.ratio(clave, e) >= 80 for e in ETIQUETAS_COMPLETADO)
        or clave.startswith(("ordenar por", "sort by"))
        or _categoria_de(texto)
    )


def separar_lineas_de_rango(lineas: list[Leido]) -> tuple[list[Leido], list[_LineaRango]]:
    """Aparta las lineas "RANGO MAXIMO" / "RANGO 14" / "30" del resto (los nombres)."""
    textos: list[Leido] = []
    rangos: list[_LineaRango] = []
    for linea in lineas:
        r = _como_linea_de_rango(linea)
        if r is not None:
            rangos.append(r)
        else:
            textos.append(linea)
    return textos, rangos


def _como_linea_de_rango(linea: Leido) -> _LineaRango | None:
    texto = linea.texto.strip()
    clave = normalizar(texto)
    if clave in PALABRAS_DOMINADO:
        return _LineaRango(linea, None, None, maximo=True)
    # "RANGOMAXIMO" pegado, "RANG0 MAXIM0" con ceros: se compara sin espacios.
    compacta = clave.replace(" ", "")
    if compacta and fuzz.ratio(compacta, "rangomaximo") >= 80 or fuzz.ratio(compacta, "maxrank") >= 85:
        return _LineaRango(linea, None, None, maximo=True)
    texto = re.sub(r"(?i)^rang[o0]", "RANGO", texto)  # "RANG0 38": el OCR cambia la O por un cero
    m = RE_LINEA_RANGO.match(texto)
    if m is None and re.match(r"(?i)^rango\s+[a-záé]", texto):
        # Un efecto de luz tapaba parte de la linea ("RANGO MI"): es una linea de rango,
        # asi que el objeto tiene rango, pero no se sabe cual. Queda como desconocido.
        return _LineaRango(linea, None, None, ilegible=True)
    if m:
        if m.group(1):
            return _LineaRango(linea, None, None, maximo=True)
        rango = int(m.group(2))
        tope = int(m.group(3)) if m.group(3) else None
    else:
        corto = texto.translate(_LETRAS_A_CIFRAS) if len(texto) <= 5 else texto
        m = RE_CIFRA.match(corto)
        if not m:
            return None
        rango = int(m.group(1))
        tope = int(m.group(2)) if m.group(2) else None
    if rango > 40 or (tope is not None and tope not in (30, 40)):
        return None
    return _LineaRango(linea, rango, tope)


def emparejar_rangos(tarjetas: list[Tarjeta], rangos: list[_LineaRango]) -> None:
    """A cada nombre, la linea de rango que tiene justo debajo; cada linea se usa una vez.

    Las dos van alineadas a la izquierda en la misma placa, asi que se exige
    solape horizontal. Se recorren las parejas de mas cercana a mas lejana para
    que un nombre no le robe la linea a la tarjeta de al lado.
    """
    parejas = []
    for i, t in enumerate(tarjetas):
        x, y, ancho, alto = t.caja
        for j, r in enumerate(rangos):
            l = r.linea
            solape_x = min(x + ancho, l.x + l.ancho) - max(x, l.x)
            if solape_x <= 0:
                continue
            hueco = l.y - (y + alto)  # positivo: la linea esta debajo del nombre
            if hueco < -0.3 * alto or hueco > HUECO_MAXIMO * max(alto, 8):
                continue
            parejas.append((hueco + abs(l.x - x) / 4, i, j))
    usadas_t: set[int] = set()
    usadas_r: set[int] = set()
    for _, i, j in sorted(parejas):
        if i in usadas_t or j in usadas_r:
            continue
        usadas_t.add(i)
        usadas_r.add(j)
        r, t = rangos[j], tarjetas[i]
        t.confianza_rango = r.linea.confianza
        if r.ilegible:
            t.motivo = f"linea de rango ilegible ({r.linea.texto!r})"
            continue
        if r.maximo:
            t.rango = t.tope
            t.motivo = "linea rango maximo"
        else:
            t.rango = r.rango
            if r.tope_declarado is not None and t.tope is not None and r.tope_declarado != t.tope:
                t.motivo = f"la pantalla dice tope {r.tope_declarado} y el catalogo {t.tope}"


def _decidir(t: Tarjeta, hay_cabecera: bool) -> None:
    if t.tope is None:
        t.estado = maestria.NO_APLICA
        t.motivo = "el catalogo dice que no da maestria"
        return
    if t.rango is None:
        if t.motivo.startswith("linea de rango ilegible"):
            t.estado = maestria.DESCONOCIDO
        elif hay_cabecera:
            t.estado = maestria.NO_DOMINADO
            t.motivo = "sin linea de rango bajo el nombre"
        else:
            t.estado = maestria.DESCONOCIDO
            t.motivo = "sin linea de rango y sin barra de categoria para descartar la fila MAS USADO"
        return
    if t.confianza_rango < CONFIANZA_MINIMA_RANGO:
        t.estado = maestria.DESCONOCIDO
        t.motivo = f"linea de rango dudosa ({t.confianza_rango:.2f} de confianza)"
        return
    if t.motivo.startswith("la pantalla dice tope"):
        t.estado = maestria.DESCONOCIDO
        return
    t.estado = maestria.estado_por_rango(t.rango, t.tope)
    if t.estado == maestria.DESCONOCIDO:
        t.motivo = f"rango {t.rango} imposible para un tope de {t.tope}"
    elif t.motivo != "linea rango maximo":
        t.motivo = ""


def leer_rango_maestria(lineas: list[Leido]) -> int | None:
    """Rango de maestria de la portada del perfil, si esta a la vista.

    Primero la cifra junto a la etiqueta; si no (la cifra va en un emblema que el
    OCR no lee), el titulo: "MAESTRO VERDADERO" es 30, "LEGENDARIO n" es 30+n y
    "SIGUIENTE RANGO: LEGENDARIO n" es 30+n-1. Los titulos de bronce/plata/oro
    (Iniciado, Novato... Maestro) cubren del 0 al 29.
    """
    for l in lineas:
        m = RE_RANGO_MAESTRIA.search(l.texto)
        if m and int(m.group(1)) <= 40 and l.confianza >= CONFIANZA_MINIMA_RANGO:
            return int(m.group(1))
    if not any(RE_ETIQUETA_MAESTRIA.search(l.texto) for l in lineas):
        return None
    for l in lineas:
        if l.confianza < CONFIANZA_MINIMA_RANGO:
            continue
        clave = normalizar(l.texto)
        compacta = clave.replace(" ", "")
        if RE_SIGUIENTE.search(clave):
            m = RE_LEGENDARIO.search(clave)
            if m:
                return 30 + int(m.group(1) or m.group(2)) - 1
            continue
        if fuzz.ratio(compacta, "maestroverdadero") >= 85 or fuzz.ratio(compacta, "truemaster") >= 85:
            return 30
        m = RE_LEGENDARIO.search(clave)
        if m:
            return 30 + int(m.group(1) or m.group(2))
        palabras = clave.split()
        base = next((TITULOS_BASE[p] for p in palabras if p in TITULOS_BASE), None)
        if base is not None and len(palabras) <= 4:
            grado = next((TITULOS_GRADO[p] for p in palabras if p in TITULOS_GRADO), 0)
            return base + grado
    # La cifra grande y suelta de la portada sale con menos confianza (0.5-0.6) que el
    # texto normal; aqui basta con que pase el filtro general, porque el MR es un dato
    # informativo y nunca marca nada como dominado.
    for e in (l for l in lineas if RE_ETIQUETA_MAESTRIA.search(l.texto)):
        mejor = None
        for l in lineas:
            if l is e:
                continue
            m = RE_CIFRA.match(l.texto.translate(_LETRAS_A_CIFRAS) if len(l.texto) <= 5 else l.texto)
            if not m or int(m.group(1)) > 40:
                continue
            dx = max(l.x - (e.x + e.ancho), e.x - (l.x + l.ancho), 0)
            dy = max(l.y - (e.y + e.alto), e.y - (l.y + l.alto), 0)
            if dx <= 3 * e.alto and dy <= 3 * e.alto and (mejor is None or dx + dy < mejor[0]):
                mejor = (dx + dy, int(m.group(1)))
        if mejor:
            return mejor[1]
    return None


# --- deteccion de cambio de pagina (modo automatico) ---------------------------------


def huella(imagen, lado: int = 32):
    """Miniatura en gris de la captura: basta para saber si la pantalla ha cambiado."""
    import cv2
    import numpy as np

    if imagen is None or getattr(imagen, "size", 0) == 0:
        return None
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    return cv2.resize(gris, (lado, lado // 2), interpolation=cv2.INTER_AREA).astype(np.float32)


def distinta(a, b, umbral: float = 6.0) -> bool:
    """True si las dos huellas son pantallas distintas (diferencia media de gris > umbral)."""
    import numpy as np

    if a is None or b is None:
        return a is not b
    return float(np.abs(a - b).mean()) > umbral


class DetectorPagina:
    """Avisa cuando la pantalla cambia y se queda quieta: el usuario ha pasado pagina.

    `observar(imagen)` devuelve True una sola vez por pagina nueva, cuando la
    captura lleva `quietas` observaciones seguidas igual y es distinta de la
    ultima pagina que se dio por buena.
    """

    def __init__(self, quietas: int = 2, umbral: float = 6.0):
        self.quietas = quietas
        self.umbral = umbral
        self._ultima_procesada = None
        self._anterior = None
        self._iguales = 0

    def observar(self, imagen) -> bool:
        h = huella(imagen)
        if h is None:
            return False
        if distinta(h, self._anterior, self.umbral):
            self._anterior = h
            self._iguales = 1
            return False
        self._iguales += 1
        if self._iguales != self.quietas:
            return False
        if not distinta(h, self._ultima_procesada, self.umbral):
            return False
        self._ultima_procesada = h
        return True


# --- internos ------------------------------------------------------------------------


def _anadir(fichas: dict, item_id: int, texto: str, nombre: str, puntos: float, caja, indice) -> None:
    """Una tarjeta por objeto en la pagina; si el OCR lo lee dos veces, gana la mejor."""
    previa = fichas.get(item_id)
    if previa is not None and previa[4] >= puntos:
        return
    fila = indice.execute(
        "SELECT unique_name, categoria, tipo, nombre_en FROM items WHERE id = ?", (item_id,)
    ).fetchone()
    if fila is None:
        return
    unique_name, categoria, tipo, nombre_en = fila
    tope = maestria.tope_rango(maestria.umbral_xp(categoria, tipo, nombre_en, unique_name))
    fichas[item_id] = (texto, item_id, unique_name, nombre, puntos, tuple(caja), tope)


def _reescalar(imagen, escala: float):
    import cv2

    alto, ancho = imagen.shape[:2]
    return cv2.resize(imagen, (int(ancho * escala), int(alto * escala)), interpolation=cv2.INTER_CUBIC)
