"""El chat y lo que sale solo en el juego, con la foto de precios de verdad (PreciosDiarios)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from farmadex.chat import precios as chat_precios
from farmadex.online import precios_diarios as pd
from farmadex.ui import vista_objeto

from test_precios_diarios import _doc


@pytest.fixture()
def foto(tmp_path):
    """La foto comun (singleton) apuntando a una carpeta vacia; se quita al acabar."""
    p = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    pd._reiniciar_para_pruebas(p)
    yield p
    pd._reiniciar_para_pruebas(None)


def _textos(filas) -> str:
    return " | ".join(" ".join(str(x) for x in f[1:] if isinstance(x, (str, list))) for f in filas)


def test_sin_foto_el_chat_y_la_vista_dicen_que_no_hay_precios(foto):
    # La foto comun existe siempre ("verdadera") pero esta vacia: nada de datos inventados.
    assert pd.precios() is foto and bool(foto) and not foto.disponible
    assert foto.buscar("arcane_energize", 5) is None
    assert chat_precios._precios() is None
    filas = chat_precios.filas("arcane_energize", None)
    assert [f.precio for f in filas] == [None]
    assert chat_precios.texto_30d(filas[0].precio) == "sin datos"
    assert chat_precios.texto_fecha(chat_precios.fecha_snapshot()) == "Sin precios descargados todavía"
    assert vista_objeto._precios() is None
    objeto = vista_objeto.ObjetoVisto(item_id=1, slug="arcane_energize", nombre="Arcane Energize")
    texto = _textos(vista_objeto.filas_precio(objeto, vista_objeto._precios()))
    assert "Todavía no hay precios descargados" in texto
    assert "no tiene datos" not in texto


def test_con_foto_el_chat_ensena_rangos_y_dice_de_donde_y_de_cuando(foto):
    foto.instalar(_doc())
    snapshot = chat_precios._precios()
    assert snapshot is foto
    filas = chat_precios.filas("arcane_energize", None, snapshot)
    assert [f.rango for f in filas] == [0, 5]
    assert chat_precios.texto_30d(filas[0].precio) == "3–10 p"
    assert chat_precios.texto_30d(filas[1].precio) == "91–170 p"
    pie = chat_precios.texto_fecha(chat_precios.fecha_snapshot(snapshot))
    assert "warframe.market" in pie and "30/09 00:40" in pie
    # Un objeto que la foto no trae: sin datos, nunca un numero.
    assert [f.precio for f in chat_precios.filas("no_existe", None, snapshot)] == [None]


def test_con_foto_la_vista_ensena_precio_fuente_y_fecha(foto):
    foto.instalar(_doc())
    objeto = vista_objeto.ObjetoVisto(item_id=1, slug="arcane_energize", nombre="Arcane Energize", rango=5)
    filas = vista_objeto.filas_precio(objeto, vista_objeto._precios())
    texto = _textos(filas)
    assert "120 p" in str(filas) and "7 p" in str(filas)
    assert "warframe.market" in texto and "datos del" in texto
    # Sin rangos (un set), y uno que no esta.
    filas = vista_objeto.filas_precio(vista_objeto.ObjetoVisto(2, "ash_prime_set", "Ash Prime Set"), vista_objeto._precios())
    assert "60 p" in str(filas) and "warframe.market" in _textos(filas)
    filas = vista_objeto.filas_precio(vista_objeto.ObjetoVisto(3, "no_existe", "Nada"), vista_objeto._precios())
    assert "warframe.market no tiene datos de este objeto." in _textos(filas)


def test_la_vista_se_repinta_cuando_llega_una_foto_nueva(foto, qtbot=None):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    control = vista_objeto.ControladorVistas(con_red=False)
    try:
        avisos = []
        control._precios_nuevos.connect(lambda: avisos.append(1))
        foto.instalar(_doc())  # `al_actualizar` es un metodo de PreciosDiarios
        for _ in range(50):
            app.processEvents()
            if avisos:
                break
        assert avisos
    finally:
        control.cerrar()


def test_build_leida_sola_sale_en_un_recuadro_que_no_coge_el_foco():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    control = vista_objeto.ControladorVistas(con_red=False)
    try:
        build = SimpleNamespace(equipo=SimpleNamespace(nombre="Rhino Prime"), equipo_texto="RHINO PRIME",
                                equipados=[1, 2, 3], arcanos=[1])
        control.mostrar_build(build, "Ctrl+Alt+B")
        app.processEvents()
        caja = control.caja_build
        assert caja is not None and caja.isVisible()
        assert caja.windowFlags() & Qt.WindowDoesNotAcceptFocus
        assert caja.testAttribute(Qt.WA_ShowWithoutActivating)
        assert caja.width() < 500 and caja.height() < 400
        texto = _textos(caja.filas)
        assert "Rhino Prime" in texto and "3" in texto and "Ctrl" in texto
        assert caja.geometry() in control.rectangulos()
        control.esconder_build()
        assert not caja.isVisible()
    finally:
        control.cerrar()


def test_la_build_automatica_no_abre_la_ventana_y_el_atajo_si():
    """`_build_leida` tras la lectura sola no llama a mostrar/ir_a; tras el atajo, si."""
    from farmadex.ui.overlay import VentanaOverlay

    llamadas = []
    build = SimpleNamespace(vacia=False, aviso="")

    def falsa():
        return SimpleNamespace(
            builds=SimpleNamespace(mostrar_build=lambda b: llamadas.append("pestana")),
            aviso_lectura=SimpleNamespace(listo=lambda tipo: None, fallo=lambda *a: None),
            vistas=SimpleNamespace(mostrar_build=lambda b, atajo="": llamadas.append("recuadro")),
            config={"hotkey_build": "Ctrl+Alt+B"},
            mostrar=lambda: llamadas.append("mostrar"),
            aplicar_modo=lambda modo: llamadas.append("modo"),
            ir_a=lambda destino: llamadas.append("ir_a"),
            modo="compacto",
            _leer_por_turno=lambda tipo, recuadro=True: llamadas.append(("leer", recuadro)),
        )

    v = falsa()
    VentanaOverlay._build_vista_sola(v, 1.0)
    assert llamadas == [("leer", False)] and v._build_sola
    VentanaOverlay._build_leida(v, build)
    assert llamadas == [("leer", False), "pestana", "recuadro"]
    assert not v._build_sola

    llamadas.clear()
    VentanaOverlay.leer_build(v)
    VentanaOverlay._build_leida(v, build)
    assert llamadas == [("leer", True), "pestana", "mostrar", "modo", "ir_a"]
