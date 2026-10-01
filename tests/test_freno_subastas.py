"""El freno comun de las busquedas de subastas de warframe.market y el User-Agent."""

import re
import threading

import httpx

from farmadex import URL_CONTACTO, VERSION
from farmadex.agrietados import mercado
from farmadex.online.http import Cliente


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_el_freno_deja_pasar_diez_por_minuto_y_luego_hace_esperar():
    reloj = Reloj()
    freno = mercado.FrenoSubastas(maximo=10, ventana=60.0, reloj=reloj)
    esperas = []

    def esperar_falso(segundos):
        esperas.append(segundos)
        reloj.t += segundos

    freno._condicion.wait = esperar_falso
    for _ in range(10):
        assert freno.esperar() == 0.0
        reloj.t += 1.0
    assert freno.usadas() == 10 and not esperas
    # La undecima espera a que caduque la primera (se hizo hace 10 s: faltan 50).
    assert round(freno.esperar()) == 50
    assert [round(e) for e in esperas] == [50] and freno.esperas == 1
    assert freno.usadas() == 10


def test_soltar_despierta_a_quien_espera_turno():
    freno = mercado.FrenoSubastas(maximo=1, ventana=600.0)
    freno.esperar()
    resultado = []

    def trabajo():
        try:
            freno.esperar()
            resultado.append("paso")
        except mercado.FrenoSoltado:
            resultado.append("soltado")

    hilo = threading.Thread(target=trabajo, daemon=True)
    hilo.start()
    for _ in range(200):
        if freno.esperas:
            break
        threading.Event().wait(0.01)
    freno.soltar()
    hilo.join(5)
    assert resultado == ["soltado"]


def _respuesta_subastas(peticiones):
    def responder(peticion: httpx.Request):
        peticiones.append(peticion)
        if "riven/weapons" in str(peticion.url):
            return httpx.Response(200, json={"data": [
                {"slug": "rubico", "i18n": {"en": {"name": "Rubico"}}, "gameRef": "/Lotus/Rubico",
                 "rivenType": "rifle", "group": "primary", "disposition": 1.0}]})
        return httpx.Response(200, json={"payload": {"auctions": [
            {"buyout_price": 50 + i, "starting_price": 50 + i, "owner": {"ingame_name": "x", "status": "ingame"},
             "item": {"type": "riven", "attributes": [
                 {"url_name": "multishot", "value": 90.0, "positive": True},
                 {"url_name": "critical_chance", "value": 150.0, "positive": True}]}}
            for i in range(6)]}})

    return responder


def test_todas_las_busquedas_de_subastas_pasan_por_el_mismo_freno_y_la_cache_no_gasta(tmp_path):
    """Pestana (horquilla), panel del juego (parecidos) y chat comparten freno y cache."""
    from farmadex.chat import rivens

    peticiones = []
    m = mercado.MercadoAgrietados(carpeta=tmp_path,
                                  cliente=Cliente(transporte=httpx.MockTransport(_respuesta_subastas(peticiones))))
    freno = mercado.FRENO_SUBASTAS
    assert freno.usadas() == 0
    m.subastas("rubico", ["multishot"])  # consulta a mano
    assert freno.usadas() == 1
    m.horquilla("rubico", ["multishot", "critical_chance"], None)  # pestana de Agrietados
    assert freno.usadas() == 2
    m.parecidos("rubico", ["critical_chance", "multishot"], None)  # panel del juego: misma cache
    assert freno.usadas() == 2
    h = rivens.calcular("Rubico", ["multishot", "critical_chance"], mercado=m)  # chat
    assert not h.error and h.suficiente
    assert freno.usadas() == 3
    rivens.calcular("Rubico", ["critical_chance", "multishot"], mercado=m)  # lo mismo: de la cache
    assert freno.usadas() == 3
    busquedas = [p for p in peticiones if "auctions/search" in str(p.url)]
    assert len(busquedas) == 3
    m.cerrar()


def test_el_freno_es_uno_solo_aunque_haya_varios_mercados(tmp_path):
    peticiones = []
    a = mercado.MercadoAgrietados(carpeta=tmp_path / "a",
                                  cliente=Cliente(transporte=httpx.MockTransport(_respuesta_subastas(peticiones))))
    b = mercado.MercadoAgrietados(carpeta=tmp_path / "b",
                                  cliente=Cliente(transporte=httpx.MockTransport(_respuesta_subastas(peticiones))))
    a.subastas("rubico")
    b.subastas("rubico")
    assert mercado.FRENO_SUBASTAS.usadas() == 2
    assert mercado.SUBASTAS_POR_MINUTO <= 10 and mercado.FRENO_SUBASTAS.maximo <= 10
    a.cerrar()
    b.cerrar()


def test_no_hay_otra_puerta_a_la_busqueda_de_subastas():
    """Nadie mas en el programa llama a auctions/search por su cuenta."""
    from pathlib import Path

    import farmadex

    raiz = Path(farmadex.__file__).parent
    fuera = []
    for ruta in raiz.rglob("*.py"):
        texto = ruta.read_text(encoding="utf-8")
        if "auctions/search" in texto and ruta.name != "mercado.py":
            fuera.append(ruta.name)
    assert not fuera
    texto = (raiz / "agrietados" / "mercado.py").read_text(encoding="utf-8")
    assert len(re.findall(r"auctions/search\?", texto)) == 1


def test_user_agent_identifica_a_farmadex_en_warframe_market(tmp_path):
    from farmadex import config

    esperado = f"Farmadex/{VERSION} (+{URL_CONTACTO})"
    assert URL_CONTACTO.startswith("https://github.com/")
    assert config.USER_AGENT == esperado
    vistos = []

    def responder(peticion: httpx.Request):
        vistos.append(peticion.headers.get("user-agent", ""))
        return httpx.Response(200, json={"payload": {"auctions": []}, "data": []})

    m = mercado.MercadoAgrietados(carpeta=tmp_path, cliente=None)
    assert m.cliente.cliente.headers["user-agent"] == esperado
    m.cerrar()
    c = Cliente(transporte=httpx.MockTransport(responder))
    c.json("https://api.warframe.market/v2/items")
    c.cerrar()
    assert vistos == [esperado]
    assert "Mozilla" not in esperado and "Chrome" not in esperado


def test_ningun_user_agent_de_navegador_en_el_codigo():
    from pathlib import Path

    import farmadex

    raiz = Path(farmadex.__file__).parent
    herramientas = raiz.parent.parent / "herramientas" / "precios" / "generar.py"
    for ruta in [*raiz.rglob("*.py"), herramientas]:
        texto = ruta.read_text(encoding="utf-8")
        assert "Mozilla/" not in texto and "AppleWebKit" not in texto, ruta.name
    ua = re.search(r'^USER_AGENT = "([^"]+)"', herramientas.read_text(encoding="utf-8"), re.M).group(1)
    assert ua.startswith("Farmadex") and "github.com/angelsanchez97/farmadex" in ua


def test_al_cerrar_el_programa_nadie_espera_turno():
    import pytest

    freno = mercado.FrenoSubastas(maximo=1, ventana=600.0)
    freno.esperar()
    freno.cerrar()
    with pytest.raises(mercado.FrenoSoltado):
        freno.esperar()  # ni las peticiones que estaban en cola
    freno.olvidar()
    assert freno.esperar() < 0.5
