"""Registro a fichero rotativo y captura de excepciones no controladas."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import NOMBRE_APP
from .config import DIR_LOGS, crear_carpetas

_configurado = False


def configurar(nivel: int = logging.INFO) -> logging.Logger:
    global _configurado
    raiz = logging.getLogger(NOMBRE_APP.lower())
    if _configurado:
        return raiz
    crear_carpetas()
    raiz.setLevel(nivel)
    formato = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    fichero = RotatingFileHandler(
        DIR_LOGS / f"{NOMBRE_APP.lower()}.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fichero.setFormatter(formato)
    raiz.addHandler(fichero)

    consola = logging.StreamHandler(sys.stderr)
    consola.setFormatter(formato)
    raiz.addHandler(consola)

    _configurado = True
    return raiz


def obtener(nombre: str) -> logging.Logger:
    configurar()
    return logging.getLogger(f"{NOMBRE_APP.lower()}.{nombre}")


def instalar_gancho_excepciones(mostrar_dialogo=None) -> None:
    """Manda cualquier excepcion no capturada al log (y opcionalmente a un dialogo)."""
    log = obtener("excepciones")

    def gancho(tipo, valor, traza):
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, valor, traza)
            return
        log.error("Excepcion no controlada", exc_info=(tipo, valor, traza))
        if mostrar_dialogo is not None:
            try:
                mostrar_dialogo(f"{tipo.__name__}: {valor}")
            except Exception:  # noqa: BLE001 - el dialogo nunca debe tumbar el gancho
                log.exception("Fallo al mostrar el dialogo de error")

    sys.excepthook = gancho
