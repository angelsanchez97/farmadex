"""Las piezas de la autoprueba (farmadex/autoprueba.py) que no necesitan la ventana entera.

La pasada completa (`Farmadex.exe --autoprueba <carpeta>`) tarda minutos y necesita el
indice real y los bancos de capturas: no es para la suite. Aqui se comprueba lo que la
hace fiable: que lee bien sus opciones, que la pantalla simulada recorta como una captura
de verdad y que la red simulada contesta sin salir del PC.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import numpy as np
import pytest

from farmadex import autoprueba as A

RAIZ = Path(__file__).resolve().parents[1]


def test_lee_la_carpeta_y_las_opciones(tmp_path):
    op = A._leer_argumentos(["--autoprueba", str(tmp_path / "salida"), "--capturas", "a", "--capturas", "b",
                             "--hover", "h", "--nucleos", "6", "--carga", "4", "--solo", "build,buscar",
                             "--indice", "i.sqlite", "--red-fixtures", "f", "--etiqueta", "PC normal"])
    assert op["carpeta"] == (tmp_path / "salida").resolve()
    assert op["capturas"] == ["a", "b"] and op["hover"] == ["h"]
    assert op["nucleos"] == 6 and op["carga"] == 4
    assert op["solo"] == {"build", "buscar"}
    assert op["indice"] == "i.sqlite" and op["red_fixtures"] == "f" and op["etiqueta"] == "PC normal"


def test_sin_carpeta_no_arranca():
    with pytest.raises(SystemExit):
        A._leer_argumentos(["--autoprueba"])


def test_la_mascara_de_nucleos_coge_nucleos_distintos(monkeypatch):
    monkeypatch.setattr(A.os, "cpu_count", lambda: 16)
    mascara = A._mascara_nucleos(6)
    assert bin(mascara).count("1") == 6
    assert mascara == 0b010101010101  # los logicos pares: un nucleo fisico cada uno


def test_la_pantalla_simulada_recorta_y_rellena_fuera_de_la_imagen():
    from farmadex.captura.pantalla import Region

    sim = A.PantallaSimulada()
    imagen = np.arange(20 * 30 * 3, dtype=np.uint8).reshape(20, 30, 3)
    sim.poner(imagen)
    assert sim.cursor == (15, 10)
    dentro = sim.recortar(Region(5, 4, 10, 6))
    assert np.array_equal(dentro, imagen[4:10, 5:15])
    fuera = sim.recortar(Region(25, 15, 10, 10))  # medio fuera: lo de fuera, negro
    assert fuera.shape == (10, 10, 3)
    assert np.array_equal(fuera[:5, :5], imagen[15:20, 25:30]) and not fuera[5:, 5:].any()
    sim.poner(None)
    assert sim.recortar(Region(0, 0, 5, 5)) is None


def _peticion(url, metodo="GET"):
    return httpx.Request(metodo, url)


def test_la_red_simulada_contesta_datos_al_dia_y_sin_version_nueva():
    red = A.RedSimulada(RAIZ / "tests" / "fixtures", {"items_sha": "abc", "drops_hash": "h1"}, "0.6.2")
    r = red.responder(_peticion("https://api.github.com/repos/WFCD/warframe-items/commits?path=data/json&per_page=1"))
    assert r.json()[0]["sha"] == "abc"
    r = red.responder(_peticion("https://raw.githubusercontent.com/WFCD/warframe-drop-data/master/data/info.json"))
    assert r.json()["hash"] == "h1"
    r = red.responder(_peticion("https://api.github.com/repos/angelsanchez97/farmadex/releases/latest"))
    assert r.json()["tag_name"] == "v0.6.2" and r.json()["assets"] == []
    assert red.responder(_peticion("https://ejemplo.invalid/lo-que-sea")).status_code == 404
    assert len(red.peticiones) == 4


def test_la_red_simulada_ofrece_una_version_nueva_con_su_huella():
    import hashlib

    red = A.RedSimulada(None, {}, "0.6.2")
    red.modo = "version_nueva"
    red.instalador = b"x" * 1000
    red.huella = hashlib.sha256(red.instalador).hexdigest()
    datos = red.responder(_peticion("https://api.github.com/repos/angelsanchez97/farmadex/releases/latest")).json()
    adjunto = datos["assets"][0]
    assert adjunto["digest"] == f"sha256:{red.huella}"
    from farmadex.actualizador import descarga
    from farmadex.actualizador.app import analizar_release, es_mas_nueva

    version = analizar_release(datos)
    assert es_mas_nueva(version.etiqueta) and descarga.url_permitida(version.url)
    assert red.responder(_peticion(version.url)).content == red.instalador


def test_sin_red_la_red_simulada_falla_como_sin_conexion():
    red = A.RedSimulada(None, {}, "0.6.2")
    red.modo = "sin_red"
    with pytest.raises(httpx.ConnectError):
        red.responder(_peticion("https://api.warframe.market/v2/items"))


def test_el_ejecutable_y_python_m_farmadex_enrutan_la_autoprueba_antes_de_la_app():
    arranque = (RAIZ / "empaquetado" / "arranque.py").read_text(encoding="utf-8")
    assert arranque.index("--autoprueba") < arranque.index("from farmadex.app import main")
    principal = (RAIZ / "src" / "farmadex" / "__main__.py").read_text(encoding="utf-8")
    assert principal.index("--autoprueba") < principal.index("from .app import main")


def test_los_criterios_del_visto_bueno_son_los_pedidos():
    """Build < 1 s y recompensas < 0,5 s en un PC normal; resultados < 150 ms; fichas < 200 ms."""
    assert A.CRITERIOS["build_ms"] == 1000
    assert A.CRITERIOS["recompensas_ms"] == 500
    assert A.CRITERIOS["resultados_ms"] == 150
    assert A.CRITERIOS["ficha_ms"] == 200


def test_antes_de_salir_se_deshace_la_aplicacion_qt(monkeypatch):
    """os._exit con la QApplication viva reventaba al descargar Qt (salida 139): se cierra antes."""
    from PySide6.QtWidgets import QApplication

    from farmadex import autoprueba

    hechos = []

    class Ventana:
        def close(self):
            hechos.append("close")

        def deleteLater(self):
            hechos.append("deleteLater")

    class App:
        def topLevelWidgets(self):
            return [Ventana()]

        def processEvents(self):
            hechos.append("processEvents")

        def sendPostedEvents(self, *a):
            hechos.append("sendPostedEvents")

        def shutdown(self):
            hechos.append("shutdown")

    monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: App()))
    autoprueba._cerrar_qt()
    assert hechos[-1] == "shutdown" and "close" in hechos and "sendPostedEvents" in hechos
