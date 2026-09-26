"""warframe.market (armas con disposicion, subastas) y la tabla semanal de DE, sin red."""

import json

import httpx
import pytest

from farmadex.agrietados import mercado
from farmadex.online.http import Cliente

from conftest import FIXTURES


def _leer(nombre: str) -> str:
    return (FIXTURES / nombre).read_text(encoding="utf-8")


def test_armas_con_disposicion_y_clase():
    armas = mercado.analizar_armas(json.loads(_leer("market_riven_weapons.json")))
    por_slug = {a.slug: a for a in armas}
    rubico = por_slug["rubico"]
    assert rubico.nombre_en == "Rubico" and rubico.tipo == "rifle" and rubico.clase == "rifle"
    assert 0.5 <= rubico.disposicion <= 1.55
    assert rubico.unique_name.startswith("/Lotus/")
    assert por_slug["catchmoon"].clase == "pistol"  # kitgun -> valores de pistola
    assert por_slug["balla"].clase == "melee"  # zaw -> cuerpo a cuerpo
    assert por_slug["cyngas"].clase == "archgun"
    assert por_slug["burst_laser"].grupo == "sentinel" and por_slug["burst_laser"].clase == "pistol"


def test_armas_con_formato_raro_no_revientan():
    with pytest.raises(ValueError):
        mercado.analizar_armas({"data": "nada"})
    assert mercado.analizar_armas({"data": [{"slug": "x"}, "basura", {"slug": "y", "disposition": "1.2", "rivenType": "melee"}]}) == [
        mercado.Arma("y", "Y", "", "melee", "", 1.2, None)
    ]


def test_subastas_ordenadas_y_con_atributos():
    resumen = mercado.analizar_subastas("rubico", json.loads(_leer("market_riven_auctions.json")))
    assert resumen.total == 6 and len(resumen.subastas) == 6
    precios = [s.referencia for s in resumen.subastas]
    assert precios == sorted(precios)
    primera = resumen.subastas[0]
    assert primera.atributos and all(isinstance(v, float) for _, v, _ in primera.atributos)
    assert any(negativo for _, _, negativo in primera.atributos) or len(primera.atributos) <= 3
    assert primera.vendedor.startswith("vendedor_")
    assert resumen.minimo == precios[0] and resumen.mediana is not None


def test_subastas_sin_payload():
    with pytest.raises(ValueError):
        mercado.analizar_subastas("rubico", {"payload": {}})


def test_medias_de_en_formato_javascript():
    medias = mercado.analizar_medias_de(_leer("de_weekly_rivens.txt"))
    assert ("rubico", True) in medias and ("bo", True) in medias
    rubico = medias[("rubico", True)]
    assert rubico.mediana == 200 and rubico.volumen == 3 and rubico.variado
    # La fila generica (sin arma) no entra.
    assert all(clave[0] for clave in medias)


def _transporte(respuestas: dict[str, str], fallar_resto: bool = True):
    def responder(peticion: httpx.Request):
        for trozo, cuerpo in respuestas.items():
            if trozo in str(peticion.url):
                return httpx.Response(200, text=cuerpo, headers={"content-type": "application/json"})
        if fallar_resto:
            return httpx.Response(503)
        return httpx.Response(404)

    return httpx.MockTransport(responder)


def test_armas_se_guardan_en_disco_y_se_leen_sin_red(tmp_path):
    cliente = Cliente(transporte=_transporte({"riven/weapons": _leer("market_riven_weapons.json")}))
    m = mercado.MercadoAgrietados(carpeta=tmp_path, cliente=cliente)
    armas = m.armas()
    assert len(armas) > 10
    assert (tmp_path / mercado.FICHERO_ARMAS).exists()
    m.cerrar()
    # Otro Mercado, sin red: lee el fichero.
    sin_red = Cliente(transporte=_transporte({}))
    m2 = mercado.MercadoAgrietados(carpeta=tmp_path, cliente=sin_red)
    assert [a.slug for a in m2.armas()] == [a.slug for a in armas]
    assert m2.arma_por_slug("rubico").disposicion == m.arma_por_slug("rubico").disposicion
    assert m2.arma_por_unique_name(armas[0].unique_name) == armas[0]
    m2.cerrar()


def test_subastas_con_filtro_vuelven_a_pedir_sin_el(tmp_path):
    peticiones = []

    def responder(peticion: httpx.Request):
        url = str(peticion.url)
        peticiones.append(url)
        if "positive_stats" in url:
            return httpx.Response(200, json={"payload": {"auctions": []}})
        return httpx.Response(200, text=_leer("market_riven_auctions.json"))

    m = mercado.MercadoAgrietados(carpeta=tmp_path, cliente=Cliente(transporte=httpx.MockTransport(responder)))
    resumen = m.subastas("rubico", positivos=["multishot"], negativos=["zoom"], limite=3)
    assert len(resumen.subastas) == 3 and not resumen.error
    assert len(peticiones) == 2 and "positive_stats=multishot" in peticiones[0] and "negative_stats=zoom" in peticiones[0]
    assert "positive_stats" not in peticiones[1]
    m.cerrar()


def test_subastas_sin_red_devuelven_error_legible(tmp_path):
    m = mercado.MercadoAgrietados(carpeta=tmp_path, cliente=Cliente(transporte=_transporte({})))
    resumen = m.subastas("rubico")
    assert resumen.error and not resumen.subastas and resumen.minimo is None
    assert m.medias_de() == {}
    m.cerrar()


def test_medias_de_por_red_y_cache(tmp_path):
    llamadas = []

    def responder(peticion: httpx.Request):
        llamadas.append(str(peticion.url))
        return httpx.Response(200, text=_leer("de_weekly_rivens.txt"))

    m = mercado.MercadoAgrietados(carpeta=tmp_path, cliente=Cliente(transporte=httpx.MockTransport(responder)))
    assert m.medias_de()[("rubico", True)].mediana == 200
    assert m.medias_de()[("bo", True)].volumen == 51
    assert len(llamadas) == 1
    m.cerrar()
