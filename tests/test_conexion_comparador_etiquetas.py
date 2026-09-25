"""El veredicto del comparador tiene que llegar a las etiquetas del overlay, sin
abrir el juego: se conecta `ServicioComparador.veredicto` a `EtiquetasRecompensas`
igual que hace `VentanaOverlay._arrancar_comparador` / `_veredicto_recompensas`,
y se comprueba que la marca de "mejor" aparece sobre lo que ya estaba pintado.
"""

import os
import sqlite3
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex.captura.comparador import ServicioComparador  # noqa: E402
from farmadex.captura.reliquias import Recompensa  # noqa: E402
from farmadex.online.market import Orden, Precios  # noqa: E402
from farmadex.ui.etiquetas import COLOR_MEJOR, COLOR_MEJOR_DUDOSO, EtiquetasRecompensas  # noqa: E402

ITEMS = [
    (1, "/Lotus/A/Systems", "Ash Prime Systems", "Warframes", 1, 100, "ash_prime_systems"),
    (2, "/Lotus/B/Barrel", "Braton Prime Barrel", "Primary", 1, 15, "braton_prime_barrel"),
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def indice_con(con):
    for iid, unico, nombre, categoria, comerciable, ducados, slug in ITEMS:
        con.execute(
            "INSERT INTO items (id, unique_name, nombre_en, categoria, comerciable, ducados, market_slug) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (iid, unico, nombre, categoria, comerciable, ducados, slug),
        )
    con.commit()
    return con


def _r(item_id: int, nombre: str) -> Recompensa:
    return Recompensa(item_id=item_id, nombre=nombre, texto_ocr=nombre.upper(), caja=(item_id * 300, 200, 260, 60))


def _mercado():
    tabla = {
        "ash_prime_systems": Precios(slug="ash_prime_systems", ventas=[Orden(45, 1, "u", "ingame")]),
        "braton_prime_barrel": Precios(slug="braton_prime_barrel", ventas=[Orden(4, 1, "u", "ingame")]),
    }
    return SimpleNamespace(precios=lambda slug: tabla.get(slug), cerrar=lambda: None)


def _cablear(indice_con, monkeypatch, escuadra=False):
    """Monta servicio + etiquetas conectados igual que `VentanaOverlay`, sin BD real en disco."""
    import farmadex.datos.indice as indice_mod

    monkeypatch.setattr(indice_mod, "conectar", lambda *a, **k: indice_con)
    servicio = ServicioComparador(escuadra=escuadra, crear_market=_mercado)
    etiquetas = EtiquetasRecompensas()
    servicio.veredicto.connect(etiquetas.marcar_veredicto)
    return servicio, etiquetas


def test_el_veredicto_marca_la_mejor_etiqueta_ya_pintada(app, indice_con, monkeypatch):
    servicio, etiquetas = _cablear(indice_con, monkeypatch)
    recompensas = [_r(1, "Ash Prime Systems"), _r(2, "Braton Prime Barrel")]

    # Paso 1, lo rapido: las etiquetas ya se ven con solo lo que trae el OCR.
    etiquetas.mostrar(recompensas, {})
    assert not any(r.mejor for r in etiquetas.recompensas)

    # Paso 2, lo caro: el veredicto llega por señal, como desde el hilo del comparador.
    servicio.comparar(recompensas)

    marcada = next(r for r in etiquetas.recompensas if r.item_id == 1)
    sin_marcar = next(r for r in etiquetas.recompensas if r.item_id == 2)
    assert marcada.mejor and not sin_marcar.mejor
    assert marcada.valor == 45.0
    assert etiquetas._seguro is True


def test_veredicto_dudoso_se_distingue_del_seguro(app, indice_con, monkeypatch):
    """Con precios casi empatados el veredicto no es seguro: la marca tiene que verse distinta."""
    con = indice_con
    con.execute(
        "UPDATE items SET ducados = 45, market_slug = 'braton_prime_barrel' WHERE id = 2"
    )
    con.commit()

    def mercado():
        tabla = {
            "ash_prime_systems": Precios(slug="x", ventas=[Orden(45, 1, "u", "ingame")]),
            "braton_prime_barrel": Precios(slug="x", ventas=[Orden(43, 1, "u", "ingame")]),
        }
        return SimpleNamespace(precios=lambda slug: tabla.get(slug), cerrar=lambda: None)

    import farmadex.datos.indice as indice_mod

    monkeypatch.setattr(indice_mod, "conectar", lambda *a, **k: con)
    # "Equilibrado" mide el empate por valor (45p contra 43p). Con "Lo que me falta", el que
    # viene por defecto, el empate de platino lo resuelven los ducados (100 contra 45).
    servicio = ServicioComparador(escuadra=False, crear_market=mercado, prioridad="equilibrado")
    etiquetas = EtiquetasRecompensas()
    servicio.veredicto.connect(etiquetas.marcar_veredicto)

    recompensas = [_r(1, "Ash Prime Systems"), _r(2, "Braton Prime Barrel")]
    etiquetas.mostrar(recompensas, {})
    servicio.comparar(recompensas)

    assert etiquetas._seguro is False
    assert any(r.mejor for r in etiquetas.recompensas)
    # El color de la marca insegura es distinto del seguro: no se confunden a simple vista.
    assert COLOR_MEJOR_DUDOSO != COLOR_MEJOR


def test_veredicto_de_otra_pantalla_no_se_pinta_encima(app, indice_con, monkeypatch):
    """Si llega tarde y las etiquetas ya son de otra reliquia, se descarta en vez de mezclar."""
    servicio, etiquetas = _cablear(indice_con, monkeypatch)
    primera = [_r(1, "Ash Prime Systems"), _r(2, "Braton Prime Barrel")]
    etiquetas.mostrar(primera, {})

    # Cambia lo que se ve (otra reliquia) antes de que responda la primera comparacion.
    otra = [_r(1, "Ash Prime Systems")]
    etiquetas.mostrar(otra, {})
    servicio.comparar(primera)

    assert not any(r.mejor for r in etiquetas.recompensas)


def test_sin_datos_para_decidir_no_marca_ninguna_al_azar(app, monkeypatch, con):
    """Ninguna de las dos tiene precio ni ducados: no se elige una al azar."""
    con.execute(
        "INSERT INTO items (id, unique_name, nombre_en, categoria, comerciable) "
        "VALUES (9, '/Lotus/X', 'Pieza X', 'Warframes', 1)"
    )
    con.execute(
        "INSERT INTO items (id, unique_name, nombre_en, categoria, comerciable) "
        "VALUES (10, '/Lotus/Y', 'Pieza Y', 'Warframes', 1)"
    )
    con.commit()
    import farmadex.datos.indice as indice_mod

    monkeypatch.setattr(indice_mod, "conectar", lambda *a, **k: con)

    def _sin_red():
        raise RuntimeError("sin red")

    servicio = ServicioComparador(escuadra=False, crear_market=_sin_red)
    etiquetas = EtiquetasRecompensas()
    servicio.veredicto.connect(etiquetas.marcar_veredicto)

    recompensas = [_r(9, "Pieza X"), _r(10, "Pieza Y")]
    etiquetas.mostrar(recompensas, {})
    servicio.comparar(recompensas)

    assert not any(r.mejor for r in etiquetas.recompensas)
    assert all(r.nota for r in etiquetas.recompensas)
