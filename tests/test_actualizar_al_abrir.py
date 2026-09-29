"""Actualizar al abrir: antes de construir la ventana, instalar la version nueva.

Sin red (httpx.MockTransport hace de GitHub), sin instalar nada de verdad (el
instalador es una funcion falsa) y sin ventanas visibles (offscreen).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import httpx
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex.actualizador import al_abrir, descarga, instalacion  # noqa: E402
from farmadex.actualizador.app import ComprobadorApp, Version  # noqa: E402
from farmadex.online.http import Cliente  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
CONTENIDO = b"MZ" + bytes(range(256)) * 200
HUELLA = hashlib.sha256(CONTENIDO).hexdigest()
URL = "https://github.com/angelsanchez97/farmadex/releases/download/v9.9.9/Farmadex-9.9.9-setup.exe"
CONFIG = {"actualizar_automaticamente": True, "actualizar_al_abrir": True, "comprobar_actualizaciones_app": True}


@pytest.fixture(autouse=True)
def _entorno(monkeypatch, tmp_path):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(instalacion, "RUTA_PENDIENTE", tmp_path / "pendiente.json")
    monkeypatch.setattr(instalacion, "RUTA_FALLIDA", tmp_path / "fallida.json")
    # Nada de mutex de verdad en el proceso de las pruebas.
    monkeypatch.setattr(instalacion, "senalar_en_ejecucion", lambda: None)


def version(digest=f"sha256:{HUELLA}"):
    return Version(etiqueta="v9.9.9", url=URL, notas="", nombre="Farmadex-9.9.9-setup.exe",
                   tamano=len(CONTENIDO), digest=digest)


def release_json(digest=f"sha256:{HUELLA}"):
    return {
        "tag_name": "v9.9.9", "html_url": "https://github.com/x", "body": "",
        "assets": [{"name": "Farmadex-9.9.9-setup.exe", "browser_download_url": URL,
                    "size": len(CONTENIDO), "digest": digest}],
    }


def comprobador(responder):
    c = ComprobadorApp()
    c.cliente = Cliente(transporte=httpx.MockTransport(responder))
    return c


def github_con_version(digest=f"sha256:{HUELLA}"):
    return comprobador(lambda r: httpx.Response(200, json=release_json(digest)))


def github_sin_red():
    def caido(r):
        raise httpx.ConnectError("sin red")
    return comprobador(caido)


def transporte_descarga(contenido=CONTENIDO, espera: threading.Event | None = None):
    def responder(r):
        if espera is not None:
            espera.wait(5)
        return httpx.Response(200, content=contenido)
    return httpx.MockTransport(responder)


class Instalador:
    """Hace de instalar_silencioso: apunta lo que le piden y no lanza nada."""

    def __init__(self, ok=True):
        self.ok, self.llamadas = ok, []

    def __call__(self, ruta, etiqueta, **k):
        self.llamadas.append((Path(ruta), etiqueta, k.get("en_bandeja", False)))
        return self.ok


def sin_ventanas(monkeypatch):
    def prohibida(*a, **k):
        raise AssertionError("no debe salir ninguna ventana")
    monkeypatch.setattr(al_abrir, "VentanaActualizando", prohibida)


def bajada(tmp_path) -> Path:
    return descarga.descargar(version(), tmp_path, transporte=transporte_descarga())


# -- cuando no toca --------------------------------------------------------------------


def test_motivos_para_no_actualizar_al_abrir(tmp_path):
    si = lambda: True  # noqa: E731
    assert al_abrir.motivo_para_no_hacerlo(CONFIG, ["F.exe"], si) is None
    assert al_abrir.motivo_para_no_hacerlo(CONFIG, ["F.exe", "--tras-actualizar"], si)
    assert al_abrir.motivo_para_no_hacerlo({**CONFIG, "actualizar_automaticamente": False}, ["F.exe"], si)
    assert al_abrir.motivo_para_no_hacerlo({**CONFIG, "actualizar_al_abrir": False}, ["F.exe"], si)
    assert "portable" in al_abrir.motivo_para_no_hacerlo(CONFIG, ["F.exe"], lambda: False)
    instalacion.RUTA_PENDIENTE.write_text("{}")
    assert "sin resolver" in al_abrir.motivo_para_no_hacerlo(CONFIG, ["F.exe"], si)


def test_desde_el_codigo_no_hace_nada(tmp_path, monkeypatch):
    """Sin congelar (pruebas, desarrollo) nunca es la version instalada."""
    sin_ventanas(monkeypatch)
    inst = Instalador()
    bajada(tmp_path)
    assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], carpeta=tmp_path, instalar=inst)
    assert inst.llamadas == []


def test_tras_actualizar_no_vuelve_a_mirar(tmp_path, monkeypatch):
    sin_ventanas(monkeypatch)
    inst = Instalador()
    bajada(tmp_path)
    assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe", "--tras-actualizar"], es_instalada=lambda: True,
                                            carpeta=tmp_path, instalar=inst)
    assert inst.llamadas == []


# -- instalador ya descargado ----------------------------------------------------------


def test_la_descarga_apunta_el_instalador_listo(tmp_path):
    ruta = bajada(tmp_path)
    assert json.loads((tmp_path / "lista.json").read_text()) == {
        "version": "v9.9.9", "fichero": ruta.name, "sha256": HUELLA}
    assert al_abrir.instalador_listo(tmp_path) == ("v9.9.9", ruta)


def test_instalador_listo_descarta_lo_que_no_cuadra(tmp_path, monkeypatch):
    ruta = bajada(tmp_path)
    ruta.write_bytes(b"MZ tocado")
    assert al_abrir.instalador_listo(tmp_path) is None
    assert not (tmp_path / "lista.json").exists()

    ruta = bajada(tmp_path)
    monkeypatch.setattr(instalacion, "version_fallida", lambda: "v9.9.9")
    assert al_abrir.instalador_listo(tmp_path) is None

    monkeypatch.setattr(instalacion, "version_fallida", lambda: None)
    (tmp_path / "lista.json").write_text(json.dumps({"version": "v0.0.1", "fichero": ruta.name, "sha256": HUELLA}))
    assert al_abrir.instalador_listo(tmp_path) is None
    # Ni rutas que salgan de la carpeta de descargas.
    (tmp_path / "lista.json").write_text(json.dumps({"version": "v9.9.9", "fichero": "..\\..\\otro.exe",
                                                     "sha256": HUELLA}))
    assert al_abrir.instalador_listo(tmp_path) is None


def test_ya_descargado_se_instala_sin_preguntar_a_github(tmp_path):
    ruta = bajada(tmp_path)
    inst = Instalador()
    usado = []
    c = comprobador(lambda r: usado.append(r) or httpx.Response(500))
    assert al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path,
                                        comprobador=c, instalar=inst)
    assert inst.llamadas == [(ruta, "v9.9.9", False)]
    assert usado == []


def test_en_la_bandeja_ya_descargado_se_instala_sin_ventanas(tmp_path, monkeypatch):
    sin_ventanas(monkeypatch)
    ruta = bajada(tmp_path)
    inst = Instalador()
    assert al_abrir.actualizar_al_abrir(CONFIG, ["F.exe", "--bandeja"], en_bandeja=True,
                                        es_instalada=lambda: True, carpeta=tmp_path, instalar=inst)
    assert inst.llamadas == [(ruta, "v9.9.9", True)]


def test_en_la_bandeja_sin_descargar_no_pregunta_ni_ensena_nada(tmp_path, monkeypatch):
    sin_ventanas(monkeypatch)
    usado = []
    c = comprobador(lambda r: usado.append(r) or httpx.Response(200, json=release_json()))
    inst = Instalador()
    assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe", "--bandeja"], en_bandeja=True,
                                            es_instalada=lambda: True, carpeta=tmp_path, comprobador=c,
                                            instalar=inst)
    assert usado == [] and inst.llamadas == []


def test_si_el_setup_no_arranca_se_abre_normal(tmp_path):
    bajada(tmp_path)
    inst = Instalador(ok=False)
    assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path,
                                            instalar=inst)
    assert len(inst.llamadas) == 1


# -- version nueva en GitHub -------------------------------------------------------------


def test_version_nueva_se_descarga_con_ventana_y_se_instala(tmp_path, monkeypatch):
    ventanas = []
    original = al_abrir.VentanaActualizando

    def espia(etiqueta):
        v = original(etiqueta)
        ventanas.append(v)
        return v

    monkeypatch.setattr(al_abrir, "VentanaActualizando", espia)
    inst = Instalador()
    assert al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path,
                                        comprobador=github_con_version(), transporte_descarga=transporte_descarga(),
                                        instalar=inst)
    ruta = tmp_path / "Farmadex-9.9.9-setup.exe"
    assert inst.llamadas == [(ruta, "v9.9.9", False)]
    assert ruta.read_bytes() == CONTENIDO
    assert len(ventanas) == 1
    assert "v9.9.9" in ventanas[0].texto.text() and ventanas[0].barra.value() == 100
    assert "Abrir sin actualizar" in ventanas[0].boton.text()


def test_sin_red_se_abre_normal_sin_ventanas(tmp_path, monkeypatch):
    sin_ventanas(monkeypatch)
    inst = Instalador()
    assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path,
                                            comprobador=github_sin_red(), instalar=inst)
    assert inst.llamadas == []


def test_github_lento_no_bloquea_el_arranque(tmp_path, monkeypatch):
    sin_ventanas(monkeypatch)
    suelta = threading.Event()

    def lento(r):
        suelta.wait(5)
        return httpx.Response(200, json=release_json())

    inicio = time.monotonic()
    try:
        assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path,
                                                comprobador=comprobador(lento), instalar=Instalador(), plazo=0.3)
        assert time.monotonic() - inicio < 2
    finally:
        suelta.set()


def test_sin_novedades_o_sin_huella_se_abre_normal(tmp_path, monkeypatch):
    sin_ventanas(monkeypatch)
    viejo = comprobador(lambda r: httpx.Response(200, json={**release_json(), "tag_name": "v0.0.1"}))
    assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path,
                                            comprobador=viejo, instalar=Instalador())
    assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path,
                                            comprobador=github_con_version(digest=""), instalar=Instalador())


def test_con_comprobar_apagado_no_pregunta(tmp_path, monkeypatch):
    sin_ventanas(monkeypatch)
    usado = []
    c = comprobador(lambda r: usado.append(r) or httpx.Response(200, json=release_json()))
    assert not al_abrir.actualizar_al_abrir({**CONFIG, "comprobar_actualizaciones_app": False}, ["F.exe"],
                                            es_instalada=lambda: True, carpeta=tmp_path, comprobador=c,
                                            instalar=Instalador())
    assert usado == []


def test_huella_que_no_cuadra_no_instala(tmp_path):
    inst = Instalador()
    assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path,
                                            comprobador=github_con_version(),
                                            transporte_descarga=transporte_descarga(b"MZ otra cosa"),
                                            instalar=inst)
    assert inst.llamadas == []
    assert not list(tmp_path.glob("*.exe"))


def test_abrir_sin_actualizar_corta_la_descarga(tmp_path, monkeypatch):
    espera = threading.Event()
    original = al_abrir.VentanaActualizando

    def pulsa_saltar(etiqueta):
        v = original(etiqueta)
        QTimer.singleShot(50, v.boton.click)
        return v

    monkeypatch.setattr(al_abrir, "VentanaActualizando", pulsa_saltar)
    monkeypatch.setattr(descarga, "ESPERA_REINTENTO", 0.01)
    inst = Instalador()
    try:
        assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path,
                                                comprobador=github_con_version(),
                                                transporte_descarga=transporte_descarga(espera=espera),
                                                instalar=inst)
    finally:
        espera.set()
    assert inst.llamadas == []


def test_cerrar_la_ventanita_no_cierra_la_aplicacion(tmp_path):
    """Con quitOnLastWindowClosed, cerrar la ventanita dejaba un "salir" en la cola."""
    bajada(tmp_path)
    al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path,
                                 instalar=Instalador(ok=False))
    assert not QApplication.instance().quitOnLastWindowClosed()


def test_un_fallo_inesperado_no_impide_arrancar(tmp_path, monkeypatch):
    def revienta(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(al_abrir, "instalador_listo", revienta)
    assert not al_abrir.actualizar_al_abrir(CONFIG, ["F.exe"], es_instalada=lambda: True, carpeta=tmp_path)


# -- instalador en la bandeja, arranque y ajustes ----------------------------------------


def test_en_la_bandeja_el_setup_va_sin_ventana_y_vuelve_a_la_bandeja(tmp_path):
    normal = instalacion.parametros_instalador(tmp_path / "s.exe")
    assert "/SILENT" in normal and instalacion.PARAMETRO_BANDEJA not in normal
    bandeja = instalacion.parametros_instalador(tmp_path / "s.exe", en_bandeja=True)
    assert "/VERYSILENT" in bandeja and "/SILENT" not in bandeja and instalacion.PARAMETRO_BANDEJA in bandeja
    orden = instalacion._linea_de_ordenes(tmp_path / "s.exe", tmp_path / "Farmadex.exe", en_bandeja=True)
    assert orden.rstrip('"').endswith("--bandeja")
    iss = (RAIZ / "empaquetado" / "instalador.iss").read_text(encoding="utf-8-sig")
    assert 'Parameters: "{code:ArgumentosRelanzar}"' in iss
    assert "'--tras-actualizar'" in iss and "{param:BANDEJA|0}" in iss


def test_main_sale_sin_montar_la_ventana_si_se_lanzo_el_instalador(monkeypatch):
    from farmadex import app as modulo_app
    from farmadex.instancia_unica import InstanciaUnica

    montadas, orden = [], []

    class AplicacionFalsa:
        def __init__(self, *a, **k):
            montadas.append(k)

        def ejecutar(self):
            return 0

    monkeypatch.setattr(modulo_app, "Aplicacion", AplicacionFalsa)
    monkeypatch.setattr(modulo_app, "vigilar_cierre", lambda codigo: None)
    monkeypatch.setattr(InstanciaUnica, "adquirir", lambda self: True)
    monkeypatch.setattr(InstanciaUnica, "escuchar", lambda self: orden.append("escuchar") or True)
    monkeypatch.setattr(InstanciaUnica, "soltar", lambda self: orden.append("soltar"))
    llamadas = []
    monkeypatch.setattr(al_abrir, "actualizar_al_abrir",
                        lambda cfg, args, en_bandeja=False: llamadas.append(en_bandeja) or True)
    assert modulo_app.main(["Farmadex.exe", "--bandeja"]) == 0
    assert llamadas == [True] and montadas == [] and orden == ["escuchar", "soltar"]

    monkeypatch.setattr(al_abrir, "actualizar_al_abrir", lambda cfg, args, en_bandeja=False: False)
    assert modulo_app.main(["Farmadex.exe"]) == 0
    assert len(montadas) == 1


def test_ajustes_tiene_actualizar_al_abrir(monkeypatch, tmp_path):
    from farmadex.ui import pestana_ajustes

    guardados = []
    monkeypatch.setattr(pestana_ajustes, "guardar", lambda cfg: guardados.append(dict(cfg)))
    ajustes = pestana_ajustes.PestanaAjustes()
    casilla = ajustes.actualizar_al_abrir
    assert casilla.text() == "Actualizar al abrir Farmadex"
    ajustes.auto_actualizar.setChecked(True)
    assert casilla.isChecked() and casilla.isEnabled()
    casilla.setChecked(False)
    assert guardados and guardados[-1]["actualizar_al_abrir"] is False
    ajustes.auto_actualizar.setChecked(False)
    assert not casilla.isEnabled()


def test_dns_colgado_no_pasa_del_plazo(monkeypatch):
    """Sin comprobador (como en el arranque real): el DNS colgado, donde los plazos de
    httpx no llegan, ni preparar el cliente, pueden alargar la espera mas alla del plazo."""
    import socket

    from farmadex.online import http

    def dns_colgado(*a, **k):
        time.sleep(5)
        raise OSError("dns colgado (simulado)")

    monkeypatch.setattr(socket, "getaddrinfo", dns_colgado)
    original = http.Cliente.__init__

    def cliente_lento(self, *a, **k):
        time.sleep(0.4)  # crear el cliente (certificados) tambien va dentro del plazo
        original(self, *a, **k)

    monkeypatch.setattr(http.Cliente, "__init__", cliente_lento)
    t0 = time.perf_counter()
    assert al_abrir.consultar_ultima(plazo=0.3) is None
    assert time.perf_counter() - t0 < 0.3 + 0.15


def test_sin_comprobador_la_version_nueva_llega(monkeypatch):
    """El camino del arranque real (sin comprobador) sigue encontrando la version nueva."""
    from farmadex.online import http

    original = http.Cliente.__init__

    def con_github_simulado(self, *a, **k):
        k["transporte"] = httpx.MockTransport(lambda p: httpx.Response(200, json=release_json(), request=p))
        original(self, *a, **k)

    monkeypatch.setattr(http.Cliente, "__init__", con_github_simulado)
    v = al_abrir.consultar_ultima(plazo=3.0)
    assert v is not None and v.etiqueta == "v9.9.9"
