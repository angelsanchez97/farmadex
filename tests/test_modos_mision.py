"""Que hacer en cada tipo de mision y como van sus rotaciones, al pasar el raton."""

import os
from urllib.parse import unquote

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.datos import modos_mision as mm  # noqa: E402
from farmadex.ui import glosario  # noqa: E402

# Los modos que aparecen en los datos (mision_en de los nodos y 'modo' de las fuentes).
MODOS_DE_LOS_DATOS = [
    "Skirmish", "Defense", "Survival", "Rescue", "Capture", "Spy", "Conclave", "Assassination",
    "Interception", "Disruption", "Arena", "Exterminate", "Extermination", "Excavation", "Normal",
    "Hard", "Mobile Defense", "The Perita Rebellion", "Sabotage", "Defection", "Sanctuary Onslaught",
    "Rush", "Volatile", "Void Flood", "Void Cascade", "Void Armageddon", "The Circuit",
    "Shrine Defense", "Pursuit", "Orphix", "Netracells", "Legacyte Harvest", "Infested Salvage",
    "Follie's Hunt", "Ascension", "Alchemy", "Hijack", "Caches", "Mirror Defense",
    "Conjunction Survival", "Assault", "Arbitration", "Arbitrations", "Void Storm",
]


@pytest.fixture(autouse=True)
def castellano():
    idiomas.cargar("es")
    yield
    idiomas.cargar("es")


@pytest.mark.parametrize("modo", MODOS_DE_LOS_DATOS)
def test_cada_modo_de_los_datos_tiene_que_hacer_y_recompensas(modo):
    texto = mm.explicacion(modo)
    titulo, que, recompensas = texto.splitlines()
    assert titulo and que.startswith("Que hacer: ") and recompensas.startswith("Recompensas: ")


def test_sin_porcentajes_en_los_textos():
    # Preferencia del usuario: en lo que lee la gente, reglas del juego pero no probabilidades.
    assert not [x for x in mm.textos() if "%" in x]


def test_los_alias_dan_el_mismo_texto():
    assert mm.explicacion("Extermination") == mm.explicacion("Exterminate")
    assert mm.explicacion("Arbitrations") == mm.explicacion("Arbitration")
    assert mm.explicacion(" Survival ") == mm.explicacion("Survival")
    assert mm.modo_de_origen("Void Storm (Earth)") == "Void Storm"
    assert mm.modo_de_origen("Arbitrations") == "Arbitration"
    assert mm.modo_de_origen("Derelict Vault") == ""


def test_la_rotacion_de_la_fila_anade_su_linea():
    supervivencia = mm.explicacion("Survival", "C").splitlines()
    assert supervivencia[0] == "Supervivencia"
    assert supervivencia[-1] == "Aqui la rotacion C es la recompensa de los minutos 20, 40, 60..."
    assert mm.linea_rotacion("Defense", "A") == "Aqui la rotacion A es la recompensa de las oleadas 3, 6, 15, 18..."
    assert mm.linea_rotacion("Excavation", "b") == "Aqui la rotacion B llega con 3, 7, 11... excavadoras completadas"
    assert "tercera boveda" in mm.linea_rotacion("Spy", "C")
    assert "quinta rotacion" in mm.linea_rotacion("Arbitrations", "C")
    # Sin rotacion, o con un modo sin regla por letra (Circuito), no hay linea extra.
    assert len(mm.explicacion("Survival").splitlines()) == 3
    assert mm.linea_rotacion("The Circuit", "B") == ""


def test_modo_desconocido_sin_texto_y_rotacion_generica():
    assert mm.explicacion("Relay") == "" and mm.explicacion(None) == "" and mm.explicacion("Nada") == ""
    assert mm.explicacion_rotacion("Nada", "C") == ""
    # La rotacion de un modo desconocido se queda con la explicacion generica del glosario.
    assert "href='glosa:rotacion'" in glosario.enlace_rotacion("Nada", "C", "Rotacion C", "#abc")
    # Y el tipo de mision desconocido se pinta tal cual, sin enlace.
    assert glosario.enlace_mision("Nada", "Algo <raro>", "#abc") == "Algo &lt;raro&gt;"


def test_el_tooltip_del_modo_se_titula_con_el_modo(app):
    enlace = glosario.enlace_mision("Survival", "Supervivencia", "#abc", "C")
    assert "text-decoration:none" in enlace and "color:#abc" in enlace
    clave = enlace.split("href='glosa:", 1)[1].split("'", 1)[0]
    texto = glosario.texto(clave)
    assert "<b>Supervivencia</b>" in texto and "Tipo de mision" not in texto
    assert "minutos 20, 40, 60" in texto
    # La rotacion lleva las reglas del modo y cuando llega esa letra.
    rot = glosario.enlace_rotacion("Survival", "C", "Rotacion C", "#abc")
    texto_rot = glosario.texto(rot.split("href='glosa:", 1)[1].split("'", 1)[0])
    assert "<b>Rotacion</b>" in texto_rot and "En Supervivencia:" in texto_rot


def test_en_ingles_sale_traducido():
    idiomas.cargar("en")
    texto = mm.explicacion("Survival", "C")
    assert texto.splitlines()[0] == "Survival"
    assert "What to do: Hold out" in texto
    assert "Here rotation C is the reward at minutes 20, 40, 60..." in texto


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


def test_la_fila_de_una_mision_sin_fin_lleva_el_modo_y_su_rotacion(buscador):
    # Hydron (Sedna) es una Defensa y suelta la Axi A7 en la rotacion A.
    buscador.abrir(buscador.con.execute("SELECT id FROM items WHERE nombre_en = 'Axi A7 Relic'").fetchone()[0])
    html = unquote(buscador.ficha.toHtml())
    assert "glosa:mision?Defensa" in html
    assert "Aqui la rotacion A es la recompensa de las oleadas 3, 6, 15, 18..." in html
    assert "glosa:rotacion?En Defensa:" in html


def test_la_fisura_explica_su_modo(app):
    from farmadex.online import worldstate as ws
    from farmadex.ui import pestana_mundo

    pestana = pestana_mundo.PestanaMundo()
    fisura = ws.Fisura("Neo", "Selkie, Sedna", "Supervivencia", "Grineer", None, modo="Survival")
    html = unquote(pestana._html_fisura(fisura))
    assert "glosa:mision?Supervivencia" in html and ">Supervivencia</a>" in html
    # Sin modo (datos viejos), el texto de siempre.
    viejo = ws.Fisura("Neo", "Selkie, Sedna", "Supervivencia", "Grineer", None)
    assert "glosa:mision" not in pestana._html_fisura(viejo)
