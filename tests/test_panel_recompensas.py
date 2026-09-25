"""Panel de recompensas con tarjetas: geometria, misma interfaz que las etiquetas y estilo elegible."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from farmadex.captura.comparador import Veredicto
from farmadex.captura.reliquias import SIN_IDENTIFICAR, Recompensa
from farmadex.ui.panel_recompensas import ALTO_TARJETA, PanelRecompensas


def _app():
    return QApplication.instance() or QApplication([])


CAJAS = [(833, 579, 240, 32), (1145, 580, 250, 29), (1452, 551, 220, 60)]


def _recompensas():
    return [
        Recompensa(1, "Fang Prime Plano", "PlanoDeFangPrime", CAJAS[0], ducados=15),
        Recompensa(2, "Orthos Prime Plano", "PlanoDeOrthosPrime", CAJAS[1], ducados=45),
        Recompensa(SIN_IDENTIFICAR, "Sin identificar", "EmpunaduraDeQuassus Prime", CAJAS[2]),
    ]


def test_el_panel_va_justo_debajo_de_las_tarjetas_del_juego_y_no_al_borde_inferior():
    _app()
    panel = PanelRecompensas()
    panel.resize(2560, 1440)
    panel.recompensas = _recompensas()
    rect = panel.rectangulo_panel()
    base_tarjetas = max(c[1] + c[3] for c in CAJAS)
    # deja ver la marca de rareza de debajo del nombre, sin irse lejos
    assert base_tarjetas + 30 <= rect.y() <= base_tarjetas + 1440 * 0.05
    assert rect.bottom() < 1440 * 0.62  # la franja inferior queda libre para otro overlay
    assert rect.x() <= CAJAS[0][0] and rect.right() >= CAJAS[2][0] + CAJAS[2][2]
    tarjetas = panel.rectangulos_tarjetas(rect)
    assert len(tarjetas) == 3 and all(t.height() == ALTO_TARJETA for t in tarjetas)
    assert tarjetas[0].x() < tarjetas[1].x() < tarjetas[2].x()
    assert tarjetas[2].right() <= rect.right()


def test_con_una_sola_recompensa_el_panel_sigue_centrado_en_su_tarjeta():
    _app()
    panel = PanelRecompensas()
    panel.resize(1920, 1080)
    panel.recompensas = [Recompensa(1, "Fang Prime Plano", "x", (900, 500, 200, 30))]
    rect = panel.rectangulo_panel()
    assert abs(rect.center().x() - 1000) <= 2
    assert len(panel.rectangulos_tarjetas(rect)) == 1


def test_mostrar_y_veredicto_igual_que_las_etiquetas():
    _app()
    panel = PanelRecompensas()
    recompensas = _recompensas()
    panel.mostrar(recompensas, {1: ("Dominado", "dominado")}, {1: {"minutos": "~12 min"}})
    assert panel.isVisible() and len(panel.recompensas) == 3
    actualizadas = _recompensas()
    actualizadas[0].platino, actualizadas[0].mejor, actualizadas[0].criterio_platino = 3, True, "minimo"
    panel.marcar_veredicto(actualizadas, Veredicto([], 0, False, "", True))
    assert panel.recompensas[0].platino == 3 and panel.recompensas[0].mejor and panel._seguro is False
    # Un veredicto de otra pantalla no se aplica.
    panel.marcar_veredicto([Recompensa(9, "Otra", "x", (0, 0, 1, 1))], Veredicto([], 0, True, "", True))
    assert panel.recompensas[0].platino == 3
    panel.mostrar([], {})
    assert not panel.isVisible()
    panel.hide()


def test_se_pinta_sin_reventar_con_sin_identificar_y_sin_imagenes(tmp_path):
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import QPoint

    _app()
    panel = PanelRecompensas()
    panel.resize(1920, 1080)
    recompensas = _recompensas()
    recompensas[1].platino, recompensas[1].criterio_platino, recompensas[1].mejor, recompensas[1].vaulted = 3, "minimo", True, True
    panel.mostrar(recompensas, {1: ("Dominado", "dominado")}, {1: {"imagen": "no_existe.png", "tienes": 0}})
    lienzo = QImage(1920, 1080, QImage.Format_ARGB32)
    lienzo.fill(0)
    pintor = QPainter(lienzo)
    panel.render(pintor, QPoint(0, 0))
    pintor.end()
    rect = panel.rectangulo_panel()
    # Hay algo pintado dentro del panel y nada fuera de el (por encima de las tarjetas).
    assert lienzo.pixelColor(rect.center()).alpha() > 0
    assert lienzo.pixelColor(rect.x() + 5, rect.y() - 40).alpha() == 0
    panel.hide()


def test_ajustes_cambia_el_estilo_y_la_ventana_lo_sigue(monkeypatch, tmp_path):
    from farmadex import config
    from farmadex.ui import pestana_ajustes

    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    _app()
    monkeypatch.setattr(pestana_ajustes, "guardar", lambda cfg: None)
    ajustes = pestana_ajustes.PestanaAjustes()
    recibidos = []
    ajustes.estilo_recompensas_cambiado.connect(recibidos.append)
    assert ajustes.estilo_recompensas.currentData() == "etiquetas"
    ajustes.estilo_recompensas.setCurrentIndex(1)
    assert recibidos == ["panel"] and ajustes.config["estilo_recompensas"] == "panel"


def _panel_con(cajas):
    from farmadex.ui.panel_recompensas import PanelRecompensas

    _app()
    panel = PanelRecompensas()
    panel.resize(2560, 1440)
    panel.recompensas = [Recompensa(i + 1, f"R{i}", "x", c, ducados=15) for i, c in enumerate(cajas)]
    return panel


def test_cada_tarjeta_queda_centrada_bajo_su_recompensa():
    """Captura real: Trumna, Euphona y Caliban con nombres de anchos distintos."""
    # Cajas del texto de cada recompensa: anchos muy distintos, centros equiespaciados.
    cajas = [(700, 560, 360, 36), (1150, 560, 360, 36), (1520, 540, 340, 70)]
    panel = _panel_con(cajas)
    rects = panel.rectangulos_tarjetas(panel.rectangulo_panel())
    for (x, _, w, _), rect in zip(cajas, rects):
        assert abs(rect.center().x() - (x + w // 2)) <= 2
    for a, b in zip(rects, rects[1:]):
        assert a.right() < b.left(), "no se pisan"


def test_de_una_a_cuatro_recompensas_caben_y_con_cero_no_hay_panel():
    from farmadex.ui.panel_recompensas import PanelRecompensas

    for n in (1, 2, 3, 4):
        paso = 380
        inicio = 1280 - paso * (n - 1) // 2
        cajas = [(inicio + i * paso - 150, 560, 300, 36) for i in range(n)]
        panel = _panel_con(cajas)
        rects = panel.rectangulos_tarjetas(panel.rectangulo_panel())
        assert len(rects) == n
        assert all(r.left() >= 0 and r.right() <= 2560 for r in rects)
        for a, b in zip(rects, rects[1:]):
            assert a.right() < b.left()
    _app()
    vacio = PanelRecompensas()
    vacio.mostrar([])
    assert not vacio.isVisible()


def test_con_dos_recompensas_iguales_la_marca_de_mejor_no_se_pierde():
    """Captura real: dos "Citrine Prime Plano" (el mas caro) y ninguna marcada como mejor.

    El veredicto se emparejaba por objeto y la segunda copia (no mejor) pisaba a la primera.
    """
    from types import SimpleNamespace

    _app()
    panel = PanelRecompensas()
    panel.resize(1920, 1080)
    cajas = [(100, 500, 200, 30), (400, 500, 200, 30), (700, 500, 200, 30), (1000, 500, 200, 30)]
    ids = [1, 2, 3, 3]
    panel.recompensas = [Recompensa(i, f"obj {i}", "x", c) for i, c in zip(ids, cajas)]
    llegadas = [Recompensa(i, f"obj {i}", "x", c) for i, c in zip(ids, cajas)]
    for n, r in enumerate(llegadas):
        r.mejor = n == 2
    panel.marcar_veredicto(llegadas, SimpleNamespace(seguro=False))
    assert [r.mejor for r in panel.recompensas] == [False, False, True, False]

    # En otro orden tambien se reparte bien, sin perder ninguna.
    panel.recompensas = [Recompensa(i, f"obj {i}", "x", c) for i, c in zip(ids, cajas)]
    desordenadas = [llegadas[3], llegadas[2], llegadas[0], llegadas[1]]
    panel.marcar_veredicto(desordenadas, SimpleNamespace(seguro=False))
    assert sum(r.mejor for r in panel.recompensas) == 1


def test_ajustes_elige_que_destacar_con_un_desplegable_y_se_guarda(monkeypatch, tmp_path):
    from PySide6.QtCore import Qt

    from farmadex.captura import prioridad as prio
    from farmadex.ui import pestana_ajustes

    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    _app()
    monkeypatch.setattr(pestana_ajustes, "guardar", lambda cfg: None)
    ajustes = pestana_ajustes.PestanaAjustes()
    combo = ajustes.prioridad_recompensas
    assert combo.currentData() == prio.ME_FALTA  # por defecto, "Lo que me falta"
    assert [combo.itemData(i) for i in range(combo.count())] == list(prio.CLAVES)
    assert all(combo.itemData(i, Qt.ToolTipRole) for i in range(combo.count()))  # una linea por opcion
    recibidos = []
    ajustes.prioridad_recompensas_cambiada.connect(recibidos.append)
    combo.setCurrentIndex(combo.findData(prio.PLATINO))
    assert recibidos == [prio.PLATINO] and ajustes.config["prioridad_recompensas"] == prio.PLATINO


def test_las_tres_variantes_del_panel_se_pintan_con_el_motivo_del_preajuste():
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter

    from farmadex.captura import prioridad as prio
    from farmadex.ui import panel_recompensas as modulo

    _app()
    for variante in modulo.VARIANTES:
        for prioridad in prio.CLAVES:
            panel = PanelRecompensas()
            panel.variante, panel.prioridad = variante, prioridad
            panel.resize(1920, 1080)
            recompensas = _recompensas()
            recompensas[0].objetivo, recompensas[0].mejor = "0/1", True
            recompensas[1].platino, recompensas[1].criterio_platino = 12, "minimo"
            panel.mostrar(recompensas, {}, {})
            panel.resize(1920, 1080)
            lienzo = QImage(1920, 1080, QImage.Format_ARGB32)
            lienzo.fill(0)
            pintor = QPainter(lienzo)
            panel.render(pintor, QPoint(0, 0))
            pintor.end()
            rect = panel.rectangulo_panel()
            assert rect.height() == modulo.ALTOS[variante] + 2 * modulo.HUECO + 24
            assert lienzo.pixelColor(rect.center()).alpha() > 0
            panel.hide()
