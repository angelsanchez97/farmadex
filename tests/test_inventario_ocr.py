"""Lector de Inventario/Fundicion y lector pasivo, sin juego.

Las lineas sinteticas calcan lo que RapidOCR leyo de una captura real de internet
(inventario en ingles a 1280x720, ver tests/fixtures/capturas_internet/README.md):
"180WNED" por "18 OWNED", "Q9OWNED" con el icono leido como letra, nombres
partidos en dos o tres lineas. Con la captura real en disco, se lee de verdad.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from farmadex.captura import inventario as INV
from farmadex.captura import perfil_equipo as PE
from farmadex.captura.ocr import Casador, Leido, MotorOCR

from conftest import FIXTURES
from test_captura import _insertar

CAPTURAS = FIXTURES / "capturas_internet"


@pytest.fixture()
def catalogo_inventario(con):
    ids = _insertar(con, [
        ("/w/NovaPrime", "Nova Prime", "Nova Prime", "Warframes", None, None),
        ("/w/NovaPrime/Neu", "Neuroptics Blueprint", "Plano de Neuroptica", "Warframes", "/w/NovaPrime", 45),
        ("/w/NovaPrime/Sys", "Systems Blueprint", "Plano de Sistemas", "Warframes", "/w/NovaPrime", 45),
        ("/w/AshPrime", "Ash Prime", "Ash Prime", "Warframes", None, None),
        ("/w/AshPrime/Neu", "Neuroptics Blueprint", "Plano de Neuroptica", "Warframes", "/w/AshPrime", 45),
        ("/p/VastoPrime", "Vasto Prime", "Vasto Prime", "Secondary", None, None),
        ("/p/VastoPrime/Rec", "Receiver", "Receptor", "Secondary", "/p/VastoPrime", 45),
        ("/w/Valkyr", "Valkyr", "Valkyr", "Warframes", None, None),
        ("/w/Valkyr/Chs", "Chassis", "Chasis", "Warframes", "/w/Valkyr", None),
        ("/r/Ferrite", "Ferrite", "Ferrita", "Resources", None, None),
    ])
    return con, ids


def _l(texto, x, y, ancho=100, alto=17, conf=0.85):
    return Leido(texto, x, y, ancho, alto, conf)


def test_inventario_sintetico_como_lo_leyo_el_ocr(catalogo_inventario):
    con, _ = catalogo_inventario
    lineas = [
        _l("INVENTORY", 566, 36, 148, 24, 0.89),
        _l("SORTBY:OWNED", 925, 112, 144, 19),
        _l("3.500", 284, 149, 47),  # ducados: no es una cantidad
        _l("120WNED", 287, 165, 82, 21, 0.78),
        _l("NOVAPRIME", 261, 219, 99),
        _l("NEUROPTICS", 262, 235, 99),
        _l("BLUEPRINT", 261, 249, 87),
        _l("Q9OWNED", 460, 168, 91, 17, 0.74),
        _l("VASTO PRIME", 454, 233, 106, 19),
        _l("RECEIVER", 452, 246, 78, 22),
        _l("7OWNED", 672, 164, 76, 23, 0.69),
        _l("ASHPRIME", 648, 219, 87),
        _l("NEUROPTICS", 649, 235, 99),
        _l("BLUEPRINT", 649, 249, 87),
        _l("EXIT", 1167, 666, 42, 22),
    ]
    pagina = INV.interpretar_lineas(lineas, INV.casador_inventario(con), con)
    assert pagina.pantalla == "inventario"
    por_nombre = {c.unique_name: c for c in pagina.cantidades}
    assert por_nombre["/w/NovaPrime/Neu"].cantidad == 12
    assert por_nombre["/w/NovaPrime/Neu"].fiable
    assert por_nombre["/w/AshPrime/Neu"].cantidad == 7
    # El icono se leyo como "Q": la cifra vale pero la lectura no es fiable.
    assert por_nombre["/p/VastoPrime/Rec"].cantidad == 9
    assert not por_nombre["/p/VastoPrime/Rec"].fiable
    assert {c.unique_name for c in pagina.fiables} == {"/w/NovaPrime/Neu", "/w/AshPrime/Neu"}


def test_sin_titulo_no_se_lee_nada(catalogo_inventario):
    con, _ = catalogo_inventario
    lineas = [_l("120WNED", 287, 165), _l("NOVAPRIME", 261, 219), _l("NEUROPTICS", 262, 235)]
    pagina = INV.interpretar_lineas(lineas, INV.casador_inventario(con), con)
    assert pagina.pantalla is None and pagina.cantidades == []


def test_cifra_sola_o_ducados_no_cuentan_como_cantidad(catalogo_inventario):
    con, _ = catalogo_inventario
    lineas = [_l("INVENTORY", 566, 36, conf=0.9), _l("2,500", 85, 149), _l("HIKOU PRIME", 67, 235)]
    pagina = INV.interpretar_lineas(lineas, INV.casador_inventario(con), con)
    assert pagina.pantalla == "inventario" and pagina.cantidades == []


def test_fundicion_planos_al_pie_de_la_placa(catalogo_inventario):
    con, _ = catalogo_inventario
    lineas = [
        _l("FOUNDRY", 900, 30, 120, 26, 0.9),
        _l("VALKYR CHASSIS", 120, 110, 180, 18),
        _l("4,071/500", 150, 140, 80),  # material con icono: no se sabe cual es
        _l("1 BLUEPRINT LEFT", 120, 200, 140, 14),
        _l("12 HOURS", 300, 200, 80, 14),
        _l("BUILD", 500, 200, 60, 14),
    ]
    pagina = INV.interpretar_lineas(lineas, INV.casador_inventario(con), con)
    assert pagina.pantalla == "fundicion"
    assert [(c.unique_name, c.cantidad, c.fiable) for c in pagina.cantidades] == [("/w/Valkyr/Chs", 1, True)]


@pytest.mark.parametrize("texto, esperado", [
    ("18 OWNED", 18), ("180WNED", 18), ("18OWNED", 18), ("50WNED", 5), ("Q9OWNED", 9),
    ("1,234 OWNED", 1234), ("3 EN POSESION", 3), ("POSEIDOS: 4", 4), ("TIENES 2", 2),
])
def test_patron_de_cantidad_poseida(texto, esperado):
    c = INV._como_cantidad(_l(texto, 0, 0), "inventario")
    assert c is not None and c.cantidad == esperado


@pytest.mark.parametrize("texto", ["2,500", "4,071/500", "OWNED", "SORT BY: OWNED"])
def test_lo_que_no_es_cantidad(texto):
    assert INV._como_cantidad(_l(texto, 0, 0), "inventario") is None


# --- captura real de internet (si esta en disco) -------------------------------------


@pytest.mark.skipif(
    not (CAPTURAS / "inventario_prime_parts_yt_720p.jpg").exists(),
    reason="captura de internet no presente (no se publica)",
)
def test_inventario_real_de_internet_720p_en_ingles(catalogo_inventario):
    """Miniatura de YouTube a 1280x720, ingles. Es lo mas parecido que hay a una
    pantalla real: se comprueba lo que SI se lee bien y se deja constancia de lo
    que no (el icono leido como cifra), sin dar la pantalla por calibrada."""
    import cv2

    con, _ = catalogo_inventario
    imagen = cv2.imread(str(CAPTURAS / "inventario_prime_parts_yt_720p.jpg"))
    motor = MotorOCR("rapidocr")
    # A 720p el reescalado 1,5x pierde una linea de cantidad; tal cual se leen las cuatro.
    pagina = INV.leer_pagina(imagen, motor, INV.casador_inventario(con), con, escala=1.0)
    assert pagina.pantalla == "inventario"
    fiables = {c.unique_name: c.cantidad for c in pagina.fiables}
    assert fiables == {"/w/NovaPrime/Neu": 12, "/w/AshPrime/Neu": 7, "/w/NovaPrime/Sys": 5}
    dudosas = {c.unique_name: c.cantidad for c in pagina.cantidades if not c.fiable}
    assert dudosas == {"/p/VastoPrime/Rec": 9}  # "Q9OWNED": el icono se leyo como letra


# --- lector pasivo -------------------------------------------------------------------


def test_lector_pasivo_usa_un_solo_ocr_para_las_dos_lecturas(catalogo_inventario, monkeypatch):
    from farmadex.captura.lector_pasivo import LectorPasivo
    from farmadex.datos import indice

    con, _ = catalogo_inventario
    monkeypatch.setattr(indice, "hay_indice", lambda *a, **k: True)

    class Prestada:
        def __getattr__(self, nombre):
            return getattr(con, nombre)

        def close(self):
            pass

    monkeypatch.setattr(indice, "conectar", lambda *a, **k: Prestada())
    from farmadex.captura import pantalla

    monkeypatch.setattr(pantalla, "declarar_dpi", lambda: None)
    MotorOCR.descargar()
    llamadas = []
    lineas_inventario = [
        _l("INVENTORY", 566, 36, 148, 24, 0.89), _l("120WNED", 287, 165, 82, 21, 0.78),
        _l("NOVAPRIME", 261, 219, 99), _l("NEUROPTICS", 262, 235, 99), _l("BLUEPRINT", 261, 249, 87),
    ]
    monkeypatch.setattr(MotorOCR, "leer", lambda self, imagen: llamadas.append(1) or list(lineas_inventario))
    monkeypatch.setattr(MotorOCR, "precalentar", lambda self: None)

    lector = LectorPasivo("rapidocr", perfil=True, inventario=True)
    perfiles, inventarios = [], []
    lector.pagina_perfil.connect(perfiles.append)
    lector.pagina_inventario.connect(inventarios.append)
    imagen = np.zeros((1440, 2560, 3), np.uint8)
    perfil, inventario = lector.leer_imagen(imagen)

    assert llamadas == [1]  # un OCR para las dos interpretaciones
    assert perfil is None and inventario is not None
    assert inventarios and inventarios[0].pantalla == "inventario"
    assert [c.cantidad for c in inventarios[0].fiables] == [12]
    assert lector.lecturas == 1

    # Con el inventario apagado la misma pantalla no produce nada.
    lector.activar_inventario(False)
    assert lector.leer_imagen(imagen) == (None, None)
    MotorOCR.descargar()


def test_lector_pasivo_no_mira_el_arsenal_ni_la_pausa_segun_eelog():
    from farmadex.captura.lector_pasivo import LectorPasivo

    lector = LectorPasivo.__new__(LectorPasivo)
    lector.pantalla_log = None
    lector.detector = PE.DetectorPagina()
    assert lector.merece_mirar()
    lector.pantalla_juego("abierta", "arsenal")
    assert not lector.merece_mirar()
    lector.pantalla_juego("pausa", "")
    assert not lector.merece_mirar()
    lector.pantalla_juego("abierta", "perfil")
    assert lector.merece_mirar()
    lector.pantalla_juego("abierta", "?PantallaNueva")
    assert lector.merece_mirar()  # sin clasificar: decide el OCR
    lector.pantalla_juego("cerrada", "")
    assert lector.merece_mirar()


def test_casador_restringido_casa_con_umbral_bajo_y_no_conoce_el_resto(catalogo_inventario):
    con, ids = catalogo_inventario
    completo = Casador(con)
    cerrado = completo.restringido({ids["/w/NovaPrime/Neu"], ids["/w/AshPrime/Neu"]})
    item_id, _, _ = cerrado.casar("NOVA PRIM NEUROPTCS BLUEPRNT", 70)
    assert item_id == ids["/w/NovaPrime/Neu"]
    assert cerrado.casar("VASTO PRIME RECEIVER", 70)[0] is None
    assert completo.casar("VASTO PRIME RECEIVER", 80)[0] == ids["/p/VastoPrime/Rec"]
