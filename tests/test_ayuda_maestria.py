"""Ayuda de maestria (datos/ayuda_maestria.py y ui/ayuda_maestria.py) con un indice sintetico.

Objetos: Rhino (plano por creditos, piezas del Chacal), Akbolto (plano por creditos, pide
dos Bolto), Bolto (plano por creditos), Soma Prime (piezas en reliquia de boveda), Braton
Prime (piezas en reliquia fuera de boveda), Aegrit (sindicato), Kuva Bramma (sin datos) y
Tigris (Mercado por platino, sin mas fuentes).
"""

from __future__ import annotations

import json
import os

import pytest

from farmadex.datos import ayuda_maestria as am
from farmadex.perfil import maestria


def _item(con, unico, en, es=None, categoria="Primary", padre=None, vaulted=None, tipo="Rifle", wiki=None):
    return con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo, padre_id, vaulted, wiki_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (unico, en, es, categoria, tipo, padre, vaulted, wiki),
    ).lastrowid


def _fuente(con, item, tipo, texto, prob, origen=None):
    con.execute("INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, probabilidad) VALUES (?, ?, ?, ?, ?)",
                (item, tipo, origen, texto, prob))


@pytest.fixture()
def indice(con):
    rhino = _item(con, "/W/Rhino", "Rhino", "Rhino", "Warframes", tipo="Warframe")
    _item(con, "/W/RhinoBlueprint", "Blueprint", "Plano", "Warframes", padre=rhino, tipo="Componente")
    chasis = _item(con, "/W/RhinoChassis", "Chassis", "Chasis", "Warframes", padre=rhino, tipo="Componente")
    fossa = con.execute("INSERT INTO nodos (unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_en, "
                        "clave_drops) VALUES ('SolNode1', 'Fossa', 'Fossa', 'Venus', 'Venus', 'Assassination', "
                        "'Venus/Fossa')").lastrowid
    _fuente(con, chasis, "mision", "Venus/Fossa", 38.72, fossa)
    bolto = _item(con, "/S/Bolto", "Bolto", "Bolto", "Secondary", tipo="Pistol")
    akbolto = _item(con, "/S/Akbolto", "Akbolto", "Akbolto", "Secondary", tipo="Dual Pistols")
    plano_ak = _item(con, "/S/AkboltoBlueprint", "Blueprint", "Plano", "Secondary", padre=akbolto, tipo="Componente")
    con.execute("INSERT INTO recetas (padre_id, item_id, cantidad) VALUES (?, ?, 2)", (akbolto, bolto))
    con.execute("INSERT INTO recetas (padre_id, item_id, cantidad) VALUES (?, ?, 1)", (akbolto, plano_ak))
    soma = _item(con, "/P/SomaPrime", "Soma Prime", "Soma Prime")
    cano = _item(con, "/P/SomaPrimeBarrel", "Barrel", "Cañón", padre=soma, tipo="Componente")
    axi = _item(con, "RELIQUIA/Axi S1", "Axi S1 Relic", "Reliquia Axi S1", "Relics", vaulted=1, tipo="Relic")
    _fuente(con, cano, "reliquia", "x", 11.0, axi)
    braton = _item(con, "/P/BratonPrime", "Braton Prime", "Braton Prime")
    receptor = _item(con, "/P/BratonPrimeReceiver", "Receiver", "Receptor", padre=braton, tipo="Componente")
    lith = _item(con, "RELIQUIA/Lith B1", "Lith B1 Relic", "Reliquia Lith B1", "Relics", vaulted=0, tipo="Relic")
    _fuente(con, receptor, "reliquia", "x", 11.0, lith)
    aegrit = _item(con, "/S/Aegrit", "Aegrit", "Aegrit", "Secondary", tipo="Pistol")
    _fuente(con, aegrit, "sindicato", "Kahl's Garrison", 100.0)
    _item(con, "/P/KuvaBramma", "Kuva Bramma", "Bramma Kuva", wiki="https://wiki.warframe.com/w/Kuva_Bramma")
    _item(con, "/P/Tigris", "Tigris", "Tigris", tipo="Shotgun")
    _item(con, "/M/Forma", "Forma", "Forma", "Resources", tipo="Resource")  # no da maestria
    con.commit()
    return con


PRECIOS = {"/W/Rhino": {"creditos": 35000}, "/S/Akbolto": {"creditos": 15000}, "/S/Bolto": {"creditos": 15000},
           "/P/Tigris": {"platino": 175}}


def _por_nombre(resultado):
    return {f["nombre_en"]: f for f in resultado.filas}


def test_clasifica_por_la_pieza_mas_dificil_y_ordena_por_facilidad(indice):
    r = am.calcular(indice, am.DatosUsuario(origen="json"), PRECIOS)
    f = _por_nombre(r)
    assert r.total == 8 and r.pendientes == 8 and r.sin_datos == 0
    assert f["Bolto"]["facilidad"] == am.CREDITOS
    # Rhino: el plano se compra, pero el chasis es del Chacal: manda la pieza dificil.
    assert f["Rhino"]["facilidad"] == am.DROP and f["Rhino"]["creditos"] == 35000
    assert f["Rhino"]["donde"]["donde"].startswith("Fossa") and f["Rhino"]["pieza"] == "Chasis"
    assert f["Akbolto"]["facilidad"] == am.FUNDICION and f["Akbolto"]["ingredientes"] == ["2 × Bolto"]
    assert f["Aegrit"]["facilidad"] == am.SINDICATO
    assert f["Braton Prime"]["facilidad"] == am.RELIQUIA and f["Braton Prime"]["reliquias"] == ["Lith B1 Relic"]
    assert f["Soma Prime"]["facilidad"] == am.BOVEDA
    assert f["Tigris"]["facilidad"] == am.PLATINO and f["Tigris"]["platino"] == 175
    assert f["Kuva Bramma"]["facilidad"] == am.DESCONOCIDO
    orden = [x["facilidad"] for x in r.filas]
    assert orden == sorted(orden, key=am.FACILIDAD.index)


def test_sin_precios_no_se_inventa_que_se_compra(indice):
    f = _por_nombre(am.calcular(indice, am.DatosUsuario(origen="json"), {}))
    assert f["Bolto"]["facilidad"] == am.DESCONOCIDO
    assert f["Tigris"]["facilidad"] == am.DESCONOCIDO


def test_estado_segun_lo_que_se_sabe(indice):
    umbral = maestria.XP_ARMA_30
    # Perfil JSON: lista completa, lo que no esta es "te falta".
    datos = am.DatosUsuario(origen="json", xp={"/S/Bolto": umbral, "/P/Tigris": umbral // 4})
    r = am.calcular(indice, datos, PRECIOS)
    f = _por_nombre(r)
    assert "Bolto" not in f and r.dominados == 1
    assert f["Tigris"]["estado"] == am.A_MEDIAS and f["Tigris"]["facilidad"] == am.A_MEDIAS
    assert r.filas[0]["nombre_en"] == "Tigris"  # lo que tienes a medias, lo primero
    assert f["Rhino"]["estado"] == am.PENDIENTE
    # Solo OCR: lo no visto es "sin datos", lo visto sin rango es "te falta".
    datos = am.DatosUsuario(origen="ocr", xp={"/S/Bolto": umbral}, ocr={"/W/Rhino": maestria.NO_DOMINADO})
    r = am.calcular(indice, datos, PRECIOS)
    f = _por_nombre(r)
    assert f["Rhino"]["estado"] == am.PENDIENTE and f["Akbolto"]["estado"] == am.SIN_DATOS
    assert r.sin_datos == 6 and r.pendientes == 1
    # Sin perfil: todo sin datos. Las marcas a mano mandan.
    datos = am.DatosUsuario(origen=None, manual={"/W/Rhino": True, "/S/Aegrit": False})
    r = am.calcular(indice, datos, PRECIOS)
    f = _por_nombre(r)
    assert "Rhino" not in f and [m["nombre_en"] for m in r.marcados] == ["Rhino"]
    assert f["Aegrit"]["estado"] == am.PENDIENTE and f["Bolto"]["estado"] == am.SIN_DATOS


def test_filtros_por_grupo_y_nombre(indice):
    r = am.calcular(indice, am.DatosUsuario(origen="json"), PRECIOS)
    assert {f["nombre_en"] for f in am.filtrar(r.filas, "warframes")} == {"Rhino"}
    assert {f["nombre_en"] for f in am.filtrar(r.filas, "secundarias")} == {"Bolto", "Akbolto", "Aegrit"}
    assert [f["nombre_en"] for f in am.filtrar(r.filas, texto="bramma")] == ["Kuva Bramma"]
    assert [f["nombre_en"] for f in am.filtrar(r.filas, texto="CAÑON")] == []


def test_marcas_a_mano_y_lista_pegada(indice, tmp_path):
    from farmadex.estado import usuario_db

    usuario = usuario_db.conectar(tmp_path / "u.sqlite")
    casados, fallos = am.casar_lista(indice, "rhino\nBRAMMA KUVA; akbolto, Excalibur\n\n")
    assert sorted(c["unique_name"] for c in casados) == ["/P/KuvaBramma", "/S/Akbolto", "/W/Rhino"]
    assert fallos == ["Excalibur"]
    am.marcar(usuario, [c["unique_name"] for c in casados])
    assert am.marcas(usuario) == {"/P/KuvaBramma": True, "/S/Akbolto": True, "/W/Rhino": True}
    am.quitar_marca(usuario, ["/W/Rhino"])
    assert "/W/Rhino" not in am.marcas(usuario)
    datos = am.leer_usuario(usuario)
    assert datos.origen is None and datos.manual["/S/Akbolto"] is True


def test_precios_de_los_json_de_wfcd(tmp_path):
    (tmp_path / "Primary.json").write_text(json.dumps([
        {"uniqueName": "/P/Braton", "name": "Braton"},
        {"uniqueName": "/P/Boltor", "bpCost": 15000, "marketCost": 150},
        {"uniqueName": "/P/Raro", "bpCost": True},
    ]), encoding="utf-8")
    (tmp_path / "Melee.json").write_text("{roto", encoding="utf-8")
    precios = am.precios_mercado(tmp_path)
    assert precios == {"/P/Boltor": {"creditos": 15000, "platino": 150}}
    assert am.creditos_de_planos(tmp_path) == {"/P/Boltor": 15000}


# -- interfaz ----------------------------------------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(app, indice, tmp_path, monkeypatch):
    from farmadex import idiomas
    from farmadex.estado import usuario_db
    from farmadex.ui.ayuda_maestria import PanelAyudaMaestria

    idiomas.cargar("es")
    monkeypatch.setattr(am, "precios_mercado", lambda dir_datos=None: PRECIOS)
    p = PanelAyudaMaestria()
    p.conectar(indice, usuario_db.conectar(tmp_path / "u.sqlite"))
    p.recalcular(en_segundo_plano=False)
    return p


def test_panel_sin_perfil_lo_dice_y_ofrece_marcar(panel):
    texto = panel.texto_plano()
    assert "No sé qué tienes dominado" in texto
    assert "Dominas 0 de 8" in texto and "De 8 no hay datos" in texto
    assert "Con créditos".upper() in texto and "Plano por 15.000 créditos" in texto
    assert "Ya lo tengo" in texto and "Mírala en la wiki" in texto


def test_panel_filtra_marca_y_deshace(panel):
    panel.grupo.setCurrentIndex(panel.grupo.findData("warframes"))
    assert [f["nombre_en"] for f in panel.filas_visibles()] == ["Rhino"]
    avisos = []
    panel.maestria_cambiada.connect(lambda: avisos.append(1))
    panel._enlace("marcar:/W/Rhino")
    panel.recalcular(en_segundo_plano=False)
    assert panel.filas_visibles() == [] and avisos
    assert "Marcado como dominado: 1" in panel.texto_plano()
    panel.vista.setCurrentIndex(panel.vista.findData("marcados"))
    assert [f["nombre_en"] for f in panel.filas_visibles()] == ["Rhino"]
    panel._enlace("deshacer")
    panel.recalcular(en_segundo_plano=False)
    assert panel.filas_visibles() == []
    panel.vista.setCurrentIndex(0)
    panel.grupo.setCurrentIndex(0)
    panel.caja.setText("bolt")
    assert {f["nombre_en"] for f in panel.filas_visibles()} == {"Bolto", "Akbolto"}


def test_panel_importa_una_lista(panel):
    n, fallos = panel.importar_texto("Bolto\nNo existe")
    panel.recalcular(en_segundo_plano=False)
    assert n == 1 and fallos == ["No existe"]
    assert "No reconozco 1: No existe" in panel.texto_plano()
    assert panel.resultado.dominados == 1


def test_la_pestana_perfil_lleva_el_panel_y_lo_conserva(app, indice, tmp_path, monkeypatch):
    from farmadex import idiomas
    from farmadex.estado import usuario_db
    from farmadex.ui.pestana_perfil import PestanaPerfil

    idiomas.cargar("es")
    monkeypatch.setattr(am, "precios_mercado", lambda dir_datos=None: PRECIOS)
    pestana = PestanaPerfil(usuario_db.conectar(tmp_path / "u.sqlite"))
    pestana.conectar_indice(indice)
    panel = pestana.ayuda_maestria
    assert panel.parent() is pestana.contenido
    pestana.pintar()
    pestana.pintar()
    assert pestana.ayuda_maestria is panel and panel.parent() is pestana.contenido
