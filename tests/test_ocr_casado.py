

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
