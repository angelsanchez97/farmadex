"""Un color por tipo de objeto en los resultados del buscador.

Quien empieza no sabe si "Sierra" es un mod o un arma: con un color por tipo (recursos
en amarillo, mods en azul, armas en naranja...) se ve de un vistazo sin leer la linea
entera. El color se ajusta al fondo del tema para que se lea igual con un tema oscuro
que con uno claro personalizado: si no contrasta lo bastante con el fondo, se aclara o
se oscurece hasta que lo haga, sin cambiar el tono.
"""

from __future__ import annotations

import html

from PySide6.QtGui import QColor

from ..idiomas import t
from .widgets import PALETA

# clave -> (nombre para la leyenda, color base). Tonos bien separados entre si; el
# amarillo de los recursos lo pidio el propio tester. Los nombres son claves de los
# catalogos de idiomas (las mismas que CATEGORIAS_ES del buscador).
TIPOS: dict[str, tuple[str, str]] = {
    "warframe": ("Warframe", "#4fc3f7"),
    "arma": ("Arma", "#ff8a50"),
    "companero": ("Companero", "#81c784"),
    "mod": ("Mod", "#7c9cff"),
    "arcano": ("Arcano", "#c78bff"),
    "recurso": ("Recurso", "#ffd54f"),
    "reliquia": ("Reliquia", "#d7b27a"),
    "glifo": ("Glifo", "#f48fb1"),
    "mision": ("Mision", "#4dd0a8"),
    "cosmetico": ("Aspecto", "#b0a8c8"),
    "otro": ("Otros", "#9aa4b2"),
}
# Orden de la leyenda: primero lo que mas se busca.
ORDEN = tuple(TIPOS)

CATEGORIA_A_TIPO = {
    "Warframes": "warframe", "Archwing": "warframe",
    "Primary": "arma", "Secondary": "arma", "Melee": "arma", "Arch-Gun": "arma",
    "Arch-Melee": "arma", "SentinelWeapons": "arma",
    "Sentinels": "companero", "Pets": "companero",
    "Mods": "mod", "Arcanes": "arcano", "Relics": "reliquia", "Resources": "recurso",
    "Glyphs": "glifo", "Skins": "cosmetico", "Sigils": "cosmetico", "Honoria": "cosmetico",
}

# Contraste minimo del color contra el fondo (WCAG pide 3:1 para elementos graficos).
CONTRASTE_MINIMO = 3.0


def tipo_de(resultado: dict | None) -> str:
    """Clave de TIPOS para un resultado del buscador (objeto, nodo o tipo de mision).

    Una pieza toma el color de lo que construye (la categoria de la pieza ya es la de su
    padre): los sistemas de Ash Prime van en el color de los warframes.
    """
    if not resultado:
        return "otro"
    if resultado.get("clave"):
        return "mision"
    return CATEGORIA_A_TIPO.get(resultado.get("categoria") or "", "otro")


def _luminancia(color: QColor) -> float:
    def canal(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * canal(color.redF()) + 0.7152 * canal(color.greenF()) + 0.0722 * canal(color.blueF())


def contraste(a: QColor, b: QColor) -> float:
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def color(clave: str, fondo: str | None = None) -> str:
    """El color del tipo, ajustado para leerse sobre `fondo` (por defecto, el de las listas)."""
    base = QColor(TIPOS.get(clave, TIPOS["otro"])[1])
    fondo_q = QColor(fondo or PALETA.get("panel") or "#171d26")
    if contraste(base, fondo_q) >= CONTRASTE_MINIMO:
        return base.name()
    oscuro = _luminancia(fondo_q) < 0.3
    h, s, l, _ = base.getHslF()
    h = max(h, 0.0)
    ajustado = QColor(base)
    for _ in range(20):
        l = min(1.0, l + 0.05) if oscuro else max(0.0, l - 0.05)
        ajustado = QColor.fromHslF(h, s, l)
        if contraste(ajustado, fondo_q) >= CONTRASTE_MINIMO:
            break
    return ajustado.name()


def nombre(clave: str) -> str:
    return t(TIPOS.get(clave, TIPOS["otro"])[0])


def leyenda_html(claves, fondo: str | None = None) -> str:
    """'● Warframe  ● Mod  ● Recurso' solo con los tipos que salen en la lista, en su orden."""
    vistas = set(claves)
    presentes = [c for c in ORDEN if c in vistas]
    if not presentes:
        return ""
    trozos = [
        f"<span style='color:{color(c, fondo)}'>&#9679;</span>&nbsp;{html.escape(nombre(c))}"
        for c in presentes
    ]
    return "&nbsp;&nbsp; ".join(trozos)
