"""rapidfuzz cargado bajo demanda.

Cargar rapidfuzz (sus DLL compiladas) cuesta casi un segundo del hilo de la ventana al
arrancar en un PC normal, y no hace falta hasta la primera busqueda o la primera lectura
de pantalla. Estos objetos se comportan como los modulos de rapidfuzz (`fuzz.ratio`,
`rf_process.cdist`, `Levenshtein.distance`...) pero lo importan la primera vez que se usan.
"""

from __future__ import annotations

import importlib
import threading

_cerrojo = threading.Lock()


class _ModuloPerezoso:
    __slots__ = ("_nombre", "_modulo")

    def __init__(self, nombre: str) -> None:
        self._nombre = nombre
        self._modulo = None

    def cargar(self):
        modulo = self._modulo
        if modulo is None:
            with _cerrojo:
                if self._modulo is None:
                    self._modulo = importlib.import_module(self._nombre)
                modulo = self._modulo
        return modulo

    def __getattr__(self, atributo: str):
        return getattr(self.cargar(), atributo)

    def __repr__(self) -> str:
        return f"<rapidfuzz perezoso {self._nombre}{' (cargado)' if self._modulo else ''}>"


fuzz = _ModuloPerezoso("rapidfuzz.fuzz")
rf_process = _ModuloPerezoso("rapidfuzz.process")
Levenshtein = _ModuloPerezoso("rapidfuzz.distance.Levenshtein")


def precargar() -> None:
    """Para llamarla desde un hilo de fondo: deja rapidfuzz cargado antes de que se use."""
    for modulo in (fuzz, rf_process, Levenshtein):
        modulo.cargar()
