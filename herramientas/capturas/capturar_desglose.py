"""Renderiza sin pantalla el desglose de los tiempos (tooltip abierto) y el ritmo de juego.

Uso: .venv/Scripts/python.exe herramientas/capturas/capturar_desglose.py

Guarda en esta carpeta:
- ficha_sensores_neuronales_desglose.png: ficha de Sensores neuronales con el tooltip
  del tiempo de Formido (rotacion C) abierto;
- primes_resultado_desglose.png: pestana Primes con "Caliban Prime Plano" marcado y el
  tooltip del primer "Hasta la pieza" abierto;
- ajustes_ritmo_es.png: Ajustes con el desplegable "Ritmo de juego".

El tooltip de Qt es una ventana aparte que `grab()` no recoge: se pinta encima de la
captura de la ventana, junto al enlace. Trabaja sobre la copia del indice de
herramientas/render_ui.py; la configuracion y los objetivos van a esa carpeta temporal.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import unquote

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "herramientas"))
from render_ui import preparar_sandbox  # noqa: E402

os.environ["FARMADEX_DATOS"] = str(preparar_sandbox())
sys.path.insert(0, str(RAIZ / "src"))

from farmadex import config as _config  # noqa: E402

assert str(_config.DIR_BASE).startswith(os.environ["FARMADEX_DATOS"]), _config.DIR_BASE

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QPainter, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolTip  # noqa: E402

from farmadex import tareas  # noqa: E402
from farmadex.datos import indice  # noqa: E402
from farmadex.ui import glosario  # noqa: E402
from farmadex.ui.overlay import VentanaOverlay  # noqa: E402

DESTINO = Path(__file__).resolve().parent


def _enlaces(vista, clave: str):
    """(posicion, href) de cada enlace `glosa:<clave>?...` del documento."""
    bloque = vista.document().begin()
    while bloque.isValid():
        it = bloque.begin()
        while not it.atEnd():
            fragmento = it.fragment()
            href = fragmento.charFormat().anchorHref()
            if href.startswith(f"{glosario.PREFIJO}{clave}?"):
                yield fragmento.position(), href
            it += 1
        bloque = bloque.next()


def _con_tooltip(app, ventana, vista, clave: str, contiene: str, ruta: Path) -> None:
    posicion, href = next(
        (p, h) for p, h in _enlaces(vista, clave) if contiene in unquote(h)
    )
    cursor = QTextCursor(vista.document())
    cursor.setPosition(posicion)
    vista.setTextCursor(cursor)
    vista.ensureCursorVisible()
    app.processEvents()
    # El enlace hacia el tercio de arriba: que se vea la tabla entera bajo el tooltip.
    barra = vista.verticalScrollBar()
    barra.setValue(barra.value() + vista.cursorRect(cursor).top() - vista.viewport().height() // 4)
    app.processEvents()
    rect = vista.cursorRect(cursor)
    ancla = vista.viewport().mapTo(ventana, rect.bottomLeft())
    QToolTip.showText(vista.viewport().mapToGlobal(rect.bottomLeft()), glosario.texto(href.removeprefix(glosario.PREFIJO)), vista)
    app.processEvents()
    etiqueta = next(w for w in app.topLevelWidgets() if w.metaObject().className() == "QTipLabel" and w.isVisible())
    imagen = ventana.grab()
    punta = etiqueta.grab()
    x = min(max(0, ancla.x() - punta.width() // 2), imagen.width() - punta.width())
    y = ancla.y() + 14
    if y + punta.height() > imagen.height():
        y = ancla.y() - rect.height() - punta.height() - 6
    pintor = QPainter(imagen)
    pintor.drawPixmap(QPoint(x, y), punta)
    pintor.end()
    imagen.save(str(ruta))
    QToolTip.hideText()
    print(ruta, "|", unquote(href.split("?", 1)[1]).replace("\n", " / "))


def main() -> None:
    tareas.TareaDatos.start = lambda self: None
    app = QApplication.instance() or QApplication([])
    ventana = VentanaOverlay()
    ventana.aplicar_modo("completo")
    ventana.resize(1180, 900)
    ventana.show()
    ventana.buscador.habilitar(True)

    ventana.pestanas.setCurrentWidget(ventana.buscador)
    ventana.buscador.caja.setText("sensores neuronales")
    ventana.buscador._buscar()
    app.processEvents()
    ventana.buscador.abrir(ventana.buscador._resultados[0]["item_id"])
    app.processEvents()
    _con_tooltip(app, ventana, ventana.buscador.ficha, "tiempo_medio", "rotacion C",
                 DESTINO / "ficha_sensores_neuronales_desglose.png")

    primes = ventana.primes
    primes.conectar_indice(indice.conectar())
    ventana.pestanas.setCurrentWidget(primes)
    caja = next(c for c in primes._cajas if c.objeto and c.objeto["nombre_en"] == "Caliban Prime")
    casilla = next(v for k, v in caja.casillas.items() if k.endswith("Blueprint"))
    casilla.setChecked(True)
    primes._elegir_vista("resultado")
    ventana.resize(1180, 820)
    for _ in range(3):
        app.processEvents()
    primes._pintar_resultado()
    app.processEvents()
    _con_tooltip(app, ventana, primes.resultado, "tiempo_pieza", "fisura",
                 DESTINO / "primes_resultado_desglose.png")
    casilla.setChecked(False)  # la BD de usuario es la de la caja de arena, pero se deja como estaba

    ventana.pestanas.setCurrentWidget(ventana.ajustes)
    ventana.resize(1180, 820)
    app.processEvents()
    ruta = DESTINO / "ajustes_ritmo_es.png"
    ventana.grab().save(str(ruta))
    print(ruta)
    app.quit()


if __name__ == "__main__":
    main()
