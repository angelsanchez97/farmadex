"""Modo juego (rediseno C): tarjetas HUD con la siguiente pieza y la fisura que sirve,
buscador rapido que les quita el sitio al escribir, y panel de reliquias con su pie."""

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.ui import pestana_tablero, vista_compacta  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _paso(item_id=7, nombre="Sistemas de Citrine Prime"):
    return SimpleNamespace(item={"id": item_id}, nombre=nombre, minutos=69, es_reliquia=True, reliquia="Lith S19",
                           boveda=False, mision={"donde": "Hepit, Vacio", "mision": "Captura"})


def _fisura():
    return SimpleNamespace(nodo="Afrodita, Venus", mision="Defensa movil", era="Lith", expira=None)


@pytest.fixture()
def vista(app, monkeypatch):
    """Una VistaCompacta con un Tablero de mentira: una meta y una fisura util."""
    idiomas.cargar("es")
    estado = {"pasos": [_paso()], "fisuras": None}
    monkeypatch.setattr(pestana_tablero, "pasos_pendientes", lambda indice, usuario, cache=None: list(estado["pasos"]))

    def utiles(mundo, pasos, ahora=None):
        if estado["fisuras"] is not None:
            return estado["fisuras"]
        return [(_fisura(), pasos[0])] if pasos else []

    monkeypatch.setattr(pestana_tablero, "fisuras_utiles", utiles)
    guardados = []
    monkeypatch.setattr("farmadex.config.guardar", lambda cfg: guardados.append(dict(cfg)))
    buscador = SimpleNamespace(con=None)
    v = vista_compacta.VistaCompacta(buscador)
    tablero = SimpleNamespace(usuario=object(), _rutas={}, mundo=object(), _indice_vivo=lambda: object())
    v.usar_tablero(tablero, {"hotkey_overlay": "Ctrl+Alt+W"})
    v.resize(vista_compacta.ANCHO, vista_compacta.ALTO)
    v.show()
    v.refrescar_hud()
    v.estado, v.guardados = estado, guardados
    yield v
    v.hide()


def test_las_tarjetas_ensenan_la_siguiente_pieza_y_la_fisura_que_sirve(vista):
    assert vista.hud.isVisibleTo(vista) and not vista.panel_resultados.isVisibleTo(vista)
    pieza = vista.tarjeta_pieza
    assert pieza.rotulo.texto_completo() == "SIGUIENTE PIEZA"
    assert pieza.dato.texto_completo() == "1 H 09 MIN"
    assert pieza.nombre.texto_completo() == "Sistemas de Citrine Prime"
    assert "Lith S19" in pieza.detalle.text() and "Captura en Hepit, Vacio" in pieza.detalle.text()
    fisura = vista.tarjeta_fisura
    assert fisura.isVisibleTo(vista)
    assert fisura.rotulo.texto_completo() == "FISURA LITH ABIERTA"
    assert fisura.nombre.texto_completo() == "Afrodita, Venus · Defensa movil"
    assert "Sistemas de Citrine Prime" in fisura.detalle.text()
    assert vista.tecla.text() == "CTRL+ALT+W"


def test_sin_fisura_util_o_sin_sitio_la_segunda_tarjeta_no_sale(vista):
    vista.estado["fisuras"] = []
    vista.refrescar_hud()
    assert not vista.tarjeta_fisura.isVisibleTo(vista)
    vista.estado["fisuras"] = None
    vista.refrescar_hud()
    assert vista.tarjeta_fisura.isVisibleTo(vista)
    # Ventana baja: la de la siguiente pieza se queda, la de la fisura cede el sitio.
    vista.setMinimumSize(1, 1)  # suelta, el layout no la dejaria encoger (dentro de la ventana, si)
    vista.resize(vista_compacta.ANCHO, vista.tarjeta_pieza.sizeHint().height() + vista.barra.sizeHint().height() + 20)
    assert vista.tarjeta_pieza.isVisibleTo(vista) and not vista.tarjeta_fisura.isVisibleTo(vista)


def test_sin_metas_la_tarjeta_explica_que_hacer(vista):
    vista.estado["pasos"] = []
    vista.refrescar_hud()
    assert vista.tarjeta_pieza.nombre.texto_completo() == "Sin metas todavia"
    assert "Mis metas" in vista.tarjeta_pieza.detalle.text()
    assert not vista.tarjeta_fisura.isVisibleTo(vista)
    # Sin nada que abrir, el clic no hace nada.
    abiertos = []
    vista.abrir_completo.connect(abiertos.append)
    vista.tarjeta_pieza.pulsado.emit()
    assert abiertos == []


def test_al_escribir_las_tarjetas_dejan_sitio_a_los_resultados_y_vuelven_al_borrar(vista):
    vista.caja.setText("ash")
    assert not vista.hud.isVisibleTo(vista) and vista.panel_resultados.isVisibleTo(vista)
    vista.caja.clear()
    vista._temporizador.stop()
    vista._buscar("")
    assert vista.hud.isVisibleTo(vista) and not vista.panel_resultados.isVisibleTo(vista)


def test_pulsar_la_tarjeta_abre_la_ficha_de_la_pieza(vista):
    abiertos = []
    vista.abrir_completo.connect(abiertos.append)
    vista.tarjeta_pieza.pulsado.emit()
    assert abiertos == [7]


def test_el_boton_tarjetas_las_quita_y_se_recuerda(vista):
    vista.boton_tarjetas.setChecked(False)
    assert not vista.hud.isVisibleTo(vista) and vista.panel_resultados.isVisibleTo(vista)
    assert vista.config[vista_compacta.CLAVE_TARJETAS] is False
    assert vista.guardados and vista.guardados[-1][vista_compacta.CLAVE_TARJETAS] is False
    # Al volver a crearla con esa config, nace sin tarjetas.
    otra = vista_compacta.VistaCompacta(SimpleNamespace(con=None))
    otra.usar_tablero(None, {vista_compacta.CLAVE_TARJETAS: False})
    assert not otra.tarjetas_activas()


# -- la ventana en modo juego ------------------------------------------------------------


@pytest.fixture()
def ventana(app, tmp_path, monkeypatch):
    from farmadex import config, tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    from farmadex.ui.overlay import VentanaOverlay

    idiomas.cargar("es")
    v = VentanaOverlay()
    v.show()
    yield v
    v._reloj_encima.stop()
    v.hide()


def test_en_modo_juego_el_fondo_es_transparente_y_la_cabecera_lleva_el_suyo(ventana):
    assert "transparent" in ventana.barra_cabecera.styleSheet()
    ventana.aplicar_modo("compacto")
    # Casi invisible, pero no del todo: con alfa 0 los clics atravesarian hasta el juego.
    assert "0.01" in ventana.marco.styleSheet()
    assert "rgba" in ventana.barra_cabecera.styleSheet()
    assert ventana.compacta.tablero is ventana.tablero
    assert ventana.compacta.config is ventana.config
    ventana.aplicar_modo("completo")
    assert "0.01" not in ventana.marco.styleSheet()
    assert "transparent" in ventana.barra_cabecera.styleSheet()


def test_la_tecla_del_buscador_sigue_al_atajo_de_ajustes(ventana):
    ventana.config["hotkey_overlay"] = "Ctrl+Shift+F"
    ventana._pintar_pista()
    assert ventana.compacta.tecla.text() == "CTRL+SHIFT+F"


# -- panel de reliquias ------------------------------------------------------------------


def _panel(prioridad, n=4):
    from farmadex.captura.reliquias import Recompensa
    from farmadex.ui.panel_recompensas import PanelRecompensas

    panel = PanelRecompensas()
    panel.prioridad = prioridad
    cajas = [(560 + i * 242, 440, 215, 40) for i in range(n)]
    panel.recompensas = [Recompensa(i + 1, f"Pieza {i}", "x", c, ducados=15) for i, c in enumerate(cajas)]
    panel.resize(1920, 1080)
    return panel


def test_el_pie_dice_el_total_y_la_prioridad_elegida_en_dorado(app):
    from farmadex.captura import prioridad as prio

    panel = _panel(prio.PLATINO)
    assert panel.texto_total() == "Sin precios todavia"
    panel.recompensas[0].platino, panel.recompensas[1].platino = 45, 8
    assert panel.texto_total() == "Total en pantalla: 53 platino (2 de 4 con precio)"
    rect = panel.rectangulo_panel()
    pie = panel.rectangulo_pie(rect)
    assert rect.contains(pie)
    assert all(pie.top() > t.bottom() for t in panel.rectangulos_tarjetas(rect))
    # Se pinta sin reventar con cada preajuste y con una sola recompensa (pie estrecho).
    for clave in prio.CLAVES:
        for n in (1, 4):
            p = _panel(clave, n)
            p.recompensas[0].mejor = True
            lienzo = QImage(1920, 1080, QImage.Format_ARGB32)
            lienzo.fill(0)
            pintor = QPainter(lienzo)
            p.render(pintor, QPoint(0, 0))
            pintor.end()
            r = p.rectangulo_panel()
            assert lienzo.pixelColor(p.rectangulo_pie(r).center()).alpha() > 0


def test_el_panel_deja_ver_la_rareza_bajo_el_nombre(app):
    from farmadex.captura import prioridad as prio
    from farmadex.ui.panel_recompensas import HUECO_RAREZA

    for alto in (1080, 1440):
        panel = _panel(prio.ME_FALTA)
        panel.resize(alto * 16 // 9, alto)
        base = max(r.caja[1] + r.caja[3] for r in panel.recompensas)
        assert panel.rectangulo_panel().y() >= base + max(30, round(alto * HUECO_RAREZA))


def test_la_mejor_lleva_estrella_en_la_cinta(app):
    from farmadex.captura import prioridad as prio
    from farmadex.ui import panel_recompensas as modulo

    panel = _panel(prio.ME_FALTA)
    textos = []
    original = modulo.PanelRecompensas._texto

    def espia(self, pintor, rect, texto, *a, **k):
        textos.append(texto)
        return original(self, pintor, rect, texto, *a, **k)

    panel._texto = espia.__get__(panel)
    panel.recompensas[2].mejor = True
    lienzo = QImage(1920, 1080, QImage.Format_ARGB32)
    lienzo.fill(0)
    pintor = QPainter(lienzo)
    panel.render(pintor, QPoint(0, 0))
    pintor.end()
    con_estrella = [x for x in textos if x.startswith(modulo.ESTRELLA.strip())]
    assert len(con_estrella) == 1
    assert "MEJOR OPCION" in textos
    assert "Lo que me falta" in textos
