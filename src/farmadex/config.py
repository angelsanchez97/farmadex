"""Rutas, constantes y fichero de configuracion del usuario."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from . import NOMBRE_APP, URL_CONTACTO, VERSION
from .ficheros import reemplazar

USER_AGENT = f"{NOMBRE_APP}/{VERSION} (+{URL_CONTACTO})" if URL_CONTACTO else f"{NOMBRE_APP}/{VERSION}"

PLATAFORMA = "pc"


def _base_datos_usuario() -> Path:
    raiz = os.environ.get("FARMADEX_DATOS") or os.environ.get("LOCALAPPDATA")
    if not raiz:
        raiz = str(Path.home() / ".local" / "share")
    return Path(raiz) / NOMBRE_APP


DIR_BASE = _base_datos_usuario()
DIR_DATOS = DIR_BASE / "datos"
DIR_IMG = DIR_DATOS / "img"
DIR_DB = DIR_BASE / "db"
DIR_LOGS = DIR_BASE / "logs"
RUTA_CONFIG = DIR_BASE / "config.json"
RUTA_INDICE = DIR_DB / "indice.sqlite"
RUTA_USUARIO_DB = DIR_DB / "usuario.sqlite"
RUTA_ESTADO_DATOS = DIR_DATOS / "estado_datos.json"
# Aqui se dejan las compilaciones nuevas mientras el proyecto no este publicado.
DIR_ACTUALIZACIONES = DIR_BASE / "actualizaciones"

DIR_RECURSOS = Path(__file__).resolve().parent / "datos"

POR_DEFECTO = {
    "hotkey_overlay": "Ctrl+Alt+W",
    "hotkey_cursor": "Ctrl+Alt+Q",
    "hotkey_reliquias": "Ctrl+Alt+R",
    "overlay_opacidad": 0.94,
    "tema": "orokin",
    "diseno_mundo": "lista",
    "overlay_geometria": None,
    # Vista compacta para el directo: cual se usaba y su propia posicion y tamano.
    "overlay_modo": "completo",
    "overlay_geometria_compacto": None,
    "ocultar_vaulted": False,
    "ocr_reliquias_auto": True,
    # Como se ensenan las recompensas de reliquia: "etiquetas" (pequenas, junto a cada
    # tarjeta) o "panel" (una tarjeta por recompensa bajo las del juego, con miniatura).
    "estilo_recompensas": "etiquetas",
    # Que destacar en esas recompensas (captura/prioridad.py): "me_falta", "platino",
    # "ducados" o "equilibrado" (el criterio de antes de existir el ajuste).
    "prioridad_recompensas": "me_falta",
    # Lectura pasiva de las pantallas del menu (captura + OCR solo con el juego delante).
    "perfil_pasivo": True,
    "inventario_pasivo": False,  # sin calibrar con capturas del usuario: apagado
    # Botin deducido de EE.log (recompensa de reliquia en misiones en solitario).
    "botin_eelog_auto": True,
    # Arranque con Windows (HKCU\...\Run), escondido en la bandeja. Apagado por defecto.
    "iniciar_con_windows": False,
    "motor_ocr": "rapidocr",
    "plataforma": PLATAFORMA,
    # Guia de uso guiada dentro de la ventana: si ya se vio (o se salto), no vuelve a
    # lanzarse sola. El boton "Guia" siempre la relanza aunque esto sea True.
    "guia_vista": False,
    # Aviso discreto ("Nuevo: guia de uso") para quien ya tenia Farmadex instalado antes
    # de esta funcion: se ensena una sola vez y no vuelve, aunque no haga la guia.
    "guia_aviso_visto": False,
    # "auto" = el idioma de Windows si lo tenemos traducido; si no, espanol.
    "idioma_ui": "auto",
    # Ritmo de juego: multiplica las duraciones estimadas de las misiones (no las
    # probabilidades). "rapido" x0.7, "normal" x1, "tranquilo" x1.4 (datos/eficiencia.py).
    "ritmo_juego": "normal",
    "comprobar_actualizaciones_app": True,
    # Descargar la version nueva sola e instalarla al cerrar Farmadex (o al pulsar
    # "Reiniciar y actualizar"). Apagado, solo se avisa con el enlace de descarga.
    "actualizar_automaticamente": True,
    "carpeta_actualizaciones": str(DIR_ACTUALIZACIONES),
    "ruta_eelog": str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Warframe" / "EE.log"),
}


def crear_carpetas() -> None:
    for carpeta in (DIR_BASE, DIR_DATOS, DIR_IMG, DIR_DB, DIR_LOGS, DIR_ACTUALIZACIONES):
        carpeta.mkdir(parents=True, exist_ok=True)


# Todos los que piden la configuracion comparten el mismo diccionario.
#
# Antes cada uno se hacia su copia -- la ventana, la pestana de Ajustes y el
# buscador --, y como al guardar se escribe el fichero entero, el ultimo en
# escribir borraba los cambios de los demas. En la practica: elegias un tema,
# cerrabas el programa, la ventana guardaba su posicion con el tema de antes, y
# al volver a abrir estaba todo como al principio.
_compartida: tuple[Path, dict] | None = None
# El diccionario lo tocan varios hilos (la ventana, los comprobadores de version,
# el buscador): sin cerrojo, dos `guardar` a la vez escribian el mismo .tmp y el
# `replace` del segundo fallaba en Windows, o json.dumps se encontraba el
# diccionario cambiando de tamano a mitad de recorrido. Reentrante porque
# `cargar` llama a `guardar`.
_cerrojo = threading.RLock()


def cargar(recargar: bool = False) -> dict:
    """Devuelve la configuracion, completando con los valores por defecto.

    Siempre el mismo diccionario mientras no cambie el fichero de destino, para
    que un cambio hecho desde Ajustes lo vea tambien quien guarde despues.
    """
    global _compartida
    with _cerrojo:
        if not recargar and _compartida is not None and _compartida[0] == RUTA_CONFIG:
            return _compartida[1]

        crear_carpetas()
        datos = {}
        if RUTA_CONFIG.exists():
            try:
                datos = json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                datos = {}
        if not isinstance(datos, dict):
            datos = {}
        config = dict(POR_DEFECTO)
        config.update({c: v for c, v in datos.items() if c in POR_DEFECTO})
        _compartida = (RUTA_CONFIG, config)
        if datos != config:
            guardar(config)
        return config


def guardar(config: dict) -> None:
    global _compartida
    with _cerrojo:
        crear_carpetas()
        # Copia bajo el cerrojo: lo que se escribe es una foto coherente aunque
        # otro hilo siga tocando el diccionario compartido.
        texto = json.dumps(dict(config), indent=2, ensure_ascii=False)
        tmp = RUTA_CONFIG.with_suffix(".tmp")
        tmp.write_text(texto, encoding="utf-8")
        reemplazar(tmp, RUTA_CONFIG)
        if _compartida is not None and _compartida[1] is not config:
            # Alguien ha guardado un diccionario suyo: lo que hubiera en memoria ya no
            # vale, y la proxima lectura vuelve al fichero.
            _compartida = None
