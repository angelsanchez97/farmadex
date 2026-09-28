"""Camino rapido de la pantalla de recompensas: leer solo la fila de nombres.

Medido sobre pantallas reales a 2560x1440, 1920x1080 y 1079x607 con 2, 3 y 4
tarjetas (propias, de un video de un usuario y de capturas publicas de otros
overlays): las tarjetas van centradas, cada una mide el 22,35 % del alto de la
ventana, y el nombre de cada una cae siempre entre el 37,5 % y el 43,5 % del
alto (una linea centrada en el 41 %; dos lineas del 39 % al 42 %), dentro del
24 %..76 % del ancho. Leer solo esa tira, reescalada a 80 px de alto y sin que
RapidOCR la amplie a 736 px, cuesta ~30 ms frente a ~200 ms de la franja
entera, y deja fuera de la lectura los nombres de la escuadra, los rotulos
"Obtenidos" y los paneles de otros overlays (AlecaFrame), asi que tampoco hay
que elegir fila. Con la geometria se sabe ademas que texto es de que tarjeta:
dos nombres que el detector pega en una sola caja se parten por el borde entre
tarjetas, y un nombre partido en dos cajas se vuelve a juntar.

El casado va por escalones, del conjunto mas cerrado al mas abierto: lo que
EE.log dio de esta reliquia (exacto), lo que puede salir de cualquier reliquia
(tabla `reliquia_recompensas`, ~600 objetos) y, si nada de eso encaja, el
catalogo entero con el umbral de siempre. Asi "Plano DeFang Prime" (el OCR pega
el "De") casa con el plano, que es lo que sale de la reliquia, y no con el arma.

Si la tira no da lo que EE.log dice que hay (otra escala de interfaz, un parche
que mueva las tarjetas), `leer_pantalla` cae al camino de siempre, la franja
entera, y se queda con la lectura que mas tarjetas traiga.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..registro_log import obtener
from .ocr import (
    Casador, Leido, MotorOCR, Reconocido, _caja_union, agrupar_bloques, normalizar, unir_filas,
)
from .pantalla import Region

log = obtener("reliquias")

# La fila de nombres de las tarjetas, en proporciones de la ventana del juego. Lo
# vertical vale tal cual; el ancho real de la tira lo calcula `region_fila`.
FILA_NOMBRES = (0.24, 0.375, 0.76, 0.435)
# Ancho de una tarjeta en proporcion del alto de la ventana (241/1080, 321/1440, 137/607).
ANCHO_TARJETA = 0.2235
# Alto al que se reescala la tira antes del OCR: el texto queda en ~24 px, que es
# lo que el reconocedor quiere, y la forma de entrada es siempre la misma (asi
# ONNX Runtime no vuelve a planificar memoria en cada resolucion).
ALTO_FILA = 80

# Umbrales de casado por escalon: cuanto mas cerrado el conjunto, mas se admite.
UMBRAL_CONOCIDAS = 70
UMBRAL_RELIQUIAS = 76
UMBRAL_CATALOGO = 80
# Una conocida (EE.log) con esta puntuacion o mas gana sin mirar el resto de escalones.
SEGURA_CONOCIDA = 95

SIN_IDENTIFICAR = 0  # mismo valor que en reliquias.py (aqui no se importa para no dar vueltas)
RE_NOMBRE_PLAUSIBLE = re.compile(r"^[^\d]{6,}$")
# El OCR pega a veces la preposicion con el nombre: "Plano DeFang Prime".
RE_DE_PEGADO = re.compile(r"\b([Dd]e[l]?)(?=[A-Z])")  # "DeFang"
RE_DE_PEGADO_ANTES = re.compile(r"(?<=[a-z])(De[l]?)\b")  # "PlanoDe"
# El juego escribe el plano delante ("Plano de Fang Prime"); el catalogo, detras.
RE_PLANO_DELANTE = re.compile(r"^plano\s*de\s+")
# "2 X Forma (Schéma)" y, pegado por el OCR, "2XForma(Schema".
RE_CANTIDAD_DELANTE = re.compile(r"^\s*\d{1,2}\s*[xX×]\s*(?=[A-ZÁÉÍÓÚ])")


def escalar_fila(imagen):
    """La tira a ALTO_FILA px de alto. Devuelve (imagen, escala aplicada)."""
    import cv2

    alto = imagen.shape[0]
    if alto == ALTO_FILA or alto == 0:
        return imagen, 1.0
    escala = ALTO_FILA / alto
    interpolacion = cv2.INTER_CUBIC if escala > 1 else cv2.INTER_AREA
    return cv2.resize(imagen, (max(1, int(imagen.shape[1] * escala)), ALTO_FILA), interpolation=interpolacion), escala


def leer_fila(imagen, motor: MotorOCR, minimo_confianza: float = 0.4) -> list[Leido]:
    """OCR de la tira de nombres, con las cajas en pixeles de la tira original.

    No se juntan trozos de linea aqui (`unir_filas`): en la tira el detector da
    cada nombre en una caja y, cuando pega dos vecinos, lo que hace falta es
    partirlos, no juntarlos mas. Eso lo decide la geometria en `repartir`.
    """
    if imagen is None or imagen.size == 0:
        return []
    escalada, escala = escalar_fila(imagen)
    lineas = [l for l in motor.leer_tira(escalada) if l.confianza >= minimo_confianza]
    if escala != 1.0:
        for l in lineas:
            l.x, l.y = int(l.x / escala), int(l.y / escala)
            l.ancho, l.alto = int(l.ancho / escala), int(l.alto / escala)
    return lineas


def ids_reliquias(con: sqlite3.Connection) -> set[int]:
    """Todo lo que puede salir de una reliquia, en boveda o no (la gente abre las viejas)."""
    return {f[0] for f in con.execute("SELECT DISTINCT item_id FROM reliquia_recompensas")}


def catalogo_de_piezas(casador: Casador, con: sqlite3.Connection) -> Casador:
    """El catalogo sin los objetos enteros (armas, warframes: los que tienen piezas).

    Una reliquia nunca da un arma o un warframe entero, solo planos y piezas,
    y son justo esos nombres los que se cuelan cuando el OCR pega letras:
    "Plano DeFang Prime" casaba exacto con el arma "Fang Prime" en vez de con
    su plano. Fuera del ultimo escalon, ese fallo ya no tiene por donde entrar.
    """
    padres = {f[0] for f in con.execute("SELECT DISTINCT padre_id FROM items WHERE padre_id IS NOT NULL")}
    ids = {v[0] for v in casador.candidatos.values()} - padres
    return casador.restringido(ids)


def ids_conocidas(con: sqlite3.Connection, rutas: list[str]) -> set[int]:
    """Ids de las recompensas que EE.log dio (rutas del juego), las que esten en el indice."""
    from ..datos.indice import fila_por_ruta

    ids = set()
    for ruta in rutas:
        fila = fila_por_ruta(con, ruta)
        if fila:
            ids.add(fila[0])
    return ids


def variantes_texto(texto: str) -> list[str]:
    """El texto leido y sus arreglos tipicos: "De" pegado y "Plano de X" -> "X plano"."""
    salida = [texto]
    # "2 X Forma (Schéma)": la Forma doble lleva la cantidad delante (captura real en frances).
    sin_cantidad = RE_CANTIDAD_DELANTE.sub("", texto)
    if sin_cantidad != texto and sin_cantidad:
        salida.append(sin_cantidad)
    despegado = RE_DE_PEGADO.sub(r"\1 ", RE_DE_PEGADO_ANTES.sub(r" \1", texto))
    if despegado != texto:
        salida.append(despegado)
    for t in list(salida):
        clave = normalizar(t)
        sin_plano = RE_PLANO_DELANTE.sub("", clave)
        if sin_plano != clave and sin_plano:
            salida.append(sin_plano + " plano")
    return salida


class CasadorEscalonado:
    """Casa primero contra lo que EE.log dio, luego contra lo que sale de reliquias, luego contra todo."""

    def __init__(self, catalogo: Casador, reliquias: Casador | None = None, conocidas: Casador | None = None):
        self.escalones = [
            (conocidas, UMBRAL_CONOCIDAS),
            (reliquias, UMBRAL_RELIQUIAS),
            (catalogo, UMBRAL_CATALOGO),
        ]

    def casar(self, texto: str) -> tuple[int | None, str, float]:
        """El mejor casado entre todos los escalones, no el primero que pase su umbral.

        Lo que EE.log dio es de TODA la escuadra: si la tarjeta propia es otra pieza
        del mismo objeto ("Receptor De Akbolto Prime" con el cañon de otro jugador
        en el log), el escalon de conocidas casaba el cañon con 79 y ganaba sin
        mirar que el catalogo daba el receptor con 100. Ahora una conocida solo gana
        si es casi exacta (`SEGURA_CONOCIDA`) o si nadie la supera; entre escalones
        con la misma puntuacion gana el mas cerrado.
        """
        variantes = variantes_texto(texto)
        elegido = (None, "", 0.0)
        for i, (casador, umbral) in enumerate(self.escalones):
            if casador is None:
                continue
            mejor = (None, "", 0.0)
            for variante in variantes:
                item_id, nombre, puntos = casador.casar(variante, umbral)
                if item_id and puntos > mejor[2]:
                    mejor = (item_id, nombre, puntos)
            if not mejor[0]:
                continue
            if i == 0 and mejor[2] >= SEGURA_CONOCIDA:
                return mejor
            if mejor[2] > elegido[2]:
                elegido = mejor
            if elegido[2] >= 100:  # nadie la puede superar y el empate lo gana el escalon mas cerrado
                break
        return elegido


# -- geometria de las tarjetas ------------------------------------------------


def alto_interfaz(ventana: Region) -> float:
    """Alto de referencia de la interfaz del juego: el de la ventana en 16:9 o mas ancha;
    en mas estrecha (16:10, 4:3) la interfaz se ajusta al ancho, como una caja 16:9
    centrada (asi lo calcula tambien WFInfo)."""
    return min(ventana.alto, ventana.ancho * 9 / 16)


def ranuras(ventana: Region, n: int) -> list[tuple[float, float]]:
    """Los n huecos de tarjeta, centrados en la ventana, como (x0, x1) de pantalla."""
    ancho = ANCHO_TARJETA * alto_interfaz(ventana)
    x0 = ventana.x + ventana.ancho / 2 - n * ancho / 2
    return [(x0 + i * ancho, x0 + (i + 1) * ancho) for i in range(n)]


# Margen a cada lado de las tarjetas, en proporcion del alto: nombres que el juego
# centra y se salen un poco de su tarjeta, y cajas del detector algo holgadas.
MARGEN_FILA = 0.03


def region_fila(ventana: Region) -> Region:
    """La tira de nombres de `ventana`, sea cual sea su proporcion.

    Con la tira en fraccion del ancho (24 %..76 %), a 16:10 y 4:3 las tarjetas
    de los lados quedaban cortadas (a 1600x1200 cuatro tarjetas miden 1073 px y
    la tira solo 832), y a 21:9 se leia mucho fondo de mas. Ahora el ancho sale
    de las cuatro ranuras de tarjeta. En pantallas mas estrechas que 16:9 la
    interfaz se ajusta al ancho (caja 16:9 centrada, `alto_interfaz`, como en
    WFInfo); como no hay capturas reales de 16:10 y 4:3 en el banco, la tira cubre
    tambien la otra posibilidad (tarjetas por el alto de la ventana).
    """
    arr, aba = FILA_NOMBRES[1], FILA_NOMBRES[3]
    y0, y1 = ventana.y + arr * ventana.alto, ventana.y + aba * ventana.alto
    alto_ui = alto_interfaz(ventana)
    if alto_ui < ventana.alto:  # mas estrecha que 16:9: tambien la caja 16:9 centrada
        base = ventana.y + (ventana.alto - alto_ui) / 2
        y0, y1 = min(y0, base + arr * alto_ui), max(y1, base + aba * alto_ui)
    # Ancho: el mayor de las dos posibilidades (tarjetas por el alto de la ventana o por
    # el de la caja 16:9), mas un margen.
    medio = 2 * ANCHO_TARJETA * ventana.alto + MARGEN_FILA * ventana.alto
    centro = ventana.x + ventana.ancho / 2
    x0 = max(ventana.x, centro - medio)
    x1 = min(ventana.x + ventana.ancho, centro + medio)
    return Region(round(x0), round(y0), max(1, round(x1 - x0)), max(1, round(y1 - y0)))


def _partir(linea: Leido, huecos: list[tuple[float, float]], ancho_tarjeta: float):
    """Reparte una caja entre los huecos que pisa; None si la geometria no cuadra.

    Una caja que pisa dos huecos y es mas ancha que una tarjeta son dos nombres
    pegados: se parte el texto por donde cae el borde. Una caja estrecha que
    cruza un borde es senal de que el numero de tarjetas supuesto esta mal.
    """
    x0, x1 = linea.x, linea.x + linea.ancho
    pisados = [i for i, (a, b) in enumerate(huecos) if min(x1, b) - max(x0, a) > 0.2 * ancho_tarjeta]
    if not pisados:
        return None
    if len(pisados) == 1:
        return [(pisados[0], linea)]
    if linea.ancho < 1.25 * ancho_tarjeta:
        return None
    partes = []
    texto = linea.texto
    inicio_x, inicio_c = x0, 0
    for i in pisados:
        borde = huecos[i][1] if i != pisados[-1] else x1
        corte = len(texto) if i == pisados[-1] else _corte(texto, inicio_c, len(texto) * (borde - x0) / max(1, linea.ancho))
        trozo = texto[inicio_c:corte].strip()
        if trozo:
            partes.append((i, Leido(trozo, int(inicio_x), linea.y, int(borde - inicio_x), linea.alto, linea.confianza)))
        inicio_x, inicio_c = borde, corte
    return partes


def _corte(texto: str, desde: int, aproximado: float) -> int:
    """Indice por donde partir: el espacio mas cercano a menos de 3 letras; si no, un
    cambio de minuscula a mayuscula ("PrimeEmpunadura"); si no, donde caiga."""
    objetivo = max(desde, min(len(texto), round(aproximado)))
    for delta in (0, 1, -1, 2, -2, 3, -3):
        i = objetivo + delta
        if desde < i < len(texto) and texto[i] == " ":
            return i
    for delta in (0, 1, -1, 2, -2, 3, -3):
        i = objetivo + delta
        if desde < i < len(texto) and texto[i - 1].islower() and texto[i].isupper():
            return i
    return objetivo


def repartir(lineas: list[Leido], ventana: Region, region: Region, esperadas: int | None) -> list[list[Leido]] | None:
    """Agrupa las lineas de la tira por tarjeta segun la geometria fija.

    Se prueba primero con las tarjetas que dijo EE.log y luego con 4, 3, 2 y 1;
    vale la primera cuenta con la que ninguna caja queda fuera ni cruza un
    borde. None si ninguna cuadra (otra escala de interfaz): entonces se agrupa
    sin geometria. Las cajas vienen en coordenadas de la tira.
    """
    if not lineas:
        return None
    ancho_tarjeta = ANCHO_TARJETA * alto_interfaz(ventana)
    cuentas = ([esperadas] if esperadas else []) + [n for n in (4, 3, 2, 1) if n != esperadas]
    for n in cuentas:
        huecos = [(a - region.x, b - region.x) for a, b in ranuras(ventana, n)]
        grupos: list[list[Leido]] = [[] for _ in range(n)]
        for linea in lineas:
            partes = _partir(linea, huecos, ancho_tarjeta)
            if partes is None:
                break
            for i, parte in partes:
                grupos[i].append(parte)
        else:
            return grupos
    return None


def _texto_de(grupo: list[Leido]) -> str:
    """Las lineas de una tarjeta en orden de lectura: arriba a abajo, izquierda a derecha."""
    if not grupo:
        return ""
    alto = max(1, min(l.alto for l in grupo))
    return " ".join(l.texto for l in sorted(grupo, key=lambda l: (round(l.y / (0.6 * alto)), l.x)))


def _solapan_x(a, b, minimo: float = 0.3) -> bool:
    xa, _, wa, _ = a
    xb, _, wb, _ = b
    solape = min(xa + wa, xb + wb) - max(xa, xb)
    return solape >= minimo * max(1, min(wa, wb))


def _casar_grupo(grupo: list[Leido], casador: CasadorEscalonado) -> Reconocido | None:
    """La recompensa de un grupo de lineas, o None si nada casa (texto_ocr con el texto leido)."""
    caja = _caja_union(grupo)
    texto = _texto_de(grupo)
    item_id, nombre, puntos = casador.casar(texto)
    if not item_id and len(grupo) > 1:
        for linea in sorted(grupo, key=lambda l: -l.ancho):
            item_id, nombre, puntos = casador.casar(linea.texto)
            if item_id:
                break
    if item_id:
        return Reconocido(texto, item_id, nombre, puntos, caja)
    if RE_NOMBRE_PLAUSIBLE.match(texto.strip()):
        return Reconocido(texto, SIN_IDENTIFICAR, "", 0.0, caja)
    return None


def casar_fila(
    lineas: list[Leido], casador: CasadorEscalonado, maximo: int = 4, grupos: list[list[Leido]] | None = None,
) -> list[Reconocido]:
    """Una recompensa por tarjeta, de izquierda a derecha.

    Con `grupos` (lineas ya repartidas por tarjeta segun la geometria) cada grupo
    es una tarjeta. Sin ellos, cada bloque de lineas apiladas es un nombre y dos
    bloques que se pisan en horizontal son la misma tarjeta (la etiqueta que
    Farmadex pinta encima en la segunda mirada): se queda el mejor. Dos tarjetas
    con el mismo objeto (tres "Fang Prime Blade" en una escuadra) se conservan
    las dos, que es lo que hay en pantalla. Lo que parece un nombre y no casa
    entra como "sin identificar" en vez de inventar una recompensa.
    """
    if grupos is None:
        grupos = agrupar_bloques(list(lineas))
    reconocidos = [r for r in (_casar_grupo(g, casador) for g in grupos if g) if r is not None]
    salida: list[Reconocido] = []
    for r in sorted(reconocidos, key=lambda r: (-(r.item_id != SIN_IDENTIFICAR), -r.puntuacion)):
        if not any(_solapan_x(r.caja, s.caja) for s in salida):
            salida.append(r)
    for r in salida:
        if r.item_id == SIN_IDENTIFICAR:
            log.info("Tarjeta sin identificar en la fila de nombres: %r", r.texto_ocr)
    salida.sort(key=lambda r: r.caja[0])
    if len(salida) > maximo:
        log.info("Mas tarjetas (%d) que esperadas (%d) en la fila: se dejan las de mayor parecido",
                 len(salida), maximo)
        salida = sorted(sorted(salida, key=lambda r: -r.puntuacion)[:maximo], key=lambda r: r.caja[0])
    return salida


def _reconocidas(recompensas) -> int:
    return sum(1 for r in recompensas if r.item_id != SIN_IDENTIFICAR)


def desplazar(r: Reconocido, dx: int, dy: int) -> Reconocido:
    x, y, w, h = r.caja
    return Reconocido(r.texto_ocr, r.item_id, r.nombre, r.puntuacion, (x + dx, y + dy, w, h))


@dataclass
class Lectura:
    recompensas: list[Reconocido]  # cajas en coordenadas de pantalla
    via: str  # "fila", "franja" o "nada"
    tiempos: dict = field(default_factory=dict)


Capturar = Callable[[Region], object]  # Region -> imagen BGR (numpy) o None
Lento = Callable[[Region, dict], "list[Reconocido] | None"]  # el camino de la franja entera


def leer_pantalla(
    capturar: Capturar,
    ventana: Region,
    motor: MotorOCR,
    casador: CasadorEscalonado,
    esperadas: int | None = None,
    lento: Lento | None = None,
    tiempos: dict | None = None,
    fila: tuple[float, float, float, float] = FILA_NOMBRES,
) -> Lectura | None:
    """Lee la fila de nombres y, si no da lo esperado, la franja entera (`lento`).

    `esperadas` es cuantas tarjetas dice EE.log que hay (None si no lo dijo). La
    fila se da por buena cuando trae al menos esas; si no, se llama a `lento` y
    gana la lectura con mas tarjetas. La geometria de tarjetas solo se aplica
    con la fila de siempre (`FILA_NOMBRES`): con otra (recortes de prueba) se
    agrupa sin ella. Devuelve None si no se pudo capturar.
    """
    tiempos = tiempos if tiempos is not None else {}
    region = region_fila(ventana) if fila == FILA_NOMBRES else ventana.recortar(*fila)
    t0 = time.perf_counter()
    imagen = capturar(region)
    tiempos["captura"] = tiempos.get("captura", 0.0) + time.perf_counter() - t0
    if imagen is None:
        return None
    t0 = time.perf_counter()
    lineas = leer_fila(imagen, motor)
    tiempos["ocr"] = tiempos.get("ocr", 0.0) + time.perf_counter() - t0
    t0 = time.perf_counter()
    grupos = repartir(lineas, ventana, region, esperadas) if fila == FILA_NOMBRES else None
    if grupos is None and lineas:
        lineas = unir_filas(lineas)
    encontrados = casar_fila(lineas, casador, 4, grupos)
    tiempos["casado"] = tiempos.get("casado", 0.0) + time.perf_counter() - t0
    tiempos["lineas"] = len(lineas)
    tiempos["fila"] = f"{imagen.shape[1]}x{imagen.shape[0]}"
    tiempos["geometria"] = grupos is not None
    en_pantalla = [desplazar(r, region.x, region.y) for r in encontrados]
    # Cuentan las tarjetas reconocidas, no las leidas: con la escala del HUD por debajo
    # del 100 % la fila fija corta los nombres por arriba ("RhinoPr rime", "ystemes") y
    # salian cuatro tarjetas sin reconocer que se daban por buenas sin mirar la franja.
    completa = bool(en_pantalla) and (esperadas is None or _reconocidas(en_pantalla) >= esperadas)
    if completa or lento is None:
        return Lectura(en_pantalla, "fila" if en_pantalla else "nada", tiempos)
    otros = lento(ventana, tiempos)
    if otros is None:
        otros = []
    if (_reconocidas(otros), len(otros)) > (_reconocidas(en_pantalla), len(en_pantalla)):
        log.info("La fila de nombres dio %d tarjetas y la franja entera %d: se usa la franja",
                 len(en_pantalla), len(otros))
        return Lectura(otros, "franja", tiempos)
    return Lectura(en_pantalla, "fila" if en_pantalla else "nada", tiempos)


def tira_de_prueba(nombres=("PLANO DE FANG PRIME", "SISTEMAS DE ASH PRIME", "FORMA", "RECEPTOR DE AKBOLTO PRIME")):
    """Tira oscura con nombres claros repartidos como las tarjetas, del tamano de la real a 1440p."""
    import numpy as np

    ancho, alto = 1331, ALTO_FILA
    imagen = np.full((alto, ancho, 3), 16, np.uint8)
    try:
        import cv2
    except ImportError:  # pragma: no cover - cv2 viene con rapidocr
        return imagen
    paso = ancho // len(nombres)
    for i, nombre in enumerate(nombres):
        cv2.putText(imagen, nombre, (i * paso + 12, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (235, 235, 235), 2, cv2.LINE_AA)
    return imagen


def precalentar(motor: MotorOCR) -> None:
    """Primera inferencia de la tira, con dos juegos de anchos de nombre, para que la
    primera reliquia no pague la planificacion de memoria de ONNX Runtime (~100 ms)."""
    inicio = time.monotonic()
    try:
        motor.leer_tira(tira_de_prueba())
        motor.leer_tira(tira_de_prueba(("FORMA", "PLANO DE ORTHOS PRIME", "EMPUNADURA DE QUASSUS PRIME")))
    except Exception as e:  # noqa: BLE001 - es solo un calentamiento
        log.debug("El precalentado de la fila de nombres fallo: %s", e)
        return
    log.info("Fila de nombres precalentada en %.0f ms", (time.monotonic() - inicio) * 1000)
