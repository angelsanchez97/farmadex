"""Capturas del dialogo Acerca de y del panel de recompensas de reliquia (para el README).

No toca %LocalAppData%\\Farmadex: usa una carpeta temporal propia (FARMADEX_DATOS).
El panel se pinta sobre un fondo que imita la fila de tarjetas del juego, con datos
de ejemplo (no hace falta el juego ni el OCR).

Uso: .venv/Scripts/python.exe herramientas/capturas/capturar_acerca_panel.py
Salidas en esta carpeta: acerca_de_es.png, panel_recompensas_es.png.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
os.environ["FARMADEX_DATOS"] = str(Path(tempfile.gettempdir()) / "farmadex_capturas_readme")

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex.captura.comparador import Veredicto  # noqa: E402
from farmadex.captura.reliquias import Recompensa  # noqa: E402
from farmadex.ui.acerca_de import DialogoAcercaDe  # noqa: E402
from farmadex.ui.panel_recompensas import PanelRecompensas  # noqa: E402

DESTINO = Path(__file__).resolve().parent
ANCHO, ALTO = 1920, 1080
# Cuatro tarjetas del juego, como en una fisura con escuadra de cuatro.
CAJAS = [(560, 470, 190, 40), (770, 470, 190, 40), (980, 470, 190, 40), (1190, 470, 190, 40)]


def capturar_acerca() -> None:
    dialogo = DialogoAcercaDe()
    dialogo.resize(660, 900)
    dialogo.show()
    QApplication.processEvents()
    ruta = DESTINO / "acerca_de_es.png"
    dialogo.grab().save(str(ruta))
    dialogo.close()
    print(ruta)


def _recompensas() -> list[Recompensa]:
    r = [
        Recompensa(1, "Plano de Caliban Prime", "PlanoDeCalibanPrime", CAJAS[0], ducados=100),
        Recompensa(2, "Cañón de Braton Prime", "CanonDeBratonPrime", CAJAS[1], ducados=15),
        Recompensa(3, "Forma (Plano)", "FormaPlano", CAJAS[2], ducados=None),
        Recompensa(4, "Sistemas de Ash Prime", "SistemasDeAshPrime", CAJAS[3], ducados=45),
    ]
    r[0].platino, r[0].criterio_platino, r[0].mejor = 38, "minimo", True
    r[0].objetivo = "1/1"
    r[1].platino, r[1].criterio_platino = 3, "minimo"
    r[2].platino, r[2].criterio_platino, r[2].comerciable = None, "", False
    r[3].platino, r[3].criterio_platino, r[3].vaulted = 9, "minimo", True
    return r


def capturar_panel() -> None:
    panel = PanelRecompensas()
    panel.resize(ANCHO, ALTO)
    recompensas = _recompensas()
    panel.mostrar(
        recompensas,
        {1: ("Sin dominar", "sin_tocar"), 2: ("Dominado", "dominado"), 4: ("A medias", "a_medias")},
        {1: {"minutos": "~48 min", "tienes": 0}, 2: {"minutos": "~12 min", "tienes": 2}},
    )
    panel.marcar_veredicto(recompensas, Veredicto([], 0, True, "", True))
    panel.hide()
    panel._temporizador.stop()
    panel.resize(ANCHO, ALTO)  # mostrar() la ajusta a la pantalla offscreen, que es mas pequena

    lienzo = QImage(ANCHO, ALTO, QImage.Format_ARGB32)
    lienzo.fill(QColor(24, 30, 38))
    pintor = QPainter(lienzo)
    pintor.setRenderHint(QPainter.Antialiasing)
    fuente = QFont("Segoe UI", 11)
    pintor.setFont(fuente)
    for caja, recompensa in zip(CAJAS, recompensas):
        x, y, w, h = caja
        # La tarjeta del juego: el objeto arriba y el nombre en la franja de abajo.
        tarjeta = QRect(x, y - 150, w, h + 150)
        pintor.setPen(QPen(QColor(90, 100, 115), 1))
        pintor.setBrush(QColor(40, 48, 60))
        pintor.drawRoundedRect(tarjeta, 4, 4)
        pintor.setPen(QColor(215, 220, 228))
        pintor.drawText(QRect(x + 6, y, w - 12, h), Qt.AlignCenter | Qt.TextWordWrap, recompensa.nombre.upper())
    panel.render(pintor, QPoint(0, 0))
    pintor.end()

    rect = panel.rectangulo_panel()
    recorte = QRect(CAJAS[0][0] - 40, CAJAS[0][1] - 190, 0, 0)
    recorte.setRight(CAJAS[-1][0] + CAJAS[-1][2] + 40)
    recorte.setBottom(rect.bottom() + 30)
    ruta = DESTINO / "panel_recompensas_es.png"
    lienzo.copy(recorte).save(str(ruta))
    print(ruta)


def main() -> None:
    app = QApplication.instance() or QApplication([])
    capturar_acerca()
    capturar_panel()
    app.quit()


if __name__ == "__main__":
    main()
