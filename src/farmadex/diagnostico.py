"""Diagnostico de la lectura de reliquias y el informe para pedir ayuda.

Existe porque "no me sale nada al abrir una reliquia" tiene una docena de causas
distintas (EE.log en otra ruta, pantalla completa exclusiva, motor OCR que no
carga, lectura automatica apagada, datos sin descargar...) y quien lo sufre no
suele saber mandar el registro. Aqui se recogen todas las comprobaciones en una
lista corta con un veredicto claro por linea, y se empaqueta en un .zip en el
Escritorio con el registro de Farmadex para enviarlo tal cual.

Lo que NUNCA entra en el informe: EE.log ni ninguna de sus lineas (lleva el
correo, la IP y el id de jugador). Solo se dice si existe, cuanto mide y cuando
se leyo por ultima vez.
"""

from __future__ import annotations

import ctypes
import os
import platform
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import NOMBRE_APP, VERSION
from .config import DIR_BASE, RUTA_CONFIG
from .idiomas import t
from .registro_log import RUTA_ERRORES_REGISTRO, RUTA_LOG, obtener

log = obtener("diagnostico")

# Veredictos de cada linea. "dato" es informativo (ni bien ni mal).
OK, MAL, AVISO, DATO = "ok", "mal", "aviso", "dato"
_MARCAS = {OK: "[OK]", MAL: "[MAL]", AVISO: "[AVISO]", DATO: "[i]"}

# Nombres de fichero que jamas se meten en el informe, se llamen como se llamen
# las carpetas: el registro del juego lleva datos personales.
FICHEROS_PROHIBIDOS = ("ee.log",)


@dataclass
class Linea:
    estado: str  # OK, MAL, AVISO o DATO
    texto: str

    @property
    def marca(self) -> str:
        return _MARCAS.get(self.estado, "[i]")


@dataclass
class Diagnostico:
    lineas: list[Linea] = field(default_factory=list)

    def anadir(self, estado: str, texto: str) -> None:
        self.lineas.append(Linea(estado, texto))

    @property
    def problemas(self) -> list[Linea]:
        return [l for l in self.lineas if l.estado == MAL]

    def texto(self) -> str:
        """Texto plano, una linea por comprobacion, para el informe y el portapapeles."""
        return "\n".join(f"{l.marca} {l.texto}" for l in self.lineas)

    def html(self, colores: dict[str, str]) -> str:
        """Para la etiqueta de Ajustes: cada linea con el color de su veredicto."""
        from html import escape

        trozos = []
        for l in self.lineas:
            color = colores.get(l.estado, colores.get(DATO, "#999"))
            trozos.append(f'<span style="color:{color}">{escape(l.marca)}</span> {escape(l.texto)}')
        return "<br>".join(trozos)


def _hace(epoch: float | None, ahora: float | None = None) -> str:
    """'hace 3 min', 'hace 2 h', 'hace 4 dias'; vacio si no hay fecha."""
    if epoch is None:
        return ""
    segundos = max(0, (ahora or time.time()) - epoch)
    if segundos < 90:
        return t("hace {n} s", n=int(segundos))
    if segundos < 3600 * 1.5:
        return t("hace {n} min", n=int(segundos // 60))
    if segundos < 86400 * 1.5:
        return t("hace {n} h", n=int(segundos // 3600))
    return t("hace {n} dias", n=int(segundos // 86400))


def recoger(
    *,
    eelog=None,
    ruta_eelog_configurada: str = "",
    ruta_eelog_por_defecto: str = "",
    modo_pantalla: str = "desconocido",
    juego=None,
    escala: float = 1.0,
    monitores: int = 1,
    monitor_juego=None,
    motor_fallo: str | None = None,
    motor_cargado: bool | None = None,
    motor_nombre: str = "rapidocr",
    config: dict | None = None,
    datos_listos: bool = False,
    hay_indice: bool = False,
    ultima_pantalla: float | None = None,
    ultima_lectura: tuple[float, int] | None = None,
    ultima_pintada: tuple[float, int] | None = None,
    idioma: str = "es",
    ahora: float | None = None,
) -> Diagnostico:
    """Convierte lo que la ventana sabe en una lista de veredictos.

    `eelog` es un `EstadoEELog` (o None si la vigilancia no ha arrancado);
    `juego`/`monitor_juego` son `pantalla.Region`; `ultima_lectura` y
    `ultima_pintada` son (epoch, cuantas recompensas).
    """
    config = config or {}
    ahora = ahora or time.time()
    d = Diagnostico()
    d.anadir(DATO, t("{app} {version} en Windows {windows}", app=NOMBRE_APP, version=VERSION,
                     windows=platform.version() or "?"))

    # 1. Datos e indice: sin ellos ni siquiera arranca la vigilancia.
    if datos_listos:
        d.anadir(OK, t("Datos del juego preparados"))
    elif hay_indice:
        d.anadir(AVISO, t("Los datos del juego aun se estan comprobando; la lectura de reliquias "
                          "arranca cuando terminen"))
    else:
        d.anadir(MAL, t("No hay datos del juego descargados: sin ellos no se lee ninguna reliquia. "
                        "Comprueba la conexion a internet y pulsa 'Reconstruir el indice'"))

    # 2. EE.log: que exista, que se lea y que haya dado senales de vida.
    if eelog is None:
        d.anadir(MAL, t("La vigilancia de EE.log no ha arrancado (los datos no estan listos)"))
    elif not eelog.existe:
        texto = t("No se encuentra EE.log en {ruta}. Warframe lo crea al arrancar; si el juego "
                  "esta abierto y sigue sin aparecer, es que escribe en otra carpeta",
                  ruta=eelog.ruta)
        if ruta_eelog_por_defecto and eelog.ruta != ruta_eelog_por_defecto:
            texto += " " + t("(la ruta de siempre es {ruta})", ruta=ruta_eelog_por_defecto)
        d.anadir(MAL, texto)
    elif eelog.error:
        d.anadir(MAL, t("EE.log existe pero no se puede leer: {error}", error=eelog.error))
    else:
        d.anadir(OK, t("EE.log encontrado en {ruta} ({kb} KB)", ruta=eelog.ruta, kb=eelog.tamano // 1024))
        if ruta_eelog_configurada and eelog.ruta != ruta_eelog_configurada:
            d.anadir(AVISO, t("La ruta configurada ({ruta}) no existia; se usa la de siempre",
                              ruta=ruta_eelog_configurada))
        if eelog.ultima_lectura is not None:
            d.anadir(OK, t("Leyendose: {n} lineas nuevas desde que se abrio {app}, la ultima {hace}",
                           n=eelog.lineas, app=NOMBRE_APP, hace=_hace(eelog.ultima_lectura, ahora)))
        elif eelog.modificado is not None and ahora - eelog.modificado > 5 * 60:
            d.anadir(AVISO, t("El juego no ha escrito nada en EE.log desde {hace}: parece que "
                              "Warframe no esta abierto", hace=_hace(eelog.modificado, ahora)))
        else:
            d.anadir(DATO, t("Todavia no ha llegado ninguna linea nueva de EE.log"))
        if eelog.ultimo_evento:
            d.anadir(OK, t("Ultimo aviso del juego: {evento}, {hace}", evento=eelog.ultimo_evento,
                           hace=_hace(eelog.ultimo_evento_en, ahora)))
        else:
            d.anadir(DATO, t("Ningun aviso de reliquia visto todavia en esta sesion"))

    # 3. Ultima pantalla de recompensas y que se hizo con ella.
    if ultima_pantalla is None:
        d.anadir(DATO, t("Ninguna pantalla de recompensas vista en esta sesion"))
    else:
        d.anadir(OK, t("Ultima pantalla de recompensas: {hace}", hace=_hace(ultima_pantalla, ahora)))
        if ultima_lectura is None or ultima_lectura[0] < ultima_pantalla - 1:
            d.anadir(MAL, t("De esa pantalla no se leyo nada (el lector no llego a mirarla)"))
        elif ultima_lectura[1] == 0:
            d.anadir(MAL, t("Se miro la pantalla pero no se reconocio ninguna recompensa"))
        else:
            d.anadir(OK, t("Se leyeron {n} recompensas", n=ultima_lectura[1]))
        if ultima_lectura and ultima_lectura[1] and (
            ultima_pintada is None or ultima_pintada[0] < ultima_pantalla - 1
        ):
            d.anadir(MAL, t("Se leyeron pero no se pintaron encima del juego (mira el modo de pantalla)"))

    # 4. Lectura automatica y estilo.
    if config.get("ocr_reliquias_auto", True):
        d.anadir(OK, t("Lectura automatica al abrir una reliquia: activada"))
    else:
        d.anadir(MAL, t("Lectura automatica al abrir una reliquia: DESACTIVADA (solo con el atajo {atajo})",
                        atajo=config.get("hotkey_reliquias", "")))
    if (config.get("estilo_recompensas") or "etiquetas") == "panel":
        estilo = t("panel con una tarjeta por recompensa")
    else:
        estilo = t("etiquetas pequenas junto a cada tarjeta")
    d.anadir(DATO, t("Estilo de recompensas: {estilo}", estilo=estilo))

    # 5. Ventana del juego, modo de pantalla, monitores y escala.
    if juego is None:
        d.anadir(AVISO, t("No se ve la ventana de Warframe: o no esta abierto, o esta minimizado"))
    else:
        d.anadir(OK, t("Ventana de Warframe: {ancho}x{alto} en ({x}, {y})",
                       ancho=juego.ancho, alto=juego.alto, x=juego.x, y=juego.y))
    if modo_pantalla == "exclusivo":
        d.anadir(MAL, t("Warframe esta en pantalla completa exclusiva: ninguna ventana puede dibujarse "
                        "encima del juego. En el juego: Opciones > Pantalla > Modo de pantalla = "
                        "'Ventana sin bordes'"))
    elif modo_pantalla == "desconocido":
        d.anadir(DATO, t("Modo de pantalla: sin determinar (Warframe no esta abierto)"))
    else:
        modo = t("ventana") if modo_pantalla == "ventana" else t("ventana sin bordes")
        d.anadir(OK, t("Modo de pantalla: {modo}", modo=modo))
    if monitores > 1:
        donde = ""
        if monitor_juego is not None:
            donde = t(" (el juego esta en el monitor de {ancho}x{alto} en ({x}, {y}))",
                      ancho=monitor_juego.ancho, alto=monitor_juego.alto, x=monitor_juego.x, y=monitor_juego.y)
        d.anadir(DATO, t("{n} monitores", n=monitores) + donde)
    if abs(escala - 1.0) > 0.01:
        d.anadir(DATO, t("Escala de Windows: {pct}%", pct=round(escala * 100)))

    # 6. Motor OCR.
    if motor_fallo:
        d.anadir(MAL, t("El lector de pantalla ({motor}) no carga: {error}. Prueba el otro motor en "
                        "Ajustes o reinstala {app}", motor=motor_nombre, error=motor_fallo, app=NOMBRE_APP))
    elif motor_cargado:
        d.anadir(OK, t("Lector de pantalla ({motor}) cargado", motor=motor_nombre))
    elif motor_cargado is None:
        d.anadir(AVISO, t("Lector de pantalla ({motor}) sin arrancar todavia", motor=motor_nombre))
    else:
        d.anadir(AVISO, t("Lector de pantalla ({motor}) sin cargar todavia (se carga con la primera lectura)",
                          motor=motor_nombre))

    d.anadir(DATO, t("Idioma de {app}: {idioma}", app=NOMBRE_APP, idioma=idioma))
    return d


# --- informe -----------------------------------------------------------------------


def carpeta_escritorio() -> Path:
    """El Escritorio del usuario (por Windows, que sabe si esta en OneDrive); si no, la carpeta de datos."""
    try:
        import uuid

        if os.name == "nt":
            escritorio = uuid.UUID("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")
            buf = ctypes.c_wchar_p()
            guid = (ctypes.c_ubyte * 16).from_buffer_copy(escritorio.bytes_le)
            if ctypes.windll.shell32.SHGetKnownFolderPath(guid, 0, None, ctypes.byref(buf)) == 0:
                ruta = Path(buf.value)
                ctypes.windll.ole32.CoTaskMemFree(buf)
                if ruta.is_dir():
                    return ruta
    except (AttributeError, OSError, ValueError):
        pass
    candidata = Path.home() / "Desktop"
    return candidata if candidata.is_dir() else DIR_BASE


def ficheros_del_informe() -> list[Path]:
    """Lo que va dentro: registro de Farmadex (con sus rotaciones), fallos del registro y config."""
    ficheros = [RUTA_LOG] + [RUTA_LOG.with_name(f"{RUTA_LOG.name}.{i}") for i in (1, 2, 3)]
    ficheros += [RUTA_ERRORES_REGISTRO, RUTA_CONFIG]
    return [f for f in ficheros if f.is_file() and f.name.lower() not in FICHEROS_PROHIBIDOS]


def guardar_informe(diagnostico: Diagnostico | str, destino: Path | None = None) -> Path:
    """Escribe `Farmadex-diagnostico-<fecha>.zip` en `destino` (el Escritorio) y devuelve la ruta.

    Dentro: `diagnostico.txt` y los ficheros de `ficheros_del_informe`. EE.log
    no entra nunca, ni aunque alguien lo hubiera copiado a la carpeta de logs.
    """
    destino = Path(destino) if destino else carpeta_escritorio()
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / f"{NOMBRE_APP}-diagnostico-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    texto = diagnostico if isinstance(diagnostico, str) else diagnostico.texto()
    cabecera = (
        f"{NOMBRE_APP} {VERSION} - diagnostico de reliquias - {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"(no contiene EE.log ni ninguna linea suya)\n\n"
    )
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as zip_:
        zip_.writestr("diagnostico.txt", cabecera + texto + "\n")
        for fichero in ficheros_del_informe():
            if fichero.name.lower() in FICHEROS_PROHIBIDOS:  # doble cinturon
                continue
            try:
                zip_.write(fichero, fichero.name)
            except OSError as e:
                log.warning("No se pudo meter %s en el informe: %s", fichero, e)
    log.info("Informe de diagnostico guardado en %s", ruta)
    return ruta


def revelar(ruta: Path) -> None:
    """Abre el Explorador con el .zip seleccionado, para arrastrarlo al chat sin buscarlo."""
    try:
        if os.name == "nt":
            import subprocess

            subprocess.Popen(["explorer", "/select,", str(ruta)])  # noqa: S603,S607 - es la intencion
    except OSError as e:  # pragma: no cover - sin explorador no pasa nada; la ruta ya se ensena
        log.debug("No se pudo abrir el Explorador: %s", e)
