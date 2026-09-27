"""Pantalla de recompensas con el juego en frances y otros formatos de pantalla.

Sale de capturas reales de YouTube en frances (2025, cuatro pantallas de recompensas
de una partida de Defensa en fisura) y de esas mismas reducidas a 720p/768p/900p, en
16:10 y 21:9, con la escala del HUD al 75 % y como ventana dentro del escritorio. Antes
se leian 9 de 16 tarjetas y ahora 16 de 16, sin inventar ninguna:

- El plano en frances es "(Schéma)" ("Lex Prime (Schéma)", "Forma (Schéma)"); el
  glosario solo traia "Plan".
- "2 X Forma (Schéma)" (y pegado, "2XForma(Schema"): la cantidad no es parte del nombre.
- Tres jugadores con la misma pieza: la franja se quedaba con una y las otras salian
  "sin identificar".
- Con la escala del HUD por debajo del 100 % la fila fija corta los nombres: cuatro
  tarjetas sin reconocer no bastan para no mirar la franja entera.
"""

from __future__ import annotations

import numpy as np

from farmadex.captura import recompensas_rapidas as rapidas
from farmadex.captura.ocr import Casador, Leido, Reconocido
from farmadex.captura.pantalla import Region
from farmadex.captura.reliquias import CATEGORIAS_RECOMPENSA, _quitar_repetidos

from test_fila_recompensas import catalogo_reliquia  # noqa: F401 - fixture


def test_schema_es_el_plano_en_frances(catalogo_reliquia):
    con, ids = catalogo_reliquia
    casador = Casador(con, CATEGORIAS_RECOMPENSA)
    for texto in ("Fang Prime (Schéma)", "FangPrime(Schema", "Orthos Prime (Schema)"):
        item_id, _nombre, _puntos = casador.casar(texto, 80)
        assert item_id in (ids["/m/FangPrime/Bp"], ids["/m/OrthosPrime/Bp"]), texto


def test_la_cantidad_delante_no_es_parte_del_nombre():
    assert "Forma (Schéma)" in rapidas.variantes_texto("2 X Forma (Schéma)")
    assert "Forma(Schema" in rapidas.variantes_texto("2XForma(Schema")
    assert rapidas.RE_CANTIDAD_DELANTE.sub("", "Fang Prime") == "Fang Prime"


def test_la_misma_pieza_en_dos_tarjetas_no_se_junta():
    fang = [Reconocido("Fang Prime (Schema)", 7, "Fang Prime Plano", 100.0, (100, 50, 200, 24)),
            Reconocido("Fang Prime", 7, "Fang Prime Plano", 90.0, (110, 76, 120, 24)),  # misma tarjeta, otra linea
            Reconocido("Fang Prime (Schema)", 7, "Fang Prime Plano", 100.0, (600, 50, 200, 24))]
    salida = _quitar_repetidos(fang)
    assert [r.caja[0] for r in salida] == [100, 600]


def test_tarjetas_sin_reconocer_no_bastan_para_no_mirar_la_franja(catalogo_reliquia, monkeypatch):
    con, ids = catalogo_reliquia
    casador = rapidas.CasadorEscalonado(Casador(con, CATEGORIAS_RECOMPENSA))
    monkeypatch.setattr(rapidas, "leer_fila", lambda imagen, motor: [
        Leido("RhinoPr rime", 218, 37, 250, 33, 0.9), Leido("ystemes", 529, 37, 150, 31, 0.9)])
    monkeypatch.setattr(rapidas, "casar_fila", lambda lineas, casador, maximo, grupos: [
        Reconocido(l.texto, rapidas.SIN_IDENTIFICAR, "", 0.0, (l.x, l.y, l.ancho, l.alto)) for l in lineas])

    def lento(ventana, tiempos):
        lento.veces += 1
        return [Reconocido("Fang Prime (Schema)", ids["/m/FangPrime/Bp"], "Fang Prime Plano", 100.0, (700, 560, 250, 33)),
                Reconocido("Orthos Prime (Schema)", ids["/m/OrthosPrime/Bp"], "Orthos Prime Plano", 100.0,
                           (1100, 560, 250, 33))]

    lento.veces = 0
    imagen = np.zeros((86, 1331, 3), np.uint8)
    lectura = rapidas.leer_pantalla(lambda region: imagen, Region(0, 0, 2560, 1440), None, casador, 2, lento)
    assert lento.veces == 1 and lectura.via == "franja"
    assert [r.item_id for r in lectura.recompensas] == [ids["/m/FangPrime/Bp"], ids["/m/OrthosPrime/Bp"]]
