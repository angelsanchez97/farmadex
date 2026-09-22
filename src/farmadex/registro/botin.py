"""Botin que se puede deducir de EE.log al terminar una mision, sin OCR.

Lo que el log real (septiembre de 2026) SI trae y lo que NO:

- NO trae las recompensas de mision ni de rotacion, ni los recursos recogidos
  por el suelo: `EndOfMatch.lua: Mission Succeeded` solo dice que termino bien.
  Las cantidades del inventario hay que leerlas en pantalla (captura/inventario.py).
- SI trae, al abrirse la pantalla de reliquias, una linea por reliquia abierta:
  `VoidProjections: <id> gets reward /Lotus/StoreItems/...` con el objeto exacto.
  Pero no dice cual es la del propio jugador, y en escuadra no siempre salen todas.
- SI trae, al cargar la mision, cuantos jugadores remotos hay:
  `Progress.lua: Num remote players 0`.

De ahi la regla, deliberadamente estrecha: solo cuando la mision es en solitario
(0 remotos) y ha salido exactamente UNA linea "gets reward" se da por seguro que
esa es la recompensa que el jugador se lleva, y se suma al objetivo que la pida.
En escuadra la eleccion se sigue leyendo por OCR y, cuando haga falta, la marca
el usuario. Todo esto se apaga desde Ajustes (`botin_eelog_auto`).
"""

from __future__ import annotations

from typing import Callable

from ..registro_log import obtener

log = obtener("botin")

Sumar = Callable[[str, int, str], object]  # (unique_name, cantidad, origen)


class Botin:
    """Sigue los eventos y pistas de `VigilanteEELog` y suma lo que sea seguro.

    `sumar(unique_name, cantidad, origen)` es lo que se llama con cada botin
    seguro; devuelve lo que quiera (normalmente el objetivo actualizado o None).
    """

    ORIGEN = "eelog"

    def __init__(self, sumar: Sumar, activo: bool = True):
        self.sumar = sumar
        self.activo = activo
        self.remotos: int | None = None  # jugadores remotos de la mision en curso
        self._candidatas: list[str] = []
        self._abierta = False
        self.ultimo: str | None = None  # ultimo unique_name sumado

    def evento(self, nombre: str) -> str | None:
        """Devuelve el unique_name sumado cuando `reliquia_elegida` cierra una
        recompensa segura; None en cualquier otro caso."""
        if nombre == "reliquia_abierta":
            self._candidatas = []
            self._abierta = True
        elif nombre == "reliquia_elegida":
            aplicado = self._aplicar()
            self._abierta = False
            self._candidatas = []
            return aplicado
        elif nombre == "reliquia_cerrada":
            self._abierta = False
            self._candidatas = []
        return None

    def pista(self, tipo: str, valor: str) -> None:
        if tipo == "remotos":
            try:
                self.remotos = int(valor)
            except ValueError:
                self.remotos = None
        elif tipo == "recompensa" and self._abierta:
            self._candidatas.append(valor)

    def _aplicar(self) -> str | None:
        if not self.activo or not self._candidatas:
            return None
        if self.remotos is None:
            log.info("Recompensa de reliquia en el log, pero sin saber si ibas solo: no se suma")
            return None
        if self.remotos > 0 or len(self._candidatas) != 1:
            log.info(
                "Recompensas de reliquia en el log (%d) con %d jugadores remotos: "
                "no se sabe cual es la tuya, la decide el OCR",
                len(self._candidatas), self.remotos,
            )
            return None
        ruta = self._candidatas[0]
        try:
            self.sumar(ruta, 1, self.ORIGEN)
        except Exception:  # noqa: BLE001 - un fallo aqui no puede parar el vigilante
            log.exception("No se pudo apuntar el botin %s", ruta)
            return None
        self.ultimo = ruta
        log.info("Botin seguro (mision en solitario): +1 %s", ruta)
        return ruta
