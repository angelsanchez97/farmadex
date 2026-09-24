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
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from pathlib import Path

ARGUMENTO = "--video"
TITULO = "Farmadex · Guia"
# Cada cuanto se mira si Farmadex sigue vivo, y cuanto se espera a que exista la ventana.
VIGILANCIA_S = 1.5
ESPERA_VENTANA_S = 20.0


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
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(texto, encoding="utf-8")
    os.replace(temporal, ruta)


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
        # Sin Farmadex no tiene sentido seguir: nadie ensena esta ventana.
        while proceso_vivo(args.padre):
            time.sleep(VIGILANCIA_S)
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
