"""OCR adaptativo: medida de la carga de CPU, eleccion de motor por modo y ajuste en la interfaz."""

from __future__ import annotations

import logging
import sys

import numpy as np
import pytest

from farmadex.captura import carga, ocr
from farmadex.captura.ocr import CLAVE_LIGERO, CLAVE_NORMAL, MotorOCR, modo_de_config


# --- medidor de carga ----------------------------------------------------------------

class Reloj:
    """Contadores falsos de GetSystemTimes / GetProcessTimes que se van avanzando a mano."""

    def __init__(self):
        self.ocupado = self.total = self.propio = 0

    def avanzar(self, total, ocupado, propio=0):
        self.total += total
        self.ocupado += ocupado
        self.propio += propio

    def sistema(self):
        return self.ocupado, self.total

    def proceso(self):
        return self.propio


def test_medidor_resta_lo_que_gasta_farmadex_y_hace_media_de_las_ultimas_muestras():
    reloj = Reloj()
    m = carga.MedidorCarga(muestras=2, leer_sistema=reloj.sistema, leer_proceso=reloj.proceso)
    assert m.uso_ajeno() is None  # sin dos fotos no hay media
    m.muestrear()
    assert m.uso_ajeno() is None
    reloj.avanzar(1000, 600, propio=200)  # 60 % ocupado, pero 20 puntos son nuestros
    m.muestrear()
    assert m.uso_ajeno() == pytest.approx(0.4)
    reloj.avanzar(1000, 1000)
    m.muestrear()
    assert m.uso_ajeno() == pytest.approx(0.7)  # (400 + 1000) / 2000
    reloj.avanzar(1000, 0)
    m.muestrear()
    assert m.uso_ajeno() == pytest.approx(0.5)  # la primera muestra ya salio de la ventana
    assert m.nucleos_libres(16) == pytest.approx(8.0)


def test_medidor_que_no_puede_medir_no_revienta_y_avisa_una_vez(caplog):
    def roto():
        raise OSError("sin permiso")

    m = carga.MedidorCarga(leer_sistema=roto, leer_proceso=lambda: 0)
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            m.muestrear()
    assert m.uso_ajeno() is None
    assert sum("carga" in r.getMessage() for r in caplog.records) == 1


def test_medidor_arranca_un_solo_hilo_y_se_para():
    reloj = Reloj()
    m = carga.MedidorCarga(intervalo=0.01, leer_sistema=reloj.sistema, leer_proceso=reloj.proceso)
    m.iniciar()
    hilo = m._hilo
    m.iniciar()
    assert m._hilo is hilo and hilo.daemon
    m.detener()
    assert not hilo.is_alive()


@pytest.mark.skipif(sys.platform != "win32", reason="GetSystemTimes solo existe en Windows")
def test_medidor_real_da_un_valor_entre_0_y_1():
    m = carga.MedidorCarga()
    m.muestrear()
    suma = 0
    for i in range(300000):  # un poco de trabajo para que pase algo de tiempo
        suma += i
    m.muestrear()
    uso = m.uso_ajeno()
    assert uso is None or 0.0 <= uso <= 1.0


def test_fuera_de_windows_no_se_mide(monkeypatch):
    monkeypatch.setattr(carga, "disponible", lambda: False)
    assert carga.medidor() is None and carga.uso_ajeno() is None


# --- configuracion -------------------------------------------------------------------

def test_modo_por_defecto_es_automatico_y_uno_raro_tambien(monkeypatch):
    from farmadex import config

    monkeypatch.setattr(ocr, "_winocr_instalado", True)

    assert config.POR_DEFECTO["ocr_modo"] == "auto"
    assert modo_de_config({}) == "auto"
    assert modo_de_config({"ocr_modo": "turbo"}) == "auto"
    assert modo_de_config(None) == "auto"
    for modo in ocr.MODOS_OCR:
        assert modo_de_config({"ocr_modo": modo}) == modo


# --- eleccion de motor -----------------------------------------------------------------

@pytest.fixture()
def motores(monkeypatch):
    """Motores falsos: apuntan con cuantos hilos se crearon y con cual se leyo."""
    MotorOCR.descargar()
    creados, lecturas = [], []

    def crear(hilos):
        creados.append(hilos)

        def motor(imagen):
            lecturas.append(hilos)
            return [], None

        return motor

    monkeypatch.setattr(ocr, "_crear_rapidocr", crear)
    monkeypatch.setattr(ocr, "HILOS_LIGERO", 2)
    monkeypatch.setattr(carga, "medidor", lambda: None)
    uso = {"valor": None}
    monkeypatch.setattr(carga, "uso_ajeno", lambda: uso["valor"])
    yield creados, lecturas, uso
    MotorOCR.descargar()


IMAGEN = np.full((60, 200, 3), 30, np.uint8)


def test_automatico_lee_con_hilos_normales_si_la_cpu_va_desahogada(motores):
    creados, lecturas, uso = motores
    motor = MotorOCR("auto", hilos=4)
    uso["valor"] = 0.10
    motor.leer(IMAGEN)
    assert lecturas == [4] and motor.ultima_clave == CLAVE_NORMAL


def test_automatico_aligera_con_la_cpu_cargada_y_vuelve_con_histeresis(motores):
    creados, lecturas, uso = motores
    motor = MotorOCR("auto", hilos=4)
    for valor in (0.10, 0.45, 0.35, 0.25, 0.35, None):
        uso["valor"] = valor
        motor.leer(IMAGEN)
    # 0.45 entra en ligero; 0.35 sigue ligero (histeresis); 0.25 vuelve; 0.35 ya no basta
    # para entrar; sin medida se queda como estaba.
    assert lecturas == [4, 2, 2, 4, 4, 4]
    assert sorted(creados) == [2, 4]  # como mucho dos motores, sin recargar al cambiar


def test_automatico_sin_medida_usa_los_hilos_normales(motores):
    creados, lecturas, uso = motores
    MotorOCR("auto", hilos=4).leer(IMAGEN)
    assert lecturas == [4] and creados == [4]  # el ligero ni se carga


def test_con_pocos_nucleos_automatico_no_carga_un_segundo_motor(motores):
    creados, lecturas, uso = motores
    uso["valor"] = 0.95
    MotorOCR("auto", hilos=2).leer(IMAGEN)  # el ligero seria igual que el normal
    assert lecturas == [2] and creados == [2]


def test_rapido_y_ligero_no_miran_la_carga(motores):
    creados, lecturas, uso = motores
    uso["valor"] = 0.95
    rapido = MotorOCR("rapido", hilos=4)
    assert rapido.motor == "rapidocr"
    rapido.leer(IMAGEN)
    uso["valor"] = 0.0
    MotorOCR("ligero", hilos=4).leer(IMAGEN)
    assert lecturas == [4, 2]


def test_si_el_ligero_no_carga_automatico_sigue_con_el_normal(motores, monkeypatch):
    creados, lecturas, uso = motores
    crear_bueno = ocr._crear_rapidocr

    def crear(hilos):
        if hilos == 2:
            raise RuntimeError("modelo roto")
        return crear_bueno(hilos)

    monkeypatch.setattr(ocr, "_crear_rapidocr", crear)
    uso["valor"] = 0.9
    motor = MotorOCR("auto", hilos=4)
    motor.leer(IMAGEN)
    motor.leer(IMAGEN)
    assert lecturas == [4, 4] and motor.fallo is None


def test_precalentar_en_automatico_calienta_los_dos_una_vez(motores, monkeypatch):
    creados, lecturas, uso = motores
    arrancado = []
    monkeypatch.setattr(carga, "medidor", lambda: arrancado.append(1))
    tiras = []
    monkeypatch.setattr(ocr, "_leer_tira_rapidocr", lambda motor, imagen: tiras.append(imagen.shape) or [])
    a, b = MotorOCR("auto", hilos=4), MotorOCR("auto", hilos=4)
    a.precalentar()
    b.precalentar()
    assert sorted(creados) == [2, 4]
    assert sorted(lecturas) == [2, 4]  # una lectura de prueba por motor, no por lector
    assert len(tiras) == 1  # la fila de nombres del ligero (la del normal la hace recompensas_rapidas)
    assert arrancado  # el medidor de carga se pone en marcha
    uso["valor"] = 0.9
    a.leer(IMAGEN)
    assert sorted(creados) == [2, 4]  # leer con la CPU cargada no carga nada nuevo


def test_olvidar_fallo_de_un_modo_limpia_sus_dos_motores(motores):
    MotorOCR._fallidos.update({CLAVE_NORMAL: "x", CLAVE_LIGERO: "y", "winocr": "z"})
    MotorOCR.olvidar_fallo("auto")
    assert MotorOCR._fallidos == {"winocr": "z"}
    MotorOCR.olvidar_fallo("windows")
    assert MotorOCR._fallidos == {}


# --- OCR de Windows ------------------------------------------------------------------

def test_windows_sin_winocr_cae_al_local_avisando(motores, monkeypatch, caplog):
    creados, lecturas, uso = motores
    monkeypatch.setitem(sys.modules, "winocr", None)  # import winocr -> ImportError
    motor = MotorOCR("windows", hilos=4)
    assert motor.motor == "winocr" and motor.fallo is None
    with caplog.at_level(logging.WARNING):
        motor.leer(IMAGEN)
    assert lecturas == [4] and motor.motor == "auto"
    assert any("OCR de Windows no disponible" in r.getMessage() for r in caplog.records)


def test_windows_que_falla_al_leer_repite_en_local_y_no_lo_vuelve_a_intentar(motores, monkeypatch):
    creados, lecturas, uso = motores
    monkeypatch.setattr(MotorOCR, "_winocr", True)
    intentos = []

    def falla(imagen):
        intentos.append(1)
        raise OSError("sin paquete de idioma")

    monkeypatch.setattr(ocr, "_leer_winocr", falla)
    motor = MotorOCR("windows", hilos=4)
    assert motor.leer_tira(IMAGEN) == []
    otro = MotorOCR("windows", hilos=4)
    otro.leer(IMAGEN)
    assert intentos == [1]  # el segundo ya sabe que el de Windows no va
    assert motor.motor == otro.motor == "auto" and otro.fallo is None
    assert lecturas == [4]  # el leer() de `otro`; la tira va por su propio camino


def test_windows_que_funciona_devuelve_lo_suyo(motores, monkeypatch):
    creados, lecturas, uso = motores
    monkeypatch.setattr(MotorOCR, "_winocr", True)
    leido = ocr.Leido("FORMA", 1, 2, 30, 10, 1.0)
    monkeypatch.setattr(ocr, "_leer_winocr", lambda imagen: [leido])
    motor = MotorOCR("windows")
    assert motor.leer(IMAGEN) == [leido] and motor.leer_tira(IMAGEN) == [leido]
    assert creados == [] and motor.ultima_clave == "winocr"


# --- Ajustes --------------------------------------------------------------------------

def test_ajustes_elige_el_modo_de_ocr_y_avisa(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication

    from farmadex.ui import pestana_ajustes

    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(pestana_ajustes, "guardar", lambda cfg: None)
    monkeypatch.setattr(ocr, "_winocr_instalado", True)
    ajustes = pestana_ajustes.PestanaAjustes()
    monkeypatch.setitem(ajustes.config, "ocr_modo", ajustes.config.get("ocr_modo", "auto"))
    combo = ajustes.ocr_modo
    assert [combo.itemData(i) for i in range(combo.count())] == list(ocr.MODOS_OCR)
    assert all(combo.itemText(i) for i in range(combo.count()))
    recibidos = []
    ajustes.ocr_modo_cambiado.connect(recibidos.append)
    combo.setCurrentIndex(combo.findData("ligero"))
    assert recibidos == ["ligero"] and ajustes.config["ocr_modo"] == "ligero"


def test_lector_pasivo_cambia_de_motor():
    """La lectura pasiva lee con su propio motor (sesion aparte y pocos hilos) salvo con el
    OCR de Windows: su OCR de pantalla entera hacia esperar a las lecturas pedidas."""
    from farmadex.captura.lector_pasivo import LectorPasivo

    lector = LectorPasivo("auto")
    assert lector.motor.motor == "fondo"
    lector.cambiar_motor("ligero")
    assert lector.motor.motor == "fondo"
    lector.cambiar_motor("winocr")
    assert lector.motor.motor == "winocr"


def test_el_motor_de_fondo_es_una_sesion_aparte_con_pocos_hilos(monkeypatch):
    creados = []
    monkeypatch.setattr(ocr, "_crear_rapidocr", lambda hilos: creados.append(hilos) or object())
    ocr.MotorOCR.descargar()
    try:
        fondo = ocr.MotorOCR("fondo")
        assert fondo._clave_fija() == ocr.CLAVE_FONDO
        assert fondo._cargar() is not ocr.MotorOCR("rapidocr")._cargar()
        assert creados == [ocr.HILOS_LIGERO, ocr.HILOS_OCR]
    finally:
        ocr.MotorOCR.descargar()


def test_si_el_motor_de_fondo_no_carga_se_usa_el_normal(monkeypatch):
    def crear(hilos):
        if hilos == ocr.HILOS_LIGERO and ocr.HILOS_LIGERO != ocr.HILOS_OCR:
            raise RuntimeError("sin memoria")
        return "normal"

    monkeypatch.setattr(ocr, "_crear_rapidocr", crear)
    monkeypatch.setattr(ocr, "HILOS_LIGERO", 1)
    ocr.MotorOCR.descargar()
    try:
        fondo = ocr.MotorOCR("fondo", hilos=4)
        assert fondo._cargar() == "normal"
        assert fondo.fallo is None
    finally:
        ocr.MotorOCR.descargar()


def test_la_lectura_pasiva_no_mira_durante_la_pantalla_de_reliquia():
    from farmadex.captura.lector_pasivo import LectorPasivo

    lector = LectorPasivo("auto")
    assert lector.merece_mirar()
    lector.evento("reliquia_abierta")
    assert not lector.merece_mirar()
    lector.evento("reliquia_cerrada")
    assert lector.merece_mirar()


def test_sin_winocr_la_opcion_windows_no_sale_y_cuenta_como_auto(monkeypatch):
    """Si el OCR de Windows no esta instalado no se ofrece en Ajustes, y quien lo tenia
    guardado lee con el modo automatico."""
    monkeypatch.setattr(ocr, "_winocr_instalado", False)
    assert ocr.modo_de_config({"ocr_modo": "windows"}) == "auto"
    assert ocr.modo_de_config({"ocr_modo": "ligero"}) == "ligero"
    monkeypatch.setattr(ocr, "_winocr_instalado", True)
    assert ocr.modo_de_config({"ocr_modo": "windows"}) == "windows"


def test_desplegable_de_ajustes_sin_winocr(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication

    from farmadex import config
    from farmadex.ui.pestana_ajustes import PestanaAjustes

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "_compartida", None)
    QApplication.instance() or QApplication([])
    config.cargar()["ocr_modo"] = "windows"
    for instalado, esperado in ((False, ["auto", "rapido", "ligero"]), (True, ["auto", "rapido", "ligero", "windows"])):
        monkeypatch.setattr(ocr, "_winocr_instalado", instalado)
        ajustes = PestanaAjustes()
        claves = [ajustes.ocr_modo.itemData(i) for i in range(ajustes.ocr_modo.count())]
        assert claves == esperado
        assert ajustes.ocr_modo.currentData() == ("windows" if instalado else "auto")
        ajustes.deleteLater()
