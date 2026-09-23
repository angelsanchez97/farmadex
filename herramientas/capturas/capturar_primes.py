"""Renderiza sin pantalla la pestana Primes y la ficha de una pieza prime.

Uso: .venv/Scripts/python.exe herramientas/capturas/capturar_primes.py

Guarda en esta carpeta:
- primes_rejilla_<tema>.png y primes_resultado_<tema>.png, con "Caliban Prime Plano"
  marcado, para compararlo con el Relicario de wf.xuerian.net;
- primes_minimo.png (ventana completa en su tamano minimo, 760x420) y
  primes_grande.png (1500x900, rejilla y resultado lado a lado);
- ficha_pieza_prime.png y ficha_objeto_prime.png ("Por donde empezar").

Trabaja sobre una copia del indice real (solo lectura del original) en su propia
carpeta temporal, con una BD de usuario nueva: no toca los objetivos de verdad.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

RAIZ = Path(__file__).resolve().parents[2]
DESTINO = Path(__file__).resolve().parent


def preparar() -> Path:
    real = Path(os.environ.get("LOCALAPPDATA", "")) / "Farmadex" / "db" / "indice.sqlite"
    if not real.exists():
        sys.exit("No hay indice real construido; abre la app una vez primero.")
    raiz = Path(tempfile.gettempdir()) / "farmadex_render_primes"
    if raiz.exists():
        shutil.rmtree(raiz)
    (raiz / "Farmadex" / "db").mkdir(parents=True)
    destino = raiz / "Farmadex" / "db" / "indice.sqlite"
    shutil.copy2(real, destino)
    # Antes de importar nada de farmadex: config fija sus rutas al importarse, y sin
    # esto la ventana escribe objetivos y configuracion en la carpeta de verdad.
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import tareas  # noqa: E402
from farmadex.datos import indice  # noqa: E402
from farmadex.ui.overlay import VentanaOverlay  # noqa: E402
from farmadex.ui.widgets import TEMAS  # noqa: E402


def _marcar(pestana, nombre_objeto: str, pieza_en: str) -> None:
    for caja in pestana._cajas:
        if caja.objeto and caja.objeto["nombre_en"] == nombre_objeto:
            for pieza in caja.piezas:
                if pieza["nombre_en"] == pieza_en:
                    caja.casillas[pieza["unique_name"]].setChecked(True)
                    return
    raise SystemExit(f"No encuentro {nombre_objeto} / {pieza_en}")


def main() -> None:
    tareas.TareaDatos.start = lambda self: None
    app = QApplication.instance() or QApplication([])
    ventana = VentanaOverlay()
    ventana.aplicar_modo("completo")
    ventana.show()
    ventana.buscador.habilitar(True)
    ventana.primes.conectar_indice(indice.conectar())
    ventana.objetivos.conectar_indice(indice.conectar())
    primes = ventana.primes
    ventana.pestanas.setCurrentWidget(primes)
    _marcar(primes, "Caliban Prime", "Blueprint")

    def guardar(nombre: str) -> None:
        for _ in range(3):
            app.processEvents()
        primes._pintar_resultado()
        app.processEvents()
        ruta = DESTINO / nombre
        ventana.grab().save(str(ruta))
        print(ruta)

    ventana.resize(1180, 820)
    for tema in TEMAS:
        ventana.cambiar_tema(tema)
        primes._elegir_vista("rejilla")
        guardar(f"primes_rejilla_{tema}.png")
        primes._elegir_vista("resultado")
        guardar(f"primes_resultado_{tema}.png")
    ventana.cambiar_tema("orokin")

    ventana.resize(760, 420)
    primes._elegir_vista("rejilla")
    guardar("primes_minimo.png")
    primes._elegir_vista("resultado")
    guardar("primes_minimo_resultado.png")
    ventana.resize(1500, 900)
    guardar("primes_grande.png")

    ventana.pestanas.setCurrentWidget(ventana.buscador)
    ventana.resize(1180, 820)
    for busqueda, nombre in (("plano caliban prime", "ficha_pieza_prime.png"), ("caliban prime", "ficha_objeto_prime.png")):
        ventana.buscador.caja.setText(busqueda)
        ventana.buscador._buscar()
        app.processEvents()
        ventana.buscador.abrir(ventana.buscador._resultados[0]["item_id"])
        app.processEvents()
        ruta = DESTINO / nombre
        ventana.grab().save(str(ruta))
        print(ruta)
    app.quit()


if __name__ == "__main__":
    main()
