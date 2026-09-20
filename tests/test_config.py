

def test_los_ajustes_no_se_pisan_entre_si(tmp_path, monkeypatch):
    """Lo reporto el usuario: "no me guarda los ajustes, siempre me pone el por defecto".

    La ventana, la pestana de Ajustes y el buscador pedian la configuracion cada
    uno por su cuenta y guardaban el fichero entero. Elegias un tema, cerrabas el
    programa, la ventana guardaba su geometria con el tema de antes y se perdia.
    """
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "_compartida", None)

    ventana = config.cargar()
    ajustes = config.cargar()
    assert ventana is ajustes, "tiene que ser el mismo diccionario para todos"

    ajustes["tema"] = "consola"
    config.guardar(ajustes)
    ventana["overlay_geometria"] = [10, 20, 800, 600]
    config.guardar(ventana)  # al cerrar

    de_nuevo = config.cargar(recargar=True)
    assert de_nuevo["tema"] == "consola"
    assert de_nuevo["overlay_geometria"] == [10, 20, 800, 600]


def test_guardar_un_diccionario_ajeno_no_deja_memoria_vieja(tmp_path, monkeypatch):
    """Si alguien guarda una copia suya, la siguiente lectura tiene que ir al fichero."""
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "_compartida", None)

    config.cargar()["tema"] = "orokin"
    aparte = dict(config.POR_DEFECTO, tema="tenno")
    config.guardar(aparte)
    assert config.cargar()["tema"] == "tenno"
