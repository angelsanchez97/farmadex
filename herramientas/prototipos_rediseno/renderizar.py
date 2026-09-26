"""Renderiza sin pantalla las tres propuestas y guarda los PNG en el scratchpad.

Uso: .venv/Scripts/python herramientas/prototipos_rediseno/renderizar.py [A] [B] [C]

Salida: <scratchpad>/rediseno/propuesta_{A,B,C}_{inicio,ficha,compacto}.png. El compacto se
pinta encima de un fondo que imita una partida, con un margen, para juzgar el contraste.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import comun  # noqa: E402  (prepara el entorno antes de Qt)

from PySide6.QtWidgets import QApplication  # noqa: E402

DESTINO = comun.SCRATCH / "rediseno"


def _foto(widget, ruta: Path) -> None:
    widget.show()
    QApplication.processEvents()
    widget.adjustSize() if widget.width() < 50 else None
    QApplication.processEvents()
    widget.grab().save(str(ruta))
    print(ruta, widget.width(), "x", widget.height())
    widget.close()


def main(letras: list[str]) -> None:
    app = QApplication.instance() or QApplication([])
    d = comun.cargar()
    DESTINO.mkdir(parents=True, exist_ok=True)
    for letra in letras or ["A", "B", "C"]:
        mod = importlib.import_module(f"propuesta_{letra.lower()}")
        _foto(mod.inicio(d), DESTINO / f"propuesta_{letra}_inicio.png")
        _foto(mod.ficha(d), DESTINO / f"propuesta_{letra}_ficha.png")
        tarjeta = mod.compacto(d)
        tarjeta.show()
        QApplication.processEvents()
        w, h = tarjeta.width(), tarjeta.height()
        escena = comun.FondoPartida()
        escena.resize(w + 60, h + 60)
        tarjeta.setParent(escena)
        tarjeta.move(30, 30)
        tarjeta.show()
        _foto(escena, DESTINO / f"propuesta_{letra}_compacto.png")
    app.quit()


if __name__ == "__main__":
    main(sys.argv[1:])
