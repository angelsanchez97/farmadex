"""La tabla oficial de drops de DE cuando WFCD va por detras.

El 23/09/2026 salio Citrine Prime (reliquia Neo C11 y otras) y Farmadex no la conocia:
warframe-drop-data seguia en junio y warframe-items aun no traia a Citrine Prime. La
pagina de DE (warframe.com/droptables) si. El fixture tabla_oficial.html es un recorte
real de esa pagina: unas misiones (Apolo suelta la Neo C11) y tres reliquias (Axi A7, que
el catalogo de los fixtures ya tiene; Neo C11 con Citrine Prime; Axi S21 con Steflos Prime).
"""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from conftest import FIXTURES
from farmadex.datos import descargas, indice, tabla_oficial
from farmadex.datos.drops import ImportadorDrops
from farmadex.datos.items import ImportadorItems
from farmadex.datos.tabla_oficial import FormatoDesconocido

HTML = (FIXTURES / "tabla_oficial.html").read_text(encoding="utf-8")
JUNIO = date(2026, 6, 25)  # la fecha de warframe-drop-data cuando salio Citrine Prime


def _catalogo(con, carpeta=FIXTURES):
    importador = ImportadorItems(con, {})
    for nombre in ("Warframes", "Relics", "Node"):
        importador.importar_categoria(carpeta / f"{nombre}.json")
    importador.enlazar_reliquias()
    con.commit()
    return importador


def _construir(con, importador, tabla, fecha_wfcd=JUNIO):
    datos = tabla_oficial.preparar(con, importador, tabla, [], None, fecha_wfcd)
    ImportadorDrops(con, importador.alias).importar_todo({}, datos=datos)
    con.commit()
    indice.poblar_busqueda(con)
    return datos


def _item(con, nombre_en, padre_en=None):
    if padre_en is None:
        return con.execute(
            "SELECT id, unique_name, nombre_es, categoria, padre_id FROM items "
            "WHERE nombre_en = ? AND padre_id IS NULL", (nombre_en,)
        ).fetchall()
    return con.execute(
        "SELECT i.id, i.unique_name, i.nombre_es, i.categoria, i.padre_id FROM items i "
        "JOIN items p ON p.id = i.padre_id WHERE i.nombre_en = ? AND p.nombre_en = ?",
        (nombre_en, padre_en),
    ).fetchall()


# -- lectura de la pagina ------------------------------------------------------------


def test_lee_las_reliquias_con_sus_probabilidades_por_refinamiento():
    tabla = tabla_oficial.leer(HTML)
    assert tabla.fecha == date(2026, 9, 23)
    neo = {r["state"]: r for r in tabla.reliquias if (r["tier"], r["relicName"]) == ("Neo", "C11")}
    assert set(neo) == {"Intact", "Exceptional", "Flawless", "Radiant"}
    intacta = {p["itemName"]: p["chance"] for p in neo["Intact"]["rewards"]}
    assert intacta["Citrine Prime Chassis Blueprint"] == 25.33
    assert intacta["Caliban Prime Systems Blueprint"] == 2.0
    assert len(intacta) == 6
    radiante = {p["itemName"]: p for p in neo["Radiant"]["rewards"]}
    assert radiante["Caliban Prime Systems Blueprint"]["chance"] == 10.0
    assert radiante["Caliban Prime Systems Blueprint"]["rarity"] == "Uncommon"


def test_los_nodos_se_llaman_igual_que_en_wfcd():
    misiones = tabla_oficial.leer(HTML).misiones
    apolo = misiones["Lua"]["Apollo"]
    assert apolo["gameMode"] == "Disruption" and apolo["isEvent"] is False
    assert set(apolo["rewards"]) >= {"A", "B", "C"}
    assert any(p["itemName"] == "Neo C11 Relic" for p in apolo["rewards"]["A"])
    # Mismos nombres que missionRewards.json de WFCD (comprobado contra el de junio).
    assert misiones["Mercury"]["Terminus (Caches)"]["gameMode"] == "Caches"
    assert misiones["Venus"]["Vesper Relay (Extra)"]["gameMode"] == "Follie's Hunt"
    assert misiones["Venus"]["Vesper"]["isEvent"] is True
    assert set(misiones["Duviri"]) == {"Endless: Tier 1", "Endless: Tier 1 (Hard)"}
    assert isinstance(misiones["Duviri"]["Endless: Tier 1"]["rewards"], list)
    assert "Variant Annihilation" in misiones["Saturn"]


# -- objetos que el catalogo no tiene ----------------------------------------------


def test_crea_la_reliquia_y_las_piezas_con_su_padre(con):
    importador = _catalogo(con)
    datos = _construir(con, importador, tabla_oficial.leer(HTML))
    assert set(datos) == {"relics", "missionRewards"}  # DE es mas nueva que junio

    # La reliquia, con el mismo unique_name que daria el catalogo.
    (rid, unico, nombre_es, categoria, _), = _item(con, "Neo C11 Relic")
    assert (unico, nombre_es, categoria) == ("RELIQUIA/Neo C11", "Reliquia Neo C11", "Relics")

    # Citrine Prime y sus piezas, sinteticas y enlazadas.
    (padre_id, unico_padre, _, categoria_padre, _), = _item(con, "Citrine Prime")
    assert unico_padre.startswith(tabla_oficial.PREFIJO_SINTETICO)
    assert categoria_padre == "Warframes"
    (chasis_id, unico_chasis, chasis_es, _, _), = _item(con, "Chassis", "Citrine Prime")
    assert unico_chasis.startswith("/Farmadex/DE/") and chasis_es == "Chasis"
    # El plano principal ("Daikyu Prime Blueprint") es su pieza, no el objeto padre; su
    # unique_name acaba en Blueprint para que la pestana Primes lo ponga el primero.
    (_, unico_plano, plano_es, _, _), = _item(con, "Blueprint", "Daikyu Prime")
    assert unico_plano.endswith("Blueprint") and plano_es == "Plano"

    # Probabilidades por refinamiento en reliquia_recompensas.
    filas = dict(con.execute(
        "SELECT refinamiento, probabilidad FROM reliquia_recompensas "
        "WHERE reliquia_id = ? AND item_id = ?", (rid, chasis_id),
    ).fetchall())
    assert filas == {"Intact": 25.33, "Exceptional": 23.33, "Flawless": 20.0, "Radiant": 16.67}

    # La reliquia sale en Apolo (misiones de DE), para la ruta de farmeo.
    assert con.execute(
        "SELECT count(*) FROM fuentes WHERE tipo = 'mision' AND item_id = ? "
        "AND origen_texto = 'Lua/Apollo'", (rid,)
    ).fetchone()[0] >= 1

    # Un arma sin version normal en el catalogo: la categoria sale de sus piezas.
    (_, _, _, categoria_arma, _), = _item(con, "Steflos Prime")
    assert categoria_arma == "Primary"
    assert len(_item(con, "Barrel", "Steflos Prime")) == 1

    # Buscable en espanol.
    resultados = indice.buscar(con, "chasis citrine prime")
    assert resultados and resultados[0]["item_id"] == chasis_id


def test_el_casador_reconoce_las_piezas_nuevas(con):
    from farmadex.captura.ocr import Casador

    importador = _catalogo(con)
    _construir(con, importador, tabla_oficial.leer(HTML))
    (chasis_id, *_), = _item(con, "Chassis", "Citrine Prime")
    casador = Casador(con)
    assert casador.casar("Plano De Chasis De Citrine Prime")[0] == chasis_id
    assert casador.casar("Citrine Prime Chassis Blueprint")[0] == chasis_id


def test_no_duplica_lo_que_wfcd_ya_tiene(con, tmp_path):
    # WFCD se pone al dia: su catalogo trae a Citrine Prime con sus piezas.
    warframes = json.loads((FIXTURES / "Warframes.json").read_text(encoding="utf-8"))
    base = "/Lotus/Types/Recipes/WarframeRecipes/CitrinePrime"
    warframes.append({
        "uniqueName": "/Lotus/Powersuits/Geode/CitrinePrime", "name": "Citrine Prime",
        "category": "Warframes", "type": "Warframe", "isPrime": True,
        "components": [
            {"uniqueName": base + "Blueprint", "name": "Blueprint", "itemCount": 1, "tradable": True},
            {"uniqueName": base + "ChassisComponent", "name": "Chassis", "itemCount": 1, "tradable": True},
            {"uniqueName": base + "HelmetComponent", "name": "Neuroptics", "itemCount": 1, "tradable": True},
            {"uniqueName": base + "SystemsComponent", "name": "Systems", "itemCount": 1, "tradable": True},
        ],
    })
    (tmp_path / "Warframes.json").write_text(json.dumps(warframes), encoding="utf-8")
    for nombre in ("Relics", "Node"):
        (tmp_path / f"{nombre}.json").write_text(
            (FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
    importador = _catalogo(con, tmp_path)
    _construir(con, importador, tabla_oficial.leer(HTML))

    assert con.execute(
        "SELECT count(*) FROM items WHERE unique_name LIKE '/Farmadex/%Citrine%'"
    ).fetchone()[0] == 0
    (padre_id, unico, *_), = _item(con, "Citrine Prime")
    assert unico == "/Lotus/Powersuits/Geode/CitrinePrime"
    (chasis_id, unico_chasis, *_), = _item(con, "Chassis", "Citrine Prime")
    assert unico_chasis == base + "ChassisComponent"
    assert len(_item(con, "Blueprint", "Citrine Prime")) == 1
    (rid, *_), = _item(con, "Neo C11 Relic")
    assert con.execute(
        "SELECT count(*) FROM reliquia_recompensas WHERE reliquia_id = ? AND item_id = ?",
        (rid, chasis_id),
    ).fetchone()[0] == 4
    # Lo que ya estaba en el catalogo de los fixtures tampoco se repite.
    assert len(_item(con, "Ash Prime")) == 1
    assert len(_item(con, "Axi A7 Relic")) == 1
    assert len(_item(con, "Chassis", "Ash Prime")) == 1


# -- decision entre WFCD y DE ---------------------------------------------------------


def test_decide_por_fecha_y_nunca_quita_reliquias():
    tabla = tabla_oficial.leer(HTML)
    assert tabla_oficial.es_mas_nueva(tabla, JUNIO)
    assert not tabla_oficial.es_mas_nueva(tabla, date(2026, 9, 23))
    assert tabla_oficial.es_mas_nueva(tabla, None)

    wfcd = [
        {"tier": "Axi", "relicName": "A7", "state": "Intact", "rewards": [{"itemName": "viejo"}]},
        {"tier": "Lith", "relicName": "Z9", "state": "Intact", "rewards": [{"itemName": "solo wfcd"}]},
    ]
    de = tabla.reliquias
    mezcla, nuevas = tabla_oficial.combinar_reliquias(wfcd, de, de_manda=False)
    axi = next(r for r in mezcla if (r["relicName"], r["state"]) == ("A7", "Intact"))
    assert axi["rewards"] == [{"itemName": "viejo"}]  # WFCD igual de nueva: manda WFCD
    assert any(r["relicName"] == "Z9" for r in mezcla)
    assert nuevas == len(de) - 1  # todas las de DE menos la Axi A7 Intact
    mezcla, _ = tabla_oficial.combinar_reliquias(wfcd, de, de_manda=True)
    axi = next(r for r in mezcla if (r["relicName"], r["state"]) == ("A7", "Intact"))
    assert axi["rewards"] != [{"itemName": "viejo"}]  # DE mas nueva: manda DE
    assert any(r["relicName"] == "Z9" for r in mezcla)  # y no se pierde nada

    # Misiones: solo si la de DE no sale mucho mas corta que la de WFCD.
    wfcd_misiones = {"P": {f"n{i}": {} for i in range(100)}}
    assert not tabla_oficial.misiones_completas(tabla.misiones, wfcd_misiones)
    assert tabla_oficial.misiones_completas(tabla.misiones, None)


def test_si_wfcd_esta_al_dia_solo_se_suman_las_reliquias_que_le_faltan(con):
    importador = _catalogo(con)
    datos = _construir(con, importador, tabla_oficial.leer(HTML), fecha_wfcd=date(2026, 9, 23))
    assert "missionRewards" not in datos
    assert _item(con, "Neo C11 Relic")


def test_el_aviso_de_desfase_cuenta_la_fecha_de_la_tabla_de_de():
    meta = {"items_fecha": "2026-09-22T00:00:00Z", "drops_modified": "1782419611000"}
    build = date(2026, 9, 20)
    assert indice.desfase_con_el_juego(meta, build) == [("tablas de drops", "2026-06-25")]
    assert indice.desfase_con_el_juego({**meta, "oficial_fecha": "2026-09-23"}, build) == []


# -- caida limpia ---------------------------------------------------------------------


def test_si_la_pagina_no_se_entiende_se_ignora(con, tmp_path):
    with pytest.raises(FormatoDesconocido):
        tabla_oficial.leer("<html><body>Mantenimiento</body></html>")
    with pytest.raises(FormatoDesconocido):
        tabla_oficial.leer(HTML.replace(" Relic (", " Reliquia ("))
    with pytest.raises(FormatoDesconocido):
        tabla_oficial.leer(HTML.replace("%)</td>", ")</td>"))

    rota = tmp_path / "rota.html"
    rota.write_text(HTML[: len(HTML) // 3], encoding="utf-8")  # descarga cortada
    assert tabla_oficial.cargar(rota) is None
    assert tabla_oficial.cargar(tmp_path / "no_existe.html") is None

    importador = _catalogo(con)
    antes = con.execute("SELECT count(*) FROM items").fetchone()[0]
    assert tabla_oficial.preparar(con, importador, None, [], None, JUNIO) == {}
    assert con.execute("SELECT count(*) FROM items").fetchone()[0] == antes


def test_un_fallo_a_medias_no_deja_nada_en_el_indice(con, monkeypatch):
    importador = _catalogo(con)
    antes = con.execute("SELECT count(*) FROM items").fetchone()[0]
    alias_antes = dict(importador.alias)

    def revienta(self, nombres):
        raise RuntimeError("fallo a mitad")

    # Las reliquias ya se han creado cuando fallan las piezas: todo tiene que deshacerse.
    monkeypatch.setattr(tabla_oficial.CreadorSinteticos, "piezas", revienta)
    assert tabla_oficial.preparar(con, importador, tabla_oficial.leer(HTML), [], None, JUNIO) == {}
    assert con.execute("SELECT count(*) FROM items").fetchone()[0] == antes
    assert not _item(con, "Neo C11 Relic")
    assert importador.alias == alias_antes
    assert "neo c11" not in importador.reliquias


def test_usar_tabla_oficial_con_la_pagina_rota_sigue_con_wfcd(con, tmp_path, monkeypatch):
    monkeypatch.setattr(indice, "DIR_DATOS", tmp_path)
    (tmp_path / "drops").mkdir()
    (tmp_path / "drops" / tabla_oficial.NOMBRE_FICHERO).write_text("<html>otra cosa</html>", encoding="utf-8")
    importador = _catalogo(con)
    assert indice.usar_tabla_oficial(con, importador, {}, descargas.EstadoDatos()) == ({}, "")
    # Y con la buena, se usa y se anota su fecha para meta.
    (tmp_path / "drops" / tabla_oficial.NOMBRE_FICHERO).write_text(HTML, encoding="utf-8")
    datos, fecha = indice.usar_tabla_oficial(
        con, importador, {}, descargas.EstadoDatos(drops_modified="1782419611000")
    )
    assert set(datos) == {"relics", "missionRewards"} and fecha == "2026-09-23"


# -- descarga -------------------------------------------------------------------------


def test_descarga_la_tabla_solo_si_cambia_y_sin_romper_si_falla(tmp_path, monkeypatch):
    monkeypatch.setattr(descargas, "DIR_DATOS", tmp_path)
    monkeypatch.setattr(descargas, "RUTA_ESTADO_DATOS", tmp_path / "estado_datos.json")
    monkeypatch.setattr(descargas, "crear_carpetas", lambda: None)
    version = {"valor": "Wed, 23 Sep 2026 15:13:21 GMT", "caida": False}
    pedidos = []

    def servidor(peticion):
        pedidos.append(peticion.method)
        if version["caida"]:
            return httpx.Response(503)
        cabeceras = {"last-modified": version["valor"]}
        if peticion.method == "HEAD":
            return httpx.Response(200, headers=cabeceras)
        return httpx.Response(200, headers=cabeceras, content=HTML.encode("utf-8"))

    d = descargas.Descargador(cliente=httpx.Client(transport=httpx.MockTransport(servidor)))
    ruta = d.ruta_tabla_oficial()
    assert d._sincronizar_tabla_oficial() is True
    assert ruta.read_text(encoding="utf-8") == HTML
    assert d.estado.oficial_fecha == "2026-09-23"
    assert d._sincronizar_tabla_oficial() is False  # misma version: ni se baja
    assert pedidos == ["HEAD", "GET", "HEAD"]

    version["caida"] = True
    assert d._sincronizar_tabla_oficial() is False  # sin excepcion
    assert ruta.read_text(encoding="utf-8") == HTML  # la que habia sigue entera
    d.cerrar()
