"""De donde sale cada "~70 min" de la ficha, en texto para el tooltip.

El tiempo medio es minutos por intento / probabilidad (datos/eficiencia.py), pero
visto solo, "~70 min" junto a "Formido, rotacion C, 19,4 %" parece lo que dura la
mision. Este modulo lo desglosa con los numeros de esa fila:

    ~13.5 min por partida (hasta la rotacion C).
    x ~5.2 partidas de media (19.4% cada una) = ~70 min.
    Es una media: puede caer antes o tardar mas.

El texto va dentro del enlace del tiempo (glosario.enlace(..., detalle=)) y el
glosario le anade debajo con que ritmo de juego esta calculado.
"""

from __future__ import annotations

from ..datos import eficiencia
from ..idiomas import t


def _num(valor: float) -> str:
    """13.5 -> '13.5', 5.17 -> '5.2', 21.5 -> '22': un decimal solo en numeros pequenos."""
    if valor >= 20:
        return f"{round(valor):d}"
    return f"{valor:.1f}".removesuffix(".0")


def _linea_intento(d: dict) -> tuple[str, bool]:
    """La primera linea (que es un intento y cuanto dura) y si la unidad es 'partida'."""
    clase = d["clase"]
    partida, rotacion = _num(d["partida"]), d.get("rotacion") or ""
    if clase == "jefe":
        return t("~{min} min por combate contra el jefe, contando la carga.", min=partida), True
    if clase == "bounty":
        return t(
            "Esta recompensa vuelve cada {n} contratos: {n} tandas de ~{tanda} min = ~{min} min por intento.",
            n=d["tandas"], tanda=_num(d["min_tanda"]), min=partida,
        ), False
    if clase == "tramos" and rotacion:
        return t("~{min} min por partida (hasta la rotacion {rot}).", min=partida, rot=rotacion), True
    if clase == "sin_fin":
        if d.get("unidad") == "ronda" and d["premios"] > 1 and rotacion:
            # Disrupcion: la letra no va por turno sino por ronda y conductos salvados,
            # y "2 rotaciones A" no diria nada; se cuenta en rondas.
            return t(
                "~{min} min por partida ({n} rondas de ~{rmin} min mas llegar, extraer y la carga), que dan "
                "{premios} premios de la rotacion {rot}: ~{intento} min por intento.",
                min=partida, n=d["rotaciones"], rmin=_num(d["min_rotacion"]),
                premios=d["premios"], rot=rotacion, intento=_num(d["intento"]),
            ), False
        if d["premios"] > 1:
            return t(
                "~{min} min por partida ({n} rotaciones {rot} de ~{rmin} min mas llegar, extraer y la carga), que dan "
                "{premios} intentos: ~{intento} min por intento.",
                min=partida, n=d["rotaciones"], rot=rotacion, rmin=_num(d["min_rotacion"]),
                premios=d["premios"], intento=_num(d["intento"]),
            ), False
        if rotacion:
            return t(
                "~{min} min por partida (hasta la rotacion {rot}: {n} rotaciones de ~{rmin} min mas llegar, extraer y la carga).",
                min=partida, rot=rotacion, n=d["rotaciones"], rmin=_num(d["min_rotacion"]),
            ), True
        return t(
            "~{min} min por partida ({n} rotaciones de ~{rmin} min mas llegar, extraer y la carga).",
            min=partida, n=d["rotaciones"], rmin=_num(d["min_rotacion"]),
        ), True
    return t("~{min} min por partida, contando la carga.", min=partida), True


def texto(fila: dict | None) -> str:
    """El desglose del tiempo medio de una fila de fuentes; vacio si no tiene estimacion."""
    d = eficiencia.desglose(fila) if fila else None
    if not d:
        return ""
    primera, por_partida = _linea_intento(d)
    valores = {
        "veces": _num(d["veces"]),
        "prob": f"{d['probabilidad']:.1f}",
        "total": eficiencia.texto_minutos(d["total"]),
    }
    segunda = (
        t("Con un {prob}% sale casi siempre a la primera: {total}.", **valores)
        if d["veces"] < 1.1
        else t("x ~{veces} partidas de media ({prob}% cada una) = {total}.", **valores)
        if por_partida
        else t("x ~{veces} intentos de media ({prob}% cada uno) = {total}.", **valores)
    )
    return "\n".join((primera, segunda, t("Es una media: puede caer antes o tardar mas.")))


def texto_prime(sitio: dict | None, escuadra: int, modo: str) -> str:
    """Desglose del tiempo hasta una pieza prime en un sitio de `ruta_prime.misiones_para`.

    Ahi el tiempo junta dos cosas: conseguir una reliquia util en la mision y abrirla
    en fisuras hasta que sale la pieza. Mismo modelo que `ruta_prime.minutos_pieza`:

        (minutos por reliquia + fisura) x fisuras de media

    `modo` es el refinamiento y la escuadra ya en texto ("Radiante, escuadra de 4").
    """
    from ..datos import ruta_prime  # ruta_prime importa relaciones; aqui solo hace falta al pintar

    if not sitio or not sitio.get("reliquias") or sitio.get("minutos") is None:
        return ""
    cae = min(sum(min(float(r["probabilidad_mision"]), 100.0) for r in sitio["reliquias"]), 100.0)
    d = eficiencia.desglose({**sitio, "probabilidad": cae, "probabilidad_efectiva": cae})
    if not d:
        return ""
    acierta = sum(
        min(float(r["probabilidad_mision"]), 100.0) / 100
        * ruta_prime.probabilidad_por_fisura(r["probabilidad"], escuadra)
        for r in sitio["reliquias"]
    )
    if acierta <= 0:
        return ""
    reliquia = d["intento"] / (cae / 100)  # minutos hasta que cae una reliquia util
    fisura = eficiencia.minutos_fisura()
    por_fisura = acierta / (cae / 100)  # probabilidad de la pieza en cada fisura
    fisuras = 1 / por_fisura
    primera, _por_partida = _linea_intento(d)
    return "\n".join((
        primera,
        t("{prob}% de que caiga alguna reliquia util -> ~{min} min por reliquia.",
          prob=f"{cae:.1f}", min=_num(reliquia)),
        t("+ ~{min} min por fisura para abrirla.", min=_num(fisura)),
        t("{modo}: {prob}% de sacar la pieza en cada fisura -> ~{n} fisuras de media.",
          modo=modo, prob=f"{min(por_fisura, 1.0) * 100:.0f}", n=_num(fisuras)),
        t("(~{reliquia} + ~{fisura} min) x ~{n} = {total}.", reliquia=_num(reliquia),
          fisura=_num(fisura), n=_num(fisuras), total=eficiencia.texto_minutos(sitio["minutos"])),
        t("Es una media: puede caer antes o tardar mas."),
    ))
