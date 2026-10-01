"""Foto diaria de precios: consultas sin red, descarga unica, fallos de red y de fichero."""

from __future__ import annotations

import gzip
import hashlib
import json
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from farmadex.online import precios_diarios as pd

CAMPOS = ["venta_min", "venta_mediana", "compra_max", "vendedores", "compradores", "cantidad_venta",
          "min_30d", "max_30d", "media_30d", "volumen_30d", "mediana_30d", "dias_30d", "volumen_48h"]
BASE = "https://github.com/x/y/releases/download/precios/"


def _doc(fecha: str = "2026-09-30T00:40:00Z", extra: int = 0) -> dict:
    objetos = {
        "arcane_energize": {"n": "Arcane Energize", "r": 5, "t": ["arcane_enhancement"], "p": {
            "0": [7, 8, 5, 39, 2, 3787, 3, 10, 7.7, 5518, 8, 29, 471],
            "5": [120, 130, 90, 71, 10, 220, 91, 170, 134.2, 3212, 138.5, 29, 267],
        }},
        "serration": {"n": "Serration", "r": 10, "t": ["mod"], "p": {
            "0": [5, 6, None, 3, 0, 9, 4, 8, 5.5, 40, 5, 12, 2],
            "3": [9, 9, None, 1, 0, 1, None, None, None, None, None, None, None],
        }},
        "lith_a1_relic": {"n": "Lith A1 Relic", "r": None, "s": ["intact", "exceptional", "flawless", "radiant"],
                          "t": ["relic"], "p": {
                              "|intact": [10, 10, 8, 5, 1, 20, 8, 14, 10.5, 60, 10, 20, 4],
                              "|radiant": [25, 30, None, 2, 0, 3, 20, 40, 28, 9, 27, 6, 0]}},
        "ash_prime_set": {"n": "Ash Prime Set", "r": None, "t": ["set"], "p": {
            "": [60, 62, 55, 20, 4, 30, None, None, None, 0, None, 0, 0]}},
    }
    for i in range(extra):
        objetos[f"objeto_{i}"] = {"n": f"Objeto {i}", "r": None, "t": [], "p": {"": [1] * len(CAMPOS)}}
    return {"formato": 1, "fecha": fecha, "plataforma": "pc", "fuente": "warframe.market", "dias": 30,
            "campos": CAMPOS, "resumen": {}, "objetos": objetos}


def _gz(doc: dict) -> bytes:
    return gzip.compress(json.dumps(doc).encode(), mtime=0)


def _version(datos: bytes, fecha: str) -> dict:
    return {"formato": 1, "fecha": fecha, "plataforma": "pc", "objetos": 4, "bytes": len(datos),
            "sha256": hashlib.sha256(datos).hexdigest()}


def _cargada(tmp_path: Path, doc: dict | None = None) -> pd.PreciosDiarios:
    p = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    p.instalar(doc or _doc())
    return p


def _esperar(condicion, segundos: float = 5.0) -> bool:
    """Espera a `condicion()` dejando correr los eventos de Qt (los avisos llegan por ahi)."""
    from PySide6.QtCore import QCoreApplication

    limite = time.time() + segundos
    while not condicion() and time.time() < limite:
        app = QCoreApplication.instance()
        if app is not None:
            app.processEvents()
        time.sleep(0.01)
    return bool(condicion())


class Servidor:
    """GitHub falso: sirve version + fichero; cuenta peticiones; puede bloquear o fallar."""

    def __init__(self, doc: dict | None, fecha: str | None = None):
        self.datos = _gz(doc) if doc else b""
        self.version = _version(self.datos, fecha or (doc or {}).get("fecha", "")) if doc else None
        self.peticiones: list[str] = []
        self.soltar = threading.Event()
        self.soltar.set()
        self.sin_red = False

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        self.peticiones.append(peticion.url.path.rsplit("/", 1)[-1])
        self.soltar.wait(5)
        if self.sin_red:
            raise httpx.ConnectError("sin red", request=peticion)
        if self.version is None:
            return httpx.Response(404)
        if peticion.url.path.endswith(pd.NOMBRE_VERSION):
            return httpx.Response(200, json=self.version)
        return httpx.Response(200, content=self.datos)


def _descargador(p, servidor, ahora="2026-09-30T15:00:00+00:00"):
    reloj = (lambda: datetime.fromisoformat(ahora)) if isinstance(ahora, str) else ahora
    d = pd.Descargador(p, base=BASE, transporte=httpx.MockTransport(servidor), reloj=reloj,
                       azar=random.Random(1))
    p.descargador = d
    p.cargado.set()
    return d


# -- consultas -----------------------------------------------------------------------


def test_buscar_rango_maximo_por_defecto_y_rango_pedido(tmp_path):
    p = _cargada(tmp_path)
    r5 = p.buscar("arcane_energize")
    assert (r5.rango, r5.venta_min, r5.venta_mediana, r5.compra_max) == (5, 120, 130, 90)
    assert (r5.min_30d, r5.max_30d, r5.media_30d, r5.volumen_30d) == (91, 170, 134.2, 3212)
    assert r5.fecha == datetime(2026, 9, 30, 0, 40, tzinfo=timezone.utc)
    assert r5.dias_30d == 29 and r5.volumen_48h == 267 and r5.rango_max == 5
    r0 = p.buscar("arcane_energize", 0)
    assert (r0.rango, r0.venta_min, r0.max_30d) == (0, 7, 10)
    assert p.buscar("arcane_energize", 3) is None  # ese rango no tiene nada: sin datos, no un precio inventado
    assert p.rangos("arcane_energize") == [0, 5]
    assert p.rangos("ash_prime_set") == [] and p.rangos("no_existe") == []


def test_sin_datos_en_rango_maximo_usa_el_mas_alto_con_datos(tmp_path):
    p = _cargada(tmp_path)
    s = p.buscar("serration")  # rango maximo 10 sin ordenes ni ventas
    assert s.rango == 3 and s.venta_min == 9 and s.min_30d is None
    assert p.buscar("serration", 10) is None


def test_subtipos_reliquias_y_objetos_sin_rango(tmp_path):
    p = _cargada(tmp_path)
    assert p.buscar("lith_a1_relic").subtipo == "intact"
    assert p.buscar("lith_a1_relic").venta_min == 10
    assert p.buscar("lith_a1_relic", subtipo="radiant").venta_min == 25
    assert p.subtipos("lith_a1_relic")[0] == "intact"
    s = p.buscar("ash_prime_set")
    assert s.rango is None and s.venta_min == 60 and s.min_30d is None and s.volumen_30d == 0
    assert p.buscar("ash_prime_set", 0).venta_min == 60  # pedir rango a algo sin rangos no rompe
    assert p.buscar("no_existe") is None


def test_otra_plataforma_no_da_precios_de_pc(tmp_path):
    p = pd.PreciosDiarios(carpeta=tmp_path, plataforma="ps4")
    p.instalar(_doc())
    assert not p.disponible and p.buscar("arcane_energize") is None and p.rangos("arcane_energize") == []


def test_buscar_es_instantaneo_con_catalogo_grande(tmp_path):
    p = _cargada(tmp_path, _doc(extra=5000))
    slugs = [f"objeto_{i}" for i in range(5000)]
    t0 = time.perf_counter()
    for s in slugs:
        p.buscar(s)
    frio = (time.perf_counter() - t0) / len(slugs)
    t0 = time.perf_counter()
    for _ in range(10):
        for s in slugs:
            p.buscar(s)
    caliente = (time.perf_counter() - t0) / (10 * len(slugs))
    assert frio < 1e-4 and caliente < 1e-5, (frio, caliente)


def test_precios_no_bloquea_y_avisa_al_cargar(tmp_path, monkeypatch):
    (tmp_path / pd.NOMBRE).write_bytes(_gz(_doc(extra=3000)))
    lenta = pd.PreciosDiarios.cargar_local

    def cargar_lento(self):
        time.sleep(0.3)
        return lenta(self)

    monkeypatch.setattr(pd.PreciosDiarios, "cargar_local", cargar_lento)
    instancia = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    pd._reiniciar_para_pruebas(instancia)
    avisos = []
    try:
        instancia.al_actualizar(lambda: avisos.append(1))
        t0 = time.perf_counter()
        p = pd.precios()
        assert time.perf_counter() - t0 < 0.05
        assert p is instancia and p.buscar("arcane_energize") is None  # aun cargando: sin datos
        assert p.cargado.wait(5)
        assert _esperar(lambda: avisos) and avisos == [1]
        assert p.buscar("arcane_energize").venta_min == 120
    finally:
        pd._reiniciar_para_pruebas(None)


def test_fichero_local_corrupto_no_rompe(tmp_path):
    (tmp_path / pd.NOMBRE).write_bytes(b"\x1f\x8b esto no es gzip")
    p = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    assert p.cargar_local() is False
    assert p.cargado.is_set() and p.problema_local and p.buscar("arcane_energize") is None
    # Un JSON valido pero de otro formato tampoco se usa.
    (tmp_path / pd.NOMBRE).write_bytes(_gz({**_doc(), "formato": 99}))
    assert pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc").cargar_local() is False


# -- descarga ---------------------------------------------------------------------------


def test_descarga_nueva_guarda_atomico_y_avisa(tmp_path):
    p = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    avisos = []
    p.al_actualizar(lambda: avisos.append(p.fecha))
    servidor = Servidor(_doc("2026-09-30T00:40:00Z"))
    d = _descargador(p, servidor)
    assert d.actualizar().esperar(10) == "nuevo"
    assert p.buscar("arcane_energize").venta_min == 120 and _esperar(lambda: avisos)
    assert (tmp_path / pd.NOMBRE).read_bytes() == servidor.datos
    assert json.loads((tmp_path / pd.NOMBRE_VERSION).read_text())["sha256"] == servidor.version["sha256"]
    assert not list(tmp_path.glob("*.tmp"))
    # Otra instancia (siguiente arranque) lee lo guardado.
    otra = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    assert otra.cargar_local() and otra.fecha == p.fecha
    # Ya al dia: solo se mira la version, no se baja el grande otra vez.
    servidor.peticiones.clear()
    assert d.actualizar().esperar(10) == "al_dia"
    assert servidor.peticiones == [pd.NOMBRE_VERSION] and d.descargas == 1


def test_manual_y_automatica_a_la_vez_una_sola_descarga(tmp_path):
    p = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    servidor = Servidor(_doc())
    servidor.soltar.clear()  # la primera peticion se queda esperando
    d = _descargador(p, servidor)
    automatica = d.actualizar(manual=False)
    time.sleep(0.1)
    manual = p.actualizar_ahora()
    assert manual is automatica  # el boton se une a la que ya esta en marcha
    servidor.soltar.set()
    assert manual.esperar(10) == "nuevo"
    assert d.descargas == 1 and servidor.peticiones.count(pd.NOMBRE) == 1


def test_sin_red_sigue_con_lo_anterior_y_reintenta(tmp_path):
    p = _cargada(tmp_path, _doc("2026-09-29T00:40:00Z"))
    servidor = Servidor(_doc())
    servidor.sin_red = True
    d = _descargador(p, servidor, "2026-09-30T15:00:00+00:00")
    assert d.actualizar().esperar(10) == "sin_red"
    assert p.buscar("arcane_energize").venta_min == 120  # la de ayer, con su fecha
    assert p.fecha.date().isoformat() == "2026-09-29"
    ahora = datetime.fromisoformat("2026-09-30T15:00:00+00:00")
    primero = d.siguiente(ahora) - ahora
    assert timedelta(minutes=5) <= primero <= timedelta(minutes=7)
    assert d.actualizar().esperar(10) == "sin_red"
    assert d.siguiente(ahora) - ahora >= timedelta(minutes=10)  # se espacian los reintentos


def test_sin_asset_en_la_release(tmp_path):
    p = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    d = _descargador(p, Servidor(None))
    assert d.actualizar().esperar(10) == "aun_no_hay"
    assert p.buscar("arcane_energize") is None
    ahora = datetime.fromisoformat("2026-09-30T15:00:00+00:00")
    assert timedelta(minutes=15) <= d.siguiente(ahora) - ahora <= timedelta(minutes=30)


def test_la_release_aun_tiene_la_de_ayer(tmp_path):
    p = _cargada(tmp_path, _doc("2026-09-29T00:40:00Z"))
    servidor = Servidor(_doc("2026-09-29T00:40:00Z"))
    d = _descargador(p, servidor, "2026-09-30T00:10:00+00:00")
    assert d.actualizar().esperar(10) == "aun_no_hay"
    assert servidor.peticiones == [pd.NOMBRE_VERSION] and d.descargas == 0


def test_huella_que_no_cuadra_o_fichero_roto_no_se_instalan(tmp_path):
    p = _cargada(tmp_path, _doc("2026-09-29T00:40:00Z"))
    servidor = Servidor(_doc("2026-09-30T00:40:00Z"))
    servidor.version["sha256"] = "0" * 64  # el workflow estaba subiendo el fichero
    d = _descargador(p, servidor)
    assert d.actualizar().esperar(10) == "aun_no_hay"
    assert p.fecha.date().isoformat() == "2026-09-29" and not (tmp_path / pd.NOMBRE).exists()
    servidor.datos = b"basura"
    servidor.version = _version(servidor.datos, "2026-09-30T00:40:00Z")
    assert d.actualizar().esperar(10) == "error"
    assert p.fecha.date().isoformat() == "2026-09-29"
    servidor.version["formato"] = 2
    assert d.actualizar().esperar(10) == "error"


def test_otra_plataforma_no_descarga(tmp_path):
    p = pd.PreciosDiarios(carpeta=tmp_path, plataforma="xbox")
    servidor = Servidor(_doc())
    d = _descargador(p, servidor)
    assert d.actualizar().esperar(10) == "otra_plataforma" and not servidor.peticiones


# -- horario ------------------------------------------------------------------------------


def test_siguiente_medianoche_es_estrictamente_posterior():
    exacta = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert pd.siguiente_medianoche(exacta) == datetime(2026, 10, 2, tzinfo=timezone.utc)
    assert pd.siguiente_medianoche(exacta - timedelta(microseconds=1)) == exacta


def test_a_las_00_00_exactas_espera_el_margen(tmp_path):
    p = _cargada(tmp_path, _doc("2026-09-30T00:40:00Z"))
    d = _descargador(p, Servidor(_doc()))
    exacta = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    for _ in range(50):
        cuando = d.siguiente(exacta, primera=True)
        assert exacta + timedelta(minutes=5) <= cuando <= exacta + timedelta(minutes=20)
    # Un segundo antes, con la foto de hoy: toca justo tras la siguiente medianoche, con margen.
    antes = exacta - timedelta(seconds=1)
    cuando = d.siguiente(antes)
    assert exacta + timedelta(minutes=5) <= cuando <= exacta + timedelta(minutes=20)
    # Al abrir por la tarde con la de ayer: enseguida.
    tarde = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
    assert d.siguiente(tarde, primera=True) - tarde <= timedelta(seconds=5)


def test_programador_baja_al_abrir_si_lo_local_es_de_otro_dia(tmp_path):
    (tmp_path / pd.NOMBRE).write_bytes(_gz(_doc("2026-09-29T00:40:00Z")))
    p = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    servidor = Servidor(_doc("2026-09-30T00:40:00Z"))
    inicio_real = time.monotonic()
    base = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    d = pd.Descargador(p, base=BASE, transporte=httpx.MockTransport(servidor),
                       reloj=lambda: base + timedelta(seconds=time.monotonic() - inicio_real),
                       azar=random.Random(2))
    p.descargador = d
    d.arrancar()
    try:
        deadline = time.time() + 15
        while d.descargas == 0 and time.time() < deadline:
            time.sleep(0.05)
        assert d.descargas == 1 and p.fecha.date().isoformat() == "2026-09-30"
        deadline = time.time() + 5
        while (d.proximo_intento is None or d.proximo_intento < base + timedelta(hours=1)) \
                and time.time() < deadline:
            time.sleep(0.05)
        # Con la de hoy ya dentro, lo siguiente es mañana tras las 00:00 UTC.
        assert d.proximo_intento.date().isoformat() == "2026-10-01"
    finally:
        d.detener()


def test_iniciar_no_toca_la_red_en_pruebas(monkeypatch):
    llamado = []
    monkeypatch.setattr(pd.Descargador, "arrancar", lambda self: llamado.append(1))
    pd.iniciar()
    assert not llamado


# -- panel de Ajustes ----------------------------------------------------------------------


def test_panel_precios_cuenta_atras_y_fecha(qapp_precios, tmp_path):
    from farmadex.ui import panel_precios as pp

    assert pp.texto_cuenta_atras(datetime(2026, 9, 30, 21, 30, tzinfo=timezone.utc),
                                 datetime(2026, 10, 1, tzinfo=timezone.utc)) == "02:30"
    assert pp.texto_cuenta_atras(datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
                                 datetime(2026, 10, 2, tzinfo=timezone.utc)) == "24:00"
    vacio = pd.PreciosDiarios(carpeta=tmp_path, plataforma="pc")
    vacio.cargado.set()
    reloj = lambda: datetime(2026, 9, 30, 22, 15, 30, tzinfo=timezone.utc)  # noqa: E731
    panel = pp.PanelPrecios(precios=vacio, reloj=reloj)
    assert "en vivo" in panel.fecha.texto_completo() or "vivo" in panel.fecha.text()
    assert panel.cuenta.text().endswith("01:45")
    hilo = threading.Thread(target=vacio.instalar, args=(_doc("2026-09-30T00:40:00Z"),))
    hilo.start()  # llega desde otro hilo, como una descarga: el observador repinta en el de Qt
    hilo.join()
    assert _esperar(lambda: "warframe.market" in panel.fecha.text())
    assert "warframe.market" in panel.fecha.text()
    panel.deleteLater()


@pytest.fixture()
def qapp_precios():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_mods_con_variante_juntan_ordenes_y_ventas_cerradas(tmp_path):
    doc = _doc()
    doc["objetos"]["vitality"] = {"n": "Vitality", "r": 10, "s": ["regular", "atragraph"], "t": ["mod"], "p": {
        "10": [None, None, None, None, None, None, 15, 54, 36.4, 188, 39, 30, 17],
        "10|regular": [40, 45, 20, 9, 1, 23, None, None, None, None, None, None, None],
        "10|atragraph": [250, 250, None, 1, 0, 1, None, None, None, None, None, None, None],
        "0": [None, None, None, None, None, None, 2, 5, 2.6, 14, 2.5, 8, 3],
    }}
    p = _cargada(tmp_path, doc)
    v = p.buscar("vitality")
    assert (v.rango, v.subtipo, v.venta_min, v.min_30d, v.max_30d, v.volumen_30d) == (10, "regular", 40, 15, 54, 188)
    rara = p.buscar("vitality", subtipo="atragraph")
    assert rara.venta_min == 250 and rara.min_30d is None  # las ventas cerradas no se le atribuyen
    r0 = p.buscar("vitality", 0)
    assert r0.venta_min is None and r0.min_30d == 2
    assert p.rangos("vitality") == [0, 10]
