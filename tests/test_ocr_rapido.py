"""Velocidad del OCR sin perder aciertos: memoria de ONNX Runtime, preparado con tabla,
deteccion reducida en la pantalla de mejoras, casado con memoria y tiempos por etapa."""

from __future__ import annotations

import numpy as np
import pytest

from farmadex.captura import builds as B
from farmadex.captura import ocr
from farmadex.captura.ocr import MotorOCR, resumen_tiempos

import sintetico_builds as SINT
from test_captura import _insertar


def _preparar_de_antes(imagen):
    """La cuenta de `preparar` tal y como estaba antes de la tabla (referencia)."""
    import cv2

    gris = cv2.cvtColor(np.ascontiguousarray(imagen), cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    bajo, alto = np.percentile(gris[::2, ::2], (2.0, 99.8))
    if alto - bajo >= 1:
        gris = np.clip((gris.astype(np.float32) - bajo) * (255.0 / (alto - bajo)), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(np.repeat(gris[:, :, None], 3, axis=2))


@pytest.mark.parametrize("semilla", range(6))
def test_preparar_da_exactamente_los_mismos_pixeles(semilla):
    gen = np.random.default_rng(semilla)
    alto, ancho = gen.integers(20, 400), gen.integers(20, 700)
    # Fondo oscuro con texto claro y algo de ruido, y a veces poco contraste.
    imagen = gen.integers(0, 60, (alto, ancho, 3)).astype(np.uint8)
    imagen[alto // 3: alto // 2, ancho // 4: ancho // 2] = gen.integers(150, 256)
    if semilla % 2:
        imagen = (imagen // 3 + 80).astype(np.uint8)
    assert np.array_equal(ocr.preparar(imagen), _preparar_de_antes(imagen))
    gris = imagen[:, :, 0].copy()
    assert np.array_equal(ocr.preparar(gris), _preparar_de_antes(gris))


def test_preparar_con_imagen_plana_y_con_basura():
    plana = np.full((50, 80, 3), 40, np.uint8)
    assert np.array_equal(ocr.preparar(plana), _preparar_de_antes(plana))
    assert ocr.preparar(None) is None
    assert ocr.preparar(np.zeros((0, 0, 3), np.uint8)) is None


def test_las_sesiones_no_pagan_primeras_veces_y_devuelven_la_memoria():
    """Arena encendido, patron de memoria apagado y el arena se encoge tras cada inferencia."""
    motor = ocr._crear_rapidocr(1)
    for parte in (motor.text_detector, motor.text_recognizer):
        assert isinstance(parte, ocr._Cronometrado)
    for sesion in (motor.text_detector.infer, motor.text_recognizer.session):
        assert isinstance(sesion, ocr._SesionQueSuelta)
        opciones = sesion.session.get_session_options()
        assert opciones.enable_cpu_mem_arena is True
        assert opciones.enable_mem_pattern is False
        assert opciones.intra_op_num_threads == 1
        assert opciones.get_session_config_entry("session.intra_op.allow_spinning") == "0"
    run = ocr._SesionQueSuelta.opciones_run()
    assert run.get_run_config_entry("memory.enable_memory_arena_shrinkage") == "cpu:0"


@pytest.fixture(scope="module")
def motor_real():
    MotorOCR.descargar()
    yield MotorOCR("rapidocr")
    MotorOCR.descargar()


def test_leer_deja_los_tiempos_por_etapa(motor_real):
    imagen = ocr._imagen_de_prueba()
    leidos = motor_real.leer(imagen)
    assert leidos
    t = motor_real.tiempos
    for etapa in ("preparar", "detector", "reconocedor", "total"):
        assert t[etapa] >= 0
    assert t["cajas"] == len(leidos) and t["entrada"] == f"{imagen.shape[1]}x{imagen.shape[0]}"
    texto = resumen_tiempos(t)
    assert "detector" in texto and "reconocedor" in texto and "cajas" in texto
    assert resumen_tiempos({}) == "sin tiempos"


def test_leer_tira_con_deteccion_reducida_devuelve_cajas_a_tamano_real(motor_real):
    imagen = SINT.pintar_arsenal("Excalibur", ["Vitality", "Redirection", "Intensify"], ["Flow", "Rush"],
                                 ancho=2560, alto=1440, semilla=2)
    reducida = motor_real.leer_tira(imagen, alto_deteccion=720)
    assert motor_real.tiempos["deteccion"] == "1280x720"
    assert motor_real.tiempos["entrada"] == "2560x1440"
    entera = motor_real.leer_tira(imagen)
    assert "deteccion" in motor_real.tiempos and motor_real.tiempos["deteccion"] == "2560x1440"
    # Las cajas vienen en pixeles de la captura original, no de la reducida.
    assert max(l.x + l.ancho for l in reducida) > 1800
    textos = {l.texto.lower() for l in reducida}
    for nombre in ("vitality", "redirection", "intensify", "flow", "rush"):
        assert any(nombre in t for t in textos), (nombre, textos)
    # Y leen lo mismo que buscando a tamano real.
    assert {l.texto for l in entera if "vitality" in l.texto.lower()} == \
        {l.texto for l in reducida if "vitality" in l.texto.lower()}


def test_leer_tira_sin_reduccion_si_ya_es_pequena(motor_real, monkeypatch):
    llamadas = []
    original = ocr._leer_tira_rapidocr
    monkeypatch.setattr(ocr, "_leer_tira_rapidocr", lambda *a: llamadas.append(len(a)) or original(*a))
    motor_real.leer_tira(np.full((80, 600, 3), 20, np.uint8), alto_deteccion=810)
    assert llamadas == [2]  # sin el tercer argumento: los motores falsos de las pruebas siguen valiendo


def test_la_cabecera_se_lee_con_el_boton_mas_y_el_rango_con_o():
    for texto, esperado in (("+UPGRADES /EXCALIBUR [3O] 美美", "EXCALIBUR"), ("+UPGRADES /EXCALIBUR [3O]", "EXCALIBUR"), ("+UPGRADES/EXCALIBUR [3O]", "EXCALIBUR"),
                            ("UPGRADES/EXCALIBUR[30]", "EXCALIBUR"), ("MEJORAS / KUVA BRAMMA [4O", "KUVA BRAMMA"),
                            ("SEARCH...", ""), ("CONFIG A", "")):
        assert B.RE_CABECERA.match(texto) is None if not esperado else B.RE_CABECERA.match(texto).group(1) == esperado


def test_resumen_de_etapas_de_la_build():
    tiempos = {"captura": 0.02, "preparar": 0.003, "detector": 0.06, "reconocedor": 0.12, "casado": 0.03,
               "reparto": 0.001, "entrada": "2560x1440", "deteccion": "1440x810", "cajas": 80, "motor": "rapidocr"}
    texto = B.resumen_etapas(tiempos)
    assert texto.startswith("captura 20, preparar 3, detector 60, reconocedor 120, casado 30, reparto 1 ms")
    assert "imagen 2560x1440 buscada a 1440x810" in texto and "80 cajas" in texto and "motor rapidocr" in texto
    assert B.resumen_etapas({}) == "sin tiempos"


class _CasadorContado(ocr.Casador):
    def __init__(self):  # sin indice: solo lo justo para contar las busquedas
        self.llamadas = []

    def _casar(self, texto, umbral):
        self.llamadas.append((texto, umbral))
        return (7, "Vitality", 100.0) if texto == "Vitality" else (None, "", 0.0)


def test_casar_recuerda_lo_ya_casado():
    casador = _CasadorContado()
    assert casador.casar("Vitality", 85) == (7, "Vitality", 100.0)
    assert casador.casar("Vitality", 85) == (7, "Vitality", 100.0)
    assert casador.casar("Health", 85) == (None, "", 0.0)
    assert casador.casar("Health", 85) == (None, "", 0.0)
    assert casador.casar("Vitality", 70) == (7, "Vitality", 100.0)  # otro umbral, otra cuenta
    assert casador.llamadas == [("Vitality", 85), ("Health", 85), ("Vitality", 70)]


def test_casar_memoria_acotada(monkeypatch):
    casador = _CasadorContado()
    monkeypatch.setattr(_CasadorContado, "MEMO_MAXIMO", 3)
    for i in range(10):
        casador.casar(f"texto {i}", 85)
    assert len(casador._memo) <= 3


def test_sin_letras_no_se_busca_nada(con):
    _insertar(con, [("/w/AX52", "AX-52", "AX-52", "Primary", None, None)])
    casador = ocr.Casador(con)
    for texto in ("571", "3/37", "105% 110%", "446,940", "52"):
        assert casador.casar(texto, 82) == (None, "", 0.0), texto
    assert casador.casar("AX-52", 82)[1] == "AX-52"


def test_build_deja_los_tiempos_de_cada_etapa(motor_real, con):
    _insertar(con, [("/w/Excalibur", "Excalibur", "Excalibur", "Warframes", None, None)])
    casador = B.crear_casador(con)
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    imagen = SINT.pintar_arsenal("Excalibur", ["Vitality"], ["Flow"], ancho=1920, alto=1080, semilla=3)
    build = B.leer_build(imagen, motor_real, casador, categorias)
    for etapa in ("preparar", "detector", "reconocedor", "casado", "reparto"):
        assert etapa in build.tiempos
    assert build.tiempos["deteccion"] == "1920x1080"  # a 1080p no se reduce
    assert build.equipo is not None and build.equipo.nombre == "Excalibur"


def test_normalizado_del_detector_da_los_mismos_numeros():
    from rapidocr_onnxruntime.ch_ppocr_v3_det.utils import NormalizeImage, ToCHWImage

    motor = ocr._crear_rapidocr(1)
    nombres = [type(op).__name__ for op in motor.text_detector.preprocess_op]
    assert "_NormalizarCHW" in nombres and "_SinTrasponer" in nombres
    norm = NormalizeImage(scale="1./255.", mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225], order="hwc")
    imagen = np.random.default_rng(4).integers(0, 256, (96, 160, 3)).astype(np.uint8)
    esperado = ToCHWImage()(norm({"image": imagen}))["image"]
    rapido = ocr._SinTrasponer(ToCHWImage())(ocr._NormalizarCHW(norm)({"image": imagen}))["image"]
    assert rapido.shape == esperado.shape and np.array_equal(rapido, esperado)
    # Lo que no es de 8 bits va por el camino de siempre.
    flotante = imagen.astype(np.float32)
    otro = ocr._SinTrasponer(ToCHWImage())(ocr._NormalizarCHW(norm)({"image": flotante}))["image"]
    assert np.allclose(otro, esperado)


def test_leer_con_lado_minimo_solo_cambia_esa_lectura(motor_real, monkeypatch):
    """El lector bajo el cursor amplia menos su recuadro; el resto sigue con los 736 de siempre."""
    rapid = motor_real._cargar()
    ops = [op for op in rapid.text_detector.preprocess_op if type(op).__name__ == "DetResizeForTest"]
    antes = [op.limit_side_len for op in ops]
    vistos = []
    original = rapid.text_detector._original

    class Espia:
        def __getattr__(self, n):
            return getattr(original, n)

        def __call__(self, imagen):
            vistos.append([op.limit_side_len for op in ops])
            return original(imagen)

    monkeypatch.setattr(rapid.text_detector, "_original", Espia())
    imagen = ocr._imagen_de_prueba(620, 170)
    motor_real.leer(imagen, lado_minimo=608)
    motor_real.leer(imagen)
    assert vistos == [[608] * len(ops), antes]
    assert [op.limit_side_len for op in ops] == antes == [736] * len(ops)


def test_el_lector_del_cursor_pide_su_lado_minimo(monkeypatch):
    from farmadex.captura import cursor, reliquias

    lector = cursor.LectorCursor("rapidocr")
    assert lector.lado_minimo == cursor.LADO_MINIMO == 608
    llamadas = []
    monkeypatch.setattr(reliquias, "reconocer", lambda *a, **k: llamadas.append(k) or [])
    lector.casador = object()
    assert lector._leer_protegido(np.zeros((10, 10, 3), np.uint8), umbral=85) == []
    assert llamadas == [{"umbral": 85, "lado_minimo": 608}]


# --- lectura de la pantalla de mejoras con lo que de verdad devuelve el OCR a 1440p ------
# (lineas sacadas de videos de 2026 de la Haalvu en castellano e ingles)


@pytest.mark.parametrize("texto, esperado", [
    ("ME JORAS / HAALVU [22]", "HAALVU"), ("MEJ0RAS/HAALVU [22]", "HAALVU"), ("UPGRAOES/EXCALIBUR[30]", "EXCALIBUR"),
    ("MELH0RIAS / NOVA [30]", "NOVA"), ("RAS/ALGO", None), ("CAPACIDAD 2/60", None), ("Probabilidad/Critica", None),
])
def test_cabecera_con_erratas_en_la_palabra(texto, esperado):
    m = B.es_cabecera(texto)
    assert (m.group(1) if m else None) == esperado


@pytest.mark.parametrize("leido, esperado", [
    ("HAALVU I", ["HAALVU I", "HAALVU"]), ("HAALVU3O", ["HAALVU3O", "HAALVU"]),
    ("HAALV U [2 2 ]", ["HAALV U [2 2 ]", "HAALV U"]), ("HAALVU[3O\u30113", ["HAALVU[3O\u30113", "HAALVU"]),
    ("AX-52", ["AX-52"]), ("EXCALIBUR PRIME", ["EXCALIBUR PRIME"]), ("KUVA BRAMMA 3O", ["KUVA BRAMMA 3O", "KUVA BRAMMA"]),
])
def test_nombre_de_equipo_sin_restos_del_rango(leido, esperado):
    assert B._nombres_de_equipo(leido) == esperado


def test_la_caja_de_buscar_es_la_de_la_izquierda():
    from farmadex.captura.ocr import Leido

    lineas = [Leido("BUSCAR..", 142, 852, 200, 30, 0.8), Leido("BUSCAR", 1145, 1232, 120, 30, 0.8)]
    assert B.linea_buscar(lineas, 2560).y == 852
    assert B.linea_buscar([Leido("SEARCH", 1145, 1232, 120, 30, 0.8)], 2560).y == 1232  # como antes
    assert B.linea_buscar([], 2560) is None


def test_subbloques_casan_el_nombre_partido_con_el_rango_pegado(con):
    from farmadex.captura.ocr import Leido, casar_lineas

    _insertar(con, [
        ("/m/BaneGrineer", "Primed Bane of Grineer", "Perdicion del Grineer Prime", "Mods", None, None),
        ("/m/BaneInfested", "Primed Bane of Infested", "Perdicion de los Infestados Prime", "Mods", None, None),
        ("/m/BaneCorpus", "Primed Bane of Corpus", "Perdicion del Corpus Prime", "Mods", None, None),
    ])
    casador = ocr.Casador(con)
    lineas = [Leido("14Y", 1032, 938, 61, 30, 0.8), Leido("Primed Bane of", 854, 974, 192, 30, 0.8),
              Leido("Grineer", 900, 1001, 98, 35, 0.8)]
    # Con el rango pegado el bloque entero no llega al umbral (en el catalogo real, con
    # todas las "Primed Bane", salia ambiguo) y linea a linea no se sabe que mod es.
    assert casar_lineas(lineas, casador, 90) == []
    leidos = casar_lineas(lineas, casador, 90, subbloques=True)
    assert [r.nombre for r in leidos] == ["Primed Bane of Grineer"]
    assert leidos[0].caja == (854, 974, 192, 62)


def test_subbloques_no_convierten_descripciones_en_mods(con):
    from farmadex.captura.ocr import Leido, casar_lineas

    _insertar(con, [("/m/Cargada", "Charged Chamber", "Capacidad cargada", "Mods", None, None)])
    casador = ocr.Casador(con)
    # La descripcion de la tarjeta que se ensena al pasar el raton (visto a 1440p).
    lineas = [Leido("Fuego salvaje", 694, 1044, 215, 38, 0.8), Leido("+5% de capacidad de", 665, 1081, 276, 36, 0.8),
              Leido("cargador", 742, 1117, 122, 27, 0.8), Leido("+15% de calor", 696, 1144, 210, 29, 0.8),
              Leido("RIFLE", 765, 1189, 73, 29, 0.8)]
    assert casar_lineas(lineas, casador, 85, subbloques=True) == []


def test_alto_de_deteccion_de_la_pantalla_de_mejoras():
    assert B.alto_de_deteccion(720) == 1080  # no se amplia: leer_tira solo reduce
    assert B.alto_de_deteccion(1080) == 1080
    assert B.alto_de_deteccion(1440) == 1080
    assert B.alto_de_deteccion(2160) == 1080
