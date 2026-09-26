"""Capturas del README para lo nuevo de la 0.5.0, renderizadas sin ventana visible.

Uso (desde la raiz del repo):
    QT_QPA_PLATFORM=offscreen FARMADEX_DATOS=<carpeta con Farmadex/db/indice.sqlite> \
        .venv/Scripts/python.exe herramientas/capturas/capturar_novedades_050.py [nombre ...]

Sin FARMADEX_DATOS usa la caja de arena de siempre (copia del indice real). Hace falta un
indice de esquema 14 (recetas, estadisticas, glifos). Nada de red: los precios, el mundo,
la build leida y el agrietado son inventados o salen de los ficheros de prueba.

Salidas en esta carpeta (castellano):
    buscar_colores_es.png, compacto_desplegado_es.png, ficha_estadisticas_es.png,
    ficha_glifo_es.png, objetivos_nuevos_es.png, mundo_avisos_es.png,
    ajustes_aspecto_es.png, bienvenida_es.png, bienvenida_seguro_es.png,
    build_es.png, agrietados_es.png
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
os.environ.setdefault("FARMADEX_SIN_BIENVENIDA", "1")

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "herramientas"))
sys.path.insert(0, str(RAIZ / "herramientas" / "capturas"))
from render_ui import preparar_sandbox  # noqa: E402

os.environ["FARMADEX_DATOS"] = str(preparar_sandbox())
sys.path.insert(0, str(RAIZ / "src"))

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import tareas  # noqa: E402
from farmadex.datos import indice  # noqa: E402
from farmadex.estado import objetivos as estado_objetivos  # noqa: E402
from farmadex.ui.overlay import VentanaOverlay  # noqa: E402

DESTINO = Path(__file__).resolve().parent
FIXTURES = RAIZ / "tests" / "fixtures"


class PreciosDePrueba:
    error = ""
    mejor_venta = 12
    mejor_compra = 8


def _vaciar_cola(app) -> None:
    app.processEvents()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def _id(con, nombre_en: str, padre: str | None = None) -> int | None:
    if padre is None:
        fila = con.execute(
            "SELECT id FROM items WHERE nombre_en = ? ORDER BY padre_id IS NOT NULL, id LIMIT 1", (nombre_en,)
        ).fetchone()
    else:
        fila = con.execute(
            "SELECT i.id FROM items i JOIN items p ON p.id = i.padre_id WHERE i.nombre_en = ? AND p.nombre_en = ?"
            " LIMIT 1", (nombre_en, padre),
        ).fetchone()
    return fila[0] if fila else None


def _buscar(ventana, app, texto: str) -> None:
    ventana.buscador.caja.setText(texto)
    ventana.buscador._temporizador.stop()
    ventana.buscador._buscar()
    _vaciar_cola(app)


def _abrir(ventana, app, con, nombre_en: str) -> None:
    item_id = _id(con, nombre_en)
    if item_id is None:
        print(f"  (no esta en el indice: {nombre_en})")
        return
    ventana.buscador.abrir(item_id)
    _vaciar_cola(app)


def _guardar(ventana, app, nombre: str) -> None:
    _vaciar_cola(app)
    ruta = DESTINO / nombre
    ventana.grab().save(str(ruta))
    print(ruta)


# -- cada captura ------------------------------------------------------------------


def buscar_colores(ventana, app, con) -> None:
    ventana.pestanas.setCurrentWidget(ventana.buscador)
    _buscar(ventana, app, "sierra")
    _guardar(ventana, app, "buscar_colores_es.png")


def ficha_estadisticas(ventana, app, con) -> None:
    ventana.pestanas.setCurrentWidget(ventana.buscador)
    _buscar(ventana, app, "rubico")
    _abrir(ventana, app, con, "Rubico")
    # Las estadisticas van debajo de "donde conseguirlo": se baja la ficha hasta ellas.
    ficha = ventana.buscador.ficha
    if hasattr(ficha, "find") and ficha.find("Estadisticas"):
        barra = ficha.verticalScrollBar()
        barra.setValue(barra.value() + ficha.cursorRect().top() - 40)
        cursor = ficha.textCursor()
        cursor.clearSelection()
        ficha.setTextCursor(cursor)
    _guardar(ventana, app, "ficha_estadisticas_es.png")


def ficha_glifo(ventana, app, con) -> None:
    ventana.pestanas.setCurrentWidget(ventana.buscador)
    _buscar(ventana, app, "glifo admiral bahroo")
    _abrir(ventana, app, con, "Admiral Bahroo Glyph")
    _guardar(ventana, app, "ficha_glifo_es.png")


def compacto_desplegado(ventana, app, con) -> None:
    ventana.aplicar_modo("compacto")
    ventana.resize(460, 560)
    texto = "sierra"
    ventana.compacta.caja.setText(texto)
    ventana.compacta._temporizador.stop()
    ventana.compacta._buscar(texto)
    if ventana.compacta._slug_actual:
        ventana.compacta.mostrar_precios(ventana.compacta._slug_actual, PreciosDePrueba())
    _guardar(ventana, app, "compacto_desplegado_es.png")
    ventana.aplicar_modo("completo")
    ventana.resize(1100, 700)


def objetivos_nuevos(ventana, app, con) -> None:
    usuario = ventana.objetivos.usuario
    for o in estado_objetivos.listar(usuario):
        estado_objetivos.borrar(usuario, o.id)
    # Un set Prime (panel que se despliega), un arma con receta (recursos por separado),
    # un recurso con meta grande a medias y unas Formas.
    rhino = _id(con, "Rhino Prime")
    if rhino is not None:
        estado_objetivos.anadir_set(usuario, con, rhino)
    for nombre_en, cantidad, hecho in (("Magistar", 1, 0), ("Cryotic", 500, 180), ("Forma", 3, 1)):
        fila = con.execute(
            "SELECT unique_name, COALESCE(nombre_es, nombre_en) FROM items WHERE nombre_en = ? AND padre_id IS NULL"
            " LIMIT 1", (nombre_en,),
        ).fetchone()
        if not fila:
            print(f"  (no esta en el indice: {nombre_en})")
            continue
        oid = estado_objetivos.anadir(usuario, fila[0], fila[1], cantidad, indice=con)
        if hecho:
            estado_objetivos.sumar(usuario, oid, hecho)
    ventana.objetivos.conectar_indice(indice.conectar())
    ventana.pestanas.setCurrentWidget(ventana.objetivos)
    ventana.objetivos.estados.setCurrentIndex(0)  # Sin empezar: el set y la Magistar
    _vaciar_cola(app)
    from farmadex.ui.pestana_objetivos import FilaObjetivo, PanelSet

    for panel in ventana.objetivos.findChildren(PanelSet)[:1]:
        panel._alternar()
    _vaciar_cola(app)
    for fila in ventana.objetivos.findChildren(FilaObjetivo):
        if fila.boton_recursos is not None:
            fila.boton_recursos.click()
            break
    ventana.resize(1100, 820)
    _guardar(ventana, app, "objetivos_nuevos_es.png")
    ventana.resize(1100, 700)


def mundo_avisos(ventana, app, con) -> None:
    import capturar_mundo

    ventana.mundo.conectar_objetivos(indice.conectar(), ventana.objetivos.usuario)
    ventana.mundo.actualizar(capturar_mundo.mundo_inventado(baro_activo=True))
    ventana.pestanas.setCurrentWidget(ventana.mundo)
    _vaciar_cola(app)
    ventana.mundo.boton_personalizar.click()
    ventana.resize(1100, 760)
    _guardar(ventana, app, "mundo_avisos_es.png")
    ventana.mundo.boton_personalizar.click()
    ventana.resize(1100, 700)


def ajustes_aspecto(ventana, app, con) -> None:
    ventana.pestanas.setCurrentWidget(ventana.ajustes)
    ventana.ajustes.ir_a("aspecto")
    ventana.resize(1100, 760)
    _guardar(ventana, app, "ajustes_aspecto_es.png")
    ventana.resize(1100, 700)


def bienvenida(ventana, app, con) -> None:
    ventana.pestanas.setCurrentWidget(ventana.buscador)
    _buscar(ventana, app, "")
    ventana.resize(1100, 720)
    ventana.mostrar_bienvenida(obligatoria=True)
    capa = ventana._bienvenida
    capa._ir_a(1)  # Lo basico, paso a paso
    _guardar(ventana, app, "bienvenida_es.png")
    capa._ir_a(2)  # Es seguro?
    _guardar(ventana, app, "bienvenida_seguro_es.png")
    capa.hide()
    capa.deleteLater()
    ventana._bienvenida = None
    ventana.resize(1100, 700)


def build(ventana, app, con) -> None:
    from farmadex.captura.builds import Build
    from farmadex.captura.ocr import Reconocido

    def rec(nombre_en: str) -> Reconocido | None:
        fila = con.execute(
            "SELECT id, COALESCE(nombre_es, nombre_en) FROM items WHERE nombre_en = ? AND padre_id IS NULL LIMIT 1",
            (nombre_en,),
        ).fetchone()
        return Reconocido(fila[1], fila[0], fila[1], 100.0, (0, 0, 0, 0)) if fila else None

    mods = ["Umbral Vitality", "Umbral Intensify", "Umbral Fiber", "Primed Flow", "Stretch",
            "Transient Fortitude", "Streamline", "Adaptation"]
    arcanos = ["Arcane Energize", "Molt Augmented"]
    b = Build(
        equipo=rec("Rhino Prime"), equipo_texto="RHINO PRIME",
        equipados=[r for r in map(rec, mods) if r],
        arcanos=[r for r in map(rec, arcanos) if r],
        sin_identificar=["IRON SK1N"],
    )
    ventana.builds.conectar_indice(indice.conectar())
    ventana.builds.mostrar_build(b)
    ventana.pestanas.setCurrentWidget(ventana.builds)
    _guardar(ventana, app, "build_es.png")


def agrietados(ventana, app, con) -> None:
    from farmadex.agrietados import mercado

    pestana = ventana.agrietados
    armas = mercado.analizar_armas(json.loads((FIXTURES / "market_riven_weapons.json").read_text(encoding="utf-8")))
    pestana.poner_armas(armas)
    if not pestana.elegir_arma("rubico"):
        print("  (no esta el Rubico en los datos de prueba)")
        return
    pestana.maestria.setValue(12)
    pestana.variado.setValue(4)
    pestana.poner_estadisticas([
        ("critical_chance", 141.0, False), ("critical_damage", 110.0, False),
        ("multishot", 80.0, False), ("zoom", 45.0, True),
    ])
    pestana.evaluar()
    resumen = mercado.analizar_subastas(
        "rubico", json.loads((FIXTURES / "market_riven_auctions.json").read_text(encoding="utf-8"))
    )
    medias = mercado.analizar_medias_de((FIXTURES / "de_weekly_rivens.txt").read_text(encoding="utf-8"))
    pestana._precio_pedido = "rubico"
    pestana._precio_listo("rubico", resumen, medias.get(("rubico", False)), medias.get(("rubico", True)))
    ventana.pestanas.setCurrentWidget(pestana)
    ventana.resize(1100, 760)
    _guardar(ventana, app, "agrietados_es.png")
    ventana.resize(1100, 700)


CAPTURAS = {
    "colores": buscar_colores,
    "estadisticas": ficha_estadisticas,
    "glifo": ficha_glifo,
    "compacto": compacto_desplegado,
    "objetivos": objetivos_nuevos,
    "mundo": mundo_avisos,
    "aspecto": ajustes_aspecto,
    "bienvenida": bienvenida,
    "build": build,
    "agrietados": agrietados,
}


def main(nombres: list[str]) -> None:
    tareas.TareaDatos.start = lambda self: None
    app = QApplication.instance() or QApplication([])
    ventana = VentanaOverlay()
    ventana.buscador.habilitar(True)
    ventana.aplicar_modo("completo")
    ventana.resize(1100, 700)
    ventana.show()
    ventana.cambiar_idioma("es")
    con = indice.conectar()
    for nombre in nombres or list(CAPTURAS):
        CAPTURAS[nombre](ventana, app, con)
    app.quit()


if __name__ == "__main__":
    main(sys.argv[1:])
