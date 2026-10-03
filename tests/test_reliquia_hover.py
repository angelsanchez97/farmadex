"""La tabla de la reliquia bajo el raton en el juego: leer el nombre sin equivocarse y sin gastar.

Lo que importa: nunca ensenar una reliquia que no es (mejor nada), leer una sola vez
por parada del raton, no mirar fuera de las pantallas de reliquias (o sin la tecla),
y esconder la tarjeta al alejarse.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex.captura import reliquia_hover as RH  # noqa: E402
from farmadex.captura.ocr import Leido  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# -- texto -> nombre ------------------------------------------------------------------


@pytest.mark.parametrize("texto, esperado", [
    ("Reliquia Lith S19", [("Lith S19", None)]),
    ("Neo G6 Relic", [("Neo G6", None)]),
    ("Relique Meso N1 [Éclatante]", [("Meso N1", "Radiant")]),
    ("Reliquia Axi A7 [PERFECTA]", [("Axi A7", "Flawless")]),
    ("ReligueMesoD4", [("Meso D4", None)]),  # el OCR junta las palabras
    ("NeoA13Relic", [("Neo A13", None)]),
    ("L1th 519 Relic", [("Lith S19", None)]),  # cifras por letras y al reves
    ("MES0 O1", [("Meso O1", None)]),
    ("Requiem ll", [("Requiem II", None)]),
    ("ReliqueMeso N3", [("Meso N3", None)]),  # la era pegada a "Relique" y el codigo aparte (frances, 768p)
    ("Lith G10Relic", [("Lith G10", None)]),  # "Relic" pegado al codigo (rejilla apretada a 607p)
    ("Axi H8Relic", [("Axi H8", None)]),
    ("Axi", []),
    ("with A1 friends", []),
    ("x31", []),
    ("Lith W", []),  # sin cifras no es un codigo
    ("Lith S019", []),
])
def test_nombres_de_reliquia_en_el_texto_del_ocr(texto, esperado):
    assert RH.reliquias_en_texto(texto) == esperado


NOMBRES = {"Lith S19": 1, "Lith W4": 2, "Neo G6": 3, "Meso N1": 4, "Axi A7": 5}


def _l(texto, x, y, ancho=120, alto=20, confianza=0.9):
    return Leido(texto, x, y, ancho, alto, confianza)


def test_elige_el_nombre_mas_cercano_al_cursor():
    lineas = [_l("Lith S19 Relic", 40, 100), _l("x31", 10, 10, 30), _l("Neo G6 Relic", 250, 100)]
    elegida = RH.elegir_reliquia(lineas, (100, 60), (400, 200), NOMBRES)
    assert elegida.nombre == "Lith S19" and elegida.reliquia_id == 1


def test_dos_reliquias_igual_de_cerca_no_elige_ninguna():
    lineas = [_l("Lith S19 Relic", 40, 100), _l("Neo G6 Relic", 200, 100)]
    assert RH.elegir_reliquia(lineas, (180, 90), (400, 200), NOMBRES) is None


def test_un_nombre_cortado_por_el_borde_no_cuenta():
    # "Lith S19" partido en el borde derecho del recorte podria leerse "Lith S1".
    lineas = [_l("Lith W4", 300, 100, ancho=98)]
    assert RH.elegir_reliquia(lineas, (330, 90), (400, 200), NOMBRES) is None


def test_poca_confianza_o_reliquia_inexistente_no_ensena_nada():
    assert RH.elegir_reliquia([_l("Lith S19", 40, 100, confianza=0.5)], (90, 95), (400, 200), NOMBRES) is None
    assert RH.elegir_reliquia([_l("Lith Z99", 40, 100)], (90, 95), (400, 200), NOMBRES) is None


def test_un_nombre_lejos_del_cursor_no_es_lo_que_hay_debajo():
    lineas = [_l("Lith S19", 40, 180, alto=16)]
    assert RH.elegir_reliquia(lineas, (90, 10), (400, 200), NOMBRES) is None


def test_el_refinamiento_de_la_linea_de_debajo_se_suma_al_nombre():
    lineas = [_l("Relique Meso N1", 40, 100), _l("[Eclatante]", 60, 122, ancho=80)]
    elegida = RH.elegir_reliquia(lineas, (100, 60), (400, 200), NOMBRES)
    assert elegida.nombre == "Meso N1" and elegida.refinamiento == "Radiant"


def test_nombres_del_indice(con):
    con.executemany(
        "INSERT INTO items (unique_name, nombre_en, categoria) VALUES (?, ?, ?)",
        [("R/1", "Lith S19 Relic", "Relics"), ("R/2", "Requiem II Relic", "Relics"),
         ("R/3", "Requiem Relic Relic", "Relics"), ("P/1", "Ash Prime Systems", "Warframes")],
    )
    nombres = RH.nombres_de_reliquias(con)
    assert set(nombres) == {"Lith S19", "Requiem II"}


# -- pantallas y paradas ------------------------------------------------------------------


@pytest.mark.parametrize("pantalla, mira", [
    (None, False), ("arsenal", False), ("pausa", False), ("perfil", False),
    ("?VoidRelicsRedux", True), ("?AlgoNuevo", True), ("relic_market", True),
])
def test_solo_mira_en_pantallas_de_reliquias(pantalla, mira):
    assert RH.es_pantalla_de_reliquias(pantalla) is mira


def test_una_lectura_por_parada():
    d = RH.DetectorQuieto(quieto_s=0.3)
    assert not d.observar(0.0, 100, 100)
    assert not d.observar(0.2, 101, 100)  # temblor: sigue la misma parada
    assert d.observar(0.35, 102, 101)
    assert not d.observar(0.8, 102, 101)  # quieto mas tiempo: no se repite
    assert not d.observar(1.0, 300, 100)  # se mueve
    assert d.observar(1.4, 300, 100)


def test_cache_por_posicion_y_por_imagen():
    import numpy as np

    cache = RH.CacheHover(paso=24)
    imagen = np.full((120, 160, 3), 40, np.uint8)
    marca = RH.huella(imagen)
    cache.guardar(100, 100, "x", marca, (7, None))
    assert cache.buscar(110, 105, "x", marca) == ((7, None), True)
    otra = RH.huella(np.full((120, 160, 3), 200, np.uint8))
    assert cache.buscar(110, 105, "x", otra)[1] is False  # la casilla cambio (scroll)
    assert cache.buscar(400, 105, "x", marca)[1] is False


def test_el_recorte_no_se_sale_del_juego():
    juego = RH_region(0, 0, 1920, 1080)
    for cx, cy in ((0, 0), (1919, 1079), (960, 540), (5, 1070)):
        x, y, ancho, alto = RH.region_recorte(cx, cy, juego)
        assert 0 <= x and x + ancho <= 1920 and 0 <= y and y + alto <= 1080
        assert ancho == int(RH.ANCHO_REL * 1080) and alto == int(RH.ALTO_REL * 1080)


def RH_region(x, y, ancho, alto):
    from farmadex.captura.pantalla import Region

    return Region(x, y, ancho, alto)


# -- lector con un motor falso ----------------------------------------------------------------


class MotorFalso:
    fallo = None

    def __init__(self, lineas):
        self.lineas = lineas
        self.llamadas = 0

    def leer_tira(self, _imagen):
        self.llamadas += 1
        return self.lineas


def test_el_lector_casa_y_luego_tira_de_cache():
    import numpy as np

    lector = RH.LectorHoverReliquia()
    lector.nombres = dict(NOMBRES)
    lector.motor = MotorFalso([_l("Reliquia Neo G6", 60, 120)])
    imagen = np.zeros((200, 400, 3), np.uint8)
    assert lector.leer_imagen(imagen, (110, 80), (500, 500))[:2] == (3, None)
    reliquia_id, _refino, ms = lector.leer_imagen(imagen, (112, 82), (505, 503))
    # Dos lecturas contrastadas (a dos escalas) la primera vez; la segunda sale de la cache.
    assert reliquia_id == 3 and ms == -1.0 and lector.motor.llamadas == 2


# -- controlador --------------------------------------------------------------------------------


class Reloj:
    def __init__(self):
        self.t = 10.0

    def __call__(self):
        return self.t


def _control(qapp, modo="auto", sobre=False):
    ensenadas, escondidas, pedidas = [], [], []
    reloj = Reloj()
    control = RH.HoverReliquias(lambda *a: ensenadas.append(a), lambda: escondidas.append(1), modo=modo,
                                sobre_farmadex=lambda x, y: sobre, reloj=reloj)
    control.pedir_lectura.connect(lambda *a: pedidas.append(a))
    control.juego_delante = lambda: True
    control.pos = (500, 400)
    control.cursor = lambda: control.pos
    control.tecla_pulsada = lambda: False
    return control, reloj, ensenadas, escondidas, pedidas


def _tics(control, reloj, n=5, paso=0.1):
    for _ in range(n):
        reloj.t += paso
        control.tic()


def test_en_pantalla_de_reliquias_lee_una_vez_y_ensena(qapp):
    control, reloj, ensenadas, escondidas, pedidas = _control(qapp)
    control.pantalla_juego("abierta", "?VoidRelics")
    _tics(control, reloj, 8)
    assert len(pedidas) == 1
    numero, x, y, _contexto = pedidas[0]
    control.leida(numero, x, y, 3, "Radiant", 25.0)
    assert ensenadas == [(3, "Radiant", 500, 400)]
    _tics(control, reloj, 10)
    assert len(pedidas) == 1  # quieto: ni una lectura mas
    control.pos = (700, 400)  # se aleja: fuera la tarjeta
    control.tic()
    assert escondidas and not control.visible


def test_fuera_de_las_pantallas_de_reliquias_no_lee(qapp):
    control, reloj, _e, _o, pedidas = _control(qapp)
    control.pantalla_juego("abierta", "arsenal")
    _tics(control, reloj, 10)
    control.pantalla_juego("cerrada", "")
    _tics(control, reloj, 10)
    assert pedidas == []


def test_modo_tecla_solo_mientras_se_mantiene(qapp):
    control, reloj, ensenadas, escondidas, pedidas = _control(qapp, modo="tecla")
    _tics(control, reloj, 6)
    assert pedidas == []
    control.tecla_pulsada = lambda: True
    _tics(control, reloj, 6)
    assert len(pedidas) == 1
    control.leida(*pedidas[0][:3], 5, "", 20.0)
    assert ensenadas
    control.tecla_pulsada = lambda: False
    control.tic()
    assert escondidas


def test_un_resultado_viejo_o_con_el_raton_lejos_no_se_ensena(qapp):
    control, reloj, ensenadas, _o, pedidas = _control(qapp)
    control.pantalla_juego("abierta", "?VoidRelics")
    _tics(control, reloj, 5)
    numero, x, y, _c = pedidas[0]
    control.pos = (900, 100)  # mientras se leia, el raton se fue
    control.leida(numero, x, y, 3, "", 25.0)
    assert ensenadas == []
    control.leida(numero - 1, x, y, 3, "", 25.0)
    assert ensenadas == []


def test_encima_de_farmadex_no_lee_el_juego(qapp):
    control, reloj, _e, _o, pedidas = _control(qapp, sobre=True)
    control.pantalla_juego("abierta", "?VoidRelics")
    _tics(control, reloj, 8)
    assert pedidas == []


def test_apagado_en_ajustes_no_hace_nada(qapp):
    control, reloj, _e, _o, pedidas = _control(qapp)
    control.pantalla_juego("abierta", "?VoidRelics")
    control.activar(False)
    _tics(control, reloj, 8)
    assert pedidas == []


# -- con capturas reales (se saltan si no estan) ---------------------------------------------------


CAPTURA_REFINADO = FIXTURES / "capturas_internet" / "reliquias" / "relicrunner_6.webp"


@pytest.mark.skipif(not CAPTURA_REFINADO.exists(), reason="captura de internet no incluida en el repositorio")
def test_captura_real_de_la_pantalla_de_reliquias():
    """Reliquias del Vacio / Refinado a 1079x607 (ingles): el nombre bajo cada icono."""
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from farmadex.captura.ocr import MotorOCR

    imagen = cv2.imread(str(CAPTURA_REFINADO))
    if imagen is None:
        pytest.skip("OpenCV sin soporte webp")
    motor = MotorOCR("rapidocr")
    if motor.fallo:
        pytest.skip(motor.fallo)
    alto, ancho = imagen.shape[:2]
    nombres = {"Lith W4": 1, "Lith P9": 2, "Lith A6": 3, "Neo A13": 4, "Meso N17": 5, "Axi O6": 6, "Neo G6": 7}
    lector = RH.LectorHoverReliquia()
    lector.motor, lector.nombres = motor, nombres

    class Juego:
        x, y = 0, 0

    Juego.ancho, Juego.alto = ancho, alto
    # (cursor sobre el icono, reliquia esperada): coordenadas medidas en la captura.
    casos = [((101, 160), 1), ((223, 160), 2), ((344, 198), 3), ((101, 275), 4), ((101, 390), 5), ((344, 390), 6)]
    for (x, y), esperado in casos:
        rx, ry, w, h = RH.region_recorte(x, y, Juego)
        recorte = np.ascontiguousarray(imagen[ry:ry + h, rx:rx + w])
        lector.cache.vaciar()
        assert lector.leer_imagen(recorte, (x - rx, y - ry), (x, y))[0] == esperado, (x, y)


def test_la_cache_no_confunde_dos_reliquias_de_la_misma_casilla():
    """Misma media (el nombre ocupa pocos pixeles) pero una casilla distinta: no es la misma."""
    import numpy as np

    from farmadex.captura import reliquia_hover as RH

    a = np.full((12, 16), 80.0, np.float32)
    b = a.copy()
    b[5, 7] += 50  # el nombre cambiado cae en una casilla
    assert float(np.abs(a - b).mean()) < 6  # con solo la media se daba por igual
    assert not RH.misma_huella(a, b)
    assert RH.misma_huella(a, a + 2)  # la misma pantalla con un poco de ruido sigue valiendo
    cache = RH.CacheHover()
    cache.guardar(600, 550, "reliquias", a, (11, "Intacta"))
    assert cache.buscar(605, 548, "reliquias", b) == (None, False)
