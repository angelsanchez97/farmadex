"""Tablero: la pagina con la que se abre Farmadex (rediseno C).

De un vistazo, lo que toca hacer ahora: un buscador que salta a Buscar, "Tu siguiente
paso" (de tus metas pendientes, la pieza que antes se consigue, con su reliquia, la
mision y en que fisura abrirla), las fisuras abiertas que te sirven, tus metas con su
progreso, los ciclos del mundo y lo ultimo que ha salido.

No calcula nada nuevo: la ruta de cada meta es la de Objetivos (`objetivos.ruta_de`,
que es `relaciones.mejor_ruta`), las eras que hacen falta son las de Mundo
(`objetivos.eras_necesarias`, misma regla en `eras_de`) y las fisuras se ordenan como
en Mundo (rapidas primero). Todo se pinta en diferido y solo con la pagina a la vista:
cada cambio en Objetivos avisa, pero el calculo espera a que se vea el Tablero.
"""

from __future__ import annotations

import html
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from ..datos import novedades
from ..estado import objetivos as estado_objetivos
from ..idiomas import nombre as nombre_idioma, t
from ..registro_log import obtener
from . import widgets
from .estilo_c import (
    BotonC,
    CasillaC,
    EtiquetaC,
    EtiquetaEra,
    PanelC,
    Pedestal,
    Rombo,
    columna,
    fila,
    icono,
    px,
    transparente,
)

log = obtener("tablero")

MAX_FISURAS = 5
MAX_METAS = 4
MAX_CICLOS = 4
MAX_NOVEDADES = 5
REFRESCO_RELOJES_MS = 30_000

# Estados de ciclo (en ingles, como los da la API) que se pintan con la luna.
_NOCHE = {"night", "cold", "fass"}


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def texto_tiempo(minutos: float | None) -> str:
    """'25 min', '1 h 09 min', '3 d'. Vacio sin estimacion."""
    if minutos is None or (isinstance(minutos, float) and math.isnan(minutos)):
        return ""
    minutos = max(0, round(minutos))
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    if horas >= 48:
        return f"{round(horas / 24)} d"
    return f"{horas} h {resto:02d} min" if resto else f"{horas} h"


def restante(expira: datetime | None, ahora: datetime | None = None) -> str:
    if not expira:
        return ""
    ahora = ahora or _ahora()
    return texto_tiempo(max(0.0, (expira - ahora).total_seconds() / 60))


# -- datos -----------------------------------------------------------------------------


@dataclass
class PasoMeta:
    """Una meta pendiente con la mejor forma de conseguirla hoy."""

    objetivo: estado_objetivos.Objetivo
    ruta: dict | None
    item: dict | None      # id, nombre, imagen, padre, imagen_padre (del indice)
    orden: int = 0         # posicion en la lista de objetivos (para las eras, como Mundo)

    @property
    def nombre(self) -> str:
        """'Sistemas de Citrine Prime' en el idioma de la interfaz (o el nombre guardado)."""
        if not self.item:
            return self.objetivo.nombre
        if self.item.get("padre"):
            return t("{nombre} de {padre}", nombre=self.item["nombre"], padre=self.item["padre"])
        return self.item["nombre"] or self.objetivo.nombre

    @property
    def es_reliquia(self) -> bool:
        return bool(self.ruta and self.ruta.get("tipo", "reliquia") == "reliquia" and self.ruta.get("reliquia"))

    @property
    def boveda(self) -> bool:
        return bool(self.ruta and self.ruta.get("solo_en_boveda"))

    @property
    def minutos(self) -> float | None:
        if not self.ruta:
            return None
        return self.ruta.get("minutos_pieza") or self.ruta.get("minutos_medios")

    @property
    def farmeable(self) -> bool:
        return bool(self.ruta) and not self.boveda and self.minutos is not None

    @property
    def era(self) -> str:
        if not self.es_reliquia:
            return ""
        return (self.ruta["reliquia"].get("nombre_en") or "").split(" ")[0]

    @property
    def reliquia(self) -> str:
        """'Lith S19', sin la palabra reliquia."""
        if not self.es_reliquia:
            return ""
        texto = nombre_idioma(self.ruta["reliquia"])
        for sobra in ("Reliquia ", " Relic", "Relic "):
            texto = texto.replace(sobra, "")
        return texto.strip()

    @property
    def mision(self) -> dict:
        return (self.ruta or {}).get("mision") or {}

    @property
    def imagen(self) -> str | None:
        """La del set si es una pieza (se reconoce mejor), si no la suya."""
        if not self.item:
            return None
        return self.item.get("imagen_padre") or self.item.get("imagen")


def _item(indice: sqlite3.Connection, unique_name: str) -> dict | None:
    fila_item = indice.execute(
        "SELECT i.id, i.nombre_es, i.nombre_en, i.imagen, p.nombre_es, p.nombre_en, p.imagen "
        "FROM items i LEFT JOIN items p ON p.id = i.padre_id WHERE i.unique_name = ?",
        (unique_name,),
    ).fetchone()
    if not fila_item:
        return None
    item_id, es, en, imagen, padre_es, padre_en, imagen_padre = fila_item
    padre = nombre_idioma({"nombre_es": padre_es, "nombre_en": padre_en}) if (padre_es or padre_en) else ""
    return {"id": item_id, "nombre": nombre_idioma({"nombre_es": es, "nombre_en": en}), "imagen": imagen,
            "padre": padre, "imagen_padre": imagen_padre}


def pasos_pendientes(indice: sqlite3.Connection | None, usuario: sqlite3.Connection,
                     cache: dict | None = None) -> list[PasoMeta]:
    """Las metas sin completar, de la que antes se consigue a la que mas cuesta.

    Primero lo que se puede farmear hoy (con tiempo estimado), de menos a mas minutos;
    detras lo que esta en la boveda o no tiene estimacion. `cache` guarda la ruta de
    cada objeto entre llamadas (la ruta no depende del progreso)."""
    pasos = []
    for orden, objetivo in enumerate(estado_objetivos.listar(usuario)):
        if objetivo.completado:
            continue
        ruta = item = None
        if indice is not None:
            if cache is not None and objetivo.unique_name in cache:
                ruta, item = cache[objetivo.unique_name]
            else:
                ruta = estado_objetivos.ruta_de(indice, objetivo.unique_name)
                item = _item(indice, objetivo.unique_name)
                if cache is not None:
                    cache[objetivo.unique_name] = (ruta, item)
        pasos.append(PasoMeta(objetivo, ruta, item, orden))
    pasos.sort(key=lambda p: (not p.farmeable, p.minutos if p.minutos is not None else math.inf, p.orden))
    return pasos


def eras_de(pasos: list[PasoMeta]) -> dict[str, list[str]]:
    """Que eras de reliquia hacen falta: la misma regla que `objetivos.eras_necesarias`
    (lo que usa Mundo para marcar fisuras), sin volver a calcular las rutas."""
    salida: dict[str, list[str]] = {}
    for paso in sorted(pasos, key=lambda p: p.orden):
        if paso.es_reliquia and not paso.boveda and paso.era:
            salida.setdefault(paso.era, []).append(paso.objetivo.nombre)
    return salida


def fisuras_utiles(mundo, pasos: list[PasoMeta], ahora: datetime | None = None) -> list[tuple[object, PasoMeta]]:
    """Fisuras abiertas (normales, sin Acero ni Tormenta) de una era que te hace falta,
    cada una con la meta a la que sirve (la mas rapida de esa era). Rapidas primero,
    como en Mundo."""
    from .pestana_mundo import rapidez

    if mundo is None:
        return []
    ahora = ahora or _ahora()
    por_era: dict[str, PasoMeta] = {}
    for paso in pasos:  # ya van de la mas rapida a la mas lenta
        if paso.es_reliquia and not paso.boveda and paso.era and paso.era not in por_era:
            por_era[paso.era] = paso
    salida = []
    for f in getattr(mundo, "fisuras", []) or []:
        if f.acero or f.tormenta or f.era not in por_era:
            continue
        if f.expira and f.expira <= ahora:
            continue
        salida.append((f, por_era[f.era]))
    salida.sort(key=lambda par: (rapidez(par[0].mision), -((par[0].expira - ahora).total_seconds()
                                                           if par[0].expira else 0)))
    return salida


def fisuras_abiertas(mundo, era: str, ahora: datetime | None = None) -> int:
    ahora = ahora or _ahora()
    return sum(
        1 for f in (getattr(mundo, "fisuras", []) or [])
        if f.era == era and not f.acero and not f.tormenta and not (f.expira and f.expira <= ahora)
    )


# -- piezas de la pagina ----------------------------------------------------------------


def _vaciar(capa) -> None:
    while capa.count():
        elemento = capa.takeAt(0)
        if elemento.widget() is not None:
            elemento.widget().hide()
            elemento.widget().deleteLater()
        elif elemento.layout() is not None:
            _vaciar(elemento.layout())


class Hito(PanelC):
    """Linea con rombo, rotulo y texto: "ÁBRELA EN UNA FISURA LITH — 3 abiertas ahora"."""

    def __init__(self, titulo: str, texto: str, tinta: str, clicable: bool = False):
        super().__init__(remate=False, fondo="panel2", borde="borde", chaflan=7, clicable=clicable)
        self.capa.setContentsMargins(px(14, False), px(8, False), px(14, False), px(8, False))
        self.rotulo_hito = EtiquetaC(titulo, "rotulo", tinta=tinta, mayus=True)
        self.texto = EtiquetaC(texto, "normal", recortar=True)
        self.texto.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.capa.addLayout(fila(Rombo(9, tinta), self.rotulo_hito, None, self.texto, espacio=8))


class PestanaTablero(QWidget):
    """La pagina TABLERO. La ventana le da el indice, la BD del usuario y el mundo."""

    buscar = Signal(str)       # texto tecleado en su buscador: seguir en Buscar
    abrir_item = Signal(int)   # abrir la ficha de un objeto en Buscar
    navegar = Signal(str)      # ir a otra seccion ("metas/objetivos", "mundo"...)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.indice: sqlite3.Connection | None = None
        self.usuario: sqlite3.Connection | None = None
        self.mundo = None
        self._fallo_mundo: str | None = None
        self._rutas: dict = {}
        self._pasos: list[PasoMeta] = []
        self._sucio = True
        self._imagenes_pedidas: dict[str, list] = {}

        self._diferido = QTimer(self)
        self._diferido.setSingleShot(True)
        self._diferido.setInterval(120)
        self._diferido.timeout.connect(self.refrescar)
        self._relojes = QTimer(self)
        self._relojes.setInterval(REFRESCO_RELOJES_MS)
        self._relojes.timeout.connect(self._pintar_mundo)
        widgets.imagenes().lista.connect(self._imagen_lista)

        # Buscador: al teclear se sigue en la pagina Buscar con lo escrito.
        self.panel_buscar = PanelC(remate=False, fondo="panel2", borde="acento_tenue")
        self.panel_buscar.capa.setContentsMargins(px(18, False), px(2, False), px(18, False), px(2, False))
        self.caja = QLineEdit()
        self.caja.setObjectName("cajaC")
        self.caja.textEdited.connect(self._tecleado)
        self.caja.returnPressed.connect(lambda: self.buscar.emit(self.caja.text()))
        self.pista_enter = EtiquetaC("Enter", "pequeno", tinta="tenue")
        self.panel_buscar.capa.addLayout(fila(icono("buscar", 19), self.caja, self.pista_enter, espacio=8))

        self.heroe = PanelC(t("Tu siguiente paso"))
        self.capa_heroe = QVBoxLayout()
        self.capa_heroe.setSpacing(0)
        self.heroe.capa.addLayout(self.capa_heroe, 1)

        self.panel_fisuras = PanelC(t("Fisuras que te sirven"))
        self.capa_fisuras = QVBoxLayout()
        self.capa_fisuras.setSpacing(px(10, False))
        self.panel_fisuras.capa.addLayout(self.capa_fisuras)
        self.panel_fisuras.capa.addStretch(1)
        self.boton_mundo = BotonC(t("Ver el mundo"))
        self.boton_mundo.clicked.connect(lambda: self.navegar.emit("mundo"))
        self.panel_fisuras.cabecera.addWidget(self.boton_mundo)

        self.panel_metas = PanelC(t("Mis metas"))
        self.capa_metas = QHBoxLayout()
        self.capa_metas.setSpacing(px(12, False))
        self.panel_metas.capa.addLayout(self.capa_metas, 1)
        self.boton_metas = BotonC(t("Ver todas"))
        self.boton_metas.clicked.connect(lambda: self.navegar.emit("metas/objetivos"))
        self.panel_metas.cabecera.addWidget(self.boton_metas)

        self.panel_ciclos = PanelC(t("Ciclos"))
        self.capa_ciclos = QVBoxLayout()
        self.capa_ciclos.setSpacing(px(8, False))
        self.panel_ciclos.capa.addLayout(self.capa_ciclos)
        self.panel_ciclos.capa.addStretch(1)

        # Lo ultimo que ha salido, en una linea al pie.
        self.rotulo_novedades = EtiquetaC(t("Novedades"), "rotulo", mayus=True)
        self.texto_novedades = EtiquetaC("", "normal")
        self.texto_novedades.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.texto_novedades.linkActivated.connect(self._enlace)
        self.linea_novedades = transparente(QWidget())
        self.linea_novedades.setLayout(fila(Rombo(8, "acento"), self.rotulo_novedades, 6, self.texto_novedades,
                                            None, espacio=8, margen=(px(4, False), 0, 0, 0)))
        self.linea_novedades.hide()

        contenido = QWidget()
        cuerpo = QVBoxLayout(contenido)
        cuerpo.setContentsMargins(0, px(4, False), px(4, False), px(4, False))
        cuerpo.setSpacing(px(16, False))
        cuerpo.addWidget(self.panel_buscar)
        arriba = QHBoxLayout()
        arriba.setSpacing(px(16, False))
        arriba.addWidget(self.heroe, 3)
        arriba.addWidget(self.panel_fisuras, 2)
        cuerpo.addLayout(arriba, 1)
        abajo = QHBoxLayout()
        abajo.setSpacing(px(16, False))
        abajo.addWidget(self.panel_metas, 3)
        abajo.addWidget(self.panel_ciclos, 2)
        cuerpo.addLayout(abajo)
        cuerpo.addWidget(self.linea_novedades)
        contenido.setMinimumHeight(px(540, False))

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(contenido)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.addWidget(area)
        self._textos_fijos()
        self.refrescar()

    # -- conexion con la ventana -----------------------------------------------------------

    def conectar(self, indice: sqlite3.Connection | None, usuario: sqlite3.Connection | None) -> None:
        self.indice = indice
        self.usuario = usuario
        self._rutas.clear()
        self.marcar_sucio()

    def conectar_indice(self, indice: sqlite3.Connection | None) -> None:
        self.conectar(indice, self.usuario)

    def actualizar_mundo(self, mundo) -> None:
        self.mundo = mundo
        self._fallo_mundo = None
        self._pintar_mundo()

    def marcar_desactualizado(self, motivo: str) -> None:
        self._fallo_mundo = motivo
        self._pintar_mundo()

    def marcar_sucio(self) -> None:
        """Algo ha cambiado (objetivos, ritmo, indice): se recalcula al verse la pagina."""
        self._sucio = True
        if self.isVisible():
            self._diferido.start()

    def olvidar_rutas(self) -> None:
        """El ritmo de juego cambia los tiempos: las rutas guardadas ya no valen."""
        self._rutas.clear()
        self.marcar_sucio()

    def showEvent(self, evento):  # noqa: N802 - firma de Qt
        super().showEvent(evento)
        self._relojes.start()
        if self._sucio:
            self._diferido.start()
        else:
            self._pintar_mundo()

    def hideEvent(self, evento):  # noqa: N802
        super().hideEvent(evento)
        self._relojes.stop()

    def retraducir(self) -> None:
        self._textos_fijos()
        self._rutas.clear()  # los nombres del indice van en el idioma de la interfaz
        self.refrescar()

    def repintar(self) -> None:
        """Tras cambiar de tema: lo que lleva color dentro del HTML se vuelve a escribir."""
        self.refrescar()

    def _textos_fijos(self) -> None:
        self.caja.setPlaceholderText(t("Busca un objeto, una reliquia o una mision"))
        self.heroe.poner_titulo(t("Tu siguiente paso"))
        self.panel_fisuras.poner_titulo(t("Fisuras que te sirven"))
        self.panel_metas.poner_titulo(t("Mis metas"))
        self.panel_ciclos.poner_titulo(t("Ciclos"))
        self.rotulo_novedades.setText(t("Novedades"))
        self.boton_mundo.setText(t("Ver el mundo"))
        self.boton_metas.setText(t("Ver todas"))

    # -- acciones -----------------------------------------------------------------------------

    def _tecleado(self, texto: str) -> None:
        if texto:
            self.caja.clear()
            self.buscar.emit(texto)

    def _enlace(self, href: str) -> None:
        if href.startswith("item:"):
            self.abrir_item.emit(int(href.split(":", 1)[1]))
        elif href.startswith("novedades"):
            self.buscar.emit("novedades")

    def enfocar(self) -> None:
        self.caja.setFocus()

    # -- pintado --------------------------------------------------------------------------------

    def refrescar(self) -> None:
        self._sucio = False
        self._pasos = []
        indice = self._indice_vivo()
        if self.usuario is not None and indice is not None:
            try:
                self._pasos = pasos_pendientes(indice, self.usuario, self._rutas)
            except sqlite3.Error:
                log.warning("No se pudieron calcular las metas del Tablero", exc_info=True)
                self._pasos = []
        self._pintar_heroe()
        self._pintar_metas()
        self._pintar_mundo()
        self._pintar_novedades()

    def _indice_vivo(self) -> sqlite3.Connection | None:
        if self.indice is None:
            return None
        try:
            self.indice.execute("SELECT 1")
        except sqlite3.Error:
            self.indice = None  # se esta reconstruyendo
        return self.indice

    def _hay_objetivos(self) -> bool:
        if self.usuario is None:
            return False
        try:
            return bool(estado_objetivos.listar(self.usuario))
        except sqlite3.Error:
            return False

    def _pixmap(self, nombre: str | None, lado: int, destino) -> None:
        """Pone la imagen si ya esta en disco; si no, se pide y se pone al llegar."""
        if not nombre:
            destino(None)
            return
        mapa = widgets.imagenes().pixmap(nombre, lado)
        destino(mapa)
        if mapa is None:
            self._imagenes_pedidas.setdefault(nombre, []).append((lado, destino))

    def _imagen_lista(self, nombre: str) -> None:
        for lado, destino in self._imagenes_pedidas.pop(nombre, []):
            try:
                destino(widgets.imagenes().pixmap(nombre, lado))
            except RuntimeError:
                pass  # el widget ya se borro al repintar

    def _pintar_heroe(self) -> None:
        _vaciar(self.capa_heroe)
        self._imagenes_pedidas.clear()
        if not self._pasos:
            self._heroe_vacio()
            return
        paso = self._pasos[0]
        pedestal = Pedestal(240)
        self._pixmap(paso.imagen, 256, pedestal.poner_imagen)

        textos = QVBoxLayout()
        textos.setSpacing(px(6, False))
        titulo = EtiquetaC(paso.nombre, "titulo", mayus=True, envolver=True)
        textos.addWidget(titulo)
        mision = paso.mision
        if paso.es_reliquia:
            textos.addWidget(EtiquetaC(
                t("Reliquia {reliquia}", reliquia=f"<b style='color:{widgets.PALETA['secundario']}'>"
                  f"{html.escape(paso.reliquia)}</b>"), "destacado", tinta="suave"))
        if mision.get("donde"):
            lugar = f"<b style='color:{widgets.PALETA['texto']}'>{html.escape(mision['donde'])}</b>"
            texto = (t("{mision} en {lugar}", mision=html.escape(mision["mision"]), lugar=lugar)
                     if mision.get("mision") else lugar)
            textos.addWidget(EtiquetaC(texto, "normal", tinta="suave", envolver=True))
        textos.addSpacing(px(10, False))
        if paso.minutos is not None:
            tiempo = EtiquetaC(texto_tiempo(paso.minutos), "portada", mayus=True)
            nota = t("hasta tener la pieza") if paso.es_reliquia else t("hasta conseguirlo")
            textos.addLayout(fila(tiempo, EtiquetaC(nota, "normal", tinta="suave"), None, espacio=12))
        faltan = self._texto_faltan(paso)
        if faltan:
            textos.addWidget(EtiquetaC(faltan, "normal", tinta="suave", envolver=True))
        textos.addSpacing(px(12, False))
        for hito in self._hitos(paso):
            textos.addWidget(hito)
        textos.addStretch(1)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(px(20, False))
        cuerpo.addWidget(pedestal, 0, Qt.AlignVCenter)
        cuerpo.addLayout(textos, 1)
        contenedor = PanelC(remate=False, fondo="panel", borde="panel", clicable=True)
        contenedor.capa.setContentsMargins(0, 0, 0, 0)
        contenedor.capa.addLayout(cuerpo)
        contenedor.setToolTip(t("Abrir su ficha"))
        if paso.item:
            contenedor.pulsado.connect(lambda i=paso.item["id"]: self.abrir_item.emit(i))
        self.capa_heroe.addWidget(contenedor, 1)

    def _texto_faltan(self, paso: PasoMeta) -> str:
        objetivo = paso.objetivo
        if objetivo.grupo:
            quedan = sum(1 for p in self._pasos if p.objetivo.grupo == objetivo.grupo)
            conjunto = objetivo.grupo_nombre or objetivo.nombre.split(":")[0]
            if quedan == 1:
                return t("Es la ultima pieza que te falta de {set}", set=conjunto)
            return t("Te faltan {n} piezas de {set} para el set", n=quedan, set=conjunto)
        if objetivo.objetivo > 1:
            return t("Llevas {actual} de {total}", actual=objetivo.actual, total=objetivo.objetivo)
        return ""

    def _hitos(self, paso: PasoMeta) -> list[Hito]:
        hitos = []
        if paso.es_reliquia and paso.boveda:
            hitos.append(Hito(t("En la boveda"), t("Solo con reliquias que ya tengas"), "aviso"))
        elif paso.es_reliquia:
            if self.mundo is None:
                abiertas = t("Sin datos del mundo todavia")
            else:
                n = fisuras_abiertas(self.mundo, paso.era)
                abiertas = (t("Ninguna abierta ahora") if n == 0 else t("1 abierta ahora") if n == 1
                            else t("{n} abiertas ahora", n=n))
            hito = Hito(t("Abrela en una fisura {era}", era=paso.era), abiertas, "secundario", clicable=True)
            hito.pulsado.connect(lambda: self.navegar.emit("mundo"))
            hitos.append(hito)
        siguiente = next((p for p in self._pasos[1:] if p.farmeable), None)
        if siguiente is not None:
            detalle = " · ".join(x for x in (siguiente.reliquia, texto_tiempo(siguiente.minutos)) if x)
            hito = Hito(t("Despues"), f"{siguiente.nombre}: {detalle}" if detalle else siguiente.nombre, "acento",
                        clicable=bool(siguiente.item))
            if siguiente.item:
                hito.pulsado.connect(lambda i=siguiente.item["id"]: self.abrir_item.emit(i))
            hitos.append(hito)
        return hitos

    def _heroe_vacio(self) -> None:
        hay = self._hay_objetivos()
        if hay and self.indice is None:
            # Las metas ya se conocen, pero sin el indice no se sabe donde sale nada.
            self.capa_heroe.addLayout(columna(
                None, EtiquetaC(t("Comprobando datos..."), "seccion", tinta="suave"), None), 1)
            return
        if not hay:
            titulo, texto = t("Aun no tienes metas"), t(
                "Busca un objeto y pulsa \"+ Objetivo\". Aqui veras cual es la pieza que antes puedes "
                "conseguir, donde sale y en que fisura abrir su reliquia.")
        else:
            titulo, texto = t("Has conseguido todas tus metas"), t(
                "Busca algo nuevo que quieras farmear y anadelo con \"+ Objetivo\".")
        boton = BotonC(t("Buscar algo"), principal=True, icono="buscar")
        boton.clicked.connect(self.enfocar)
        self.capa_heroe.addLayout(columna(
            None, EtiquetaC(titulo, "titulo", mayus=True, envolver=True), 4,
            EtiquetaC(texto, "normal", tinta="suave", envolver=True), 10,
            fila(boton, None), None, espacio=6,
        ), 1)

    def _pintar_metas(self) -> None:
        _vaciar(self.capa_metas)
        if not self._pasos:
            if self.indice is None and self._hay_objetivos():
                texto = t("Comprobando datos...")
            elif not self._hay_objetivos():
                texto = t("Todavia no tienes metas. Busca algo y pulsa '+ Objetivo'.")
            else:
                texto = t("No te queda nada pendiente.")
            self.capa_metas.addWidget(EtiquetaC(texto, "normal", tinta="suave", envolver=True), 1)
            return
        # En progreso delante; dentro, el orden de "Tu siguiente paso".
        metas = sorted(self._pasos, key=lambda p: p.objetivo.estado != estado_objetivos.EN_PROGRESO)[:MAX_METAS]
        primero = self._pasos[0]
        for paso in metas:
            o = paso.objetivo
            casilla = CasillaC(paso.nombre, t("{actual} de {total}", actual=o.actual, total=o.objetivo),
                               o.actual / o.objetivo if o.objetivo else 0, marcada=paso is primero)
            casilla.setMinimumWidth(px(96, False))
            imagen = (paso.item or {}).get("imagen") or paso.imagen
            self._pixmap(imagen, 64, casilla.poner_imagen)
            casilla.setToolTip(t("Abrir su ficha"))
            if paso.item:
                casilla.pulsado.connect(lambda i=paso.item["id"]: self.abrir_item.emit(i))
            else:
                casilla.pulsado.connect(lambda: self.navegar.emit("metas/objetivos"))
            self.capa_metas.addWidget(casilla, 1)
        for _ in range(MAX_METAS - len(metas)):
            self.capa_metas.addStretch(1)

    def _pintar_mundo(self) -> None:
        self._pintar_fisuras()
        self._pintar_ciclos()

    def _texto_sin_mundo(self) -> str:
        if self._fallo_mundo:
            return t("No se pudo leer el estado del mundo. Se vuelve a intentar solo.")
        return t("Cargando el estado del mundo...")

    def _pintar_fisuras(self) -> None:
        _vaciar(self.capa_fisuras)
        if self.mundo is None:
            self.capa_fisuras.addWidget(EtiquetaC(self._texto_sin_mundo(), "normal", tinta="suave", envolver=True))
            return
        eras = eras_de(self._pasos)
        if not eras:
            self.capa_fisuras.addWidget(EtiquetaC(
                t("Cuando tengas metas que salen de reliquias, aqui veras las fisuras abiertas que te sirven."),
                "normal", tinta="suave", envolver=True))
            return
        utiles = fisuras_utiles(self.mundo, self._pasos)
        if not utiles:
            self.capa_fisuras.addWidget(EtiquetaC(
                t("Ninguna fisura abierta sirve ahora mismo. Necesitas:") + " " + ", ".join(eras),
                "normal", tinta="suave", envolver=True))
            return
        for f, paso in utiles[:MAX_FISURAS]:
            detalle = " · ".join(x for x in (f.mision, t("para {nombre}", nombre=paso.nombre)) if x)
            nodo = EtiquetaC(f.nodo, "destacado", recortar=True)
            linea = EtiquetaC(detalle, "pequeno", recortar=True)
            caja = transparente(QWidget())
            caja.setLayout(fila(Rombo(10, "secundario"), EtiquetaEra(f.era), 4,
                                columna(nodo, linea, espacio=0),
                                EtiquetaC(restante(f.expira), "normal", tinta="suave"), espacio=8))
            self.capa_fisuras.addWidget(caja)

    def _pintar_ciclos(self) -> None:
        _vaciar(self.capa_ciclos)
        if self.mundo is None:
            self.capa_ciclos.addWidget(EtiquetaC(self._texto_sin_mundo(), "normal", tinta="suave", envolver=True))
            return
        ciclos = list(getattr(self.mundo, "ciclos", []) or [])[:MAX_CICLOS]
        if not ciclos:
            self.capa_ciclos.addWidget(EtiquetaC(t("Sin datos de ciclos"), "normal", tinta="suave"))
            return
        for c in ciclos:
            noche = (c.estado_en or "").lower() in _NOCHE
            caja = transparente(QWidget())
            caja.setLayout(fila(icono("luna" if noche else "sol", 15, "secundario" if noche else "acento"),
                                EtiquetaC(c.nombre, "fuerte", recortar=True), EtiquetaC(c.estado, "normal", tinta="suave"),
                                None,
                                EtiquetaC(restante(c.expira), "normal", tinta="suave"), espacio=8))
            self.capa_ciclos.addWidget(caja)

    def _pintar_novedades(self) -> None:
        datos = None
        indice = self._indice_vivo()
        if indice is not None:
            try:
                datos = novedades.ultima(indice)
            except sqlite3.Error:
                datos = None
        if not datos or not datos.get("items"):
            self.linea_novedades.hide()
            return
        acento = widgets.PALETA["acento"]
        nombres = ", ".join(
            f"<a style='color:{acento};text-decoration:none' href='item:{f['item_id']}'>"
            f"{html.escape(nombre_idioma(f))}</a>" for f in datos["items"][:MAX_NOVEDADES]
        )
        if len(datos["items"]) > MAX_NOVEDADES:
            nombres += f", <a style='color:{acento};text-decoration:none' href='novedades'>&hellip;</a>"
        suave = widgets.PALETA["suave"]
        self.texto_novedades.setText(f"<span style='color:{suave}'>{html.escape(novedades.titulo(datos))}:</span> "
                                     f"{nombres}")
        self.linea_novedades.show()
