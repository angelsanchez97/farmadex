"""Glosario de terminos del juego: una o dos frases al pasar el raton.

Quien empieza no sabe que es una reliquia, una era o la boveda; quien lleva
anos no quiere que se lo expliquen. Por eso el glosario no ocupa sitio: los
terminos se pintan como siempre y solo al posar el raton sale la explicacion.

En la ficha (QTextBrowser) y en las etiquetas ricas (QLabel) los terminos van
como enlaces `glosa:<clave>`; en los widgets normales (casillas, desplegables)
basta con `aplicar(widget, clave)`.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QEvent
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLabel, QTextBrowser, QToolTip, QWidget

from ..idiomas import t

PREFIJO = "glosa:"

# clave -> (titulo, explicacion). Los dos pasan por t(); la explicacion, corta.
TERMINOS: dict[str, tuple[str, str]] = {
    "reliquia": (
        "Reliquia",
        "Objeto que se abre en una mision de fisura del Vacio y suelta una de sus seis "
        "piezas Prime al terminar. Las reliquias se consiguen jugando misiones normales.",
    ),
    "era": (
        "Era",
        "Familia de reliquias: Lith, Meso, Neo, Axi, Requiem y Omnia. Cada reliquia solo "
        "se abre en una fisura de su misma era; cuanto mas alta la era, mas dificil la mision.",
    ),
    "refinamiento": (
        "Refinamiento",
        "Mejora de una reliquia pagada con Trazas del Vacio: Intacta, Excepcional, Impecable "
        "o Radiante. A mas refinamiento, mas probabilidad de que salga la pieza rara.",
    ),
    "rotacion": (
        "Rotacion",
        "En las misiones sin fin (Supervivencia, Defensa...) las recompensas van en ciclos "
        "A, A, B, C. La rotacion C es la cuarta recompensa: el minuto 20 o la oleada 20.",
    ),
    "boveda": (
        "Boveda",
        "Lo que esta en boveda ya no sale en ninguna reliquia que se pueda farmear: "
        "solo se consigue comprandolo, o comprando su reliquia, a otro jugador.",
    ),
    "fisura": (
        "Fisura del Vacio",
        "Mision normal en la que ademas puedes abrir una reliquia de su misma era. "
        "Salen en el mapa con un icono de fisura y cambian cada pocas horas.",
    ),
    "tormenta": (
        "Tormenta del Vacio",
        "Fisura en una mision de Railjack (la nave): hace falta tener Railjack y, ademas "
        "de la pieza, dan holoclaves.",
    ),
    "camino_de_acero": (
        "Camino de Acero",
        "Version dificil del mapa estelar, con enemigos mucho mas fuertes a cambio de "
        "mejores recompensas. Se desbloquea al completar todos los nodos normales.",
    ),
    "dominado": (
        "Dominado",
        "Cada warframe, arma o companero subido a rango 30 (40 en algunos) da puntos de "
        "maestria una sola vez. 'Sin dominar' quiere decir que todavia te los daria.",
    ),
    "maestria": (
        "Rango de maestria",
        "El nivel de tu cuenta (MR). Sube dominando equipo y desbloquea armas, mods, "
        "comercio y modos de juego.",
    ),
    "prime": (
        "Prime",
        "Version mejorada y dorada de un warframe o un arma. Sus piezas solo salen de "
        "reliquias o de otros jugadores.",
    ),
    "pieza": (
        "Pieza",
        "Parte de un warframe o de un arma (plano, chasis, sistemas, neuroptica...). "
        "Con todas las piezas se construye el objeto completo en la Fundicion.",
    ),
    "ducados": (
        "Ducados",
        "Moneda que da Baro Ki'Teer a cambio de piezas Prime que te sobren. Con ella se "
        "compran los objetos que solo vende el.",
    ),
    "baro": (
        "Baro Ki'Teer",
        "El Comerciante del Vacio: aparece cada dos semanas en un relevo con objetos que no "
        "se consiguen de otra forma, a cambio de ducados y creditos.",
    ),
    "rareza": (
        "Rareza",
        "Lo comun sale mas veces y lo raro, menos. En una reliquia sin refinar: tres piezas "
        "comunes (25 % cada una), dos poco comunes (11 %) y una rara (2 %).",
    ),
    "reputacion": (
        "Reputacion",
        "Puntos que ganas con un sindicato haciendo sus misiones o entregando objetos; se "
        "gastan en su tienda.",
    ),
}


def texto(clave: str) -> str:
    """El contenido del tooltip, en HTML, en el idioma de la interfaz. Vacio si no existe."""
    termino = TERMINOS.get(clave)
    if not termino:
        return ""
    titulo, explicacion = termino
    return (
        f"<p style='white-space:normal'><b>{html.escape(t(titulo))}</b><br>"
        f"{html.escape(t(explicacion))}</p>"
    )


def enlace(clave: str, visible: str, color: str, negrita: bool = False) -> str:
    """El termino tal cual se ve, como enlace `glosa:` que solo sirve para el tooltip."""
    cuerpo = html.escape(visible)
    if negrita:
        cuerpo = f"<b>{cuerpo}</b>"
    return f"<a href='{PREFIJO}{clave}' style='color:{color};text-decoration:none'>{cuerpo}</a>"


def es_glosa(url: str) -> bool:
    return url.startswith(PREFIJO)


def mostrar(url: str, widget: QWidget | None = None) -> bool:
    """Ensena el tooltip de un enlace `glosa:` bajo el cursor. Devuelve si lo era."""
    if not es_glosa(url):
        return False
    contenido = texto(url.removeprefix(PREFIJO))
    if contenido:
        QToolTip.showText(QCursor.pos(), contenido, widget)
    return True


def aplicar(widget: QWidget, clave: str) -> None:
    """Tooltip de glosario en un widget normal (casilla, desplegable, etiqueta)."""
    widget.setToolTip(texto(clave))


def conectar_etiqueta(etiqueta: QLabel) -> None:
    """Una QLabel con enlaces `glosa:` ensena el tooltip al pasar el raton por ellos."""
    etiqueta.linkHovered.connect(lambda url: mostrar(url, etiqueta) if url else QToolTip.hideText())
    etiqueta.linkActivated.connect(lambda url: mostrar(url, etiqueta))


class FichaConGlosario(QTextBrowser):
    """QTextBrowser que ensena el glosario al pasar el raton por un enlace `glosa:`."""

    def event(self, evento):  # noqa: N802 - firma de Qt
        if evento.type() == QEvent.ToolTip:
            url = self.anchorAt(evento.pos())
            if es_glosa(url):
                QToolTip.showText(evento.globalPos(), texto(url.removeprefix(PREFIJO)), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(evento)
