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
    # El instalador antes que el zip: GitHub los devuelve por orden alfabetico y
    # el portable iba primero, asi que se ofrecia un zip a quien solo quiere
    # pulsar dos veces. Si no hay ninguno de los dos, la pagina de la release.
    adjuntos = [
        (str(a.get("name", "")).lower(), a.get("browser_download_url"))
        for a in datos.get("assets") or []
    ]
    instalador = next(
        (url for nombre, url in adjuntos if nombre.endswith(".exe")),
        next(
            (url for nombre, url in adjuntos if nombre.endswith(".zip")),
            datos.get("html_url", ""),
        ),
    )
    return Version(etiqueta=etiqueta, url=instalador, notas=datos.get("body") or "")


class ComprobadorApp(QObject):
    """Mira las releases de GitHub.

    Contesta siempre: hay version nueva, no la hay, o no se ha podido mirar.
    Quien escucha decide cuanto ruido hace con cada cosa -- una version nueva
    merece un aviso en la ventana, "estas al dia" solo merece verse si entras en
    Ajustes a mirarlo.

    `a_mano` no cambia lo que se contesta, solo que no se reutiliza la respuesta
    guardada: si acabas de publicar y pulsas el boton, quieres preguntar otra vez.
    """

    nueva_version = Signal(object)  # Version
    sin_novedades = Signal()
    fallo = Signal(str)  # motivo, para ensenarlo en Ajustes

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
        self._lanzar(manual=False)

    @Slot()
    def comprobar_a_mano(self) -> None:
        """Igual, pero sin reutilizar la respuesta guardada."""
        self._lanzar(manual=True)

    def _lanzar(self, manual: bool) -> None:
        if not self.activo:
            log.debug("Comprobacion de version desactivada (no hay repositorio publicado)")
            self.sin_novedades.emit()
            return
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._hilo = threading.Thread(
            target=self.comprobar_ahora, args=(manual,), name="comprobador-app", daemon=True
        )
        self._hilo.start()

    def comprobar_ahora(self, manual: bool = False) -> None:
        """La consulta en si, sincrona. Nunca propaga."""
        if not self.activo:
            return
        url = f"https://api.github.com/repos/{PROPIETARIO}/{REPOSITORIO}/releases/latest"
        try:
            # A mano no se usa la cache: si acabas de publicar y pulsas el boton,
            # lo que quieres es preguntar otra vez, no que te repitan lo de hace un rato.
            datos = self.cliente.json(url, segundos_cache=0 if manual else 3600, intentos=1)
        except Exception as e:  # noqa: BLE001 - 404 con repo privado, sin red, JSON raro
            # Sin pedirlo no es un error que contar al usuario: solo se anota.
            log.info("Sin informacion de versiones nuevas (%s)", e)
            self.fallo.emit(str(e))
            return
        try:
            version = analizar_release(datos if isinstance(datos, dict) else {})
        except Exception as e:  # noqa: BLE001 - respuesta con otra forma
            log.info("Respuesta de versiones ilegible (%s)", e)
            self.fallo.emit(str(e))
            return
        if version and es_mas_nueva(version.etiqueta):
            log.info("Hay una version nueva: %s", version.etiqueta)
            self.nueva_version.emit(version)
        else:
            self.sin_novedades.emit()

    def cerrar(self) -> None:
        self.cliente.cerrar()
