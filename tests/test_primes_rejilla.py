"""Pestana Primes: genericos aparte, cuadricula regular, orden de los sets y la casilla
de boveda que no se deja lanzar dos veces."""

from __future__ import annotations

import os

import pytest
from test_ruta_prime import _item, _premio, prime  # noqa: F401 - fixture del indice sintetico

from farmadex.estado import objetivos as estado_objetivos
from farmadex.estado import usuario_db

# Nada de ventanas visibles: el usuario juega mientras se pasan las pruebas.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def entorno(app, con, prime, tmp_path, monkeypatch):  # noqa: F811
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    # Un Adaptador Exilus y otro set, para ver los genericos y el orden.
    exilus = _item(con, "/E/ExilusAdapter", "Exilus Weapon Adapter", "Adaptador Exilus de arma", "Misc")
    plano_exilus = _item(con, "/E/ExilusAdapterBlueprint", "Blueprint", "Plano", padre=exilus, tipo="Componente")
    kuva = _item(con, "/K/Kuva", "Kuva", "Kuva", categoria="Resources")
    braton = _item(con, "/P/BratonPrime", "Braton Prime", "Braton Prime")
    cano = _item(con, "/P/BratonPrimeBarrel", "Barrel", "Canon", padre=braton, tipo="Componente")
    culata = _item(con, "/P/BratonPrimeStock", "Stock", "Culata", padre=braton, tipo="Componente")
    for pieza in (plano_exilus, kuva, cano, culata):
        _premio(con, prime["lith"], pieza, {"Intact": 11.0, "Radiant": 10.0})
    con.commit()
    usuario = usuario_db.conectar(tmp_path / "usuario.sqlite")
    return con, prime, usuario


def _pestana(con, usuario):
    from farmadex.ui.pestana_primes import PestanaPrimes

    pestana = PestanaPrimes(usuario=usuario)
    pestana.conectar_indice(con)
    return pestana


def _titulos(pestana) -> list[str]:
    return [c._titulo for c in pestana._orden_sets()]


def test_forma_y_exilus_van_en_su_categoria_al_final(entorno):
    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    assert [c._titulo for c in pestana._cajas_sets] == ["Braton Prime", "Caliban Prime"]
    formas, otros = pestana._cajas_genericas
    assert formas._titulo == "Formas y Adaptadores Exilus"
    assert [p["nombre_en"] for p in formas.piezas] == ["Forma", "Blueprint"]
    # "Plano" solo no dice nada: lleva delante su objeto.
    assert formas.casillas["/E/ExilusAdapterBlueprint"].text() == "Adaptador Exilus de arma: Plano"
    assert otros._titulo == "Otros objetos de reliquia" and [p["nombre_en"] for p in otros.piezas] == ["Kuva"]
    # En la rejilla: cabecera de sets, sets, cabecera de genericos, genericos.
    widgets = [pestana.fluida.itemAt(i).widget() for i in range(pestana.fluida.count())]
    assert widgets[0] is pestana._cabeceras["sets"] and widgets[3] is pestana._cabeceras["genericos"]
    assert widgets[4:] == [formas, otros]
    # Marcar un generico sigue creando su objetivo.
    formas.casillas["/E/ExilusAdapterBlueprint"].setChecked(True)
    assert [o.unique_name for o in estado_objetivos.listar(usuario)] == ["/E/ExilusAdapterBlueprint"]


def test_el_filtro_esconde_la_cabecera_sin_cajas(entorno):
    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    pestana.filtro.setText("kuva")
    assert pestana._cabeceras["sets"].isHidden()
    assert not pestana._cabeceras["genericos"].isHidden()


def test_todas_las_cajas_miden_lo_mismo(entorno):
    from farmadex.ui.pestana_primes import ANCHO_CAJA_MAX, ANCHO_CAJA_MIN

    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    assert ANCHO_CAJA_MIN <= pestana.fluida.ancho_min <= ANCHO_CAJA_MAX
    pestana.resize(900, 600)
    pestana.show()
    pestana.contenido.resize(880, 2000)
    pestana.fluida.setGeometry(pestana.contenido.rect())
    anchos = {c.width() for c in pestana._cajas_sets} | {pestana._cajas_genericas[0].width()}
    assert len(anchos) == 1
    # "Otros objetos de reliquia" ocupa la fila entera en vez de ensanchar las demas.
    assert pestana._cajas_genericas[1].width() > anchos.pop()
    pestana.hide()


def test_ordenar_por_marcados_busqueda_y_conseguidos(entorno):
    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    assert _titulos(pestana) == ["Braton Prime", "Caliban Prime"]
    caliban = next(c for c in pestana._cajas_sets if c._titulo == "Caliban Prime")
    caliban.casillas["/P/CalibanPrimeBlueprint"].setChecked(True)
    pestana.orden.setCurrentIndex(pestana.orden.findData("marcados"))
    assert _titulos(pestana) == ["Caliban Prime", "Braton Prime"]
    # Se recuerda.
    from farmadex import config

    assert config.cargar()["primes_orden"] == "marcados"
    # Mas piezas en busqueda: Braton con dos marcadas pasa delante; una completada no cuenta.
    braton = next(c for c in pestana._cajas_sets if c._titulo == "Braton Prime")
    braton.casillas["/P/BratonPrimeBarrel"].setChecked(True)
    braton.casillas["/P/BratonPrimeStock"].setChecked(True)
    pestana.orden.setCurrentIndex(pestana.orden.findData("buscadas"))
    assert _titulos(pestana) == ["Braton Prime", "Caliban Prime"]
    for objetivo in estado_objetivos.listar(usuario):
        if objetivo.unique_name.startswith("/P/Braton"):
            estado_objetivos.sumar(usuario, objetivo.id, 1)
    assert _titulos(pestana) == ["Caliban Prime", "Braton Prime"]
    # Recien conseguidos: lo completado, primero.
    pestana.orden.setCurrentIndex(pestana.orden.findData("conseguidos"))
    assert _titulos(pestana) == ["Braton Prime", "Caliban Prime"]


def test_mas_recientes_con_y_sin_fechas_en_el_indice(entorno):
    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    pestana.orden.setCurrentIndex(pestana.orden.findData("recientes"))
    columnas = [f[1] for f in con.execute("PRAGMA table_info(items)")]
    if "fecha_salida" not in columnas:
        # Indice viejo: sin fechas, por nombre y sin fallar.
        assert _titulos(pestana) == ["Braton Prime", "Caliban Prime"]
        con.execute("ALTER TABLE items ADD COLUMN fecha_salida TEXT")
    con.execute("UPDATE items SET fecha_salida = '2026-09-23' WHERE unique_name = '/P/CalibanPrime'")
    con.execute("UPDATE items SET fecha_salida = '2017-01-01' WHERE unique_name = '/P/BratonPrime'")
    con.commit()
    pestana._fechas = None
    assert _titulos(pestana) == ["Caliban Prime", "Braton Prime"]


def test_la_casilla_de_boveda_no_se_lanza_dos_veces(entorno, monkeypatch):
    con, prime, usuario = entorno
    pestana = _pestana(con, usuario)
    llamadas = []
    original = pestana._construir_rejilla

    def construir():
        llamadas.append(pestana.incluir_boveda.isEnabled())
        # Un clic mas mientras carga (el usuario impaciente): no debe relanzar nada.
        pestana._cambiar_boveda(False)
        original()

    monkeypatch.setattr(pestana, "_construir_rejilla", construir)
    pestana.incluir_boveda.setChecked(True)
    assert llamadas == [False]  # se construye una vez, con la casilla desactivada
    assert not pestana.incluir_boveda.isEnabled()
    assert pestana.incluir_boveda.text() == "Cargando, espera..."
    pestana._boveda_lista()
    assert pestana.incluir_boveda.isEnabled()
    assert pestana.incluir_boveda.text() == "Incluir lo que esta en boveda"
    assert any(c.objeto and c.objeto["nombre_en"] == "Ash Prime" for c in pestana._cajas)
