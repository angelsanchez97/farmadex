"""OCR de la pantalla y casado de lo leido con el catalogo.

Motor por defecto: RapidOCR (ONNX Runtime, CPU). Va empaquetado con sus modelos,
asi que no descarga nada en tiempo de ejecucion. En modo automatico usa menos
hilos cuando la CPU va cargada (el juego apretando). Motor alternativo: el OCR de
Windows (`winocr`), seleccionable en Ajustes; si no esta, se usa el local.

Solo se procesan pixeles ya capturados: este modulo no toca el juego.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass

from ..datos.difuso import fuzz, rf_process
from ..datos.difuso import Levenshtein

from ..datos.items import normalizar
from ..registro_log import obtener
from . import carga

log = obtener("ocr")

# Lo que puede salir en una pantalla de recompensas o en el inventario.
# Con fr/de/pt/it hacen falta tambien sus articulos y preposiciones: "Plan du Chassis
# de Caliban Prime", "Bauplan fur...", "Projeto do Chassi...".
PALABRAS_VACIAS = {
    "de", "del", "la", "el", "los", "las", "of", "the",
    "du", "des", "le", "les", "l",  # fr
    "der", "die", "das", "dem", "den", "von", "fur",  # de (normalizar() quita la dieresis)
    "do", "da", "dos", "das", "o", "a",  # pt
    "di", "il", "lo", "gli",  # it
}

# Palabras que aparecen en cientos de nombres y que, solas o juntas, no
# identifican nada: "BLUEPRINT" suelto no puede casarse con "Bo Blueprint".
GENERICAS = {
    "prime", "plano", "blueprint", "sistemas", "systems", "chasis", "chassis",
    "neuroptica", "neuroptics", "canon", "barrel", "receptor", "receiver", "culata",
    "stock", "mango", "handle", "hoja", "blade", "guarda", "guard", "empunadura",
    "grip", "cadena", "chain", "enlace", "link", "cabeza", "head", "disco", "disc",
    "estrella", "star", "ala", "wing", "arnes", "harness", "cuerda", "string",
    "nucleo", "core", "mod", "set", "mk", "i", "ii", "iii", "iv", "v", "x",
    "carcasa", "carapace", "cerebro", "cerebrum", "kit", "vidar", "zetki", "lavan",
}

# Lo unico que distingue "Photor Vidar MK I" de "MK IV": una lectura dudosa no basta.
NUMERALES = {"i", "ii", "iii", "iv", "v", "vi", "x", "mk", "1", "2", "3", "4", "5"}

# Marcas de icono que traen algunos nombres del catalogo: "<SHARD_RED_SIMPLE> ...".
RE_ETIQUETAS = re.compile(r"<[^>]*>")

# El catalogo (WFCD) traduce "Handle" como "Mango" y el juego escribe "Empunadura"
# en algunas armas (visto en pantalla: "Empunadura De Quassus Prime"). Se registran
# las dos formas para que la pieza case exacta y no se vaya a otra arma.
SINONIMOS = {"mango": "empunadura", "empunadura": "mango"}

# Hilos de calculo para ONNX Runtime: el usuario juega mientras esto corre.
# Medido (Ryzen 9800X3D, franja de recompensas): 4 hilos 395 ms, 2 hilos 412 ms.
# Con pocos nucleos, 4 hilos le quitan al juego mas de lo que ganan.


def _hilos_por_defecto() -> int:
    import os

    nucleos = os.cpu_count() or 4
    return 4 if nucleos >= 8 else 2


HILOS_OCR = _hilos_por_defecto()


def _hilos_ligero() -> int:
    return 2


def _hilos_fondo() -> int:
    import os

    return 1 if (os.cpu_count() or 4) < 8 else 2


# Motor ligero: el que usa el modo automatico con la CPU cargada (el juego apretando)
# y el modo "ligero" siempre. Medido en un 9800X3D (8 nucleos/16 hilos) con la CPU
# saturada por otros procesos: con 2 hilos la fila de nombres tarda 118 ms y con 4
# 161 ms (con 16, 302): cuando no sobra CPU, mas hilos solo se estorban entre si y
# con el juego. Con la CPU libre, 4 hilos son lo mas rapido (41 ms frente a 51).
# Antes, con menos de 8 nucleos, el ligero iba con 1 hilo; desde que los hilos no se
# quedan dando vueltas ("spinning", ver `_crear_rapidocr`) 2 hilos ya no se estorban:
# medido simulando un PC de 4 nucleos con 3 ocupados al 100 %, la pantalla de mejoras
# se lee un ~25 % antes con 2 que con 1 (y exactamente igual). Es una rafaga corta que
# el usuario pide con su atajo.
HILOS_LIGERO = _hilos_ligero()
# La lectura pasiva (perfil, inventario) va sola y de fondo: ahi no hay prisa y con pocos
# nucleos se queda en 1 hilo para no quitarle nada al juego.
HILOS_FONDO = _hilos_fondo()

# Modos de Ajustes > Datos del juego > Avanzado > "Lectura de pantalla (OCR)".
MODOS_OCR = ("auto", "rapido", "ligero", "windows")
_ALIAS_MOTOR = {"rapido": "rapidocr", "windows": "winocr"}
CLAVE_NORMAL = "rapidocr"
CLAVE_LIGERO = "rapidocr_ligero"
# Motor aparte para la lectura pasiva (perfil, inventario): su OCR de pantalla entera
# (~0,5-1 s) en la misma sesion que las lecturas pedidas las hacia esperar (medido con la
# autoprueba: recompensas de 150 ms a 300-700 ms). Con su propia sesion y pocos hilos,
# como mucho se reparten la CPU.
CLAVE_FONDO = "rapidocr_fondo"

# Modo automatico: fraccion de CPU (0-1) ocupada por OTROS programas a partir de la
# cual se pasa al motor ligero, y por debajo de la cual se vuelve al normal. Medido
# en el PC de referencia: hasta ~0.40 los 4 hilos siguen siendo lo mas rapido; por
# encima, 2 hilos leen igual o mejor y ademas le dejan la CPU al juego.
CARGA_ALTA = 0.40
CARGA_BAJA = 0.30


_winocr_instalado: bool | None = None


def winocr_disponible() -> bool:
    """Si el paquete del OCR de Windows (`winocr`) esta instalado. Se mira una vez y sin
    importarlo (importarlo carga las librerias de Windows Runtime)."""
    global _winocr_instalado
    if _winocr_instalado is None:
        import importlib.util

        try:
            _winocr_instalado = importlib.util.find_spec("winocr") is not None
        except (ImportError, ValueError):
            _winocr_instalado = False
    return _winocr_instalado


def modo_de_config(config) -> str:
    """El modo de OCR guardado en la configuracion ("auto" si falta o no se conoce).

    "windows" sin el OCR de Windows instalado cuenta como "auto": en Ajustes esa
    opcion ni sale, y asi quien la tenia guardada no se queda en un modo invisible."""
    modo = (config or {}).get("ocr_modo", "auto")
    if modo == "windows" and not winocr_disponible():
        return "auto"
    return modo if modo in MODOS_OCR else "auto"

CATEGORIAS_PLAUSIBLES = (
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
    "Arcanes",
    "Resources",
    "Misc",
    "Gear",
    "Relics",
    "Skins",
    "Railjack",
)


class ErrorMotorOCR(RuntimeError):
    """El motor OCR no se pudo cargar (falta un modulo, un modelo, un paquete de idioma)."""


@dataclass
class Leido:
    texto: str
    x: int
    y: int
    ancho: int
    alto: int
    confianza: float


@dataclass
class Reconocido:
    texto_ocr: str
    item_id: int | None
    nombre: str
    puntuacion: float
    caja: tuple[int, int, int, int]


def lote_reconocedor(hilos: int) -> int:
    """Cuantos recortes lee el reconocedor de una vez segun los hilos de su sesion.

    Cada lote se rellena hasta el recorte mas ancho, y ese relleno tambien se calcula.
    Con muchos hilos compensa (se reparten el lote); con uno o dos, no: medido con las
    capturas reales de la pantalla de mejoras, con 1 hilo leer de uno en uno es un ~12 %
    mas rapido que de 6 en 6, con 2 hilos de 2 en 2 algo mas rapido, y con 4 el lote de
    6 de siempre sigue siendo lo mejor.
    """
    if hilos <= 1:
        return 1
    if hilos <= 3:
        return 2
    return 6


def _crear_rapidocr(hilos: int):
    """RapidOCR con el numero de hilos acotado, sin el clasificador de giro y con la
    memoria de ONNX Runtime gestionada para que ninguna lectura pague "primeras veces".

    El paquete no deja pasar opciones de sesion, asi que se le cambian las fabricas
    de `SessionOptions` e `InferenceSession` solo mientras se construye. El texto del
    juego siempre esta derecho: el clasificador de 0/180 grados solo anadia tiempo.

    Memoria (medido en un 9800X3D, `herramientas/perfil_ocr.py`): RapidOCR apaga el
    "arena" de memoria y deja encendido el patron de memoria, que ONNX Runtime
    planifica la primera vez que ve cada forma de entrada. Esa primera vez costaba
    de 2 a 5 veces la inferencia, y casi todas las lecturas traen formas nuevas
    (cada pantalla tiene nombres de anchos distintos): la pantalla de mejoras
    reconocia en ~700 ms la primera vez y en ~150 ms la segunda. Con el arena
    encendido y el patron apagado no hay primeras veces; y encogiendo el arena al
    acabar cada inferencia (`_SesionQueSuelta`) la memoria vuelve al sistema en vez
    de quedarse ocupada (sin encoger, el detector se quedaba con ~1 GB).
    """
    import rapidocr_onnxruntime.utils as utiles
    from rapidocr_onnxruntime import RapidOCR

    opciones_originales = utiles.SessionOptions
    sesion_original = utiles.InferenceSession

    def con_hilos():
        opciones = opciones_originales()
        opciones.intra_op_num_threads = max(1, hilos)
        opciones.inter_op_num_threads = 1
        # Sin "spinning": por defecto los hilos de ONNX Runtime se quedan dando vueltas
        # esperando trabajo, y con el juego ocupando nucleos se pelean con el y entre
        # ellos. Medido con la CPU peleada (herramientas/perfil_ocr.py y 4 procesos
        # ocupando los mismos nucleos): detector a 1080p 789 -> 305 ms y un lote del
        # reconocedor 154 -> 44 ms con 4 hilos; con la CPU libre da igual.
        opciones.add_session_config_entry("session.intra_op.allow_spinning", "0")
        return opciones

    def sesion(ruta, sess_options=None, providers=None, **kw):
        if sess_options is not None:
            sess_options.enable_cpu_mem_arena = True
            sess_options.enable_mem_pattern = False
        return sesion_original(ruta, sess_options=sess_options, providers=providers, **kw)

    utiles.SessionOptions = con_hilos
    utiles.InferenceSession = sesion
    try:
        motor = RapidOCR(use_angle_cls=False)
    finally:
        utiles.SessionOptions = opciones_originales
        utiles.InferenceSession = sesion_original
    motor.text_recognizer.rec_batch_num = lote_reconocedor(hilos)
    motor.text_detector.infer = _SesionQueSuelta(motor.text_detector.infer)
    motor.text_recognizer.session = _SesionQueSuelta(motor.text_recognizer.session)
    _normalizado_rapido(motor.text_detector)
    motor.text_detector = _Cronometrado(motor.text_detector)
    motor.text_recognizer = _Cronometrado(motor.text_recognizer)
    return motor


# `leer` deja que RapidOCR amplie la imagen antes de buscar texto hasta que su lado
# corto mida 736 px: un recuadro de 620x170 bajo el cursor se buscaba a 2684x736.
# `leer(imagen, lado_minimo=...)` cambia ese lado solo para esa lectura (lo usa el
# lector bajo el cursor, ver cursor.LADO_MINIMO). Para el resto no se toca: medido,
# bajarlo en general perdia una tarjeta de la franja de recompensas y una
# estadistica de un agrietado sintetico.


def _normalizado_rapido(detector) -> None:
    """Cambia la normalizacion del detector de RapidOCR por una con tabla que da lo mismo.

    La original pasa la imagen a float y hace resta y division por canal sobre la
    imagen entera, y luego la traspone: ~40-75 ms a 1080p, casi la mitad de lo que
    tarda la propia red en mirar la captura. Como los pixeles son de 8 bits, la
    cuenta se hace una vez para los 256 valores posibles y se aplica con una tabla
    ya en el orden canal-alto-ancho que quiere la red: ~12 ms y exactamente los
    mismos numeros. Si el paquete cambia y no se reconocen las piezas, no se toca.
    """
    ops = getattr(detector, "preprocess_op", None)
    if not isinstance(ops, list):
        return
    nombres = [type(op).__name__ for op in ops]
    if "NormalizeImage" not in nombres or "ToCHWImage" not in nombres:
        return
    i_norm, i_chw = nombres.index("NormalizeImage"), nombres.index("ToCHWImage")
    if i_chw != i_norm + 1:
        return
    ops[i_norm] = _NormalizarCHW(ops[i_norm])
    ops[i_chw] = _SinTrasponer(ops[i_chw])


class _NormalizarCHW:
    """NormalizeImage + ToCHWImage de RapidOCR en una pasada con tabla (imagenes de 8 bits)."""

    def __init__(self, original):
        import numpy as np

        self._original = original
        valores = np.arange(256, dtype=np.float32).reshape(256, 1, 1)
        tabla = (valores * original.scale - original.mean.reshape(1, 1, -1)) / original.std.reshape(1, 1, -1)
        self._tablas = [np.ascontiguousarray(tabla[:, 0, c]) for c in range(tabla.shape[2])]

    def __call__(self, data):
        import cv2
        import numpy as np

        imagen = data["image"]
        if not (isinstance(imagen, np.ndarray) and imagen.dtype == np.uint8 and imagen.ndim == 3
                and imagen.shape[2] == len(self._tablas)):
            data = self._original(data)
            data["image"] = np.array(data["image"]).transpose((2, 0, 1))
            data["_chw"] = True
            return data
        salida = np.empty((imagen.shape[2],) + imagen.shape[:2], dtype=np.float32)
        for c, tabla in enumerate(self._tablas):
            salida[c] = cv2.LUT(np.ascontiguousarray(imagen[:, :, c]), tabla)
        data["image"] = salida
        data["_chw"] = True
        return data


class _SinTrasponer:
    """ToCHWImage que no hace nada si la imagen ya viene en canal-alto-ancho (_NormalizarCHW)."""

    def __init__(self, original):
        self._original = original

    def __call__(self, data):
        if data.pop("_chw", False):
            return data
        return self._original(data)


class _Cronometrado:
    """Envuelve el detector o el reconocedor de RapidOCR y suma lo que tarda (con su
    preparacion y su postproceso), para el registro de tiempos por etapa."""

    def __init__(self, original):
        self._original = original
        self.segundos = 0.0
        self.llamadas = 0

    def __getattr__(self, nombre):
        return getattr(self._original, nombre)

    def __call__(self, *args, **kwargs):
        inicio = time.perf_counter()
        try:
            return self._original(*args, **kwargs)
        finally:
            self.segundos += time.perf_counter() - inicio
            self.llamadas += 1


class _SesionQueSuelta:
    """Una sesion de RapidOCR (`OrtInferSession`) que al acabar cada inferencia
    devuelve al sistema la memoria del arena."""

    _opciones_run = None

    def __init__(self, original):
        self._original = original

    def __getattr__(self, nombre):
        return getattr(self._original, nombre)

    @classmethod
    def opciones_run(cls):
        if cls._opciones_run is None:
            import onnxruntime

            opciones = onnxruntime.RunOptions()
            opciones.add_run_config_entry("memory.enable_memory_arena_shrinkage", "cpu:0")
            cls._opciones_run = opciones
        return cls._opciones_run

    def __call__(self, entrada):
        sesion = self._original.session
        return sesion.run(None, {sesion.get_inputs()[0].name: entrada}, self.opciones_run())


class MotorOCR:
    """Envoltorio sobre RapidOCR con carga perezosa (tarda ~1 s la primera vez).

    Los modelos se comparten entre todas las instancias del mismo motor: el
    lector de recompensas y el del cursor cargan una sola copia.

    `motor` es el modo de Ajustes > Lectura de pantalla (ver `MODOS_OCR`) o uno de
    los nombres de siempre: "rapidocr" (hilos normales, igual que "rapido") y
    "winocr" (igual que "windows"). En "auto" hay dos motores cargados, el normal
    y el ligero, y cada lectura usa uno u otro segun lo cargada que vaya la CPU
    (`captura/carga.py`). Las sesiones de ONNX Runtime no dejan cambiar los hilos
    una vez creadas, y rehacerlas cuesta ~130 ms mas ~700 ms de primera inferencia
    (medido): por eso se tienen las dos a mano (unos 25 MB mas de memoria).
    """

    _compartidos: dict[str, object] = {}
    _fallidos: dict[str, str] = {}  # motor -> motivo; no se reintenta en bucle
    _precalentados: set[str] = set()  # motores que ya hicieron su primera inferencia
    _cerrojo = threading.Lock()
    _aligerado = False  # modo automatico: si ahora se lee con el motor ligero
    _winocr: bool | None = None  # si el paquete winocr esta instalado (se mira una vez)

    def __init__(self, motor: str = "rapidocr", hilos: int = HILOS_OCR):
        motor = _ALIAS_MOTOR.get(motor, motor)
        if motor not in (CLAVE_NORMAL, "ligero", "auto", "winocr", "fondo"):
            log.warning("Modo de OCR desconocido %r; se usa el normal", motor)
            motor = CLAVE_NORMAL
        self.motor = motor
        self.hilos = hilos
        self._forzada: str | None = None  # precalentado: que motor usar sin mirar la carga
        self.ultima_clave: str | None = None  # con que motor se hizo la ultima lectura
        self.tiempos: dict = {}  # lo que costo cada etapa de la ultima lectura (resumen_tiempos)

    # -- que motor toca -----------------------------------------------------------

    def _adaptativo(self) -> bool:
        """Automatico y con un motor ligero que de verdad use menos hilos que el normal."""
        return self.motor == "auto" and HILOS_LIGERO < self.hilos

    def _clave_fija(self) -> str:
        if self.motor == "fondo":
            return CLAVE_FONDO
        return CLAVE_LIGERO if self.motor == "ligero" else CLAVE_NORMAL

    def _decidir_auto(self) -> str:
        """Motor normal o ligero segun la media reciente de CPU ocupada por otros programas.

        Con histeresis (entra en ligero con `CARGA_ALTA`, vuelve por debajo de
        `CARGA_BAJA`) para no ir cambiando en cada lectura. Sin medida (fuera de
        Windows, o recien arrancado) se queda como estaba: al principio, normal.
        """
        if CLAVE_LIGERO in MotorOCR._fallidos:
            return CLAVE_NORMAL
        uso = carga.uso_ajeno()
        antes = MotorOCR._aligerado
        if uso is not None:
            aligerar = uso >= (CARGA_BAJA if antes else CARGA_ALTA)
            if aligerar != antes:
                MotorOCR._aligerado = aligerar
                log.info("OCR automatico: otros programas usan el %.0f %% de la CPU; se lee con %d hilos",
                         uso * 100, HILOS_LIGERO if aligerar else self.hilos)
        return CLAVE_LIGERO if MotorOCR._aligerado else CLAVE_NORMAL

    def _clave_para_leer(self) -> str:
        if self._forzada:
            return self._forzada
        return self._decidir_auto() if self._adaptativo() else self._clave_fija()

    # -- estado para la interfaz y el diagnostico -----------------------------------

    @property
    def fallo(self) -> str | None:
        """Motivo por el que este motor no se pudo cargar, o None si va bien.

        El OCR de Windows no cuenta: si falta o falla se cae al lector local.
        """
        if self.motor == "winocr":
            return None
        if self.motor == "fondo" and CLAVE_FONDO in MotorOCR._fallidos:
            return MotorOCR._fallidos.get(CLAVE_NORMAL)  # sin el de fondo se usa el normal
        return MotorOCR._fallidos.get(self._clave_fija())

    @property
    def cargado(self) -> bool:
        """True si el motor (propio o compartido) ya esta en memoria; para el diagnostico."""
        claves = ("winocr",) if self.motor == "winocr" else (CLAVE_NORMAL, CLAVE_LIGERO)
        return any(c in MotorOCR._compartidos for c in claves)

    # -- carga ----------------------------------------------------------------------

    def _motor_de(self, clave: str):
        """Carga (o recupera) uno de los motores compartidos. Lanza `ErrorMotorOCR`."""
        with MotorOCR._cerrojo:
            motivo = MotorOCR._fallidos.get(clave)
            if motivo:
                raise ErrorMotorOCR(motivo)
            compartido = MotorOCR._compartidos.get(clave)
            if compartido is not None:
                return compartido
            inicio = time.monotonic()
            try:
                if clave == "winocr":
                    nuevo = "winocr"
                else:
                    nuevo = _crear_rapidocr(HILOS_FONDO if clave == CLAVE_FONDO
                                            else HILOS_LIGERO if clave == CLAVE_LIGERO else self.hilos)
            except Exception as e:  # noqa: BLE001 - lo que sea, no puede tumbar la app
                motivo = f"{type(e).__name__}: {e}"
                MotorOCR._fallidos[clave] = motivo
                log.exception("No se pudo cargar el motor OCR '%s'", clave)
                raise ErrorMotorOCR(motivo) from e
            MotorOCR._compartidos[clave] = nuevo
            log.info("Motor OCR '%s' cargado en %.1f s", clave, time.monotonic() - inicio)
            return nuevo

    def _pasar_a_local(self, motivo: str) -> None:
        """El OCR de Windows no esta o no funciona: se lee con el local (automatico)."""
        log.warning("OCR de Windows no disponible (%s); se usa el lector local", motivo)
        self.motor = "auto"

    def _cargar(self):
        """El motor con el que hacer esta lectura. Lanza `ErrorMotorOCR` si no se puede."""
        if self.motor == "winocr":
            if MotorOCR._winocr is None:
                try:
                    import winocr  # noqa: F401 - solo para comprobar que esta

                    MotorOCR._winocr = True
                except ImportError:
                    MotorOCR._winocr = False
            if not MotorOCR._winocr:
                self._pasar_a_local("el paquete winocr no esta instalado")
            elif "winocr" in MotorOCR._fallidos:
                self._pasar_a_local(MotorOCR._fallidos["winocr"])
            else:
                self.ultima_clave = "winocr"
                return self._motor_de("winocr")
        clave = self._clave_para_leer()
        try:
            motor = self._motor_de(clave)
        except ErrorMotorOCR:
            if clave == CLAVE_FONDO:
                # El de fondo no carga: la lectura pasiva comparte el normal, como antes.
                motor = self._motor_de(CLAVE_NORMAL)
                self.ultima_clave = CLAVE_NORMAL
                return motor
            if clave != CLAVE_LIGERO or self.motor != "auto" or self._forzada:
                raise
            clave = CLAVE_NORMAL  # el ligero no carga: mejor el normal que nada
            motor = self._motor_de(clave)
        self.ultima_clave = clave
        return motor

    def precalentar(self) -> None:
        """Carga el motor y hace una lectura de prueba, para que la primera reliquia no la pague.

        Medido (herramientas/medir_reliquia.py): cargar el modelo cuesta ~300 ms y
        la primera inferencia de ONNX Runtime ~500 ms; con esto la primera lectura
        de verdad baja a ~350 ms, lo mismo que cualquier otra pantalla con nombres
        nuevos (ONNX Runtime planifica la memoria del reconocedor por cada ancho
        de texto que no ha visto; solo repetir la misma pantalla baja a ~180 ms).
        Se hace una sola vez por motor compartido, con una imagen del tamano de la
        franja de recompensas y nombres pintados para que pasen por el detector y
        por el reconocedor. En automatico se calientan los dos (normal y ligero):
        el ligero entra justo cuando el juego aprieta, y no es momento de pagar su
        carga. Lanza `ErrorMotorOCR` si el motor no carga; un fallo de la lectura de
        prueba solo se registra.
        """
        motor = self._cargar()
        if motor == "winocr":  # pragma: no cover - el OCR de Windows no calienta nada
            return
        adaptativo = self._adaptativo()
        claves = (CLAVE_NORMAL, CLAVE_LIGERO) if adaptativo else (self._clave_fija(),)
        if adaptativo:
            carga.medidor()  # que haya media de carga para cuando llegue la primera lectura
        for clave in claves:
            with MotorOCR._cerrojo:
                if clave in MotorOCR._precalentados:
                    continue
                MotorOCR._precalentados.add(clave)
            inicio = time.monotonic()
            self._forzada = clave
            try:
                self.leer(_imagen_de_prueba())
                if clave == CLAVE_LIGERO:
                    # La fila de nombres la calienta recompensas_rapidas con el motor
                    # que toque al arrancar (el normal); la del ligero, aqui.
                    from .recompensas_rapidas import tira_de_prueba

                    self.leer_tira(tira_de_prueba())
            except ErrorMotorOCR as e:
                if clave != CLAVE_LIGERO:
                    raise
                log.warning("El motor OCR ligero no se pudo cargar; se usara el normal: %s", e)
                continue
            except Exception as e:  # noqa: BLE001 - es solo un calentamiento
                log.warning("El precalentado del OCR fallo: %s", e)
                continue
            finally:
                self._forzada = None
            log.info("Motor OCR '%s' precalentado en %.0f ms", clave, (time.monotonic() - inicio) * 1000)

    @classmethod
    def descargar(cls) -> None:
        """Suelta los modelos compartidos y olvida los fallos (pruebas, cambio de motor)."""
        with cls._cerrojo:
            cls._compartidos.clear()
            cls._fallidos.clear()
            cls._precalentados.clear()
            cls._aligerado = False
            cls._winocr = None

    @classmethod
    def olvidar_fallo(cls, motor: str) -> None:
        """Permite volver a intentar cargar `motor` (el usuario lo cambio en Ajustes)."""
        motor = _ALIAS_MOTOR.get(motor, motor)
        claves = ("winocr",) if motor == "winocr" else (CLAVE_NORMAL, CLAVE_LIGERO, CLAVE_FONDO)
        with cls._cerrojo:
            for clave in claves:
                cls._fallidos.pop(clave, None)

    # -- lectura --------------------------------------------------------------------

    def _medir(self, motor, inicio: float, preparado: float, imagen, deteccion=None) -> None:
        """Deja en `self.tiempos` lo que costo cada etapa de la ultima lectura."""
        fin = time.perf_counter()
        tiempos = {"preparar": preparado - inicio, "total": fin - inicio,
                   "entrada": f"{imagen.shape[1]}x{imagen.shape[0]}", "motor": self.ultima_clave or ""}
        detector = getattr(motor, "text_detector", None)
        reconocedor = getattr(motor, "text_recognizer", None)
        if isinstance(detector, _Cronometrado) and isinstance(reconocedor, _Cronometrado):
            tiempos["detector"] = detector.segundos
            tiempos["reconocedor"] = reconocedor.segundos
        if deteccion:
            tiempos["deteccion"] = deteccion
        self.tiempos = tiempos

    @staticmethod
    def _poner_a_cero(motor) -> None:
        for parte in (getattr(motor, "text_detector", None), getattr(motor, "text_recognizer", None)):
            if isinstance(parte, _Cronometrado):
                parte.segundos, parte.llamadas = 0.0, 0

    def leer(self, imagen, lado_minimo: int | None = None, alto_deteccion: int | None = None) -> list[Leido]:
        """Devuelve los trozos de texto encontrados, con su caja y su confianza.

        Lanza `ErrorMotorOCR` si el motor no se puede cargar; un fallo durante la
        lectura se registra y devuelve lista vacia. Lo que tardo cada etapa queda
        en `self.tiempos` (ver `resumen_tiempos`). `lado_minimo` cambia, solo para
        esta lectura, hasta donde amplia RapidOCR la imagen antes de buscar texto.

        Con `alto_deteccion`, una imagen mas alta se busca (detector) reducida a ese
        alto y se lee (reconocedor) a tamano real, como en `leer_tira`, pero con el
        mismo filtro de confianza que la lectura normal. El detector sobre una captura
        de 4K entera pedia de golpe ~1,3 GB de memoria (medido); reducida, lo mismo que
        a 1440p.
        """
        if imagen is None:
            return []
        inicio = time.perf_counter()
        self.tiempos = {}
        imagen = preparar(imagen)
        if imagen is None:
            return []
        preparado = time.perf_counter()
        motor = self._cargar()
        if motor == "winocr":
            return self._leer_windows(imagen, self.leer)
        self._poner_a_cero(motor)
        if alto_deteccion and imagen.shape[0] > alto_deteccion * 1.05:
            return self._leer_reducida(motor, imagen, alto_deteccion, inicio, preparado)
        reescalados = []
        if lado_minimo:
            detector = getattr(motor, "text_detector", None)
            reescalados = [op for op in getattr(detector, "preprocess_op", None) or []
                           if type(op).__name__ == "DetResizeForTest" and getattr(op, "limit_type", "") == "min"]
        previos = [op.limit_side_len for op in reescalados]
        for op in reescalados:
            op.limit_side_len = lado_minimo
        try:
            resultado, _ = motor(imagen)
        except Exception as e:  # noqa: BLE001 - onnxruntime lanza de todo
            log.warning("El OCR fallo sobre una captura de %sx%s: %s",
                        imagen.shape[1], imagen.shape[0], e)
            return []
        finally:
            for op, lado in zip(reescalados, previos):
                op.limit_side_len = lado
        salida = []
        for caja, texto, confianza in resultado or []:
            xs = [int(p[0]) for p in caja]
            ys = [int(p[1]) for p in caja]
            texto = texto.strip()
            if not texto:
                continue
            salida.append(
                Leido(
                    texto=texto,
                    x=min(xs),
                    y=min(ys),
                    ancho=max(xs) - min(xs),
                    alto=max(ys) - min(ys),
                    confianza=float(confianza),
                )
            )
        self._medir(motor, inicio, preparado, imagen)
        self.tiempos["cajas"] = len(salida)
        return salida

    def _leer_reducida(self, motor, imagen, alto_deteccion: int, inicio: float, preparado: float) -> list[Leido]:
        """`leer` con el detector sobre la imagen reducida (ver `leer`)."""
        try:
            leidos = _leer_tira_rapidocr(motor, imagen, alto_deteccion)
        except Exception as e:  # noqa: BLE001 - onnxruntime lanza de todo
            log.warning("El OCR fallo sobre una captura de %sx%s: %s", imagen.shape[1], imagen.shape[0], e)
            return []
        # El mismo corte que aplica RapidOCR en la lectura normal (`text_score`).
        minimo = float(getattr(motor, "text_score", 0.5) or 0.0)
        salida = [l for l in leidos if l.confianza >= minimo]
        escala = alto_deteccion / imagen.shape[0]
        self._medir(motor, inicio, preparado, imagen,
                    f"{round(imagen.shape[1] * escala)}x{round(imagen.shape[0] * escala)}")
        self.tiempos["cajas"] = len(salida)
        return salida

    def leer_tira(self, imagen, alto_deteccion: int | None = None) -> list[Leido]:
        """Lee una tira estrecha de texto (la fila de nombres de las recompensas) tal cual.

        RapidOCR amplia cualquier imagen hasta 736 px de lado corto antes de
        detectar (una tira de 1250x80 pasa a 11500x736: ~150 ms) y, si es mas de
        8 veces mas ancha que alta, ni detecta: la lee entera como una sola linea.
        Aqui se llaman el detector y el reconocedor directamente y sin reescalar:
        ~30 ms. Mismo contrato que `leer`.

        Con `alto_deteccion`, una imagen mas alta se busca (detector) reducida a ese
        alto, pero se lee (reconocedor) a tamano real: el coste del detector crece
        con los pixeles, y para encontrar donde hay texto no hace falta tanto detalle
        como para leerlo (ver `builds.ALTO_DETECCION`).
        """
        if imagen is None:
            return []
        inicio = time.perf_counter()
        self.tiempos = {}
        imagen = preparar(imagen)
        if imagen is None:
            return []
        preparado = time.perf_counter()
        motor = self._cargar()
        if motor == "winocr":  # el OCR de Windows no reescala
            return self._leer_windows(imagen, self.leer_tira)
        self._poner_a_cero(motor)
        reducir = bool(alto_deteccion) and imagen.shape[0] > alto_deteccion * 1.05
        try:
            if reducir:
                salida = _leer_tira_rapidocr(motor, imagen, alto_deteccion)
            else:
                salida = _leer_tira_rapidocr(motor, imagen)
        except Exception as e:  # noqa: BLE001 - onnxruntime lanza de todo
            log.warning("El OCR fallo sobre una tira de %sx%s: %s", imagen.shape[1], imagen.shape[0], e)
            return []
        escala = alto_deteccion / imagen.shape[0] if reducir else 1.0
        self._medir(motor, inicio, preparado, imagen,
                    f"{round(imagen.shape[1] * escala)}x{round(imagen.shape[0] * escala)}")
        self.tiempos["cajas"] = len(salida)
        return salida

    def leer_linea(self, imagen) -> tuple[str, float]:
        """Reconoce `imagen` como UNA linea de texto ya recortada, sin pasar por el detector.

        Para trozos tan pequenos que el detector no los ve (una cifra suelta): devuelve
        (texto, confianza). Con el OCR de Windows, que no tiene reconocedor aparte, se lee
        como una tira normal.
        """
        if imagen is None:
            return "", 0.0
        preparada = preparar(imagen)
        if preparada is None:
            return "", 0.0
        motor = self._cargar()
        if motor == "winocr" or not hasattr(motor, "text_recognizer"):
            leidos = unir_filas(self.leer_tira(imagen))
            return " ".join(l.texto for l in leidos), min([l.confianza for l in leidos] or [0.0])
        try:
            textos, _ = motor.text_recognizer([preparada])
        except Exception as e:  # noqa: BLE001 - onnxruntime lanza de todo
            log.warning("El OCR fallo sobre una linea de %sx%s: %s", preparada.shape[1], preparada.shape[0], e)
            return "", 0.0
        if not textos:
            return "", 0.0
        return str(textos[0][0]).strip(), float(textos[0][1])

    def _leer_windows(self, imagen, repetir) -> list[Leido]:
        """OCR de Windows; si falla (sin paquete de idioma...), se apunta y se repite en local."""
        try:
            return _leer_winocr(imagen)
        except Exception as e:  # noqa: BLE001 - WinRT lanza de todo
            motivo = f"{type(e).__name__}: {e}"
            with MotorOCR._cerrojo:
                MotorOCR._fallidos["winocr"] = motivo
            self._pasar_a_local(motivo)
            return repetir(imagen)


def _leer_winocr(imagen) -> list[Leido]:  # pragma: no cover - depende del paquete de idioma
    import winocr
    from PIL import Image

    pil = Image.fromarray(imagen[:, :, ::-1])
    resultado = winocr.recognize_pil_sync(pil, lang="es")
    return [
        Leido(
            texto=linea["text"],
            x=int(linea["bounding_rect"]["x"]),
            y=int(linea["bounding_rect"]["y"]),
            ancho=int(linea["bounding_rect"]["width"]),
            alto=int(linea["bounding_rect"]["height"]),
            confianza=1.0,
        )
        for linea in resultado.get("lines", [])
    ]


def _leer_tira_rapidocr(motor, imagen, alto_deteccion: int | None = None) -> list[Leido]:
    """Detector y reconocedor de RapidOCR a pelo, con el reescalado del detector apagado.

    El limite se cambia solo mientras dura la deteccion: el motor es compartido y
    el resto de lecturas siguen queriendo el reescalado de siempre. Con
    `alto_deteccion` se detecta sobre una copia reducida a ese alto y las cajas se
    llevan a la imagen original, de donde se recortan para el reconocedor.
    """
    import numpy as np

    busqueda, escala = imagen, 1.0
    if alto_deteccion and imagen.shape[0] > alto_deteccion:
        import cv2

        escala = alto_deteccion / imagen.shape[0]
        busqueda = cv2.resize(imagen, (max(1, round(imagen.shape[1] * escala)), alto_deteccion),
                              interpolation=cv2.INTER_AREA)
    detector = motor.text_detector
    reescalados = [op for op in detector.preprocess_op if type(op).__name__ == "DetResizeForTest"]
    previos = [(op.limit_type, op.limit_side_len) for op in reescalados]
    for op in reescalados:
        op.limit_type, op.limit_side_len = "max", 8192
    try:
        cajas, _ = detector(busqueda)
    finally:
        for op, (tipo, lado) in zip(reescalados, previos):
            op.limit_type, op.limit_side_len = tipo, lado
    if cajas is None or len(cajas) == 0:
        return []
    if escala != 1.0:
        cajas = np.asarray(cajas, dtype=np.float32) / np.float32(escala)
        cajas[:, :, 0] = np.clip(cajas[:, :, 0], 0, imagen.shape[1] - 1)
        cajas[:, :, 1] = np.clip(cajas[:, :, 1], 0, imagen.shape[0] - 1)
    cajas = motor.sorted_boxes(cajas)
    textos, _ = motor.text_recognizer(motor.get_crop_img_list(imagen, cajas))
    salida = []
    for caja, (texto, confianza) in zip(cajas, textos):
        texto = texto.strip()
        if not texto:
            continue
        xs = [int(p[0]) for p in caja]
        ys = [int(p[1]) for p in caja]
        salida.append(Leido(texto, min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), float(confianza)))
    return salida


def resumen_tiempos(tiempos: dict | None) -> str:
    """Las etapas de una lectura en una linea para el registro: "preparar 3 ms, detector ..."."""
    if not tiempos:
        return "sin tiempos"
    partes = [f"{etapa} {tiempos[etapa] * 1000:.0f} ms"
              for etapa in ("preparar", "detector", "reconocedor") if etapa in tiempos]
    detalle = f"{tiempos.get('cajas', 0)} cajas, imagen {tiempos.get('entrada', '?')}"
    if tiempos.get("deteccion") and tiempos["deteccion"] != tiempos.get("entrada"):
        detalle += f" (buscada a {tiempos['deteccion']})"
    if tiempos.get("motor"):
        detalle += f", motor {tiempos['motor']}"
    return ", ".join(partes) + f" [{detalle}]"


def _imagen_de_prueba(ancho: int = 1536, alto: int = 454):
    """Franja oscura con una palabra clara, como la pantalla de recompensas a 1080p."""
    import numpy as np

    imagen = np.full((alto, ancho, 3), 16, np.uint8)
    # Cuatro nombres repartidos como las tarjetas, para que el reconocedor reciba
    # un lote parecido al real (varias cajas de texto de anchos distintos).
    paso = ancho // 4
    try:
        import cv2

        for i, palabra in enumerate(("SISTEMAS DE ASH PRIME", "CANON DE BRATON PRIME", "RECEPTOR PRIME", "PLANO")):
            cv2.putText(imagen, palabra, (paso * i + 20, alto * 3 // 4), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (235, 235, 235), 2)
    except ImportError:  # pragma: no cover - cv2 viene con rapidocr
        for i in range(4):
            imagen[alto * 3 // 4 - 20 : alto * 3 // 4, paso * i + 20 : paso * i + 220] = 235
    return imagen


def _orden_libre(clave: str) -> str:
    """La clave con las palabras ordenadas: 'chasis caliban prime' == 'caliban prime chasis'."""
    return " ".join(sorted(clave.split()))

RE_PRIME_ROTO = re.compile(r"^p.{1,4}e$")


def _parece_prime(trozo: str) -> bool:
    """Si el trozo puede ser un "prime" mal leido o cortado: "pnke", "prme", "pri", "pm"."""
    if not 2 <= len(trozo) <= 6:
        return False
    if len(trozo) >= 4 and Levenshtein.distance(trozo, "prime") <= 2:
        return True  # "prims", "rrime", "raime", "primc"
    if trozo[0] != "p":
        return False
    if RE_PRIME_ROTO.match(trozo):
        return True
    resto = iter("prime")
    return all(letra in resto for letra in trozo)  # sus letras salen de "prime", en orden


def _lleva_prime_roto(texto: str, clave: str) -> bool:
    """Si en lo leido hay un trozo que no es del nombre `clave` y parece un "Prime" mal
    leido, suelto ("Ember Pnke") o pegado detras de una palabra del nombre ("EberPnke")."""
    palabras = [p for p in clave.split() if p != "prime"]
    partido = re.sub(r"(?<=[a-zà-ÿ])(?=[A-Z])", " ", texto or "")  # "EberPnke" -> "Eber Pnke"
    for trozo in normalizar(partido).split() + normalizar(texto or "").split():
        if trozo in palabras:
            continue
        if _parece_prime(trozo) and all(fuzz.ratio(trozo, p) < 80 for p in palabras):
            return True
        for corte in range(2, 7):
            cabeza, cola = trozo[:-corte], trozo[-corte:]
            if len(cabeza) >= 3 and _parece_prime(cola) and any(
                    fuzz.ratio(cabeza, p) >= 75 or (len(p) >= 3 and fuzz.ratio(cabeza[-len(p):], p) >= 75) for p in palabras):
                return True
    return False


def preparar(imagen):
    """Deja la captura como la quiere el OCR: gris, con contraste y contigua.

    El juego pinta texto claro sobre fondos oscuros pero a veces con poca luz
    (menus semitransparentes, texto gris sobre gris). En escala de gris y con el
    contraste estirado entre los percentiles 2 y 99.8 el detector lee texto que
    en color se le escapaba, y ademas tarda menos. Devuelve None si no es imagen.
    """
    import numpy as np

    if not isinstance(imagen, np.ndarray) or imagen.ndim not in (2, 3) or imagen.size == 0:
        return None
    if imagen.ndim == 3 and imagen.shape[2] > 3:
        imagen = imagen[:, :, :3]
    if imagen.dtype != np.uint8:
        imagen = np.clip(imagen, 0, 255).astype(np.uint8)
    try:
        import cv2
    except ImportError:  # pragma: no cover - cv2 viene con rapidocr
        cv2 = None
    if imagen.ndim == 3:
        if cv2 is not None:
            gris = cv2.cvtColor(np.ascontiguousarray(imagen), cv2.COLOR_BGR2GRAY)
        else:  # pragma: no cover
            gris = imagen.mean(axis=2).astype(np.uint8)
    else:
        gris = np.ascontiguousarray(imagen)
    # Percentiles sobre una muestra: en una franja de 1536x450 no se nota.
    bajo, alto = np.percentile(gris[::2, ::2], (2.0, 99.8))
    if alto - bajo >= 1:
        # La misma cuenta de siempre, pero sobre los 256 valores posibles y aplicada con
        # una tabla: da exactamente los mismos pixeles y a 4K pasa de ~90 ms a ~3 ms.
        tabla = np.clip((np.arange(256, dtype=np.float32) - bajo) * (255.0 / (alto - bajo)), 0, 255)
        tabla = tabla.astype(np.uint8)
        gris = cv2.LUT(gris, tabla) if cv2 is not None else tabla[gris]
    if cv2 is not None:
        return cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR)
    return np.ascontiguousarray(np.repeat(gris[:, :, None], 3, axis=2))  # pragma: no cover


def unir_filas(leidos: list[Leido], holgura: float = 0.6) -> list[Leido]:
    """Junta los trozos de una misma linea que el detector devolvio partidos.

    "AKBOLTO PRIME" y "BLUEPRINT" salen a veces como dos cajas separadas por un
    hueco menor que la altura del texto; por separado casan con cosas distintas.
    """
    pendientes = sorted(leidos, key=lambda l: (l.y, l.x))
    filas: list[Leido] = []
    for trozo in pendientes:
        for fila in filas:
            alto = min(fila.alto, trozo.alto) or 1
            solape = min(fila.y + fila.alto, trozo.y + trozo.alto) - max(fila.y, trozo.y)
            hueco = max(trozo.x - (fila.x + fila.ancho), fila.x - (trozo.x + trozo.ancho))
            if solape >= 0.5 * alto and hueco <= holgura * max(fila.alto, trozo.alto):
                izquierda, derecha = sorted((fila, trozo), key=lambda l: l.x)
                fila.texto = f"{izquierda.texto} {derecha.texto}"
                x0, y0 = min(fila.x, trozo.x), min(fila.y, trozo.y)
                x1 = max(fila.x + fila.ancho, trozo.x + trozo.ancho)
                y1 = max(fila.y + fila.alto, trozo.y + trozo.alto)
                fila.x, fila.y, fila.ancho, fila.alto = x0, y0, x1 - x0, y1 - y0
                fila.confianza = min(fila.confianza, trozo.confianza)
                break
        else:
            filas.append(Leido(trozo.texto, trozo.x, trozo.y, trozo.ancho, trozo.alto,
                               trozo.confianza))
    return filas


def agrupar_bloques(lineas: list[Leido], holgura: float = 0.9) -> list[list[Leido]]:
    """Agrupa las lineas que van una debajo de otra: los nombres largos se partan."""
    pendientes = sorted(lineas, key=lambda l: (l.y, l.x))
    bloques: list[list[Leido]] = []
    for linea in pendientes:
        for bloque in bloques:
            ultima = bloque[-1]
            solape_x = min(ultima.x + ultima.ancho, linea.x + linea.ancho) - max(ultima.x, linea.x)
            hueco_y = linea.y - (ultima.y + ultima.alto)
            if solape_x > 0 and -0.3 * linea.alto <= hueco_y <= holgura * max(ultima.alto, linea.alto):
                bloque.append(linea)
                break
        else:
            bloques.append([linea])
    return bloques


# El rango de una tarjeta de mod tal y como sale del OCR: "14", "14Y", "8r", "16X"
# (el icono de polaridad se lee como una letra).
RE_RANGO_TARJETA = re.compile(r"^\d{1,2}\W?[A-Za-z]?\W?$")


def _limites_trozo(bloque: list[Leido]) -> tuple[int, int] | None:
    """(desde, hasta) del bloque sin los rangos de tarjeta de los extremos, o None si
    no queda un trozo de 2 lineas o mas distinto del bloque entero."""
    desde, hasta = 0, len(bloque)
    while desde < hasta and RE_RANGO_TARJETA.match(bloque[desde].texto.strip()):
        desde += 1
    while hasta > desde and RE_RANGO_TARJETA.match(bloque[hasta - 1].texto.strip()):
        hasta -= 1
    if hasta - desde < 2 or (desde, hasta) == (0, len(bloque)):
        return None
    return desde, hasta


def _casar_trozo(bloque: list[Leido], casador: "Casador", umbral: int):
    """El bloque sin los rangos de tarjeta de arriba y de abajo, si asi casa (y quedan
    2 lineas o mas): ((desde, hasta), Reconocido), o None. Solo se quitan rangos: con
    trozos cualquiera, la descripcion de un mod ("+5% de capacidad de / cargador")
    acababa casando con otro mod."""
    limites = _limites_trozo(bloque)
    if limites is None:
        return None
    desde, hasta = limites
    trozo = bloque[desde:hasta]
    texto = " ".join(l.texto for l in trozo)
    item_id, nombre, puntos = casador.casar(texto, umbral)
    if not item_id:
        return None
    return (desde, hasta), Reconocido(texto, item_id, nombre, puntos, _caja_union(trozo))


def _caja_union(lineas: list[Leido]) -> tuple[int, int, int, int]:
    x0 = min(l.x for l in lineas)
    y0 = min(l.y for l in lineas)
    x1 = max(l.x + l.ancho for l in lineas)
    y1 = max(l.y + l.alto for l in lineas)
    return x0, y0, x1 - x0, y1 - y0


_avisado_rapidfuzz = False


def rapidfuzz_en_cpp() -> bool:
    """Si rapidfuzz usa su version compilada. Si no la encuentra (empaquetado roto, DLL
    que no carga) cae en silencio a Python puro, unas 100 veces mas lento: medido con el
    indice real, casar una pantalla de mejoras pasaba de ~30 ms a ~8 s."""
    return not fuzz.ratio.__module__.endswith("_py") and not rf_process.cdist.__module__.endswith("_py")


def avisar_si_rapidfuzz_lento() -> None:
    global _avisado_rapidfuzz
    if _avisado_rapidfuzz:
        return
    _avisado_rapidfuzz = True
    if rapidfuzz_en_cpp():
        log.info("Casado de nombres con rapidfuzz compilado (%s)", fuzz.ratio.__module__)
    else:
        log.warning("rapidfuzz va en Python puro (%s, %s): casar los nombres leidos sera muy lento",
                    fuzz.ratio.__module__, rf_process.cdist.__module__)
        # El motivo real (una DLL que no carga, un modulo que falta) rapidfuzz se lo calla.
        try:
            import rapidfuzz.fuzz_cpp  # noqa: F401
        except Exception as error:  # noqa: BLE001 - solo es para el registro
            log.warning("  motivo: %r", error)


@dataclass
class _Consulta:
    """Un texto leido ya preparado para la busqueda aproximada en el catalogo."""

    texto: str
    consulta: str
    compacta: str
    ordenada: str
    con_plano: bool


# Hilos para la preseleccion en lote (`Casador.precasar`): el juego va a la vez, asi que
# no se cogen todos los nucleos.
HILOS_CASADO = HILOS_OCR


class Casador:
    """Casa el texto leido con los nombres del catalogo, en espanol y en ingles."""

    # Si el segundo mejor es otro objeto y queda a menos de esto, no se decide:
    # "Photor Vidar MK I" y "MK IV" se parecen demasiado tras un OCR con erratas.
    MARGEN = 4.0

    def __init__(self, con: sqlite3.Connection, categorias=CATEGORIAS_PLAUSIBLES, filtro=None):
        """`filtro(categoria, tipo, unique_name) -> bool` deja fuera fichas que no
        pueden salir en la pantalla que se lee (p. ej. componentes en el perfil)."""
        marcas = ", ".join("?" for _ in categorias)
        # Con nombres repetidos (mods Beginner/Expert, "Unfused Artifact"...) se
        # prefiere el que tenga datos de mercado o de ducados.
        filas = con.execute(
            f"""
            SELECT i.id, i.nombre_en, i.nombre_es, p.nombre_en, p.nombre_es,
                   i.categoria, i.tipo, i.unique_name, i.padre_id
              FROM items i LEFT JOIN items p ON p.id = i.padre_id
             WHERE i.categoria IN ({marcas})
             ORDER BY (i.market_slug IS NULL), (i.ducados IS NULL), length(i.unique_name)
            """,
            tuple(categorias),
        ).fetchall()

        # Nombres en fr/de/pt/it/pl de los objetos de arriba y de sus padres.
        ids = {f[0] for f in filas} | {f[8] for f in filas if f[8]}
        nombres_idioma: dict[int, dict[str, str]] = {}
        if ids:
            marcas_id = ", ".join("?" * len(ids))
            for iid, idioma, nombre in con.execute(
                f"SELECT item_id, idioma, nombre FROM items_nombres WHERE item_id IN ({marcas_id})",
                tuple(ids),
            ):
                nombres_idioma.setdefault(iid, {})[idioma] = nombre

        # Palabras genericas y la palabra local de "Blueprint" en cada idioma, sacadas
        # del glosario de componentes (WFCD no trae esa palabra traducida en ningun sitio).
        self.genericas = set(GENERICAS)
        # "Schéma" es como pone el juego en frances el plano en la pantalla de recompensas
        # ("Lex Prime (Schéma)", captura real de 2025); el glosario solo trae "Plan".
        # Y en portugues "(Diagrama)" ("Guandao Prime (Diagrama)", 86 capturas reales): sin
        # ella el plano se parecia a la "Lama" italiana de la misma arma.
        # En aleman el juego pone "Blaupause" ("Akbronco Prime Blaupause", video real de 2024)
        # y el glosario solo trae "Bauplan": sin ella el plano casaba con "Bronco Prime".
        self.palabras_plano = ["plano", "blueprint", "schema", "diagrama", "blaupause"]
        for idioma, en, valor in con.execute(
            "SELECT idioma, en, valor FROM glosario_idiomas WHERE dominio = 'componente'"
        ):
            palabra = normalizar(valor)
            if not palabra:
                continue
            self.genericas.update(palabra.split())
            if en == "Blueprint" and palabra not in self.palabras_plano:
                self.palabras_plano.append(palabra)

        self.candidatos: dict[str, tuple[int, str]] = {}
        # En que idiomas se llama asi cada clave ("es", "en", "fr"...): para no mezclar el
        # nombre de un idioma con los de otro (captura/huecos_build.py).
        self.idiomas_de_clave: dict[str, set[str]] = {}
        alias: dict[str, tuple[int, str]] = {}
        for iid, nombre_en, nombre_es, padre_en, padre_es, categoria, tipo, unique_name, padre_id in filas:
            if filtro is not None and not filtro(categoria, tipo, unique_name):
                continue
            pares = [(nombre_es, padre_es, "es"), (nombre_en, padre_en, "en")]
            extra_item = nombres_idioma.get(iid, {})
            extra_padre = nombres_idioma.get(padre_id, {}) if padre_id else {}
            for idioma, nombre_i in extra_item.items():
                # Sin nombre del padre en ese idioma, el nombre en espanol o ingles vale
                # igual: los nombres propios (Ash Prime, Braton Prime...) no cambian.
                pares.append((nombre_i, extra_padre.get(idioma) or padre_es or padre_en, idioma))
            for nombre, padre, idioma in pares:
                if not nombre:
                    continue
                etiqueta = f"{padre} {nombre}" if padre else nombre
                etiqueta = " ".join(RE_ETIQUETAS.sub(" ", etiqueta).split())
                clave = normalizar(etiqueta)
                for variante in _con_sinonimos(clave):
                    if not variante:
                        continue
                    self.candidatos.setdefault(variante, (iid, etiqueta))
                    self.idiomas_de_clave.setdefault(variante, set()).add(idioma)
                    # El juego escribe "Plano"/"Blueprint"/etc. al final; tambien se busca sin el.
                    sin_plano = variante
                    for palabra in self.palabras_plano:
                        sin_plano = sin_plano.removesuffix(f" {palabra}")
                    if sin_plano != variante:
                        alias.setdefault(sin_plano, (iid, etiqueta))
        # Los otros nombres de cada objeto (tabla items_alias de datos/items.py): el entero
        # con que lo pinta el juego cuando no sale de juntar padre y pieza ("Hoja de War",
        # "Motor del Mazo del Lobo") y los que el indice tenia antes. Van detras de los
        # de arriba y no los pisan. Un indice sin la tabla se lee igual.
        try:
            otros = con.execute(
                f"""
                SELECT a.item_id, a.nombre, i.categoria, i.tipo, i.unique_name
                  FROM items_alias a JOIN items i ON i.id = a.item_id
                 WHERE i.categoria IN ({marcas})
                 ORDER BY (a.origen != 'oficial'), a.rowid
                """,
                tuple(categorias),
            ).fetchall()
        except sqlite3.Error:
            otros = []
        for iid, nombre, categoria, tipo, unique_name in otros:
            if filtro is not None and not filtro(categoria, tipo, unique_name):
                continue
            etiqueta = " ".join(RE_ETIQUETAS.sub(" ", nombre or "").split())
            for variante in _con_sinonimos(normalizar(etiqueta)):
                if variante:
                    self.candidatos.setdefault(variante, (iid, etiqueta))
        # Los alias van detras: "Cycron" es el arma, no "Cycron Plano". Se
        # guardan aparte para cuando lo leido SI traia "Plano" al final.
        self.alias = alias
        self.claves_alias = list(alias)
        self.alias_compactos = {k.replace(" ", ""): v for k, v in alias.items()}
        self.alias_compacto_a_clave = {k.replace(" ", ""): k for k in alias}
        for clave, valor in alias.items():
            self.candidatos.setdefault(clave, valor)
        self.claves = list(self.candidatos)
        # Las mismas claves sin importar el orden de las palabras: el juego escribe
        # "Plano de Chasis de Caliban Prime" y el catalogo "Caliban Prime Chasis".
        self.por_palabras = {}
        for clave, valor in self.candidatos.items():
            self.por_palabras.setdefault(_orden_libre(clave), valor)
        self.alias_por_palabras = {}
        for clave, valor in alias.items():
            self.alias_por_palabras.setdefault(_orden_libre(clave), valor)
        # El OCR pega las palabras a menudo ("CHASISDEASHPRIME"), asi que se
        # guarda tambien cada nombre sin espacios para poder casarlo.
        self.compactos = {k.replace(" ", ""): v for k, v in self.candidatos.items()}
        self.compactos_a_clave = {k.replace(" ", ""): k for k in self.candidatos}
        self.claves_compactas = list(self.compactos)
        # Cuando el OCR pega las palabras se pierde el orden y no valen los
        # comparadores por palabras. Ordenando las letras, "chasisashprime" y
        # "ashprimechasis" son la misma cadena.
        self.ordenadas: dict[str, str] = {}
        for k in self.candidatos:
            self.ordenadas.setdefault("".join(sorted(k.replace(" ", ""))), k)
        self.claves_ordenadas = list(self.ordenadas)

    def restringido(self, ids: set[int]) -> "Casador":
        """Copia que solo conoce esos objetos (las recompensas que EE.log ya dio).

        Con un conjunto cerrado de 1-4 nombres el casado admite un umbral mas bajo
        sin confundirse. Se construye filtrando los diccionarios ya hechos: ~5 ms,
        frente a los ~30 de volver a leer el indice.
        """
        copia = Casador.__new__(Casador)
        copia.genericas = self.genericas
        copia.palabras_plano = self.palabras_plano
        copia.candidatos = {k: v for k, v in self.candidatos.items() if v[0] in ids}
        copia.alias = {k: v for k, v in self.alias.items() if v[0] in ids}
        copia.alias_compactos = {k.replace(" ", ""): v for k, v in copia.alias.items()}
        # Los alias ("daikyu prime" -> su plano) NO entran como candidatos: leido
        # a secas, "Citrine Prime" es la segunda linea de "Plano De Chasis De /
        # Citrine Prime", no el plano principal (dos chasis salieron como plano).
        # Solo se buscan cuando lo leido trae "Plano" (ver casar).
        copia.claves_alias = list(copia.alias)
        copia.alias_compacto_a_clave = {k.replace(" ", ""): k for k in copia.alias}
        copia.claves = list(copia.candidatos)
        copia.compactos = {k.replace(" ", ""): v for k, v in copia.candidatos.items()}
        copia.compactos_a_clave = {k.replace(" ", ""): k for k in copia.candidatos}
        copia.claves_compactas = list(copia.compactos)
        copia.ordenadas = {}
        for k in copia.candidatos:
            copia.ordenadas.setdefault("".join(sorted(k.replace(" ", ""))), k)
        copia.claves_ordenadas = list(copia.ordenadas)
        copia.por_palabras = {k: v for k, v in self.por_palabras.items() if v[0] in ids}
        copia.alias_por_palabras = {k: v for k, v in self.alias_por_palabras.items() if v[0] in ids}
        return copia

    # Resultados ya calculados por (texto, umbral). Las pantallas repiten muchisimo
    # texto de una lectura a otra (rotulos, estadisticas, los mismos nombres) y cada
    # texto que NO casa cuesta 1-3 ms de busqueda aproximada en ~30.000 nombres.
    MEMO_MAXIMO = 4096

    def casar(self, texto: str, umbral: int = 82) -> tuple[int | None, str, float]:
        """Devuelve (item_id, etiqueta, puntuacion) del objeto que mejor encaja."""
        memo = self.__dict__.get("_memo")
        if memo is None:
            memo = self._memo = {}
        clave_memo = (texto, umbral)
        hecho = memo.get(clave_memo)
        if hecho is None:
            hecho = self._casar(texto, umbral)
            if len(memo) >= self.MEMO_MAXIMO:
                memo.clear()
            memo[clave_memo] = hecho
        return hecho

    def calentar(self) -> None:
        """Deja hecho de antemano lo que la primera lectura construiria sobre la marcha
        (listas ordenadas, palabras de los nombres, los hilos de la busqueda): sin esto
        la primera lectura de la sesion pagaba ~250 ms de mas."""
        avisar_si_rapidfuzz_lento()
        self._ordenadas_de("claves")
        self._ordenadas_de("claves_alias")
        self._es_palabra_de_nombre("")
        self.precasar(["calentar casador"], 82)
        self._memo.pop(("calentar casador", 82), None)

    def precasar(self, textos, umbral: int = 82) -> None:
        """Casa de una vez todos los `textos` que aun no esten en la memoria.

        Lo caro de un texto que no casa es la preseleccion aproximada contra los
        ~10.000 nombres (4-5 pasadas de `rf_process.extract`, ~2 ms por texto, y
        una pantalla trae 50-80 textos que no son nombres). Aqui esa preseleccion
        se hace para todos a la vez con `rf_process.cdist` en varios hilos (en C++,
        sin el GIL). El resultado es el mismo que llamando a `casar` uno a uno; las
        llamadas siguientes a `casar` salen de la memoria.
        """
        memo = self.__dict__.get("_memo")
        if memo is None:
            memo = self._memo = {}
        pendientes: dict[str, _Consulta] = {}
        for texto in dict.fromkeys(textos):
            if (texto, umbral) in memo or texto in pendientes:
                continue
            consulta = self._consulta(texto)
            if isinstance(consulta, _Consulta):
                pendientes[texto] = consulta
            else:
                memo[(texto, umbral)] = consulta
        if not pendientes:
            return
        if len(memo) + len(pendientes) >= self.MEMO_MAXIMO:
            memo.clear()
        lotes = self._preseleccionar_lote(list(pendientes.values()))
        for (texto, consulta), posibles in zip(pendientes.items(), lotes):
            memo[(texto, umbral)] = self._decidir(consulta, umbral, posibles)

    def _casar(self, texto: str, umbral: int) -> tuple[int | None, str, float]:
        consulta = self._consulta(texto)
        if not isinstance(consulta, _Consulta):
            return consulta
        return self._decidir(consulta, umbral, self._preseleccion(consulta))

    def _consulta(self, texto: str):
        """Lo leido ya normalizado para buscarlo, o el resultado si no hace falta buscar
        (vacio, sin letras, exacto o solo palabras genericas)."""
        nada = (None, "", 0.0)
        clave = normalizar(RE_ETIQUETAS.sub(" ", texto or ""))
        if not clave or len(clave) < 3:
            return nada
        # Sin ninguna letra ("571", "3/37", "105%") no puede ser un nombre del catalogo:
        # ninguno se escribe solo con cifras, y la busqueda aproximada costaba igual.
        if not any(c.isalpha() for c in clave):
            return nada
        exacto = self.candidatos.get(clave)
        if exacto:
            return exacto[0], exacto[1], 100.0

        # El juego escribe "Chasis de Ash Prime" donde el catalogo dice
        # "Ash Prime Chasis", y el OCR a veces pega las palabras.
        # La primera palabra nunca es un articulo en un nombre del juego: si lo
        # parece es una letra perdida ("las De Odonata Prime" son las Alas), y
        # quitarla dejaba "odonata prime", el plano principal.
        # Lo mismo detras de "de": "Plano De las De Odonata Prime" son las Alas.
        palabras = clave.split()
        palabras = palabras[:1] + [
            p for i, p in enumerate(palabras[1:], 1)
            if p not in PALABRAS_VACIAS or palabras[i - 1] in ("de", "du", "des", "von")
        ]
        consulta = " ".join(palabras) or clave
        exacto = self.candidatos.get(consulta)
        if exacto:
            return exacto[0], exacto[1], 100.0
        # "Ash Prime Systems Blueprint" y "Sistemas de Ash Prime (Plano)" son la
        # misma pieza que el catalogo guarda sin el sufijo.
        # En castellano el juego lo pone DELANTE: "Plano de Chasis de Caliban Prime".
        # Sin quitarlo, "plano chasis caliban prime" se parecia casi igual al chasis
        # que al plano principal ("Caliban Prime Plano"), y ganaba el principal.
        con_plano = False
        # El OCR tambien pega la palabra: "Ash Prime ChassisBlueprint", "PlanoDe Forma".
        for palabra in self.palabras_plano:
            ultima = consulta.rsplit(" ", 1)[-1]
            if ultima.endswith(palabra) and len(ultima) > len(palabra) + 2:
                consulta = f"{consulta.removesuffix(palabra)} {palabra}"
            primera = consulta.split(" ", 1)[0]
            if primera.startswith(palabra) and len(primera) > len(palabra) + 2:
                resto = primera.removeprefix(palabra)
                resto = "" if resto in PALABRAS_VACIAS else resto
                consulta = " ".join(x for x in (palabra, resto, consulta.partition(" ")[2]) if x)
        # Y la lee mal: "Odonata Prime Wings lueprint". Sin reconocerla, el
        # plano principal ganaba a las alas.
        extremos = consulta.split()
        if len(extremos) >= 3:
            for i in (-1, 0):
                if extremos[i] in self.palabras_plano or len(extremos[i]) < 5:
                    continue
                parecida = max(self.palabras_plano, key=lambda w: fuzz.ratio(extremos[i], w))
                if fuzz.ratio(extremos[i], parecida) >= 80 and not self._es_palabra_de_nombre(extremos[i]):
                    extremos[i] = parecida
            consulta = " ".join(extremos)
        for palabra in self.palabras_plano:
            prefijo = f"{palabra} "
            if consulta.startswith(prefijo) and consulta != prefijo.strip():
                con_plano = True
                consulta = consulta.removeprefix(prefijo)
                break
        for palabra in self.palabras_plano:
            sufijo = f" {palabra}"
            if consulta.endswith(sufijo):
                con_plano = True
                consulta = consulta.removesuffix(sufijo)
                break
        if con_plano:
            # "IVARAPRIME BLUEPRINT" es la pieza, no la warframe; y "Plano de Caliban
            # Prime" es el plano principal, no la warframe entera.
            exacto = (
                self.alias.get(consulta)
                or self.candidatos.get(consulta)
                or self.alias_por_palabras.get(_orden_libre(consulta))
                or self.por_palabras.get(_orden_libre(consulta))
            )
            if exacto:
                return exacto[0], exacto[1], 100.0
        else:
            exacto = self.por_palabras.get(_orden_libre(consulta))
            if exacto:
                return exacto[0], exacto[1], 100.0
        compacta = consulta.replace(" ", "")
        exacto = (self.alias_compactos.get(compacta) if con_plano else None) or             self.compactos.get(compacta)
        if exacto:
            return exacto[0], exacto[1], 100.0

        # Solo palabras genericas ("BLUEPRINT", "PRIME SYSTEMS"): no hay objeto.
        if all(p in self.genericas for p in consulta.split()) or compacta in self.genericas:
            return nada
        return _Consulta(texto, consulta, compacta, _orden_libre(consulta), con_plano)

    def _preseleccion(self, q: "_Consulta") -> set[str]:
        """Las claves del catalogo que merece la pena puntuar (busqueda aproximada)."""
        consulta, compacta, ordenada, con_plano = q.consulta, q.compacta, q.ordenada, q.con_plano
        # token_sort_ratio(a, b) es ratio() entre las dos con las palabras ordenadas; con
        # los nombres ya ordenados de antemano (`_ordenadas_de`) sale lo mismo en ~6
        # veces menos tiempo: era lo que mas costaba de cada texto que no casa.
        claves = self.claves
        posibles = {
            claves[m[2]] for m in rf_process.extract(
                ordenada, self._ordenadas_de("claves"), scorer=fuzz.ratio, limit=8, score_cutoff=55
            )
        }
        if con_plano:
            # "Plano De Daiky Prime": la clave corta del plano es un alias.
            claves_alias = self.claves_alias
            posibles |= {
                claves_alias[m[2]] for m in rf_process.extract(
                    ordenada, self._ordenadas_de("claves_alias"), scorer=fuzz.ratio, limit=8, score_cutoff=55
                )
            }
            # Por letras tambien: con la primera letra perdida ("rost prime") el orden
            # de palabras despistaba a la preseleccion y "frost prime" ni entraba.
            posibles |= {
                self.alias_compacto_a_clave[m[0]]
                for m in rf_process.extract(
                    compacta, list(self.alias_compacto_a_clave), scorer=fuzz.ratio, limit=8, score_cutoff=55
                )
            }
        posibles |= {
            self.compactos_a_clave[m[0]]
            for m in rf_process.extract(
                compacta, self.claves_compactas, scorer=fuzz.ratio, limit=8, score_cutoff=55
            )
        }
        if len(compacta) >= 8:
            # Texto pegado o con las palabras en otro orden: mismas letras casi
            # en la misma proporcion. Solo sirve para preseleccionar; la
            # puntuacion de verdad la pone _puntuar.
            posibles |= {
                self.ordenadas[m[0]]
                for m in rf_process.extract(
                    "".join(sorted(compacta)), self.claves_ordenadas,
                    scorer=fuzz.ratio, limit=8, score_cutoff=80,
                )
            }
        return posibles

    def _preseleccionar_lote(self, consultas: list["_Consulta"]) -> list[set[str]]:
        """`_preseleccion` de muchas consultas a la vez: mismas listas, mismos cortes y
        los mismos 8 mejores por lista (empates por posicion, como `extract`)."""
        import numpy as np

        posibles: list[set[str]] = [set() for _ in consultas]

        def pasada(indices: list[int], textos: list[str], opciones: list[str], a_clave, corte: int) -> None:
            if not indices or not opciones:
                return
            matriz = rf_process.cdist(textos, opciones, scorer=fuzz.ratio, score_cutoff=corte,
                                      workers=HILOS_CASADO)
            for fila, i in enumerate(indices):
                puntos = matriz[fila]
                elegidos = np.flatnonzero(puntos >= corte)
                if len(elegidos) > 8:
                    elegidos = elegidos[np.lexsort((elegidos, -puntos[elegidos]))[:8]]
                posibles[i].update(a_clave(int(j)) for j in elegidos)

        todas = list(range(len(consultas)))
        claves = self.claves
        pasada(todas, [q.ordenada for q in consultas], self._ordenadas_de("claves"), claves.__getitem__, 55)
        con_plano = [i for i, q in enumerate(consultas) if q.con_plano]
        if con_plano:
            claves_alias = self.claves_alias
            pasada(con_plano, [consultas[i].ordenada for i in con_plano], self._ordenadas_de("claves_alias"),
                   claves_alias.__getitem__, 55)
            compactas_alias = list(self.alias_compacto_a_clave)
            pasada(con_plano, [consultas[i].compacta for i in con_plano], compactas_alias,
                   lambda j: self.alias_compacto_a_clave[compactas_alias[j]], 55)
        compactas = self.claves_compactas
        pasada(todas, [q.compacta for q in consultas], compactas,
               lambda j: self.compactos_a_clave[compactas[j]], 55)
        largas = [i for i, q in enumerate(consultas) if len(q.compacta) >= 8]
        ordenadas = self.claves_ordenadas
        pasada(largas, ["".join(sorted(consultas[i].compacta)) for i in largas], ordenadas,
               lambda j: self.ordenadas[ordenadas[j]], 80)
        return posibles

    def _decidir(self, q: "_Consulta", umbral: int, posibles: set[str]) -> tuple[int | None, str, float]:
        """Puntua la preseleccion y decide (o no, si hay dudas)."""
        nada = (None, "", 0.0)
        texto, consulta, compacta, con_plano = q.texto, q.consulta, q.compacta, q.con_plano
        # Cuanto mas corto lo leido, menos erratas caben: "BLADE" no es "Blaze".
        umbral_efectivo = max(float(umbral), 96.0 - len(compacta))
        puntuadas = sorted(
            ((self._puntuar(consulta, compacta, c), c) for c in posibles), reverse=True
        )
        if not puntuadas or puntuadas[0][0] < umbral_efectivo:
            return nada
        def objeto(c: str) -> tuple[int, str]:
            # Leido con "Plano" y con errata ("Plano De Daiky Prime"): la clave
            # corta es la del arma, pero lo que salio es su plano.
            return self.alias[c] if con_plano and c in self.alias else self.candidatos.get(c) or self.alias[c]

        mejor_puntos, mejor_clave = puntuadas[0]
        mejor_id = objeto(mejor_clave)[0]
        if not _lleva_lo_distintivo(mejor_clave, compacta, self.genericas):
            # "EMPUNADURA DE QUASSUS PRIME" se parecia un 84 % a "Nikana Prime
            # Empunadura" solo por las palabras genericas: sin rastro de "nikana"
            # en lo leido, no es ese objeto. Mejor nada que una etiqueta segura y falsa.
            return nada
        if "prime" in compacta and "prime" not in mejor_clave.replace(" ", ""):
            # Lo leido dice "prime" y el candidato no lo lleva: "PrimeHandle" (la cola de
            # "Masseter Prime Handle" cortada por el borde del recuadro, captura real a 607p)
            # estaba a una letra de "Pride Handle" y lo abria. Ningun objeto sin "Prime" en
            # el nombre se escribe con "prime" en pantalla.
            return nada
        hermana = self._hermana_prime(mejor_clave)
        if hermana is not None and mejor_puntos < 100.0 and "prime" not in compacta:
            # El mismo objeto existe con y sin "Prime" ("Ember Neuroptiques" y "Ember Prime
            # Neuroptiques") y lo leido no dice "prime" con todas sus letras: solo vale para
            # la variante que le toca. "EberPnke Neuroptiques" (un "Ember Prime" mal leido,
            # captura real en frances) casaba con la pieza de la Ember sin Prime, y dar la
            # que no es cambia el precio y la reliquia. Con un "Prime" roto en lo leido no se
            # da la de sin Prime; sin rastro de "Prime", no se da la Prime.
            roto = _lleva_prime_roto(texto, mejor_clave)
            if roto != ("prime" in mejor_clave.split()):
                log.debug("Ambiguo %r: %s o %s (con y sin Prime)", texto, mejor_clave, hermana)
                return nada
        for puntos, otra in puntuadas[1:]:
            if objeto(otra)[0] == mejor_id:
                continue
            # Dos objetos que solo se distinguen por un numeral ("MK I" / "MK IV")
            # exigen una lectura casi perfecta; si no, mejor no decir nada.
            solo_numeral = (set(mejor_clave.split()) ^ set(otra.split())) <= NUMERALES
            # "bor prime" esta a una letra de "bo prime" y de "boar prime": no hay
            # forma de saber cual es, por mucho que uno puntue algo mas.
            a_una_letra = (
                Levenshtein.distance(compacta, mejor_clave.replace(" ", "")) <= 1
                and Levenshtein.distance(compacta, otra.replace(" ", "")) <= 1
            )
            if mejor_puntos < 97.0 and (mejor_puntos - puntos < self.MARGEN or solo_numeral or a_una_letra):
                log.debug("Ambiguo %r: %s (%.0f) frente a %s (%.0f)",
                          texto, mejor_clave, mejor_puntos, otra, puntos)
                return nada
            break
        iid, etiqueta = objeto(mejor_clave)
        return iid, etiqueta, float(mejor_puntos)

    def _hermana_prime(self, clave: str) -> str | None:
        """La clave del mismo nombre con "prime" si esta no lo lleva, o sin el si lo lleva
        (y es otro objeto); None si no hay tal. Se calcula una vez por casador."""
        hermanas = self.__dict__.get("_hermanas_prime")
        if hermanas is None:
            hermanas = {}
            todas = dict(self.alias)
            todas.update(self.candidatos)
            por_orden = {_orden_libre(k): k for k in todas}
            for con_prime in todas:
                palabras = con_prime.split()
                if "prime" not in palabras:
                    continue
                palabras.remove("prime")
                sin_prime = por_orden.get(_orden_libre(" ".join(palabras)))
                if sin_prime is not None and todas[sin_prime][0] != todas[con_prime][0]:
                    hermanas[con_prime] = sin_prime
                    hermanas.setdefault(sin_prime, con_prime)
            self._hermanas_prime = hermanas
        return hermanas.get(clave)

    def _ordenadas_de(self, atributo: str) -> list[str]:
        """La lista `atributo` (claves o claves_alias) con las palabras de cada nombre
        ordenadas, calculada una vez por casador (tambien para los de `restringido`)."""
        cache = self.__dict__.setdefault("_ordenadas", {})
        lista = getattr(self, atributo)
        hecho = cache.get(atributo)
        if hecho is None or hecho[0] is not lista:
            hecho = (lista, [_orden_libre(k) for k in lista])
            cache[atributo] = hecho
        return hecho[1]

    def _es_palabra_de_nombre(self, palabra: str) -> bool:
        """Si la palabra aparece tal cual en algun nombre del catalogo (no es una errata)."""
        if not hasattr(self, "_palabras_de_nombre") or self._palabras_de_nombre is None:
            self._palabras_de_nombre = {p for clave in self.candidatos for p in clave.split()}
        return palabra in self._palabras_de_nombre

    def _puntuar(self, consulta: str, compacta: str, candidata: str) -> float:
        """Parecido 0-100 entre lo leido y una clave del catalogo.

        Se toma lo mejor de tres medidas: palabras alineadas una a una (aguanta
        el cambio de orden "Chasis de Ash Prime" / "Ash Prime Chasis"), cadenas
        sin espacios (aguanta el texto pegado) y palabras del candidato
        contenidas en el texto pegado. Un candidato mucho mas corto o mas largo
        que lo leido pierde puntos: "Ash Prime" no es "Chasis de Ash Prime".
        """
        palabras_c = candidata.split()
        compacta_c = candidata.replace(" ", "")
        puntos = max(
            _alinear(consulta.split(), palabras_c),
            fuzz.ratio(compacta, compacta_c),
        ) * _castigo_largo(compacta, compacta_c)
        if len(compacta) >= 8:
            # Texto pegado (del todo o a medias): puede llevar dentro un "de"
            # que el catalogo no tiene.
            variantes = {compacta}
            for vacia in ("de", "del", "of", "the"):
                if vacia in compacta:
                    variantes.add(compacta.replace(vacia, "", 1))
            for variante in variantes:
                factor = _castigo_largo(variante, compacta_c)
                puntos = max(
                    puntos,
                    _contenidas(variante, palabras_c) * factor,
                    fuzz.ratio(variante, compacta_c) * factor,
                )
        return puntos


def _con_sinonimos(clave: str) -> list[str]:
    """La clave y sus variantes con sinonimos (mango <-> empunadura) y con las letras que
    el OCR no tiene escritas como las lee: la "ł" polaca sale "t" o "l" ("Mroczne Wtokna",
    "Ograniczony Umyst" en capturas reales), la "ß" alemana "ss" o "b" y la "œ" "oe"."""
    salida = [clave]
    palabras = clave.split()
    for i, p in enumerate(palabras):
        if p in SINONIMOS:
            salida.append(" ".join(palabras[:i] + [SINONIMOS[p]] + palabras[i + 1:]))
    for letra, como in LETRAS_SIN_OCR.items():
        if letra in clave:
            salida += [s.replace(letra, c) for s in list(salida) for c in como]
    return salida


# Letras de los nombres que el reconocedor del OCR no tiene y como las lee.
LETRAS_SIN_OCR = {"ł": ("t", "l"), "ß": ("ss", "b"), "œ": ("oe",)}


def _lleva_lo_distintivo(clave: str, compacta: str, genericas=GENERICAS) -> bool:
    """True si alguna palabra NO generica del candidato aparece (aunque con erratas)
    en lo leido. Un candidato sin palabras distintivas no se comprueba."""
    distintivas = [p for p in clave.split() if p not in genericas and p not in PALABRAS_VACIAS and len(p) >= 3]
    if not distintivas:
        return True
    return any(fuzz.partial_ratio(p, compacta) >= 75 for p in distintivas)


def _castigo_largo(a: str, b: str) -> float:
    """Factor 0.5-1: cuanto mas distintas las longitudes, menos vale el parecido."""
    return 1 - abs(len(a) - len(b)) / max(len(a), len(b), 1) * 0.5


def _alinear(palabras_a: list[str], palabras_b: list[str]) -> float:
    """Empareja palabra a palabra por parecido y pesa cada pareja por su largo."""
    if not palabras_a or not palabras_b:
        return 0.0
    parejas = sorted(
        ((fuzz.ratio(a, b), i, j) for i, a in enumerate(palabras_a) for j, b in enumerate(palabras_b)),
        reverse=True,
    )
    usadas_a: set[int] = set()
    usadas_b: set[int] = set()
    suma = 0.0
    for parecido, i, j in parejas:
        if i in usadas_a or j in usadas_b:
            continue
        usadas_a.add(i)
        usadas_b.add(j)
        suma += (len(palabras_a[i]) + len(palabras_b[j])) * parecido / 100.0
    total = sum(len(p) for p in palabras_a) + sum(len(p) for p in palabras_b)
    return 100.0 * suma / total


def _contenidas(compacta: str, palabras: list[str]) -> float:
    """Cuanto de cada palabra del candidato aparece dentro del texto pegado."""
    if not palabras:
        return 0.0
    # Cada letra leida cuenta para UNA palabra: se colocan de la mas larga a la
    # mas corta y lo ya usado se tapa. Sin eso "sistemas hova prime" (Nova con la
    # N mal leida) llevaba dentro "ash" a caballo de "sistem-as h-ova" y ganaba
    # Ash Prime Sistemas.
    libre = compacta
    suma = 0.0
    for p in sorted(palabras, key=len, reverse=True):
        if len(p) >= 3:
            sitio = fuzz.partial_ratio_alignment(p, libre)
            if sitio is None:
                continue
            suma += len(p) * sitio.score / 100.0
            if sitio.score >= 60:
                libre = libre[:sitio.dest_start] + "#" * (sitio.dest_end - sitio.dest_start) + libre[sitio.dest_end:]
        elif len(p) == 2 and p in libre:
            # "mk" se puede comprobar; una sola letra ("i") esta en cualquier sitio.
            suma += len(p)
            libre = libre.replace(p, "##", 1)
    return 100.0 * suma / sum(len(p) for p in palabras)


def leer_lineas(imagen, motor: MotorOCR, minimo_confianza: float = 0.4,
                lado_minimo: int | None = None) -> list[Leido]:
    """OCR de la imagen con los trozos de cada linea ya unidos."""
    leidos = motor.leer(imagen, lado_minimo=lado_minimo) if lado_minimo else motor.leer(imagen)
    return [l for l in unir_filas(leidos) if l.confianza >= minimo_confianza]


def reconocer(
    imagen, motor: MotorOCR, casador: Casador, umbral: int = 82, minimo_confianza: float = 0.4,
    lado_minimo: int | None = None,
) -> list[Reconocido]:
    """Lee la imagen y devuelve solo los trozos que casan con algo del catalogo."""
    return casar_lineas(leer_lineas(imagen, motor, minimo_confianza, lado_minimo), casador, umbral)


def casar_lineas(lineas: list[Leido], casador: Casador, umbral: int = 82,
                 subbloques: bool = False) -> list[Reconocido]:
    """Los trozos ya leidos que casan con algo del catalogo.

    Primero se prueba cada bloque de lineas juntas (los nombres largos se partan
    en dos lineas bajo la tarjeta); si el bloque no casa, cada linea por su lado.

    Con `subbloques`, antes de ir linea a linea se prueba el bloque sin los rangos
    de tarjeta: en las tarjetas de mod el rango de arriba ("14Y") se pega al nombre
    partido ("Primed Bane of" / "Grineer"); el bloque entero no casaba y por
    separado ninguna linea dice que mod es.
    """
    salida = []
    bloques = agrupar_bloques(lineas)
    precasar = getattr(casador, "precasar", None)
    if precasar is not None:
        # Todos los textos que se van a probar, casados de una vez (ver Casador.precasar):
        # lo de abajo ya sale de la memoria.
        textos = []
        for bloque in bloques:
            if len(bloque) > 1:
                textos.append(" ".join(l.texto for l in bloque))
                if subbloques:
                    limites = _limites_trozo(bloque)
                    if limites is not None:
                        textos.append(" ".join(l.texto for l in bloque[limites[0]:limites[1]]))
            textos.extend(l.texto for l in bloque)
        precasar(textos, umbral)
    for bloque in bloques:
        if len(bloque) > 1:
            texto = " ".join(l.texto for l in bloque)
            item_id, nombre, puntos = casador.casar(texto, umbral)
            if item_id:
                salida.append(Reconocido(texto, item_id, nombre, puntos, _caja_union(bloque)))
                continue
            trozo = _casar_trozo(bloque, casador, umbral) if subbloques else None
            if trozo is not None:
                (desde, hasta), reconocido = trozo
                salida.append(reconocido)
                bloque = bloque[:desde] + bloque[hasta:]
        for linea in bloque:
            item_id, nombre, puntos = casador.casar(linea.texto, umbral)
            if item_id:
                salida.append(
                    Reconocido(
                        texto_ocr=linea.texto,
                        item_id=item_id,
                        nombre=nombre,
                        puntuacion=puntos,
                        caja=(linea.x, linea.y, linea.ancho, linea.alto),
                    )
                )
    return salida
