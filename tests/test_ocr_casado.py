

def test_plano_delante_se_casa_con_la_pieza_no_con_el_plano_principal(indice_poblado):
    """Captura real: "Plano De Chasis De Caliban Prime" salia como "Caliban Prime".

    El juego en castellano pone "Plano" delante; el casador solo sabia quitarlo
    detras, y sin quitarlo la pieza y el plano principal se parecian casi igual.
    """
    from farmadex.captura.ocr import Casador

    con, _, _ = indice_poblado
    casador = Casador(con)
    iid, etiqueta, puntos = casador.casar("Plano De Chasis De Ash Prime")[:3]
    assert "Chasis" in etiqueta and puntos == 100.0
    iid, etiqueta, _ = casador.casar("Plano De Sistemas De Ash Prime")[:3]
    assert "Sistemas" in etiqueta



def test_plano_delante_con_errata_es_el_plano_no_el_objeto(indice_poblado):
    """Captura real: "Plano De Daiky Prime" (el arco tapaba la u) salia "Sin identificar".

    Al quitar "Plano" la clave corta es la del arma entera, que no sale en
    reliquias; tiene que ganar su plano, tambien en la copia restringida.
    """
    from farmadex.captura.ocr import Casador

    con, _, _ = indice_poblado
    # El fixture no trae el plano principal: se clona el chasis como "Blueprint".
    columnas = [c[1] for c in con.execute("PRAGMA table_info(items)") if c[1] != "id"]
    valores = {c: ("?" if c in ("nombre_en", "nombre_es", "unique_name") else c) for c in columnas}
    con.execute(
        f"INSERT INTO items ({', '.join(columnas)}) SELECT {', '.join(valores.values())} "
        "FROM items WHERE unique_name LIKE '%AshPrimeChassisComponent'",
        tuple(v for c in columnas if valores[c] == "?" for v in
              [{"nombre_en": "Blueprint", "nombre_es": "Plano",
                "unique_name": "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeBlueprint"}[c]]),
    )
    plano = con.execute("SELECT id FROM items WHERE unique_name LIKE '%AshPrimeBlueprint'").fetchone()[0]
    casador = Casador(con)
    assert casador.casar("Plano De Ash Prime")[0] == plano
    assert casador.casar("Plano De Ash Primme")[0] == plano
    restringido = casador.restringido({plano})
    assert restringido.casar("Plano De Ash Primme")[0] == plano
    # Sin "Plano" delante no se sabe que pieza es: puede ser la segunda linea de
    # "Plano De Chasis De / Ash Prime" (dos chasis de Citrine salieron como plano).
    assert restringido.casar("Ash Prime")[0] != plano


def test_cada_letra_leida_cuenta_para_una_sola_palabra():
    """"sistemas hova prime" (Nova con la N mal leida) salia Ash Prime Sistemas:
    "ash" cabia a caballo de "sistem-as h-ova", letras que ya eran de "sistemas"."""
    from farmadex.captura.ocr import _contenidas

    leido = "sistemashovaprime"
    assert _contenidas(leido, ["nova", "prime", "sistemas"]) > _contenidas(leido, ["ash", "prime", "sistemas"])


def test_plano_pegado_y_articulo_falso_delante(indice_poblado):
    """El OCR pega "ChassisBlueprint" y "DeChasis"."""
    from farmadex.captura.ocr import Casador

    con, _, _ = indice_poblado
    casador = Casador(con)
    assert "Chas" in casador.casar("Ash Prime ChassisBlueprint")[1]
    assert "Chas" in casador.casar("Plano DeChasis De Ash Prime")[1]
