import json
from pathlib import Path

from farmadex.online.market import analizar_ordenes
from farmadex.online.servicio_market import resumen

FIXTURE = Path(__file__).parent / "fixtures" / "market_top.json"


def _precios():
    return analizar_ordenes("ash_prime_systems", json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_las_ventas_salen_de_la_mas_barata():
    precios = _precios()
    assert precios.ventas
    platinos = [o.platino for o in precios.ventas if o.estado == "ingame"]
    assert platinos == sorted(platinos)
    assert precios.mejor_venta == min(platinos)


def test_manda_quien_esta_dentro_del_juego():
    datos = json.loads(FIXTURE.read_text(encoding="utf-8"))
    datos["data"]["sell"].insert(
        0,
        {"platinum": 1, "quantity": 1, "user": {"ingameName": "fantasma", "status": "offline"}},
    )
    precios = analizar_ordenes("x", datos)
    # El de 1 platino esta desconectado: no puede ser la mejor oferta.
    assert precios.ventas[0].estado == "ingame"
    assert precios.ventas[0].platino > 1


def test_resumen_legible():
    texto = resumen(_precios())
    assert "platino" in texto and "mediana" in texto


def test_resumen_cuando_falla_la_api():
    from farmadex.online.market import Precios

    assert "no disponible" in resumen(Precios(slug="x", error="timeout"))
    assert "nadie lo vende" in resumen(Precios(slug="x"))


def test_respuesta_inesperada_no_rompe():
    precios = analizar_ordenes("x", {"data": {"sell": None, "buy": [{}]}})
    assert precios.ventas == []
    assert precios.compras[0].platino == 0


# -- mods y arcanos: el precio depende del rango -------------------------------

ENERGIZE = Path(__file__).parent / "fixtures" / "market_energize_top.json"
ENERGIZE_R5 = Path(__file__).parent / "fixtures" / "market_energize_rango5.json"
ENERGIZE_ITEM = Path(__file__).parent / "fixtures" / "market_energize_item.json"


def _json(ruta):
    return json.loads(ruta.read_text(encoding="utf-8"))


class _ClienteFalso:
    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.pedidas = []

    def json(self, url, segundos_cache=0, intentos=3):
        self.pedidas.append(url)
        return self.respuestas[url]

    def cerrar(self):
        pass


def _market(respuestas):
    from farmadex.online.market import Market

    market = Market.__new__(Market)
    market.disponible = True
    market.cliente = _ClienteFalso(respuestas)
    return market


def test_top_sin_filtro_mezcla_rangos_y_se_separan():
    # Captura real: /top devuelve ventas a rango 0 (8p) y compras a rango 5 (130p).
    precios = analizar_ordenes("arcane_energize", _json(ENERGIZE))
    assert precios.con_rango and precios.rango == 5 and precios.rango_max == 5
    # A rango 5 solo hay compras en esa respuesta; las ventas de 8p no se mezclan.
    assert precios.ventas == [] and precios.mejor_compra == 130
    r0 = precios.en_rango(0)
    assert r0.mejor_venta == 8 and r0.compras == []
    assert precios.en_rango(5) is precios


def test_rango_pedido_explicitamente():
    precios = analizar_ordenes("arcane_energize", _json(ENERGIZE), rango=0)
    assert precios.rango == 0 and precios.mejor_venta == 8
    assert precios.en_rango(5).mejor_compra == 130


def test_mod_rank_de_la_v1_tambien_vale():
    datos = {"data": {"sell": [
        {"platinum": 3, "mod_rank": 0, "user": {"status": "ingame"}},
        {"platinum": 40, "mod_rank": 10, "user": {"status": "ingame"}},
    ], "buy": []}}
    precios = analizar_ordenes("x", datos)
    assert precios.rango == 10 and precios.mejor_venta == 40
    assert precios.en_rango(0).mejor_venta == 3


def test_rango_maximo_de_la_ficha():
    from farmadex.online.market import rango_maximo_de

    assert rango_maximo_de(_json(ENERGIZE_ITEM)) == 5
    assert rango_maximo_de({"data": {}}) is None
    assert rango_maximo_de({}) is None


def test_market_compone_rango_maximo_y_rango_cero():
    from farmadex.online.market import BASE

    market = _market({
        f"{BASE}/orders/item/arcane_energize/top": _json(ENERGIZE),
        f"{BASE}/items/arcane_energize": _json(ENERGIZE_ITEM),
        f"{BASE}/orders/item/arcane_energize/top?rank=5": _json(ENERGIZE_R5),
    })
    precios = market.precios("arcane_energize")

    # Antes: "se vende desde 8p, te lo compran por 130p". Ahora, a rango 5: 150p / 130p.
    assert precios.rango == 5 and precios.rango_max == 5
    assert precios.mejor_venta == 150 and precios.mejor_compra == 130
    assert precios.en_rango(0).mejor_venta == 8
    assert len(market.cliente.pedidas) == 3

    texto = resumen(precios)
    assert "rango maximo (5)" in texto and "150" in texto and "rango 0 desde 8p" in texto


def test_piezas_prime_siguen_sin_rango():
    from farmadex.online.market import BASE

    market = _market({f"{BASE}/orders/item/ash_prime_systems/top": _json(FIXTURE)})
    precios = market.precios("ash_prime_systems")
    assert not precios.con_rango and precios.mejor_venta == 17
    assert len(market.cliente.pedidas) == 1, "una pieza prime no necesita mas peticiones"
    assert "rango" not in resumen(precios)


# -- emparejar: casar el catalogo de warframe.market con el indice -------------


def _insertar_item(con, *, unique_name, nombre_en, categoria="Warframes", padre_id=None, es_prime=0):
    cur = con.execute(
        "INSERT INTO items (unique_name, nombre_en, categoria, padre_id, es_prime) "
        "VALUES (?, ?, ?, ?, ?)",
        (unique_name, nombre_en, categoria, padre_id, es_prime),
    )
    return cur.lastrowid


def _entrada_catalogo(slug, nombre_en, game_ref="/Lotus/no/coincide/con/nada", item_id="x"):
    return {"slug": slug, "id": item_id, "gameRef": game_ref, "i18n": {"en": {"name": nombre_en}}}


def _market_slug(con, item_id):
    return con.execute("SELECT market_slug FROM items WHERE id = ?", (item_id,)).fetchone()[0]


def test_emparejar_componente_por_nombre_compuesto(con):
    from farmadex.online.market import BASE

    padre_id = _insertar_item(con, unique_name="/Lotus/Padre/AshPrime", nombre_en="Ash Prime", es_prime=1)
    comp_id = _insertar_item(
        con,
        unique_name="/Lotus/Types/Recipes/WarframeRecipes/AshPrimeSystemsComponent",
        nombre_en="Systems",
        padre_id=padre_id,
        es_prime=1,
    )
    con.commit()

    market = _market({
        f"{BASE}/items": {"data": [_entrada_catalogo("ash_prime_systems", "Ash Prime Systems")]}
    })
    assert market.emparejar(con) == 1
    assert _market_slug(con, comp_id) == "ash_prime_systems"
    assert _market_slug(con, padre_id) is None


def test_emparejar_plano_con_sufijo_blueprint(con):
    from farmadex.online.market import BASE

    padre_id = _insertar_item(con, unique_name="/Lotus/Padre/AshPrime2", nombre_en="Ash Prime", es_prime=1)
    comp_id = _insertar_item(
        con, unique_name="/Lotus/Componente/AshPrimeChassis", nombre_en="Chassis",
        padre_id=padre_id, es_prime=1,
    )
    con.commit()

    market = _market({
        f"{BASE}/items": {
            "data": [_entrada_catalogo("ash_prime_chassis_blueprint", "Ash Prime Chassis Blueprint")]
        }
    })
    assert market.emparejar(con) == 1
    assert _market_slug(con, comp_id) == "ash_prime_chassis_blueprint"


def test_emparejar_sigue_casando_por_game_ref(con):
    from farmadex.online.market import BASE

    item_id = _insertar_item(
        con, unique_name="/Lotus/Weapons/Tenno/Pistol/BratonPrime", nombre_en="Braton Prime",
        categoria="Primary", es_prime=1,
    )
    con.commit()

    market = _market({
        f"{BASE}/items": {
            "data": [
                _entrada_catalogo(
                    "braton_prime",
                    "esto no deberia hacer falta leerlo",
                    game_ref="/Lotus/Weapons/Tenno/Pistol/BratonPrime",
                )
            ]
        }
    })
    assert market.emparejar(con) == 1
    assert _market_slug(con, item_id) == "braton_prime"


def test_emparejar_nombre_ambiguo_no_se_empareja(con):
    from farmadex.online.market import BASE

    padre_id = _insertar_item(con, unique_name="/Lotus/Padre/VastoPrime", nombre_en="Vasto Prime", es_prime=1)
    comp_id = _insertar_item(
        con, unique_name="/Lotus/Componente/VastoBarrel", nombre_en="Barrel",
        padre_id=padre_id, es_prime=1,
    )
    otro_id = _insertar_item(
        con, unique_name="/Lotus/Duplicado/VastoPrimeBarrel", nombre_en="Vasto Prime Barrel",
        categoria="Misc",
    )
    con.commit()

    market = _market({
        f"{BASE}/items": {"data": [_entrada_catalogo("vasto_prime_barrel", "Vasto Prime Barrel")]}
    })
    assert market.emparejar(con) == 0
    assert _market_slug(con, comp_id) is None
    assert _market_slug(con, otro_id) is None


# -- instancia compartida --------------------------------------------------


def test_compartido_es_el_mismo_desde_varios_hilos():
    """El buscador y el comparador tienen que compartir limitador y cache."""
    import threading

    from farmadex.online import market

    market.cerrar_compartido()
    vistos = []

    def coger():
        vistos.append(market.compartido())

    hilos = [threading.Thread(target=coger) for _ in range(6)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    try:
        assert len({id(m) for m in vistos}) == 1
        assert vistos[0] is market.compartido()
        # Un solo Cliente detras: un solo limitador de peticiones por segundo.
        assert vistos[0].cliente.limitador.intervalo == 1 / market.POR_SEGUNDO
    finally:
        market.cerrar_compartido()


def test_cerrar_uno_no_deja_al_otro_sin_mercado():
    from farmadex.online import market

    market.cerrar_compartido()
    m = market.compartido()
    try:
        m.cerrar()  # lo que hace ServicioMarket al parar su hilo
        assert not m.cliente.cliente.is_closed
        assert market.compartido() is m
    finally:
        market.cerrar_compartido()
    assert m.cliente.cliente.is_closed
    assert market.compartido() is not m
    market.cerrar_compartido()


def test_servicio_market_usa_el_compartido():
    from farmadex.online import market
    from farmadex.online.servicio_market import ServicioMarket

    market.cerrar_compartido()
    servicio = ServicioMarket()
    servicio.iniciar()
    try:
        assert servicio.market is market.compartido()
    finally:
        servicio.cerrar()
        market.cerrar_compartido()
