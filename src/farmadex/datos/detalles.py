"""Lo que la ficha ensena de un objeto ademas de donde sale.

WFCD trae en cada objeto datos que hasta ahora se tiraban al importar: las estadisticas
de las armas (critico, estado, cadencia, dano por tipo...), la disposicion de riven, el
efecto de cada mod y de cada arcano rango a rango (tambien en castellano, en i18n_es) y
las habilidades de los warframes. Se guardan tal cual, un JSON por objeto en la tabla
`detalles`, porque no sirven para buscar: solo para pintarlos en la ficha.

Un indice construido antes de existir la tabla se sigue pudiendo leer: `leer` devuelve
un diccionario vacio y la ficha sale como antes.
"""

from __future__ import annotations

import json
import re
import sqlite3

# Categorias de WFCD que son armas (las de Archwing y las de centinela tambien).
CATEGORIAS_ARMA = frozenset({
    "Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee", "SentinelWeapons",
})
CATEGORIAS_CUERPO_A_CUERPO = frozenset({"Melee", "Arch-Melee"})

# Tipos de dano en el orden en que los ensena el juego. Los drenajes (shieldDrain...) y
# "cinematic" son internos y no se pintan.
TIPOS_DANO = (
    "impact", "puncture", "slash", "heat", "cold", "electricity", "toxin", "blast",
    "radiation", "gas", "magnetic", "viral", "corrosive", "void", "tau", "true",
)

# "<DT_FIRE_COLOR>Calor", "<LOWER_IS_BETTER>", "<ACTIVATE_ABILITY_1>": marcas del juego
# para pintar iconos y colores. El texto de al lado ya dice el elemento, asi que se quitan.
RE_MARCA = re.compile(r"<[^<>]{1,40}>")
# "|DAMAGE| %": huecos que el juego rellena con el valor del rango; sin el no significan nada.
RE_HUECO = re.compile(r"\|[A-Z_0-9]+\|")


def limpiar(texto) -> str:
    """Texto del juego sin marcas de icono, con saltos de linea de verdad."""
    if not isinstance(texto, str):
        return ""
    t = texto.replace("\\n", "\n").replace("\r\n", "\n").replace("<LINE_SEPARATOR>", "\n")
    t = RE_MARCA.sub("", t)
    lineas = [re.sub(r"[ \t]+", " ", linea).strip() for linea in t.split("\n")]
    return "\n".join(linea for linea in lineas if linea)


def _efectos(level_stats) -> list[str]:
    """Una cadena por rango (rango 0 primero). Las lineas repetidas dentro de un rango se
    quitan: los arcanos repiten '+1 Revivir arcano' como linea suelta y dentro del texto."""
    if not isinstance(level_stats, list):
        return []
    salida = []
    for nivel in level_stats:
        stats = nivel.get("stats") if isinstance(nivel, dict) else None
        if not isinstance(stats, list):
            continue
        lineas: list[str] = []
        for s in stats:
            for linea in limpiar(s).split("\n"):
                if linea and linea not in lineas:
                    lineas.append(linea)
        salida.append("\n".join(lineas))
    return salida if any(salida) else []


def _num(valor):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return round(float(valor), 4)


def _texto(valor) -> str | None:
    return (valor.strip() or None) if isinstance(valor, str) else None


def _arma(obj: dict, categoria: str) -> dict:
    dano = obj.get("damage") if isinstance(obj.get("damage"), dict) else {}
    arma = {
        "critico": _num(obj.get("criticalChance")),
        "mult_critico": _num(obj.get("criticalMultiplier")),
        "estado": _num(obj.get("procChance")),
        "cadencia": _num(obj.get("fireRate")),
        "cargador": _num(obj.get("magazineSize")),
        "recarga": _num(obj.get("reloadTime")),
        "multidisparo": _num(obj.get("multishot")),
        "precision": _num(obj.get("accuracy")),
        "gatillo": _texto(obj.get("trigger")),
        "ruido": _texto(obj.get("noise")),
        "maestria": _num(obj.get("masteryReq")),
        # Disposicion de riven: 1 a 5 puntos, y el multiplicador exacto (omegaAttenuation).
        "disposicion": _num(obj.get("disposition")),
        "riven": _num(obj.get("omegaAttenuation")),
        "dano_total": _num(obj.get("totalDamage")),
        "dano": {t: _num(dano[t]) for t in TIPOS_DANO if _num(dano.get(t))},
        "cuerpo_a_cuerpo": categoria in CATEGORIAS_CUERPO_A_CUERPO,
    }
    if categoria in CATEGORIAS_CUERPO_A_CUERPO:
        arma["alcance"] = _num(obj.get("range"))
        arma["pesado"] = _num(obj.get("heavyAttackDamage"))
    return {k: v for k, v in arma.items() if v not in (None, {}, "")}


def _warframe(obj: dict, trad: dict) -> dict:
    wf = {
        "vida": _num(obj.get("health")),
        "escudo": _num(obj.get("shield")),
        "armadura": _num(obj.get("armor")),
        "energia": _num(obj.get("power")),
        "velocidad": _num(obj.get("sprintSpeed")),
        "maestria": _num(obj.get("masteryReq")),
    }
    pasiva_en = limpiar(obj.get("passiveDescription"))
    pasiva_es = limpiar(trad.get("passiveDescription"))
    # Una pasiva con huecos ("|DAMAGE| % mas") no se entiende sin los numeros: fuera.
    if pasiva_en and not RE_HUECO.search(pasiva_en):
        wf["pasiva"] = {"en": pasiva_en, "es": pasiva_es if not RE_HUECO.search(pasiva_es) else ""}
    traducidas = {
        h.get("abilityUniqueName"): h for h in trad.get("abilities") or [] if isinstance(h, dict)
    }
    habilidades = []
    for h in obj.get("abilities") or []:
        if not isinstance(h, dict):
            continue
        es = traducidas.get(h.get("abilityUniqueName") or h.get("uniqueName")) or {}
        nombre_en = limpiar(h.get("abilityName") or h.get("name"))
        if not nombre_en:
            continue
        habilidades.append({
            "en": nombre_en, "es": limpiar(es.get("abilityName")),
            "desc_en": limpiar(h.get("description")), "desc_es": limpiar(es.get("description")),
        })
    if habilidades:
        wf["habilidades"] = habilidades
    return {k: v for k, v in wf.items() if v not in (None, "", [])}


def extraer(obj: dict, categoria: str, trad: dict | None = None) -> dict:
    """Los detalles de un objeto de WFCD que merece la pena ensenar; vacio si no hay nada.

    `trad` es su entrada de i18n_es ({"name", "levelStats", "abilities"...}).
    """
    trad = trad if isinstance(trad, dict) else {}
    salida: dict = {}
    if categoria in CATEGORIAS_ARMA:
        arma = _arma(obj, categoria)
        if arma:
            salida["arma"] = arma
    elif categoria == "Warframes":
        wf = _warframe(obj, trad)
        if wf:
            salida["warframe"] = wf
    elif categoria in ("Mods", "Arcanes"):
        efecto_en = _efectos(obj.get("levelStats"))
        if efecto_en:
            efecto = {"en": efecto_en}
            efecto_es = _efectos(trad.get("levelStats"))
            if len(efecto_es) == len(efecto_en):
                efecto["es"] = efecto_es
            datos = {"efecto": efecto, "rareza": _texto(obj.get("rarity"))}
            if categoria == "Mods":
                datos.update({
                    "polaridad": _texto(obj.get("polarity")),
                    "drenaje": _num(obj.get("baseDrain")),
                    "rango_max": _num(obj.get("fusionLimit")),
                    "compat": _texto(obj.get("compatName")),
                })
            salida["mod" if categoria == "Mods" else "arcano"] = {
                k: v for k, v in datos.items() if v is not None
            }
    return salida


def guardar(con: sqlite3.Connection, item_id: int, datos: dict) -> None:
    """Mezcla `datos` con lo que ya tuviera el objeto (el codigo de un glifo llega aparte)."""
    if not datos:
        return
    previo = leer(con, item_id)
    previo.update(datos)
    con.execute(
        "INSERT OR REPLACE INTO detalles (item_id, datos) VALUES (?, ?)",
        (item_id, json.dumps(previo, ensure_ascii=False)),
    )


def leer(con: sqlite3.Connection, item_id: int | None) -> dict:
    """Los detalles de un objeto; vacio si no tiene o si el indice es de antes de la tabla."""
    if not item_id:
        return {}
    try:
        fila = con.execute("SELECT datos FROM detalles WHERE item_id = ?", (item_id,)).fetchone()
    except sqlite3.Error:
        return {}
    if not fila:
        return {}
    try:
        datos = json.loads(fila[0])
    except (TypeError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def efecto_en_idioma(efecto: dict | None, castellano: bool) -> list[str]:
    """El efecto por rango en castellano si toca y lo hay; si no, el ingles del juego."""
    if not isinstance(efecto, dict):
        return []
    if castellano and efecto.get("es"):
        return list(efecto["es"])
    return list(efecto.get("en") or [])
