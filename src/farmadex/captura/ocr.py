"""OCR de la pantalla y casado de lo leido con el catalogo.

Motor por defecto: RapidOCR (ONNX Runtime, CPU). Va empaquetado con sus modelos,
asi que no descarga nada en tiempo de ejecucion. Motor alternativo: el OCR de
Windows (`winocr`), seleccionable en Ajustes.

Solo se procesan pixeles ya capturados: este modulo no toca el juego.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass

from rapidfuzz import fuzz, process as rf_process

from ..datos.items import normalizar
from ..registro_log import obtener

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


def _crear_rapidocr(hilos: int):
    """RapidOCR con el numero de hilos acotado y sin el clasificador de giro.

    El paquete no deja pasar opciones de sesion, asi que se le cambia la fabrica
    de `SessionOptions` solo mientras se construye. El texto del juego siempre
    esta derecho: el clasificador de 0/180 grados solo anadia tiempo.
    """
    import rapidocr_onnxruntime.utils as utiles
    from rapidocr_onnxruntime import RapidOCR

    original = utiles.SessionOptions

    def con_hilos():
        opciones = original()
        opciones.intra_op_num_threads = max(1, hilos)
        opciones.inter_op_num_threads = 1
        return opciones

    utiles.SessionOptions = con_hilos
    try:
        return RapidOCR(use_angle_cls=False)
    finally:
        utiles.SessionOptions = original


class MotorOCR:
    """Envoltorio sobre RapidOCR con carga perezosa (tarda ~1 s la primera vez).

    Los modelos se comparten entre todas las instancias del mismo motor: el
    lector de recompensas y el del cursor cargan una sola copia.
    """

    _compartidos: dict[str, object] = {}
    _fallidos: dict[str, str] = {}  # motor -> motivo; no se reintenta en bucle
    _precalentados: set[str] = set()  # motores que ya hicieron su primera inferencia
    _cerrojo = threading.Lock()

    def __init__(self, motor: str = "rapidocr", hilos: int = HILOS_OCR):
        self.motor = motor
        self.hilos = hilos
        self._ocr = None

    @property
    def fallo(self) -> str | None:
        """Motivo por el que este motor no se pudo cargar, o None si va bien."""
        return MotorOCR._fallidos.get(self.motor)

    def _cargar(self):
        """Carga (o recupera) el motor. Lanza `ErrorMotorOCR` si no se puede."""
        if self._ocr is not None:
            return self._ocr
        with MotorOCR._cerrojo:
            motivo = MotorOCR._fallidos.get(self.motor)
            if motivo:
                raise ErrorMotorOCR(motivo)
            if self.motor == "winocr":
                try:
                    import winocr  # noqa: F401 - solo para comprobar que esta
                except ImportError:
                    log.warning("winocr no esta disponible; se usa RapidOCR")
                    self.motor = "rapidocr"
            compartido = MotorOCR._compartidos.get(self.motor)
            if compartido is not None:
                self._ocr = compartido
                return self._ocr
            inicio = time.monotonic()
            try:
                if self.motor == "winocr":
                    self._ocr = "winocr"
                else:
                    self._ocr = _crear_rapidocr(self.hilos)
            except Exception as e:  # noqa: BLE001 - lo que sea, no puede tumbar la app
                motivo = f"{type(e).__name__}: {e}"
                MotorOCR._fallidos[self.motor] = motivo
                log.exception("No se pudo cargar el motor OCR '%s'", self.motor)
                raise ErrorMotorOCR(motivo) from e
            MotorOCR._compartidos[self.motor] = self._ocr
            log.info("Motor OCR '%s' cargado en %.1f s", self.motor, time.monotonic() - inicio)
        return self._ocr

    def precalentar(self) -> None:
        """Carga el motor y hace una lectura de prueba, para que la primera reliquia no la pague.

        Medido (herramientas/medir_reliquia.py): cargar el modelo cuesta ~300 ms y
        la primera inferencia de ONNX Runtime ~500 ms; con esto la primera lectura
        de verdad baja a ~350 ms, lo mismo que cualquier otra pantalla con nombres
        nuevos (ONNX Runtime planifica la memoria del reconocedor por cada ancho
        de texto que no ha visto; solo repetir la misma pantalla baja a ~180 ms).
        Se hace una sola vez por motor compartido, con una imagen del tamano de la
        franja de recompensas y nombres pintados para que pasen por el detector y
        por el reconocedor. Lanza `ErrorMotorOCR` si el motor no carga; un fallo
        de la lectura de prueba solo se registra.
        """
        motor = self._cargar()
        with MotorOCR._cerrojo:
            if self.motor in MotorOCR._precalentados:
                return
            MotorOCR._precalentados.add(self.motor)
        if motor == "winocr":  # pragma: no cover - el OCR de Windows no calienta nada
            return
        inicio = time.monotonic()
        try:
            self.leer(_imagen_de_prueba())
        except Exception as e:  # noqa: BLE001 - es solo un calentamiento
            log.warning("El precalentado del OCR fallo: %s", e)
            return
        log.info("Motor OCR '%s' precalentado en %.0f ms", self.motor, (time.monotonic() - inicio) * 1000)

    @classmethod
    def descargar(cls) -> None:
        """Suelta los modelos compartidos y olvida los fallos (pruebas, cambio de motor)."""
        with cls._cerrojo:
            cls._compartidos.clear()
            cls._fallidos.clear()
            cls._precalentados.clear()

    @classmethod
    def olvidar_fallo(cls, motor: str) -> None:
        """Permite volver a intentar cargar `motor` (el usuario lo cambio en Ajustes)."""
        with cls._cerrojo:
            cls._fallidos.pop(motor, None)

    def leer(self, imagen) -> list[Leido]:
        """Devuelve los trozos de texto encontrados, con su caja y su confianza.

        Lanza `ErrorMotorOCR` si el motor no se puede cargar; un fallo durante la
        lectura se registra y devuelve lista vacia.
        """
        if imagen is None:
            return []
        imagen = preparar(imagen)
        if imagen is None:
            return []
        motor = self._cargar()
        if motor == "winocr":  # pragma: no cover - depende del paquete de idioma
            return self._leer_windows(imagen)
        try:
            resultado, _ = motor(imagen)
        except Exception as e:  # noqa: BLE001 - onnxruntime lanza de todo
            log.warning("El OCR fallo sobre una captura de %sx%s: %s",
                        imagen.shape[1], imagen.shape[0], e)
            return []
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
        return salida

    def leer_tira(self, imagen) -> list[Leido]:
        """Lee una tira estrecha de texto (la fila de nombres de las recompensas) tal cual.

        RapidOCR amplia cualquier imagen hasta 736 px de lado corto antes de
        detectar (una tira de 1250x80 pasa a 11500x736: ~150 ms) y, si es mas de
        8 veces mas ancha que alta, ni detecta: la lee entera como una sola linea.
        Aqui se llaman el detector y el reconocedor directamente y sin reescalar:
        ~30 ms. Mismo contrato que `leer`.
        """
        if imagen is None:
            return []
        imagen = preparar(imagen)
        if imagen is None:
            return []
        motor = self._cargar()
        if motor == "winocr":  # pragma: no cover - el OCR de Windows no reescala
            return self._leer_windows(imagen)
        try:
            return _leer_tira_rapidocr(motor, imagen)
        except Exception as e:  # noqa: BLE001 - onnxruntime lanza de todo
            log.warning("El OCR fallo sobre una tira de %sx%s: %s", imagen.shape[1], imagen.shape[0], e)
            return []

    def _leer_windows(self, imagen) -> list[Leido]:  # pragma: no cover
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


def _leer_tira_rapidocr(motor, imagen) -> list[Leido]:
    """Detector y reconocedor de RapidOCR a pelo, con el reescalado del detector apagado.

    El limite se cambia solo mientras dura la deteccion: el motor es compartido y
    el resto de lecturas siguen queriendo el reescalado de siempre.
    """
    detector = motor.text_detector
    reescalados = [op for op in detector.preprocess_op if type(op).__name__ == "DetResizeForTest"]
    previos = [(op.limit_type, op.limit_side_len) for op in reescalados]
    for op in reescalados:
        op.limit_type, op.limit_side_len = "max", 8192
    try:
        cajas, _ = detector(imagen)
    finally:
        for op, (tipo, lado) in zip(reescalados, previos):
            op.limit_type, op.limit_side_len = tipo, lado
    if cajas is None or len(cajas) == 0:
        return []
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
    if imagen.ndim == 3:
        try:
            import cv2

            gris = cv2.cvtColor(np.ascontiguousarray(imagen), cv2.COLOR_BGR2GRAY)
        except ImportError:  # pragma: no cover - cv2 viene con rapidocr
            gris = imagen.mean(axis=2).astype(np.uint8)
    else:
        gris = imagen
    # Percentiles sobre una muestra: en una franja de 1536x450 no se nota.
    bajo, alto = np.percentile(gris[::2, ::2], (2.0, 99.8))
    if alto - bajo >= 1:
        gris = np.clip((gris.astype(np.float32) - bajo) * (255.0 / (alto - bajo)), 0, 255)
        gris = gris.astype(np.uint8)
    return np.ascontiguousarray(np.repeat(gris[:, :, None], 3, axis=2))


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


def _caja_union(lineas: list[Leido]) -> tuple[int, int, int, int]:
    x0 = min(l.x for l in lineas)
    y0 = min(l.y for l in lineas)
    x1 = max(l.x + l.ancho for l in lineas)
    y1 = max(l.y + l.alto for l in lineas)
    return x0, y0, x1 - x0, y1 - y0


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
        self.palabras_plano = ["plano", "blueprint"]
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
        alias: dict[str, tuple[int, str]] = {}
        for iid, nombre_en, nombre_es, padre_en, padre_es, categoria, tipo, unique_name, padre_id in filas:
            if filtro is not None and not filtro(categoria, tipo, unique_name):
                continue
            pares = [(nombre_es, padre_es), (nombre_en, padre_en)]
            extra_item = nombres_idioma.get(iid, {})
            extra_padre = nombres_idioma.get(padre_id, {}) if padre_id else {}
            for idioma, nombre_i in extra_item.items():
                # Sin nombre del padre en ese idioma, el nombre en espanol o ingles vale
                # igual: los nombres propios (Ash Prime, Braton Prime...) no cambian.
                pares.append((nombre_i, extra_padre.get(idioma) or padre_es or padre_en))
            for nombre, padre in pares:
                if not nombre:
                    continue
                etiqueta = f"{padre} {nombre}" if padre else nombre
                etiqueta = " ".join(RE_ETIQUETAS.sub(" ", etiqueta).split())
                clave = normalizar(etiqueta)
                for variante in _con_sinonimos(clave):
                    if not variante:
                        continue
                    self.candidatos.setdefault(variante, (iid, etiqueta))
                    # El juego escribe "Plano"/"Blueprint"/etc. al final; tambien se busca sin el.
                    sin_plano = variante
                    for palabra in self.palabras_plano:
                        sin_plano = sin_plano.removesuffix(f" {palabra}")
                    if sin_plano != variante:
                        alias.setdefault(sin_plano, (iid, etiqueta))
        # Los alias van detras: "Cycron" es el arma, no "Cycron Plano". Se
        # guardan aparte para cuando lo leido SI traia "Plano" al final.
        self.alias = alias
        self.alias_compactos = {k.replace(" ", ""): v for k, v in alias.items()}
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

    def casar(self, texto: str, umbral: int = 82) -> tuple[int | None, str, float]:
        """Devuelve (item_id, etiqueta, puntuacion) del objeto que mejor encaja."""
        nada = (None, "", 0.0)
        clave = normalizar(RE_ETIQUETAS.sub(" ", texto or ""))
        if not clave or len(clave) < 3:
            return nada
        exacto = self.candidatos.get(clave)
        if exacto:
            return exacto[0], exacto[1], 100.0

        # El juego escribe "Chasis de Ash Prime" donde el catalogo dice
        # "Ash Prime Chasis", y el OCR a veces pega las palabras.
        palabras = [p for p in clave.split() if p not in PALABRAS_VACIAS]
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
        # Cuanto mas corto lo leido, menos erratas caben: "BLADE" no es "Blaze".
        umbral_efectivo = max(float(umbral), 96.0 - len(compacta))

        posibles = {
            m[0] for m in rf_process.extract(
                consulta, self.claves, scorer=fuzz.token_sort_ratio, limit=8, score_cutoff=55
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

        puntuadas = sorted(
            ((self._puntuar(consulta, compacta, c), c) for c in posibles), reverse=True
        )
        if not puntuadas or puntuadas[0][0] < umbral_efectivo:
            return nada
        mejor_puntos, mejor_clave = puntuadas[0]
        mejor_id = self.candidatos[mejor_clave][0]
        if not _lleva_lo_distintivo(mejor_clave, compacta, self.genericas):
            # "EMPUNADURA DE QUASSUS PRIME" se parecia un 84 % a "Nikana Prime
            # Empunadura" solo por las palabras genericas: sin rastro de "nikana"
            # en lo leido, no es ese objeto. Mejor nada que una etiqueta segura y falsa.
            return nada
        for puntos, otra in puntuadas[1:]:
            if self.candidatos[otra][0] == mejor_id:
                continue
            # Dos objetos que solo se distinguen por un numeral ("MK I" / "MK IV")
            # exigen una lectura casi perfecta; si no, mejor no decir nada.
            solo_numeral = (set(mejor_clave.split()) ^ set(otra.split())) <= NUMERALES
            if mejor_puntos < 97.0 and (mejor_puntos - puntos < self.MARGEN or solo_numeral):
                log.debug("Ambiguo %r: %s (%.0f) frente a %s (%.0f)",
                          texto, mejor_clave, mejor_puntos, otra, puntos)
                return nada
            break
        iid, etiqueta = self.candidatos[mejor_clave]
        return iid, etiqueta, float(mejor_puntos)

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
    """La clave y sus variantes con sinonimos (mango <-> empunadura)."""
    salida = [clave]
    palabras = clave.split()
    for i, p in enumerate(palabras):
        if p in SINONIMOS:
            salida.append(" ".join(palabras[:i] + [SINONIMOS[p]] + palabras[i + 1:]))
    return salida


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
    suma = 0.0
    for p in palabras:
        if len(p) >= 3:
            suma += len(p) * fuzz.partial_ratio(p, compacta) / 100.0
        elif len(p) == 2 and p in compacta:
            # "mk" se puede comprobar; una sola letra ("i") esta en cualquier sitio.
            suma += len(p)
    return 100.0 * suma / sum(len(p) for p in palabras)


def leer_lineas(imagen, motor: MotorOCR, minimo_confianza: float = 0.4) -> list[Leido]:
    """OCR de la imagen con los trozos de cada linea ya unidos."""
    return [l for l in unir_filas(motor.leer(imagen)) if l.confianza >= minimo_confianza]


def reconocer(
    imagen, motor: MotorOCR, casador: Casador, umbral: int = 82, minimo_confianza: float = 0.4
) -> list[Reconocido]:
    """Lee la imagen y devuelve solo los trozos que casan con algo del catalogo."""
    return casar_lineas(leer_lineas(imagen, motor, minimo_confianza), casador, umbral)


def casar_lineas(lineas: list[Leido], casador: Casador, umbral: int = 82) -> list[Reconocido]:
    """Los trozos ya leidos que casan con algo del catalogo.

    Primero se prueba cada bloque de lineas juntas (los nombres largos se partan
    en dos lineas bajo la tarjeta); si el bloque no casa, cada linea por su lado.
    """
    salida = []
    for bloque in agrupar_bloques(lineas):
        if len(bloque) > 1:
            texto = " ".join(l.texto for l in bloque)
            item_id, nombre, puntos = casador.casar(texto, umbral)
            if item_id:
                salida.append(Reconocido(texto, item_id, nombre, puntos, _caja_union(bloque)))
                continue
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
