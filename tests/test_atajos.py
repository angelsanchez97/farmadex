"""Atajos: tecla sola, raton y mando; captura pulsando la tecla; y rafagas que no tumban nada.

El fallo de partida (0.6.4, de un tester): pulsar un atajo de lectura muchas veces
seguidas encolaba una lectura entera por pulsacion en el hilo de captura. Con 40
pulsaciones de build eran 17 s leyendo sin parar, y mientras tanto la lectura automatica
de reliquias y la de bajo el cursor esperaban detras ("dejan de funcionar").
"""

from __future__ import annotations

import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QThread, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from farmadex import hotkeys
from farmadex.hotkeys import (
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, Atajo, GestorHotkeys, Mandos, Sondeo, choca_con_el_juego,
    formatear, interpretar, normalizar,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _bombear(app, segundos):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        app.processEvents()
        time.sleep(0.002)


# -- formato: lo que ya tenia el usuario sigue valiendo --------------------------------------


@pytest.mark.parametrize("viejo, canonico", [
    ("Ctrl+Alt+W", "Ctrl+Alt+W"), ("ctrl + shift + q", "Ctrl+Shift+Q"), ("Alt+F5", "Alt+F5"),
    ("Ctrl+Espacio", "Ctrl+Space"), ("Ctrl+Alt+G", "Ctrl+Alt+G"), ("mayus+supr", "Shift+Delete"),
])
def test_la_configuracion_de_antes_se_lee_igual(viejo, canonico):
    atajo = interpretar(viejo)
    assert atajo.tipo == "teclado" and atajo.registrable
    assert normalizar(viejo) == canonico
    assert interpretar(canonico) == atajo


@pytest.mark.parametrize("texto, tipo", [
    ("F9", "teclado"), ("G", "teclado"), ("Mouse4", "raton"), ("Ctrl+Mouse5", "raton"),
    ("Mouse3", "raton"), ("Mando:View+A", "mando"), ("Mando:LB+RB", "mando"), ("pad:back+start", "mando"),
    ("VK192", "teclado"), ("Num5", "teclado"),
])
def test_tecla_sola_raton_y_mando(texto, tipo):
    atajo = interpretar(texto)
    assert atajo.tipo == tipo
    assert interpretar(formatear(atajo)) == atajo  # ida y vuelta
    assert not atajo.registrable or atajo.modificadores  # solo con modificador va por RegisterHotKey


def test_nombres_del_mando_equivalentes():
    assert interpretar("Mando:Back+Start") == interpretar("Mando:View+Menu")
    assert formatear(interpretar("Mando:a+lb")) == "Mando:LB+A"


def test_aviso_de_teclas_del_juego():
    for tecla in ("W", "Space", "E", "1", "Shift+W", "Mando:A"):
        assert choca_con_el_juego(tecla), tecla
    for tecla in ("F9", "Ctrl+W", "Mouse4", "Mando:View+A", "Insert"):
        assert not choca_con_el_juego(tecla), tecla


# -- sondeo: tecla sola, raton y mando sin tragarse nada -------------------------------------


class Teclado:
    def __init__(self):
        self.abajo: set[int] = set()

    def __call__(self, vk):
        return vk in self.abajo


def _sondeo(atajos, teclado, **kw):
    kw.setdefault("primer_plano_nuestro", lambda: False)
    return Sondeo({n: interpretar(c) for n, c in atajos.items()}, tecla_abajo=teclado, **kw)


def test_flanco_una_vez_por_pulsacion_y_mantener_no_repite():
    teclado = Teclado()
    s = _sondeo({"build": "F9"}, teclado)
    assert s.mirar() == []
    teclado.abajo.add(0x78)
    assert s.mirar() == ["build"]
    for _ in range(30):  # medio segundo mantenida
        assert s.mirar() == []
    teclado.abajo.clear()
    assert s.mirar() == []
    teclado.abajo.add(0x78)
    assert s.mirar() == ["build"]


def test_los_modificadores_tienen_que_coincidir():
    teclado = Teclado()
    s = _sondeo({"a": "G", "b": "Ctrl+Mouse4"}, teclado)
    teclado.abajo |= {0x11, ord("G")}  # Ctrl+G no es G
    assert s.mirar() == []
    teclado.abajo = {0x11, 0x05}
    assert s.mirar() == ["b"]
    teclado.abajo = {0x05}  # sin Ctrl, el lateral solo no es Ctrl+Mouse4
    assert s.mirar() == []


def test_una_letra_sola_no_salta_escribiendo_en_farmadex_pero_f9_si():
    teclado = Teclado()
    nuestro = {"v": True}
    s = _sondeo({"letra": "G", "fn": "F9", "raton": "Mouse4"}, teclado, primer_plano_nuestro=lambda: nuestro["v"])
    teclado.abajo = {ord("G")}
    assert s.mirar() == []
    teclado.abajo = {0x78}
    assert s.mirar() == ["fn"]
    teclado.abajo = {0x05}
    assert s.mirar() == ["raton"]
    teclado.abajo = set()
    s.mirar()
    nuestro["v"] = False
    teclado.abajo = {ord("G")}
    assert s.mirar() == ["letra"]


def test_en_pausa_no_salta_ni_al_soltar_la_pausa_con_la_tecla_pulsada():
    teclado = Teclado()
    s = _sondeo({"fn": "F9"}, teclado)
    s.pausado = True
    teclado.abajo = {0x78}
    assert s.mirar() == []
    s.pausado = False
    assert s.mirar() == []  # la pulsacion que se capturaba en Ajustes no dispara al acabar


class MandoFalso:
    def __init__(self):
        self.botones = {}  # hueco -> mascara (ausente = desconectado)
        self.llamadas = []

    def __call__(self, hueco):
        self.llamadas.append(hueco)
        return self.botones.get(hueco)


def test_mando_combinacion_y_huecos_vacios_casi_gratis():
    falso = MandoFalso()
    reloj = {"t": 0.0}
    mandos = Mandos(obtener_estado=falso, reloj=lambda: reloj["t"])
    s = _sondeo({"overlay": "Mando:View+A"}, Teclado(), mandos=mandos)
    # Sin mando: el primer vistazo mira los 4 huecos; los siguientes, ninguno hasta 3 s.
    for _ in range(60):
        assert s.mirar() == []
        reloj["t"] += 0.016
    assert len(falso.llamadas) == 4
    reloj["t"] += 3.0
    falso.botones[1] = 0
    assert s.mirar() == []
    assert mandos.hay_mando
    falso.llamadas.clear()
    falso.botones[1] = 0x1000  # A sola: no
    reloj["t"] += 0.016
    assert s.mirar() == []
    assert falso.llamadas == [1]  # conectado: solo se pregunta por el suyo
    falso.botones[1] = 0x1000 | 0x0020
    assert s.mirar() == ["overlay"]
    assert s.mirar() == []


def test_sin_atajos_de_mando_no_se_carga_xinput():
    s = _sondeo({"fn": "F9"}, Teclado())
    assert s.mandos is None


# -- el hilo de atajos de verdad ---------------------------------------------------------------


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="hilo de atajos de Windows")
def test_hilo_real_rafaga_de_teclas_solas_y_combinaciones(app, monkeypatch):
    """50 pulsaciones seguidas de una tecla sola (sondeo) y 50 WM_HOTKEY de una combinacion:
    se entregan todas, en el hilo de la ventana, y el hilo termina limpio."""
    import ctypes

    teclado = Teclado()
    monkeypatch.setattr(hotkeys, "_tecla_abajo_win", teclado)
    monkeypatch.setattr(hotkeys, "_tecla_pulsada_win", teclado)
    monkeypatch.setattr(hotkeys, "_primer_plano_es_nuestro", lambda: False)
    recibidas = []
    hilos = set()
    gestor = GestorHotkeys({"build": "F13", "combi": "Ctrl+Alt+Shift+F11"})

    def recibir(nombre):
        recibidas.append(nombre)
        hilos.add(threading.current_thread().name)

    gestor.pulsada.connect(recibir)
    gestor.start()
    try:
        limite = time.monotonic() + 3
        while time.monotonic() < limite and gestor.sondeo is None:
            _bombear(app, 0.02)
        assert gestor.sondeo is not None
        for _ in range(50):
            teclado.abajo = {0x7C}  # F13, toques de 50 ms (los muy cortos los salva el bit de Windows)
            time.sleep(0.05)
            teclado.abajo = set()
            time.sleep(0.05)
        id_combi = next((i for i, n in gestor._ids.items() if n == "combi"), None)
        if id_combi is not None:  # si otro programa tiene la combinacion, se prueba solo el sondeo
            for _ in range(50):
                ctypes.windll.user32.PostThreadMessageW(gestor._id_hilo, hotkeys.WM_HOTKEY, id_combi, 0)
        _bombear(app, 0.5)
    finally:
        gestor.parar()
    assert recibidas.count("build") == 50
    if id_combi is not None:
        assert recibidas.count("combi") == 50
    assert hilos == {"MainThread"}
    assert not gestor.isRunning()


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="hilo de atajos de Windows")
def test_sin_atajos_de_sondeo_el_hilo_duerme(app, monkeypatch):
    llamadas = []
    monkeypatch.setattr(hotkeys, "_tecla_abajo_win", lambda vk: llamadas.append(vk) or False)
    gestor = GestorHotkeys({"combi": "Ctrl+Alt+Shift+F10", "vacio": ""})
    gestor.start()
    _bombear(app, 0.3)
    gestor.parar()
    assert llamadas == [] and gestor.sondeo is None
    assert not gestor.isRunning()


# -- rafagas de lecturas: una en marcha como mucho ------------------------------------------------


class LectorLento(QObject):
    """Como un lector de verdad (LectorBase.leer_turno), pero cada lectura dura 60 ms."""

    turno_terminado = Signal(int)
    leida = Signal(int)

    def __init__(self):
        super().__init__()
        self.lecturas = 0
        self.a_la_vez = 0
        self.max_a_la_vez = 0

    def leer_turno(self, numero):
        from farmadex.captura.reliquias import LectorBase

        LectorBase.leer_turno(self, numero)

    def leer_ahora(self):
        self.a_la_vez += 1
        self.max_a_la_vez = max(self.max_a_la_vez, self.a_la_vez)
        time.sleep(0.06)
        self.lecturas += 1
        self.a_la_vez -= 1
        self.leida.emit(self.lecturas)


class Puente(QObject):
    pedir = Signal(int)


def test_rafaga_de_50_pulsaciones_lee_dos_o_tres_veces_y_sigue_funcionando(app):
    from farmadex.captura.cursor import TurnoLecturas

    hilo = QThread()
    lector = LectorLento()
    lector.moveToThread(hilo)
    puente = Puente()
    turno = TurnoLecturas(puente.pedir.emit, pausa_s=0.3)
    puente.pedir.connect(lector.leer_turno)
    lector.turno_terminado.connect(turno.terminada)
    hilo.start()
    try:
        for _ in range(50):
            turno.pedir()
            _bombear(app, 0.005)
        limite = time.monotonic() + 5
        while time.monotonic() < limite and (turno.ocupado or turno.pendiente):
            _bombear(app, 0.02)
        assert not turno.ocupado and not turno.pendiente
        assert 1 <= lector.lecturas <= 3, lector.lecturas
        assert lector.max_a_la_vez == 1
        # Y despues, una pulsacion normal lee enseguida.
        _bombear(app, 0.35)
        antes = lector.lecturas
        assert turno.pedir() == "lanzada"
        limite = time.monotonic() + 2
        while time.monotonic() < limite and lector.lecturas == antes:
            _bombear(app, 0.01)
        assert lector.lecturas == antes + 1
    finally:
        hilo.quit()
        hilo.wait(2000)


def test_leer_turno_avisa_aunque_la_lectura_reviente(app):
    from farmadex.captura.reliquias import LectorBase

    class Roto(QObject):
        turno_terminado = Signal(int)

        def leer_ahora(self):
            raise RuntimeError("motor roto")

    roto = Roto()
    avisos = []
    roto.turno_terminado.connect(avisos.append, Qt.DirectConnection)
    LectorBase.leer_turno(roto, 7)  # no lanza
    assert avisos == [7]


# -- el recuadro "Leyendo..." ------------------------------------------------------------------


def test_recuadro_leyendo_se_va_con_el_resultado_y_dice_si_falla(app):
    from farmadex.ui.aviso_lectura import AvisoLectura

    aviso = AvisoLectura()
    aviso._crear().excluida = True  # como en Windows 10/11: fuera de las capturas
    aviso.leyendo("build", QPoint(400, 300))
    assert aviso.visible() and aviso.estado == "leyendo"
    assert "Leyendo" in aviso.caja.texto
    assert aviso.ultimo_ms < 200
    aviso.listo("agrietado")  # de otra lectura: no toca este
    assert aviso.visible()
    aviso.listo("build")
    assert not aviso.visible()
    aviso.leyendo("cursor", QPoint(50, 50))
    aviso.fallo("cursor", "No se reconoció nada bajo el cursor")
    assert aviso.visible() and aviso.caja.fallo and aviso.estado == "fallo"
    aviso._caducar()
    assert not aviso.visible()
    # Una lectura nueva no arrastra el texto de fallo de la anterior.
    aviso.leyendo("reliquias", QPoint(50, 50))
    assert not aviso.caja.fallo and "Leyendo" in aviso.caja.texto
    aviso.cerrar()


def test_recuadro_desactivado_no_sale(app):
    from farmadex.ui.aviso_lectura import AvisoLectura

    aviso = AvisoLectura(activo=False)
    aviso.leyendo("build")
    assert not aviso.visible()


def test_colocar_no_se_sale_de_la_pantalla():
    from farmadex.ui.aviso_lectura import colocar

    zona = (0, 0, 1920, 1080)
    x, y = colocar((200, 60), (1910, 1070), zona)
    assert 0 <= x <= 1720 and 0 <= y <= 1020
    x, y = colocar((200, 60), (100, 100), zona, arriba=True)
    assert x == (1920 - 200) // 2 and y < 100


def test_el_ocultador_no_toca_lo_que_ya_esta_fuera_de_las_capturas(app):
    from PySide6.QtWidgets import QWidget

    from farmadex.ui import ocultar_captura

    w = QWidget()
    w.resize(50, 50)
    w.show()
    app.processEvents()
    ventana = w.windowHandle()
    assert ventana in ocultar_captura._ventanas_qt()
    ventana.setProperty("farmadex_sin_ocultar", True)
    assert ventana not in ocultar_captura._ventanas_qt()
    w.close()


# -- Ajustes: el atajo se captura pulsandolo ----------------------------------------------------


def _tecla(campo, tecla, mods=Qt.NoModifier, texto=""):
    QApplication.sendEvent(campo, QKeyEvent(QEvent.KeyPress, tecla, mods, texto))


def test_campo_captura_tecla_sola_combinacion_esc_y_retroceso(app):
    from farmadex.ui.campo_atajo import CampoAtajo

    campo = CampoAtajo("Ctrl+Alt+B")
    cambios = []
    campo.cambiado.connect(cambios.append)
    campo.empezar()
    assert hotkeys.en_pausa() and "Pulsa" in campo.text()
    _tecla(campo, Qt.Key_F9)
    assert campo.valor() == "F9" and not campo.capturando and not hotkeys.en_pausa()
    campo.empezar()
    _tecla(campo, Qt.Key_Control, Qt.ControlModifier)  # un modificador solo: sigue esperando
    assert campo.capturando
    _tecla(campo, Qt.Key_W, Qt.ControlModifier | Qt.AltModifier, "w")
    assert campo.valor() == "Ctrl+Alt+W"
    campo.empezar()
    _tecla(campo, Qt.Key_Escape)
    assert campo.valor() == "Ctrl+Alt+W" and not campo.capturando
    campo.empezar()
    _tecla(campo, Qt.Key_Backspace)
    assert campo.valor() == ""
    assert cambios == ["F9", "Ctrl+Alt+W", ""]
    assert not hotkeys.en_pausa()


def test_campo_captura_boton_lateral_del_raton(app):
    from farmadex.ui.campo_atajo import CampoAtajo

    campo = CampoAtajo("")
    campo.empezar()
    evento = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), Qt.BackButton,
                         Qt.BackButton, Qt.NoModifier)
    QApplication.sendEvent(campo, evento)
    assert campo.valor() == "Mouse4"
    campo.releaseMouse()


def test_campo_captura_combinacion_del_mando(app):
    from farmadex.ui.campo_atajo import CampoAtajo

    class MandosGuion:
        def __init__(self, pasos):
            self.pasos = list(pasos)

        def botones(self):
            return self.pasos.pop(0) if self.pasos else 0

    campo = CampoAtajo("", mandos=MandosGuion([0x0020, 0x0020 | 0x1000, 0x1000, 0]))
    campo.empezar()
    for _ in range(4):
        campo._mirar_mando()
    assert campo.valor() == "Mando:View+A"
    assert not hotkeys.en_pausa()


def test_texto_legible_y_avisos():
    from farmadex.ui.campo_atajo import aviso_de, texto_legible

    assert texto_legible("Ctrl+Alt+W") == "Ctrl + Alt + W"
    assert texto_legible("") and texto_legible("Mando:View+A").endswith("View + A")
    assert aviso_de("G") and aviso_de("Mando:A")
    assert aviso_de("F9") == "" and aviso_de("Ctrl+Alt+G") == ""


def test_ajustes_guarda_el_atajo_capturado_y_avisa_de_duplicados(app, monkeypatch, tmp_path):
    from farmadex.ui import pestana_ajustes

    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    monkeypatch.setattr(pestana_ajustes, "guardar", lambda cfg: None)
    ajustes = pestana_ajustes.PestanaAjustes()
    emitidos = []
    ajustes.hotkeys_cambiadas.connect(emitidos.append)
    campo = ajustes.campos_hotkey["build"]
    campo.empezar()
    _tecla(campo, Qt.Key_F9)
    assert ajustes.config["hotkey_build"] == "F9"
    assert emitidos and emitidos[-1]["build"] == "F9"
    # El mismo atajo en dos sitios: no se guarda y se dice.
    otro = ajustes.campos_hotkey["agrietado"]
    otro.empezar()
    _tecla(otro, Qt.Key_F9)
    assert ajustes.config["hotkey_agrietado"] != "F9"
    assert "dos veces" in ajustes.aviso_hotkey.text()
    # Tecla del juego: se guarda, pero con aviso.
    otro.empezar()
    _tecla(otro, Qt.Key_G, Qt.NoModifier, "g")
    assert ajustes.config["hotkey_agrietado"] == "G"
    assert "juego" in ajustes.aviso_hotkey.text()


def test_sin_exclusion_de_capturas_el_recuadro_no_estorba_a_la_lectura(app):
    """Windows sin WDA_EXCLUDEFROMCAPTURE: arriba (fuera de lo que se lee) y sin recuadro en la
    build, que captura la pantalla entera y tendria que esconderlo."""
    from farmadex.ui.aviso_lectura import AvisoLectura

    aviso = AvisoLectura()
    aviso._crear().excluida = False
    aviso.leyendo("build", QPoint(400, 300))
    assert not aviso.visible()
    aviso.leyendo("agrietado", QPoint(960, 540))
    assert aviso.visible()
    assert aviso.caja.y() < 540 - 300  # lejos de la tarjeta que hay bajo el cursor
    aviso.cerrar()

