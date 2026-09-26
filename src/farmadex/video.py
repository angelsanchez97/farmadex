"""Proceso hijo del reproductor de guias: una ventana WebView2 que Farmadex incrusta.

Quien juega con un solo monitor quiere ver la guia en video sin salir del juego, dentro
de la ventana de Farmadex. Qt no trae navegador sin QtWebEngine (~300 MB mas en cada
instalador y cada actualizacion), asi que se usa WebView2, el Chromium de Edge que ya
trae Windows 10/11, a traves de pywebview. pywebview tiene su propio bucle de ventanas y
no convive con el de Qt en el mismo proceso: por eso va en un proceso aparte, el mismo
ejecutable con un argumento:

    Farmadex.exe --video <url> --estado <fichero> --padre <pid> --datos <carpeta>
    python -m farmadex.video <url> --estado <fichero> ...        (desde el codigo)

El hijo crea una ventana sin bordes y escondida y escribe su HWND en el fichero de
estado ("HWND 123456", o "ERROR <motivo>" si no puede). Farmadex la mete en su panel con
QWidget.createWindowContainer(QWindow.fromWinId(hwnd)), que es el mecanismo oficial de
Qt para ventanas nativas ajenas (ui/reproductor.py). El fichero y no la salida estandar
porque el .exe no tiene consola y ahi stdout puede no existir.

Muere con Farmadex: vigila el PID del padre y se cierra en cuanto desaparece, aunque
Farmadex se haya caido sin avisar. Para cambiar de video, Farmadex cierra este proceso
(por su PID) y lanza otro.

El mismo hijo sirve para cualquier pagina web dentro de Farmadex (el panel Web, con las
builds de Overframe): los botones "Atras" y "Recargar" del panel dejan una orden en un
fichero al lado del de estado ("ATRAS", "RECARGAR") y el hijo la ejecuta en la pagina.
El hijo apunta en otro fichero la direccion que se esta viendo, para que "Abrir en el
navegador" abra esa y no la del principio. Los enlaces que piden ventana nueva se abren
en la misma vista: el usuario no quiere que se le abran ventanas.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from pathlib import Path

from .ficheros import reemplazar, temporal_de

ARGUMENTO = "--video"
TITULO = "Farmadex · Guia"
# Cada cuanto se mira si Farmadex sigue vivo, y cuanto se espera a que exista la ventana.
VIGILANCIA_S = 1.5
ESPERA_VENTANA_S = 20.0
# Cada cuanto se miran las ordenes del panel (Atras, Recargar).
ORDENES_S = 0.2
# Orden del panel -> JavaScript que la hace en la pagina.
ORDENES = {"ATRAS": "history.back()", "ADELANTE": "history.forward()", "RECARGAR": "location.reload()"}


def rutas_auxiliares(estado: str | Path) -> tuple[Path, Path]:
    """(fichero de ordenes, fichero con la direccion actual), al lado del de estado.

    Farmadex y el hijo las sacan de aqui los dos: asi no hacen falta argumentos nuevos.
    """
    estado = Path(estado)
    return estado.with_name(estado.stem + "_ordenes.txt"), estado.with_name(estado.stem + "_url.txt")


def leer_orden(ruta: str | Path) -> str | None:
    """La orden pendiente (y se borra, para no repetirla); None si no hay ninguna valida."""
    ruta = Path(ruta)
    try:
        texto = ruta.read_text(encoding="utf-8").strip().upper()
        ruta.unlink()
    except OSError:
        return None
    return texto if texto in ORDENES else None


def atender(ventana, ordenes: Path, url_actual: Path, ultima_url: str) -> str:
    """Una vuelta del hijo: hace la orden pendiente y apunta la direccion si ha cambiado.

    Devuelve la direccion apuntada. Nunca falla: una pagina que no deja ejecutar el
    JavaScript solo se queda sin ir atras.
    """
    orden = leer_orden(ordenes)
    if orden:
        try:
            ejecutar = getattr(ventana, "run_js", None) or ventana.evaluate_js
            ejecutar(ORDENES[orden])
        except Exception:  # noqa: BLE001 - pagina aun sin cargar o que no lo permite
            pass
    try:
        actual = str(ventana.get_current_url() or "")
    except Exception:  # noqa: BLE001 - aun sin pagina
        actual = ""
    if actual and actual != ultima_url:
        try:
            escribir_estado(url_actual, actual)
        except OSError:
            return ultima_url
        return actual
    return ultima_url


def enrutar(argv: list[str] | None = None) -> int | None:
    """Si el ejecutable se lanzo con --video, corre el reproductor y devuelve su codigo.

    None si no es una ejecucion del reproductor: el arranque sigue con la aplicacion
    normal. Va antes de importar nada de Qt (empaquetado/arranque.py y app.main).
    """
    argumentos = list(sys.argv[1:] if argv is None else argv)
    if ARGUMENTO not in argumentos:
        return None
    argumentos.remove(ARGUMENTO)
    return main(argumentos)


def leer_argumentos(argv: list[str]) -> argparse.Namespace:
    analizador = argparse.ArgumentParser(prog="farmadex.video", add_help=False)
    analizador.add_argument("url")
    analizador.add_argument("--estado", required=True)
    analizador.add_argument("--padre", type=int, default=0)
    analizador.add_argument("--datos", default="")
    analizador.add_argument("--ancho", type=int, default=640)
    analizador.add_argument("--alto", type=int, default=360)
    return analizador.parse_args(argv)


def escribir_estado(ruta: str | Path, texto: str) -> None:
    """Deja el estado en el fichero de una vez (primero a uno temporal y luego se renombra),
    para que Farmadex nunca lea una linea a medias."""
    ruta = Path(ruta)
    temporal = temporal_de(ruta)
    temporal.write_text(texto, encoding="utf-8")
    reemplazar(temporal, ruta)


def proceso_vivo(pid: int) -> bool:
    """Si el proceso sigue vivo (Windows: OpenProcess + GetExitCodeProcess)."""
    if pid <= 0:
        return True
    kernel32 = ctypes.windll.kernel32
    manejador = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not manejador:
        return False
    try:
        codigo = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(manejador, ctypes.byref(codigo)):
            return False
        return codigo.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(manejador)


def hwnd_de(ventana) -> int:
    """El HWND de la ventana de pywebview (su Form de WinForms), o 0 si aun no existe."""
    nativa = getattr(ventana, "native", None)
    if nativa is None:
        return 0
    try:
        return int(nativa.Handle.ToInt64())
    except Exception:  # noqa: BLE001 - WinForms todavia sin handle
        return 0


def main(argv: list[str]) -> int:
    args = leer_argumentos(argv)
    try:
        import webview
    except Exception as error:  # noqa: BLE001 - sin pywebview no hay reproductor
        escribir_estado(args.estado, f"ERROR sin_pywebview {error}")
        return 2

    ordenes, url_actual = rutas_auxiliares(args.estado)
    try:
        # Un enlace que pide ventana nueva se abre en la misma vista, no en el navegador.
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    except Exception:  # noqa: BLE001 - version de pywebview sin ese ajuste
        pass
    ventana = webview.create_window(
        TITULO, args.url, width=args.ancho, height=args.alto, x=-32000, y=-32000,
        frameless=True, easy_drag=False, hidden=True, focus=True, background_color="#000000",
    )

    def al_arrancar() -> None:
        limite = time.monotonic() + ESPERA_VENTANA_S
        hwnd = 0
        while not hwnd and time.monotonic() < limite:
            time.sleep(0.1)
            hwnd = hwnd_de(ventana)
        if not hwnd:
            escribir_estado(args.estado, "ERROR sin_ventana")
            ventana.destroy()
            return
        escribir_estado(args.estado, f"HWND {hwnd}")
        # Sin Farmadex no tiene sentido seguir: nadie ensena esta ventana. Mientras tanto,
        # las ordenes del panel (Atras, Recargar) y la direccion que se esta viendo.
        ultima_url, siguiente_vigilancia = "", 0.0
        while True:
            ahora = time.monotonic()
            if ahora >= siguiente_vigilancia:
                if not proceso_vivo(args.padre):
                    break
                siguiente_vigilancia = ahora + VIGILANCIA_S
            ultima_url = atender(ventana, ordenes, url_actual, ultima_url)
            time.sleep(ORDENES_S)
        ventana.destroy()

    try:
        # pywebview corre `al_arrancar` en un hilo suyo en cuanto arranca el bucle.
        webview.start(al_arrancar, gui="edgechromium", private_mode=False, storage_path=args.datos or None)
    except Exception as error:  # noqa: BLE001 - sin WebView2 (Windows sin Edge Runtime...)
        escribir_estado(args.estado, f"ERROR sin_webview2 {error}")
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover - proceso hijo
    raise SystemExit(main(sys.argv[1:]))
