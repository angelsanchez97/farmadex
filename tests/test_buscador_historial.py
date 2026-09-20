"""El boton "Atras" del buscador.

Lo reporto un usuario: el boton no hacia nada. El historial se borraba al
cambiar de resultado en la lista y cada busqueda nueva lo dejaba con un solo
elemento, asi que solo servia navegando por los enlaces de una misma ficha.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture()
def aplicacion():
    """Una sola QApplication para todas las pruebas de este fichero."""
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def buscador(indice_poblado, monkeypatch, aplicacion):
    """Buscador conectado al indice de prueba, sin pantalla."""
    from farmadex.datos import indice as modulo_indice
    from farmadex.ui.pestana_buscador import PestanaBuscador

    con, _, _ = indice_poblado
    monkeypatch.setattr(modulo_indice, "conectar", lambda *a, **k: con)
    pestana = PestanaBuscador()
    pestana.habilitar(True)
    return pestana


def _buscar(pestana, texto: str) -> None:
    pestana.caja.setText(texto)
    pestana._buscar()


def test_moverse_por_la_lista_cuenta_como_navegar(buscador):
    _buscar(buscador, "ash prime")
    assert buscador.lista.count() >= 2, "hacen falta dos resultados para la prueba"
    primero = buscador._actual
    assert not buscador.atras.isEnabled(), "con una sola ficha vista no hay adonde volver"

    buscador.lista.setCurrentRow(1)
    assert buscador._actual != primero
    assert buscador.atras.isEnabled(), "cambiar de resultado tiene que dejar volver"

    buscador._volver()
    assert buscador._actual == primero


def test_al_volver_se_recupera_la_busqueda_anterior(buscador):
    _buscar(buscador, "sistemas ash prime")
    primero = buscador._actual

    _buscar(buscador, "axi")
    assert buscador._actual != primero
    assert buscador.atras.isEnabled()

    buscador._volver()
    # Sin recuperar el texto, la lista ensenaria las reliquias y la ficha otra cosa.
    assert buscador.caja.text() == "sistemas ash prime"
    assert buscador._actual == primero


def test_el_historial_no_crece_sin_limite(buscador):
    from farmadex.ui.pestana_buscador import MAX_HISTORIAL

    _buscar(buscador, "ash prime")
    ids = [r["item_id"] for r in buscador._resultados]
    for _ in range(MAX_HISTORIAL + 20):
        for item_id in ids:
            buscador.abrir(item_id)
    assert len(buscador._historial) <= MAX_HISTORIAL


def test_abrir_lo_mismo_dos_veces_no_apila(buscador):
    _buscar(buscador, "ash prime")
    actual = buscador._actual
    antes = len(buscador._historial)
    buscador.abrir(actual)
    buscador.abrir(actual)
    assert len(buscador._historial) == antes


def test_volver_sin_historial_no_revienta(buscador):
    buscador._volver()  # nada que hacer, pero no puede lanzar
    assert buscador.atras.isEnabled() is False
