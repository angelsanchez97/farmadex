from farmadex.datos import ducados


def test_pieza_barata_con_muchos_ducados_va_a_baro():
    v = ducados.decidir(45, 3)
    assert v.destino == ducados.DUCADOS and v.a_baro
    assert v.ducados_por_platino == 15.0


def test_pieza_con_precio_se_vende():
    assert ducados.decidir(100, 40).destino == ducados.PLATINO
    # Justo en el umbral (5p) ya no es "barata".
    assert ducados.decidir(100, 5).destino == ducados.PLATINO


def test_pieza_que_no_vale_nada_en_ninguno():
    assert ducados.decidir(15, 2).destino == ducados.INDIFERENTE


def test_sin_datos():
    assert ducados.decidir(45, None).destino == ducados.SIN_DATOS
    assert ducados.decidir(None, None).destino == ducados.SIN_DATOS
    # Un mod no tiene ducados: si tiene precio, se vende.
    assert ducados.decidir(None, 12).destino == ducados.PLATINO


def test_umbral_configurable():
    umbral = ducados.umbral_de({"ducados_umbral_platino": 10, "ducados_umbral_ducados": 100})
    assert ducados.decidir(45, 8, umbral).destino == ducados.INDIFERENTE
    assert ducados.decidir(100, 8, umbral).destino == ducados.DUCADOS
    # Basura en la configuracion: se vuelve al de fabrica.
    assert ducados.umbral_de({"ducados_umbral_platino": "muchos"}) == ducados.POR_DEFECTO
    assert ducados.umbral_de(None) == ducados.POR_DEFECTO


def test_valorar_desde_el_indice(indice_poblado):
    from farmadex.online.market import Orden, Precios

    con, _, _ = indice_poblado
    iid = con.execute("SELECT id FROM items WHERE nombre_en = 'Systems'").fetchone()[0]
    con.execute("UPDATE items SET ducados = 45 WHERE id = ?", (iid,))
    precios = Precios(slug="x", ventas=[Orden(platino=3, cantidad=1, usuario="a", estado="ingame")])
    assert ducados.valorar(con, iid, precios).destino == ducados.DUCADOS
    assert ducados.valorar(con, iid, Precios(slug="x", error="timeout")).destino == ducados.SIN_DATOS
    assert ducados.valorar(con, iid, None).ducados == 45
