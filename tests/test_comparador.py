"""El comparador de recompensas: que elige, por que, y que hace cuando no sabe."""

import sqlite3
import time

import pytest

from farmadex.captura import comparador
from farmadex.captura.comparador import Puntuacion, Veredicto, decidir, puntuar
from farmadex.captura.reliquias import Recompensa, resumir
from farmadex.online.market import Orden, Precios

ITEMS = [
    # id, unique_name, nombre_en, categoria, comerciable, ducados, market_slug
    (1, "/Lotus/A/Systems", "Ash Prime Systems", "Warframes", 1, 100, "ash_prime_systems"),
    (2, "/Lotus/B/Barrel", "Braton Prime Barrel", "Primary", 1, 15, "braton_prime_barrel"),
    (3, "/Lotus/C/Link", "Nikana Prime Link", "Melee", 1, 45, "nikana_prime_link"),
    (4, "/Lotus/D/Forma", "Forma Blueprint", "Misc", 0, None, None),
    (5, "/Lotus/E/Nuevo", "Pieza Sin Datos", "Warframes", 1, None, None),
    (6, "/Lotus/F/Reliquia", "Axi Z9 Relic", "Relics", 0, None, None),
]


@pytest.fixture()
def indice(con):
    for iid, unico, nombre, categoria, comerciable, ducados, slug in ITEMS:
        con.execute(
            "INSERT INTO items (id, unique_name, nombre_en, categoria, comerciable, ducados, market_slug) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (iid, unico, nombre, categoria, comerciable, ducados, slug),
        )
    # La pieza sin ducados sale como poco comun en dos reliquias y rara en una.
    for reliquia, rareza in ((6, "Uncommon"), (6, "Rare")):
        con.execute(
            "INSERT OR IGNORE INTO reliquia_recompensas VALUES (?, ?, ?, ?, ?)",
            (reliquia, "Intact" if rareza == "Uncommon" else "Radiant", 5, rareza, 10.0),
        )
    con.execute(
        "INSERT OR IGNORE INTO reliquia_recompensas VALUES (?, ?, ?, ?, ?)",
        (6, "Exceptional", 5, "Uncommon", 10.0),
    )
    con.commit()
    return con


@pytest.fixture()
def usuario():
    from farmadex.estado import usuario_db

    con = sqlite3.connect(":memory:")
    con.executescript(usuario_db.ESQUEMA)
    yield con
    con.close()


def _r(item_id: int, nombre: str) -> Recompensa:
    return Recompensa(item_id=item_id, nombre=nombre, texto_ocr=nombre.upper(), caja=(0, 0, 10, 10))


def _precios(ventas: list[int], estado: str = "ingame") -> Precios:
    p = Precios(slug="x")
    p.ventas = [Orden(platino=v, cantidad=1, usuario="u", estado=estado) for v in ventas]
    return p


def _mercado(tabla: dict):
    def precios_de(slug: str):
        return tabla.get(slug)

    return precios_de


def test_gana_el_platino_y_se_explica(indice):
    mercado = _mercado({
        "ash_prime_systems": _precios([40, 42, 45, 50, 60]),
        "braton_prime_barrel": _precios([3, 4, 5]),
    })
    recompensas = [_r(2, "Braton Prime Barrel"), _r(1, "Ash Prime Systems")]
    v = puntuar(recompensas, indice, mercado, escuadra=False)
    assert v.mejor == 1 and v.seguro
    assert recompensas[1].mejor and not recompensas[0].mejor
    assert recompensas[1].platino == 45  # mediana de los cinco primeros, no en escuadra
    assert "45 platino" in v.motivo and "100 ducados" in v.motivo
    assert v.resumen().startswith("Elige Ash Prime Systems")
    assert "MEJOR: Ash Prime Systems" in resumir(recompensas)


def test_en_escuadra_cuenta_el_vendedor_mas_barato_y_avisa_de_mercado_fino(indice):
    mercado = _mercado({"ash_prime_systems": _precios([40, 60, 80])})
    v = puntuar([_r(1, "Ash Prime Systems")], indice, mercado, escuadra=True)
    p = v.puntuaciones[0]
    assert p.platino == 40 and p.platino_mediana == 60
    assert any("Mercado fino" in n for n in p.notas)


def test_los_ducados_ganan_a_un_platino_de_risa(indice):
    mercado = _mercado({
        "ash_prime_systems": _precios([3, 3, 4]),  # 100 ducados = 10p equivalentes
        "nikana_prime_link": _precios([6, 6, 7]),  # 45 ducados = 4.5p
    })
    v = puntuar([_r(3, "Nikana Prime Link"), _r(1, "Ash Prime Systems")], indice, mercado)
    assert v.mejor == 1
    assert v.puntuaciones[1].via == "ducados"
    assert "100 ducados" in v.motivo and "solo 3 platino" in v.motivo


def test_el_objetivo_pendiente_manda_sobre_el_precio(indice, usuario):
    usuario.execute(
        "INSERT INTO objetivos (item_unique_name, nombre, cantidad_objetivo, cantidad_actual, creado_en) "
        "VALUES ('/Lotus/B/Barrel', 'Braton Prime: Barrel', 1, 0, '2026-09-20T10:00:00')"
    )
    mercado = _mercado({
        "ash_prime_systems": _precios([80, 85, 90]),
        "braton_prime_barrel": _precios([2, 2, 2]),
    })
    v = puntuar([_r(1, "Ash Prime Systems"), _r(2, "Braton Prime Barrel")], indice, mercado, usuario)
    assert v.mejor == 1 and v.seguro
    assert "objetivo" in v.motivo and "0/1" in v.motivo


def test_objetivo_ya_completado_no_cuenta(indice, usuario):
    usuario.execute(
        "INSERT INTO objetivos (item_unique_name, nombre, cantidad_objetivo, cantidad_actual, creado_en, "
        "completado_en) VALUES ('/Lotus/B/Barrel', 'x', 1, 1, '2026-09-20T10:00:00', '2026-09-20T11:00:00')"
    )
    mercado = _mercado({"ash_prime_systems": _precios([80]), "braton_prime_barrel": _precios([2])})
    v = puntuar([_r(1, "Ash Prime Systems"), _r(2, "Braton Prime Barrel")], indice, mercado, usuario)
    assert v.mejor == 0


def test_sin_precio_se_dice_y_el_veredicto_no_es_seguro(indice):
    mercado = _mercado({"ash_prime_systems": _precios([50])})  # de la otra no se sabe nada
    recompensas = [_r(1, "Ash Prime Systems"), _r(5, "Pieza Sin Datos")]
    v = puntuar(recompensas, indice, mercado)
    assert v.mejor == 0 and not v.seguro
    assert "Pieza Sin Datos sin valorar" in v.motivo
    assert v.resumen().startswith("Probablemente")
    p = v.puntuaciones[1]
    assert p.valor is None and p.confianza == comparador.CONFIANZA_PARCIAL
    assert p.rareza == "poco comun"  # la rareza mas repetida entre sus reliquias
    assert "Sin precio" in recompensas[1].nota


def test_mercado_caido_no_inventa_precio(indice):
    def roto(slug):
        raise RuntimeError("sin red")

    v = puntuar([_r(1, "Ash Prime Systems"), _r(2, "Braton Prime Barrel")], indice, roto)
    assert v.puntuaciones[0].platino is None
    # Aun sin red, los ducados bastan para decidir: 100 frente a 15.
    assert v.mejor == 0 and v.seguro
    assert all("mercado no disponible" in p.notas[0] for p in v.puntuaciones)


def test_error_de_la_api_se_transmite_en_la_nota(indice):
    mercado = _mercado({"ash_prime_systems": Precios(slug="x", error="429 Too Many Requests")})
    v = puntuar([_r(1, "Ash Prime Systems")], indice, mercado)
    assert "429" in v.puntuaciones[0].notas[0]


def test_nadie_lo_vende_es_distinto_de_no_saber(indice):
    mercado = _mercado({"ash_prime_systems": Precios(slug="x")})
    v = puntuar([_r(1, "Ash Prime Systems")], indice, mercado)
    assert "nadie lo vende" in v.puntuaciones[0].notas[0]
    assert v.puntuaciones[0].via == "ducados"


def test_forma_vale_cero_a_sabiendas(indice):
    v = puntuar([_r(4, "Forma Blueprint"), _r(2, "Braton Prime Barrel")], indice, None)
    forma = v.puntuaciones[0]
    assert forma.valor == 0.0 and forma.confianza == comparador.CONFIANZA_COMPLETA
    assert v.mejor == 1 and v.seguro


def test_sin_nada_que_valorar_no_se_elige(indice):
    v = puntuar([_r(5, "Pieza Sin Datos")], indice, None)
    assert v.mejor is None and not v.seguro
    assert v.resumen().startswith("Sin datos para elegir")


def test_solo_rareza_se_elige_la_mas_rara_pero_sin_seguridad(indice):
    con = indice
    con.execute(
        "INSERT INTO items (id, unique_name, nombre_en, categoria, comerciable) VALUES (7, '/Lotus/G', 'Otra', 'Warframes', 1)"
    )
    con.execute("INSERT INTO reliquia_recompensas VALUES (6, 'Intact', 7, 'Common', 25.0)")
    v = puntuar([_r(7, "Otra"), _r(5, "Pieza Sin Datos")], indice, None)
    assert v.mejor == 1 and not v.seguro
    assert "mas rara" in v.motivo


def test_casi_empate_se_avisa(indice):
    mercado = _mercado({
        "ash_prime_systems": _precios([50]),
        "nikana_prime_link": _precios([48]),
    })
    v = puntuar([_r(1, "Ash Prime Systems"), _r(3, "Nikana Prime Link")], indice, mercado)
    assert v.mejor == 0 and not v.seguro
    assert "casi empata con Nikana Prime Link" in v.motivo


def test_plazo_agotado_deja_de_pedir_precios(indice):
    reloj = iter([0.0, 0.0, 0.0, 0.1, 100.0, 100.0, 100.0, 100.1, 100.2, 100.3, 100.4, 100.5])
    pedidos = []

    def mercado(slug):
        pedidos.append(slug)
        return _precios([50])

    v = puntuar(
        [_r(1, "Ash Prime Systems"), _r(3, "Nikana Prime Link")],
        indice, mercado, plazo_s=6.0, reloj=lambda: next(reloj),
    )
    assert pedidos == ["ash_prime_systems"]
    assert "no dio tiempo" in v.puntuaciones[1].notas[0]
    assert v.mejor == 0


def test_puntuar_tarda_menos_de_lo_que_dura_la_cuenta_atras(indice):
    """Sin red (precios en cache), completar + puntuar cuatro piezas es cosa de milisegundos."""
    mercado = _mercado({s: _precios([10, 12, 14]) for s in ("ash_prime_systems", "braton_prime_barrel", "nikana_prime_link")})
    recompensas = [_r(1, "A"), _r(2, "B"), _r(3, "C"), _r(4, "Forma Blueprint")]
    inicio = time.perf_counter()
    v = puntuar(recompensas, indice, mercado)
    total = (time.perf_counter() - inicio) * 1000
    assert total < 200, f"puntuar tardo {total:.0f} ms"
    assert set(v.tiempos_ms) == {"completar", "precios", "puntuar", "total"}


def test_decidir_sin_recompensas():
    v = decidir([])
    assert v.mejor is None and not v.seguro


def test_rareza_por_ducados_no_consulta_el_indice():
    assert comparador.rareza_de(None, 1, 100) == "rara"
    assert comparador.rareza_de(None, 1, 45) == "poco comun"
    assert comparador.rareza_de(None, 1, 15) == "comun"


def test_servicio_emite_veredicto_sin_reventar_sin_indice(monkeypatch, tmp_path):
    """Sin indice construido el servicio devuelve un veredicto vacio en vez de una excepcion."""
    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    from farmadex.captura.comparador import ServicioComparador

    recibido = []
    servicio = ServicioComparador(escuadra=True, crear_market=lambda: None)
    servicio.veredicto.connect(lambda recompensas, v: recibido.append((recompensas, v)))
    servicio.comparar([])
    assert recibido and isinstance(recibido[0][1], Veredicto)
    assert recibido[0][1].mejor is None


def test_puntuacion_clave_ordena_objetivo_valor_rareza():
    a = Puntuacion(1, "a", valor=5.0, rareza="comun")
    b = Puntuacion(2, "b", valor=100.0)
    c = Puntuacion(3, "c", objetivo="0/1", valor=1.0)
    d = Puntuacion(4, "d", rareza="rara")
    assert sorted([a, b, c, d], key=lambda p: p.clave, reverse=True) == [c, b, a, d]


def test_el_servicio_crea_el_mercado_al_iniciar_y_no_lo_repite():
    """Crear el cliente HTTP cuesta ~220 ms: se hace al arrancar el hilo, no en la primera reliquia."""
    from types import SimpleNamespace

    from farmadex.captura.comparador import ServicioComparador

    creados = []

    def fabrica():
        creados.append(1)
        return SimpleNamespace(precios=lambda slug: None, cerrar=lambda: None)

    servicio = ServicioComparador(escuadra=True, crear_market=fabrica)
    assert creados == []  # nada hasta que arranca el hilo
    servicio.iniciar()
    assert len(creados) == 1
    assert servicio._precios_de() is not None
    assert len(creados) == 1  # la primera reliquia reutiliza el que ya habia
    servicio.cerrar()


def test_iniciar_sin_mercado_no_revienta():
    from farmadex.captura.comparador import ServicioComparador

    servicio = ServicioComparador(escuadra=True, crear_market=lambda: (_ for _ in ()).throw(OSError("sin red")))
    servicio.iniciar()  # solo se registra; la primera reliquia se puntua con ducados y rareza
    assert servicio._precios_de() is None
