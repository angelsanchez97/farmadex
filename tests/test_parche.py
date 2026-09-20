"""El dia del parche: datos rotos, campos nuevos y fuentes desfasadas no rompen nada
y, cuando algo no cuadra, la aplicacion lo detecta y lo dice."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from farmadex.captura import ocr, pantalla
from farmadex.captura.ocr import Leido
from farmadex.datos import indice, items
from farmadex.datos.drops import ImportadorDrops
from farmadex.datos.items import ImportadorItems
from farmadex.online import market, worldstate
from farmadex.registro import eelog

FIXTURES = Path(__file__).parent / "fixtures"


# --- EE.log: version del juego y modo de ventana ---------------------------------

CABECERA = (
    "0.079 Sys [Diag]: Process Command-line: -windowMode:2 -shaderCache:1 -graphicsDriver:dx12"
    " -cluster:public -language:es\n"
    "0.079 Sys [Diag]: Build Label: 2026.08.19.11.06 Retail Windows x64 [Stripped]\n"
    "0.080 Sys [Diag]: Build Unique ID: 427001834\n"
    "0.082 Sys [Diag]: Windows user-name: alguien\n"
)


def test_la_cabecera_de_eelog_da_build_fecha_y_modo(tmp_path):
    ruta = tmp_path / "EE.log"
    ruta.write_text(CABECERA + "x" * 1000, encoding="utf-8")
    cabecera = eelog.leer_cabecera(ruta)
    assert cabecera.build == "2026.08.19.11.06"
    assert cabecera.fecha_build == date(2026, 8, 19)
    assert cabecera.modo_ventana == 2


def test_una_cabecera_con_otro_formato_no_revienta(tmp_path, caplog):
    ruta = tmp_path / "EE.log"
    ruta.write_text("0.001 Sys [Diag]: Algo nuevo que no se conoce\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cabecera = eelog.leer_cabecera(ruta)
    assert cabecera.build == "" and cabecera.fecha_build is None and cabecera.modo_ventana is None
    assert "Build Label" in caplog.text
    # Un build con formato raro tampoco da fecha, pero tampoco error.
    assert eelog.Cabecera(build="retail-2026").fecha_build is None
    assert eelog.leer_cabecera(tmp_path / "no_existe.log").build == ""


def test_un_mensaje_nuevo_de_la_pantalla_de_reliquias_se_anota_una_vez(caplog):
    eelog._mensajes_desconocidos.clear()
    linea = "123.4 Script [Info]: ProjectionRewardChoice.lua: Rewards revealed (new in U40)"
    with caplog.at_level(logging.INFO, logger="farmadex.eelog"):
        assert eelog.clasificar(linea) is None
        assert eelog.clasificar(linea) is None
    assert caplog.text.count("Rewards revealed") == 1
    # Los conocidos siguen funcionando.
    assert eelog.clasificar("Script [Info]: ProjectionRewardChoice.lua: Got rewards") == "reliquia_recompensas"


# --- desfase entre el parche y los datos descargados ------------------------------

def test_desfase_avisa_de_las_fuentes_anteriores_al_parche():
    meta = {"items_fecha": "2026-08-10T12:00:00Z", "drops_modified": "1755561600000"}  # 2025-08-19
    atrasadas = indice.desfase_con_el_juego(meta, date(2026, 8, 19))
    assert [f for f, _ in atrasadas] == ["catalogo de objetos", "tablas de drops"]
    assert atrasadas[0][1] == "2026-08-10"

    # Con datos posteriores al parche no hay aviso; sin build tampoco.
    al_dia = {"items_fecha": "2026-08-20T01:00:00Z", "drops_modified": "2026-08-21"}
    assert indice.desfase_con_el_juego(al_dia, date(2026, 8, 19)) == []
    assert indice.desfase_con_el_juego(meta, None) == []
    assert indice.desfase_con_el_juego({}, date(2026, 8, 19)) == []


def test_fechas_de_meta_en_sus_dos_formatos_y_basura():
    assert indice.fecha_de_meta("2026-08-10T12:00:00Z") == date(2026, 8, 10)
    assert indice.fecha_de_meta("1755561600000") == date(2025, 8, 19)
    assert indice.fecha_de_meta("1755561600") == date(2025, 8, 19)
    assert indice.fecha_de_meta("") is None
    assert indice.fecha_de_meta("ayer") is None
    assert indice.fecha_de_meta("99999999999999999999") is None


# --- catalogo de WFCD con campos y categorias nuevas ------------------------------

def test_el_catalogo_con_campos_raros_y_categoria_nueva_se_importa_igual(con, tmp_path, caplog):
    objetos = [
        {
            "uniqueName": "/Lotus/Nuevo/Cosa",
            "name": "Cosa Prime",
            "category": "CategoriaInventada",
            "type": ["lista", "en vez de texto"],
            "vaulted": "true",  # texto en vez de bool
            "tradable": "no",
            "ducats": "45",  # numero como texto
            "description": {"raro": 1},
            "campoNuevo": {"que": "nadie conoce"},
            "components": [
                {"uniqueName": "/Lotus/Nuevo/Cosa/Sys", "name": "Systems", "itemCount": "1", "ducats": None,
                 "drops": ["cadena suelta", {"location": "Solaris Z9 Relic (Radiant)", "chance": 2}]},
                "una cadena donde iba un componente",
            ],
            "drops": {"a": {"location": "Vanguard B4 Relic", "chance": 5, "rarity": "Rare"}},
        },
        "basura",
        {"uniqueName": "/Lotus/SinNombre"},
    ]
    ruta = tmp_path / "CategoriaInventada.json"
    ruta.write_text(json.dumps(objetos), encoding="utf-8")
    importador = ImportadorItems(con, {})
    items._eras_avisadas.clear()
    with caplog.at_level(logging.WARNING):
        assert importador.importar_categoria(ruta) == 1
    assert "CategoriaInventada" in caplog.text  # se avisa de la categoria nueva
    assert "Solaris" in caplog.text  # y de la era de reliquia nueva

    fila = con.execute(
        "SELECT categoria, tipo, vaulted, comerciable, ducados FROM items WHERE unique_name = '/Lotus/Nuevo/Cosa'"
    ).fetchone()
    assert fila == ("CategoriaInventada", "lista\nen vez de texto", 1, 0, 45)
    pieza = con.execute(
        "SELECT item_count FROM items WHERE unique_name = '/Lotus/Nuevo/Cosa/Sys'"
    ).fetchone()
    assert pieza == (1,)
    # Las reliquias de eras nuevas entran como fuente de tipo reliquia, no como 'otro'.
    tipos = {f[0] for f in con.execute("SELECT DISTINCT tipo FROM fuentes")}
    assert tipos == {"reliquia"}
    eras = {json.loads(f[0])["reliquia"] for f in con.execute("SELECT datos_extra FROM fuentes")}
    assert eras == {"Solaris Z9", "Vanguard B4"}


def test_reliquias_con_recompensas_rotas_no_tumban_la_importacion(con, tmp_path):
    reliquias = [
        {
            "uniqueName": "/Lotus/Proj/SolarisZ9Bronze",
            "name": "Solaris Z9 Intact",
            "category": "Relics",
            "vaulted": False,
            "rewards": [
                "cadena",
                {"chance": 2, "rarity": "Rare", "item": "no es un objeto"},
                {"chance": 25, "rarity": "Common", "item": {"uniqueName": "/Lotus/NoExiste"}},
            ],
        },
        {"uniqueName": "/Lotus/Proj/Raro", "name": "Nombre De Tres Palabras", "category": "Relics"},
    ]
    ruta = tmp_path / "Relics.json"
    ruta.write_text(json.dumps(reliquias), encoding="utf-8")
    importador = ImportadorItems(con, {})
    importador.importar_categoria(ruta)
    assert con.execute("SELECT nombre_es FROM items WHERE unique_name = 'RELIQUIA/Solaris Z9'").fetchone() == (
        "Reliquia Solaris Z9",
    )


# --- tablas de drops con entradas rotas ------------------------------------------

def test_las_tablas_de_drops_con_entradas_rotas_guardan_lo_que_vale(indice_poblado, tmp_path):
    con, _, drops = indice_poblado
    antes = con.execute("SELECT COUNT(*) FROM fuentes WHERE tipo = 'mision'").fetchone()[0]
    tabla = {
        "Sedna": {
            "Hydron": {
                "gameMode": "Defense",
                "rewards": {
                    "A": [
                        "cadena suelta",
                        {"itemName": None, "chance": 1},
                        {"item": "Axi A7 Relic", "chance": 7.5, "rarity": "Rare"},  # clave nueva 'item'
                        {"itemName": "Axi A7 Relic (Radiant)", "chance": 1.0},
                    ],
                    "B": "no es una lista",
                },
            },
            "Roto": "no es un nodo",
        },
        "Basura": ["lista", "en", "vez", "de", "nodos"],
    }
    ruta = tmp_path / "missionRewards.json"
    ruta.write_text(json.dumps({"missionRewards": tabla}), encoding="utf-8")
    drops.mission_rewards(ruta)
    despues = con.execute("SELECT COUNT(*) FROM fuentes WHERE tipo = 'mision'").fetchone()[0]
    assert despues == antes + 2


def test_muchos_nombres_sin_casar_suben_el_nivel_del_aviso(con, caplog):
    from farmadex.datos import drops as modulo

    importador = ImportadorDrops(con, {})
    for i in range(modulo.UMBRAL_SIN_CASAR + 1):
        importador.item_id(f"Objeto Nuevo Del Parche {i}")
    with caplog.at_level(logging.WARNING, logger="farmadex.drops"):
        importador.importar_todo({})
    assert "sin casar" in caplog.text


# --- estado del mundo: claves nuevas, eras nuevas y datos viejos -------------------

@pytest.fixture()
def datos_mundo():
    return json.loads((FIXTURES / "worldstate.json").read_text(encoding="utf-8"))


def test_un_ciclo_nuevo_y_una_era_nueva_se_ensenan_en_vez_de_perderse(datos_mundo, caplog):
    datos_mundo["hollvaniaCycle"] = {"state": "dusk", "expiry": "2030-01-01T00:00:00.000Z"}
    datos_mundo["claveInventada"] = {"lo": "que sea"}
    datos_mundo["fissures"].insert(0, {
        "tier": "Solaris", "node": "Hydron (Sedna)", "missionType": "Defense", "enemy": "Grineer",
        "expiry": "2030-01-01T00:00:00.000Z", "isHard": True,
    })
    worldstate._eras_avisadas.clear()
    with caplog.at_level(logging.INFO, logger="farmadex.worldstate"):
        mundo = worldstate.analizar(datos_mundo, worldstate.Traductor(None))

    ciclos = {c.nombre: c.estado for c in mundo.ciclos}
    assert ciclos["Hollvania"] == "dusk"  # clave limpia y estado tal cual
    assert ciclos["Tierra"] in ("dia", "noche")
    assert mundo.claves_nuevas == ["claveInventada", "hollvaniaCycle"]
    solaris = [f for f in mundo.fisuras if f.era == "Solaris"]
    assert solaris and solaris[0].acero
    assert solaris == mundo.fisuras[-1:]  # detras de las eras conocidas, no perdida
    assert "Solaris" in caplog.text


def test_respuesta_que_no_es_un_objeto_da_un_mundo_vacio():
    mundo = worldstate.analizar(["lista"], worldstate.Traductor(None))
    assert mundo.fisuras == [] and mundo.momento is None


def test_el_mundo_viejo_se_marca_como_tal(datos_mundo, monkeypatch):
    ahora = datetime.now(timezone.utc)
    datos_mundo["timestamp"] = (ahora - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    servicio = worldstate.ServicioMundo(None)
    monkeypatch.setattr(servicio.cliente, "json", lambda *a, **k: datos_mundo)
    recibidos, fallos = [], []
    servicio.actualizado.connect(recibidos.append)
    servicio.fallo.connect(fallos.append)

    servicio.refrescar()
    assert len(recibidos) == 1 and recibidos[0].esta_viejo()
    assert fallos and "45 min" in fallos[0]

    # Datos frescos: sin aviso.
    datos_mundo["timestamp"] = ahora.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fallos.clear()
    servicio.refrescar()
    assert fallos == [] and not recibidos[-1].esta_viejo()

    # Sin 'timestamp' no se puede saber de cuando son: tambien se dice.
    datos_mundo.pop("timestamp")
    servicio.refrescar()
    assert fallos and "de cuando" in fallos[-1]
    servicio.cerrar()


# --- warframe.market con otro contrato ------------------------------------------

def test_una_respuesta_rara_del_mercado_da_error_y_no_excepcion(monkeypatch):
    m = market.Market()
    respuestas = iter([
        {"data": {"sell": "no es una lista"}},
        {"data": {"sell": ["cadena", {"platinum": "12.0", "user": "sin objeto"}]}},
        ["ni siquiera un objeto"],
    ])
    monkeypatch.setattr(m.cliente, "json", lambda *a, **k: next(respuestas))
    assert m.precios("x").error == "respuesta con formato inesperado"
    tolerante = m.precios("x")
    assert tolerante.error == "" and tolerante.mejor_venta == 12
    assert m.precios("x").error == "respuesta con formato inesperado"
    m.cerrar()


# --- OCR: las tarjetas fuera de la franja habitual ---------------------------------

def test_si_la_franja_sale_vacia_se_lee_la_ventana_entera(con, monkeypatch):
    from farmadex.captura.reliquias import LectorRecompensas

    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria) VALUES ('/p/Forma', 'Forma', 'Forma', 'Misc')"
    )
    con.commit()
    monkeypatch.setattr(indice, "hay_indice", lambda *a, **k: True)

    class Prestada:
        def __getattr__(self, nombre):
            return getattr(con, nombre)

        def close(self):
            pass

    monkeypatch.setattr(indice, "conectar", lambda *a, **k: Prestada())
    monkeypatch.setattr(pantalla, "declarar_dpi", lambda: None)
    monkeypatch.setattr(pantalla, "region_objetivo", lambda: pantalla.Region(100, 200, 1000, 500))
    capturas = []
    monkeypatch.setattr(
        pantalla, "capturar", lambda region: capturas.append(region) or np.zeros((50, 200, 3), np.uint8)
    )

    lecturas = []

    def leer_falso(self, imagen):
        lecturas.append(imagen.shape)
        # La franja (primera lectura) esta vacia; la ventana entera trae la tarjeta.
        return [] if len(lecturas) == 1 else [Leido("FORMA", 40, 30, 90, 20, 0.95)]

    monkeypatch.setattr(ocr.MotorOCR, "leer", leer_falso)
    monkeypatch.setattr(ocr.MotorOCR, "fallo", property(lambda self: None))
    lector = LectorRecompensas("rapidocr")
    leidas = []
    lector.leidas.connect(leidas.append)
    lector.leer_ahora()
    assert len(lecturas) == 2

    assert len(capturas) == 2
    assert (capturas[1].x, capturas[1].y) == (100, 200)  # la segunda captura es la ventana entera
    assert len(leidas) == 1 and [r.nombre for r in leidas[0]] == ["Forma"]
    assert leidas[0][0].caja[:2] == (140, 230)  # coordenadas de pantalla relativas a la ventana


# --- ajustes: lo que se le ensena al usuario -------------------------------------

def test_ajustes_ensena_el_modo_de_pantalla_y_el_aviso_de_parche(tmp_path, monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from farmadex import config, idiomas
    from farmadex.ui.pestana_ajustes import PestanaAjustes

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    ajustes = PestanaAjustes()

    ajustes.mostrar_modo_pantalla("exclusivo")
    assert "exclusiva" in ajustes.estado_juego.text()
    ajustes.mostrar_modo_pantalla("sin_bordes")
    assert "sin bordes" in ajustes.estado_juego.text()

    assert not ajustes.aviso_parche.isVisibleTo(ajustes)
    ajustes.avisar_parche("Warframe se ha actualizado y los datos van por detras")
    assert ajustes.aviso_parche.isVisibleTo(ajustes)
    ajustes.avisar_parche(None)
    assert not ajustes.aviso_parche.isVisibleTo(ajustes)


def test_el_aviso_grande_solo_los_dias_siguientes_al_parche():
    hoy = date(2026, 9, 20)
    assert indice.parche_reciente(date(2026, 9, 20), hoy)
    assert indice.parche_reciente(date(2026, 9, 7), hoy)
    assert not indice.parche_reciente(date(2026, 8, 19), hoy)  # un mes: las tablas de DE no cambiaron
    assert not indice.parche_reciente(None, hoy)
