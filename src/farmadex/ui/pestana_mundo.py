"""Pestana Mundo (rediseno C): que hago ahora mismo en el juego.

Cuatro sub-pestanas: TODO (de un vistazo), FISURAS (todas, en columnas por era),
BARO Y TESHIN (las dos tiendas que cambian) e INVASIONES Y ALERTAS (con la incursion,
los arcontes, el arbitraje y la onda nocturna). Sustituyen al selector Lista/Tablero
de antes; la clave `diseno_mundo` guarda ahora la sub-pestana ("lista" y "tablero"
abren TODO).

Lo que sirve para tus metas va con borde dorado y ★; lo que caduca pronto, en naranja;
lo terminado, fuera. Todo el texto se puede seleccionar y copiar, las recompensas
abren su ficha en Buscar y "Personalizar y avisos" elige que bloques se ven y de que
avisa Windows.
"""

from __future__ import annotations

import html
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import cargar, guardar
from ..idiomas import glosa, t
from ..online import avisos_mundo
from ..online import worldstate as ws
from ..online.worldstate import Fisura, Mundo
from ..registro_log import obtener
from . import glosario
from .estilo_c import (
    COLOR_ERA,
    BotonC,
    EtiquetaC,
    EtiquetaEra,
    PanelC,
    Rombo,
    SubPestanasC,
    color,
    columna,
    fila,
    icono,
    px,
    transparente,
)
from .personalizar_mundo import PanelPersonalizar, ocultas
from .widgets import PALETA

log = obtener("mundo")

# Claves internas; lo que se ensena es su traduccion.
ERAS = ("Todas", "Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia")
# Una columna por era en el panel de fisuras; Omnia (y cualquier era nueva) va en la nota.
ERAS_COLUMNAS = ("Lith", "Meso", "Neo", "Axi", "Requiem")
# Botones de tipo de fisura: texto -> clave interna (mismo orden).
MODOS = ("Normales", "Camino de Acero", "Tormentas")
CLAVES_MODO = ("normal", "acero", "tormenta")
MODOS_POR_DEFECTO = ("normal",)
CLAVE_MODOS = "mundo_modos_fisura"
# Que bloque de "Personalizar" esconde cada tipo de fisura.
SECCION_MODO = {"normal": "fisuras", "acero": "acero", "tormenta": "tormentas"}

SUBPESTANAS = (
    ("todo", "Todo"),
    ("fisuras", "Fisuras"),
    ("tienda", "Baro y Teshin"),
    ("eventos", "Invasiones y alertas"),
)
TITULOS = {
    "objetivos": "Fisuras para tus metas",
    "fisuras": "Fisuras del Vacío",
    "baro": "Baro Ki'Teer",
    "teshin": "Teshin · Camino de Acero",
    "hoy": "Hoy",
    "invasiones": "Invasiones",
    "alertas": "Alertas",
    "arbitraje": "Arbitraje",
    "ciclos": "Ciclos",
    "sortie": "Incursión y arcontes",
    "nightwave": "Onda nocturna",
}
DISENOS = tuple(clave for clave, _ in SUBPESTANAS)
DISENO_POR_DEFECTO = "todo"
CLAVE_DISENO = "diseno_mundo"
# Valores de antes del rediseno C (selector Lista/Tablero): los dos abren TODO.
DISENOS_ANTIGUOS = {"lista": "todo", "tablero": "todo"}
CLAVE_FACCIONES = "mundo_facciones"
# Facciones de las fisuras: clave interna -> nombre en la interfaz y color del nombre.
# Colores fijos (no del tema): se reconocen igual con cualquier tema, como en el juego.
FACCIONES = (
    ("grineer", "Grineer", "#ef7d5a", "Grineer"),
    ("corpus", "Corpus", "#5eb3f0", "Corpus"),
    ("infested", "Infestados", "#86cf6c", "Infested"),
    ("orokin", "Orokin", "#e6c464", "Orokin"),
    ("murmur", "Murmullo", "#bd92ec", "Murmur"),
    ("crossfire", "Fuego cruzado", "#d0d0d0", "Crossfire"),
    ("narmer", "Narmer", "#ec98bd", "Narmer"),
)
COLORES_FACCION = {clave: color_f for clave, _, color_f, _en in FACCIONES}
# La leyenda de colores siempre ensena estas (las que mas salen) y las demas si aparecen.
FACCIONES_LEYENDA = ("grineer", "corpus", "infested", "crossfire")
# Lo que manda la API (ingles) o el glosario (espanol) -> clave de FACCIONES.
_ALIAS_FACCION = {
    "infestation": "infested", "infestados": "infested", "infestado": "infested",
    "corrupted": "orokin", "corruptos": "orokin", "corrupto": "orokin",
    "sentient": "murmur", "sintientes": "murmur", "murmullo": "murmur", "the murmur": "murmur",
    "fuego cruzado": "crossfire",
}
# Por debajo de estos minutos la cuenta atras se pinta en naranja.
MINUTOS_URGENTE = 10
# Cuantas cosas ensena TODO antes de mandar a su sub-pestana ("y N mas").
MAX_INVASIONES = 4
MAX_POR_COLUMNA = 4
# En "Fisuras para tus metas" solo las mas rapidas de cada era.
MAX_POR_ERA_OBJETIVOS = 2
# Estados de ciclo que se pintan con la luna (el resto, con el sol).
_NOCHE = {"night", "cold", "fass", "fear", "sorrow"}
# Por debajo de estos anchos (px a escala 1) las filas de paneles se apilan.
ANCHO_FILA_ARRIBA = 1040
ANCHO_FILA_ABAJO = 900
# Misiones rapidas primero: lo que se acaba en tres minutos por delante de lo sin fin.
RAPIDEZ = {
    "capture": 0, "captura": 0,
    "extermination": 1, "exterminate": 1, "exterminio": 1,
    "rescue": 2, "rescate": 2,
    "sabotage": 3, "sabotaje": 3,
    "spy": 4, "espionaje": 4,
    "mobile defense": 5, "defensa movil": 5,
    "assassination": 6, "asesinato": 6, "hijack": 6, "secuestro": 6,
    "disruption": 7, "disrupcion": 7,
    "excavation": 8, "excavacion": 8,
    "defense": 9, "defensa": 9, "survival": 9, "supervivencia": 9,
    "interception": 10, "intercepcion": 10,
}
# Color de la fila de la caza de arcontes en HOY (el rojo de Requiem, como en el juego).
COLOR_ARCONTES = COLOR_ERA["Requiem"]


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def rapidez(mision: str) -> int:
    """0 = se hace en tres minutos; 10 = sin fin. Desconocidas, en medio."""
    return RAPIDEZ.get(_sin_tildes(mision or "").lower().strip(), 6)


def minutos_restantes(expira: datetime | None, ahora: datetime | None = None) -> float | None:
    if not expira:
        return None
    ahora = ahora or datetime.now(timezone.utc)
    return (expira - ahora).total_seconds() / 60


def tiempo_restante(expira: datetime | None, ahora: datetime | None = None) -> str:
    """'45 s', '15 min', '1 h 09 min', '2 d 3 h'; 'terminado' si ya paso; vacio sin fecha."""
    if not expira:
        return ""
    ahora = ahora or datetime.now(timezone.utc)
    segundos = int((expira - ahora).total_seconds())
    if segundos <= 0:
        return "terminado"
    dias, resto = divmod(segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, segs = divmod(resto, 60)
    if dias:
        return f"{dias} d {horas} h"
    if horas:
        return f"{horas} h {minutos:02d} min"
    if minutos:
        return f"{minutos} min"
    return f"{segs} s"


def tiempo_grande(expira: datetime | None) -> str:
    """La cuenta atras en mayusculas para los titulares (LLEGA EN 10 D 21 H)."""
    texto = tiempo_restante(expira)
    return t("terminado") if texto == "terminado" else texto


def _terminado(expira) -> bool:
    return expira is not None and tiempo_restante(expira) == "terminado"


def _restante(expira) -> str:
    """La cuenta atras en HTML: naranja si queda poco; la palabra cuando ya ha pasado."""
    texto = tiempo_restante(expira)
    if texto == "terminado":
        return t("terminado")
    minutos = minutos_restantes(expira)
    if minutos is not None and minutos < MINUTOS_URGENTE:
        return f"<span style='color:{PALETA['aviso']};font-weight:bold'>{texto}</span>"
    return texto


def normalizar_diseno(valor) -> str:
    """La sub-pestana guardada, aceptando los valores de antes (lista/tablero)."""
    valor = DISENOS_ANTIGUOS.get(str(valor or ""), valor)
    return valor if valor in DISENOS else DISENO_POR_DEFECTO


def clave_faccion(fisura) -> str:
    """'grineer', 'corpus'...; vacio si no se sabe de que faccion es."""
    bruto = _sin_tildes(getattr(fisura, "faccion", "") or getattr(fisura, "enemigo", "") or "").lower().strip()
    return _ALIAS_FACCION.get(bruto, bruto)


def color_faccion(nombre: str, defecto: str | None = None) -> str:
    """El color fijo de una faccion por su nombre (en ingles o traducido)."""
    clave = _sin_tildes(nombre or "").lower().strip()
    return COLORES_FACCION.get(_ALIAS_FACCION.get(clave, clave), defecto or PALETA["suave"])


def _esc(texto) -> str:
    """Escapa para el HTML de las etiquetas. Sin tocar las comillas: los atributos van entre
    comillas simples con valores ya codificados, y una etiqueta sin '<' se ensena como texto
    plano, donde un &#x27; saldria tal cual."""
    return html.escape(str(texto or ""), quote=False)


def _recortada(texto: str, rol: str = "normal", tinta: str | None = None) -> EtiquetaC:
    """Etiqueta de una linea que se corta con "..." si no cabe. Se pule antes de medirla:
    si no, mide con la letra por defecto y se corta aunque sobre sitio."""
    etiqueta = EtiquetaC(texto, rol, tinta=tinta, recortar=True)
    etiqueta.ensurePolished()
    etiqueta.updateGeometry()
    return etiqueta


def _partir_nodo(nodo: str) -> tuple[str, str]:
    """'Ukko, Vacio' -> ('Ukko', 'Vacio')."""
    nombre, _coma, planeta = (nodo or "").partition(", ")
    return nombre, planeta


# Texto que se puede seleccionar y copiar con el raton, sin perder los enlaces.
SELECCIONABLE = Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse


def _vaciar_layout(layout) -> None:
    while layout.count():
        elemento = layout.takeAt(0)
        widget = elemento.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif elemento.layout() is not None:
            _vaciar_layout(elemento.layout())


def _encogible(etiqueta: QLabel) -> QLabel:
    """Una etiqueta en una columna estrecha: se recorta antes que ensanchar la pagina."""
    etiqueta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    etiqueta.setMinimumWidth(px(30, False))
    return etiqueta


class Bloque(PanelC):
    """Un panel del mundo con esquinas cortadas: rotulo, un dato a la derecha del titulo
    (`extra`), contenido en `caja` y las cuentas atras que se refrescan cada segundo."""

    def __init__(self, titulo: str, clave: str, remate: bool = True, parent=None):
        super().__init__(titulo, remate=remate, parent=parent)
        self.clave = clave
        self._titulo = titulo
        self.extra = EtiquetaC("", "pequeno")
        self.cabecera.addWidget(self.extra)
        self.caja = QVBoxLayout()
        self.caja.setContentsMargins(0, 0, 0, 0)
        self.caja.setSpacing(px(6, False))
        self.capa.setSpacing(px(8, False))
        self.capa.addLayout(self.caja)
        self.capa.addStretch(1)
        # (etiqueta, funcion que da el texto o None si ya termino, lo que se esconde entonces)
        self.relojes: list[tuple[QLabel, object, QWidget | None]] = []
        self.extra_expira = None
        # Que hacer con un enlace que no es del glosario (item:, buscar:, sub:): lo pone la pestana.
        self.al_activar = None

    # -- titulo --------------------------------------------------------------------

    def title(self) -> str:
        return self._titulo

    def setTitle(self, texto: str) -> None:  # noqa: N802 - mismo nombre que QGroupBox
        self._titulo = texto
        self.poner_titulo(texto)

    # -- contenido ----------------------------------------------------------------

    def limpiar(self) -> None:
        self.relojes.clear()
        self.extra_expira = None
        self.extra.setText("")
        _vaciar_layout(self.caja)

    def preparar(self, etiqueta: QLabel) -> QLabel:
        """Seleccionable, con los enlaces del glosario y los de la pestana."""
        etiqueta.setTextInteractionFlags(SELECCIONABLE)
        etiqueta.setOpenExternalLinks(False)
        etiqueta.linkHovered.connect(lambda url, e=etiqueta: glosario.mostrar(url, e) if url else None)
        etiqueta.linkActivated.connect(self._activar)
        return etiqueta

    def _activar(self, url: str) -> None:
        if glosario.mostrar(url, self):
            return
        if self.al_activar:
            self.al_activar(url)

    def texto(self, texto_html: str, rol: str = "normal", tinta: str | None = None,
              envolver: bool = True, mayus: bool = False) -> EtiquetaC:
        """Una etiqueta del estilo C, copiable (no la anade a la caja)."""
        etiqueta = EtiquetaC(texto_html, rol, tinta=tinta, envolver=envolver, mayus=mayus)
        return self.preparar(etiqueta)

    def contador(self, n: int) -> None:
        self.extra.setText(str(n))

    def cuenta_atras(self, expira, prefijo: str = "") -> None:
        """La cuenta atras del bloque entero al lado del titulo."""
        self.extra_expira = (prefijo, expira)
        self._pintar_extra()

    def _pintar_extra(self) -> None:
        if self.extra_expira is None:
            return
        prefijo, expira = self.extra_expira
        texto = _restante(expira)
        if _terminado(expira):
            # "termina en terminado" no es una frase: cuando ya ha pasado, solo la palabra.
            self.extra.setText(texto)
            return
        self.extra.setText(f"{_esc(prefijo)} {texto}".strip() if texto else _esc(prefijo))

    def reloj(self, etiqueta: QLabel, funcion, ocultar: QWidget | None = None) -> None:
        """`funcion()` da el texto de ahora, o None cuando ya termino (se esconde `ocultar`)."""
        self.relojes.append((etiqueta, funcion, ocultar))
        texto = funcion()
        if texto is None:
            (ocultar or etiqueta).hide()
        else:
            etiqueta.setText(texto)

    def linea(self, texto_html: str, expira=None, marcada: bool = False, rol: str = "normal") -> EtiquetaC:
        etiqueta = self.texto(texto_html, rol)
        if marcada:
            etiqueta.setStyleSheet(
                f"background: {PALETA['panel2']}; border-left: 3px solid {PALETA['acento']};"
                f" padding: {px(3, False)}px {px(6, False)}px;"
            )
        self.caja.addWidget(etiqueta)
        if expira is not None:
            self.reloj(etiqueta, lambda b=texto_html, e=expira: None if _terminado(e) else f"{b} · {_restante(e)}")
        return etiqueta

    def subtitulo(self, texto: str) -> EtiquetaC:
        etiqueta = self.texto(texto, "rotulo", mayus=True, envolver=False)
        etiqueta.setContentsMargins(0, px(4, False), 0, 0)
        self.caja.addWidget(etiqueta)
        return etiqueta

    def vacia(self, texto: str) -> EtiquetaC:
        etiqueta = self.texto(texto if "<" not in texto else _esc(texto), "normal", tinta="suave")
        self.caja.addWidget(etiqueta)
        return etiqueta

    def anadir_fila(self, *piezas, espacio: int = 6) -> QWidget:
        """Varias piezas en una fila, dentro de un widget (para poder esconderla entera)."""
        caja = transparente(QWidget())
        caja.setLayout(fila(*piezas, espacio=px(espacio, False)))
        self.caja.addWidget(caja)
        return caja

    def refrescar_relojes(self) -> None:
        for etiqueta, funcion, ocultar in self.relojes:
            texto = funcion()
            if texto is None:
                # Lo que ha caducado desaparece sin esperar al siguiente refresco.
                (ocultar or etiqueta).hide()
            else:
                etiqueta.setText(texto)
        self._pintar_extra()


# Compatibilidad con quien importaba los nombres de antes.
Seccion = Bloque
Tarjeta = Bloque


class TarjetaFisura(QWidget):
    """Una fisura en su columna de era: nodo, mision y planeta, y la faccion en su color
    o, si te sirve para tus metas, "★ para ..." con el borde dorado."""

    def __init__(self, fisura: Fisura, bloque: Bloque, util_para: list[str], marcar_modo: bool, parent=None):
        super().__init__(parent)
        transparente(self)
        self.fisura = fisura
        self.util = bool(util_para)
        self.color_barra = COLORES_FACCION.get(clave_faccion(fisura), PALETA["suave"])
        p = PALETA
        nombre, planeta = _partir_nodo(fisura.nodo)
        self.nombre = bloque.preparar(_recortada(nombre, "fuerte"))
        self.tiempo = bloque.preparar(EtiquetaC("", "pequeno"))
        mision = glosario.enlace_mision(fisura.modo, fisura.mision, p["suave"]) if fisura.mision else ""
        detalle = " · ".join(x for x in (mision, _esc(planeta)) if x)
        self.detalle = _encogible(bloque.preparar(EtiquetaC(detalle or "&nbsp;", "pequeno")))
        if self.util:
            nombres = list(dict.fromkeys(util_para))
            abajo = f"<span style='color:{p['acento']};font-weight:600'>★ " + _esc(
                t("para {nombre}", nombre=nombres[0])) + "</span>"
            self.setToolTip(t("Te sirve para: {lista}", lista=", ".join(nombres)))
        else:
            abajo = f"<span style='color:{self.color_barra};font-weight:600'>{_esc(fisura.enemigo or '')}</span>"
        if marcar_modo and fisura.acero:
            abajo += " · " + glosario.enlace("camino_de_acero", t("Acero"), p["aviso"])
        if marcar_modo and fisura.tormenta:
            abajo += " · " + glosario.enlace("tormenta", t("Tormenta"), p["aviso"])
        self.abajo = _encogible(bloque.preparar(EtiquetaC(abajo, "pequeno")))
        capa = QVBoxLayout(self)
        capa.setContentsMargins(px(10, False), px(3, False), px(6, False), px(3, False))
        capa.setSpacing(0)
        capa.addLayout(fila(self.nombre, None, self.tiempo, espacio=px(4, False)))
        capa.addWidget(self.detalle)
        capa.addWidget(self.abajo)
        bloque.reloj(self.tiempo, lambda e=fisura.expira: None if _terminado(e) else _restante(e), ocultar=self)

    def paintEvent(self, _evento):  # noqa: N802 - firma de Qt
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.fillRect(r, color("panel2"))
        p.fillRect(QRectF(0, 0, px(3, False), self.height()), color(self.color_barra))
        if self.util:
            p.setPen(QPen(color("acento"), 1))
            p.drawRect(r)
        p.end()


class BarraBandos(QWidget):
    """La barra de una invasion: lo que lleva el atacante en su color y el resto en el del defensor."""

    def __init__(self, progreso: float, atacante: str, defensor: str, parent=None):
        super().__init__(parent)
        transparente(self)
        self.progreso = max(0.0, min(1.0, progreso))
        self.atacante, self.defensor = atacante, defensor
        self.setFixedHeight(px(3, False))

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()
        hueco = px(3, False)
        corte = int(w * self.progreso)
        p.fillRect(0, 0, max(0, corte - hueco // 2), h, color(self.atacante))
        p.fillRect(min(w, corte + hueco // 2), 0, w, h, color(self.defensor))
        p.end()


class PanelFisuras(Bloque):
    """Fisuras del Vacio: botones de tipo, facciones con su leyenda y una columna por era."""

    def __init__(self, pestana: "PestanaMundo", completo: bool):
        super().__init__(t(TITULOS["fisuras"]), "fisuras")
        self.completo = completo
        self.botones_modo: dict[str, BotonC] = {}
        for clave in CLAVES_MODO:
            boton = BotonC("", tam=11)
            boton.setCheckable(True)
            boton.toggled.connect(lambda marcado, c=clave: pestana._modo_pulsado(c, marcado))
            self.botones_modo[clave] = boton
        glosario.aplicar(self.botones_modo["acero"], "camino_de_acero")
        glosario.aplicar(self.botones_modo["tormenta"], "tormenta")
        self.boton_facciones = BotonC("", icono="abajo", tam=11)
        self.boton_facciones.setMenu(pestana.menu_facciones)
        self.leyenda = QHBoxLayout()
        self.leyenda.setSpacing(px(5, False))
        caja_leyenda = transparente(QWidget())
        caja_leyenda.setLayout(self.leyenda)
        caja_leyenda.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.caja_leyenda = caja_leyenda
        controles = fila(*self.botones_modo.values(), self.boton_facciones, px(10, False), caja_leyenda,
                         espacio=px(6, False))
        self.capa.insertLayout(1, controles)
        glosario.aplicar(self.rotulo, "fisura")

    def pintar_leyenda(self, claves: list[str]) -> None:
        _vaciar_layout(self.leyenda)
        self.leyenda.addStretch(1)
        nombres = {clave: (nombre, en) for clave, nombre, _c, en in FACCIONES}
        for clave in claves:
            nombre, en = nombres[clave]
            self.leyenda.addWidget(Rombo(7, COLORES_FACCION[clave]))
            self.leyenda.addWidget(EtiquetaC(glosa(nombre, en), "pequeno"))
            self.leyenda.addSpacing(px(4, False))


class PestanaMundo(QWidget):
    # Un objeto pinchado (Baro, una recompensa): la ventana abre su ficha en Buscar.
    abrir_item = Signal(int)
    # Una recompensa que no esta en el indice: la ventana la busca por su nombre en Buscar.
    buscar_texto = Signal(str)
    # Texto para un aviso de Windows (la ventana lo manda a la bandeja).
    aviso_windows = Signal(str)
    # La sub-pestana elegida (se recuerda en `diseno_mundo`).
    diseno_cambiado = Signal(str)

    def __init__(self, parent=None, diseno: str | None = None):
        super().__init__(parent)
        transparente(self)
        self.config = cargar()
        if diseno is None:
            diseno = self.config.get(CLAVE_DISENO)
        self.diseno = normalizar_diseno(diseno)
        if self.config.get(CLAVE_DISENO) in DISENOS_ANTIGUOS:
            # Migracion: "lista"/"tablero" de antes pasan a la sub-pestana TODO (se escribe
            # en el siguiente guardado; una version antigua lee "todo" como su disposicion
            # por defecto, asi que no se rompe nada volviendo atras).
            self.config[CLAVE_DISENO] = normalizar_diseno(self.config[CLAVE_DISENO])
        self.mundo: Mundo | None = None
        self._motivo_fallo: str | None = None
        # Para cruzar las fisuras con los objetivos: conexiones que pasa la ventana.
        self.indice = None
        self.usuario = None
        self._eras_necesarias: dict[str, list[str]] = {}
        facciones = self.config.get(CLAVE_FACCIONES) or []
        self._facciones: set[str] = {str(f) for f in facciones} if isinstance(facciones, list) else set()
        modos = self.config.get(CLAVE_MODOS)
        self._modos: set[str] = {m for m in modos if m in CLAVES_MODO} if isinstance(modos, list) else set()
        self._modos = self._modos or set(MODOS_POR_DEFECTO)
        self._avisador = avisos_mundo.Avisador(self.config.get(avisos_mundo.CLAVE_ENVIADOS))

        # Menu de facciones, compartido por los paneles de fisuras de TODO y de FISURAS.
        self.menu_facciones = QMenu(self)
        self.acciones_faccion = {}
        for clave, _nombre, _color, _en in FACCIONES:
            accion = self.menu_facciones.addAction("")
            accion.setCheckable(True)
            accion.setChecked(clave in self._facciones)
            accion.toggled.connect(self._cambiar_facciones)
            self.acciones_faccion[clave] = accion
        self.menu_facciones.addSeparator()
        self.accion_todas = self.menu_facciones.addAction("")
        self.accion_todas.triggered.connect(self._todas_las_facciones)

        # -- cabecera: sub-pestanas y el boton de personalizar
        self.subpestanas = SubPestanasC([(clave, t(texto)) for clave, texto in SUBPESTANAS])
        self.subpestanas.cambiada.connect(self._sub_pulsada)
        self.boton_personalizar = BotonC("", icono="", tam=11)
        self.boton_personalizar.setCheckable(True)
        self.boton_personalizar.toggled.connect(self.mostrar_personalizar)
        self.subpestanas.derecha.addWidget(self.boton_personalizar)
        self.aviso = EtiquetaC(t("Consultando el estado del mundo..."), "normal", tinta="suave", envolver=True)
        self.aviso.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pie = EtiquetaC("", "pequeno", tinta="tenue")
        self.pie.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._bloques: list[Bloque] = []
        self._reflujo: list[tuple[QBoxLayout, int]] = []
        self._construir_paginas()

        self.paginas = QStackedWidget()
        transparente(self.paginas)
        self.paginas.addWidget(self.vistas)
        self.desplazable = self.vistas  # nombre de antes: la vista del mundo (no la de personalizar)
        self.pagina_ajustes = None
        self._nueva_pagina_ajustes()

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(px(8, False))
        caja.addLayout(fila(self.subpestanas, margen=(px(4, False), px(2, False), 0, 0)))
        caja.addWidget(self.aviso)
        caja.addWidget(self.paginas, 1)
        caja.addWidget(self.pie)

        self._reloj = QTimer(self)
        self._reloj.timeout.connect(self._tic)
        self._reloj.start(1000)
        self._textos_fijos()
        self.mostrar_sub(self.diseno, guardar_cambio=False)
        self.pintar()

    # -- construccion -------------------------------------------------------------

    def _bloque(self, clave_titulo: str, remate: bool = True) -> Bloque:
        bloque = Bloque(t(TITULOS[clave_titulo]), clave_titulo, remate=remate)
        bloque.al_activar = self._enlace
        self._bloques.append(bloque)
        return bloque

    def _panel_fisuras(self, completo: bool) -> PanelFisuras:
        panel = PanelFisuras(self, completo)
        panel.al_activar = self._enlace
        self._bloques.append(panel)
        return panel

    def _pagina(self) -> tuple[QScrollArea, QVBoxLayout]:
        contenido = transparente(QWidget())
        capa = QVBoxLayout(contenido)
        capa.setContentsMargins(0, 0, px(6, False), 0)
        capa.setSpacing(px(12, False))
        desplazable = QScrollArea()
        transparente(desplazable)
        transparente(desplazable.viewport())
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QFrame.NoFrame)
        desplazable.setWidget(contenido)
        return desplazable, capa

    def _fila_reflujo(self, umbral: int) -> QBoxLayout:
        """Paneles uno al lado de otro que se apilan si la ventana es estrecha."""
        capa = QBoxLayout(QBoxLayout.LeftToRight)
        capa.setSpacing(px(14, False))
        self._reflujo.append((capa, umbral))
        return capa

    def _construir_paginas(self) -> None:
        self.vistas = QStackedWidget()
        transparente(self.vistas)
        self.vistas_por_clave: dict[str, QScrollArea] = {}

        # TODO: fisuras con Baro, Teshin y Hoy al lado; invasiones, alertas y ciclos debajo.
        pagina, capa = self._pagina()
        self.fisuras_todo = self._panel_fisuras(completo=False)
        self.baro_todo = self._bloque("baro")
        self.teshin_todo = self._bloque("teshin", remate=False)
        self.hoy = self._bloque("hoy", remate=False)
        lado = columna(self.baro_todo, self.teshin_todo, self.hoy, None, espacio=px(12, False))
        arriba = self._fila_reflujo(ANCHO_FILA_ARRIBA)
        arriba.addWidget(self.fisuras_todo, 13)
        arriba.addLayout(lado, 6)
        self.invasiones_todo = self._bloque("invasiones")
        self.alertas_todo = self._bloque("alertas", remate=False)
        self.ciclos = self._bloque("ciclos")
        abajo = self._fila_reflujo(ANCHO_FILA_ABAJO)
        abajo.addWidget(self.invasiones_todo, 7)
        abajo.addWidget(self.alertas_todo, 4)
        abajo.addWidget(self.ciclos, 5)
        capa.addLayout(arriba)
        capa.addLayout(abajo)
        capa.addStretch(1)
        self._anadir_vista("todo", pagina)

        # FISURAS: las que sirven para tus metas y todas, sin limite por columna.
        pagina, capa = self._pagina()
        self.metas = self._bloque("objetivos")
        self.fisuras_completo = self._panel_fisuras(completo=True)
        capa.addWidget(self.metas)
        capa.addWidget(self.fisuras_completo)
        capa.addStretch(1)
        self._anadir_vista("fisuras", pagina)

        # BARO Y TESHIN: el inventario entero y las proximas semanas de Teshin.
        pagina, capa = self._pagina()
        self.baro_tienda = self._bloque("baro")
        self.teshin_tienda = self._bloque("teshin")
        tiendas = self._fila_reflujo(ANCHO_FILA_ABAJO)
        tiendas.addWidget(self.baro_tienda, 3)
        tiendas.addWidget(self.teshin_tienda, 2)
        capa.addLayout(tiendas)
        capa.addStretch(1)
        self._anadir_vista("tienda", pagina)

        # INVASIONES Y ALERTAS: todo, con la incursion, los arcontes y la onda nocturna.
        pagina, capa = self._pagina()
        self.invasiones_eventos = self._bloque("invasiones")
        self.alertas_eventos = self._bloque("alertas", remate=False)
        self.arbitraje = self._bloque("arbitraje", remate=False)
        eventos = self._fila_reflujo(ANCHO_FILA_ABAJO)
        eventos.addWidget(self.invasiones_eventos, 3)
        eventos.addLayout(columna(self.alertas_eventos, self.arbitraje, None, espacio=px(14, False)), 2)
        self.sortie = self._bloque("sortie")
        self.nightwave = self._bloque("nightwave", remate=False)
        diarios = self._fila_reflujo(ANCHO_FILA_ABAJO)
        diarios.addWidget(self.sortie, 1)
        diarios.addWidget(self.nightwave, 1)
        capa.addLayout(eventos)
        capa.addLayout(diarios)
        capa.addStretch(1)
        self._anadir_vista("eventos", pagina)

        glosario.aplicar(self.baro_todo.rotulo, "baro")
        glosario.aplicar(self.baro_tienda.rotulo, "baro")
        glosario.aplicar(self.teshin_todo.rotulo, "camino_de_acero")
        glosario.aplicar(self.teshin_tienda.rotulo, "camino_de_acero")
        # Los bloques de siempre por su clave (lo que se esconde desde "Personalizar").
        self.tarjetas = {
            "fisuras": self.fisuras_todo, "objetivos": self.metas, "baro": self.baro_todo,
            "teshin": self.teshin_todo, "ahora": self.hoy, "invasiones": self.invasiones_todo,
            "alertas": self.alertas_todo, "ciclos": self.ciclos, "sortie": self.sortie,
            "nightwave": self.nightwave, "arbitraje": self.arbitraje,
        }
        self._visibles_por_seccion = {
            "objetivos": [self.metas],
            "baro": [self.baro_todo, self.baro_tienda],
            "teshin": [self.teshin_todo, self.teshin_tienda],
            "ahora": [self.hoy],
            "invasiones": [self.invasiones_todo, self.alertas_todo, self.invasiones_eventos,
                           self.alertas_eventos, self.arbitraje],
            "ciclos": [self.ciclos],
            "sortie": [self.sortie],
            "nightwave": [self.nightwave],
        }

    def _anadir_vista(self, clave: str, pagina: QScrollArea) -> None:
        self.vistas.addWidget(pagina)
        self.vistas_por_clave[clave] = pagina

    def _nueva_pagina_ajustes(self) -> None:
        """La pagina de personalizar; se rehace entera al cambiar de idioma o de tema."""
        en_ajustes = self.pagina_ajustes is not None and self.paginas.currentWidget() is self.pagina_ajustes
        nueva = PanelPersonalizar()
        nueva.volver.connect(lambda: self.boton_personalizar.setChecked(False))
        nueva.secciones_cambiadas.connect(self.pintar)
        nueva.avisos_cambiados.connect(self.pintar)
        nueva.probar_aviso.connect(
            lambda: self.aviso_windows.emit(t("Así se verán los avisos de Farmadex sobre el mundo de Warframe"))
        )
        if self.pagina_ajustes is not None:
            self.paginas.removeWidget(self.pagina_ajustes)
            self.pagina_ajustes.deleteLater()
        self.pagina_ajustes = nueva
        self.paginas.addWidget(nueva)
        if en_ajustes:
            self.paginas.setCurrentWidget(nueva)

    def resizeEvent(self, evento):  # noqa: N802 - firma de Qt
        super().resizeEvent(evento)
        self._reordenar()

    def _reordenar(self) -> None:
        ancho = self.width()
        for capa, umbral in self._reflujo:
            direccion = QBoxLayout.LeftToRight if ancho >= px(umbral, False) else QBoxLayout.TopToBottom
            if capa.direction() != direccion:
                capa.setDirection(direccion)

    # -- sub-pestanas y personalizar ---------------------------------------------------

    def _sub_pulsada(self, clave: str) -> None:
        if self.boton_personalizar.isChecked():
            self.boton_personalizar.setChecked(False)
        self.mostrar_sub(clave)

    def mostrar_sub(self, clave: str, guardar_cambio: bool = True) -> None:
        """Ensena una sub-pestana (todo, fisuras, tienda, eventos) y la recuerda."""
        clave = normalizar_diseno(clave)
        self.vistas.setCurrentWidget(self.vistas_por_clave[clave])
        self.subpestanas.poner_activa(clave)
        if clave == self.diseno:
            return
        self.diseno = clave
        if guardar_cambio:
            self.config[CLAVE_DISENO] = clave
            guardar(self.config)
            self.diseno_cambiado.emit(clave)

    def cambiar_diseno(self, diseno: str) -> None:
        """Compatibilidad: lo que antes elegia Lista/Tablero ahora elige la sub-pestana."""
        self.mostrar_sub(diseno)

    def mostrar_personalizar(self, mostrar: bool) -> None:
        if self.boton_personalizar.isChecked() != mostrar:
            self.boton_personalizar.setChecked(mostrar)  # vuelve a entrar por la senal
            return
        if mostrar:
            self.pagina_ajustes.sincronizar()
        self.paginas.setCurrentWidget(self.pagina_ajustes if mostrar else self.vistas)
        # En personalizar, el boton para volver esta dentro de la propia pagina.
        self.boton_personalizar.setVisible(not mostrar)
        if not mostrar:
            # Al volver se aplica lo elegido: bloques y, si hay avisos nuevos, se mandan ya.
            self.pintar()
            self._avisar()

    # -- filtros de fisuras --------------------------------------------------------------

    def _paneles_fisuras(self) -> list[PanelFisuras]:
        return [self.fisuras_todo, self.fisuras_completo]

    def _modos_visibles(self, escondidas: set[str] | None = None) -> list[str]:
        escondidas = ocultas(self.config) if escondidas is None else escondidas
        return [c for c in CLAVES_MODO if SECCION_MODO[c] not in escondidas]

    def modos_activos(self, escondidas: set[str] | None = None) -> set[str]:
        visibles = self._modos_visibles(escondidas)
        return (self._modos & set(visibles)) or set(visibles[:1])

    def _modo_pulsado(self, clave: str, marcado: bool) -> None:
        modos = set(self._modos)
        if marcado:
            modos.add(clave)
        else:
            modos.discard(clave)
        if not modos & set(self._modos_visibles()):
            # Siempre queda al menos un tipo elegido: sin ninguno no se veria nada.
            self._sincronizar_botones()
            return
        self._modos = modos
        self.config[CLAVE_MODOS] = [c for c in CLAVES_MODO if c in modos]
        guardar(self.config)
        self.pintar()

    def _sincronizar_botones(self) -> None:
        activos = self.modos_activos()
        for panel in self._paneles_fisuras():
            for clave, boton in panel.botones_modo.items():
                boton.blockSignals(True)
                boton.setChecked(clave in activos)
                boton.blockSignals(False)
                boton.update()

    def _cambiar_facciones(self, *_):
        self._facciones = {c for c, accion in self.acciones_faccion.items() if accion.isChecked()}
        self.config[CLAVE_FACCIONES] = sorted(self._facciones)
        guardar(self.config)
        self._textos_facciones()
        self.pintar()

    def _todas_las_facciones(self) -> None:
        for accion in self.acciones_faccion.values():
            accion.blockSignals(True)
            accion.setChecked(False)
            accion.blockSignals(False)
        self._cambiar_facciones()

    @property
    def filtro_faccion(self) -> BotonC:
        """El boton de facciones de TODO (el de FISURAS dice lo mismo)."""
        return self.fisuras_todo.boton_facciones

    @property
    def botones_modo(self) -> dict[str, BotonC]:
        return self.fisuras_todo.botones_modo

    def _textos_facciones(self) -> None:
        for clave, nombre, _color, en in FACCIONES:
            self.acciones_faccion[clave].setText(glosa(nombre, en))
        self.accion_todas.setText(t("Enseñar todas"))
        if self._facciones:
            texto = t("Facciones: {n}", n=len(self._facciones))
        else:
            texto = t("Facciones: todas")
        for panel in self._paneles_fisuras():
            panel.boton_facciones.setText(texto)
            panel.boton_facciones.setToolTip(t(
                "Elige las facciones que te interesan: solo se enseñan sus fisuras. "
                "El nombre de la facción sale con su color para reconocerla de un vistazo."))
            panel.boton_facciones.updateGeometry()

    def _textos_fijos(self) -> None:
        for clave, texto in SUBPESTANAS:
            self.subpestanas.poner_texto(clave, t(texto))
        self.boton_personalizar.setText(t("Personalizar y avisos"))
        self.boton_personalizar.setToolTip(t("Elige qué bloques ver y de qué quieres que Farmadex te avise"))
        for panel in self._paneles_fisuras():
            for clave, texto in zip(CLAVES_MODO, MODOS):
                panel.botones_modo[clave].setText(t(texto))
                panel.botones_modo[clave].updateGeometry()
        self._textos_facciones()
        for bloque in self._bloques:
            bloque.setTitle(t(TITULOS[bloque.clave]))

    def _enlace(self, url: str) -> None:
        if url.startswith("item:"):
            self.abrir_item.emit(int(url.removeprefix("item:")))
        elif url.startswith("buscar:"):
            self.buscar_texto.emit(unquote(url.removeprefix("buscar:")))
        elif url.startswith("sub:"):
            self.mostrar_sub(url.removeprefix("sub:"))

    # -- idioma y tema ------------------------------------------------------------------

    def retraducir(self) -> None:
        self._textos_fijos()
        glosario.aplicar(self.botones_modo["acero"], "camino_de_acero")
        for panel in self._paneles_fisuras():
            glosario.aplicar(panel.rotulo, "fisura")
            glosario.aplicar(panel.botones_modo["acero"], "camino_de_acero")
            glosario.aplicar(panel.botones_modo["tormenta"], "tormenta")
        for bloque, termino in ((self.baro_todo, "baro"), (self.baro_tienda, "baro"),
                                (self.teshin_todo, "camino_de_acero"), (self.teshin_tienda, "camino_de_acero")):
            glosario.aplicar(bloque.rotulo, termino)
        self._nueva_pagina_ajustes()
        self._pintar_aviso()
        self.pintar()

    def repintar(self) -> None:
        """Tras cambiar de tema: el HTML lleva los colores dentro."""
        self.pintar()

    # -- avisos de Windows ------------------------------------------------------------

    def _prefs_avisos(self) -> dict:
        return avisos_mundo.normalizar(self.config.get(avisos_mundo.CLAVE_CONFIG))

    def _poner_aviso(self, clave: str, activo: bool) -> None:
        """Lo que encienden los botones "Avisarme" de los paneles (lo mismo que Personalizar)."""
        prefs = self._prefs_avisos()
        prefs[clave] = bool(activo)
        self.config[avisos_mundo.CLAVE_CONFIG] = avisos_mundo.normalizar(prefs)
        guardar(self.config)
        if self.pagina_ajustes is not None:
            self.pagina_ajustes.sincronizar()
        self._sincronizar_botones_aviso()
        if activo:
            self._avisar()

    def _boton_aviso(self, texto: str, clave: str) -> BotonC:
        boton = BotonC(texto, icono="reloj", tam=11)
        boton.setCheckable(True)
        boton.setProperty("clave_aviso", clave)
        boton.setProperty("texto_aviso", texto)
        boton.setChecked(bool(self._prefs_avisos().get(clave)))
        self._texto_boton_aviso(boton)
        boton.toggled.connect(lambda marcado, c=clave: self._poner_aviso(c, marcado))
        return boton

    def _texto_boton_aviso(self, boton: BotonC) -> None:
        boton.setText(t("Te aviso") if boton.isChecked() else boton.property("texto_aviso"))
        boton.setToolTip(t("Pulsa otra vez para quitar el aviso") if boton.isChecked()
                         else t("Te avisa Windows aunque tengas Farmadex escondido"))
        boton.updateGeometry()

    def _sincronizar_botones_aviso(self) -> None:
        prefs = self._prefs_avisos()
        for bloque in self._bloques:
            for boton in bloque.findChildren(BotonC):
                clave = boton.property("clave_aviso")
                if clave:
                    boton.blockSignals(True)
                    boton.setChecked(bool(prefs.get(clave)))
                    boton.blockSignals(False)
                    self._texto_boton_aviso(boton)

    def _avisar(self) -> None:
        """Manda a la bandeja lo nuevo que el usuario ha pedido que se le avise."""
        mundo = self.mundo
        if mundo is None or mundo.esta_viejo():
            # Con datos viejos se avisaria de cosas que ya pasaron.
            return
        prefs = self._prefs_avisos()
        if not avisos_mundo.alguno_activo(prefs):
            return
        try:
            avisos = avisos_mundo.calcular(mundo, prefs, facciones=self._facciones)
        except Exception:  # noqa: BLE001 - un aviso roto no puede tumbar la pestana
            log.warning("No se pudieron calcular los avisos del mundo", exc_info=True)
            return
        nuevos = self._avisador.nuevos(avisos)
        self.config[avisos_mundo.CLAVE_ENVIADOS] = dict(self._avisador.enviados)
        if not nuevos:
            return
        guardar(self.config)
        log.info("Avisos del mundo: %s", [a.clave for a in nuevos])
        self.aviso_windows.emit(avisos_mundo.juntar(nuevos))

    # -- datos ------------------------------------------------------------------------

    def conectar_objetivos(self, indice, usuario) -> None:
        """Con el indice y la BD del usuario se sabe que eras de reliquia hacen falta."""
        self.indice = indice
        self.usuario = usuario
        self.refrescar_objetivos()

    def refrescar_objetivos(self) -> None:
        """Tras anadir o completar un objetivo: las fisuras marcadas cambian."""
        self._eras_necesarias = self._calcular_eras()
        self._marcar_baro()
        self.pintar()

    def _calcular_eras(self) -> dict[str, list[str]]:
        if self.indice is None or self.usuario is None:
            return {}
        from ..estado import objetivos as estado_objetivos

        try:
            eras = estado_objetivos.eras_necesarias(self.indice, self.usuario)
            completos = self._nombres_completos(estado_objetivos.listar(self.usuario))
        except Exception:  # noqa: BLE001 - un fallo aqui no puede dejar Mundo en blanco
            log.warning("No se pudieron calcular las eras de los objetivos", exc_info=True)
            return {}
        return {era: [completos.get(n, n) for n in nombres] for era, nombres in eras.items()}

    def _nombres_completos(self, objetivos) -> dict[str, str]:
        """'Sistemas' -> 'Sistemas de Citrine Prime': una pieza suelta no dice de que es."""
        from ..idiomas import nombre as nombre_idioma

        salida = {}
        for objetivo in objetivos:
            fila_padre = self.indice.execute(
                "SELECT p.nombre_es, p.nombre_en FROM items i JOIN items p ON p.id = i.padre_id "
                "WHERE i.unique_name = ?", (objetivo.unique_name,)).fetchone()
            if not fila_padre:
                continue
            padre = nombre_idioma({"nombre_es": fila_padre[0], "nombre_en": fila_padre[1]})
            if padre and padre.lower() not in objetivo.nombre.lower():
                salida[objetivo.nombre] = t("{nombre} de {padre}", nombre=objetivo.nombre, padre=padre)
        return salida

    def actualizar(self, mundo: Mundo) -> None:
        self.mundo = mundo
        self._motivo_fallo = None
        if self.indice is not None:
            self._eras_necesarias = self._calcular_eras()
        self._marcar_baro()
        self._pintar_aviso()
        if self.window() is not self and not self.isVisible():
            # Dentro de la ventana y sin verse (otra seccion delante, o Farmadex escondido):
            # pintarla cuesta ~40 ms y llega cada poco; se pinta al volver a ensenarse.
            self._pintar_pendiente = True
        else:
            self.pintar()
        self._avisar()

    _pintar_pendiente = False

    def showEvent(self, evento):  # noqa: N802 - firma de Qt
        super().showEvent(evento)
        if self._pintar_pendiente:
            self._pintar_pendiente = False
            self.pintar()

    def _marcar_baro(self) -> None:
        """Marca lo que Baro trae y esta en tus objetivos (arriba y en dorado, y para los avisos)."""
        baro = getattr(self.mundo, "baro_detalle", None)
        if baro is None or self.usuario is None:
            return
        from ..estado import objetivos as estado_objetivos

        try:
            unicos = [o.unique_name for o in estado_objetivos.listar(self.usuario)]
        except Exception:  # noqa: BLE001 - sin objetivos, Baro se ensena igual
            log.warning("No se pudieron leer los objetivos para Baro", exc_info=True)
            return
        ws.marcar_objetivos(baro, unicos)

    def marcar_desactualizado(self, motivo: str) -> None:
        self._motivo_fallo = motivo
        self._pintar_aviso()
        # Los bloques vacios dicen por que lo estan; hay que repintarlos con el motivo.
        self.pintar()

    # -- estado de los datos ------------------------------------------------------------

    def estado_datos(self) -> str:
        """'consultando' (aun nada), 'fallo' (nada y la consulta fallo), 'viejo' (la API
        publica un estado desfasado) o 'fresco' (datos al dia, con o sin fallo posterior)."""
        if self.mundo is None:
            return "fallo" if self._motivo_fallo else "consultando"
        if self.mundo.esta_viejo():
            return "viejo"
        return "fresco"

    def _edad(self) -> str:
        """Cuanto hace del 'timestamp' que publica la API: '35 min', '2 h', '2 h 10 min'."""
        minutos = int(self.mundo.minutos_de_antiguedad() or 0) if self.mundo else 0
        horas, minutos = divmod(minutos, 60)
        if not horas:
            return t("{n} min", n=minutos)
        if not minutos:
            return t("{n} h", n=horas)
        return t("{h} h {m} min", h=horas, m=minutos)

    def _texto_sin_datos(self) -> str | None:
        """Lo que va en un bloque vacio cuando la culpa no es del filtro; None si los datos valen."""
        estado = self.estado_datos()
        if estado == "viejo":
            return t(
                "Sin datos al día: el estado del mundo que publica la API es de hace {tiempo}",
                tiempo=self._edad(),
            )
        if estado == "fallo":
            return t(
                "No se ha podido consultar el estado del mundo ({motivo}). "
                "Se reintenta solo cada minuto.",
                motivo=self._motivo_fallo,
            )
        return None

    def _vacia(self, bloque: Bloque, texto: str) -> None:
        """Un bloque sin nada: el texto normal, o la verdad si los datos no estan al dia."""
        bloque.vacia(self._texto_sin_datos() or texto)

    def _pintar_aviso(self) -> None:
        estado = self.estado_datos()
        tinta = "aviso"
        if estado == "consultando":
            texto, tinta = t("Consultando el estado del mundo..."), "suave"
        elif estado == "fallo":
            texto = t("Sin conexión con el estado del mundo ({motivo})", motivo=self._motivo_fallo)
        elif estado == "viejo":
            texto = t("El estado del mundo que publica la API es de hace {tiempo}", tiempo=self._edad())
        elif self._motivo_fallo:
            texto = t("Datos del mundo sin actualizar; se muestra lo último conocido")
        elif getattr(self.mundo, "fuente", "") == "de":
            texto, tinta = t("warframestat no está al día; se usa el worldState oficial de DE"), "suave"
        else:
            texto, tinta = "", "suave"
        self.aviso.setText(texto)
        self.aviso.poner_tinta(tinta)
        self.aviso.setVisible(bool(texto))
        self._pintar_pie()

    def _pintar_pie(self) -> None:
        if self.estado_datos() != "fresco":
            self.pie.setText("")
            return
        self.pie.setText(t("Datos del juego de hace {tiempo} · se actualiza solo cada minuto", tiempo=self._edad()))

    def _tic(self) -> None:
        for bloque in self._bloques:
            bloque.refrescar_relojes()
        self._pintar_pie()

    # -- pintado ------------------------------------------------------------------------

    def pintar(self) -> None:
        mundo = self.mundo
        escondidas = ocultas(self.config)
        for bloque in self._bloques:
            bloque.limpiar()
        try:
            self._pintar_todo(mundo, escondidas)
        finally:
            self._aplicar_visibilidad(escondidas)

    def _aplicar_visibilidad(self, escondidas: set[str]) -> None:
        """Lo que el usuario ha escondido en "Personalizar", fuera siempre."""
        visibles = self._modos_visibles(escondidas)
        for panel in self._paneles_fisuras():
            panel.setVisible(bool(visibles))
            for clave, boton in panel.botones_modo.items():
                boton.setVisible(clave in visibles)
        for seccion, bloques in self._visibles_por_seccion.items():
            for bloque in bloques:
                bloque.setVisible(seccion not in escondidas)
        self._sincronizar_botones()

    def _pintar_todo(self, mundo: Mundo | None, escondidas: set[str]) -> None:
        abiertas = self._fisuras_abiertas(mundo, escondidas) if mundo is not None else []
        sin_filtro = sum(1 for f in mundo.fisuras if not _terminado(f.expira)) if mundo is not None else 0
        marcar = "objetivos" not in escondidas
        for panel in self._paneles_fisuras():
            self._pintar_panel_fisuras(panel, abiertas, sin_filtro, marcar)
        self._pintar_metas(self.metas, abiertas)
        for bloque, completo in ((self.baro_todo, False), (self.baro_tienda, True)):
            self._pintar_baro(bloque, completo)
        for bloque, completo in ((self.teshin_todo, False), (self.teshin_tienda, True)):
            self._pintar_teshin(bloque, completo)
        self._pintar_hoy(self.hoy, escondidas)
        for bloque, completo in ((self.invasiones_todo, False), (self.invasiones_eventos, True)):
            self._pintar_invasiones(bloque, completo)
        for bloque in (self.alertas_todo, self.alertas_eventos):
            self._pintar_alertas(bloque)
        self._pintar_arbitraje(self.arbitraje)
        self._pintar_ciclos(self.ciclos)
        self._pintar_sortie(self.sortie)
        self._pintar_nightwave(self.nightwave)

    # Fisuras ------------------------------------------------------------------------

    def _fisuras_abiertas(self, mundo: Mundo, escondidas: set[str] | None = None) -> list[Fisura]:
        """Las que no han terminado y pasan el filtro, de la mas rapida a la mas larga."""
        activos = self.modos_activos(escondidas)
        salida = []
        for f in mundo.fisuras:
            if _terminado(f.expira):
                continue
            modo = "tormenta" if f.tormenta else ("acero" if f.acero else "normal")
            if modo not in activos:
                continue
            if self._facciones:
                faccion = clave_faccion(f)
                # Una faccion que no se reconoce no se esconde: mejor de mas que perderla.
                if faccion in COLORES_FACCION and faccion not in self._facciones:
                    continue
            salida.append(f)
        # Rapidas primero; a igual rapidez, la que mas tiempo deja.
        salida.sort(key=lambda f: (rapidez(f.mision), -(minutos_restantes(f.expira) or 0)))
        return salida

    def _objetivos_de(self, f: Fisura) -> list[str]:
        return self._eras_necesarias.get(f.era, [])

    def _html_fisura(self, f: Fisura, con_era: bool = True) -> str:
        """Una fisura en una linea (para "Fisuras para tus metas" y para copiarla)."""
        p = PALETA
        partes = []
        if con_era:
            partes.append(glosario.enlace("era", f.era, COLOR_ERA.get(f.era, p["acento"]), negrita=True))
        partes.append(f"<b>{_esc(f.nodo)}</b>")
        if f.mision:
            partes.append(glosario.enlace_mision(f.modo, f.mision, p["texto"]))
        if f.enemigo:
            color_f = COLORES_FACCION.get(clave_faccion(f), p["suave"])
            partes.append(f"<span style='color:{color_f}'>{_esc(f.enemigo)}</span>")
        if f.acero:
            partes.append(glosario.enlace("camino_de_acero", t("Acero"), p["aviso"]))
        if f.tormenta:
            partes.append(glosario.enlace("tormenta", t("Tormenta"), p["aviso"]))
        texto = " · ".join(partes)
        objetivos = self._objetivos_de(f)
        if objetivos:
            texto += (
                f" <span style='color:{p['acento']}'>★ "
                f"{_esc(', '.join(dict.fromkeys(objetivos)))}</span>"
            )
        return texto

    def _texto_filtro(self) -> str:
        activos = self.modos_activos()
        partes = [t(texto) for clave, texto in zip(CLAVES_MODO, MODOS) if clave in activos]
        if self._facciones:
            partes.append(t("Facciones: {n}", n=len(self._facciones)))
        return ", ".join(partes)

    def _texto_sin_fisuras(self, sin_filtro: int) -> str:
        """Por que no se ve ninguna fisura, sin echarle la culpa al filtro sin motivo."""
        texto = self._texto_sin_datos()
        if texto:
            return texto
        if sin_filtro:
            return t("Hay {n} fisuras abiertas, pero ninguna pasa el filtro ({filtro})",
                     n=sin_filtro, filtro=self._texto_filtro())
        return t("Ahora mismo no hay ninguna fisura abierta")

    def _pintar_panel_fisuras(self, panel: PanelFisuras, abiertas: list[Fisura], sin_filtro: int,
                              marcar: bool) -> None:
        p = PALETA
        activos = self.modos_activos()
        mundo = self.mundo
        # Cuantas hay de cada tipo (con el filtro de facciones), en el boton.
        for clave, boton in panel.botones_modo.items():
            if mundo is None:
                continue
            n = sum(1 for f in mundo.fisuras if not _terminado(f.expira)
                    and ("tormenta" if f.tormenta else ("acero" if f.acero else "normal")) == clave
                    and (not self._facciones or clave_faccion(f) not in COLORES_FACCION
                         or clave_faccion(f) in self._facciones))
            ayuda = {"acero": "camino_de_acero", "tormenta": "tormenta"}.get(clave)
            boton.setToolTip(t("{n} abiertas ahora", n=n) + ("<br>" + glosario.texto(ayuda) if ayuda else ""))
        presentes = {clave_faccion(f) for f in abiertas}
        panel.pintar_leyenda([c for c, *_x in FACCIONES if c in FACCIONES_LEYENDA or c in presentes])
        panel.contador(len(abiertas)) if abiertas else panel.extra.setText("")
        if mundo is None:
            panel.vacia(self._texto_sin_datos() or t("Consultando el estado del mundo..."))
            return
        if not abiertas:
            panel.vacia(self._texto_sin_fisuras(sin_filtro))
            return

        marcar_modo = len(activos) > 1
        columnas = transparente(QWidget())
        capa_columnas = QHBoxLayout(columnas)
        capa_columnas.setContentsMargins(0, 0, 0, 0)
        capa_columnas.setSpacing(px(12, False))
        alguna_util = False
        for era in ERAS_COLUMNAS:
            lista = [f for f in abiertas if f.era == era]
            if marcar:
                # Las que te sirven, arriba de su columna (sin perder el orden de rapidez).
                lista.sort(key=lambda f: not self._objetivos_de(f))
            columna_era = QVBoxLayout()
            columna_era.setSpacing(px(4, False))
            nombre_era = EtiquetaEra(era, por_era=True, tam=14)
            glosario.aplicar(nombre_era, "era")
            columna_era.addLayout(fila(Rombo(9, COLOR_ERA[era]), nombre_era, None,
                                       EtiquetaC(str(len(lista)), "pequeno", tinta="tenue"), espacio=px(6, False)))
            raya = QFrame()
            raya.setFixedHeight(1)
            raya.setStyleSheet(f"background: {p['borde']}; border: none;")
            columna_era.addWidget(raya)
            limite = len(lista) if panel.completo else MAX_POR_COLUMNA
            for f in lista[:limite]:
                util = self._objetivos_de(f) if marcar else []
                alguna_util = alguna_util or bool(util)
                columna_era.addWidget(TarjetaFisura(f, panel, util, marcar_modo))
            if not lista:
                columna_era.addWidget(EtiquetaC(t("Ninguna ahora"), "pequeno", tinta="tenue"))
            elif len(lista) > limite:
                mas = panel.texto(
                    f"<a href='sub:fisuras' style='color:{p['acento']};text-decoration:none'>"
                    + _esc(t("y {n} más", n=len(lista) - limite)) + " ›</a>", "pequeno", envolver=False)
                columna_era.addWidget(mas)
            columna_era.addStretch(1)
            capa_columnas.addLayout(columna_era, 1)
        panel.caja.addWidget(columnas)

        notas = []
        if marcar and alguna_util:
            notas.append(_esc(t("★ con borde dorado: te sirve para tus metas")))
        elif marcar and self._eras_necesarias:
            notas.append(_esc(t("Ninguna fisura abierta sirve ahora mismo. Necesitas:")) + " " + ", ".join(
                f"{glosario.enlace('era', era, COLOR_ERA.get(era, p['acento']), negrita=True)} "
                f"({_esc(', '.join(dict.fromkeys(nombres)))})"
                for era, nombres in self._eras_necesarias.items()))
        otras = [f for f in abiertas if f.era not in ERAS_COLUMNAS]
        if otras:
            por_era: dict[str, list[str]] = {}
            for f in otras:
                por_era.setdefault(f.era, []).append(f"{f.nodo} · {f.mision}".strip(" ·"))
            for era, lugares in por_era.items():
                notas.append(glosario.enlace("era", era, COLOR_ERA.get(era, p["suave"]), negrita=True)
                             + ": " + _esc(" / ".join(lugares)))
        if notas:
            panel.caja.addWidget(panel.texto(" · ".join(notas), "pequeno", tinta="tenue"))

    def _pintar_metas(self, bloque: Bloque, abiertas: list[Fisura]) -> None:
        """FISURAS, arriba: las que sirven para lo que estas farmeando, en lineas copiables."""
        p = PALETA
        if self.mundo is None:
            self._vacia(bloque, t("Consultando el estado del mundo..."))
            return
        if not self._eras_necesarias:
            bloque.vacia(t("Añade objetivos en Mis metas y aquí verás las fisuras que te sirven."))
            return
        por_era: dict[str, int] = {}
        utiles = []
        for f in abiertas:
            if self._objetivos_de(f) and por_era.get(f.era, 0) < MAX_POR_ERA_OBJETIVOS:
                por_era[f.era] = por_era.get(f.era, 0) + 1
                utiles.append(f)
        for f in utiles:
            bloque.linea(self._html_fisura(f), f.expira, marcada=True)
        total = sum(1 for f in abiertas if self._objetivos_de(f))
        if utiles:
            bloque.extra.setText(
                t("{n} de {total}", n=len(utiles), total=total) if total > len(utiles) else str(total)
            )
        elif self._texto_sin_datos():
            # Con datos viejos "ninguna sirve" seria mentira: no se sabe.
            self._vacia(bloque, "")
        else:
            eras = ", ".join(
                f"{glosario.enlace('era', era, COLOR_ERA.get(era, p['acento']), negrita=True)} "
                f"<span style='color:{p['suave']}'>({_esc(', '.join(dict.fromkeys(nombres)))})</span>"
                for era, nombres in self._eras_necesarias.items()
            )
            bloque.linea(
                f"<span style='color:{p['suave']}'>"
                + _esc(t("Ninguna fisura abierta sirve ahora mismo. Necesitas:"))
                + f"</span> {eras}"
            )

    # Baro y Teshin -------------------------------------------------------------------

    def _pintar_baro(self, bloque: Bloque, completo: bool) -> None:
        p = PALETA
        mundo = self.mundo
        if mundo is None:
            self._vacia(bloque, t("Consultando el estado del mundo..."))
            return
        baro = getattr(mundo, "baro_detalle", None)
        if baro is None:
            # Datos antiguos: solo la cabecera en texto y la lista tal cual.
            if mundo.baro_cabecera:
                bloque.linea(f"<b>{_esc(mundo.baro_cabecera)}</b>")
            for o in mundo.baro if completo else mundo.baro[:6]:
                bloque.linea(f"{_esc(o.texto)} <span style='color:{p['suave']}'>{_esc(o.detalle)}</span>")
            if not mundo.baro:
                self._vacia(bloque, t("Vuelve a un relevo cuando llegue"))
            return

        grande = bloque.texto("", "seccion", tinta="acento", mayus=True, envolver=False)
        if baro.activo:
            bloque.reloj(grande, lambda b=baro: t("Ya se ha ido") if _terminado(b.expira)
                         else t("Se va en {tiempo}", tiempo=tiempo_grande(b.expira)))
            lugar = t("Está en {lugar}", lugar=baro.lugar) if baro.lugar else ""
        else:
            bloque.reloj(grande, lambda b=baro: t("Llega en {tiempo}", tiempo=tiempo_grande(b.llegada))
                         if b.llegada and not _terminado(b.llegada) else t("Llega pronto"))
            lugar = baro.lugar
            if baro.llegada and baro.expira and baro.expira > baro.llegada:
                dias = round((baro.expira - baro.llegada).total_seconds() / 86400)
                if dias >= 1:
                    lugar = " · ".join(x for x in (lugar, t("se queda {n} días", n=dias)) if x)
        izquierda = columna(grande, bloque.preparar(_recortada(lugar, "pequeno")) if lugar else None,
                            espacio=0)
        if baro.activo:
            bloque.anadir_fila(izquierda, None)
        else:
            bloque.anadir_fila(izquierda, None, self._boton_aviso(t("Avisarme"), "baro"))

        if not baro.activo:
            bloque.vacia(t("Cuando llegue verás aquí lo que trae, con lo que te falta marcado."))
            if completo:
                bloque.vacia(t("Guarda piezas Prime repetidas para cambiarlas por ducados cuando llegue"))
            return
        if not baro.inventario:
            bloque.vacia(t("Inventario todavía sin publicar"))
            return
        # Lo que cubre un objetivo, primero y marcado; luego por ducados.
        inventario = sorted(baro.inventario, key=lambda o: (not o.objetivo, -(o.ducados or 0)))
        utiles = [o for o in inventario if o.objetivo]
        lista = inventario if completo else utiles
        if completo:
            bloque.extra.setText(t("{n} objetos", n=len(inventario)))
        for o in lista:
            bloque.linea(self._html_objeto_baro(o), marcada=bool(o.objetivo))
        if not completo:
            if utiles:
                texto = t("Trae {n} cosas; {m} te sirven para tus metas.", n=len(inventario), m=len(utiles))
            else:
                texto = t("Trae {n} cosas; ninguna está en tus metas.", n=len(inventario))
            bloque.caja.addWidget(bloque.texto(
                _esc(texto) + f" <a href='sub:tienda' style='color:{p['acento']};text-decoration:none'>"
                + _esc(t("Verlo todo")) + " ›</a>", "pequeno"))
        else:
            bloque.anadir_fila(None, self._boton_aviso(t("Avisarme si trae algo de mis metas"), "baro_objetivo"))

    def _html_objeto_baro(self, o) -> str:
        p = PALETA
        precio = []
        if o.ducados:
            precio.append(glosario.enlace("ducados", t("{n} ducados", n=o.ducados), p["suave"]))
        if o.creditos:
            precio.append(f"<span style='color:{p['suave']}'>{o.creditos:,} cr</span>".replace(",", "."))
        nombre = _esc(o.nombre_mostrar)
        if o.item_id:
            nombre = f"<a style='color:{p['texto']};text-decoration:none' href='item:{o.item_id}'>{nombre}</a>"
        texto = f"{nombre} · {' · '.join(precio)}" if precio else nombre
        if o.objetivo:
            texto += f" <span style='color:{p['acento']}'>★ {_esc(t('cubre un objetivo'))}</span>"
        return texto

    def _pintar_teshin(self, bloque: Bloque, completo: bool) -> None:
        mundo = self.mundo
        if mundo is None:
            self._vacia(bloque, t("Consultando el estado del mundo..."))
            return
        if self._texto_sin_datos():
            self._vacia(bloque, "")
            return
        ahora = datetime.now(timezone.utc)
        nombre, fin, fuente = avisos_mundo.teshin_actual(mundo, ahora)
        coste = ""
        if fuente == "api":
            coste = next((r.detalle for r in mundo.acero if r.texto), "")
        oferta = bloque.preparar(_recortada(avisos_mundo.nombre_teshin(nombre), "seccion"))
        izquierda = columna(oferta, bloque.texto(_esc(coste), "pequeno") if coste else None, espacio=0)
        cuando = bloque.texto(t("cambia en"), "pequeno", tinta="tenue", envolver=False)
        cuando.setAlignment(Qt.AlignRight)
        tiempo = bloque.texto("", "dato", tinta="suave", mayus=True, envolver=False)
        tiempo.setAlignment(Qt.AlignRight)
        bloque.reloj(tiempo, lambda e=fin: tiempo_grande(e))
        bloque.anadir_fila(izquierda, None, columna(cuando, tiempo, espacio=0))
        if fuente != "api":
            bloque.caja.addWidget(bloque.texto(_esc(t(
                "La API no lo ha publicado: sale de la rotación semanal fija del juego, que casi nunca cambia.")),
                "pequeno", tinta="tenue"))
        if not completo:
            return
        bloque.subtitulo(t("Las próximas semanas"))
        siguientes = avisos_mundo.teshin_siguientes(mundo, ahora)
        if siguientes is None:
            bloque.vacia(t("No se puede saber: lo de esta semana no está en la rotación conocida."))
        else:
            for nombre_sig, desde in siguientes:
                dia = (desde + timedelta(minutes=1)).astimezone()
                bloque.linea(f"<span style='color:{PALETA['suave']}'>"
                             + _esc(t("Desde el {dia}/{mes}", dia=dia.day, mes=dia.month))
                             + f"</span> · <b>{_esc(avisos_mundo.nombre_teshin(nombre_sig))}</b>")
        bloque.caja.addWidget(bloque.texto(_esc(t(
            "Recuerda: cada semana Palladino, en Estela de Hierro, cambia Fragmentos de Agrietado por Kuva.")),
            "pequeno"))
        bloque.anadir_fila(None, self._boton_aviso(t("Avisarme cada semana"), "teshin_cambio"))

    # Hoy, invasiones, alertas y ciclos -----------------------------------------------

    def _fila_hoy(self, bloque: Bloque, titulo: str, tinta: str, resumen: str, detalle: str) -> QWidget:
        p = PALETA
        rotulo = EtiquetaC(titulo, "dato", mayus=True, envolver=False)
        rotulo.setStyleSheet(f"color: {color(tinta).name()}; letter-spacing: 1px;")
        valor = bloque.texto(
            f"<a href='sub:eventos' style='color:{p['suave']};text-decoration:none'>{_esc(resumen)}</a>",
            "pequeno", envolver=False)
        valor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        _encogible(valor)
        caja = bloque.anadir_fila(Rombo(8, tinta), rotulo, valor, espacio=6)
        caja.layout().setStretch(2, 1)
        caja.setToolTip(detalle)
        return caja

    @staticmethod
    def _resumen_lista(lista) -> tuple[str, str]:
        """('Amaltea, Jupiter y 2 mas', detalle linea a linea) de la incursion o los arcontes."""
        if not lista:
            return "", ""
        primero = lista[0].texto.split(" - ", 1)[0]
        resumen = t("{primero} y {n} más", primero=primero, n=len(lista) - 1) if len(lista) > 1 else primero
        lineas = [r.texto + (f" ({r.detalle})" if r.detalle else "") for r in lista]
        fin = tiempo_restante(lista[0].expira)
        if fin and fin != "terminado":
            lineas.append(t("Termina en {tiempo}", tiempo=fin))
        return resumen, "\n".join(lineas)

    def _pintar_hoy(self, bloque: Bloque, escondidas: set[str]) -> None:
        mundo = self.mundo
        if mundo is None or self._texto_sin_datos():
            self._vacia(bloque, t("Consultando el estado del mundo..."))
            return
        if "sortie" not in escondidas:
            resumen, detalle = self._resumen_lista(mundo.sortie)
            self._fila_hoy(bloque, t("Incursión"), "acento", resumen or t("sin publicar ahora"), detalle)
            resumen, detalle = self._resumen_lista(mundo.arcontes)
            self._fila_hoy(bloque, t("Caza de arcontes"), COLOR_ARCONTES, resumen or t("sin publicar ahora"), detalle)
        if "nightwave" not in escondidas:
            diarios = sum(1 for r in mundo.nightwave if r.texto.startswith(f"[{t('diario')}]"))
            semanales = len(mundo.nightwave) - diarios
            if mundo.nightwave:
                resumen = " · ".join(x for x in (
                    t("{n} diarios", n=diarios) if diarios != 1 else t("1 diario"),
                    t("{n} semanales", n=semanales) if semanales != 1 else t("1 semanal")) if x)
            else:
                resumen = t("sin retos ahora")
            detalle = "\n".join(r.texto for r in mundo.nightwave)
            self._fila_hoy(bloque, t("Onda nocturna"), "secundario", resumen, detalle)
        arbitraje = mundo.arbitracion
        if arbitraje is not None and not _terminado(arbitraje.expira):
            resumen = arbitraje.texto
            detalle = " · ".join(x for x in (arbitraje.texto, arbitraje.detalle) if x)
        else:
            resumen, detalle = t("sin publicar ahora"), ""
        self._fila_hoy(bloque, t("Arbitraje"), "suave", resumen, detalle)

    def _html_premios(self, objetos) -> str:
        """Las recompensas como enlaces: con ficha en el indice la abren; si no, se buscan en Buscar."""
        p = PALETA
        trozos = []
        vistos = set()
        for o in objetos or []:
            nombre = (f"{o.cantidad}× " if o.cantidad > 1 else "") + o.nombre_mostrar
            if nombre in vistos:
                continue
            vistos.add(nombre)
            destino = f"item:{o.item_id}" if o.item_id else "buscar:" + quote(o.nombre_mostrar, safe="")
            trozos.append(
                f"<a style='color:{p['acento']};text-decoration:underline;font-weight:600' href='{destino}'>"
                f"{_esc(nombre)}</a> ›"
            )
        return "&nbsp;&nbsp; ".join(trozos)

    def _pintar_invasiones(self, bloque: Bloque, completo: bool) -> None:
        p = PALETA
        mundo = self.mundo
        if mundo is None:
            self._vacia(bloque, t("Consultando el estado del mundo..."))
            return
        invasiones = mundo.invasiones
        bloque.contador(len(invasiones)) if invasiones else None
        lista = invasiones if completo else invasiones[:MAX_INVASIONES]
        for i in lista:
            nombre, planeta = _partir_nodo(i.nodo)
            ca, cd = color_faccion(i.atacante), color_faccion(i.defensor)
            piezas = [bloque.preparar(EtiquetaC(nombre, "fuerte"))]
            if planeta:
                piezas.append(bloque.preparar(EtiquetaC(planeta, "pequeno")))
            piezas.append(None)
            if i.atacante and i.defensor:
                bandos = t("{atacante} contra {defensor}",
                           atacante=f"<span style='color:{ca};font-weight:600'>{_esc(i.atacante)}</span>"
                                    f"<span style='color:{p['tenue']}'>",
                           defensor=f"</span><span style='color:{cd};font-weight:600'>{_esc(i.defensor)}</span>")
                piezas.append(bloque.preparar(EtiquetaC(bandos, "pequeno")))
            bloque.anadir_fila(*piezas, espacio=5)
            barra = BarraBandos(abs(i.porcentaje) / 100, ca, cd)
            barra.setToolTip(t("{n}% hecho", n=f"{abs(i.porcentaje):.0f}"))
            bloque.caja.addWidget(barra)
            premios = self._html_premios(getattr(i, "objetos", []))
            if not premios and i.recompensas:
                premios = _esc(i.recompensas)
            if premios:
                bloque.caja.addWidget(bloque.texto(premios, "normal"))
        sobran = len(invasiones) - len(lista)
        if sobran > 0:
            bloque.caja.addWidget(bloque.texto(
                f"<a href='sub:eventos' style='color:{p['acento']};text-decoration:none'>"
                + _esc(t("y {n} invasiones más", n=sobran)) + " ›</a>", "pequeno"))
        if not invasiones:
            self._vacia(bloque, t("No hay invasiones activas"))

    def _pintar_alertas(self, bloque: Bloque) -> None:
        p = PALETA
        mundo = self.mundo
        if mundo is None or self._texto_sin_datos():
            self._vacia(bloque, t("Consultando el estado del mundo..."))
            return
        alertas = [a for a in mundo.alertas if not _terminado(a.expira)]
        if alertas:
            bloque.contador(len(alertas))
        for a in alertas:
            premios = self._html_premios(getattr(a, "objetos", []))
            texto = _esc(a.texto)
            if premios:
                nodo = a.texto.split(" - ", 1)[0]
                texto = f"<b>{_esc(nodo)}</b> &middot; {premios}"
            if a.detalle:
                texto += f" <span style='color:{p['suave']}'>{_esc(a.detalle)}</span>"
            bloque.linea(texto, a.expira)
        if not alertas:
            bloque.caja.addWidget(bloque.texto(_esc(t("Ahora no hay ninguna alerta.")), "fuerte"))
            bloque.caja.addWidget(bloque.texto(_esc(t(
                "Suelen traer catalizadores, reactores o aspectos. Si quieres, te aviso en cuanto salga una.")),
                "pequeno"))
        bloque.anadir_fila(self._boton_aviso(t("Avisarme de alertas"), "alertas"), None)

    def _pintar_arbitraje(self, bloque: Bloque) -> None:
        mundo = self.mundo
        if mundo is None or self._texto_sin_datos():
            self._vacia(bloque, t("Consultando el estado del mundo..."))
            return
        a = mundo.arbitracion
        if a is not None and not _terminado(a.expira):
            bloque.linea(f"<b>{_esc(a.texto)}</b> <span style='color:{PALETA['suave']}'>"
                         f"{_esc(a.detalle)}</span>", a.expira)
        else:
            bloque.vacia(t("Ahora no hay arbitraje publicado"))
        bloque.anadir_fila(self._boton_aviso(t("Avisarme de arbitrajes"), "arbitraje"), None)

    def _pintar_ciclos(self, bloque: Bloque) -> None:
        mundo = self.mundo
        if mundo is None:
            self._vacia(bloque, t("Consultando el estado del mundo..."))
            return
        for c in mundo.ciclos:
            noche = (c.estado_en or "").lower() in _NOCHE
            tiempo = bloque.preparar(EtiquetaC("", "pequeno"))
            caja = bloque.anadir_fila(icono("luna" if noche else "sol", 14, "secundario" if noche else "acento"),
                                      bloque.preparar(EtiquetaC(c.nombre, "fuerte")),
                                      bloque.preparar(EtiquetaC(c.estado, "pequeno")), None, tiempo, espacio=6)
            if c.expira is not None:
                bloque.reloj(tiempo, lambda e=c.expira: None if _terminado(e) else tiempo_restante(e), ocultar=caja)
        if not mundo.ciclos:
            self._vacia(bloque, t("Sin datos de ciclos"))

    def _pintar_sortie(self, bloque: Bloque) -> None:
        p = PALETA
        mundo = self.mundo
        if mundo is None:
            self._vacia(bloque, t("Consultando el estado del mundo..."))
            return
        if mundo.sortie:
            bloque.cuenta_atras(mundo.sortie[0].expira)
            bloque.subtitulo(t("Incursión del día"))
            for r in mundo.sortie:
                bloque.linea(
                    _esc(r.texto)
                    + (f" <span style='color:{p['suave']}'>{_esc(r.detalle)}</span>" if r.detalle else "")
                )
        if mundo.arcontes:
            bloque.subtitulo(t("Caza de arcontes"))
            fin = bloque.texto("", "pequeno")
            bloque.caja.addWidget(fin)
            bloque.reloj(fin, lambda e=mundo.arcontes[0].expira: t("Termina en {tiempo}", tiempo=tiempo_restante(e))
                         if e and not _terminado(e) else "")
            for r in mundo.arcontes:
                bloque.linea(_esc(r.texto))
        if not (mundo.sortie or mundo.arcontes):
            self._vacia(bloque, t("Sin incursión ni caza de arcontes"))

    def _pintar_nightwave(self, bloque: Bloque) -> None:
        p = PALETA
        mundo = self.mundo
        if mundo is None:
            self._vacia(bloque, t("Consultando el estado del mundo..."))
            return
        bloque.contador(len(mundo.nightwave)) if mundo.nightwave else None
        for r in mundo.nightwave:
            bloque.linea(
                f"{_esc(r.texto)} <span style='color:{p['suave']}'>{_esc(r.detalle)}</span>",
                r.expira,
            )
        if not mundo.nightwave:
            self._vacia(bloque, t("Sin retos activos"))
