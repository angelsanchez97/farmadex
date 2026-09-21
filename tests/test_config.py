

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


def test_guardar_desde_varios_hilos_a_la_vez_no_revienta_ni_corrompe(tmp_path, monkeypatch):
    """La ventana, el buscador y los comprobadores guardan cada uno desde su hilo."""
    import json
    import threading

    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    config._compartida = None
    compartida = config.cargar()
    errores = []
    claves = ["hotkey_overlay", "hotkey_cursor", "hotkey_reliquias"]

    def martillear(n):
        try:
            for i in range(60):
                compartida[claves[i % 3]] = f"Ctrl+{n}{i}"
                config.guardar(compartida)
        except Exception as e:  # noqa: BLE001 - es lo que se mide
            errores.append(e)

    hilos = [threading.Thread(target=martillear, args=(n,)) for n in range(6)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert not errores, errores
    en_disco = json.loads(config.RUTA_CONFIG.read_text(encoding="utf-8"))
    assert set(en_disco) == set(config.POR_DEFECTO)
    assert config.cargar() is compartida


def test_un_config_que_no_es_un_objeto_se_ignora(tmp_path, monkeypatch):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    config._compartida = None
    config.crear_carpetas()
    config.RUTA_CONFIG.write_text("[1, 2, 3]", encoding="utf-8")
    assert config.cargar()["tema"] == config.POR_DEFECTO["tema"]
