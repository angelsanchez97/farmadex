"""Lectura por OCR de las pantallas donde el juego ensena cuantas unidades tienes:
Equipamiento > Inventario (recursos, piezas, planos, mods...) y la Fundicion.

Lo que se ha podido ver en capturas reales de internet (ver
tests/fixtures/capturas_internet/README.md; NO hay capturas del usuario aun):

Inventario (interfaz actual, ingles, 1280x720):
  - Titulo "INVENTORY" arriba en el centro y una barra de pestanas con iconos;
    "SORT BY: OWNED" a la derecha.
  - Rejilla de 6-7 placas por fila. En cada placa, de arriba abajo: precio en
    ducados ("2,500", solo piezas prime), una linea "<icono> 18 OWNED" y el
    nombre en una o mas lineas ("NOVA PRIME" / "NEUROPTICS" / "BLUEPRINT").
  - El OCR a 720p lee "180WNED", "Q9OWNED", "7OWNED": la O de OWNED sale como
    cero y el icono a veces como una letra o UNA CIFRA ("780WNED" para 8 OWNED).
    Por eso la cifra sola nunca vale: hace falta la palabra (OWNED / POSEIDO...)
    detras, y aun asi la lectura queda marcada como poco fiable.

Fundicion (Update 41, ingles, 1920x1080):
  - Titulo "FOUNDRY". Placas anchas con el nombre de la receta ("VALKYR
    CHASSIS"), debajo los materiales como "4,071/500" con SOLO un icono (el
    nombre del material no esta escrito: no se puede saber que recurso es), y
    al pie "1 BLUEPRINT LEFT", "12 HOURS", "BUILD".
  - De aqui solo se saca cuantos planos de cada receta tienes.

Todo lo que no case con el catalogo con puntuacion alta, o cuyo titulo de
pantalla no se haya leido, se descarta: apuntar cantidades falsas en los
objetivos del usuario es peor que no apuntar nada. Ver `MINIMO_PUNTUACION`.
El espanol de estas pantallas NO se ha visto: las palabras castellanas de abajo
son suposiciones y se anota en el log cada linea con cifra que no se entiende,
para completar la tabla cuando haya una captura real.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field

from ..registro_log import obtener
from .ocr import CATEGORIAS_PLAUSIBLES, Casador, Leido, MotorOCR, _caja_union, agrupar_bloques, unir_filas

log = obtener("inventario_ocr")

# Titulo de la pantalla. El OCR pega palabras y confunde O/0.
TITULOS = {
    "inventory": "inventario", "inventario": "inventario", "inventari0": "inventario",
    "foundry": "fundicion", "fundicion": "fundicion", "fundici0n": "fundicion",
}
# "18 OWNED", "180WNED" (la O leida como 0), "Q9OWNED" (icono leido como letra).
# Castellano: candidatos sin confirmar ("18 EN POSESION", "POSEIDOS: 18", "TIENES 18").
RE_POSEIDO = re.compile(
    r"^[^\d]{0,2}(\d[\d.,]*?)\s*(?:0|o)?(?:wned|owned)\b"
    r"|^[^\d]{0,2}(\d[\d.,]*)\s*(?:pose[ií]d[oa]s?|en\s*posesi[oó]n|en\s*propiedad|unidades)\b"
    r"|^(?:pose[ií]d[oa]s?|tienes|owned|cantidad)\s*[:.]?\s*(\d[\d.,]*)$",
    re.IGNORECASE,
)
# Pie de la placa de la fundicion: "1 BLUEPRINT LEFT" / "2 BLUEPRINTS LEFT".
# Castellano: candidatos ("1 PLANO RESTANTE", "QUEDAN 2 PLANOS").
RE_PLANOS = re.compile(
    r"^[^\d]{0,2}(\d[\d.,]*)\s*(?:blueprints?|planos?)\s*(?:left|restantes?|disponibles?)?$"
    r"|^quedan?\s*(\d[\d.,]*)\s*planos?$",
    re.IGNORECASE,
)
# Materiales de una receta: "4,071/500". Se reconocen para NO tomarlos por nada
# mas; el nombre del material no esta escrito, asi que no se guardan.
RE_FRACCION = re.compile(r"^[^\d]{0,2}(\d[\d.,]*)\s*/\s*(\d[\d.,]*)$")
RE_SOLO_CIFRA = re.compile(r"^[^\d]{0,2}\d[\d.,]*$")

# Un nombre por debajo de esto no entra: con el inventario sin calibrar se exige
# mas parecido que en el perfil (82).
MINIMO_PUNTUACION = 90.0
MINIMO_CONFIANZA_CIFRA = 0.60
# La linea de cantidad esta en la misma placa que el nombre: encima (inventario)
# o debajo (fundicion), a menos de estas alturas de linea.
HUECO_INVENTARIO = 4.0
HUECO_FUNDICION = 9.0

CATEGORIAS_INVENTARIO = CATEGORIAS_PLAUSIBLES

_lineas_raras: set[str] = set()


def casador_inventario(indice: sqlite3.Connection) -> Casador:
    """Todo el catalogo con nombre: piezas, planos, recursos, mods, reliquias..."""
    return Casador(indice, CATEGORIAS_INVENTARIO)


@dataclass
class Cantidad:
    unique_name: str
    nombre: str
    cantidad: int
    texto_ocr: str  # la linea de cantidad tal cual se leyo
    texto_nombre: str
    puntuacion: float  # parecido del nombre con el catalogo
    confianza: float  # del OCR, la menor de las dos lineas
    caja: tuple[int, int, int, int]
    pantalla: str = ""
    fiable: bool = True  # False cuando la cifra pudo absorber el icono de la placa
    motivo: str = ""


@dataclass
class PaginaInventario:
    pantalla: str | None = None  # "inventario" / "fundicion" / None si no se reconocio
    cantidades: list[Cantidad] = field(default_factory=list)
    sin_casar: list[str] = field(default_factory=list)
    descartadas: list[str] = field(default_factory=list)
    lineas: int = 0

    @property
    def fiables(self) -> list[Cantidad]:
        return [c for c in self.cantidades if c.fiable]


@dataclass
class _LineaCantidad:
    linea: Leido
    cantidad: int
    tipo: str  # "poseido" / "planos"
    fiable: bool


# --- lectura -------------------------------------------------------------------------


def leer_pagina(
    imagen,
    motor: MotorOCR,
    casador: Casador,
    indice: sqlite3.Connection,
    minimo_confianza: float = 0.4,
    escala: float = 1.0,
) -> PaginaInventario:
    if imagen is None:
        return PaginaInventario()
    if escala != 1.0:
        import cv2

        alto, ancho = imagen.shape[:2]
        imagen = cv2.resize(imagen, (int(ancho * escala), int(alto * escala)), interpolation=cv2.INTER_CUBIC)
    lineas = [l for l in unir_filas(motor.leer(imagen)) if l.confianza >= minimo_confianza]
    if escala != 1.0:
        for l in lineas:
            l.x, l.y = int(l.x / escala), int(l.y / escala)
            l.ancho, l.alto = int(l.ancho / escala), int(l.alto / escala)
    return interpretar_lineas(lineas, casador, indice)


def interpretar_lineas(
    lineas: list[Leido], casador: Casador, indice: sqlite3.Connection
) -> PaginaInventario:
    """Parte pura: de las lineas leidas a las cantidades. Probable sin OCR."""
    pagina = PaginaInventario(lineas=len(lineas))
    pagina.pantalla = pantalla_de(lineas)
    if pagina.pantalla is None:
        return pagina
    textos, cantidades = separar_cantidades(lineas, pagina.pantalla)
    nombres: list[tuple[str, int | None, str, float, tuple, float]] = []
    for bloque in agrupar_bloques(textos):
        texto = " ".join(l.texto for l in bloque)
        if _es_ruido(texto):
            continue
        item_id, nombre, puntos = casador.casar(texto, umbral=int(MINIMO_PUNTUACION))
        confianza = min(l.confianza for l in bloque)
        if item_id and puntos >= MINIMO_PUNTUACION:
            nombres.append((texto, item_id, nombre, puntos, _caja_union(bloque), confianza))
        elif not RE_SOLO_CIFRA.match(texto) and not RE_FRACCION.match(texto):
            pagina.sin_casar.append(texto)
    for texto, item_id, nombre, puntos, caja, confianza in nombres:
        pareja = _emparejar(caja, cantidades, pagina.pantalla)
        if pareja is None:
            pagina.descartadas.append(f"{texto!r}: sin linea de cantidad")
            continue
        fila = indice.execute("SELECT unique_name FROM items WHERE id = ?", (item_id,)).fetchone()
        if fila is None:
            continue
        unique_name = fila[0]
        pagina.cantidades.append(
            Cantidad(
                unique_name=unique_name,
                nombre=nombre,
                cantidad=pareja.cantidad,
                texto_ocr=pareja.linea.texto,
                texto_nombre=texto,
                puntuacion=puntos,
                confianza=min(confianza, pareja.linea.confianza),
                caja=caja,
                pantalla=pagina.pantalla,
                fiable=pareja.fiable and pareja.linea.confianza >= MINIMO_CONFIANZA_CIFRA,
                motivo="" if pareja.fiable else "la cifra puede llevar pegado el icono de la placa",
            )
        )
    pagina.cantidades.sort(key=lambda c: (c.caja[1], c.caja[0]))
    return pagina


def pantalla_de(lineas: list[Leido]) -> str | None:
    """Que pantalla es, por su titulo; None si no hay titulo que lo diga."""
    for l in lineas:
        clave = _normalizar(l.texto).replace(" ", "")
        if clave in TITULOS and l.confianza >= 0.7:
            return TITULOS[clave]
    return None


def separar_cantidades(lineas: list[Leido], pantalla: str) -> tuple[list[Leido], list[_LineaCantidad]]:
    textos, cantidades = [], []
    for l in lineas:
        c = _como_cantidad(l, pantalla)
        if c is not None:
            cantidades.append(c)
        elif RE_FRACCION.match(l.texto.strip()) or RE_SOLO_CIFRA.match(l.texto.strip()):
            continue  # ducados, materiales de receta: no son nombres ni cantidades
        else:
            textos.append(l)
    return textos, cantidades


def _como_cantidad(l: Leido, pantalla: str) -> _LineaCantidad | None:
    texto = l.texto.strip()
    m = RE_POSEIDO.match(texto)
    if m and pantalla == "inventario":
        cifra = next(g for g in m.groups() if g)
        cantidad = _entero(cifra)
        if cantidad is None:
            return None
        # Si delante de la cifra habia una letra, el icono se colo en la lectura;
        # si se colo como CIFRA ("780WNED" por "8 OWNED") no hay forma de saberlo.
        return _LineaCantidad(l, cantidad, "poseido", bool(re.match(r"^\d", texto)))
    m = RE_PLANOS.match(texto)
    if m and pantalla == "fundicion":
        cantidad = _entero(next(g for g in m.groups() if g))
        if cantidad is None:
            return None
        return _LineaCantidad(l, cantidad, "planos", bool(re.match(r"^\d", texto)))
    if re.search(r"\d", texto) and not RE_FRACCION.match(texto) and not RE_SOLO_CIFRA.match(texto):
        if len(texto) <= 24 and texto not in _lineas_raras and re.search(r"(wned|pose|plan|tien|unid|left|quedan)", texto, re.I):
            _lineas_raras.add(texto)
            log.info("Linea con cifra sin entender en %s (candidata a patron): %r", pantalla, texto)
    return None


def _emparejar(caja, cantidades: list[_LineaCantidad], pantalla: str) -> _LineaCantidad | None:
    """La linea de cantidad de la misma placa: la mas cercana con solape horizontal."""
    x, y, ancho, alto = caja
    alto_linea = max(alto, 8)
    mejor, mejor_distancia = None, None
    for c in cantidades:
        l = c.linea
        solape = min(x + ancho, l.x + l.ancho) - max(x, l.x)
        if solape <= 0:
            continue
        if pantalla == "inventario":
            hueco = y - (l.y + l.alto)  # la cantidad va encima del nombre
            limite = HUECO_INVENTARIO * max(l.alto, 8)
        else:
            hueco = l.y - (y + alto)  # en la fundicion va al pie de la placa
            limite = HUECO_FUNDICION * max(l.alto, 8)
        if hueco < -0.3 * alto_linea or hueco > limite:
            continue
        distancia = hueco + abs(l.x - x) / 4
        if mejor_distancia is None or distancia < mejor_distancia:
            mejor, mejor_distancia = c, distancia
    return mejor


def _entero(cifra: str) -> int | None:
    limpio = re.sub(r"[.,]", "", cifra)
    if not limpio.isdigit() or len(limpio) > 7:
        return None
    return int(limpio)


def _normalizar(texto: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9 ]", "", sin_acentos.lower()).strip()


RE_RUIDO = re.compile(
    r"\bfps\b|\bmhz\b|\brtx\b|ryzen|\bram\b|\d\s*mb\b|sort\s*by|ordenar|search|buscar|"
    r"select\s*items|sell\s*pile|exit|salir|build|construir|hours?|horas?|minutes?|minutos?",
    re.IGNORECASE,
)


def _es_ruido(texto: str) -> bool:
    return bool(RE_RUIDO.search(texto)) or len(texto) < 3
