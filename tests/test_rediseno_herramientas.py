"""Rediseno C, zona HERRAMIENTAS / AJUSTES / bienvenida / guia: piezas nuevas y textos."""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def config_temporal(tmp_path, monkeypatch):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    yield config
    idiomas.cargar("es")
    from farmadex.ui import widgets

    widgets.ESCALA.update({"interfaz": 1.0, "letra": 1.0})
    widgets.elegir_tema(widgets.TEMA_POR_DEFECTO, None)


@pytest.fixture()
def ajustes(app, config_temporal):
    from farmadex.ui.pestana_ajustes import PestanaAjustes

    return PestanaAjustes()


@pytest.fixture()
def ventana(app, tmp_path, monkeypatch, config_temporal):
    from farmadex import tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db

    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    from farmadex.ui.overlay import VentanaOverlay

    v = VentanaOverlay()
    v.resize(1180, 760)
    v.show()
    yield v
    v.hide()


# -- el menu en ingles: "Tablero" con clave propia -------------------------------------------

def test_una_clave_con_contexto_se_traduce_aparte():
    try:
        assert idiomas.t("Tablero||menu") == "Tablero"  # castellano: el texto sin el contexto
        idiomas.cargar("en")
        assert idiomas.t("Tablero||menu") == "Home"
        assert idiomas.t("Tablero") == "Board"  # la otra "Tablero" (Mundo) no cambia
        idiomas.cargar("fr")
        assert idiomas.t("Tablero||menu") == "Accueil"
    finally:
        idiomas.cargar("es")


def test_el_menu_superior_dice_home_en_ingles(ventana):
    assert ventana.menu.entrada("tablero").text() == "Tablero"
    try:
        idiomas.cargar("en")
        ventana.cambiar_idioma("en")
        assert ventana.menu.entrada("tablero").text() == "Home"
    finally:
        idiomas.cargar("es")
        ventana.cambiar_idioma("es")


@pytest.mark.parametrize("codigo", ["en", "fr", "de", "pt"])
def test_los_titulares_del_veredicto_estan_traducidos(codigo):
    from farmadex.ui.pestana_agrietados import TITULARES

    catalogo = json.loads((idiomas.dir_catalogos() / f"{codigo}.json").read_text(encoding="utf-8"))
    for _desde, texto in TITULARES:
        assert texto in catalogo, texto


# -- Ajustes ----------------------------------------------------------------------------------

def test_la_columna_de_secciones_imita_una_lista(ajustes):
    from farmadex.ui.pestana_ajustes import SECCIONES

    cambios = []
    ajustes.secciones.currentRowChanged.connect(cambios.append)
    assert [ajustes.secciones.item(i).text() for i in range(ajustes.secciones.count())] == [t for _c, t in SECCIONES]
    ajustes.secciones.item(2).click()
    assert cambios == [2] and ajustes.seccion_actual() == "aspecto"
    ajustes.secciones.setCurrentRow(2)  # la misma: no vuelve a avisar
    assert cambios == [2]
    # Acerca de, Salir y los creditos, al pie de la columna.
    assert ajustes.boton_acerca.parentWidget() is ajustes.panel_secciones
    assert ajustes.boton_salir.parentWidget() is ajustes.panel_secciones
    salidas = []
    ajustes.salir.connect(lambda: salidas.append(1))
    ajustes.boton_salir.click()
    assert salidas == [1]


def test_los_selectores_de_tamano_y_tema_hablan_como_un_desplegable(ajustes):
    selector = ajustes.escala_letra
    avisos = []
    selector.currentIndexChanged.connect(avisos.append)
    i = selector.findData(1.3)
    assert i >= 0 and selector.itemText(i) == "Muy grande"
    selector.boton(i).click()
    assert avisos == [i] and selector.currentData() == 1.3 and selector.boton(i).isChecked()
    selector.blockSignals(True)
    selector.setCurrentIndex(0)
    selector.blockSignals(False)
    assert avisos == [i] and selector.currentIndex() == 0
    assert ajustes.hay_cambios_aspecto()
    # Una tarjeta por tema; pulsarla cambia el tema al momento.
    temas = []
    ajustes.tema_cambiado.connect(temas.append)
    j = ajustes.tema.findData("cherry")
    ajustes.tema.boton(j).click()
    assert temas == ["cherry"] and ajustes.tema.currentData() == "cherry"


def test_la_opacidad_ensena_su_valor(ajustes):
    ajustes.opacidad.setValue(80)
    assert ajustes.valor_opacidad.text() == "80 %"


def test_la_muestra_guarda_el_color_y_la_flecha_lo_devuelve(ajustes):
    ajustes._poner_color("ok", "#123456")
    assert ajustes.muestras["ok"].text() == "#123456" and ajustes.muestras["ok"].personal
    assert ajustes.deshacer_color["ok"].isEnabled()
    ajustes.deshacer_color["ok"].click()
    assert not ajustes.muestras["ok"].personal and not ajustes.deshacer_color["ok"].isEnabled()


def test_la_vista_previa_pinta_con_lo_pendiente_sin_tocar_la_paleta_activa(ajustes):
    from farmadex.ui import widgets

    activa = widgets.PALETA
    antes = dict(activa)
    ajustes._poner_color("acento", "#00ff00")
    assert ajustes.vista_previa.paleta["acento"] == "#00ff00"
    ajustes.vista_previa.marco.grab()  # pinta las piezas con la paleta pendiente
    assert widgets.PALETA is activa and dict(widgets.PALETA) == antes


def test_avanzado_admite_filas_nuevas(ajustes):
    from PySide6.QtWidgets import QLabel, QPushButton

    filas = ajustes.capa_avanzado.rowCount()
    boton, nota = QPushButton("x"), QLabel("lo que hace")
    ajustes.anadir_avanzado(boton, nota, QLabel("Etiqueta"))
    assert ajustes.capa_avanzado.rowCount() == filas + 1
    ajustes.ir_a("datos")
    ajustes.boton_avanzado.click()
    assert boton.isVisibleTo(ajustes) and nota.isVisibleTo(ajustes)


def test_el_selector_de_ocr_sigue_en_avanzado(ajustes):
    ajustes.ir_a("datos")
    ajustes.boton_avanzado.click()
    assert ajustes.ocr_modo.isVisibleTo(ajustes)
    modos = []
    ajustes.ocr_modo_cambiado.connect(modos.append)
    ajustes.ocr_modo.setCurrentIndex(ajustes.ocr_modo.findData("ligero"))
    assert modos == ["ligero"] and ajustes.config["ocr_modo"] == "ligero"


# -- bienvenida -------------------------------------------------------------------------------

def test_la_bienvenida_va_por_pasos_numerados_y_avisa_de_como_empezar(ventana):
    ventana.mostrar_bienvenida(obligatoria=True)
    capa = ventana._bienvenida
    assert capa.contador.text() == "1 DE 5"
    assert not capa.caja_empezar.isVisibleTo(capa)
    capa.boton_siguiente.click()
    # En "Lo basico": el aviso de que al final se elige, pero todavia sin los botones.
    assert capa.caja_empezar.isVisibleTo(capa) and capa.nota_empezar.isVisibleTo(capa)
    assert not capa.boton_guia.isVisibleTo(capa) and not capa.boton_empezar.isVisibleTo(capa)
    pasos = " ".join(e.text() for e in capa.textos)
    assert ventana.config.get("hotkey_overlay", "Ctrl+Alt+W").upper() in pasos
    assert "Ventana sin bordes" in pasos
    # Siempre como HTML: si no, los &quot; que deja frase() se verian tal cual.
    from PySide6.QtCore import Qt

    assert all(e.textFormat() == Qt.RichText for e in capa.textos if "<" in e.text())
    assert sum("<span>" in e.text() for e in capa.textos) >= 7  # los pasos sin etiquetas propias
    # Los apartados vistos quedan con el rombo lleno.
    assert capa.entradas[0].visto and capa.entradas[1].visto and not capa.entradas[2].visto
    capa._ir_a(capa.paginas.count() - 1)
    assert capa.boton_guia.isVisibleTo(capa) and capa.boton_guia.principal
    capa.terminar(False)


# -- guia -------------------------------------------------------------------------------------

def test_la_guia_usa_la_burbuja_c_y_resalta_el_boton_con_su_atajo(ventana):
    from PySide6.QtCore import QPoint, QRect

    from farmadex.ui.estilo_c import PanelC

    ventana.mostrar_guia()
    guia = ventana._guia
    assert isinstance(guia.burbuja, PanelC)
    titulos = [p.titulo for p in guia._pasos]
    for titulo, pagina in (("Build", ventana.builds), ("Agrietados", ventana.agrietados)):
        guia._ir_a_paso(titulos.index(titulo))
        tecla = pagina.tecla_atajo
        assert tecla.isVisible()
        rect = QRect(tecla.mapTo(ventana, QPoint(0, 0)), tecla.size())
        assert guia._rect_resalte.contains(rect), titulo
    avisos = guia._pasos[titulos.index("Avisos del mundo")].cuerpo
    assert "Facciones" in avisos and "filtras por faccion" not in avisos
    guia.terminar()


def test_el_menu_de_la_guia_dice_tablero_con_la_clave_del_menu(ventana):
    ventana.mostrar_guia()
    guia = ventana._guia
    assert guia._pasos[1].titulo == "Tablero"
    guia.terminar()
