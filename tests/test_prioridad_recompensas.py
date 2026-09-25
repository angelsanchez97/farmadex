"""Preajustes de "Al abrir reliquias, destacar": como decide cada uno y que motivo ensena."""

import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from farmadex.captura import prioridad as prio  # noqa: E402
from farmadex.captura.comparador import Puntuacion, decidir  # noqa: E402
from farmadex.captura.reliquias import SIN_IDENTIFICAR, Recompensa, completar  # noqa: E402


def _p(item_id, nombre, platino=None, ducados=None, **extra) -> Puntuacion:
    return Puntuacion(item_id=item_id, nombre=nombre, platino=platino, ducados=ducados, **extra)


def _elegida(puntuaciones, prioridad):
    v = decidir(puntuaciones, prioridad=prioridad)
    return (v.elegida.nombre if v.elegida else None), v


# -- Lo que me falta -------------------------------------------------------------


def test_me_falta_el_objetivo_gana_aunque_otra_valga_mucho_mas():
    nombre, v = _elegida([_p(1, "Cara", 60, 100), _p(2, "Objetivo", 3, 15, objetivo="0/1")], prio.ME_FALTA)
    assert nombre == "Objetivo" and v.seguro and "0/1" in v.motivo
    assert v.prioridad == prio.ME_FALTA


def test_me_falta_completar_set_va_detras_del_objetivo_y_delante_del_platino():
    set_casi = _p(1, "Set 3/4", 2, 15, set_tengo=2, set_total=4)
    set_empezado = _p(2, "Set 2/4", 2, 15, set_tengo=1, set_total=4)
    cara = _p(3, "Cara", 50, 100)
    nombre, v = _elegida([cara, set_empezado, set_casi], prio.ME_FALTA)
    assert nombre == "Set 3/4" and v.seguro and "3/4" in v.motivo
    objetivo = _p(4, "Objetivo", 1, 15, objetivo="1/2")
    assert _elegida([set_casi, objetivo], prio.ME_FALTA)[0] == "Objetivo"


def test_me_falta_una_pieza_que_ya_tienes_no_completa_nada():
    ya_la_tienes = _p(1, "Repetida", 2, 15, set_tengo=3, set_total=4, tienes=1)
    assert _elegida([ya_la_tienes, _p(2, "Cara", 20, 45)], prio.ME_FALTA)[0] == "Cara"


def test_me_falta_sin_dominar_segun_el_perfil_gana_al_platino_pero_a_medias_no():
    sin_tocar = _p(1, "Nunca usado", 4, 15, maestria_estado="sin_tocar")
    a_medias = _p(2, "Subiendolo", 4, 15, maestria_estado="a_medias")
    dominado = _p(3, "Dominado", 30, 45, maestria_estado="dominado")
    nombre, v = _elegida([dominado, a_medias, sin_tocar], prio.ME_FALTA)
    assert nombre == "Nunca usado" and v.seguro
    # Sin la pieza sin tocar, lo que decide es el platino.
    assert _elegida([a_medias, dominado], prio.ME_FALTA)[0] == "Dominado"


def test_me_falta_inventario_a_cero_cuenta_como_no_la_tienes():
    nombre, v = _elegida([_p(1, "Cara", 30, 45), _p(2, "Cero", 5, 15, tienes=0)], prio.ME_FALTA)
    assert nombre == "Cero" and v.motivo == "no lo tienes"


def test_me_falta_sin_datos_del_usuario_no_inventa_y_decide_el_platino_y_luego_los_ducados():
    nombre, v = _elegida([_p(1, "Barata", 5, 100), _p(2, "Cara", 20, 15)], prio.ME_FALTA)
    assert nombre == "Cara" and v.seguro and v.motivo.startswith("20 platino")
    # Precios casi iguales: desempatan los ducados.
    nombre, v = _elegida([_p(1, "Pocos ducados", 20, 15), _p(2, "Muchos ducados", 19, 100)], prio.ME_FALTA)
    assert nombre == "Muchos ducados" and v.seguro and "100 ducados" in v.motivo


# -- Mas platino ----------------------------------------------------------------


def test_platino_gana_la_mas_cara_aunque_otra_sea_objetivo():
    nombre, v = _elegida([_p(1, "Objetivo", 5, 15, objetivo="0/1"), _p(2, "Cara", 40, 45)], prio.PLATINO)
    assert nombre == "Cara" and v.seguro and v.motivo.startswith("40 platino")


def test_platino_con_empate_de_precio_decide_lo_que_te_falta():
    nombre, v = _elegida([_p(1, "Cara", 21, 45), _p(2, "Objetivo", 20, 15, objetivo="0/1")], prio.PLATINO)
    assert nombre == "Objetivo" and v.seguro and "0/1" in v.motivo


def test_platino_con_alguna_sin_precio_no_lo_afirma():
    nombre, v = _elegida([_p(1, "Con precio", 10, 45), _p(2, "Sin precio", None, 100)], prio.PLATINO)
    assert nombre == "Con precio" and not v.seguro and "Sin precio" in v.motivo


def test_platino_empate_total_se_dice():
    nombre, v = _elegida([_p(1, "Una", 10, 45), _p(2, "Otra", 10, 45)], prio.PLATINO)
    assert nombre == "Una" and not v.seguro and "casi empata con Otra" in v.motivo


# -- Mas ducados ----------------------------------------------------------------


def test_ducados_gana_la_de_mas_ducados_y_a_igualdad_el_platino():
    nombre, v = _elegida([_p(1, "Cara", 40, 45), _p(2, "Baro", 3, 100)], prio.DUCADOS)
    assert nombre == "Baro" and v.seguro and v.motivo.startswith("100 ducados")
    assert _elegida([_p(1, "Barata", 3, 100), _p(2, "Cara", 30, 100)], prio.DUCADOS)[0] == "Cara"


# -- Equilibrado (el de siempre) ------------------------------------------------


def test_equilibrado_es_el_criterio_de_siempre():
    from farmadex.captura.comparador import _valorar

    baro, cara = _p(1, "Baro", 3, 100), _p(2, "Poco", 6, 15)
    for p in (baro, cara):
        _valorar(p)
    # 100 ducados = "10p en ducados" > 6p: lo que haria un jugador con ella.
    assert _elegida([cara, baro], prio.EQUILIBRADO)[0] == "Baro"
    assert decidir([cara, baro]).prioridad == prio.EQUILIBRADO  # el valor por defecto de la funcion


# -- Casos comunes a todos -------------------------------------------------------


@pytest.mark.parametrize("prioridad", [prio.ME_FALTA, prio.PLATINO, prio.DUCADOS])
def test_una_sin_identificar_nunca_es_la_mejor_y_quita_seguridad(prioridad):
    nombre, v = _elegida([_p(SIN_IDENTIFICAR, "??", None, None), _p(2, "Conocida", 5, 15)], prioridad)
    assert nombre == "Conocida" and not v.seguro


@pytest.mark.parametrize("prioridad", [prio.ME_FALTA, prio.PLATINO, prio.DUCADOS])
def test_sin_ningun_dato_no_se_elige_al_azar(prioridad):
    v = decidir([_p(1, "X"), _p(2, "Y")], prioridad=prioridad)
    assert v.mejor is None and not v.seguro


def test_normalizar_una_clave_desconocida_cae_al_valor_por_defecto():
    assert prio.normalizar("inventada") == prio.ME_FALTA == prio.PRIORIDAD_POR_DEFECTO
    assert prio.normalizar(None) == prio.ME_FALTA
    assert [c for c, _t, _a in prio.PREAJUSTES] == [prio.ME_FALTA, prio.PLATINO, prio.DUCADOS, prio.EQUILIBRADO]


# -- El motivo grande de cada tarjeta ---------------------------------------------


def _r(**campos) -> Recompensa:
    r = Recompensa(1, "Pieza", "PIEZA", (0, 0, 10, 10))
    for k, v in campos.items():
        setattr(r, k, v)
    return r


def test_motivo_principal_sigue_al_preajuste():
    objetivo_cara = _r(objetivo="0/1", platino=40, ducados=100)
    assert prio.motivo_principal(objetivo_cara, prio.ME_FALTA) == prio.Motivo("falta", "Te falta")
    assert prio.motivo_principal(objetivo_cara, prio.PLATINO) == prio.Motivo("platino", "40 platino")
    assert prio.motivo_principal(objetivo_cara, prio.DUCADOS) == prio.Motivo("ducados", "100 ducados")
    assert prio.motivo_principal(objetivo_cara, prio.EQUILIBRADO).clave == "falta"
    assert prio.motivo_principal(_r(set_tengo=2, set_total=4, ducados=15), prio.ME_FALTA) == prio.Motivo(
        "set", "Completa set 3/4"
    )
    assert prio.motivo_principal(_r(maestria_estado="sin_tocar"), prio.ME_FALTA).texto == "Sin dominar"
    # Equilibrado ensena lo que mas vale: 100 ducados (= 10p) frente a 4p.
    assert prio.motivo_principal(_r(platino=4, ducados=100), prio.EQUILIBRADO).clave == "ducados"
    assert prio.motivo_principal(_r(platino=40, ducados=100), prio.EQUILIBRADO).clave == "platino"


def test_motivo_principal_sin_datos_dice_por_que():
    assert prio.motivo_principal(_r(vaulted=True), prio.PLATINO).clave == "boveda"
    assert prio.motivo_principal(_r(comerciable=False), prio.ME_FALTA).clave == "sin_valor"
    assert prio.motivo_principal(_r(), prio.ME_FALTA).clave == "sin_precio"
    sin_identificar = Recompensa(SIN_IDENTIFICAR, "?", "XX", (0, 0, 1, 1))
    assert prio.motivo_principal(sin_identificar, prio.ME_FALTA).clave == "sin_identificar"


# -- completar: de donde salen los datos --------------------------------------------


@pytest.fixture()
def indice_set(con):
    """Un prime de cuatro piezas (id 10) y un objeto suelto (id 20)."""
    con.execute("INSERT INTO items (id, unique_name, nombre_en, categoria) VALUES (10, '/P', 'Braton Prime', 'Primary')")
    for iid, nombre, ducados in ((11, "Barrel", 15), (12, "Blueprint", 25), (13, "Receiver", 45), (14, "Stock", 25)):
        con.execute(
            "INSERT INTO items (id, unique_name, nombre_en, categoria, padre_id, item_count, ducados, comerciable) "
            "VALUES (?, ?, ?, 'Primary', 10, 1, ?, 1)",
            (iid, f"/P/{nombre}", nombre, ducados),
        )
    con.execute("INSERT INTO items (id, unique_name, nombre_en, categoria, ducados) VALUES (20, '/S', 'Suelto', 'Misc', 100)")
    con.commit()
    return con


@pytest.fixture()
def usuario():
    from farmadex.estado import usuario_db

    u = sqlite3.connect(":memory:")
    u.executescript(usuario_db.ESQUEMA)
    yield u
    u.close()


def test_completar_sin_datos_del_usuario_deja_todo_sin_saber(indice_set, usuario):
    r = Recompensa(14, "Stock", "STOCK", (0, 0, 1, 1))
    completar([r], indice_set, usuario)
    assert (r.tienes, r.set_tengo, r.set_total, r.maestria_estado) == (None, 0, 4, None)
    assert prio.motivo_principal(r, prio.ME_FALTA).clave == "ducados"  # salta al siguiente sin inventar
    sin_usuario = Recompensa(14, "Stock", "STOCK", (0, 0, 1, 1))
    completar([sin_usuario], indice_set)
    assert sin_usuario.set_total == 0


def test_completar_cuenta_las_piezas_del_set_por_inventario_y_objetivos_completados(indice_set, usuario):
    from farmadex.estado import inventario, objetivos
    from types import SimpleNamespace

    inventario.guardar(usuario, [SimpleNamespace(unique_name="/P/Barrel", cantidad=1)])
    oid = objetivos.anadir(usuario, "/P/Blueprint", "Plano", 1)
    objetivos.sumar(usuario, oid, 1)
    r = Recompensa(14, "Stock", "STOCK", (0, 0, 1, 1))
    completar([r], indice_set, usuario)
    assert (r.set_tengo, r.set_total, r.tienes) == (2, 4, None)
    assert prio.motivo_principal(r, prio.ME_FALTA) == prio.Motivo("set", "Completa set 3/4")
    # La pieza con su objetivo completado: ya la tienes, no "completa" nada.
    plano = Recompensa(12, "Blueprint", "BP", (0, 0, 1, 1))
    completar([plano], indice_set, usuario)
    assert plano.tienes == 1 and prio.progreso_set(plano) is None


def test_completar_lee_la_maestria_del_objeto_padre_si_hay_perfil(indice_set, usuario):
    from farmadex.perfil import almacen

    r = Recompensa(14, "Stock", "STOCK", (0, 0, 1, 1))
    completar([r], indice_set, usuario)
    assert r.maestria_estado is None  # sin perfil no se sabe
    almacen.preparar(usuario)
    usuario.execute("INSERT INTO perfil_meta VALUES ('nombre', 'Tenno')")
    usuario.commit()
    completar([r], indice_set, usuario)
    assert r.maestria_estado == "sin_tocar"
    assert prio.motivo_principal(r, prio.ME_FALTA).texto == "Sin dominar"
