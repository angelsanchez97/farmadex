"""Fallos que salen al usar el programa de principio a fin, cruzando pestanas.

- Las tablas de WFCD marcan casi todos los premios de reliquia como "Uncommon": la ficha
  de la Axi A7 decia "Poco comun" de los Sistemas de Ash Prime (10 % en Radiante) mientras
  la vista compacta los llamaba "Rara".
- La ficha de una reliquia en boveda decia "Sin fuentes registradas: puede venir de una
  mision de historia...", cuando la compacta y Objetivos dicen que hay que comprarla.
- Los contratos salian como "Contratos de Cetus Level 10 - 30 Cetus Bounty · Stage 2,
  Stage 3 of 4, and Stage 3 of 5" en cualquier idioma.
"""
from __future__ import annotations

import pytest

from farmadex import idiomas
from farmadex.datos import nodos, relaciones
from farmadex.datos.relaciones import rareza_reliquia


def test_la_rareza_del_premio_la_fija_la_probabilidad_no_la_tabla():
    assert rareza_reliquia("Radiant", 10.0, "Uncommon") == "Rare"
    assert rareza_reliquia("Radiant", 20, "Uncommon") == "Uncommon"
    assert rareza_reliquia("Radiant", 16.67, "Uncommon") == "Common"
    assert rareza_reliquia("Intact", 2.0, None) == "Rare"
    assert rareza_reliquia("Intact", 25.33, "Uncommon") == "Common"
    assert rareza_reliquia("Flawless", 17, "Uncommon") == "Uncommon"
    assert rareza_reliquia("Flawless", 20, "Uncommon") == "Common"
    # Lo que no cuadra con ningun refinamiento conocido se deja como venia.
    assert rareza_reliquia("Requiem", 25.33, "Uncommon") == "Uncommon"
    assert rareza_reliquia("Radiant", None, "Rare") == "Rare"
    assert rareza_reliquia("Radiant", 33.3, None) is None


def _neo_z5(con) -> int:
    """Una reliquia real con la tabla tal cual la da WFCD: seis premios, seis Uncommon."""
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo, vaulted) "
        "VALUES ('RELIQUIA/Neo Z5', 'Neo Z5 Relic', 'Reliquia Neo Z5', 'Relics', 'Relic', 1)"
    )
    rid = con.execute("SELECT id FROM items WHERE unique_name = 'RELIQUIA/Neo Z5'").fetchone()[0]
    premios = (("Zhuge Prime Barrel", 10.0), ("Lex Prime Barrel", 16.67), ("Forma", 20.0))
    for nombre, prob in premios:
        con.execute(
            "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria) VALUES (?, ?, ?, 'Primary')",
            (f"/p/{nombre}", nombre, nombre),
        )
        iid = con.execute("SELECT id FROM items WHERE unique_name = ?", (f"/p/{nombre}",)).fetchone()[0]
        con.execute(
            "INSERT INTO reliquia_recompensas (reliquia_id, refinamiento, item_id, rareza, probabilidad) "
            "VALUES (?, 'Radiant', ?, 'Uncommon', ?)",
            (rid, iid, prob),
        )
        con.execute(
            "INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, refinamiento, rareza, probabilidad) "
            "VALUES (?, 'reliquia', ?, 'Neo Z5 Relic (Radiant)', 'Radiant', 'Uncommon', ?)",
            (iid, rid, prob),
        )
    con.commit()
    return rid


def test_contenido_y_reliquias_de_corrigen_la_rareza(con):
    rid = _neo_z5(con)
    contenido = {c["nombre_en"]: c["rareza"] for c in relaciones.contenido_de(con, rid, "Radiant")}
    assert contenido == {"Zhuge Prime Barrel": "Rare", "Lex Prime Barrel": "Common", "Forma": "Uncommon"}
    zhuge = con.execute("SELECT id FROM items WHERE nombre_en = 'Zhuge Prime Barrel'").fetchone()[0]
    assert relaciones.reliquias_de(con, zhuge)[0]["rareza"] == "Rare"


def test_el_importador_de_drops_guarda_la_rareza_por_probabilidad(con, tmp_path):
    import json

    from farmadex.datos.drops import ImportadorDrops

    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo) "
        "VALUES ('RELIQUIA/Neo Z5', 'Neo Z5 Relic', 'Reliquia Neo Z5', 'Relics', 'Relic')"
    )
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria) VALUES ('/p/Zhuge', 'Zhuge Prime Barrel', 'Canon de Zhuge Prime', 'Primary')"
    )
    con.commit()
    alias = {
        "neo z5 relic": con.execute("SELECT id FROM items WHERE nombre_en = 'Neo Z5 Relic'").fetchone()[0],
        "zhuge prime barrel": con.execute("SELECT id FROM items WHERE nombre_en = 'Zhuge Prime Barrel'").fetchone()[0],
    }
    ruta = tmp_path / "relics.json"
    ruta.write_text(json.dumps({"relics": [{
        "tier": "Neo", "relicName": "Z5", "state": "Radiant",
        "rewards": [{"itemName": "Zhuge Prime Barrel", "rarity": "Uncommon", "chance": 10}],
    }]}), encoding="utf-8")
    ImportadorDrops(con, alias).relics(ruta)
    assert con.execute("SELECT rareza FROM reliquia_recompensas").fetchone()[0] == "Rare"
    assert con.execute("SELECT rareza FROM fuentes WHERE tipo = 'reliquia'").fetchone()[0] == "Rare"


@pytest.mark.parametrize(
    "codigo, contrato, etapa",
    [
        ("es", "Contratos de Cetus · nivel 10-30", "etapas 2 y 3"),
        ("en", "Cetus bounties · level 10-30", "stages 2 and 3"),
        ("de", "Cetus-Auftraege · Stufe 10-30", "Phasen 2 und 3"),
    ],
)
def test_los_contratos_se_leen_en_el_idioma_de_la_interfaz(codigo, contrato, etapa):
    idiomas.cargar(codigo)
    try:
        assert nodos.nombre_contrato("Contratos de Cetus Level 10 - 30 Cetus Bounty") == contrato
        assert nodos.etapa_bonita("Stage 2, Stage 3 of 4, and Stage 3 of 5") == etapa
    finally:
        idiomas.cargar("es")


def test_los_contratos_especiales_conservan_lo_que_los_distingue():
    idiomas.cargar("es")
    assert nodos.nombre_contrato("Contratos de Cetus Level 15 - 25 Ghoul Bounty") == "Contratos de Cetus · nivel 15-25 · Ghoul"
    assert nodos.nombre_contrato("Contratos del Valle Level 40 - 60 PROFIT-TAKER - PHASE 1") == (
        "Contratos del Valle · nivel 40-60 · Profit-Taker - Phase 1"
    )
    assert nodos.nombre_contrato("Laboratorio Entrati Level  55 - 60 Entrati Lab Bounty") == "Laboratorio Entrati · nivel 55-60"
    assert nodos.nombre_contrato("Venus/Fossa") is None
    assert nodos.etapa_bonita("Stage 1") == "etapa 1"
    assert nodos.etapa_bonita("Stage 4 of 5") == "etapa 4 de 5"
    assert nodos.etapa_bonita("Final stage") == "etapa final"
    assert nodos.etapa_bonita("First Completion") == "primera vez"
    assert nodos.etapa_bonita("Algo raro") == "Algo raro"
    assert nodos.etapa_bonita(None) == ""
    # nombre_bonito, que usan la ficha, la compacta y Objetivos, pasa por aqui.
    assert nodos.nombre_bonito(None, "Contratos de Deimos Level 5 - 15 Cambion Drift Bounty") == "Contratos de Deimos · nivel 5-15"


def test_la_ficha_de_una_reliquia_en_boveda_no_dice_que_venga_de_una_mision_de_historia(con, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from farmadex.datos import indice as modulo_indice, items
    from farmadex.ui.pestana_buscador import PestanaBuscador

    QApplication.instance() or QApplication([])
    idiomas.cargar("es")
    rid = _neo_z5(con)
    monkeypatch.setattr(modulo_indice, "conectar", lambda *a, **k: con)
    pestana = PestanaBuscador()
    pestana.habilitar(True)
    html_ficha = pestana._html(items.ficha(con, rid))
    assert "Sin fuentes registradas" not in html_ficha
    assert "No cae en ninguna mision activa" in html_ficha
    assert "Hay que comprarla a otro jugador" in html_ficha
    # Y el contenido lleva la rareza buena: la pieza al 10 % es la rara.
    assert html_ficha.index("Zhuge Prime Barrel") < html_ficha.index("Lex Prime Barrel")
    assert "Raro" in html_ficha
