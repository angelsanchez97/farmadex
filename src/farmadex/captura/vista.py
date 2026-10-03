"""Lo que Farmadex ve solo en el juego, sin atajos: objetos comerciables, agrietados y builds.

Un vigia (`VigiaVistas`) vive en su propio hilo y mira la pantalla con disparadores
baratos; el OCR solo corre cuando un disparador salta:

- Precio de un objeto: el recuadro que saca el juego al pasar el raton por un objeto
  (inventario, comercio, arsenal) lleva, si el objeto es comerciable, el icono de
  "intercambiable" a la derecha de la fila de debajo del titulo. Con el raton quieto se
  captura un trozo a su alrededor y se busca ese icono por su forma (`buscar_icono`,
  ~10 ms). Solo si esta, se lee el titulo del recuadro (~40 ms) y se casa con el catalogo.
  En las capturas reales los planos generales prime (Atlas Prime, Sicarus Prime...) tambien
  llevan el icono; la via sin icono (`PLANO_SIN_ICONO`) esta hecha pero apagada.
- Agrietados: la tarjeta de un agrietado abierto (al revelarlo, al ciclarlo, desde un
  enlace del chat o en su vista de mods) sale grande en medio de la pantalla. Cuando el
  centro cambia y se queda quieto, se mira si hay el morado de su marco
  (`parece_agrietado`); solo entonces se lee la tarjeta con el lector de siempre.
- Build: la pantalla de mejoras del arsenal pone arriba "MEJORAS / EXCALIBUR [30]". Se
  mira una franja fina de arriba; cuando cambia y se queda quieta, se lee solo esa franja
  y, si es esa cabecera, se pide la lectura de la build entera.

Coste en reposo: con el juego delante, el vigia pregunta la posicion del raton y la
ventana activa y captura dos trocitos de pantalla (una tira fina de arriba y un cuadrado
del centro) cada `SONDEO_MS`. Medido a 1440p: 0,04 y 0,12 ms de CPU por captura, o sea
unas tres milesimas de un nucleo. El raton solo se mira cuando se para (un recorte, 0,16 ms
de CPU, unas pocas veces por parada). En partida el juego esconde el cursor y entonces el
vigia no captura nada (`cursor_visible`): solo trabaja en los menus. Nunca hay OCR
continuo, y con el juego detras tampoco se captura nada. Quien juega con mando no ve el
cursor de Windows en los menus: para el siguen valiendo los atajos.

Nunca falsa seguridad: si el nombre no casa con seguridad, no hay precio; si la tarjeta
no se entiende entera, el panel lo dice en vez de evaluar.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..registro_log import obtener
from . import pantalla

log = obtener("vista")

TIC_MS = 50
SONDEO_MS = 50  # franjas de pantalla (build y agrietado)
QUIETO_S = 0.12  # raton quieto este tiempo = esta mirando algo
TOLERANCIA_PX = 4
RADIO_FUERA_PX = 30  # moverse mas que esto desde donde se leyo quita el recuadro de precio
REINTENTO_ICONO_S = 0.15  # con el raton quieto, cada cuanto se vuelve a buscar el icono...
BUSCAR_ICONO_HASTA_S = 1.5  # ...y hasta cuando (el juego tarda un poco en sacar el recuadro)
INTENTOS_TITULO = 3  # lecturas del titulo sin casar antes de rendirse en esta parada
PLANO_TRAS_S = 0.45  # raton quieto este rato sin icono: se prueba si es un plano prime
# Apagado: en las capturas reales (comercio e inventario, 1440p y 4K) los planos generales
# prime SI llevan el icono, y sin el la busqueda por el filete del recuadro colaba nombres
# de otras partes de la pantalla (rejillas, pantallas de reliquias). Se deja hecho por si
# aparece una pantalla de verdad donde falte el icono, pero no se usa.
PLANO_SIN_ICONO = False
COMPROBAR_SIGUE_S = 0.5  # con el precio a la vista, cada cuanto se mira si el recuadro sigue

# -- el icono de "intercambiable" ---------------------------------------------------------
#
# Dos corchetes con una flecha cada uno, a la derecha de la fila del precio en creditos del
# recuadro del juego. La plantilla es la forma media del icono medida en capturas reales
# (1440p y 4K, llevadas a 1080p): 25x28 niveles de gris, guardados aqui para no depender
# de ningun fichero.
#
# Todo se busca con el recorte reducido a como se veria a 1080p (el juego escala su
# interfaz con el alto de la ventana): asi el icono mide siempre lo mismo y buscarlo
# cuesta igual a 4K que a 1080p.
ALTO_REFERENCIA = 1080
ANCHO_ICONO, ALTO_ICONO = 25, 28
ESCALAS_ICONO = (1.0, 1.2, 1.42)  # tamanos de interfaz vistos en capturas reales
UMBRAL_ICONO = 0.86  # medido: los de verdad dan 0,91 o mas; lo demas, 0,79 o menos
UMBRAL_BASTO = 0.55  # primera pasada a media resolucion
# El mismo dibujo es el boton de la pestana de comercio del chat, abajo del todo: ahi no cuenta.
BANDA_CHAT_REL = 0.92
# El trozo que se captura alrededor del raton (fracciones del alto del juego): el recuadro
# del juego sale al lado del objeto, y su cabecera puede quedar bastante por encima.
RECORTE_ANCHO_REL = 1.24
RECORTE_ARRIBA_REL, RECORTE_ABAJO_REL = 0.50, 0.25
# Del icono hacia la izquierda y hacia arriba esta el titulo (fracciones del alto).
TITULO_IZQ_REL, TITULO_ARRIBA_REL = 0.37, 0.095
TITULO_DER_REL = 0.10

_ICONO_B85 = (
    "c-l>pJ7`m37=~+e&VT>^bJDa;Lz|?cAQC|Zk;H%$L2bm*;-Et*8W*Py)<jTj2Nki@!9^Dxt=gI_Dk7-"
    "ZA&XE!5Ueex*h|vnq%BHrM87{-{Kog;{cgNcNLzBjIfWun7$byD6A2+L4Jc(AVE`H-016zOQN{@9$aXVLun7(&I0M81$-"
    "U<WZIc)#LQ+|swrwfUsR+a#f0^9p?dwrs6<v|osnbXMgz!ag&u?vK9^9Rr7!an#{7<rLtC^Ve4ZSHf8jZ^4=GNk<GAtTMSF69~2B"
    "keXy;A#I&CV~^iq|Zc%>wC4?&g_YN_HF={pdK4V&fZyq|zW&`FYGzdSyF$=fha{$hwnIhE0R1+ESFkk+3!Op9p*6Yfe(S0Ho`SVG"
    "2hI$>B_;F6D{<ED}i9enhAgO$%p4#Pd#47zzhc8h{EqV-"
    ")jv4uDIc{{d_OAYV#KL*ih%x)_1sy1;_@#e69NtxzxpfXJ2%j|AW(giGpH3(c*XK+nh*uj(1Wm(_(MouOXV1cdPTMlm4`f%|7G-"
    "w*A)H6HG0IaoYb9OKX`I8$C4IQVw`{pFAaUkUENQ79xtyFmT3<-)`J-"
    "zwFW>7icYz3}YwpL|lb3)25|`*)#KsW<AynUl;rvAkW%UQsTNefK_PGGCo~Ih#K3$L^8muU@|x7KkxB6pkD|JGc7oddR|rT3y}V9"
    "ydXZE5)g~dur;q2NA+3YHw@XVIagICPFaJ9v{Q3l{$zc<cdpa2}(IZI-V2`Bvi-L{0AF0y?_"
)


def plantilla_icono(ancho: int = ANCHO_ICONO, alto: int = ALTO_ICONO):
    """El icono de intercambiable en gris (uint8), al tamano pedido."""
    import base64
    import zlib

    import cv2
    import numpy as np

    base = np.frombuffer(zlib.decompress(base64.b85decode(_ICONO_B85)), np.uint8).reshape(ALTO_ICONO, ANCHO_ICONO)
    if (ancho, alto) == (ANCHO_ICONO, ALTO_ICONO):
        return base.copy()
    return cv2.resize(base, (max(6, int(ancho)), max(6, int(alto))), interpolation=cv2.INTER_LINEAR)


_PLANTILLAS: dict[tuple[int, int], object] = {}


def _plantilla(ancho: int, alto: int):
    hecha = _PLANTILLAS.get((ancho, alto))
    if hecha is None:
        hecha = _PLANTILLAS[(ancho, alto)] = plantilla_icono(ancho, alto)
    return hecha


@dataclass
class IconoEncontrado:
    x: int  # esquina del icono en la imagen
    y: int
    lado: int  # alto del icono
    puntuacion: float
    ancho: int = 0


def buscar_icono(imagen, alto_juego: int, umbral: float = UMBRAL_ICONO, y_maxima: int | None = None) -> IconoEncontrado | None:
    """Busca el icono de intercambiable en `imagen` (BGR). None si no esta.

    El recorte se lleva a su tamano a 1080p y se compara la forma en gris
    (TM_CCOEFF_NORMED): primero a media resolucion, que cuesta la cuarta parte, y solo
    donde se parece se confirma a resolucion entera. `y_maxima` (en pixeles de la imagen)
    deja fuera lo que quede mas abajo (la barra del chat). Devuelve la posicion en
    pixeles de `imagen`.
    """
    import cv2
    import numpy as np

    if imagen is None or imagen.size == 0 or not alto_juego:
        return None
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    f = ALTO_REFERENCIA / float(alto_juego)
    if abs(f - 1.0) > 0.03:
        gris = cv2.resize(gris, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
    else:
        f = 1.0
    if y_maxima is not None:
        gris = gris[: max(0, int(y_maxima * f))]
    if gris.shape[0] < 64 or gris.shape[1] < 64:
        return None
    media = cv2.resize(gris, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    mejor: IconoEncontrado | None = None
    for escala in ESCALAS_ICONO:
        w, h = int(round(ANCHO_ICONO * escala)), int(round(ALTO_ICONO * escala))
        basto = cv2.matchTemplate(media, _plantilla(max(6, w // 2), max(6, h // 2)), cv2.TM_CCOEFF_NORMED)
        plantilla = _plantilla(w, h)
        for _ in range(3):  # los tres mejores sitios de la pasada basta
            _mn, mx, _pmn, pmx = cv2.minMaxLoc(basto)
            if mx < UMBRAL_BASTO:
                break
            x0, y0 = max(0, pmx[0] * 2 - 6), max(0, pmx[1] * 2 - 6)
            zona = gris[y0:y0 + h + 12, x0:x0 + w + 12]
            if zona.shape[0] >= h and zona.shape[1] >= w:
                fino = cv2.matchTemplate(zona, plantilla, cv2.TM_CCOEFF_NORMED)
                _mn2, mx2, _p2, pmx2 = cv2.minMaxLoc(fino)
                if mx2 >= umbral and (mejor is None or mx2 > mejor.puntuacion):
                    mejor = IconoEncontrado(int((x0 + pmx2[0]) / f), int((y0 + pmx2[1]) / f), int(h / f),
                                            float(mx2), int(w / f))
            cv2.rectangle(basto, (max(0, pmx[0] - 6), max(0, pmx[1] - 6)), (pmx[0] + 6, pmx[1] + 6), -1.0, -1)
    return mejor


# -- el titulo del recuadro ---------------------------------------------------------------

# "Plano" en los idiomas del juego (ademas de lo que traiga el glosario del indice).
PALABRAS_PLANO = ("BLUEPRINT", "PLANO", "PLAN", "SCHEMA", "BAUPLAN", "PROGETTO", "PROJEKT", "DIAGRAMA", "PROJETO")


def _llano(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper()


def es_plano_prime(texto: str) -> bool:
    """"NIDUS PRIME BLUEPRINT", "PLANO DE BURSTON PRIME": lo comerciable sin icono."""
    llano = _llano(texto)
    palabras = set(re.findall(r"[A-Z]+", llano))
    return "PRIME" in palabras and any(p in palabras for p in PALABRAS_PLANO)


@dataclass
class Lectura:
    """Lo que ha salido de leer un recuadro de objeto."""

    item_id: int | None = None
    etiqueta: str = ""
    texto: str = ""
    puntuacion: float = 0.0
    rango: int | None = None
    motivo: str = ""  # por que no hay objeto


def lineas_de_titulo(lineas, icono: IconoEncontrado | None, ancho: int = 0):
    """Las lineas del titulo: las que quedan justo encima de la fila del icono, seguidas.

    El titulo va arriba a la izquierda del recuadro, en una o dos lineas (tres como
    mucho), y debajo la fila del precio en creditos con el icono a la derecha. Se sube
    desde esa fila mientras las lineas vayan pegadas; lo que quede mas arriba con un
    hueco es otra cosa de la pantalla. Sin icono (planos prime) valen todas, de arriba abajo.
    """
    if not lineas:
        return []
    if icono is None:
        return sorted(lineas, key=lambda l: (l.y, l.x))
    arriba = [l for l in lineas if l.y + l.alto <= icono.y + icono.lado * 0.25 and l.x < icono.x]
    arriba.sort(key=lambda l: -(l.y + l.alto))
    titulo = []
    suelo = icono.y
    for l in arriba:
        if titulo and l.y + l.alto > titulo[-1].y + titulo[-1].alto * 0.5:
            continue  # en la misma fila que una ya cogida (trozo suelto)
        hueco = suelo - (l.y + l.alto)
        # Entre el titulo y la fila del precio puede ir la fila de rombos de maestria.
        if hueco > l.alto * (3.3 if not titulo else 0.9) or len(titulo) >= 3:
            break
        if titulo and abs(l.x - titulo[-1].x) > l.alto * 2.5:
            break
        titulo.append(l)
        suelo = l.y
    return list(reversed(titulo))


def interpretar_titulo(lineas_titulo, todas, casador, umbral: int = 88, exigir_prime: bool = False) -> Lectura:
    """Casa el titulo con el catalogo; solo devuelve objeto si casa con seguridad."""
    textos = [l.texto.strip() for l in lineas_titulo if l.texto.strip() and not RE_SOLO_CIFRAS.match(l.texto.strip())]
    if not textos:
        return Lectura(motivo="no se ve el nombre")
    # "BUSCAR..." (la caja de busqueda, junto al icono en el inventario en castellano) casaba
    # con el mod "Fetch", que en castellano se llama "Buscar": un nombre de objeto nunca
    # acaba en punto.
    if RE_ACABA_EN_PUNTO.search(textos[-1]):
        return Lectura(texto=" ".join(textos), motivo="acaba en punto: no es un nombre de objeto")
    # El rango no se lee: el recuadro lo ensena con rombos, y el "RANGO 5" que a veces
    # sale en el texto es la descripcion del efecto, no el rango del objeto.
    rango = None
    if exigir_prime:
        # Sin icono no se sabe donde acaba el titulo: cada linea y cada pareja seguida.
        intentos = [" ".join(textos[i:i + 2]) for i in range(len(textos) - 1)] + textos
        intentos = [x for x in intentos if es_plano_prime(x)]
    else:
        # Con icono el titulo son esas lineas enteras: medio titulo es otro objeto.
        intentos = [" ".join(textos)]
    for texto in intentos:
        item_id, etiqueta, puntos = casador.casar(texto, umbral=umbral)
        if item_id is not None and puntos >= umbral:
            return Lectura(item_id, etiqueta, texto, puntos, rango)
    return Lectura(texto=" ".join(textos), rango=rango,
                   motivo="el nombre no es un plano prime" if exigir_prime else "el nombre no casa con seguridad")


RE_SOLO_CIFRAS = re.compile(r"^[\d\s.,/xX%+\-]+$")
RE_ACABA_EN_PUNTO = re.compile(r"[.…]\s*$")

# -- el recuadro sin icono: el filete de debajo del precio -------------------------------

FILETE_MIN_REL, FILETE_MAX_REL = 0.26, 0.45  # largo del filete en fracciones del alto del juego


def buscar_filete(imagen, alto_juego: int):
    """(x, y, largo) del filete horizontal del recuadro del juego en `imagen`, o None.

    Bajo el titulo y el precio en creditos, el recuadro lleva una raya fina clara de casi
    todo su ancho. Se busca una raya de 1-3 px mas clara que lo de encima y lo de debajo
    y de ese largo (las celdas del inventario son mas cortas y las cabeceras mas largas).
    """
    import cv2
    import numpy as np

    if imagen is None or imagen.size == 0 or not alto_juego:
        return None
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    f = ALTO_REFERENCIA / float(alto_juego)
    if abs(f - 1.0) > 0.03:
        gris = cv2.resize(gris, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
    else:
        f = 1.0
    g = gris.astype(np.int16)
    if g.shape[0] < 12:
        return None
    centro = g[3:-3]
    fuera = np.maximum(g[:-6], g[6:])
    raya = ((centro - fuera) > 14).astype(np.uint8)
    minimo, maximo = int(FILETE_MIN_REL * ALTO_REFERENCIA), int(FILETE_MAX_REL * ALTO_REFERENCIA)
    # Tolera huecos pequenos (el filete se difumina en los extremos) y exige el largo.
    raya = cv2.morphologyEx(raya, cv2.MORPH_CLOSE, np.ones((1, 9), np.uint8))
    larga = cv2.morphologyEx(raya, cv2.MORPH_OPEN, np.ones((1, minimo), np.uint8))
    if not larga.any():
        return None
    n, _etq, datos, _c = cv2.connectedComponentsWithStats(larga, connectivity=8)
    mejor = None
    for k in range(1, n):
        x, y, w, h, _a = datos[k]
        if minimo <= w <= maximo and h <= 4 and (mejor is None or w > mejor[2]):
            mejor = (int(x), int(y) + 3, int(w))
    if mejor is None:
        return None
    return int(mejor[0] / f), int(mejor[1] / f), int(mejor[2] / f)


# -- agrietados: el morado del marco ----------------------------------------------------

# Region central donde sale la tarjeta abierta (fracciones del alto del juego, centrada).
CENTRO_ANCHO_REL, CENTRO_ALTO_REL = 0.62, 0.80
# Morado de los agrietados en HSV de OpenCV (H 0-180): el marco, el nombre y el fondo del
# revelado. Medido en las capturas reales del banco.
MORADO_H = (125, 160)
MORADO_S_MIN, MORADO_V_MIN = 60, 70
PARTE_MORADA_MIN = 0.015


def parece_agrietado(imagen) -> bool:
    """Si en el centro hay bastante morado de agrietado como para merecer leer la tarjeta."""
    import cv2
    import numpy as np

    if imagen is None or imagen.size == 0:
        return False
    pequena = cv2.resize(imagen, (160, max(1, int(160 * imagen.shape[0] / imagen.shape[1]))),
                         interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(pequena, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    morado = (h >= MORADO_H[0]) & (h <= MORADO_H[1]) & (s >= MORADO_S_MIN) & (v >= MORADO_V_MIN)
    return float(np.count_nonzero(morado)) / morado.size >= PARTE_MORADA_MIN


# -- build: la cabecera de la pantalla de mejoras -------------------------------------

# Para saber si algo ha cambiado basta un trocito: una tira fina de la franja de arriba y un
# cuadrado pequeno en el centro (donde cae la tarjeta del agrietado). Capturarlos no cuesta
# CPU medible ni a 4K; los trozos grandes solo se capturan cuando estos cambian y se paran.
TESTIGO_FRANJA_REL = (0.030, 0.075)
TESTIGO_CENTRO_REL = 0.16
# La franja de arriba lleva la cabecera y, debajo, la barra de capacidad ("CAPACIDAD 5/74").
# Con 0,13 la barra se quedaba fuera cuando el jugador tiene la interfaz grande o en la
# interfaz antigua (capturas reales en polaco y ruso), y sin ella no habia segundo
# disparador cuando la cabecera esta tapada.
FRANJA_ALTO_REL = 0.16
# La franja se busca (detector) reducida a este alto y se lee a tamano real: medido con las
# capturas reales, reducir tambien la lectura a 4K perdia la cabecera entera.
FRANJA_ALTO_DETECCION = 173
# La barra de capacidad en cada idioma, y como lee el OCR (modelo latino) la rusa
# "ВМЕСТИМОСТЬ" ("BMECTWMOCTb", "BMECTMMOCTb") y la cabecera "УЛУЧШЕНИЯ" ("yJY4WEHMA",
# "yIYWEHMA", "yNyYWEHMA"): parecidos de letras, no una traduccion.
PALABRAS_CAPACIDAD = ("CAPACITY", "CAPACIDAD", "CAPACITE", "CAPACITA", "KAPAZITAT", "CAPACIDADE", "POJEMNOSC",
                      "BMECTWMOCTB", "BMECTMMOCTB")
_CABECERA_RUSA = ("YJYYWEHMA", "YIYWEHMA", "YNYYWEHMA")
RE_CAPACIDAD_NUMEROS = re.compile(r"^\W*-?\d{1,3}\s*/\s*\d{2,3}\W*$")
# La cola de la cabecera con el rango ("RANGO 30", "GRADO 3O", "RANGA 30", "[30]"), sola o
# pegada al final de otra cosa ("14-RIMERANGA30", "18/RPRIMEGRADO30", "PAHI 3O" en ruso).
RE_COLA_RANGO = re.compile(r"(?:RANK|RANGA|RANGO|RANG|NIVEAU|NIVEL|GRADO|STUFE|PAH[A-Z]?)\s*[\dO]{1,2}\W*$|\[\s*[\dO]{1,2}\s*\]")


def _misma_fila(a, b) -> bool:
    return min(a.y + a.alto, b.y + b.alto) - max(a.y, b.y) >= 0.5 * min(a.alto, b.alto)


def _a_la_derecha(linea, lineas):
    """Las lineas que siguen a `linea` en su misma fila, de izquierda a derecha."""
    derecha = [l for l in lineas if l is not linea and l.x >= linea.x + linea.ancho * 0.5 and _misma_fila(linea, l)]
    return sorted(derecha, key=lambda l: l.x)


def es_cabecera_mejoras(lineas) -> bool:
    """Si la franja de arriba es la pantalla de mejoras.

    Tres disparadores, cualquiera vale:
    - la cabecera entera ("UPGRADES / EXCALIBUR [30]") en cualquier idioma, con erratas;
    - la palabra de la cabecera cortada (una ayuda, la camara del streamer o la imagen del
      companero la tapa: "POTENZIA", "ULEPSZ") seguida en su fila por la cola del rango
      ("...PRIME GRADO 30"), tambien en ruso leido con letras latinas;
    - la barra de capacidad ("CAPACIDAD" y "5/74" en la misma fila), que esta debajo de la
      cabecera y se ve aunque una grabacion o un aviso tapen la cabecera entera.
    """
    from ..datos.difuso import fuzz
    from .builds import PALABRAS_CABECERA, es_cabecera, es_resto_de_cabecera

    for linea in lineas:
        texto = linea.texto.strip()
        if es_cabecera(texto) or es_resto_de_cabecera(texto):
            return True
        compacta = re.sub(r"[^A-Z]", "", _llano(texto))
        for palabra in PALABRAS_CABECERA:
            # El OCR se come a veces el principio ("IDGRADES:NYX...") o lo pega todo.
            trozo = compacta[: len(palabra)]
            if len(compacta) > len(palabra) + 2 and len(trozo) == len(palabra) and fuzz.ratio(trozo, palabra) >= 75:
                return True
    for linea in lineas:
        compacta = re.sub(r"[^A-Z]", "", _llano(linea.texto))
        if len(compacta) < 6:
            continue
        derecha = _a_la_derecha(linea, lineas)
        if _es_capacidad(compacta) and any(RE_CAPACIDAD_NUMEROS.match(_llano(l.texto)) for l in derecha):
            return True
        if _es_cabecera_cortada(compacta):
            cola = " ".join(_llano(l.texto) for l in [linea] + derecha)
            if RE_COLA_RANGO.search(re.sub(r"[^A-Z0-9\[\]/ ]", "", cola)):
                return True
    return False


def _es_capacidad(compacta: str) -> bool:
    from ..datos.difuso import fuzz

    return any(fuzz.ratio(compacta, p) >= 80 for p in PALABRAS_CAPACIDAD)


def _es_cabecera_cortada(compacta: str) -> bool:
    """"ULEPSZ", "POTENZIA", "yJY4WEHMA..." (en ruso): el principio de la palabra de la cabecera."""
    from ..datos.difuso import fuzz
    from .builds import PALABRAS_CABECERA

    for palabra in list(PALABRAS_CABECERA) + list(_CABECERA_RUSA):
        n = min(len(compacta), len(palabra))
        if n >= 6 and fuzz.ratio(compacta[:n], palabra[:n]) >= (80 if palabra in _CABECERA_RUSA else 85):
            return True
    return False


# -- se esta en un menu o jugando? --------------------------------------------------------


def cursor_visible() -> bool:
    """Si Windows esta pintando el cursor. En partida el juego lo esconde; en los menus
    (arsenal, inventario, comercio, chat, un agrietado abierto) se ve. Es lo que le cuesta
    cero al vigia mientras se juega: sin cursor no captura nada. Si no se puede saber, True.
    """
    import ctypes
    from ctypes import wintypes

    class CURSORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hCursor", wintypes.HANDLE),
                    ("ptScreenPos", wintypes.POINT)]

    try:
        info = CURSORINFO()
        info.cbSize = ctypes.sizeof(CURSORINFO)
        if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(info)):
            return True
        return bool(info.flags & 0x1)  # CURSOR_SHOWING
    except (AttributeError, OSError):
        return True


# -- huellas ------------------------------------------------------------------------------


def huella(imagen, lado: int = 32):
    from .perfil_equipo import huella as h

    return h(imagen, lado)


def distinta(a, b, umbral: float = 6.0) -> bool:
    from .perfil_equipo import distinta as d

    return d(a, b, umbral)


class Quieta:
    """Una franja de pantalla: avisa una vez cuando cambia y se queda quieta."""

    def __init__(self, umbral: float = 5.0):
        self.umbral = umbral
        self.anterior = None
        self.ultima = None
        self.iguales = 0
        self.t_cambio = 0.0  # monotonic del primer fotograma distinto (cuando aparecio)

    def observar(self, imagen, ahora: float) -> bool:
        h = huella(imagen)
        if h is None:
            return False
        if distinta(h, self.anterior, self.umbral):
            if self.iguales >= 1 or self.anterior is None:
                self.t_cambio = ahora
            self.anterior = h
            self.iguales = 1
            return False
        self.iguales += 1
        if self.iguales != 2:
            return False
        if not distinta(h, self.ultima, self.umbral):
            return False
        self.ultima = h
        return True

    def olvidar(self) -> None:
        self.anterior = self.ultima = None
        self.iguales = 0


# -- el vigia -------------------------------------------------------------------------


# Tras el aviso de EE.log de una pantalla de reliquia, cuanto se deja de mirar como mucho
# (si el aviso de que se cerro no llega). Igual que el lector pasivo.
PAUSA_RELIQUIA_S = 20.0


class VigiaVistas(QObject):
    """Vive en su hilo. `iniciar()` arranca el temporizador; todo lo demas va por senales."""

    leyendo_precio = Signal(object)  # (x, y) del raton: el icono esta, sale "Leyendo…"
    objeto_visto = Signal(object)  # ui.vista_objeto.ObjetoVisto
    sin_objeto = Signal(str)  # habia icono pero no se sabe que es
    objeto_fuera = Signal()  # el recuadro del juego se ha ido (o el raton)
    riven_visto = Signal(object, float)  # TarjetaLeida, monotonic de cuando aparecio
    riven_fuera = Signal()
    build_vista = Signal(float)  # la pantalla de mejoras esta delante: leer la build

    def __init__(self, motor_ocr: str = "rapidocr", precio: bool = True, rivens: bool = True,
                 builds: bool = True, parent=None):
        super().__init__(parent)
        self.motor_nombre = motor_ocr
        self.motor = None
        self.activo_precio = precio
        self.activo_rivens = rivens
        self.activo_builds = builds
        self.casador = None
        self.con = None
        self._slugs: dict[int, tuple[str | None, str | None]] = {}
        self.lector_riven = None
        self._precalentar_pendiente = False  # se pide al arrancar; se hace con el juego delante
        self._temporizador: QTimer | None = None
        self._ocupado = False
        self._hwnd = None
        self._hwnd_hasta = 0.0
        self.pantalla_log: str | None = None
        # raton
        self._pos = None
        self._t_mov = 0.0
        self._t_ultimo_intento = 0.0
        self._resuelto = False  # ya hay respuesta para esta parada del raton
        self._plano_probado = False
        self._avisado = False  # ya salio "Leyendo…" en esta parada
        self._fallos = 0
        self._via = "icono"
        self.ultima_lectura = None
        self._mostrando: tuple[int, int] | None = None  # donde estaba el raton al ensenar el precio
        self._t_comprobado = 0.0
        self._t_icono_visto = 0.0
        # franjas
        self._t_sondeo = 0.0
        self.franja_build = Quieta()
        self.franja_centro = Quieta()
        self._riven_a_la_vista = False
        self._build_a_la_vista = False
        self._reliquia_hasta = 0.0  # monotonic hasta el que hay una pantalla de reliquia
        # medidas
        self.sondeos = 0
        self.lecturas = {"precio": 0, "riven": 0, "build": 0}
        self.ms_ultimo: dict[str, float] = {}

    # -- control --

    @Slot()
    def iniciar(self) -> None:
        if self._temporizador is not None:
            return
        self._temporizador = QTimer(self)
        self._temporizador.setInterval(TIC_MS)
        self._temporizador.timeout.connect(self.tic)
        self._temporizador.start()
        log.info("Vigia de vistas en marcha (precio=%s, agrietados=%s, builds=%s)",
                 self.activo_precio, self.activo_rivens, self.activo_builds)
        self._precalentar_pendiente = True

    @Slot()
    def _precalentar(self) -> None:
        """Deja listos el casador, el motor y el lector de agrietados antes de la primera vista.

        Si no, la primera tarjeta que se ve en la sesion paga esa carga (casi un segundo en un PC normal).
        Se hace en el primer tic con el juego delante: al abrir Farmadex trababa la ventana un cuarto de segundo
        (el hilo del vigia y el de la ventana se reparten Python). Sin indice todavia no hace nada: se preparara
        al leer, como siempre."""
        try:
            if self.preparar() and self.activo_rivens:
                self._lector_riven()
        except Exception:  # noqa: BLE001 - es solo adelantar trabajo: al leer se reintenta
            log.debug("El vigia no pudo precalentarse", exc_info=True)

    @Slot()
    def parar(self) -> None:
        if self._temporizador is not None:
            self._temporizador.stop()

    @Slot(bool)
    def activar_precio(self, activo: bool) -> None:
        self.activo_precio = activo

    @Slot(bool)
    def activar_rivens(self, activo: bool) -> None:
        self.activo_rivens = activo
        self.franja_centro.olvidar()

    @Slot(bool)
    def activar_builds(self, activo: bool) -> None:
        self.activo_builds = activo
        self.franja_build.olvidar()

    @Slot(str)
    def cambiar_motor(self, motor_ocr: str) -> None:
        from .ocr import MotorOCR

        MotorOCR.olvidar_fallo(motor_ocr)
        self.motor_nombre = motor_ocr
        self.motor = None

    @Slot(str, str)
    def pantalla_juego(self, accion: str, nombre: str) -> None:
        self.pantalla_log = nombre if accion == "abierta" else ("pausa" if accion == "pausa" else None)

    @Slot(str)
    def evento(self, nombre: str) -> None:
        """Los avisos de EE.log de la pantalla de recompensas de reliquia: mientras esta
        abierta no se mira nada. Ahi no hay precio, agrietado ni build que sacar, y una
        lectura del vigia a la vez que la de las recompensas la hacia esperar (medido con la
        autoprueba y el PC cargado: de 150 ms a mas de 500)."""
        if nombre in ("reliquia_abierta", "reliquia_recompensas"):
            self._reliquia_hasta = time.monotonic() + PAUSA_RELIQUIA_S
        elif nombre in ("reliquia_cerrada", "reliquia_elegida"):
            self._reliquia_hasta = 0.0

    @property
    def activo(self) -> bool:
        return self.activo_precio or self.activo_rivens or self.activo_builds

    # -- preparacion --

    def _motor(self):
        if self.motor is None:
            from .ocr import MotorOCR

            self.motor = MotorOCR(self.motor_nombre)
        return self.motor

    def preparar(self) -> bool:
        """Casador de objetos comerciables y lector de tarjetas; False si aun no hay indice."""
        if self.casador is not None:
            return True
        from ..datos import indice
        from .ocr import Casador

        if not indice.hay_indice():
            return False
        con = indice.conectar()
        self.con = con
        try:
            self.casador = Casador(con)
            self._slugs = {}
            for iid, slug, padre_slug, comerciable in con.execute(
                "SELECT i.id, i.market_slug, p.market_slug, i.comerciable FROM items i "
                "LEFT JOIN items p ON p.id = i.padre_id WHERE i.market_slug IS NOT NULL"
            ):
                self._slugs[iid] = (slug, padre_slug)
        except Exception:  # noqa: BLE001 - indice a medio construir: se reintenta luego
            log.exception("No se pudo preparar el vigia de vistas")
            self.casador = None
            return False
        pantalla.declarar_dpi()
        try:  # la primera lectura no paga la carga del motor ni la del casador
            self._motor().precalentar()
            self.casador.casar("AKARIUS PRIME LINK", umbral=88)
        except Exception:  # noqa: BLE001 - sin motor se dira al leer
            log.debug("El vigia no pudo precalentar el motor OCR")
        return True

    def _lector_riven(self):
        if self.lector_riven is None:
            from ..agrietados.lector import LectorTarjeta
            from .agrietados import armas_conocidas

            armas = armas_conocidas(self.con)
            if armas:
                self.lector_riven = LectorTarjeta(armas)
        return self.lector_riven

    # -- bucle --

    def _ventana_juego(self):
        ahora = time.monotonic()
        if ahora >= self._hwnd_hasta:
            self._hwnd = pantalla.ventana_juego()
            self._hwnd_hasta = ahora + 2.0
        return self._hwnd

    @Slot()
    def tic(self) -> None:
        if self._ocupado or not self.activo:
            return
        if time.monotonic() < self._reliquia_hasta:
            return  # pantalla de recompensas de reliquia: la CPU es para leerlas
        self._ocupado = True
        try:
            hwnd = self._ventana_juego()
            if not hwnd or pantalla._ventana_activa() != hwnd:
                self._juego_detras()
                return
            if self._precalentar_pendiente:
                # Una vez, al ver el juego delante (no al abrir Farmadex, que la ventana se notaria).
                self._precalentar_pendiente = False
                self._precalentar()
            if not cursor_visible():
                # En partida (el juego esconde el cursor) no se mira nada de nada.
                self._juego_detras()
                self.franja_build.olvidar()
                return
            region = pantalla.region_ventana(hwnd)
            if region is None:
                return
            ahora = time.monotonic()
            if self.activo_precio:
                self._mirar_raton(region, ahora)
            if (self.activo_rivens or self.activo_builds) and ahora - self._t_sondeo >= SONDEO_MS / 1000:
                self._t_sondeo = ahora
                self._sondear(region, ahora)
        except Exception:  # noqa: BLE001 - un fallo aqui no puede tumbar el hilo
            log.exception("Fallo en el vigia de vistas")
        finally:
            self._ocupado = False

    def _fuera_de_juego(self) -> None:
        if self._mostrando is not None:
            self._mostrando = None
            self.objeto_fuera.emit()
        self._pos = None

    def _juego_detras(self) -> None:
        """El juego ya no esta delante: fuera los recuadros, y al volver se mira de nuevo."""
        self._fuera_de_juego()
        if self._riven_a_la_vista:
            self._riven_a_la_vista = False
            self.riven_fuera.emit()
            self.franja_centro.olvidar()

    # -- precio bajo el raton --

    def _mirar_raton(self, region, ahora: float) -> None:
        x, y = pantalla._posicion_cursor()
        if not region.contiene(x, y):
            self._fuera_de_juego()
            return
        if self._pos is None or abs(x - self._pos[0]) > TOLERANCIA_PX or abs(y - self._pos[1]) > TOLERANCIA_PX:
            self._pos = (x, y)
            self._t_mov = ahora
            self._resuelto = False
            self._plano_probado = False
            self._avisado = False
            self._fallos = 0
            if self._mostrando is not None and (abs(x - self._mostrando[0]) > RADIO_FUERA_PX
                                                or abs(y - self._mostrando[1]) > RADIO_FUERA_PX):
                self._mostrando = None
                self.objeto_fuera.emit()
            return
        quieto = ahora - self._t_mov
        if self._mostrando is not None:
            # Con el precio a la vista: si el recuadro del juego se va (el raton sigue
            # quieto pero se cerro el inventario), fuera tambien el nuestro.
            if ahora - self._t_comprobado >= COMPROBAR_SIGUE_S:
                self._t_comprobado = ahora
                imagen, r = self._recorte(region, x, y)
                if imagen is not None and self._via == "icono" and buscar_icono(
                        imagen, region.alto, y_maxima=self._y_maxima(region, r)) is None:
                    self._mostrando = None
                    self.objeto_fuera.emit()
            return
        if self._resuelto or quieto < QUIETO_S or quieto > BUSCAR_ICONO_HASTA_S:
            return
        if ahora - self._t_ultimo_intento < REINTENTO_ICONO_S:
            return
        self._t_ultimo_intento = ahora
        # Los planos prime sin icono: una sola vez por parada y cuando el icono ya habria salido.
        plano = PLANO_SIN_ICONO and quieto >= PLANO_TRAS_S and not self._plano_probado
        if plano:
            self._plano_probado = True
        objeto = self.leer_recuadro(region, x, y, t_visto=max(self._t_mov, ahora - REINTENTO_ICONO_S), plano=plano)
        self._via = objeto.via if objeto is not None else self._via

    def _recorte(self, region, x: int, y: int):
        ancho = min(region.ancho, int(region.alto * RECORTE_ANCHO_REL))
        arriba, abajo = int(region.alto * RECORTE_ARRIBA_REL), int(region.alto * RECORTE_ABAJO_REL)
        alto = min(region.alto, arriba + abajo)
        rx = max(region.x, min(x - ancho // 2, region.x + region.ancho - ancho))
        ry = max(region.y, min(y - arriba, region.y + region.alto - alto))
        recorte = pantalla.Region(rx, ry, ancho, alto)
        imagen = pantalla.capturar_sin_ocultar(recorte)
        if imagen is not None:
            imagen = pantalla.descartar_propias(imagen, recorte)
        return imagen, recorte

    def _y_maxima(self, region, recorte) -> int:
        """Hasta que fila del recorte se busca el icono (por debajo esta la barra del chat)."""
        return int(region.y + region.alto * BANDA_CHAT_REL - recorte.y)

    def leer_recuadro(self, region, x: int, y: int, t_visto: float = 0.0, plano: bool = False):
        """Busca el icono junto al raton y, si esta, lee y casa el titulo. Devuelve el ObjetoVisto o None."""
        imagen, recorte = self._recorte(region, x, y)
        if imagen is None:
            return None
        return self.leer_recorte(imagen, recorte, region, x, y, t_visto, plano)

    def leer_recorte(self, imagen, recorte, region, x: int, y: int, t_visto: float = 0.0, plano: bool = False):
        icono = buscar_icono(imagen, region.alto, y_maxima=self._y_maxima(region, recorte))
        if icono is None:
            if not plano:
                return None
            filete = buscar_filete(imagen, region.alto)
            if filete is None:
                return None
            return self._leer_titulo(imagen, recorte, region, None, x, y, t_visto, filete=filete)
        if not self._avisado:
            self._avisado = True
            self.leyendo_precio.emit((x, y))
        objeto = self._leer_titulo(imagen, recorte, region, icono, x, y, t_visto)
        if objeto is None:
            # El recuadro del juego aparece fundiendose: a medio salir el titulo no se lee.
            # Se vuelve a probar un par de veces antes de darlo por no reconocido.
            self._fallos += 1
            if self._fallos >= INTENTOS_TITULO:
                self._resuelto = True
                self.sin_objeto.emit("")
        return objeto

    def _leer_titulo(self, imagen, recorte, region, icono, x, y, t_visto, filete=None):
        from ..ui.vista_objeto import ObjetoVisto
        from .ocr import ErrorMotorOCR, unir_filas

        if not self.preparar():
            return None
        h = region.alto
        if icono is not None:
            x0 = max(0, icono.x - int(h * TITULO_IZQ_REL))
            y0 = max(0, icono.y - int(h * TITULO_ARRIBA_REL))
            # Un titulo largo sigue a la derecha del icono ("ACCELTRA PRIME BLUEPRINT" a 1440p
            # acababa 0,065 h mas alla y se leia "BLUEPR"): el recorte llega hasta el borde del
            # recuadro. Lo que empiece a la derecha del icono no es titulo (lineas_de_titulo).
            x1 = min(imagen.shape[1], icono.x + (icono.ancho or icono.lado) + int(h * TITULO_DER_REL))
            y1 = min(imagen.shape[0], icono.y + int(icono.lado * 1.25))
        else:
            fx, fy, largo = filete
            x0, x1 = max(0, fx - int(h * 0.01)), min(imagen.shape[1], fx + largo + int(h * 0.01))
            y0, y1 = max(0, fy - int(h * 0.135)), fy
        trozo = imagen[y0:y1, x0:x1]
        if trozo.size == 0:
            return None
        # A 4K las letras miden el doble de lo que hace falta: se lee como a 1440p.
        escala = min(1.0, 1440.0 / h)
        if escala < 0.97:
            import cv2

            trozo = cv2.resize(trozo, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
        else:
            escala = 1.0
        t0 = time.perf_counter()
        try:
            lineas = [l for l in unir_filas(self._motor().leer_tira(trozo)) if l.confianza >= 0.5]
        except ErrorMotorOCR as e:
            log.warning("Vigia de vistas sin motor OCR: %s", e)
            self.activo_precio = False
            return None
        self.lecturas["precio"] += 1
        for l in lineas:  # a coordenadas del recorte
            l.x, l.y = int(l.x / escala) + x0, int(l.y / escala) + y0
            l.ancho, l.alto = int(l.ancho / escala), int(l.alto / escala)
        titulo = lineas_de_titulo(lineas, icono)
        lectura = interpretar_titulo(titulo, lineas, self.casador, exigir_prime=icono is None)
        ms = (time.perf_counter() - t0) * 1000
        self.ms_ultimo["precio_ocr"] = ms
        self.ultima_lectura = lectura
        slug, slug_set = self._slugs.get(lectura.item_id, (None, None)) if lectura.item_id else (None, None)
        if slug and slug.endswith("_set"):
            # Un set entero no es un objeto del inventario: seria medio titulo ("ASH PRIME"
            # de "ASH PRIME CHASSIS BLUEPRINT"). Mejor nada que el precio de otra cosa.
            lectura.motivo, slug = "solo se ha leido parte del nombre", None
        if icono is None and slug and not slug.endswith("_blueprint"):
            lectura.motivo, slug = "sin icono solo valen los planos prime", None
        if lectura.item_id is None or not slug:
            motivo = lectura.motivo or "sin precio en warframe.market"
            log.info("Recuadro de objeto sin casar (%s): %r en %.0f ms", motivo, lectura.texto, ms)
            return None
        if icono is not None:
            ancho_caja = int(h * 0.40)
            derecha = icono.x + (icono.ancho or icono.lado) + int(h * 0.02)
            arriba = (titulo[0].y if titulo else icono.y) - int(h * 0.012)
            caja_pantalla = (recorte.x + derecha - ancho_caja, recorte.y + arriba, ancho_caja, int(h * 0.20))
        else:
            caja_pantalla = (recorte.x + x0, recorte.y + y0, x1 - x0, int(h * 0.22))
        objeto = ObjetoVisto(lectura.item_id, slug, lectura.etiqueta, lectura.rango,
                             slug_set if slug_set and slug_set.endswith("_set") else None,
                             caja_pantalla, (x, y), t_visto or time.monotonic(),
                             "icono" if icono is not None else "prime")
        log.info("Objeto a la vista: %r -> %s (%s, rango %s) en %.0f ms", lectura.texto, lectura.etiqueta,
                 slug, lectura.rango, ms)
        self._resuelto = True
        self._mostrando = (x, y)
        self._t_comprobado = time.monotonic()
        self.objeto_visto.emit(objeto)
        return objeto

    # -- franjas: agrietado y build --

    def _capturar_limpia(self, zona):
        """La zona tal cual, o None si alguna ventana de Farmadex la tapa (entonces no se mira:
        al quitarla pareceria que la pantalla acaba de cambiar y se leeria otra vez)."""
        cruda = pantalla.capturar_sin_ocultar(zona)
        if cruda is None:
            return None
        limpia = pantalla.descartar_propias(cruda, zona)
        return cruda if limpia is cruda else None

    def _sondear(self, region, ahora: float) -> None:
        """Mira dos trocitos de pantalla (unos pocos miles de pixeles); el trozo grande solo
        se captura cuando el pequeno ha cambiado y se ha quedado quieto."""
        self.sondeos += 1
        h = region.alto
        if self.activo_builds and self.pantalla_log not in ("pausa",):
            testigo = pantalla.Region(region.x, region.y + int(h * TESTIGO_FRANJA_REL[0]), region.ancho,
                                      max(4, int(h * (TESTIGO_FRANJA_REL[1] - TESTIGO_FRANJA_REL[0]))))
            imagen = self._capturar_limpia(testigo)
            if imagen is not None and self.franja_build.observar(imagen, ahora):
                franja = pantalla.Region(region.x, region.y, region.ancho, max(8, int(h * FRANJA_ALTO_REL)))
                entera = self._capturar_limpia(franja)
                if entera is not None:
                    self.mirar_cabecera(entera, self.franja_build.t_cambio)
        if self.activo_rivens:
            lado = max(16, int(h * TESTIGO_CENTRO_REL))
            testigo = pantalla.Region(region.x + (region.ancho - lado) // 2, region.y + (h - lado) // 2, lado, lado)
            imagen = self._capturar_limpia(testigo)
            if imagen is None:
                return
            nueva = self.franja_centro.observar(imagen, ahora)
            if self._riven_a_la_vista and self.franja_centro.iguales == 1:
                # El centro ha cambiado: la tarjeta se ha ido (o es otra).
                self._riven_a_la_vista = False
                self.riven_fuera.emit()
            if nueva:
                ancho = min(region.ancho, int(h * CENTRO_ANCHO_REL))
                alto = int(h * CENTRO_ALTO_REL)
                centro = pantalla.Region(region.x + (region.ancho - ancho) // 2, region.y + (h - alto) // 2, ancho, alto)
                entera = self._capturar_limpia(centro)
                if entera is not None:
                    self.mirar_centro(entera, region, self.franja_centro.t_cambio)

    def mirar_cabecera(self, imagen, t_visto: float = 0.0) -> bool:
        from .ocr import ErrorMotorOCR, unir_filas

        try:
            lineas = [l for l in unir_filas(self._motor().leer_tira(imagen, alto_deteccion=FRANJA_ALTO_DETECCION))
                      if l.confianza >= 0.3]
        except ErrorMotorOCR:
            return False
        self.lecturas["build"] += 1
        es = es_cabecera_mejoras(lineas)
        if es and not self._build_a_la_vista:
            log.info("Pantalla de mejoras a la vista (%s)", " | ".join(l.texto for l in lineas[:3]))
            self.build_vista.emit(t_visto or time.monotonic())
        self._build_a_la_vista = es
        return es

    def mirar_centro(self, imagen, region, t_visto: float = 0.0):
        """Si hay morado de agrietado en el centro, lee la tarjeta; emite solo si se reconoce."""
        if not parece_agrietado(imagen):
            return None
        if not self.preparar():
            return None
        lector = self._lector_riven()
        if lector is None:
            return None
        from .agrietados import leer_tarjeta
        from .ocr import ErrorMotorOCR

        t0 = time.perf_counter()
        try:
            tarjeta = leer_tarjeta(imagen, self._motor(), lector)
        except ErrorMotorOCR:
            return None
        self.lecturas["riven"] += 1
        ms = (time.perf_counter() - t0) * 1000
        # Solo cuenta si es una tarjeta de verdad: arma reconocida o velada.
        if tarjeta.velado or (tarjeta.arma_slug and tarjeta.estadisticas):
            log.info("Agrietado a la vista: %s %s (fiable=%s) en %.0f ms", tarjeta.arma_slug, tarjeta.nombre,
                     tarjeta.fiable, ms)
            self._riven_a_la_vista = True
            self.riven_visto.emit(tarjeta, t_visto or time.monotonic())
            return tarjeta
        log.debug("Morado en el centro pero sin tarjeta de agrietado (%.0f ms)", ms)
        return None
