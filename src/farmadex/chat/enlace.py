"""El enlace del chat del juego que hay bajo el raton: color, recorte y OCR de solo el enlace.

En el chat de Warframe cada linea es "[hora] Usuario: texto [Enlace] texto". Colores
medidos en capturas reales del chat (4K, WFChatParser; los mismos que dio el tester):

- nombre de usuario  #84cbce (turquesa claro)
- enlace sin el raton #33ccff (azul)
- enlace con el raton encima #e7d45d (amarillo)

Los bordes de las letras mezclan el color con el fondo (casi negro, o el juego detras si
el chat es transparente), asi que no se compara el color tal cual sino su "direccion": el
pixel dividido por su canal mas alto. Un pixel de enlace a media intensidad sobre negro
sigue apuntando igual que #33ccff; el blanco del texto normal (1, 1, 1) o el dorado de los
menus (1, 0,67, 0) quedan lejos.

Coste: nada mientras el raton se mueve o esta quieto. Al pararse el raton con Warframe
delante se mira UNA tira pequena alrededor del cursor (~0,24 x 0,025 de la altura del
juego); solo si ahi hay amarillo de enlace (y el azul/turquesa de alrededor dice que es el
chat) se captura la linea y se lee con el OCR solo el trozo amarillo, sin detector de
texto: ~10-30 ms. Todo sin distinguir mayusculas.

Este modulo no importa nada de la interfaz: el controlador recibe funciones para ensenar
y esconder la tarjeta.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..registro_log import obtener

log = obtener("chat.enlace")

# (r, g, b) de referencia, en el orden de prioridad que pidio el tester.
USUARIO = (0x84, 0xCB, 0xCE)
ENLACE = (0x33, 0xCC, 0xFF)
AMARILLO = (0xE7, 0xD4, 0x5D)
# Distancia maxima (en "direccion" de color, 0..1 por canal) y brillo minimo relativo.
TOLERANCIA = {USUARIO: 0.10, ENLACE: 0.12, AMARILLO: 0.13}
BRILLO_MINIMO = 0.42

# Geometria en fracciones de la altura del juego.
SONDA_ANCHO, SONDA_ALTO = 0.24, 0.026   # primera mirada, muy pequena
TIRA_ANCHO, TIRA_ALTO = 0.80, 0.090     # la linea entera (enlaces largos) y sus vecinas
ALTO_LINEA_MIN, ALTO_LINEA_MAX = 0.0045, 0.034
HUECO_MAX_REL = 0.9  # hueco entre letras de un mismo enlace, en altos de linea
PIXELES_MIN_REL = 1.2e-5  # amarillo minimo en la sonda (x alto^2): ~56 px a 4K, ~6 a 720p
CHAT_MIN_REL = 1.5e-5  # azul/turquesa minimo en la tira para creer que es el chat

QUIETO_S = 0.12
INTERVALO_MS = 50
TOLERANCIA_PX = 3
RADIO_PX = 30


# -- color ---------------------------------------------------------------------------------


def mascara(imagen_bgr, referencia: tuple[int, int, int], tolerancia: float | None = None):
    """Pixeles del color `referencia` (con sus bordes mezclados con un fondo oscuro)."""
    import numpy as np

    img = imagen_bgr.astype(np.float32)
    b, g, r = img[..., 0], img[..., 1], img[..., 2]
    alto = np.maximum(np.maximum(r, g), b)
    ref = np.array(referencia, dtype=np.float32)
    ref_n = ref / ref.max()
    tol = TOLERANCIA.get(referencia, 0.12) if tolerancia is None else tolerancia
    seguro = np.maximum(alto, 1.0)
    d = np.maximum(np.maximum(np.abs(r / seguro - ref_n[0]), np.abs(g / seguro - ref_n[1])),
                   np.abs(b / seguro - ref_n[2]))
    return (d < tol) & (alto >= BRILLO_MINIMO * ref.max())


def intensidad(imagen_bgr, referencia: tuple[int, int, int] = AMARILLO):
    """0..255: cuanto de "letra de ese color" tiene cada pixel (para darselo al OCR)."""
    import numpy as np

    img = imagen_bgr.astype(np.float32)
    b, g, r = img[..., 0], img[..., 1], img[..., 2]
    alto = np.maximum(np.maximum(r, g), b)
    ref = np.array(referencia, dtype=np.float32)
    ref_n = ref / ref.max()
    seguro = np.maximum(alto, 1.0)
    d = np.maximum(np.maximum(np.abs(r / seguro - ref_n[0]), np.abs(g / seguro - ref_n[1])),
                   np.abs(b / seguro - ref_n[2]))
    parecido = np.clip(1.0 - d / 0.30, 0.0, 1.0)
    return np.clip(parecido * alto / ref.max() * 255.0, 0, 255).astype(np.uint8)


# -- donde esta el enlace -------------------------------------------------------------------


@dataclass
class Caja:
    x: int
    y: int
    ancho: int
    alto: int


def _tramos(indices, hueco: int) -> list[tuple[int, int]]:
    """[(ini, fin)] de indices ordenados, uniendo los separados por <= hueco."""
    salida: list[tuple[int, int]] = []
    for i in indices:
        i = int(i)
        if salida and i - salida[-1][1] <= hueco + 1:
            salida[-1] = (salida[-1][0], i)
        else:
            salida.append((i, i))
    return salida


def caja_bajo_cursor(masc, cursor: tuple[int, int], alto_juego: int, color_mascara=None) -> Caja | None:
    """El trozo de ese color (una linea de texto) que toca el cursor, o None.

    `masc` es la mascara del color en la tira; `cursor` (x, y) en coordenadas de la tira.
    Primero la linea: las filas con color alrededor del cursor, seguidas. Luego, en esas
    filas, el tramo de columnas que contiene (o casi) al cursor.
    """
    import numpy as np

    cx, cy = cursor
    alto_min = max(3, int(ALTO_LINEA_MIN * alto_juego))
    alto_max = max(alto_min + 2, int(ALTO_LINEA_MAX * alto_juego))
    filas = np.flatnonzero(masc.any(axis=1))
    if filas.size == 0:
        return None
    lineas = _tramos(filas, hueco=max(1, alto_min // 3))
    # La linea del cursor: la que lo contiene o la mas cercana (a menos de media linea).
    elegida = None
    mejor = None
    for a, b in lineas:
        distancia = 0 if a <= cy <= b else min(abs(cy - a), abs(cy - b))
        if mejor is None or distancia < mejor:
            mejor, elegida = distancia, (a, b)
    a, b = elegida
    alto_linea = b - a + 1
    if mejor > max(3, alto_linea // 2) or not alto_min <= alto_linea <= alto_max:
        return None
    columnas = np.flatnonzero(masc[a:b + 1].any(axis=0))
    tramos = _tramos(columnas, hueco=max(2, int(HUECO_MAX_REL * alto_linea)))
    holgura = max(4, alto_linea)
    candidatos = [(x0, x1) for x0, x1 in tramos if x0 - holgura <= cx <= x1 + holgura]
    if not candidatos:
        return None
    x0, x1 = min(candidatos, key=lambda t: 0 if t[0] <= cx <= t[1] else min(abs(cx - t[0]), abs(cx - t[1])))
    if x1 - x0 + 1 < 2 * alto_linea:
        return None  # dos o tres letras sueltas: no es un enlace
    return Caja(int(x0), int(a), int(x1 - x0 + 1), int(alto_linea))


def imagen_para_ocr(tira_bgr, caja: Caja, referencia=AMARILLO, alto_objetivo: int = 40):
    """Recorte de la caja como letra oscura sobre blanco, a ~40 px de alto (lo que lee mejor)."""
    import cv2
    import numpy as np

    margen_y = max(2, caja.alto // 3)
    margen_x = max(3, caja.alto // 2)
    y0, y1 = max(0, caja.y - margen_y), min(tira_bgr.shape[0], caja.y + caja.alto + margen_y)
    x0, x1 = max(0, caja.x - margen_x), min(tira_bgr.shape[1], caja.x + caja.ancho + margen_x)
    tinta = intensidad(tira_bgr[y0:y1, x0:x1], referencia)
    gris = 255 - tinta
    escala = alto_objetivo / max(1, gris.shape[0])
    if abs(escala - 1.0) > 0.1:
        gris = cv2.resize(gris, None, fx=escala, fy=escala,
                          interpolation=cv2.INTER_CUBIC if escala > 1 else cv2.INTER_AREA)
    return cv2.cvtColor(np.ascontiguousarray(gris), cv2.COLOR_GRAY2BGR)


def hay_chat(tira_bgr, alto_juego: int) -> bool:
    """¿Hay nombres de usuario o enlaces sin raton en la tira? Asi se sabe que es el chat."""
    minimo = max(4, int(CHAT_MIN_REL * alto_juego * alto_juego))
    return int(mascara(tira_bgr, USUARIO).sum()) + int(mascara(tira_bgr, ENLACE).sum()) >= minimo


def amarillo_suficiente(sonda_bgr, alto_juego: int) -> bool:
    return int(mascara(sonda_bgr, AMARILLO).sum()) >= max(5, int(PIXELES_MIN_REL * alto_juego * alto_juego))


def region_sonda(cx: int, cy: int, juego) -> tuple[int, int, int, int]:
    return _region(cx, cy, juego, SONDA_ANCHO, SONDA_ALTO, 0.5)


def region_tira(cx: int, cy: int, juego, desde_izquierda: bool = False) -> tuple[int, int, int, int]:
    """La linea del cursor y sus vecinas. Con `desde_izquierda`, desde el borde del juego (usuario)."""
    if desde_izquierda:
        alto = max(24, int(TIRA_ALTO * juego.alto))
        ancho = min(juego.ancho, cx - juego.x + int(0.40 * juego.alto))
        y = max(juego.y, min(cy - alto // 2, juego.y + juego.alto - alto))
        return juego.x, y, max(1, ancho), min(alto, juego.alto)
    return _region(cx, cy, juego, TIRA_ANCHO, TIRA_ALTO, 0.45)


def _region(cx, cy, juego, ancho_rel, alto_rel, izquierda) -> tuple[int, int, int, int]:
    ancho = max(64, int(ancho_rel * juego.alto))
    alto = max(12, int(alto_rel * juego.alto))
    x = cx - int(ancho * izquierda)
    y = cy - alto // 2
    x = max(juego.x, min(x, juego.x + juego.ancho - ancho))
    y = max(juego.y, min(y, juego.y + juego.alto - alto))
    return x, y, min(ancho, juego.ancho), min(alto, juego.alto)


# -- OCR del recorte ------------------------------------------------------------------------


def leer_recorte(motor_ocr, imagen) -> tuple[str, float]:
    """Texto de un recorte de UNA linea: el reconocedor de RapidOCR a pelo (sin detector).

    Con el OCR de Windows (u otro motor sin reconocedor suelto) se usa su lectura de tira.
    """
    try:
        motor = motor_ocr._cargar()
    except Exception:  # noqa: BLE001
        return "", 0.0
    reconocedor = getattr(motor, "text_recognizer", None)
    if reconocedor is not None:
        try:
            textos, _ = reconocedor([imagen])
            if textos:
                texto, confianza = textos[0]
                return str(texto).strip(), float(confianza)
        except Exception as e:  # noqa: BLE001 - onnxruntime lanza de todo
            log.warning("El OCR del enlace fallo: %s", e)
            return "", 0.0
        return "", 0.0
    lineas = motor_ocr.leer_tira(imagen)
    if not lineas:
        return "", 0.0
    lineas.sort(key=lambda l: l.x)
    return " ".join(l.texto for l in lineas), min(l.confianza for l in lineas)


def usuario_de_linea(tira_bgr, caja_enlace: Caja, alto_juego: int, motor_ocr) -> str:
    """El nombre (turquesa) de la linea del enlace, a su izquierda, sin los dos puntos; '' si no se ve."""
    import numpy as np

    y0 = max(0, caja_enlace.y - caja_enlace.alto // 2)
    y1 = min(tira_bgr.shape[0], caja_enlace.y + caja_enlace.alto + caja_enlace.alto // 2)
    banda = tira_bgr[y0:y1, : max(1, caja_enlace.x)]
    if banda.size == 0:
        return ""
    masc = mascara(banda, USUARIO)
    columnas = np.flatnonzero(masc.any(axis=0))
    if columnas.size == 0:
        return ""
    tramos = _tramos(columnas, hueco=max(2, int(0.6 * caja_enlace.alto)))
    x0, x1 = tramos[-1]  # el nombre mas cercano por la izquierda
    caja = Caja(int(x0), 0, int(x1 - x0 + 1), banda.shape[0])
    texto, confianza = leer_recorte(motor_ocr, imagen_para_ocr(banda, caja, USUARIO))
    texto = texto.strip().rstrip(":").strip()
    if confianza < 0.6 or not texto or " " in texto:
        return ""
    return texto


# -- lector (hilo propio) ---------------------------------------------------------------------


@dataclass
class Lectura:
    numero: int
    x: int
    y: int
    texto: str = ""
    confianza: float = 0.0
    usuario: str = ""
    ms: float = 0.0
    motivo: str = ""  # por que no hay enlace (para el registro)


class LectorEnlaceChat(QObject):
    """Sonda, tira y OCR. Vive en su propio hilo: nunca espera detras de otra lectura."""

    leida = Signal(object)  # Lectura

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(parent)
        self._modo_motor = motor_ocr
        self.motor = None
        self.con_usuario = False
        self.sondas = 0
        self.lecturas = 0
        self.ms_sondas = 0.0

    @Slot(str)
    def cambiar_motor(self, motor_ocr: str) -> None:
        self._modo_motor = motor_ocr
        self.motor = None

    def _motor(self):
        if self.motor is None:
            from ..captura.ocr import MotorOCR

            self.motor = MotorOCR(self._modo_motor)
        return self.motor

    @Slot(int, int, int)
    def leer(self, numero: int, x: int, y: int) -> None:
        inicio = time.perf_counter()
        lectura = Lectura(numero, x, y)
        try:
            from ..captura import pantalla

            juego = pantalla.region_juego()
            if juego is None or not juego.contiene(x, y):
                lectura.motivo = "fuera del juego"
            else:
                self._leer_en(pantalla, juego, lectura)
        except Exception:  # noqa: BLE001 - un fallo aqui nunca tumba el hilo
            log.exception("Fallo leyendo el enlace del chat")
            lectura.motivo = "error"
        lectura.ms = (time.perf_counter() - inicio) * 1000
        self.leida.emit(lectura)

    def _capturar(self, pantalla, region):
        imagen = pantalla.capturar_sin_ocultar(region)
        # Lo nuestro (la tarjeta de precio) no puede leerse como si fuera el juego.
        return pantalla.descartar_propias(imagen, region, tapado_maximo=0.9)

    def _leer_en(self, pantalla, juego, lectura: Lectura) -> None:
        self.sondas += 1
        t0 = time.perf_counter()
        sx, sy, sw, sh = region_sonda(lectura.x, lectura.y, juego)
        sonda = self._capturar(pantalla, pantalla.Region(sx, sy, sw, sh))
        hay = sonda is not None and amarillo_suficiente(sonda, juego.alto)
        self.ms_sondas += (time.perf_counter() - t0) * 1000
        if not hay:
            lectura.motivo = "sin amarillo"
            return
        desde_izquierda = self.con_usuario
        tx, ty, tw, th = region_tira(lectura.x, lectura.y, juego, desde_izquierda)
        tira = self._capturar(pantalla, pantalla.Region(tx, ty, tw, th))
        if tira is None:
            lectura.motivo = "sin captura"
            return
        texto, confianza, usuario, motivo = self.leer_imagen(tira, (lectura.x - tx, lectura.y - ty), juego.alto)
        lectura.texto, lectura.confianza, lectura.usuario, lectura.motivo = texto, confianza, usuario, motivo

    def leer_imagen(self, tira, cursor, alto_juego: int) -> tuple[str, float, str, str]:
        """(texto del enlace, confianza, usuario, motivo si no hay). Probable sin ventana."""
        if not hay_chat(tira, alto_juego):
            return "", 0.0, "", "no parece el chat"
        caja = caja_bajo_cursor(mascara(tira, AMARILLO), cursor, alto_juego)
        if caja is None:
            return "", 0.0, "", "amarillo sin forma de enlace"
        motor = self._motor()
        if motor.fallo:
            return "", 0.0, "", "sin OCR"
        texto, confianza = leer_recorte(motor, imagen_para_ocr(tira, caja))
        self.lecturas += 1
        usuario = usuario_de_linea(tira, caja, alto_juego, motor) if self.con_usuario and texto else ""
        return texto, confianza, usuario, ""


# -- controlador (hilo de la interfaz) ----------------------------------------------------------


class HoverChat(QObject):
    """Decide cuando mirar y cuando ensenar o esconder la tarjeta. Vive en el hilo de la interfaz.

    `mostrar(lectura)` recibe una `Lectura` con texto (el enlace leido) y la posicion; quien
    la recibe resuelve el nombre y pinta. `ocultar()` la esconde. Solo se mira con Warframe
    delante, fuera de las ventanas de Farmadex, y una vez por parada del raton.
    """

    pedir_lectura = Signal(int, int, int)

    def __init__(self, mostrar: Callable[[object], bool], ocultar: Callable[[], None],
                 activo: bool = True, sobre_farmadex: Callable[[int, int], bool] | None = None,
                 parent=None, reloj: Callable[[], float] = time.monotonic):
        super().__init__(parent)
        from ..captura.reliquia_hover import DetectorQuieto

        self._mostrar, self._ocultar = mostrar, ocultar
        self._sobre_farmadex = sobre_farmadex or (lambda x, y: False)
        self._reloj = reloj
        self.activo = activo
        self.detector = DetectorQuieto(QUIETO_S, TOLERANCIA_PX)
        self.numero = 0
        self.en_curso: int | None = None
        self._t_en_curso = 0.0
        self.t_parada: dict[int, float] = {}  # numero -> cuando se paro el raton (latencia)
        self.ancla: tuple[int, int] | None = None
        self.visible = False
        self._hwnd: int | None = None
        self._t_hwnd = float("-inf")
        self.tics = 0
        self._temporizador = QTimer(self)
        self._temporizador.setInterval(INTERVALO_MS)
        self._temporizador.timeout.connect(self.tic)
        self.cursor = self._cursor_real
        self.juego_delante = self._juego_delante_real

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

    @staticmethod
    def _cursor_real() -> tuple[int, int]:  # pragma: no cover - depende del SO
        from ..captura import pantalla

        return pantalla._posicion_cursor()

    def _juego_delante_real(self) -> bool:  # pragma: no cover - depende del SO
        from ..captura import pantalla

        ahora = self._reloj()
        if ahora - self._t_hwnd > 2.0:
            self._hwnd, self._t_hwnd = pantalla.ventana_juego(), ahora
        return bool(self._hwnd) and pantalla._ventana_activa() == self._hwnd

    @Slot()
    def tic(self) -> None:
        self.tics += 1
        try:
            if not self.activo or not self.juego_delante():
                self._esconder()
                self.detector.reiniciar()
                return
            x, y = self.cursor()
            if self.visible and self.ancla and _lejos(self.ancla, (x, y)):
                self._esconder()
            if self._sobre_farmadex(x, y):
                return
            ahora = self._reloj()
            if self.en_curso is not None and ahora - self._t_en_curso > 3.0:
                self.en_curso = None
            if self.detector.observar(ahora, x, y) and not (self.visible and self.ancla
                                                            and not _lejos(self.ancla, (x, y))):
                if self.en_curso is None:
                    self.numero += 1
                    self.en_curso, self._t_en_curso = self.numero, ahora
                    self.t_parada = {self.numero: ahora - QUIETO_S}
                    self.pedir_lectura.emit(self.numero, x, y)
                else:
                    self.detector.reiniciar()
        except Exception:  # noqa: BLE001 - el temporizador no puede reventar la ventana
            log.exception("Fallo en el sondeo del chat")

    @Slot(object)
    def leida(self, lectura) -> None:
        if lectura.numero == self.en_curso:
            self.en_curso = None
        if lectura.numero != self.numero or not lectura.texto or not self.activo:
            return
        if _lejos((lectura.x, lectura.y), self.cursor()):
            return  # el raton ya se fue mientras se leia
        if self._mostrar(lectura):
            self.ancla = (lectura.x, lectura.y)
            self.visible = True

    def latencia_ms(self, numero: int) -> float | None:
        t = self.t_parada.get(numero)
        return None if t is None else (self._reloj() - t) * 1000

    def _esconder(self) -> None:
        if self.visible:
            self.visible = False
            self.ancla = None
            self._ocultar()


def _lejos(a: tuple[int, int], b: tuple[int, int], radio: int = RADIO_PX) -> bool:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 > radio * radio
