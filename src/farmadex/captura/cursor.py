"""'Que es esto': lee el texto que hay alrededor del raton y abre su ficha.

Pulsar el atajo muchas veces seguidas tumbaba el programa: cada pulsacion
encolaba una lectura completa (captura + OCR) en el hilo de captura, y cada una
al acabar volvia a abrir la ventana. Ahora `TurnoLecturas` (en el hilo de la
interfaz) deja una sola lectura en marcha, espera un minimo entre lecturas y,
si se pulsa mientras lee, guarda solo la ultima peticion: las de en medio se
descartan, y el resultado de una lectura que ya tiene otra detras no se ensena.
"""

from __future__ import annotations

import re
import time
from typing import Callable

from PySide6.QtCore import QTimer, Signal, Slot

from ..idiomas import t
from ..registro_log import obtener
from . import pantalla
from .ocr import ErrorMotorOCR, agrupar_bloques, casar_lineas, leer_lineas, resumen_tiempos
from .recompensas_rapidas import RE_DE_PEGADO, RE_DE_PEGADO_ANTES, palabra_de_otro_objeto, palabras_del_catalogo
from .reliquias import LectorBase

log = obtener("cursor")

# Hasta donde amplia RapidOCR el recuadro (620x170 a 1080p) antes de buscar texto. Con los
# 736 de siempre se buscaba a 2684x736; con 608 cuesta ~30 % menos y, medido sobre
# 72 capturas reales (12 recuadros cada una), encuentra 12 nombres mas de los que
# pierde (1) sin colar mas falsos. Con 544 o menos ya perdia nombres.
LADO_MINIMO = 608

# El recuadro alrededor del raton medido a 1080p. Se escala con el alto del juego: a 4K
# los nombres miden el doble y un recuadro fijo solo cogia media palabra; a 720p cogia
# medio inventario de alrededor.
ANCHO_RECUADRO, ALTO_RECUADRO = 620, 170


# Si el raton esta sobre el dibujo de una tarjeta (recompensas, inventario), el nombre
# cae por debajo del recuadro normal: la segunda mirada baja hasta este multiplo del alto.
# Medido en el banco de precision: con el raton en el dibujo de la tarjeta de recompensa
# (a 0,33 del alto) el recuadro normal solo cogia 8 de 34 nombres; con este, todos.
FACTOR_RECUADRO_BAJO = 2.6


def region_mas_baja(region, limite=None, factor: float = FACTOR_RECUADRO_BAJO):
    """El mismo recuadro, estirado hacia abajo (sin salirse de `limite`, la ventana del juego)."""
    alto = int(region.alto * factor)
    if limite is not None:
        alto = min(alto, limite.y + limite.alto - region.y)
    return pantalla.Region(region.x, region.y, region.ancho, max(region.alto, alto))


# "+1 Steel Essence", "+50 Ferrita": el aviso de lo recogido en la mision, no un objeto
# que el raton senale (en el banco de precision se colo como ficha al estirar el recuadro).
RE_RECOGIDO = re.compile(r"^\s*\+\s*\d")


def alineados(encontrados, punto, ancho_region: int) -> list:
    """Lo leido que esta encima o debajo del raton, del mas cercano al mas lejano."""
    encontrados = [r for r in encontrados if not RE_RECOGIDO.match(r.texto_ocr or "")]

    def distancia(r):
        x = r.caja[0] + r.caja[2] / 2
        y = r.caja[1] + r.caja[3] / 2
        return (x - punto[0]) ** 2 + (y - punto[1]) ** 2

    cercanos = [r for r in encontrados if alineado_con_raton(r.caja, punto, ancho_region)]
    return sorted(cercanos, key=lambda r: (distancia(r), -r.puntuacion))


def despegar(texto: str) -> str:
    """"Plano DeForma" -> "Plano De Forma": el OCR pega la preposicion y asi no casaba nada."""
    return RE_DE_PEGADO.sub(r"\1 ", RE_DE_PEGADO_ANTES.sub(r" \1", texto))


def leer_recuadro(imagen, motor, casador, umbral: int = 85, lado_minimo: int | None = LADO_MINIMO):
    """(reconocidos, lineas) del recuadro: lo que casa y todas las lineas leidas."""
    lineas = leer_lineas(imagen, motor, 0.4, lado_minimo)
    for linea in lineas:
        linea.texto = despegar(linea.texto)
    return casar_lineas(lineas, casador, umbral), lineas


def _dentro(linea, caja) -> bool:
    x, y, w, h = caja
    cx, cy = linea.x + linea.ancho / 2, linea.y + linea.alto / 2
    return x <= cx <= x + w and y <= cy <= y + h


# Un trozo de nombre que acaba en preposicion ("Plano De Neuropticas De") esta cortado.
RE_ACABA_EN_ENLACE = re.compile(r"(?i)(?:\b(?:de|del|des|du|der|di|da|do|dos|das|von|of)|[:\-])\s*$")


def a_medias(reconocido, lineas, alto_region: int, padres: set | None = None,
             palabras: set | None = None) -> bool:
    """Si lo casado puede ser solo un trozo del nombre que senala el raton.

    Los nombres largos van en dos lineas ("Plano De Neuropticas De" / "Zephyr Prime").
    Con una sola linea leida, el catalogo encontraba otra cosa: "Jade Neuropticas",
    "Chasse", o el objeto entero ("Caliban Prime") en vez de la pieza. Es dudoso si
    el bloque de lineas en el que esta tiene lineas que no entraron en el casado, o si
    toca el borde de arriba o de abajo del recuadro (la otra linea puede estar fuera).
    Con `padres` (ids de los objetos que tienen piezas) solo se duda de un objeto entero
    o de un texto que acaba en preposicion; sin ellos, de todo lo que pueda estar cortado.
    """
    caja = reconocido.caja
    if palabras and palabra_de_otro_objeto(reconocido.texto_ocr or "", reconocido.nombre or "", palabras):
        return True  # "Akbronco Prime" no es "Bronco Prime"
    if padres is not None and reconocido.item_id not in padres and not RE_ACABA_EN_ENLACE.search(reconocido.texto_ocr or ""):
        # Un nombre completo de pieza (o de algo sin piezas) no se confunde por faltarle una
        # linea: lo peligroso es el objeto entero ("Caliban Prime") o un trozo que acaba en "De".
        return False
    propias = [l for l in lineas if _dentro(l, caja)]
    alto_linea = max([l.alto for l in propias] or [caja[3]])
    if caja[1] < 0.6 * alto_linea or caja[1] + caja[3] > alto_region - 0.8 * alto_linea:
        return True
    for bloque in agrupar_bloques(list(lineas)):
        if any(l in propias for l in bloque) and any(l not in propias for l in bloque):
            return True
    return False


def elegir_bajo_cursor(capturar, region, juego, punto_de, leer, padres: set | None = None,
                       palabras: set | None = None):
    """Lo que senala el raton: (mejor | None, ordenados, texto_dudoso | None).

    `capturar(Region)` da la imagen, `punto_de(Region)` donde esta el raton en ella y
    `leer(imagen)` -> (reconocidos, lineas) o None si el motor fallo. Primera mirada
    con el recuadro normal; si no hay nada alineado con el raton o lo alineado puede
    estar a medias (`a_medias`), segunda mirada con el recuadro estirado hacia abajo.
    Lo que siga a medias no se da por bueno: se devuelve su texto como dudoso.
    """
    imagen = capturar(region)
    if imagen is None:
        return None, [], None
    leido = leer(imagen)
    if leido is None:
        return None, [], None
    encontrados, lineas = leido
    ordenados = alineados(encontrados, punto_de(region), region.ancho)
    dudoso = ordenados and a_medias(ordenados[0], lineas, region.alto, padres, palabras)
    if not ordenados or dudoso:
        region_baja = region_mas_baja(region, juego)
        imagen = capturar(region_baja) if region_baja.alto > region.alto else None
        leido = leer(imagen) if imagen is not None else None
        if leido is not None:
            otros, lineas_b = leido
            ordenados_b = alineados(otros, punto_de(region_baja), region_baja.ancho)
            log.info("Bajo el cursor, segunda mirada mas abajo: %d encontrados, %d alineados", len(otros), len(ordenados_b))
            if ordenados_b and not a_medias(ordenados_b[0], lineas_b, region_baja.alto, padres, palabras):
                return ordenados_b[0], ordenados_b, None
            if ordenados_b or not ordenados:
                ordenados, dudoso = ordenados_b, bool(ordenados_b)
    if ordenados and dudoso:
        return None, ordenados, ordenados[0].texto_ocr
    return (ordenados[0] if ordenados else None), ordenados, None


def tamano_recuadro(alto_juego: int | None) -> tuple[int, int]:
    """(ancho, alto) del recuadro para un juego de ese alto (1080p si no se sabe)."""
    escala = max(0.5, (alto_juego or 1080) / 1080.0)
    return int(ANCHO_RECUADRO * escala), int(ALTO_RECUADRO * escala)


class LectorCursor(LectorBase):
    """Captura un recuadro alrededor del cursor y busca ahi un nombre conocido."""

    encontrado = Signal(int, str)  # item_id, nombre
    candidatos = Signal(list)  # [(item_id, nombre, puntuacion)] cuando hay dudas
    terminado = Signal(int)  # numero de la solicitud; siempre, haya ido bien o mal

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(motor_ocr, None, parent)
        # La ultima solicitud que ha pedido la interfaz. La escribe el hilo de la
        # interfaz (un entero: asignacion atomica) y la lee este hilo antes de ensenar
        # un resultado, para no abrir la ficha de algo que ya no se esta mirando.
        self.ultima_pedida = 0
        self.lado_minimo = LADO_MINIMO  # lo usa LectorBase._leer_protegido
        self._ids_padres: set | None = None

    @Slot()
    def leer_ahora(self) -> None:
        self.leer_solicitud(0)

    @Slot(int)
    def leer_solicitud(self, numero: int) -> None:
        if self._ocupado:
            self.terminado.emit(numero)
            return
        self._ocupado = True
        try:
            self._leer(numero)
        except Exception:  # noqa: BLE001 - ultima red: nunca un dialogo de error
            log.exception("Fallo inesperado leyendo bajo el cursor")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            self.candidatos.emit([])
        finally:
            self._ocupado = False
            self.terminado.emit(numero)

    def _padres(self) -> set | None:
        """Ids de los objetos que tienen piezas (armas y warframes enteros); None si no hay indice."""
        if getattr(self, "_ids_padres", None) is None:
            try:
                from ..datos import indice

                con = indice.conectar()
                try:
                    self._ids_padres = {f[0] for f in con.execute(
                        "SELECT DISTINCT padre_id FROM items WHERE padre_id IS NOT NULL")}
                finally:
                    con.close()
            except Exception:  # noqa: BLE001 - sin indice: se duda de todo lo que pueda estar cortado
                log.debug("Sin indice para saber que objetos tienen piezas", exc_info=True)
                return None
        return self._ids_padres

    def _leer_lineas_protegido(self, imagen):
        """`leer_recuadro` sin que nada se propague: None si el motor no esta disponible."""
        try:
            return leer_recuadro(imagen, self.motor, self.casador, 85, self.lado_minimo)
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            return None

    def _vieja(self, numero: int) -> bool:
        return bool(numero) and numero < self.ultima_pedida

    def _leer(self, numero: int = 0) -> None:
        if not self._preparado():
            self.candidatos.emit([])
            return
        self.estado.emit(t("Leyendo lo que hay bajo el cursor..."))
        inicio = time.perf_counter()
        # Con el juego en ventana, el recuadro no se sale de ella.
        juego = pantalla.region_juego()
        if juego is not None:
            alto_juego = juego.alto
        else:
            try:
                alto_juego = pantalla.region_pantalla_completa().alto
            except Exception:  # noqa: BLE001 - sin Windows (pruebas): como a 1080p
                alto_juego = None
        ancho_r, alto_r = tamano_recuadro(alto_juego)
        region = pantalla.region_alrededor_del_cursor(ancho_r, alto_r, limite=juego)
        fallo = []

        def capturar(r):
            imagen = pantalla.capturar(r)
            if imagen is None and not fallo:
                fallo.append(r)
            return imagen

        mejor, ordenados, dudoso = elegir_bajo_cursor(capturar, region, juego, punto_del_raton, self._leer_lineas_protegido,
                                                     self._padres(), palabras_del_catalogo(getattr(self, "casador", None)))
        fin = time.perf_counter()
        tiempos = getattr(getattr(self, "motor", None), "tiempos", None) or {}
        log.info("Lectura bajo el cursor en %.0f ms (%s): %s", (fin - inicio) * 1000, resumen_tiempos(tiempos),
                 repr(mejor.nombre) if mejor else "nada")
        if fallo and not ordenados:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.candidatos.emit([])
            return
        if dudoso:
            # Leido pero a medias: se dice lo leido en vez de abrir la ficha de otra cosa.
            log.info("Bajo el cursor: %r puede ser solo un trozo del nombre (%s): no se da por bueno",
                     dudoso, ", ".join(repr(r.nombre) for r in ordenados[:3]))
            self.estado.emit(t("Leído: {texto} (sin reconocer)", texto=dudoso))
            self.candidatos.emit([])
            return
        if mejor is None:
            if self.motor.fallo:  # ya se aviso del motor
                self.candidatos.emit([])
                return
            log.info("Bajo el cursor: nada alineado con el raton")
            self.estado.emit(t("No se reconoció nada bajo el cursor"))
            self.candidatos.emit([])
            return
        if self._vieja(numero):
            # Mientras se leia se volvio a pulsar el atajo: manda la lectura nueva.
            log.info("Lectura bajo el cursor %d descartada: ya hay otra pedida (%r)", numero, mejor.nombre)
            return
        log.info("Bajo el cursor: %r -> %s", mejor.texto_ocr, mejor.nombre)
        self.estado.emit(t("Bajo el cursor: {nombre}", nombre=mejor.nombre))
        self.encontrado.emit(mejor.item_id, mejor.nombre)
        self.candidatos.emit(
            [(r.item_id, r.nombre, r.puntuacion) for r in ordenados[:3]]
        )


def punto_del_raton(region) -> tuple[float, float]:
    """Donde esta el raton dentro del recuadro capturado; el centro si no se sabe."""
    centro = region.ancho / 2, region.alto / 2
    try:
        cx, cy = pantalla._posicion_cursor()
        x, y = cx - region.x, cy - region.y
    except Exception:  # noqa: BLE001 - sin posicion (o recuadro de prueba): el centro
        return centro
    if 0 <= x < region.ancho and 0 <= y < region.alto:
        return float(x), float(y)
    return centro


def alineado_con_raton(caja, punto: tuple[float, float], ancho_region: int) -> bool:
    """Si el texto leido esta encima o debajo del raton (en horizontal, con holgura).

    En vertical no se limita: el raton suele estar sobre el icono y el nombre va debajo.
    """
    x0, ancho = caja[0], caja[2]
    hueco = max(0.0, x0 - punto[0], punto[0] - (x0 + ancho))
    return hueco <= max(0.5 * ancho, 0.04 * ancho_region)


class TurnoLecturas:
    """Una lectura bajo el cursor a la vez, con pausa minima y la ultima peticion gana.

    Vive en el hilo de la interfaz. `lanzar(numero)` manda la lectura al hilo de
    captura; quien la haga tiene que avisar con `terminada(numero)` al acabar.
    Si una lectura no avisa nunca (hilo colgado), a los `LIMITE_S` se deja de
    esperarla para que el atajo no se quede muerto para siempre.
    """

    PAUSA_S = 0.8  # entre el inicio de una lectura y el de la siguiente
    LIMITE_S = 20.0

    def __init__(
        self,
        lanzar: Callable[[int], None],
        pausa_s: float | None = None,
        reloj: Callable[[], float] = time.monotonic,
        programar: Callable[[int, Callable[[], None]], None] | None = None,
    ):
        self._lanzar = lanzar
        self.pausa_s = self.PAUSA_S if pausa_s is None else pausa_s
        self._reloj = reloj
        self._programar = programar or (lambda ms, f: QTimer.singleShot(ms, f))
        self.ultima = 0  # numero de la ultima peticion
        self.en_curso: int | None = None
        self._t_inicio = float("-inf")
        self.pendiente = False
        self._programada = False
        self.descartadas = 0

    @property
    def ocupado(self) -> bool:
        return self.en_curso is not None

    def pedir(self) -> str:
        """Una pulsacion del atajo. Devuelve "lanzada" o "en_cola"."""
        self.ultima += 1
        ahora = self._reloj()
        if self.en_curso is not None and ahora - self._t_inicio > self.LIMITE_S:
            log.warning("La lectura bajo el cursor %d no termino en %.0f s: se deja de esperar",
                        self.en_curso, self.LIMITE_S)
            self.en_curso = None
        if self.en_curso is None and ahora - self._t_inicio >= self.pausa_s and not self._programada:
            self._arrancar()
            return "lanzada"
        if self.pendiente:
            self.descartadas += 1
        self.pendiente = True
        if self.en_curso is None:
            self._programar_siguiente()
        return "en_cola"

    def terminada(self, numero: int) -> bool:
        """La lectura `numero` acabo. Devuelve si su resultado sigue valiendo."""
        vigente = numero == self.ultima
        if numero == self.en_curso or numero == 0:
            self.en_curso = None
        if self.pendiente and self.en_curso is None:
            self._programar_siguiente()
        return vigente

    def _programar_siguiente(self) -> None:
        if self._programada:
            return
        falta = max(0.0, self.pausa_s - (self._reloj() - self._t_inicio))
        self._programada = True
        self._programar(int(falta * 1000), self._siguiente)

    def _siguiente(self) -> None:
        self._programada = False
        if self.pendiente and self.en_curso is None:
            self._arrancar()

    def _arrancar(self) -> None:
        self.pendiente = False
        self.en_curso = self.ultima
        self._t_inicio = self._reloj()
        self._lanzar(self.ultima)
