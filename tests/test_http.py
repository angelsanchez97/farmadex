"""El cliente HTTP compartido: reintentos, cache y mensajes, sin tocar la red."""

import threading

import httpx
import pytest

from farmadex.online import http


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


def _cliente(respuestas):
    """Un Cliente cuyo servidor contesta, por orden, con lo que se le da (codigo o excepcion)."""
    llamadas = []

    def servidor(peticion: httpx.Request) -> httpx.Response:
        llamadas.append(str(peticion.url))
        siguiente = respuestas[min(len(llamadas) - 1, len(respuestas) - 1)]
        if isinstance(siguiente, Exception):
            raise siguiente
        codigo, cuerpo = siguiente
        return httpx.Response(codigo, json=cuerpo) if cuerpo is not None else httpx.Response(
            codigo, text="<html>no json</html>"
        )

    return http.Cliente(transporte=httpx.MockTransport(servidor)), llamadas


def test_un_404_no_se_reintenta():
    cliente, llamadas = _cliente([(404, {"message": "WorldState Not Found"})])
    with pytest.raises(RuntimeError, match="HTTP 404"):
        cliente.json("https://x/y", intentos=3)
    assert len(llamadas) == 1


def test_un_503_se_reintenta_y_acaba_bien():
    cliente, llamadas = _cliente([(503, {}), (503, {}), (200, {"ok": 1})])
    assert cliente.json("https://x/y", intentos=3) == {"ok": 1}
    assert len(llamadas) == 3


def test_fallo_de_red_se_reintenta_y_el_mensaje_es_legible():
    cliente, llamadas = _cliente([httpx.ConnectError("boom")])
    with pytest.raises(RuntimeError, match="no hay conexion"):
        cliente.json("https://x/y", intentos=2)
    assert len(llamadas) == 2


def test_timeout_dice_que_el_servidor_no_responde():
    cliente, _ = _cliente([httpx.ReadTimeout("lento")])
    with pytest.raises(RuntimeError, match="tiempo agotado"):
        cliente.json("https://x/y", intentos=1)


def test_html_en_vez_de_json_no_es_un_traceback():
    cliente, _ = _cliente([(200, None)])
    with pytest.raises(RuntimeError, match="no es JSON"):
        cliente.json("https://x/y", intentos=1)


def test_la_cache_evita_la_segunda_peticion_y_se_comparte_entre_hilos():
    cliente, llamadas = _cliente([(200, {"v": 1})])
    resultados = []

    def pedir():
        resultados.append(cliente.json("https://x/y", segundos_cache=60))

    hilos = [threading.Thread(target=pedir) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert resultados == [{"v": 1}] * 8
    # Como mucho una por hilo que entro antes de que la primera guardara; nunca mas.
    assert 1 <= len(llamadas) <= 8
    assert cliente.json("https://x/y", segundos_cache=60) == {"v": 1}
    assert len(llamadas) <= 8


def test_sin_cache_cada_llamada_va_al_servidor():
    cliente, llamadas = _cliente([(200, {"v": 1})])
    cliente.json("https://x/y")
    cliente.json("https://x/y")
    assert len(llamadas) == 2


def test_conectar_tiene_su_propio_plazo_corto():
    cliente = http.Cliente(timeout=20.0)
    assert cliente.cliente.timeout.connect == http.SEGUNDOS_CONECTAR
    assert cliente.cliente.timeout.read == 20.0
