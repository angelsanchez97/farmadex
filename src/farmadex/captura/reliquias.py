"""Lectura de la pantalla de recompensas de reliquia y etiquetas encima de ella.

Cuando el juego abre esa pantalla (lo dice EE.log) o cuando se pulsa el atajo,
se captura la ventana, se leen los 1-4 nombres y se pinta encima de cada uno
lo que interesa: platino, si esta en boveda y si te sirve para un objetivo.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, is_dataclass, replace

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..idiomas import t
from ..registro_log import obtener
from . import pantalla
from . import recompensas_rapidas as rapidas
from .ocr import (
    Casador, ErrorMotorOCR, Leido, MotorOCR, Reconocido, _caja_union, agrupar_bloques, casar_lineas,
    leer_lineas, reconocer, resumen_tiempos,
)

log = obtener("reliquias")

# La franja de la pantalla donde el juego pinta las recompensas (proporciones).
# Las tarjetas estan centradas en vertical y repartidas en horizontal.
FRANJA = (0.10, 0.30, 0.90, 0.72)

AVISO_MOTOR = "No se pudo cargar el lector de pantalla (mira el registro)"
AVISO_DATOS = "Los datos del juego todavía no están preparados"

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
    # Tambien `completar`, solo si hay base de datos del usuario y el dato se sabe
    # (para los preajustes de `prioridad`; sin dato se quedan asi y no cuentan):
    tienes: int | None = None  # cuantas hay en el inventario leido; None = no se leyo
    set_tengo: int = 0  # otras piezas del mismo objeto que ya tienes
    set_total: int = 0  # piezas que lleva ese objeto
    maestria_estado: str | None = None  # del objeto al que pertenece, si hay perfil
    # Lo rellena `comparador.puntuar`:
    rareza: str | None = None  # "comun", "poco comun", "rara" o None si no se sabe
    valor: float | None = None  # platino equivalente; None = no se pudo valorar
    mejor: bool = False  # la que conviene elegir
    nota: str = ""  # por que falta algo ("Sin precio: ...")


def copiar(recompensas: list) -> list:
    """Copias de las recompensas, para que quien las pinte pueda cambiar sus cajas.

    La misma lista va al lector (que la guarda para completar la siguiente mirada),
    a la ventana y al comparador. La ventana pasa las cajas a pixeles logicos y a
    coordenadas del monitor del juego: si lo hacia sobre los mismos objetos, con
    Windows al 125 % o el juego en el segundo monitor la siguiente mirada ya no
    reconocia sus tarjetas y salian siete en vez de cuatro.
    """
    import copy

    return [replace(r) if is_dataclass(r) else copy.copy(r) for r in recompensas]


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
    def arrancar(self) -> None:
        """Lo que se conecta a `QThread.started`: llama a `iniciar` en el hilo del lector.

        No se conecta `iniciar` directamente porque las subclases lo redefinen, y con un
        slot redefinido PySide6 (6.11) no lo ejecuta en el hilo del objeto sino en el de
        la ventana: la carga del OCR y de los casadores (1-3 s) congelaba la ventana al
        arrancar. Este metodo no se redefine en ninguna subclase.
        """
        self.iniciar()

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
        """`reconocer` sin que nada se propague: None si el motor no esta disponible.

        Un lector puede fijar `self.lado_minimo` (ver `MotorOCR.leer`)."""
        lado_minimo = getattr(self, "lado_minimo", None)
        try:
            if lado_minimo:
                return reconocer(imagen, self.motor, self.casador, umbral=umbral, lado_minimo=lado_minimo)
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
    # Las tarjetas ya no estan en pantalla (la vigilancia no ve sus nombres): hay que
    # esconder el panel aunque EE.log aun no haya dicho que la pantalla se cerro.
    tarjetas_fuera = Signal()

    UMBRAL_CONOCIDAS = 70
    # Valores de partida tambien a nivel de clase: hay pruebas que construyen el
    # lector sin pasar por __init__.
    tarjetas = 0
    _miradas = 0
    _t_previas: float | None = None
    _casador_reliquias: Casador | None = None
    _casador_piezas: Casador | None = None
    _repetidas = 0
    _ultima_firma: tuple | None = None
    _t_vigilancia: float | None = None
    _fallos_vigilancia = 0

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(motor_ocr, CATEGORIAS_RECOMPENSA, parent)
        self.conocidas: list[str] = []  # unique_names que EE.log dio para esta reliquia
        self.jugadores: int | None = None  # tamano de la escuadra segun EE.log
        self._casador_conocidas: Casador | None = None
        self._casador_reliquias: Casador | None = None  # lo que puede salir de una reliquia
        self._casador_piezas: Casador | None = None  # el catalogo sin armas ni warframes enteros
        self._t_aviso: float | None = None  # cuando EE.log aviso de la pantalla
        self.tarjetas = 0  # lineas "Missing icon data!" de esta pantalla: una por recompensa
        self._miradas = 0  # lecturas de esta pantalla; las dos primeras solo miran la fila
        self._previas: list[Recompensa] = []  # lo mejor leido de cada tarjeta en esta pantalla
        self._confirmaciones = 0  # miradas de mas con todas las tarjetas ya leidas

    @Slot()
    def iniciar(self) -> None:
        super().iniciar()
        if self.casador is not None and self._casador_reliquias is None:
            from ..datos import indice

            con = indice.conectar()
            try:
                ids = rapidas.ids_reliquias(con)
                self._casador_piezas = rapidas.catalogo_de_piezas(self.casador, con)
            finally:
                con.close()
            self._casador_reliquias = self.casador.restringido(ids) if ids else None
        if not self.motor.fallo:
            rapidas.precalentar(self.motor)

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
        elif tipo == "tarjeta":
            self.tarjetas = min(4, self.tarjetas + 1)

    @Slot(str)
    def evento(self, nombre: str) -> None:
        if nombre in ("reliquia_abierta", "reliquia_cerrada", "reliquia_recompensas"):
            self._repetidas = 0
            self._ultima_firma = None
        if nombre in ("reliquia_abierta", "reliquia_cerrada"):
            self._previas = []
            self._confirmaciones = 0
            self._t_vigilancia = None
        if nombre == "reliquia_abierta":
            self.conocidas = []
            self._casador_conocidas = None
            self._t_aviso = time.monotonic()
            self.tarjetas = 0
            self._miradas = 0
        elif nombre == "reliquia_recompensas":
            self._t_aviso = time.monotonic()
            self._miradas = 0
        elif nombre == "reliquia_cerrada":
            self.conocidas = []
            self._casador_conocidas = None
            self._t_aviso = None
            self.tarjetas = 0

    def _esperadas(self) -> int | None:
        """Cuantas tarjetas hay segun EE.log (marcas de tarjeta o escuadra), o None."""
        return max(self.tarjetas, self.jugadores or 0) or None

    def _escalonado(self) -> rapidas.CasadorEscalonado:
        return rapidas.CasadorEscalonado(
            self._casador_piezas or self.casador, self._casador_reliquias, self._conocidas()
        )

    def _conocidas(self) -> Casador | None:
        """Casador restringido a lo que EE.log dio; None si no dio nada o no esta en el indice."""
        if not self.conocidas or self.casador is None:
            return None
        if self._casador_conocidas is None:
            from ..datos import indice

            con = indice.conectar()
            try:
                ids = rapidas.ids_conocidas(con, self.conocidas)
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

    CONFIRMACIONES = 2
    CONFIRMACION_MS = 400

    def _toca_confirmar(self) -> bool:
        if self._t_aviso is None or self._confirmaciones >= self.CONFIRMACIONES:
            return False
        return time.monotonic() - self._t_aviso <= self.PLAZO_REINTENTO_S

    def _confirmar(self) -> None:
        if self._t_aviso is not None:  # si la pantalla ya se cerro, no hay nada que mirar
            self.leer_ahora()

    # Con mas tarjetas esperadas que leidas (EE.log cuenta de mas, o una tarjeta que el
    # OCR no saca), repetir la misma lectura no arregla nada: se para a la tercera igual.
    REPETICIONES_MAX = 3

    def _toca_reintentar(self, halladas: int) -> bool:
        if self._t_aviso is None:
            return False
        if time.monotonic() - self._t_aviso > self.PLAZO_REINTENTO_S:
            return False
        if self._repetidas >= self.REPETICIONES_MAX:
            return False
        return halladas < (self._esperadas() or 1)

    def _reintentar(self) -> None:
        QTimer.singleShot(self.REINTENTO_MS, self._reintento)

    def _reintento(self) -> None:
        # Si EE.log ya cerro la pantalla mientras esperaba, no se lee: seria leer otra
        # cosa (una lectura por atajo no pasa por aqui, no programa reintentos).
        if self._t_aviso is not None:
            self.leer_ahora()

    def _anotar_firma(self, recompensas: list) -> None:
        firma = tuple(r.item_id for r in recompensas)
        self._repetidas = self._repetidas + 1 if firma == self._ultima_firma else 1
        self._ultima_firma = firma

    # -- vigilancia: esconder el panel si la pantalla se va sin que EE.log lo diga --

    VIGILANCIA_MS = 500
    VIGILANCIA_S = 12.0  # lo que dura el panel en pantalla (etiquetas.SEGUNDOS_VISIBLE)
    FALLOS_PARA_ESCONDER = 2  # dos miradas seguidas sin nombres: un destello no esconde nada

    def _empezar_vigilancia(self) -> None:
        arrancada = self._t_vigilancia is not None
        self._t_vigilancia = time.monotonic()
        self._fallos_vigilancia = 0
        if not arrancada:
            QTimer.singleShot(self.VIGILANCIA_MS, self._vigilar)

    def _vigilar(self) -> None:
        """Mirada barata a la fila de nombres (~30 ms) mientras el panel esta visible."""
        if self._t_vigilancia is None or not self._previas:
            self._t_vigilancia = None
            return
        if time.monotonic() - self._t_vigilancia > self.VIGILANCIA_S:
            self._t_vigilancia = None
            return
        if not self._ocupado:
            siguen = self._siguen_en_pantalla()
            if siguen is False:
                self._fallos_vigilancia += 1
                if self._fallos_vigilancia >= self.FALLOS_PARA_ESCONDER:
                    log.info("Los nombres de las tarjetas ya no estan en pantalla: se esconde el panel")
                    self._t_vigilancia = None
                    self._previas = []
                    self.tarjetas_fuera.emit()
                    return
            elif siguen:
                self._fallos_vigilancia = 0
        QTimer.singleShot(self.VIGILANCIA_MS, self._vigilar)

    def _siguen_en_pantalla(self) -> bool | None:
        """True si la fila aun trae alguna de las recompensas pintadas; None si no se pudo mirar."""
        if self.motor is None or getattr(self.motor, "fallo", None) or self.casador is None:
            return None
        self._ocupado = True
        try:
            ventana = pantalla.region_objetivo()
            imagen = pantalla.capturar(rapidas.region_fila(ventana))
            if imagen is None:
                return None
            lineas = rapidas.leer_fila(imagen, self.motor)
            if not lineas:
                return False
            ids = {r.item_id for r in self._previas if r.item_id != SIN_IDENTIFICAR}
            if not ids:
                return True  # nada que comparar: con texto en la fila se da por visto
            vistas = rapidas.casar_fila(rapidas.unir_filas(lineas), self._escalonado(), 4)
            return any(r.item_id in ids for r in vistas)
        except Exception:  # noqa: BLE001 - la vigilancia nunca tumba nada
            log.debug("Fallo en la vigilancia de la fila de nombres", exc_info=True)
            return None
        finally:
            self._ocupado = False

    def _leer(self) -> None:
        if not self._preparado():
            self.leidas.emit([])
            return
        self.estado.emit(t("Leyendo la pantalla..."))
        tiempos: dict = {}
        ventana = pantalla.region_objetivo()
        self._miradas += 1
        # Tras el aviso de EE.log, las dos primeras miradas solo leen la fila de
        # nombres (~30 ms): si la pantalla aun no esta pintada, gastar la franja
        # entera solo retrasaria la siguiente mirada. A partir de la tercera, y
        # siempre que se lee por atajo, la franja entera entra como respaldo.
        lento = None if (self._miradas <= 2 and self._toca_reintentar(0)) else self._leer_franja
        lectura = rapidas.leer_pantalla(
            pantalla.capturar, ventana, self.motor, self._escalonado(), self._esperadas(), lento, tiempos,
        )
        if lectura is None:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.leidas.emit([])
            return
        fila = lectura.recompensas
        self._anotar_tiempos(tiempos, ventana, lectura.via, len(fila))
        if not fila and self._toca_reintentar(0):
            # Pronto para la pantalla: se vuelve a mirar en 150 ms sin borrar lo pintado.
            self._reintentar()
            return
        recompensas = [
            Recompensa(
                item_id=r.item_id,
                nombre=r.nombre if r.item_id != SIN_IDENTIFICAR else t("Sin identificar"),
                texto_ocr=r.texto_ocr,
                caja=r.caja,
            )
            for r in fila
        ]
        recompensas = conservar_mejores(self._previas_de_esta_pantalla(recompensas), recompensas, ventana)
        self._previas = recompensas
        self._t_previas = time.monotonic()
        log.info(
            "Recompensas leidas: %s",
            ", ".join(f"{r.texto_ocr} -> {r.nombre}" for r in recompensas) or "ninguna",
        )
        self.estado.emit(
            t("{n} recompensas reconocidas", n=len(recompensas)) if recompensas else
            t("No se reconoció ninguna recompensa")
        )
        self.leidas.emit(copiar(recompensas))  # _previas no se comparte con nadie
        self._anotar_firma(recompensas)
        if recompensas:
            self._empezar_vigilancia()
        if self._toca_reintentar(len(recompensas)):
            # Se pinta ya lo que hay y se completa con la siguiente mirada.
            self._reintentar()
        elif self._toca_confirmar():
            # Ya estan todas, pero el juego pinta los nombres con un fundido: a los
            # 0,6 s "Plano De Chasis De" aun salia a medias y la tarjeta quedaba como
            # el plano. Una mirada mas tarde, con el texto entero, lo corrige
            # (conservar_mejores se queda con la lectura mas completa).
            self._confirmaciones += 1
            QTimer.singleShot(self.CONFIRMACION_MS, self._confirmar)


    # Lo leido antes solo completa una lectura de la MISMA pantalla. Por atajo, sin EE.log
    # (o con su "cerrada" llegando tarde), las tarjetas de la reliquia anterior se
    # colaban en la siguiente: la autoprueba pinto 7 recompensas en una pantalla de 4.
    VIDA_PREVIAS_S = 8.0

    def _previas_de_esta_pantalla(self, nuevas: list) -> list:
        if not self._previas or self._t_previas is None:
            return []
        if time.monotonic() - self._t_previas > self.VIDA_PREVIAS_S:
            return []
        ids_nuevas = {r.item_id for r in nuevas if r.item_id and r.item_id != SIN_IDENTIFICAR}
        ids_viejas = {r.item_id for r in self._previas if r.item_id and r.item_id != SIN_IDENTIFICAR}
        if ids_nuevas and not ids_nuevas & ids_viejas:
            log.info("Recompensas de otra pantalla: no se mezclan con las anteriores")
            return []
        return self._previas

    def _ids_conocidas(self) -> set[int]:
        casador = self._conocidas()
        return {v[0] for v in casador.candidatos.values()} if casador else set()

    def _leer_franja(self, ventana, tiempos: dict) -> list[Reconocido] | None:
        """El camino de siempre: la franja entera y, si esta vacia, la ventana entera.

        Devuelve las tarjetas de la fila elegida con las cajas en coordenadas de
        pantalla; None si el motor no esta disponible o no se pudo capturar.
        """
        region = ventana.recortar(*FRANJA)
        t0 = time.perf_counter()
        imagen = pantalla.capturar(region)
        tiempos["captura"] = tiempos.get("captura", 0.0) + time.perf_counter() - t0
        if imagen is None:
            return None
        encontrados = self._leer_y_casar(imagen, tiempos)
        if encontrados is None:
            return None
        if not encontrados and not self._toca_reintentar(0):
            # Si un parche mueve las tarjetas fuera de la franja habitual, se lee
            # la ventana entera antes de dar la pantalla por vacia (nunca mientras
            # aun toque reintentar: es la lectura mas cara y la pantalla puede
            # simplemente no estar pintada todavia).
            log.info("Nada en la franja de recompensas; se prueba con la ventana entera")
            imagen = pantalla.capturar(ventana)
            if imagen is None:
                return []
            region = ventana
            encontrados = self._leer_y_casar(imagen, tiempos)
            if encontrados is None:
                return None
            if encontrados:
                log.warning(
                    "Las recompensas estaban fuera de la franja esperada: "
                    "puede que el juego haya cambiado la pantalla"
                )
        tiempos["franja"] = f"{imagen.shape[1]}x{imagen.shape[0]}"
        # Primero la fila (si no, la copia de otro overlay con mas puntuacion
        # desplazaria a la tarjeta real), y dentro de la fila una por objeto.
        fila = elegir_fila(
            encontrados, tiempos.pop("_lineas", []),
            conocidas=self._ids_conocidas(), maximo=self._esperadas() or 4,
        )
        return [rapidas.desplazar(r, region.x, region.y) for r in fila]

    def _leer_y_casar(self, imagen, tiempos: dict) -> list[Reconocido] | None:
        """`leer_franja` sin que nada se propague: None si el motor no esta disponible."""
        try:
            return leer_franja(imagen, self.motor, self.casador, self._conocidas(), self.UMBRAL_CONOCIDAS, tiempos)
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            return None
        except Exception:  # noqa: BLE001 - un fallo de lectura no puede tumbar la app
            log.exception("Fallo leyendo la pantalla")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            return None

    def _anotar_tiempos(self, tiempos: dict, ventana, via: str, encontradas: int) -> None:
        """Una linea de INFO por lectura, para diagnosticar a distancia sin datos personales."""
        desde_aviso = (
            f"{(time.monotonic() - self._t_aviso) * 1000:.0f} ms desde el aviso de EE.log"
            if self._t_aviso is not None else "por atajo"
        )
        log.info(
            "Reliquia (%s): captura %.0f ms, ocr %.0f ms, casado %.0f ms; %d lineas, %d recompensas "
            "(%d por EE.log de %d conocidas, %s esperadas); fila %s, franja %s, ventana %dx%d; "
            "motor %s x%d hilos; %s; ultimo OCR: %s",
            via, tiempos.get("captura", 0) * 1000, tiempos.get("ocr", 0) * 1000, tiempos.get("casado", 0) * 1000,
            tiempos.get("lineas", 0), encontradas, tiempos.get("conocidas", 0), len(self.conocidas),
            self._esperadas() or "?", tiempos.get("fila", "-"), tiempos.get("franja", "-"),
            ventana.ancho, ventana.alto, self.motor.motor, self.motor.hilos, desde_aviso,
            resumen_tiempos(getattr(self.motor, "tiempos", None)),
        )


def leer_franja(imagen, motor: MotorOCR, casador: Casador, conocidas: Casador | None,
                umbral_conocidas: int, tiempos: dict) -> list[Reconocido]:
    """OCR de la franja una vez; casado primero contra lo que EE.log dio y luego contra todo.

    Una franja mas alta que la de 1080p se reduce antes del OCR: el tiempo del
    motor crece con los pixeles y a 1440p, con el juego peleando por la CPU, era
    lo que dejaba las etiquetas para los ultimos segundos. Deja las lineas leidas
    en `tiempos["_lineas"]` para `elegir_fila`.
    """
    t0 = time.perf_counter()
    escala = 1.0
    if imagen.shape[0] > ALTO_FRANJA_OCR * 1.15:
        import cv2

        escala = ALTO_FRANJA_OCR / imagen.shape[0]
        imagen = cv2.resize(
            imagen, (int(imagen.shape[1] * escala), ALTO_FRANJA_OCR), interpolation=cv2.INTER_AREA
        )
    lineas = leer_lineas(imagen, motor)
    if escala != 1.0:
        for l in lineas:
            l.x, l.y = int(l.x / escala), int(l.y / escala)
            l.ancho, l.alto = int(l.ancho / escala), int(l.alto / escala)
    for l in lineas:
        # "2 X Forma (Schéma)": la cantidad de la Forma doble no es parte del nombre.
        l.texto = RE_CANTIDAD_DELANTE.sub("", l.texto) or l.texto
    tiempos["_lineas"] = lineas
    tiempos["escala"] = escala
    tiempos["ocr"] = tiempos.get("ocr", 0.0) + time.perf_counter() - t0
    t0 = time.perf_counter()
    seguros = casar_lineas(lineas, conocidas, umbral_conocidas) if conocidas else []
    resto = casar_lineas(lineas, casador, 80)
    encontrados = _combinar(seguros, resto)
    tiempos["casado"] = tiempos.get("casado", 0.0) + time.perf_counter() - t0
    tiempos["lineas"] = len(lineas)
    tiempos["conocidas"] = len(seguros)
    return encontrados


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
RE_CANTIDAD_DELANTE = rapidas.RE_CANTIDAD_DELANTE


def _letras(texto: str) -> int:
    return sum(c.isalnum() for c in texto or "")


def _ranura(caja, ventana) -> int | None:
    """Posicion de la tarjeta en medios anchos de tarjeta desde el centro de la ventana.

    No depende de cuantas tarjetas haya (con 3 caen en impares, con 4 en pares), y
    dos miradas de la misma pantalla dan la misma aunque las cajas varien unos pixeles.
    """
    if ventana is None or not caja:
        return None
    ancho = rapidas.ANCHO_TARJETA * rapidas.alto_interfaz(ventana)
    if ancho <= 0:
        return None
    centro = caja[0] + caja[2] / 2
    return round(2 * (centro - (ventana.x + ventana.ancho / 2)) / ancho)


def conservar_mejores(previas: list, nuevas: list, ventana=None) -> list:
    """Cada tarjeta se queda con su mejor lectura de esta pantalla.

    Se lee varias veces mientras la pantalla se pinta, para completar las tarjetas
    que faltan. Visto en un registro real: la primera mirada leyo "Plano chasisDe
    CitrinePrime" (el chasis) y la segunda, de la misma tarjeta, solo "Citrine
    Prime", y esa lectura peor sustituyo a la buena. Ahora, para la misma tarjeta
    (misma posicion), una lectura nueva solo gana si identifica algo que la vieja
    no, o si lee al menos tanto texto como ella.

    La misma tarjeta se reconoce por su posicion, por su ranura en la ventana
    (`ventana`, si se da) o, si no, por ser el mismo objeto: nunca salen mas de
    cuatro tarjetas.
    """
    if not previas:
        return nuevas
    salida = []
    usadas = set()

    def libre(v):
        return id(v) not in usadas

    for nueva in nuevas:
        centro = nueva.caja[0] + nueva.caja[2] / 2
        ranura = _ranura(nueva.caja, ventana)
        # Primero el mismo objeto (el mas cercano, por si hay dos iguales); si no, la
        # misma posicion; si no, la misma ranura.
        vieja = None
        if nueva.item_id != SIN_IDENTIFICAR:
            iguales = [v for v in previas if libre(v) and v.item_id == nueva.item_id]
            vieja = min(iguales, key=lambda v: abs(v.caja[0] + v.caja[2] / 2 - centro), default=None)
        if vieja is None:
            vieja = next(
                (v for v in previas if libre(v)
                 and abs(v.caja[0] + v.caja[2] / 2 - centro) < max(v.caja[2], nueva.caja[2]) / 2),
                None,
            )
        if vieja is None and ranura is not None:
            vieja = next((v for v in previas if libre(v) and _ranura(v.caja, ventana) == ranura), None)
        if vieja is not None:
            usadas.add(id(vieja))
        if vieja is None or vieja.item_id == SIN_IDENTIFICAR or vieja.item_id == nueva.item_id:
            salida.append(nueva)
        elif nueva.item_id == SIN_IDENTIFICAR or _letras(nueva.texto_ocr) < _letras(vieja.texto_ocr):
            vieja.caja = nueva.caja  # la posicion buena es la ultima (la tarjeta pudo moverse)
            salida.append(vieja)
        else:
            salida.append(nueva)
    # Una tarjeta que ya se habia leido y esta mirada no ve (un destello, el cursor
    # encima) no desaparece, salvo que su hueco ya este ocupado.
    for v in previas:
        if not libre(v) or v.item_id == SIN_IDENTIFICAR or len(salida) >= 4:
            continue
        ranura = _ranura(v.caja, ventana)
        if ranura is not None and any(_ranura(s.caja, ventana) == ranura for s in salida):
            continue
        salida.append(v)
    return sorted(salida, key=lambda r: r.caja[0])


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


def _pisa(a, b) -> bool:
    x, y, w, h = a
    sx, sy, sw, sh = b
    return min(x + w, sx + sw) > max(x, sx) and min(y + h, sy + sh) > max(y, sy)


def _combinar(seguros: list[Reconocido], resto: list[Reconocido]) -> list[Reconocido]:
    """Junta lo casado contra EE.log (`seguros`) y contra el catalogo (`resto`).

    Donde los dos casan la misma linea gana el de mas puntuacion. Una conocida
    solo gana a un casado de catalogo mejor si es casi exacta: EE.log trae lo de
    toda la escuadra y la tarjeta propia puede ser otra pieza del mismo objeto
    ("Receptor De Akbolto Prime" casaba con 79 el cañon de otro jugador y tapaba
    el receptor, que el catalogo daba con 100).
    """
    from .recompensas_rapidas import SEGURA_CONOCIDA

    vencidos = set()
    for i, s in enumerate(seguros):
        rivales = [r for r in resto if _pisa(r.caja, s.caja)]
        if rivales and s.puntuacion < SEGURA_CONOCIDA and max(r.puntuacion for r in rivales) > s.puntuacion:
            vencidos.add(i)
    buenos = [s for i, s in enumerate(seguros) if i not in vencidos]
    return buenos + _sin_solapar(resto, buenos)


def _sin_solapar(nuevos: list[Reconocido], seguros: list[Reconocido]) -> list[Reconocido]:
    """Descarta lo casado contra el catalogo entero que pisa una linea ya casada por EE.log
    (las que `_combinar` ha dado por buenas: ya ganaron a lo que pisan)."""
    return [r for r in nuevos if not any(_pisa(r.caja, s.caja) for s in seguros)]


def texto_platino(r: Recompensa) -> str:
    """'3 platino (venta mas barata)' o '3 platino (mediana)': que precio es, no solo cuanto."""
    if r.criterio_platino == "minimo":
        return t("{n} platino (venta más barata)", n=r.platino)
    if r.criterio_platino == "mediana":
        return t("{n} platino (mediana)", n=r.platino)
    return t("{n} platino", n=r.platino)


def _quitar_repetidos(encontrados: list[Reconocido]) -> list[Reconocido]:
    """El OCR parte los nombres en varias lineas: se queda la mejor por objeto y tarjeta.

    Solo se juntan las lecturas del mismo objeto que caen en la misma columna: dos
    jugadores pueden llevarse la misma pieza (captura real en frances con tres "Rhino
    Prime - Systèmes (Schéma)" de cuatro), y quedarse con una sola dejaba las otras como
    tarjetas sin identificar.
    """
    salida: list[Reconocido] = []
    for r in sorted(encontrados, key=lambda r: -r.puntuacion):
        x, _, ancho, _ = r.caja
        if any(o.item_id == r.item_id and min(x + ancho, o.caja[0] + o.caja[2]) > max(x, o.caja[0]) for o in salida):
            continue
        salida.append(r)
    return sorted(salida, key=lambda r: r.caja[0])


def completar(
    recompensas: list[Recompensa], indice_con: sqlite3.Connection, usuario_con=None
) -> list[Recompensa]:
    """Anade ducados, estado de boveda, si cubre algun objetivo pendiente y, con base
    del usuario, lo que hace falta para priorizar: inventario, set y maestria."""
    hay_perfil = _hay_perfil(usuario_con) if usuario_con is not None else False
    for r in recompensas:
        fila = indice_con.execute(
            "SELECT ducados, vaulted, unique_name, market_slug, comerciable, padre_id FROM items WHERE id = ?",
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
            try:
                _datos_para_priorizar(r, fila[5], indice_con, usuario_con, hay_perfil)
            except sqlite3.Error:  # un dato de mas nunca deja sin etiquetas
                log.debug("Sin datos de prioridad para %s", r.unique_name, exc_info=True)
    return recompensas


def _hay_perfil(usuario_con) -> bool:
    try:
        return usuario_con.execute("SELECT 1 FROM perfil_meta WHERE clave = 'nombre'").fetchone() is not None
    except sqlite3.Error:  # tabla sin crear: nunca se importo un perfil
        return False


def _cantidad_leida(usuario_con, unique_name: str) -> int | None:
    """Del inventario leido en pantalla. Solo lectura: aqui no se crea ninguna tabla,
    porque esto tambien corre en el hilo del comparador con su propia conexion."""
    if not unique_name:
        return None
    try:
        fila = usuario_con.execute(
            "SELECT cantidad FROM inventario_lecturas WHERE item_type = ?", (unique_name,)
        ).fetchone()
    except sqlite3.Error:
        return None
    return fila[0] if fila else None


def _datos_para_priorizar(r: Recompensa, padre_id, indice_con, usuario_con, hay_perfil: bool) -> None:
    """Rellena `tienes`, `set_tengo`/`set_total` y `maestria_estado` con lo que se sepa."""
    r.tienes = _cantidad_leida(usuario_con, r.unique_name)
    if r.tienes is None:
        # Sin inventario leido, un objetivo ya completado de esta pieza tambien dice que la tienes.
        hecho = usuario_con.execute(
            "SELECT cantidad_actual FROM objetivos WHERE item_unique_name = ? AND completado_en IS NOT NULL",
            (r.unique_name,),
        ).fetchone()
        if hecho:
            r.tienes = hecho[0]
    if padre_id:
        piezas = indice_con.execute(
            "SELECT id, unique_name, item_count FROM items WHERE padre_id = ?", (padre_id,)
        ).fetchall()
        tengo = 0
        for pieza_id, unico, necesarias in piezas:
            if pieza_id == r.item_id:
                continue
            # La tienes si el inventario lo dice o si su objetivo ya se completo
            # (marcarla en Primes y conseguirla la deja completada).
            cantidad = _cantidad_leida(usuario_con, unico)
            completada = usuario_con.execute(
                "SELECT 1 FROM objetivos WHERE item_unique_name = ? AND completado_en IS NOT NULL",
                (unico,),
            ).fetchone()
            if (cantidad is not None and cantidad >= (necesarias or 1)) or completada:
                tengo += 1
        r.set_tengo, r.set_total = tengo, len(piezas)
    if hay_perfil:
        from .. import perfil as datos_perfil

        # Una pieza no da maestria; lo que importa es el objeto al que pertenece.
        estado = datos_perfil.estado_de(usuario_con, indice_con, r.item_id)
        if estado.estado == datos_perfil.NO_APLICA and padre_id:
            estado = datos_perfil.estado_de(usuario_con, indice_con, padre_id)
        if estado.estado != datos_perfil.NO_APLICA:
            r.maestria_estado = estado.estado


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
            detalles.append(t("En bóveda"))
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
    # atras en 15) los nombres ya se leen, y EE.log escribe "Got rewards" ~0,4-0,6 s
    # despues de "Relic rewards initialized". La espera fija de 1,5 s era margen sin
    # medir y era el trozo mas grande del retraso. Si la primera lectura llega antes
    # de tiempo, el lector reintenta solo (LectorRecompensas.REINTENTO_MS), y como
    # las dos primeras miradas solo leen la fila de nombres (~40 ms), mirar pronto
    # sale casi gratis.
    ESPERA_MS = 80
    # Se dispara con el PRIMER marcador de la pantalla y no solo con "Got rewards":
    # el juego vuelca EE.log a rafagas, y en un registro real "Relic rewards
    # initialized" llego al instante mientras "Got rewards" tardo 4,8 s en aparecer
    # (los nombres se pintaron 5,5 s despues de la pantalla). Con el primero, el
    # lector ya esta mirando la fila cada 150 ms cuando el juego pinta las tarjetas;
    # el segundo, si llega tarde, solo vale como confirmacion.
    EVENTOS_DISPARO = ("reliquia_abierta", "reliquia_recompensas")

    def __init__(self, activo: bool = True, parent=None):
        super().__init__(parent)
        self.activo = activo
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self.disparar.emit)

    def evento(self, nombre: str) -> None:
        if nombre in self.EVENTOS_DISPARO and self.activo:
            self._temporizador.start(self.ESPERA_MS)
        elif nombre in ("reliquia_cerrada", "reliquia_elegida"):
            self._temporizador.stop()
