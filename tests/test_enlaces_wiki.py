"""Enlaces a la wiki oficial, el boton "Buscar en la wiki" y las rotaciones a la vista."""

import os
from urllib.parse import unquote

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.datos import eficiencia  # noqa: E402
from farmadex.datos import modos_mision as mm  # noqa: E402
from farmadex.ui import desglose_tiempo, enlaces_wiki, glosario  # noqa: E402

WIKI = "https://wiki.warframe.com"


@pytest.fixture(autouse=True)
def castellano():
    idiomas.cargar("es")
    yield
    idiomas.cargar("es")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# -- direcciones ----------------------------------------------------------------------

def test_direcciones_de_reliquia_nodo_y_modo():
    assert enlaces_wiki.url_reliquia("Lith S19 Relic") == f"{WIKI}/w/Lith_S19"
    assert enlaces_wiki.url_reliquia("Requiem I Relic") == f"{WIKI}/w/Requiem_I"
    assert enlaces_wiki.url_nodo("Hepit") == f"{WIKI}/w/Hepit"
    assert enlaces_wiki.url_nodo("Olympus") == f"{WIKI}/w/Olympus"
    # War es la espada de Stalker: el nodo es "War (Node)".
    assert enlaces_wiki.url_nodo("War") == f"{WIKI}/w/War_(Node)"
    assert enlaces_wiki.url_modo("Survival") == f"{WIKI}/w/Survival"
    assert enlaces_wiki.url_modo("Mobile Defense") == f"{WIKI}/w/Mobile_Defense"
    assert enlaces_wiki.url_modo("Arbitrations") == f"{WIKI}/w/Arbitrations"
    assert enlaces_wiki.url_modo("Orphix") == f"{WIKI}/w/Orphix_(Mission)"
    assert enlaces_wiki.url_modo("Nada") == "" and enlaces_wiki.url_nodo(None) == ""
    assert enlaces_wiki.url_busqueda(" sistemas ash prime ") == f"{WIKI}/?search=sistemas+ash+prime"
    assert enlaces_wiki.url_item({"wiki_url": "https://x/y", "categoria": "Warframes"}) == "https://x/y"
    assert enlaces_wiki.url_item({"wiki_url": None, "categoria": "Relics", "nombre_en": "Axi A7 Relic"}) == f"{WIKI}/w/Axi_A7"
    assert enlaces_wiki.url_item({"wiki_url": None, "categoria": "Mods", "nombre_en": "Serration"}) == ""


def test_el_nodo_se_enlaza_sin_cambiar_de_color_y_el_resto_se_queda():
    fila = {"donde": "Hepit, Vacio", "nodo_en": "Hepit", "nodo_es": "Hepit"}
    html = enlaces_wiki.donde(fila, "#abc")
    assert html == f"<a href='{WIKI}/w/Hepit' style='color:#abc;text-decoration:none'>Hepit</a>, Vacio"
    # Un contrato o un jefe no empieza por el nodo: tal cual, escapado.
    jefe = {"donde": "Alad V (Themisto, Jupiter)", "nodo_en": "Themisto"}
    assert enlaces_wiki.donde(jefe, "#abc") == "Alad V (Themisto, Jupiter)"


def test_la_linea_de_la_wiki_junta_modos_y_nodos_sin_repetir():
    filas = [
        {"modo": "Capture", "nodo_en": "Hepit", "nodo_es": "Hepit"},
        {"modo": "Disruption", "nodo_en": "Olympus", "nodo_es": "Olimpo"},
        {"modo": "Capture", "nodo_en": "Ukko", "nodo_es": "Ukko"},
        {"modo": "", "nodo_en": None},
    ]
    linea = enlaces_wiki.linea(filas, "#111", "#222")
    assert linea.count(f"{WIKI}/w/Capture") == 1
    assert ">Captura</a>" in linea and ">Disrupcion</a>" in linea and ">Olimpo</a>" in linea
    assert f"{WIKI}/w/Olympus" in linea and "En la wiki:" in linea
    # Modos primero, luego nodos.
    assert linea.index("Disrupcion") < linea.index("Hepit")
    assert enlaces_wiki.linea([{"modo": "", "nodo_en": None}], "#1", "#2") == ""


# -- rotaciones a la vista ------------------------------------------------------------

@pytest.mark.parametrize(("modo", "letra", "corta"), [
    ("Survival", "C", "min 20"),
    ("Survival", "A", "min 5 y 10"),
    ("Survival", "B", "min 15"),
    ("Conjunction Survival", "C", "min 20"),
    ("Defense", "C", "oleada 12"),
    ("Defense", "a", "oleadas 3 y 6"),
    ("Excavation", "C", "4a excavadora"),
    ("Interception", "C", "4a ronda"),
    ("Spy", "C", "3a boveda"),
    ("Defection", "C", "8 grupos"),
    ("Void Cascade", "C", "16 Exolizadores"),
    ("Arbitrations", "C", "de la 5a en adelante"),
    ("Disruption", "A", "rondas 1-2 con 1-2 conductos"),
    ("Disruption", "B", "rondas 1-2 con 4 conductos"),
    ("Disruption", "C", "ronda 3+ con 4 conductos"),
    # Sin regla clara, nada: mejor nada que inventar.
    ("Mirror Defense", "C", ""),
    ("Skirmish", "B", ""),
    ("The Circuit", "A", ""),
    ("Nada", "C", ""),
    ("Survival", None, ""),
])
def test_forma_corta_de_la_rotacion(modo, letra, corta):
    assert mm.rotacion_corta(modo, letra) == corta


def test_la_rotacion_se_ve_con_su_forma_corta_y_sigue_con_su_tooltip():
    enlace = glosario.enlace_rotacion("Survival", "C", "Rotacion C", "#abc")
    assert ">Rotacion C (min 20)</a>" in enlace and "glosa:rotacion?" in enlace
    # Modo sin regla: solo la letra, como antes.
    assert ">Rotacion C</a>" in glosario.enlace_rotacion("Mirror Defense", "C", "Rotacion C", "#abc")


def test_la_forma_corta_se_traduce():
    idiomas.cargar("en")
    assert mm.rotacion_corta("Survival", "C") == "min 20"
    assert mm.rotacion_corta("Defense", "A") == "waves 3 and 6"
    assert mm.rotacion_corta("Disruption", "C") == "round 3+ with 4 conduits"
    idiomas.cargar("de")
    assert mm.rotacion_corta("Spy", "C") == "3. Tresor"


def test_disrupcion_ya_no_dice_que_salvar_mas_siempre_es_mejor():
    texto = mm.MODOS["Disruption"][3]
    assert "Cuanto mas avanzas" not in texto
    assert "al menos un conducto" in texto and "sal tras la ronda 2" in texto
    assert "desde la ronda 4 ya no sale" in mm.linea_rotacion("Disruption", "A")
    assert "rondas 1 y 2 salvando los cuatro" in mm.linea_rotacion("Disruption", "B")


# -- tiempos de Disrupcion ------------------------------------------------------------

def _disrupcion(letra):
    return {"tipo": "mision", "origen_texto": "", "rotacion": letra, "etapa": None, "probabilidad": 10.0,
            "probabilidad_enemigo": None, "modo": "Disruption", "jefe": False}


def test_disrupcion_con_su_regla_de_rondas_y_conductos():
    minutos = {r: eficiencia.minutos_por_intento(_disrupcion(r))[0] for r in "ABC"}
    # Rondas de 4 min, mas llegar/extraer (3) y la carga (1.5):
    # A: rondas 1-2 dejando caer conductos -> (2*4 + 4.5) / 2 A = 6.25 min por A.
    # B: rondas 1-2 salvando los cuatro -> (2*4 + 4.5) / 2 B = 6.25 (antes 16.5, B en la 3.a ronda).
    # C: salir tras la ronda 4 con C en la 3 y la 4 -> (4*4 + 4.5) / 2 C = 10.25 (antes 20.5).
    assert minutos == {"A": 6.25, "B": 6.25, "C": 10.25}
    # El resto de modos sin fin sigue con A, A, B, C: Supervivencia C = 4*5 + 4.5.
    superv = dict(_disrupcion("C"), modo="Survival")
    assert eficiencia.minutos_por_intento(superv)[0] == 24.5


def test_el_desglose_de_disrupcion_habla_de_rondas():
    texto = desglose_tiempo.texto(_disrupcion("C"))
    primera = texto.splitlines()[0]
    assert primera == ("~20 min por partida (4 rondas de ~4 min mas llegar, extraer y la carga), que dan "
                       "2 premios de la rotacion C: ~10.2 min por intento.")
    assert "rotaciones" not in primera
    # 10.25 min por intento al 10 % -> ~102.5 min de media (1.7 h).
    assert "x ~10 intentos de media (10.0% cada uno) = ~1.7 h." in texto


# -- la ficha y el boton --------------------------------------------------------------

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
    """Lo que el programa manda al navegador, sin abrir nada de verdad."""
    from PySide6.QtGui import QDesktopServices

    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: urls.append(url.toString()) or True))
    return urls


def _axi(buscador):
    return buscador.con.execute("SELECT id FROM items WHERE nombre_en = 'Axi A7 Relic'").fetchone()[0]


def test_boton_wiki_apagado_sin_nada_y_busca_lo_escrito(buscador, abiertas):
    assert not buscador.boton_wiki.isEnabled()
    buscador.caja.setText("sistemas ash")
    assert buscador.boton_wiki.isEnabled()
    buscador._vaciar_ficha()  # sin ficha abierta: busca el texto
    buscador.boton_wiki.click()
    assert abiertas == [f"{WIKI}/?search=sistemas+ash"]
    buscador.caja.setText("")
    assert not buscador.boton_wiki.isEnabled()


def test_boton_wiki_con_ficha_abre_la_pagina_del_objeto(buscador, abiertas):
    buscador.abrir(_axi(buscador))
    assert buscador.boton_wiki.isEnabled()
    buscador.boton_wiki.click()
    # Las reliquias no traen wiki_url: su pagina se llama como ellas.
    assert abiertas == [f"{WIKI}/w/Axi_A7"]


def test_la_ficha_enlaza_reliquia_nodo_y_modo_y_los_abre_al_pulsar(buscador, abiertas):
    from PySide6.QtCore import QUrl

    buscador.abrir(_axi(buscador))
    html = unquote(buscador.ficha.toHtml())
    assert f"{WIKI}/w/Axi_A7" in html  # "Abrir en la wiki" de la reliquia
    assert f"{WIKI}/w/Hydron" in html  # el nodo de la fila
    assert f"{WIKI}/w/Defense" in html  # el modo, en la linea "En la wiki:"
    assert "En la wiki:" in html
    # La rotacion a la vista (Hydron es una Defensa y suelta la Axi A7 en la A).
    assert "(oleadas 3 y 6)" in html
    # Pulsar un enlace http lo abre en el navegador; glosa: e item: no.
    buscador._enlace(QUrl(f"{WIKI}/w/Hydron"))
    buscador._enlace(QUrl("glosa:boveda"))
    assert abiertas == [f"{WIKI}/w/Hydron"]


def test_la_tarjeta_de_reliquia_enlaza_a_su_pagina(buscador):
    ash = buscador.con.execute(
        "SELECT id FROM items WHERE unique_name LIKE '%AshPrimeSystemsComponent'"
    ).fetchone()[0]
    html = buscador._bloque_reliquias(ash)
    assert f"href='{WIKI}/w/Axi_A7'" in html and "wiki &rarr;" in html
