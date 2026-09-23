"""Renderiza el overlay con datos reales, en cada tema, y deja los PNG en herramientas/capturas/.

Uso: .venv/Scripts/python.exe herramientas/render_ui.py [vacio|orokin|tenno|cherry|todos]

No toca los datos del usuario: copia el indice real a una carpeta temporal y trabaja
ahi (FARMADEX_DATOS), con su propio config.json y su propia base de objetivos.
Las capturas se componen sobre un fondo parecido a una partida para juzgar el contraste.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CAPTURAS = RAIZ / "herramientas" / "capturas"
TEMAS = ("vacio", "orokin", "tenno", "cherry")


def preparar_sandbox() -> Path:
    real = Path(os.environ.get("FARMADEX_INDICE_ORIGEN") or Path(os.environ.get("LOCALAPPDATA", "")) / "Farmadex" / "db" / "indice.sqlite")
    if not real.exists():
        sys.exit("No hay indice real construido; abre la app una vez primero.")
    raiz = Path(tempfile.gettempdir()) / "farmadex_render"
    # Antes del import de farmadex de abajo: config fija sus rutas al importarse y, sin
    # esto, la copia del indice dejaba config apuntando a la carpeta de verdad.
    os.environ["FARMADEX_DATOS"] = str(raiz)
    caja = raiz / "Farmadex"  # config.DIR_BASE = FARMADEX_DATOS / NOMBRE_APP
    (caja / "db").mkdir(parents=True, exist_ok=True)
    destino = caja / "db" / "indice.sqlite"
    if not destino.exists() or destino.stat().st_size != real.stat().st_size:
        shutil.copy2(real, destino)
        # La copia puede ser de un esquema anterior; para pintar da igual.
        sys.path.insert(0, str(RAIZ / "src"))
        from farmadex.datos.indice import VERSION_ESQUEMA
        import sqlite3

        con = sqlite3.connect(destino)
        con.execute("UPDATE meta SET valor = ? WHERE clave = 'esquema_version'", (VERSION_ESQUEMA,))
        con.commit()
        con.close()
    # Las imagenes descargadas se comparten con la app para no bajarlas dos veces.
    img_real = real.parents[1] / "datos" / "img"
    (caja / "datos").mkdir(exist_ok=True)
    if img_real.exists() and not (caja / "datos" / "img").exists():
        try:
            os.symlink(img_real, caja / "datos" / "img", target_is_directory=True)
        except OSError:
            shutil.copytree(img_real, caja / "datos" / "img")
    return raiz


def fondo_de_partida(ancho: int, alto: int):
    """Un fondo con luces y sombras fuertes, como una mision: lo peor para leer encima."""
    import numpy as np
    from PIL import Image, ImageFilter

    generador = np.random.default_rng(3)
    y, x = np.mgrid[0:alto, 0:ancho].astype(np.float32)
    r = 40 + 120 * np.exp(-((x - ancho * 0.7) ** 2 + (y - alto * 0.3) ** 2) / (2 * 260 ** 2))
    g = 60 + 90 * np.exp(-((x - ancho * 0.2) ** 2 + (y - alto * 0.8) ** 2) / (2 * 300 ** 2))
    b = 90 + 110 * np.exp(-((x - ancho * 0.3) ** 2 + (y - alto * 0.2) ** 2) / (2 * 220 ** 2))
    r += 150 * np.exp(-((x - ancho * 0.85) ** 2 + (y - alto * 0.85) ** 2) / (2 * 120 ** 2))
    ruido = generador.normal(0, 18, (alto, ancho)).astype(np.float32)
    arr = np.stack([r + ruido, g + ruido * 0.7, b + ruido * 0.5], axis=2)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return img.filter(ImageFilter.GaussianBlur(2))


def renderizar(tema: str) -> list[Path]:
    """Se ejecuta en un proceso hijo con FARMADEX_DATOS ya apuntando al sandbox."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, str(RAIZ / "src"))
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication

    from farmadex import config
    from farmadex.datos import indice
    from farmadex.estado import objetivos as estado_objetivos
    from farmadex.online.worldstate import Traductor, analizar
    from farmadex.ui import overlay as modulo_overlay
    from farmadex.ui.widgets import HOJA_ESTILOS

    cfg = config.cargar()
    cfg["tema"] = tema
    cfg["overlay_geometria"] = None
    config.guardar(cfg)

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(HOJA_ESTILOS)
    modulo_overlay.VentanaOverlay.preparar_datos = lambda self, forzar=False: None
    ventana = modulo_overlay.VentanaOverlay()
    ventana.resize(1180, 760)
    con = indice.conectar()

    # Objetivos de muestra: una pieza prime, un recurso y algo en boveda.
    usuario = ventana.objetivos.usuario
    for o in estado_objetivos.listar(usuario):
        estado_objetivos.borrar(usuario, o.id)
    for nombre_en, padre_en, cantidad, hechos in (
        ("Systems", "Ash Prime", 1, 0), ("Forma", None, 5, 2), ("Chassis", "Rhino Prime", 1, 1),
    ):
        fila = con.execute(
            "SELECT i.unique_name, COALESCE(i.nombre_es, i.nombre_en) FROM items i"
            " LEFT JOIN items p ON p.id = i.padre_id"
            " WHERE i.nombre_en = ? AND COALESCE(p.nombre_en, '') = ? LIMIT 1",
            (nombre_en, padre_en or ""),
        ).fetchone()
        if fila:
            etiqueta = f"{fila[1]} de {padre_en}" if padre_en else fila[1]
            estado_objetivos.anadir(usuario, fila[0], etiqueta, cantidad)
            if hechos:
                estado_objetivos.sumar_por_item(usuario, fila[0], hechos)
    ventana.buscador.habilitar(True)
    ventana.objetivos.conectar_indice(indice.conectar())
    ventana.ajustes.refrescar_estado()
    ventana.ajustes.estado_version("Estas en la ultima version")

    datos_mundo = json.loads((RAIZ / "tests" / "fixtures" / "worldstate.json").read_text("utf-8"))
    ventana.mundo.actualizar(analizar(datos_mundo, Traductor(con)))

    ventana.buscador.caja.setText("ash prime")
    ventana.buscador._temporizador.stop()  # si no, la busqueda diferida deshace la seleccion
    ventana.buscador._buscar()
    # La ficha de una pieza ensena las reliquias, que es lo que hay que juzgar.
    for fila in range(ventana.buscador.lista.count()):
        if ventana.buscador.lista.item(fila).text().startswith("Sistemas"):
            ventana.buscador.lista.setCurrentRow(fila)
            break
    ventana.buscador.precios.hide()
    ventana.show()
    # Dar tiempo a que bajen las imagenes de los resultados y de la ficha.
    limite = time.monotonic() + 6
    while time.monotonic() < limite:
        app.processEvents()
        time.sleep(0.05)
    ventana.buscador.repintar()

    fondo = fondo_de_partida(ventana.width() + 160, ventana.height() + 120)
    CAPTURAS.mkdir(parents=True, exist_ok=True)
    salidas = []
    for nombre, pestana in (
        ("buscar", ventana.buscador), ("objetivos", ventana.objetivos),
        ("mundo", ventana.mundo), ("ajustes", ventana.ajustes),
    ):
        ventana.pestanas.setCurrentWidget(pestana)
        for _ in range(5):
            app.processEvents()
        mapa = ventana.grab()
        bufer = QBuffer()
        bufer.open(QIODevice.WriteOnly)
        mapa.toImage().save(bufer, "PNG")
        from io import BytesIO

        from PIL import Image

        capa = Image.open(BytesIO(bytes(bufer.data()))).convert("RGBA")
        lienzo = fondo.convert("RGBA").copy()
        lienzo.alpha_composite(capa, (80, 60))
        destino = CAPTURAS / f"{tema}_{nombre}.png"
        lienzo.convert("RGB").save(destino)
        salidas.append(destino)
    ventana.etiquetas.hide()
    return salidas


def main() -> int:
    eleccion = sys.argv[1] if len(sys.argv) > 1 else "todos"
    if os.environ.get("FARMADEX_RENDER_HIJO"):
        for ruta in renderizar(eleccion):
            print(ruta)
        return 0
    caja = preparar_sandbox()
    # El backend offscreen no encuentra las fuentes de Windows por si solo.
    fuentes = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    entorno = dict(os.environ, FARMADEX_DATOS=str(caja), FARMADEX_RENDER_HIJO="1",
                   QT_QPA_PLATFORM="offscreen", QT_QPA_FONTDIR=str(fuentes))
    temas = TEMAS if eleccion == "todos" else (eleccion,)
    for tema in temas:
        resultado = subprocess.run(
            [sys.executable, __file__, tema], env=entorno, capture_output=True, text=True,
            timeout=180,
        )
        print(resultado.stdout.strip())
        if resultado.returncode:
            print(resultado.stderr[-3000:])
            return resultado.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
