"""Lectura de la pantalla de mejoras del arsenal: que warframe o arma es y que mods lleva.

Se captura la ventana del juego entera, se lee con el OCR sin reescalar (los
nombres de las tarjetas de mod miden ~20 px a 1080p y el reescalado normal del
detector se los come) y cada linea se casa con el catalogo. La cabecera
("MEJORAS / EXCALIBUR [30]") da el equipo; las tarjetas de arriba son los mods
equipados y las de abajo, bajo el buscador, la coleccion.

Solo se ensena lo que casa con seguridad. Lo que se leyo pero no se reconocio
se devuelve aparte, para que el usuario vea que no se ha ignorado.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field

from PySide6.QtCore import Signal, Slot
from rapidfuzz import fuzz

from ..idiomas import t
from ..registro_log import obtener
from . import pantalla
from .ocr import Casador, ErrorMotorOCR, Leido, Reconocido, casar_lineas, unir_filas
from .reliquias import LectorBase

log = obtener("builds")

CATEGORIAS_BUILD = (
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
)

# La cabecera de la pantalla: "UPGRADES / EXCALIBUR [30]", "MEJORAS / EXCALIBUR [30]",
# "AMÉLIORATIONS / ...". El OCR suele pegarlo todo: "UPGRADES/EXCALIBUR[30]", a veces
# con el boton "+" de al lado delante, el rango con una O por cero y el laurel de la
# maestria leido como garabatos detras: "+UPGRADES/EXCALIBUR [3O] 美美". La interfaz
# anterior a 2025 ponia dos puntos: "UPGRADES: UNRANKED HYDROID".
RE_CABECERA = re.compile(
    r"(?i)^\W*(?:UPGRADES?|MEJORAS?|AM[EÉ]LIORATIONS?|VERBESSERUNGEN|MELHORIAS)\s*[/:]\s*(.+?)"
    r"\s*(?:\[\s*[\dOIL|]+\s*\]?)?(?:\s*[^\x00-\u024F]+)*\s*$"
)
# La caja de busqueda separa lo equipado (arriba) de la coleccion (abajo).
RE_BUSCAR = re.compile(r"(?i)^(?:SEARCH|BUSCAR|RECHERCHER|SUCHEN|PESQUISAR)\b")
UMBRAL_MODS = 85
MINIMO_CONFIANZA = 0.5
# El detector (donde hay texto) mira la captura reducida a este alto; el
# reconocedor (que pone) sigue leyendo cada recorte a tamano real. El detector
# cuesta segun los pixeles: a 1440p eran ~320 ms y a 4K ~800 ms solo en buscar.
# No se baja de 1080: medido con capturas reales de la wiki (interfaces viejas con
# letra pequena, la pantalla de artefactos de tektolito), buscar a 810 o 900 perdia
# mods que a 1080 se leen. Una captura de 1440p se busca a 1080, igual que una de
# 1080p (la resolucion con la que esta medido todo lo demas); una de 4K, a 1620.
ALTO_DETECCION = 1080


def alto_de_deteccion(alto: int) -> int | None:
    """A que alto se busca el texto: 1080, sin reducir nunca a menos de tres cuartos.

    1440p se busca a 1080 (0,75). A 4K, reducir a la mitad o a dos tercios perdia
    algun nombre en capturas reales ("Primed Shred", "Primary Acuity"); a 1620
    (tres cuartos, lo mismo que 1440p a 1080) ya no.
    """
    if not ALTO_DETECCION:
        return None
    return max(ALTO_DETECCION, alto * 3 // 4)


@dataclass
class Build:
    """Lo leido en la pantalla de mejoras. Los ids son del indice."""

    equipo: Reconocido | None = None
    equipo_texto: str = ""
    equipados: list[Reconocido] = field(default_factory=list)
    coleccion: list[Reconocido] = field(default_factory=list)
    arcanos: list[Reconocido] = field(default_factory=list)
    sin_identificar: list[str] = field(default_factory=list)
    milisegundos: int = 0
    # Segundos por etapa de la ultima lectura (captura, preparar, detector,
    # reconocedor, casado, reparto) y datos de la imagen, para el registro.
    tiempos: dict = field(default_factory=dict)

    @property
    def vacia(self) -> bool:
        return self.equipo is None and not self.equipados and not self.coleccion and not self.arcanos


def _filtro_build(categoria: str, tipo: str | None, unique_name: str) -> bool:
    """Deja fuera lo que no puede salir en la pantalla de mejoras.

    Las piezas de receta (chasis, canon...) tienen padre y el Casador ya las etiqueta
    con el; aqui no interesan, ni los agrietados genericos ("Rifle Riven Mod").
    """
    if "/Recipes/" in unique_name or "Component" in unique_name:
        return False
    if tipo and "Riven" in tipo:
        return False
    return True


def crear_casador(con) -> Casador:
    return Casador(con, CATEGORIAS_BUILD, filtro=_filtro_build)


# La palabra de la cabecera en cada idioma, para reconocerla aunque el OCR la lea con
# erratas: la letra del juego es muy espaciada y sale "ME JORAS", "MEJ0RAS", "UPGRAOES".
PALABRAS_CABECERA = ("UPGRADES", "MEJORAS", "AMELIORATIONS", "VERBESSERUNGEN", "MELHORIAS")
_CIFRAS_POR_LETRAS = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "|": "I"})


def _arreglar_cabecera(texto: str) -> str:
    """"ME JORAS / HAALVU [22]" -> "MEJORAS/ HAALVU [22]": arregla la palabra de delante de la
    barra si se parece mucho a la de la cabecera en algun idioma; si no, lo deja tal cual."""
    separador = re.search(r"[/:]", texto)
    if separador is None:
        return texto
    delante, detras = texto[:separador.start()], texto[separador.end():]
    compacta = re.sub(r"[^A-Z0-9|]", "", unicodedata.normalize("NFKD", delante).upper().translate(_CIFRAS_POR_LETRAS))
    compacta = compacta.translate(_CIFRAS_POR_LETRAS)
    if not compacta:
        return texto
    for palabra in PALABRAS_CABECERA:
        # Las 3 primeras letras tienen que estar: "MEJORAS" no puede salir de "RAS".
        if compacta[:3] == palabra[:3] and fuzz.ratio(compacta, palabra) >= 80:
            return f"{palabra}/{detras}"
    return texto


def es_cabecera(texto: str):
    """El `re.Match` de la cabecera ("UPGRADES / EXCALIBUR [30]") o None."""
    texto = texto.strip()
    return RE_CABECERA.match(texto) or RE_CABECERA.match(_arreglar_cabecera(texto))


def cabecera(lineas: list[Leido]) -> tuple[str, Leido | None]:
    """El nombre del equipo segun la cabecera ("UPGRADES / EXCALIBUR [30]") y su linea."""
    for linea in lineas:
        m = es_cabecera(linea.texto)
        if m:
            return m.group(1).strip(), linea
    return "", None


# Restos del rango y de las formas pegados detras del nombre: "HAALVU3O", "HAALVU303OI",
# "HAALVU3O 3OI", "HAALVU3013=". Empiezan por una cifra (o un borde de corchete).
RE_RANGO_PEGADO = re.compile(r"(?<=[A-Za-z])(?:\s|[\[\(=|])*\d[\s\dOIl|=\-\]\[)(]*$")
# "UNRANKED HYDROID" (sin rango) delante, "NIDUS RANK 29" detras (interfaz vieja).
RE_SIN_RANGO = re.compile(r"(?i)^(?:UNRANKED|SIN\s*RANGO)\s*|\s*(?:RANK|RANGO)\s*\d+\s*$")


def _nombres_de_equipo(nombre: str) -> list[str]:
    """Lo leido en la cabecera y, detras, lo mismo sin los restos del rango que el OCR
    pega al nombre: "HAALVU I[22]" (una letra suelta), "HAALVU[3O]3" o "HAALV U [2 2 ]"
    (el corchete), "HAALVU3O" (sin corchete). Se prueban en orden."""
    intentos = [nombre]
    limpio = RE_SIN_RANGO.sub("", nombre).strip()
    if limpio and limpio != nombre:
        intentos.append(limpio)
        nombre = limpio
    corte = re.split(r"[\[\(【（]", nombre, maxsplit=1)[0].strip()
    if corte and corte != nombre:
        intentos.append(corte)
    for base in [i for i in intentos if not re.search(r"[\[\(【（]", i)]:
        sin_rango = RE_RANGO_PEGADO.sub("", base).strip()
        if sin_rango and sin_rango not in intentos:
            intentos.append(sin_rango)
    for base in list(intentos):
        palabras = base.split()
        # Solo si la letra suelta puede ser el borde del corchete: "HAALVU I[22]".
        if len(palabras) > 1 and palabras[-1] in ("I", "l", "|", "1"):
            intentos.append(" ".join(palabras[:-1]))
    return intentos


def linea_buscar(lineas: list[Leido], ancho: int) -> Leido | None:
    """La caja de busqueda, que separa lo equipado (arriba) de la coleccion (abajo).

    Va a la izquierda de la pantalla; puede haber otro "BUSCAR" (la ayuda del mando, abajo
    en el centro), y si se tomaba ese toda la coleccion contaba como equipada. Si no hay
    ninguno a la izquierda se usa el ultimo, como antes.
    """
    candidatas = [l for l in lineas if RE_BUSCAR.match(l.texto.strip())]
    izquierda = [l for l in candidatas if l.x < ancho * 0.35]
    if izquierda:
        return min(izquierda, key=lambda l: l.y)
    return candidatas[-1] if candidatas else None


def separar_build(
    lineas: list[Leido],
    reconocidos: list[Reconocido],
    categorias: dict[int, str],
    equipo: Reconocido | None = None,
    ancho: int | None = None,
) -> Build:
    """Reparte lo reconocido en equipo, mods equipados, coleccion y arcanos.

    `categorias` es item_id -> categoria del indice; `equipo` es lo que caso el
    nombre de la cabecera (lo casa `leer_build`, que tiene el casador). Lo que no
    case queda en `sin_identificar` (texto tal cual), sin las lineas de la interfaz.
    """
    build = Build(equipo=equipo)
    build.equipo_texto, linea_cabecera = cabecera(lineas)
    if ancho is None:
        ancho = max((l.x + l.ancho for l in lineas), default=1920)
    buscar = linea_buscar(lineas, ancho)
    y_buscar = buscar.y if buscar is not None else None
    reconocidas_cajas = {r.caja for r in reconocidos}
    for r in sorted(reconocidos, key=lambda r: (r.caja[1], r.caja[0])):
        categoria = categorias.get(r.item_id, "")
        texto = r.texto_ocr.strip()
        if RE_BUSCAR.match(texto) or es_cabecera(texto):
            continue
        # El panel de estadisticas de la izquierda ("Alcance", "Salud"...) no lleva
        # tarjetas: lo que case ahi es una palabra de la interfaz, no un mod.
        en_panel_izquierdo = r.caja[0] < ancho * 0.28 and (y_buscar is None or r.caja[1] < y_buscar)
        if en_panel_izquierdo and (y_buscar is not None or r.caja[1] < (lineas and max(l.y for l in lineas) or 0) * 0.6):
            continue
        if categoria == "Arcanes":
            build.arcanos.append(r)
        elif categoria == "Mods":
            if y_buscar is not None and r.caja[1] > y_buscar:
                build.coleccion.append(r)
            else:
                build.equipados.append(r)
        elif build.equipo is None and linea_cabecera is None:
            # Sin cabecera legible, el primer objeto que no es mod hace de equipo.
            build.equipo = r
    for linea in lineas:
        texto = linea.texto.strip()
        if (linea.x, linea.y, linea.ancho, linea.alto) in reconocidas_cajas:
            continue
        if _es_interfaz(texto):
            continue
        # Solo nombres: dos letras seguidas como minimo y no un numero.
        if len(re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", texto)) >= 4 and not es_cabecera(texto):
            build.sin_identificar.append(texto)
    # Las cajas de los bloques (nombres a dos lineas) no coinciden con las de las lineas:
    # se quitan de "sin identificar" los textos que ya forman parte de algo reconocido.
    reconocidos_texto = " ".join(r.texto_ocr for r in reconocidos).lower()
    build.sin_identificar = [s for s in build.sin_identificar if s.lower() not in reconocidos_texto]
    return build


_PALABRAS_INTERFAZ = {
    "capacity", "capacidad", "config", "health", "salud", "shield", "escudo", "armor", "armadura",
    "energy", "energia", "energía", "sprint", "ability", "habilidad", "duration", "duracion",
    "duración", "efficiency", "eficiencia", "range", "alcance", "strength", "fuerza", "rank",
    "bonuses", "rango", "bonificaciones", "all", "todos", "todo", "drain", "consumo", "search",
    "buscar", "actions", "acciones", "mods", "remove", "quitar", "back", "atras", "atrás",
    "upgrades", "mejoras", "damage", "daño", "dano", "speed", "velocidad", "critical", "critico",
    "crítico", "status", "estado", "chance", "probabilidad", "fire", "rate", "cadencia", "magazine",
    "cargador", "reload", "recarga", "accuracy", "precision", "precisión", "noise", "ruido",
    "trigger", "gatillo", "multishot", "multidisparo", "ammo", "municion", "munición", "total",
    "impact", "impacto", "puncture", "perforacion", "perforación", "slash", "cortante", "polarity",
    "polaridad", "exilus", "aura", "arcane", "arcano", "arcanes", "arcanos", "riven", "agrietado",
    "disposition", "disposicion", "disposición", "sort", "ordenar", "by", "por", "name", "nombre",
}


def _es_interfaz(texto: str) -> bool:
    # Las letras sueltas ("CONFIG A") no cuentan como palabra.
    palabras = [p for p in re.split(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]+", texto.lower()) if len(p) > 1]
    if not palabras:
        return True
    return all(p in _PALABRAS_INTERFAZ for p in palabras)


class LectorBuild(LectorBase):
    """Captura la ventana del juego y devuelve la build reconocida por senal."""

    leida = Signal(object)  # Build

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(motor_ocr, CATEGORIAS_BUILD, parent)
        self._categorias: dict[int, str] = {}

    @Slot()
    def iniciar(self) -> None:
        from ..datos import indice

        self._precalentar()
        if not indice.hay_indice():
            self.casador = None
            return
        con = indice.conectar()
        try:
            self.casador = crear_casador(con)
            marcas = ", ".join("?" for _ in CATEGORIAS_BUILD)
            self._categorias = dict(
                con.execute(f"SELECT id, categoria FROM items WHERE categoria IN ({marcas})", CATEGORIAS_BUILD)
            )
        finally:
            con.close()
        pantalla.declarar_dpi()

    @Slot()
    def leer_ahora(self) -> None:
        if self._ocupado:
            return
        self._ocupado = True
        try:
            self._leer()
        except Exception:  # noqa: BLE001 - nunca un dialogo de error
            log.exception("Fallo inesperado leyendo la build")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            self.leida.emit(Build())
        finally:
            self._ocupado = False

    def _leer(self) -> None:
        if not self._preparado():
            self.leida.emit(Build())
            return
        self.estado.emit(t("Leyendo la pantalla de mejoras..."))
        inicio = time.perf_counter()
        region = pantalla.region_objetivo()
        imagen = pantalla.capturar(region)
        if imagen is None:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.leida.emit(Build())
            return
        capturado = time.perf_counter()
        try:
            build = leer_build(imagen, self.motor, self.casador, self._categorias)
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            self.leida.emit(Build())
            return
        build.tiempos["captura"] = capturado - inicio
        build.milisegundos = int((time.perf_counter() - inicio) * 1000)
        log.info("Build leida en %d ms (%s): equipo=%s, %d equipados, %d en coleccion, %d arcanos, %d sin identificar",
                 build.milisegundos, resumen_etapas(build.tiempos),
                 build.equipo.nombre if build.equipo else build.equipo_texto or "?",
                 len(build.equipados), len(build.coleccion), len(build.arcanos), len(build.sin_identificar))
        if build.vacia:
            self.estado.emit(t("No se reconoció nada: abre la pantalla de mejoras del arsenal y vuelve a probar"))
        else:
            self.estado.emit(t("Build leída"))
        self.leida.emit(build)


def resumen_etapas(tiempos: dict) -> str:
    """"captura 20, preparar 3, detector 60, ... ms; imagen 2560x1440 buscada a 1440x810, 80 cajas"."""
    etapas = [f"{etapa} {tiempos[etapa] * 1000:.0f}" for etapa in
              ("captura", "preparar", "detector", "reconocedor", "casado", "reparto") if etapa in tiempos]
    texto = ", ".join(etapas) + " ms" if etapas else "sin tiempos"
    if tiempos.get("entrada"):
        texto += f"; imagen {tiempos['entrada']}"
        if tiempos.get("deteccion") and tiempos["deteccion"] != tiempos["entrada"]:
            texto += f" buscada a {tiempos['deteccion']}"
    if "cajas" in tiempos:
        texto += f", {tiempos['cajas']} cajas"
    if tiempos.get("motor"):
        texto += f", motor {tiempos['motor']}"
    return texto


def leer_build(imagen, motor, casador: Casador, categorias: dict[int, str]) -> Build:
    """OCR de la captura entera y reparto en equipo, mods y arcanos.

    El texto se busca en la captura reducida (`alto_de_deteccion`) y se lee a tamano
    real (los nombres de las tarjetas miden ~20 px a 1080p). Deja en `build.tiempos`
    lo que costo cada etapa.
    """
    # La confianza se filtra ANTES de unir filas: un garabato de baja confianza pegado a
    # la cabecera ("UPGRADES/EXCALIBUR[30] 美") se la llevaba por delante al unirse.
    lineas = unir_filas([l for l in motor.leer_tira(imagen, alto_deteccion=alto_de_deteccion(imagen.shape[0]))
                         if l.confianza >= MINIMO_CONFIANZA])
    tiempos = dict(getattr(motor, "tiempos", None) or {})
    inicio = time.perf_counter()
    reconocidos = casar_lineas(lineas, casador, UMBRAL_MODS, subbloques=True)
    equipo = None
    nombre_equipo, linea = cabecera(lineas)
    for nombre in _nombres_de_equipo(nombre_equipo) if nombre_equipo else []:
        item_id, etiqueta, puntos = casador.casar(nombre, UMBRAL_MODS)
        if item_id and categorias.get(item_id) not in ("Mods", "Arcanes"):
            equipo = Reconocido(nombre, item_id, etiqueta, puntos, (linea.x, linea.y, linea.ancho, linea.alto))
            break
    casado = time.perf_counter()
    build = separar_build(lineas, reconocidos, categorias, equipo, ancho=imagen.shape[1])
    tiempos["casado"] = casado - inicio
    tiempos["reparto"] = time.perf_counter() - casado
    build.tiempos = tiempos
    return build
