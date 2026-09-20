"""Pestana Perfil: importa el JSON de perfil de warframe.com y ensena que falta por dominar.

La capa de datos vive en `farmadex.perfil`; aqui solo se elige el fichero, se
lee en segundo plano (el guardado y el casado van en el hilo principal, que es
el dueno de las conexiones SQLite) y se pinta el resultado en HTML.
"""

from __future__ import annotations

import html
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import perfil as datos_perfil
from ..estado import usuario_db
from ..idiomas import glosa, nombre as nombre_idioma, t
from ..perfil import A_MEDIAS, DOMINADO, SIN_TOCAR, PerfilInvalido
from ..registro_log import obtener
from .pestana_buscador import categoria_es
from .widgets import COLOR_DISPONIBLE, PALETA, BarraProgreso

log = obtener("perfil_ui")

# Nombres oficiales en castellano de los sindicatos, por su etiqueta del perfil.
SINDICATOS = {
    "SteelMeridianSyndicate": "Meridiano de Acero",
    "ArbitersSyndicate": "Arbitros de Hexis",
    "CephalonSudaSyndicate": "Cefalon Suda",
    "PerrinSyndicate": "Secuencia Perrin",
    "RedVeilSyndicate": "Velo Rojo",
    "NewLokaSyndicate": "Nueva Loka",
    "CetusSyndicate": "Ostrones",
    "QuillsSyndicate": "Los Quills",
    "SolarisSyndicate": "Solaris Unidos",
    "VoxSyndicate": "Vox Solaris",
    "VentKidsSyndicate": "Ventkids",
    "EntratiSyndicate": "Entrati",
    "NecraloidSyndicate": "Necraloid",
    "ZarimanSyndicate": "Los Holdfasts",
    "EntratiLabSyndicate": "Cavia",
    "HexSyndicate": "Los Hex",
    "KahlSyndicate": "Guarnicion de Kahl",
    "ConclaveSyndicate": "Conclave",
}

# Intrinsecos: los de Railjack y los del Errante, en el orden del juego.
INTRINSECOS = {
    "LPS_PILOTING": "Pilotaje",
    "LPS_GUNNERY": "Artilleria",
    "LPS_TACTICAL": "Tactica",
    "LPS_ENGINEERING": "Ingenieria",
    "LPS_COMMAND": "Mando",
    "LPS_DRIFT_RIDING": "Monta",
    "LPS_DRIFT_COMBAT": "Combate",
    "LPS_DRIFT_OPPORTUNITY": "Oportunidad",
    "LPS_DRIFT_ENDURANCE": "Resistencia",
}
_INTRINSECOS_RAILJACK = ("LPS_PILOTING", "LPS_GUNNERY", "LPS_TACTICAL", "LPS_ENGINEERING", "LPS_COMMAND")

# La descarga del perfil desde warframe.com (getProfileViewingData.php) dejo de estar
# abierta en septiembre de 2026: devuelve 403 tambien con la sesion iniciada. La
# importacion desde fichero se queda por si DE la reabre o llega otra fuente (OCR).
_PREFIJOS_NODO = ("SolNode", "ClanNode", "SettlementNode")


class _LectorPerfil(QThread):
    """Lee y valida el fichero fuera del hilo de la interfaz. No toca ninguna BD."""

    leido = Signal(object)
    fallo = Signal(str)

    def __init__(self, ruta: Path, parent=None):
        super().__init__(parent)
        self.ruta = ruta

    def run(self) -> None:
        try:
            self.leido.emit(datos_perfil.cargar(self.ruta))
        except PerfilInvalido as e:
            self.fallo.emit(str(e))
        except Exception:  # noqa: BLE001 - un fichero raro no puede tumbar la ventana
            log.exception("Error leyendo el perfil %s", self.ruta)
            self.fallo.emit(t("No se pudo leer el fichero; mira el registro para el detalle"))


class PestanaPerfil(QWidget):
    perfil_cambiado = Signal()
    abrir_item = Signal(int)

    def __init__(self, usuario: sqlite3.Connection | None = None, parent=None):
        super().__init__(parent)
        self.usuario: sqlite3.Connection = usuario if usuario is not None else usuario_db.conectar()
        self.indice: sqlite3.Connection | None = None
        self._lector: _LectorPerfil | None = None
        self._ruta_en_curso: Path | None = None

        self.boton = QPushButton()
        self.boton.setObjectName("principal")
        self.boton.clicked.connect(self.elegir_fichero)
        self.filtro_acero = QCheckBox()
        self.filtro_acero.toggled.connect(lambda _: self.pintar())
        self.progreso = BarraProgreso()
        self.estado = QLabel("")
        self.estado.setWordWrap(True)
        self.estado.setTextFormat(Qt.PlainText)
        self._pintar_estado("")
        self.vista = QTextBrowser()
        self.vista.setOpenLinks(False)
        self.vista.anchorClicked.connect(self._enlace)

        fila = QHBoxLayout()
        fila.addWidget(self.boton)
        fila.addWidget(self.filtro_acero)
        fila.addStretch(1)
        fila.addWidget(self.progreso)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 8, 4, 4)
        caja.setSpacing(8)
        caja.addLayout(fila)
        caja.addWidget(self.estado)
        caja.addWidget(self.vista, 1)
        self.retraducir()

    # -- ciclo de vida -----------------------------------------------------------

    def conectar_indice(self, con: sqlite3.Connection | None) -> None:
        self.indice = con
        self.pintar()

    def retraducir(self) -> None:
        self.boton.setText(t("Importar perfil (JSON)..."))
        self.filtro_acero.setText(t("Nodos pendientes del Camino de Acero"))
        self._pintar_estado("")  # el aviso de la ultima importacion era de un solo uso
        self.pintar()

    def repintar(self) -> None:
        """Tras cambiar de tema: los colores van dentro del HTML."""
        self._pintar_estado(self.estado.text(), error=self.estado.property("error") or False)
        self.pintar()

    def hay_perfil(self) -> bool:
        return datos_perfil.hay_perfil(self.usuario)

    # -- importar ----------------------------------------------------------------

    def elegir_fichero(self) -> None:
        inicio = Path.home() / "Downloads"
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            t("Elige el JSON de tu perfil"),
            str(inicio if inicio.is_dir() else Path.home()),
            t("Perfil de Warframe (*.json);;Todos los ficheros (*)"),
        )
        if ruta:
            self.importar(Path(ruta))

    def importar(self, ruta: Path | str, en_segundo_plano: bool = True) -> None:
        """Lee el fichero (en su hilo, salvo que se pida lo contrario) y lo guarda."""
        ruta = Path(ruta)
        if self._lector is not None and self._lector.isRunning():
            return
        self._ruta_en_curso = ruta
        self._pintar_estado(t("Leyendo {fichero}...", fichero=ruta.name))
        if not en_segundo_plano:
            try:
                self._leido(datos_perfil.cargar(ruta))
            except PerfilInvalido as e:
                self._fallo(str(e))
            return
        self.boton.setEnabled(False)
        self.progreso.actualizar(t("Importando el perfil..."), 0, 0)
        self._lector = _LectorPerfil(ruta, self)
        self._lector.leido.connect(self._leido)
        self._lector.fallo.connect(self._fallo)
        self._lector.finished.connect(self._terminado)
        self._lector.start()

    def _terminado(self) -> None:
        self.boton.setEnabled(True)
        self.progreso.ocultar()

    def _leido(self, perfil) -> None:
        datos_perfil.guardar(self.usuario, perfil, self._ruta_en_curso)
        mensaje = t(
            "Perfil de {nombre} importado: rango de maestria {rango}, {objetos} objetos con XP y {nodos} nodos",
            nombre=perfil.nombre, rango=perfil.rango, objetos=len(perfil.xp), nodos=len(perfil.nodos),
        )
        if self.indice is not None:
            casado = datos_perfil.casar_con_catalogo(self.usuario, self.indice)
            if casado.sin_catalogo:
                mensaje += " " + t(
                    "({n} objetos del perfil no estan en el catalogo; probablemente son del ultimo parche)",
                    n=len(casado.sin_catalogo),
                )
                log.info("Sin catalogo: %s", ", ".join(casado.sin_catalogo[:20]))
        self._pintar_estado(mensaje)
        self.pintar()
        self.perfil_cambiado.emit()

    def _fallo(self, motivo: str) -> None:
        # El motivo viene del lector en castellano y ya es claro; no hace falta dialogo.
        self._pintar_estado(t("No se ha importado: {motivo}", motivo=motivo), error=True)

    def _pintar_estado(self, texto: str, error: bool = False) -> None:
        color = PALETA["aviso"] if error else PALETA["suave"]
        self.estado.setProperty("error", error)
        self.estado.setStyleSheet(f"color: {color};")
        self.estado.setText(texto)
        self.estado.setVisible(bool(texto))

    def _enlace(self, url: QUrl) -> None:
        texto = url.toString()
        if texto.startswith("item:"):
            self.abrir_item.emit(int(texto[5:]))
        elif texto.startswith("http"):
            import webbrowser

            webbrowser.open(texto)

    # -- pintar ------------------------------------------------------------------

    def pintar(self) -> None:
        if self.indice is None:
            self.vista.setHtml(_parrafo_suave(t("Preparando los datos...")))
            self.filtro_acero.setVisible(False)
            return
        if not self.hay_perfil():
            self.filtro_acero.setVisible(False)
            self.vista.setHtml(self._html_sin_perfil())
            return
        self.filtro_acero.setVisible(True)
        self.vista.setHtml(self._html_perfil())

    def _html_sin_perfil(self) -> str:
        p = PALETA
        return (
            f"<div style='font-size:18px;font-weight:bold;margin-bottom:8px'>"
            f"{html.escape(t('Perfil del jugador: preparado, pero hoy sin fuente de datos'))}</div>"
            f"<p style='color:{p['texto']}'>"
            + html.escape(t(
                "Digital Extremes no publica ahora mismo los datos del perfil: la descarga desde "
                "warframe.com que usaba esta pestana devuelve acceso denegado, tambien con la sesion iniciada."
            ))
            + "</p><p style='color:" + p["texto"] + "'>"
            + t(
                "Si consigues un fichero de perfil valido (por ejemplo, uno guardado antes), "
                "puedes importarlo con {boton}. Se esta estudiando leer el perfil directamente "
                "de tus propias pantallas del juego.",
                boton=f"<b>{html.escape(t('Importar perfil (JSON)...'))}</b>",
            )
            + "</p>"
            + _parrafo_suave(
                t("Con el perfil, la ficha de cada objeto en Buscar dice si ya lo has dominado, "
                  "y aqui veras lo que te falta por categoria y los nodos que no has completado. "
                  "Farmadex no pide nada a Digital Extremes: solo lee el fichero que tu le das.")
            )
        )

    def _html_perfil(self) -> str:
        usuario, indice = self.usuario, self.indice
        meta = datos_perfil.resumen(usuario) or {}
        conteo = datos_perfil.resumen_maestria(usuario, indice)
        acero = self.filtro_acero.isChecked()
        pendientes_nodos = datos_perfil.nodos_pendientes(usuario, indice, camino_acero=acero)
        total_nodos = self._total_nodos()
        partes = [self._cabecera(meta), self._tabla_maestria(conteo)]
        partes.append(self._bloque_nodos_resumen(total_nodos, len(pendientes_nodos), acero))
        partes.append(self._bloque_intrinsecos(meta.get("intrinsecos") or {}))
        partes.append(self._bloque_sindicatos(meta.get("sindicatos") or []))
        partes.append(self._bloque_pendientes(datos_perfil.pendientes_por_categoria(usuario, indice)))
        partes.append(self._bloque_nodos(pendientes_nodos, acero))
        return "".join(partes)

    def _cabecera(self, meta: dict) -> str:
        p = PALETA
        detalles = []
        if meta.get("clan"):
            detalles.append(t("Clan {clan}", clan=meta["clan"]))
        if meta.get("plataformas"):
            detalles.append(", ".join(meta["plataformas"]))
        importado = _fecha_local(meta.get("importado_en"))
        if importado:
            detalles.append(t("Importado el {fecha}", fecha=importado))
        if meta.get("fichero"):
            detalles.append(Path(meta["fichero"]).name)
        return (
            f"<div style='font-size:22px;font-weight:bold'>{html.escape(meta.get('nombre') or '')}"
            f" <span style='font-size:14px;color:{p['acento']}'>"
            f"{html.escape(t('Rango de maestria {n}', n=meta.get('rango', 0)))}</span></div>"
            f"<div style='color:{p['suave']};font-size:13px;margin-top:2px'>"
            f"{html.escape(' · '.join(detalles))}</div>"
        )

    def _tabla_maestria(self, conteo: dict[str, dict]) -> str:
        p = PALETA
        filas = []
        total = {"total": 0, DOMINADO: 0, A_MEDIAS: 0, SIN_TOCAR: 0}
        for categoria, c in sorted(conteo.items(), key=lambda par: categoria_es(par[0])):
            for clave in total:
                total[clave] += c[clave]
            filas.append(_fila_maestria(categoria_es(categoria), c, p["texto"]))
        filas.append(_fila_maestria(t("Total"), total, p["acento"], negrita=True))
        cabecera = (
            f"<tr style='color:{p['suave']}'><td></td>"
            f"<td align='right'>{html.escape(t('Dominados'))}</td>"
            f"<td align='right'>{html.escape(t('A medias'))}</td>"
            f"<td align='right'>{html.escape(t('Sin tocar'))}</td>"
            f"<td align='right'>{html.escape(t('Total'))}</td></tr>"
        )
        return _seccion(t("Maestria por categoria")) + _envolver([cabecera] + filas)

    def _bloque_nodos_resumen(self, total: int, pendientes: int, acero: bool) -> str:
        hechos = max(0, total - pendientes)
        valores = {"hechos": hechos, "total": total, "pendientes": pendientes}
        texto = (
            t("Nodos del Camino de Acero: {hechos} de {total} completados ({pendientes} pendientes)", **valores)
            if acero
            else t("Nodos del mapa: {hechos} de {total} completados ({pendientes} pendientes)", **valores)
        )
        return _seccion(t("Mapa estelar")) + f"<div>{html.escape(texto)}</div>"

    def _bloque_intrinsecos(self, valores: dict[str, int]) -> str:
        if not any(clave in valores for clave in INTRINSECOS):
            return ""
        p = PALETA
        grupos = (
            (t("Railjack"), [k for k in INTRINSECOS if k in _INTRINSECOS_RAILJACK]),
            (t("Errante"), [k for k in INTRINSECOS if k not in _INTRINSECOS_RAILJACK]),
        )
        lineas = []
        for titulo, claves in grupos:
            trozos = [
                f"{html.escape(t(INTRINSECOS[k]))} <b>{int(valores.get(k, 0))}</b>"
                for k in claves if k in valores
            ]
            if trozos:
                lineas.append(
                    f"<div><span style='color:{p['suave']}'>{html.escape(titulo)}:</span> "
                    + " &middot; ".join(trozos) + "</div>"
                )
        return _seccion(t("Intrinsecos")) + "".join(lineas)

    def _bloque_sindicatos(self, sindicatos: list[dict]) -> str:
        if not sindicatos:
            return ""
        p = PALETA
        filas = []
        for s in sindicatos:
            nombre = t(SINDICATOS.get(s["tag"], s["tag"].removesuffix("Syndicate")))
            titulo = s["titulo"]
            if titulo < 0:
                rango = f"<span style='color:{p['aviso']}'>{html.escape(t('en contra ({n})', n=titulo))}</span>"
            else:
                rango = html.escape(t("rango {n}", n=titulo))
            filas.append(
                f"<tr><td>{html.escape(nombre)}</td><td>{rango}</td>"
                f"<td align='right' style='color:{p['suave']}'>{_miles(s['standing'])}</td></tr>"
            )
        return _seccion(t("Sindicatos")) + _envolver(filas)

    def _bloque_pendientes(self, grupos: dict[str, list[dict]]) -> str:
        p = PALETA
        if not grupos:
            return _seccion(t("Por dominar")) + f"<div style='color:{COLOR_DISPONIBLE}'>" + html.escape(
                t("Lo tienes todo dominado. Enhorabuena, Tenno.")) + "</div>"
        partes = [_seccion(t("Por dominar"))]
        for categoria, filas in sorted(grupos.items(), key=lambda par: categoria_es(par[0])):
            empezados = sum(1 for f in filas if f["estado"] == A_MEDIAS)
            resumen = t("{n} pendientes", n=len(filas))
            if empezados:
                resumen += " · " + t("{n} a medias", n=empezados)
            enlaces = []
            for f in filas:
                enlace = (
                    f"<a style='color:{p['texto']};text-decoration:none' href='item:{f['item_id']}'>"
                    f"{html.escape(nombre_idioma(f))}</a>"
                )
                if f["estado"] == A_MEDIAS:
                    pct = min(100, int(100 * f["xp"] / f["umbral"])) if f["umbral"] else 0
                    enlace += f" <span style='color:{p['aviso']}'>{pct} %</span>"
                enlaces.append(enlace)
            partes.append(
                f"<div style='margin-top:8px'><b>{html.escape(categoria_es(categoria))}</b> "
                f"<span style='color:{p['suave']}'>&middot; {html.escape(resumen)}</span></div>"
                f"<div style='margin-left:12px'>{' &nbsp;·&nbsp; '.join(enlaces)}</div>"
            )
        return "".join(partes)

    def _bloque_nodos(self, pendientes: list[dict], acero: bool) -> str:
        p = PALETA
        titulo = t("Nodos pendientes del Camino de Acero") if acero else t("Nodos pendientes")
        if not pendientes:
            return _seccion(titulo) + f"<div style='color:{COLOR_DISPONIBLE}'>" + html.escape(
                t("Mapa completo: no te falta ningun nodo.")) + "</div>"
        nombres = self._nombres_nodos()
        # El indice trae el mismo planeta con y sin tilde segun el nodo ("Pluton" y
        # "Pluton" con acento): se agrupa sin acentos y se ensena el primer nombre visto.
        por_planeta: dict[str, list[str]] = {}
        etiquetas: dict[str, str] = {}
        for n in pendientes:
            fila = nombres.get(n["unique_name"], {})
            planeta = nombre_idioma(fila, "planeta") or n["planeta"] or "?"
            nombre = nombre_idioma(fila) or n["nombre"] or n["unique_name"]
            mision = glosa(n["mision"], fila.get("mision_en")) if n["mision"] else ""
            texto = html.escape(nombre)
            if mision:
                texto += f" <span style='color:{p['suave']}'>({html.escape(mision)})</span>"
            clave = _sin_acentos(planeta)
            etiquetas.setdefault(clave, planeta)
            por_planeta.setdefault(clave, []).append(texto)
        partes = [_seccion(titulo)]
        for clave in sorted(por_planeta):
            partes.append(
                f"<div style='margin-top:4px'><b>{html.escape(etiquetas[clave])}</b> "
                f"<span style='color:{p['suave']}'>({len(por_planeta[clave])})</span>: "
                + ", ".join(por_planeta[clave]) + "</div>"
            )
        return "".join(partes)

    # -- consultas auxiliares al indice --------------------------------------------

    def _total_nodos(self) -> int:
        condicion = " OR ".join("unique_name LIKE ?" for _ in _PREFIJOS_NODO)
        return self.indice.execute(
            f"SELECT COUNT(*) FROM nodos WHERE {condicion}", tuple(f"{p}%" for p in _PREFIJOS_NODO)
        ).fetchone()[0]

    def _nombres_nodos(self) -> dict[str, dict]:
        """Nombres de nodo y planeta en los dos idiomas del indice, para elegir segun la interfaz."""
        return {
            fila[0]: {
                "nombre_en": fila[1], "nombre_es": fila[2],
                "planeta_en": fila[3], "planeta_es": fila[4], "mision_en": fila[5],
            }
            for fila in self.indice.execute(
                "SELECT unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_en "
                "FROM nodos WHERE unique_name IS NOT NULL"
            )
        }


# -- trozos de HTML ------------------------------------------------------------------


def _seccion(titulo: str) -> str:
    return (
        f"<div style='color:{PALETA['acento']};font-size:12px;font-weight:bold;"
        f"margin-top:16px;margin-bottom:4px'>{html.escape(titulo).upper()}</div>"
    )


def _parrafo_suave(texto: str) -> str:
    return f"<p style='color:{PALETA['suave']}'>{html.escape(texto)}</p>"


def _envolver(filas: list[str]) -> str:
    return (
        f"<table width='100%' cellspacing='0' cellpadding='4' style='background:{PALETA['panel2']}'>"
        + "".join(filas) + "</table>"
    )


def _fila_maestria(etiqueta: str, c: dict, color: str, negrita: bool = False) -> str:
    peso = "font-weight:bold;" if negrita else ""
    return (
        f"<tr style='color:{color};{peso}'><td>{html.escape(etiqueta)}</td>"
        f"<td align='right' style='color:{COLOR_DISPONIBLE}'>{c[DOMINADO]}</td>"
        f"<td align='right' style='color:{PALETA['aviso']}'>{c[A_MEDIAS]}</td>"
        f"<td align='right'>{c[SIN_TOCAR]}</td>"
        f"<td align='right'>{c['total']}</td></tr>"
    )


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _fecha_local(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        momento = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if momento.tzinfo is not None:
        momento = momento.astimezone()
    else:
        momento = momento.replace(tzinfo=timezone.utc).astimezone()
    return momento.strftime("%d/%m/%Y %H:%M")
