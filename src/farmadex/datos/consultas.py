"""Lo que el usuario escribe en el buscador, antes de buscarlo.

La gente no escribe "citrine prime": escribe "como sacar citrine prime", "donde
farmear hepit" o "cual es el ultimo warframe". El indice solo sabe de nombres, asi que
aqui se quitan las muletillas de pregunta (en los cinco idiomas de la interfaz) y se
reconocen las preguntas por "lo nuevo", que no son un nombre sino una intencion.

Todo va sobre el texto ya normalizado (items.normalizar: minusculas, sin tildes ni
signos), asi que "¿Cómo sacar...?" y "como sacar" son lo mismo.
"""

from __future__ import annotations

from .items import normalizar

# Muletillas de pregunta que se quitan del principio. Las largas primero: "como se
# consigue" antes que "como". Sin tildes (van contra el texto normalizado).
MULETILLAS = sorted({
    # castellano
    "como sacar", "como saco", "como se saca", "como consigo", "como conseguir", "como se consigue",
    "como obtener", "como obtengo", "como se obtiene", "como farmear", "como farmeo", "como se farmea",
    "como hacer", "como hago", "como se hace", "como se juega", "como jugar", "como construir",
    "donde farmear", "donde farmeo", "donde se farmea", "donde sale", "donde salen", "donde cae",
    "donde caen", "donde consigo", "donde conseguir", "donde encuentro", "donde encontrar",
    "donde esta", "que suelta", "que es", "cual es", "quiero", "busco",
    # ingles
    "how to get", "how do i get", "how do you get", "how to farm", "how do i farm", "how to obtain",
    "how to make", "how to build", "how to do", "how do i do", "how to play", "where to farm",
    "where to get", "where to find", "where do i get", "where do i farm", "where does", "what is",
    "what drops", "whats",
    # frances
    "comment obtenir", "comment avoir", "comment farmer", "comment faire", "comment trouver",
    "comment jouer", "ou farmer", "ou trouver", "ou obtenir", "qu est ce que", "c est quoi",
    # aleman
    "wie bekomme ich", "wie bekommt man", "wie farme ich", "wie farmt man", "wie mache ich",
    "wie macht man", "wie spielt man", "wo farmen", "wo farme ich", "wo finde ich", "wo bekomme ich",
    "was ist",
    # portugues
    "como pegar", "como pego", "como obter", "como farmar", "como fazer", "onde farmar",
    "onde pegar", "onde conseguir", "onde encontrar", "onde fica", "o que e",
}, key=lambda m: (-len(m), m))

# Articulos que quedan delante tras quitar la muletilla ("como sacar el ultimo...").
ARTICULOS = {"el", "la", "los", "las", "un", "una", "lo", "the", "a", "an", "le", "les", "l",
             "der", "die", "das", "den", "o", "os", "as", "um", "uma", "de", "del", "do", "da"}

# "ultimo", "nuevo"... en los cinco idiomas: la pregunta es por lo mas reciente. Sin "nova"
# (portugues) a proposito: es una warframe, y "nova prime" dejaria de encontrarse.
MARCAS_NOVEDAD = {
    "ultimo", "ultima", "ultimos", "ultimas", "nuevo", "nueva", "nuevos", "nuevas", "reciente",
    "recientes", "latest", "newest", "new", "recent", "last", "dernier", "derniere", "derniers",
    "nouveau", "nouvelle", "nouveaux", "neueste", "neuester", "neuestes", "neuesten", "neu", "neue",
    "neuer", "neues", "neuen", "letzte", "letzter", "letztes", "novo", "novos", "novas",
}
# Frases que por si solas ya son "lo nuevo".
FRASES_NOVEDAD = {
    "lo nuevo", "novedades", "que hay de nuevo", "whats new", "what s new", "new stuff",
    "nouveautes", "quoi de neuf", "neuheiten", "was gibt es neues", "novidades", "o que ha de novo",
}
# Lo que se pide de lo nuevo -> filtro de novedades.py.
OBJETIVOS = {
    **dict.fromkeys(("warframe", "warframes", "frame", "frames"), "warframe"),
    **dict.fromkeys(("arma", "armas", "weapon", "weapons", "arme", "armes", "waffe", "waffen"), "arma"),
    **dict.fromkeys(("prime", "primes"), "prime"),
    **dict.fromkeys(("actualizacion", "update", "parche", "patch", "maj", "aktualisierung",
                     "atualizacao", "mise", "jour"), "todo"),
}


def limpiar(texto: str) -> str:
    """El texto sin la muletilla de pregunta del principio: 'como sacar citrine prime' ->
    'citrine prime'. Si no queda nada (o no habia muletilla), el texto de siempre."""
    normal = normalizar(texto)
    for muletilla in MULETILLAS:
        if normal == muletilla:
            break
        if normal.startswith(muletilla + " "):
            resto = normal[len(muletilla) + 1:].strip()
            return resto or texto.strip()
    return texto.strip()


def intencion_novedad(texto: str) -> str | None:
    """'warframe', 'arma', 'prime', 'warframe prime', 'arma prime' o 'todo' si el texto
    pregunta por lo mas nuevo ('ultimo warframe', 'new prime', 'novedades'); None si no.

    Conservador a proposito: cualquier palabra que no sea marca, objetivo o articulo
    ('new loka') lo descarta, para no tapar la busqueda normal de un objeto.
    """
    normal = normalizar(limpiar(texto))
    if normal in FRASES_NOVEDAD:
        return "todo"
    palabras = [p for p in normal.split() if p not in ARTICULOS]
    if not palabras or not any(p in MARCAS_NOVEDAD for p in palabras):
        return None
    objetivos = []
    for p in palabras:
        if p in MARCAS_NOVEDAD:
            continue
        if p not in OBJETIVOS:
            return None
        objetivos.append(OBJETIVOS[p])
    if not objetivos:
        return None if len(palabras) > 1 else "todo"
    tipo = "warframe" if "warframe" in objetivos else "arma" if "arma" in objetivos else ""
    prime = "prime" in objetivos
    if tipo and prime:
        return f"{tipo} prime"
    return tipo or ("prime" if prime else "todo")
