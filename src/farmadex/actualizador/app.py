"""Aviso de versiones nuevas de la aplicacion (GitHub Releases).

Mientras el repositorio sea privado, la peticion devuelve 404 y no se dice
nada: el usuario no tiene por que ver un error por algo que aun no existe.
Nunca se instala nada solo; solo se avisa y se abre la pagina de descarga.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, Slot

from .. import VERSION
from ..online.http import Cliente
from ..registro_log import obtener

log = obtener("actualizador.app")

# Se rellenan cuando el repositorio exista; vacios = comprobacion desactivada.
PROPIETARIO = "angelsanchez97"
REPOSITORIO = "farmadex"

RE_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass
class Version:
    etiqueta: str
    url: str
    notas: str


def numeros(texto: str) -> tuple[int, int, int] | None:
    m = RE_VERSION.search(texto or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def es_mas_nueva(candidata: str, actual: str = VERSION) -> bool:
    """Compara por numero, no por texto: '0.10.0' es mas que '0.9.0'."""
    a, b = numeros(candidata), numeros(actual)
    if not a or not b:
        return False
    return a > b


def analizar_release(datos: dict) -> Version | None:
    """Saca de la respuesta de GitHub la version y el instalador."""
    etiqueta = datos.get("tag_name") or ""
    if not etiqueta:
        return None
    instalador = next(
        (
            a.get("browser_download_url")
            for a in datos.get("assets") or []
            if str(a.get("name", "")).lower().endswith((".exe", ".zip"))
        ),
        datos.get("html_url", ""),
    )
    return Version(etiqueta=etiqueta, url=instalador, notas=datos.get("body") or "")


class ComprobadorApp(QObject):
    nueva_version = Signal(object)  # Version

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cliente = Cliente(cabeceras={"Accept": "application/vnd.github+json"})
        self._hilo: threading.Thread | None = None

    @property
    def activo(self) -> bool:
        return bool(PROPIETARIO and REPOSITORIO)

    @Slot()
    def comprobar(self) -> None:
        """Consulta GitHub en un hilo para no congelar la interfaz."""
        if not self.activo:
            log.debug("Comprobacion de version desactivada (no hay repositorio publicado)")
            return
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._hilo = threading.Thread(
            target=self.comprobar_ahora, name="comprobador-app", daemon=True
        )
        self._hilo.start()

    def comprobar_ahora(self) -> None:
        """La consulta en si, sincrona. Nunca propaga."""
        if not self.activo:
            return
        url = f"https://api.github.com/repos/{PROPIETARIO}/{REPOSITORIO}/releases/latest"
        try:
            datos = self.cliente.json(url, segundos_cache=3600, intentos=1)
        except Exception as e:  # noqa: BLE001 - 404 con repo privado, sin red, JSON raro
            # No es un error que contar al usuario: solo se anota.
            log.info("Sin informacion de versiones nuevas (%s)", e)
            return
        try:
            version = analizar_release(datos if isinstance(datos, dict) else {})
        except Exception as e:  # noqa: BLE001 - respuesta con otra forma
            log.info("Respuesta de versiones ilegible (%s)", e)
            return
        if version and es_mas_nueva(version.etiqueta):
            log.info("Hay una version nueva: %s", version.etiqueta)
            self.nueva_version.emit(version)

    def cerrar(self) -> None:
        self.cliente.cerrar()
