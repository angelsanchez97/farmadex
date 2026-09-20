"""Rutas, constantes y fichero de configuracion del usuario."""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import NOMBRE_APP, URL_CONTACTO, VERSION

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
    "tema": "vacio",
    "diseno_mundo": "lista",
    "overlay_geometria": None,
    # Vista compacta para el directo: cual se usaba y su propia posicion y tamano.
    "overlay_modo": "completo",
    "overlay_geometria_compacto": None,
    "ocultar_vaulted": False,
    "ocr_reliquias_auto": True,
    "motor_ocr": "rapidocr",
    "plataforma": PLATAFORMA,
    # "auto" = el idioma de Windows si lo tenemos traducido; si no, espanol.
    "idioma_ui": "auto",
    "comprobar_actualizaciones_app": True,
    "carpeta_actualizaciones": str(DIR_ACTUALIZACIONES),
    "ruta_eelog": str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Warframe" / "EE.log"),
}


def crear_carpetas() -> None:
    for carpeta in (DIR_BASE, DIR_DATOS, DIR_IMG, DIR_DB, DIR_LOGS, DIR_ACTUALIZACIONES):
        carpeta.mkdir(parents=True, exist_ok=True)


def cargar() -> dict:
    """Devuelve la configuracion, completando con los valores por defecto."""
    crear_carpetas()
    datos = {}
    if RUTA_CONFIG.exists():
        try:
            datos = json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            datos = {}
    config = dict(POR_DEFECTO)
    config.update({c: v for c, v in datos.items() if c in POR_DEFECTO})
    if datos != config:
        guardar(config)
    return config


def guardar(config: dict) -> None:
    crear_carpetas()
    tmp = RUTA_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(RUTA_CONFIG)
