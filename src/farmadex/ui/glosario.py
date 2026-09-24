"""Glosario de terminos del juego: una o dos frases al pasar el raton.

Quien empieza no sabe que es una reliquia, una era o la boveda; quien lleva
anos no quiere que se lo expliquen. Por eso el glosario no ocupa sitio: los
terminos se pintan como siempre y solo al posar el raton sale la explicacion.

En la ficha (QTextBrowser) y en las etiquetas ricas (QLabel) los terminos van
como enlaces `glosa:<clave>`; en los widgets normales (casillas, desplegables)
basta con `aplicar(widget, clave)`.

Un enlace puede llevar ademas un detalle propio (`glosa:<clave>?<texto>`): el
tooltip ensena entonces ese texto en vez de la explicacion generica. Asi cada
tiempo de la ficha explica SUS numeros (minutos por partida, partidas de media).
En los terminos de TERMINOS_TITULO_PROPIO la primera linea del detalle es el titulo:
el tooltip del tipo de mision se titula "Supervivencia", no "Tipo de mision".
"""

from __future__ import annotations

import html
from urllib.parse import quote, unquote

from PySide6.QtCore import QEvent
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLabel, QTextBrowser, QToolTip, QWidget

from ..datos import eficiencia, modos_mision
from ..idiomas import t

PREFIJO = "glosa:"

# Terminos de tiempo estimado: su tooltip dice ademas con que ritmo de juego se calculo.
TERMINOS_TIEMPO = ("tiempo_medio", "tiempo_pieza")
# Terminos cuyo detalle trae su propio titulo en la primera linea.
TERMINOS_TITULO_PROPIO = ("mision",)
NOMBRES_RITMO = {"rapido": "Rapido", "normal": "Normal", "tranquilo": "Tranquilo"}

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
    "mision": (
        "Tipo de mision",
        "Cada tipo de mision tiene su objetivo (aguantar, defender, capturar...) y su forma "
        "de dar recompensas: una sola al terminar o una cada cierto tiempo mientras sigas.",
    ),
    "tiempo_medio": (
        "Tiempo medio estimado",
        "Lo que suele durar la mision dividido por la probabilidad: un 10 % en una mision "
        "de 10 minutos son ~100 minutos de media, mejor que un 20 % en una de 40 (~200). "
        "En las misiones sin fin cuenta llegar a la rotacion. Las duraciones son una "
        "estimacion para un jugador medio, no un dato del juego.",
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
    "inventario": (
        "Tienes",
        "Cantidad leida en pantalla la ultima vez que abriste el Inventario o la Fundicion "
        "con Farmadex mirando. Puede quedarse vieja hasta que vuelvas a abrirlos.",
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
    "radshare": (
        "Escuadra compartiendo reliquia",
        "Los cuatro abren la misma reliquia con el mismo refinamiento y cada uno elige entre "
        "las cuatro recompensas: cada fisura gasta una reliquia tuya y te da cuatro tiradas. "
        "Una pieza al 10 % sale asi en una de cada 2,9 fisuras en vez de una de cada 10.",
    ),
    "tiempo_pieza": (
        "Tiempo hasta la pieza",
        "Minutos de media hasta tenerla: lo que tarda en caer una reliquia util en esa mision "
        "mas una fisura para abrirla, por las reliquias que hay que abrir segun el refinamiento "
        "y si vas solo o en escuadra. No cuenta refinar (Trazas del Vacio). Es una estimacion "
        "para un jugador medio.",
    ),
}


def nota_ritmo() -> str:
    """'Calculado con ritmo de juego Normal (x1); se cambia en Ajustes.' ya traducido."""
    elegido = eficiencia.ritmo()
    return t(
        "Calculado con ritmo de juego {ritmo} (x{factor}); se cambia en Ajustes.",
        ritmo=t(NOMBRES_RITMO[elegido]),
        factor=f"{eficiencia.RITMOS[elegido]:g}",
    )


def texto(clave: str) -> str:
    """El contenido del tooltip, en HTML, en el idioma de la interfaz. Vacio si no existe.

    `clave` puede traer detalle propio tras '?' (lo que pone `enlace(..., detalle=)`):
    se ensena ese detalle, linea a linea, en lugar de la explicacion generica.
    """
    clave, _, detalle = clave.partition("?")
    termino = TERMINOS.get(clave)
    if not termino:
        return ""
    titulo, explicacion = termino
    titulo = t(titulo)
    lineas = unquote(detalle).splitlines()
    if detalle and clave in TERMINOS_TITULO_PROPIO and len(lineas) > 1:
        titulo, lineas = lineas[0], lineas[1:]
    cuerpo = (
        "<br>".join(html.escape(linea) for linea in lineas)
        if detalle
        else html.escape(t(explicacion))
    )
    if clave in TERMINOS_TIEMPO:
        cuerpo += f"<br><i>{html.escape(nota_ritmo())}</i>"
    contenido = f"<p style='white-space:normal'><b>{html.escape(titulo)}</b><br>{cuerpo}</p>"
    if detalle:
        # El desglose son varias lineas con numeros: sin ancho fijo, Qt parte el tooltip
        # en una columna estrecha y cada linea ocupa tres.
        contenido = f"<table width='420' cellspacing='0' cellpadding='0'><tr><td>{contenido}</td></tr></table>"
    return contenido


def enlace(clave: str, visible: str, color: str, negrita: bool = False, detalle: str = "") -> str:
    """El termino tal cual se ve, como enlace `glosa:` que solo sirve para el tooltip.

    Con `detalle` (texto plano, una linea por salto de linea) el tooltip ensena ese texto
    en vez de la explicacion generica del termino.
    """
    cuerpo = html.escape(visible)
    if negrita:
        cuerpo = f"<b>{cuerpo}</b>"
    destino = PREFIJO + clave + (f"?{quote(detalle, safe='')}" if detalle else "")
    return f"<a href='{destino}' style='color:{color};text-decoration:none'>{cuerpo}</a>"


def enlace_mision(modo: str | None, visible: str, color: str, rotacion: str | None = None) -> str:
    """El tipo de mision de una fila ('Supervivencia') con lo que se hace y como da premios.

    `modo` es el nombre ingles del juego (Survival); `visible`, lo que ya ensenaba la
    fila. Si el modo no esta en modos_mision se pinta tal cual, sin tooltip: mejor nada
    que una explicacion generica que no dice que hacer en esa mision concreta.
    """
    detalle = modos_mision.explicacion(modo, rotacion)
    if not detalle:
        return html.escape(visible)
    return enlace("mision", visible, color, detalle=detalle)


def enlace_rotacion(modo: str | None, rotacion: str, visible: str, color: str) -> str:
    """'Rotacion C (min 20)' explicando cuando llega esa rotacion en ESE modo; si no, la generica.

    El parentesis dice a la vista cuando cae esa letra en ese modo, sin tener que pasar
    el raton: quien juega no sabe que en Supervivencia la C es el minuto 20. Si el modo
    no tiene una regla clara, se queda solo 'Rotacion C'.
    """
    corta = modos_mision.rotacion_corta(modo, rotacion)
    if corta:
        visible = f"{visible} ({corta})"
    return enlace("rotacion", visible, color, detalle=modos_mision.explicacion_rotacion(modo, rotacion))


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
