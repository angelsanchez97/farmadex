"""Perfil del jugador importado desde el JSON que el mismo descarga de warframe.com.

Uso tipico:

    from farmadex.perfil import importar, estado_de, pendientes_por_categoria
    resultado = importar(ruta_json, usuario, indice)   # lee, valida, guarda y casa
    estado_de(usuario, indice, item_id).dominado

Farmadex no pide nada a DE: solo lee el fichero que el usuario le entrega.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .almacen import (
    Casado,
    EstadoItem,
    casar_con_catalogo,
    completados_ocr,
    desconocidos_ocr,
    estadistica,
    estado_de,
    estado_por_unique_name,
    estados_de_todos,
    guardar,
    hay_perfil,
    lecturas_ocr,
    nodo_hecho,
    nodos_pendientes,
    pendientes_por_categoria,
    preparar,
    registrar_lecturas_ocr,
    resumen,
    resumen_maestria,
    xp_guardada,
)
from .desde_ocr import LecturaOCR, ResultadoEscaneo
from .desde_ocr import construir as construir_desde_ocr
from .desde_ocr import desde_tarjetas
from .desde_ocr import guardar as guardar_desde_ocr
from .lector import Perfil, PerfilInvalido, cargar, interpretar
from .maestria import (
    A_MEDIAS, DESCONOCIDO, DOMINADO, NO_APLICA, NO_DOMINADO, SIN_TOCAR, es_masterizable, estado_por_rango,
    tope_rango, umbral_xp,
)

__all__ = [
    "A_MEDIAS", "DESCONOCIDO", "DOMINADO", "NO_APLICA", "NO_DOMINADO", "SIN_TOCAR",
    "Casado", "EstadoItem", "LecturaOCR", "Perfil", "PerfilInvalido", "ResultadoEscaneo",
    "ResultadoImportacion",
    "cargar", "casar_con_catalogo", "completados_ocr", "construir_desde_ocr", "desconocidos_ocr", "desde_tarjetas",
    "es_masterizable", "estadistica", "estado_de", "estado_por_rango",
    "estado_por_unique_name", "estados_de_todos", "guardar", "guardar_desde_ocr", "hay_perfil",
    "importar", "interpretar", "lecturas_ocr", "nodo_hecho", "nodos_pendientes",
    "pendientes_por_categoria", "preparar", "registrar_lecturas_ocr",
    "resumen", "resumen_maestria", "tope_rango", "umbral_xp", "xp_guardada",
]


@dataclass
class ResultadoImportacion:
    perfil: Perfil
    casado: Casado | None  # None si no se paso el indice
    segundos: float


def importar(
    ruta: Path | str, usuario: sqlite3.Connection, indice: sqlite3.Connection | None = None
) -> ResultadoImportacion:
    """Lee y valida el fichero, lo guarda en la BD del usuario y lo casa con el catalogo.

    Lanza PerfilInvalido si el fichero no sirve; en ese caso no se toca lo guardado.
    """
    inicio = time.perf_counter()
    perfil = cargar(ruta)
    guardar(usuario, perfil, ruta)
    casado = casar_con_catalogo(usuario, indice) if indice is not None else None
    return ResultadoImportacion(perfil, casado, time.perf_counter() - inicio)
