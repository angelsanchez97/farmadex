"""La marca de maestria que comparten la ficha del buscador y las etiquetas de recompensas.

Una pieza (los Sistemas de Ash Prime) no da maestria por si misma: lo que
interesa es si el objeto del que forma parte ya esta dominado, asi que aqui se
sube al padre cuando la pieza no aplica.
"""

from __future__ import annotations

import sqlite3

from .. import perfil as datos_perfil
from ..idiomas import t
from ..perfil import A_MEDIAS, DOMINADO, NO_APLICA, SIN_TOCAR, EstadoItem
from .widgets import COLOR_DISPONIBLE, PALETA

# Fondos oscuros para las etiquetas de la ficha, a juego con los de boveda/disponible.
FONDO_DOMINADO = "#15301a"
FONDO_A_MEDIAS = "#3a2a12"


def estado_con_padre(usuario: sqlite3.Connection, indice: sqlite3.Connection, item_id: int) -> EstadoItem:
    """Estado de maestria del objeto o, si es una pieza, del objeto al que pertenece."""
    estado = datos_perfil.estado_de(usuario, indice, item_id)
    if estado.estado != NO_APLICA:
        return estado
    fila = indice.execute("SELECT padre_id FROM items WHERE id = ?", (item_id,)).fetchone()
    if fila and fila[0]:
        return datos_perfil.estado_de(usuario, indice, fila[0])
    return estado


def texto_maestria(estado: EstadoItem) -> str | None:
    """'Dominado', 'Maestria 43 % (rango 19)' o 'Sin dominar'; None si el objeto no da maestria."""
    if estado.estado == DOMINADO:
        return t("Dominado")
    if estado.estado == A_MEDIAS:
        return t("Maestria {pct} % (rango {rango})", pct=int(estado.porcentaje), rango=estado.rango or 0)
    if estado.estado == SIN_TOCAR:
        return t("Sin dominar")
    return None


def colores_maestria(estado: EstadoItem) -> tuple[str, str]:
    """(fondo, texto) para pintar la etiqueta en HTML segun el estado."""
    if estado.estado == DOMINADO:
        return FONDO_DOMINADO, COLOR_DISPONIBLE
    if estado.estado == A_MEDIAS:
        return FONDO_A_MEDIAS, PALETA["aviso"]
    return PALETA["panel"], PALETA["suave"]
