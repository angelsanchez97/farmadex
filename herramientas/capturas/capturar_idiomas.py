"""Renderiza el overlay sin pantalla en varios idiomas y guarda un PNG por pestana.

Uso: QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe herramientas/capturas/capturar_idiomas.py [es en ...]

Trabaja sobre una copia del indice real en una carpeta temporal (la misma caja de
arena que herramientas/render_ui.py), con su propia BD de usuario: asi se puede
importar el perfil de los fixtures para pintar la pestana Perfil sin tocar el
perfil ni los objetivos reales del usuario. No arranca hilos ni descarga nada.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Sin esto el modo offscreen en Windows no encuentra ninguna fuente y pinta cuadrados.
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "herramientas"))
from render_ui import preparar_sandbox  # noqa: E402

# config.py fija sus rutas al importarse: la caja de arena va antes de importar farmadex.
os.environ["FARMADEX_DATOS"] = str(preparar_sandbox())
sys.path.insert(0, str(RAIZ / "src"))

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import tareas  # noqa: E402
from farmadex.datos import indice  # noqa: E402
from farmadex.online import worldstate  # noqa: E402
from farmadex.ui.overlay import VentanaOverlay  # noqa: E402

DESTINO = Path(__file__).resolve().parent
PERFIL_FIXTURE = RAIZ / "tests" / "fixtures" / "perfil_recortado.json"


def _borrar_perfil(usuario) -> None:
    """Vacia las tablas perfil_* de la caja de arena para volver a la pantalla sin perfil."""
    tablas = [f[0] for f in usuario.execute("SELECT name FROM sqlite_master WHERE name LIKE 'perfil_%'")]
    with usuario:
        for tabla in tablas:
            usuario.execute(f"DELETE FROM {tabla}")


def main(codigos: list[str]) -> None:
    tareas.TareaDatos.start = lambda self: None  # nada de descargas ni hilos
    app = QApplication.instance() or QApplication([])
    ventana = VentanaOverlay()
    ventana.aplicar_modo("completo")  # la caja de arena puede tener guardada la compacta
    ventana.resize(1180, 760)
    ventana.show()

    con = indice.conectar()
    ventana.objetivos.conectar_indice(con)
    ventana.buscador.habilitar(True)
    ventana.buscador.caja.setText("ash prime systems")
    ventana.buscador._buscar()

    datos = json.loads((RAIZ / "tests/fixtures/worldstate.json").read_text(encoding="utf-8"))
    mundo = worldstate.analizar(datos, worldstate.Traductor(indice.conectar()))

    pestanas = (
        ("buscar", ventana.buscador), ("objetivos", ventana.objetivos), ("mundo", ventana.mundo),
        ("perfil", ventana.perfil), ("ajustes", ventana.ajustes),
    )
    for codigo in codigos:
        ventana.cambiar_idioma(codigo)
        ventana.mundo.actualizar(mundo)
        ventana.buscador._buscar()
        # Los widgets viejos se borran con deleteLater: sin vaciar esa cola aqui
        # se pintarian encima de los nuevos (en la app real lo hace el bucle de eventos).
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        # Perfil: primero la pantalla vacia (como la ve quien no ha importado nada)...
        _borrar_perfil(ventana.perfil.usuario)
        ventana.perfil.conectar_indice(indice.conectar())
        ventana.pestanas.setCurrentWidget(ventana.perfil)
        app.processEvents()
        ruta = DESTINO / f"perfil_vacio_{codigo}.png"
        ventana.grab().save(str(ruta))
        print(ruta)
        # ...y despues con el perfil de los fixtures importado.
        ventana.perfil.importar(PERFIL_FIXTURE, en_segundo_plano=False)
        # La ficha abierta en Buscar pasa a llevar la marca de maestria.
        ventana.buscador.abrir(ventana.buscador._actual) if ventana.buscador._actual else None
        for nombre, pestana in pestanas:
            ventana.pestanas.setCurrentWidget(pestana)
            app.processEvents()
            ruta = DESTINO / f"{nombre}_{codigo}.png"
            ventana.grab().save(str(ruta))
            print(ruta)
        # La parte baja del perfil: lo que falta por dominar y los nodos pendientes.
        ventana.pestanas.setCurrentWidget(ventana.perfil)
        barra = ventana.perfil.vista.verticalScrollBar()
        barra.setValue(barra.maximum() // 2)
        app.processEvents()
        ruta = DESTINO / f"perfil_pendientes_{codigo}.png"
        ventana.grab().save(str(ruta))
        print(ruta)
        barra.setValue(barra.maximum())
        app.processEvents()
        ruta = DESTINO / f"perfil_nodos_{codigo}.png"
        ventana.grab().save(str(ruta))
        print(ruta)
        barra.setValue(0)
    app.quit()


if __name__ == "__main__":
    main(sys.argv[1:] or ["es", "en"])
