"""Lectura de la pantalla de fin de mision: cuanto has recogido de cada recurso.

Por que la pantalla y no EE.log (medido el 1 de octubre de 2026 sobre un EE.log
real de 204.753 lineas y 29 misiones terminadas): el juego NO escribe en el log
ni lo que recoges por el suelo ni el resumen de la mision. Los nombres de los
recursos (`/Lotus/Types/Items/MiscItems/Plastids`...) salen una sola vez, cuando
el juego carga el tipo, nunca con cantidades. Lo unico con cantidad son los
premios de etapa de los contratos de las llanuras ("Got Reward ... with count").
EE.log solo sirve para saber CUANDO ha acabado la mision
(`EndOfMatch.lua: Mission Succeeded`).

Lo que se ve en capturas reales de la pantalla (15 de la comunidad de Steam,
720p a 1440p, ingles, castellano y portugues; ver tests/test_fin_mision.py):

- A la derecha, una rejilla de placas cuadradas. Cada placa lleva la cantidad
  arriba a la izquierda ("1,196") y el nombre abajo, centrado, en una o dos
  lineas ("Paquete De" / "Polímeros"). Una placa sin cifra es 1 unidad.
- En la interfaz actual, delante de la cifra hay un icono redondo con una marca.
  El OCR lo lee a veces como un "0" o un "?" pegado delante ("0360" por 360,
  "?30" por 30) y a veces no lo lee. Un cero delante nunca es parte de la cifra.
- El separador de miles cambia con el idioma del juego (coma, punto, espacio) y
  el OCR a veces se lo come ("153808" por "153,808").
- La rejilla tiene barra de desplazamiento: con mucho botin, el recurso puede no
  estar a la vista. Y una cifra de un solo digito a veces no se detecta.

De ahi las reglas, todas pensadas para no sumar NUNCA una cantidad dudosa:

1. El nombre tiene que casar con el recurso sin ambiguedad (igual, o casi igual
   y sin otro recurso parecido).
2. Tiene que haber exactamente una cifra en el sitio de la placa donde va.
3. La cifra se lee dos veces por caminos distintos: la del OCR de la pantalla
   entera y otra del recorte ampliado de la propia cifra, ya sin el icono. Si no
   dan lo mismo, no vale.
4. Con separadores, los grupos tienen que ser de tres cifras.
5. Lo mismo se tiene que leer en dos capturas seguidas (`LectorFinMision`).

Lo que no cumple todo eso no se suma y se dice ("no he podido leer X").
Sin cifra a la vista no se da por hecho que sea 1: puede ser una cifra que el
OCR no ha visto.

Coste: nada en reposo. Solo al acabar una mision, y solo si hay algun recurso
como meta sin completar, se hacen entre 2 y `MAX_LECTURAS` lecturas.
"""

from __future__ import annotations

import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..registro_log import obtener
from . import pantalla
from .lector_pasivo import ALTO_DETECCION_PASIVA, motor_de_fondo
from .ocr import ErrorMotorOCR, Leido, MotorOCR

log = obtener("fin_mision")

# Geometria de la placa, sin depender de la resolucion: la cifra esta arriba a la
# izquierda y el nombre abajo en el centro, asi que (centro del nombre - borde izquierdo
# de la cifra) / (pie del nombre - techo de la cifra) vale ~0,5 en todas las capturas
# medidas (0,48-0,53; 0,33 si la caja de la cifra no coge el icono). El vecino de al lado
# da mas de 1,5 y el de la fila de arriba, menos de 0,23.
RAZON_MIN, RAZON_MAX = 0.30, 0.62
# Alto de ese tramo (casi la placa entera) respecto al alto de la ventana: 0,15 medido
# de 720p a 1440p. El margen cubre la escala de menus del juego.
ALTO_MIN, ALTO_MAX = 0.07, 0.30
MINIMO_CONFIANZA_NOMBRE = 0.60
MINIMO_CONFIANZA_CIFRA = 0.50
# La segunda lectura (el recorte de la cifra, sin buscar cajas) da confianzas mas bajas
# con un solo digito: un "4" bien leido se queda en 0,50. Lo que protege es que coincidan.
MINIMO_CONFIANZA_SEGUNDA = 0.25
# Con un solo digito el reconocedor da aun menos (un "7" o un "2" bien leidos se quedan en
# 0,21-0,30 en capturas reales de 1080p): vale si las DOS relecturas (dos escalas) dicen lo
# mismo que la primera, o una sola con 0,4.
MINIMO_CONFIANZA_UN_DIGITO = 0.2
CONFIANZA_UN_DIGITO_SOLA = 0.4
# Parecido minimo de un nombre que no casa letra a letra, y ventaja sobre el segundo.
MINIMO_PARECIDO = 92.0
VENTAJA_PARECIDO = 6.0

# Motivos por los que un recurso no se suma (para el aviso al usuario y el registro).
NO_VISTO = "no_visto"            # su placa no esta a la vista (o el nombre no se ha leido)
SIN_CIFRA = "sin_cifra"          # la placa esta, pero no se ve cifra (puede ser 1... o no)
CIFRA_DUDOSA = "cifra_dudosa"    # la cifra no supera las comprobaciones
NO_REPETIDA = "no_repetida"      # dos capturas seguidas no dan lo mismo

# Delante puede ir el icono leido como un signo ("?30"); detras, nada: "8%" o "46 asesinatos"
# son estadisticas de la escuadra, no cantidades.
_RE_SOLO_CIFRA = re.compile(r"^\D{0,2}\d[\d.,'   ]*$")
_RE_GRUPOS = re.compile(r"^\d{1,3}(?:[.,'   ]\d{3})+$")


def normalizar(texto: str) -> str:
    """Minusculas, sin tildes y solo letras y cifras: "Placa DeAleación" -> "placadealeacion"."""
    plano = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in plano.lower() if c.isalnum() and not unicodedata.combining(c))


def cifra_de(texto: str) -> int | None:
    """La cantidad escrita en una caja de cifra, o None si no se puede asegurar.

    "1,196" -> 1196; "0360" y "?30" (el icono leido como 0 o ?) -> 360 y 30;
    "153808" -> 153808; "12,7" (cortada) -> None; "0" -> None.
    """
    t = (texto or "").strip()
    if not _RE_SOLO_CIFRA.match(t):
        return None
    t = re.sub(r"^\D+", "", t).rstrip()
    t = t.lstrip("0")  # el icono de delante leido como cero; una cantidad no empieza por 0
    t = re.sub(r"^\D+", "", t)
    if not t:
        return None
    if t.isdigit():
        valor = int(t)
    elif _RE_GRUPOS.match(t):
        valor = int(re.sub(r"\D", "", t))
    else:
        return None
    return valor if 0 < valor <= 9_999_999 else None


def es_caja_de_cifra(texto: str) -> bool:
    return bool(_RE_SOLO_CIFRA.match((texto or "").strip()))


# -- nombres ------------------------------------------------------------------------


@dataclass
class Nombres:
    """Los nombres de todos los recursos del indice, para casar sin confundir uno con otro."""

    por_clave: dict[str, set[str]] = field(default_factory=dict)  # normalizado -> unique_names

    @classmethod
    def del_indice(cls, indice: sqlite3.Connection) -> "Nombres":
        nombres = cls()
        try:
            filas = indice.execute(
                "SELECT unique_name, nombre_en, nombre_es FROM items WHERE categoria = 'Resources'"
            ).fetchall()
        except sqlite3.Error:
            return nombres
        for unico, en, es in filas:
            nombres.anadir(unico, en, es)
        return nombres

    def anadir(self, unique_name: str, *textos: str | None) -> None:
        for texto in textos:
            clave = normalizar(texto or "")
            if len(clave) >= 3:
                self.por_clave.setdefault(clave, set()).add(unique_name)

    def casar(self, texto: str, buscados: set[str] | None = None) -> str | None:
        """El unique_name del recurso que se llama asi, o None si hay duda.

        Un mismo nombre puede ser varios objetos del indice ("Salvage" es el recurso y
        cuatro premios de tutorial; "Kuva", el recurso y el de la tienda): si solo uno de
        ellos esta entre los `buscados`, es ese.
        """
        clave = normalizar(texto)
        if len(clave) < 3:
            return None
        exactos = self.por_clave.get(clave)
        if exactos:
            return self._unico(exactos, buscados)
        if len(clave) < 6:
            return None  # en nombres cortos una letra cambiada ya es otro recurso
        from rapidfuzz import fuzz, process

        mejores = process.extract(clave, list(self.por_clave), scorer=fuzz.ratio, limit=3,
                                  score_cutoff=MINIMO_PARECIDO - VENTAJA_PARECIDO)
        if not mejores or mejores[0][1] < MINIMO_PARECIDO:
            return None
        ganadores = self.por_clave[mejores[0][0]]
        ganador = self._unico(ganadores, buscados)
        if ganador is None:
            return None
        for otra, puntos, _ in mejores[1:]:
            if puntos > mejores[0][1] - VENTAJA_PARECIDO and self.por_clave[otra] != ganadores:
                return None  # hay otro recurso casi igual de parecido
        return ganador

    @staticmethod
    def _unico(candidatos: set[str], buscados: set[str] | None) -> str | None:
        if len(candidatos) == 1:
            return next(iter(candidatos))
        if buscados:
            entre = candidatos & buscados
            if len(entre) == 1:
                return next(iter(entre))
        return None


# -- interpretar las lineas del OCR ---------------------------------------------------


@dataclass
class Placa:
    """Una placa de la rejilla cuyo nombre es un recurso buscado."""

    unique_name: str
    texto: str
    caja_nombre: tuple[int, int, int, int]  # x, y, ancho, alto
    cifra: Leido | None = None
    cantidad: int | None = None
    motivo: str = ""  # vacio si la cantidad vale


def _bloques_de_nombre(lineas: list[Leido]) -> list[list[Leido]]:
    """Junta las lineas de un mismo nombre partido en dos o tres ("Paquete De" / "Polimeros")."""
    pendientes = sorted(lineas, key=lambda l: (l.y, l.x))
    bloques: list[list[Leido]] = []
    for linea in pendientes:
        for bloque in bloques:
            ultima = bloque[-1]
            solape = min(ultima.x + ultima.ancho, linea.x + linea.ancho) - max(ultima.x, linea.x)
            hueco = linea.y - (ultima.y + ultima.alto)
            alto = max(ultima.alto, linea.alto)
            centros = abs((ultima.x + ultima.ancho / 2) - (linea.x + linea.ancho / 2))
            if (solape >= 0.5 * min(ultima.ancho, linea.ancho) and -0.6 * alto <= hueco <= 0.9 * alto
                    and centros <= 1.5 * alto):
                bloque.append(linea)
                break
        else:
            bloques.append([linea])
    return bloques


def _caja(bloque: list[Leido]) -> tuple[int, int, int, int]:
    x0 = min(l.x for l in bloque)
    y0 = min(l.y for l in bloque)
    x1 = max(l.x + l.ancho for l in bloque)
    y1 = max(l.y + l.alto for l in bloque)
    return x0, y0, x1 - x0, y1 - y0


def interpretar(lineas: list[Leido], alto_ventana: int, nombres: Nombres,
                buscados: set[str]) -> list[Placa]:
    """Las placas de los recursos `buscados` que se ven, cada una con su cifra si la hay.

    No comprueba la cifra por segunda vez (eso es `comprobar_cifra`, que necesita la
    imagen): aqui solo se decide que caja de cifra es la de cada placa.
    """
    cifras = [l for l in lineas if es_caja_de_cifra(l.texto)]
    textos = [l for l in lineas if not es_caja_de_cifra(l.texto) and l.confianza >= MINIMO_CONFIANZA_NOMBRE]
    placas: list[Placa] = []
    vistos: dict[str, int] = {}
    # Un nombre de dos lineas tambien se prueba linea a linea por si el bloque junta de mas.
    candidatos = [b for b in _bloques_de_nombre(textos)]
    for bloque in candidatos:
        texto = " ".join(l.texto for l in bloque)
        unico = nombres.casar(texto, buscados)
        if unico is None or unico not in buscados:
            continue
        x, y, ancho, alto = _caja(bloque)
        placa = Placa(unico, texto, (x, y, ancho, alto))
        centro, pie = x + ancho / 2, y + alto
        posibles = []
        for c in cifras:
            tramo = pie - c.y
            if not (ALTO_MIN * alto_ventana <= tramo <= ALTO_MAX * alto_ventana):
                continue
            if c.y + c.alto > y:  # la cifra va por encima del nombre
                continue
            razon = (centro - c.x) / tramo
            if RAZON_MIN <= razon <= RAZON_MAX:
                posibles.append(c)
        if len(posibles) == 1:
            placa.cifra = posibles[0]
            placa.cantidad = cifra_de(posibles[0].texto)
            if placa.cantidad is None or posibles[0].confianza < MINIMO_CONFIANZA_CIFRA:
                placa.cantidad, placa.motivo = None, CIFRA_DUDOSA
        elif posibles:
            placa.motivo = CIFRA_DUDOSA  # dos cifras para una placa: no se sabe cual
        else:
            placa.motivo = SIN_CIFRA
        vistos[unico] = vistos.get(unico, 0) + 1
        placas.append(placa)
    # El mismo recurso en dos placas (la pantalla y otra cosa con su nombre): ninguna vale.
    for placa in placas:
        if vistos[placa.unique_name] > 1:
            placa.cantidad, placa.motivo = None, CIFRA_DUDOSA
    return placas


# -- segunda lectura de la cifra, sin el icono ------------------------------------------


def _tramos_de_tinta(columna_con_tinta) -> list[tuple[int, int]]:
    """Trozos seguidos de columnas con tinta: [(desde, hasta)), ...]."""
    tramos, inicio = [], None
    for i, hay in enumerate(columna_con_tinta):
        if hay and inicio is None:
            inicio = i
        elif not hay and inicio is not None:
            tramos.append((inicio, i))
            inicio = None
    if inicio is not None:
        tramos.append((inicio, len(columna_con_tinta)))
    return tramos


def recorte_sin_icono(imagen, cifra: Leido):
    """El trozo de imagen con la cifra, ya sin el icono redondo de delante si lo hay.

    El icono es el primer "caracter" y es tan ancho como alto; una cifra es la mitad
    de ancha que alta. Se mira la tinta por columnas: si el primer tramo es ancho, se
    corta por detras de el.
    """
    import numpy as np

    alto_img, ancho_img = imagen.shape[:2]
    margen = max(2, cifra.alto // 5)
    # Por la izquierda se coge mas: la caja del OCR corta a veces el icono por la mitad y
    # entonces no se reconocia como icono (medido: "42" releido como "942").
    x0, y0 = max(0, cifra.x - max(margen, int(cifra.alto * 0.7))), max(0, cifra.y - margen)
    x1 = min(ancho_img, cifra.x + cifra.ancho + margen)
    y1 = min(alto_img, cifra.y + cifra.alto + margen)
    recorte = imagen[y0:y1, x0:x1]
    if recorte.size == 0:
        return None
    gris = recorte.max(axis=2).astype(np.int16) if recorte.ndim == 3 else recorte.astype(np.int16)
    claro, oscuro = int(np.percentile(gris, 98)), int(np.percentile(gris, 20))
    if claro - oscuro < 40:
        return recorte  # sin contraste: que decida la segunda lectura
    tinta = gris > (oscuro + (claro - oscuro) * 0.55)
    columnas = tinta.sum(axis=0) >= max(1, tinta.shape[0] // 12)
    tramos = _tramos_de_tinta(columnas)
    if tramos:
        desde, hasta = tramos[0]
        if (hasta - desde) >= 0.72 * cifra.alto and len(tramos) > 1:
            corte = (hasta + tramos[1][0]) // 2
            recorte = recorte[:, corte:]
    return recorte


def _reconocer_recorte(motor, recorte, alto: int = 48) -> tuple[str, float]:
    """El texto de un recorte pequeno, llevado a `alto` px y leido sin buscar cajas.

    Medido sobre los recortes de las capturas reales: a 48 px, con un borde fino que
    repite el fondo, es como mejor lee el reconocedor las cifras sueltas.
    """
    import cv2
    import numpy as np

    if recorte is None or recorte.size == 0 or recorte.shape[0] < 4 or recorte.shape[1] < 3:
        return "", 0.0
    escala = alto / recorte.shape[0]
    grande = cv2.resize(recorte, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    borde = max(4, int(grande.shape[0] * 0.15))
    grande = cv2.copyMakeBorder(grande, borde, borde, borde, borde, cv2.BORDER_REPLICATE)
    interno = motor._cargar()  # noqa: SLF001 - el reconocedor a pelo, como `leer_tira`
    if interno == "winocr" or not hasattr(interno, "text_recognizer"):
        leidos = motor.leer(grande)
        if len(leidos) != 1:
            return "", 0.0
        return leidos[0].texto, leidos[0].confianza
    textos, _ = interno.text_recognizer([np.ascontiguousarray(grande)])
    if not textos:
        return "", 0.0
    texto, confianza = textos[0]
    return (texto or "").strip(), float(confianza)


def comprobar_cifra(imagen, placa: Placa, motor) -> None:
    """Relecturas de la cifra de la placa (el recorte sin el icono, a dos escalas); si no
    coinciden con la primera, se anula."""
    if placa.cantidad is None or placa.cifra is None:
        return
    lecturas: list[tuple[str, float]] = []
    try:
        recorte = recorte_sin_icono(imagen, placa.cifra)
        if recorte is not None:
            lecturas = [_reconocer_recorte(motor, recorte, 48), _reconocer_recorte(motor, recorte, 64)]
    except Exception:  # noqa: BLE001 - onnxruntime y cv2 lanzan de todo
        log.exception("No se pudo releer la cifra de %s", placa.unique_name)
    un_digito = placa.cantidad < 10
    minimo = MINIMO_CONFIANZA_UN_DIGITO if un_digito else MINIMO_CONFIANZA_SEGUNDA
    iguales = [c for t, c in lecturas if c >= minimo and cifra_de(t) == placa.cantidad]
    confirmada = bool(iguales) and (not un_digito or len(iguales) >= 2 or max(iguales) >= CONFIANZA_UN_DIGITO_SOLA)
    if not confirmada:
        log.info("Cifra de %s sin confirmar: primera lectura %r, relecturas %s",
                 placa.unique_name, placa.cifra.texto, [(t, round(c, 2)) for t, c in lecturas])
        placa.cantidad, placa.motivo = None, CIFRA_DUDOSA


def tramo_tipico(lineas: list[Leido], alto_ventana: int, nombres: Nombres | None = None) -> float | None:
    """Distancia tipica entre el techo de la cifra y el pie del nombre en esta pantalla.

    Sale de las placas con cifra que se ven: con ella se sabe donde deberia estar la cifra
    de una placa en la que el OCR no la vio. Con `nombres`, primero las placas que son un
    recurso (si hay al menos dos): el panel de la escuadra, a la izquierda, tiene cifras
    sobre nombres de jugadores a otra distancia y en una captura real torcia la mediana
    (95 px por 163) y tiraba las cifras buenas.
    """
    cifras = [l for l in lineas if es_caja_de_cifra(l.texto) and cifra_de(l.texto) is not None]
    textos = [l for l in lineas if not es_caja_de_cifra(l.texto) and l.confianza >= MINIMO_CONFIANZA_NOMBRE]
    tramos = []
    de_recursos = []
    for bloque in _bloques_de_nombre(textos):
        x, y, ancho, alto = _caja(bloque)
        centro, pie = x + ancho / 2, y + alto
        es_recurso = nombres is not None and nombres.casar(" ".join(l.texto for l in bloque)) is not None
        for c in cifras:
            tramo = pie - c.y
            if (ALTO_MIN * alto_ventana <= tramo <= ALTO_MAX * alto_ventana and c.y + c.alto <= y
                    and 0.30 <= (centro - c.x) / tramo <= 0.56):
                tramos.append(tramo)
                if es_recurso:
                    de_recursos.append(tramo)
    if len(de_recursos) >= 2:
        tramos = de_recursos
    if not tramos:
        return None
    tramos.sort()
    mediana = tramos[len(tramos) // 2]
    # Las placas de una pantalla son todas iguales: si los tramos no se parecen, no hay rejilla clara.
    parecidos = [v for v in tramos if abs(v - mediana) <= 0.08 * mediana]
    return mediana if len(parecidos) >= max(1, len(tramos) * 2 // 3) else None


TOLERANCIA_TRAMO = 0.08
# Donde esta el icono respecto al nombre, en partes del tramo: su borde izquierdo queda a
# 0,465 del centro del nombre y su techo a 0,985 del pie (medido en 1080p y 1440p).
_ICONO_X, _ICONO_Y, _ICONO_HOLGURA = 0.465, 0.985, 0.06


# Donde cae la cifra dentro de la placa, en partes del tramo cifra-nombre (medido).
_ZONA_IZQ, _ZONA_ANCHO, _ZONA_ARRIBA, _ZONA_ALTO = 0.56, 0.62, 0.05, 0.24


def pantalla_con_iconos(imagen, lineas: list[Leido]) -> bool | None:
    """Si en esta pantalla las cifras llevan delante el icono redondo (interfaz actual).

    Se mira en la imagen, no en el texto del OCR (que unas veces lo lee como "0" o "?" y
    otras lo salta): delante de la cifra, un trozo de tinta tan ancho como alto. En la
    interfaz anterior la cifra va sola. None si no hay cifras en las que mirarlo.
    """
    import numpy as np

    cifras = [l for l in lineas if es_caja_de_cifra(l.texto) and cifra_de(l.texto) is not None]
    if not cifras:
        return None
    # Lo que dice el texto del OCR ya basta cuando lee el icono ("042", "?30", "①1,155").
    if sum(1 for c in cifras if c.texto.strip()[0] not in "123456789") * 2 >= len(cifras):
        return True
    if imagen is None:
        return None
    con_icono = 0
    for c in cifras[:8]:
        margen = int(c.alto * 1.3)
        y0, y1 = max(0, c.y - c.alto // 4), min(imagen.shape[0], c.y + c.alto + c.alto // 4)
        x0, x1 = max(0, c.x - margen), min(imagen.shape[1], c.x + c.ancho)
        zona = imagen[y0:y1, x0:x1]
        if zona.size == 0:
            continue
        gris = zona.max(axis=2).astype(np.int16) if zona.ndim == 3 else zona.astype(np.int16)
        claro, oscuro = int(np.percentile(gris, 98)), int(np.percentile(gris, 20))
        if claro - oscuro < 40:
            continue
        tinta = gris > (oscuro + (claro - oscuro) * 0.55)
        tramos = _tramos_de_tinta(tinta.sum(axis=0) >= max(1, tinta.shape[0] // 12))
        if len(tramos) >= 2 and 0.72 * c.alto <= (tramos[0][1] - tramos[0][0]) <= 1.5 * c.alto:
            con_icono += 1
    return con_icono * 2 >= min(len(cifras), 8)


def buscar_cifra(imagen, placa: Placa, tramo: float, motor, con_iconos: bool | None = None) -> None:
    """Para una placa sin cifra a la vista: mira de cerca el sitio donde iria.

    - Si ahi esta el icono redondo y nada mas, la placa es de 1 unidad: el icono
      demuestra que se esta mirando el sitio correcto.
    - Si ahi hay una cifra (las de un digito se le escapan a la lectura de la pantalla
      entera), se queda con ella; luego `comprobar_cifra` la confirma o la anula.
    - En la interfaz sin iconos (`con_iconos` False), si en el sitio de la cifra no hay
      nada escrito, la placa es de 1 unidad (el juego no pone cifra a una unidad); y si
      hay tinta pequena que el detector no vio, se lee como cifra.
    - En cualquier otro caso se queda como estaba ("sin cifra").
    """
    import cv2
    import numpy as np

    x, y, ancho, alto = placa.caja_nombre
    centro, pie = x + ancho / 2, y + alto
    x0 = int(max(0, centro - _ZONA_IZQ * tramo))
    y0 = int(max(0, pie - tramo - _ZONA_ARRIBA * tramo))
    x1 = int(min(imagen.shape[1], x0 + _ZONA_ANCHO * tramo))
    y1 = int(min(imagen.shape[0], y0 + _ZONA_ALTO * tramo))
    zona = imagen[y0:y1, x0:x1]
    if zona.size == 0 or zona.shape[0] < 8:
        return
    # Que la zona entera este dentro de la captura: en el borde no se sabe que falta.
    completa = (x1 - x0) >= _ZONA_ANCHO * tramo * 0.95 and (y1 - y0) >= _ZONA_ALTO * tramo * 0.95
    tinta = _tinta_de_cifra(zona, tramo)
    icono_en_su_sitio = False
    if tinta is not None and tinta[4]:
        tx, ty = tinta[0], tinta[1]
        fuera_x = abs((centro - (x0 + tx)) / tramo - _ICONO_X)
        fuera_y = abs((pie - (y0 + ty)) / tramo - _ICONO_Y)
        icono_en_su_sitio = fuera_x <= _ICONO_HOLGURA and fuera_y <= _ICONO_HOLGURA
        if icono_en_su_sitio and not tinta[5]:
            placa.cantidad, placa.motivo, placa.cifra = 1, "", None  # solo el icono: 1 unidad
            return
    escala = max(1.0, 96 / zona.shape[0])
    grande = cv2.resize(zona, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    leidos = [l for l in motor.leer(np.ascontiguousarray(grande)) if es_caja_de_cifra(l.texto)]
    if len(leidos) == 1 and cifra_de(leidos[0].texto) is not None:
        l = leidos[0]
        placa.cifra = Leido(l.texto, x0 + int(l.x / escala), y0 + int(l.y / escala),
                            max(1, int(l.ancho / escala)), max(1, int(l.alto / escala)), l.confianza)
        placa.cantidad, placa.motivo = cifra_de(l.texto), ""
        if l.confianza < MINIMO_CONFIANZA_CIFRA:
            placa.cantidad, placa.motivo = None, CIFRA_DUDOSA
        return
    if tinta is None:
        if leidos:
            placa.motivo = CIFRA_DUDOSA
        elif con_iconos is False and completa:
            placa.cantidad, placa.motivo, placa.cifra = 1, "", None  # nada escrito: 1 unidad
        return
    tx, ty, tancho, talto, icono, resto = tinta
    if icono:
        if not icono_en_su_sitio or not resto:
            if leidos:
                placa.motivo = CIFRA_DUDOSA
            return  # hay algo redondo, pero no donde va el icono de esta placa
    elif con_iconos is not False:
        if leidos:
            placa.motivo = CIFRA_DUDOSA
        return  # en esta pantalla las cifras llevan icono: sin el no hay prueba de estar en el sitio
    # Icono y algo pegado detras (o, sin iconos, tinta pequena): una cifra corta que el
    # detector no vio. Se lee el recorte (primera lectura) y `comprobar_cifra` lo relee.
    margen = max(2, talto // 5)
    recorte = zona[max(0, ty - margen):ty + talto + margen, max(0, tx - margen):tx + tancho + margen]
    texto, confianza = _reconocer_recorte(motor, recorte)
    cantidad = cifra_de(texto) if confianza >= MINIMO_CONFIANZA_SEGUNDA else None
    if cantidad is None:
        placa.motivo = CIFRA_DUDOSA
        return
    placa.cifra = Leido(texto, x0 + tx, y0 + ty, tancho, talto, confianza)
    placa.cantidad, placa.motivo = cantidad, ""


def _tinta_de_cifra(zona, tramo: float):
    """(x, y, ancho, alto, hay_icono, hay_algo_detras) de lo escrito en la zona de la cifra.

    None si no hay nada claro. El icono es el primer trozo de tinta y es redondo: tan
    ancho como alto y de ~1/7 del tramo (23 px de 164 a 1080p). Lo de detras, si esta
    pegado (a menos de un alto de texto), son las cifras; lo que quede mas lejos es el
    dibujo del objeto y no cuenta.
    """
    import numpy as np

    gris = zona.max(axis=2).astype(np.int16) if zona.ndim == 3 else zona.astype(np.int16)
    claro, oscuro = int(np.percentile(gris, 99)), int(np.percentile(gris, 30))
    if claro - oscuro < 60:
        return None
    tinta = gris > (oscuro + (claro - oscuro) * 0.6)
    tramos = _tramos_de_tinta(tinta.sum(axis=0) >= 2)
    if not tramos:
        return None
    desde, hasta = tramos[0]
    filas = np.flatnonzero(tinta[:, desde:hasta].sum(axis=1) >= 1)
    if filas.size == 0:
        return None
    arriba, alto = int(filas[0]), int(filas[-1] - filas[0] + 1)
    lado = 0.14 * tramo
    ancho = hasta - desde
    icono = (0.7 * lado <= ancho <= 1.4 * lado and 0.7 * lado <= alto <= 1.4 * lado
             and 0.75 <= ancho / max(1, alto) <= 1.3)
    fin, resto = hasta, False
    for d2, h2 in tramos[1:]:
        if d2 - fin > 0.8 * alto:
            break
        fin, resto = h2, True
    return desde, arriba, fin - desde, alto, bool(icono), resto


def leer_imagen(imagen, motor, nombres: Nombres, buscados: set[str],
                alto_deteccion: int | None = None) -> list[Placa]:
    """OCR de la captura entera y placas de los recursos buscados, con la cifra comprobada."""
    if imagen is None or not buscados:
        return []
    lineas = motor.leer(imagen, alto_deteccion=alto_deteccion)
    placas = interpretar(lineas, imagen.shape[0], nombres, buscados)
    tramo = tramo_tipico(lineas, imagen.shape[0], nombres) if placas else None
    con_iconos = pantalla_con_iconos(imagen, lineas) if placas else None
    # Para dar una placa sin nada escrito por 1 unidad hace falta que este en la rejilla: otra
    # placa (con cifra) en su misma fila. Un nombre suelto que se parece a un recurso (el
    # "CHERCHER..." del buscador se parecia a "Researcher") no la tiene.
    filas_con_cifra = [p.cifra.y for p in placas if p.cifra is not None] + [
        l.y for l in lineas if es_caja_de_cifra(l.texto) and cifra_de(l.texto) is not None]
    for placa in placas:
        en_rejilla = bool(tramo) and any(
            abs((placa.caja_nombre[1] + placa.caja_nombre[3] - tramo) - y) < 0.35 * tramo for y in filas_con_cifra)
        try:
            if placa.cifra is not None and placa.cantidad is not None and tramo:
                # Todas las placas de una pantalla miden lo mismo: una cifra a otra distancia
                # de su nombre que las demas no es de esta placa.
                x, y, ancho, alto = placa.caja_nombre
                if abs((y + alto - placa.cifra.y) - tramo) > TOLERANCIA_TRAMO * tramo:
                    placa.cantidad, placa.motivo = None, CIFRA_DUDOSA
            if placa.motivo == SIN_CIFRA and tramo:
                buscar_cifra(imagen, placa, tramo, motor, con_iconos if en_rejilla else None)
        except Exception:  # noqa: BLE001 - onnxruntime y cv2 lanzan de todo
            log.exception("No se pudo mirar de cerca la placa de %s", placa.unique_name)
        comprobar_cifra(imagen, placa, motor)
    return placas


# -- juntar varias capturas de la misma mision ---------------------------------------------


@dataclass
class Resultado:
    """Lo que se ha sacado de la pantalla de fin de una mision."""

    mision: str  # clave unica de la mision (para no contarla dos veces)
    cantidades: dict[str, int] = field(default_factory=dict)  # unique_name -> cantidad segura
    no_leidos: dict[str, str] = field(default_factory=dict)  # unique_name -> motivo
    lecturas: int = 0
    segundos: float = 0.0


class Acumulador:
    """Junta las lecturas de una mision: una cantidad vale cuando sale igual dos veces."""

    def __init__(self, buscados: set[str]):
        self.buscados = set(buscados)
        self.vistas: dict[str, list[int]] = {}
        self.motivos: dict[str, str] = {}
        self.seguras: dict[str, int] = {}

    def anotar(self, placas: list[Placa]) -> bool:
        """Apunta una lectura. True si ha traido algo nuevo (una cantidad vista o confirmada)."""
        novedad = False
        for placa in placas:
            if placa.unique_name not in self.buscados or placa.unique_name in self.seguras:
                continue
            if placa.cantidad is None:
                self.motivos[placa.unique_name] = placa.motivo or CIFRA_DUDOSA
                continue
            anteriores = self.vistas.setdefault(placa.unique_name, [])
            if placa.cantidad in anteriores:
                self.seguras[placa.unique_name] = placa.cantidad
            else:
                anteriores.append(placa.cantidad)
            novedad = True
        return novedad

    @property
    def completo(self) -> bool:
        return self.buscados <= set(self.seguras)

    def resultado(self, mision: str) -> Resultado:
        salida = Resultado(mision, dict(self.seguras))
        for unico in self.buscados - set(self.seguras):
            if len(self.vistas.get(unico, [])) >= 1:
                salida.no_leidos[unico] = NO_REPETIDA
            else:
                salida.no_leidos[unico] = self.motivos.get(unico, NO_VISTO)
        return salida


# -- el lector, en el hilo de la lectura pasiva -------------------------------------------

# Cuanto se espera desde el aviso de EE.log hasta la primera captura (la pantalla
# entra con una animacion) y entre capturas. SIN COMPROBAR EN EL JUEGO: son los
# tiempos de la pantalla de reliquias, que si estan medidos.
ESPERA_PRIMERA_MS = 2500
ESPERA_ENTRE_MS = 2000
# Tope de lecturas por mision: si en este rato el recurso no ha salido a la vista, se
# deja de mirar y se dice. Nunca se queda mirando la pantalla.
MAX_LECTURAS = 6
# Lo normal es acabar antes: desde la tercera lectura, dos seguidas sin nada nuevo bastan
# (la pantalla esta quieta y lo que falta no esta a la vista).
MIN_LECTURAS = 3
LECTURAS_SIN_NOVEDAD = 2


class LectorFinMision(QObject):
    """Al acabar una mision lee la pantalla de resultados unas pocas veces y para.

    Vive en el hilo de la lectura pasiva. La ventana le pasa, al llegar el aviso de
    EE.log, que recursos hay como meta sin completar (`leer_mision`); sin ninguno, o
    con la opcion apagada, no hace nada. En reposo no tiene ningun temporizador en marcha.
    """

    resultado = Signal(object)  # Resultado

    def __init__(self, motor_ocr: str = "rapidocr", activo: bool = False, parent=None):
        super().__init__(parent)
        self.activo = activo
        self.motor = MotorOCR(motor_de_fondo(motor_ocr))
        self.nombres: Nombres | None = None
        self._acumulador: Acumulador | None = None
        self._mision = ""
        self._lecturas = 0
        self._segundos = 0.0
        self._sin_novedad = 0
        self._temporizador: QTimer | None = None

    @Slot(bool)
    def activar(self, activo: bool) -> None:
        self.activo = activo
        if not activo:
            self._terminar(emitir=False)

    @Slot()
    def parar(self) -> None:
        """Al cerrar: para el temporizador en su hilo (ver `tareas.parar_en_su_hilo`)."""
        self._terminar(emitir=False)

    @Slot(str)
    def cambiar_motor(self, motor_ocr: str) -> None:
        MotorOCR.olvidar_fallo(motor_ocr)
        self.motor = MotorOCR(motor_de_fondo(motor_ocr))

    @Slot(object)
    def leer_mision(self, buscados) -> None:
        """Ha acabado una mision: `buscados` son los unique_name de los recursos pendientes."""
        buscados = set(buscados or ())
        if not self.activo or not buscados:
            return
        if self._acumulador is not None:
            self._terminar(emitir=True)  # otra mision sin haber acabado de leer la anterior
        self._mision = clave_de_mision()
        self._acumulador = Acumulador(buscados)
        self._lecturas, self._segundos, self._sin_novedad = 0, 0.0, 0
        if self._temporizador is None:
            self._temporizador = QTimer(self)
            self._temporizador.setSingleShot(True)
            self._temporizador.timeout.connect(self._leer)
        self._temporizador.start(ESPERA_PRIMERA_MS)
        log.info("Fin de mision: se va a leer la pantalla buscando %d recurso(s)", len(buscados))

    def _capturar(self):
        hwnd = pantalla.ventana_juego()
        if not hwnd or pantalla._ventana_activa() != hwnd:  # noqa: SLF001
            return None
        region = pantalla.region_ventana(hwnd)
        if region is None:
            return None
        return pantalla.descartar_propias(pantalla.capturar_sin_ocultar(region), region)

    def _nombres(self) -> Nombres:
        if self.nombres is None:
            from ..datos import indice

            self.nombres = Nombres.del_indice(indice.conectar())
        return self.nombres

    @Slot()
    def _leer(self) -> None:
        acumulador = self._acumulador
        if acumulador is None:
            return
        self._lecturas += 1
        novedad = False
        try:
            imagen = self._capturar()
            if imagen is not None:
                inicio = time.perf_counter()
                placas = leer_imagen(imagen, self.motor, self._nombres(), acumulador.buscados,
                                     alto_deteccion=ALTO_DETECCION_PASIVA)
                self._segundos += time.perf_counter() - inicio
                novedad = acumulador.anotar(placas)
        except ErrorMotorOCR as e:
            log.warning("Sin OCR para la pantalla de fin de mision: %s", e)
            self._terminar(emitir=True)
            return
        except Exception:  # noqa: BLE001 - un fallo aqui no puede tumbar el hilo
            log.exception("Fallo leyendo la pantalla de fin de mision")
        self._sin_novedad = 0 if novedad else self._sin_novedad + 1
        quieta = self._lecturas >= MIN_LECTURAS and self._sin_novedad >= LECTURAS_SIN_NOVEDAD
        if acumulador.completo or quieta or self._lecturas >= MAX_LECTURAS:
            self._terminar(emitir=True)
        elif self._temporizador is not None:
            self._temporizador.start(ESPERA_ENTRE_MS)

    def _terminar(self, emitir: bool) -> None:
        acumulador, self._acumulador = self._acumulador, None
        if self._temporizador is not None:
            self._temporizador.stop()
        if acumulador is None or not emitir:
            return
        salida = acumulador.resultado(self._mision)
        salida.lecturas, salida.segundos = self._lecturas, self._segundos
        log.info("Fin de mision %s: %d recurso(s) leidos, %d sin leer, %d lecturas, %.2f s de OCR",
                 salida.mision, len(salida.cantidades), len(salida.no_leidos),
                 salida.lecturas, salida.segundos)
        self.resultado.emit(salida)


_ultima_clave = ""


def clave_de_mision() -> str:
    """Una clave distinta para cada mision terminada (la hora, con desempate)."""
    global _ultima_clave
    clave = time.strftime("%Y-%m-%dT%H:%M:%S")
    if _ultima_clave.split("#")[0] == clave:
        n = int(_ultima_clave.partition("#")[2] or 1) + 1
        clave = f"{clave}#{n}"
    _ultima_clave = clave
    return clave
