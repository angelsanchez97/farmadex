"""Segundo constructor de `Perfil`: a partir de lo leido por OCR en las pantallas del juego.

El JSON de perfil de DE devuelve 403, asi que la maestria se lee de Perfil >
Equipamiento con OCR (`captura/perfil_equipo.py`). Este modulo no sabe de
imagenes: recibe lecturas ya interpretadas (unique_name, rango, estado) y produce
el mismo `Perfil` que entiende `almacen.guardar`, con `origen="ocr"` para que el
almacen FUSIONE en vez de sustituir: hoy las armas, manana las warframes.

La XP es sintetica (`maestria.xp_sintetica`): la minima que corresponde al rango
leido. Basta para "dominado / a medias" y `rango_actual` la invierte exacta.
Lo desconocido no entra en la XP: se registra aparte para que la interfaz y la
herramienta de consola puedan decir "visto pero sin leer" en vez de adivinar.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import almacen, maestria
from .lector import EntradaXP, Perfil


@dataclass(frozen=True)
class LecturaOCR:
    unique_name: str
    rango: int | None
    estado: str  # maestria.DOMINADO / A_MEDIAS / DESCONOCIDO
    confianza: float = 0.0
    nombre: str = ""
    pantalla: str = ""  # categoria del juego en la que se vio (Warframes, Primarias...)

    @property
    def conocida(self) -> bool:
        return self.estado in (maestria.DOMINADO, maestria.A_MEDIAS) and self.rango is not None


@dataclass
class ResultadoEscaneo:
    perfil: Perfil
    lecturas: list[LecturaOCR]
    guardadas: int  # objetos con rango que han entrado en el perfil
    desconocidas: list[LecturaOCR]


def desde_tarjetas(tarjetas, pantalla: str = "") -> list[LecturaOCR]:
    """Convierte las `Tarjeta` de `captura.perfil_equipo` (o cualquier objeto con los
    mismos atributos) en lecturas planas. Las que el catalogo dice que no dan
    maestria se descartan."""
    salida = []
    for t in tarjetas:
        if t.estado == maestria.NO_APLICA:
            continue
        salida.append(
            LecturaOCR(
                unique_name=t.unique_name,
                rango=t.rango if t.estado != maestria.DESCONOCIDO else None,
                estado=t.estado,
                confianza=float(getattr(t, "confianza_rango", 0.0) or 0.0),
                nombre=t.nombre,
                pantalla=pantalla,
            )
        )
    return salida


def fusionar_lecturas(lecturas) -> dict[str, LecturaOCR]:
    """Una lectura por objeto. Una conocida siempre gana a una desconocida; entre dos
    conocidas gana la de mas confianza y, a igualdad, la de rango mas alto (el rango
    de un objeto solo puede subir)."""
    mejor: dict[str, LecturaOCR] = {}
    for l in lecturas:
        actual = mejor.get(l.unique_name)
        if actual is None or _clave(l) > _clave(actual):
            mejor[l.unique_name] = l
    return mejor


def _clave(l: LecturaOCR) -> tuple:
    return (l.conocida, round(l.confianza, 2), l.rango or -1)


def construir(
    lecturas,
    indice: sqlite3.Connection,
    rango_maestria: int | None = None,
    nombre: str | None = None,
) -> Perfil:
    """El `Perfil` equivalente a lo leido. Solo las lecturas con rango aportan XP."""
    xp: list[EntradaXP] = []
    for l in fusionar_lecturas(lecturas).values():
        if not l.conocida:
            continue
        umbral = _umbral(indice, l.unique_name)
        if umbral is None:
            continue
        xp.append(EntradaXP(l.unique_name, maestria.xp_sintetica(l.rango, umbral)))
    xp.sort(key=lambda e: e.item_type)
    return Perfil(
        nombre=nombre or "",
        account_id=None,
        rango=int(rango_maestria or 0),
        creado=None,
        clan=None,
        clan_nivel=None,
        plataformas=[],
        operador_desbloqueado=None,
        xp=xp,
        nodos=[],
        intrinsecos={},
        sindicatos=[],
        reputacion_diaria={},
        desafios={},
        estadisticas={},
        origen="ocr",
    )


def guardar(
    usuario: sqlite3.Connection,
    indice: sqlite3.Connection,
    lecturas,
    rango_maestria: int | None = None,
    nombre: str | None = None,
    completados: dict[str, tuple[int, int]] | None = None,
) -> ResultadoEscaneo:
    """Construye el perfil, lo fusiona con lo ya guardado y registra cada lectura.

    `completados` es el contador "COMPLETADO x/y" leido por categoria de pantalla;
    se guarda en perfil_meta (clave `ocr_completado`) para que la interfaz pueda
    ensenar la cifra del juego junto a la del OCR.
    """
    lecturas = list(lecturas)
    perfil = construir(lecturas, indice, rango_maestria, nombre)
    almacen.guardar(usuario, perfil)
    almacen.registrar_lecturas_ocr(usuario, fusionar_lecturas(lecturas).values())
    if completados:
        almacen.guardar_completados_ocr(usuario, completados)
    desconocidas = [l for l in fusionar_lecturas(lecturas).values() if not l.conocida]
    return ResultadoEscaneo(perfil, lecturas, len(perfil.xp), desconocidas)


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _umbral(indice: sqlite3.Connection, unique_name: str) -> int | None:
    fila = indice.execute(
        "SELECT categoria, tipo, nombre_en FROM items WHERE unique_name = ?", (unique_name,)
    ).fetchone()
    if fila is None:
        return None
    return maestria.umbral_xp(fila[0], fila[1], fila[2], unique_name)
