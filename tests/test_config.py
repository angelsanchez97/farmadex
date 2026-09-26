

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


# -- Todas las claves que usa el codigo tienen que estar en POR_DEFECTO ---------------
#
# `cargar` tira lo que no esta en POR_DEFECTO: una clave nueva que se guarde sin
# anadirla alli funciona mientras la app sigue abierta y se pierde al reiniciar
# (paso con la chincheta del modo juego, el orden de Primes y las tarjetas HUD).

def _claves_de_config_en_el_codigo() -> dict[str, str]:
    """{clave: donde} de lo que el codigo lee o guarda en la configuracion.

    Se recorre src/ con ast buscando `<algo>config.get(...)`, `<algo>config[...]`,
    `cfg...` y `_guardar(...)`; los argumentos que son constantes (CLAVE_X,
    modulo.CLAVE_X) se resuelven con las asignaciones de texto de todo src/."""
    import ast
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "src" / "farmadex"
    arboles = {r: ast.parse(r.read_text(encoding="utf-8")) for r in raiz.rglob("*.py")}
    constantes: dict[str, set[str]] = {}
    for arbol in arboles.values():
        for nodo in ast.walk(arbol):
            if (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                    and isinstance(nodo.targets[0], ast.Name)
                    and isinstance(nodo.value, ast.Constant) and isinstance(nodo.value.value, str)):
                constantes.setdefault(nodo.targets[0].id, set()).add(nodo.value.value)

    def es_config(expr) -> bool:
        texto = ast.unparse(expr).lower()
        return texto.endswith(("config", "cfg")) and "configurad" not in texto

    def valor(expr) -> set[str]:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return {expr.value}
        nombre = expr.id if isinstance(expr, ast.Name) else expr.attr if isinstance(expr, ast.Attribute) else ""
        if nombre.startswith("CLAVE_"):
            return constantes.get(nombre, set())
        return set()

    claves: dict[str, str] = {}
    for ruta, arbol in arboles.items():
        if ruta.name == "config.py":
            continue
        for nodo in ast.walk(arbol):
            args = []
            if isinstance(nodo, ast.Subscript) and es_config(nodo.value):
                args = [nodo.slice]
            elif isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) and nodo.args:
                if nodo.func.attr in ("get", "setdefault", "pop") and es_config(nodo.func.value):
                    args = [nodo.args[0]]
                elif nodo.func.attr == "_guardar" and ruta.name == "pestana_ajustes.py":
                    args = [nodo.args[0]]
            for arg in args:
                for clave in valor(arg):
                    claves.setdefault(clave, f"{ruta.name}:{nodo.lineno}")
    return claves


def test_todas_las_claves_que_usa_el_codigo_estan_en_por_defecto():
    from farmadex import config

    claves = _claves_de_config_en_el_codigo()
    # Que el recorrido de verdad encuentra cosas (si no, el test no probaria nada).
    for esperada in ("compacta_siempre_encima", "modo_juego_tarjetas", "primes_orden", "ocr_modo",
                     "prioridad_recompensas", "escala_interfaz", "colores_personalizados",
                     "bienvenida_vista", "hotkey_build", "mundo_facciones", "avisos_mundo_enviados"):
        assert esperada in claves, esperada
    faltan = {c: donde for c, donde in claves.items() if c not in config.POR_DEFECTO}
    assert not faltan, f"claves que cargar() tiraria al reiniciar: {faltan}"
    # Las que se montan con texto: hotkey_<nombre> y la geometria de cada modo.
    for nombre in ("overlay", "cursor", "reliquias", "build", "agrietado"):
        assert f"hotkey_{nombre}" in config.POR_DEFECTO
    for clave in ("overlay_geometria", "overlay_geometria_compacto", "overlay_geometria_video"):
        assert clave in config.POR_DEFECTO


def test_las_claves_nuevas_sobreviven_a_reiniciar(tmp_path, monkeypatch):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(config, "_compartida", None)
    cfg = config.cargar()
    cfg.update({"compacta_siempre_encima": False, "modo_juego_tarjetas": False, "primes_orden": "falta",
                "ocr_modo": "ligero", "overlay_geometria_video": [1, 2, 3, 4]})
    config.guardar(cfg)
    de_nuevo = config.cargar(recargar=True)
    assert de_nuevo["compacta_siempre_encima"] is False
    assert de_nuevo["modo_juego_tarjetas"] is False
    assert de_nuevo["primes_orden"] == "falta"
    assert de_nuevo["ocr_modo"] == "ligero"
    assert de_nuevo["overlay_geometria_video"] == [1, 2, 3, 4]
