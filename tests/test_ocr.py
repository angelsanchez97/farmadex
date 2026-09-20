"""Pruebas del OCR con imagenes generadas: no hacen falta capturas del juego."""

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from farmadex.captura.ocr import Casador, MotorOCR, reconocer


def imagen_con(textos, ancho=1000, alto=260):
    img = Image.new("RGB", (ancho, alto), (12, 16, 22))
    dibujo = ImageDraw.Draw(img)
    try:
        fuente = ImageFont.truetype("seguisb.ttf", 34)
    except OSError:  # pragma: no cover - depende de las fuentes del sistema
        fuente = ImageFont.load_default()
    for i, texto in enumerate(textos):
        dibujo.text((30, 30 + i * 70), texto, fill=(232, 236, 245), font=fuente)
    return np.array(img)[:, :, ::-1].copy()


@pytest.fixture(scope="module")
def motor():
    return MotorOCR()


def test_casador_encuentra_por_nombre_en_espanol(indice_poblado):
    con, _, _ = indice_poblado
    casador = Casador(con)
    item_id, nombre, puntos = casador.casar("SISTEMAS DE ASH PRIME")
    assert item_id and "Sistemas" in nombre and puntos > 80


def test_casador_aguanta_erratas_del_ocr(indice_poblado):
    con, _, _ = indice_poblado
    casador = Casador(con)
    assert casador.casar("ASH PRIME SYSTENS")[0] is not None
    assert casador.casar("ASH PRIME SYSTEMS BLUEPRINT")[0] is not None


def test_casador_rechaza_lo_que_no_es_un_objeto(indice_poblado):
    con, _, _ = indice_poblado
    casador = Casador(con)
    assert casador.casar("SELECCIONA TU RECOMPENSA")[0] is None
    assert casador.casar("ab")[0] is None


@pytest.mark.slow
def test_lectura_completa_de_una_pantalla_sintetica(indice_poblado, motor):
    con, _, _ = indice_poblado
    casador = Casador(con)
    imagen = imagen_con(["SISTEMAS DE ASH PRIME", "CHASIS DE ASH PRIME"])
    reconocidos = reconocer(imagen, motor, casador, umbral=80)

    nombres = {r.nombre for r in reconocidos}
    assert any("Sistemas" in n for n in nombres)
    assert any("Chasis" in n for n in nombres)
    # Cada uno con su caja, que es lo que permite pintar la etiqueta encima.
    assert all(r.caja[2] > 0 and r.caja[3] > 0 for r in reconocidos)

