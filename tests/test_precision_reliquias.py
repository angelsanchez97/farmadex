"""Campana de precision (zona reliquias): lo que fallaba en el banco grande y como se arreglo.

Banco en el scratchpad (precision/reliquias, cursor, hover, vista); aqui solo las reglas,
con lecturas falsas, para que no vuelvan a romperse.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from farmadex.captura import cursor, recompensas_rapidas as rapidas, reliquia_hover as RH, vista  # noqa: E402
from farmadex.captura.ocr import Leido, Reconocido  # noqa: E402
from farmadex.captura.pantalla import Region  # noqa: E402


def _l(texto, x, y, ancho, alto, conf=0.9):
    return Leido(texto, x, y, ancho, alto, conf)


# -- objeto bajo el cursor ------------------------------------------------------------------


def test_region_mas_baja_estira_hacia_abajo_sin_salirse_del_juego():
    juego = Region(0, 0, 1920, 1080)
    r = cursor.region_mas_baja(Region(650, 300, 620, 170), juego)
    assert (r.x, r.y, r.ancho) == (650, 300, 620) and r.alto == int(170 * cursor.FACTOR_RECUADRO_BAJO)
    # Pegado al borde de abajo: no se sale.
    r = cursor.region_mas_baja(Region(650, 900, 620, 170), juego)
    assert r.y + r.alto == 1080 and r.alto == 180  # solo hasta el borde del juego


def test_alineados_ignora_los_avisos_de_recogida():
    recogido = SimpleNamespace(caja=(100, 120, 120, 12), puntuacion=100, item_id=5, nombre="Steel Essence",
                               texto_ocr="+1SteelEssence")
    pieza = SimpleNamespace(caja=(100, 80, 120, 12), puntuacion=90, item_id=7, nombre="Larkspur", texto_ocr="Larkspur")
    assert [r.item_id for r in cursor.alineados([recogido, pieza], (150, 60), 620)] == [7]


def test_con_el_raton_en_el_dibujo_se_mira_mas_abajo(monkeypatch):
    """Sobre el dibujo de la tarjeta de recompensa el nombre queda fuera del recuadro normal:
    con el recuadro estirado hacia abajo se lee (banco: de 8/34 a 33/34)."""
    from farmadex.captura.cursor import LectorCursor

    lector = LectorCursor()
    monkeypatch.setattr(lector, "_preparado", lambda: True)
    monkeypatch.setattr(cursor.pantalla, "region_juego", lambda: Region(0, 0, 1920, 1080))
    monkeypatch.setattr(cursor.pantalla, "_posicion_cursor", lambda: (960, 356))
    monkeypatch.setattr(cursor.pantalla, "region_alrededor_del_cursor", lambda w, h, limite=None: Region(650, 271, w, h))
    capturas = []
    monkeypatch.setattr(cursor.pantalla, "capturar", lambda r: capturas.append(r) or object())
    nombre = SimpleNamespace(caja=(260, 160, 200, 20), puntuacion=100, item_id=9, nombre="Fang Prime Plano",
                             texto_ocr="Plano De Fang Prime")
    monkeypatch.setattr(lector, "_leer_protegido", lambda imagen, umbral: [] if len(capturas) == 1 else [nombre])
    abiertos = []
    lector.encontrado.connect(lambda i, n: abiertos.append(i))
    lector.leer_solicitud(0)
    assert abiertos == [9] and len(capturas) == 2 and capturas[1].alto > capturas[0].alto


# -- tabla de reliquia al pasar el raton ----------------------------------------------------


def test_una_g_minuscula_en_el_codigo_es_un_nueve():
    assert RH.reliquias_en_texto("LithPgRelic") == [("Lith P9", None)]
    assert RH.reliquias_en_texto("Lith P9 Relic") == [("Lith P9", None)]
    assert RH.reliquias_en_texto("Axi G6 Relic") == [("Axi G6", None)]  # la G mayuscula sigue siendo letra


def test_codigo_cerrado_solo_si_le_sigue_texto():
    assert RH.codigo_cerrado("NeoG6Relic-PossibleRewards")
    assert RH.codigo_cerrado("Lith G13 Relic")
    assert not RH.codigo_cerrado("Relique Lith G1")  # cortado: podria ser G13


def test_una_linea_cortada_por_la_derecha_vale_si_el_codigo_esta_cerrado():
    nombres = {"Neo G6": 3, "Lith G1": 4, "Lith G13": 5}
    pegada = [_l("Neo G6 Relic -Possible Rewards", 0, 40, 200, 14)]  # toca el borde derecho (ancho 200)
    assert RH.elegir_reliquia(pegada, (50, 45), (200, 150), nombres).reliquia_id == 3
    cortada = [_l("Relique Lith G1", 60, 40, 140, 14)]
    assert RH.elegir_reliquia(cortada, (100, 45), (200, 150), nombres) is None


def test_dos_lecturas_tienen_que_coincidir_y_una_tercera_desempata():
    c = SimpleNamespace(reliquia_id=1, refinamiento=None, nombre="Lith A1")
    otra = SimpleNamespace(reliquia_id=2, refinamiento=None, nombre="Lith A7")
    imagen = np.zeros((300, 400, 3), np.uint8)
    # Coinciden a la primera: dos lecturas.
    res, n = RH.leer_contrastando(lambda img: [], imagen, lambda lineas: c)
    assert res[0] == 1 and n == 2
    # Discrepan y la tercera decide.
    turnos = iter([c, otra, c])
    res, n = RH.leer_contrastando(lambda img: [], imagen, lambda lineas: next(turnos))
    assert res[0] == 1 and n == 3
    # Tres distintas: nada (mejor ninguna reliquia que una inventada).
    turnos = iter([c, otra, None])
    res, n = RH.leer_contrastando(lambda img: [], imagen, lambda lineas: next(turnos))
    assert res is None and n == 3


def test_el_recorte_pequeno_se_lee_a_escalas_mayores():
    escalas = []

    def leer(img):
        escalas.append(img.shape[0])
        return []

    turnos = iter([SimpleNamespace(reliquia_id=i, refinamiento=None, nombre=str(i)) for i in (1, 2, 3)])
    RH.leer_contrastando(leer, np.zeros((180, 240, 3), np.uint8), lambda lineas: next(turnos))
    assert escalas == [270, 360, 450]  # 1,5x, 2x y 2,5x de 180


# -- fila de nombres de las recompensas -----------------------------------------------------


def test_una_tarjeta_sin_identificar_en_la_fila_pide_la_franja(monkeypatch):
    class CasadorFalso:
        def casar(self, texto):
            return (None, "", 0.0) if "Xyzzy" in texto else (11, "Fang Prime Plano", 100.0)

    ventana = Region(0, 0, 1920, 1080)
    lineas = [_l("Plano De Fang Prime", 100, 20, 200, 25), _l("Plano Xyzzy Prime", 700, 20, 200, 25)]
    monkeypatch.setattr(rapidas, "leer_fila", lambda imagen, motor: [Leido(**vars(l)) for l in lineas])
    monkeypatch.setattr(rapidas, "repartir", lambda *a: None)
    veces = []

    def lento(ventana, tiempos):
        veces.append(1)
        return [Reconocido("a", 11, "Fang Prime Plano", 100.0, (500, 440, 200, 25)),
                Reconocido("b", 12, "Orthos Prime Plano", 100.0, (1100, 440, 200, 25))]

    lectura = rapidas.leer_pantalla(lambda r: np.zeros((60, 1300, 3), np.uint8), ventana, object(), CasadorFalso(),
                                    None, lento)
    assert veces == [1] and lectura.via == "franja" and [r.item_id for r in lectura.recompensas] == [11, 12]


# -- precio al ver un objeto ----------------------------------------------------------------


def test_el_titulo_se_recorta_hasta_mas_alla_del_icono(monkeypatch):
    """"ACCELTRA PRIME BLUEPRINT" a 1440p seguia 0,065 h a la derecha del icono y se leia
    "BLUEPR": el recorte del titulo llega ahora hasta el borde del recuadro."""
    v = vista.VigiaVistas("rapidocr", precio=True, rivens=False, builds=False)
    v.casador = SimpleNamespace(casar=lambda texto, umbral=88: (None, "", 0.0))
    anchos = []

    class Motor:
        def leer_tira(self, trozo):
            anchos.append(trozo.shape[1])
            return []

    v.motor = Motor()
    h = 1440
    imagen = np.zeros((int(h * 0.75), int(h * 1.24), 3), np.uint8)
    icono = vista.IconoEncontrado(x=600, y=400, lado=40, puntuacion=0.95) if "ancho" not in vista.IconoEncontrado.__dataclass_fields__ \
        else vista.IconoEncontrado(x=600, y=400, lado=40, puntuacion=0.95, ancho=40)
    v._leer_titulo(imagen, Region(0, 0, imagen.shape[1], imagen.shape[0]), Region(0, 0, 2560, h), icono, 500, 450, 0.0)
    assert anchos and anchos[0] >= 600 + 40 + int(h * 0.09) - (600 - int(h * vista.TITULO_IZQ_REL))


def test_un_titulo_que_acaba_en_punto_no_es_un_objeto():
    """"BUSCAR..." (la caja de busqueda del inventario en castellano) casaba con el mod Fetch."""
    casador = SimpleNamespace(casar=lambda texto, umbral=88: (5, "Buscar", 100.0))
    lectura = vista.interpretar_titulo([_l("BUSCAR...", 0, 0, 80, 12)], [], casador)
    assert lectura.item_id is None and "punto" in lectura.motivo
    assert vista.interpretar_titulo([_l("BUSCAR", 0, 0, 80, 12)], [], casador).item_id == 5


# -- recompensas: solo lo que puede salir de una reliquia, y nada desaparece --------------------


def test_la_tarjeta_cortada_no_casa_con_un_mod(con):
    """Banco: "Canon DeLe" (de "Cañon De Lex Prime", cortado) salia como el mod "Cañoneo"."""
    from farmadex.captura.ocr import Casador
    from farmadex.captura.reliquias import CATEGORIAS_RECOMPENSA
    from test_captura import _insertar

    ids = _insertar(con, [
        ("/m/Cannonade", "Cannonade", "Cañoneo", "Mods", None, None),
        ("/r/Ferrite", "Ferrite", "Ferrita", "Resources", None, None),
        ("/p/LexPrime", "Lex Prime", "Lex Prime", "Secondary", None, None),
        ("/p/LexPrime/B", "Barrel", "Cañón", "Secondary", "/p/LexPrime", 45),
        ("/p/LexPrime/R", "Receiver", "Receptor", "Secondary", "/p/LexPrime", 15),
    ])
    catalogo = Casador(con, CATEGORIAS_RECOMPENSA)
    assert catalogo.casar("Canon DeLe", 80)[0] == ids["/m/Cannonade"]  # el catalogo entero si se confunde
    piezas = rapidas.catalogo_de_piezas(catalogo, con)
    assert rapidas.CasadorEscalonado(piezas).casar("Canon DeLe")[0] is None
    assert piezas.casar("Ferrita", 80)[0] is None
    assert rapidas.CasadorEscalonado(piezas).casar("Cañón De Lex Prime")[0] == ids["/p/LexPrime/B"]
    assert piezas.casar("Lex Prime", 80)[0] != ids["/p/LexPrime"]  # nunca el objeto entero


def test_parece_nombre_admite_cifras_sueltas_del_ocr_pero_no_contadores():
    assert rapidas.parece_nombre("Bupmpaim:Mo3r")  # "Вирм Прайм: Мозг" leido con letras latinas
    assert rapidas.parece_nombre("aHTa3MapaiM: pueMHuK")
    assert rapidas.parece_nombre("Plano De Forma")
    assert not rapidas.parece_nombre("x13")
    assert not rapidas.parece_nombre("15")
    assert not rapidas.parece_nombre("2 X 100")


def test_tres_tarjetas_en_ruso_salen_las_tres_sin_identificar(con):
    """Banco (pfD-4-jzAZQ, 3440x1440, ruso): de tres tarjetas salia una; ahora las tres, sin
    reconocer, en su sitio. El indice no tiene nombres en ruso: no se inventa ninguna."""
    from farmadex.captura.ocr import Casador
    from farmadex.captura.reliquias import CATEGORIAS_RECOMPENSA

    ventana = Region(0, 0, 3440, 1440)
    region = rapidas.region_fila(ventana)
    lineas = [_l("DepCTOHpaM:CTBON", 207, 20, 265, 30), _l("aHTa3MapaiM:", 536, 5, 205, 30),
              _l("pueMHuK", 580, 40, 118, 30), _l("Bupmpaim:Mo3r", 833, 20, 215, 30)]
    grupos = rapidas.repartir(lineas, ventana, region, None)
    fila = rapidas.casar_fila(lineas, rapidas.CasadorEscalonado(Casador(con, CATEGORIAS_RECOMPENSA)), 4, grupos)
    assert [r.item_id for r in fila] == [rapidas.SIN_IDENTIFICAR] * 3
