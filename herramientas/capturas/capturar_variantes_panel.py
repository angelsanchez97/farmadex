"""Renderiza los tres disenos del panel de recompensas con cada preajuste, para elegir.

Cuatro recompensas reales del indice (una que te falta, una que completa set, una
cara en platino y una con muchos ducados) con datos de usuario de ejemplo en una
base en memoria, puntuadas por el comparador de verdad con precios fijos, sobre un
fondo tipo partida. Tambien las etiquetas pequenas, que siguen el mismo preajuste.

No toca %LocalAppData%\\Farmadex: FARMADEX_DATOS apunta a una carpeta temporal y el
indice se abre en solo lectura. Todo offscreen, no abre ninguna ventana.

Uso:
    .venv/Scripts/python.exe herramientas/capturas/capturar_variantes_panel.py RUTA_INDICE [CARPETA_SALIDA]
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
os.environ.setdefault("FARMADEX_DATOS", str(Path(tempfile.gettempdir()) / "farmadex_variantes_panel"))

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "herramientas"))

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex.captura import prioridad as prio  # noqa: E402
from farmadex.captura.comparador import puntuar  # noqa: E402
from farmadex.captura.reliquias import Recompensa  # noqa: E402
from farmadex.online.market import Orden, Precios  # noqa: E402
from farmadex.ui import panel_recompensas as modulo_panel  # noqa: E402
from farmadex.ui.etiquetas import EtiquetasRecompensas  # noqa: E402
from farmadex.ui.panel_recompensas import PanelRecompensas  # noqa: E402

ANCHO, ALTO = 1920, 1080
CAJAS = [(545, 470, 200, 40), (765, 470, 200, 40), (985, 470, 200, 40), (1205, 470, 200, 40)]
# (padre en ingles, pieza en ingles, nombre en pantalla, precio de venta mas barato)
MUESTRA = [
    ("Caliban Prime", "Systems", "Sistemas de Caliban Prime", 18),  # objetivo: te falta
    ("Braton Prime", "Stock", "Culata de Braton Prime", 3),  # tienes Canon y Plano: completa set
    ("Nikana Prime", "Hilt", "Empunadura de Nikana Prime", 45),  # la cara, ya dominada
    ("Trumna Prime", "Receiver", "Receptor de Trumna Prime", 6),  # 100 ducados, sin dominar
]
PRESETS = {"me_falta": prio.ME_FALTA, "platino": prio.PLATINO}


def _pieza(indice, padre: str, pieza: str) -> tuple[int, str, int]:
    fila = indice.execute(
        "SELECT i.id, i.unique_name, p.id FROM items i JOIN items p ON p.id = i.padre_id "
        "WHERE p.nombre_en = ? AND i.nombre_en = ?", (padre, pieza),
    ).fetchone()
    if not fila:
        sys.exit(f"No esta en el indice: {padre} {pieza}")
    return fila


def preparar_usuario(indice) -> sqlite3.Connection:
    from farmadex.estado import inventario, objetivos, usuario_db
    from farmadex.perfil import almacen

    usuario = sqlite3.connect(":memory:")
    usuario.executescript(usuario_db.ESQUEMA)
    caliban = _pieza(indice, "Caliban Prime", "Systems")
    objetivos.anadir(usuario, caliban[1], "Sistemas de Caliban Prime", 1)
    tienes = [_pieza(indice, "Braton Prime", nombre)[1] for nombre in ("Barrel", "Blueprint")]
    inventario.guardar(usuario, [SimpleNamespace(unique_name=u, cantidad=1) for u in tienes])
    almacen.preparar(usuario)
    usuario.execute("INSERT INTO perfil_meta VALUES ('nombre', 'Tenno')")
    nikana = indice.execute("SELECT unique_name FROM items WHERE nombre_en = 'Nikana Prime'").fetchone()[0]
    usuario.execute("INSERT INTO perfil_xp (item_type, xp) VALUES (?, ?)", (nikana, 10_000_000))
    usuario.commit()
    return usuario


def recompensas_puntuadas(indice, usuario, prioridad: str) -> tuple[list[Recompensa], object]:
    recompensas, precios = [], {}
    for caja, (padre, pieza, nombre, platino) in zip(CAJAS, MUESTRA):
        item_id, _unico, _padre = _pieza(indice, padre, pieza)
        recompensas.append(Recompensa(item_id, nombre, nombre.upper(), caja))
        slug = indice.execute("SELECT market_slug FROM items WHERE id = ?", (item_id,)).fetchone()[0]
        precios[slug] = Precios(slug=slug, ventas=[Orden(platino + i, 1, f"u{i}", "ingame") for i in range(6)])
    veredicto = puntuar(recompensas, indice, precios.get, usuario, escuadra=True, prioridad=prioridad)
    print(f"  {prioridad}: {veredicto.resumen()}")
    return recompensas, veredicto


def fondo() -> QImage:
    from render_ui import fondo_de_partida

    bufer = BytesIO()
    fondo_de_partida(ANCHO, ALTO).save(bufer, "PNG")
    imagen = QImage()
    imagen.loadFromData(bufer.getvalue(), "PNG")
    return imagen.convertToFormat(QImage.Format_ARGB32)


def tarjetas_del_juego(pintor, recompensas) -> None:
    pintor.setFont(QFont("Segoe UI", 11))
    for caja, recompensa in zip(CAJAS, recompensas):
        x, y, w, h = caja
        tarjeta = QRect(x, y - 150, w, h + 150)
        pintor.setPen(QPen(QColor(90, 100, 115), 1))
        pintor.setBrush(QColor(40, 48, 60, 220))
        pintor.drawRoundedRect(tarjeta, 4, 4)
        pintor.setPen(QColor(215, 220, 228))
        pintor.drawText(QRect(x + 6, y, w - 12, h), Qt.AlignCenter | Qt.TextWordWrap, recompensa.nombre.upper())


def maestria_de(recompensas) -> dict:
    estados = {"sin_tocar": "Sin dominar", "dominado": "Dominado", "a_medias": "A medias"}
    return {r.item_id: (estados[r.maestria_estado], r.maestria_estado) for r in recompensas if r.maestria_estado}


def componer(vista, recompensas, arriba: int, abajo: int, margen: int = 50) -> QImage:
    lienzo = fondo()
    pintor = QPainter(lienzo)
    pintor.setRenderHint(QPainter.Antialiasing)
    tarjetas_del_juego(pintor, recompensas)
    vista.render(pintor, QPoint(0, 0))
    pintor.end()
    recorte = QRect(CAJAS[0][0] - margen, arriba, 0, 0)
    recorte.setRight(CAJAS[-1][0] + CAJAS[-1][2] + margen)
    recorte.setBottom(abajo)
    return lienzo.copy(recorte)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ruta_indice = Path(sys.argv[1])
    salida = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(tempfile.gettempdir()) / "farmadex_variantes_panel" / "png"
    salida.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    indice = sqlite3.connect(f"file:{ruta_indice.as_posix()}?mode=ro", uri=True)
    usuario = preparar_usuario(indice)
    extras = {}
    for (padre, pieza, _n, _p), minutos in zip(MUESTRA, ("~35 min", "~12 min", "~1 h 10 min", "~20 min")):
        extras[_pieza(indice, padre, pieza)[0]] = {"minutos": minutos}

    for nombre_preset, prioridad in PRESETS.items():
        for variante in modulo_panel.VARIANTES:
            recompensas, veredicto = recompensas_puntuadas(indice, usuario, prioridad)
            panel = PanelRecompensas()
            panel.variante, panel.prioridad = variante, prioridad
            panel.resize(ANCHO, ALTO)
            panel.mostrar(recompensas, maestria_de(recompensas), extras)
            panel.marcar_veredicto(recompensas, veredicto)
            panel.hide()
            panel._temporizador.stop()
            panel.resize(ANCHO, ALTO)  # mostrar() la ajusta a la pantalla offscreen
            rect = panel.rectangulo_panel()
            imagen = componer(panel, recompensas, CAJAS[0][1] - 190, rect.bottom() + 30)
            ruta = salida / f"variante_{variante}_{nombre_preset}.png"
            imagen.save(str(ruta))
            print(ruta)
        recompensas, veredicto = recompensas_puntuadas(indice, usuario, prioridad)
        etiquetas = EtiquetasRecompensas()
        etiquetas.prioridad = prioridad
        etiquetas.resize(ANCHO, ALTO)
        etiquetas.mostrar(recompensas, maestria_de(recompensas))
        etiquetas.marcar_veredicto(recompensas, veredicto)
        etiquetas.hide()
        etiquetas._temporizador.stop()
        etiquetas.resize(ANCHO, ALTO)
        imagen = componer(etiquetas, recompensas, CAJAS[0][1] - 330, CAJAS[0][1] + 70, margen=180)
        ruta = salida / f"etiquetas_pequenas_{nombre_preset}.png"
        imagen.save(str(ruta))
        print(ruta)
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
