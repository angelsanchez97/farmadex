"""Recorrido guiado dentro de la ventana: una capa encima que resalta cada zona.

Se lanza sola la primera vez que la ventana esta lista (ver `VentanaOverlay.mostrar_guia`
y `_datos_listos`) o a mano con el boton "Guia" de la cabecera. Siempre se puede saltar
con el boton o con Escape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import NOMBRE_APP
from ..idiomas import t
from .widgets import PALETA

# Margen alrededor del widget resaltado y tamano maximo de la burbuja: con esto no se
# sale de la ventana ni en el minimo de la vista completa (760x420).
MARGEN_RESALTE = 6
ANCHO_BURBUJA = 320
MARGEN_VENTANA = 12


@dataclass
class Paso:
    titulo: str
    cuerpo: str
    # Atributo de VentanaOverlay que hay que activar en pestanas antes de resaltar (o None).
    pestana: str | None
    # Funcion(ventana) -> QWidget a resaltar (o una tupla de widgets, que se resaltan
    # juntos en un solo recuadro), o None para un paso sin resalte (centrado).
    objetivo: Callable[[object], QWidget | tuple[QWidget, ...] | None] | None


def _pasos(ventana) -> list[Paso]:
    """Textos y objetivos de cada paso. Se recalcula en cada arranque de la guia para que
    salga siempre en el idioma activo y con el atajo que el usuario tenga configurado."""
    atajo = ventana.config.get("hotkey_overlay", "Ctrl+Alt+W")
    return [
        Paso(
            titulo=t("Bienvenido a Farmadex"),
            cuerpo=t(
                "Esta ventana se abre y se cierra encima del juego con {atajo} (o con Escape "
                "para cerrarla). Esta guia rapida te ensena las partes principales; se puede "
                "saltar en cualquier momento.",
                atajo=atajo,
            )
            + " "
            + t(
                "Farmadex solo mira la pantalla y el registro del juego, pero DE no respalda "
                "ningun programa de terceros: el aviso completo esta en Ajustes > {boton}.",
                boton=t("Acerca de {app}", app=NOMBRE_APP),
            ),
            pestana=None,
            objetivo=None,
        ),
        Paso(
            titulo=t("Buscar"),
            cuerpo=t(
                "Escribe aqui cualquier objeto, pieza, mod o reliquia, aunque tenga alguna "
                "errata. La ficha te dice donde conseguirlo, con los sitios ordenados por el "
                "tiempo medio que se tarda en cada uno."
            ),
            pestana="buscador",
            objetivo=lambda v: getattr(v.buscador, "caja", None),
        ),
        Paso(
            titulo=t("Misiones y preguntas"),
            cuerpo=t(
                "Tambien puedes escribir una mision (Hepit, Olimpo) o un tipo de mision "
                "(supervivencia, disrupcion): te explica como se juega y que da cada rotacion. "
                "Y puedes preguntar como hablas: \"como sacar citrine prime\", \"el ultimo "
                "warframe\" o \"novedades\". Con la caja vacia, aqui ves lo ultimo que ha salido."
            ),
            pestana="buscador",
            objetivo=lambda v: getattr(v.buscador, "ficha", None),
        ),
        Paso(
            titulo=t("Wiki y videos"),
            cuerpo=t(
                "\"Buscar en la wiki\" abre la wiki oficial de lo que tengas abierto, para lo que "
                "Farmadex no cuenta (habilidades, como se construye...). \"Guias en YouTube\" "
                "busca videos de esa mision u objeto y te los pone en la pestana Video."
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
                "Con \"+ Objetivo\" (o \"+ Set completo\" para un Prime entero) anades lo que "
                "estas viendo a tu lista de objetivos, con barra de progreso y la mejor ruta "
                "para conseguirlo ahora mismo."
            ),
            pestana="buscador",
            objetivo=lambda v: getattr(v.buscador, "boton_objetivo", None),
        ),
        Paso(
            titulo=t("Tus objetivos"),
            cuerpo=t(
                "Aqui se quedan apuntados, con su progreso y la reliquia o el sitio directo "
                "donde farmear cada uno ahora mismo."
            ),
            pestana="objetivos",
            objetivo=lambda v: getattr(v, "objetivos", None),
        ),
        Paso(
            titulo=t("Primes"),
            cuerpo=t(
                "Marca las piezas prime que te faltan y pulsa \"Donde farmear\": te dice en que "
                "reliquias salen y donde conseguirlas antes. Lo que marcas aqui se apunta "
                "tambien en tus objetivos."
            ),
            pestana="primes",
            objetivo=lambda v: getattr(v, "primes", None),
        ),
        Paso(
            titulo=t("Mundo"),
            cuerpo=t(
                "Fisuras del Vacio abiertas, los ciclos de Cetus, el Valle del Orbe y Cambion, "
                "invasiones, arbitracion y demas: que hacer ahora mismo, marcando lo que sirve "
                "para tus objetivos pendientes."
            ),
            pestana="mundo",
            objetivo=lambda v: getattr(v, "mundo", None),
        ),
        Paso(
            titulo=t("Video"),
            cuerpo=t(
                "Aqui se ven las guias de YouTube sin salir de Farmadex, por si juegas con un "
                "solo monitor. Con \"Modo video\" la ventana se queda solo con el video, encima "
                "del juego, y con \"Salir del video\" vuelves a la vista normal."
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
                "Farmadex lee sola sus recompensas y las pinta encima. Aqui se activa o se "
                "desactiva esa lectura automatica, y un poco mas abajo se elige si se ensenan "
                "como etiquetas pequenas o como un panel."
            ),
            pestana="ajustes",
            objetivo=lambda v: getattr(getattr(v, "ajustes", None), "ocr_auto", None),
        ),
        Paso(
            titulo=t("Perfil"),
            cuerpo=t(
                "Importa tu perfil de Warframe (el fichero JSON) para ver tu rango de "
                "maestria, lo que te falta por dominar y tu progreso por categoria. Con el "
                "perfil importado, Buscar y las etiquetas de recompensas dicen si ya lo tienes."
            ),
            pestana="perfil",
            objetivo=lambda v: getattr(v, "perfil", None),
        ),
        Paso(
            titulo=t("Modo compacto"),
            cuerpo=t(
                "Con Ctrl+M (o este boton) la ventana pasa a una cajita pensada para jugar o "
                "para un directo, con solo la busqueda y lo esencial. Los bordes de la ventana "
                "se pueden arrastrar para cambiar el tamano, en los dos modos."
            ),
            pestana=None,
            objetivo=lambda v: getattr(v, "boton_modo", None),
        ),
        Paso(
            titulo=t("Ajustes"),
            cuerpo=t(
                "Tema de color, idioma, atajos de teclado, como se comprueban las "
                "actualizaciones y si Farmadex arranca solo con Windows: todo se cambia aqui, "
                "casi siempre al momento."
            ),
            pestana="ajustes",
            objetivo=lambda v: getattr(v, "ajustes", None),
        ),
        Paso(
            titulo=t("Si no sale nada al abrir una reliquia"),
            cuerpo=t(
                "Pulsa \"Comprobar la lectura de reliquias\": te dice paso a paso que falla. Si "
                "no lo arreglas, \"Guardar informe para enviar\" deja un archivo para mandarlo a "
                "quien te ayude; no lleva nada de tu cuenta."
            ),
            pestana="ajustes",
            objetivo=lambda v: tuple(
                w for w in (
                    getattr(getattr(v, "ajustes", None), "boton_diagnostico", None),
                    getattr(getattr(v, "ajustes", None), "boton_informe", None),
                ) if w is not None
            ) or None,
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

        self.burbuja = QFrame(self)
        self.burbuja.setObjectName("burbujaGuia")
        self.burbuja.setFixedWidth(ANCHO_BURBUJA)
        self.burbuja.setStyleSheet(
            f"#burbujaGuia {{ background: {PALETA['panel']}; border: 1px solid {PALETA['acento']};"
            " border-radius: 10px; }}"
        )

        self.titulo = QLabel()
        self.titulo.setWordWrap(True)
        self.titulo.setStyleSheet(f"color: {PALETA['acento']}; font-weight: 700; font-size: 15px;")
        self.cuerpo = QLabel()
        self.cuerpo.setWordWrap(True)
        self.cuerpo.setStyleSheet(f"color: {PALETA['texto']}; font-size: 13px;")
        self.contador = QLabel()
        self.contador.setStyleSheet(f"color: {PALETA['suave']}; font-size: 11px;")

        self.boton_saltar = QPushButton(t("Saltar guia"))
        self.boton_saltar.clicked.connect(self.saltar)
        self.boton_atras = QPushButton(t("Atras"))
        self.boton_atras.clicked.connect(self.atras)
        self.boton_siguiente = QPushButton()
        self.boton_siguiente.setObjectName("principal")
        self.boton_siguiente.clicked.connect(self.siguiente)

        botones = QHBoxLayout()
        botones.addWidget(self.boton_saltar)
        botones.addStretch(1)
        botones.addWidget(self.boton_atras)
        botones.addWidget(self.boton_siguiente)

        dentro = QVBoxLayout(self.burbuja)
        dentro.setContentsMargins(14, 12, 14, 12)
        dentro.setSpacing(6)
        dentro.addWidget(self.titulo)
        dentro.addWidget(self.cuerpo)
        dentro.addWidget(self.contador)
        dentro.addLayout(botones)

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
            pestana = getattr(self.ventana, paso.pestana, None)
            if pestana is not None:
                self.ventana.pestanas.setCurrentWidget(pestana)
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
        if self._rect_resalte is not None:
            sub = QPainterPath()
            sub.addRoundedRect(self._rect_resalte, 8, 8)
            camino = camino.subtracted(sub)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawPath(camino)
        if self._rect_resalte is not None:
            painter.setPen(QColor(PALETA["acento"]))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self._rect_resalte, 8, 8)

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
