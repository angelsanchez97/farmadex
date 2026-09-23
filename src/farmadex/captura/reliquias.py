"""Lectura de la pantalla de recompensas de reliquia y etiquetas encima de ella.

Cuando el juego abre esa pantalla (lo dice EE.log) o cuando se pulsa el atajo,
se captura la ventana, se leen los 1-4 nombres y se pinta encima de cada uno
lo que interesa: platino, si esta en boveda y si te sirve para un objetivo.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..idiomas import t
from ..registro_log import obtener
from . import pantalla
from .ocr import (
    Casador, ErrorMotorOCR, Leido, MotorOCR, Reconocido, _caja_union, agrupar_bloques, casar_lineas,
    leer_lineas, reconocer,
)

log = obtener("reliquias")

# La franja de la pantalla donde el juego pinta las recompensas (proporciones).
# Las tarjetas estan centradas en vertical y repartidas en horizontal.
FRANJA = (0.10, 0.30, 0.90, 0.72)

AVISO_MOTOR = "No se pudo cargar el lector de pantalla (mira el registro)"
AVISO_DATOS = "Los datos del juego todavia no estan preparados"

CATEGORIAS_RECOMPENSA = (
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
    "Resources",
    "Misc",
    "Gear",
    "Railjack",
)


# Alto de franja a partir del cual se reduce la imagen antes del OCR (1080p da 454).
ALTO_FRANJA_OCR = 454
SIN_IDENTIFICAR = 0  # item_id de una tarjeta leida que no casa con el catalogo


@dataclass
class Recompensa:
    item_id: int  # SIN_IDENTIFICAR (0) si la tarjeta se vio pero no se reconocio
    nombre: str
    texto_ocr: str
    caja: tuple[int, int, int, int]  # en coordenadas de pantalla
    criterio_platino: str = ""  # "minimo" (vendedor mas barato) o "mediana"
    ducados: int | None = None
    vaulted: bool = False
    objetivo: str = ""
    platino: int | None = None
    # Lo rellena `completar`:
    unique_name: str = ""
    market_slug: str = ""
    comerciable: bool = True
    # Lo rellena `comparador.puntuar`:
    rareza: str | None = None  # "comun", "poco comun", "rara" o None si no se sabe
    valor: float | None = None  # platino equivalente; None = no se pudo valorar
    mejor: bool = False  # la que conviene elegir
    nota: str = ""  # por que falta algo ("Sin precio: ...")


class LectorBase(QObject):
    """Lo comun a los lectores: motor compartido, casador y fallos que no revientan.

    Un fallo del motor OCR (modulo que PyInstaller no arrastro, modelo que falta,
    paquete de idioma de Windows sin instalar) se registra, se avisa UNA vez por
    la senal `estado` y la aplicacion sigue con el resto de pestanas. Al cambiar
    el motor en Ajustes (`cambiar_motor`) se vuelve a intentar.
    """

    estado = Signal(str)

    def __init__(self, motor_ocr: str = "rapidocr", categorias=None, parent=None):
        super().__init__(parent)
        self.motor = MotorOCR(motor_ocr)
        self.categorias = categorias
        self.casador: Casador | None = None
        self._ocupado = False
        self._avisado_motor = False

    @Slot()
    def iniciar(self) -> None:
        """Prepara el casador con el indice y precalienta el motor OCR.

        Corre en el hilo de captura al arrancar, cuando nadie espera: asi la primera
        reliquia no paga la carga del modelo ni la primera inferencia (~800 ms
        medidos). Si no hay indice, el casador se reintenta luego.
        """
        from ..datos import indice

        self._precalentar()
        if not indice.hay_indice():
            self.casador = None
            return
        con = indice.conectar()
        try:
            self.casador = (
                Casador(con, self.categorias) if self.categorias else Casador(con)
            )
        finally:
            con.close()
        pantalla.declarar_dpi()

    def _precalentar(self) -> None:
        """Carga y calienta el motor sin que un fallo reviente el arranque.

        Un motor que no carga deja su motivo apuntado en `MotorOCR`; se avisa al
        usuario en la primera lectura (`_preparado`), no aqui, para que el aviso
        salga una sola vez y cuando el tiene algo que ver.
        """
        try:
            self.motor.precalentar()
        except ErrorMotorOCR as e:
            log.debug("El motor OCR no se pudo precalentar: %s", e)
        except Exception:  # noqa: BLE001 - un calentamiento no puede tumbar el arranque
            log.exception("Fallo inesperado precalentando el motor OCR")

    @Slot(str)
    def cambiar_motor(self, motor_ocr: str) -> None:
        """El usuario eligio otro motor en Ajustes: se vuelve a intentar con el."""
        MotorOCR.olvidar_fallo(motor_ocr)
        self.motor = MotorOCR(motor_ocr)
        self._avisado_motor = False
        self._precalentar()

    def _preparado(self) -> bool:
        """Casador listo y motor sin fallo conocido; si no, avisa y devuelve False."""
        if self.casador is None:
            self.iniciar()
            if self.casador is None:
                self.estado.emit(t(AVISO_DATOS))
                return False
        if self.motor.fallo:
            self._avisar_motor(self.motor.fallo)
            return False
        return True

    def _avisar_motor(self, motivo: str) -> None:
        if not self._avisado_motor:
            self._avisado_motor = True
            log.error("Lector de pantalla no disponible: %s", motivo)
            self.estado.emit(t(AVISO_MOTOR))
        else:
            log.debug("Lector de pantalla sigue sin estar disponible: %s", motivo)

    def _leer_protegido(self, imagen, umbral: int) -> list[Reconocido] | None:
        """`reconocer` sin que nada se propague: None si el motor no esta disponible."""
        try:
            return reconocer(imagen, self.motor, self.casador, umbral=umbral)
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            return None
        except Exception:  # noqa: BLE001 - un fallo de lectura no puede tumbar la app
            log.exception("Fallo leyendo la pantalla")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            return None


class LectorRecompensas(LectorBase):
    """Hace la captura y el OCR en su hilo; devuelve las recompensas reconocidas.

    Si EE.log ya ha dicho que recompensas hay en pantalla (`pista` con
    "recompensa"), esos nombres se casan primero contra un conjunto cerrado con
    un umbral mas bajo (`UMBRAL_CONOCIDAS`): mismo OCR, casado mas seguro. Lo
    que el log no dijo se sigue casando contra el catalogo entero.
    """

    leidas = Signal(list)  # list[Recompensa]

    UMBRAL_CONOCIDAS = 70

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(motor_ocr, CATEGORIAS_RECOMPENSA, parent)
        self.conocidas: list[str] = []  # unique_names que EE.log dio para esta reliquia
        self.jugadores: int | None = None  # tamano de la escuadra segun EE.log
        self._casador_conocidas: Casador | None = None
        self._t_aviso: float | None = None  # cuando EE.log aviso de la pantalla

    @Slot(str, str)
    def pista(self, tipo: str, valor: str) -> None:
        if tipo == "recompensa" and valor not in self.conocidas:
            self.conocidas.append(valor)
            self._casador_conocidas = None
        elif tipo == "remotos":
            try:
                self.jugadores = min(4, int(valor) + 1)
            except ValueError:
                self.jugadores = None

    @Slot(str)
    def evento(self, nombre: str) -> None:
        if nombre == "reliquia_abierta":
            self.conocidas = []
            self._casador_conocidas = None
            self._t_aviso = time.monotonic()
        elif nombre == "reliquia_recompensas":
            self._t_aviso = time.monotonic()
        elif nombre == "reliquia_cerrada":
            self.conocidas = []
            self._casador_conocidas = None
            self._t_aviso = None

    def _conocidas(self) -> Casador | None:
        """Casador restringido a lo que EE.log dio; None si no dio nada o no esta en el indice."""
        if not self.conocidas or self.casador is None:
            return None
        if self._casador_conocidas is None:
            from ..datos import indice

            con = indice.conectar()
            try:
                marcas = ",".join("?" for _ in self.conocidas)
                ids = {f[0] for f in con.execute(
                    f"SELECT id FROM items WHERE unique_name IN ({marcas})", tuple(self.conocidas)
                )}
            finally:
                con.close()
            self._casador_conocidas = self.casador.restringido(ids) if ids else None
        return self._casador_conocidas

    @Slot()
    def leer_ahora(self) -> None:
        """Captura la franja de recompensas y reconoce lo que haya."""
        if self._ocupado:
            return
        self._ocupado = True
        try:
            self._leer()
        except Exception:  # noqa: BLE001 - ultima red: nunca un dialogo de error
            log.exception("Fallo inesperado leyendo las recompensas")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            self.leidas.emit([])
        finally:
            self._ocupado = False

    # Si la lectura sale corta (menos tarjetas que jugadores, o ninguna), se vuelve
    # a mirar enseguida en vez de esperar a ciegas; hasta PLAZO_REINTENTO_S desde el
    # aviso de EE.log, que es mucho menos que los 15 s de la cuenta atras.
    REINTENTO_MS = 150
    PLAZO_REINTENTO_S = 3.0

    def _toca_reintentar(self, halladas: int) -> bool:
        if self._t_aviso is None:
            return False
        if time.monotonic() - self._t_aviso > self.PLAZO_REINTENTO_S:
            return False
        esperadas = self.jugadores or 1
        return halladas < esperadas

    def _reintentar(self) -> None:
        QTimer.singleShot(self.REINTENTO_MS, self.leer_ahora)

    def _leer(self) -> None:
        if not self._preparado():
            self.leidas.emit([])
            return
        self.estado.emit(t("Leyendo la pantalla..."))
        tiempos: dict[str, float] = {}
        t0 = time.perf_counter()
        ventana = pantalla.region_objetivo()
        region = ventana.recortar(*FRANJA)
        imagen = pantalla.capturar(region)
        tiempos["captura"] = time.perf_counter() - t0
        if imagen is None:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.leidas.emit([])
            return
        encontrados = self._leer_y_casar(imagen, tiempos)
        if encontrados is None:
            self.leidas.emit([])
            return
        if not encontrados and self._toca_reintentar(0):
            # Pronto para la pantalla: se vuelve a mirar en 150 ms sin gastar una
            # segunda lectura de la ventana entera ni borrar lo que haya pintado.
            self._anotar_tiempos(tiempos, imagen, ventana, 0)
            self._reintentar()
            return
        if not encontrados:
            # Si un parche mueve las tarjetas fuera de la franja habitual, se lee
            # la ventana entera antes de dar la pantalla por vacia.
            log.info("Nada en la franja de recompensas; se prueba con la ventana entera")
            imagen = pantalla.capturar(ventana)
            if imagen is not None:
                region = ventana
                encontrados = self._leer_y_casar(imagen, tiempos)
                if encontrados is None:
                    self.leidas.emit([])
                    return
                if encontrados:
                    log.warning(
                        "Las recompensas estaban fuera de la franja esperada: "
                        "puede que el juego haya cambiado la pantalla"
                    )
        self._anotar_tiempos(tiempos, imagen, ventana, len(encontrados))
        # Primero la fila (si no, la copia de otro overlay con mas puntuacion
        # desplazaria a la tarjeta real), y dentro de la fila una por objeto.
        fila = elegir_fila(
            encontrados, tiempos.pop("_lineas", []),
            conocidas=self._ids_conocidas(), maximo=self.jugadores or 4,
        )
        recompensas = [
            Recompensa(
                item_id=r.item_id,
                nombre=r.nombre if r.item_id != SIN_IDENTIFICAR else t("Sin identificar"),
                texto_ocr=r.texto_ocr,
                caja=(
                    region.x + r.caja[0],
                    region.y + r.caja[1],
                    r.caja[2],
                    r.caja[3],
                ),
            )
            for r in fila
        ]
        log.info(
            "Recompensas leidas: %s",
            ", ".join(f"{r.texto_ocr} -> {r.nombre}" for r in recompensas) or "ninguna",
        )
        self.estado.emit(
            t("{n} recompensas reconocidas", n=len(recompensas)) if recompensas else
            t("No se reconocio ninguna recompensa")
        )
        self.leidas.emit(recompensas)
        if self._toca_reintentar(len(recompensas)):
            # Se pinta ya lo que hay y se completa con la siguiente mirada.
            self._reintentar()


    def _ids_conocidas(self) -> set[int]:
        casador = self._conocidas()
        return {v[0] for v in casador.candidatos.values()} if casador else set()

    def _leer_y_casar(self, imagen, tiempos: dict) -> list[Reconocido] | None:
        """OCR una vez; casado primero contra lo que EE.log dio y luego contra todo.

        Una franja mas alta que la de 1080p se reduce antes del OCR: el tiempo
        del motor crece con los pixeles y a 1440p, con el juego peleando por la
        CPU, era lo que dejaba las etiquetas para los ultimos segundos.
        """
        try:
            t0 = time.perf_counter()
            escala = 1.0
            if imagen.shape[0] > ALTO_FRANJA_OCR * 1.15:
                import cv2

                escala = ALTO_FRANJA_OCR / imagen.shape[0]
                imagen = cv2.resize(
                    imagen, (int(imagen.shape[1] * escala), ALTO_FRANJA_OCR), interpolation=cv2.INTER_AREA
                )
            lineas = leer_lineas(imagen, self.motor)
            if escala != 1.0:
                for l in lineas:
                    l.x, l.y = int(l.x / escala), int(l.y / escala)
                    l.ancho, l.alto = int(l.ancho / escala), int(l.alto / escala)
            tiempos["_lineas"] = lineas
            tiempos["escala"] = escala
            tiempos["ocr"] = tiempos.get("ocr", 0.0) + time.perf_counter() - t0
            t0 = time.perf_counter()
            conocidas = self._conocidas()
            seguros = casar_lineas(lineas, conocidas, self.UMBRAL_CONOCIDAS) if conocidas else []
            resto = casar_lineas(lineas, self.casador, 80)
            encontrados = seguros + _sin_solapar(resto, seguros)
            tiempos["casado"] = tiempos.get("casado", 0.0) + time.perf_counter() - t0
            tiempos["lineas"] = len(lineas)
            tiempos["conocidas"] = len(seguros)
            return encontrados
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            return None
        except Exception:  # noqa: BLE001 - un fallo de lectura no puede tumbar la app
            log.exception("Fallo leyendo la pantalla")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            return None

    def _anotar_tiempos(self, tiempos: dict, imagen, ventana, encontradas: int) -> None:
        """Una linea de INFO por lectura, para diagnosticar a distancia sin datos personales."""
        desde_aviso = (
            f"{(time.monotonic() - self._t_aviso) * 1000:.0f} ms desde el aviso de EE.log"
            if self._t_aviso is not None else "por atajo"
        )
        alto, ancho = imagen.shape[:2] if imagen is not None else (0, 0)
        log.info(
            "Reliquia: captura %.0f ms, ocr %.0f ms, casado %.0f ms; %d lineas, %d recompensas "
            "(%d por EE.log de %d conocidas); franja %dx%d de una ventana de %dx%d; motor %s x%d hilos; %s",
            tiempos.get("captura", 0) * 1000, tiempos.get("ocr", 0) * 1000, tiempos.get("casado", 0) * 1000,
            tiempos.get("lineas", 0), encontradas, tiempos.get("conocidas", 0), len(self.conocidas),
            ancho, alto, ventana.ancho, ventana.alto, self.motor.motor, self.motor.hilos, desde_aviso,
        )


def _solapan_vertical(a, b, minimo: float = 0.3) -> bool:
    """True si las dos cajas comparten al menos `minimo` del alto de la mas baja."""
    _, ya, _, ha = a
    _, yb, _, hb = b
    solape = min(ya + ha, yb + hb) - max(ya, yb)
    return solape >= minimo * max(1, min(ha, hb))


def _se_tocan(a, b) -> bool:
    xa, ya, wa, ha = a
    xb, yb, wb, hb = b
    return min(xa + wa, xb + wb) > max(xa, xb) and min(ya + ha, yb + hb) > max(ya, yb)


RE_NOMBRE_PLAUSIBLE = re.compile(r"^[^\d]{6,}$")


def elegir_fila(
    encontrados: list[Reconocido],
    lineas: list[Leido],
    conocidas: set[int] | None = None,
    maximo: int = 4,
) -> list[Reconocido]:
    """Se queda con la fila de tarjetas del juego y descarta el resto.

    Las recompensas van en una sola fila, repartidas en horizontal. Otro overlay
    (AlecaFrame) repite los mismos nombres mas abajo, y los nombres de la
    escuadra van entre medias: por eso, de todas las filas con algo casado, se
    elige la que mas recompensas de EE.log contiene y, a igualdad, la de mas
    arriba. En esa fila, lo que se lee como nombre y no casa entra como "sin
    identificar" (item_id SIN_IDENTIFICAR): se ve que hay una tarjeta y que no
    se sabe cual es, en vez de inventar una. Nunca mas de `maximo` (jugadores).
    """
    if not encontrados:
        return []
    conocidas = conocidas or set()
    # Filas: bloques de lineas que se solapan en vertical.
    bloques = agrupar_bloques(list(lineas)) if lineas else [[]]
    cajas = [_caja_union(b) for b in bloques if b]
    filas: list[list[tuple]] = []
    for caja in sorted(cajas, key=lambda c: c[1]):
        for fila in filas:
            if _solapan_vertical(fila[0], caja):
                fila.append(caja)
                break
        else:
            filas.append([caja])
    if not filas:
        filas = [[r.caja for r in encontrados]]

    def casados_en(fila):
        return [r for r in encontrados if any(_se_tocan(r.caja, c) for c in fila)]

    candidatas = [(f, casados_en(f)) for f in filas]
    candidatas = [(f, c) for f, c in candidatas if c]
    if not candidatas:
        return sorted(_quitar_repetidos(encontrados), key=lambda r: r.caja[0])[:maximo]
    fila, casados = max(
        candidatas,
        key=lambda fc: (sum(1 for r in fc[1] if r.item_id in conocidas), -min(c[1] for c in fc[0])),
    )
    casados = _quitar_repetidos(casados)
    descartadas = len(encontrados) - len(casados)
    if descartadas:
        log.info(
            "Recompensas fuera de la fila de tarjetas, descartadas: %d (fila elegida en y=%d de %d filas)",
            descartadas, min(c[1] for c in fila), len(filas),
        )
    # Nombres de la misma fila que no casaron: se ensenan como no identificados.
    textos = {tuple(_caja_union(b)): " ".join(l.texto for l in b) for b in bloques if b}
    salida = list(casados)
    for caja in fila:
        if any(_se_tocan(caja, r.caja) for r in casados):
            continue
        texto = textos.get(tuple(caja), "")
        if RE_NOMBRE_PLAUSIBLE.match(texto.strip()):
            salida.append(Reconocido(texto, SIN_IDENTIFICAR, "", 0.0, tuple(caja)))
            log.info("Tarjeta sin identificar: %r", texto)
    salida.sort(key=lambda r: r.caja[0])
    if len(salida) > maximo:
        log.info("Mas tarjetas (%d) que jugadores (%d): se dejan las %d de mayor parecido",
                 len(salida), maximo, maximo)
        salida = sorted(sorted(salida, key=lambda r: -r.puntuacion)[:maximo], key=lambda r: r.caja[0])
    return salida


def _sin_solapar(nuevos: list[Reconocido], seguros: list[Reconocido]) -> list[Reconocido]:
    """Descarta lo casado contra el catalogo entero que pisa una linea ya casada por EE.log."""
    salida = []
    for r in nuevos:
        x, y, w, h = r.caja
        pisa = any(
            min(x + w, sx + sw) > max(x, sx) and min(y + h, sy + sh) > max(y, sy)
            for sx, sy, sw, sh in (s.caja for s in seguros)
        )
        if not pisa:
            salida.append(r)
    return salida


def texto_platino(r: Recompensa) -> str:
    """'3 platino (venta mas barata)' o '3 platino (mediana)': que precio es, no solo cuanto."""
    if r.criterio_platino == "minimo":
        return t("{n} platino (venta mas barata)", n=r.platino)
    if r.criterio_platino == "mediana":
        return t("{n} platino (mediana)", n=r.platino)
    return t("{n} platino", n=r.platino)


def _quitar_repetidos(encontrados: list[Reconocido]) -> list[Reconocido]:
    """El OCR parte los nombres en varias lineas: se queda la mejor por objeto."""
    mejores: dict[int, Reconocido] = {}
    for r in encontrados:
        previo = mejores.get(r.item_id)
        if previo is None or r.puntuacion > previo.puntuacion:
            mejores[r.item_id] = r
    return sorted(mejores.values(), key=lambda r: r.caja[0])


def completar(
    recompensas: list[Recompensa], indice_con: sqlite3.Connection, usuario_con=None
) -> list[Recompensa]:
    """Anade ducados, estado de boveda y si cubre algun objetivo pendiente."""
    for r in recompensas:
        fila = indice_con.execute(
            "SELECT ducados, vaulted, unique_name, market_slug, comerciable FROM items WHERE id = ?",
            (r.item_id,),
        ).fetchone()
        if not fila:
            continue
        r.ducados, r.vaulted = fila[0], bool(fila[1])
        r.unique_name = fila[2] or ""
        r.market_slug = fila[3] or ""
        r.comerciable = bool(fila[4])
        if usuario_con is not None:
            objetivo = usuario_con.execute(
                "SELECT nombre, cantidad_actual, cantidad_objetivo FROM objetivos "
                "WHERE item_unique_name = ? AND completado_en IS NULL",
                (fila[2],),
            ).fetchone()
            if objetivo:
                r.objetivo = f"{objetivo[1]}/{objetivo[2]}"
    return recompensas


def resumir(recompensas: list[Recompensa]) -> str:
    """Una linea con lo leido, para cuando no se puede pintar encima del juego."""
    trozos = []
    for r in recompensas:
        detalles = []
        if r.platino is not None:
            detalles.append(texto_platino(r))
        if r.ducados:
            detalles.append(t("{n} ducados", n=r.ducados))
        if r.vaulted:
            detalles.append(t("En boveda"))
        if r.objetivo:
            detalles.append(t("Objetivo: {nombre}", nombre=r.objetivo))
        if r.nota:
            detalles.append(r.nota)
        nombre = t("MEJOR: {nombre}", nombre=r.nombre) if r.mejor else r.nombre
        trozos.append(f"{nombre} ({', '.join(detalles)})" if detalles else nombre)
    return " · ".join(trozos)


class DisparadorAutomatico(QObject):
    """Convierte los eventos de EE.log en una lectura, con su espera y su interruptor."""

    disparar = Signal()

    # Medido en el video de un usuario: en el primer fotograma de la pantalla (cuenta
    # atras en 15) los nombres ya se leen, y EE.log escribe "Got rewards" ~0,4 s
    # despues de abrirse. La espera fija de 1,5 s era margen sin medir y era el
    # trozo mas grande del retraso. Si la primera lectura llega antes de tiempo, el
    # lector reintenta solo (LectorRecompensas.REINTENTO_MS).
    ESPERA_MS = 150

    def __init__(self, activo: bool = True, parent=None):
        super().__init__(parent)
        self.activo = activo
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self.disparar.emit)

    def evento(self, nombre: str) -> None:
        if nombre == "reliquia_recompensas" and self.activo:
            self._temporizador.start(self.ESPERA_MS)
        elif nombre in ("reliquia_cerrada", "reliquia_elegida"):
            self._temporizador.stop()
