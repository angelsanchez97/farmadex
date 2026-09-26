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
from dataclasses import dataclass, field

from PySide6.QtCore import Signal, Slot

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
# "AMÉLIORATIONS / ...". El OCR suele pegarlo todo: "UPGRADES/EXCALIBUR[30]".
RE_CABECERA = re.compile(r"(?i)^(?:UPGRADES?|MEJORAS?|AM[EÉ]LIORATIONS?|VERBESSERUNGEN|MELHORIAS)\s*/\s*(.+?)\s*(?:\[\s*\d+\s*\])?\s*$")
# La caja de busqueda separa lo equipado (arriba) de la coleccion (abajo).
RE_BUSCAR = re.compile(r"(?i)^(?:SEARCH|BUSCAR|RECHERCHER|SUCHEN|PESQUISAR)\b")
UMBRAL_MODS = 85
MINIMO_CONFIANZA = 0.5


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


def cabecera(lineas: list[Leido]) -> tuple[str, Leido | None]:
    """El nombre del equipo segun la cabecera ("UPGRADES / EXCALIBUR [30]") y su linea."""
    for linea in lineas:
        m = RE_CABECERA.match(linea.texto.strip())
        if m:
            return m.group(1).strip(), linea
    return "", None


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
    y_buscar = None
    for linea in lineas:
        if RE_BUSCAR.match(linea.texto.strip()):
            y_buscar = linea.y
    if ancho is None:
        ancho = max((l.x + l.ancho for l in lineas), default=1920)
    reconocidas_cajas = {r.caja for r in reconocidos}
    for r in sorted(reconocidos, key=lambda r: (r.caja[1], r.caja[0])):
        categoria = categorias.get(r.item_id, "")
        texto = r.texto_ocr.strip()
        if RE_BUSCAR.match(texto) or RE_CABECERA.match(texto):
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
        if len(re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", texto)) >= 4 and not RE_CABECERA.match(texto):
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
        region = pantalla.region_objetivo()
        imagen = pantalla.capturar(region)
        if imagen is None:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.leida.emit(Build())
            return
        inicio = time.monotonic()
        try:
            build = leer_build(imagen, self.motor, self.casador, self._categorias)
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            self.leida.emit(Build())
            return
        build.milisegundos = int((time.monotonic() - inicio) * 1000)
        log.info("Build leida en %d ms: equipo=%s, %d equipados, %d en coleccion, %d arcanos, %d sin identificar",
                 build.milisegundos, build.equipo.nombre if build.equipo else build.equipo_texto or "?",
                 len(build.equipados), len(build.coleccion), len(build.arcanos), len(build.sin_identificar))
        if build.vacia:
            self.estado.emit(t("No se reconocio nada: abre la pantalla de mejoras del arsenal y vuelve a probar"))
        else:
            self.estado.emit(t("Build leida"))
        self.leida.emit(build)


def leer_build(imagen, motor, casador: Casador, categorias: dict[int, str]) -> Build:
    """OCR de la captura entera (sin reescalar) y reparto en equipo, mods y arcanos."""
    # La confianza se filtra ANTES de unir filas: un garabato de baja confianza pegado a
    # la cabecera ("UPGRADES/EXCALIBUR[30] 美") se la llevaba por delante al unirse.
    lineas = unir_filas([l for l in motor.leer_tira(imagen) if l.confianza >= MINIMO_CONFIANZA])
    reconocidos = casar_lineas(lineas, casador, UMBRAL_MODS)
    equipo = None
    nombre_equipo, linea = cabecera(lineas)
    if nombre_equipo:
        item_id, etiqueta, puntos = casador.casar(nombre_equipo, UMBRAL_MODS)
        if item_id and categorias.get(item_id) not in ("Mods", "Arcanes"):
            equipo = Reconocido(nombre_equipo, item_id, etiqueta, puntos, (linea.x, linea.y, linea.ancho, linea.alto))
    return separar_build(lineas, reconocidos, categorias, equipo, ancho=imagen.shape[1])
