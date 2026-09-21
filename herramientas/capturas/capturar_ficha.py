"""Renderiza sin pantalla la ficha de uno o varios objetos y guarda un PNG por cada uno.

Uso: QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe herramientas/capturas/capturar_ficha.py SUFIJO "busqueda 1" "busqueda 2" ...

Cada busqueda abre el primer resultado y guarda ficha_<busqueda>_<SUFIJO>.png. Sirve para
comparar la ficha antes y despues de un cambio (SUFIJO = antes / despues). Trabaja sobre
una copia del indice real en la caja de arena de herramientas/render_ui.py.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "herramientas"))
from render_ui import preparar_sandbox  # noqa: E402

os.environ["FARMADEX_DATOS"] = str(preparar_sandbox())
sys.path.insert(0, str(RAIZ / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import tareas  # noqa: E402
from farmadex.ui.overlay import VentanaOverlay  # noqa: E402

DESTINO = Path(__file__).resolve().parent


def main(sufijo: str, busquedas: list[str]) -> None:
    tareas.TareaDatos.start = lambda self: None
    app = QApplication.instance() or QApplication([])
    ventana = VentanaOverlay()
    ventana.aplicar_modo("completo")
    ventana.resize(1180, 900)
    ventana.show()
    ventana.buscador.habilitar(True)
    ventana.pestanas.setCurrentWidget(ventana.buscador)
    for busqueda in busquedas:
        ventana.buscador.caja.setText(busqueda)
        ventana.buscador._buscar()
        app.processEvents()
        if not ventana.buscador._resultados:
            print(f"sin resultados para {busqueda!r}")
            continue
        ventana.buscador.abrir(ventana.buscador._resultados[0]["item_id"])
        app.processEvents()
        nombre = re.sub(r"[^a-z0-9]+", "_", busqueda.lower()).strip("_")
        ruta = DESTINO / f"ficha_{nombre}_{sufijo}.png"
        ventana.grab().save(str(ruta))
        print(ruta)
    app.quit()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
