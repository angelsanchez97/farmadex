"""Colores por tipo en los resultados, ficha con estadisticas y vista compacta desplegable."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from farmadex.datos import detalles  # noqa: E402


@pytest.fixture()
def aplicacion():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def con_detalles(indice_poblado):
    """El indice de prueba con un mod, un arma y un glifo con sus detalles."""
    con, _, _ = indice_poblado
    filas = (
        (901, "/Mods/Serration", "Serration", "Sierra", "Mods",
         {"mod": {"efecto": {"en": ["+15% Damage", "+165% Damage"], "es": ["+15% de daño", "+165% de daño"]},
                  "polaridad": "madurai", "drenaje": 4, "rango_max": 1, "compat": "Rifle"}}),
        (902, "/Weapons/Braton", "Braton", "Braton", "Primary",
         {"arma": {"critico": 0.12, "mult_critico": 2.0, "estado": 0.26, "cargador": 100.0, "disposicion": 4.0,
                   "riven": 1.25, "dano": {"slash": 21.0}}}),
        (903, "/Glyphs/Teshin", "Teshin Glyph", "Glifo de Teshin", "Glyphs", {"glifo": {"codigo": "WARWITHIN"}}),
    )
    for iid, unico, en, es, categoria, datos in filas:
        con.execute("INSERT INTO items (id, unique_name, nombre_en, nombre_es, categoria) VALUES (?, ?, ?, ?, ?)",
                    (iid, unico, en, es, categoria))
        detalles.guardar(con, iid, datos)
    con.commit()
    from farmadex.datos import indice

    indice.poblar_busqueda(con)
    return con


@pytest.fixture()
def buscador(con_detalles, monkeypatch, aplicacion):
    from farmadex import idiomas
    from farmadex.datos import indice as modulo_indice
    from farmadex.ui.pestana_buscador import PestanaBuscador

    idiomas.cargar("es")
    monkeypatch.setattr(modulo_indice, "conectar", lambda *a, **k: con_detalles)
    pestana = PestanaBuscador()
    pestana.habilitar(True)
    return pestana


# -- colores ------------------------------------------------------------------------------


def test_cada_categoria_tiene_su_tipo_y_las_piezas_el_de_su_padre():
    from farmadex.ui import colores_tipo

    assert colores_tipo.tipo_de({"categoria": "Resources"}) == "recurso"
    assert colores_tipo.tipo_de({"categoria": "Warframes", "tipo": "Componente"}) == "warframe"
    assert colores_tipo.tipo_de({"categoria": "Melee"}) == "arma"
    assert colores_tipo.tipo_de({"clave": "nodo:3", "categoria": None}) == "mision"
    assert colores_tipo.tipo_de({"categoria": "Loquesea"}) == "otro"


@pytest.mark.parametrize("fondo", ["#171d26", "#ffffff", "#f4f5f7", "#26221a"])
def test_los_colores_se_leen_en_temas_claros_y_oscuros(aplicacion, fondo):
    from PySide6.QtGui import QColor

    from farmadex.ui import colores_tipo

    for clave in colores_tipo.TIPOS:
        color = colores_tipo.color(clave, fondo)
        assert colores_tipo.contraste(QColor(color), QColor(fondo)) >= colores_tipo.CONTRASTE_MINIMO, (clave, fondo)


def test_la_leyenda_solo_trae_los_tipos_de_la_lista(aplicacion):
    from farmadex.ui import colores_tipo

    texto = colores_tipo.leyenda_html(iter(["mod", "recurso", "mod"]))
    assert "Mod" in texto and "Recurso" in texto and "Warframe" not in texto
    assert texto.index("Mod") < texto.index("Recurso")
    assert colores_tipo.leyenda_html([]) == ""


def test_la_lista_del_buscador_lleva_tipo_y_leyenda(buscador):
    from farmadex.ui.pestana_buscador import ROL_TIPO

    buscador.caja.setText("sierra")
    buscador._buscar()
    assert buscador.lista.item(0).data(ROL_TIPO) == "mod"
    assert not buscador.leyenda.isHidden() and "Mod" in buscador.leyenda.text()
    buscador.caja.setText("")
    buscador._buscar()
    assert buscador.leyenda.isHidden()


# -- ficha ----------------------------------------------------------------------------------


def test_ficha_de_mod_con_efecto_por_rango(buscador):
    buscador.abrir(901)
    texto = buscador.ficha.toPlainText()
    assert "+165% de daño" in texto and "Rango 0" in texto and "Madurai" in texto


def test_ficha_de_arma_con_disposicion_de_riven(buscador):
    buscador.abrir(902)
    texto = buscador.ficha.toPlainText()
    assert "12% ×2" in texto and "●●●●○" in texto and "×1.25" in texto
    assert "100" in texto  # el cargador de 100 no se queda en "1"


def test_el_codigo_del_glifo_se_copia(buscador):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication

    avisos = []
    buscador.estado.connect(avisos.append)
    buscador.abrir(903)
    assert "WARWITHIN" in buscador.ficha.toPlainText()
    buscador._enlace(QUrl("copiar:WARWITHIN"))
    assert QGuiApplication.clipboard().text() == "WARWITHIN"
    assert any("WARWITHIN" in a for a in avisos)


def test_sin_detalles_la_ficha_sale_como_siempre(buscador):
    from farmadex.ui import ficha_detalles

    assert ficha_detalles.html_detalles(buscador.con, {"id": 1}) == ""
    assert ficha_detalles.html_detalles(None, {"id": 901}) == ""


def test_puntos_de_disposicion():
    from farmadex.ui.ficha_detalles import puntos_disposicion

    assert puntos_disposicion(1) == "●○○○○" and puntos_disposicion(5.0) == "●●●●●"
    assert puntos_disposicion(0) == "" and puntos_disposicion(None) == ""


# -- vista compacta ---------------------------------------------------------------------------


@pytest.fixture()
def compacta(buscador):
    from farmadex.ui.vista_compacta import VistaCompacta

    vista = VistaCompacta(buscador)
    vista.resize(560, 420)
    vista.show()
    return vista


def test_la_compacta_despliega_el_resultado_debajo_y_se_cierra_al_pulsar_otra_vez(compacta):
    compacta.caja.setText("sierra")
    compacta._buscar("sierra")
    lista = compacta.lista
    assert lista.isVisibleTo(compacta) and not compacta.resumen.isVisibleTo(compacta)
    assert lista.abierta == 0
    detalle = lista._filas[0].detalle
    assert detalle.isVisibleTo(compacta) and "+165% de daño" in detalle.text()

    lista._pulsada(0)  # pulsar la abierta la cierra
    assert lista.abierta == -1 and not detalle.isVisibleTo(compacta)
    compacta.repintar()  # y no se vuelve a abrir sola
    assert lista.abierta == -1


def test_la_compacta_abre_otro_resultado_sin_cambiar_de_vista(compacta):
    compacta.caja.setText("ash prime")
    compacta._buscar("ash prime")
    assert len(compacta._resultados) >= 2
    compacta.lista._pulsada(1)
    assert compacta._indice_actual == 1 and compacta.lista.abierta == 1
    assert not compacta.lista._filas[0].detalle.isVisibleTo(compacta)


def test_lo_abierto_desde_fuera_sale_en_el_resumen(compacta):
    compacta.caja.setText("sierra")
    compacta._buscar("sierra")
    compacta.abrir(902)  # el lector del cursor abre algo que no esta en la lista
    assert compacta.resumen.isVisibleTo(compacta) and not compacta.lista.isVisibleTo(compacta)
    assert "Braton" in compacta.resumen.text()


def test_copiar_desde_la_compacta(compacta):
    from PySide6.QtGui import QGuiApplication

    compacta.caja.setText("teshin")
    compacta._buscar("teshin")
    copiados = []
    compacta.lista.copiado.connect(copiados.append)
    fila = compacta.lista._filas[0]
    assert "WARWITHIN" in fila.detalle.text()
    compacta.lista._enlace("copiar:WARWITHIN", fila.detalle)
    assert copiados == ["WARWITHIN"] and QGuiApplication.clipboard().text() == "WARWITHIN"
