"""Vista compacta para el directo: una caja de busqueda y lo esencial del resultado.

Pensada para consultar en cinco segundos sin tapar la partida ni ensenarle al
espectador una ventana entera: nombre, donde cae lo mejor, precio si lo hay y
si esta en boveda. Nada de tablas. Arriba y abajo se cambia de resultado y con
Enter se abre la ficha completa.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..datos import indice, items, relaciones
from ..idiomas import es_castellano, glosa, nombre as nombre_idioma, t
from . import glosario
from .pestana_buscador import PestanaBuscador, _con_padre, _etiqueta, categoria_es, era_de
from .widgets import COLOR_BOVEDA, COLOR_DISPONIBLE, PALETA, color_rareza

# Tamano por defecto: en 2560x1440 ocupa un 4 % de la pantalla (la completa, un 21 %).
ANCHO = 560
ALTO = 250


class VistaCompacta(QWidget):
    pedir_precios = Signal(str)
    # El usuario quiere ver la ficha entera de este objeto: la ventana cambia a completo.
    abrir_completo = Signal(int)

    def __init__(self, buscador: PestanaBuscador, parent=None):
        super().__init__(parent)
        # El indice y el perfil se comparten con la pestana Buscar (misma conexion).
        self.buscador = buscador
        self._resultados: list[dict] = []
        self._indice_actual = -1
        self._datos: dict | None = None
        self._slug_actual = ""
        self._precio_html = ""
        self._sin_resultados: str | None = None
        p = PALETA

        self.caja = QLineEdit()
        self.caja.setClearButtonEnabled(True)
        self.caja.setMinimumHeight(36)
        self.caja.installEventFilter(self)

        self.resumen = QLabel()
        self.resumen.setTextFormat(Qt.RichText)
        self.resumen.setWordWrap(True)
        self.resumen.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.resumen.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.resumen.linkActivated.connect(self._enlace)
        glosario.conectar_etiqueta(self.resumen)

        self.pie = QLabel()
        self.pie.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        self.posicion = QLabel()
        self.posicion.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        pie = QHBoxLayout()
        pie.addWidget(self.pie, 1)
        pie.addWidget(self.posicion, 0, Qt.AlignRight)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 4, 4, 2)
        caja.setSpacing(6)
        caja.addWidget(self.caja)
        caja.addWidget(self.resumen, 1)
        caja.addLayout(pie)

        self.caja.textChanged.connect(self._buscar)
        self.retraducir()

    # -- idioma y tema --------------------------------------------------------

    def retraducir(self) -> None:
        self.caja.setPlaceholderText(t("Busca algo (Enter: ficha completa)"))
        self.pie.setText(t("↑↓ otro resultado · Enter ficha completa · Ctrl+M vista completa"))
        self.repintar()

    def repintar(self) -> None:
        p = PALETA
        self.pie.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        self.posicion.setStyleSheet(f"color: {p['suave']}; font-size: 12px;")
        if self._datos:
            self.resumen.setText(self._html(self._datos))
        elif self._sin_resultados is not None:
            self.resumen.setText(self._html_sin_resultados(self._sin_resultados))
        else:
            self.resumen.setText(
                f"<span style='color:{p['suave']}'>"
                + html.escape(t("Escribe el nombre de un objeto, una pieza, un mod o una reliquia."))
                + "</span>"
            )

    # -- teclas ----------------------------------------------------------------

    def eventFilter(self, objeto, evento):  # noqa: N802 - firma de Qt
        if objeto is self.caja and evento.type() == QEvent.KeyPress:
            tecla = evento.key()
            if tecla == Qt.Key_Down:
                self._mover(1)
                return True
            if tecla == Qt.Key_Up:
                self._mover(-1)
                return True
            if tecla in (Qt.Key_Return, Qt.Key_Enter) and self._datos:
                self.abrir_completo.emit(self._datos["item"]["id"])
                return True
        return super().eventFilter(objeto, evento)

    def _mover(self, paso: int) -> None:
        if not self._resultados:
            return
        self._mostrar(max(0, min(len(self._resultados) - 1, self._indice_actual + paso)))

    # -- busqueda ----------------------------------------------------------------

    @property
    def con(self):
        return self.buscador.con

    def _buscar(self, texto: str) -> None:
        texto = texto.strip()
        self._resultados = []
        self._indice_actual = -1
        self._datos = None
        self._sin_resultados = None
        self._slug_actual = ""
        self.posicion.setText("")
        if not self.con or len(texto) < 2:
            self.repintar()
            return
        self._resultados = indice.buscar(self.con, texto)
        if self._resultados:
            self._mostrar(0)
        else:
            self._sin_resultados = texto
            self.repintar()

    def _mostrar(self, posicion: int) -> None:
        self._indice_actual = posicion
        self.posicion.setText(f"{posicion + 1}/{len(self._resultados)}")
        self.abrir(self._resultados[posicion]["item_id"])

    def abrir(self, item_id: int) -> None:
        """Ensena un objeto concreto (desde la lista o desde el lector del cursor)."""
        if not self.con:
            return
        datos = items.ficha(self.con, item_id)
        if not datos:
            return
        self._datos = datos
        self._sin_resultados = None
        self._precio_html = ""
        slug = datos["item"].get("market_slug") or ""
        self._slug_actual = slug
        if slug:
            self._precio_html = (
                f"<span style='color:{PALETA['suave']}'>{html.escape(t('Mercado: consultando...'))}</span>"
            )
            self.pedir_precios.emit(slug)
        self.repintar()

    def mostrar_precios(self, slug: str, precios) -> None:
        if slug != self._slug_actual:
            return
        p = PALETA
        if getattr(precios, "error", None):
            texto = f"<span style='color:{p['suave']}'>{html.escape(t('Mercado: no disponible'))}</span>"
        elif precios.mejor_venta is None and precios.mejor_compra is None:
            texto = f"<span style='color:{p['suave']}'>{html.escape(t('Mercado: nadie lo vende ahora mismo'))}</span>"
        else:
            partes = []
            if precios.mejor_venta is not None:
                partes.append(t("se vende desde <b>{n}p</b>", n=precios.mejor_venta))
            if precios.mejor_compra is not None:
                partes.append(t("te lo compran por <b>{n}p</b>", n=precios.mejor_compra))
            texto = html.escape(t("Mercado:")) + " " + " &middot; ".join(partes)
        self._precio_html = texto
        self.repintar()

    def _enlace(self, url: str) -> None:
        if glosario.mostrar(url, self.resumen):
            return
        if url.startswith("item:"):
            self.abrir(int(url.removeprefix("item:")))
        elif url.startswith("buscar:"):
            self.caja.setText(url.removeprefix("buscar:"))

    # -- pintado ------------------------------------------------------------------

    def _html(self, datos: dict) -> str:
        p = PALETA
        item, padre = datos["item"], datos["padre"]
        nombre = html.escape(nombre_idioma(item))
        if padre:
            nombre = _con_padre(nombre, html.escape(nombre_idioma(padre)))
        otro = item["nombre_en"] if es_castellano() else (item["nombre_es"] or "")
        es_reliquia = item["categoria"] == "Relics"

        etiquetas = []
        clave_categoria = "reliquia" if es_reliquia else ("pieza" if item["tipo"] == "Componente" else None)
        etiquetas.append(_etiqueta(categoria_es(item["categoria"], item["tipo"]), p["panel"], p["suave"], clave_categoria))
        era = era_de(item["nombre_en"]) if es_reliquia else ""
        if era:
            etiquetas.append(_etiqueta(t(era), p["panel"], p["acento"], "era"))
        if item["es_prime"]:
            etiquetas.append(_etiqueta("Prime", p["panel"], color_rareza("Rare"), "prime"))
        if item["vaulted"]:
            etiquetas.append(_etiqueta(t("En boveda"), "#3a2a12", COLOR_BOVEDA, "boveda"))
        elif item["vaulted"] == 0 and es_reliquia:
            etiquetas.append(_etiqueta(t("Disponible"), "#15301a", COLOR_DISPONIBLE, "boveda"))
        if item["ducados"]:
            etiquetas.append(_etiqueta(t("{n} ducados", n=item["ducados"]), p["panel"], p["suave"], "ducados"))
        maestria = self.buscador._etiqueta_maestria(item["id"])
        if maestria:
            etiquetas.append(maestria)

        lineas = [
            f"<div><span style='font-size:17px;font-weight:bold'>{nombre}</span>"
            + (f" <span style='color:{p['suave']};font-size:12px'>{html.escape(otro)}</span>" if otro and otro != nombre_idioma(item) else "")
            + "</div>",
            f"<div style='margin-top:3px'>{' '.join(etiquetas)}</div>",
            f"<div style='margin-top:6px'>{self._donde(datos)}</div>",
        ]
        if self._precio_html:
            lineas.append(f"<div style='margin-top:4px'>{self._precio_html}</div>")
        return "".join(lineas)

    def _donde(self, datos: dict) -> str:
        """Una sola linea: la mejor forma de conseguirlo hoy."""
        p = PALETA
        con = self.con
        item = datos["item"]
        if item["categoria"] == "Relics":
            return self._donde_reliquia(item["id"])
        ruta = relaciones.mejor_ruta(con, item["id"])
        if ruta and (ruta.get("tipo") != "reliquia" or not ruta["reliquia"]):
            # Sin reliquia de por medio: el mejor sitio y de que tipo es.
            if not ruta["mision"]:
                ruta = None
            else:
                tipo = glosa(indice.traducir(con, "tipo_fuente", ruta.get("tipo")), ruta.get("tipo"))
                return self._mision(ruta["mision"]) + (
                    f" <span style='color:{p['suave']}'>({html.escape(tipo)})</span>" if tipo else ""
                )
        if ruta:
            reliquia = ruta["reliquia"]
            prob = reliquia["probabilidades"].get("Radiant") or max(list(reliquia["probabilidades"].values()) or [0])
            # El nombre ya dice "Reliquia Neo N5"; no se repite la palabra delante.
            texto = (
                f"<a style='color:{p['acento']};text-decoration:none' href='item:{reliquia['reliquia_id']}'>"
                f"<b>{html.escape(nombre_idioma(reliquia))}</b></a> "
                + glosario.enlace("refinamiento", t("({prob}% en Radiante)", prob=f"{prob:.1f}"), p["suave"])
            )
            if ruta["solo_en_boveda"]:
                return texto + "<br>" + glosario.enlace(
                    "boveda", t("Solo en boveda: hay que comprarla a otro jugador"), COLOR_BOVEDA
                )
            if ruta["mision"]:
                return texto + "<br>" + self._mision(ruta["mision"])
            return texto
        fuentes = [f for f in datos["fuentes"] if f["tipo"] != "reliquia"]
        if fuentes:
            f = max(fuentes, key=lambda x: x["probabilidad"] or 0)
            if f["nodo_en"]:
                donde = f"{nombre_idioma(f, 'nodo')}, {nombre_idioma(f, 'planeta')}".strip(", ")
                mision = glosa(indice.traducir(con, "mision", f["mision_en"]), f["mision_en"])
                if mision:
                    donde += f" - {mision}"
            else:
                from ..datos.nodos import nombre_bonito

                donde = nombre_bonito(con, f["origen_texto"])
            extra = []
            if f["rotacion"]:
                extra.append(glosario.enlace("rotacion", glosa(indice.traducir(con, "rotacion", f["rotacion"]), f["rotacion"]), p["suave"]))
            if f["rareza"]:
                extra.append(glosario.enlace("rareza", glosa(indice.traducir(con, "rareza", f["rareza"]), f["rareza"]), color_rareza(f["rareza"])))
            if f["probabilidad"] is not None:
                extra.append(f"<b>{f['probabilidad']:.1f}%</b>")
            return f"<b>{html.escape(donde)}</b>" + (" &middot; " + " &middot; ".join(extra) if extra else "")
        if datos["componentes"]:
            piezas = ", ".join(
                f"<a style='color:{p['acento']};text-decoration:none' href='item:{c['id']}'>{html.escape(nombre_idioma(c))}</a>"
                for c in datos["componentes"]
            )
            return f"{glosario.enlace('pieza', t('Se construye con'), p['suave'])}: {piezas}"
        return (
            f"<span style='color:{p['suave']}'>"
            + html.escape(t("Sin fuentes registradas: puede venir de una mision de historia, del mercado, "
                            "de un evento o de un sindicato."))
            + "</span>"
        )

    def _donde_reliquia(self, reliquia_id: int) -> str:
        p = PALETA
        misiones = relaciones.misiones_de(self.con, reliquia_id)
        partes = []
        if misiones:
            partes.append(html.escape(t("Cae en")) + " " + self._mision(misiones[0]))
        else:
            partes.append(f"<span style='color:{p['suave']}'>{html.escape(t('No cae en ninguna mision activa'))}</span>")
        # La pieza rara es la menos probable; la columna de rareza no es fiable en las tablas.
        contenido = relaciones.contenido_de(self.con, reliquia_id, "Radiant")
        if contenido:
            c = min(contenido, key=lambda x: x["probabilidad"] or 100)
            partes.append(
                glosario.enlace("rareza", t("Rara"), color_rareza("Rare")) + ": "
                f"<a style='color:{p['texto']};text-decoration:none' href='item:{c['item_id']}'>"
                f"<b>{html.escape(_con_padre(nombre_idioma(c), nombre_idioma(c, 'padre')))}</b></a>"
                f" <span style='color:{p['suave']}'>{c['probabilidad']:.1f}%</span>"
            )
        return "<br>".join(partes)

    def _mision(self, m: dict) -> str:
        p = PALETA
        trozos = [f"<b>{html.escape(m.get('donde') or '')}</b>"]
        if m.get("mision"):
            trozos.append(html.escape(m["mision"]))
        if m.get("rotacion"):
            trozos.append(glosario.enlace(
                "rotacion", glosa(indice.traducir(self.con, "rotacion", m["rotacion"]), m["rotacion"]), p["suave"]
            ))
        prob = m.get("probabilidad_efectiva") or m.get("probabilidad")
        if prob:
            trozos.append(f"{prob:.1f}%")
        return " &middot; ".join(trozos)

    def _html_sin_resultados(self, texto: str) -> str:
        p = PALETA
        salida = [
            f"<div style='font-size:15px;font-weight:bold'>"
            f"{html.escape(t('No he encontrado nada para «{busqueda}»', busqueda=texto))}</div>"
        ]
        parecidos = self.buscador.sugerencias(texto)
        if parecidos:
            enlaces = " &middot; ".join(
                f"<a style='color:{p['acento']};text-decoration:none' href='item:{r['item_id']}'>"
                f"{html.escape(_con_padre(nombre_idioma(r), nombre_idioma(r, 'padre')))}</a>"
                for r in parecidos
            )
            salida.append(f"<div style='margin-top:4px;color:{p['suave']}'>{html.escape(t('Quiza buscabas:'))} {enlaces}</div>")
        return "".join(salida)

