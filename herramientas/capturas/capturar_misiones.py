"""Renderiza sin pantalla lo nuevo de la 0.3.x para el README y el manual.

Uso: .venv/Scripts/python.exe herramientas/capturas/capturar_misiones.py

Guarda en esta carpeta:
- ficha_mision_olimpo.png: la ficha de un nodo (como se juega, rotaciones y que suelta
  cada una);
- ficha_tipo_supervivencia.png: la ficha de un tipo de mision;
- ficha_lith_s19_rotaciones.png: una reliquia con la rotacion a la vista en cada fila;
- novedades_ultimo_warframe.png, buscar_portada_novedades.png y
  pregunta_citrine_prime.png: preguntas en lenguaje natural y la linea de Novedades;
- botones_wiki_youtube.png: recorte de la fila de botones con una ficha abierta;
- video_panel_vacio.png: la pestana Video antes de abrir una guia (el reproductor
  WebView2 no se puede pintar sin pantalla);
- guia_paso_<n>.png: los pasos nuevos de la guia.

Trabaja sobre una copia del indice real en su propia carpeta temporal (FARMADEX_DATOS),
con su config y su BD de usuario: no toca los datos de verdad. El indice de origen se
puede cambiar con FARMADEX_INDICE_ORIGEN. No abre ninguna ventana visible.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

RAIZ = Path(__file__).resolve().parents[2]
DESTINO = Path(__file__).resolve().parent


def preparar() -> Path:
    real = Path(
        os.environ.get("FARMADEX_INDICE_ORIGEN")
        or Path(os.environ.get("LOCALAPPDATA", "")) / "Farmadex" / "db" / "indice.sqlite"
    )
    if not real.exists():
        sys.exit("No hay indice real construido; abre la app una vez primero.")
    raiz = Path(tempfile.gettempdir()) / "farmadex_render_misiones"
    if raiz.exists():
        shutil.rmtree(raiz)
    (raiz / "Farmadex" / "db").mkdir(parents=True)
    destino = raiz / "Farmadex" / "db" / "indice.sqlite"
    shutil.copy2(real, destino)
    # Las imagenes ya descargadas se copian (nunca un enlace: lo que se bajase ahora
    # acabaria en la carpeta de verdad).
    img = Path(os.environ.get("LOCALAPPDATA", "")) / "Farmadex" / "datos" / "img"
    if img.exists():
        shutil.copytree(img, raiz / "Farmadex" / "datos" / "img")
    # Antes de importar nada de farmadex: config fija sus rutas al importarse.
    os.environ["FARMADEX_DATOS"] = str(raiz)
    sys.path.insert(0, str(RAIZ / "src"))
    import sqlite3

    from farmadex.datos.indice import VERSION_ESQUEMA

    con = sqlite3.connect(destino)
    con.execute("UPDATE meta SET valor = ? WHERE clave = 'esquema_version'", (VERSION_ESQUEMA,))
    con.commit()
    con.close()
    return raiz


preparar()

from farmadex import config as _config  # noqa: E402

assert str(_config.DIR_BASE).startswith(os.environ["FARMADEX_DATOS"]), _config.DIR_BASE

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import tareas  # noqa: E402
from farmadex.datos import indice  # noqa: E402
from farmadex.ui.overlay import VentanaOverlay  # noqa: E402


def main() -> None:
    tareas.TareaDatos.start = lambda self: None
    app = QApplication.instance() or QApplication([])
    ventana = VentanaOverlay()
    ventana.aplicar_modo("completo")
    ventana.cambiar_tema("orokin")
    ventana.resize(1180, 880)
    ventana.show()
    ventana.buscador.habilitar(True)
    ventana.primes.conectar_indice(indice.conectar())
    ventana.objetivos.conectar_indice(indice.conectar())
    b = ventana.buscador
    # Sin precios: cambian cada hora y no es lo que se ensena aqui.
    b._consultar_precio = lambda item: b.precios.hide()

    def asentar() -> None:
        for _ in range(5):
            app.processEvents()

    def guardar(nombre: str, recorte: QRect | None = None) -> None:
        asentar()
        imagen = ventana.grab(recorte) if recorte is not None else ventana.grab()
        ruta = DESTINO / nombre
        imagen.save(str(ruta))
        print(ruta)

    def buscar(texto: str) -> None:
        ventana.pestanas.setCurrentWidget(b)
        b.caja.setText(texto)
        b._temporizador.stop()
        b._buscar()
        asentar()

    def bajar_hasta(texto: str) -> None:
        """Desplaza la ficha hasta que `texto` quede arriba del todo."""
        cursor = b.ficha.document().find(texto)
        if cursor.isNull():
            return
        b.ficha.verticalScrollBar().setValue(b.ficha.cursorRect(cursor).top() + b.ficha.verticalScrollBar().value() - 8)

    buscar("olimpo")
    guardar("ficha_mision_olimpo.png")
    buscar("supervivencia")
    guardar("ficha_tipo_supervivencia.png")

    buscar("lith s19")
    guardar("ficha_lith_s19.png")
    bajar_hasta("Contenido en")
    guardar("ficha_lith_s19_rotaciones.png")

    # Con una ficha abierta los dos botones estan activos: recorte de su fila.
    zona = QRect()
    for w in (b.ocultar_vaulted, b.boton_wiki, b.boton_youtube, b.boton_set, b.boton_objetivo):
        zona = zona.united(QRect(w.mapTo(ventana, QPoint(0, 0)), w.size()))
    guardar("botones_wiki_youtube.png", zona.adjusted(-12, -10, 12, 10))

    buscar("el ultimo warframe")
    guardar("novedades_ultimo_warframe.png", QRect(0, 0, ventana.width(), 420))
    buscar("como sacar citrine prime")
    guardar("pregunta_citrine_prime.png")
    buscar("")
    # La linea de Novedades es lo unico que hay: solo la parte de arriba.
    guardar("buscar_portada_novedades.png", QRect(0, 0, ventana.width(), 260))

    ventana.pestanas.setCurrentWidget(ventana.video)
    guardar("video_panel_vacio.png")

    # Pasos nuevos de la guia, con la ficha de Olimpo abierta detras.
    buscar("olimpo")
    ventana.mostrar_guia()
    guia = ventana._guia
    for titulo, nombre in (
        ("Misiones y preguntas", "guia_paso_misiones.png"),
        ("Wiki y videos", "guia_paso_wiki_youtube.png"),
        ("Primes", "guia_paso_primes.png"),
        ("Video", "guia_paso_video.png"),
        ("Si no sale nada al abrir una reliquia", "guia_paso_diagnostico.png"),
    ):
        guia._ir_a_paso(next(i for i, p in enumerate(guia._pasos) if p.titulo == titulo))
        guardar(nombre)
    guia.terminar()
    app.quit()


if __name__ == "__main__":
    main()
