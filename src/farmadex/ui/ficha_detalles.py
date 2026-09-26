"""Bloques de la ficha con los datos de WFCD que no son "donde sale".

Estadisticas de las armas (y su disposicion de riven), efecto de cada mod y de cada
arcano rango a rango, lo basico de un warframe con sus habilidades, y el codigo de
canje de los glifos con un boton para copiarlo. Lo usan la ficha de Buscar (completa) y
la vista compacta (`compacto=True`: lo justo para leerlo en cinco segundos).

Los nombres de las estadisticas son terminos del juego: en castellano se ensenan en
castellano y en los demas idiomas el ingles del juego, igual que hace `glosa`.
"""

from __future__ import annotations

import html
import sqlite3

from ..datos import detalles, eficiencia, glifos, indice, relaciones
from ..idiomas import es_castellano, glosa, t
from . import glosario
from .widgets import PALETA

# Enlace que copia un texto al portapapeles: "copiar:<texto>".
PREFIJO_COPIAR = "copiar:"

DANO = {
    "impact": "Impacto", "puncture": "Perforación", "slash": "Corte", "heat": "Calor",
    "cold": "Frío", "electricity": "Electricidad", "toxin": "Toxina", "blast": "Explosión",
    "radiation": "Radiación", "gas": "Gas", "magnetic": "Magnético", "viral": "Viral",
    "corrosive": "Corrosivo", "void": "Vacío", "tau": "Tau", "true": "Verdadero",
}
# Colores de cada tipo de dano, los de la interfaz del juego mas o menos.
COLOR_DANO = {
    "impact": "#9fb3c8", "puncture": "#c8c39f", "slash": "#e07a7a", "heat": "#ff9a4d",
    "cold": "#8fd3ff", "electricity": "#b99cff", "toxin": "#7fdc6b", "blast": "#ffb35c",
    "radiation": "#f2e36b", "gas": "#a6d86b", "magnetic": "#6bb6ff", "viral": "#6bd6b2",
    "corrosive": "#b7e05c", "void": "#e6e6f0", "tau": "#e6e6f0", "true": "#e6e6f0",
}
POLARIDADES = {
    "madurai": "Madurai", "vazarin": "Vazarin", "naramon": "Naramon", "zenurik": "Zenurik",
    "unairu": "Unairu", "penjaga": "Penjaga", "umbra": "Umbra", "aura": "Aura", "any": "",
}
GATILLOS = {
    "Auto": "Automático", "Semi": "Semiautomático", "Burst": "Ráfaga", "Charge": "Carga",
    "Held": "Mantenido", "Duplex": "Dúplex", "Active": "Activo", "Auto Burst": "Ráfaga automática",
    "Semi-Auto": "Semiautomático", "Auto-Spool": "Automático con aceleración",
}


def _g(es: str, en: str) -> str:
    """Termino del juego: castellano si toca; si no, el catalogo o el ingles del juego."""
    return glosa(es, en)


def _n(valor, decimales: int = 1) -> str:
    """12.0 -> '12'; 2.15 -> '2.2'. Sin ceros de relleno."""
    if valor is None:
        return ""
    if decimales <= 0:
        return str(int(round(float(valor))))
    return f"{float(valor):.{decimales}f}".rstrip("0").rstrip(".") or "0"


def _pct(valor) -> str:
    return f"{_n(float(valor) * 100)}%" if valor is not None else ""


def _seccion(titulo: str, clave_glosario: str | None = None) -> str:
    p = PALETA
    texto = (glosario.enlace(clave_glosario, titulo.upper(), p["acento"]) if clave_glosario
             else html.escape(titulo.upper()))
    return (f"<div style='color:{p['acento']};font-size:12px;font-weight:bold;"
            f"margin-top:14px;margin-bottom:4px'>{texto}</div>")


def _tabla(filas: list[str]) -> str:
    return (f"<table width='100%' cellspacing='0' cellpadding='5' style='background:{PALETA['panel2']}'>"
            + "".join(filas) + "</table>")


def _celdas(pares: list[tuple[str, str]], por_fila: int) -> list[str]:
    """Pares (etiqueta, valor) en filas de `por_fila` columnas: 'Critico  12% x2'."""
    p = PALETA
    filas = []
    for i in range(0, len(pares), por_fila):
        trozo = pares[i:i + por_fila]
        celdas = "".join(
            f"<td style='color:{p['suave']}'>{etiqueta}</td><td><b>{valor}</b></td>"
            for etiqueta, valor in trozo
        )
        filas.append(f"<tr>{celdas}</tr>")
    return filas


def puntos_disposicion(puntos) -> str:
    """4 -> '●●●●○'. Fuera de 1..5, vacio."""
    try:
        n = int(round(float(puntos)))
    except (TypeError, ValueError):
        return ""
    if not 1 <= n <= 5:
        return ""
    return "●" * n + "○" * (5 - n)


def html_detalles(con: sqlite3.Connection | None, item: dict | None, compacto: bool = False) -> str:
    """Todos los bloques que tenga el objeto, o cadena vacia si no tiene ninguno."""
    if con is None or not item:
        return ""
    datos = detalles.leer(con, item.get("id"))
    if not datos:
        return ""
    partes = []
    if "glifo" in datos:
        partes.append(bloque_glifo(datos["glifo"], compacto))
    if "arma" in datos:
        partes.append(bloque_arma(datos["arma"], compacto))
    if "warframe" in datos:
        partes.append(bloque_warframe(datos["warframe"], compacto))
    if "mod" in datos:
        partes.append(bloque_efecto(datos["mod"], compacto, es_mod=True))
    if "arcano" in datos:
        partes.append(bloque_efecto(datos["arcano"], compacto, es_mod=False))
    return "".join(p for p in partes if p)


# Tope de cada barra de estadisticas de la ficha C: lo que en el juego ya es "mucho".
# Solo sirve para dibujar la barra; el numero que se ensena es el de verdad.
TOPES_ARMA = {
    "critico": 0.5, "mult_critico": 4.0, "estado": 0.5, "cadencia": 15.0, "cargador": 200.0,
    "recarga": 5.0, "multidisparo": 5.0, "alcance": 5.0,
}


def estadisticas_arma(arma: dict | None) -> list[tuple[str, str, float | None]]:
    """(nombre, valor, parte de la barra 0..1 o None) de cada estadistica de un arma, para
    la ficha C. La recarga va al reves: cuanto mas corta, mas llena."""
    if not arma:
        return []
    melee = arma.get("cuerpo_a_cuerpo")
    salida: list[tuple[str, str, float | None]] = []

    def poner(es, en, valor, clave=None, crudo=None, al_reves=False):
        if not valor:
            return
        parte = None
        if clave and crudo is not None and TOPES_ARMA.get(clave):
            parte = max(0.0, min(1.0, float(crudo) / TOPES_ARMA[clave]))
            if al_reves:
                parte = 1.0 - parte
        salida.append((_g(es, en), valor, parte))

    poner("Probabilidad crítica", "Critical chance", _pct(arma.get("critico")), "critico", arma.get("critico"))
    if arma.get("mult_critico"):
        poner("Multiplicador crítico", "Critical multiplier", f"×{_n(arma['mult_critico'])}", "mult_critico",
              arma["mult_critico"])
    poner("Probabilidad de estado", "Status chance", _pct(arma.get("estado")), "estado", arma.get("estado"))
    if melee:
        poner("Velocidad de ataque", "Attack speed", _n(arma.get("cadencia"), 2))
        poner("Alcance", "Range", f"{_n(arma.get('alcance'))} m" if arma.get("alcance") else "", "alcance",
              arma.get("alcance"))
    else:
        if arma.get("cadencia"):
            poner("Cadencia", "Fire rate", t("{n} por segundo", n=_n(arma["cadencia"], 2)), "cadencia",
                  arma["cadencia"])
        poner("Cargador", "Magazine", _n(arma.get("cargador"), 0), "cargador", arma.get("cargador"))
        poner("Recarga", "Reload", f"{_n(arma.get('recarga'), 2)} s" if arma.get("recarga") else "", "recarga",
              arma.get("recarga"), al_reves=True)
        if arma.get("multidisparo") and float(arma["multidisparo"]) != 1:
            poner("Multidisparo", "Multishot", _n(arma["multidisparo"]), "multidisparo", arma["multidisparo"])
        gatillo = arma.get("gatillo")
        if gatillo:
            poner("Gatillo", "Trigger", glosa(GATILLOS.get(gatillo, gatillo), gatillo))
    return salida


def dano_arma(arma: dict | None) -> list[tuple[str, str, float, str]]:
    """(clave, nombre, valor, color) de cada tipo de dano de un arma, en su orden."""
    salida = []
    for clave, cantidad in ((arma or {}).get("dano") or {}).items():
        if cantidad:
            salida.append((clave, _g(DANO.get(clave, clave), clave.capitalize()), float(cantidad),
                           COLOR_DANO.get(clave, PALETA["texto"])))
    return salida


def numero(valor, decimales: int = 1) -> str:
    """El numero como lo escribe la ficha, sin ceros de relleno (para las piezas C)."""
    return _n(valor, decimales)


def bloques(con: sqlite3.Connection | None, item: dict | None) -> dict:
    """Los bloques de detalles por separado y sin su titulo, para repartirlos en paneles.

    Claves posibles: "glifo", "arma" (la tabla de siempre), "warframe" (vida, escudo... y
    la pasiva), "habilidades", "mod", "arcano"; y "_datos" con lo leido de `detalles`.
    """
    if con is None or not item:
        return {}
    datos = detalles.leer(con, item.get("id"))
    if not datos:
        return {}
    salida: dict = {"_datos": datos}
    if "glifo" in datos:
        salida["glifo"] = bloque_glifo(datos["glifo"], titulo=False)
    if "arma" in datos:
        salida["arma"] = bloque_arma(datos["arma"])
    if "warframe" in datos:
        salida["warframe"] = bloque_warframe(datos["warframe"], titulo=False, con_habilidades=False)
        salida["habilidades"] = html_habilidades(datos["warframe"])
    if "mod" in datos:
        salida["mod"] = bloque_efecto(datos["mod"], es_mod=True, titulo=False)
    if "arcano" in datos:
        salida["arcano"] = bloque_efecto(datos["arcano"], es_mod=False, titulo=False)
    return {k: v for k, v in salida.items() if v}


def bloque_glifo(glifo: dict, compacto: bool = False, titulo: bool = True) -> str:
    codigo = (glifo or {}).get("codigo")
    if not codigo:
        return ""
    p = PALETA
    boton = (
        f"<a href='{PREFIJO_COPIAR}{html.escape(codigo)}' style='text-decoration:none;"
        f"color:{p['acento_texto'] if 'acento_texto' in p else p['fondo']};background:{p['acento']};"
        f"font-weight:bold'>&nbsp;&nbsp;{html.escape(t('Copiar'))}&nbsp;&nbsp;</a>"
    )
    canjear = (f"<a style='color:{p['acento']}' href='{html.escape(glifos.url_canje(codigo))}'>"
               f"{html.escape(t('Canjear en la web'))} &rarr;</a>")
    cabecera = (f"<span style='color:{p['suave']}'>{html.escape(t('Codigo del glifo:'))}</span> "
                f"<b style='font-size:{15 if compacto else 17}px'>{html.escape(codigo)}</b>&nbsp;&nbsp;{boton}")
    if compacto:
        return f"<div style='margin-top:4px'>{cabecera}</div>"
    nota = html.escape(t("Escribelo en el Mercado del juego o en la web de Warframe. Sale de la wiki "
                         "oficial: si ya no funciona, es que ha caducado."))
    return (
        (_seccion(t("Codigo de canje")) if titulo else "")
        + f"<div>{cabecera} &nbsp; {canjear}</div>"
        + f"<div style='color:{p['suave']};font-size:12px;margin-top:3px'>{nota}</div>"
    )


def _disposicion(arma: dict) -> str:
    puntos = puntos_disposicion(arma.get("disposicion"))
    if not puntos:
        return ""
    p = PALETA
    exacta = f" <span style='color:{p['suave']}'>(×{_n(arma['riven'], 2)})</span>" if arma.get("riven") else ""
    return glosario.enlace("disposicion", puntos, p["acento"]) + exacta


def bloque_arma(arma: dict, compacto: bool = False) -> str:
    if not arma:
        return ""
    p = PALETA
    melee = arma.get("cuerpo_a_cuerpo")
    pares: list[tuple[str, str]] = []

    def poner(es, en, valor):
        if valor:
            pares.append((html.escape(_g(es, en)), valor))

    critico = _pct(arma.get("critico"))
    if critico and arma.get("mult_critico"):
        critico += f" ×{_n(arma['mult_critico'])}"
    poner("Daño", "Damage", _n(arma.get("dano_total")))
    poner("Crítico", "Critical", critico)
    poner("Estado", "Status", _pct(arma.get("estado")))
    if melee:
        poner("Velocidad de ataque", "Attack speed", _n(arma.get("cadencia"), 2))
        poner("Alcance", "Range", f"{_n(arma.get('alcance'))} m" if arma.get("alcance") else "")
    else:
        poner("Cadencia", "Fire rate", _n(arma.get("cadencia"), 2))
        poner("Cargador", "Magazine", _n(arma.get("cargador"), 0))
        poner("Recarga", "Reload", f"{_n(arma.get('recarga'), 2)} s" if arma.get("recarga") else "")
        if arma.get("multidisparo") and float(arma["multidisparo"]) != 1:
            poner("Multidisparo", "Multishot", _n(arma["multidisparo"]))
        gatillo = arma.get("gatillo")
        poner("Gatillo", "Trigger", html.escape(glosa(GATILLOS.get(gatillo, gatillo), gatillo)) if gatillo else "")
    if arma.get("maestria"):
        poner("Maestría", "Mastery", f"MR {_n(arma['maestria'], 0)}")
    disposicion = _disposicion(arma)
    if disposicion:
        pares.append((glosario.enlace("disposicion", html.escape(_g("Disposición de riven", "Riven disposition")),
                                      p["suave"]), disposicion))

    dano = arma.get("dano") or {}
    tipos = " &middot; ".join(
        f"<span style='color:{COLOR_DANO.get(k, p['texto'])}'>{html.escape(_g(DANO.get(k, k), k.capitalize()))}</span>"
        f" <b>{_n(v)}</b>"
        for k, v in dano.items()
    )
    if compacto:
        resumen = " &middot; ".join(f"{etiqueta} <b>{valor}</b>" for etiqueta, valor in pares[:5])
        linea_disp = (f"<br>{glosario.enlace('disposicion', html.escape(_g('Disposición de riven', 'Riven disposition')), p['suave'])}: {disposicion}"
                      if disposicion else "")
        return f"<div style='margin-top:4px'>{resumen}{linea_disp}</div>"
    salida = _seccion(t("Estadisticas")) + _tabla(_celdas(pares, 3))
    if tipos:
        salida += f"<div style='margin:4px 0 0 4px'>{tipos}</div>"
    return salida


def bloque_warframe(wf: dict, compacto: bool = False, titulo: bool = True, con_habilidades: bool = True) -> str:
    if not wf:
        return ""
    p = PALETA
    pares = []
    for clave, es, en in (("vida", "Vida", "Health"), ("escudo", "Escudo", "Shield"),
                          ("armadura", "Armadura", "Armor"), ("energia", "Energía", "Energy")):
        if wf.get(clave) is not None:
            pares.append((html.escape(_g(es, en)), _n(wf[clave], 0)))
    castellano = es_castellano()
    habilidades = wf.get("habilidades") or []
    if compacto:
        linea = " &middot; ".join(f"{e} <b>{v}</b>" for e, v in pares)
        nombres = ", ".join(html.escape((h.get("es") if castellano else "") or h["en"]) for h in habilidades)
        return (f"<div style='margin-top:4px'>{linea}</div>"
                + (f"<div style='color:{p['suave']}'>{nombres}</div>" if nombres else ""))
    salida = ((_seccion(t("Estadisticas")) if titulo else "") + _tabla(_celdas(pares, 4))) if pares else ""
    pasiva = wf.get("pasiva") or {}
    texto_pasiva = (pasiva.get("es") if castellano else "") or pasiva.get("en") or ""
    if texto_pasiva:
        salida += (f"<p style='margin:6px 0 2px 4px'><b>{html.escape(_g('Pasiva', 'Passive'))}:</b> "
                   f"{html.escape(texto_pasiva)}</p>")
    if habilidades and con_habilidades:
        salida += _seccion(_g("Habilidades", "Abilities")) + html_habilidades(wf)
    return salida


def html_habilidades(wf: dict | None) -> str:
    """Las habilidades de un warframe, numeradas y con su descripcion (sin titulo)."""
    habilidades = (wf or {}).get("habilidades") or []
    if not habilidades:
        return ""
    p = PALETA
    castellano = es_castellano()
    filas = []
    for i, h in enumerate(habilidades, start=1):
        nombre = (h.get("es") if castellano else "") or h["en"]
        desc = (h.get("desc_es") if castellano else "") or h.get("desc_en") or ""
        filas.append(f"<tr><td valign='top' style='color:{p['suave']}'>{i}</td>"
                     f"<td><b>{html.escape(nombre)}</b><br>"
                     f"<span style='color:{p['suave']}'>{html.escape(desc)}</span></td></tr>")
    return _tabla(filas)


def bloque_efecto(datos: dict, compacto: bool = False, es_mod: bool = True, titulo: bool = True) -> str:
    """Efecto de un mod o arcano: al maximo arriba y, en la ficha completa, rango a rango."""
    efectos = detalles.efecto_en_idioma(datos.get("efecto"), es_castellano())
    if not efectos:
        return ""
    p = PALETA
    maximo = len(efectos) - 1
    extra = []
    if es_mod:
        polaridad = POLARIDADES.get((datos.get("polaridad") or "").lower(), datos.get("polaridad") or "")
        if polaridad:
            extra.append(html.escape(_g("Polaridad", "Polarity")) + f" <b>{html.escape(polaridad)}</b>")
        if datos.get("drenaje") is not None:
            drenaje = int(datos["drenaje"])
            # El coste sube uno por rango: de base a base + rango maximo.
            valor = f"{drenaje}&ndash;{drenaje + maximo}" if maximo else str(drenaje)
            extra.append(html.escape(_g("Capacidad", "Capacity")) + f" <b>{valor}</b>")
        if datos.get("compat"):
            extra.append(html.escape(_g("Para", "For")) + f" <b>{html.escape(datos['compat'])}</b>")
    al_maximo = html.escape(efectos[-1]).replace("\n", "<br>")
    titulo_max = html.escape(_g("Al rango máximo", "At max rank")) + f" ({maximo})"
    if compacto:
        return (f"<div style='margin-top:4px'><span style='color:{p['suave']}'>{titulo_max}:</span> "
                f"{al_maximo}</div>")
    salida = _seccion(_g("Efecto", "Effect")) if titulo else ""
    salida += f"<div style='margin:2px 0 4px 4px'><span style='color:{p['suave']}'>{titulo_max}:</span> <b>{al_maximo}</b></div>"
    if extra:
        salida += f"<div style='margin:0 0 6px 4px;color:{p['suave']}'>{' &middot; '.join(extra)}</div>"
    if len(efectos) > 1:
        filas = [
            f"<tr><td width='70' valign='top' style='color:{p['suave']}'>"
            f"{html.escape(_g('Rango', 'Rank'))} {rango}</td>"
            f"<td>{html.escape(texto).replace(chr(10), '<br>')}</td></tr>"
            for rango, texto in enumerate(efectos)
        ]
        salida += _tabla(filas)
    return salida


def bloque_fuentes_compacto(con: sqlite3.Connection | None, item_id: int | None, maximo: int = 3,
                            saltar: int = 1) -> str:
    """Otros buenos sitios donde sale, con su probabilidad, para la vista compacta desplegada.

    La vista compacta ya ensena el mejor sitio en su linea de "donde"; por eso se salta el
    primero (`saltar`) y se dan los `maximo` siguientes.

    Una pieza prime: sus mejores reliquias fuera de boveda con la probabilidad en Intacta
    y en Radiante. Lo demas: las primeras fuentes de `relaciones.fuentes_de` (ya vienen de
    mejor a peor) con rotacion, probabilidad y tiempo medio si se puede estimar.
    """
    if con is None or not item_id:
        return ""
    p = PALETA
    filas = []
    reliquias = relaciones.reliquias_de(con, item_id, incluir_vaulted=False)
    for r in reliquias[saltar:saltar + maximo]:
        probs = " &middot; ".join(
            f"{html.escape(glosa(indice.traducir(con, 'refinamiento', ref), ref))} <b>{r['probabilidades'][ref]:.1f}%</b>"
            for ref in ("Intact", "Radiant") if ref in r["probabilidades"]
        )
        nombre = html.escape(r.get("nombre_es") if es_castellano() and r.get("nombre_es") else r.get("nombre_en") or "")
        filas.append(f"<a style='color:{p['texto']};text-decoration:none' href='item:{r['reliquia_id']}'>"
                     f"<b>{nombre}</b></a> <span style='color:{p['suave']}'>{probs}</span>")
    if not reliquias:
        for f in relaciones.fuentes_de(con, item_id)[saltar:saltar + maximo]:
            trozos = [f"<b>{html.escape(f.get('donde') or f.get('origen_texto') or '')}</b>"]
            if f.get("mision"):
                trozos.append(html.escape(f["mision"]))
            if f.get("rotacion"):
                trozos.append(html.escape(glosa(indice.traducir(con, "rotacion", f["rotacion"]), f["rotacion"])))
            prob = f.get("probabilidad_efectiva") or f.get("probabilidad")
            if prob:
                trozos.append(f"{prob:.1f}%")
            tiempo = eficiencia.texto_minutos(f.get("minutos_medios"))
            if tiempo:
                trozos.append(html.escape(tiempo))
            filas.append(" &middot; ".join(trozos))
    if not filas:
        return ""
    return (f"<div style='margin-top:6px;color:{p['suave']}'>{html.escape(t('Tambien sale en:'))}</div>"
            + "".join(f"<div style='margin-left:8px'>{f}</div>" for f in filas))
