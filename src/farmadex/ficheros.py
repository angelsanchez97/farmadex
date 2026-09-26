"""Escritura de ficheros que aguanta los bloqueos de Windows.

En Windows no se puede sustituir un fichero que otro proceso tiene abierto en
ese instante: OBS leyendo el texto del directo, el antivirus mirando un JSON
recien escrito, el explorador sacando la vista previa. El "temporal + renombrar"
de siempre fallaba entonces con PermissionError (WinError 5 o 32). Aqui se
reintenta un momento y, si el bloqueo sigue, se escribe encima sin renombrar:
se pierde la atomicidad, pero no el guardado.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import logging

log = logging.getLogger("farmadex.ficheros")  # sin registro_log: config importa esto

REINTENTOS = 10
ESPERA_S = 0.1


def temporal_de(destino: Path) -> Path:
    """Temporal al lado de `destino`, propio de este proceso: si dos Farmadex descargan
    a la vez, cada uno escribe el suyo y no se pisan (WinError 32 al renombrar)."""
    destino = Path(destino)
    return destino.with_name(f"{destino.name}.{os.getpid()}.tmp")


def reemplazar(tmp: Path, destino: Path) -> None:
    """`tmp` pasa a ser `destino`, aunque `destino` este abierto un momento por otro."""
    for intento in range(REINTENTOS):
        try:
            os.replace(tmp, destino)
            return
        except PermissionError:
            time.sleep(ESPERA_S * (intento + 1))
    log.warning("%s sigue bloqueado; se escribe encima sin renombrar", destino)
    Path(destino).write_bytes(Path(tmp).read_bytes())
    try:
        Path(tmp).unlink(missing_ok=True)
    except OSError:
        pass


def escribir_texto(destino: Path, texto: str) -> None:
    """Escribe `texto` en `destino` pasando por un temporal al lado."""
    destino = Path(destino)
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    reemplazar(tmp, destino)
