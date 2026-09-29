"""Alertas de precio (warframe.market) y horquilla de precio de agrietados parecidos, sin red."""

import json
import os

import httpx
import pytest

from farmadex.agrietados import mercado as mercado_agrietados
from farmadex.online import alertas as logica
from farmadex.online import market as modulo_market
from farmadex.online.http import Cliente
from farmadex.online.market import Orden, Precios

from conftest import FIXTURES


# -- plataforma --------------------------------------------------------------------------------


def test_plataforma_de_la_config(monkeypatch):
    monkeypatch.setattr(modulo_market, "cargar", lambda: {"plataforma": "PS4"})
    assert modulo_market.plataforma_configurada() == "ps4"
    monkeypatch.setattr(modulo_market, "cargar", lambda: {"plataforma": "gameboy"})
    assert modulo_market.plataforma_configurada() == "pc"
    monkeypatch.setattr(modulo_market, "cargar", lambda: {})
    assert modulo_market.plataforma_configurada() == "pc"


def test_market_manda_la_plataforma_configurada(monkeypatch):
    monkeypatch.setattr(modulo_market, "cargar", lambda: {"plataforma": "xbox"})
    m = modulo_market.Market()
    try:
        assert m.cliente.cliente.headers["Platform"] == "xbox"
    finally:
        m.cliente.cerrar()


# -- ventas_ahora -------------------------------------------------------------------------------


def _market_con(respuestas: dict[str, object], vistos: list[str]):
    def responder(peticion: httpx.Request) -> httpx.Response:
        url = str(peticion.url)
        vistos.append(url)
        for trozo, respuesta in respuestas.items():
            if trozo in url:
                if isinstance(respuesta, int):
                    return httpx.Response(respuesta, request=peticion)
                return httpx.Response(200, json=respuesta, request=peticion)
        return httpx.Response(404, request=peticion)

    m = modulo_market.Market()
    m.cliente.cerrar()
    m.cliente = Cliente(transporte=httpx.MockTransport(responder))
    return m


def _top(ventas):
    return {"data": {"sell": ventas, "buy": []}}


def _venta(platino, usuario, estado="ingame", rango=None):
    orden = {"platinum": platino, "quantity": 1, "user": {"ingameName": usuario, "status": estado}}
    if rango is not None:
        orden["rank"] = rango
    return orden


def test_ventas_ahora_junta_rangos_si_no_se_pide_rango():
    vistos = []
    m = _market_con({"/top": _top([_venta(30, "a", rango=0), _venta(150, "b", rango=10)])}, vistos)
    p = m.ventas_ahora("energize")
    assert p.error == "" and sorted(o.platino for o in p.ventas) == [30, 150]
    assert p.rango is None and not p.por_rango
    assert vistos[-1].endswith("/orders/item/energize/top")


def test_ventas_ahora_con_rango_pide_ese_rango():
    vistos = []
    m = _market_con({"/top": _top([_venta(150, "b", rango=10)])}, vistos)
    p = m.ventas_ahora("energize", rango=10)
    assert [o.platino for o in p.ventas] == [150]
    assert vistos[-1].endswith("top?rank=10")


def test_ventas_ahora_un_solo_intento_ante_429():
    vistos = []
    m = _market_con({"/top": 429}, vistos)
    p = m.ventas_ahora("ash_prime_set")
    assert p.error == "HTTP 429" and not p.ventas
    assert len(vistos) == 1  # no insiste en el acto: el vigilante espera


def test_ficha_nombre_y_rango_maximo():
    vistos = []
    m = _market_con({"/items/energize": {"data": {"maxRank": 5, "i18n": {"en": {"name": "Energize"}}}}}, vistos)
    assert m.ficha("energize") == {"nombre_en": "Energize", "rango_max": 5}


# -- logica de alertas ---------------------------------------------------------------------------


def _precios(*ordenes):
    return Precios(slug="ash_prime_set", ventas=list(ordenes))


def test_coincidencias_solo_conectados_y_a_tu_precio():
    alerta = logica.Alerta(slug="ash_prime_set", nombre="Ash Prime", precio=60, nombre_en="Ash Prime Set")
    lista = logica.coincidencias(alerta, _precios(
        Orden(55, 1, "online1", "online"), Orden(58, 1, "juego1", "ingame"),
        Orden(40, 1, "desconectado", "offline"), Orden(61, 1, "caro", "ingame"),
    ))
    assert [c.vendedor for c in lista] == ["juego1", "online1"]  # en el juego primero
    assert lista[0].mensaje == '/w juego1 Hi! I want to buy: "Ash Prime Set" for 58 platinum. (warframe.market)'


def test_coincidencias_respeta_el_rango():
    alerta = logica.Alerta(slug="energize", nombre="Energizar", precio=200, rango=10, nombre_en="Energize")
    lista = logica.coincidencias(alerta, _precios(Orden(30, 1, "r0", "ingame", 0), Orden(150, 1, "r10", "ingame", 10)))
    assert [c.vendedor for c in lista] == ["r10"]
    assert '"Energize (rank 10)"' in lista[0].mensaje


def test_almacen_guarda_y_carga(tmp_path):
    ruta = tmp_path / "alertas.json"
    a = logica.Almacen(ruta)
    assert a.anadir(logica.Alerta(slug="x", nombre="X", precio=10))
    # La misma alerta otra vez no se duplica: cambia el precio.
    assert a.anadir(logica.Alerta(slug="x", nombre="X", precio=8))
    assert len(a.lista()) == 1 and a.lista()[0].precio == 8
    a.pausar(a.lista()[0].id, True)
    b = logica.Almacen(ruta)
    assert len(b.lista()) == 1 and b.lista()[0].precio == 8 and not b.lista()[0].activa
    b.borrar(b.lista()[0].id)
    assert logica.Almacen(ruta).lista() == []


def test_almacen_con_fichero_roto(tmp_path):
    ruta = tmp_path / "alertas.json"
    ruta.write_text("{esto no es json", encoding="utf-8")
    assert logica.Almacen(ruta).lista() == []
    ruta.write_text(json.dumps({"alertas": [{"slug": "", "precio": 5}, {"slug": "y", "precio": "no"},
                                            {"slug": "z", "precio": 3}]}), encoding="utf-8")
    assert [a.slug for a in logica.Almacen(ruta).lista()] == ["z"]


class _Reloj:
    def __init__(self):
        self.ahora = 1000.0

    def __call__(self):
        return self.ahora


def _vigilante(tmp_path, respuestas):
    almacen = logica.Almacen(tmp_path / "alertas.json")
    reloj = _Reloj()
    llamadas = []

    def consultar(slug, rango):
        llamadas.append((slug, rango))
        return respuestas.pop(0) if respuestas else _precios()

    v = logica.Vigilante(almacen, consultar, ficha=lambda slug: {"nombre_en": "Ash Prime Set", "rango_max": None},
                         reloj=reloj)
    return v, almacen, reloj, llamadas


def test_no_repite_el_mismo_aviso(tmp_path):
    venta = Orden(50, 1, "Vendedor", "ingame")
    v, almacen, reloj, llamadas = _vigilante(tmp_path, [_precios(venta), _precios(venta), _precios(Orden(45, 1, "Vendedor", "ingame"))])
    almacen.anadir(logica.Alerta(slug="ash_prime_set", nombre="Ash Prime", precio=60))
    alerta = v.siguiente()
    nuevas = v.comprobar(alerta)
    assert [c.platino for c in nuevas] == [50]
    assert "Ash Prime Set" in nuevas[0].mensaje  # nombre del mercado sacado de su ficha
    # Aun no toca: ni la misma alerta antes de su intervalo ni otra peticion tan seguida.
    reloj.ahora += logica.SEPARACION_S
    assert v.siguiente() is None
    reloj.ahora += logica.INTERVALO_ALERTA_S
    assert v.comprobar(v.siguiente()) == []  # mismo vendedor, mismo precio: no se repite
    reloj.ahora += logica.INTERVALO_ALERTA_S
    assert [c.platino for c in v.comprobar(v.siguiente())] == [45]  # ha bajado: si se avisa
    # Tambien tras reiniciar Farmadex (los avisos dados se guardan).
    otro = logica.Almacen(tmp_path / "alertas.json")
    c = logica.Coincidencia(almacen.lista()[0].id, "Vendedor", 45, "ingame", "")
    assert otro.nuevas([c]) == []


def test_fallo_espera_cada_vez_mas_y_no_deja_datos_viejos(tmp_path):
    v, almacen, reloj, llamadas = _vigilante(tmp_path, [
        _precios(Orden(70, 1, "a", "ingame")),
        Precios(slug="ash_prime_set", error="HTTP 429"),
        Precios(slug="ash_prime_set", error="HTTP 503"),
    ])
    almacen.anadir(logica.Alerta(slug="ash_prime_set", nombre="Ash Prime", precio=60))
    v.comprobar(v.siguiente())
    estado = v.estado(almacen.lista()[0].id)
    assert estado.mejor == 70 and estado.cuando is not None
    reloj.ahora += logica.INTERVALO_ALERTA_S
    v.comprobar(v.siguiente())
    assert estado.error == "HTTP 429" and v.espera_hasta == reloj.ahora + logica.ESPERA_MIN_S
    assert v.siguiente() is None
    reloj.ahora += logica.ESPERA_MIN_S
    v.comprobar(v.siguiente())
    assert v.espera_hasta == reloj.ahora + 2 * logica.ESPERA_MIN_S  # backoff
    from farmadex.ui.pestana_alertas import texto_estado

    texto = texto_estado(almacen.lista()[0], estado)
    assert "503" in texto and "70" not in texto  # el fallo, no el precio de antes


def test_pausada_no_se_consulta(tmp_path):
    v, almacen, reloj, llamadas = _vigilante(tmp_path, [])
    almacen.anadir(logica.Alerta(slug="ash_prime_set", nombre="Ash Prime", precio=60))
    almacen.pausar(almacen.lista()[0].id, True)
    assert v.siguiente() is None


def test_muchas_alertas_no_pasan_de_una_peticion_cada_separacion(tmp_path):
    v, almacen, reloj, llamadas = _vigilante(tmp_path, [])
    for i in range(10):
        almacen.anadir(logica.Alerta(slug=f"item_{i}", nombre=f"I{i}", precio=10))
    peticiones = 0
    for _ in range(3600):  # una hora en pasos de un segundo
        alerta = v.siguiente()
        if alerta is not None:
            v.comprobar(alerta)
            peticiones += 1
        reloj.ahora += 1
    assert peticiones <= 3600 / logica.SEPARACION_S + 1
    assert {s for s, _r in llamadas} == {f"item_{i}" for i in range(10)}  # todas se miran


def test_texto_estado_lleva_la_hora():
    from farmadex.ui.pestana_alertas import texto_estado

    alerta = logica.Alerta(slug="x", nombre="X", precio=10)
    assert "Aún sin comprobar" in texto_estado(alerta, None)
    estado = logica.Estado(cuando=1000.0, mejor=12, vendedor="a")
    assert "12p" in texto_estado(alerta, estado, ahora=1000.0 + 300) and "5 min" in texto_estado(alerta, estado, ahora=1300)


# -- pestana ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def pestana(app, tmp_path):
    from farmadex import idiomas
    from farmadex.ui.pestana_alertas import PestanaAlertas

    idiomas.cargar("es")
    p = PestanaAlertas(con_red=False, almacen=logica.Almacen(tmp_path / "alertas.json"))
    yield p
    p.deleteLater()


def test_crear_pausar_borrar_desde_la_pestana(pestana):
    assert pestana.vacio.isVisibleTo(pestana)
    pestana.preparar_alerta("ash_prime_set", "Ash Prime (set)", "/Lotus/AshPrime")
    assert pestana.panel_nueva.isVisibleTo(pestana) and pestana.boton_crear.isEnabled()
    pestana._preparado("ash_prime_set", {"nombre_en": "Ash Prime Set", "rango_max": None},
                       _precios(Orden(80, 1, "a", "ingame"), Orden(20, 1, "off", "offline")))
    assert pestana.precio.value() == 79  # por debajo de lo mas barato conectado (no del desconectado)
    assert "80p" in pestana.info_nueva.text()
    pestana.precio.setValue(70)
    pestana.crear()
    alertas = pestana.almacen.lista()
    assert len(alertas) == 1 and alertas[0].precio == 70 and alertas[0].nombre_en == "Ash Prime Set"
    assert not pestana.panel_nueva.isVisibleTo(pestana)
    fila = pestana.filas[alertas[0].id]
    assert "70p" in fila.tope.text()
    fila.boton_pausa.click()
    assert not pestana.almacen.lista()[0].activa
    assert "En pausa" in pestana.filas[alertas[0].id].estado.text()
    pestana.filas[alertas[0].id].boton_borrar.click()
    assert pestana.almacen.lista() == []


def test_objeto_sin_mercado_no_deja_crear(pestana):
    pestana.preparar_alerta("", "Mandachord")
    assert not pestana.boton_crear.isEnabled()


def test_rango_para_mods(pestana):
    pestana.preparar_alerta("energize", "Energizar", "")
    pestana._preparado("energize", {"nombre_en": "Energize", "rango_max": 5}, Precios(slug="energize", error="HTTP 503"))
    assert not pestana.rango.isHidden() and pestana.rango.count() == 3
    assert "503" in pestana.info_nueva.text()
    pestana.rango.setCurrentIndex(1)
    pestana.precio.setValue(100)
    pestana.crear()
    assert pestana.almacen.lista()[0].rango == 5


def test_aviso_de_bandeja_una_vez_por_alerta(pestana):
    alerta = logica.Alerta(slug="x", nombre="X", precio=10)
    avisos = []
    pestana.aviso.connect(lambda texto, mensaje: avisos.append((texto, mensaje)))
    c1 = logica.Coincidencia(alerta.id, "a", 8, "ingame", "/w a hola")
    c2 = logica.Coincidencia(alerta.id, "b", 9, "ingame", "/w b hola")
    pestana._nuevas([(alerta, c1), (alerta, c2)])
    assert len(avisos) == 1 and avisos[0][1] == "/w a hola" and "a" in avisos[0][0] and "8" in avisos[0][0]


# -- horquilla de agrietados -------------------------------------------------------------------


def test_horquilla_cuartiles():
    h = mercado_agrietados.calcular_horquilla("rubico", [100, 200, 300, 400, 500, 0, 9000], "exacto")
    assert h.n == 6 and h.suficiente and h.minimo == 100
    assert h.bajo <= h.mediana <= h.alto and h.mediana == 350


def test_horquilla_pocas_subastas_no_da_rango():
    h = mercado_agrietados.calcular_horquilla("rubico", [100, 200], "exacto")
    assert not h.suficiente and h.bajo is None and h.alto is None and h.minimo == 100


def _mercado_con(respuestas, vistos, tmp_path):
    def responder(peticion):
        url = str(peticion.url)
        vistos.append(url)
        for trozo, cuerpo in respuestas:
            if trozo in url:
                if isinstance(cuerpo, int):
                    return httpx.Response(cuerpo, request=peticion)
                return httpx.Response(200, json=cuerpo, request=peticion)
        return httpx.Response(404, request=peticion)

    return mercado_agrietados.MercadoAgrietados(carpeta=tmp_path, cliente=Cliente(transporte=httpx.MockTransport(responder)))


def _subastas(precios):
    return {"payload": {"auctions": [
        {"buyout_price": p, "starting_price": p, "closed": False, "owner": {"ingame_name": f"v{i}", "status": "ingame"},
         "item": {"type": "riven", "attributes": [], "re_rolls": 0, "mod_rank": 8}}
        for i, p in enumerate(precios)
    ]}}


def test_horquilla_relaja_la_negativa_si_hay_pocas(tmp_path):
    vistos = []
    m = _mercado_con([("negative_stats=zoom", _subastas([300, 400])), ("positive_stats", _subastas([200, 250, 300, 350, 400, 450]))],
                     vistos, tmp_path)
    h = m.horquilla("rubico", ["critical_damage", "critical_chance"], "zoom")
    assert h.nivel == "positivas" and h.n == 6 and h.suficiente
    assert "positive_stats=critical_chance,critical_damage" in vistos[0] and "negative_stats=zoom" in vistos[0]
    assert "negative_stats" not in vistos[1]
    # Nunca se pide "cualquier agrietado del arma" sin estadisticas.
    assert all("positive_stats=" in u for u in vistos)
    # Cacheada: la segunda vez no hay peticiones.
    antes = len(vistos)
    assert m.horquilla("rubico", ["critical_chance", "critical_damage"], "zoom") is h
    assert len(vistos) == antes


def test_horquilla_sin_negativa_pide_none(tmp_path):
    vistos = []
    m = _mercado_con([("positive_stats", _subastas([100] * 6))], vistos, tmp_path)
    h = m.horquilla("rubico", ["multishot", "damage"], None)
    assert h.nivel == "exacto" and "negative_stats=none" in vistos[0]


def test_horquilla_sin_red_dice_el_error(tmp_path):
    m = _mercado_con([("auctions", 503)], [], tmp_path)
    h = m.horquilla("rubico", ["damage"], None)
    assert h.error and not h.suficiente and h.bajo is None


def test_horquilla_con_la_fixture_real():
    datos = json.loads((FIXTURES / "market_riven_auctions.json").read_text(encoding="utf-8"))
    resumen = mercado_agrietados.analizar_subastas("rubico", datos)
    h = mercado_agrietados.calcular_horquilla("rubico", [s.precio for s in resumen.subastas if s.precio], "exacto")
    assert h.n == len([s for s in resumen.subastas if s.precio])


def test_texto_horquilla_nunca_inventa():
    from farmadex.ui.pestana_agrietados import texto_horquilla

    pocas = mercado_agrietados.calcular_horquilla("rubico", [120, 130], "exacto")
    texto = texto_horquilla(pocas)
    assert "sin datos suficientes" in texto and "2" in texto and "120p" in texto and "entre" not in texto
    ninguna = mercado_agrietados.calcular_horquilla("rubico", [], "exacto")
    assert "sin datos suficientes" in texto_horquilla(ninguna)
    buena = mercado_agrietados.calcular_horquilla("rubico", [100, 200, 300, 400, 500], "positivas")
    texto = texto_horquilla(buena)
    assert "200p" in texto and "400p" in texto and "5 subastas" in texto and "negativa" in texto
    assert "no responde" in texto_horquilla(mercado_agrietados.Horquilla(arma="rubico", error="HTTP 503"))
