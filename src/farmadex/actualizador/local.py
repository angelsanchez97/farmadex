"""Versiones nuevas desde una carpeta del propio PC.

Mientras el proyecto no este publicado, cada compilacion deja una copia de su
instalador en la carpeta de actualizaciones del usuario. Farmadex la mira al
arrancar: si hay un instalador con una version mas alta que la que se esta
ejecutando, lo dice y ofrece lanzarlo. No se instala nada sin que el usuario
pulse el boton.
"""

from __future__ import annotations

import os
import re
import subprocess

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .. import NOMBRE_APP
from ..config import DIR_ACTUALIZACIONES, cargar
from ..registro_log import obtener
from .app import Version, es_mas_nueva, numeros

log = obtener("actualizador.local")

# Farmadex-0.2.0-setup.exe / Farmadex-0.2.0-portable.zip
RE_ARTEFACTO = re.compile(
    rf"^{NOMBRE_APP}-(\d+\.\d+\.\d+)-(setup\.exe|portable\.zip)$", re.IGNORECASE
)


def carpeta_por_defecto() -> Path:
    """La carpeta de actualizaciones del usuario, configurable en config.json.

    Es la misma se ejecute desde el codigo o desde el programa instalado: si
    dependiera de donde esta el .exe, la version instalada no encontraria nunca
    las compilaciones nuevas.
    """
    try:
        configurada = cargar().get("carpeta_actualizaciones")
    except Exception:  # noqa: BLE001 - sin configuracion se usa la de siempre
        configurada = None
    return Path(configurada) if configurada else DIR_ACTUALIZACIONES


def buscar(carpeta: Path | str, version_actual: str | None = None) -> Version | None:
    """El instalador mas nuevo de la carpeta, si es posterior al que se ejecuta."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return None

    mejor: tuple[tuple[int, int, int], Path] | None = None
    for fichero in carpeta.iterdir():
        m = RE_ARTEFACTO.match(fichero.name)
        if not m:
            continue
        # El instalador manda sobre el zip: instalar es un doble clic.
        if mejor and fichero.suffix.lower() == ".zip" and mejor[1].suffix.lower() == ".exe":
            continue
        version = numeros(m.group(1))
        if version and (mejor is None or version >= mejor[0]):
            mejor = (version, fichero)

    if not mejor:
        return None
    etiqueta = ".".join(str(n) for n in mejor[0])
    if not (es_mas_nueva(etiqueta, version_actual) if version_actual else es_mas_nueva(etiqueta)):
        return None
    return Version(etiqueta=etiqueta, url=str(mejor[1]), notas=_notas(carpeta))


def _notas(carpeta: Path) -> str:
    """Si hay un CHANGELOG al lado, se ensena su primer bloque."""
    for candidato in (carpeta / "CHANGELOG.md", carpeta.parent / "CHANGELOG.md"):
        if candidato.exists():
            try:
                texto = candidato.read_text(encoding="utf-8")
            except OSError:
                continue
            bloques = texto.split("\n## ")
            if len(bloques) > 1:
                return ("## " + bloques[1]).strip()[:1500]
    return ""


def instalar(version: Version) -> bool:
    """Lanza el instalador y devuelve True si arranco (la app debe cerrarse luego)."""
    ruta = Path(version.url)
    if not ruta.exists():
        log.warning("El instalador ya no esta: %s", ruta)
        return False
    if ruta.suffix.lower() == ".zip":
        # Un zip no se instala solo: se abre la carpeta y lo hace el usuario.
        os.startfile(ruta.parent)  # noqa: S606 - abrir el explorador es la intencion
        return False
    try:
        subprocess.Popen([str(ruta)], close_fds=True)
        log.info("Instalador lanzado: %s", ruta)
        return True
    except OSError as e:
        log.error("No se pudo lanzar el instalador: %s", e)
        return False


class ComprobadorLocal(QObject):
    """Mira la carpeta de compilaciones al arrancar y cada media hora."""

    nueva_version = Signal(object)  # Version

    def __init__(self, carpeta: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.carpeta = Path(carpeta) if carpeta else carpeta_por_defecto()

    @Slot()
    def comprobar(self) -> None:
        try:
            version = buscar(self.carpeta)
        except OSError as e:  # pragma: no cover - carpeta en red caida, permisos
            log.warning("No se pudo mirar la carpeta de versiones: %s", e)
            return
        if version:
            log.info("Version nueva en disco: %s (%s)", version.etiqueta, version.url)
            self.nueva_version.emit(version)
