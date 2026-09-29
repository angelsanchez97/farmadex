"""¿Que hago ahora? (datos/que_hago.py y ui/que_hago.py) con un indice sintetico y numeros a mano.

Indice: Braton Prime Receptor al 10 % (Radiante) en Lith A5 (fuera de boveda, cae en una
Captura al 10 %) y al 20 % en Axi A1 (en boveda). Ash Prime Sistemas al 20 % en Meso M1
(fuera de boveda, cae en la rotacion C de una Supervivencia al 30 %).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from farmadex.datos import eficiencia, que_hago, ruta_prime
from farmadex.online.worldstate import Fisura

AHORA = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _item(con, unico, en, es=None, categoria="Primary", padre=None, vaulted=None, tipo=None):
    return con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria, tipo, es_prime, padre_id, vaulted) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?)", (unico, en, es, categoria, tipo, padre, vaulted),
    ).lastrowid


def _nodo(con, clave, nombre, planeta, mision):
    return con.execute(
        "INSERT INTO nodos (unique_name, nombre_en, nombre_es, planeta_en, planeta_es, mision_en, nivel_min, "
        "nivel_max, clave_drops) VALUES (?, ?, ?, ?, ?, ?, 10, 15, ?)", (clave, nombre, nombre, planeta, planeta,
                                                                          mision, clave),
    ).lastrowid


def _premio(con, reliquia, item, probs):
    for refinamiento, prob in probs.items():
        con.execute("INSERT INTO reliquia_recompensas (reliquia_id, refinamiento, item_id, probabilidad) "
                    "VALUES (?, ?, ?, ?)", (reliquia, refinamiento, item, prob))
        con.execute("INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, refinamiento, probabilidad) "
                    "VALUES (?, 'reliquia', ?, 'x', ?, ?)", (item, reliquia, refinamiento, prob))


def _cae(con, reliquia, nodo, clave, prob, rotacion=None):
    con.execute("INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, rotacion, probabilidad) "
                "VALUES (?, 'mision', ?, ?, ?, ?)", (reliquia, nodo, clave, rotacion, prob))


@pytest.fixture()
def datos(con, monkeypatch):
    from farmadex import idiomas

    idiomas.cargar("es")
    monkeypatch.setattr(eficiencia, "ritmo", lambda: "normal")
    braton = _item(con, "/P/BratonPrime", "Braton Prime", "Braton Prime")
    receptor = _item(con, "/P/BratonPrimeReceiver", "Receiver", "Receptor", padre=braton, tipo="Componente")
    ash = _item(con, "/P/AshPrime", "Ash Prime", "Ash Prime", "Warframes")
    sistemas = _item(con, "/P/AshPrimeSystems", "Systems", "Sistemas", "Warframes", padre=ash, tipo="Componente")
    rhino = _item(con, "/P/Rhino", "Rhino", "Rhino", "Warframes")
    lith = _item(con, "RELIQUIA/Lith A5", "Lith A5 Relic", "Reliquia Lith A5", "Relics", vaulted=0, tipo="Relic")
    axi = _item(con, "RELIQUIA/Axi A1", "Axi A1 Relic", "Reliquia Axi A1", "Relics", vaulted=1, tipo="Relic")
    meso = _item(con, "RELIQUIA/Meso M1", "Meso M1 Relic", "Reliquia Meso M1", "Relics", vaulted=0, tipo="Relic")
    _premio(con, lith, receptor, {"Intact": 2.0, "Radiant": 10.0})
    _premio(con, axi, receptor, {"Intact": 11.0, "Radiant": 20.0})
    _premio(con, meso, sistemas, {"Intact": 11.0, "Radiant": 20.0})
    captura = _nodo(con, "Earth/Captura", "Captura", "Earth", "Capture")
    superv = _nodo(con, "Earth/Superv", "Superv", "Earth", "Survival")
    _cae(con, lith, captura, "Earth/Captura", 10.0)
    _cae(con, meso, superv, "Earth/Superv", 30.0, "C")
    fossa = _nodo(con, "Venus/Fossa", "Fossa", "Venus", "Assassination")
    con.execute("INSERT INTO fuentes (item_id, tipo, origen_id, origen_texto, probabilidad) "
                "VALUES (?, 'mision', ?, 'Venus/Fossa', 38.0)", (rhino, fossa))
    con.commit()
    return {"con": con, "receptor": receptor, "sistemas": sistemas, "lith": lith, "axi": axi, "meso": meso,
            "rhino": rhino}


def _fisura(era, nodo, modo, minutos=40, acero=False, tormenta=False):
    return Fisura(era, nodo, modo, "Grineer", AHORA + timedelta(minutes=minutos), acero, tormenta, modo, "Grineer")


def _metas(*pares):
    return [que_hago.Meta(u, n) for u, n in pares]


RECEPTOR = ("/P/BratonPrimeReceiver", "Receptor de Braton Prime")
SISTEMAS = ("/P/AshPrimeSystems", "Sistemas de Ash Prime")


def _recomendar(datos, metas, fisuras, tienes=None, escuadra=1, **kw):
    return que_hago.recomendar(datos["con"], metas, tienes or {}, fisuras, AHORA, "Radiant", escuadra, "normal", **kw)


def test_minutos_de_fisura_por_tipo_de_mision(monkeypatch):
    # Captura: la mision (1) + reactivo (1) + carga (1.5) = lo mismo que eficiencia.FISURA.
    assert que_hago.minutos_fisura_de("Capture", "normal") == pytest.approx(eficiencia.FISURA)
    # Supervivencia: una rotacion (5) + entrar y salir (3) + carga (1.5).
    assert que_hago.minutos_fisura_de("Survival", "normal") == pytest.approx(9.5)
    # Espionaje: la mision entera (8) + reactivo + carga.
    assert que_hago.minutos_fisura_de("Spy", "normal") == pytest.approx(10.5)
    assert que_hago.minutos_fisura_de("Capture", "rapido") == pytest.approx(eficiencia.FISURA * 0.7)


def test_recomienda_la_reliquia_de_tu_meta_en_la_fisura_abierta(datos):
    r = _recomendar(datos, _metas(RECEPTOR), [_fisura("Lith", "Hepit, Vacio", "Capture")])
    assert r.estado == que_hago.OK
    c = r.consejos[0]
    assert c.reliquia == "Lith A5" and c.reliquia_id == datos["lith"]
    assert [p.nombre for p in c.piezas] == ["Receptor de Braton Prime"]
    assert c.probabilidad == 10.0 and c.tienes is None
    # No la tienes (no se sabe): conseguirla cuesta (1 + 1.5) / 10 % = 25 min en la Captura.
    assert c.minutos_reliquia == pytest.approx(25.0)
    assert c.sitio_reliquia["donde"].startswith("Captura")
    # (3.5 de fisura + 25 de reliquia) / 10 % de pieza en solitario.
    assert c.minutos == pytest.approx((3.5 + 25.0) / 0.10, rel=1e-3)


def test_la_reliquia_que_tienes_no_cuesta_farmearla_y_la_de_boveda_solo_si_la_tienes(datos):
    fisuras = [_fisura("Axi", "Xini", "Interception")]
    # Axi A1 esta en boveda: sin tenerla no hay consejo, y la alternativa lo dice.
    r = _recomendar(datos, _metas(RECEPTOR), fisuras)
    assert r.estado == que_hago.SIN_FISURA and not r.consejos
    assert r.alternativa and r.alternativa["reliquia"]["reliquia_id"] == datos["lith"]
    # Con dos leidas en el inventario, si: (8 min de Intercepcion) / 20 %.
    r = _recomendar(datos, _metas(RECEPTOR), fisuras, tienes={"RELIQUIA/Axi A1": 2})
    c = r.consejos[0]
    assert c.reliquia == "Axi A1" and c.tienes == 2 and c.minutos_reliquia is None
    assert c.minutos == pytest.approx(que_hago.minutos_fisura_de("Interception", "normal") / 0.20, rel=1e-3)


def test_omnia_vale_para_todas_las_eras_y_se_ordena_por_tiempo_hasta_la_pieza(datos):
    fisuras = [_fisura("Lith", "Hepit", "Capture"), _fisura("Omnia", "Omnia", "Capture"),
               _fisura("Meso", "Io", "Survival")]
    r = _recomendar(datos, _metas(RECEPTOR, SISTEMAS), fisuras)
    assert r.estado == que_hago.OK
    minutos = [c.minutos for c in r.consejos]
    assert minutos == sorted(minutos)
    # Una fila por reliquia: la Omnia vale para las dos, y se cuenta como fisura de mas.
    reliquias = [c.reliquia for c in r.consejos]
    assert sorted(reliquias) == ["Lith A5", "Meso M1"]
    assert sum(c.otras_fisuras for c in r.consejos) == 1


def test_fisura_que_se_cierra_antes_de_terminarla_no_cuenta(datos):
    r = _recomendar(datos, _metas(RECEPTOR), [_fisura("Lith", "Hepit", "Capture", minutos=2)])
    assert r.estado == que_hago.SIN_FISURA
    r = _recomendar(datos, _metas(RECEPTOR), [_fisura("Lith", "Hepit", "Capture", minutos=-1)])
    assert r.estado == que_hago.SIN_FISURA


def test_camino_de_acero_va_detras_si_no_consta_que_lo_tienes(datos):
    fisuras = [_fisura("Lith", "Normal", "Survival"), _fisura("Lith", "Acero", "Capture", acero=True)]
    metas = _metas(RECEPTOR)
    r = _recomendar(datos, metas, fisuras)
    assert r.consejos[0].fisura.nodo == "Normal" and r.consejos[0].otras_fisuras == 1
    r = _recomendar(datos, metas, fisuras, acero=True)
    assert r.consejos[0].fisura.nodo == "Acero"  # la Captura es mas rapida


def test_escuadra_de_cuatro_sube_la_probabilidad_por_fisura(datos):
    r = _recomendar(datos, _metas(RECEPTOR), [_fisura("Lith", "Hepit", "Capture")], escuadra=4)
    assert r.consejos[0].por_fisura == pytest.approx(ruta_prime.probabilidad_por_fisura(10.0, 4))


def test_estados_sin_consejo(datos):
    assert _recomendar(datos, [], [_fisura("Lith", "Hepit", "Capture")]).estado == que_hago.SIN_METAS
    assert que_hago.recomendar(None, _metas(RECEPTOR), {}, []).estado == que_hago.SIN_INDICE
    # Sin saber el mundo: se dice, con la mejor ruta real para mientras tanto.
    r = _recomendar(datos, _metas(RECEPTOR), None)
    assert r.estado == que_hago.SIN_MUNDO and r.alternativa["reliquia"]["reliquia_id"] == datos["lith"]
    # Rhino no sale de reliquias: ninguna fisura sirve, y la alternativa es su mision.
    r = _recomendar(datos, _metas(("/P/Rhino", "Rhino")), [_fisura("Lith", "Hepit", "Capture")])
    assert r.estado == que_hago.SIN_RELIQUIAS and r.meta_alternativa == "Rhino"
    assert "Fossa" in r.alternativa["mision"]["donde"]
    # Solo en boveda y sin tenerla: se dice, no se inventa donde farmearla.
    datos["con"].execute("UPDATE items SET vaulted = 1 WHERE id = ?", (datos["lith"],))
    r = _recomendar(datos, _metas(RECEPTOR), [_fisura("Lith", "Hepit", "Capture")])
    assert r.estado == que_hago.SOLO_BOVEDA and not r.consejos


def test_firma_de_fisuras():
    a = [_fisura("Lith", "Hepit", "Capture")]
    assert que_hago.firma_fisuras(a) == que_hago.firma_fisuras(list(a))
    assert que_hago.firma_fisuras(a) != que_hago.firma_fisuras([])
    assert que_hago.firma_fisuras(None) != que_hago.firma_fisuras([])


def test_leer_usuario_metas_e_inventario(tmp_path):
    from farmadex.estado import inventario, objetivos, usuario_db

    usuario = usuario_db.conectar(tmp_path / "u.sqlite")
    objetivos.anadir(usuario, "/P/BratonPrimeReceiver", "Receptor de Braton Prime", 1)
    hecho = objetivos.anadir(usuario, "/P/AshPrimeSystems", "Sistemas", 1)
    objetivos.completar(usuario, hecho)
    inventario.preparar(usuario)
    inventario.guardar(usuario, [inventario.Lectura("RELIQUIA/Lith A5", 3), inventario.Lectura("/P/Forma", 9)])
    metas, tienes, acero = que_hago.leer_usuario(usuario)
    assert [m.unique_name for m in metas] == ["/P/BratonPrimeReceiver"]
    assert tienes == {"RELIQUIA/Lith A5": 3}
    assert acero is False


# -- interfaz ----------------------------------------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_panel_pinta_el_consejo_y_abre_la_ficha(app, datos, tmp_path, monkeypatch):
    from farmadex import idiomas
    from farmadex.estado import objetivos, usuario_db
    from farmadex.ui import que_hago as ui

    idiomas.cargar("es")
    monkeypatch.setattr(ruta_prime, "preferencias", lambda: ("Radiant", 1))
    monkeypatch.setattr(que_hago, "datetime", type("F", (), {"now": staticmethod(lambda tz=None: AHORA)}))
    monkeypatch.setattr(ui, "_ahora", lambda: AHORA)
    usuario = usuario_db.conectar(tmp_path / "u.sqlite")
    objetivos.anadir(usuario, "/P/BratonPrimeReceiver", "Receptor de Braton Prime", 1)
    panel = ui.PanelQueHago()
    panel.conectar(datos["con"], usuario)
    mundo = type("M", (), {"fisuras": [_fisura("Lith", "Hepit, Vacio", "Capture")]})()
    panel.actualizar_mundo(mundo)
    panel.recalcular(en_segundo_plano=False)
    texto = panel.texto_plano()
    assert "Abre Lith A5 en la fisura de Hepit, Vacio" in texto
    assert "Receptor de Braton Prime" in texto
    assert "por reliquia" in texto and "si no la tienes, cae en Captura" in texto
    abiertos = []
    panel.abrir_item.connect(abiertos.append)
    panel._enlace(f"item:{datos['lith']}")
    assert abiertos == [datos["lith"]]
    # Otras fisuras: la firma cambia y se pide recalcular.
    panel._sucio = False
    panel.actualizar_mundo(type("M", (), {"fisuras": []})())
    assert panel._sucio
    panel.recalcular(en_segundo_plano=False)
    assert "Ninguna fisura abierta te sirve ahora" in panel.texto_plano()
    assert "farmea Lith A5 en Captura" in panel.texto_plano()


def test_panel_sin_metas_lo_dice(app, datos, tmp_path):
    from farmadex import idiomas
    from farmadex.estado import usuario_db
    from farmadex.ui import que_hago as ui

    idiomas.cargar("es")
    panel = ui.PanelQueHago()
    panel.conectar(datos["con"], usuario_db.conectar(tmp_path / "u.sqlite"))
    panel.actualizar_mundo(type("M", (), {"fisuras": []})())
    panel.recalcular(en_segundo_plano=False)
    assert "Todavía no tienes metas" in panel.texto_plano()


def test_fuera_del_castellano_la_pieza_va_con_el_nombre_del_indice(datos):
    from farmadex import idiomas

    idiomas.cargar("en")
    try:
        r = _recomendar(datos, _metas(RECEPTOR), [_fisura("Lith", "Hepit", "Capture")])
        assert [p.nombre for p in r.consejos[0].piezas] == ["Braton Prime Receiver"]
    finally:
        idiomas.cargar("es")
