"""Bienvenida obligatoria, Ajustes por secciones, aspecto personalizado y textos de confianza."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def config_temporal(tmp_path, monkeypatch):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    yield config
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
    v.show()
    yield v
    v.hide()


def _tecla(widget, tecla) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.ShortcutOverride, tecla, Qt.NoModifier))
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, tecla, Qt.NoModifier))


# -- configuracion y temas -------------------------------------------------------------

def test_config_trae_las_claves_nuevas_y_no_comparte_diccionarios(config_temporal):
    cfg = config_temporal.cargar()
    assert cfg["bienvenida_vista"] is False
    assert cfg["escala_interfaz"] == 1.0 and cfg["escala_letra"] == 1.0
    cfg["colores_personalizados"]["orokin"] = {"acento": "#ff0000"}
    assert config_temporal.POR_DEFECTO["colores_personalizados"] == {}


def test_paleta_ignora_colores_invalidos_y_rehace_el_fondo_rgb():
    from farmadex.ui import widgets

    p = widgets.paleta_de("vacio", {"fondo": "#102030", "acento": "rojo", "inventado": "#ffffff"})
    assert p["fondo"] == "#102030" and p["fondo_rgb"] == "16, 32, 48"
    assert p["acento"] == widgets.TEMAS["vacio"]["acento"]
    assert "inventado" not in p


def test_aspecto_guardado_filtra_lo_que_se_haya_tocado_a_mano():
    from farmadex.ui import widgets

    cfg = {"tema": "tenno", "escala_interfaz": 7, "escala_letra": "1.3",
           "colores_personalizados": {"tenno": {"texto": "#abcdef", "borde": "mal"}}}
    colores, interfaz, letra = widgets.aspecto_guardado(cfg)
    assert colores == {"texto": "#abcdef"}
    assert interfaz == 1.0 and letra == 1.3


def test_la_escala_agranda_letra_y_medidas_de_la_hoja():
    from farmadex.ui import widgets

    normal = widgets.hoja_estilos(widgets.TEMAS["orokin"], (1.0, 1.0))
    grande = widgets.hoja_estilos(widgets.TEMAS["orokin"], (1.3, 1.5))
    assert "font-size: 14px" in normal
    assert f"font-size: {round(14 * 1.3 * 1.5)}px" in grande
    assert f"padding: {round(6 * 1.3)}px {round(14 * 1.3)}px" in grande  # botones
    assert widgets.px(12, escala=(1.0, 1.5)) == 18
    assert widgets.px(12, letra=False, escala=(1.0, 1.5)) == 12


def test_el_color_de_los_botones_es_una_categoria_propia():
    from farmadex.ui import widgets

    p = widgets.paleta_de("orokin", {"boton": "#123456"})
    hoja = widgets.hoja_estilos(p, (1.0, 1.0))
    assert "QPushButton {{ background: #123456".replace("{{", "{") in hoja


def test_elegir_tema_aplica_lo_personalizado_de_la_config(config_temporal):
    from farmadex.ui import widgets

    cfg = config_temporal.cargar()
    cfg["colores_personalizados"] = {"cherry": {"acento": "#00ff00"}}
    cfg["escala_letra"] = 1.15
    config_temporal.guardar(cfg)
    assert widgets.elegir_tema("cherry")["acento"] == "#00ff00"
    assert widgets.ESCALA["letra"] == 1.15
    assert widgets.elegir_tema("vacio")["acento"] == widgets.TEMAS["vacio"]["acento"]


# -- Ajustes por secciones ---------------------------------------------------------------

def test_ajustes_va_por_secciones_en_vertical(ajustes):
    from farmadex.ui.pestana_ajustes import SECCIONES

    assert ajustes.secciones.count() == len(SECCIONES) == ajustes.paginas.count()
    assert ajustes.seccion_actual() == "general"
    ajustes.ir_a("reliquias")
    assert ajustes.seccion_actual() == "reliquias"
    assert ajustes.ocr_auto.isVisibleTo(ajustes)
    assert not ajustes.idioma.isVisibleTo(ajustes)
    assert not hasattr(ajustes, "diseno_mundo")  # ahora vive en la pestana Mundo


def test_el_mantenimiento_va_plegado_en_avanzado_y_explicado(ajustes):
    ajustes.ir_a("datos")
    for boton in (ajustes.boton_reconstruir, ajustes.boton_carpeta, ajustes.boton_reproductor):
        assert not boton.isVisibleTo(ajustes)
    ajustes.boton_avanzado.click()
    for boton in (ajustes.boton_reconstruir, ajustes.boton_carpeta, ajustes.boton_reproductor):
        assert boton.isVisibleTo(ajustes)
    notas = " ".join(n.text() for n in ajustes._notas)
    assert "tus objetivos no se tocan" in notas          # reconstruir
    assert "No borres nada de ahi" in notas              # carpeta
    assert "cookies de YouTube" in notas                 # reproductor
    assert "No cambia las probabilidades" in notas       # ritmo
    assert "Es un atajo de teclado" in notas             # leer bajo el cursor


def test_el_diagnostico_abre_su_seccion(ajustes):
    class Diag:
        def html(self, colores):
            return "[OK] todo bien"

    ajustes.mostrar_diagnostico(Diag())
    assert ajustes.seccion_actual() == "reliquias"
    assert ajustes.resultado_diagnostico.isVisibleTo(ajustes)


def test_ajustes_cambia_de_idioma_con_las_secciones(ajustes):
    idiomas.cargar("en")
    try:
        ajustes.retraducir()
        textos = [ajustes.secciones.item(i).text() for i in range(ajustes.secciones.count())]
        assert "Appearance" in textos and "Help" in textos
        assert "Advanced" in ajustes.boton_avanzado.text()
    finally:
        idiomas.cargar("es")


# -- aspecto personalizado -----------------------------------------------------------------

def test_los_colores_quedan_pendientes_hasta_guardar(ajustes, config_temporal):
    tema = ajustes.tema.currentData()
    ajustes._poner_color("acento", "#FF0000")
    assert ajustes.hay_cambios_aspecto()
    assert ajustes.boton_guardar_aspecto.isEnabled()
    assert ajustes.muestras["acento"].text() == "#ff0000"
    assert not config_temporal.cargar(recargar=True).get("colores_personalizados")

    avisos = []
    ajustes.apariencia_cambiada.connect(lambda: avisos.append(1))
    ajustes.guardar_aspecto()
    assert avisos == [1]
    guardado = config_temporal.cargar(recargar=True)
    assert guardado["colores_personalizados"] == {tema: {"acento": "#ff0000"}}
    assert not ajustes.hay_cambios_aspecto()


def test_descartar_vuelve_a_lo_guardado(ajustes):
    ajustes._poner_color("texto", "#010203")
    ajustes.escala_letra.setCurrentIndex(ajustes.escala_letra.findData(1.5))
    assert ajustes.hay_cambios_aspecto()
    ajustes.descartar_aspecto()
    assert not ajustes.hay_cambios_aspecto()
    assert ajustes.escala_letra.currentData() == 1.0
    assert not ajustes.boton_guardar_aspecto.isEnabled()


def test_el_color_del_tema_no_cuenta_como_personalizado(ajustes):
    from farmadex.ui.widgets import TEMAS

    base = TEMAS[ajustes.tema.currentData()]["fondo"]
    ajustes._poner_color("fondo", base.upper())
    assert not ajustes.hay_cambios_aspecto()


def test_tamanos_se_guardan_y_sobreviven_a_reabrir(ajustes, config_temporal):
    ajustes.escala_interfaz.setCurrentIndex(ajustes.escala_interfaz.findData(1.15))
    ajustes.escala_letra.setCurrentIndex(ajustes.escala_letra.findData(1.3))
    ajustes.guardar_aspecto()
    config_temporal._compartida = None  # como al volver a abrir Farmadex
    cfg = config_temporal.cargar()
    assert cfg["escala_interfaz"] == 1.15 and cfg["escala_letra"] == 1.3
    from farmadex.ui.pestana_ajustes import PestanaAjustes

    otra = PestanaAjustes()
    assert otra.escala_interfaz.currentData() == 1.15
    assert otra.escala_letra.currentData() == 1.3


def test_lo_de_fabrica_limpia_todos_los_temas(ajustes, config_temporal):
    cfg = config_temporal.cargar()
    cfg["colores_personalizados"] = {"vacio": {"acento": "#111111"}, "tenno": {"texto": "#222222"}}
    cfg["escala_letra"] = 1.5
    config_temporal.guardar(cfg)
    ajustes._cargar_aspecto()
    ajustes.aspecto_de_fabrica()
    assert ajustes.hay_cambios_aspecto()
    assert "fabrica" in ajustes.estado_aspecto.text()
    ajustes.guardar_aspecto()
    guardado = config_temporal.cargar(recargar=True)
    assert guardado["colores_personalizados"] == {}
    assert guardado["escala_letra"] == 1.0


def test_la_vista_previa_usa_lo_pendiente(ajustes):
    ajustes._poner_color("aviso", "#abcdef")
    assert "#abcdef" in ajustes.vista_previa.aviso.styleSheet()
    ajustes.escala_letra.setCurrentIndex(ajustes.escala_letra.findData(1.5))
    assert "font-size: 21px" in ajustes.vista_previa.styleSheet()  # 14 * 1.5


# -- bienvenida ----------------------------------------------------------------------------

def test_no_salta_sin_pantalla_ni_con_la_variable(app, monkeypatch):
    from farmadex.ui import bienvenida

    assert bienvenida.toca_bienvenida({}) is False  # las pruebas corren en offscreen
    monkeypatch.setattr(type(app), "platformName", lambda self: "windows")
    assert bienvenida.toca_bienvenida({}) is True
    assert bienvenida.toca_bienvenida({"bienvenida_vista": True}) is False
    monkeypatch.setenv("FARMADEX_SIN_BIENVENIDA", "1")
    assert bienvenida.toca_bienvenida({}) is False


def test_en_las_pruebas_la_ventana_no_la_ensena_sola(ventana):
    QApplication.processEvents()
    assert ventana._bienvenida is None


def test_primera_vez_obligatoria_y_luego_no_vuelve(ventana, monkeypatch, config_temporal):
    from farmadex.ui import overlay

    monkeypatch.setattr(overlay, "toca_bienvenida", lambda cfg: not cfg.get("bienvenida_vista"))
    ventana._avisar_o_lanzar_guia()
    capa = ventana._bienvenida
    assert capa is not None and capa.obligatoria
    assert ventana._guia is None  # la guia la ofrece la bienvenida, no salta a la vez
    assert not capa.boton_cerrar.isVisibleTo(capa)
    assert not capa.boton_empezar.isVisibleTo(capa)
    _tecla(capa, Qt.Key_Escape)
    assert ventana._bienvenida is capa and ventana.isVisible()
    for _ in range(capa.paginas.count()):
        capa.boton_siguiente.click()
    assert capa.boton_empezar.isVisibleTo(capa) and capa.boton_guia.isVisibleTo(capa)
    capa.boton_empezar.click()  # "Empezar sin recorrido"
    assert ventana._bienvenida is None and ventana._guia is None
    cfg = config_temporal.cargar(recargar=True)
    assert cfg["bienvenida_vista"] is True and cfg["guia_vista"] is True
    ventana._avisar_o_lanzar_guia()
    assert ventana._bienvenida is None


def test_quien_actualiza_tambien_la_ve_una_vez(ventana, monkeypatch):
    from farmadex.ui import overlay

    monkeypatch.setattr(overlay, "toca_bienvenida", lambda cfg: not cfg.get("bienvenida_vista"))
    ventana._config_existia_antes = True
    ventana.config["guia_vista"] = True  # ya habia hecho la guia en la version anterior
    ventana._avisar_o_lanzar_guia()
    capa = ventana._bienvenida
    assert capa is not None
    capa._ir_a(capa.paginas.count() - 1)
    assert not capa.boton_guia.isVisibleTo(capa)  # la guia ya la conoce: solo "Empezar"
    capa.boton_empezar.click()
    assert ventana.config["bienvenida_vista"] is True


def test_empezar_con_recorrido_lanza_la_guia(ventana):
    ventana.mostrar_bienvenida(obligatoria=True)
    capa = ventana._bienvenida
    capa._ir_a(capa.paginas.count() - 1)
    capa.boton_guia.click()
    assert ventana._bienvenida is None
    assert ventana._guia is not None


def test_desde_ajustes_se_abre_y_se_cierra_con_escape(ventana):
    ventana.ajustes.boton_bienvenida.click()
    capa = ventana._bienvenida
    assert capa is not None and not capa.obligatoria
    assert capa.boton_cerrar.isVisibleTo(capa)
    _tecla(capa, Qt.Key_Escape)
    assert ventana._bienvenida is None
    assert ventana.isVisible()  # Escape no ha escondido tambien el overlay


def test_la_bienvenida_trae_lo_prometido(ventana):
    ventana.mostrar_bienvenida()
    capa = ventana._bienvenida
    texto = " ".join(e.text() for e in capa.textos)
    for pieza in ("vaas", "twitch.tv/vaas1897", "github.com/angelsanchez97/farmadex/releases",
                  "SHA256SUMS.txt", "Get-FileHash", "EE.log", "memoria del juego",
                  "we do not endorse any use of third-party software", "at your own risk",
                  "Preguntas frecuentes", "Gracias"):
        assert pieza in texto, pieza
    assert "no te pueden banear" not in texto.lower()
    assert "no esta aprobado por DE" in texto
    capa.terminar(False)


def test_la_bienvenida_sigue_el_tamano_de_la_ventana(ventana):
    ventana.mostrar_bienvenida()
    capa = ventana._bienvenida
    ventana.resize(800, 500)
    QApplication.processEvents()
    assert capa.geometry() == ventana.rect()
    assert ventana.rect().contains(capa.tarjeta.geometry())
    capa.terminar(False)


# -- confianza: Acerca de, documento y empaquetado ----------------------------------------------

def test_acerca_de_explica_windows_la_descarga_y_la_huella(app, config_temporal):
    from PySide6.QtWidgets import QLabel

    from farmadex.ui import acerca_de

    dialogo = acerca_de.DialogoAcercaDe()
    texto = "\n".join(e.text() for e in dialogo.findChildren(QLabel))
    for pieza in ("Windows protegio tu PC", acerca_de.URL_RELEASES, "SHA256SUMS.txt", "Get-FileHash",
                  "EE.log", "No lee ni escribe la memoria del juego"):
        assert pieza in texto, pieza
    assert not dialogo.boton_bienvenida.isVisibleTo(dialogo)  # sin ventana no hay bienvenida
    dialogo.close()


def test_construir_genera_sha256sums():
    ps1 = (RAIZ / "empaquetado" / "construir.ps1").read_text(encoding="utf-8")
    assert "SHA256SUMS.txt" in ps1
    assert "Get-FileHash" in ps1
    assert '".exe", ".zip"' in ps1


def test_documento_de_seguridad():
    doc = (RAIZ / "docs" / "SEGURIDAD.md").read_text(encoding="utf-8")
    for pieza in ("SmartScreen", "https://github.com/angelsanchez97/farmadex/releases", "SHA256SUMS.txt",
                  "Get-FileHash", "EE.log", "memoria del juego", "Third Party Software and You",
                  "no está aprobado ni respaldado por Digital Extremes"):
        assert pieza in doc, pieza
    assert "no te pueden banear" not in doc.lower()


def test_la_guia_resalta_la_columna_de_secciones_de_ajustes(ventana):
    from farmadex.ui.guia import _pasos

    paso = next(p for p in _pasos(ventana) if p.titulo == "Ajustes")
    assert paso.objetivo(ventana) is ventana.ajustes.secciones
    diag = next(p for p in _pasos(ventana) if "reliquia" in p.titulo and "Si no sale" in p.titulo)
    diag.objetivo(ventana)
    assert ventana.ajustes.seccion_actual() == "reliquias"
