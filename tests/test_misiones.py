"""Buscar una mision (nodo o tipo), su ficha, las muletillas de pregunta y las guias de YouTube."""

import os
from urllib.parse import unquote

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.datos import consultas, misiones  # noqa: E402
from farmadex.ui import guias_youtube  # noqa: E402

WIKI = "https://wiki.warframe.com"
YT = "https://www.youtube.com/results?search_query="


@pytest.fixture(autouse=True)
def castellano():
    idiomas.cargar("es")
    yield
    idiomas.cargar("es")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def buscador(app, indice_poblado, tmp_path, monkeypatch):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_buscador import PestanaBuscador

    con, _, _ = indice_poblado
    b = PestanaBuscador()
    b.con = con
    return b


@pytest.fixture()
def abiertas(monkeypatch):
    from PySide6.QtGui import QDesktopServices

    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: urls.append(url.toString()) or True))
    return urls


def _buscar(buscador, texto):
    buscador.caja.setText(texto)
    buscador._temporizador.stop()
    buscador._buscar()


# -- muletillas -----------------------------------------------------------------------

@pytest.mark.parametrize(("texto", "queda"), [
    ("como sacar citrine prime", "citrine prime"),
    ("¿Cómo conseguir Citrine Prime?", "citrine prime"),
    ("donde farmear hepit", "hepit"),
    ("como hacer hepit", "hepit"),
    ("how to get citrine prime", "citrine prime"),
    ("where to farm hepit", "hepit"),
    ("comment obtenir citrine prime", "citrine prime"),
    ("wie bekomme ich citrine prime", "citrine prime"),
    ("como pegar citrine prime", "citrine prime"),
    ("onde farmar hepit", "hepit"),
    # Sin muletilla, o si la muletilla es todo lo escrito, se queda tal cual.
    ("citrine prime", "citrine prime"),
    ("como sacar", "como sacar"),
])
def test_quita_las_muletillas_de_pregunta(texto, queda):
    assert consultas.limpiar(texto).lower() == queda


@pytest.mark.parametrize(("texto", "filtro"), [
    ("como sacar el ultimo warframe", "warframe"),
    ("ultimo warframe", "warframe"),
    ("la ultima arma", "arma"),
    ("ultimo prime", "prime"),
    ("nuevo warframe prime", "warframe prime"),
    ("lo nuevo", "todo"),
    ("novedades", "todo"),
    ("ultima actualizacion", "todo"),
    ("latest warframe", "warframe"),
    ("new prime", "prime"),
    ("dernier warframe", "warframe"),
    ("neueste waffe", "arma"),
    ("novidades", "todo"),
    # Nombres de verdad que llevan una de esas palabras: busqueda normal.
    ("nova prime", None),
    ("new loka", None),
    ("ash prime", None),
])
def test_intencion_de_novedad(texto, filtro):
    assert consultas.intencion_novedad(texto) == filtro


# -- buscar misiones ------------------------------------------------------------------

def test_buscar_nodo_y_tipo_de_mision(indice_poblado):
    con, _, _ = indice_poblado
    nodo = misiones.buscar(con, "hydron")
    assert nodo and nodo[0]["clave"].startswith("nodo:") and nodo[0]["nivel"] == 0
    assert nodo[0]["modo"] == "Defense" and nodo[0]["planeta_en"] == "Sedna"
    # En castellano, en ingles, y empezando por lo escrito.
    for texto in ("defensa", "Defense", "defen"):
        claves = [r["clave"] for r in misiones.buscar(con, texto)]
        assert "modo:Defense" in claves, texto
    # Dos letras: solo coincidencia exacta ("de" no trae todo lo que empieza por De).
    assert misiones.buscar(con, "de") == []
    # El Circuito por nivel y el sabotaje con escondites no son tipos que se busquen.
    assert not [r for r in misiones.buscar(con, "normal") if r["clave"] == "modo:Normal"]
    assert [n["nodo_en"] for n in misiones.nodos_de_modo(con, "Defense")] == ["Hydron"]


def test_el_nodo_abre_su_ficha_con_rotaciones_y_premios(buscador):
    _buscar(buscador, "hydron")
    assert buscador._mision_actual and buscador._mision_actual.startswith("nodo:")
    assert buscador._actual is None and not buscador.boton_objetivo.isEnabled()
    html = unquote(buscador.ficha.toHtml())
    assert "Hydron" in html and "Sedna" in html
    assert "Protege el objetivo" in html  # que hacer en una Defensa
    assert "(oleada 12)" in html  # la rotacion C a la vista
    assert "Aqui la rotacion C es la recompensa de las oleadas 12, 24, 36..." in html
    # Lo que suelta, por rotacion, enlazado a la ficha de cada objeto.
    axi = buscador.con.execute("SELECT id FROM items WHERE nombre_en = 'Axi A7 Relic'").fetchone()[0]
    assert f"item:{axi}" in html and "11.1%" in html
    # La wiki del nodo y del modo, y las guias en video.
    assert f"{WIKI}/w/Hydron" in html and f"{WIKI}/w/Defense" in html and "video:" in html
    assert buscador.url_wiki() == f"{WIKI}/w/Hydron"
    # "Como hacer hydron" es lo mismo.
    _buscar(buscador, "como hacer hydron")
    assert buscador._mision_actual.startswith("nodo:")


def test_el_tipo_de_mision_abre_su_ficha_con_sus_nodos(buscador):
    _buscar(buscador, "defensa")
    assert buscador._mision_actual == "modo:Defense"
    html = unquote(buscador.ficha.toHtml())
    assert "Tipo de mision" in html and "NODOS DE ESTE TIPO (1)" in html
    nodo = buscador.con.execute("SELECT id FROM nodos WHERE nombre_en = 'Hydron'").fetchone()[0]
    assert f"nodo:{nodo}" in html
    # Pinchar el nodo abre su ficha; Atras vuelve a la del tipo.
    from PySide6.QtCore import QUrl

    buscador._enlace(QUrl(f"nodo:{nodo}"))
    assert buscador._mision_actual == f"nodo:{nodo}"
    buscador._volver()
    assert buscador._mision_actual == "modo:Defense"


def test_la_ficha_de_disrupcion_trae_la_tabla_de_rondas(buscador):
    buscador.abrir_mision("modo:Disruption")
    texto = buscador.ficha.toPlainText()
    assert "Conductos salvados" in texto and "4+" in texto
    assert "rondas 1-2 con 4 conductos" in texto
    assert "Cuanto mas avanzas" not in texto


def test_los_objetos_siguen_delante_si_casan(buscador):
    _buscar(buscador, "ash prime")
    assert buscador._resultados[0].get("clave") is None
    assert buscador._actual is not None


# -- guias en YouTube -----------------------------------------------------------------

@pytest.mark.parametrize(("idioma", "consulta"), [
    ("es", "warframe+Hydron+Defensa"),
    ("en", "warframe+Hydron+Defense"),
    ("fr", "warframe+Hydron+Defense"),
    ("de", "warframe+Hydron+Defense"),
    ("pt", "warframe+Hydron+Defense"),
])
def test_url_de_youtube_en_el_idioma_de_la_interfaz(buscador, idioma, consulta):
    _buscar(buscador, "hydron")
    idiomas.cargar(idioma)
    assert buscador.url_youtube() == f"{YT}{consulta}&sp=CAM%253D"


def test_el_boton_de_youtube_va_al_reproductor_o_al_navegador(buscador, abiertas):
    assert not buscador.boton_youtube.isEnabled()
    _buscar(buscador, "hydron")
    assert buscador.boton_youtube.isEnabled()
    # Sin reproductor (pestana suelta): navegador del sistema.
    buscador.boton_youtube.click()
    assert abiertas == [f"{YT}warframe+Hydron+Defensa&sp=CAM%253D"]
    # Con reproductor (la ventana lo pone): dentro de Farmadex, sin navegador.
    pedidas = []
    buscador.reproductor = pedidas.append
    buscador.boton_youtube.click()
    assert pedidas == [abiertas[0]] and len(abiertas) == 1
    # Con una ficha de objeto, la guia es del objeto.
    ash = buscador.con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    buscador.abrir(ash)
    assert buscador.url_youtube() == f"{YT}warframe+Ash+Prime&sp=CAM%253D"


def test_la_clave_de_api_es_solo_un_punto_de_extension():
    # Con o sin clave, hoy siempre la busqueda (ninguna llamada de red).
    assert guias_youtube.url_guia("Hepit Captura", "clave") == guias_youtube.url_guia("Hepit Captura")
    assert guias_youtube.url_guia("  ") == ""
