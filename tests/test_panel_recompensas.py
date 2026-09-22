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
    assert base_tarjetas < rect.y() <= base_tarjetas + 12
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
