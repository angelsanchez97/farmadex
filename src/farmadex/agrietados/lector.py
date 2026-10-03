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

from ..datos.difuso import fuzz, rf_process

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
# En frances pone "PM 11" (captura real de YouTube, 2025).
RE_MR = re.compile(r"(?i)\b(?:MR|RM|PM|MASTERY|MAESTR[IÍ]A)\D{0,4}(\d{1,3})\b")
RE_MR_SOLO = re.compile(r"(?i)^(?:MR|RM|PM|MASTERY|MAESTR[IÍ]A)\W*$")
# El icono de variar se lee como "0" u "O" y detras van las veces: "011", "O4", "050".
RE_VARIADO = re.compile(r"^[0O]\s?(\d{1,3})$")
RE_SOLO_DIGITOS = re.compile(r"^[\dOo\-–~+\s]+[A-Za-z]?$")

UMBRAL_ATRIBUTO = 78
UMBRAL_ARMA = 80
# Un agrietado pide de maestria 8 a 16.
MAESTRIA_MIN, MAESTRIA_MAX = 8, 16
# Signo explicito al principio de una estadistica releida.
RE_SIGNO = re.compile(r"^\s*([+\-−–—])\s*\d")
# El icono de variar leido como "0", "O", "C", "Q", "G", "@" o "©" delante de la cifra.
AVISO_FUERA_DE_RANGO = "Hay valores que no caben en lo posible para esta arma"
# Ampliaciones con las que se relee una estadistica dudosa, por orden.
ESCALAS_RELECTURA = (2.5, 1.6, 1.0, 0.5, 3.5)
# Ampliaciones del pie (maestria y veces variado): se leen todas y tienen que estar de acuerdo.
ESCALAS_PIE = (3.0, 2.0)
# Con la tarjeta pequena (ampliada para leerla) un "3" y un "8" se confunden: cada valor se
# relee a estas ampliaciones y todas las lecturas tienen que dar lo mismo.
ESCALAS_VERIFICACION = (0.75, 1.6)
RE_VARIADO_AMPLIO = re.compile(r"^[0OoCcQGg@©¢]\s?(\d{1,3})$")


def _maestria_de(cifras: str) -> int | None:
    """La maestria de "MR 12", "MR012" o "MR611": el candado de "MR 🔒 12" se lee a veces como
    una cifra mas ("0", "6", "1"). Un agrietado pide de 8 a 16, asi que no hay duda: si las
    cifras no caben, se prueba sin la primera; si tampoco, no hay maestria."""
    for texto in (cifras, cifras[1:]):
        if texto and texto.isdigit() and MAESTRIA_MIN <= int(texto) <= MAESTRIA_MAX:
            return int(texto)
    return None


def _rango_por_capacidad(capacidad: int) -> int | None:
    """Rango del mod (0-8) por su capacidad: un agrietado gasta 10 + rango, y la mitad (5 a 9)
    si la polaridad del hueco coincide."""
    if 10 <= capacidad <= 18:
        return capacidad - 10
    if 5 <= capacidad <= 9:
        return capacidad * 2 - 10
    return None


TIPOS_VELADO = frozenset({
    "melee", "rifle", "pistol", "shotgun", "kitgun", "zaw", "archgun", "companion", "primary", "secondary",
    "cuerpo a cuerpo", "fusil", "pistola", "escopeta", "arma de archwing", "companero",
})


def _es_tipo_velado(cabecera: list[Leido], pie: list[Leido]) -> bool:
    textos = [normalizar(l.texto) for l in cabecera if not RE_SOLO_DIGITOS.match(l.texto.strip())]
    textos = [t.replace(" riven mod", "").replace(" riven", "").strip() for t in textos if t]
    cero = any(re.search(r"(?i)\b(?:MR|RM|PM)\W*0(?!\d)", l.texto) for l in pie)
    # Sin estadisticas y con solo el tipo de arma por rotulo no puede ser otra cosa; el "MR 0"
    # lo confirma cuando se lee (en una tarjeta pequena a veces ni se ve).
    return bool(textos) and len(textos) == 1 and textos[0] in TIPOS_VELADO and (cero or not pie)


def _solo_rotulo(cabecera: list[Leido], cuerpo: list[Leido]) -> list[Leido]:
    """De lo que hay encima de las estadisticas, el rotulo (arma y nombre, una o dos lineas
    pegadas a la primera estadistica) y las cifras sueltas (la capacidad, arriba del todo).
    Un texto de la interfaz que asoma por encima de la tarjeta ("UPGRADES", "SELECT A MOD TO
    BEGIN FUSION") no es parte del nombre del arma."""
    if not cabecera or not cuerpo:
        return cabecera
    x0 = min(l.x for l in cuerpo) - 2 * cuerpo[0].alto
    x1 = max(l.x + l.ancho for l in cuerpo) + 2 * cuerpo[0].alto
    textos = [l for l in cabecera if not RE_SOLO_DIGITOS.match(l.texto.strip()) and x0 <= l.x + l.ancho / 2 <= x1]
    pegadas: list[Leido] = []
    debajo = cuerpo[0]
    for linea in sorted(textos, key=lambda l: l.y, reverse=True):
        alto = max(linea.alto, debajo.alto)
        if debajo.y - (linea.y + linea.alto) > 1.6 * alto:
            break
        pegadas.append(linea)
        debajo = linea
    if not pegadas:
        return cabecera
    return [l for l in cabecera if l in pegadas or RE_SOLO_DIGITOS.match(l.texto.strip())]


def _misma_fila(linea: Leido, filas: list[Leido]) -> bool:
    for f in filas:
        solape = min(f.y + f.alto, linea.y + linea.alto) - max(f.y, linea.y)
        if solape >= 0.5 * min(f.alto, linea.alto):
            return True
    return False


def _caja_pie_completa(tarjeta: "TarjetaLeida") -> tuple[int, int, int, int] | None:
    """El pie de la tarjeta de borde a borde: la maestria va pegada a la izquierda y el contador
    de variar a la derecha, y el detector suele ver solo uno de los dos (o ninguno). Las
    estadisticas van centradas: dan el eje de la tarjeta y, la mas ancha, casi su anchura."""
    cajas = [e.caja for e in tarjeta.estadisticas if e.caja is not None]
    if not cajas:
        return tarjeta.caja_pie
    alto = max(c[3] for c in cajas)
    x0 = min(c[0] for c in cajas) - alto
    x1 = max(c[0] + c[2] for c in cajas) + alto
    eje = sum(c[0] + c[2] / 2 for c in cajas) / len(cajas)
    pie = tarjeta.caja_pie
    if pie is not None:
        # Lo que se vio del pie y su reflejo al otro lado del eje.
        x0 = min(x0, pie[0] - alto * 0.5, 2 * eje - (pie[0] + pie[2]) - alto * 0.5)
        x1 = max(x1, pie[0] + pie[2] + alto * 0.5, 2 * eje - pie[0] + alto * 0.5)
        y0, h = pie[1] - alto * 0.3, max(pie[3], alto) + alto * 0.6
    else:
        y0 = max(c[1] + c[3] for c in cajas) + alto * 0.4
        h = alto * 2.6
    return (int(x0), int(y0), int(x1 - x0), int(h))


@dataclass
class EstadisticaLeida:
    texto: str  # lo que decia la tarjeta, tal cual (para ensenarlo si no se entiende)
    valor: float | None
    slug: str | None
    negativo: bool
    confianza: float  # 0-1: OCR y casado juntos
    signo_dudoso: bool = False  # el OCR no dio signo y se dedujo de la posicion/pixeles
    caja: tuple[int, int, int, int] | None = None  # x, y, ancho, alto de la linea en la captura
    fuera_de_rango: bool = False  # el valor no cabe en lo posible para esa arma: lectura mal
    antigua: bool = False  # nombre de estadistica que el juego ya no usa: su valor no se compara
    valor_dudoso: bool = False  # dos lecturas dieron cifras distintas: no se sabe cual es

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
    capacidad: int | None = None  # la cifra de arriba a la derecha (10 sin subir, 18 al maximo)
    rango_mod: int | None = None  # 0-8, deducido de la capacidad (los valores crecen con el rango)
    caja_pie: tuple[int, int, int, int] | None = None
    pie_dudoso: bool = False  # dos lecturas del pie dieron cifras distintas: no se da ninguna
    caja_mr: tuple[int, int, int, int] | None = None  # la linea "MR 12" del pie
    caja_capacidad: tuple[int, int, int, int] | None = None

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
    # El nombre en frances, aleman, portugues, italiano y polaco (del indice): con el juego
    # en frances, el "Laser Rifle" de un companero es "Fusil Laser".
    otros_nombres: tuple[str, ...] = ()
    # Para comprobar que cada valor leido cabe en lo posible (grados.rango): la disposicion
    # de warframe.market y la clase de valores base (rifle, shotgun, pistol, archgun, melee).
    disposicion: float | None = None
    clase: str = ""


class LectorTarjeta:
    """Interpreta las lineas leidas de una tarjeta. Se construye con las armas conocidas."""

    def __init__(self, armas: list[ArmaConocida]):
        self.armas = armas
        self._claves: dict[str, ArmaConocida] = {}
        for arma in armas:
            for nombre in (arma.nombre, arma.nombre_en, *arma.otros_nombres):
                clave = normalizar(nombre)
                if clave:
                    self._claves.setdefault(clave, arma)
                    self._claves.setdefault(clave.replace(" ", ""), arma)
        self._lista_claves = list(self._claves)
        self._atributos = grados.nombres_para_casar()
        self._claves_atributo = [c for c, _ in self._atributos]
        self._slug_por_clave = dict(self._atributos)
        self._ultima_clave = ""

    # -- entrada --------------------------------------------------------------------

    def leer(self, lineas: list[Leido], releer=None, contador=None, verificar: bool = False) -> TarjetaLeida:
        """`lineas` ya unidas por filas (ocr.unir_filas), de una sola tarjeta.

        `releer(caja, escala)`, si se da, vuelve a leer con el OCR un trozo de la captura
        ampliado (x, y, ancho, alto en las coordenadas de `lineas`) y devuelve sus lineas;
        se usa para lo dudoso: el pie (maestria y veces variado, que el detector se salta
        a menudo), las estadisticas sin signo, sin entender o con un valor imposible.

        `contador(caja, caja_mr, maestria)`, si se da, mira en la imagen la mitad derecha de la
        fila del pie y devuelve (hay_icono_de_variar, veces | None): separa el icono de las cifras por su
        forma, porque el OCR lo lee a veces como una cifra mas ("↻ 6" -> "56").
        """
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
        separadas = _separar_pie_pegado(orden)
        # Una cifra suelta en la misma fila que "MR"/"MASTERY" es la maestria o las veces
        # variado ("MASTERY" y "12" salen como dos cajas), no una continuacion de la
        # estadistica de arriba.
        filas_pie = [l for l in separadas if self._es_pie(l.texto.strip())]
        for linea in separadas:
            texto = linea.texto.strip()
            if not texto:
                continue
            if self._es_pie(texto) or (RE_SOLO_DIGITOS.match(texto) and _misma_fila(linea, filas_pie)):
                pie.append(linea)
                continue
            if _parece_stat(texto):
                en_stats = True
                cuerpo.append(linea)
            elif en_stats:
                # Continuacion de la estadistica anterior, si va justo debajo: lo que queda
                # lejos (un boton, un medidor de fps) no es de la tarjeta.
                previa = cuerpo[-1]
                if linea.y - (previa.y + previa.alto) <= 1.5 * max(previa.alto, linea.alto):
                    cuerpo.append(linea)
            else:
                cabecera.append(linea)

        if not cuerpo and _es_tipo_velado(cabecera, pie):
            # Sin desvelar: la tarjeta solo dice el tipo ("Melee", "Rifle") y "MR 0".
            tarjeta.velado = True
            tarjeta.avisos.append("Agrietado sin desvelar: no tiene estadisticas que leer.")
            return tarjeta
        self._leer_cabecera(_solo_rotulo(cabecera, cuerpo), tarjeta)
        self._leer_estadisticas(cuerpo, tarjeta)
        self._leer_pie(pie, tarjeta)
        avisos_de_lectura = list(tarjeta.avisos)
        self._comprobar(tarjeta)
        self._validar_capacidad(tarjeta)
        if releer is not None and not tarjeta.velado:
            self._releer_dudoso(tarjeta, releer, contador, avisos_de_lectura)
            if verificar:
                self._verificar_valores(tarjeta, releer, avisos_de_lectura)
        return tarjeta

    # -- relecturas ampliadas ----------------------------------------------------------------

    def _validar_capacidad(self, tarjeta: TarjetaLeida) -> None:
        """La capacidad va arriba a la derecha de la tarjeta. Una cifra suelta lejos de ella
        (un contador de la interfaz, un medidor de fps) no es la capacidad: si se tomara, el
        rango del mod saldria mal y con el lo que se da por posible."""
        caja = tarjeta.caja_capacidad
        cajas = [e.caja for e in tarjeta.estadisticas if e.caja is not None]
        if caja is None or not cajas:
            return
        alto = max(min(c[3] for c in cajas), 1)
        eje = sum(c[0] + c[2] / 2 for c in cajas) / len(cajas)
        medio_ancho = max(c[2] for c in cajas) / 2 + 3 * alto
        arriba = min(c[1] for c in cajas)
        x = caja[0] + caja[2] / 2
        if not (eje - alto < x < eje + medio_ancho and 0 < arriba - caja[1] < 16 * alto):
            tarjeta.capacidad = tarjeta.rango_mod = tarjeta.caja_capacidad = None
            self._comprobar_rangos(tarjeta, rehacer=True)

    def _releer_dudoso(self, tarjeta: TarjetaLeida, releer, contador=None, avisos_de_lectura=()) -> None:
        stats = tarjeta.estadisticas
        cambiado = False
        for e in stats:
            if e.caja is None or not (e.signo_dudoso or e.fuera_de_rango or not e.entendida):
                continue
            # Varias ampliaciones: una tarjeta pequena ampliada lee "+91.3" como "f913" a un
            # tamano y bien a otro. Se para en cuanto la estadistica queda entendida, con signo
            # y dentro de lo posible.
            for escala in ESCALAS_RELECTURA:
                if not (e.signo_dudoso or e.fuera_de_rango or not e.entendida):
                    break
                try:
                    lineas = releer(e.caja, escala)
                except Exception:  # noqa: BLE001 - una relectura que falla no tumba la lectura
                    log.exception("Fallo releyendo una estadistica")
                    continue
                # El recorte lleva margen y a veces asoman las lineas de arriba y de abajo.
                lineas = [l for l in lineas
                          if e.caja[1] - 0.3 * l.alto <= l.y + l.alto / 2 <= e.caja[1] + e.caja[3] + 0.3 * l.alto]
                texto = " ".join(l.texto.strip() for l in sorted(lineas, key=lambda l: (l.y, l.x)) if l.texto.strip())
                if not texto:
                    continue
                nueva = self._interpretar_stat(texto, min([l.confianza for l in lineas] or [0.0]))
                signo = RE_SIGNO.match(texto)
                # Una estadistica ya reconocida no cambia de nombre por releerla: solo el valor.
                if nueva.entendida and (not e.entendida or (e.fuera_de_rango and nueva.slug == e.slug)):
                    # Solo vale si lo nuevo cabe en lo posible: una relectura peor no sustituye.
                    nueva.negativo = e.negativo if nueva.slug == e.slug else nueva.negativo
                    if self._en_rango(tarjeta, nueva) is not False:
                        e.texto, e.valor, e.slug, e.confianza = texto, nueva.valor, nueva.slug, nueva.confianza
                        e.fuera_de_rango = False
                        cambiado = True
                if signo and nueva.slug == e.slug and nueva.valor == e.valor:
                    es_negativo = signo.group(1) != "+"
                    atributo = grados.POR_SLUG.get(e.slug) if e.slug else None
                    if not (atributo and atributo.solo_positivo and es_negativo) and e.signo_dudoso:
                        e.negativo, e.signo_dudoso = es_negativo, False
                        cambiado = True
        if tarjeta.maestria is None or tarjeta.variado is None:
            caja = _caja_pie_completa(tarjeta)
            if caja is not None:
                self._releer_pie(tarjeta, caja, releer, contador)
                cambiado = cambiado or tarjeta.pie_dudoso
        if cambiado:
            # Los avisos de coherencia se rehacen; los de la lectura (arma sin reconocer...) siguen.
            tarjeta.avisos = list(avisos_de_lectura)
            self._comprobar(tarjeta)

    def _verificar_valores(self, tarjeta: TarjetaLeida, releer, avisos_de_lectura=()) -> None:
        """Cada valor releido a otras ampliaciones: si alguna lectura da otra cifra para la misma
        estadistica, el valor queda en duda (nunca se elige uno por mayoria: en una tarjeta
        borrosa la mayoria tambien se equivoca)."""
        cambiado = False
        for e in tarjeta.estadisticas:
            if e.caja is None or not e.entendida:
                continue
            for escala in ESCALAS_VERIFICACION:
                try:
                    lineas = releer(e.caja, escala)
                except Exception:  # noqa: BLE001
                    log.exception("Fallo verificando una estadistica")
                    continue
                lineas = [l for l in lineas
                          if e.caja[1] - 0.3 * l.alto <= l.y + l.alto / 2 <= e.caja[1] + e.caja[3] + 0.3 * l.alto]
                texto = " ".join(l.texto.strip() for l in sorted(lineas, key=lambda l: (l.y, l.x)) if l.texto.strip())
                if not texto:
                    continue
                otra = self._interpretar_stat(texto, 1.0)
                if otra.valor is not None and (otra.slug == e.slug or otra.slug is None) and abs(otra.valor - e.valor) > 0.05:
                    e.valor_dudoso = True
                    cambiado = True
                    break
        if cambiado:
            tarjeta.avisos = list(avisos_de_lectura)
            self._comprobar(tarjeta)

    def _releer_pie(self, tarjeta: TarjetaLeida, caja, releer, contador=None) -> None:
        """El pie entero (de borde a borde de la tarjeta) releido a varias ampliaciones. Un dato
        solo se da por bueno si ninguna de las lecturas dice otra cosa: el icono de variar se
        lee a veces como una cifra, y una maestria o un contador equivocados cambian el precio."""
        maestrias: set[int] = set()
        con_icono: set[int] = set()   # "03", "O3", "C3": el icono leido como letra redonda
        sin_icono: set[int] = set()   # una cifra suelta a la derecha: puede llevar el icono dentro
        caja_mr = tarjeta.caja_mr
        for escala in ESCALAS_PIE:
            try:
                lineas = releer(caja, escala)
            except Exception:  # noqa: BLE001
                log.exception("Fallo releyendo el pie de la tarjeta")
                continue
            lineas = [l for l in lineas if caja[1] - 0.3 * l.alto <= l.y + l.alto / 2 <= caja[1] + caja[3] + 0.3 * l.alto]
            maestria, prefijado, suelto, caja_leida = self._interpretar_pie_ampliado(lineas, caja)
            if maestria is not None:
                maestrias.add(maestria)
            if prefijado is not None:
                con_icono.add(prefijado)
            if suelto is not None:
                sin_icono.add(suelto)
            caja_mr = caja_mr or caja_leida
        if tarjeta.maestria is None:
            if len(maestrias) == 1:
                tarjeta.maestria = maestrias.pop()
            elif maestrias:
                tarjeta.pie_dudoso = True
        if tarjeta.variado is not None:
            return
        hay_icono, contado = False, None
        eje = caja[0] + caja[2] / 2
        # En las tarjetas antiguas "MASTERY 🔒 11" va centrado y no hay contador a la derecha.
        if contador is not None and caja_mr is not None and caja_mr[0] + caja_mr[2] / 2 < eje - caja_mr[3]:
            x0 = int(max(eje, caja_mr[0] + caja_mr[2] + caja_mr[3] * 0.5))
            x1 = int(2 * eje - caja_mr[0] + caja_mr[3] * 0.9)
            try:
                hay_icono, contado = contador((x0, caja_mr[1], x1 - x0, caja_mr[3]), caja_mr, tarjeta.maestria)
            except Exception:  # noqa: BLE001
                log.exception("Fallo mirando el contador de variar")
        coherente = lambda n, v: v == n or (str(v).endswith(str(n)) and len(str(v)) == len(str(n)) + 1)  # noqa: E731
        if contado is not None:
            if all(v == contado for v in con_icono) and all(coherente(contado, v) for v in sin_icono):
                tarjeta.variado = contado
            else:
                tarjeta.pie_dudoso = True
        elif con_icono:
            if len(con_icono) == 1 and all(coherente(next(iter(con_icono)), v) for v in sin_icono):
                tarjeta.variado = next(iter(con_icono))
            else:
                tarjeta.pie_dudoso = True
        elif sin_icono:
            # Solo una cifra suelta: sin poder mirar la imagen se acepta si todas las lecturas
            # dicen lo mismo; pudiendo mirarla y sin haber visto el icono, no.
            if contador is None and len(sin_icono) == 1:
                tarjeta.variado = next(iter(sin_icono))
            else:
                tarjeta.pie_dudoso = True
        elif hay_icono:
            tarjeta.pie_dudoso = True

    def _interpretar_pie_ampliado(self, lineas: list[Leido], caja):
        """Del pie ampliado: "MR 12" (o "MR" y "12" sueltos) a la izquierda y "↻ 3" (leido como
        "03", "O3", "C3", "Q3"...) a la derecha. Devuelve (maestria, veces variado leidas con
        el icono delante, veces variado leidas como cifra suelta, caja de la linea "MR")."""
        centro = caja[0] + caja[2] / 2
        derecha = caja[0] + caja[2] * 0.62  # el contador de variar va pegado al borde derecho
        maestria = prefijado = suelto = caja_mr = None
        sueltas: list[tuple[float, float, int]] = []
        fin_mr = alto_mr = None
        for l in sorted(lineas, key=lambda l: l.x):
            texto = l.texto.strip()
            m = RE_MR.search(texto)
            if m:
                if maestria is None:
                    maestria = _maestria_de(m.group(1))
                    caja_mr = (l.x, l.y, l.ancho, l.alto)
                resto = texto[m.end():].replace(" ", "")
                # Todo el pie en una sola caja: "MR 12 03".
                m2 = RE_VARIADO_AMPLIO.match(resto)
                if m2 and prefijado is None and l.x + l.ancho > derecha:
                    prefijado = int(m2.group(1))
                    caja_mr = None  # la caja abarca todo el pie: no sirve para situar el contador
                continue
            if RE_MR_SOLO.match(texto):
                fin_mr, alto_mr = l.x + l.ancho, l.alto
                continue
            compacto = texto.replace(" ", "")
            m = RE_VARIADO_AMPLIO.match(compacto)
            if m and l.x + l.ancho / 2 > centro:
                if prefijado is None:
                    prefijado = int(m.group(1))
                continue
            if re.fullmatch(r"\d{1,3}", compacto):
                sueltas.append((l.x, l.x + l.ancho / 2, int(compacto)))
        for x, x_medio, n in sueltas:
            # "MR" (con el candado en medio) y su cifra en otra caja: la cifra que va justo
            # detras del "MR" es la maestria, este donde este ("MASTERY 🔒 11" va centrado).
            if fin_mr is not None and -alto_mr <= x - fin_mr < 2.5 * alto_mr:
                if maestria is None and MAESTRIA_MIN <= n <= MAESTRIA_MAX:
                    maestria = n
            elif x_medio > derecha and suelto is None:
                suelto = n
        if maestria is not None and not MAESTRIA_MIN <= maestria <= MAESTRIA_MAX:
            maestria = None
        return maestria, prefijado, suelto, caja_mr

    # -- cabecera: arma y nombre -------------------------------------------------------

    def _leer_cabecera(self, lineas: list[Leido], tarjeta: TarjetaLeida) -> None:
        textos = []
        for linea in lineas:
            texto = linea.texto.strip()
            # La primera linea suele ser la capacidad y la polaridad: "18-", "10Y", "9h".
            if RE_SOLO_DIGITOS.match(texto) or texto.upper() in ("ABOUT", "ACERCA DE"):
                if tarjeta.capacidad is None:
                    m = re.match(r"\s*(\d{1,2})", texto)
                    if m:
                        tarjeta.capacidad, tarjeta.rango_mod = int(m.group(1)), _rango_por_capacidad(int(m.group(1)))
                        tarjeta.caja_capacidad = (linea.x, linea.y, linea.ancho, linea.alto)
                continue
            textos.append(texto)
        if not textos:
            tarjeta.avisos.append("No se leyo el nombre del arma.")
            return
        junto = " ".join(textos)
        arma, nombre, puntos = self._separar_arma_y_nombre(junto)
        tarjeta.arma_texto = arma
        # El nombre es una sola palabra con guion; al partirse en dos lineas el OCR deja
        # "Hexa- critasus" o, si se come el guion, "Sci plecidra".
        nombre = re.sub(r"\s*-\s*", "-", nombre.strip())
        nombre = re.sub(r"\s+", "-", nombre)
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
            for corte in range(2, len(palabra) - (1 if i < len(palabras) - 1 else 3)):
                cabeza = " ".join(palabras[:i] + [palabra[:corte]])
                cola = " ".join([palabra[corte:]] + palabras[i + 1:])
                candidatos.append((cabeza, cola))
        for cabeza, cola in candidatos:
            # El guion es del nombre del agrietado ("Acri-visicron"): el arma nunca va pegada a el.
            if cola.lstrip().startswith(("-", "–")) or cabeza.rstrip().endswith(("-", "–")):
                continue
            if grados.descomponer_nombre(cola) is None:
                continue
            arma = self._casar_arma(cabeza)
            puntos = self._parecido_arma(cabeza) if arma else 0.0
            if arma and (mejor is None or puntos > mejor[0]):
                mejor = (puntos, cabeza, cola)
        if mejor is not None:
            return mejor[1], mejor[2], mejor[0]
        # Solo el nombre del agrietado, sin arma (tapada o fuera del recorte): se da el nombre
        # y el arma queda sin leer, nunca un arma parecida a un trozo del nombre.
        if len(palabras) == 1 and grados.descomponer_nombre(texto) and not self._casar_arma(texto):
            return "", texto, 0.0
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
            stat = self._interpretar_stat(texto, confianza_ocr)
            x0, y0 = min(l.x for l in grupo), min(l.y for l in grupo)
            x1, y1 = max(l.x + l.ancho for l in grupo), max(l.y + l.alto for l in grupo)
            stat.caja = (x0, y0, x1 - x0, y1 - y0)
            tarjeta.estadisticas.append(stat)

    def _interpretar_stat(self, texto: str, confianza_ocr: float) -> EstadisticaLeida:
        multiplicador = RE_MULTIPLICADOR.match(texto)
        if multiplicador:
            return self._interpretar_multiplicador(texto, multiplicador, confianza_ocr)
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
        # "+132.T%": el decimal no se leyo. Dar 132 seria inventar: se relee o se dice.
        decimal_perdido = bool(re.match(r"^[.,]\s*[^\d\s%]", resto)) and "." not in valor_txt
        negativo = signo in ("-", "−", "–", "—")
        signo_dudoso = signo in ("", "f", "t")
        slug, puntos = self._casar_atributo(resto)
        if decimal_perdido:
            return EstadisticaLeida(texto, None, slug, negativo, confianza_ocr * 0.5, signo_dudoso)
        if slug is None:
            return EstadisticaLeida(texto, valor, None, negativo, confianza_ocr * 0.5, signo_dudoso)
        atributo = grados.POR_SLUG[slug]
        if slug in grados.SIGNO_AL_REVES and signo in ("+", "-", "−", "–", "—"):
            negativo = signo == "+"
        if atributo.solo_positivo and negativo:
            # Frio, calor, electricidad, toxina y atravesar nunca son negativos: el "-" es
            # un guion de la tarjeta o una mancha, no un signo.
            negativo = False
            signo_dudoso = True
        estadistica = EstadisticaLeida(texto, valor, slug, negativo, confianza_ocr * (puntos / 100.0), signo_dudoso)
        estadistica.antigua = self._ultima_clave in grados.NOMBRES_ANTIGUOS
        return estadistica

    def _interpretar_multiplicador(self, texto: str, m: re.Match, confianza_ocr: float) -> EstadisticaLeida:
        """"x1,4 points de Dégâts aux Infestés" (tarjeta real en frances, 2025): el dano a
        una faccion va como multiplicador. x1.4 es +40 % y x0.53, -47 %."""
        cifra = m.group("valor").replace(",", ".").translate(str.maketrans("lIiO", "1110"))
        try:
            factor = float(cifra)
        except ValueError:
            return EstadisticaLeida(texto, None, None, False, 0.0)
        porcentaje = round((factor - 1) * 100, 1)
        resto = RE_PUNTOS_DE.sub("", m.group("resto") or "")
        slug, puntos = self._casar_atributo(resto)
        if slug is None or not slug.startswith("damage_vs_"):
            # Solo el dano a facciones va asi: otra cosa es una mala lectura.
            return EstadisticaLeida(texto, abs(porcentaje), None, porcentaje < 0, confianza_ocr * 0.5)
        return EstadisticaLeida(texto, abs(porcentaje), slug, porcentaje < 0, confianza_ocr * (puntos / 100.0))

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
        self._ultima_clave = ""
        for variante in variantes:
            compacta = variante.replace(" ", "")
            for candidata in self._claves_atributo:
                puntos = max(
                    fuzz.ratio(compacta, candidata.replace(" ", "")),
                    fuzz.token_set_ratio(variante, candidata) - 6,  # "damage to" cabe en "damage to grineer"
                )
                if puntos > mejor_puntos:
                    mejor_slug, mejor_puntos = self._slug_por_clave[candidata], puntos
                    self._ultima_clave = candidata
        if mejor_puntos < UMBRAL_ATRIBUTO:
            return None, mejor_puntos
        if self._empata_con_otra(variantes, mejor_slug, mejor_puntos):
            # "Channeling" a secas cabe igual en "Channeling Damage" y en "Channeling
            # Efficiency": con dos estadisticas igual de parecidas, no se elige ninguna.
            return None, mejor_puntos
        return mejor_slug, mejor_puntos

    def _empata_con_otra(self, variantes, slug, puntos) -> bool:
        for variante in variantes:
            compacta = variante.replace(" ", "")
            for candidata in self._claves_atributo:
                if self._slug_por_clave[candidata] == slug:
                    continue
                otro = max(fuzz.ratio(compacta, candidata.replace(" ", "")), fuzz.token_set_ratio(variante, candidata) - 6)
                if otro >= puntos - 0.5:
                    return True
        return False

    # -- pie: maestria y veces variado ---------------------------------------------------

    @staticmethod
    def _es_pie(texto: str) -> bool:
        return bool(RE_MR.search(texto) or RE_MR_SOLO.match(texto) or RE_VARIADO.match(texto.replace(" ", "")))

    def _leer_pie(self, lineas: list[Leido], tarjeta: TarjetaLeida) -> None:
        if lineas:
            x0, y0 = min(l.x for l in lineas), min(l.y for l in lineas)
            x1, y1 = max(l.x + l.ancho for l in lineas), max(l.y + l.alto for l in lineas)
            tarjeta.caja_pie = (x0, y0, x1 - x0, y1 - y0)
        sueltas: list[Leido] = []
        for linea in lineas:
            texto = linea.texto.strip()
            if tarjeta.caja_mr is None and RE_MR.search(texto) and not RE_VARIADO_AMPLIO.search(texto.split()[-1]):
                tarjeta.caja_mr = (linea.x, linea.y, linea.ancho, linea.alto)
            m = RE_MR.search(texto)
            if m:
                tarjeta.maestria = _maestria_de(m.group(1))
                continue
            m = RE_VARIADO.match(texto.replace(" ", ""))
            if m and tarjeta.variado is None:
                tarjeta.variado = int(m.group(1))
                continue
            if RE_SOLO_DIGITOS.match(texto) and re.fullmatch(r"\d{1,3}", texto.replace(" ", "")):
                sueltas.append(linea)
        # "MASTERY" / "MR" sin cifra y la cifra en otra caja de la misma fila: la primera a la
        # derecha es la maestria; las de mas a la derecha, las veces variado.
        con_mr = [l for l in lineas if RE_MR_SOLO.match(l.texto.strip())]
        for suelta in sorted(sueltas, key=lambda l: l.x):
            n = int(suelta.texto.replace(" ", ""))
            if con_mr and tarjeta.maestria is None and suelta.x > con_mr[0].x and MAESTRIA_MIN <= n <= MAESTRIA_MAX:
                tarjeta.maestria = n
        if tarjeta.maestria is not None and not MAESTRIA_MIN <= tarjeta.maestria <= MAESTRIA_MAX:
            tarjeta.avisos.append(f"La maestria leida ({tarjeta.maestria}) no es posible: un agrietado va de {MAESTRIA_MIN} a {MAESTRIA_MAX}.")
            tarjeta.maestria = None

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
            # Deducido del nombre, que tambien lo lee el OCR (un prefijo mal leido cambia
            # la cuenta): se marca, pero sigue en duda salvo con cuatro estadisticas, que
            # siempre llevan negativo.
            stats[-1].signo_dudoso = len(stats) != 4
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
        inseguros = [e for e in stats if e.valor_dudoso]
        if inseguros:
            tarjeta.avisos.append("No se leyo seguro el valor de: " + "; ".join(f'"{e.texto}"' for e in inseguros)
                                  + ". Revisalo en la tarjeta.")
        if tarjeta.pie_dudoso:
            tarjeta.avisos.append("No se leyo bien la maestria o las veces que se ha variado: revisalas.")
        self._comprobar_rangos(tarjeta)

    def _en_rango(self, tarjeta: TarjetaLeida, e: EstadisticaLeida) -> bool | None:
        """Si el valor de `e` cabe en lo posible para el arma de la tarjeta; None si no se sabe."""
        arma = self._claves.get(normalizar(tarjeta.arma_nombre)) if tarjeta.arma_nombre else None
        if arma is None or arma.disposicion is None or not arma.clase or not e.entendida or e.antigua:
            return None
        stats = [s for s in tarjeta.estadisticas if s.entendida]
        positivos = sum(1 for s in stats if not s.negativo)
        negativos = sum(1 for s in stats if s.negativo)
        tramo = grados.rango(e.slug, arma.clase, arma.disposicion, positivos, negativos, e.negativo)
        if tramo is None:
            return None
        minimo, maximo = sorted((abs(tramo[0]), abs(tramo[1])))
        if tarjeta.rango_mod is not None:
            factor = (tarjeta.rango_mod + 1) / 9.0
            minimo, maximo = minimo * factor, maximo * factor
        else:
            minimo = minimo / 9.0
        return minimo * 0.7 <= abs(e.valor) <= maximo * 1.4

    def _comprobar_rangos(self, tarjeta: TarjetaLeida, rehacer: bool = False) -> None:
        """Cada valor tiene que caber en lo posible para esa arma: un "913 %" por "91.3 %" (el
        OCR perdio el punto) o un "12.5" leido "125" son datos inventados si se dan por buenos.

        El rango sale de grados.rango (base de la clase x disposicion x multiplicador por numero
        de positivos y negativos, con el azar de +-10 %) y crece con el rango del mod: a rango 0
        los valores son 1/9 de los de rango 8. La disposicion cambia con los parches y la
        tarjeta puede ser vieja: se deja un margen ancho (-30 % / +40 %), que basta para cazar
        los decimales perdidos (x10) sin tirar lecturas buenas.
        """
        if rehacer:
            tarjeta.avisos = [a for a in tarjeta.avisos if not a.startswith(AVISO_FUERA_DE_RANGO)]
        fuera = []
        for e in tarjeta.estadisticas:
            e.fuera_de_rango = self._en_rango(tarjeta, e) is False
            if e.fuera_de_rango:
                fuera.append(e)
        if fuera:
            tarjeta.avisos.append(AVISO_FUERA_DE_RANGO + " (lectura mal o arma cambiada): "
                                  + "; ".join(f'"{e.texto}"' for e in fuera))


def _separar_pie_pegado(lineas: list[Leido]) -> list[Leido]:
    """"+7.9%StatusChance MASTERY8" son dos lineas que el OCR junto: se separan."""
    salida = []
    for linea in _separar_stats_pegadas(lineas):
        texto = linea.texto.strip()
        m = RE_MR.search(texto)
        if m and m.start() > 0 and _parece_stat(texto[: m.start()]):
            salida.append(Leido(texto[: m.start()].strip(), linea.x, linea.y, linea.ancho, linea.alto, linea.confianza))
            salida.append(Leido(texto[m.start():].strip(), linea.x, linea.y + 1, linea.ancho, linea.alto, linea.confianza))
            continue
        salida.append(linea)
    return salida


# Una segunda estadistica pegada detras de otra en la misma linea: "+115.6%Krit.Chance
# +37.4.% Nachladegeschwindigk" (tarjeta real en aleman; las palabras largas parten la
# linea y el OCR junta las dos). Ninguna estadistica lleva dentro " +37.4 %".
RE_OTRA_STAT = re.compile(r"\s+(?=[+\-−–]\s?\d{1,3}(?:[.,]\d{1,2})?\.?\s*%|[xX×]\s?[\dlI][.,]\d)")
# El dano a una faccion como multiplicador: "x1,4 points de Degats aux Infestes", "x0,53...";
# el OCR lee a veces el 1 como "l".
RE_MULTIPLICADOR = re.compile(r"^\s*[xX×]\s?(?P<valor>[\dlIiO][.,]\d{1,2})\s*(?P<resto>.*)$")
RE_PUNTOS_DE = re.compile(r"(?i)^\s*points?\s*de\s*")


def _separar_stats_pegadas(lineas: list[Leido]) -> list[Leido]:
    salida = []
    for linea in lineas:
        # "37.4.%": un punto colado delante del "%".
        trozos = [re.sub(r"(?<=\d)\.(?=\s*%)", "", t) for t in RE_OTRA_STAT.split(linea.texto.strip()) if t]
        # El nombre de la segunda puede seguir en la linea de abajo ("+37.4 %" / "Nachlade...").
        if len(trozos) > 1 and all(_parece_stat(t) for t in trozos):
            for i, trozo in enumerate(trozos):
                salida.append(Leido(trozo, linea.x, linea.y + i, linea.ancho, linea.alto, linea.confianza))
            continue
        if len(trozos) == 1 and trozos[0] != linea.texto.strip():
            linea = Leido(trozos[0], linea.x, linea.y, linea.ancho, linea.alto, linea.confianza)
        salida.append(linea)
    return salida


def _parece_stat(texto: str) -> bool:
    multiplicador = RE_MULTIPLICADOR.match(texto)
    if multiplicador:
        return bool(re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", multiplicador.group("resto") or ""))
    m = RE_STAT.match(texto)
    if not m:
        return False
    resto = m.group("resto") or ""
    # Un numero solo ("18", "011") no es una estadistica: hace falta texto detras. Sin signo
    # ni unidad, unas pocas letras ("18VME": la capacidad y un trozo de la interfaz) tampoco.
    if not m.group("signo") and not m.group("unidad") and len(re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", resto)) < 5:
        return False
    return bool(re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", resto)) or bool(m.group("unidad") in ("%", "96"))


def parsear_texto(lineas_texto: list[str], lector: LectorTarjeta) -> TarjetaLeida:
    """Atajo para pruebas y para pegar texto a mano: cada linea en su fila."""
    leidos = [Leido(texto, 0, i * 20, 200, 16, 0.9) for i, texto in enumerate(lineas_texto)]
    return lector.leer(leidos)
