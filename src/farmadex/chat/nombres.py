"""Nombre escrito (o leido del chat) -> objeto de warframe.market, en todos los idiomas del indice.

Sale de lo que ya existe: la tabla `busqueda` del indice (un nombre normalizado por
objeto e idioma: en, es, fr, de, pt, it, pl, con el nombre del padre en las piezas) y
el `market_slug` que `online/market.py` casa en cada objeto. Aqui solo se montan
diccionarios para buscar en O(1):

1. el nombre tal cual (normalizado: minusculas, sin tildes ni signos);
2. sin importar el orden de las palabras ni las de relleno ("Plano de Neurópticas de
   Loki Prime" == "Loki Prime Neuroptics Blueprint");
3. lo mismo sin la palabra "plano"/"blueprint" (el mercado nombra las piezas con ella,
   el indice sin ella); solo si con ella no casa, para no confundir "Loki Prime
   Blueprint" (el plano principal) con "Loki Prime" (el set);
4. parecido (rapidfuzz), solo para lo leido con OCR y con un listón alto: si dos
   objetos distintos quedan casi igual de cerca, no se elige ninguno.

Nunca inventa: lo que no casa devuelve None y quien llama dice "no reconocido".
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..datos.items import normalizar
from ..registro_log import obtener

log = obtener("chat.nombres")

# Palabras que no distinguen un nombre de otro (articulos y preposiciones de los idiomas
# del indice). "de" une "Plano de Neurópticas de Loki Prime"; en ingles no hace falta.
RELLENO = frozenset("""
de del la el los las lo un una of the du des le les d l der die das den dem von vom
do da dos das di della dello delle dei degli al au aux z ze
""".split())
PALABRAS_PLANO = ("blueprint", "plano", "schema", "plan", "bauplan", "projeto", "progetto", "planos",
                  "projekt", "diagramme")
CATEGORIAS_ARMA = ("Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee")
UMBRAL_DIFUSO = 88.0
MARGEN_DIFUSO = 3.0


@dataclass(frozen=True, slots=True)
class Objeto:
    item_id: int
    slug: str | None  # None = no se comercia entre jugadores
    nombre_en: str
    nombre_es: str
    categoria: str
    padre_slug: str | None = None

    def nombre(self) -> str:
        from ..idiomas import es_castellano

        return (self.nombre_es or self.nombre_en) if es_castellano() else (self.nombre_en or self.nombre_es)

    @property
    def es_mod_o_arcano(self) -> bool:
        return self.categoria in ("Mods", "Arcanes")


def _es_pieza_con_agrietado(tipo: str | None, unico: str | None) -> bool:
    """Recamara de kitgun y punta de zaw: el agrietado lleva su nombre ("Catchmoon", "Plague Keewar")."""
    unico = unico or ""
    if tipo in ("Kitgun Component", "Pistol", "Rifle") and "/Barrel" in unico:
        return True
    return tipo == "Zaw Component" and "/Tip" in unico and "PvPVariant" not in unico


def _orden_libre(clave: str, quitar_plano: bool = False) -> str:
    palabras = [p for p in clave.split() if p not in RELLENO]
    if quitar_plano:
        palabras = [p for p in palabras if p not in PALABRAS_PLANO]
    return " ".join(sorted(palabras))


def _sin_plano(clave: str) -> str:
    return " ".join(p for p in clave.split() if p not in PALABRAS_PLANO)


class Resolutor:
    """Diccionarios nombre -> objeto montados una vez desde el indice (~0,2 s)."""

    def __init__(self, con):
        filas = con.execute(
            """
            SELECT i.id, i.market_slug, i.nombre_en, i.nombre_es, i.categoria,
                   p.nombre_en, p.nombre_es, p.market_slug, i.tipo, i.unique_name
              FROM items i LEFT JOIN items p ON p.id = i.padre_id
            """
        ).fetchall()
        self.objetos: dict[int, Objeto] = {}
        self.slugs: set[str] = set()
        armas: dict[str, str] = {}
        for iid, slug, n_en, n_es, cat, p_en, p_es, p_slug, tipo, unico in filas:
            nombre_en = f"{p_en} {n_en}" if p_en else (n_en or "")
            nombre_es = f"{p_es or p_en} {n_es or n_en}" if p_en else (n_es or n_en or "")
            self.objetos[iid] = Objeto(iid, slug, nombre_en, nombre_es, cat or "", p_slug)
            if slug:
                self.slugs.add(slug)
            if n_en and not p_en and (cat in CATEGORIAS_ARMA or _es_pieza_con_agrietado(tipo, unico)):
                armas.setdefault(normalizar(n_en), n_en)
        self.armas = armas
        self.exacto: dict[str, int] = {}
        self.libre: dict[str, int] = {}
        self.libre_sin_plano: dict[str, int] = {}
        ambiguos: dict[str, set[str]] = {}
        for texto, iid in con.execute("SELECT texto, item_id FROM busqueda"):
            if iid not in self.objetos or not texto:
                continue
            # Para no guardar tres veces lo mismo (son ~85.000 nombres), las tablas de orden
            # libre solo llevan las claves que cambian respecto a la anterior.
            libre = _orden_libre(texto)
            sin_plano = _orden_libre(texto, quitar_plano=True)
            self._meter(self.exacto, texto, iid, ambiguos)
            if libre and libre != texto:
                self._meter(self.libre, libre, iid, ambiguos)
            if sin_plano and sin_plano != libre:
                self._meter(self.libre_sin_plano, sin_plano, iid, ambiguos)
        # Una clave con dos objetos comerciables distintos no se usa: mejor "no reconocido".
        for tabla in (self.exacto, self.libre, self.libre_sin_plano):
            for clave in [c for c, i in tabla.items() if i == -1]:
                del tabla[clave]
        self._claves_difusas = [c for c, i in self.exacto.items() if self.objetos[i].slug]
        log.info("Nombres para el chat: %d claves, %d objetos comerciables, %d armas",
                 len(self.exacto), len(self.slugs), len(self.armas))

    def _meter(self, tabla: dict[str, int], clave: str, iid: int, ambiguos) -> None:
        previo = tabla.get(clave)
        if previo is None:
            tabla[clave] = iid
            return
        if previo == -1 or previo == iid:
            return
        a, b = self.objetos[previo], self.objetos[iid]
        if a.slug and b.slug and a.slug != b.slug:
            tabla[clave] = -1  # dos objetos que se venden por separado: ambiguo
        elif b.slug and not a.slug:
            tabla[clave] = iid  # entre un adorno y lo que se vende, lo que se vende

    # -- busquedas ------------------------------------------------------------------

    def buscar(self, texto: str) -> Objeto | None:
        """Casado exacto (con los pasos 1-3 del modulo). Sin parecidos."""
        clave = normalizar(texto)
        if not clave:
            return None
        libre = _orden_libre(clave)
        for tabla, k in ((self.exacto, clave), (self.libre, libre), (self.exacto, libre)):
            iid = tabla.get(k)
            if iid is not None:
                return self.objetos[iid]
        sin = _orden_libre(clave, quitar_plano=True)
        if sin and sin != libre:
            for tabla, k in ((self.exacto, _sin_plano(clave)), (self.libre_sin_plano, sin),
                             (self.libre, sin), (self.exacto, sin)):
                iid = tabla.get(k)
                if iid is not None:
                    return self.objetos[iid]
        else:
            iid = self.libre_sin_plano.get(libre)
            if iid is not None:
                return self.objetos[iid]
        return None

    def buscar_difuso(self, texto: str, umbral: float = UMBRAL_DIFUSO) -> Objeto | None:
        """Exacto y, si no, el nombre comerciable mas parecido si no hay otro casi igual de cerca."""
        exacto = self.buscar(texto)
        if exacto is not None:
            return exacto
        clave = normalizar(texto)
        if len(clave) < 4:
            return None
        from rapidfuzz import fuzz, process

        mejores = process.extract(clave, self._claves_difusas, scorer=fuzz.ratio, limit=6,
                                  score_cutoff=umbral - MARGEN_DIFUSO)
        if not mejores or mejores[0][1] < umbral:
            return None
        primero = self.objetos[self.exacto[mejores[0][0]]]
        for clave_otra, puntos, _ in mejores[1:]:
            otro = self.objetos[self.exacto[clave_otra]]
            if otro.slug != primero.slug and puntos >= mejores[0][1] - MARGEN_DIFUSO:
                log.debug("Parecido ambiguo para %r: %s / %s", texto, primero.slug, otro.slug)
                return None
        return primero

    def slug_de_set(self, obj: Objeto) -> str | None:
        """El slug del set al que pertenece (o que es) el objeto; None si no hay set."""
        for slug in (obj.slug, obj.padre_slug):
            if slug and slug.endswith("_set"):
                return slug
        if obj.slug and f"{obj.slug}_set" in self.slugs:
            return f"{obj.slug}_set"
        return None

    def arma_al_principio(self, palabras: list[str]) -> tuple[str, int] | None:
        """(nombre en ingles del arma, cuantas palabras ocupa) si el texto empieza por un arma."""
        for largo in range(min(4, len(palabras)), 0, -1):
            nombre = self.armas.get(" ".join(palabras[:largo]))
            if nombre:
                return nombre, largo
        return None


    def arma_parecida(self, palabras: list[str], umbral: float | None = None) -> tuple[str, int] | None:
        """Como `arma_al_principio` pero con una letra mal leida ("rsvnapse" -> Synapse).

        El OCR a veces lee el corchete de delante como una letra: se prueba tambien sin ella.
        Solo armas de una o dos palabras y con un parecido alto (80, o `umbral`), sin empate
        con otra arma.
        """
        from rapidfuzz import fuzz, process

        claves = self.__dict__.setdefault("_claves_armas", list(self.armas))
        for largo in (2, 1):
            if len(palabras) <= largo:
                continue
            trozo = " ".join(palabras[:largo])
            for prueba in dict.fromkeys((trozo, trozo[1:] if trozo[:1] in "rl1ijt(" else trozo)):
                if len(prueba) < 4:
                    continue
                mejores = process.extract(prueba, claves, scorer=fuzz.ratio, limit=2, score_cutoff=umbral or 80)
                if mejores and (len(mejores) == 1 or mejores[0][1] - mejores[1][1] >= 5):
                    return self.armas[mejores[0][0]], largo
        return None


# -- compartido -----------------------------------------------------------------------

_resolutor: Resolutor | None = None
_cerrojo = threading.Lock()


def resolutor() -> Resolutor | None:
    """El resolutor montado desde el indice instalado (una vez); None si no hay indice."""
    global _resolutor
    if _resolutor is not None:
        return _resolutor
    with _cerrojo:
        if _resolutor is None:
            from ..datos import indice

            if not indice.hay_indice():
                return None
            con = indice.conectar()
            try:
                _resolutor = Resolutor(con)
            except Exception:  # noqa: BLE001 - un indice raro no tumba la lectura del chat
                log.exception("No se pudieron montar los nombres para el chat")
                return None
            finally:
                con.close()
    return _resolutor


def olvidar() -> None:
    """Tras instalar un indice nuevo: se vuelve a montar al siguiente uso."""
    global _resolutor
    with _cerrojo:
        _resolutor = None


def precargar_en_segundo_plano() -> None:
    """Monta los diccionarios en un hilo para que el primer enlace no espere."""
    threading.Thread(target=resolutor, name="chat-nombres", daemon=True).start()
