"""Capturas de la guia de uso, en el tamano minimo de la ventana y en uno grande.

No depende de datos reales ni de %LocalAppData%\\Farmadex: usa una carpeta temporal
propia (FARMADEX_DATOS) y desactiva la carga real de datos (TareaDatos.start), igual
que capturar_compacto.py. Sirve para comprobar que la burbuja de la guia no se sale
de la ventana ni tapa lo que resalta.

Uso: .venv/Scripts/python.exe herramientas/capturas/capturar_guia.py
Salidas en esta carpeta: guia_paso<N>_<tamano>.png (pasos 2, 5, 6 y 8; "minimo" es
760x420 y "grande" 1400x900).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
os.environ["FARMADEX_DATOS"] = str(Path(tempfile.gettempdir()) / "farmadex_capturas_guia")

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import tareas  # noqa: E402
from farmadex.datos import indice  # noqa: E402
from farmadex.ui.overlay import VentanaOverlay  # noqa: E402

DESTINO = Path(__file__).resolve().parent
TAMANOS = {"minimo": (760, 420), "grande": (1400, 900)}
# Pasos representativos: bienvenida centrada, uno con objetivo en pestana, uno en
# Ajustes (mas relleno alrededor) y el de modo compacto (objetivo en la cabecera).
PASOS_A_CAPTURAR = (0, 1, 5, 7)


def main() -> None:
    tareas.TareaDatos.start = lambda self: None
    indice.hay_indice = lambda ruta=None: False
    app = QApplication.instance() or QApplication([])
    ventana = VentanaOverlay()
    ventana.buscador.habilitar(True)

    for nombre_tamano, (ancho, alto) in TAMANOS.items():
        ventana.setMinimumSize(1, 1)  # por si el tamano pedido es el minimo de completo
        ventana.resize(ancho, alto)
        ventana.show()
        ventana.mostrar_guia()
        guia = ventana._guia
        for paso in PASOS_A_CAPTURAR:
            guia._ir_a_paso(paso)
            app.processEvents()
            ruta = DESTINO / f"guia_paso{paso + 1}_{nombre_tamano}.png"
            ventana.grab().save(str(ruta))
            print(ruta)
        guia.saltar()
        app.processEvents()

    app.quit()


if __name__ == "__main__":
    main()
