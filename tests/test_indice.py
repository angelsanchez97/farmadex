from farmadex.datos import indice, items


def test_normalizar_quita_acentos_y_signos():
    assert items.normalizar("Intercepción") == "intercepcion"
    assert items.normalizar("Ash  Prime!") == "ash prime"
    assert items.normalizar("Arch-Gun") == "arch gun"


def test_nombre_canonico_reliquia():
    assert items.nombre_canonico_reliquia("Axi A7 Radiant") == ("Axi A7", "Radiant")
    assert items.nombre_canonico_reliquia("Axi A7") == ("Axi A7", "Intact")


def test_busqueda_en_espanol_encuentra_el_componente(indice_poblado):
    con, _, _ = indice_poblado
    resultados = indice.buscar(con, "sistemas ash prime")
    assert resultados, "la busqueda en espanol no devolvio nada"
    primero = resultados[0]
    assert primero["nombre_es"] == "Sistemas"
    assert primero["padre_en"] == "Ash Prime"


def test_busqueda_en_ingles_llega_al_mismo_objeto(indice_poblado):
    con, _, _ = indice_poblado
    es = indice.buscar(con, "sistemas ash prime")[0]["item_id"]
    en = indice.buscar(con, "ash prime systems")[0]["item_id"]
    assert es == en


def test_busqueda_sin_acentos_y_con_falta_de_ortografia(indice_poblado):
    con, _, _ = indice_poblado
    assert indice.buscar(con, "sistemas")
    assert indice.buscar(con, "asch prime")  # cae al modo difuso


def test_ficha_encadena_componente_reliquia_y_vaulted(indice_poblado):
    con, _, _ = indice_poblado
    item_id = indice.buscar(con, "sistemas ash prime")[0]["item_id"]
    ficha = items.ficha(con, item_id)

    assert ficha["padre"]["nombre_en"] == "Ash Prime"
    reliquias = [f for f in ficha["fuentes"] if f["tipo"] == "reliquia"]
    assert reliquias, "el componente no tiene fuentes de reliquia"
    assert all(f["origen_id"] for f in reliquias), "hay reliquias sin enlazar"
    assert {f["refinamiento"] for f in reliquias} >= {"Intact", "Radiant"}
    assert reliquias[0]["reliquia_en"] == "Axi A7 Relic"
    assert reliquias[0]["reliquia_vaulted"] == 1


def test_traducciones_del_glosario(con):
    assert indice.traducir(con, "mision", "Interception") == "Interceptación"
    assert indice.traducir(con, "rareza", "Rare") == "Raro"
    # Lo que no esta traducido se devuelve tal cual, no se pierde.
    assert indice.traducir(con, "mision", "Inventado") == "Inventado"
