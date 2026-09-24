"""Lo nuevo: fecha y actualizacion de cada objeto en el indice, y "el ultimo warframe"."""

import json
import os
import sqlite3
from urllib.parse import unquote

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.datos import novedades  # noqa: E402

# Como Warframes.json de WFCD tras la Actualizacion 44.0 (comprobado el 2026-09-24): Narin
# y Citrine Prime salen en ella; Styanax Prime, en la 43.0. Un objeto con `introduced`
# solo como texto (formato viejo) y otro sin fecha.
WARFRAMES = [
    {"uniqueName": "/P/Narin", "name": "Narin", "category": "Warframes", "type": "Warframe",
     "releaseDate": "2026-09-23",
     "introduced": {"name": "Update 44.0", "date": "2026-09-23", "aliases": ["44", "44.0"], "parent": "44.0"}},
    {"uniqueName": "/P/CitrinePrime", "name": "Citrine Prime", "category": "Warframes", "type": "Warframe",
     "isPrime": True, "releaseDate": "2026-09-23",
     "introduced": {"name": "Update 44.0", "date": "2026-09-23"}},
    {"uniqueName": "/P/StyanaxPrime", "name": "Styanax Prime", "category": "Warframes", "type": "Warframe",
     "isPrime": True, "releaseDate": "2026-06-17", "introduced": {"name": "Update 43.0", "date": "2026-06-17"}},
    {"uniqueName": "/P/Viejo", "name": "Viejo", "category": "Warframes", "type": "Warframe",
     "introduced": "Update 10.0"},
    {"uniqueName": "/P/SinFecha", "name": "Sin Fecha", "category": "Warframes", "type": "Warframe"},
]
ARMAS = [
    {"uniqueName": "/P/Corufell", "name": "Corufell", "category": "Primary", "type": "Rifle",
     "releaseDate": "2026-09-23", "introduced": {"name": "Update 44.0", "date": "2026-09-23"}},
    # Un prime de un hotfix de la misma actualizacion, unos dias despues: cuenta como de la 44.0.
    {"uniqueName": "/P/SteflosPrime", "name": "Steflos Prime", "category": "Primary", "type": "Rifle",
     "isPrime": True, "releaseDate": "2026-09-25", "introduced": {"name": "Hotfix 44.0.2", "date": "2026-09-25"}},
    # Un mod "Primed" lleva es_prime por el nombre, pero no es un prime.
    {"uniqueName": "/P/PrimedMod", "name": "Primed Polar Magazine", "category": "Mods", "type": "Mod",
     "releaseDate": "2026-08-19", "introduced": {"name": "Hotfix 43.5.4", "date": "2026-08-19"}},
]


@pytest.fixture(autouse=True)
def castellano():
    idiomas.cargar("es")
    yield
    idiomas.cargar("es")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def indice(con, tmp_path):
    from farmadex.datos.items import ImportadorItems

    importador = ImportadorItems(con, {})
    for nombre, datos in (("Warframes", WARFRAMES), ("Primary", ARMAS)):
        ruta = tmp_path / f"{nombre}.json"
        ruta.write_text(json.dumps(datos), encoding="utf-8")
        importador.importar_categoria(ruta)
    con.commit()
    from farmadex.datos import indice as modulo

    modulo.poblar_busqueda(con)
    return con


def test_el_indice_guarda_fecha_y_actualizacion(indice):
    filas = dict(
        (nombre, (fecha, act))
        for nombre, fecha, act in indice.execute("SELECT nombre_en, fecha_salida, actualizacion FROM items")
    )
    assert filas["Narin"] == ("2026-09-23", "Update 44.0")
    assert filas["Steflos Prime"] == ("2026-09-25", "Hotfix 44.0.2")
    # `introduced` como texto: la actualizacion si, la fecha no (no la trae).
    assert filas["Viejo"] == (None, "Update 10.0")
    assert filas["Sin Fecha"] == (None, None)


def test_la_ultima_actualizacion_junta_sus_hotfixes(indice):
    datos = novedades.ultima(indice)
    assert datos["numero"] == "44.0" and datos["fecha"] == "2026-09-23"
    nombres = [f["nombre_en"] for f in datos["items"]]
    # Warframes delante, luego armas; dentro, los primes detras.
    assert nombres == ["Narin", "Citrine Prime", "Corufell", "Steflos Prime"]
    assert novedades.titulo(datos) == "Actualizacion 44.0"
    assert novedades.fecha_legible(datos["fecha"]) == "23/09/2026"
    idiomas.cargar("en")
    assert novedades.titulo(datos) == "Update 44.0" and novedades.fecha_legible("2026-09-23") == "2026-09-23"


def test_filtros_de_novedades(indice):
    assert [f["nombre_en"] for f in novedades.ultima(indice, "warframe")["items"]] == ["Narin", "Citrine Prime"]
    assert [f["nombre_en"] for f in novedades.ultima(indice, "arma")["items"]] == ["Corufell", "Steflos Prime"]
    # El mod "Primed" no es un prime.
    primes = [f["nombre_en"] for f in novedades.ultima(indice, "prime")["items"]]
    assert primes == ["Citrine Prime", "Steflos Prime"]


def test_indice_viejo_sin_columnas_de_fecha():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, nombre_en TEXT, padre_id INTEGER)")
    assert novedades.ultima(con) is None


@pytest.fixture()
def buscador(app, indice, tmp_path, monkeypatch):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_buscador import PestanaBuscador

    b = PestanaBuscador()
    b.con = indice
    return b


def _buscar(buscador, texto):
    buscador.caja.setText(texto)
    buscador._temporizador.stop()
    buscador._buscar()


def test_el_ultimo_warframe_abre_narin_y_menciona_los_demas(buscador):
    _buscar(buscador, "como sacar el ultimo warframe")
    narin = buscador.con.execute("SELECT id FROM items WHERE nombre_en = 'Narin'").fetchone()[0]
    citrine = buscador.con.execute("SELECT id FROM items WHERE nombre_en = 'Citrine Prime'").fetchone()[0]
    assert buscador._actual == narin
    texto = buscador.ficha.toPlainText()
    assert "Lo mas nuevo: Actualizacion 44.0 (23/09/2026)." in texto and "Tambien salio: Citrine Prime" in texto
    assert f"item:{citrine}" in unquote(buscador.ficha.toHtml())


def test_novedades_abre_la_ficha_de_la_actualizacion(buscador):
    _buscar(buscador, "novedades")
    assert buscador._mision_actual == "novedades:todo"
    texto = buscador.ficha.toPlainText()
    assert "Lo nuevo de la Actualizacion 44.0 (23/09/2026)" in texto
    for nombre in ("Narin", "Citrine Prime", "Corufell", "Steflos Prime"):
        assert nombre in texto
    assert "Como conseguirlo" in texto
    # El ultimo prime: varios, asi que la ficha de novedades (no un objeto suelto).
    _buscar(buscador, "ultimo prime")
    assert buscador._mision_actual == "novedades:prime"


def test_con_el_buscador_vacio_una_linea_de_novedades(buscador):
    _buscar(buscador, "")
    texto = buscador.ficha.toPlainText()
    assert texto.startswith("Novedades (Actualizacion 44.0): Narin, Citrine Prime")


def test_sin_datos_de_fecha_un_aviso_claro(app, con, tmp_path, monkeypatch):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_buscador import PestanaBuscador

    b = PestanaBuscador()
    b.con = con  # indice vacio: nada con fecha
    _buscar(b, "ultimo warframe")
    assert "No hay datos de fecha de salida" in b.ficha.toPlainText()
