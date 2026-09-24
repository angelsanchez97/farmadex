"""Reproductor de guias dentro de Farmadex, sin abrir nunca una ventana ni un proceso de verdad.

El usuario juega mientras pasan las pruebas: el proceso hijo (pywebview) y el incrustado
de su ventana se sustituyen por dobles; solo se comprueba el cableado.
"""

import os
import runpy
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from farmadex import idiomas, video  # noqa: E402
from farmadex.ui import reproductor  # noqa: E402

URL = "https://www.youtube.com/results?search_query=warframe+Hepit+Captura+guia&sp=CAM%253D"


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


class ProcesoFalso:
    """Lo que el panel usa de QProcess: estado y kill (por su PID, que aqui no hay)."""

    def __init__(self):
        self.vivo = True
        self.matado = False

    def state(self):
        return QProcess.Running if self.vivo else QProcess.NotRunning

    def kill(self):
        self.matado, self.vivo = True, False

    def waitForFinished(self, _ms):  # noqa: N802 - firma de Qt
        return True


@pytest.fixture()
def panel(app, monkeypatch):
    lanzados, incrustados = [], []

    def lanzar(programa, argumentos):
        proceso = ProcesoFalso()
        lanzados.append((programa, argumentos, proceso))
        return proceso

    def incrustar(hwnd):
        incrustados.append(hwnd)
        return QWidget()

    p = reproductor.PanelVideo(lanzar=lanzar, incrustar=incrustar)
    p.lanzados, p.incrustados = lanzados, incrustados
    yield p
    p.cerrar()


@pytest.fixture()
def abiertas(monkeypatch):
    from PySide6.QtGui import QDesktopServices

    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: urls.append(url.toString()) or True))
    return urls


# -- construccion del comando ---------------------------------------------------------

def test_comando_del_exe_y_desde_el_codigo(tmp_path):
    estado, datos = tmp_path / "e.txt", tmp_path / "perfil"
    programa, args = reproductor.comando(URL, estado, 42, datos, congelado=True, ejecutable=r"C:\F\Farmadex.exe")
    assert programa == r"C:\F\Farmadex.exe"
    assert args == ["--video", URL, "--estado", str(estado), "--padre", "42", "--datos", str(datos)]
    # Desde el codigo: pythonw (sin consola negra encima del juego) si existe.
    python = tmp_path / "python.exe"
    python.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    programa, args = reproductor.comando(URL, estado, 42, datos, congelado=False, ejecutable=str(python))
    assert programa == str(tmp_path / "pythonw.exe") and args[:3] == ["-m", "farmadex.video", URL]


def test_leer_estado(tmp_path):
    ruta = tmp_path / "e.txt"
    assert reproductor.leer_estado(ruta) is None
    ruta.write_text("HWND 1234", encoding="utf-8")
    assert reproductor.leer_estado(ruta) == ("HWND", "1234")
    ruta.write_text("ERROR sin_webview2 algo", encoding="utf-8")
    assert reproductor.leer_estado(ruta) == ("ERROR", "sin_webview2 algo")
    ruta.write_text("basura", encoding="utf-8")
    assert reproductor.leer_estado(ruta) is None


# -- panel ------------------------------------------------------------------------------

def test_abre_e_incrusta_la_ventana_del_hijo(panel, carpeta):
    panel.abrir(URL)
    (programa, args, proceso), = panel.lanzados
    assert URL in args and "--estado" in args and str(os.getpid()) in args
    assert str(carpeta / "perfil") in args  # perfil de WebView2 en la carpeta de datos
    estado = Path(args[args.index("--estado") + 1])
    assert estado.parent == carpeta
    assert not panel.reproduciendo
    estado.write_text("HWND 777", encoding="utf-8")
    panel._sondear()
    assert panel.incrustados == [777] and panel.reproduciendo
    # El contenedor va en la ventana anfitriona (opaca), no dentro del overlay translucido.
    assert panel.pila.currentWidget() is panel.area
    assert panel._contenedor.window() is panel._anfitrion


def test_la_anfitriona_sigue_al_hueco_del_panel(panel):
    panel.resize(640, 400)
    panel.show()
    panel.abrir(URL)
    estado = Path(panel.lanzados[0][1][panel.lanzados[0][1].index("--estado") + 1])
    estado.write_text("HWND 5", encoding="utf-8")
    panel._sondear()
    panel._recolocar()
    assert panel._anfitrion.isVisible() and panel._anfitrion.geometry() == panel.hueco()
    # El panel se esconde (otra pestana, overlay escondido): la anfitriona tambien.
    panel.hide()
    panel._recolocar()
    assert not panel._anfitrion.isVisible()


def test_otro_video_cierra_el_anterior_por_su_pid(panel):
    panel.abrir(URL)
    primero = panel.lanzados[0][2]
    panel.abrir(URL + "&otro")
    assert primero.matado and len(panel.lanzados) == 2 and panel.url.endswith("&otro")


def test_si_falla_dice_que_no_se_puede_y_no_abre_nada_solo(panel, abiertas):
    panel.abrir(URL)
    proceso = panel.lanzados[0][2]
    estado = Path(panel.lanzados[0][1][panel.lanzados[0][1].index("--estado") + 1])
    estado.write_text("ERROR sin_webview2", encoding="utf-8")
    panel._sondear()
    assert "No se puede reproducir aqui" in panel.mensaje.text()
    assert not panel.boton_fallo.isHidden() and proceso.matado
    assert abiertas == []  # el navegador solo al pulsar
    panel.boton_fallo.click()
    assert abiertas == [URL]


def test_si_no_arranca_el_proceso(app, abiertas):
    def lanzar(*_):
        raise OSError("no hay ejecutable")

    p = reproductor.PanelVideo(lanzar=lanzar, incrustar=lambda hwnd: QWidget())
    p.abrir(URL)
    assert "No se puede reproducir aqui" in p.mensaje.text() and abiertas == []


def test_si_el_hijo_no_contesta_a_tiempo(panel, monkeypatch):
    monkeypatch.setattr(reproductor, "ESPERA_MS", 400)
    panel.abrir(URL)
    panel._sondear()
    panel._sondear()
    assert "No se puede reproducir aqui" in panel.mensaje.text()


def test_cerrar_para_el_video_y_borrar_datos(panel, carpeta):
    panel.abrir(URL)
    proceso = panel.lanzados[0][2]
    (carpeta / "perfil" / "EBWebView").mkdir(parents=True)
    assert panel.borrar_datos()
    assert proceso.matado and not (carpeta / "perfil").exists()
    assert panel.url == "" and not panel.boton_cerrar.isEnabled()


# -- proceso hijo y enrutado de --video -------------------------------------------------

def test_enrutar_solo_con_el_argumento(monkeypatch):
    llamadas = []
    monkeypatch.setattr(video, "main", lambda argv: llamadas.append(argv) or 0)
    assert video.enrutar(["--bandeja"]) is None and llamadas == []
    assert video.enrutar(["--video", URL, "--estado", "e.txt"]) == 0
    assert llamadas == [[URL, "--estado", "e.txt"]]


def test_el_exe_enruta_video_antes_de_arrancar_qt(monkeypatch):
    llamadas = []
    monkeypatch.setattr(video, "enrutar", lambda argv: llamadas.append(argv) or 5)
    monkeypatch.setattr(sys, "argv", ["Farmadex.exe", "--video", URL, "--estado", "e.txt"])
    arranque = Path(__file__).resolve().parents[1] / "empaquetado" / "arranque.py"
    with pytest.raises(SystemExit) as salida:
        runpy.run_path(str(arranque), run_name="__main__")
    assert salida.value.code == 5 and llamadas == [["--video", URL, "--estado", "e.txt"]]


def test_app_main_tambien_enruta(monkeypatch):
    from farmadex import app as aplicacion

    monkeypatch.setattr(video, "main", lambda argv: 7)
    assert aplicacion.main(["farmadex", "--video", URL, "--estado", "e.txt"]) == 7


def test_el_hijo_sin_pywebview_lo_dice_en_el_estado(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", None)  # import webview -> ImportError
    estado = tmp_path / "e.txt"
    assert video.main([URL, "--estado", str(estado)]) == 2
    assert estado.read_text(encoding="utf-8").startswith("ERROR sin_pywebview")


def test_el_hijo_vigila_al_padre():
    assert video.proceso_vivo(os.getpid())
    assert video.proceso_vivo(0)  # sin padre que vigilar


# -- modo video en la ventana ------------------------------------------------------------

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

    v.video._lanzar = lanzar
    v.video._incrustar_ventana = lambda hwnd: QWidget()
    v.lanzados = lanzados
    yield v
    v.hide()


def test_guias_en_la_pestana_video_y_modo_video_recordado(ventana):
    assert ventana.buscador.reproductor == ventana.abrir_video
    ventana.abrir_video(URL)
    assert ventana.pestanas.currentWidget() is ventana.video and ventana.video.url == URL
    ventana.aplicar_modo("video")
    assert ventana.modo == "video" and not ventana.pestanas.tabBar().isVisibleTo(ventana)
    assert ventana.boton_modo.text() == "Salir del video"
    ventana.setGeometry(50, 60, 500, 330)
    ventana.alternar_modo()  # Ctrl+M / "Salir del video"
    assert ventana.modo == "completo" and ventana.config["overlay_geometria_video"] == [50, 60, 500, 330]
    ventana.aplicar_modo("video")
    assert ventana.geometry().getRect() == (50, 60, 500, 330)


def test_cerrar_el_video_en_modo_video_vuelve_a_la_completa(ventana):
    ventana.abrir_video(URL)
    ventana.aplicar_modo("video")
    ventana.video.cerrar()
    assert ventana.modo == "completo" and ventana.lanzados[0].matado


def test_al_salir_se_cierra_el_reproductor_que_lanzo(ventana):
    ventana.abrir_video(URL)
    ventana.cerrar_de_verdad()
    assert ventana.lanzados[0].matado
