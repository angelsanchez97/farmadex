"""Puntua las recompensas de una reliquia y marca la que conviene elegir.

Es la pieza que decide: `reliquias.py` lee la pantalla y deja 1-4 `Recompensa`;
aqui se les pone valor y se elige. El criterio, en orden:

1. **Objetivo pendiente.** Si una recompensa es una pieza que el usuario tiene en
   su lista y aun no ha completado, gana. Para eso se farmea.
2. **Valor en platino equivalente.** El mayor de dos numeros: el precio en
   warframe.market y los ducados a razon de `DUCADOS_POR_PLATINO`. Asi una pieza
   de 100 ducados que nadie compra por mas de 3p vale "10p en ducados", que es lo
   que un jugador hace con ella (guardarla para Baro).
3. **Rareza**, solo para desempatar o cuando no hay precio: rara > poco comun > comun.

Cuando no se sabe, se dice. Una recompensa sin precio y sin ducados queda como
"desconocida", el veredicto se marca `seguro=False` y la etiqueta lo explica; no
se inventa un numero. Lo unico que se da por valor cero es lo que el indice marca
como no comerciable y sin ducados (un plano de Forma), porque ahi si se sabe.

Escuadra de cuatro
------------------
El usuario abre reliquias en escuadra. En Warframe cada jugador puede elegir la
misma recompensa que los demas, asi que no hay competencia por la pieza: la
pregunta de "cual conviene sabiendo que los otros tres eligen" es de mercado.
Si los cuatro se llevan la rara, en un minuto hay cuatro copias mas en venta y el
precio que se consigue de verdad es el de quien vende mas barato ahora, no la
mediana. Por eso en modo escuadra el platino que cuenta es `mejor_venta` (el
vendedor mas barato que esta en el juego) y se avisa cuando el mercado es fino
(pocos vendedores). Los ducados y los objetivos no se devaluan por eso.

Tiempo
------
La recompensa se elige con una cuenta atras de unos 15 s. Medido el 2026-09-20
con `herramientas/comparar_reliquias.py ... --medir 3` (indice real, red domestica):

    espera animacion (DisparadorAutomatico.ESPERA_MS)   1500 ms
    captura + OCR RapidOCR de la franja                  600-1300 ms (medir_ocr.py)
    completar (indice + objetivos)                       0.0 ms (4 piezas)
    precios: ~290 ms por pieza con slug, en frio         572 ms con 2 slugs; 4 slugs ~1200 ms
             (limite del cliente: 2 peticiones/s)        1 ms con la cache de 10 min
    puntuar                                              0.02 ms
    ------------------------------------------------------------------
    total desde "Got rewards" hasta veredicto            ~3.5-4 s en frio, ~2.5 s con cache

Queda margen, pero por si la red se atasca `puntuar` lleva un plazo
(`PLAZO_PRECIOS_S`): cuando se agota deja de pedir precios y da el veredicto con
lo que tiene, marcando las que quedaron sin precio. Cada `Veredicto` trae sus
tiempos por fase en `tiempos_ms`, y se escriben en el log.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal, Slot

from ..idiomas import t
from ..registro_log import obtener
from .reliquias import Recompensa, completar

log = obtener("comparador")

# Un jugador no cambia un platino por menos de unos diez ducados (es el cambio
# implicito de las ofertas de Baro). Conservador a proposito.
DUCADOS_POR_PLATINO = 10
# Margen por debajo del cual dos valores se consideran empate.
EMPATE = 0.10
# Tiempo maximo dedicado a pedir precios antes de dar el veredicto con lo que haya.
PLAZO_PRECIOS_S = 6.0
# Con menos vendedores que esto, en escuadra el precio se cae al vender los cuatro.
MERCADO_FINO = 5

RAREZAS = {"Common": "comun", "Uncommon": "poco comun", "Rare": "rara"}
ORDEN_RAREZA = {"comun": 0, "poco comun": 1, "rara": 2}
# Los ducados delatan la rareza: 15/25 comun, 45/65 poco comun, 100 rara.
RAREZA_POR_DUCADOS = {15: "comun", 25: "comun", 45: "poco comun", 65: "poco comun", 100: "rara"}

CONFIANZA_COMPLETA = "completa"  # precio o ducados conocidos
CONFIANZA_PARCIAL = "parcial"  # solo rareza
CONFIANZA_NINGUNA = "ninguna"  # ni siquiera eso

# Firma del proveedor de precios: recibe el slug de warframe.market y devuelve un
# `online.market.Precios` (o None si no hay red). Se inyecta para no atar este
# modulo al cliente HTTP y poder probarlo sin conexion.
ProveedorPrecios = Callable[[str], object]


@dataclass
class Puntuacion:
    item_id: int
    nombre: str
    unique_name: str = ""
    platino: int | None = None  # el que cuenta para el valor
    platino_mediana: int | None = None
    platino_mejor_venta: int | None = None
    vendedores: int = 0
    ducados: int | None = None
    rareza: str | None = None
    objetivo: str = ""
    valor: float | None = None  # platino equivalente; None = no se sabe
    via: str = ""  # "platino", "ducados", "nada" o "" si desconocido
    confianza: str = CONFIANZA_NINGUNA
    notas: list[str] = field(default_factory=list)

    @property
    def desconocida(self) -> bool:
        return self.valor is None

    @property
    def clave(self) -> tuple:
        """Orden de preferencia: objetivo, valor, rareza. Lo desconocido va al final."""
        return (
            1 if self.objetivo else 0,
            self.valor if self.valor is not None else -1.0,
            ORDEN_RAREZA.get(self.rareza or "", -1),
        )


@dataclass
class Veredicto:
    puntuaciones: list[Puntuacion]
    mejor: int | None  # indice en `puntuaciones`, None si no hay con que decidir
    seguro: bool  # False = "probablemente", falta algun dato para afirmarlo
    motivo: str
    escuadra: bool = True
    tiempos_ms: dict[str, float] = field(default_factory=dict)

    @property
    def elegida(self) -> Puntuacion | None:
        return self.puntuaciones[self.mejor] if self.mejor is not None else None

    def resumen(self) -> str:
        """Una linea para el log, la barra de estado o la consola."""
        elegida = self.elegida
        if elegida is None:
            return t("Sin datos para elegir: {motivo}", motivo=self.motivo)
        if self.seguro:
            cabeza = t("Elige {nombre}", nombre=elegida.nombre)
        else:
            cabeza = t("Probablemente {nombre}", nombre=elegida.nombre)
        return f"{cabeza}: {self.motivo}"


def rareza_de(indice_con: sqlite3.Connection, item_id: int, ducados: int | None) -> str | None:
    """La rareza de la pieza: por sus ducados si los tiene, si no por las reliquias que la sueltan."""
    if ducados in RAREZA_POR_DUCADOS:
        return RAREZA_POR_DUCADOS[ducados]
    fila = indice_con.execute(
        "SELECT rareza, COUNT(*) AS n FROM reliquia_recompensas WHERE item_id = ? "
        "AND rareza IS NOT NULL GROUP BY rareza ORDER BY n DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    return RAREZAS.get(fila[0], fila[0].lower()) if fila else None


def _valorar(p: Puntuacion) -> None:
    """Rellena `valor`, `via` y `confianza` a partir de lo que se sepa."""
    candidatos: list[tuple[float, str]] = []
    if p.platino is not None:
        candidatos.append((float(p.platino), "platino"))
    if p.ducados:
        candidatos.append((p.ducados / DUCADOS_POR_PLATINO, "ducados"))
    if candidatos:
        p.valor, p.via = max(candidatos)
        p.confianza = CONFIANZA_COMPLETA
    elif p.via == "nada":
        p.valor = 0.0
        p.confianza = CONFIANZA_COMPLETA
    elif p.rareza:
        p.confianza = CONFIANZA_PARCIAL
    else:
        p.confianza = CONFIANZA_NINGUNA


def puntuar(
    recompensas: list[Recompensa],
    indice_con: sqlite3.Connection,
    precios_de: ProveedorPrecios | None = None,
    usuario_con: sqlite3.Connection | None = None,
    escuadra: bool = True,
    plazo_s: float = PLAZO_PRECIOS_S,
    reloj: Callable[[], float] = time.perf_counter,
) -> Veredicto:
    """Completa, pone precio, puntua y elige. Deja el resultado tambien en cada `Recompensa`."""
    inicio = reloj()
    tiempos: dict[str, float] = {}

    completar(recompensas, indice_con, usuario_con)
    tiempos["completar"] = (reloj() - inicio) * 1000

    puntuaciones = [
        Puntuacion(
            item_id=r.item_id,
            nombre=r.nombre,
            unique_name=r.unique_name,
            ducados=r.ducados,
            rareza=r.rareza or rareza_de(indice_con, r.item_id, r.ducados),
            objetivo=r.objetivo,
        )
        for r in recompensas
    ]

    # Precios, con plazo: lo que no llegue a tiempo se queda sin precio y se dice.
    t_precios = reloj()
    for r, p in zip(recompensas, puntuaciones):
        if r.platino is not None:
            p.platino = p.platino_mediana = p.platino_mejor_venta = r.platino
            continue
        if not r.market_slug:
            if not r.comerciable and not r.ducados:
                p.via = "nada"
                p.notas.append(t("No se vende ni da ducados"))
            else:
                p.notas.append(t("Sin precio: no esta en warframe.market"))
            continue
        if precios_de is None:
            p.notas.append(t("Sin precio: mercado no disponible"))
            continue
        if reloj() - inicio > plazo_s:
            p.notas.append(t("Sin precio: no dio tiempo a consultarlo"))
            continue
        _aplicar_precio(p, _pedir(precios_de, r.market_slug), escuadra)
        r.platino = p.platino
    tiempos["precios"] = (reloj() - t_precios) * 1000

    t_puntuar = reloj()
    for p in puntuaciones:
        _valorar(p)
    veredicto = decidir(puntuaciones, escuadra)
    tiempos["puntuar"] = (reloj() - t_puntuar) * 1000
    tiempos["total"] = (reloj() - inicio) * 1000
    veredicto.tiempos_ms = tiempos

    for i, (r, p) in enumerate(zip(recompensas, puntuaciones)):
        r.rareza = p.rareza
        r.valor = p.valor
        r.mejor = i == veredicto.mejor
        r.nota = "; ".join(p.notas)
    log.info(
        "Veredicto en %.0f ms (completar %.0f, precios %.0f, puntuar %.0f): %s",
        tiempos["total"], tiempos["completar"], tiempos["precios"], tiempos["puntuar"],
        veredicto.resumen(),
    )
    return veredicto


def _pedir(precios_de: ProveedorPrecios, slug: str):
    try:
        return precios_de(slug)
    except Exception as e:  # noqa: BLE001 - un fallo de red no puede dejar sin veredicto
        log.warning("No se pudo pedir el precio de %s: %s", slug, e)
        return None


def _aplicar_precio(p: Puntuacion, precios, escuadra: bool) -> None:
    """Vuelca un `online.market.Precios` (o lo que falte) en la puntuacion."""
    if precios is None:
        p.notas.append(t("Sin precio: mercado no disponible"))
        return
    error = getattr(precios, "error", "")
    if error:
        p.notas.append(t("Sin precio: {error}", error=error))
        return
    ventas = getattr(precios, "ventas", None) or []
    if not ventas:
        p.notas.append(t("Sin precio: nadie lo vende ahora"))
        return
    p.vendedores = len(ventas)
    p.platino_mejor_venta = precios.mejor_venta
    mediana = precios.mediana_venta
    p.platino_mediana = int(round(mediana)) if mediana is not None else None
    if escuadra:
        # Van a salir tres copias mas a la venta: lo realista es el precio del mas barato.
        p.platino = p.platino_mejor_venta
        if p.vendedores < MERCADO_FINO:
            p.notas.append(t("Mercado fino: {n} vendedores", n=p.vendedores))
    else:
        p.platino = p.platino_mediana


def decidir(puntuaciones: list[Puntuacion], escuadra: bool = True) -> Veredicto:
    """Elige entre puntuaciones ya valoradas y explica por que."""
    if not puntuaciones:
        return Veredicto([], None, False, t("no se reconocio ninguna recompensa"), escuadra)

    orden = sorted(range(len(puntuaciones)), key=lambda i: puntuaciones[i].clave, reverse=True)
    mejor = puntuaciones[orden[0]]
    desconocidas = [p for p in puntuaciones if p.desconocida]

    if mejor.objetivo:
        return Veredicto(
            puntuaciones, orden[0], True,
            t("cubre tu objetivo ({progreso})", progreso=mejor.objetivo), escuadra,
        )

    if mejor.desconocida:
        # Nada tiene valor; a lo sumo se ordena por rareza y se dice que es una suposicion.
        if mejor.rareza and len(puntuaciones) > 1:
            return Veredicto(
                puntuaciones, orden[0], False,
                t("sin precios; es la mas rara ({rareza})", rareza=mejor.rareza), escuadra,
            )
        return Veredicto(
            puntuaciones, None, False, t("sin precio ni ducados de ninguna"), escuadra,
        )

    motivo = _motivo_valor(mejor)
    seguro = True
    if len(orden) > 1:
        segunda = puntuaciones[orden[1]]
        if segunda.valor is not None and mejor.valor > 0 and (
            (mejor.valor - segunda.valor) / mejor.valor < EMPATE
        ):
            seguro = False
            motivo += t("; casi empata con {nombre}", nombre=segunda.nombre)
    if desconocidas:
        seguro = False
        motivo += t("; {nombres} sin valorar", nombres=", ".join(p.nombre for p in desconocidas))
    return Veredicto(puntuaciones, orden[0], seguro, motivo, escuadra)


def _motivo_valor(p: Puntuacion) -> str:
    if p.via == "platino":
        texto = t("{n} platino", n=p.platino)
        if p.ducados:
            texto += " (" + t("{n} ducados", n=p.ducados) + ")"
        return texto
    if p.via == "ducados":
        texto = t("{n} ducados", n=p.ducados)
        if p.platino is not None:
            texto += " " + t("(solo {n} platino)", n=p.platino)
        return texto
    return t("ninguna vale gran cosa")


class ServicioComparador(QObject):
    """`puntuar` en el hilo de captura, para que la red no pare la ventana.

    La interfaz conecta `LectorRecompensas.leidas` a `comparar` y pinta al recibir
    `veredicto(recompensas, Veredicto)`. Las conexiones SQLite se abren aqui, en el
    hilo que las usa; el proveedor de precios se crea perezoso la primera vez.
    """

    veredicto = Signal(list, object)  # list[Recompensa] ya completadas, Veredicto

    def __init__(self, escuadra: bool = True, ruta_usuario=None, crear_market=None, parent=None):
        super().__init__(parent)
        self.escuadra = escuadra
        self.ruta_usuario = ruta_usuario
        self._crear_market = crear_market
        self._market = None

    def _precios_de(self):
        if self._market is None:
            try:
                if self._crear_market is not None:
                    self._market = self._crear_market()
                else:
                    from ..online.market import Market

                    self._market = Market()
            except Exception as e:  # noqa: BLE001 - sin mercado se puntua con ducados y rareza
                log.warning("Mercado no disponible para el comparador: %s", e)
                return None
        # Una fabrica que devuelve None (o algo sin `precios`) dejaba el veredicto
        # vacio sin decir por que: se trata como "no hay mercado" y se sigue con
        # ducados y rareza, que es peor respuesta pero es una respuesta.
        if self._market is None or not hasattr(self._market, "precios"):
            log.warning("El comparador no tiene mercado con el que consultar precios")
            return None
        return self._market.precios

    @Slot(list)
    def comparar(self, recompensas: list) -> None:
        if not recompensas:
            self.veredicto.emit([], decidir([], self.escuadra))
            return
        from ..datos import indice
        from ..estado import usuario_db

        indice_con = indice.conectar()
        usuario_con = None
        try:
            try:
                usuario_con = (
                    usuario_db.conectar(self.ruta_usuario) if self.ruta_usuario else usuario_db.conectar()
                )
            except Exception as e:  # noqa: BLE001 - sin objetivos se puntua igual
                log.warning("Sin base de datos del usuario para el comparador: %s", e)
            resultado = puntuar(
                recompensas, indice_con, self._precios_de(), usuario_con, escuadra=self.escuadra
            )
        except Exception:  # noqa: BLE001 - un fallo aqui no puede dejar la pantalla sin etiquetas
            log.exception("Fallo puntuando las recompensas")
            resultado = decidir([], self.escuadra)
        finally:
            indice_con.close()
            if usuario_con is not None:
                usuario_con.close()
        self.veredicto.emit(recompensas, resultado)

    @Slot()
    def cerrar(self) -> None:
        if self._market is not None:
            try:
                self._market.cerrar()
            except Exception:  # noqa: BLE001
                pass
