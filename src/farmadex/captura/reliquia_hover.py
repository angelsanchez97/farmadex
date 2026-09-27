"""La tabla de la reliquia que hay bajo el raton, dentro del juego.

Al dejar el raton quieto encima de una reliquia (Reliquias del Vacio / Refinado,
eleccion de reliquia antes de una fisura, Varzia, mercado...) se recorta un trozo
pequeno de pantalla alrededor del cursor, se lee con el OCR y, si ahi pone con
seguridad "Lith S19" / "Reliquia Axi A7" / "Neo G6 Relic", la interfaz ensena la
tarjeta con su tabla (`ui/tooltip_reliquia.py`).

Para no gastar CPU mientras se juega:

- Solo mira en pantallas de reliquias segun EE.log (`es_pantalla_de_reliquias`) o,
  en el modo "tecla", mientras se mantiene pulsada la tecla elegida.
- El sondeo del raton es un temporizador de la interfaz cada 100 ms que solo pide
  la posicion del cursor y la ventana activa (microsegundos).
- Se lee UNA vez por parada: cuando el raton lleva `QUIETO_S` sin moverse despues
  de haberse movido. Con el raton quieto no se vuelve a leer nada.
- Cache por posicion: volver a la misma casilla con la misma imagen no repite el OCR.
- El OCR es de un recorte de ~1/3 x 1/4 de la altura del juego, sin reescalar
  (`MotorOCR.leer_tira`): ~25 ms medidos a 1080p.

Nunca falsa seguridad: si el texto no trae una era y un codigo que existan en el
indice, o hay dos reliquias igual de cerca del cursor, no se ensena nada.

Este modulo no importa nada de la interfaz: el controlador recibe funciones para
ensenar y esconder la tarjeta.
"""

from __future__ import annotations

import ctypes
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..registro_log import obtener

log = obtener("reliquia_hover")

QUIETO_S = 0.3  # raton quieto este tiempo = el usuario esta mirando algo
INTERVALO_MS = 100  # sondeo del raton
TOLERANCIA_PX = 4  # temblor de la mano que no cuenta como mover
RADIO_PX = 40  # alejarse mas que esto de donde se leyo esconde la tarjeta
CONFIANZA_MINIMA = 0.70  # del OCR, por linea
# Recorte alrededor del cursor, en fracciones de la altura del juego. Mas hacia abajo
# que hacia arriba: en la rejilla de reliquias el nombre va debajo del icono.
ANCHO_REL, ALTO_REL, ARRIBA_REL = 0.32, 0.24, 0.35
# Otra reliquia a menos de esta proporcion de la distancia de la mas cercana = duda.
MARGEN_AMBIGUO = 1.4
# Un nombre mas lejos del cursor que esto (fraccion del alto del recorte) no es "lo que
# hay bajo el raton": en la rejilla, del centro del icono a su nombre hay ~0,06 del alto
# del juego, o sea ~0,26 del recorte.
DISTANCIA_MAX_REL = 0.375

ERAS = ("Lith", "Meso", "Neo", "Axi", "Requiem")
MODOS = ("auto", "tecla")
# Teclas que se pueden mantener pulsadas (codigo virtual de Windows).
TECLAS = {"alt": 0x12, "ctrl": 0x11, "shift": 0x10, "raton4": 0x05, "raton5": 0x06}

# Nombres de pantalla de EE.log que tienen pinta de ensenar reliquias. Los nombres
# reales de estas pantallas no estan comprobados todavia (solo el arsenal lo esta,
# ver registro/eelog.py): se casan por trozos del nombre, sin mayusculas.
TROZOS_PANTALLA_RELIQUIAS = ("relic", "projection", "fissure", "vaulttrader", "varzia", "market", "trade")
# Pantallas conocidas donde seguro que no hay reliquias bajo el raton.
PANTALLAS_SIN_RELIQUIAS = ("arsenal", "perfil", "fundicion", "codex", "menu", "carga", "pausa", "inventario")

# Palabras de refinamiento en los idiomas del juego (sin tildes, en mayusculas).
REFINAMIENTOS = {
    "INTACTA": "Intact", "INTACT": "Intact", "INTACTE": "Intact", "INTAKT": "Intact",
    "EXCEPCIONAL": "Exceptional", "EXCEPTIONAL": "Exceptional", "EXCEPTIONNELLE": "Exceptional",
    "AUSSERGEWOHNLICH": "Exceptional",
    "IMPECABLE": "Flawless", "PERFECTA": "Flawless", "FLAWLESS": "Flawless", "IMPECCABLE": "Flawless",
    "MAKELLOS": "Flawless", "IMPECAVEL": "Flawless",
    "RADIANTE": "Radiant", "RADIANT": "Radiant", "ECLATANTE": "Radiant", "STRAHLEND": "Radiant",
}

# Confusiones tipicas del OCR: en la letra del codigo, cifras que parecen letras, y al reves.
A_LETRA = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G", "4": "A", "7": "T"}
A_CIFRA = {"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "|": "1", "S": "5", "B": "8",
           "Z": "2", "G": "6", "T": "7", "A": "4"}
_ERAS_MAYUS = {e.upper(): e for e in ERAS}
# "LITH S19", "LITHS19", "L1TH 519"... sobre el texto compacto (sin espacios).
RE_ROMANO = re.compile(r"^(IV|I{1,3})$")


# -- pantallas ---------------------------------------------------------------------


def es_pantalla_de_reliquias(pantalla: str | None) -> bool:
    """Lo ultimo que EE.log dijo que esta abierto, ¿puede ensenar reliquias?

    Nada abierto (andando por la nave o en mision) = no. Una pantalla sin clasificar
    ("?Nombre") cuenta si su nombre lo parece; las demas desconocidas tambien, porque
    los nombres de las pantallas de reliquias no estan comprobados en un log real y
    mas vale mirar de mas en un menu que no salir nunca (una lectura por parada).
    """
    if not pantalla:
        return False
    if pantalla.startswith("?"):
        return True
    nombre = pantalla.lower()
    if nombre in PANTALLAS_SIN_RELIQUIAS:
        return False
    return any(trozo in nombre for trozo in TROZOS_PANTALLA_RELIQUIAS)


# -- texto -> reliquia ----------------------------------------------------------------


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def _era(palabra: str) -> str | None:
    """'LITH', 'L1TH', 'LlTH', 'MES0', 'AX1'... -> 'Lith'/'Meso'/'Axi'; None si no es una era."""
    if palabra in _ERAS_MAYUS:
        return _ERAS_MAYUS[palabra]
    arreglada = "".join(A_LETRA.get(c, c) for c in palabra).replace("|", "I")
    if arreglada in _ERAS_MAYUS:
        return _ERAS_MAYUS[arreglada]
    # Una letra cambiada solo en las eras largas: en tres letras (Neo, Axi) seria adivinar.
    for era in ("LITH", "MESO", "REQUIEM"):
        if len(arreglada) == len(era) and sum(a != b for a, b in zip(arreglada, era)) == 1:
            if era == "LITH" and arreglada[1:] == "ITH":  # "AITH", "OITH": no
                continue
            return _ERAS_MAYUS[era]
    return None


def _codigo(texto: str, era: str) -> str | None:
    """'S19', '519', 'SI9' -> 'S19'; en Requiem, 'II', 'll' -> 'II'. None si no cuadra."""
    if era == "Requiem":
        romano = texto.replace("L", "I").replace("1", "I").replace("|", "I")
        return romano if RE_ROMANO.match(romano) else None
    if not 2 <= len(texto) <= 3:
        return None
    letra = A_LETRA.get(texto[0], texto[0])
    cifras = "".join(A_CIFRA.get(c, c) for c in texto[1:])
    if not (letra.isalpha() and letra.isascii() and cifras.isdigit()) or cifras.startswith("0"):
        return None
    return letra + cifras


RE_TROZOS = re.compile(r"[A-Z0-9|]+")


def reliquias_en_texto(texto: str) -> list[tuple[str, str | None]]:
    """[('Lith S19', 'Radiant'|None), ...] con lo que parece un nombre de reliquia en el texto.

    Acepta "Reliquia Lith S19", "Lith S19 Relic", "Relique Meso N1 [Eclatante]",
    "ReligueMesoD4" (el OCR junta palabras) y confusiones de letra y cifra. No mira
    el indice: eso lo hace quien llama, que es quien sabe que reliquias existen.
    """
    limpio = _sin_tildes(texto).upper()
    trozos = RE_TROZOS.findall(limpio)
    refinamiento = next((REFINAMIENTOS[t] for t in trozos if t in REFINAMIENTOS), None)
    salida: list[tuple[str, str | None]] = []
    for i, trozo in enumerate(trozos):
        encontrado = None
        era = _era(trozo)
        if era and i + 1 < len(trozos):
            codigo = _codigo(trozos[i + 1], era)
            if codigo:
                encontrado = f"{era} {codigo}"
        if encontrado is None:
            # Palabras pegadas: "RELIGUEMESOD4", "LITHS19".
            for era_m, era in _ERAS_MAYUS.items():
                pos = trozo.find(era_m)
                if pos < 0:
                    continue
                resto = trozo[pos + len(era_m):]
                # El codigo, y detras nada o la palabra reliquia pegada ("NEOA13RELIC").
                for largo in ((3, 2) if era != "Requiem" else (3, 2, 1)):
                    cola = resto[largo:]
                    if len(resto) >= largo and (not cola or cola.startswith("REL")):
                        codigo = _codigo(resto[:largo], era)
                        if codigo:
                            encontrado = f"{era} {codigo}"
                            break
                if encontrado:
                    break
        if encontrado and encontrado not in (s[0] for s in salida):
            salida.append((encontrado, refinamiento))
    return salida


def nombres_de_reliquias(con) -> dict[str, int]:
    """{'Lith S19': id, 'Requiem II': id} de las reliquias del indice."""
    salida: dict[str, int] = {}
    for item_id, nombre_en in con.execute("SELECT id, nombre_en FROM items WHERE categoria = 'Relics'"):
        corto = (nombre_en or "").removesuffix(" Relic").strip()
        partes = corto.split(" ")
        if len(partes) == 2 and partes[0] in ERAS and _codigo(partes[1].upper(), partes[0]) == partes[1].upper():
            salida[corto] = item_id
    return salida


@dataclass
class Candidata:
    reliquia_id: int
    nombre: str  # "Lith S19"
    refinamiento: str | None
    texto_ocr: str
    distancia: float


def elegir_reliquia(lineas, cursor: tuple[float, float], tamano: tuple[int, int],
                    nombres: dict[str, int], confianza: float = CONFIANZA_MINIMA) -> Candidata | None:
    """La reliquia que senala el cursor entre las lineas leidas del recorte, o None.

    `lineas` son `ocr.Leido` en coordenadas del recorte; `cursor`, donde cae el raton
    en ese recorte. Se descartan las lineas cortadas por el borde izquierdo o derecho
    del recorte ("Lith G1" de un "Lith G13" partido seria otra reliquia), las de poca
    confianza y los nombres que no existen en el indice. Si quedan dos reliquias
    distintas casi igual de cerca, no se elige ninguna.
    """
    ancho, _alto = tamano
    candidatas: list[Candidata] = []
    # Una linea de refinamiento suelta ("[Eclatante]") debajo del nombre se lo presta.
    refinos = [(l, REFINAMIENTOS.get(re.sub(r"[^A-Z]", "", _sin_tildes(l.texto).upper())))
               for l in lineas]
    for l in lineas:
        if l.confianza < confianza:
            continue
        if l.x <= 2 or l.x + l.ancho >= ancho - 2:
            continue
        for nombre, refinamiento in reliquias_en_texto(l.texto):
            reliquia_id = nombres.get(nombre)
            if reliquia_id is None:
                continue
            if refinamiento is None:
                refinamiento = next(
                    (r for o, r in refinos if r and 0 < o.y - l.y < 2.5 * max(l.alto, 1)
                     and abs((o.x + o.ancho / 2) - (l.x + l.ancho / 2)) < l.ancho), None)
            cx = min(max(cursor[0], l.x), l.x + l.ancho)
            cy = min(max(cursor[1], l.y), l.y + l.alto)
            distancia = ((cursor[0] - cx) ** 2 + (cursor[1] - cy) ** 2) ** 0.5
            if distancia > DISTANCIA_MAX_REL * _alto:
                continue
            candidatas.append(Candidata(reliquia_id, nombre, refinamiento, l.texto, distancia))
    if not candidatas:
        return None
    candidatas.sort(key=lambda c: c.distancia)
    mejor = candidatas[0]
    otra = next((c for c in candidatas[1:] if c.reliquia_id != mejor.reliquia_id), None)
    if otra is not None and otra.distancia < max(mejor.distancia, 8.0) * MARGEN_AMBIGUO:
        log.debug("Dos reliquias casi igual de cerca del cursor (%s, %s): no se elige", mejor.nombre, otra.nombre)
        return None
    return mejor


def region_recorte(cx: int, cy: int, juego) -> tuple[int, int, int, int]:
    """(x, y, ancho, alto) del recorte alrededor del cursor, dentro de la ventana del juego."""
    alto_juego = juego.alto
    ancho = max(160, int(ANCHO_REL * alto_juego))
    alto = max(120, int(ALTO_REL * alto_juego))
    x = cx - ancho // 2
    y = cy - int(ARRIBA_REL * alto)
    x = max(juego.x, min(x, juego.x + juego.ancho - ancho))
    y = max(juego.y, min(y, juego.y + juego.alto - alto))
    return x, y, min(ancho, juego.ancho), min(alto, juego.alto)


def huella(imagen) -> "object":
    """Miniatura gris 16x12: sirve para saber si en esa casilla sigue lo mismo."""
    import numpy as np

    gris = imagen.mean(axis=2) if imagen.ndim == 3 else imagen
    alto, ancho = gris.shape[:2]
    filas = np.linspace(0, alto, 13).astype(int)
    columnas = np.linspace(0, ancho, 17).astype(int)
    return np.array([[gris[filas[i]:filas[i + 1], columnas[j]:columnas[j + 1]].mean()
                      for j in range(16)] for i in range(12)], dtype=np.float32)


def misma_huella(a, b, tolerancia: float = 6.0) -> bool:
    import numpy as np

    return a is not None and b is not None and a.shape == b.shape and float(np.abs(a - b).mean()) < tolerancia


# Por debajo de esta altura de recorte (juego a menos de ~900 px de alto) la letra es tan
# pequena que el OCR confunde cifras (un 9 por un 6): se amplia antes de leer.
ALTO_PARA_AMPLIAR = 216


def leer_ampliando(leer, imagen):
    """Lee el recorte; si es pequeno, ampliado, y devuelve las cajas en su tamano original."""
    alto = imagen.shape[0]
    if alto >= ALTO_PARA_AMPLIAR:
        return leer(imagen)
    import cv2

    escala = 1.5
    grande = cv2.resize(imagen, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    lineas = leer(grande)
    for l in lineas:
        l.x, l.y = int(l.x / escala), int(l.y / escala)
        l.ancho, l.alto = int(l.ancho / escala), int(l.alto / escala)
    return lineas


# -- quieto o moviendose ----------------------------------------------------------------


class DetectorQuieto:
    """Avisa UNA vez por parada: cuando el raton lleva `quieto_s` sin moverse."""

    def __init__(self, quieto_s: float = QUIETO_S, tolerancia: int = TOLERANCIA_PX):
        self.quieto_s = quieto_s
        self.tolerancia = tolerancia
        self._pos: tuple[int, int] | None = None
        self._desde = 0.0
        self._avisado = False

    def observar(self, ahora: float, x: int, y: int) -> bool:
        if self._pos is None or abs(x - self._pos[0]) > self.tolerancia or abs(y - self._pos[1]) > self.tolerancia:
            self._pos, self._desde, self._avisado = (x, y), ahora, False
            return False
        if not self._avisado and ahora - self._desde >= self.quieto_s:
            self._avisado = True
            return True
        return False

    def reiniciar(self) -> None:
        self._pos, self._avisado = None, False


class CacheHover:
    """Lo leido cerca de cada punto de la pantalla (a menos de `paso` px), con la huella de la imagen."""

    def __init__(self, paso: int = 24, limite: int = 256):
        self.paso = paso
        self.limite = limite
        self._datos: list[tuple[int, int, str, object, tuple]] = []

    def buscar(self, x: int, y: int, contexto: str, huella_nueva):
        for gx, gy, gc, marca, resultado in reversed(self._datos):
            if gc == contexto and abs(gx - x) <= self.paso and abs(gy - y) <= self.paso and misma_huella(marca, huella_nueva):
                return resultado, True
        return None, False

    def guardar(self, x: int, y: int, contexto: str, huella_nueva, resultado) -> None:
        if len(self._datos) >= self.limite:
            del self._datos[: self.limite // 2]
        self._datos.append((x, y, contexto, huella_nueva, resultado))

    def vaciar(self) -> None:
        self._datos.clear()


# -- lector (hilo de captura) -------------------------------------------------------------


class LectorHoverReliquia(QObject):
    """Recorta, lee y casa. Vive en el hilo de captura, con el mismo motor OCR que el resto."""

    # numero, x, y (fisicos, donde se pidio), reliquia_id (0 = nada), refinamiento, ms del OCR (-1 = cache)
    leida = Signal(int, int, int, int, str, float)

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(parent)
        self._modo_motor = motor_ocr
        self.motor = None  # se crea al primer uso: sin hover no se toca el OCR
        self.nombres: dict[str, int] | None = None
        self.cache = CacheHover()
        self.lecturas = 0
        self.ms_total = 0.0

    @Slot(str)
    def cambiar_motor(self, motor_ocr: str) -> None:
        self._modo_motor = motor_ocr
        self.motor = None

    def _motor(self):
        if self.motor is None:
            from .ocr import MotorOCR

            self.motor = MotorOCR(self._modo_motor)
        return self.motor

    def _nombres(self) -> dict[str, int]:
        if self.nombres is None:
            from ..datos import indice

            if not indice.hay_indice():
                return {}
            con = indice.conectar()
            try:
                self.nombres = nombres_de_reliquias(con)
            finally:
                con.close()
        return self.nombres

    @Slot(int, int, int, str)
    def leer(self, numero: int, x: int, y: int, contexto: str = "") -> None:
        try:
            from . import pantalla

            juego = pantalla.region_juego()
            if juego is None or not juego.contiene(x, y):
                self.leida.emit(numero, x, y, 0, "", 0.0)
                return
            rx, ry, ancho, alto = region_recorte(x, y, juego)
            imagen = pantalla.capturar(pantalla.Region(rx, ry, ancho, alto))
            if imagen is None:
                self.leida.emit(numero, x, y, 0, "", 0.0)
                return
            reliquia_id, refinamiento, ms = self.leer_imagen(imagen, (x - rx, y - ry), (x, y), contexto)
            self.leida.emit(numero, x, y, reliquia_id, refinamiento or "", ms)
        except Exception:  # noqa: BLE001 - un fallo aqui nunca tumba el hilo de captura
            log.exception("Fallo leyendo la reliquia bajo el raton")
            self.leida.emit(numero, x, y, 0, "", 0.0)

    def leer_imagen(self, imagen, cursor, pos_pantalla=(0, 0), contexto: str = "") -> tuple[int, str | None, float]:
        """(reliquia_id o 0, refinamiento, ms del OCR o -1 si salio de la cache). Probable sin ventana."""
        nombres = self._nombres()
        if not nombres:
            return 0, None, 0.0
        marca = huella(imagen)
        guardado, hay = self.cache.buscar(pos_pantalla[0], pos_pantalla[1], contexto, marca)
        if hay:
            return guardado[0], guardado[1], -1.0
        t0 = time.perf_counter()
        motor = self._motor()
        if motor.fallo:
            return 0, None, 0.0
        leer = getattr(motor, "leer_tira", None) or motor.leer
        lineas = leer_ampliando(leer, imagen)
        ms = (time.perf_counter() - t0) * 1000
        self.lecturas += 1
        self.ms_total += ms
        elegida = elegir_reliquia(lineas, cursor, (imagen.shape[1], imagen.shape[0]), nombres)
        resultado = (elegida.reliquia_id, elegida.refinamiento) if elegida else (0, None)
        self.cache.guardar(pos_pantalla[0], pos_pantalla[1], contexto, marca, resultado)
        if elegida:
            log.info("Reliquia bajo el raton: %s (%r, OCR %.0f ms)", elegida.nombre, elegida.texto_ocr, ms)
        else:
            log.debug("Nada seguro bajo el raton (%d lineas, OCR %.0f ms)", len(lineas), ms)
        return resultado[0], resultado[1], ms


# -- controlador (hilo de la interfaz) ------------------------------------------------------


def _tecla_pulsada(vk: int) -> bool:  # pragma: no cover - depende del SO
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except (AttributeError, OSError):
        return False


class HoverReliquias(QObject):
    """Decide cuando leer y cuando ensenar o esconder la tarjeta. Vive en el hilo de la interfaz.

    `mostrar(reliquia_id, refinamiento, x_fisico, y_fisico)` y `ocultar()` los pone quien
    tiene la tarjeta; `sobre_farmadex(x, y)` dice si el cursor esta encima de una
    ventana propia (ahi no se lee: es la app, no el juego).
    """

    pedir_lectura = Signal(int, int, int, str)  # numero, x, y, contexto

    def __init__(self, mostrar: Callable[[int, str, int, int], None], ocultar: Callable[[], None],
                 activo: bool = True, modo: str = "auto", tecla: str = "alt",
                 sobre_farmadex: Callable[[int, int], bool] | None = None, parent=None,
                 reloj: Callable[[], float] = time.monotonic):
        super().__init__(parent)
        self._mostrar, self._ocultar = mostrar, ocultar
        self._sobre_farmadex = sobre_farmadex or (lambda x, y: False)
        self._reloj = reloj
        self.activo = activo
        self.modo = modo if modo in MODOS else "auto"
        self.tecla = tecla if tecla in TECLAS else "alt"
        self.pantalla: str | None = None
        self.detector = DetectorQuieto()
        self.numero = 0
        self.en_curso: int | None = None
        self._t_en_curso = 0.0
        self.ancla: tuple[int, int] | None = None  # donde se leyo lo que se ensena
        self.visible = False
        self._hwnd: int | None = None
        self._t_hwnd = float("-inf")
        self.tics = 0
        self._temporizador = QTimer(self)
        self._temporizador.setInterval(INTERVALO_MS)
        self._temporizador.timeout.connect(self.tic)
        # Para las pruebas: de donde salen el cursor, la ventana activa y la tecla.
        self.cursor = self._cursor_real
        self.juego_delante = self._juego_delante_real
        self.tecla_pulsada = lambda: _tecla_pulsada(TECLAS[self.tecla])

    # -- ajustes y EE.log --

    def iniciar(self) -> None:
        if self.activo:
            self._temporizador.start()

    def parar(self) -> None:
        self._temporizador.stop()
        self._esconder()

    def activar(self, activo: bool) -> None:
        self.activo = bool(activo)
        if self.activo:
            self._temporizador.start()
        else:
            self.parar()

    def cambiar_modo(self, modo: str) -> None:
        self.modo = modo if modo in MODOS else "auto"
        self._esconder()

    def cambiar_tecla(self, tecla: str) -> None:
        self.tecla = tecla if tecla in TECLAS else "alt"

    @Slot(str, str)
    def pantalla_juego(self, accion: str, nombre: str) -> None:
        """Lo que EE.log cuenta de las pantallas (la misma senal que el lector pasivo)."""
        self.pantalla = nombre if accion == "abierta" else ("pausa" if accion == "pausa" else None)
        if self.modo == "auto" and not es_pantalla_de_reliquias(self.pantalla):
            self._esconder()

    # -- sondeo --

    @staticmethod
    def _cursor_real() -> tuple[int, int]:  # pragma: no cover - depende del SO
        from . import pantalla

        return pantalla._posicion_cursor()

    def _juego_delante_real(self) -> bool:  # pragma: no cover - depende del SO
        from . import pantalla

        ahora = self._reloj()
        if ahora - self._t_hwnd > 2.0:  # buscar la ventana recorre todas: cada 2 s basta
            self._hwnd, self._t_hwnd = pantalla.ventana_juego(), ahora
        return bool(self._hwnd) and pantalla._ventana_activa() == self._hwnd

    def debe_mirar(self) -> bool:
        if not self.activo or not self.juego_delante():
            return False
        if self.modo == "tecla":
            return self.tecla_pulsada()
        return es_pantalla_de_reliquias(self.pantalla)

    @Slot()
    def tic(self) -> None:
        self.tics += 1
        try:
            if not self.debe_mirar():
                self._esconder()
                self.detector.reiniciar()
                return
            x, y = self.cursor()
            if self.visible and self.ancla and _lejos(self.ancla, (x, y)):
                self._esconder()
            if self._sobre_farmadex(x, y):
                return
            ahora = self._reloj()
            if self.en_curso is not None and ahora - self._t_en_curso > 5.0:
                self.en_curso = None  # una lectura que no contesto no bloquea para siempre
            if self.detector.observar(ahora, x, y) and not (self.visible and self.ancla and not _lejos(self.ancla, (x, y))):
                if self.en_curso is None:
                    self.numero += 1
                    self.en_curso, self._t_en_curso = self.numero, ahora
                    self.pedir_lectura.emit(self.numero, x, y, self.pantalla or self.modo)
                else:
                    self.detector.reiniciar()  # se vuelve a pedir en la siguiente parada
        except Exception:  # noqa: BLE001 - el temporizador no puede reventar la ventana
            log.exception("Fallo en el sondeo de la reliquia bajo el raton")

    @Slot(int, int, int, int, str, float)
    def leida(self, numero: int, x: int, y: int, reliquia_id: int, refinamiento: str, _ms: float) -> None:
        if numero == self.en_curso:
            self.en_curso = None
        if numero != self.numero or not reliquia_id or not self.debe_mirar():
            return
        if _lejos((x, y), self.cursor()):
            return  # el raton ya se fue a otra cosa mientras se leia
        self.ancla = (x, y)
        self.visible = True
        self._mostrar(reliquia_id, refinamiento, x, y)

    def _esconder(self) -> None:
        if self.visible:
            self.visible = False
            self.ancla = None
            self._ocultar()


def _lejos(a: tuple[int, int], b: tuple[int, int], radio: int = RADIO_PX) -> bool:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 > radio * radio
