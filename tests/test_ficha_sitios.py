"""La ficha de Buscar ensena TODOS los sitios donde sale un objeto, con su barra de rapidez.

Regresion del rediseno C (0.6.0): un recurso que ademas se fabrica (Celula orokin,
Sensores neuronales: tienen plano) perdia la tabla entera de misiones, contratos y
enemigos y solo quedaba el "Como conseguirlo" con la mejor. Y en la columna estrecha la
tabla de seis columnas partia los nombres letra a letra.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

# Misiones de la Celula orokin de prueba (planeta, nodo, modo, rotacion, probabilidad).
SITIOS = [
    ("Deimos", "Formido", "Sabotage", "C", 19.4),
    ("Ceres", "Ker", "Sabotage", "C", 15.1),
    ("Jupiter", "Carpo", "Survival", "C", 15.1),
    ("Saturn", "Tethys", "Assassination", None, 30.0),
    ("Kuva Fortress", "Dakata", "Exterminate", None, 3.7),
]


@pytest.fixture()
def aplicacion():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def buscador(indice_poblado, monkeypatch, aplicacion, tmp_path):
    from farmadex import config, idiomas
    from farmadex.datos import indice as modulo_indice
    from farmadex.ui.pestana_buscador import PestanaBuscador

    con, importador, _ = indice_poblado
    celula = [{
        "uniqueName": "/Lotus/Types/Items/MiscItems/OrokinCell",
        "name": "Orokin Cell",
        "description": "Ancient energy cell from the Orokin era.",
        "category": "Resources",
        "type": "Resource",
        "tradable": False,
        "drops": [],
        "components": [{
            "uniqueName": "/Lotus/Types/Recipes/OrokinCellBlueprint",
            "name": "Blueprint",
            "itemCount": 1,
            "drops": [],
        }],
    }]
    ruta = tmp_path / "Resources.json"
    ruta.write_text(json.dumps(celula), encoding="utf-8")
    importador.importar_categoria(ruta)
    recompensas = {}
    for planeta, nodo, modo, rot, prob in SITIOS:
        premio = {"itemName": "Orokin Cell", "rarity": "Uncommon", "chance": prob}
        recompensas.setdefault(planeta, {})[nodo] = {
            "gameMode": modo, "rewards": {rot: [premio]} if rot else [premio]}
    ruta_mr = tmp_path / "missionRewards.json"
    ruta_mr.write_text(json.dumps(recompensas), encoding="utf-8")
    from farmadex.datos.drops import ImportadorDrops

    ImportadorDrops(con, importador.alias).mission_rewards(ruta_mr)
    con.commit()
    modulo_indice.poblar_busqueda(con)

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    monkeypatch.setattr(modulo_indice, "conectar", lambda *a, **k: con)
    pestana = PestanaBuscador()
    pestana.habilitar(True)
    pestana.resize(1180, 900)
    pestana.show()
    yield pestana
    pestana.close()


def _celula(buscador) -> int:
    return buscador.con.execute(
        "SELECT id FROM items WHERE unique_name = '/Lotus/Types/Items/MiscItems/OrokinCell'"
    ).fetchone()[0]


def _panel(buscador, titulo: str):
    """El BloqueHtml del panel cuyo rotulo es `titulo`."""
    from farmadex.ui.estilo_c import PanelC
    from farmadex.ui.ficha_c import BloqueHtml

    for panel in buscador.ficha.findChildren(PanelC):
        if panel.rotulo is not None and titulo.upper() in panel.rotulo.text().upper():
            bloques = panel.findChildren(BloqueHtml)
            if bloques:
                return bloques[0]
    return None


def _filas_con_barra(bloque) -> list[str]:
    """Nombre de cada fila de la tabla de sitios que lleva marca de relleno."""
    import re

    return re.findall(r"name=['\"]relleno-\d+['\"]", bloque.toHtml())


def test_recurso_con_plano_ensena_todos_sus_sitios_con_barra(buscador, aplicacion):
    from farmadex.datos import relaciones

    buscador.abrir(_celula(buscador))
    aplicacion.processEvents()
    donde = _panel(buscador, "Dónde se consigue")
    assert donde is not None, "sin panel Dónde se consigue"
    fuentes = relaciones.fuentes_de(buscador.con, _celula(buscador))
    estimables = [f for f in fuentes if f.get("minutos_medios") is not None]
    assert len(fuentes) == len(SITIOS)
    assert len(estimables) >= 4
    # Una fila por sitio (no solo el mejor), y cada una con tiempo lleva su barra.
    texto = donde.toPlainText()
    for sitio in ("Formido", "Ker", "Carpo", "Tethys", "Dakata"):
        assert sitio in texto, sitio
    assert len(_filas_con_barra(donde)) == len(estimables)
    # El plano sigue a la vista, en su propio panel.
    construye = _panel(buscador, "Se construye con")
    assert construye is not None and "Plano" in construye.toPlainText()


def test_las_barras_se_pintan_en_la_ficha(buscador, aplicacion):
    """La marca no basta: la celda del nombre tiene que salir rellena de verdad."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor

    buscador.abrir(_celula(buscador))
    aplicacion.processEvents()
    aplicacion.processEvents()
    donde = _panel(buscador, "Dónde se consigue")
    donde._relleno.aplicar()
    documento = donde.document()
    rellenas = 0
    bloque = documento.begin()
    vistas = set()
    while bloque.isValid():
        tabla = QTextCursor(bloque).currentTable()
        if tabla is not None and tabla.firstPosition() not in vistas:
            vistas.add(tabla.firstPosition())
            for fila in range(tabla.rows()):
                if tabla.columns() > 1 and tabla.cellAt(fila, 1).format().background().style() != Qt.NoBrush:
                    rellenas += 1
        bloque = bloque.next()
    assert rellenas == len(_filas_con_barra(donde))


def test_la_tabla_de_sitios_cabe_en_una_columna_estrecha(buscador):
    """Tres columnas (franja, sitio + detalle, % + tiempo): no se parten las palabras."""
    from farmadex.datos import relaciones

    grupo = [f for f in relaciones.fuentes_de(buscador.con, _celula(buscador)) if f["tipo"] == "mision"]
    tabla = buscador._tabla_fuentes(grupo)
    assert tabla.count("<tr>") == len(grupo)
    primera = tabla.split("<tr>")[1]
    assert primera.count("<td") == 3
    # El tiempo lleva su desglose al pasar el raton.
    assert "glosa:tiempo_medio" in tabla


def test_set_sin_fuentes_propias_sigue_pieza_a_pieza(buscador):
    """Ash Prime no cae el solo: 'Dónde se consigue' es la lista de piezas, sin panel aparte."""
    ash = buscador.con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    buscador.abrir(ash)
    donde = _panel(buscador, "Dónde se consigue")
    assert donde is not None and "Sistemas" in donde.toPlainText()
    assert _panel(buscador, "Se construye con") is None


def test_pieza_prime_lista_todas_sus_reliquias_con_sus_misiones(buscador):
    """Sistemas de Ash Prime: cada reliquia que la da y, debajo, las misiones donde cae."""
    from farmadex.datos import relaciones

    sistemas = buscador.con.execute(
        "SELECT id FROM items WHERE unique_name LIKE '%AshPrimeSystemsComponent'"
    ).fetchone()[0]
    buscador.abrir(sistemas)
    reliquias = _panel(buscador, "Reliquias")
    assert reliquias is not None
    texto = reliquias.toPlainText()
    todas = relaciones.reliquias_de(buscador.con, sistemas, incluir_vaulted=True)
    assert todas and any(relaciones.misiones_de(buscador.con, r["reliquia_id"]) for r in todas)
    for r in todas:
        assert r["nombre_es"] or r["nombre_en"]
        assert (r["nombre_en"] or "").removesuffix(" Relic") in texto or (r["nombre_es"] or "") in texto
        for m in relaciones.misiones_de(buscador.con, r["reliquia_id"])[:3]:
            assert m["donde"].split(",")[0] in texto


def test_una_columna_como_y_donde_arriba_y_pedestal_pequeno_al_lado(buscador, aplicacion):
    """Ventana del usuario (1100x700): la ficha va a una columna y las misiones se ven sin bajar."""
    from farmadex.ui.estilo_c import PanelC, Pedestal, px

    # La pestana sola, sin el menu ni los margenes de la ventana: 900 deja la ficha como la
    # ventana de 1100 del usuario.
    buscador.resize(1060, 700)
    buscador.caja.setText("orokin")
    buscador._temporizador.stop()
    buscador._buscar()  # con resultados, la lista ocupa la izquierda como en la app
    buscador.abrir(_celula(buscador))
    aplicacion.processEvents()
    aplicacion.processEvents()
    assert buscador.ficha.estrecha()
    buscador._montar()
    pedestal = buscador.ficha.findChildren(Pedestal)[0]
    assert pedestal.maximumWidth() <= px(96, False)
    # El pedestal comparte fila con el nombre (no ocupa una fila entera encima).
    primera = buscador.ficha.capa.itemAt(0).layout()
    assert primera is not None and primera.itemAt(0).widget() is pedestal
    # Orden de los paneles: Como conseguirlo, Donde se consigue y el plano detras.
    rotulos = []
    for i in range(buscador.ficha.capa.count()):
        w = buscador.ficha.capa.itemAt(i).widget()
        if isinstance(w, PanelC) and w.rotulo is not None:
            rotulos.append(w.rotulo.text().upper())
    assert rotulos[0].startswith("CÓMO CONSEGUIRLO")
    assert "DÓNDE SE CONSIGUE" in rotulos[1]
    assert rotulos.index(next(r for r in rotulos if "SE CONSTRUYE" in r)) > 1
    # Dentro de "Donde se consigue", las misiones van antes que la tarjeta de planeta.
    texto = _panel(buscador, "Dónde se consigue").toPlainText()
    if "RECURSO DE PLANETA" in texto.upper():
        assert texto.upper().index("MISIONES") < texto.upper().index("RECURSO DE PLANETA")


def test_una_columna_sin_fuentes_van_antes_los_datos_propios(buscador, aplicacion, tmp_path):
    """Como la Hek: solo "Plano · Sin fuentes registradas". Ese panel no sube arriba."""
    import json as _json

    from farmadex.datos import indice as modulo_indice
    from farmadex.ui.estilo_c import PanelC

    con = buscador.con
    arma = [{
        "uniqueName": "/Lotus/Weapons/Prueba/EscopetaSinFuentes",
        "name": "Escopeta Sin Fuentes",
        "description": "Una escopeta de prueba que solo se fabrica.",
        "category": "Resources",
        "type": "Resource",
        "tradable": False,
        "drops": [],
        "components": [{"uniqueName": "/Lotus/Types/Recipes/EscopetaSinFuentesBlueprint",
                        "name": "Blueprint", "itemCount": 1, "drops": []}],
    }]
    ruta = tmp_path / "SinFuentes.json"
    ruta.write_text(_json.dumps(arma), encoding="utf-8")
    from farmadex.datos.items import ImportadorItems

    ImportadorItems(con, {}).importar_categoria(ruta)
    con.execute("UPDATE items SET descripcion_es = ? WHERE unique_name = ?",
                ("Una escopeta de prueba que solo se fabrica.", "/Lotus/Weapons/Prueba/EscopetaSinFuentes"))
    con.commit()
    modulo_indice.poblar_busqueda(con)
    iid = con.execute("SELECT id FROM items WHERE unique_name = '/Lotus/Weapons/Prueba/EscopetaSinFuentes'"
                      ).fetchone()[0]

    buscador.resize(1060, 700)
    buscador.caja.setText("orokin")
    buscador._temporizador.stop()
    buscador._buscar()
    buscador.abrir(iid)
    aplicacion.processEvents()
    aplicacion.processEvents()
    assert buscador.ficha.estrecha()
    buscador._montar()
    orden = []
    for i in range(buscador.ficha.capa.count()):
        w = buscador.ficha.capa.itemAt(i).widget()
        if isinstance(w, PanelC) and w.rotulo is not None:
            orden.append(w.rotulo.text().upper())
        elif w is not None and "escopeta de prueba" in (w.property("fuenteC") or ""):
            orden.append("DESCRIPCION")
    assert "DESCRIPCION" in orden and any("DÓNDE SE CONSIGUE" in r for r in orden)
    assert orden.index("DESCRIPCION") < next(i for i, r in enumerate(orden) if "DÓNDE SE CONSIGUE" in r)
    # La Celula orokin, que si tiene fuentes, sigue con "Donde se consigue" arriba.
    buscador.abrir(_celula(buscador))
    buscador._montar()
    primeros = [buscador.ficha.capa.itemAt(i).widget() for i in range(1, 3)]
    assert any(isinstance(w, PanelC) and w.rotulo is not None and "DÓNDE" in w.rotulo.text().upper()
               for w in primeros)
