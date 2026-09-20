"""Pruebas de captura/: casado sin OCR, agrupado de lineas, fallos del motor, regiones."""

import numpy as np
import pytest

from farmadex.captura import ocr, pantalla
from farmadex.captura.cursor import LectorCursor
from farmadex.captura.ocr import (
    Casador,
    ErrorMotorOCR,
    Leido,
    MotorOCR,
    agrupar_bloques,
    preparar,
    unir_filas,
)
from farmadex.captura.reliquias import AVISO_MOTOR, LectorRecompensas


def _insertar(con, filas):
    """filas: (unique_name, nombre_en, nombre_es, categoria, padre_unique_name | None, ducados)."""
    ids = {}
    for unique, en, es, categoria, padre, ducados in filas:
        con.execute(
            "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, padre_id, ducados)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (unique, en, es, categoria, ids.get(padre), ducados),
        )
        ids[unique] = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.commit()
    return ids


@pytest.fixture()
def catalogo(con):
    ids = _insertar(con, [
        ("/w/Mirage", "Mirage", "Mirage", "Warframes", None, None),
        ("/w/MiragePrime", "Mirage Prime", "Mirage Prime", "Warframes", None, None),
        ("/w/MiragePrime/Bp", "Blueprint", "Plano", "Warframes", "/w/MiragePrime", 100),
        ("/w/MiragePrime/Sys", "Systems", "Sistemas", "Warframes", "/w/MiragePrime", 45),
        ("/w/MiragePrime/Chs", "Chassis", "Chasis", "Warframes", "/w/MiragePrime", 45),
        ("/w/Trinity/Neu", "Neuroptics", "Neuroptica", "Warframes", "/w/TrinityPrime", 45),
        ("/w/TrinityPrime", "Trinity Prime", "Trinity Prime", "Warframes", None, None),
        ("/w/TrinityPrime/Neu", "Neuroptics", "Neuroptica", "Warframes", "/w/TrinityPrime", 45),
        ("/p/Cycron", "Cycron", "Cycron", "Secondary", None, None),
        ("/p/Cycron/Bp", "Blueprint", "Plano", "Secondary", "/p/Cycron", None),
        ("/p/Bo", "Bo", "Bo", "Melee", None, None),
        ("/p/Bo/Bp", "Blueprint", "Plano", "Melee", "/p/Bo", None),
        ("/m/Blaze", "Blaze", "Llamarada", "Mods", None, None),
        ("/m/Pride", "Pride", "Orgullo", "Mods", None, None),
        ("/m/Recover", "Recover", "Recuperar", "Mods", None, None),
        ("/r/PhotorMk1", "Photor Vidar MK I", "Photor Vidar MK I", "Railjack", None, None),
        ("/r/PhotorMk4", "Photor Vidar MK IV", "Photor Vidar MK IV", "Railjack", None, None),
        ("/x/Shard", "<Shard_red_simple> Crimson Archon Shard",
         "<SHARD_RED_SIMPLE> Fragmento Carmesi de Arconte", "Misc", None, None),
        ("/m/Sure1", "Sure Shot", "Tiro seguro", "Mods", None, None),
        ("/m/Sure2", "Sure Shot", "Tiro seguro", "Mods", None, 15),
    ])
    return con, ids


# --- casado -------------------------------------------------------------------

def test_palabras_genericas_solas_no_casan_con_nada(catalogo):
    con, _ = catalogo
    casador = Casador(con)
    assert casador.casar("BLUEPRINT")[0] is None  # no es "Bo Blueprint"
    assert casador.casar("PRIME SYSTEMS")[0] is None
    assert casador.casar("PLANO")[0] is None


def test_palabras_cortas_exigen_mas_parecido(catalogo):
    con, _ = catalogo
    casador = Casador(con)
    assert casador.casar("BLADE", 80)[0] is None  # no es "Blaze"
    assert casador.casar("PRIME", 80)[0] is None  # no es "Pride"
    assert casador.casar("RECEVER", 80)[0] is None  # no es "Recover"


def test_nombre_exacto_gana_al_alias_sin_plano(catalogo):
    con, ids = catalogo
    casador = Casador(con)
    assert casador.casar("CYCRON")[0] == ids["/p/Cycron"]
    assert casador.casar("PLANO DE CYCRON")[0] == ids["/p/Cycron/Bp"]
    assert casador.casar("MIRAGE PRIME")[0] == ids["/w/MiragePrime"]


def test_texto_pegado_y_desordenado(catalogo):
    con, ids = catalogo
    casador = Casador(con)
    assert casador.casar("CHASISDEMIRAGEPRIME")[0] == ids["/w/MiragePrime/Chs"]
    assert casador.casar("SISTEMAS DE MIRAGE PRIME")[0] == ids["/w/MiragePrime/Sys"]
    # Errata del OCR (Y leida como V) con las palabras a medio pegar.
    assert casador.casar("NEUROPTICA DE TRINITVPRIME")[0] == ids["/w/TrinityPrime/Neu"]


def test_una_errata_en_un_nombre_corto_no_cambia_de_objeto(catalogo):
    con, ids = catalogo
    casador = Casador(con)
    # "MRAGE" a secas podria ser Mirage con una letra menos, pero es demasiado
    # corto para fiarse; con la palabra entera si se resuelve.
    assert casador.casar("MRAGE")[0] is None
    assert casador.casar("MRAGE PRIME")[0] == ids["/w/MiragePrime"]


def test_empate_entre_dos_objetos_distintos_no_se_decide(catalogo):
    con, _ = catalogo
    casador = Casador(con)
    # "MK N" es lo que el OCR saca de "MK IV" o de "MK I": no se sabe cual.
    assert casador.casar("PHOTOR VIDAR MK N")[0] is None


def test_marcas_de_icono_del_catalogo_se_ignoran(catalogo):
    con, ids = catalogo
    casador = Casador(con)
    assert casador.casar("CRIMSON ARCHON SHARD")[0] == ids["/x/Shard"]
    assert casador.casar("FRAGMENTO CARMESI DE ARCONTE")[0] == ids["/x/Shard"]


def test_nombres_repetidos_prefieren_el_que_tiene_datos(catalogo):
    con, ids = catalogo
    casador = Casador(con)
    assert casador.casar("SURE SHOT")[0] == ids["/m/Sure2"]


# --- agrupado de lo leido -------------------------------------------------------

def test_unir_filas_junta_trozos_de_la_misma_linea():
    filas = unir_filas([
        Leido("AKBOLTO PRIME", 100, 50, 200, 24, 0.9),
        Leido("BLUEPRINT", 310, 51, 140, 23, 0.8),
        Leido("FORMA", 900, 50, 90, 24, 0.9),  # otra tarjeta, lejos
    ])
    assert [f.texto for f in filas] == ["AKBOLTO PRIME BLUEPRINT", "FORMA"]
    assert filas[0].x == 100 and filas[0].ancho == 350 and filas[0].confianza == 0.8


def test_agrupar_bloques_junta_las_dos_lineas_de_un_nombre_partido():
    bloques = agrupar_bloques([
        Leido("NEUROPTICA DE", 640, 70, 250, 26, 0.9),
        Leido("TRINITY PRIME", 650, 112, 230, 22, 0.9),
        Leido("CYCRON", 1200, 90, 120, 22, 0.9),
    ])
    assert [[l.texto for l in b] for b in bloques] == [["NEUROPTICA DE", "TRINITY PRIME"], ["CYCRON"]]


def test_reconocer_prueba_el_bloque_entero_antes_que_cada_linea(catalogo):
    con, ids = catalogo
    casador = Casador(con)

    class MotorFalso:
        def leer(self, imagen):
            return [
                Leido("NEUROPTICA DE", 640, 70, 250, 26, 0.9),
                Leido("TRINITY PRIME", 650, 112, 230, 22, 0.9),
            ]

    reconocidos = ocr.reconocer(np.zeros((200, 800, 3), np.uint8), MotorFalso(), casador, 80)
    assert [r.item_id for r in reconocidos] == [ids["/w/TrinityPrime/Neu"]]
    assert reconocidos[0].caja == (640, 70, 250, 64)


# --- preprocesado -------------------------------------------------------------

def test_preparar_estira_el_contraste_y_devuelve_bgr_contiguo():
    imagen = np.full((40, 80, 4), 70, np.uint8)  # BGRA como mss
    imagen[10:30, 10:70, :3] = 120  # texto gris sobre gris
    salida = preparar(imagen)
    assert salida.shape == (40, 80, 3) and salida.flags["C_CONTIGUOUS"]
    assert salida.max() >= 250 and salida.min() <= 5
    assert preparar(None) is None and preparar(np.zeros((0, 0, 3), np.uint8)) is None


# --- fallos del motor -----------------------------------------------------------

@pytest.fixture()
def motor_roto(monkeypatch):
    MotorOCR.descargar()
    llamadas = []

    def reventar(hilos):
        llamadas.append(hilos)
        raise AttributeError("module 'ch_ppocr_v3_det' has no attribute 'TextDetector'")

    monkeypatch.setattr(ocr, "_crear_rapidocr", reventar)
    monkeypatch.setattr(pantalla, "capturar", lambda region: np.zeros((100, 300, 3), np.uint8))
    monkeypatch.setattr(pantalla, "declarar_dpi", lambda: None)
    yield llamadas
    MotorOCR.descargar()


def _con_indice(monkeypatch, con):
    from farmadex.datos import indice

    monkeypatch.setattr(indice, "hay_indice", lambda *a, **k: True)

    class Prestada:
        def __getattr__(self, nombre):
            return getattr(con, nombre)

        def close(self):
            pass

    monkeypatch.setattr(indice, "conectar", lambda *a, **k: Prestada())


def test_motor_que_no_carga_avisa_una_vez_y_no_revienta(catalogo, motor_roto, monkeypatch):
    con, _ = catalogo
    _con_indice(monkeypatch, con)
    lector = LectorRecompensas("rapidocr")
    estados, leidas = [], []
    lector.estado.connect(estados.append)
    lector.leidas.connect(leidas.append)

    lector.leer_ahora()
    lector.leer_ahora()
    lector.leer_ahora()

    assert estados.count(AVISO_MOTOR) == 1
    assert leidas == [[], [], []]  # la interfaz recibe siempre su respuesta
    assert len(motor_roto) == 1  # no se reintenta la carga en bucle
    with pytest.raises(ErrorMotorOCR):
        lector.motor._cargar()


def test_cambiar_de_motor_permite_reintentar(catalogo, motor_roto, monkeypatch):
    con, _ = catalogo
    _con_indice(monkeypatch, con)
    lector = LectorCursor("rapidocr")
    estados = []
    lector.estado.connect(estados.append)
    lector.leer_ahora()
    lector.leer_ahora()
    assert estados.count(AVISO_MOTOR) == 1 and len(motor_roto) == 1

    lector.cambiar_motor("rapidocr")
    lector.leer_ahora()
    assert len(motor_roto) == 2  # se volvio a intentar...
    assert estados.count(AVISO_MOTOR) == 2  # ...y se aviso otra vez, una sola


def test_los_dos_lectores_comparten_el_motor(monkeypatch):
    MotorOCR.descargar()
    creados = []
    monkeypatch.setattr(ocr, "_crear_rapidocr", lambda hilos: creados.append(hilos) or object())
    try:
        a, b = MotorOCR("rapidocr"), MotorOCR("rapidocr")
        assert a._cargar() is b._cargar()
        assert creados == [ocr.HILOS_OCR]
    finally:
        MotorOCR.descargar()


def test_sin_indice_avisa_de_datos_y_no_revienta(monkeypatch, tmp_path):
    from farmadex.datos import indice

    monkeypatch.setattr(indice, "hay_indice", lambda *a, **k: False)
    lector = LectorRecompensas("rapidocr")
    estados = []
    lector.estado.connect(estados.append)
    lector.leer_ahora()
    assert lector.casador is None
    assert any("datos" in e.lower() for e in estados)


# --- regiones -----------------------------------------------------------------

def test_recuadro_del_cursor_no_se_sale_del_escritorio_con_dos_monitores(monkeypatch):
    # Segundo monitor a la izquierda del primario: coordenadas negativas.
    monkeypatch.setattr(pantalla, "_escritorio_virtual",
                        lambda: pantalla.Region(-1920, 0, 1920 + 2560, 1440))
    monkeypatch.setattr(pantalla, "_posicion_cursor", lambda: (-1900, 10))
    region = pantalla.region_alrededor_del_cursor(620, 170)
    assert (region.x, region.y) == (-1920, 0)

    monkeypatch.setattr(pantalla, "_posicion_cursor", lambda: (2550, 1430))
    region = pantalla.region_alrededor_del_cursor(620, 170)
    assert region.x + region.ancho == 2560 and region.y + region.alto == 1440


def test_recortar_franja_en_proporciones():
    region = pantalla.Region(100, 200, 1000, 500).recortar(0.1, 0.3, 0.9, 0.7)
    assert (region.x, region.y, region.ancho, region.alto) == (200, 350, 800, 200)


# --- precalentado del motor al arrancar ------------------------------------------


def test_iniciar_precalienta_el_motor_una_sola_vez(monkeypatch):
    """La primera reliquia no paga ni la carga del modelo ni la primera inferencia."""
    from farmadex.datos import indice

    MotorOCR.descargar()
    lecturas = []

    def motor_falso(imagen):
        lecturas.append(imagen.shape)
        return [], None

    creados = []
    monkeypatch.setattr(ocr, "_crear_rapidocr", lambda hilos: creados.append(hilos) or motor_falso)
    monkeypatch.setattr(indice, "hay_indice", lambda *a, **k: False)
    monkeypatch.setattr(pantalla, "declarar_dpi", lambda: None)
    try:
        a, b = LectorRecompensas("rapidocr"), LectorCursor("rapidocr")
        a.iniciar()
        b.iniciar()
        assert creados == [ocr.HILOS_OCR]  # el modelo se carga al arrancar, una vez
        assert len(lecturas) == 1  # y la lectura de prueba se hace una vez por motor compartido
        alto, ancho, canales = lecturas[0]
        assert canales == 3 and ancho > alto  # del tamano y forma de la franja de recompensas
        a.iniciar()  # reintentos (sin indice) no vuelven a calentar
        assert len(lecturas) == 1
    finally:
        MotorOCR.descargar()


def test_motor_roto_no_revienta_el_arranque_y_avisa_una_vez(catalogo, motor_roto, monkeypatch):
    con, _ = catalogo
    _con_indice(monkeypatch, con)
    lector = LectorRecompensas("rapidocr")
    estados = []
    lector.estado.connect(estados.append)

    lector.iniciar()  # no lanza nada; el fallo queda apuntado en el motor
    assert estados == []  # y no se avisa hasta que el usuario pide leer
    assert lector.casador is not None  # el casador se prepara igual

    lector.leer_ahora()
    lector.leer_ahora()
    assert estados.count(AVISO_MOTOR) == 1
    assert len(motor_roto) == 1  # iniciar no reintenta la carga
