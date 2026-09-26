"""MIS METAS en estilo C: la fila "fantasma", los botones del set, "Para esto te sirve hoy"
y los controles de cada pagina a la derecha de las sub-pestanas."""

import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from farmadex.estado import objetivos, usuario_db  # noqa: E402
from farmadex.ui import pestana_objetivos, pestana_tablero  # noqa: E402
from test_objetivos_limites import _magistar  # noqa: E402

AHORA = datetime(2026, 9, 26, 20, 0)


@pytest.fixture()
def pestana(tmp_path, monkeypatch, indice_poblado):
    QApplication.instance() or QApplication([])
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    con, _, _ = indice_poblado
    _magistar(con)
    real = usuario_db.conectar
    monkeypatch.setattr(pestana_objetivos.usuario_db, "conectar", lambda *a, **k: real(tmp_path / "u.sqlite"))
    monkeypatch.setattr(pestana_objetivos, "confirmar", lambda *_a: True)
    monkeypatch.setattr(pestana_tablero, "_ahora", lambda: AHORA)
    p = pestana_objetivos.PestanaObjetivos()
    p.conectar_indice(con)
    yield p
    p.usuario.close()


def _filas(p):
    return [p.caja_filas.itemAt(i).widget() for i in range(p.caja_filas.count())
            if p.caja_filas.itemAt(i).widget() not in (None, p.vacio)]


def test_una_pieza_suelta_lleva_su_set_en_el_nombre(pestana, indice_poblado):
    """La fila "fantasma" de la fase 1: una pieza anadida sola desde la ficha se guarda
    como "Sistemas" y, sin su set, parecia la misma fila que los Sistemas de otro set."""
    con, _, _ = indice_poblado
    sistemas = con.execute("SELECT id FROM items WHERE unique_name LIKE '%AshPrimeSystems%'").fetchone()[0]
    pestana.anadir_item(sistemas)
    [objetivo] = objetivos.listar(pestana.usuario)
    assert objetivo.nombre == "Sistemas" and objetivo.nombre_completo == "Ash Prime: Sistemas"
    [entrada] = objetivos.entradas(pestana.usuario)
    assert entrada.nombre == "Ash Prime: Sistemas"
    assert _filas(pestana)[0].titulo.texto_completo() == "Ash Prime: Sistemas"


def test_refrescar_no_deja_filas_viejas_a_la_vista(pestana):
    for i in range(3):
        objetivos.anadir(pestana.usuario, f"/X{i}", f"X{i}")
    pestana.refrescar()
    pestana.refrescar()  # sin volver al bucle de eventos: lo viejo aun no se ha borrado
    vivas = [w for w in pestana.contenido.findChildren(pestana_objetivos.FilaObjetivo) if w.parent() is pestana.contenido]
    assert len(vivas) == 3


def test_los_botones_del_set_cuentan_piezas(pestana, indice_poblado):
    con, _, _ = indice_poblado
    ash = con.execute("SELECT id FROM items WHERE nombre_en = 'Ash Prime'").fetchone()[0]
    pestana.anadir_item(ash, set_completo=True)
    panel = _filas(pestana)[0]
    assert isinstance(panel, pestana_objetivos.PanelSet) and not panel.menos.isEnabled()
    panel.mas.click()
    assert sum(o.completado for o in objetivos.listar(pestana.usuario)) == 1
    panel = _filas(pestana)[0]
    assert panel.cuenta.text() == "1 / 2" and "1 de 2 piezas" in panel.etiqueta.text()
    panel.menos.click()
    assert sum(o.completado for o in objetivos.listar(pestana.usuario)) == 0
    _filas(pestana)[0].completar.click()
    assert all(o.completado for o in objetivos.listar(pestana.usuario))
    assert pestana.estado == objetivos.COMPLETADOS


def test_la_fila_con_receta_se_abre_con_la_flecha_o_con_un_clic(pestana, indice_poblado):
    con, _, _ = indice_poblado
    mag = con.execute("SELECT id FROM items WHERE unique_name = '/Mag'").fetchone()[0]
    pestana.anadir_item(mag)
    fila = _filas(pestana)[0]
    assert fila.panel_recursos.isHidden()
    fila.panel.pulsado.emit()  # clic en cualquier parte de la fila
    fila = _filas(pestana)[0]
    assert not fila.panel_recursos.isHidden()
    assert "0 DE 3" in fila.rotulo_recursos.texto_completo()


def _paso(unico, nombre, era=None, boveda=False):
    objetivo = objetivos.Objetivo(1, unico, nombre, 1, 0, False)
    ruta = None
    if era:
        ruta = {"tipo": "reliquia", "reliquia": {"nombre_en": f"{era} S19 Relic"}, "solo_en_boveda": boveda,
                "minutos_pieza": 20}
    return pestana_tablero.PasoMeta(objetivo, ruta, {"id": 7, "nombre": nombre, "padre": "", "imagen": None})


def _mundo():
    fisura = SimpleNamespace(era="Lith", acero=False, tormenta=False, expira=AHORA + timedelta(hours=1),
                             mision="Captura", nodo="Hepit")
    acero = SimpleNamespace(era="Neo", acero=True, tormenta=False, expira=AHORA + timedelta(hours=1),
                            mision="Captura", nodo="Ukko")
    forma = SimpleNamespace(unique_name="/Forma", item_id=None, nombre_mostrar="Plano de Forma")
    invasion = SimpleNamespace(nodo="Antea (Saturno)", objetos=[forma])
    return SimpleNamespace(fisuras=[fisura, fisura, acero], invasiones=[invasion], alertas=[], baro_detalle=None)


def test_lineas_de_para_esto_te_sirve_hoy():
    pasos = [_paso("/Sis", "Sistemas de Citrine Prime", "Lith"), _paso("/Cha", "Chasis", "Neo"),
             _paso("/Vieja", "Plano viejo", "Axi", boveda=True), _paso("/Forma", "Forma")]
    lineas = pestana_objetivos.lineas_hoy(_mundo(), pasos, AHORA)
    assert [(x["tipo"], x["detalle"], x["derecha"]) for x in lineas] == [
        ("fisura", "Sistemas de Citrine Prime", "2 abiertas"),  # Neo solo tiene Acero; Axi, en boveda
        ("invasion", "Forma", "Antea (Saturno)"),
    ]
    assert "Antea" in lineas[1]["texto_fila"]
    assert pestana_objetivos.lineas_hoy(None, pasos) == []


def test_la_caja_de_hoy_y_la_fila_ensenan_lo_que_da_el_mundo(pestana):
    objetivos.anadir(pestana.usuario, "/Forma", "Forma", 3)
    pestana.refrescar()
    etiquetas = lambda: " ".join(w.text() for w in pestana.panel_hoy.findChildren(pestana_objetivos.EtiquetaC))  # noqa: E731
    assert "Cargando el estado del mundo" in etiquetas()
    pestana.actualizar_mundo(_mundo())
    assert "Antea (Saturno)" in etiquetas()
    pestana.refrescar()  # las filas cogen el mundo al rehacerse
    fila = _filas(pestana)[0]
    assert fila.hoy is not None and "Antea" in fila.hoy.text()


def test_leer_inventario_enciende_la_misma_opcion_de_ajustes(pestana):
    from farmadex import config

    pestana.boton_inventario.click()
    assert config.cargar()["inventario_pasivo"] is True and pestana.aviso.isVisibleTo(pestana)
    pestana.boton_inventario.click()
    assert config.cargar()["inventario_pasivo"] is False


def test_estados_hablan_como_la_barra_de_pestanas(pestana):
    cambios = []
    pestana.estados.currentChanged.connect(cambios.append)
    pestana.estados.setCurrentIndex(2)
    assert cambios == [2] and pestana.estado == objetivos.COMPLETADOS
    pestana.estados.boton(0).click()
    assert pestana.estado == objetivos.SIN_EMPEZAR


def test_los_controles_de_cada_pagina_van_junto_a_las_sub_pestanas():
    QApplication.instance() or QApplication([])
    from farmadex.ui.overlay import SeccionConSub

    paginas = {}
    for clave in ("a", "b", "c"):
        pagina = QWidget()
        if clave != "c":
            pagina.controles_cabecera = QWidget(pagina)
        paginas[clave] = pagina
    seccion = SeccionConSub([("a", "A"), ("b", "B"), ("c", "C")], paginas)
    derecha = seccion.subpestanas.derecha
    assert derecha.indexOf(paginas["a"].controles_cabecera) >= 0
    seccion.mostrar("b")
    assert not paginas["a"].controles_cabecera.isVisibleTo(seccion)
    assert paginas["b"].controles_cabecera.isVisibleTo(seccion)
    seccion.mostrar("c")
    assert not paginas["b"].controles_cabecera.isVisibleTo(seccion)
