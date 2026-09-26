"""Builds de Overframe dentro de Farmadex: la direccion, los botones y la pestana Web.

Farmadex no descarga ni lee nada de Overframe: solo arma una busqueda y la abre en la
pestana Web. Aqui nunca se lanza un WebView ni un proceso de verdad (dobles, como en
test_reproductor.py) ni se abre el navegador (openUrl interceptado).
"""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from farmadex import idiomas, video  # noqa: E402
from farmadex.ui import builds_overframe, reproductor  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def castellano():
    idiomas.cargar("es")
    yield
    idiomas.cargar("es")


@pytest.fixture(autouse=True)
def carpeta(tmp_path, monkeypatch):
    destino = tmp_path / "reproductor"
    monkeypatch.setattr(reproductor, "carpeta_datos", lambda: destino)
    return destino


@pytest.fixture()
def abiertas(monkeypatch):
    from PySide6.QtGui import QDesktopServices

    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: urls.append(url.toString()) or True))
    return urls


def _consulta(url: str) -> str:
    partes = urlparse(url)
    assert partes.scheme == "https" and partes.netloc == "duckduckgo.com"
    return parse_qs(partes.query)["q"][0]


# -- la direccion ------------------------------------------------------------------------

def test_busqueda_limitada_a_overframe_con_el_nombre_ingles():
    url = builds_overframe.url_builds("  Ash   Prime ")
    assert _consulta(url) == "site:overframe.gg Ash Prime"
    assert builds_overframe.url_builds("") == "" and builds_overframe.url_builds(None) == ""


def test_solo_lo_que_tiene_builds_y_la_pieza_usa_su_padre():
    ash = {"categoria": "Warframes", "nombre_en": "Ash Prime"}
    pieza = {"categoria": "Warframes", "nombre_en": "Ash Prime Systems"}
    assert builds_overframe.nombre_con_builds(ash) == "Ash Prime"
    assert builds_overframe.nombre_con_builds(pieza, ash) == "Ash Prime"
    for categoria in ("Primary", "Melee", "Arch-Gun", "Archwing", "Sentinels", "SentinelWeapons", "Pets"):
        assert builds_overframe.nombre_con_builds({"categoria": categoria, "nombre_en": "X"}) == "X"
    for categoria in ("Mods", "Arcanes", "Relics", "Resources", None):
        assert builds_overframe.nombre_con_builds({"categoria": categoria, "nombre_en": "X"}) == ""
    assert builds_overframe.nombre_con_builds(None) == ""


# -- el hijo: ordenes del panel y direccion actual -----------------------------------------

class VentanaFalsa:
    def __init__(self, url="https://overframe.gg/items/arsenal/1/ash-prime/"):
        self.url, self.js = url, []

    def run_js(self, script):
        self.js.append(script)

    def get_current_url(self):
        return self.url


def test_el_hijo_hace_la_orden_una_vez_y_apunta_la_direccion(tmp_path):
    ordenes, url_actual = video.rutas_auxiliares(tmp_path / "estado_1_web.txt")
    assert ordenes.parent == url_actual.parent == tmp_path and ordenes != url_actual
    ventana = VentanaFalsa()
    ordenes.write_text("ATRAS", encoding="utf-8")
    ultima = video.atender(ventana, ordenes, url_actual, "")
    assert ventana.js == ["history.back()"] and not ordenes.exists()
    assert ultima == ventana.url and url_actual.read_text(encoding="utf-8") == ventana.url
    # Sin orden nueva no repite nada; una orden desconocida se ignora.
    ordenes.write_text("rm -rf", encoding="utf-8")
    video.atender(ventana, ordenes, url_actual, ultima)
    assert ventana.js == ["history.back()"]
    ordenes.write_text("RECARGAR", encoding="utf-8")
    video.atender(ventana, ordenes, url_actual, ultima)
    assert ventana.js[-1] == "location.reload()"


def test_el_hijo_no_se_cae_si_la_pagina_no_deja(tmp_path):
    class Rota(VentanaFalsa):
        def run_js(self, script):
            raise RuntimeError("aun sin cargar")

        def get_current_url(self):
            raise RuntimeError("aun sin pagina")

    ordenes, url_actual = video.rutas_auxiliares(tmp_path / "e.txt")
    ordenes.write_text("ATRAS", encoding="utf-8")
    assert video.atender(Rota(), ordenes, url_actual, "previa") == "previa"


# -- el panel Web --------------------------------------------------------------------------

class ProcesoFalso:
    def __init__(self):
        self.vivo, self.matado = True, False

    def state(self):
        return QProcess.Running if self.vivo else QProcess.NotRunning

    def kill(self):
        self.matado, self.vivo = True, False

    def waitForFinished(self, _ms):  # noqa: N802 - firma de Qt
        return True


def _panel(clase):
    lanzados = []

    def lanzar(programa, argumentos):
        proceso = ProcesoFalso()
        lanzados.append((argumentos, proceso))
        return proceso

    p = clase(lanzar=lanzar, incrustar=lambda hwnd: QWidget())
    p.lanzados = lanzados
    return p


def _incrustar(panel):
    argumentos = panel.lanzados[-1][0]
    estado = Path(argumentos[argumentos.index("--estado") + 1])
    estado.write_text("HWND 9", encoding="utf-8")
    panel._sondear()
    return estado


URL = builds_overframe.url_builds("Ash Prime")


def test_el_panel_web_tiene_sus_ficheros_y_sus_textos(app, carpeta):
    web, guia = _panel(reproductor.PanelWeb), _panel(reproductor.PanelVideo)
    try:
        assert "Builds en Overframe" in web.mensaje.text() and web.boton_modo.isHidden()
        assert web.boton_cerrar.text() == "Cerrar pagina"
        web.abrir(URL)
        guia.abrir("https://www.youtube.com/results?search_query=warframe")
        args_web, args_guia = web.lanzados[0][0], guia.lanzados[0][0]
        # Cada panel su fichero de estado y su perfil: pueden estar abiertos a la vez.
        assert args_web[args_web.index("--estado") + 1] != args_guia[args_guia.index("--estado") + 1]
        assert str(carpeta / "perfil_web") in args_web and str(carpeta / "perfil") in args_guia
        assert not guia.lanzados[0][1].matado
        _incrustar(web)
        assert web.reproduciendo and "Pagina abierta" in web._texto_abierto()
    finally:
        web.cerrar()
        guia.cerrar()


def test_atras_y_recargar_dejan_la_orden_al_hijo(app):
    web = _panel(reproductor.PanelWeb)
    try:
        assert not web.boton_atras.isEnabled() and not web.ordenar("ATRAS")  # nada abierto
        web.abrir(URL)
        estado = _incrustar(web)
        ordenes, _ = video.rutas_auxiliares(estado)
        assert web.boton_atras.isEnabled() and web.boton_recargar.isEnabled()
        web.boton_atras.click()
        assert video.leer_orden(ordenes) == "ATRAS"
        web.boton_recargar.click()
        assert video.leer_orden(ordenes) == "RECARGAR"
    finally:
        web.cerrar()
    assert not ordenes.exists()


def test_abrir_en_el_navegador_abre_lo_que_se_esta_viendo_y_solo_al_pulsar(app, abiertas):
    web = _panel(reproductor.PanelWeb)
    try:
        web.abrir(URL)
        estado = _incrustar(web)
        assert abiertas == []
        web.boton_navegador.click()
        assert abiertas == [URL]  # aun no ha navegado: la de inicio
        _, url_actual = video.rutas_auxiliares(estado)
        url_actual.write_text("https://overframe.gg/build/123/", encoding="utf-8")
        web.boton_navegador.click()
        assert abiertas[-1] == "https://overframe.gg/build/123/"
    finally:
        web.cerrar()


def test_si_falla_lo_dice_y_ofrece_el_navegador(app, abiertas):
    web = _panel(reproductor.PanelWeb)
    try:
        web.abrir(URL)
        argumentos = web.lanzados[0][0]
        Path(argumentos[argumentos.index("--estado") + 1]).write_text("ERROR sin_webview2", encoding="utf-8")
        web._sondear()
        assert "No se puede abrir aqui" in web.mensaje.text() and abiertas == []
        web.boton_fallo.click()
        assert abiertas == [URL]
    finally:
        web.cerrar()


def test_borrar_datos_borra_tambien_el_perfil_web(app, carpeta):
    web = _panel(reproductor.PanelWeb)
    (carpeta / "perfil_web" / "EBWebView").mkdir(parents=True)
    assert web.borrar_datos() and not (carpeta / "perfil_web").exists()


# -- boton en Buscar -------------------------------------------------------------------------

@pytest.fixture()
def buscador(app, indice_poblado, tmp_path, monkeypatch):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_buscador import PestanaBuscador

    con, _, _ = indice_poblado
    b = PestanaBuscador()
    b.con = con
    return b


def _id(con, nombre_en):
    return con.execute("SELECT id FROM items WHERE nombre_en = ?", (nombre_en,)).fetchone()[0]


def test_boton_overframe_en_la_ficha_de_un_warframe_y_de_su_pieza(buscador, abiertas):
    abiertos = []
    buscador.navegador_web = abiertos.append
    assert buscador.boton_overframe.isHidden()
    buscador.abrir(_id(buscador.con, "Ash Prime"))
    assert not buscador.boton_overframe.isHidden()
    buscador.boton_overframe.click()
    assert [_consulta(u) for u in abiertos] == ["site:overframe.gg Ash Prime"] and abiertas == []
    # La ficha lo dice con todas las letras y el enlace hace lo mismo que el boton.
    assert "href='overframe:'" in buscador.ficha.toHtml() or "overframe:" in buscador._html(buscador._datos_actuales)
    assert "Builds en Overframe" in buscador.ficha.toPlainText()
    from PySide6.QtCore import QUrl

    buscador._enlace(QUrl("overframe:"))
    assert len(abiertos) == 2 and abiertas == []
    pieza = buscador.con.execute(
        "SELECT id FROM items WHERE padre_id = ? LIMIT 1", (_id(buscador.con, "Ash Prime"),)
    ).fetchone()[0]
    buscador.abrir(pieza)
    assert _consulta(buscador.url_overframe()) == "site:overframe.gg Ash Prime"


def test_sin_builds_el_boton_se_apaga(buscador):
    buscador.abrir(_id(buscador.con, "Axi A7 Relic"))
    assert buscador.boton_overframe.isHidden() and buscador.url_overframe() == ""
    assert "Builds en Overframe" not in buscador.ficha.toPlainText()


# -- boton en Build -----------------------------------------------------------------------------

def test_boton_overframe_en_build_con_el_equipo_reconocido(app, tmp_path, monkeypatch):
    import sqlite3

    from farmadex import config
    from farmadex.captura.builds import Build
    from farmadex.captura.ocr import Reconocido

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_builds import PestanaBuilds

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, categoria TEXT, nombre_en TEXT)")
    con.executemany("INSERT INTO items VALUES (?, ?, ?)", [(1, "Warframes", "Excalibur"), (2, "Mods", "Vitality")])
    p = PestanaBuilds()
    p.conectar_indice(con)
    emitidas = []
    p.abrir_web.connect(emitidas.append)

    p.mostrar_build(Build(equipados=[Reconocido("Vitality", 2, "Vitalidad", 100.0, (0, 0, 1, 1))]))
    assert p.boton_overframe.isHidden() and p.url_overframe() == ""
    p.mostrar_build(Build(equipo=Reconocido("EXCALIBUR", 1, "Excalibur", 100.0, (0, 0, 1, 1))))
    assert not p.boton_overframe.isHidden()
    p.boton_overframe.click()
    assert [_consulta(u) for u in emitidas] == ["site:overframe.gg Excalibur"]


# -- la ventana: pestana Web ---------------------------------------------------------------------

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

    v = VentanaOverlay()
    lanzados = []

    def lanzar(programa, argumentos):
        proceso = ProcesoFalso()
        lanzados.append(proceso)
        return proceso

    for panel in (v.video, v.web):
        panel._lanzar = lanzar
        panel._incrustar_ventana = lambda hwnd: QWidget()
    v.lanzados = lanzados
    yield v
    v.hide()


def test_overframe_se_abre_en_la_pestana_web_de_la_ventana(ventana):
    assert ventana.buscador.navegador_web == ventana.abrir_web
    ventana.aplicar_modo("compacto")
    ventana.abrir_web(URL)
    assert ventana.modo == "completo" and ventana.pestanas.currentWidget() is ventana.web
    assert ventana.web.url == URL and len(ventana.lanzados) == 1
    # Build emite y la ventana lo abre igual.
    ventana.builds.abrir_web.emit(URL + "x")
    assert ventana.web.url == URL + "x" and ventana.lanzados[0].matado
    ventana.cerrar_de_verdad()
    assert ventana.lanzados[1].matado
