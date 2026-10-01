"""La cabecera de la pantalla de mejoras tal como se ve en el PC de un jugador de verdad.

Capturas reales (`fixtures/cabeceras_reales/`, solo la esquina de arriba del juego):
- la interfaz del juego con un tema de colores propio: "MEJORAS/" en amarillo y el nombre
  en rojo vivo sobre azul oscuro, con la letra grande y muy espaciada;
- un medidor de rendimiento (temperaturas, milisegundos) pintado encima de la esquina, que
  pisa el principio de "MEJORAS".

Con eso el lector veia "WESJORAS/TORXICAS DOBLESCOEN" o "ASI NEKROS PRIME [30]", no
reconocia la cabecera y dejaba el equipo sin identificar. Peor: la 0.6.10 llego a dar un
equipo que no era (un "PRINE [30]", resto de "NEKROS PRIME [30]", como el arma "Pride").
Aqui estan los dos arreglos: leer bien esa cabecera y no identificar nunca un equipo con un
texto que no dice cual es.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from farmadex.captura import builds as B
from farmadex.captura import vista as V
from farmadex.captura.ocr import Leido, MotorOCR, unir_filas

from conftest import FIXTURES
from test_captura import _insertar

REALES = FIXTURES / "cabeceras_reales"
EQUIPOS = [
    ("/s/DualCodaTorxica", "Dual Coda Torxica", "Torxicas Dobles Coda", "Secondary"),
    ("/w/NekrosPrime", "Nekros Prime", "Nekros Prime", "Warframes"),
    ("/w/Nekros", "Nekros", "Nekros", "Warframes"),
    ("/w/InarosPrime", "Inaros Prime", "Inaros Prime", "Warframes"),
    ("/w/Inaros", "Inaros", "Inaros", "Warframes"),
    ("/w/Qorvex", "Qorvex", "Qorvex", "Warframes"),
    ("/w/ExcaliburUmbra", "Excalibur Umbra", "Excalibur Umbra", "Warframes"),
    ("/w/Excalibur", "Excalibur", "Excalibur", "Warframes"),
    ("/w/Limbo", "Limbo", "Limbo", "Warframes"),
    ("/w/ValkyrPrime", "Valkyr Prime", "Valkyr Prime", "Warframes"),
    ("/m/Pride", "Pride", "Pride", "Melee"),
    ("/m/BoPrime", "Bo Prime", "Bo Prime", "Melee"),
    ("/m/WarPrime", "War Prime", "War Prime", "Melee"),
    ("/m/VenkaPrime", "Venka Prime", "Venka Prime", "Melee"),
    ("/m/PrismaSkana", "Prisma Skana", "Skana Prisma", "Melee"),
    ("/m/Skana", "Skana", "Skana", "Melee"),
    ("/p/KuvaBramma", "Kuva Bramma", "Bramma Kuva", "Primary"),
    ("/p/CodaBubonico", "Coda Bubonico", "Bubonico Coda", "Primary"),
    ("/p/Bubonico", "Bubonico", "Bubonico", "Primary"),
    ("/p/TenetArcaPlasmor", "Tenet Arca Plasmor", "Arca Plasmor Tenet", "Primary"),
    ("/p/ArcaPlasmor", "Arca Plasmor", "Arca Plasmor", "Primary"),
    ("/s/Akbronco", "Akbronco", "Akbronco", "Secondary"),
    ("/s/Bronco", "Bronco", "Bronco", "Secondary"),
    ("/p/Sporothrix", "Sporothrix", "Sporothrix", "Primary"),
    ("/p/CodaSporothrix", "Coda Sporothrix", "Sporothrix Coda", "Primary"),
    ("/s/Atomos", "Atomos", "Atomos", "Secondary"),
    ("/x/Reach", "Reach", "Alcance", "Mods"),
]


@pytest.fixture()
def catalogo(con):
    _insertar(con, [(u, en, es, cat, None, None) for u, en, es, cat in EQUIPOS])
    return B.crear_casador(con), dict(con.execute("SELECT id, categoria FROM items"))


def _linea(texto: str, y: int = 40) -> Leido:
    return Leido(texto, 20, y, 900, 44, 0.9)


def _de_cabecera(texto: str, catalogo):
    nombre, linea = B.cabecera([_linea(texto)])
    equipo = B._casar_equipo(nombre, linea, *catalogo)
    return equipo.nombre if equipo is not None else None


# -- la palabra de la cabecera, con el medidor pisandola ---------------------------------------

# Lo que el OCR lee de verdad en la cabecera del jugador (a varios tamanos), y variantes.
@pytest.mark.parametrize("texto, nombre", [
    ("WESJORAS/TORXICAS DOBLESCOEN", "TORXICAS DOBLESCOEN"),
    ("AESJORAS/TORXICAS", "TORXICAS"),
    ("MEESJORAS/TORXICAS DOBLES CODA-[4O]", "TORXICAS DOBLES CODA-"),
    ("MESORAS/TORXICAS DOBLES CODX 4O) C", "TORXICAS DOBLES CODX 4O) C"),
    ("MEORAS/TORXIEAS MLS NT", "TORXIEAS MLS NT"),
    ("16.5 MEJORAS/ QORVEX [30]", "QORVEX"),
    ("165MEJORAS/QORVEX [30]", "QORVEX"),
    ("60 FPS UPGRADES / QORVEX [30]", "QORVEX"),
])
def test_cabecera_con_basura_delante(texto, nombre):
    hallado = B.es_cabecera(texto)
    assert hallado is not None and hallado.group(1).strip() == nombre
    assert V.es_cabecera_mejoras([_linea(texto)])


@pytest.mark.parametrize("texto", [
    "FehaRAS/RHINO PRIME [30]",        # tapada de verdad: no es la palabra (se trata aparte, tras la barra)
    "LEER LA PANTALLA DE MEJORAS",     # un boton de Farmadex
    "HORAS / 24",
    "RAS/ QORVEX",
    "114 785 985",
    "CONFIG A",
])
def test_no_es_la_palabra_de_la_cabecera(texto):
    assert B.es_cabecera(texto) is None


def test_idioma_con_la_palabra_pisada():
    assert B.idioma_de_cabecera("WESJORAS/TORXICAS DOBLESCOEN") == "es"
    assert B.idioma_de_cabecera("MEESJORAS/TORXICAS DOBLES CODA-[4O]") == "es"


# -- el equipo: lo leido de verdad da el equipo de verdad --------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("WESJORAS/TORXICAS DOBLESCOEN", None),                        # sin rango y con erratas: no basta
    ("MEESJORAS/TORXICAS DOBLES CODA-[4O]", "Torxicas Dobles Coda"),
    ("MEjORAS/TORXICAS DOBLES CODK [4O) C", "Torxicas Dobles Coda"),
    ("MESORAS/TORXICAS DOBLES CODX 4O) C", "Torxicas Dobles Coda"),
    ("AS/ NEKROS PRIME [30]", "Nekros Prime"),
    ("AS/NEKRDS PRIME [30]", "Nekros Prime"),
    ("MEJORAS/ NEKROS [30]", "Nekros"),                            # entero y exacto: es el Nekros
    ("MEJORAS/ EXCALIBUR UMBRA [30]", "Excalibur Umbra"),
    ("MEJORAS/ BRAMMA KUVA [40]", "Bramma Kuva"),
    ("16.5 MEJORAS/ QORVEX [30]", "Qorvex"),
])
def test_equipo_de_la_cabecera_real(catalogo, texto, esperado):
    nombre, equipo = B._equipo_de_franja([_linea(texto)], *catalogo)
    assert (equipo.nombre if equipo is not None else None) == esperado


def test_la_barra_leida_como_una_letra_y_el_principio_tapado(catalogo):
    """"ASI NEKROS PRIME [30]": lo que queda de "MEJORAS/ NEKROS PRIME [30]"."""
    assert B.nombres_ante_el_rango("ASI NEKROS PRIME [30]") == ["NEKROS PRIME"]
    assert "NEKROS PRIME" in B.nombres_ante_el_rango("ASINEKROS PRIME [30]")
    assert B.nombres_ante_el_rango("NEKROS PRIME") == []          # sin rango no se toca
    assert B.nombres_ante_el_rango("AS/ NEKROS PRIME [30]") == []  # con barra va por su camino
    for texto in ("ASI NEKROS PRIME [30]", "ASINEKROS PRIME [30]"):
        nombre, equipo = B._equipo_de_franja([_linea(texto)], *catalogo)
        assert equipo is not None and equipo.nombre == "Nekros Prime"
    # Con una errata ademas ("NEKRDS"), por este camino no se identifica: se relee la franja.
    assert B._equipo_de_franja([_linea("ASINEKRDS PRIME [30]")], *catalogo)[1] is None


# -- nunca un equipo que no es ------------------------------------------------------------------

GENERICAS = sorted(B.PALABRAS_VARIANTE) + [
    "MEJORAS", "UPGRADES", "AMELIORATIONS", "MELHORIAS", "APRIMORAMENTOS", "POTENZIAMENTI", "ULEPSZENIA",
    "CAPACIDAD", "CAPACITY", "CAPACITE", "KAPAZITAT", "CAPACIDADE", "POJEMNOSC", "BUSCAR", "SEARCH", "CHERCHER",
    "SUCHE", "PROCURAR", "CERCA", "TODOS", "ALL", "TOUS", "ALLE", "TUDO", "TUTTO", "RANGO", "RANK", "RANG", "NIVEAU",
    "NIVEL", "GRADO", "RANGA", "CONFIG", "CONFIG A", "AURA", "EXILUS", "ARCANO", "ARCANE", "MOD", "MODS", "DRENAJE",
    "DRAIN", "NOMBRE", "NAME", "POLARIDAD", "POLARITY", "POSTURA", "STANCE", "ACCIONES", "ACTIONS", "ARSENAL",
    "EQUIPAR", "EQUIP", "SALIR", "EXIT", "INCARNON", "RIVEN", "FORMA", "OROKIN", "MADURAI", "VAZARIN", "NARAMON",
    "PRINE", "PRlME", "PR1ME", "PRIMF", "E PRIME", "S PRIME", "R PRIME", "Y PRIME", "UMBRA", "KUVA", "TENET", "CODA",
]


@pytest.mark.parametrize("palabra", GENERICAS)
def test_una_palabra_generica_no_identifica_ningun_equipo(catalogo, palabra):
    """"PRIME [30]" (o "PRINE [30]", que dio "Pride" en la 0.6.10), "CODA", "UPGRADES"...:
    ni sola ni con el rango, ni con la barra delante, ni como resto de una cabecera tapada."""
    for texto in (palabra, f"{palabra} [30]", f"MEJORAS/ {palabra} [30]", f"AS/ {palabra} [30]", f"AS/ {palabra} [30",
                  f"MEJORAS / {palabra}", f"ASI {palabra} [30]"):
        nombre, equipo = B._equipo_de_franja([_linea(texto)], *catalogo)
        assert equipo is None, (texto, equipo.nombre)
        nombre, linea = B.cabecera([_linea(texto)])
        assert B._casar_equipo(nombre, linea, *catalogo) is None, texto
        assert B._casar_equipo(texto, None, *catalogo) is None, texto


def test_el_caso_pride(catalogo):
    """Captura real: de "…AS/ NEKROS PRIME [30]" la franja releida dio "AS/ PRINE [30 CO"."""
    lineas = [_linea("AS/ PRINE [30 CO回")]
    nombre, equipo = B._equipo_de_franja(lineas, *catalogo)
    assert equipo is None
    assert B.equipo_parecido("PRINE", *catalogo) is None and B.equipo_parecido("PRIDF", *catalogo) is None
    # El arma Pride se sigue reconociendo cuando su cabecera se lee entera.
    assert _de_cabecera("MEJORAS / PRIDE [30]", catalogo) == "Pride"


@pytest.mark.parametrize("texto", [
    "AS/ NEKROS",                       # sin el rango detras: puede ser un Nekros Prime cortado
    "MEJORAS/ NEKROS",
    "ASI NEKROS [30]",                  # sin la barra delante: no hay tope por delante
    "MEJORAS/ BUBONICO",                # ... o un Bubonico Coda
    "DA BUBONICO [30]",                 # "CODA" cortado
    "I ARCA PLASMOR [40]",
    "MEJORAS/ Y EXCALIBUR [30]",        # con una ficha quitada y hermanos de variante
    "ONCO [30]", "AS/ BRONCO",          # Bronco o Akbronco
    "MEJORAS/ ENANT PRIME [30]",        # resto de "REVENANT PRIME": no es Venka Prime
    "MEJORAS/ AR4 PRIME [30]",          # resto de "IVARA PRIME" con errata: no es War Prime
    "MEJORAS/ A SPOROTHRIX [30]",       # "CODA SPOROTHRIX" cortado: no es el Sporothrix
    "MEJORAS/ PRIMA SKANA [30]",        # "PRISMA" con una letra menos: no es otra variante
    "MEJORAS/ INEROS [30]",             # tan cerca de Inaros como de Nekros
    "MEJORAS/ LIM [30]", "MEJORAS/ LIMB0 PRIME [30]",
    "MEJORAS/ VALKYR [30]",             # solo existe Valkyr Prime en este catalogo: no se le pone
    "MEJORAS/ Alcance [30]",            # un mod
])
def test_un_nombre_cortado_o_dudoso_no_se_identifica(catalogo, texto):
    nombre, equipo = B._equipo_de_franja([_linea(texto)], *catalogo)
    assert equipo is None, equipo.nombre
    nombre, linea = B.cabecera([_linea(texto)])
    assert B._casar_equipo(nombre, linea, *catalogo) is None


CONFUSAS = {"I": "TL1", "T": "I7", "L": "I1", "O": "0DQ", "D": "O", "E": "FB", "M": "NW", "N": "MH", "S": "5", "A": "4",
            "R": "K", "K": "RX", "C": "G", "G": "C", "U": "V", "V": "UY", "B": "8E", "P": "F", "X": "K", "Y": "V"}


def test_barrido_de_erratas_y_cortes_nunca_da_otro_equipo(catalogo):
    """Para cada equipo: una letra mal leida, una letra de menos, el nombre cortado por
    delante o por detras y solo una de sus palabras. Sale el equipo de verdad o ninguno,
    salvo que lo que queda sea letra por letra el nombre de otro (eso no se puede saber)."""
    casador, categorias = catalogo
    nombres = {}
    for _u, en, es, cat in EQUIPOS:
        if cat not in ("Mods", "Arcanes"):
            for n in (en, es):
                nombres[n.upper()] = casador.casar(n, 100)[0]
    ids_de = {}
    for n, i in nombres.items():
        ids_de.setdefault(i, set()).add(n.replace(" ", ""))
    equivocados = []

    def comprobar(real: int, texto_linea: str, leido: str) -> None:
        nombre, equipo = B._equipo_de_franja([_linea(texto_linea)], casador, categorias)
        if equipo is None or equipo.item_id == real:
            return
        if leido.replace(" ", "") in ids_de[equipo.item_id]:
            return  # lo leido ES el nombre de otro equipo
        equivocados.append((texto_linea, equipo.nombre))

    for nombre, real in nombres.items():
        for i, c in enumerate(nombre):
            for otra in CONFUSAS.get(c, ""):
                errata = nombre[:i] + otra + nombre[i + 1:]
                comprobar(real, f"MEJORAS/ {errata} [30]", errata)
            if c != " ":
                menos = nombre[:i] + nombre[i + 1:]
                comprobar(real, f"MEJORAS/ {menos} [30]", menos)
        palabras = nombre.split()
        cortes = [nombre[q:] for q in range(1, min(7, len(nombre) - 2))] + [nombre[:-q] for q in range(1, min(7, len(nombre) - 2))]
        cortes += palabras if len(palabras) > 1 else []
        for corte in (c.strip() for c in cortes):
            for linea in (f"{corte} [30]", f"AS/ {corte}", f"AS/ {corte} [30]", f"MEJORAS/ {corte}", f"ASI {corte} [30]",
                          f"MEJORAS/ {corte} [30]"):
                # El ultimo es una cabecera entera: si el corte no es el nombre de nadie, nada.
                comprobar(real, linea, corte)
    assert not equivocados, equivocados[:20]


# -- la franja releida sin depender del color ----------------------------------------------------

def test_franjas_sin_color_dejan_claro_un_rojo_vivo():
    franja = np.zeros((40, 120, 3), np.uint8)
    franja[:] = (70, 35, 20)          # azul oscuro (BGR)
    franja[10:30, 20:100] = (30, 30, 235)  # letras rojas: en gris quedarian casi tan oscuras como el fondo
    gris = cv2.cvtColor(franja, cv2.COLOR_BGR2GRAY)
    fuerte, negativo = B.franjas_sin_color(franja)
    assert fuerte.shape == franja.shape and negativo.shape == franja.shape
    contraste_gris = int(gris[20, 60]) - int(gris[5, 5])
    contraste_fuerte = int(fuerte[20, 60, 0]) - int(fuerte[5, 5, 0])
    assert contraste_fuerte > 150 > contraste_gris
    assert int(negativo[20, 60, 0]) == 255 - int(fuerte[20, 60, 0])


class MotorDeColores:
    """La lectura normal de la franja da basura (tema rojo); la que no depende del color, el nombre."""

    def __init__(self):
        self.tiempos = {}
        self.sin_color = 0

    def leer(self, _franja):
        return [Leido("MEORAS/TORXIEAS MLS NT", 0, 0, 900, 40, 0.6)]

    def leer_tira(self, franja, alto_deteccion=None):
        self.sin_color += 1
        assert (franja[..., 0] == franja[..., 1]).all()  # gris: los tres canales iguales
        return [Leido("MEESJORAS/TORXICAS DOBLES CODA-[4O]", 0, 0, 900, 40, 0.75)]


def test_releer_la_cabecera_sin_color_solo_si_lo_normal_falla(catalogo):
    imagen = np.zeros((1440, 2560, 3), np.uint8)
    motor = MotorDeColores()
    texto, equipo = B._releer_cabecera(imagen, motor, *catalogo, [])
    assert equipo is not None and equipo.nombre == "Torxicas Dobles Coda"
    assert motor.sin_color == 1  # al primer acierto se para

    class MotorNormal(MotorDeColores):
        def leer(self, _franja):
            return [Leido("MEJORAS/ QORVEX [30]", 0, 0, 900, 40, 0.9)]

    motor = MotorNormal()
    texto, equipo = B._releer_cabecera(imagen, motor, *catalogo, [])
    assert equipo.nombre == "Qorvex" and motor.sin_color == 0  # sin lecturas de mas


# -- con el OCR de verdad sobre los recortes reales ----------------------------------------------

@pytest.fixture(scope="module")
def motor_real():
    motor = MotorOCR()
    motor.precalentar()
    return motor


@pytest.mark.slow
@pytest.mark.parametrize("fichero, esperado", [("torxicas_dobles_coda.png", "Torxicas Dobles Coda"),
                                               ("nekros_prime.png", "Nekros Prime")])
@pytest.mark.parametrize("alto", [1080, 1440, 2160])
def test_cabecera_real_del_jugador_con_el_ocr(catalogo, motor_real, fichero, esperado, alto):
    """La esquina real del juego (tema rojo y amarillo, medidor encima) puesta en una pantalla
    de cada tamano: el equipo sale, y nunca otro."""
    recorte = cv2.imdecode(np.fromfile(str(REALES / fichero), np.uint8), cv2.IMREAD_COLOR)
    escala = alto / 1440
    if escala != 1:
        recorte = cv2.resize(recorte, None, fx=escala, fy=escala,
                             interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_CUBIC)
    pantalla = np.full((alto, alto * 16 // 9, 3), (40, 25, 20), np.uint8)
    pantalla[: recorte.shape[0], : recorte.shape[1]] = recorte
    lineas = unir_filas([l for l in motor_real.leer_tira(pantalla, alto_deteccion=B.alto_de_deteccion(alto))
                         if l.confianza >= B.MINIMO_CONFIANZA])
    nombre, linea = B.cabecera(lineas)
    equipo = B._casar_equipo(nombre, linea, *catalogo)
    if equipo is None:
        for l in lineas:
            for texto in B.nombres_ante_el_rango(l.texto):
                equipo = equipo or B._casar_equipo(texto, l, *catalogo, entero=False)
    if equipo is None:
        _texto, equipo = B._releer_cabecera(pantalla, motor_real, *catalogo, lineas)
    assert equipo is not None and equipo.nombre == esperado


@pytest.mark.parametrize("texto, es", [
    ("ASI NEKROS PRIME [30]", True),        # leido de verdad en la pantalla del jugador
    ("ASI IEKROS PRIME3O]", True),
    ("RASINEKROS PRIME [30]", True),
    ("ESY EXCALIBUR [30]", True),           # "UPGRADES/" tapado
    ("NEKROS PRIME [30]", False),           # sin resto de la palabra ni barra
    ("PRIME [30]", False),
    ("ASI NEKROS PRIME", False),            # sin rango
    ("999.999.999 1888 3.205.804", False),
    ("Rhinnio Coleman [30]", False),
    ("CASI TODO LISTO (30)", False),
])
def test_resto_de_cabecera_para_la_lectura_sola(texto, es):
    assert B.es_resto_de_cabecera(texto) is es
    assert V.es_cabecera_mejoras([_linea(texto)]) is es
