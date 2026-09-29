"""¿Vender una pieza por platino o cambiarla por ducados a Baro Ki'Teer?

Solo aritmetica: no pide nada a la red ni abre ninguna base de datos, para poder
llamarse en el camino del panel de recompensas sin retrasarlo. Los precios los
trae quien llama (el veredicto del comparador, o la cache de precios vistos).

La cuenta que se hace
---------------------
Una pieza da los ducados que marca el indice (15, 25, 45, 65, 100) y se vende en
warframe.market por lo que pida el vendedor mas barato que esta conectado (a ese
precio hay que ponerse para venderla pronto). Se compara cuantos ducados da por
cada platino que se dejaria de ganar:

    ducados por platino = ducados / platino

Como referencia se usa la misma que el comparador (`DUCADOS_POR_PLATINO`): un
jugador no cambia un platino por menos de unos diez ducados, porque es mas o
menos a lo que salen las cosas de Baro. Alrededor de ese valor da casi igual, asi
que hay una franja muerta en la que no se recomienda nada con fuerza:

- 12 o mas ducados por platino: **fundir** (Baro te da mas).
- 8 o menos: **vender** (el platino compensa).
- entre medias: **da igual**, lo que te venga mejor.

Liquidez: si nadie la esta comprando y hay pocos vendedores conectados, el precio
es de un mercado fino y venderla puede costar dias. Entonces se pide menos para
fundir (8 o mas) y el umbral de vender baja a 5.

Lo que manda por encima de la cuenta: si la pieza esta en las metas del usuario,
"te hace falta" y no se aconseja deshacerse de ella. Y sin precio, sin ducados o
con un precio viejo no se aconseja nada: mejor callar que dar un consejo falso.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..idiomas import actual, t

# Equivalencia de referencia, la misma que usa el comparador para puntuar.
DUCADOS_POR_PLATINO = 10
FUNDIR_DESDE = 12.0
VENDER_HASTA = 8.0
# Mercado poco liquido (nadie compra y pocos venden): cuesta mas vender.
FUNDIR_DESDE_ILIQUIDO = 8.0
VENDER_HASTA_ILIQUIDO = 5.0
POCOS_VENDEDORES = 5
# Un precio de hace mas de esto ya no sirve para aconsejar (el mercado se mueve).
EDAD_MAXIMA_S = 12 * 3600

FALTA = "falta"
VENDER = "vender"
FUNDIR = "fundir"
IGUAL = "igual"
CLAVES = (FALTA, VENDER, FUNDIR, IGUAL)


@dataclass
class Consejo:
    clave: str  # una de CLAVES
    corto: str  # para una etiqueta: "Mejor vender"
    motivo: str  # la explicacion, para el tooltip o la linea de detalle

    def como_dict(self) -> dict:
        return {"clave": self.clave, "corto": self.corto, "motivo": self.motivo}


def poco_liquido(vendedores: int | None, compradores: int | None) -> bool:
    """Nadie compra y hay pocos vendedores conectados. Sin datos de compradores, solo cuenta que haya pocos."""
    if vendedores is None:
        return False
    if compradores is not None and compradores > 0:
        return False
    return vendedores < POCOS_VENDEDORES


def aconsejar(
    platino: int | float | None,
    ducados: int | None,
    *,
    es_meta: bool = False,
    vendedores: int | None = None,
    compradores: int | None = None,
    edad_s: float | None = 0.0,
) -> Consejo | None:
    """El consejo para una pieza, o None si no hay datos para darlo con seguridad.

    `platino`: lo que se sacaria vendiendola ya (vendedor mas barato). `edad_s`:
    cuantos segundos tiene ese precio; None = no se sabe, y entonces no se aconseja.
    """
    if es_meta:
        return Consejo(FALTA, t("Te hace falta"), t("Está en tus metas: mejor quedártela."))
    if not ducados or ducados <= 0:
        return None  # sin ducados no hay nada que comparar
    if platino is None or edad_s is None or edad_s > EDAD_MAXIMA_S or edad_s < 0:
        return None
    platino = float(platino)
    if platino <= 0:
        return None
    ratio = ducados / platino
    iliquido = poco_liquido(vendedores, compradores)
    fundir_desde = FUNDIR_DESDE_ILIQUIDO if iliquido else FUNDIR_DESDE
    vender_hasta = VENDER_HASTA_ILIQUIDO if iliquido else VENDER_HASTA
    p, d = int(round(platino)), int(ducados)
    r = f"{ratio:.1f}".removesuffix(".0")
    if actual() != "en":
        r = r.replace(".", ",")  # 8,3 en castellano, frances, aleman y portugues
    if ratio >= fundir_desde:
        motivo = t("Da {d} ducados y se vende por {p} platino: son {r} ducados por platino, "
                   "y a Baro le sacas más partido.", d=d, p=p, r=r)
        if iliquido:
            motivo += " " + t("Además casi nadie la compra ahora.")
        return Consejo(FUNDIR, t("Mejor fundir"), motivo)
    if ratio <= vender_hasta:
        motivo = t("Se vende por {p} platino y solo da {d} ducados: son {r} ducados por platino, "
                   "sale más a cuenta venderla.", d=d, p=p, r=r)
        if iliquido:
            motivo += " " + t("Ojo: casi nadie la compra ahora, puede tardar en venderse.")
        return Consejo(VENDER, t("Mejor vender"), motivo)
    return Consejo(IGUAL, t("Vender o fundir: parecido"),
                   t("Da {d} ducados y se vende por {p} platino ({r} ducados por platino): "
                     "sale más o menos igual, lo que te venga mejor.", d=d, p=p, r=r))


def explicacion_umbral() -> str:
    """El criterio en una frase, para la ayuda de la vista del historial."""
    return t("Vender o fundir: como referencia, unos {n} ducados valen lo que 1 platino. Si la pieza da "
             "bastantes más ducados por cada platino que pagan por ella, conviene guardarla para Baro; "
             "si da bastantes menos, conviene venderla. Si está en tus metas, te hace falta. Sin precio "
             "reciente no se aconseja nada.", n=DUCADOS_POR_PLATINO)
