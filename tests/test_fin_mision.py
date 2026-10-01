"""Lectura de la pantalla de fin de mision (captura/fin_mision.py).

Las lineas de OCR de estas pruebas son las que RapidOCR dio de verdad sobre capturas
reales de la comunidad de Steam (texto y caja de cada trozo); las capturas no estan en
el repositorio. La medida completa sobre esas capturas esta en el informe de la funcion:
13 pantallas (720p a 1440p, ingles y castellano, interfaz actual y la anterior), 64 placas,
8 combinaciones de motor y escala: ninguna cantidad mal sumada; tres de cada cuatro, leidas.
"""

import numpy as np
import pytest

from farmadex.captura import fin_mision as FM
from farmadex.captura.ocr import Leido

PLASTIDOS = "/Lotus/Types/Items/MiscItems/Plastids"
GALIO = "/Lotus/Types/Items/MiscItems/Gallium"
POLIMEROS = "/Lotus/Types/Items/MiscItems/PolymerBundle"
PLACA = "/Lotus/Types/Items/MiscItems/AlloyPlate"
FERRITA = "/Lotus/Types/Items/MiscItems/Ferrite"
RESTOS = "/Lotus/Types/Items/MiscItems/Salvage"
HEXENON = "/Lotus/Types/Items/MiscItems/ConcentratedGas"
NEURODOS = "/Lotus/Types/Items/MiscItems/Neurode"
SENSORES = "/Lotus/Types/Items/MiscItems/NeuralSensor"


@pytest.fixture()
def nombres():
    n = FM.Nombres()
    n.anadir(PLASTIDOS, "Plastids", "Plástidos")
    n.anadir(GALIO, "Gallium", "Galio")
    n.anadir(POLIMEROS, "Polymer Bundle", "Paquete de polímeros")
    n.anadir(PLACA, "Alloy Plate", "Placa de aleación")
    n.anadir(FERRITA, "Ferrite", "Ferrita")
    n.anadir(RESTOS, "Salvage", "Restos")
    n.anadir(HEXENON, "Hexenon", "Hexenon")
    n.anadir(NEURODOS, "Neurodes", "Neurodos")
    n.anadir(SENSORES, "Neural Sensors", "Sensores neuronales")
    return n


def L(texto, x, y, ancho, alto, confianza=0.8):
    return Leido(texto, x, y, ancho, alto, confianza)


# Captura real a 1920x1080 en castellano (interfaz actual, con el icono delante de la cifra).
LINEAS_1080_ES = [
    L("IMPORTANCIA", 1283, 585, 153, 26), L("BUSCAR..", 1564, 587, 100, 23),
    L("040", 924, 633, 58, 25, 0.61), L("856", 1105, 633, 70, 25, 0.75), L("04", 1286, 634, 43, 23, 0.54),
    L("2,614", 1463, 632, 90, 27, 0.82), L("1,196", 1644, 632, 89, 27, 0.71),
    L("Paquete De", 1474, 743, 123, 37, 0.79), L("Carburos", 960, 770, 86, 27),
    L("Diodos Cubicos", 1110, 768, 144, 29), L("Galio", 1338, 771, 50, 25, 0.82),
    L("Polimeros", 1494, 771, 97, 27, 0.83), L("Plastidos", 1678, 769, 89, 27, 0.87),
    L("?1,820", 1104, 812, 88, 28, 0.74), L("Esmeralda", 954, 952, 97, 24), L("Talento", 971, 932, 67, 21),
    L("Titanio", 1150, 951, 65, 25), L("ESTADiSTICAS", 1549, 992, 158, 29), L("SALIR", 1742, 994, 70, 27),
]

# Captura real a 1366x768 en castellano (interfaz anterior, sin icono).
LINEAS_768_ES = [
    L("1asesinatos de Eximus", 592, 360, 156, 21), L("54% de dano infligido", 837, 361, 141, 20),
    L("46asesinatos", 1084, 363, 94, 17), L("IMPORTANCIA", 913, 417, 110, 17), L("BUSCAR.", 1113, 417, 66, 17),
    L("93", 782, 447, 24, 18, 0.67), L("1,339", 910, 445, 45, 21, 0.83), L("31", 1038, 447, 19, 17, 0.66),
    L("12,736", 1165, 446, 61, 20, 0.82), L("Vestigios Del", 1053, 530, 89, 20), L("Hexenon", 683, 546, 62, 20),
    L("Placa DeAleacion", 783, 546, 117, 17), L("Restos", 945, 547, 49, 18), L("Vacio", 1078, 548, 39, 17),
    L("Creditos", 1197, 547, 58, 18),
]


# -- cifras ---------------------------------------------------------------------------


@pytest.mark.parametrize("texto, valor", [
    ("1,196", 1196), ("2.614", 2614), ("1 790", 1790), ("153808", 153808), ("93", 93), ("7", 7),
    ("0360", 360),      # el icono de delante leido como un cero
    ("?30", 30),        # o como un signo
    ("?1,820", 1820), ("01,726", 1726), ("193,584", 193584),
])
def test_cifras_que_se_entienden(texto, valor):
    assert FM.cifra_de(texto) == valor


@pytest.mark.parametrize("texto", [
    "12,7",      # cortada: los grupos son de tres cifras
    "1,33",
    "0", "00", "", "abc",
    "8%",        # estadistica de la escuadra
    "46asesinatos",
    "13,500/10,000",
])
def test_cifras_dudosas_no_valen(texto):
    assert FM.cifra_de(texto) is None


def test_nombres_sin_tildes_espacios_ni_mayusculas(nombres):
    assert nombres.casar("Plastidos") == PLASTIDOS
    assert nombres.casar("Placa DeAleacion") == PLACA
    assert nombres.casar("PAQUETE DE POLÍMEROS") == POLIMEROS
    assert nombres.casar("Alloy Plate") == PLACA


def test_un_nombre_parecido_a_dos_recursos_o_demasiado_corto_no_casa(nombres):
    assert nombres.casar("Neuro") is None
    assert nombres.casar("Galia") is None  # corto: una letra cambiada ya es otra cosa
    assert nombres.casar("Titanio") is None  # no esta en el catalogo
    nombres.anadir("/otro", "Plastids")  # dos objetos con el mismo nombre: ambiguo
    assert nombres.casar("Plastids") is None


# -- placas --------------------------------------------------------------------------------


def test_cada_recurso_con_la_cifra_de_su_placa_y_no_la_del_vecino(nombres):
    placas = FM.interpretar(LINEAS_1080_ES, 1080, nombres, {PLASTIDOS, GALIO, POLIMEROS})
    leido = {p.unique_name: p.cantidad for p in placas}
    assert leido == {PLASTIDOS: 1196, GALIO: 4, POLIMEROS: 2614}


def test_interfaz_anterior_y_estadisticas_de_la_escuadra(nombres):
    placas = FM.interpretar(LINEAS_768_ES, 768, nombres, {PLACA, RESTOS, HEXENON})
    leido = {p.unique_name: (p.cantidad, p.motivo) for p in placas}
    assert leido[PLACA] == (93, "")
    assert leido[RESTOS] == (1339, "")
    # La cifra del Hexenon (un 7) no la vio el OCR: no se inventa un 1.
    assert leido[HEXENON] == (None, FM.SIN_CIFRA)


def test_solo_se_miran_los_recursos_que_son_meta(nombres):
    assert FM.interpretar(LINEAS_1080_ES, 1080, nombres, set()) == []
    placas = FM.interpretar(LINEAS_1080_ES, 1080, nombres, {FERRITA})
    assert placas == []  # la Ferrita no esta en esta pantalla


def test_la_cifra_de_la_fila_de_arriba_no_es_de_esta_placa(nombres):
    # Una placa de la segunda fila sin cifra propia: la del recurso de encima no le vale.
    lineas = LINEAS_1080_ES + [L("Ferrita", 1690, 951, 65, 25)]
    placa = next(p for p in FM.interpretar(lineas, 1080, nombres, {FERRITA}))
    assert placa.cantidad is None and placa.motivo == FM.SIN_CIFRA


def test_el_mismo_recurso_dos_veces_en_pantalla_no_se_suma(nombres):
    lineas = LINEAS_1080_ES + [L("1,196", 644, 632, 89, 27), L("Plastidos", 678, 769, 89, 27)]
    placas = [p for p in FM.interpretar(lineas, 1080, nombres, {PLASTIDOS})]
    assert len(placas) == 2 and all(p.cantidad is None for p in placas)


def test_cifra_con_poca_confianza_no_vale(nombres):
    lineas = [L("1,196", 1644, 632, 89, 27, 0.30), L("Plastidos", 1678, 769, 89, 27)]
    placa = FM.interpretar(lineas, 1080, nombres, {PLASTIDOS})[0]
    assert placa.cantidad is None and placa.motivo == FM.CIFRA_DUDOSA


def test_tramo_tipico_de_la_rejilla():
    assert FM.tramo_tipico(LINEAS_1080_ES, 1080) == pytest.approx(164, abs=4)
    assert FM.tramo_tipico(LINEAS_768_ES, 768) == pytest.approx(119, abs=4)
    assert FM.tramo_tipico([L("SALIR", 10, 10, 50, 20)], 1080) is None


# -- segunda lectura -----------------------------------------------------------------------


class MotorFalso:
    """Devuelve lo que se le diga: `lineas` en la lectura entera, `recorte` en la segunda."""

    def __init__(self, lineas=(), recorte=("", 0.0), zona=()):
        self.lineas, self.recorte, self.zona = list(lineas), recorte, list(zona)
        self.lecturas = 0

    def leer(self, imagen, **_kw):
        self.lecturas += 1
        return [Leido(**l.__dict__) for l in (self.lineas if self.lecturas == 1 else self.zona)]

    def _cargar(self):
        motor = self

        class Interno:
            @staticmethod
            def text_recognizer(_imagenes):
                return [motor.recorte], 0.0

        return Interno()


def _imagen(alto=1080, ancho=1920):
    rng = np.random.default_rng(7)
    return rng.integers(10, 40, size=(alto, ancho, 3), dtype=np.uint8)


def test_la_cantidad_vale_si_la_segunda_lectura_coincide(nombres):
    motor = MotorFalso(LINEAS_1080_ES, recorte=("1,196", 0.71))
    placas = FM.leer_imagen(_imagen(), motor, nombres, {PLASTIDOS})
    assert [(p.cantidad, p.motivo) for p in placas] == [(1196, "")]


@pytest.mark.parametrize("recorte", [("1,198", 0.9), ("", 0.0), ("1,196", 0.2), ("G04", 0.7)])
def test_si_la_segunda_lectura_no_coincide_no_se_suma(nombres, recorte):
    motor = MotorFalso(LINEAS_1080_ES, recorte=recorte)
    placas = FM.leer_imagen(_imagen(), motor, nombres, {PLASTIDOS})
    assert [(p.cantidad, p.motivo) for p in placas] == [(None, FM.CIFRA_DUDOSA)]


def test_una_cifra_a_otra_distancia_que_las_demas_placas_no_vale(nombres):
    # El nombre esta en su fila, pero "su" cifra esta 30 px mas arriba que las del resto.
    lineas = [l for l in LINEAS_1080_ES if l.texto != "1,196"] + [L("1,196", 1650, 602, 89, 27)]
    motor = MotorFalso(lineas, recorte=("1,196", 0.8))
    placas = FM.leer_imagen(_imagen(), motor, nombres, {PLASTIDOS})
    assert [(p.cantidad, p.motivo) for p in placas] == [(None, FM.CIFRA_DUDOSA)]


def _pintar_icono(imagen, x, y, lado):
    import cv2

    cv2.circle(imagen, (x + lado // 2, y + lado // 2), lado // 2 - 1, (230, 230, 230), 2)


def _lineas_con_ferrita_sin_cifra():
    return LINEAS_1080_ES + [L("Ferrita", 1690, 951, 65, 25)]


def test_placa_con_el_icono_y_sin_cifra_es_una_unidad(nombres):
    imagen = _imagen()
    tramo = FM.tramo_tipico(_lineas_con_ferrita_sin_cifra(), 1080)
    centro, pie = 1690 + 65 / 2, 951 + 25
    _pintar_icono(imagen, int(centro - FM._ICONO_X * tramo), int(pie - FM._ICONO_Y * tramo), 23)
    motor = MotorFalso(_lineas_con_ferrita_sin_cifra())
    placa = FM.leer_imagen(imagen, motor, nombres, {FERRITA})[0]
    assert (placa.cantidad, placa.motivo) == (1, "")


def test_sin_icono_a_la_vista_no_se_da_por_hecho_que_sea_una(nombres):
    motor = MotorFalso(_lineas_con_ferrita_sin_cifra())
    placa = FM.leer_imagen(_imagen(), motor, nombres, {FERRITA})[0]
    assert (placa.cantidad, placa.motivo) == (None, FM.SIN_CIFRA)


def test_algo_redondo_fuera_de_su_sitio_no_cuenta_como_icono(nombres):
    imagen = _imagen()
    tramo = FM.tramo_tipico(_lineas_con_ferrita_sin_cifra(), 1080)
    centro, pie = 1690 + 65 / 2, 951 + 25
    _pintar_icono(imagen, int(centro - FM._ICONO_X * tramo) + 40, int(pie - FM._ICONO_Y * tramo) + 8, 23)
    motor = MotorFalso(_lineas_con_ferrita_sin_cifra())
    placa = FM.leer_imagen(imagen, motor, nombres, {FERRITA})[0]
    assert placa.cantidad is None


def test_cifra_corta_que_solo_se_ve_de_cerca_necesita_las_dos_lecturas(nombres):
    zona = [L("7", 60, 30, 20, 40, 0.8)]
    motor = MotorFalso(_lineas_con_ferrita_sin_cifra(), recorte=("7", 0.5), zona=zona)
    placa = FM.leer_imagen(_imagen(), motor, nombres, {FERRITA})[0]
    assert (placa.cantidad, placa.motivo) == (7, "")
    motor = MotorFalso(_lineas_con_ferrita_sin_cifra(), recorte=("1", 0.5), zona=zona)
    placa = FM.leer_imagen(_imagen(), motor, nombres, {FERRITA})[0]
    assert (placa.cantidad, placa.motivo) == (None, FM.CIFRA_DUDOSA)


# -- varias capturas de la misma mision ----------------------------------------------------


def _placa(unico, cantidad, motivo=""):
    return FM.Placa(unico, "x", (0, 0, 1, 1), None, cantidad, motivo)


def test_una_cantidad_vale_cuando_sale_igual_en_dos_capturas():
    acumulador = FM.Acumulador({PLASTIDOS, GALIO})
    acumulador.anotar([_placa(PLASTIDOS, 1196)])
    assert not acumulador.completo and acumulador.seguras == {}
    acumulador.anotar([_placa(PLASTIDOS, 1196), _placa(GALIO, None, FM.CIFRA_DUDOSA)])
    resultado = acumulador.resultado("m1")
    assert resultado.cantidades == {PLASTIDOS: 1196}
    assert resultado.no_leidos == {GALIO: FM.CIFRA_DUDOSA}


def test_dos_capturas_que_no_coinciden_no_suman_nada():
    acumulador = FM.Acumulador({PLASTIDOS})
    acumulador.anotar([_placa(PLASTIDOS, 1196)])
    acumulador.anotar([_placa(PLASTIDOS, 196)])
    resultado = acumulador.resultado("m1")
    assert resultado.cantidades == {} and resultado.no_leidos == {PLASTIDOS: FM.NO_REPETIDA}


def test_lo_que_no_se_ha_visto_se_dice():
    acumulador = FM.Acumulador({PLASTIDOS})
    acumulador.anotar([])
    assert acumulador.resultado("m1").no_leidos == {PLASTIDOS: FM.NO_VISTO}


# -- el lector ---------------------------------------------------------------------------------


@pytest.fixture()
def lector(monkeypatch):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    lector = FM.LectorFinMision("rapidocr", activo=True)
    lector.nombres = FM.Nombres()
    lector.resultados = []
    lector.resultado.connect(lector.resultados.append)
    lector.capturas = 0

    def capturar():
        lector.capturas += 1
        return _imagen(72, 128)

    monkeypatch.setattr(lector, "_capturar", capturar)
    return lector


def test_apagado_o_sin_recursos_como_meta_no_hace_nada(lector):
    lector.leer_mision([])
    assert lector._temporizador is None and lector._acumulador is None
    lector.activar(False)
    lector.leer_mision([PLASTIDOS])
    assert lector._temporizador is None and lector._acumulador is None
    assert lector.capturas == 0


def test_lee_dos_veces_suma_y_para(lector, monkeypatch):
    monkeypatch.setattr(FM, "leer_imagen", lambda *a, **k: [_placa(PLASTIDOS, 1196)])
    lector.leer_mision([PLASTIDOS])
    assert lector._temporizador.isActive() and lector._temporizador.isSingleShot()
    lector._leer()
    assert lector.resultados == [] and lector._temporizador.isActive()
    lector._leer()
    assert [r.cantidades for r in lector.resultados] == [{PLASTIDOS: 1196}]
    # Acabada la mision no queda nada en marcha: coste en reposo, cero.
    assert not lector._temporizador.isActive() and lector._acumulador is None
    lector._leer()
    assert lector.capturas == 2 and len(lector.resultados) == 1


def test_si_no_aparece_deja_de_mirar_tras_unas_pocas_lecturas(lector, monkeypatch):
    monkeypatch.setattr(FM, "leer_imagen", lambda *a, **k: [])
    lector.leer_mision([PLASTIDOS])
    for _ in range(FM.MAX_LECTURAS + 3):
        lector._leer()
    # Pantalla quieta y sin el recurso a la vista: tres lecturas y fuera.
    assert lector.capturas == FM.MIN_LECTURAS
    assert [r.no_leidos for r in lector.resultados] == [{PLASTIDOS: FM.NO_VISTO}]
    assert not lector._temporizador.isActive()


def test_si_la_pantalla_no_para_de_cambiar_hay_un_tope_de_lecturas(lector, monkeypatch):
    cantidades = iter(range(100, 200))
    monkeypatch.setattr(FM, "leer_imagen", lambda *a, **k: [_placa(PLASTIDOS, next(cantidades))])
    lector.leer_mision([PLASTIDOS])
    for _ in range(FM.MAX_LECTURAS + 3):
        lector._leer()
    assert lector.capturas == FM.MAX_LECTURAS
    assert [(r.cantidades, r.no_leidos) for r in lector.resultados] == [({}, {PLASTIDOS: FM.NO_REPETIDA})]


def test_sin_el_juego_delante_no_se_lee_nada(lector, monkeypatch):
    llamadas = []
    monkeypatch.setattr(lector, "_capturar", lambda: None)
    monkeypatch.setattr(FM, "leer_imagen", lambda *a, **k: llamadas.append(1) or [])
    lector.leer_mision([PLASTIDOS])
    for _ in range(FM.MAX_LECTURAS):
        lector._leer()
    assert llamadas == [] and lector.resultados[0].cantidades == {}
    assert lector.resultados[0].lecturas == FM.MIN_LECTURAS


def test_cada_mision_tiene_su_clave():
    claves = {FM.clave_de_mision() for _ in range(5)}
    assert len(claves) == 5
