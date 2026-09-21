"""Cliente HTTP compartido: un hilo de peticiones por host, reintentos y cache corta."""

from __future__ import annotations

import threading
import time

import httpx

from ..config import USER_AGENT
from ..registro_log import obtener

log = obtener("http")

# Un servidor caido no debe tener a un hilo esperando 20 s solo para conectar:
# conectar es rapido o no es; leer la respuesta si puede tardar.
SEGUNDOS_CONECTAR = 5.0
# Codigos que merecen otro intento: el servidor esta saturado o caido a ratos.
# Un 404 o un 400 no cambian por insistir, y reintentarlos solo gasta cuota.
CODIGOS_REINTENTABLES = {408, 425, 429, 500, 502, 503, 504}
# Entradas de cache a partir de las cuales se barren las caducadas al guardar.
MAX_CACHE = 2000


class Limitador:
    """Deja pasar como mucho N peticiones por segundo a un mismo host."""

    def __init__(self, por_segundo: float):
        self.intervalo = 1.0 / por_segundo if por_segundo > 0 else 0.0
        self._ultima = 0.0
        self._cerrojo = threading.Lock()

    def esperar(self) -> None:
        if not self.intervalo:
            return
        with self._cerrojo:
            espera = self._ultima + self.intervalo - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            self._ultima = time.monotonic()


class Cliente:
    """Peticiones JSON con limite por segundo, reintentos y cache; seguro entre hilos.

    `transporte` existe para las pruebas: un `httpx.MockTransport` contesta sin red.
    """

    def __init__(
        self,
        por_segundo: float = 0.0,
        cabeceras: dict | None = None,
        timeout: float = 20.0,
        transporte: httpx.BaseTransport | None = None,
    ):
        self.limitador = Limitador(por_segundo)
        self.cliente = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, SEGUNDOS_CONECTAR)),
            headers={"User-Agent": USER_AGENT, **(cabeceras or {})},
            follow_redirects=True,
            transport=transporte,
        )
        self._cache: dict[str, tuple[float, object]] = {}
        self._cerrojo = threading.Lock()

    def json(self, url: str, segundos_cache: float = 0.0, intentos: int = 3):
        if segundos_cache:
            with self._cerrojo:
                guardado = self._cache.get(url)
            if guardado and time.monotonic() - guardado[0] < segundos_cache:
                return guardado[1]

        ultimo: Exception | None = None
        for intento in range(intentos):
            self.limitador.esperar()
            try:
                r = self.cliente.get(url)
                r.raise_for_status()
                datos = r.json()
            except httpx.HTTPStatusError as e:
                ultimo = e
                if e.response.status_code not in CODIGOS_REINTENTABLES:
                    break
            except (httpx.HTTPError, ValueError) as e:
                ultimo = e
            else:
                if segundos_cache:
                    self._guardar_en_cache(url, datos, segundos_cache)
                return datos
            if intento < intentos - 1:
                time.sleep(2**intento)
        log.warning("Fallo pidiendo %s: %s", url, _resumen_error(ultimo))
        raise RuntimeError(_resumen_error(ultimo))

    def _guardar_en_cache(self, url: str, datos: object, segundos_cache: float) -> None:
        ahora = time.monotonic()
        with self._cerrojo:
            if len(self._cache) >= MAX_CACHE:
                # Las entradas caducan cada una a su ritmo, pero ninguna vive mas que
                # la cache mas larga que se pide (un dia): con eso basta para barrer.
                self._cache = {
                    u: (t, d) for u, (t, d) in self._cache.items() if ahora - t < 86400
                }
            self._cache[url] = (ahora, datos)

    def cerrar(self) -> None:
        self.cliente.close()


def _resumen_error(error: Exception | None) -> str:
    """Un motivo corto y legible: el codigo HTTP o el tipo de fallo de red."""
    if error is None:
        return "sin intentos"
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    if isinstance(error, httpx.TimeoutException):
        return "el servidor no responde (tiempo agotado)"
    if isinstance(error, httpx.ConnectError):
        return "no hay conexion con el servidor"
    if isinstance(error, ValueError):
        return "la respuesta no es JSON valido"
    return str(error) or type(error).__name__
