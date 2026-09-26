"""Recorrido guiado dentro de la ventana: una capa encima que resalta cada zona.

Se lanza sola la primera vez que la ventana esta lista (ver `VentanaOverlay.mostrar_guia`
y `_datos_listos`) o a mano con el boton "Guia" de la cabecera. Siempre se puede saltar
con el boton o con Escape.

Estilo C: la burbuja es un panel con esquinas cortadas y filete de acento (rombo y
titulo en mayusculas, botones C) y el hueco resaltado lleva el mismo corte en las
esquinas, con un remate dorado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QScrollArea, QWidget

from .. import NOMBRE_APP
from ..idiomas import t
from .estilo_c import BotonC, EtiquetaC, PanelC, Rombo, fila, px, ruta_chaflan
from .widgets import PALETA

# Margen alrededor del widget resaltado y tamano maximo de la burbuja: con esto no se
# sale de la ventana ni en el minimo de la vista completa (760x420).
MARGEN_RESALTE = 6
ANCHO_BURBUJA = 340
GLIFO_ATRAS = "\ue72b"
MARGEN_VENTANA = 12


@dataclass
class Paso:
    titulo: str
    cuerpo: str
    # Pagina que hay que abrir antes de resaltar (o None): cualquier destino que acepte
    # `VentanaOverlay.ir_a` ("tablero", "metas/primes" o el atributo, como "primes").
    pestana: str | None
    # Funcion(ventana) -> QWidget a resaltar (o una tupla de widgets, que se resaltan
    # juntos en un solo recuadro), o None para un paso sin resalte (centrado).
    objetivo: Callable[[object], QWidget | tuple[QWidget, ...] | None] | None


def _en_ajustes(ventana, seccion: str, *nombres: str):
    """Widgets de Ajustes a resaltar, abriendo antes su seccion (Ajustes va por
    secciones en una columna y lo de las demas no se ve)."""
    ajustes = getattr(ventana, "ajustes", None)
    if ajustes is None:
        return None
    if hasattr(ajustes, "ir_a"):
        ajustes.ir_a(seccion)
    widgets = tuple(w for w in (getattr(ajustes, n, None) for n in nombres) if w is not None)
    if not widgets:
        return None
    return widgets[0] if len(widgets) == 1 else widgets


def _pasos(ventana) -> list[Paso]:
    """Textos y objetivos de cada paso. Se recalcula en cada arranque de la guia para que
    salga siempre en el idioma activo y con el atajo que el usuario tenga configurado."""
    atajo = ventana.config.get("hotkey_overlay", "Ctrl+Alt+W")
    return [
        Paso(
            titulo=t("Bienvenido a Farmadex"),
            cuerpo=t(
                "Esta ventana se abre y se cierra encima del juego con {atajo} (o con Escape "
                "para cerrarla). Esta guía rápida te enseña las partes principales; se puede "
                "saltar en cualquier momento.",
                atajo=atajo,
            )
            + " "
            + t(
                "Farmadex solo mira la pantalla y el registro del juego, pero DE no respalda "
                "ningún programa de terceros: el aviso completo está en Ajustes > {boton}.",
                boton=t("Acerca de {app}", app=NOMBRE_APP),
            ),
            pestana=None,
            objetivo=None,
        ),
        Paso(
            titulo=t("Tablero||menu"),
            cuerpo=t(
                "Farmadex se abre aquí. \"Tu siguiente paso\" es la pieza de tus metas que antes puedes "
                "conseguir: qué reliquia es, dónde sale y en qué fisura abrirla. Al lado, las fisuras "
                "abiertas que te sirven; debajo, tus metas y los ciclos del mundo."
            ),
            pestana="tablero",
            objetivo=lambda v: getattr(getattr(v, "tablero", None), "heroe", None),
        ),
        Paso(
            titulo=t("El menú"),
            cuerpo=t(
                "Arriba están las secciones: Buscar, Mis metas (tus objetivos, los primes y tu perfil), "
                "Mundo, Herramientas (build, agrietados, vídeo y web) y Ajustes. Las que tienen varias "
                "partes las enseñan justo debajo del menú."
            ),
            pestana=None,
            objetivo=lambda v: getattr(v, "menu", None),
        ),
        Paso(
            titulo=t("Buscar"),
            cuerpo=t(
                "Escribe aquí cualquier objeto, pieza, mod o reliquia, aunque tenga alguna "
                "errata. La ficha te dice dónde conseguirlo, con los sitios ordenados por el "
                "tiempo medio que se tarda en cada uno."
            ),
            pestana="buscador",
            objetivo=lambda v: getattr(v.buscador, "caja", None),
        ),
        Paso(
            titulo=t("Misiones y preguntas"),
            cuerpo=t(
                "También puedes escribir una misión (Hepit, Olimpo) o un tipo de misión "
                "(supervivencia, disrupción): te explica cómo se juega y qué da cada rotación. "
                "Y puedes preguntar como hablas: \"como sacar citrine prime\", \"el último "
                "warframe\" o \"novedades\". Con la caja vacía, aquí ves lo último que ha salido."
            ),
            pestana="buscador",
            objetivo=lambda v: getattr(v.buscador, "ficha", None),
        ),
        Paso(
            titulo=t("Wiki y vídeos"),
            cuerpo=t(
                "\"Buscar en la wiki\" abre la wiki oficial de lo que tengas abierto, para lo que "
                "Farmadex no cuenta (habilidades, cómo se construye...). \"Guías en YouTube\" "
                "busca vídeos de esa misión u objeto y te los pone en Herramientas > Vídeo."
            ),
            pestana="buscador",
            objetivo=lambda v: tuple(
                w for w in (getattr(v.buscador, "boton_wiki", None), getattr(v.buscador, "boton_youtube", None))
                if w is not None
            ) or None,
        ),
        Paso(
            titulo=t("Objetivos"),
            cuerpo=t(
                "Con \"+ Objetivo\" (o \"+ Set completo\" para un Prime entero) añades lo que "
                "estás viendo a tu lista de objetivos, con barra de progreso y la mejor ruta "
                "para conseguirlo ahora mismo."
            ),
            pestana="buscador",
            objetivo=lambda v: getattr(v.buscador, "boton_objetivo", None),
        ),
        Paso(
            titulo=t("Tus objetivos"),
            cuerpo=t(
                "Aquí se quedan apuntados, con su progreso y la reliquia o el sitio directo "
                "donde farmear cada uno ahora mismo. A la derecha, \"Para esto te sirve hoy\" te "
                "dice qué fisuras, invasiones, alertas o cosas de Baro abiertas ahora te sirven."
            ),
            pestana="objetivos",
            objetivo=lambda v: getattr(v, "objetivos", None),
        ),
        Paso(
            titulo=t("Ordenar tus objetivos"),
            cuerpo=t(
                "Arriba los separas en Sin empezar, En progreso y Completados, y puedes filtrar por "
                "categoría (sets, recursos, armas...). En cada uno pones cuántos quieres y sumas "
                "varios de golpe; un set se despliega con un clic para ver sus piezas, y en un arma "
                "puedes apuntar sus recursos de fabricación por separado. Antes de borrar, Farmadex "
                "te pregunta, y puedes marcar varios para quitarlos juntos."
            ),
            pestana="objetivos",
            objetivo=lambda v: tuple(
                w for w in (getattr(v.objetivos, "estados", None), getattr(v.objetivos, "filtro", None))
                if w is not None
            ) or None,
        ),
        Paso(
            titulo=t("Primes"),
            cuerpo=t(
                "Marca las piezas prime que te faltan y pulsa \"Dónde farmear\": te dice en qué "
                "reliquias salen y dónde conseguirlas antes. Lo que marcas aquí se apunta "
                "también en tus objetivos."
            ),
            pestana="primes",
            objetivo=lambda v: getattr(v, "primes", None),
        ),
        Paso(
            titulo=t("Mundo"),
            cuerpo=t(
                "Lo que pasa ahora en el juego, en cuatro partes: Todo, Fisuras, Baro y Teshin, e "
                "Invasiones y alertas. Fisuras del Vacío, ciclos, invasiones, arbitraje y demás, "
                "marcando lo que sirve para tus objetivos pendientes."
            ),
            pestana="mundo",
            objetivo=lambda v: getattr(v, "mundo", None),
        ),
        Paso(
            titulo=t("Avisos del mundo"),
            cuerpo=t(
                "En \"Personalizar y avisos\" eliges que te avise Windows aunque tengas la ventana "
                "escondida: cuando llega Baro, cuando hay una fisura o una invasión que te interesa, "
                "la noche en Cetus... Ahí también ocultas los bloques que no uses. Las facciones se "
                "eligen en Fisuras, con el botón \"Facciones\". Y si pulsas una recompensa, se abre "
                "su ficha."
            ),
            pestana="mundo",
            objetivo=lambda v: getattr(getattr(v, "mundo", None), "boton_personalizar", None),
        ),
        Paso(
            titulo=t("Vídeo"),
            cuerpo=t(
                "Aquí se ven las guías de YouTube sin salir de Farmadex, por si juegas con un "
                "solo monitor. Con \"Modo vídeo\" la ventana se queda solo con el vídeo, encima "
                "del juego, y con \"Salir del vídeo\" vuelves a la vista normal."
            ),
            pestana="video",
            # La barra de botones del panel, no el panel entero: si no, la burbuja tapa el
            # texto que dice como abrir una guia.
            objetivo=lambda v: tuple(
                w for w in (
                    getattr(getattr(v, "video", None), "boton_modo", None),
                    getattr(getattr(v, "video", None), "boton_cerrar", None),
                ) if w is not None
            ) or None,
        ),
        Paso(
            titulo=t("Recompensas de reliquia"),
            cuerpo=t(
                "Con Warframe en Ventana sin bordes (o ventana normal), al abrir una reliquia "
                "Farmadex lee sola sus recompensas y las pinta encima. Aquí se activa o se "
                "desactiva esa lectura automática, y un poco más abajo se elige si se enseñan "
                "como etiquetas pequeñas o como un panel, y que destacar en grande: lo que te "
                "falta, el platino o los ducados."
            ),
            pestana="ajustes",
            objetivo=lambda v: _en_ajustes(v, "reliquias", "ocr_auto"),
        ),
        Paso(
            titulo=t("Perfil"),
            cuerpo=t(
                "Importa tu perfil de Warframe (el fichero JSON) para ver tu rango de "
                "maestría, lo que te falta por dominar y tu progreso por categoría. Con el "
                "perfil importado, Buscar y las etiquetas de recompensas dicen si ya lo tienes."
            ),
            pestana="perfil",
            objetivo=lambda v: getattr(v, "perfil", None),
        ),
        Paso(
            titulo=t("Build"),
            cuerpo=t(
                "Abre en el juego la pantalla de mejoras de un warframe o un arma y "
                "pulsa {atajo}: Farmadex lee sus mods y arcanos y los lista aquí. "
                "Pulsas uno y te dice de dónde sale.",
                atajo=ventana.config.get("hotkey_build", "Ctrl+Alt+B"),
            ),
            pestana="builds",
            # El boton de leer y su atajo, a la derecha de las sub-pestanas de Herramientas.
            objetivo=lambda v: tuple(
                w for w in (getattr(getattr(v, "builds", None), "boton", None),
                            getattr(getattr(v, "builds", None), "tecla_atajo", None))
                if w is not None
            ) or None,
        ),
        Paso(
            titulo=t("Agrietados"),
            cuerpo=t(
                "Para saber si un mod agrietado es bueno: pon el ratón sobre la tarjeta en el juego y "
                "pulsa {atajo}, o apunta sus estadísticas a mano. Te da la nota de cada una, de S (lo "
                "mejor) a F, entre qué valores puede salir y un precio de referencia en warframe.market.",
                atajo=ventana.config.get("hotkey_agrietado", "Ctrl+Alt+G"),
            ),
            pestana="agrietados",
            objetivo=lambda v: tuple(
                w for w in (getattr(getattr(v, "agrietados", None), "boton_leer", None),
                            getattr(getattr(v, "agrietados", None), "tecla_atajo", None))
                if w is not None
            ) or None,
        ),
        Paso(
            titulo=t("Modo juego"),
            cuerpo=t(
                "Con Ctrl+M (o este botón) la ventana pasa a una cajita pensada para jugar o "
                "para un directo, con solo la búsqueda y lo esencial. Pulsa un resultado y sus "
                "detalles se despliegan debajo, y con \"Fijar\" se queda siempre encima del juego. "
                "La ventana se mueve y cambia de tamaño arrastrando desde cualquier borde."
            ),
            pestana=None,
            objetivo=lambda v: getattr(v, "boton_modo", None),
        ),
        Paso(
            titulo=t("Ajustes"),
            cuerpo=t(
                "A la izquierda eliges la sección: General (idioma, actualizaciones, arrancar con "
                "Windows), Atajos, Apariencia (colores y tamaño de letra), Reliquias, Datos del juego "
                "y Ayuda, donde puedes volver a ver la bienvenida."
            ),
            pestana="ajustes",
            objetivo=lambda v: getattr(getattr(v, "ajustes", None), "secciones", None)
            or getattr(v, "ajustes", None),
        ),
        Paso(
            titulo=t("A tu gusto"),
            cuerpo=t(
                "En Apariencia haces la ventana y la letra más grandes o más pequeñas y cambias "
                "cualquier color. Lo ves antes en la vista previa, y solo se aplica al pulsar "
                "Guardar; \"Volver a lo de fábrica\" lo deja todo como estaba."
            ),
            pestana="ajustes",
            objetivo=lambda v: _en_ajustes(v, "aspecto", "escala_interfaz", "escala_letra"),
        ),
        Paso(
            titulo=t("Si no sale nada al abrir una reliquia"),
            cuerpo=t(
                "Pulsa \"Comprobar la lectura de reliquias\": te dice paso a paso qué falla. Si "
                "no lo arreglas, \"Guardar informe para enviar\" deja un archivo para mandarlo a "
                "quien te ayude; no lleva nada de tu cuenta."
            ),
            pestana="ajustes",
            objetivo=lambda v: _en_ajustes(v, "reliquias", "boton_diagnostico", "boton_informe"),
        ),
    ]


def _traer_a_la_vista(widget: QWidget) -> None:
    """Si el widget vive dentro de un QScrollArea, desplaza el area hasta ensenarlo."""
    padre = widget.parentWidget()
    while padre is not None:
        if isinstance(padre, QScrollArea):
            padre.ensureWidgetVisible(widget, 20, 20)
            return
        padre = padre.parentWidget()


class CapaGuia(QWidget):
    """Capa translucida sobre toda la ventana, con un agujero sobre lo que se explica."""

    def __init__(self, ventana):
        super().__init__(ventana)
        self.ventana = ventana
        self._pasos = _pasos(ventana)
        self._indice = 0
        self._rect_resalte: QRect | None = None

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)

        # Burbuja en estilo C: panel con esquinas cortadas y filete de acento.
        self.burbuja = PanelC(fondo="panel", borde="acento", parent=self)
        self.burbuja.setObjectName("burbujaGuia")
        self.burbuja.poner_marcado(True)
        self.burbuja.setFixedWidth(px(ANCHO_BURBUJA, False))

        self.titulo = EtiquetaC("", "seccion", tinta="acento", mayus=True, envolver=True)
        self.cuerpo = EtiquetaC("", "normal", envolver=True)
        self.contador = EtiquetaC("", "pequeno")

        self.boton_saltar = BotonC(t("Saltar guía"), tam=10)
        self.boton_saltar.clicked.connect(self.saltar)
        self.boton_atras = BotonC(t("Atrás"), icono=GLIFO_ATRAS, tam=10)
        self.boton_atras.clicked.connect(self.atras)
        self.boton_siguiente = BotonC(principal=True, icono="derecha", tam=10)
        self.boton_siguiente.clicked.connect(self.siguiente)

        dentro = self.burbuja.capa
        dentro.setContentsMargins(px(16, False), px(12, False), px(16, False), px(14, False))
        dentro.setSpacing(px(8, False))
        dentro.addLayout(fila(Rombo(8, "acento"), self.titulo, espacio=px(8, False)))
        dentro.addWidget(self.cuerpo)
        dentro.addWidget(self.contador)
        dentro.addLayout(fila(self.boton_saltar, None, self.boton_atras, self.boton_siguiente, espacio=px(6, False)))

        self.setGeometry(ventana.rect())
        self._ir_a_paso(0)
        self.show()
        self.raise_()
        self.setFocus()

    # -- navegacion -----------------------------------------------------------

    def _ir_a_paso(self, indice: int) -> None:
        self._indice = max(0, min(indice, len(self._pasos) - 1))
        paso = self._pasos[self._indice]
        if paso.pestana is not None:
            self.ventana.ir_a(paso.pestana)
        self.titulo.setText(paso.titulo)
        self.cuerpo.setText(paso.cuerpo)
        self.contador.setText(t("Paso {n} de {total}", n=self._indice + 1, total=len(self._pasos)))
        self.boton_atras.setEnabled(self._indice > 0)
        ultimo = self._indice == len(self._pasos) - 1
        self.boton_siguiente.setText(t("Terminar") if ultimo else t("Siguiente"))
        self.reposicionar()

    def atras(self) -> None:
        self._ir_a_paso(self._indice - 1)

    def siguiente(self) -> None:
        if self._indice >= len(self._pasos) - 1:
            self.terminar()
        else:
            self._ir_a_paso(self._indice + 1)

    def saltar(self) -> None:
        self.terminar()

    def terminar(self) -> None:
        from ..config import guardar

        self.ventana.config["guia_vista"] = True
        self.ventana.config["guia_aviso_visto"] = True
        guardar(self.ventana.config)
        if getattr(self.ventana, "_guia", None) is self:
            self.ventana._guia = None
        # hide() antes: deleteLater() solo programa el borrado del objeto, no lo quita
        # de la pantalla, y si se lanza la guia otra vez enseguida (el boton "Guia",
        # o esta misma capa por error) se verian dos burbujas superpuestas.
        self.hide()
        self.deleteLater()

    # -- geometria --------------------------------------------------------------

    def reposicionar(self) -> None:
        """Recalcula el agujero y la burbuja: al cambiar de paso o al redimensionar la
        ventana. El objetivo puede estar en una pestana que se acaba de activar, asi que
        primero se procesan eventos pendientes para que ya tenga geometria valida."""
        self.setGeometry(self.ventana.rect())
        from PySide6.QtWidgets import QApplication

        QApplication.instance().processEvents()
        paso = self._pasos[self._indice]
        objetivo = paso.objetivo(self.ventana) if paso.objetivo else None
        widgets = objetivo if isinstance(objetivo, tuple) else (objetivo,)
        visibles = [w for w in widgets if w is not None and w.isVisible()]
        self._rect_resalte = None
        if visibles:
            # Lo que esta al fondo de un area con scroll (el diagnostico en Ajustes) se
            # trae a la vista antes de medirlo; si no, el agujero caeria fuera.
            for w in visibles:
                _traer_a_la_vista(w)
            QApplication.instance().processEvents()
            union = QRect()
            for w in visibles:
                union = union.united(QRect(w.mapTo(self.ventana, QPoint(0, 0)), w.size()))
            bruto = union.adjusted(
                -MARGEN_RESALTE, -MARGEN_RESALTE, MARGEN_RESALTE, MARGEN_RESALTE
            )
            # Un widget dentro de un area con scroll (Ajustes en la ventana minima) puede
            # devolver una geometria mas ancha que la propia ventana: sin recortar, el
            # agujero y su borde saldrian fuera. Si tras recortar casi no queda nada, mejor
            # sin resalte (burbuja centrada) que un agujero irreconocible.
            recortado = bruto.intersected(self.rect())
            if recortado.width() > 20 and recortado.height() > 10:
                self._rect_resalte = recortado
        self._colocar_burbuja()
        self.update()

    def _colocar_burbuja(self) -> None:
        self.burbuja.adjustSize()
        # adjustSize no siempre cuenta todas las lineas del texto partido: con un cuerpo
        # largo la burbuja se quedaba corta y cortaba la ultima frase.
        if self.burbuja.hasHeightForWidth():
            necesario = self.burbuja.heightForWidth(self.burbuja.width())
            if necesario > self.burbuja.height():
                self.burbuja.resize(self.burbuja.width(), necesario)
        alto = self.burbuja.height()
        ancho = self.burbuja.width()
        area = self.rect()
        if self._rect_resalte is None:
            x = area.center().x() - ancho // 2
            y = area.center().y() - alto // 2
        else:
            r = self._rect_resalte
            x = r.left()
            y = r.bottom() + 12
            if y + alto > area.bottom() - MARGEN_VENTANA:
                y = r.top() - alto - 12
            if y < MARGEN_VENTANA:
                # Ni encima ni debajo caben (objetivo muy alto): al lado, o centrado si
                # tampoco cabe a los lados.
                y = max(MARGEN_VENTANA, min(r.center().y() - alto // 2, area.bottom() - alto - MARGEN_VENTANA))
                x = r.right() + 12
                if x + ancho > area.right() - MARGEN_VENTANA:
                    x = r.left() - ancho - 12
        x = max(MARGEN_VENTANA, min(x, area.right() - ancho - MARGEN_VENTANA))
        y = max(MARGEN_VENTANA, min(y, area.bottom() - alto - MARGEN_VENTANA))
        self.burbuja.move(x, y)

    # -- pintado y teclado --------------------------------------------------------

    def paintEvent(self, evento) -> None:  # noqa: N802 - firma de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        camino = QPainterPath()
        camino.addRect(float(self.rect().x()), float(self.rect().y()), float(self.rect().width()), float(self.rect().height()))
        hueco = None
        if self._rect_resalte is not None:
            # El hueco con las esquinas cortadas, como los paneles del estilo C.
            r = QRectF(self._rect_resalte).adjusted(0.5, 0.5, -0.5, -0.5)
            corte = min(10.0, r.width() / 4, r.height() / 4)
            hueco = ruta_chaflan(r, corte)
            camino = camino.subtracted(hueco)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawPath(camino)
        if hueco is not None:
            acento = QColor(PALETA["acento"])
            painter.setPen(QPen(acento, 1.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(hueco)
            # Remate dorado arriba a la izquierda y abajo a la derecha.
            largo = min(40.0, r.width() / 4)
            painter.setPen(QPen(acento, 2.5))
            painter.drawLine(QPointF(r.left() + corte, r.top()), QPointF(r.left() + corte + largo, r.top()))
            painter.drawLine(QPointF(r.right() - corte - largo, r.bottom()), QPointF(r.right() - corte, r.bottom()))

    def event(self, evento) -> bool:  # noqa: N802 - firma de Qt
        # Escape tiene que saltar la guia, no cerrar el overlay: se corta aqui, antes de
        # que el QShortcut de la ventana (Escape -> ocultar) llegue a activarse.
        if evento.type() == QEvent.ShortcutOverride and evento.key() == Qt.Key_Escape:
            evento.accept()
            return True
        return super().event(evento)

    def keyPressEvent(self, evento) -> None:  # noqa: N802 - firma de Qt
        if evento.key() == Qt.Key_Escape:
            self.saltar()
            return
        super().keyPressEvent(evento)
