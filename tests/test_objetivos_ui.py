"""Pestana Objetivos sin ventanas: paginas, pestanas de estado, confirmaciones y paneles."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from farmadex.estado import objetivos, usuario_db
from farmadex.estado.objetivos import COMPLETADOS, EN_PROGRESO, SIN_EMPEZAR
from farmadex.ui import pestana_objetivos
from test_objetivos_limites import _magistar


@pytest.fixture()
def pestana(tmp_path, monkeypatch, indice_poblado):
    QApplication.instance() or QApplication([])
    con, _, _ = indice_poblado
    _magistar(con)
    real = usuario_db.conectar
    monkeypatch.setattr(pestana_objetivos.usuario_db, "conectar", lambda *a, **k: real(tmp_path / "u.sqlite"))
    preguntas = []
    respuesta = {"si": True}

    def confirmar(_parent, titulo, texto):
        preguntas.append((titulo, texto))
        return respuesta["si"]

    monkeypatch.setattr(pestana_objetivos, "confirmar", confirmar)
    p = pestana_objetivos.PestanaObjetivos()
    p.conectar_indice(con)
    p.preguntas, p.respuesta = preguntas, respuesta
    yield p
    p.usuario.close()


def _filas(p):
    salida = []
    for i in range(p.caja_filas.count()):
        w = p.caja_filas.itemAt(i).widget()
        if w is not None and w is not p.vacio:
            salida.append(w)
    return salida


def _fila_de(p, nombre):
    return next(w for w in _filas(p) if getattr(w, "objetivo", None) and w.objetivo.nombre == nombre)


def test_diez_por_pagina_y_pestanas_de_estado(pestana):
    for i in range(12):
        objetivos.anadir(pestana.usuario, f"/R{i}", f"Recurso {i}", 5)
    hecho = objetivos.anadir(pestana.usuario, "/Hecho", "Hecho", 1)
    objetivos.sumar(pestana.usuario, hecho, 1)
    pestana.refrescar()

    assert pestana.estado == SIN_EMPEZAR
    assert pestana.estados.tabText(0) == "Sin empezar (12)"
    assert pestana.estados.tabText(2) == "Completados (1)"
    assert len(_filas(pestana)) == 10 and pestana.siguiente.isEnabled()
    assert _filas(pestana)[0].objetivo.nombre == "Recurso 11"  # lo ultimo, arriba
    pestana.siguiente.click()
    assert len(_filas(pestana)) == 2 and pestana.texto_pagina.text() == "Pagina 2 de 2"

    pestana.estados.setCurrentIndex(2)
    assert [w.objetivo.nombre for w in _filas(pestana)] == ["Hecho"]
    # Lo completado sigue editable.
    assert _filas(pestana)[0].editar.isEnabled()


def test_sumar_varias_unidades_y_pedir_confirmacion_en_la_meta(pestana):
    oid = objetivos.anadir(pestana.usuario, "/Cryotic", "Criotica", 500)
    pestana.refrescar()
    fila = _fila_de(pestana, "Criotica")
    fila.control.paso.setValue(450)
    fila.control.mas.click()
    assert objetivos.obtener_objetivo(pestana.usuario, oid).actual == 450
    assert pestana.estado == EN_PROGRESO  # la pestana sigue al objetivo, no lo pierde de vista
    fila = _fila_de(pestana, "Criotica")
    assert fila.control.paso.value() == 450  # recuerda cuanto sumas por clic
    fila.control.mas.click()  # se para en 500, no en 900
    assert objetivos.obtener_objetivo(pestana.usuario, oid).actual == 500
    assert pestana.estado == COMPLETADOS

    fila = _fila_de(pestana, "Criotica")
    pestana.respuesta["si"] = False
    fila.control.mas.click()
    assert pestana.preguntas and objetivos.obtener_objetivo(pestana.usuario, oid).objetivo == 500
    pestana.respuesta["si"] = True
    _fila_de(pestana, "Criotica").control.mas.click()
    o = objetivos.obtener_objetivo(pestana.usuario, oid)
    assert (o.objetivo, o.actual) == (950, 950)


def test_quitar_pregunta_antes(pestana):
    objetivos.anadir(pestana.usuario, "/Cryotic", "Criotica", 5)
    pestana.refrescar()
    pestana.respuesta["si"] = False
    _fila_de(pestana, "Criotica").quitar.click()
    assert len(objetivos.listar(pestana.usuario)) == 1 and pestana.preguntas
    pestana.respuesta["si"] = True
    _fila_de(pestana, "Criotica").quitar.click()
    assert objetivos.listar(pestana.usuario) == []


def test_borrar_varios_marcados(pestana):
    for i in range(3):
        objetivos.anadir(pestana.usuario, f"/X{i}", f"X{i}")
    pestana.refrescar()
    assert not pestana.borrar_marcados.isEnabled()
    filas = _filas(pestana)
    filas[0].marcar.setChecked(True)
    filas[1].marcar.setChecked(True)
    assert pestana.borrar_marcados.text() == "Borrar marcados (2)"
    pestana.borrar_marcados.click()
    assert "2 objetivos" in pestana.preguntas[-1][1]
    assert [o.nombre for o in objetivos.listar(pestana.usuario)] == ["X0"]

    pestana.todos.setChecked(True)
    assert pestana.borrar_marcados.isEnabled()


def test_set_como_panel_desplegable(pestana, indice_poblado):
    con, _, _ = indice_poblado
    ash = con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    assert pestana.anadir_item(ash, set_completo=True) == 2
    panel = _filas(pestana)[0]
    assert isinstance(panel, pestana_objetivos.PanelSet)
    assert panel.piezas.isHidden() and not panel.filas
    panel.cabecera.click()
    panel = _filas(pestana)[0]
    assert not panel.piezas.isHidden() and len(panel.filas) == 2
    assert {f.titulo.text().count("Ash Prime") for f in panel.filas} == {0}  # solo "Sistemas"
    panel.filas[0].completar.click()
    assert pestana.estado == EN_PROGRESO
    assert "1 de 2 piezas" in _filas(pestana)[0].etiqueta.text()


def test_arma_con_recursos_uno_a_uno(pestana, indice_poblado):
    con, _, _ = indice_poblado
    mag = con.execute("SELECT id FROM items WHERE unique_name = '/Mag'").fetchone()[0]
    pestana.anadir_item(mag)
    fila = _fila_de(pestana, "Magistar")
    assert fila.boton_recursos is not None and "0 de 3" in fila.boton_recursos.text()
    assert fila.panel_recursos.isHidden()
    fila.boton_recursos.click()
    fila = _fila_de(pestana, "Magistar")
    recursos = fila.panel_recursos.findChildren(pestana_objetivos.FilaRecurso)
    assert len(recursos) == 3
    next(r for r in recursos if r.recurso.unique_name == "/Rubedo").listo.click()
    # Marcar un recurso lo pasa a "en progreso", y la pestana le sigue.
    assert pestana.estado == EN_PROGRESO and pestana.estados.tabText(1) == "En progreso (1)"
    assert "1 de 3" in _fila_de(pestana, "Magistar").boton_recursos.text()
    _fila_de(pestana, "Magistar").completar.click()
    assert pestana.estado == COMPLETADOS
    assert "3 de 3" in _fila_de(pestana, "Magistar").boton_recursos.text()


def test_filtro_por_categoria(pestana, indice_poblado):
    con, _, _ = indice_poblado
    mag = con.execute("SELECT id FROM items WHERE unique_name = '/Mag'").fetchone()[0]
    pestana.anadir_item(mag)
    objetivos.anadir(pestana.usuario, "/Rubedo", "Rubedo", 100, indice=con)
    pestana.refrescar()
    pestana.filtro.setCurrentIndex(pestana.filtro.findData(objetivos.ARMAS))
    assert [w.objetivo.nombre for w in _filas(pestana)] == ["Magistar"]
    pestana.filtro.setCurrentIndex(pestana.filtro.findData(objetivos.RECURSOS))
    assert [w.objetivo.nombre for w in _filas(pestana)] == ["Rubedo"]
    pestana.filtro.setCurrentIndex(pestana.filtro.findData(objetivos.WARFRAMES))
    assert _filas(pestana) == [] and pestana.vacio.isVisibleTo(pestana)


def test_la_rueda_no_cambia_el_numero_sin_clic(pestana):
    objetivos.anadir(pestana.usuario, "/Cryotic", "Criotica", 500)
    pestana.refrescar()
    paso = _fila_de(pestana, "Criotica").control.paso
    evento = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(paso, evento)
    assert paso.value() == 1


def test_dialogo_de_cantidad_con_limites():
    QApplication.instance() or QApplication([])
    dialogo = pestana_objetivos.DialogoCantidad("Criotica", 500, 800, en_inventario=1200)
    assert dialogo.actual.value() == 500 and dialogo.meta.minimum() == 1
    assert dialogo.meta.maximum() == objetivos.MAX_CANTIDAD
    dialogo.meta.setValue(100)
    assert dialogo.actual.maximum() == 100 and dialogo.valores() == (100, 100)
    dialogo.meta.setValue(2000)
    dialogo.usar_inventario.click()
    assert dialogo.valores() == (2000, 1200)
