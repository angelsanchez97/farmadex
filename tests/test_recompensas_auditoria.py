"""Fallos de la auditoria de la pantalla de recompensas (0.6.2), cada uno con su prueba.

1. El escalon de EE.log (lo que les toco a TODOS en la escuadra) ganaba aunque el
   catalogo casara mejor: "RECEPTOR DE AKBOLTO PRIME" salia como el cañon de otro.
2. La ventana cambiaba las cajas de los mismos objetos que el lector guardaba para
   la siguiente mirada: con Windows al 125 % o el juego en el 2.o monitor, 7 tarjetas.
3. La rareza salia de los ducados o de la columna de WFCD (casi todo "Uncommon").
4. La tira de nombres, en fraccion del ancho, cortaba las tarjetas a 16:10 y 4:3.
5. El panel se quedaba encima de la pantalla siguiente si EE.log llegaba tarde, y
   los reintentos seguian tras cerrarse la pantalla o repitiendo lo mismo.
"""

from __future__ import annotations

import os
import time

import pytest

from farmadex.captura import comparador
from farmadex.captura import recompensas_rapidas as rapidas
from farmadex.captura import reliquias
from farmadex.captura.ocr import Casador, Leido, MotorOCR, Reconocido
from farmadex.captura.pantalla import Region
from farmadex.captura.reliquias import (
    CATEGORIAS_RECOMPENSA, LectorRecompensas, Recompensa, conservar_mejores, copiar,
)

from test_captura import _insertar


@pytest.fixture()
def catalogo_escuadra(con):
    """Piezas de un mismo objeto con nombres distintos (es/en), como en una escuadra real."""
    ids = _insertar(con, [
        ("/p/AkboltoPrime", "Akbolto Prime", "Akbolto Prime", "Secondary", None, None),
        ("/p/AkboltoPrime/Barrel", "Barrel", "Cañón", "Secondary", "/p/AkboltoPrime", 45),
        ("/p/AkboltoPrime/Receiver", "Receiver", "Receptor", "Secondary", "/p/AkboltoPrime", 45),
        ("/p/AkboltoPrime/Link", "Link", "Enlace", "Secondary", "/p/AkboltoPrime", 15),
        ("/w/AshPrime", "Ash Prime", "Ash Prime", "Warframes", None, None),
        ("/w/AshPrime/Chassis", "Chassis", "Chasis", "Warframes", "/w/AshPrime", 45),
        ("/w/AshPrime/Systems", "Systems", "Sistemas", "Warframes", "/w/AshPrime", 100),
        ("/p/BratonPrime", "Braton Prime", "Braton Prime", "Primary", None, None),
        ("/p/BratonPrime/Barrel", "Barrel", "Cañón", "Primary", "/p/BratonPrime", 45),
        ("/p/BratonPrime/Stock", "Stock", "Culata", "Primary", "/p/BratonPrime", 15),
    ])
    return con, ids


def _escalonado(con, conocida_id):
    catalogo = Casador(con, CATEGORIAS_RECOMPENSA)
    piezas = rapidas.catalogo_de_piezas(catalogo, con)
    return rapidas.CasadorEscalonado(piezas, None, catalogo.restringido({conocida_id})), catalogo


# -- 1. el escalon de EE.log no tapa un casado mejor del catalogo -----------------------


@pytest.mark.parametrize("conocida, leido, esperado", [
    ("/p/AkboltoPrime/Barrel", "Receptor De Akbolto Prime", "/p/AkboltoPrime/Receiver"),
    ("/p/AkboltoPrime/Barrel", "RECEPTOR DE AKBOLTO PRIME", "/p/AkboltoPrime/Receiver"),
    ("/p/AkboltoPrime/Barrel", "Akbolto Prime Receiver", "/p/AkboltoPrime/Receiver"),
    ("/w/AshPrime/Chassis", "PLANO DE SISTEMAS DE ASH PRIME", "/w/AshPrime/Systems"),
    ("/p/BratonPrime/Barrel", "CULATA DE BRATON PRIME", "/p/BratonPrime/Stock"),
])
def test_la_conocida_de_otro_jugador_no_gana_al_catalogo(catalogo_escuadra, conocida, leido, esperado):
    con, ids = catalogo_escuadra
    casador, _ = _escalonado(con, ids[conocida])
    item_id, nombre, puntos = casador.casar(leido)
    assert item_id == ids[esperado], (leido, nombre, puntos)


def test_la_conocida_sigue_rescatando_una_lectura_floja(catalogo_escuadra):
    con, ids = catalogo_escuadra
    casador, _ = _escalonado(con, ids["/p/AkboltoPrime/Link"])
    # Nada del catalogo pasa su umbral con esto; la conocida si, y gana.
    assert casador.casar("Enlce De Akblto Prme")[0] == ids["/p/AkboltoPrime/Link"]
    # Y casi exacta gana sin mirar mas.
    assert casador.casar("Enlace De Akbolto Prime")[0] == ids["/p/AkboltoPrime/Link"]


def test_leer_franja_no_descarta_un_casado_de_catalogo_mejor(catalogo_escuadra, monkeypatch):
    con, ids = catalogo_escuadra
    catalogo = Casador(con, CATEGORIAS_RECOMPENSA)
    conocidas = catalogo.restringido({ids["/p/AkboltoPrime/Barrel"]})
    lineas = [
        Leido("Receptor De Akbolto Prime", 100, 100, 240, 24, 0.9),  # la tarjeta propia
        Leido("Cañón De Akbolto Prime", 400, 100, 240, 24, 0.9),  # la del otro jugador
    ]
    monkeypatch.setattr(reliquias, "leer_lineas", lambda imagen, motor: [Leido(**vars(l)) for l in lineas])
    import numpy as np

    encontrados = reliquias.leer_franja(np.zeros((300, 800, 3), np.uint8), None, catalogo, conocidas, 70, {})
    por_x = {r.caja[0]: r.item_id for r in encontrados}
    assert por_x[100] == ids["/p/AkboltoPrime/Receiver"]
    assert por_x[400] == ids["/p/AkboltoPrime/Barrel"]


def test_combinar_deja_la_conocida_casi_exacta():
    seguro = Reconocido("x", 1, "A", 96.0, (0, 0, 100, 20))
    rival = Reconocido("x", 2, "B", 100.0, (10, 0, 100, 20))
    assert [r.item_id for r in reliquias._combinar([seguro], [rival])] == [1]
    flojo = Reconocido("x", 1, "A", 79.0, (0, 0, 100, 20))
    assert [r.item_id for r in reliquias._combinar([flojo], [rival])] == [2]


# -- 2. la ventana trabaja con copias ---------------------------------------------------


def _cuatro():
    return [
        Recompensa(11, "A", "A", (300, 540, 200, 40)), Recompensa(22, "B", "B", (700, 540, 200, 40)),
        Recompensa(33, "C", "C", (1100, 540, 200, 40)), Recompensa(44, "D", "D", (1500, 540, 200, 40)),
    ]


@pytest.fixture()
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_con_escala_125_y_segundo_monitor_no_salen_siete_tarjetas(qt_app, monkeypatch):
    from PySide6.QtCore import QRect

    from farmadex.captura import pantalla
    from farmadex.ui import etiquetas as mod_etiquetas
    from farmadex.ui import overlay
    from farmadex.ui.panel_recompensas import PanelRecompensas

    ventana = Region(2560, 0, 2560, 1440)  # juego en el monitor de la derecha
    monkeypatch.setattr(pantalla, "escala_fisica_logica", lambda *a: 1.25)
    monkeypatch.setattr(mod_etiquetas, "pantalla_de_las_cajas", lambda recompensas: QRect(2048, 0, 2048, 1152))

    lectura1 = [Recompensa(r.item_id, r.nombre, r.texto_ocr, (r.caja[0] + 2560,) + r.caja[1:]) for r in _cuatro()]
    guardadas = conservar_mejores([], lectura1, ventana)  # lo que el lector guarda en _previas
    emitidas = copiar(guardadas)
    panel = PanelRecompensas()
    try:
        panel.mostrar(overlay._a_logicas(emitidas))
        etiquetas = mod_etiquetas.EtiquetasRecompensas()
        etiquetas.mostrar(overlay._a_logicas(emitidas))
        # Lo que el lector guardo sigue en pixeles fisicos de escritorio.
        assert [r.caja for r in guardadas] == [r.caja for r in lectura1]
        assert panel.recompensas[0].caja != guardadas[0].caja  # la ventana si las ha movido (sus copias)
        # Segunda mirada: el cursor tapa la C.
        lectura2 = [Recompensa(r.item_id, r.nombre, r.texto_ocr, r.caja) for r in lectura1 if r.item_id != 33]
        salida = conservar_mejores(guardadas, lectura2, ventana)
        assert len(salida) <= 4
        assert sorted(r.item_id for r in salida) == [11, 22, 33, 44]
    finally:
        panel.deleteLater()


def test_conservar_mejores_empareja_por_ranura_o_por_objeto_aunque_las_cajas_no_casen():
    ventana = Region(0, 0, 2560, 1440)
    previas = _cuatro()
    for r in previas:  # como si alguien las hubiera pasado a otras coordenadas
        x, y, w, h = r.caja
        r.caja = (round(x / 1.25) - 300, y, w, h)
    nuevas = [r for r in _cuatro() if r.item_id != 33]
    salida = conservar_mejores(previas, nuevas, ventana)
    assert len(salida) == 4 and sorted(r.item_id for r in salida) == [11, 22, 33, 44]


def test_la_ranura_no_depende_de_cuantas_tarjetas_haya():
    ventana = Region(0, 0, 1920, 1080)
    for n in (2, 3, 4):
        ranuras = [reliquias._ranura((round(a), 400, round(b - a), 30), ventana) for a, b in rapidas.ranuras(ventana, n)]
        assert len(set(ranuras)) == n
        assert ranuras == sorted(ranuras)


# -- 3. rareza por probabilidad -------------------------------------------------------


def test_la_rareza_sale_de_la_probabilidad_y_es_la_mas_rara(con):
    ids = _insertar(con, [
        ("/r/Axi", "Axi A1 Relic", "Reliquia Axi A1", "Relics", None, None),
        ("/r/Neo", "Neo N1 Relic", "Reliquia Neo N1", "Relics", None, None),
        ("/w/AshPrime", "Ash Prime", "Ash Prime", "Warframes", None, None),
        ("/w/AshPrime/Systems", "Systems", "Sistemas", "Warframes", "/w/AshPrime", 65),
        ("/w/AshPrime/Neuro", "Neuroptics", "Neuroptica", "Warframes", "/w/AshPrime", 45),
    ])
    sistemas, neuro = ids["/w/AshPrime/Systems"], ids["/w/AshPrime/Neuro"]
    filas = [
        # WFCD dice "Uncommon" en todo; la probabilidad dice otra cosa.
        (ids["/r/Axi"], "Intact", sistemas, "Uncommon", 25.33),  # comun aqui
        (ids["/r/Neo"], "Radiant", sistemas, "Uncommon", 10.0),  # rara aqui
        (ids["/r/Axi"], "Intact", neuro, "Uncommon", 11.0),  # poco comun
    ]
    con.executemany("INSERT INTO reliquia_recompensas VALUES (?, ?, ?, ?, ?)", filas)
    con.commit()
    assert comparador.rareza_de(con, sistemas, 65) == "rara"
    assert comparador.rareza_de(con, neuro, 45) == "poco comun"
    assert comparador.rareza_de(con, 999999, 65) == "rara"  # sin tabla: por ducados
    assert comparador.rareza_de(con, 999999, None) is None


# -- 4. la tira de nombres en cualquier proporcion ------------------------------------


@pytest.mark.parametrize("ancho, alto", [
    (1920, 1080), (2560, 1440), (1280, 720), (3840, 2160),  # 16:9
    (1920, 1200), (2560, 1600), (1680, 1050),  # 16:10
    (1600, 1200), (1024, 768),  # 4:3
    (2560, 1080), (3440, 1440), (5120, 1440),  # 21:9 y 32:9
])
def test_la_tira_cubre_las_cuatro_tarjetas_en_cualquier_proporcion(ancho, alto):
    ventana = Region(100, 50, ancho, alto)
    tira = rapidas.region_fila(ventana)
    huecos = rapidas.ranuras(ventana, 4)
    assert tira.x <= huecos[0][0] and tira.x + tira.ancho >= huecos[-1][1] - 1
    assert tira.x >= ventana.x and tira.x + tira.ancho <= ventana.x + ventana.ancho
    assert tira.y <= ventana.y + 0.39 * alto and tira.y + tira.alto >= ventana.y + 0.43 * alto
    # Sin leer medio escritorio: a 21:9 la tira es mucho mas estrecha que la ventana.
    assert tira.ancho <= 4 * rapidas.ANCHO_TARJETA * alto + 2 * rapidas.MARGEN_FILA * alto + 2


def test_la_tira_vieja_cortaba_las_tarjetas_a_4_3():
    ventana = Region(0, 0, 1600, 1200)
    vieja = ventana.recortar(*rapidas.FILA_NOMBRES)
    nueva = rapidas.region_fila(ventana)
    # Interfaz en caja 16:9 centrada: los nombres caen mas abajo de lo que cubria la vieja.
    base = (1200 - 900) / 2
    fondo_nombres = base + 0.435 * 900
    assert vieja.y + vieja.alto < fondo_nombres - 10
    assert nueva.y + nueva.alto >= fondo_nombres - 1
    # Tarjetas escaladas por el alto: la vieja cortaba la primera por la izquierda.
    primera = 1600 / 2 - 2 * rapidas.ANCHO_TARJETA * 1200
    assert vieja.x > primera + 100 and nueva.x <= primera


@pytest.fixture(scope="module")
def motor():
    m = MotorOCR("rapidocr")
    try:
        m.precalentar()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"RapidOCR no disponible: {e}")
    return m


def _pantalla(ancho, alto, nombres, por_alto=False):
    """Pantalla oscura con los nombres donde los pone el juego (partidos si no caben).

    Por defecto la interfaz en caja 16:9 (`alto_interfaz`); con `por_alto`, la otra
    posibilidad: tarjetas escaladas con el alto de la ventana.
    """
    import cv2
    import numpy as np

    imagen = np.full((alto, ancho, 3), 16, np.uint8)
    ventana = Region(0, 0, ancho, alto)
    alto_ui = alto if por_alto else rapidas.alto_interfaz(ventana)
    base = (alto - alto_ui) / 2
    escala = 0.62 * alto_ui / 1080
    grosor = max(1, round(alto_ui / 700))
    ancho_t = rapidas.ANCHO_TARJETA * alto_ui
    x_ini = ancho / 2 - len(nombres) * ancho_t / 2
    huecos = [(x_ini + i * ancho_t, x_ini + (i + 1) * ancho_t) for i in range(len(nombres))]
    for (x0, x1), nombre in zip(huecos, nombres):
        lineas, actual = [], ""
        for palabra in nombre.split():
            prueba = f"{actual} {palabra}".strip()
            if actual and cv2.getTextSize(prueba, cv2.FONT_HERSHEY_SIMPLEX, escala, grosor)[0][0] > 0.85 * (x1 - x0):
                lineas.append(actual)
                actual = palabra
            else:
                actual = prueba
        lineas.append(actual)
        paso = int(alto_ui * 0.024)
        y = int(base + alto_ui * 0.41 - (len(lineas) - 1) * paso / 2)
        for j, linea in enumerate(lineas):
            w = cv2.getTextSize(linea, cv2.FONT_HERSHEY_SIMPLEX, escala, grosor)[0][0]
            cv2.putText(imagen, linea, (int((x0 + x1) / 2 - w / 2), y + j * paso + int(alto_ui * 0.006)),
                        cv2.FONT_HERSHEY_SIMPLEX, escala, (235, 235, 235), grosor, cv2.LINE_AA)
    return imagen


@pytest.mark.parametrize("ancho, alto, por_alto", [
    (1920, 1200, False), (1600, 1200, False), (2560, 1080, False), (3440, 1440, False), (1920, 1080, False),
    (1280, 720, False), (1920, 1200, True), (1600, 1200, True),  # la otra posibilidad de escalado
])
def test_la_fila_lee_las_cuatro_tarjetas_a_16_10_4_3_y_21_9(catalogo_escuadra, motor, ancho, alto, por_alto):
    con, ids = catalogo_escuadra
    casador = rapidas.CasadorEscalonado(Casador(con, CATEGORIAS_RECOMPENSA))
    nombres = ["RECEPTOR DE AKBOLTO PRIME", "SISTEMAS DE ASH PRIME", "CULATA DE BRATON PRIME", "ENLACE DE AKBOLTO PRIME"]
    imagen = _pantalla(ancho, alto, nombres, por_alto)
    ventana = Region(0, 0, ancho, alto)

    def capturar(region):
        return imagen[region.y:region.y + region.alto, region.x:region.x + region.ancho].copy()

    lectura = rapidas.leer_pantalla(capturar, ventana, motor, casador, 4, None, {})
    esperado = [ids[k] for k in ("/p/AkboltoPrime/Receiver", "/w/AshPrime/Systems", "/p/BratonPrime/Stock",
                                 "/p/AkboltoPrime/Link")]
    assert [r.item_id for r in lectura.recompensas] == esperado, [r.texto_ocr for r in lectura.recompensas]


# -- 5. panel colgado, reintentos tras cerrar y reintentos que no cambian nada -----------


def _lector(qt_app):
    lector = LectorRecompensas("rapidocr")
    lector._previas = [Recompensa(11, "A", "A", (300, 540, 200, 40))]
    return lector


def test_la_vigilancia_esconde_el_panel_si_los_nombres_ya_no_estan(qt_app, monkeypatch):
    lector = _lector(qt_app)
    avisos = []
    lector.tarjetas_fuera.connect(lambda: avisos.append(1))
    programadas = []
    monkeypatch.setattr(reliquias.QTimer, "singleShot", lambda ms, f: programadas.append((ms, f)))
    respuestas = iter([True, False, True, False, False])
    monkeypatch.setattr(lector, "_siguen_en_pantalla", lambda: next(respuestas))
    lector._empezar_vigilancia()
    assert programadas and programadas[-1][0] == lector.VIGILANCIA_MS
    for _ in range(4):
        programadas.pop()[1]()
        assert not avisos  # un fallo suelto (destello, cursor) no esconde nada
    programadas.pop()[1]()
    assert avisos == [1] and not programadas and lector._previas == []


def test_la_vigilancia_para_cuando_el_panel_ya_se_escondio_solo(qt_app, monkeypatch):
    lector = _lector(qt_app)
    programadas = []
    monkeypatch.setattr(reliquias.QTimer, "singleShot", lambda ms, f: programadas.append((ms, f)))
    monkeypatch.setattr(lector, "_siguen_en_pantalla", lambda: True)
    lector._empezar_vigilancia()
    lector._t_vigilancia = time.monotonic() - lector.VIGILANCIA_S - 1
    programadas.pop()[1]()
    assert not programadas


def test_el_reintento_programado_no_lee_si_la_pantalla_ya_se_cerro(qt_app, monkeypatch):
    lector = _lector(qt_app)
    leidas = []
    monkeypatch.setattr(lector, "leer_ahora", lambda: leidas.append(1))
    lector.evento("reliquia_abierta")
    lector.evento("reliquia_cerrada")
    lector._reintento()
    assert not leidas
    lector.evento("reliquia_abierta")
    lector._reintento()
    assert leidas == [1]


def test_los_reintentos_paran_al_repetir_tres_veces_lo_mismo(qt_app):
    lector = _lector(qt_app)
    lector.evento("reliquia_abierta")
    lector.tarjetas = 4  # EE.log dice 4 y solo se leen 3
    tres = _cuatro()[:3]
    for _ in range(2):
        lector._anotar_firma(tres)
        assert lector._toca_reintentar(3)
    lector._anotar_firma(tres)
    assert not lector._toca_reintentar(3)
    lector._anotar_firma(_cuatro()[:2])  # cambia lo leido: se vuelve a intentar
    assert lector._toca_reintentar(2)
