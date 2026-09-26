"""herramientas/iconos/generar_ico.py: SVG -> .ico con todos los tamanos, sin tocar el del programa."""

import importlib.util
import struct
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<rect x="10" y="10" width="236" height="236" rx="48" fill="#12100c"/>
<circle cx="128" cy="128" r="80" fill="#e6b450"/>
</svg>"""


@pytest.fixture(scope="module")
def modulo():
    ruta = RAIZ / "herramientas" / "iconos" / "generar_ico.py"
    spec = importlib.util.spec_from_file_location("generar_ico", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _entradas(datos: bytes):
    reservado, tipo, cuantas = struct.unpack_from("<HHH", datos, 0)
    assert (reservado, tipo) == (0, 1)
    for i in range(cuantas):
        ancho, alto, _, _, planos, bits, tam, desp = struct.unpack_from("<BBBBHHII", datos, 6 + 16 * i)
        yield (ancho or 256), (alto or 256), planos, bits, datos[desp:desp + tam]


def test_el_ico_lleva_todos_los_tamanos(modulo, tmp_path):
    svg = tmp_path / "icono.svg"
    svg.write_text(SVG, encoding="utf-8")
    ico = modulo.generar(svg, tmp_path / "salida" / "icono.ico")
    entradas = list(_entradas(ico.read_bytes()))
    assert [e[0] for e in entradas] == [16, 24, 32, 48, 64, 128, 256]
    for ancho, alto, planos, bits, blob in entradas:
        assert ancho == alto and planos == 1 and bits == 32
        if ancho == 256:
            assert blob.startswith(b"\x89PNG")
        else:
            # BITMAPINFOHEADER con alto doble (imagen + mascara) y tamano exacto.
            tam_cab, w, h = struct.unpack_from("<Iii", blob, 0)
            assert (tam_cab, w, h) == (40, ancho, ancho * 2)
            assert len(blob) == 40 + ancho * ancho * 4 + ((ancho + 31) // 32) * 4 * ancho


def test_el_16_tiene_transparencia_en_las_esquinas_y_color_en_el_centro(modulo, tmp_path):
    svg = tmp_path / "icono.svg"
    svg.write_text(SVG, encoding="utf-8")
    blob = next(e[4] for e in _entradas(modulo.construir_ico(svg)) if e[0] == 16)
    pixeles = blob[40:40 + 16 * 16 * 4]
    esquina = pixeles[0:4]  # fila de abajo, columna 0
    centro = pixeles[(8 * 16 + 8) * 4:(8 * 16 + 8) * 4 + 4]
    assert esquina[3] == 0
    b, g, r, a = centro
    assert a == 255 and r > 200 and g > 150 and b < 120  # dorado


def test_nunca_pisa_el_icono_del_programa(modulo, tmp_path):
    svg = tmp_path / "icono.svg"
    svg.write_text(SVG, encoding="utf-8")
    antes = modulo.ICO_DEL_PROGRAMA.read_bytes()
    with pytest.raises(ValueError):
        modulo.generar(svg, modulo.ICO_DEL_PROGRAMA)
    assert modulo.ICO_DEL_PROGRAMA.read_bytes() == antes
    assert modulo.SALIDA_POR_DEFECTO != modulo.ICO_DEL_PROGRAMA


def test_svg_roto_da_error_claro(modulo, tmp_path):
    svg = tmp_path / "roto.svg"
    svg.write_text("esto no es un svg", encoding="utf-8")
    with pytest.raises(ValueError):
        modulo.construir_ico(svg)


def test_la_bandeja_usa_el_icono_del_programa():
    """La bandeja y los avisos ensenan el mismo icono que el .exe, no la F dibujada a mano."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from farmadex.ui.overlay import icono_bandeja, ruta_icono

    assert ruta_icono().exists()
    mapa = icono_bandeja()
    assert not mapa.isNull() and mapa.width() == 64
