"""Sistema de diseno C: tema por defecto, colores derivados, hoja global y piezas."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex.ui import estilo_c, widgets  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def tema_por_defecto():
    anterior = dict(widgets.PALETA)
    widgets.elegir_tema(widgets.TEMA_POR_DEFECTO, None)
    yield widgets.PALETA
    widgets.PALETA.clear()
    widgets.PALETA.update(anterior)


def test_el_tema_de_la_maqueta_c_es_el_de_las_instalaciones_nuevas():
    from farmadex import config

    assert widgets.TEMA_POR_DEFECTO == "lua" == config.POR_DEFECTO["tema"]
    assert widgets.TEMAS["lua"]["acento"] == "#d4b06a"
    # Los temas de siempre siguen ahi.
    assert {"vacio", "orokin", "tenno", "cherry"} <= set(widgets.TEMAS)


def test_quien_ya_tenia_un_tema_lo_conserva(tmp_path, monkeypatch):
    import json

    from farmadex import config

    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps({"tema": "orokin"}), encoding="utf-8")
    monkeypatch.setattr(config, "RUTA_CONFIG", ruta)
    assert config.cargar(recargar=True)["tema"] == "orokin"


def test_todos_los_temas_tienen_los_colores_del_estilo_c():
    for nombre in widgets.TEMAS:
        p = widgets.paleta_de(nombre)
        for clave in ("secundario", "tenue", "acento_tenue", "boton"):
            assert widgets.color_valido(p[clave]), (nombre, clave)


def test_el_color_de_apoyo_se_puede_personalizar():
    assert "secundario" in widgets.CLAVES_COLOR
    p = widgets.paleta_de("orokin", {"secundario": "#112233", "acento": "#ff0000"})
    assert p["secundario"] == "#112233"
    # El filete apagado sale del acento personalizado, no del de fabrica.
    assert p["acento_tenue"] != widgets.paleta_de("orokin")["acento_tenue"]


def test_paletas_viejas_sin_secundario_no_rompen_la_hoja():
    viejo = {k: v for k, v in widgets.TEMAS["orokin"].items() if k not in ("secundario", "boton")}
    hoja = widgets.hoja_estilos(viejo, (1.0, 1.0))
    assert 'QLabel[rolC="titulo"]' in hoja


def test_la_hoja_lleva_los_roles_y_escala_su_letra():
    normal = widgets.hoja_estilos(widgets.TEMAS["lua"], (1.0, 1.0))
    grande = widgets.hoja_estilos(widgets.TEMAS["lua"], (1.0, 1.5))
    for rol in estilo_c.ROLES:
        assert f'QLabel[rolC="{rol}"]' in normal
    assert f"font-size: {estilo_c.TAM['portada']}px" in normal
    assert f"font-size: {round(estilo_c.TAM['portada'] * 1.5)}px" in grande
    assert 'QLabel[tinta="secundario"] { color: #58d3c0; }' in normal
    assert '*[transparenteC="true"] { background: transparent; }' in normal


def test_cinco_tamanos_de_letra():
    assert len(estilo_c.TAM) == 5
    assert estilo_c.TAM["portada"] > estilo_c.TAM["titulo"] > estilo_c.TAM["seccion"] > estilo_c.TAM["normal"] > estilo_c.TAM["pequeno"]


def test_etiqueta_en_mayusculas_con_rol_y_tinta(app):
    e = estilo_c.EtiquetaC("Tu siguiente paso", "rotulo", tinta="secundario", mayus=True)
    assert e.text() == "TU SIGUIENTE PASO"
    assert e.property("rolC") == "rotulo" and e.property("tinta") == "secundario"
    # Con HTML no se toca el texto (las etiquetas no se pasan a mayusculas).
    e.setText("<b>hola</b>")
    assert e.text() == "<b>hola</b>"


def test_etiqueta_que_se_recorta_guarda_el_texto_entero(app):
    e = estilo_c.EtiquetaC("Defensa movil · para Sistemas de Citrine Prime", "pequeno", recortar=True)
    e.resize(60, 20)
    e.show()
    QApplication.processEvents()
    assert e.texto_completo() == "Defensa movil · para Sistemas de Citrine Prime"
    assert e.text() != e.texto_completo() and e.text().endswith("…")
    assert e.toolTip() == e.texto_completo()


def test_boton_c_es_un_boton_de_verdad(app, tema_por_defecto):
    b = estilo_c.BotonC("Ver que farmear", principal=True, icono="buscar", pista="Ctrl+M")
    pulsado = []
    b.clicked.connect(lambda: pulsado.append(True))
    b.click()
    assert pulsado == [True]
    ancho = b.sizeHint().width()
    b.poner_solo_icono(True)
    assert b.sizeHint().width() < ancho and b.text() == "Ver que farmear"
    b.grab()  # se pinta sin errores


def test_subpestanas_avisan_y_se_pueden_poner_sin_avisar(app):
    sub = estilo_c.SubPestanasC([("objetivos", "Objetivos"), ("primes", "Primes")])
    avisos = []
    sub.cambiada.connect(avisos.append)
    assert sub.activa() == "objetivos"
    sub.entrada("primes").click()
    assert avisos == ["primes"] and sub.activa() == "primes"
    sub.poner_activa("objetivos")
    assert avisos == ["primes"] and sub.activa() == "objetivos"
    sub.poner_texto("primes", "PRIMES!")
    assert sub.entrada("primes").text() == "PRIMES!"


def test_interruptor_rombos_insignias_y_teclas(app, tema_por_defecto):
    i = estilo_c.Interruptor(False)
    cambios = []
    i.toggled.connect(cambios.append)
    i.click()
    assert cambios == [True] and i.isChecked()
    r = estilo_c.RombosDisposicion(3)
    r.poner(9)
    assert r.n == 5
    insignia = estilo_c.Insignia("Boveda", "aviso")
    assert insignia.text() == "BOVEDA" and widgets.PALETA["aviso"] in insignia.styleSheet()
    assert estilo_c.EtiquetaEra("Lith", por_era=True).styleSheet().count(estilo_c.COLOR_ERA["Lith"]) == 1
    barra = estilo_c.BarraTeclas([("Esc", "Volver"), ("W", "Abrir la wiki")])
    assert barra.textos["Esc"].text() == "VOLVER"
    for pieza in (i, r, insignia, barra, estilo_c.PanelC("Titulo"), estilo_c.Filete(), estilo_c.Pedestal(120),
                  estilo_c.CasillaC("Chasis", "0 de 1", 0.5, marcada=True), estilo_c.BarraFina(0.3)):
        pieza.resize(200, 120)
        pieza.grab()


def test_panel_clicable_y_refresco_tras_cambiar_de_tema(app, tema_por_defecto):
    panel = estilo_c.PanelC("Mis metas", clicable=True)
    pulsado = []
    panel.pulsado.connect(lambda: pulsado.append(1))
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    panel.resize(100, 50)
    evento = QMouseEvent(QMouseEvent.MouseButtonRelease, QPointF(10, 10), QPointF(10, 10), Qt.LeftButton,
                         Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(panel, evento)
    assert pulsado == [1]
    assert panel.rotulo.text() == "MIS METAS"
    rombo = estilo_c.Rombo(8, parent=panel)
    antes = rombo.width()
    widgets.ESCALA["interfaz"] = 1.3
    try:
        estilo_c.refrescar_todo(panel)
        assert rombo.width() > antes
    finally:
        widgets.ESCALA["interfaz"] = 1.0
