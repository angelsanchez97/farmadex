"""Vigilancia de EE.log, el registro que el propio juego escribe.

Solo se miran las lineas que interesan y solo se guarda el evento reconocido:
el fichero contiene datos personales (correo, IP, nombre de cuenta) y nada de
eso se copia, se ensena ni sale del equipo.

Marcadores comprobados contra un EE.log real (Warframe, septiembre de 2026):

    Script [Info]: ProjectionRewardChoice.lua: Relic rewards initialized
    Script [Info]: ProjectionRewardChoice.lua: Got rewards
    Script [Info]: ProjectionRewardChoice.lua: Selection countdown done
    Script [Info]: ProjectionRewardChoice.lua: Relic reward screen shut down
    Script [Info]: EndOfMatch.lua: Mission Succeeded

Importante: el juego NO escribe en el log que objeto te has llevado, asi que de
aqui no se puede deducir el progreso de un objetivo. Solo sirve para saber
CUANDO mirar la pantalla; lo que hay en ella lo lee el OCR.

Pistas (`VigilanteEELog.pista`), tambien comprobadas contra un EE.log real:

    Dialog.lua: Dialog::CreateOkCancel(description=¿Seguro que quieres equipar
        Reliquia Lith K5 [PERFECTA] para esta mision? ...       -> ("reliquia", "Lith K5")
    Dialog.lua: ...¿Refinar Reliquia Lith S18 a RADIANTE? ...   -> ("reliquia", "Lith S18")
    VoidProjections: <id> gets reward /Lotus/StoreItems/Types/Recipes/Weapons/
        WeaponParts/AkboltoPrimeBarrel                          -> ("recompensa", "/Lotus/Types/...")

La reliquia equipada se sabe unos 3 minutos antes de abrirse (lo que dura la
mision), y sirve para pedir los precios de sus recompensas con tiempo. Las
lineas "gets reward" salen en el mismo instante que "Got rewards", solo para
algunos jugadores de la escuadra (no siempre el propio), y dan el objeto exacto
sin esperar al OCR. El texto del dialogo esta en el idioma del juego, pero el
nombre de la reliquia ("Lith K5") no se traduce. El id de jugador no se copia.

Pantallas del menu (`VigilanteEELog.pantalla`), comprobadas contra un EE.log real
(septiembre de 2026) solo para el arsenal; las demas son nombres CANDIDATOS que
se confirman cuando el usuario abra esas pantallas con Farmadex vigilando (cada
nombre nuevo se anota una vez en el log de Farmadex, sin datos personales):

    Script [Info]: LoadOutRedux.lua: Background::ScreenOpened(screenName=LoadOut)
    Script [Info]: ThemedSquadOverlay.lua: Background::OpenScreen(screenName=InvitePanel, ...)
    Script [Info]: LoadOutRedux.lua: Background::GoToPreviousScreen(skipScreens=1)
    Input [Info]: Subscribing for /Lotus/Interface/LoadOutRedux.swf with input filter ...
    Sys [Info]: Executing command: /EE/Editor/ToolMenus/Commands/CmdShowPauseMenu

`ScreenOpened`/`OpenScreen` dan el nombre logico de la pantalla; `Subscribing for`
sale cada vez que un panel .swf toma el teclado (tambien al volver a el). Con el
nombre se sabe si merece la pena mirar la pantalla por OCR (perfil, inventario,
fundicion) o no (arsenal, menu de pausa, dialogos).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..registro_log import obtener

log = obtener("eelog")

EVENTOS = {
    "ProjectionRewardChoice.lua: Relic rewards initialized": "reliquia_abierta",
    "ProjectionRewardChoice.lua: Got rewards": "reliquia_recompensas",
    "ProjectionRewardChoice.lua: Selection countdown done": "reliquia_elegida",
    "ProjectionRewardChoice.lua: Relic reward screen shut down": "reliquia_cerrada",
    "EndOfMatch.lua: Mission Succeeded": "mision_completada",
}

# El script de la pantalla de reliquias: si un parche cambia sus mensajes, las
# lineas nuevas se anotan en el log (una vez cada una) para poder actualizar EVENTOS.
SCRIPT_RELIQUIAS = "ProjectionRewardChoice.lua:"
_mensajes_desconocidos: set[str] = set()

# Cabecera del fichero, tal y como la escribe el juego al arrancar:
#   Sys [Diag]: Process Command-line: -windowMode:2 -graphicsDriver:dx12 ...
#   Sys [Diag]: Build Label: 2026.08.19.11.06 Retail Windows x64 [Stripped]
RE_BUILD = re.compile(r"Build Label:\s*(\S+)")
RE_MODO_VENTANA = re.compile(r"-windowMode:(\d+)")
RE_FECHA_BUILD = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})")
BYTES_CABECERA = 32_768


@dataclass
class Cabecera:
    """Lo que interesa de las primeras lineas de EE.log."""

    build: str = ""  # "2026.08.19.11.06"
    modo_ventana: int | None = None  # el -windowMode con el que arranco el juego

    @property
    def fecha_build(self) -> date | None:
        """La fecha que lleva dentro la etiqueta de build; None si cambia de formato."""
        m = RE_FECHA_BUILD.match(self.build)
        if not m:
            return None
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None


def analizar_cabecera(texto: str) -> Cabecera:
    cabecera = Cabecera()
    m = RE_BUILD.search(texto)
    if m:
        cabecera.build = m.group(1)
    m = RE_MODO_VENTANA.search(texto)
    if m:
        cabecera.modo_ventana = int(m.group(1))
    return cabecera


def leer_cabecera(ruta: Path) -> Cabecera:
    """Lee solo el principio del fichero; lo demas (correo, IP...) no se toca."""
    try:
        with Path(ruta).open("rb") as f:
            texto = f.read(BYTES_CABECERA).decode("utf-8", errors="replace")
    except OSError as e:
        log.warning("No se pudo leer la cabecera de EE.log: %s", e)
        return Cabecera()
    cabecera = analizar_cabecera(texto)
    if not cabecera.build:
        log.warning("EE.log no trae 'Build Label' donde se esperaba: version del juego desconocida")
    return cabecera


def clasificar(linea: str) -> str | None:
    """Devuelve el nombre del evento, o None si la linea no interesa."""
    for marcador, evento in EVENTOS.items():
        if marcador in linea:
            return evento
    if SCRIPT_RELIQUIAS in linea:
        mensaje = linea.split(SCRIPT_RELIQUIAS, 1)[1].strip()[:80]
        if mensaje and mensaje not in _mensajes_desconocidos:
            _mensajes_desconocidos.add(mensaje)
            log.info("Mensaje nuevo de la pantalla de reliquias (sin evento asociado): %r", mensaje)
    return None


# Nombre de reliquia dentro de un dialogo del juego (equipar, refinar). Solo en
# lineas de Dialog.lua: en el chat o en nombres de jugador podria salir cualquier cosa.
SCRIPT_DIALOGO = "Dialog.lua:"
RE_RELIQUIA = re.compile(r"\b(Lith|Meso|Neo|Axi|Requiem) ([A-Z]\d{1,2})\b")
# Recompensa que le ha tocado a un jugador de la escuadra, con la ruta del objeto.
RE_RECOMPENSA = re.compile(r"VoidProjections: [0-9a-f]+ gets reward (/Lotus/\S+)")
# El juego nombra las recompensas como articulo de tienda; el indice, como objeto.
PREFIJO_TIENDA = "/Lotus/StoreItems/"


def pista(linea: str) -> tuple[str, str] | None:
    """("reliquia", "Lith K5") o ("recompensa", unique_name); None si la linea no trae nada."""
    if SCRIPT_DIALOGO in linea:
        m = RE_RELIQUIA.search(linea)
        return ("reliquia", f"{m.group(1)} {m.group(2)}") if m else None
    m = RE_RECOMPENSA.search(linea)
    if m:
        ruta = m.group(1)
        if ruta.startswith(PREFIJO_TIENDA):
            ruta = "/Lotus/" + ruta[len(PREFIJO_TIENDA):]
        return ("recompensa", ruta)
    m = RE_REMOTOS.search(linea)
    if m:
        return ("remotos", m.group(1))
    return None


# Al cargar una mision, Progress.lua dice cuantos jugadores remotos hay (0 = en
# solitario). Visto en un EE.log real; la linea vecina con el nombre de cada
# jugador remoto no se lee.
RE_REMOTOS = re.compile(r"Progress\.lua: Num remote players (\d+)")


# --- pantallas del menu -----------------------------------------------------------

RE_PANTALLA = re.compile(r"Background::(?:OpenScreen|ScreenOpened)\(screenName=(\w+)")
RE_INTERFAZ = re.compile(r"Subscribing for /Lotus/Interface/(\w+)\.swf")
MARCADORES_CIERRE = ("Background::GoToPreviousScreen(", "Background::CloseScreen(")
MARCADOR_PAUSA = "CmdShowPauseMenu"

# Nombre en el log -> pantalla interna. Solo "arsenal" esta visto en un log real;
# el resto son candidatos razonables que se confirman al abrir la pantalla.
PANTALLAS = {
    "LoadOut": "arsenal", "LoadOutRedux": "arsenal", "ArsenalRedux": "arsenal",
    "Profile": "perfil", "ProfileRedux": "perfil", "PlayerProfile": "perfil",
    "ProfileMenu": "perfil", "ProfileScreen": "perfil",
    "Inventory": "inventario", "InventoryRedux": "inventario", "InventoryScreen": "inventario",
    "Foundry": "fundicion", "FoundryRedux": "fundicion", "FoundryScreen": "fundicion",
    "Codex": "codex", "CodexRedux": "codex",
    "InvitePanel": "escuadra", "ChatRedux": "chat", "Dialog": "dialogo",
    "TopMenu": "menu", "ThemedMainMenu": "menu", "Progress": "carga",
}
# Pantallas donde puede haber algo que leer por OCR.
PANTALLAS_LEGIBLES = ("perfil", "inventario", "fundicion")
# Paneles que no cambian de pantalla (chat, dialogos): no tocan el estado.
PANTALLAS_SUPERPUESTAS = ("chat", "dialogo", "escuadra")
_pantallas_desconocidas: set[str] = set()


def pantalla_de(linea: str) -> tuple[str, str] | None:
    """("abierta", "perfil"), ("abierta", "?NombreNuevo"), ("cerrada", "") o ("pausa", "").

    Un nombre que no esta en PANTALLAS vuelve con "?" delante y se anota una vez
    en el log para poder anadirlo a la tabla: asi se descubren los marcadores del
    perfil, el inventario y la fundicion sin copiar el fichero del usuario.
    """
    m = RE_PANTALLA.search(linea) or RE_INTERFAZ.search(linea)
    if m:
        nombre = m.group(1)
        interna = PANTALLAS.get(nombre)
        if interna is None:
            if nombre not in _pantallas_desconocidas:
                _pantallas_desconocidas.add(nombre)
                log.info("Pantalla del juego sin clasificar (candidata a marcador): %r", nombre)
            return ("abierta", "?" + nombre)
        if interna in PANTALLAS_SUPERPUESTAS:
            return None
        return ("abierta", interna)
    if MARCADOR_PAUSA in linea:
        return ("pausa", "")
    if any(marca in linea for marca in MARCADORES_CIERRE):
        return ("cerrada", "")
    return None


def leer_lineas(ruta: Path, posicion: int) -> tuple[list[str], int]:
    """Lineas completas escritas desde `posicion`, y hasta donde se leyo.

    Se lee en binario: en modo texto, `tell()` tras iterar lineas lanza OSError y
    la posicion no avanzaba, con lo que cada evento se repetia en cada pasada.
    Una linea a medio escribir se deja para la siguiente lectura.
    """
    with ruta.open("rb") as f:
        f.seek(posicion)
        datos = f.read()
    fin = datos.rfind(b"\n")
    if fin < 0:
        return [], posicion
    texto = datos[: fin + 1].decode("utf-8", errors="replace")
    return texto.splitlines(), posicion + fin + 1


def leer_eventos(ruta: Path, posicion: int) -> tuple[list[str], int]:
    """Eventos en las lineas completas escritas desde `posicion`, y hasta donde se leyo."""
    lineas, posicion = leer_lineas(ruta, posicion)
    return [e for e in (clasificar(linea) for linea in lineas) if e], posicion


class VigilanteEELog(QThread):
    """Sigue el final del fichero y avisa de los eventos reconocidos."""

    evento = Signal(str)  # nombre del evento
    pista = Signal(str, str)  # ("reliquia", "Lith K5") o ("recompensa", unique_name)
    pantalla = Signal(str, str)  # ("abierta", "perfil"), ("cerrada", ""), ("pausa", "")
    arranque = Signal(object)  # Cabecera: al ver el fichero y cada vez que el juego arranca

    INTERVALO = 0.5

    def __init__(self, ruta: str | Path, parent=None):
        super().__init__(parent)
        self.ruta = Path(ruta)
        self._parar = False

    def run(self) -> None:  # noqa: D102
        posicion = -1  # todavia no se ha visto el fichero
        avisado = False
        while not self._parar:
            try:
                if not self.ruta.exists():
                    if not avisado:
                        log.info("Todavia no existe %s; se espera a que arranque el juego", self.ruta)
                        avisado = True
                    time.sleep(2)
                    continue
                tamano = self.ruta.stat().st_size
                if posicion < 0:
                    posicion = tamano  # al arrancar solo interesa lo nuevo
                    self._anunciar_cabecera()
                elif tamano < posicion:
                    log.info("EE.log se ha reiniciado (el juego se ha vuelto a abrir)")
                    posicion = 0
                    # La cabecera se escribe de golpe al arrancar; un segundo basta.
                    time.sleep(1)
                    self._anunciar_cabecera()
                if tamano > posicion:
                    lineas, posicion = leer_lineas(self.ruta, posicion)
                    self._procesar(lineas)
            except OSError as e:
                log.warning("No se pudo leer EE.log: %s", e)
                time.sleep(2)
            time.sleep(self.INTERVALO)

    def _procesar(self, lineas: list[str]) -> None:
        """Emite, en el orden del fichero, los eventos y las pistas de las lineas nuevas."""
        for linea in lineas:
            evento = clasificar(linea)
            if evento:
                log.info("EE.log: %s", evento)
                self.evento.emit(evento)
                continue
            encontrada = pista(linea)
            if encontrada:
                log.info("EE.log: pista %s = %s", *encontrada)
                self.pista.emit(*encontrada)
                continue
            cambio = pantalla_de(linea)
            if cambio:
                log.debug("EE.log: pantalla %s %s", *cambio)
                self.pantalla.emit(*cambio)

    def _anunciar_cabecera(self) -> None:
        cabecera = leer_cabecera(self.ruta)
        log.info("Warframe build %s, windowMode %s", cabecera.build or "?", cabecera.modo_ventana)
        self.arranque.emit(cabecera)

    def parar(self) -> None:
        self._parar = True
        self.wait(3000)
