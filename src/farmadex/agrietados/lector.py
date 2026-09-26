"""Lectura de la tarjeta de un agrietado a partir de lo que devuelve el OCR.

La tarjeta lleva, de arriba abajo: la capacidad y la polaridad (se ignoran), el
nombre del arma y el nombre del agrietado (en una o dos lineas, a veces pegados),
dos a cuatro estadisticas ("+116% Perforacion", "-32.5% Dano a Infestados", que
pueden partirse en dos lineas), y abajo el rango de maestria ("MR 8") y las
veces que se ha variado ("↻ 11", que el OCR lee como "011").

Nada de aqui decide por si solo: cada trozo lleva una confianza y lo que no cuadra
se marca como dudoso para que la interfaz lo ensene con el aviso, no como un dato.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process as rf_process

from ..captura.ocr import Leido
from ..datos.items import normalizar
from ..registro_log import obtener
from . import grados

log = obtener("agrietados.lector")

# "+116%Puncture", "-2.4 Magazine", "+2.7PunchThrough", "+8.1s Combo Duration".
# El OCR se come el signo a veces (queda "32.5%Damageto") y lee "%" como "96" o "9".
RE_STAT = re.compile(
    r"^\s*(?P<signo>[+\-−–—]|f|t)?\s*(?P<valor>(?:\d{1,3}|[Oo](?=[.,]))(?:[.,]\d{1,2})?)\s*(?P<unidad>%|96|9|s|m)?\s*(?P<resto>.*)$"
)
# "MR 8", "MR=13", "MASTERY 9", "MASTERY品9", "RM 8", "MAESTRIA 12".
RE_MR = re.compile(r"(?i)\b(?:MR|RM|MASTERY|MAESTR[IÍ]A)\D{0,4}(\d{1,2})\b")
RE_MR_SOLO = re.compile(r"(?i)^(?:MR|RM|MASTERY|MAESTR[IÍ]A)\W*$")
# El icono de variar se lee como "0" u "O" y detras van las veces: "011", "O4", "050".
RE_VARIADO = re.compile(r"^[0O]\s?(\d{1,3})$")
RE_SOLO_DIGITOS = re.compile(r"^[\dOo\-–~+\s]+[A-Za-z]?$")

UMBRAL_ATRIBUTO = 78
UMBRAL_ARMA = 80


@dataclass
class EstadisticaLeida:
    texto: str  # lo que decia la tarjeta, tal cual (para ensenarlo si no se entiende)
    valor: float | None
    slug: str | None
    negativo: bool
    confianza: float  # 0-1: OCR y casado juntos
    signo_dudoso: bool = False  # el OCR no dio signo y se dedujo de la posicion/pixeles

    @property
    def entendida(self) -> bool:
        return self.valor is not None and self.slug is not None


@dataclass
class TarjetaLeida:
    arma_texto: str = ""
    arma_slug: str | None = None
    arma_nombre: str = ""
    nombre: str = ""  # "Hexa-scidra"
    nombre_slugs: list[str] | None = None  # lo que el nombre dice que lleva
    estadisticas: list[EstadisticaLeida] = field(default_factory=list)
    maestria: int | None = None
    variado: int | None = None
    velado: bool = False
    avisos: list[str] = field(default_factory=list)

    @property
    def fiable(self) -> bool:
        """Todo entendido y sin contradicciones: se puede evaluar sin que el usuario lo repase."""
        if self.velado or not self.arma_slug or not self.estadisticas:
            return False
        if not all(e.entendida for e in self.estadisticas):
            return False
        return not self.avisos


@dataclass
class ArmaConocida:
    slug: str
    nombre: str  # como lo escribe el juego (en ingles o espanol)
    nombre_en: str


class LectorTarjeta:
    """Interpreta las lineas leidas de una tarjeta. Se construye con las armas conocidas."""

    def __init__(self, armas: list[ArmaConocida]):
        self.armas = armas
        self._claves: dict[str, ArmaConocida] = {}
        for arma in armas:
            for nombre in (arma.nombre, arma.nombre_en):
                clave = normalizar(nombre)
                if clave:
                    self._claves.setdefault(clave, arma)
                    self._claves.setdefault(clave.replace(" ", ""), arma)
        self._lista_claves = list(self._claves)
        self._atributos = grados.nombres_para_casar()
        self._claves_atributo = [c for c, _ in self._atributos]
        self._slug_por_clave = dict(self._atributos)

    # -- entrada --------------------------------------------------------------------

    def leer(self, lineas: list[Leido]) -> TarjetaLeida:
        """`lineas` ya unidas por filas (ocr.unir_filas), de una sola tarjeta."""
        tarjeta = TarjetaLeida()
        orden = sorted(lineas, key=lambda l: (l.y, l.x))
        if any("veiled" in l.texto.lower() or "velado" in l.texto.lower() or "???" in l.texto for l in orden):
            tarjeta.velado = True
            tarjeta.avisos.append("La tarjeta esta velada: no hay estadisticas que leer.")
            return tarjeta

        cabecera: list[Leido] = []
        cuerpo: list[Leido] = []
        pie: list[Leido] = []
        en_stats = False
        for linea in _separar_pie_pegado(orden):
            texto = linea.texto.strip()
            if not texto:
                continue
            if self._es_pie(texto):
                pie.append(linea)
                continue
            if _parece_stat(texto):
                en_stats = True
                cuerpo.append(linea)
            elif en_stats:
                cuerpo.append(linea)  # continuacion de la estadistica anterior
            else:
                cabecera.append(linea)

        self._leer_cabecera(cabecera, tarjeta)
        self._leer_estadisticas(cuerpo, tarjeta)
        self._leer_pie(pie, tarjeta)
        self._comprobar(tarjeta)
        return tarjeta

    # -- cabecera: arma y nombre -------------------------------------------------------

    def _leer_cabecera(self, lineas: list[Leido], tarjeta: TarjetaLeida) -> None:
        textos = []
        for linea in lineas:
            texto = linea.texto.strip()
            # La primera linea suele ser la capacidad y la polaridad: "18-", "10Y", "9h".
            if RE_SOLO_DIGITOS.match(texto) or texto.upper() in ("ABOUT", "ACERCA DE"):
                continue
            textos.append(texto)
        if not textos:
            tarjeta.avisos.append("No se leyo el nombre del arma.")
            return
        junto = " ".join(textos)
        arma, nombre, puntos = self._separar_arma_y_nombre(junto)
        tarjeta.arma_texto = arma
        tarjeta.nombre = nombre
        tarjeta.nombre_slugs = grados.descomponer_nombre(nombre) if nombre else None
        if arma:
            casada = self._casar_arma(arma)
            if casada is not None:
                tarjeta.arma_slug, tarjeta.arma_nombre = casada.slug, casada.nombre
            else:
                tarjeta.avisos.append(f"No se reconoce el arma: \"{arma}\".")
        else:
            tarjeta.avisos.append("No se leyo el nombre del arma.")

    def _separar_arma_y_nombre(self, texto: str) -> tuple[str, str, float]:
        """"Aklex Lexi-insiata" -> ("Aklex", "Lexi-insiata"). Tambien pegado: "SomaHexa-visisus".

        Se prueba cada corte posible: la cola tiene que descomponerse en prefijos y
        sufijo de estadisticas, y la cabeza parecerse a un arma. Si ningun corte vale,
        todo el texto se toma por arma y el nombre queda vacio.
        """
        palabras = texto.split()
        mejor: tuple[float, str, str] | None = None
        # Cortes por palabra (lo normal) y, dentro de la ultima palabra, por letra
        # (cuando el OCR pego el arma al nombre).
        candidatos: list[tuple[str, str]] = []
        for i in range(1, len(palabras)):
            candidatos.append((" ".join(palabras[:i]), " ".join(palabras[i:])))
        for i, palabra in enumerate(palabras):
            for corte in range(2, len(palabra) - 3):
                cabeza = " ".join(palabras[:i] + [palabra[:corte]])
                cola = " ".join([palabra[corte:]] + palabras[i + 1:])
                candidatos.append((cabeza, cola))
        for cabeza, cola in candidatos:
            if grados.descomponer_nombre(cola) is None:
                continue
            arma = self._casar_arma(cabeza)
            puntos = self._parecido_arma(cabeza) if arma else 0.0
            if arma and (mejor is None or puntos > mejor[0]):
                mejor = (puntos, cabeza, cola)
        if mejor is not None:
            return mejor[1], mejor[2], mejor[0]
        # Sin nombre reconocible: quiza el OCR lo perdio. El arma es lo que mas se parezca.
        return texto, "", 0.0

    def _parecido_arma(self, texto: str) -> float:
        clave = normalizar(texto)
        if not clave:
            return 0.0
        if clave in self._claves or clave.replace(" ", "") in self._claves:
            return 100.0
        mejor = rf_process.extractOne(clave, self._lista_claves, scorer=fuzz.ratio)
        return float(mejor[1]) if mejor else 0.0

    def _casar_arma(self, texto: str) -> ArmaConocida | None:
        clave = normalizar(texto)
        if not clave:
            return None
        exacta = self._claves.get(clave) or self._claves.get(clave.replace(" ", ""))
        if exacta:
            return exacta
        compacta = clave.replace(" ", "")
        parecidas = rf_process.extract(compacta, self._lista_claves, scorer=fuzz.ratio, limit=3, score_cutoff=UMBRAL_ARMA)
        if not parecidas:
            return None
        mejor = parecidas[0]
        # Dos armas distintas casi igual de parecidas ("Boar" / "Bo"): no se decide.
        otras = [p for p in parecidas[1:] if self._claves[p[0]].slug != self._claves[mejor[0]].slug]
        if otras and mejor[1] - otras[0][1] < 8 and mejor[1] < 97:
            return None
        return self._claves[mejor[0]]

    # -- estadisticas ------------------------------------------------------------------

    def _leer_estadisticas(self, lineas: list[Leido], tarjeta: TarjetaLeida) -> None:
        grupos: list[list[Leido]] = []
        for linea in lineas:
            if _parece_stat(linea.texto) or not grupos:
                grupos.append([linea])
            else:
                grupos[-1].append(linea)
        for grupo in grupos:
            texto = " ".join(l.texto.strip() for l in grupo)
            confianza_ocr = min(l.confianza for l in grupo)
            tarjeta.estadisticas.append(self._interpretar_stat(texto, confianza_ocr))

    def _interpretar_stat(self, texto: str, confianza_ocr: float) -> EstadisticaLeida:
        m = RE_STAT.match(texto)
        if not m:
            return EstadisticaLeida(texto, None, None, False, 0.0)
        signo = m.group("signo") or ""
        valor_txt = m.group("valor").replace(",", ".").replace("O", "0").replace("o", "0")
        unidad = m.group("unidad") or ""
        resto = m.group("resto") or ""
        # El juego nunca ensena dos decimales: "+123.79CriticalChance" es "+123.7%" con el
        # "%" leido como "9", y "+35.79%" un 9 colado.
        if "." in valor_txt and len(valor_txt.split(".")[1]) == 2:
            valor_txt = valor_txt[:-1]
        # "+117.7966Heat": "%" leido como "96" tras el valor con dos decimales.
        if unidad in ("96", "9"):
            unidad = "%"
        try:
            valor = float(valor_txt)
        except ValueError:
            return EstadisticaLeida(texto, None, None, False, 0.0)
        negativo = signo in ("-", "−", "–", "—")
        signo_dudoso = signo in ("", "f", "t")
        slug, puntos = self._casar_atributo(resto)
        if slug is None:
            return EstadisticaLeida(texto, valor, None, negativo, confianza_ocr * 0.5, signo_dudoso)
        atributo = grados.POR_SLUG[slug]
        if atributo.solo_positivo and negativo:
            # Frio, calor, electricidad, toxina y atravesar nunca son negativos: el "-" es
            # un guion de la tarjeta o una mancha, no un signo.
            negativo = False
            signo_dudoso = True
        return EstadisticaLeida(texto, valor, slug, negativo, confianza_ocr * (puntos / 100.0), signo_dudoso)

    def _casar_atributo(self, texto: str) -> tuple[str | None, float]:
        # Fuera los iconos de elemento que el OCR convierte en letras sueltas ("*Cold",
        # "WHeat", "yPuncture", "Cslash") y los "0" que en realidad son "o" ("Zo0m").
        limpio = re.sub(r"^[^A-Za-zÁÉÍÓÚÑáéíóúñ]+", "", texto.strip())
        limpio = re.sub(r"(?<=[A-Za-z])0+(?=[A-Za-z])", lambda m: "o" * len(m.group()), limpio)
        limpio = re.sub(r"[()\[\]]", " ", limpio)
        clave = normalizar(limpio)
        if not clave:
            return None, 0.0
        # Los iconos leidos como una letra pegada al nombre ("Wheat", "Cslash", "yPuncture").
        variantes = [clave]
        if len(clave) > 4:
            variantes.append(clave[1:])
        mejor_slug, mejor_puntos = None, 0.0
        for variante in variantes:
            compacta = variante.replace(" ", "")
            for candidata in self._claves_atributo:
                puntos = max(
                    fuzz.ratio(compacta, candidata.replace(" ", "")),
                    fuzz.token_set_ratio(variante, candidata) - 6,  # "damage to" cabe en "damage to grineer"
                )
                if puntos > mejor_puntos:
                    mejor_slug, mejor_puntos = self._slug_por_clave[candidata], puntos
        if mejor_puntos < UMBRAL_ATRIBUTO:
            return None, mejor_puntos
        return mejor_slug, mejor_puntos

    # -- pie: maestria y veces variado ---------------------------------------------------

    @staticmethod
    def _es_pie(texto: str) -> bool:
        return bool(RE_MR.search(texto) or RE_MR_SOLO.match(texto) or RE_VARIADO.match(texto.replace(" ", "")))

    def _leer_pie(self, lineas: list[Leido], tarjeta: TarjetaLeida) -> None:
        for linea in lineas:
            texto = linea.texto.strip()
            m = RE_MR.search(texto)
            if m:
                tarjeta.maestria = int(m.group(1))
                continue
            m = RE_VARIADO.match(texto.replace(" ", ""))
            if m and tarjeta.variado is None:
                tarjeta.variado = int(m.group(1))

    # -- coherencia --------------------------------------------------------------------

    def _comprobar(self, tarjeta: TarjetaLeida) -> None:
        stats = tarjeta.estadisticas
        if not stats:
            tarjeta.avisos.append("No se leyo ninguna estadistica.")
            return
        if len(stats) < 2 or len(stats) > 4:
            tarjeta.avisos.append(f"Se leyeron {len(stats)} estadisticas y un agrietado lleva de 2 a 4.")
        # Ninguna estadistica pasa de +500 % (el tope real ronda el 460 % de dano en pistola):
        # un valor mayor es un decimal perdido ("+91.3%" leido como "913%").
        disparatadas = [e for e in stats if e.valor is not None and abs(e.valor) > 500]
        if disparatadas:
            tarjeta.avisos.append("Hay valores imposibles (mas de 500 %): " + "; ".join(f'"{e.texto}"' for e in disparatadas))
        no_entendidas = [e for e in stats if not e.entendida]
        if no_entendidas:
            tarjeta.avisos.append("Hay estadisticas sin identificar: " + "; ".join(f'"{e.texto}"' for e in no_entendidas))
        negativos = [e for e in stats if e.negativo]
        if len(negativos) > 1:
            tarjeta.avisos.append("Se leyeron dos negativos y un agrietado solo puede llevar uno.")
        if negativos and stats[-1] is not negativos[0]:
            tarjeta.avisos.append("El negativo no es la ultima estadistica, que es donde lo pone el juego.")
        # El OCR se come el signo "-" con facilidad. Dos cosas lo recuperan sin adivinar:
        # el nombre del agrietado solo lleva las estadisticas positivas (una por prefijo o
        # sufijo), asi que si hay una mas que letras en el nombre, la ultima es la negativa;
        # y con cuatro estadisticas siempre hay negativo, porque el maximo son tres positivas.
        del_nombre = list(tarjeta.nombre_slugs or [])
        if del_nombre and len(stats) == len(del_nombre) + 1 and stats[-1].entendida and not negativos:
            stats[-1].negativo = True
            stats[-1].signo_dudoso = False
            negativos = [stats[-1]]
            for e in stats[:-1]:
                if e.slug in del_nombre:
                    e.negativo = False
                    e.signo_dudoso = False
        elif del_nombre and len(stats) == len(del_nombre):
            for e in stats:
                if e.signo_dudoso:
                    e.negativo = False
                    e.signo_dudoso = False
        elif len(stats) == 4 and not negativos and stats[-1].entendida:
            stats[-1].negativo = True
            stats[-1].signo_dudoso = False
            negativos = [stats[-1]]
        # El nombre dice que positivas lleva; si no cuadran, algo se leyo mal.
        if del_nombre:
            positivas = {e.slug for e in stats if e.slug and not e.negativo}
            faltan = set(del_nombre) - positivas
            if faltan and positivas:
                tarjeta.avisos.append(
                    "El nombre del agrietado no cuadra con las estadisticas leidas ("
                    + ", ".join(grados.POR_SLUG[x].nombre_es for x in sorted(faltan)) + ")."
                )
        dudosos = [e for e in stats if e.signo_dudoso and e.entendida]
        if dudosos:
            tarjeta.avisos.append("No se vio bien el signo de alguna estadistica: revisa cual es la negativa.")


def _separar_pie_pegado(lineas: list[Leido]) -> list[Leido]:
    """"+7.9%StatusChance MASTERY8" son dos lineas que el OCR junto: se separan."""
    salida = []
    for linea in lineas:
        texto = linea.texto.strip()
        m = RE_MR.search(texto)
        if m and m.start() > 0 and _parece_stat(texto[: m.start()]):
            salida.append(Leido(texto[: m.start()].strip(), linea.x, linea.y, linea.ancho, linea.alto, linea.confianza))
            salida.append(Leido(texto[m.start():].strip(), linea.x, linea.y + 1, linea.ancho, linea.alto, linea.confianza))
            continue
        salida.append(linea)
    return salida


def _parece_stat(texto: str) -> bool:
    m = RE_STAT.match(texto)
    if not m:
        return False
    resto = m.group("resto") or ""
    # Un numero solo ("18", "011") no es una estadistica: hace falta texto detras.
    return bool(re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", resto)) or bool(m.group("unidad") in ("%", "96"))


def parsear_texto(lineas_texto: list[str], lector: LectorTarjeta) -> TarjetaLeida:
    """Atajo para pruebas y para pegar texto a mano: cada linea en su fila."""
    leidos = [Leido(texto, 0, i * 20, 200, 16, 0.9) for i, texto in enumerate(lineas_texto)]
    return lector.leer(leidos)
