"""Herramientas > Mercado: la cuenta de rentabilidad (sin Qt) y la pagina (offscreen).

La foto real no va en el repositorio: la prueba que la usa se salta si no esta. Para
pasarla, FARMADEX_FOTO_PRECIOS=<ruta a precios.json.gz> (y, si se quiere, con nombres,
FARMADEX_INDICE_REAL=<ruta a indice.sqlite>).
"""

from __future__ import annotations

import gzip
import json
import os
import random
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from farmadex.datos import rentabilidad as rent
from farmadex.online import precios_diarios as pd

CAMPOS = ["venta_min", "venta_mediana", "compra_max", "vendedores", "compradores", "cantidad_venta",
          "min_30d", "max_30d", "media_30d", "volumen_30d", "mediana_30d", "dias_30d", "volumen_48h"]
BASE = "https://github.com/x/y/releases/download/precios/"


def _p(venta_min=None, compra_max=None, mediana=None, volumen=None, dias=30, v48=None, minimo=None, maximo=None):
    """Una linea de mercado con los campos en el orden de la foto."""
    return [venta_min, venta_min, compra_max, 3, 2, 5, minimo, maximo, mediana, volumen, mediana, dias, v48]


def _objetos() -> dict:
    return {
        # Arcano que sale mejor subido: 300 >= 21 x 10.
        "arcano_caro": {"n": "Arcane Expensive", "r": 5, "t": ["arcane_enhancement", "legendary"], "p": {
            "0": _p(11, 9, 10, 3000, 30, 200), "5": _p(310, 280, 300, 600, 30, 40)}},
        # Arcano que sale mejor suelto: 130 < 21 x 8.
        "arcano_suelto": {"n": "Arcane Loose", "r": 5, "t": ["arcane_enhancement"], "p": {
            "0": _p(8, 6, 8, 5000, 30, 400), "5": _p(125, 90, 130, 3000, 29, 240)}},
        # Mod que se vende mas caro al maximo (legendario: 40.920 de endo).
        "mod_prime": {"n": "Primed Thing", "r": 10, "t": ["mod", "legendary"], "p": {
            "0": _p(25, 20, 25, 2000, 30, 99), "10": _p(80, 65, 84, 1500, 30, 100)}},
        # Mod que vale lo mismo subido: no se manda gastar endo.
        "mod_igual": {"n": "Same Price Mod", "r": 3, "t": ["mod", "rare"], "p": {
            "0": _p(120, 30, 120, 1200, 30, 80), "3": _p(120, 30, 120, 1500, 30, 110)}},
        # Mod con datos solo en un rango, y con variante rara que no cuenta.
        "mod_unico": {"n": "Only Base Mod", "r": 10, "t": ["mod", "uncommon"], "s": ["regular", "atragraph"], "p": {
            "0": _p(None, None, 6, 300, 30, 10), "0|regular": _p(7, 5), "10|atragraph": _p(250, None)}},
        "set_bueno": {"n": "Good Prime Set", "r": None, "t": ["set", "prime", "warframe"], "d": 175, "p": {
            "": _p(78, 75, 78, 950, 30, 68, 71, 80)}},
        "pieza": {"n": "Good Prime Chassis Blueprint", "r": None, "t": ["component", "prime", "blueprint"], "d": 45,
                  "p": {"": _p(12, 9, 12, 600, 30, 30)}},
        "lith_x1_relic": {"n": "Lith X1 Relic", "r": None, "t": ["relic", "lith"], "v": True,
                          "s": ["intact", "exceptional", "flawless", "radiant"], "p": {
                              "|intact": _p(9, None, 10, 90, 20, 6), "|radiant": _p(30, None, 28, 4, 2, 0)}},
        "axi_z9_relic": {"n": "Axi Z9 Relic", "r": None, "t": ["relic", "axi"], "v": False,
                         "s": ["intact", "radiant"], "p": {"|intact": _p(3, 2, 3, 400, 30, 20)}},
        # Dos ventas a 5000: nunca un nivel alto.
        "rareza": {"n": "Ultra Rare Thing", "r": None, "t": ["misc"], "p": {"": _p(4900, 1500, 5000, 2, 2, 0)}},
        # Muchas ventas pero en tres dias sueltos (precio hinchado): tampoco.
        "hinchado": {"n": "Pumped Thing", "r": None, "t": ["misc"], "p": {"": _p(1500, 80, 99999, 250, 3, 0)}},
        # Sin ventas cerradas: no entra, aunque tenga ordenes.
        "sin_ventas": {"n": "No Sales Set", "r": None, "t": ["set", "prime"], "p": {"": _p(60, 55, None, 0, 0, 0)}},
        "solo_ordenes": {"n": "Orders Only", "r": None, "t": ["misc"], "p": {"": _p(60, 55)}},
        # Vuela, pero vale 1 de platino.
        "barato": {"n": "Cheap Fast Thing", "r": None, "t": ["misc"], "p": {"": _p(1, None, 1, 9000, 30, 600)}},
    }


def _doc(objetos: dict | None = None, fecha: str = "2026-09-30T00:40:00Z") -> dict:
    return {"formato": 1, "fecha": fecha, "plataforma": "pc", "fuente": "warframe.market", "dias": 30,
            "campos": CAMPOS, "resumen": {}, "objetos": objetos if objetos is not None else _objetos()}


def _fotos(tmp_path: Path, objetos: dict | None = None, **kw) -> pd.PreciosDiarios:
    p = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    p.instalar(_doc(objetos, **kw))
    return p


def _por_slug(filas) -> dict:
    return {f.slug: f for f in filas}


# -- la cuenta ---------------------------------------------------------------------------


def test_tipos_copias_y_endo():
    assert rent.tipo_de(["mod", "rare"]) == "mods"
    assert rent.tipo_de(["arcane_enhancement"]) == "arcanos"
    assert rent.tipo_de(["set", "prime", "warframe"]) == "sets_prime"
    assert rent.tipo_de(["component", "prime", "blueprint"]) == "piezas_prime"
    assert rent.tipo_de(["relic", "lith"]) == "reliquias"
    assert rent.tipo_de(["fish"]) == "otros" and rent.tipo_de(None) == "otros"
    assert rent.copias_para_rango(5) == 21 and rent.copias_para_rango(3) == 10
    assert rent.endo_para_rango(10, ["mod", "legendary"]) == 40920
    assert rent.endo_para_rango(10, ["mod", "uncommon"]) == 20460
    assert rent.endo_para_rango(5, ["mod"]) is None  # sin rareza no se inventa


def test_sin_ventas_no_entra_y_el_orden_es_por_puntos(tmp_path):
    filas = rent.calcular(_fotos(tmp_path))
    slugs = [f.slug for f in filas]
    assert "sin_ventas" not in slugs and "solo_ordenes" not in slugs
    con_nivel = [f for f in filas if not f.pocos_datos]
    assert [f.puntos for f in con_nivel] == sorted((f.puntos for f in con_nivel), reverse=True)
    # Los de pocos datos, siempre al final.
    assert all(f.pocos_datos for f in filas[len(con_nivel):])
    assert filas[0].slug == "arcano_caro" and filas[0].nivel == "S"


def test_pocas_ventas_nunca_suben_de_nivel(tmp_path):
    f = _por_slug(rent.calcular(_fotos(tmp_path)))
    assert f["rareza"].nivel == rent.SIN_NIVEL and f["rareza"].pocos_datos
    # 250 ventas pero en 3 dias: tampoco se le pone nivel, por mucho que "valga" 99.999.
    assert f["hinchado"].nivel == rent.SIN_NIVEL
    assert f["lith_x1_relic"].venta.subtipo == "intact"  # la variante con ventas de verdad
    assert f["lith_x1_relic"].nivel in rent.NIVELES


def test_niveles_segun_puntos(tmp_path):
    f = _por_slug(rent.calcular(_fotos(tmp_path)))
    assert f["set_bueno"].venta.rapidez == 1.0 and f["set_bueno"].puntos == 78 and f["set_bueno"].nivel == "S"
    assert f["pieza"].puntos == 12 and f["pieza"].nivel == "B"
    assert f["barato"].puntos == 1 and f["barato"].nivel == "D"  # se vende solo, pero no vale nada
    assert f["axi_z9_relic"].nivel == "D"
    assert rent.nivel_de(60) == "S" and rent.nivel_de(59.9) == "A" and rent.nivel_de(3.9) == "D"
    # Rapidez a medias: 150 ventas en 30 dias = 5 al dia = 0,5.
    lento = rent.fila_de("x", {"n": "X", "r": None, "t": [], "p": {"": _p(100, 90, 100, 150, 30, 10)}},
                         _fotos(tmp_path, {"x": {"n": "X", "r": None, "t": [], "p": {"": _p(100, 90, 100, 150, 30, 10)}}}))
    assert lento.venta.rapidez == 0.5 and lento.puntos == 50 and lento.nivel == "A"


def test_rango_recomendado_en_arcanos_cuenta_las_copias(tmp_path):
    f = _por_slug(rent.calcular(_fotos(tmp_path)))
    caro, suelto = f["arcano_caro"], f["arcano_suelto"]
    assert (caro.venta.rango, caro.motivo_rango, caro.copias) == (5, "arcano_max", 21)
    assert caro.otra.rango == 0
    assert (suelto.venta.rango, suelto.motivo_rango) == (0, "arcano_suelto")
    assert suelto.otra.rango == 5 and suelto.otra.precio == 130
    assert suelto.nivel == "C"  # 8 de platino cada uno: el nivel es el de venderlo suelto


def test_rango_recomendado_en_mods_solo_compara_precios(tmp_path):
    f = _por_slug(rent.calcular(_fotos(tmp_path)))
    prime, igual, unico = f["mod_prime"], f["mod_igual"], f["mod_unico"]
    assert (prime.venta.rango, prime.motivo_rango, prime.endo) == (10, "mod_precio", 40920)
    assert prime.copias is None  # el endo no se convierte a platino ni a copias
    assert (igual.venta.rango, igual.motivo_rango) == (0, "mod_precio")  # mismo precio: no se gasta endo
    assert (unico.venta.rango, unico.motivo_rango, unico.otra) == (0, "unico", None)
    assert unico.venta.venta_min == 7  # ordenes de la variante normal; la rara (250) no cuenta


def test_margen_solo_con_comprador_y_vendedor(tmp_path):
    f = _por_slug(rent.calcular(_fotos(tmp_path)))
    assert f["set_bueno"].venta.margen == 3
    assert f["barato"].venta.margen is None
    assert f["lith_x1_relic"].venta.margen is None


def test_filtros_por_tipo_boveda_y_nombre(tmp_path):
    filas = rent.calcular(_fotos(tmp_path))
    con = sqlite3.connect(tmp_path / "indice.sqlite")
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, nombre_en TEXT, nombre_es TEXT, vaulted INTEGER,"
                " padre_id INTEGER, market_slug TEXT)")
    con.executemany("INSERT INTO items VALUES (?, ?, ?, ?, ?, ?)", [
        (1, "Good Prime", "Bueno Prime", 1, None, "set_bueno"),
        (2, "Chassis Blueprint", "Plano de chasis", None, 1, "pieza"),
        (3, "Primed Thing", "Munición criogénica Prime", None, None, "mod_prime"),
    ])
    assert rent.poner_nombres(filas, con, castellano=True) == 3
    f = _por_slug(filas)
    assert f["pieza"].nombre == "Bueno Prime: Plano de chasis" and f["pieza"].item_id == 2
    assert f["set_bueno"].boveda is True and f["mod_prime"].boveda is None
    assert f["set_bueno"].nombre == "Bueno Prime (set)"  # en el indice el set es el propio objeto
    assert f["barato"].nombre == "Cheap Fast Thing" and f["barato"].item_id is None  # no esta en el indice
    assert {x.slug for x in rent.filtrar(filas, tipo="arcanos")} == {"arcano_caro", "arcano_suelto"}
    assert {x.slug for x in rent.filtrar(filas, tipo="reliquias", boveda="si")} == {"lith_x1_relic"}
    assert {x.slug for x in rent.filtrar(filas, boveda="no")} == {"axi_z9_relic"}
    assert [x.slug for x in rent.filtrar(filas, texto="municion CRIOGENICA")] == ["mod_prime"]  # sin tildes
    assert [x.slug for x in rent.filtrar(filas, texto="primed thing")] == ["mod_prime"]         # y en ingles
    assert all(not x.pocos_datos for x in rent.filtrar(filas, con_pocos_datos=False))
    assert rent.filtrar(filas, texto="no existe nada asi") == []
    rent.poner_nombres(filas, con, castellano=False)
    assert _por_slug(filas)["pieza"].nombre == "Good Prime: Chassis Blueprint"
    # Sin indice: nombres en ingles de la foto, sin ficha, y no falla.
    assert rent.poner_nombres(filas, None, castellano=True) == 0
    assert _por_slug(filas)["set_bueno"].nombre == "Good Prime Set"


def _muchos(n: int) -> dict:
    azar = random.Random(7)
    objetos = {}
    for i in range(n):
        if i % 3 == 0:
            objetos[f"mod_{i}"] = {"n": f"Mod {i}", "r": 10, "t": ["mod", "rare"], "p": {
                "0": _p(10, 8, azar.randint(1, 60), azar.randint(0, 3000), azar.randint(0, 30), 5),
                "10": _p(40, 30, azar.randint(20, 200), azar.randint(0, 2000), azar.randint(0, 30), 5)}}
        else:
            objetos[f"cosa_{i}"] = {"n": f"Cosa {i}", "r": None, "t": ["set", "prime"], "p": {
                "": _p(10, 8, azar.randint(1, 300), azar.randint(0, 3000), azar.randint(0, 30), 5)}}
    return objetos


def test_cuatro_mil_objetos_en_menos_de_un_segundo(tmp_path):
    fotos = _fotos(tmp_path, _muchos(4000))
    inicio = time.perf_counter()
    filas = rent.calcular(fotos)
    rent.poner_nombres(filas, None, True)
    rent.filtrar(filas, texto="cosa 12")
    assert time.perf_counter() - inicio < 1.0
    assert len(filas) > 3000
    assert all(f.venta.ventas_30d > 0 and f.venta.precio > 0 for f in filas)


def test_foto_real():
    ruta = os.environ.get("FARMADEX_FOTO_PRECIOS", "")
    if not ruta or not Path(ruta).exists():
        pytest.skip("sin foto real (FARMADEX_FOTO_PRECIOS)")
    fotos = pd.PreciosDiarios(carpeta=Path(ruta).parent, plataforma="pc")
    fotos.instalar(json.loads(gzip.decompress(Path(ruta).read_bytes())))
    inicio = time.perf_counter()
    filas = rent.calcular(fotos)
    indice = os.environ.get("FARMADEX_INDICE_REAL", "")
    con = sqlite3.connect(f"file:{Path(indice).as_posix()}?mode=ro", uri=True) if indice else None
    enlazadas = rent.poner_nombres(filas, con, True)
    tardado = time.perf_counter() - inicio
    assert tardado < 1.0
    assert 2000 < len(filas) <= len(fotos)
    # Nada inventado: todo lo que entra tiene ventas y precio; lo de pocos datos, sin nivel.
    for f in filas:
        assert f.venta.ventas_30d > 0 and f.venta.precio > 0
        assert (f.nivel == rent.SIN_NIVEL) == f.venta.pocos_datos
        if f.nivel in ("S", "A"):
            assert f.venta.ventas_30d >= rent.MIN_VENTAS and (f.venta.dias_30d or 0) >= rent.MIN_DIAS
    niveles = [f.nivel for f in filas]
    assert 0 < niveles.count("S") < niveles.count("A") < niveles.count("B") < niveles.count("C")
    assert filas[0].nivel == "S" and all(f.nombre for f in filas)
    if con is not None:
        assert enlazadas > len(filas) * 0.8


# -- la pagina -----------------------------------------------------------------------------


@pytest.fixture()
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def castellano():
    from farmadex import idiomas

    idiomas.cargar("es")
    yield idiomas
    idiomas.cargar("es")


def _reloj(texto: str):
    estado = {"ahora": datetime.fromisoformat(texto)}

    def reloj():
        return estado["ahora"]

    reloj.poner = lambda nuevo: estado.__setitem__("ahora", datetime.fromisoformat(nuevo))
    return reloj


def _pagina(app, tmp_path, fotos=None, ahora="2026-09-30T15:00:00+00:00", ruta_indice=None):
    from farmadex.ui.pestana_mercado import PestanaMercado

    fotos = fotos if fotos is not None else _fotos(tmp_path)
    w = PestanaMercado(precios=fotos, reloj=_reloj(ahora), ruta_indice=ruta_indice or tmp_path / "no_hay.sqlite")
    w.resize(1100, 700)
    w.show()
    app.processEvents()
    assert w.esperar_calculo()
    app.processEvents()
    return w


def _textos(w, columna: str) -> list[str]:
    from farmadex.ui.pestana_mercado import COLUMNAS

    c = COLUMNAS.index(columna)
    return [w.modelo.data(w.modelo.index(f, c)) for f in range(w.modelo.rowCount())]


def test_pagina_pinta_la_lista_con_su_fecha_y_formula(app, tmp_path, castellano):
    w = _pagina(app, tmp_path)
    assert w.modelo.rowCount() == 12 and w.tabla.isVisible() and not w.vacio.isVisible()
    assert _textos(w, "nivel")[0] == "S" and _textos(w, "objeto")[0] == "Arcane Expensive"
    assert "Pocos datos" in _textos(w, "nivel")          # visible, no escondido
    assert _textos(w, "nivel")[-1] == "Pocos datos"       # y al final
    assert "warframe.market" in w.fecha.texto_completo() and "30/09/2026" in w.fecha.texto_completo()
    assert "09:00" in w.cuenta.texto_completo()                     # de las 15:00 a las 00:00 UTC
    assert "precio habitual × rapidez" in w.nota.text()   # la formula, en la propia pantalla
    assert "60" in w.leyenda.text() and "Cómo se calcula" in w.nota.toolTip()
    assert w.cuantos.text() == "12 objetos"
    # El margen que no tiene sentido no se pinta como numero.
    margenes = dict(zip(_textos(w, "objeto"), _textos(w, "margen")))
    assert margenes["Good Prime Set"].startswith("3 (") and margenes["Cheap Fast Thing"] == "—"
    pista = w.modelo.data(w.modelo.index(0, 0), 3)  # Qt.ToolTipRole
    assert "21" in pista and "Nivel S" in pista
    # En reliquias no se ensena margen: sus ordenes no casan con las ventas cerradas.
    from farmadex.ui.pestana_mercado import margen_de

    reliquia = next(f for f in w.modelo.filas if f.slug == "axi_z9_relic")
    assert reliquia.venta.margen == 1 and margen_de(reliquia) is None
    w.deleteLater()


def test_pagina_filtra_busca_y_ordena(app, tmp_path, castellano):
    from PySide6.QtCore import Qt

    from farmadex.ui.pestana_mercado import COLUMNAS

    w = _pagina(app, tmp_path)
    w.tipo.setCurrentIndex(w.tipo.findData("mods"))
    assert set(_textos(w, "objeto")) == {"Primed Thing", "Same Price Mod", "Only Base Mod"}
    assert dict(zip(_textos(w, "objeto"), _textos(w, "rango")))["Primed Thing"] == "Rango 10"
    w.tipo.setCurrentIndex(0)
    w.boveda.setCurrentIndex(w.boveda.findData("si"))
    assert _textos(w, "objeto") == ["Lith X1 Relic"] and _textos(w, "rango") == ["Intacta"]
    w.boveda.setCurrentIndex(0)
    w.caja.setText("ARCANE")
    assert _textos(w, "objeto") == ["Arcane Expensive", "Arcane Loose"]
    w.caja.setText("zzzz")
    assert w.modelo.rowCount() == 0 and w.vacio.isVisible() and "filtrado" in w.vacio.text()
    w.caja.setText("")
    w.con_pocos.setChecked(False)
    assert "Pocos datos" not in _textos(w, "nivel") and w.modelo.rowCount() == 10
    w.con_pocos.setChecked(True)
    # Ordenar por columnas: precio de mayor a menor y al reves; lo que no tiene dato, al final.
    w.tabla.horizontalHeader().setSortIndicator(COLUMNAS.index("precio"), Qt.DescendingOrder)
    assert _textos(w, "objeto")[0] == "Pumped Thing"
    w.tabla.horizontalHeader().setSortIndicator(COLUMNAS.index("precio"), Qt.AscendingOrder)
    assert _textos(w, "objeto")[0] == "Cheap Fast Thing"
    w.tabla.horizontalHeader().setSortIndicator(COLUMNAS.index("margen"), Qt.AscendingOrder)
    assert _textos(w, "margen")[-1] == "—" and _textos(w, "margen")[0] != "—"
    w.tabla.horizontalHeader().setSortIndicator(COLUMNAS.index("objeto"), Qt.AscendingOrder)
    assert _textos(w, "objeto")[0] == "Arcane Expensive"
    w.deleteLater()


def test_clic_abre_la_ficha_o_busca_por_nombre(app, tmp_path, castellano):
    con = sqlite3.connect(tmp_path / "indice.sqlite")
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, nombre_en TEXT, nombre_es TEXT, vaulted INTEGER,"
                " padre_id INTEGER, market_slug TEXT)")
    con.execute("INSERT INTO items VALUES (77, 'Arcane Expensive', 'Arcano caro', NULL, NULL, 'arcano_caro')")
    con.commit()
    con.close()
    w = _pagina(app, tmp_path, ruta_indice=tmp_path / "indice.sqlite")
    abiertos, buscados = [], []
    w.abrir_item.connect(abiertos.append)
    w.buscar_texto.connect(buscados.append)
    assert _textos(w, "objeto")[0] == "Arcano caro"  # el nombre en el idioma del jugador
    w.tabla.clicked.emit(w.modelo.index(0, 1))
    w.tabla.clicked.emit(w.modelo.index(_textos(w, "objeto").index("Good Prime Set"), 1))
    assert abiertos == [77] and buscados == ["Good Prime Set"]  # sin ficha en el indice: se busca
    # En ingles, el nombre ingles (y se puede seguir buscando por el castellano).
    castellano.cargar("en")
    w.retraducir()
    assert w.esperar_calculo()
    app.processEvents()
    assert _textos(w, "objeto")[0] == "Arcane Expensive" and w.titulo.texto_completo().upper() == "WHAT TO SELL"
    w.caja.setText("arcano caro")
    assert w.modelo.rowCount() == 1
    w.deleteLater()


def test_se_repinta_sola_con_una_foto_nueva(app, tmp_path, castellano):
    fotos = _fotos(tmp_path)
    w = _pagina(app, tmp_path, fotos)
    nuevos = {"nuevo": {"n": "Brand New Set", "r": None, "t": ["set", "prime"], "p": {"": _p(200, 190, 200, 900, 30, 60)}}}
    fotos.instalar(_doc(nuevos, fecha="2026-10-01T00:45:00Z"))
    app.processEvents()
    assert w.esperar_calculo()
    app.processEvents()
    assert _textos(w, "objeto") == ["Brand New Set"] and "01/10/2026" in w.fecha.texto_completo()
    # Escondida no calcula nada: lo hace al volver a ensenarse.
    w.hide()
    fotos.instalar(_doc(fecha="2026-10-02T00:45:00Z"))
    app.processEvents()
    assert w._sucio and not w._calculando and not w.reloj_pantalla.isActive()
    w.show()
    app.processEvents()
    assert w.esperar_calculo()
    app.processEvents()
    assert w.modelo.rowCount() == 12 and w.reloj_pantalla.isActive()
    w.deleteLater()


def test_sin_foto_o_de_otra_plataforma_lo_dice_y_no_inventa(app, tmp_path, castellano):
    from farmadex.ui.pestana_mercado import PestanaMercado

    vacia = pd.PreciosDiarios(carpeta=tmp_path / "nada", plataforma="pc")
    vacia.cargado.set()
    w = PestanaMercado(precios=vacia, reloj=_reloj("2026-09-30T15:00:00+00:00"))
    w.show()
    app.processEvents()
    assert w.modelo.rowCount() == 0 and w.vacio.isVisible() and "no hay precios" in w.vacio.text()
    assert not w.tabla.isVisible() and "no hay precios" in w.fecha.texto_completo()
    w.deleteLater()
    consola = pd.PreciosDiarios(carpeta=tmp_path / "ps4", plataforma="ps4")
    consola.instalar(_doc())
    w = PestanaMercado(precios=consola, reloj=_reloj("2026-09-30T15:00:00+00:00"))
    w.show()
    app.processEvents()
    assert w.modelo.rowCount() == 0 and "PC" in w.vacio.text()
    w.deleteLater()


# -- el boton de actualizar ----------------------------------------------------------------


class _FotosFalsas:
    """Lo justo de PreciosDiarios para contar pulsaciones y controlar la descarga."""

    def __init__(self, fotos):
        self._fotos = fotos
        self.pedidas = 0
        self.tarea = None
        self.descargador = None

    def __getattr__(self, nombre):
        return getattr(self._fotos, nombre)

    def actualizar_ahora(self):
        self.pedidas += 1
        self.tarea = pd.Tarea(manual=True)
        return self.tarea


def test_motivo_del_boton_apagado():
    from farmadex.ui.pestana_mercado import motivo_boton_apagado as motivo

    def a(texto):
        return datetime.fromisoformat(texto)

    assert motivo(a("2026-09-30T15:00:00+00:00"), False) == ""
    assert motivo(a("2026-09-30T15:00:00+00:00"), True) == "descargando"
    assert motivo(a("2026-09-30T23:57:59+00:00"), False) == ""
    assert motivo(a("2026-09-30T23:58:00+00:00"), False) == "medianoche"
    assert motivo(a("2026-10-01T00:00:00+00:00"), False) == "medianoche"
    assert motivo(a("2026-10-01T00:04:59+00:00"), False) == "medianoche"
    assert motivo(a("2026-10-01T00:05:00+00:00"), False) == ""
    # La hora que cuenta es la UTC, no la del PC del jugador.
    assert motivo(a("2026-10-01T02:00:00+02:00"), False) == "medianoche"
    assert motivo(a("2026-10-01T00:00:00+02:00"), False) == ""
    assert motivo(a("2026-09-30T15:00:10+00:00"), False, a("2026-09-30T15:00:00+00:00")) == "respiro"
    assert motivo(a("2026-09-30T15:01:00+00:00"), False, a("2026-09-30T15:00:00+00:00")) == ""


def test_boton_actualizar_se_apaga_mientras_descarga(app, tmp_path, castellano):
    fotos = _FotosFalsas(_fotos(tmp_path))
    w = _pagina(app, tmp_path, fotos)
    assert w.boton.isEnabled()
    w.boton.click()
    assert fotos.pedidas == 1 and not w.boton.isEnabled() and "Descargando" in w.estado.texto_completo()
    w.boton.click()
    w.actualizar_ahora()   # ni por codigo: mientras hay una en marcha no se pide otra
    assert fotos.pedidas == 1
    fotos.tarea.resultado = "al_dia"
    fotos.tarea.hecha.set()
    w._mirar_tarea()
    assert not w.boton.isEnabled() and w.motivo_apagado() == "respiro"   # un respiro tras pedirlos
    w._reloj.poner("2026-09-30T15:01:00+00:00")
    w.refrescar_cabecera()
    assert w.boton.isEnabled()
    # La descarga automatica en marcha tambien lo apaga.
    fotos.descargador = type("D", (), {"estado": "descargando"})()
    w.refrescar_cabecera()
    assert not w.boton.isEnabled() and "Descargando" in w.estado.texto_completo()
    fotos.descargador.estado = "sin_red"
    w.refrescar_cabecera()
    assert w.boton.isEnabled() and "Sin conexión" in w.estado.texto_completo()
    w.deleteLater()


def test_pulsar_justo_a_las_00_00_utc_no_pide_nada_ni_falla(app, tmp_path, castellano):
    fotos = _FotosFalsas(_fotos(tmp_path))
    w = _pagina(app, tmp_path, fotos, ahora="2026-09-30T23:50:00+00:00")
    assert w.boton.isEnabled() and "00:10" in w.cuenta.texto_completo()
    # El reloj da las 00:00:00 sin que la pantalla se haya repasado: el boton aun parece
    # encendido, pero el clic vuelve a mirar la hora y no pide nada.
    w._reloj.poner("2026-10-01T00:00:00+00:00")
    assert w.boton.isEnabled()
    w.boton.click()
    assert fotos.pedidas == 0 and not w.boton.isEnabled()
    assert "solos" in w.estado.texto_completo() and "medianoche" in w.boton.toolTip()
    assert "24:00" in w.cuenta.texto_completo()
    for hora in ("2026-09-30T23:58:30+00:00", "2026-10-01T00:00:01+00:00", "2026-10-01T00:04:00+00:00"):
        w._reloj.poner(hora)
        w.refrescar_cabecera()
        assert not w.boton.isEnabled()
        w.actualizar_ahora()
    assert fotos.pedidas == 0
    w._reloj.poner("2026-10-01T00:06:00+00:00")
    w.refrescar_cabecera()
    assert w.boton.isEnabled()
    w.boton.click()
    assert fotos.pedidas == 1
    w.deleteLater()


class _Servidor:
    def __init__(self, doc):
        self.datos = gzip.compress(json.dumps(doc).encode(), mtime=0)
        import hashlib

        self.version = {"formato": 1, "fecha": doc["fecha"], "plataforma": "pc", "objetos": len(doc["objetos"]),
                        "bytes": len(self.datos), "sha256": hashlib.sha256(self.datos).hexdigest()}
        self.peticiones = []
        self.soltar = threading.Event()
        self.soltar.set()

    def __call__(self, peticion):
        self.peticiones.append(peticion.url.path.rsplit("/", 1)[-1])
        self.soltar.wait(5)
        if peticion.url.path.endswith(pd.NOMBRE_VERSION):
            return httpx.Response(200, json=self.version)
        return httpx.Response(200, content=self.datos)


def test_descarga_de_verdad_a_las_00_00_utc_y_a_la_vez_que_la_automatica(app, tmp_path, castellano):
    """Aunque alguien salte el apagado del boton: a medianoche la foto de hoy aun no esta
    y no pasa nada (se queda la de ayer); y si coincide con la automatica, hay una sola."""
    fotos = _fotos(tmp_path, fecha="2026-09-30T00:40:00Z")
    servidor = _Servidor(_doc(fecha="2026-09-30T00:40:00Z"))  # GitHub sigue con la de ayer
    reloj = _reloj("2026-10-01T00:00:00+00:00")
    fotos.descargador = pd.Descargador(fotos, base=BASE, transporte=httpx.MockTransport(servidor), reloj=reloj,
                                       azar=random.Random(1))
    w = _pagina(app, tmp_path, fotos, ahora="2026-10-01T00:00:00+00:00")
    filas_antes = w.modelo.rowCount()
    servidor.soltar.clear()
    automatica = fotos.descargador.actualizar(manual=False)
    manual = fotos.actualizar_ahora()          # lo que haria el boton
    assert manual is automatica                 # se une a la que ya esta en marcha
    w.refrescar_cabecera()
    assert not w.boton.isEnabled()
    servidor.soltar.set()
    assert manual.esperar(5) == "aun_no_hay"
    assert servidor.peticiones == [pd.NOMBRE_VERSION] and fotos.descargador.descargas == 0
    app.processEvents()
    w.refrescar_cabecera()
    assert w.modelo.rowCount() == filas_antes and "30/09/2026" in w.fecha.texto_completo()
    assert "preparando" in w.estado.texto_completo() or "solos" in w.estado.texto_completo()
    w.deleteLater()


def test_cuatro_mil_filas_no_atascan_la_pagina(app, tmp_path, castellano):
    w = _pagina(app, tmp_path, _fotos(tmp_path, _muchos(4000)))
    assert w.modelo.rowCount() > 3000 and w.ultimo_calculo_s < 1.0
    inicio = time.perf_counter()
    w.caja.setText("cosa 1")
    w.caja.setText("")
    w.tabla.horizontalHeader().setSortIndicator(3, w.tabla.horizontalHeader().sortIndicatorOrder())
    w.tabla.verticalScrollBar().setValue(w.tabla.verticalScrollBar().maximum())
    app.processEvents()
    w.grab()
    assert time.perf_counter() - inicio < 1.0
    w.deleteLater()


# -- dentro de la ventana ----------------------------------------------------------------------


def test_mercado_esta_en_herramientas_y_abre_fichas(app, tmp_path, monkeypatch, castellano):
    from farmadex import config, tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    pd._reiniciar_para_pruebas(_fotos(tmp_path))
    try:
        from farmadex.ui.overlay import VentanaOverlay
        from farmadex.ui.pestana_mercado import PestanaMercado

        v = VentanaOverlay()
        v.show()
        pagina = v.ir_a("herramientas/mercado")
        assert isinstance(pagina, PestanaMercado) and v.ruta_actual() == "herramientas/mercado"
        assert v.ir_a("mercado") is pagina
        app.processEvents()
        assert pagina.esperar_calculo()
        app.processEvents()
        assert pagina.modelo.rowCount() == 12
        abiertos, buscados = [], []
        monkeypatch.setattr(v, "_abrir_desde_cursor", lambda item_id, nombre: abiertos.append(item_id))
        monkeypatch.setattr(v.buscador.caja, "setText", buscados.append)
        pagina.abrir_item.emit(5)
        pagina.tabla.clicked.emit(pagina.modelo.index(0, 1))
        assert abiertos == [5] and buscados == ["Arcane Expensive"]
        assert v.ruta_actual() == "buscar"
        v.hide()
        v.deleteLater()
    finally:
        pd._reiniciar_para_pruebas(None)
