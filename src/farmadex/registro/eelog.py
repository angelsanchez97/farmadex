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


def leer_eventos(ruta: Path, posicion: int) -> tuple[list[str], int]:
    """Eventos en las lineas completas escritas desde `posicion`, y hasta donde se leyo.

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
    eventos = [e for e in (clasificar(linea) for linea in texto.splitlines()) if e]
    return eventos, posicion + fin + 1


class VigilanteEELog(QThread):
    """Sigue el final del fichero y avisa de los eventos reconocidos."""

    evento = Signal(str)  # nombre del evento
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
                    eventos, posicion = leer_eventos(self.ruta, posicion)
                    for evento in eventos:
                        log.info("EE.log: %s", evento)
                        self.evento.emit(evento)
            except OSError as e:
                log.warning("No se pudo leer EE.log: %s", e)
                time.sleep(2)
            time.sleep(self.INTERVALO)

    def _anunciar_cabecera(self) -> None:
        cabecera = leer_cabecera(self.ruta)
        log.info("Warframe build %s, windowMode %s", cabecera.build or "?", cabecera.modo_ventana)
        self.arranque.emit(cabecera)

    def parar(self) -> None:
        self._parar = True
        self.wait(3000)
