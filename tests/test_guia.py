"""Guia de uso guiada: avanza, retrocede, se salta, guarda el flag y no se relanza sola."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def ventana(app, tmp_path, monkeypatch):
    """Una VentanaOverlay sin hilos, sin indice y con su configuracion en una carpeta temporal."""
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
    v.hide()
    idiomas.cargar("es")


def _escape(widget) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Escape, Qt.NoModifier))
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))


def test_boton_guia_la_lanza_desde_el_principio(ventana):
    assert ventana._guia is None
    ventana.mostrar_guia()
    assert ventana._guia is not None
    assert ventana._guia._indice == 0
    assert ventana._guia.contador.text() == "Paso 1 de 19"


def test_avanza_y_retrocede(ventana):
    ventana.mostrar_guia()
    guia = ventana._guia
    guia.siguiente()
    assert guia._indice == 1
    titulo_paso_2 = guia.titulo.text()
    guia.siguiente()
    assert guia._indice == 2
    guia.atras()
    assert guia._indice == 1
    assert guia.titulo.text() == titulo_paso_2
    # En el primer paso "Atras" esta desactivado; en el ultimo, "Siguiente" dice "Terminar".
    guia.atras()
    assert guia._indice == 0
    assert not guia.boton_atras.isEnabled()


def test_llegar_al_ultimo_paso_cambia_el_boton_a_terminar(ventana):
    ventana.mostrar_guia()
    guia = ventana._guia
    total = len(guia._pasos)
    for _ in range(total - 1):
        guia.siguiente()
    assert guia._indice == total - 1
    assert guia.boton_siguiente.text() == "Terminar"


def test_cambia_de_pestana_sola_cuando_el_paso_lo_pide(ventana):
    ventana.mostrar_guia()
    guia = ventana._guia
    # El paso de Mundo pide la pestana "mundo".
    indices = {p.pestana: i for i, p in enumerate(guia._pasos) if p.pestana == "mundo"}
    guia._ir_a_paso(next(iter(indices.values())))
    assert ventana.pestanas.currentWidget() is ventana.mundo


def test_cada_paso_con_objetivo_lo_resalta_dentro_de_la_ventana(ventana):
    """Tambien los que estan al fondo de Ajustes (diagnostico) o son varios botones juntos."""
    ventana.resize(1180, 760)
    ventana.mostrar_guia()
    guia = ventana._guia
    for i, paso in enumerate(guia._pasos):
        if paso.objetivo is None:
            continue
        guia._ir_a_paso(i)
        assert guia._rect_resalte is not None, paso.titulo
        assert guia.rect().contains(guia._rect_resalte), paso.titulo


def test_wiki_y_youtube_se_resaltan_juntos(ventana):
    ventana.resize(1180, 760)
    ventana.mostrar_guia()
    guia = ventana._guia
    i = next(i for i, p in enumerate(guia._pasos) if p.titulo == "Wiki y videos")
    guia._ir_a_paso(i)
    from PySide6.QtCore import QPoint, QRect

    for boton in (ventana.buscador.boton_wiki, ventana.buscador.boton_youtube):
        rect = QRect(boton.mapTo(ventana, QPoint(0, 0)), boton.size())
        assert guia._rect_resalte.contains(rect)


def test_saltar_con_boton_termina_y_guarda_el_flag(ventana):
    from farmadex.config import cargar

    ventana.mostrar_guia()
    guia = ventana._guia
    guia.siguiente()
    guia.boton_saltar.click()
    assert ventana._guia is None
    assert cargar()["guia_vista"] is True


def test_saltar_con_escape_termina_igual(ventana):
    from farmadex.config import cargar

    ventana.mostrar_guia()
    guia = ventana._guia
    _escape(guia)
    assert ventana._guia is None
    assert cargar()["guia_vista"] is True
    # Escape no debe haber cerrado tambien el overlay entero.
    assert ventana.isVisible()


def test_terminar_en_el_ultimo_paso_tambien_guarda_el_flag(ventana):
    from farmadex.config import cargar

    ventana.mostrar_guia()
    guia = ventana._guia
    for _ in range(len(guia._pasos) - 1):
        guia.siguiente()
    guia.siguiente()  # en el ultimo paso, "Siguiente" (ya renombrado "Terminar") cierra
    assert ventana._guia is None
    assert cargar()["guia_vista"] is True


def test_primera_vez_la_lanza_sola(ventana, monkeypatch):
    """Instalacion nueva: `_config_existia_antes` es False, la guia se abre sin que se pida."""
    from PySide6.QtCore import QTimer

    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda ms, fn: fn()))
    assert ventana._config_existia_antes is False
    ventana._avisar_o_lanzar_guia()
    assert ventana._guia is not None


def test_actualizacion_no_la_lanza_sola_solo_avisa(ventana):
    """Quien ya tenia Farmadex (config.json de antes) recibe un aviso discreto, no la guia."""
    ventana._config_existia_antes = True
    ventana.config["guia_aviso_visto"] = False
    ventana._avisar_o_lanzar_guia()
    assert ventana._guia is None
    assert "guia_nueva" in ventana._avisos
    assert ventana.config["guia_aviso_visto"] is True


def test_el_aviso_de_actualizacion_no_vuelve_a_salir(ventana):
    ventana._config_existia_antes = True
    ventana.config["guia_aviso_visto"] = True
    ventana._avisar_o_lanzar_guia()
    assert ventana._guia is None
    assert "guia_nueva" not in ventana._avisos


def test_no_se_relanza_sola_si_ya_se_vio(ventana):
    ventana.config["guia_vista"] = True
    ventana._avisar_o_lanzar_guia()
    assert ventana._guia is None
    assert "guia_nueva" not in ventana._avisos


def test_el_enlace_del_aviso_abre_la_guia(ventana):
    ventana._config_existia_antes = True
    ventana.config["guia_aviso_visto"] = False
    ventana._avisar_o_lanzar_guia()
    assert ventana._guia is None
    ventana._enlace_banner("farmadex:guia")
    assert ventana._guia is not None
    assert "guia_nueva" not in ventana._avisos


def test_el_boton_guia_relanza_aunque_ya_estuviera_vista(ventana):
    from farmadex.config import cargar

    ventana.config["guia_vista"] = True
    from farmadex.config import guardar

    guardar(ventana.config)
    ventana.mostrar_guia()
    assert ventana._guia is not None
    assert cargar()["guia_vista"] is True


def test_desde_modo_compacto_pasa_a_completo(ventana):
    ventana.aplicar_modo("compacto")
    assert ventana.modo == "compacto"
    ventana.mostrar_guia()
    assert ventana.modo == "completo"


def test_la_guia_ensena_lo_nuevo_de_la_0_5(ventana):
    """Build, Agrietados, los avisos de Mundo, el aspecto y como ordenar objetivos tienen su paso,
    y cada uno abre su pestana y resalta su boton o su zona."""
    ventana.resize(1180, 760)
    ventana.mostrar_guia()
    guia = ventana._guia
    esperados = {
        "Build": (ventana.builds, ventana.builds.boton),
        "Agrietados": (ventana.agrietados, ventana.agrietados.boton_leer),
        "Avisos del mundo": (ventana.mundo, ventana.mundo.boton_personalizar),
        "A tu gusto": (ventana.ajustes, ventana.ajustes.escala_interfaz),
        "Ordenar tus objetivos": (ventana.objetivos, ventana.objetivos.estados),
    }
    from PySide6.QtCore import QPoint, QRect

    titulos = [p.titulo for p in guia._pasos]
    for titulo, (pestana, widget) in esperados.items():
        assert titulo in titulos, titulo
        guia._ir_a_paso(titulos.index(titulo))
        assert ventana.pestanas.currentWidget() is pestana, titulo
        rect = QRect(widget.mapTo(ventana, QPoint(0, 0)), widget.size())
        assert guia._rect_resalte is not None and guia._rect_resalte.intersects(rect), titulo
    # Los atajos que salen en el texto son los que tiene configurados el usuario.
    guia._ir_a_paso(titulos.index("Build"))
    assert ventana.config.get("hotkey_build", "Ctrl+Alt+B") in guia.cuerpo.text()
    compacto = guia._pasos[titulos.index("Modo compacto")].cuerpo
    assert "Fijar" in compacto
