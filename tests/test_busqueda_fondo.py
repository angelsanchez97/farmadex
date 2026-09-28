"""Buscar en segundo plano: escribir no se atasca y solo se ensena la ultima busqueda."""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest

pytest.importorskip("PySide6")


@pytest.fixture()
def aplicacion():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def _esperar(aplicacion, fondo, condicion=lambda: True, segundos=5.0):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        fondo.esperar(50)
        aplicacion.processEvents()
        if not fondo.ocupada() and condicion():
            return
    raise AssertionError("la busqueda en segundo plano no termino")


def _base(tmp_path):
    ruta = tmp_path / "b.sqlite"
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE t (x TEXT)")
    con.execute("INSERT INTO t VALUES ('hola')")
    con.commit()
    return con


def test_solo_se_entrega_la_ultima_peticion_y_en_el_hilo_de_la_ventana(aplicacion, tmp_path):
    from farmadex.ui.busqueda_fondo import BusquedaEnFondo

    con = _base(tmp_path)
    fondo = BusquedaEnFondo()
    principal = threading.get_ident()
    hilos, entregas = [], []

    def trabajo(n):
        def hacer(c):
            hilos.append(threading.get_ident())
            time.sleep(0.05)
            return (n, c.execute("SELECT x FROM t").fetchone()[0])
        return hacer

    def al_terminar(r):
        entregas.append((r, threading.get_ident()))

    for n in range(4):
        fondo.pedir(con, trabajo(n), al_terminar)
    _esperar(aplicacion, fondo)
    assert entregas == [((3, "hola"), principal)]
    assert hilos and all(h != principal for h in hilos)
    # Las que se quedaron viejas antes de empezar ni se ejecutan.
    assert len(hilos) < 4


def test_cancelar_tira_lo_que_estaba_en_marcha(aplicacion, tmp_path):
    from farmadex.ui.busqueda_fondo import BusquedaEnFondo

    con = _base(tmp_path)
    fondo = BusquedaEnFondo()
    entregas = []
    fondo.pedir(con, lambda c: time.sleep(0.05) or 1, entregas.append)
    fondo.cancelar()
    fondo.esperar(2000)
    aplicacion.processEvents()
    assert entregas == []


def test_con_base_en_memoria_se_hace_en_el_acto(aplicacion):
    from farmadex.ui.busqueda_fondo import BusquedaEnFondo

    con = sqlite3.connect(":memory:")
    entregas = []
    BusquedaEnFondo().pedir(con, lambda c: c.execute("SELECT 7").fetchone()[0], entregas.append)
    assert entregas == [7]


def test_si_falla_en_el_hilo_se_repite_con_la_conexion_de_la_ventana(aplicacion, tmp_path):
    from farmadex.ui.busqueda_fondo import BusquedaEnFondo

    con = _base(tmp_path)
    fondo = BusquedaEnFondo()
    entregas = []

    def trabajo(c):
        if c is not con:
            raise RuntimeError("fallo en el hilo")
        return "en primer plano"

    fondo.pedir(con, trabajo, entregas.append)
    _esperar(aplicacion, fondo, lambda: bool(entregas))
    assert entregas == ["en primer plano"]


# -- Buscar y el modo juego ----------------------------------------------------------------


@pytest.fixture()
def buscador(indice_poblado, monkeypatch, aplicacion, tmp_path):
    from farmadex import config, idiomas
    from farmadex.datos import indice as modulo_indice
    from farmadex.ui.pestana_buscador import PestanaBuscador

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    con, _, _ = indice_poblado
    con.commit()  # el hilo abre su propia conexion: solo ve lo confirmado, como en la app
    monkeypatch.setattr(modulo_indice, "conectar", lambda *a, **k: con)
    pestana = PestanaBuscador()
    pestana.habilitar(True)
    return pestana


def test_teclear_en_buscar_no_busca_en_el_hilo_de_la_ventana(buscador, aplicacion, monkeypatch):
    from farmadex.ui import pestana_buscador as modulo

    principal = threading.get_ident()
    hilos = []
    original = modulo.calcular_busqueda

    def espia(con, texto):
        hilos.append(threading.get_ident())
        return original(con, texto)

    monkeypatch.setattr(modulo, "calcular_busqueda", espia)
    buscador.caja.setText("ash prime")
    assert buscador._temporizador.isActive()
    buscador._temporizador.stop()
    buscador._temporizador.timeout.emit()
    _esperar(aplicacion, buscador._busqueda, lambda: bool(buscador._resultados))
    assert hilos and all(h != principal for h in hilos)
    assert buscador._resultados[0]["nombre_en"] == "Ash Prime"
    # La ficha del primero llega en cuanto se deja de teclear (PAUSA_FICHA_MS).
    _esperar(aplicacion, buscador._busqueda, buscador.hay_ficha, segundos=2.0)


def test_mientras_se_teclea_sale_la_lista_y_la_ficha_espera_a_la_pausa(buscador, aplicacion, monkeypatch):
    """Montar la ficha a cada letra dejaba la caja sin atender las teclas: primero la
    lista, y la ficha del primer resultado cuando se deja de escribir."""
    from farmadex.ui import pestana_buscador as modulo

    abiertas = []
    original = modulo.PestanaBuscador.abrir
    monkeypatch.setattr(modulo.PestanaBuscador, "abrir",
                        lambda self, item_id, recordar=True: abiertas.append(item_id) or original(self, item_id, recordar))
    buscador.caja.setText("ash prime")
    buscador._temporizador.stop()
    buscador._temporizador.timeout.emit()
    _esperar(aplicacion, buscador._busqueda, lambda: bool(buscador._resultados))
    assert buscador.lista.currentRow() == 0
    assert abiertas == []  # aun no: se acaba de teclear
    buscador.caja.setText("ash prime c")  # otra tecla antes de la pausa: la ficha sigue esperando
    assert not buscador._ficha_pendiente.isActive()
    buscador._temporizador.stop()
    buscador.caja.blockSignals(True)
    buscador.caja.setText("ash prime")
    buscador.caja.blockSignals(False)
    buscador._temporizador.timeout.emit()
    _esperar(aplicacion, buscador._busqueda, lambda: bool(abiertas), segundos=2.0)
    assert abiertas == [buscador._resultados[0]["item_id"]]  # una sola ficha, la del primero


def test_una_busqueda_nueva_no_monta_la_ficha_de_la_anterior(buscador, aplicacion, monkeypatch):
    """Al vaciar la lista se "seleccionaban" los resultados viejos y se montaba la ficha del
    primero de la busqueda anterior: hasta 120 ms tirados en cada busqueda."""
    from farmadex.ui import pestana_buscador as modulo

    buscador.caja.setText("ash prime")
    buscador._buscar()
    abiertas = []
    original = modulo.PestanaBuscador.abrir
    monkeypatch.setattr(modulo.PestanaBuscador, "abrir",
                        lambda self, item_id, recordar=True: abiertas.append(item_id) or original(self, item_id, recordar))
    buscador.caja.blockSignals(True)
    buscador.caja.setText("axi a7")
    buscador.caja.blockSignals(False)
    buscador._buscar()
    assert abiertas == [buscador._resultados[0]["item_id"]]


def test_si_se_sigue_escribiendo_la_busqueda_vieja_no_se_ensena(buscador, aplicacion):
    buscador.caja.setText("ash prime")
    buscador._temporizador.stop()
    buscador._temporizador.timeout.emit()
    buscador.caja.blockSignals(True)
    buscador.caja.setText("axi a7")  # lo escrito ya no es lo que se busco
    buscador.caja.blockSignals(False)
    buscador._busqueda.esperar(5000)
    aplicacion.processEvents()
    assert buscador._resultados == []


def test_enter_busca_en_el_acto_y_anula_lo_pendiente(buscador, aplicacion):
    buscador.caja.setText("ash prime")
    buscador._temporizador.stop()
    buscador._temporizador.timeout.emit()
    buscador.caja.blockSignals(True)
    buscador.caja.setText("axi a7")
    buscador.caja.blockSignals(False)
    buscador._enter()
    assert "Axi" in buscador._resultados[0]["nombre_en"]
    buscador._busqueda.esperar(5000)
    aplicacion.processEvents()
    assert "Axi" in buscador._resultados[0]["nombre_en"]


def test_sin_resultados_las_sugerencias_llegan_hechas_del_hilo(buscador, aplicacion, monkeypatch):
    from farmadex.ui import pestana_buscador as modulo

    buscador.caja.setText("como consigo ash")
    buscador._temporizador.stop()
    texto = buscador.caja.text().strip()
    calculado = modulo.calcular_busqueda(buscador.con, texto)
    if calculado["objetos"] or calculado["encontradas"]:
        pytest.skip("con este indice de prueba la frase entera ya encuentra algo")
    buscador._busqueda.pedir(buscador.con, lambda c: modulo.calcular_busqueda(c, texto),
                             lambda r: buscador._aplicar_busqueda(texto, r))
    _esperar(aplicacion, buscador._busqueda)
    llamadas = []
    monkeypatch.setattr(modulo, "buscar_sugerencias", lambda *a: llamadas.append(a) or [])
    assert buscador.sugerencias(texto)  # sale de lo calculado en el hilo
    assert llamadas == []


def test_el_modo_juego_busca_en_segundo_plano(buscador, aplicacion):
    from farmadex.ui.vista_compacta import VistaCompacta

    vista = VistaCompacta(buscador)
    vista.caja.setText("ash prime")
    vista._temporizador.stop()
    vista._temporizador.timeout.emit()
    _esperar(aplicacion, vista._busqueda, lambda: bool(vista._resultados))
    assert vista._resultados[0]["nombre_en"] == "Ash Prime"
    assert vista._datos is not None


def test_el_retardo_entre_teclas_es_corto():
    from farmadex.ui.pestana_buscador import RETARDO_TECLAS_MS

    assert 60 <= RETARDO_TECLAS_MS <= 150


# -- el difuso suelta el GIL y da lo mismo que extract ---------------------------------------


def test_parecidos_da_lo_mismo_que_extract():
    from rapidfuzz import fuzz, process

    from farmadex.datos import indice

    textos = ["serration", "serration", "sierra", "rhino neuroptics", "rhino neuropticas",
              "ash prime systems", "braton prime", "axi a7 relic", "serro", "zzz"]
    for consulta in ("serracion", "rhino neuroptic", "ash prme", "braton"):
        esperado = [
            (i, float(p)) for _, p, i in process.extract(
                consulta, textos, scorer=fuzz.token_sort_ratio, limit=6,
                score_cutoff=indice.CORTE_DIFUSO)
        ]
        assert indice._parecidos(consulta, textos, 6) == esperado
    assert indice._parecidos("x", [], 5) == []
