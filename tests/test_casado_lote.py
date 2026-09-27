"""Casado en lote (Casador.precasar) y lectura de la cabecera de la pantalla de mejoras.

El casado de una pantalla de mejoras llegaba a 3-8 s con el indice real: cada texto
que no es un nombre pasaba por 4-5 busquedas aproximadas contra ~10.000 nombres, una
por una. Ahora se preseleccionan todos a la vez y el resultado tiene que ser el mismo.
"""

from __future__ import annotations

import random

from farmadex.captura import builds as B
from farmadex.captura import ocr as O
from farmadex.captura.ocr import Leido

from test_builds_ocr import MODS, OTROS, _l, catalogo  # noqa: F401 - fixture


def _textos(nombres: list[str]) -> list[str]:
    """Nombres con erratas de OCR, pegados, con "Plano" y rotulos que no son nada."""
    gen = random.Random(5)
    salida = ["CAPACIDAD", "BONIFICACIONES DE RANGO", "+50% MAX. DE ENERGIA", "571", "3/37", "Zzzzz",
              "En el juego, abre Arsenal > Mejorar de la warframe", "Vitalidad (Mod)"]
    for n in nombres:
        salida += [n, n.upper(), n.replace(" ", ""), n + " Plano", "Plano de " + n]
        letras = list(n)
        for _ in range(2):
            i = gen.randrange(len(letras))
            letras[i] = gen.choice("aeiou0l1 ")
        salida.append("".join(letras))
    return salida


def test_precasar_da_lo_mismo_que_casar_uno_a_uno(catalogo):  # noqa: F811
    con, _ = catalogo
    nombres = [en for _u, en, _es, _c in MODS + OTROS] + [es for _u, _en, es, _c in MODS + OTROS]
    textos = _textos(nombres)
    uno, lote = B.crear_casador(con), B.crear_casador(con)
    esperado = {t: uno._casar(t, 85) for t in textos}
    lote.precasar(textos, 85)
    assert {t: lote._memo[(t, 85)] for t in textos} == esperado
    # Y `casar` sale de la memoria con lo mismo.
    assert all(lote.casar(t, 85) == esperado[t] for t in textos)
    assert sum(1 for v in esperado.values() if v[0]) > len(nombres)  # casa de verdad, no todo vacio


def test_precasar_tambien_en_la_copia_restringida(catalogo):  # noqa: F811
    con, ids = catalogo
    casador = B.crear_casador(con)
    restringido = casador.restringido(set(list(ids.values())[:3]))
    textos = _textos([en for _u, en, _es, _c in MODS[:5]])
    esperado = {t: restringido._casar(t, 82) for t in textos}
    restringido.precasar(textos, 82)
    assert {t: restringido._memo[(t, 82)] for t in textos} == esperado


def test_casar_lineas_prepara_todo_de_una_vez(catalogo, monkeypatch):  # noqa: F811
    con, _ = catalogo
    casador = B.crear_casador(con)
    lotes = []
    original = casador.precasar
    monkeypatch.setattr(casador, "precasar", lambda textos, umbral: lotes.append(list(textos)) or original(textos, umbral))
    sueltas = []
    original_casar = O.Casador._casar
    monkeypatch.setattr(O.Casador, "_casar", lambda self, t, u: sueltas.append(t) or original_casar(self, t, u))
    lineas = [_l("14Y", 700, 380), _l("Steel", 700, 400), _l("Fiber", 700, 421), _l("Vitality", 900, 400),
              _l("CAPACITY", 100, 100)]
    reconocidos = O.casar_lineas(lineas, casador, 85, subbloques=True)
    assert len(lotes) == 1
    assert sueltas == []  # nada se busco uno a uno: todo salio de la memoria
    assert {r.nombre for r in reconocidos} == {"Steel Fiber", "Vitality"}


def test_calentar_deja_la_primera_lectura_hecha(catalogo):  # noqa: F811
    con, _ = catalogo
    casador = B.crear_casador(con)
    casador.calentar()
    assert "claves" in casador._ordenadas and casador._palabras_de_nombre
    assert ("calentar casador", 82) not in casador.__dict__.get("_memo", {})


def test_rapidfuzz_compilado():
    """En Python puro todo el casado va ~100 veces mas lento (medido: 30 ms -> 8 s)."""
    assert O.rapidfuzz_en_cpp()


# -- cabecera ---------------------------------------------------------------------------


def test_rango_con_letra_por_cifra():
    """Captura real en castellano (2019): "MEJORAS: LIMBO PRIME RANGO 3O"."""
    assert B._nombres_de_equipo("LIMBO PRIME RANGO 3O")[1] == "LIMBO PRIME"
    assert B._nombres_de_equipo("NIDUS RANK 29")[1] == "NIDUS"


def test_cabecera_partida_en_dos_cajas():
    for izq, der in (("MEJORAS /", "EXCALIBUR [30]"), ("MEJORAS", "/EXCALIBUR [30]"),
                     ("UPGRAOES", "EXCALIBUR [30]"), ("ME JORAS:", "HYDROID")):
        lineas = [_l(izq, 190, 48, 200, 34), _l(der, 460, 50, 300, 32), _l("CAPACIDAD", 100, 120)]
        nombre, linea = B.cabecera(lineas)
        assert nombre in ("EXCALIBUR", "HYDROID"), (izq, der)
        assert (linea.x, linea.ancho) == (190, 570)  # la caja cubre las dos mitades
    # Una palabra de cabecera sin nada a su derecha en la fila no inventa equipo.
    assert B.cabecera([_l("MEJORAS", 190, 48), _l("EXCALIBUR", 190, 400)]) == ("", None)


def test_cabecera_partida_da_el_equipo_y_no_sale_como_sin_identificar(catalogo):  # noqa: F811
    con, _ = catalogo
    casador = B.crear_casador(con)
    categorias = dict(con.execute("SELECT id, categoria FROM items"))

    class Motor:
        tiempos = {}

        def leer_tira(self, imagen, alto_deteccion=None):
            return [Leido("MEJORAS /", 190, 48, 200, 34, 0.9), Leido("EXCALIBUR [30]", 460, 50, 300, 32, 0.9),
                    Leido("Vitality", 700, 400, 120, 20, 0.9), Leido("BUSCAR...", 106, 638, 120, 20, 0.9)]

    import numpy as np

    build = B.leer_build(np.zeros((1080, 1920, 3), np.uint8), Motor(), casador, categorias)
    assert build.equipo is not None and build.equipo.nombre == "Excalibur"
    assert build.sin_identificar == []


def test_sin_identificar_no_mete_rotulos_ni_estadisticas():
    assert not B._puede_ser_nombre("BONIFICACIONES DE RANGO")
    assert not B._puede_ser_nombre("TUTORIAL")
    assert not B._puede_ser_nombre("+50% Max. de Energia")
    assert not B._puede_ser_nombre("Combina tipos de danos elementales primarios para crear secundarios")
    assert B._puede_ser_nombre("Continuidad Prime")
    assert B._puede_ser_nombre("Zzzzz")
