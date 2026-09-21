"""Renderiza el banner de avisos (version nueva, parche, pantalla exclusiva) en las dos vistas.

Uso: QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe herramientas/capturas/capturar_avisos.py [es en fr de pt]

Misma caja de arena que capturar_idiomas.py (copia del indice real, sin hilos ni red).
Salidas en esta carpeta: avisos_<vista>_<idioma>.png.
"""

from __future__ import annotations

import os
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


class VersionDePrueba:
    etiqueta = "9.9.9"
    url = "https://example.invalid/farmadex"
    ruta = None


def main(codigos: list[str]) -> None:
    tareas.TareaDatos.start = lambda self: None
    app = QApplication.instance() or QApplication([])
    ventana = VentanaOverlay()
    ventana.buscador.habilitar(True)
    ventana.cambiar_tema("orokin")  # el tema por defecto, que es el que ve casi todo el mundo
    ventana.show()
    for codigo in codigos:
        ventana.cambiar_idioma(codigo)
        ventana._hay_version_nueva(VersionDePrueba())
        for vista, tamano in (("completo", (760, 420)), ("compacto", (420, 190))):
            ventana.aplicar_modo(vista)
            ventana.resize(*tamano)
            caja = ventana.compacta.caja if vista == "compacto" else ventana.buscador.caja
            caja.setText("ash prime systems")
            if vista == "completo":
                ventana.buscador._temporizador.stop()
                ventana.buscador._buscar()
            else:
                ventana.compacta._temporizador.stop()
                ventana.compacta._buscar("ash prime systems")
            app.processEvents()
            ruta = DESTINO / f"avisos_{vista}_{codigo}.png"
            ventana.grab().save(str(ruta))
            print(ruta)
    app.quit()


if __name__ == "__main__":
    main(sys.argv[1:] or ["es", "en", "fr", "de", "pt"])
