"""Historial de la sesion: lo que el OCR lee y lo que EE.log cuenta, y el resumen del dia.

Dos fuentes, dos tablas de `usuario.sqlite`:

- `historial_recompensas`: cada lectura de la pantalla de recompensas, con la hora,
  las 1-4 piezas (JSON) y lo que dijo el comparador (cual convenia y cuanto valia).
- `historial_eventos`: los eventos de EE.log que cuentan algo del dia, hoy
  `reliquia_abierta` y `mision_completada`.

Sobre el valor: el juego NO escribe en EE.log que recompensa se llevo el usuario,
asi que el valor del dia es una **estimacion**: se da por hecho que eligio la que
el comparador recomendo, salvo que la interfaz llame a `marcar_elegida`. El
resumen lo dice (`valor_estimado`) y la plantilla de OBS trae el aviso por defecto.

Exportacion para OBS: `exportar_obs` escribe un fichero de texto plano que una
fuente "Texto (GDI+)" de OBS puede leer con "Leer desde fichero". La plantilla es
un `str.format` con los huecos de `HUECOS`; los huecos desconocidos se dejan tal
cual en vez de romper. Se escribe en un temporal y se renombra encima, para que
OBS no lea nunca un fichero a medias.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from ..config import DIR_BASE
from ..idiomas import t
from ..registro_log import obtener
from ..ficheros import reemplazar

log = obtener("historial")

EVENTOS_QUE_CUENTAN = ("reliquia_abierta", "mision_completada")

RUTA_OBS_POR_DEFECTO = DIR_BASE / "obs_sesion.txt"

PLANTILLA_OBS = (
    "Reliquias: {reliquias} | Misiones: {misiones} | "
    "Valor: ~{platino}p / {ducados} ducados | Ultima: {ultima}"
)

HUECOS = (
    "reliquias",  # reliquias abiertas segun EE.log (o lecturas si EE.log no dio nada)
    "misiones",  # misiones completadas
    "lecturas",  # veces que se leyo la pantalla
    "platino",  # valor total estimado en platino (entero)
    "ducados",  # ducados totales de lo elegido/recomendado
    "ultima",  # ultima pieza (nombre) o "-"
    "caidas",  # "Pieza x2, Otra x1"
    "objetivos",  # piezas que cubrian un objetivo
    "hora",  # hora de la exportacion HH:MM
    "fecha",  # dia del resumen
    "estimado",  # "~" si el valor es estimado, "" si no
)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Caida:
    unique_name: str
    nombre: str
    veces: int
    valor: float = 0.0


@dataclass
class ResumenDia:
    fecha: date
    reliquias_abiertas: int = 0
    misiones: int = 0
    lecturas: int = 0
    valor_platino: float = 0.0
    ducados: int = 0
    valor_estimado: bool = False  # True si alguna lectura no tiene elegida confirmada
    sin_valorar: int = 0  # lecturas cuyo mejor no tenia valor
    caidas: list[Caida] = field(default_factory=list)
    objetivos: list[str] = field(default_factory=list)
    ultima: str = ""
    ultima_hora: str = ""

    def como_dict(self) -> dict:
        return {
            "fecha": self.fecha.isoformat(),
            "reliquias_abiertas": self.reliquias_abiertas,
            "misiones": self.misiones,
            "lecturas": self.lecturas,
            "valor_platino": round(self.valor_platino, 1),
            "ducados": self.ducados,
            "valor_estimado": self.valor_estimado,
            "sin_valorar": self.sin_valorar,
            "caidas": [c.__dict__ for c in self.caidas],
            "objetivos": self.objetivos,
            "ultima": self.ultima,
            "ultima_hora": self.ultima_hora,
        }


# -- escritura -----------------------------------------------------------------


def registrar_lectura(
    usuario: sqlite3.Connection, recompensas: list, veredicto=None, leido_en: str | None = None
) -> int:
    """Guarda una lectura de la pantalla. `recompensas` son `captura.reliquias.Recompensa`."""
    items = []
    for r in recompensas:
        items.append(
            {
                "unique_name": getattr(r, "unique_name", "") or "",
                "nombre": r.nombre,
                "texto_ocr": getattr(r, "texto_ocr", ""),
                "platino": getattr(r, "platino", None),
                "ducados": getattr(r, "ducados", None),
                "rareza": getattr(r, "rareza", None),
                "objetivo": getattr(r, "objetivo", ""),
                "valor": getattr(r, "valor", None),
                "mejor": bool(getattr(r, "mejor", False)),
                "nota": getattr(r, "nota", ""),
            }
        )
    mejor = next((i for i in items if i["mejor"]), None)
    if mejor is None and veredicto is not None and getattr(veredicto, "mejor", None) is not None:
        if 0 <= veredicto.mejor < len(items):
            mejor = items[veredicto.mejor]
            mejor["mejor"] = True
    cursor = usuario.execute(
        "INSERT INTO historial_recompensas (leido_en, textos_ocr, items_json, elegido_unique_name, "
        "mejor_unique_name, valor_platino, ducados) VALUES (?, ?, ?, NULL, ?, ?, ?)",
        (
            leido_en or _ahora(),
            " | ".join(i["texto_ocr"] or i["nombre"] for i in items),
            json.dumps(items, ensure_ascii=False),
            mejor["unique_name"] if mejor else None,
            mejor["valor"] if mejor else None,
            mejor["ducados"] if mejor else None,
        ),
    )
    usuario.commit()
    return cursor.lastrowid


def marcar_elegida(usuario: sqlite3.Connection, lectura_id: int, unique_name: str) -> bool:
    """La interfaz sabe (porque el usuario lo dijo) que se llevo esta pieza: el valor deja de ser estimado."""
    fila = usuario.execute(
        "SELECT items_json FROM historial_recompensas WHERE id = ?", (lectura_id,)
    ).fetchone()
    if not fila:
        return False
    items = json.loads(fila[0])
    elegido = next((i for i in items if i["unique_name"] == unique_name), None)
    usuario.execute(
        "UPDATE historial_recompensas SET elegido_unique_name = ?, valor_platino = ?, ducados = ? "
        "WHERE id = ?",
        (
            unique_name,
            elegido["valor"] if elegido else None,
            elegido["ducados"] if elegido else None,
            lectura_id,
        ),
    )
    usuario.commit()
    return True


def registrar_evento(
    usuario: sqlite3.Connection, evento: str, ocurrido_en: str | None = None
) -> int | None:
    """Apunta un evento de EE.log si es de los que cuentan; los demas se ignoran."""
    if evento not in EVENTOS_QUE_CUENTAN:
        return None
    cursor = usuario.execute(
        "INSERT INTO historial_eventos (evento, ocurrido_en) VALUES (?, ?)",
        (evento, ocurrido_en or _ahora()),
    )
    usuario.commit()
    return cursor.lastrowid


# -- lectura -------------------------------------------------------------------


def _rango_dia(dia: date) -> tuple[str, str]:
    return f"{dia.isoformat()}T00:00:00", f"{dia.isoformat()}T23:59:59"


def resumen_dia(usuario: sqlite3.Connection, dia: date | None = None) -> ResumenDia:
    dia = dia or date.today()
    desde, hasta = _rango_dia(dia)
    resumen = ResumenDia(fecha=dia)

    for evento, n in usuario.execute(
        "SELECT evento, COUNT(*) FROM historial_eventos WHERE ocurrido_en BETWEEN ? AND ? "
        "GROUP BY evento",
        (desde, hasta),
    ):
        if evento == "reliquia_abierta":
            resumen.reliquias_abiertas = n
        elif evento == "mision_completada":
            resumen.misiones = n

    filas = usuario.execute(
        "SELECT leido_en, items_json, elegido_unique_name, mejor_unique_name, valor_platino, ducados "
        "FROM historial_recompensas WHERE leido_en BETWEEN ? AND ? ORDER BY leido_en",
        (desde, hasta),
    ).fetchall()
    resumen.lecturas = len(filas)
    if not resumen.reliquias_abiertas:
        # Sin EE.log (atajo manual, o el juego no escribio) se cuenta lo que se leyo.
        resumen.reliquias_abiertas = resumen.lecturas

    contador: Counter[str] = Counter()
    nombres: dict[str, str] = {}
    valores: dict[str, float] = {}
    for leido_en, items_json, elegido, mejor, valor, ducados in filas:
        items = json.loads(items_json)
        clave = elegido or mejor
        pieza = next((i for i in items if i["unique_name"] == clave), None) if clave else None
        if elegido is None:
            resumen.valor_estimado = True
        if pieza is None:
            resumen.sin_valorar += 1
            continue
        if valor is None:
            resumen.sin_valorar += 1
        else:
            resumen.valor_platino += float(valor)
        resumen.ducados += int(ducados or 0)
        identificador = pieza["unique_name"] or pieza["nombre"]
        contador[identificador] += 1
        nombres[identificador] = pieza["nombre"]
        valores[identificador] = valores.get(identificador, 0.0) + float(valor or 0)
        if pieza.get("objetivo"):
            resumen.objetivos.append(pieza["nombre"])
        resumen.ultima = pieza["nombre"]
        resumen.ultima_hora = leido_en[11:16]

    resumen.caidas = [
        Caida(u, nombres[u], n, round(valores[u], 1)) for u, n in contador.most_common()
    ]
    return resumen


# -- exportacion para OBS ------------------------------------------------------


class _HuecosSeguros(dict):
    """Un hueco que no existe se deja escrito tal cual, en vez de tirar la exportacion."""

    def __missing__(self, clave: str) -> str:
        return "{" + clave + "}"


def valores_plantilla(resumen: ResumenDia, ahora: datetime | None = None) -> dict[str, str]:
    ahora = ahora or datetime.now()
    caidas = ", ".join(
        f"{c.nombre} x{c.veces}" if c.veces > 1 else c.nombre for c in resumen.caidas
    )
    return {
        "reliquias": str(resumen.reliquias_abiertas),
        "misiones": str(resumen.misiones),
        "lecturas": str(resumen.lecturas),
        "platino": str(int(round(resumen.valor_platino))),
        "ducados": str(resumen.ducados),
        "ultima": resumen.ultima or "-",
        "caidas": caidas or "-",
        "objetivos": ", ".join(resumen.objetivos) or "-",
        "hora": ahora.strftime("%H:%M"),
        "fecha": resumen.fecha.isoformat(),
        "estimado": "~" if resumen.valor_estimado else "",
    }


def renderizar(resumen: ResumenDia, plantilla: str = PLANTILLA_OBS, ahora: datetime | None = None) -> str:
    try:
        return plantilla.format_map(_HuecosSeguros(valores_plantilla(resumen, ahora)))
    except (ValueError, IndexError) as e:
        # Llaves sin cerrar o huecos posicionales: se avisa y se usa la plantilla por defecto.
        log.warning("Plantilla de OBS mal formada (%s); se usa la plantilla por defecto", e)
        return PLANTILLA_OBS.format_map(_HuecosSeguros(valores_plantilla(resumen, ahora)))


def exportar_obs(
    resumen: ResumenDia, ruta: Path | str = RUTA_OBS_POR_DEFECTO, plantilla: str = PLANTILLA_OBS
) -> Path:
    """Escribe el texto para OBS de forma atomica (temporal + renombrado)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    texto = renderizar(resumen, plantilla)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    reemplazar(tmp, ruta)
    return ruta


# -- pegamento -----------------------------------------------------------------


class Sesion:
    """Une las dos fuentes con el resumen y la exportacion, sin Qt: la interfaz llama.

    - `evento(nombre)` con cada evento de `VigilanteEELog`.
    - `lectura(recompensas, veredicto)` con cada `ServicioComparador.veredicto`.
    Tras cada cambio se reexporta el fichero de OBS si `ruta_obs` esta puesta.
    """

    def __init__(
        self,
        usuario: sqlite3.Connection,
        ruta_obs: Path | str | None = None,
        plantilla: str = PLANTILLA_OBS,
    ):
        self.usuario = usuario
        self.ruta_obs = Path(ruta_obs) if ruta_obs else None
        self.plantilla = plantilla
        self.ultima_lectura_id: int | None = None

    def evento(self, nombre: str) -> None:
        if registrar_evento(self.usuario, nombre) is not None:
            self.exportar()

    def lectura(self, recompensas: list, veredicto=None) -> int | None:
        if not recompensas:
            return None
        self.ultima_lectura_id = registrar_lectura(self.usuario, recompensas, veredicto)
        self.exportar()
        return self.ultima_lectura_id

    def elegida(self, unique_name: str) -> None:
        if self.ultima_lectura_id is not None:
            marcar_elegida(self.usuario, self.ultima_lectura_id, unique_name)
            self.exportar()

    def resumen(self, dia: date | None = None) -> ResumenDia:
        return resumen_dia(self.usuario, dia)

    def exportar(self) -> Path | None:
        if self.ruta_obs is None:
            return None
        try:
            return exportar_obs(self.resumen(), self.ruta_obs, self.plantilla)
        except OSError as e:
            log.warning("No se pudo escribir el fichero de OBS %s: %s", self.ruta_obs, e)
            return None


def texto_resumen(resumen: ResumenDia) -> str:
    """Resumen legible en varias lineas, para la consola y la barra de estado."""
    if resumen.lecturas != resumen.reliquias_abiertas:
        reliquias = t(
            "Reliquias abiertas: {n} (lecturas OCR: {m})", n=resumen.reliquias_abiertas, m=resumen.lecturas
        )
    else:
        reliquias = t("Reliquias abiertas: {n}", n=resumen.reliquias_abiertas)
    platino, ducados = int(round(resumen.valor_platino)), resumen.ducados
    if resumen.valor_estimado:
        valor = t("Valor estimado: {n} platino, {d} ducados", n=platino, d=ducados)
    else:
        valor = t("Valor: {n} platino, {d} ducados", n=platino, d=ducados)
    lineas = [
        t("Dia {fecha}", fecha=resumen.fecha.isoformat()),
        reliquias,
        t("Misiones completadas: {n}", n=resumen.misiones),
        valor,
    ]
    if resumen.sin_valorar:
        lineas.append(t("Lecturas sin valorar: {n}", n=resumen.sin_valorar))
    if resumen.caidas:
        lineas.append(t("Ha caido:"))
        for c in resumen.caidas:
            lineas.append(f"  {c.nombre} x{c.veces} (~{c.valor:.0f}p)")
    if resumen.objetivos:
        lineas.append(t("Para objetivos: {nombres}", nombres=", ".join(resumen.objetivos)))
    return "\n".join(lineas)
