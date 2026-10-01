"""Historial de lo mirado en el chat: objeto, precio, hora y quien lo escribio.

APAGADO por defecto: guarda nombres de otros jugadores. Solo en este PC (un fichero de
texto en la carpeta de datos de Farmadex), nunca sale a internet, y se borra entero con
un boton. Una linea JSON por consulta; se recorta a las ultimas `MAXIMO` al escribir.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..registro_log import obtener

log = obtener("chat.historial")

FICHERO = "historial_chat.jsonl"
MAXIMO = 2000


def ruta_por_defecto() -> Path:
    from ..config import DIR_DATOS

    return DIR_DATOS / FICHERO


class HistorialChat:
    def __init__(self, ruta: Path | None = None, activo: bool = False):
        self.ruta = Path(ruta) if ruta else ruta_por_defecto()
        self.activo = bool(activo)
        self._cerrojo = threading.Lock()
        self._lineas_desde_recorte = 0

    def apuntar(self, objeto: str, slug: str | None, precio: str, usuario: str = "",
                cuando: datetime | None = None) -> bool:
        """Guarda una consulta si el historial esta encendido. Devuelve si se guardo."""
        if not self.activo:
            return False
        fila = {
            "hora": (cuando or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds"),
            "objeto": objeto,
            "slug": slug,
            "precio": precio,
            "usuario": usuario or "",
        }
        try:
            with self._cerrojo:
                self.ruta.parent.mkdir(parents=True, exist_ok=True)
                with self.ruta.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(fila, ensure_ascii=False) + "\n")
                self._lineas_desde_recorte += 1
                if self._lineas_desde_recorte >= 200:
                    self._recortar()
            return True
        except OSError as e:
            log.warning("No se pudo guardar el historial del chat: %s", e)
            return False

    def _recortar(self) -> None:
        self._lineas_desde_recorte = 0
        try:
            lineas = self.ruta.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lineas) > MAXIMO:
            self.ruta.write_text("\n".join(lineas[-MAXIMO:]) + "\n", encoding="utf-8")

    def leer(self, limite: int = 200) -> list[dict]:
        """Las ultimas consultas, la mas reciente primero."""
        try:
            lineas = self.ruta.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        salida = []
        for linea in reversed(lineas[-limite:]):
            try:
                salida.append(json.loads(linea))
            except json.JSONDecodeError:
                continue
        return salida

    def borrar(self) -> bool:
        """Borra el fichero entero. True si no queda nada."""
        with self._cerrojo:
            try:
                self.ruta.unlink(missing_ok=True)
                return True
            except OSError as e:
                log.warning("No se pudo borrar el historial del chat: %s", e)
                return False
