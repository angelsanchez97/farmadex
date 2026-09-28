"""Sin conexion, comprobar los datos no puede retrasar el resto del arranque.

La autoprueba (farmadex/autoprueba.py, con --sin-red) midio 22 s desde que se abre la
ventana hasta que se puede leer la pantalla: cada peticion de version se reintentaba
tres veces con esperas de 1, 2 y 4 s aunque no hubiera red, y la lectura de pantalla,
Objetivos y Mundo esperan a que termine la comprobacion. Ahora un servidor con el que no
se puede ni conectar no se reintenta, y con dos asi se da por hecho que no hay red.
"""

from __future__ import annotations

import httpx
import pytest

from farmadex.datos import descargas


@pytest.fixture()
def descargador(tmp_path, monkeypatch):
    monkeypatch.setattr(descargas, "RUTA_ESTADO_DATOS", tmp_path / "estado_datos.json")
    monkeypatch.setattr(descargas, "DIR_DATOS", tmp_path)
    monkeypatch.setattr(descargas, "crear_carpetas", lambda: None)
    esperas = []
    monkeypatch.setattr(descargas.time, "sleep", esperas.append)
    peticiones = []

    def crear(servidor):
        def responder(peticion):
            peticiones.append(str(peticion.url))
            return servidor(peticion)

        d = descargas.Descargador(cliente=httpx.Client(transport=httpx.MockTransport(responder)))
        d.peticiones, d.esperas = peticiones, esperas
        return d

    return crear


def _sin_red(peticion):
    raise httpx.ConnectError("sin red", request=peticion)


def test_sin_red_las_versiones_fallan_al_momento_y_sin_esperas(descargador):
    d = descargador(_sin_red)
    assert d.version_items() == ("", "")
    assert d.version_drops() == ("", "")
    assert d._sincronizar_tabla_oficial() is False
    assert d.esperas == []  # ni un segundo esperando
    # Un intento por servidor distinto hasta saber que no hay red; lo demas ni se pide.
    assert len(d.peticiones) <= 3
    assert d.sin_red()


def test_sin_red_sincronizar_con_los_ficheros_ya_bajados_no_descarga_nada(descargador, tmp_path):
    d = descargador(_sin_red)
    for ruta in list(d.rutas_items().values()) + list(d.rutas_drops().values()) + [d.ruta_piezas()]:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("[]", encoding="utf-8")
    assert d.sincronizar() is False
    assert d.esperas == []


def test_un_fallo_de_respuesta_si_se_reintenta(descargador):
    """Un 503 (servidor saturado) si puede arreglarse esperando: ahi se sigue reintentando."""
    llamadas = []

    def saturado(peticion):
        llamadas.append(1)
        if len(llamadas) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"sha": "s", "commit": {"committer": {"date": "d"}}}])

    d = descargador(saturado)
    assert d.version_items()[0] == "s"
    assert d.esperas == [1, 2]
    assert not d.sin_red()


def test_un_servidor_caido_no_impide_probar_el_espejo(descargador):
    """Que falle un servidor no es "sin red": el espejo de las tablas se sigue probando."""

    def solo_espejo(peticion):
        if peticion.url.host == "raw.githubusercontent.com":
            raise httpx.ConnectError("bloqueado", request=peticion)
        return httpx.Response(200, json={"hash": "h", "modified": "1"})

    d = descargador(solo_espejo)
    assert d.version_drops()[0] == "h"
    assert not d.sin_red()
