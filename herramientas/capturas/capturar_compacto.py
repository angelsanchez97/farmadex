"""Renderiza la vista compacta y la busqueda sin resultados, en varios idiomas, a PNG.

Uso: QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe herramientas/capturas/capturar_compacto.py [es en ...]

Misma caja de arena que capturar_idiomas.py (copia del indice real, sin hilos ni red).
Salidas en esta carpeta: compacto_<busqueda>_<idioma>.png y sin_resultados_<idioma>.png.
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
# Una pieza prime, una reliquia y un warframe: los tres tipos de "donde cae".
BUSQUEDAS = (("pieza", "ash prime systems"), ("reliquia", "axi a7"), ("warframe", "rhino"))


def objetivo_rhino(ventana) -> None:
    """En la BD de la caja de arena: el chasis de Rhino y el plano (sin ruta) como objetivos."""
    from farmadex.datos import indice
    from farmadex.estado import objetivos as estado_objetivos

    usuario = ventana.objetivos.usuario
    for o in estado_objetivos.listar(usuario):
        estado_objetivos.borrar(usuario, o.id)
    con = indice.conectar()
    for nombre_en in ("Chassis", "Blueprint"):
        fila = con.execute(
            "SELECT i.unique_name, COALESCE(i.nombre_es, i.nombre_en) FROM items i JOIN items p ON p.id = i.padre_id"
            " WHERE i.nombre_en = ? AND p.nombre_en = 'Rhino' LIMIT 1", (nombre_en,),
        ).fetchone()
        if fila:
            estado_objetivos.anadir(usuario, fila[0], f"{fila[1]} de Rhino", 1)
    ventana.objetivos.conectar_indice(indice.conectar())


class PreciosDePrueba:
    error = ""
    mejor_venta = 12
    mejor_compra = 8


def main(codigos: list[str]) -> None:
    tareas.TareaDatos.start = lambda self: None
    app = QApplication.instance() or QApplication([])
    ventana = VentanaOverlay()
    ventana.buscador.habilitar(True)
    ventana.show()
    for codigo in codigos:
        ventana.cambiar_idioma(codigo)
        # Busqueda sin resultados en la vista completa: la ficha anterior debe desaparecer.
        ventana.aplicar_modo("completo")
        ventana.resize(1100, 700)
        ventana.buscador.caja.setText("ash prime")
        ventana.buscador._temporizador.stop()
        ventana.buscador._buscar()
        app.processEvents()
        ventana.buscador.caja.setText("como consigo rhino")
        ventana.buscador._temporizador.stop()
        ventana.buscador._buscar()
        app.processEvents()
        ruta = DESTINO / f"sin_resultados_{codigo}.png"
        ventana.grab().save(str(ruta))
        print(ruta)

        # Una pieza que no sale de reliquias (el chasis de Rhino cae del Chacal): ruta directa.
        ventana.buscador.caja.setText("chasis de rhino")
        ventana.buscador._temporizador.stop()
        ventana.buscador._buscar()
        app.processEvents()
        ruta = DESTINO / f"buscar_ruta_directa_{codigo}.png"
        ventana.grab().save(str(ruta))
        print(ruta)
        objetivo_rhino(ventana)
        ventana.pestanas.setCurrentWidget(ventana.objetivos)
        app.processEvents()
        ruta = DESTINO / f"objetivos_ruta_directa_{codigo}.png"
        ventana.grab().save(str(ruta))
        print(ruta)
        ventana.pestanas.setCurrentWidget(ventana.buscador)

        ventana.aplicar_modo("compacto")
        for nombre, texto in BUSQUEDAS:
            ventana.compacta.caja.setText(texto)
            if ventana.compacta._slug_actual:
                ventana.compacta.mostrar_precios(ventana.compacta._slug_actual, PreciosDePrueba())
            app.processEvents()
            ruta = DESTINO / f"compacto_{nombre}_{codigo}.png"
            ventana.grab().save(str(ruta))
            print(ruta)
        ventana.compacta.caja.setText("como consigo rhino")
        app.processEvents()
        ruta = DESTINO / f"compacto_sin_resultados_{codigo}.png"
        ventana.grab().save(str(ruta))
        print(ruta)
    app.quit()


if __name__ == "__main__":
    main(sys.argv[1:] or ["es", "en"])
