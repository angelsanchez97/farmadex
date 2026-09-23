"""El camino rapido de la pantalla de recompensas: la fila de nombres y su geometria.

Las pruebas con OCR de verdad usan RapidOCR sobre tiras sinteticas (nombres
claros sobre fondo oscuro, como en el juego). La comparacion con pantallas
reales la hace `herramientas/banco_recompensas.py`; `test_banco_real` la corre
si hay capturas con verdad anotada y un indice real, y se salta si no.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from farmadex.captura import recompensas_rapidas as rapidas
from farmadex.captura.ocr import Casador, Leido, MotorOCR
from farmadex.captura.pantalla import Region
from farmadex.captura.reliquias import CATEGORIAS_RECOMPENSA, LectorRecompensas
from farmadex.datos import indice
from farmadex.registro import eelog

from test_captura import _insertar
from test_fila_recompensas import catalogo_reliquia  # noqa: F401 - fixture

RAIZ = Path(__file__).resolve().parents[1]
VENTANA_1440 = Region(0, 0, 2560, 1440)


def _l(texto, x, y, ancho, alto, conf=0.9):
    return Leido(texto, x, y, ancho, alto, conf)


# -- indice -------------------------------------------------------------------


def test_la_pieza_de_warframe_se_encuentra_aunque_eelog_la_llame_plano(con):
    ids = _insertar(con, [
        ("/Lotus/Powersuits/Sentient/CalibanPrime", "Caliban Prime", "Caliban Prime", "Warframes", None, None),
        ("/Lotus/Types/Recipes/WarframeRecipes/CalibanPrimeChassisComponent", "Chassis", "Chasis", "Warframes",
         "/Lotus/Powersuits/Sentient/CalibanPrime", 45),
        ("/Lotus/Types/Recipes/WarframeRecipes/CalibanPrimeBlueprint", "Blueprint", "Plano", "Warframes",
         "/Lotus/Powersuits/Sentient/CalibanPrime", 30),
    ])
    ruta = "/Lotus/Types/Recipes/WarframeRecipes/CalibanPrimeChassisBlueprint"
    assert indice.variantes_ruta(ruta)[1].endswith("CalibanPrimeChassisComponent")
    assert indice.fila_por_ruta(con, ruta)[0] == ids["/Lotus/Types/Recipes/WarframeRecipes/CalibanPrimeChassisComponent"]
    # El plano principal existe tal cual y no se toca.
    plano = "/Lotus/Types/Recipes/WarframeRecipes/CalibanPrimeBlueprint"
    assert indice.fila_por_ruta(con, plano, "id, nombre_es")[1] == "Plano"
    assert indice.fila_por_ruta(con, "/Lotus/Nada") is None
    assert rapidas.ids_conocidas(con, [ruta, "/Lotus/Nada"]) == {
        ids["/Lotus/Types/Recipes/WarframeRecipes/CalibanPrimeChassisComponent"]
    }


# -- geometria ----------------------------------------------------------------


def test_las_ranuras_van_centradas_y_miden_lo_medido():
    tres = rapidas.ranuras(VENTANA_1440, 3)
    ancho = rapidas.ANCHO_TARJETA * 1440
    assert tres[0][0] == pytest.approx(1280 - 1.5 * ancho)
    assert tres[-1][1] == pytest.approx(1280 + 1.5 * ancho)
    # Medido en el video del usuario: tarjetas de x=797 a x=1760.
    assert 790 <= tres[0][0] <= 805 and 1750 <= tres[2][1] <= 1770
    cuatro = rapidas.ranuras(Region(0, 0, 1920, 1080), 4)
    assert 470 <= cuatro[0][0] <= 482 and 1438 <= cuatro[3][1] <= 1450  # medido: 476..1443


def test_repartir_junta_lo_partido_y_parte_lo_pegado():
    region = VENTANA_1440.recortar(*rapidas.FILA_NOMBRES)  # x=614
    # Tres tarjetas: nombres centrados en cada hueco (x de la tira = x de pantalla - 614).
    lineas = [
        _l("Empunadura De Quassus", 836, 6, 305, 37),  # tarjeta 3, arriba
        _l("Prime", 951, 39, 75, 33),  # tarjeta 3, abajo
        _l("Plano De", 218, 37, 100, 33),  # tarjeta 1 partida en dos cajas
        _l("Fang Prime", 330, 37, 138, 33),
        _l("Plano De Orthos Prime", 529, 37, 270, 31),  # tarjeta 2
    ]
    grupos = rapidas.repartir(lineas, VENTANA_1440, region, 3)
    assert [rapidas._texto_de(g) for g in grupos] == [
        "Plano De Fang Prime", "Plano De Orthos Prime", "Empunadura De Quassus Prime",
    ]
    # Dos nombres que el detector devolvio pegados en una sola caja (tarjetas 2 y 3).
    pegada = [_l("Plano De Orthos PrimeEmpunadura De Quassus Prime", 529, 37, 612, 33)]
    grupos = rapidas.repartir(pegada, VENTANA_1440, region, 3)
    assert [rapidas._texto_de(g) for g in grupos] == ["", "Plano De Orthos Prime", "Empunadura De Quassus Prime"]
    # Sin pista de por donde cortar (ni espacio ni mayuscula), se corta por proporcion: a
    # un par de letras del sitio, que el casado difuso admite.
    pegada = [_l("plano de orthos primeempunadura de quassus prime", 529, 37, 612, 33)]
    uno, dos = [rapidas._texto_de(g) for g in rapidas.repartir(pegada, VENTANA_1440, region, 3)][1:]
    assert uno.startswith("plano de orthos") and "quassus" not in uno and dos.endswith("quassus prime")


def test_repartir_deduce_cuantas_tarjetas_hay_y_se_rinde_si_nada_cuadra():
    region = VENTANA_1440.recortar(*rapidas.FILA_NOMBRES)
    lineas = [_l("Plano De Fang Prime", 218, 37, 250, 33), _l("Plano De Orthos Prime", 529, 37, 270, 31),
              _l("Empunadura De Quassus Prime", 836, 6, 305, 37)]
    # EE.log no dijo nada: con 4 tarjetas los nombres cruzarian los bordes; con 3 cuadra.
    grupos = rapidas.repartir(lineas, VENTANA_1440, region, None)
    assert len(grupos) == 3 and all(len(g) == 1 for g in grupos)
    # EE.log dijo 4 pero hay 3: se descarta la cuenta que no cuadra.
    assert len(rapidas.repartir(lineas, VENTANA_1440, region, 4)) == 3
    # Otra escala de interfaz: una caja fuera de todo hueco.
    assert rapidas.repartir([_l("Algo", 5, 10, 60, 20)], VENTANA_1440, region, 3) is None
    assert rapidas.repartir([], VENTANA_1440, region, 3) is None


# -- casado -------------------------------------------------------------------


def test_variantes_texto_despega_el_de_y_pone_el_plano_detras():
    assert "Plano De Fang Prime" in rapidas.variantes_texto("Plano DeFang Prime")
    assert "fang prime plano" in rapidas.variantes_texto("Plano DeFang Prime")
    assert "Plano De Chasis De" in rapidas.variantes_texto("PlanoDe Chasis De")
    assert rapidas.variantes_texto("Culata De Trumna Prime") == ["Culata De Trumna Prime"]


def test_el_catalogo_de_piezas_no_tiene_armas_enteras(catalogo_reliquia):
    con, ids = catalogo_reliquia
    catalogo = Casador(con, CATEGORIAS_RECOMPENSA)
    piezas = rapidas.catalogo_de_piezas(catalogo, con)
    assert catalogo.casar("Fang Prime", 80)[0] == ids["/m/FangPrime"]
    assert piezas.casar("Fang Prime", 80)[0] in (None, ids["/m/FangPrime/Bp"])
    assert piezas.casar("Plano De Fang Prime", 80)[0] == ids["/m/FangPrime/Bp"]


def test_casar_fila_conserva_dos_tarjetas_con_el_mismo_objeto_y_no_inventa(catalogo_reliquia):
    con, ids = catalogo_reliquia
    casador = rapidas.CasadorEscalonado(Casador(con, CATEGORIAS_RECOMPENSA))
    lineas = [
        _l("Plano De Fang Prime", 20, 37, 250, 33),
        _l("Plano De Fang Prime", 330, 37, 250, 33),
        _l("Zzzz Prime Cosa", 640, 37, 250, 33),  # parece un nombre y no casa
        _l("1 platino", 30, 5, 80, 20),  # etiqueta propia encima de la primera: se pisa con ella
    ]
    fila = rapidas.casar_fila(lineas, casador)
    assert [r.item_id for r in fila] == [ids["/m/FangPrime/Bp"], ids["/m/FangPrime/Bp"], rapidas.SIN_IDENTIFICAR]
    assert fila[2].texto_ocr == "Zzzz Prime Cosa"


def test_el_escalon_de_eelog_manda_y_el_de_reliquias_va_antes_que_el_catalogo(catalogo_reliquia):
    con, ids = catalogo_reliquia
    catalogo = Casador(con, CATEGORIAS_RECOMPENSA)
    conocidas = catalogo.restringido({ids["/m/QuassusPrime/H"]})
    casador = rapidas.CasadorEscalonado(catalogo, None, conocidas)
    # Con el conjunto cerrado de EE.log, una lectura floja basta.
    assert casador.casar("Empunadra De Quassus Prme")[0] == ids["/m/QuassusPrime/H"]
    assert rapidas.CasadorEscalonado(catalogo).casar("xyzxyz")[0] is None


# -- OCR de verdad sobre una tira sintetica ------------------------------------


@pytest.fixture(scope="module")
def motor():
    m = MotorOCR("rapidocr")
    try:
        m.precalentar()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"RapidOCR no disponible: {e}")
    return m


def test_la_tira_sintetica_se_lee_sin_reescalar(motor):
    tira = rapidas.tira_de_prueba(("PLANO DE FANG PRIME", "PLANO DE ORTHOS PRIME", "FORMA"))
    lineas = rapidas.leer_fila(tira, motor)
    textos = " | ".join(l.texto.upper().replace(" ", "") for l in sorted(lineas, key=lambda l: l.x))
    assert "FANGPRIME" in textos and "ORTHOSPRIME" in textos and "FORMA" in textos
    assert all(0 <= l.y < rapidas.ALTO_FILA for l in lineas)


def test_leer_pantalla_usa_la_fila_si_basta_y_la_franja_si_no(catalogo_reliquia, motor, monkeypatch):
    con, ids = catalogo_reliquia
    casador = rapidas.CasadorEscalonado(Casador(con, CATEGORIAS_RECOMPENSA))
    llamadas = []

    def capturar(region):
        llamadas.append(region)
        return rapidas.tira_de_prueba(("PLANO DE FANG PRIME", "PLANO DE ORTHOS PRIME", "FORMA"))

    lineas_falsas = [_l("Plano De Fang Prime", 218, 37, 250, 33), _l("Plano De Orthos Prime", 529, 37, 270, 31)]
    monkeypatch.setattr(rapidas, "leer_fila", lambda imagen, motor: [Leido(**vars(l)) for l in lineas_falsas])

    def lento(ventana, tiempos):
        lento.veces += 1
        return [rapidas.Reconocido("x", ids["/m/FangPrime/Bp"], "Fang Prime Plano", 100.0, (700, 560, 250, 33))] * 3

    lento.veces = 0
    # Dos esperadas y dos leidas: no hace falta la franja.
    lectura = rapidas.leer_pantalla(capturar, VENTANA_1440, motor, casador, 2, lento)
    assert lectura.via == "fila" and lento.veces == 0
    assert [r.item_id for r in lectura.recompensas] == [ids["/m/FangPrime/Bp"], ids["/m/OrthosPrime/Bp"]]
    # Las cajas vuelven en coordenadas de pantalla (la tira empieza en x=614, y=540).
    assert lectura.recompensas[0].caja[0] >= 614 and lectura.recompensas[0].caja[1] >= 540
    # Tres esperadas y dos leidas: se pide la franja y gana la que mas trae.
    lectura = rapidas.leer_pantalla(capturar, VENTANA_1440, motor, casador, 3, lento)
    assert lectura.via == "franja" and lento.veces == 1 and len(lectura.recompensas) == 3
    # Sin `lento` (las primeras miradas) se devuelve lo que hay y ya.
    lectura = rapidas.leer_pantalla(capturar, VENTANA_1440, motor, casador, 3, None)
    assert lectura.via == "fila" and len(lectura.recompensas) == 2
    assert rapidas.leer_pantalla(lambda region: None, VENTANA_1440, motor, casador) is None


# -- EE.log -------------------------------------------------------------------


def test_eelog_cuenta_las_tarjetas_por_missing_icon_data():
    assert eelog.pista("739.932 Script [Info]: ProjectionRewardChoice.lua: Missing icon data!") == ("tarjeta", "1")
    assert eelog.clasificar("739.932 Script [Info]: ProjectionRewardChoice.lua: Missing icon data!") is None


def test_el_lector_espera_las_tarjetas_que_dijo_eelog():
    lector = LectorRecompensas.__new__(LectorRecompensas)
    lector.conocidas, lector.jugadores, lector.tarjetas, lector._miradas = [], None, 0, 0
    lector._casador_conocidas = None
    assert lector._esperadas() is None
    lector.pista("remotos", "1")
    assert lector._esperadas() == 2
    for _ in range(3):
        lector.pista("tarjeta", "1")
    assert lector._esperadas() == 3  # las marcas de tarjeta mandan sobre la escuadra
    lector._t_aviso = None
    lector.evento("reliquia_abierta")
    assert lector.tarjetas == 0 and lector._esperadas() == 2


# -- banco con pantallas reales ------------------------------------------------


def _indice_real() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Farmadex" / "db" / "indice.sqlite"


@pytest.mark.skipif(
    not _indice_real().exists() or not (RAIZ / "tests" / "fixtures" / "capturas_reliquias" / "verdad.json").exists(),
    reason="hace falta el indice real y capturas con verdad anotada",
)
def test_banco_real_el_camino_nuevo_acierta_al_menos_igual_y_es_mas_rapido():
    sys.path.insert(0, str(RAIZ / "herramientas"))
    import banco_recompensas as banco

    filas = banco.correr(vueltas=1, carga=0, ruta_indice=_indice_real())
    assert filas, "no hay capturas con verdad"
    for fila in filas:
        actual, nuevo = fila["actual"], fila["nuevo"]
        assert nuevo["aciertos"] >= actual["aciertos"], fila
        assert nuevo["inventadas"] <= max(actual["inventadas"], 0), fila
    assert sum(f["nuevo"]["aciertos"] for f in filas) >= 0.9 * sum(f["tarjetas"] for f in filas)
    assert sum(f["nuevo"]["ms"] for f in filas) < sum(f["actual"]["ms"] for f in filas)
