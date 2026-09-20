"""Cliente HTTP compartido: un hilo de peticiones por host, reintentos y cache corta."""

from __future__ import annotations

import threading
import time

import httpx

from ..config import USER_AGENT
from ..registro_log import obtener

log = obtener("http")


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
    def __init__(self, por_segundo: float = 0.0, cabeceras: dict | None = None, timeout: float = 20.0):
        self.limitador = Limitador(por_segundo)
        self.cliente = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, **(cabeceras or {})},
            follow_redirects=True,
        )
        self._cache: dict[str, tuple[float, object]] = {}
        self._cerrojo = threading.Lock()

    def json(self, url: str, segundos_cache: float = 0.0, intentos: int = 3):
        ahora = time.monotonic()
        if segundos_cache:
            with self._cerrojo:
                guardado = self._cache.get(url)
            if guardado and ahora - guardado[0] < segundos_cache:
                return guardado[1]

        ultimo = None
        for intento in range(intentos):
            self.limitador.esperar()
            try:
                r = self.cliente.get(url)
                r.raise_for_status()
                datos = r.json()
                if segundos_cache:
                    with self._cerrojo:
                        self._cache[url] = (time.monotonic(), datos)
                return datos
            except (httpx.HTTPError, ValueError) as e:
                ultimo = e
                if intento < intentos - 1:
                    time.sleep(2**intento)
        log.warning("Fallo pidiendo %s: %s", url, ultimo)
        raise RuntimeError(str(ultimo))

    def cerrar(self) -> None:
        self.cliente.close()
