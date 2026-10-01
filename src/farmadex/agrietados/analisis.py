"""Tu agrietado frente a los parecidos que se venden en warframe.market.

Sin red ni Qt: recibe tu evaluacion (grados.evaluar) y las subastas parecidas que
devolvio `mercado.parecidos` y saca una comparacion honesta:

- la "tirada" de cada agrietado es la media de donde cayo cada estadistica dentro de lo
  posible para esa arma (0 = lo peor, 1 = lo mejor), la misma cuenta que los grados;
- solo cuentan las subastas de la misma arma cuyas estadisticas entran TODAS en lo
  posible (una subasta con un valor imposible esta mal apuntada o a otro rango);
- con menos de `MINIMO_MUESTRAS` no se da veredicto, se dice cuantas hay;
- el precio de referencia es la mediana de lo que piden por los que tiran como el tuyo
  o mejor, y el de los que tiran peor, cada uno con cuantas subastas lo sostienen.

Nunca pone un numero que no salga de subastas reales.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from . import grados

MINIMO_MUESTRAS = 5
# Diferencia de tirada (en puntos de 0 a 100) que se considera "parecida" a la tuya.
MARGEN_IGUAL = 5.0


@dataclass
class Comparacion:
    muestras: int = 0  # subastas parecidas que se han podido evaluar
    descartadas: int = 0  # con algun valor imposible para esta arma
    tirada_tuya: float | None = None  # 0..100
    tirada_media: float | None = None  # 0..100, de las muestras
    por_encima: int = 0  # muestras que tiran peor que la tuya
    precio_mejores: int | None = None  # mediana de lo que piden por las que tiran como la tuya o mejor
    n_mejores: int = 0
    precio_peores: int | None = None
    n_peores: int = 0
    precio_mediana: int | None = None
    motivo: str = ""  # por que no hay veredicto
    tiradas: list[tuple[float, int]] = field(default_factory=list)  # (tirada, precio) de cada muestra

    @property
    def suficiente(self) -> bool:
        return self.muestras >= MINIMO_MUESTRAS and self.tirada_tuya is not None

    @property
    def diferencia(self) -> float | None:
        if self.tirada_tuya is None or self.tirada_media is None:
            return None
        return self.tirada_tuya - self.tirada_media

    @property
    def posicion(self) -> str:
        """"encima", "debajo" o "igual" respecto a la media de los parecidos ("" sin datos)."""
        d = self.diferencia
        if d is None or not self.suficiente:
            return ""
        if d > MARGEN_IGUAL:
            return "encima"
        if d < -MARGEN_IGUAL:
            return "debajo"
        return "igual"

    @property
    def percentil(self) -> float | None:
        """Que parte de los parecidos tira peor que el tuyo (0..100)."""
        if not self.suficiente:
            return None
        return 100.0 * self.por_encima / self.muestras


def tirada(evaluaciones) -> float | None:
    """Media de la posicion (0..100) de todas las estadisticas; None si alguna es imposible."""
    if not evaluaciones:
        return None
    posiciones = []
    for ev in evaluaciones:
        if ev.minimo is None or ev.grado is None or ev.posicion is None:
            return None
        posiciones.append(ev.posicion)
    return 100.0 * sum(posiciones) / len(posiciones)


def comparar(tuyas: list[tuple[str, float, bool]], clase: str, disposicion: float, subastas) -> Comparacion:
    """Compara tus estadisticas (slug, valor, negativo) con las subastas parecidas."""
    c = Comparacion()
    c.tirada_tuya = tirada(grados.evaluar(tuyas, clase, disposicion))
    if c.tirada_tuya is None:
        c.motivo = "tu agrietado tiene algún valor que no cuadra con esta arma"
        return c
    for s in subastas or []:
        precio = getattr(s, "precio", None)
        if not precio or not s.atributos:
            continue
        valor = tirada(grados.evaluar(list(s.atributos), clase, disposicion))
        if valor is None:
            c.descartadas += 1
            continue
        c.tiradas.append((valor, int(precio)))
    c.muestras = len(c.tiradas)
    if not c.tiradas:
        c.motivo = "no hay subastas parecidas que se puedan comparar"
        return c
    c.tirada_media = statistics.fmean(v for v, _p in c.tiradas)
    c.precio_mediana = int(round(statistics.median(p for _v, p in c.tiradas)))
    c.por_encima = sum(1 for v, _p in c.tiradas if v < c.tirada_tuya)
    mejores = [p for v, p in c.tiradas if v >= c.tirada_tuya - MARGEN_IGUAL]
    peores = [p for v, p in c.tiradas if v < c.tirada_tuya - MARGEN_IGUAL]
    c.n_mejores, c.n_peores = len(mejores), len(peores)
    if mejores:
        c.precio_mejores = int(round(statistics.median(mejores)))
    if peores:
        c.precio_peores = int(round(statistics.median(peores)))
    if c.muestras < MINIMO_MUESTRAS:
        c.motivo = "pocas subastas parecidas para comparar"
    return c
