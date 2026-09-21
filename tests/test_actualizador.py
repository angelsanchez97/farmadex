from farmadex import VERSION
from farmadex.actualizador.app import analizar_release, es_mas_nueva, numeros


def test_comparacion_por_numero_no_por_texto():
    assert es_mas_nueva("0.10.0", "0.9.0")
    assert es_mas_nueva("v1.0.0", "0.9.9")
    assert not es_mas_nueva("0.1.0", "0.1.0")
    assert not es_mas_nueva("0.0.9", "0.1.0")


def test_versiones_ilegibles_no_provocan_avisos():
    assert numeros("no es una version") is None
    assert not es_mas_nueva("beta", "0.1.0")
    assert not es_mas_nueva("1.2.3", "sin version")


def test_analizar_una_release_con_instalador():
    version = analizar_release(
        {
            "tag_name": "v0.2.0",
            "body": "Arreglado el OCR",
            "html_url": "https://github.com/x/y/releases/v0.2.0",
            "assets": [
                {"name": "notas.txt", "browser_download_url": "https://x/notas.txt"},
                {"name": "Farmadex-0.2.0-setup.exe", "browser_download_url": "https://x/setup.exe"},
            ],
        }
    )
    assert version.etiqueta == "v0.2.0"
    assert version.url == "https://x/setup.exe"


def test_release_sin_instalador_cae_a_la_pagina():
    version = analizar_release({"tag_name": "v0.2.0", "html_url": "https://pagina"})
    assert version.url == "https://pagina"


def test_release_vacia():
    assert analizar_release({}) is None


def test_comprobar_datos_sin_red_no_revienta(monkeypatch):
    from farmadex.actualizador import datos

    class DescargadorRoto:
        def version_items(self):
            raise ConnectionError("sin red")

        def cerrar(self):
            pass

    monkeypatch.setattr(datos, "Descargador", DescargadorRoto)
    comprobador = datos.ComprobadorDatos()
    comprobador.comprobar_ahora()  # no lanza nada


def test_comprobar_app_traga_cualquier_fallo_del_cliente(monkeypatch):
    from farmadex.actualizador import app

    monkeypatch.setattr(app, "PROPIETARIO", "alguien")
    monkeypatch.setattr(app, "REPOSITORIO", "farmadex")
    comprobador = app.ComprobadorApp()
    avisos = []
    comprobador.nueva_version.connect(avisos.append)

    def reventar(*a, **k):
        raise ValueError("JSON raro")

    monkeypatch.setattr(comprobador.cliente, "json", reventar)
    comprobador.comprobar_ahora()
    monkeypatch.setattr(comprobador.cliente, "json", lambda *a, **k: ["no", "es", "un", "dict"])
    comprobador.comprobar_ahora()
    assert avisos == []

    monkeypatch.setattr(
        comprobador.cliente, "json", lambda *a, **k: {"tag_name": "v99.0.0", "html_url": "u"}
    )
    comprobador.comprobar_ahora()
    assert [v.etiqueta for v in avisos] == ["v99.0.0"]
    comprobador.cerrar()


def test_comprobar_a_mano_contesta_siempre(monkeypatch):
    """El boton "Comprobar ahora" de Ajustes no puede quedarse callado.

    Lo reporto el usuario con la 0.1.4: el boton solo miraba la carpeta local de
    compilaciones, que en su PC esta vacia, asi que con la 0.1.5 ya publicada en
    GitHub seguia diciendole que estaba en la ultima version.
    """
    from farmadex.actualizador import app

    monkeypatch.setattr(app, "PROPIETARIO", "alguien")
    monkeypatch.setattr(app, "REPOSITORIO", "farmadex")
    comprobador = app.ComprobadorApp()
    nuevas, iguales, fallos = [], [], []
    comprobador.nueva_version.connect(nuevas.append)
    comprobador.sin_novedades.connect(lambda: iguales.append(1))
    comprobador.fallo.connect(fallos.append)

    # 1) La misma version que la instalada: lo dice, no se calla.
    monkeypatch.setattr(comprobador.cliente, "json", lambda *a, **k: {"tag_name": VERSION})
    comprobador.comprobar_ahora(manual=True)
    assert iguales == [1] and nuevas == [] and fallos == []

    # 2) Sin red: tambien lo dice.
    def reventar(*a, **k):
        raise RuntimeError("sin conexion")

    monkeypatch.setattr(comprobador.cliente, "json", reventar)
    comprobador.comprobar_ahora(manual=True)
    assert fallos == ["sin conexion"]

    # 3) La automatica del arranque contesta igual: quien escucha decide si lo
    #    ensena. Una version nueva sale en el banner de la ventana; "estas al dia"
    #    solo se escribe en Ajustes, que es donde se va a mirar.
    iguales.clear()
    monkeypatch.setattr(comprobador.cliente, "json", lambda *a, **k: {"tag_name": VERSION})
    comprobador.comprobar_ahora()
    assert iguales == [1]
    comprobador.cerrar()


def test_a_mano_no_se_queda_con_la_respuesta_guardada(monkeypatch):
    """Sin esto, pulsar el boton justo despues de publicar repite lo de hace una hora."""
    from farmadex.actualizador import app

    monkeypatch.setattr(app, "PROPIETARIO", "alguien")
    monkeypatch.setattr(app, "REPOSITORIO", "farmadex")
    comprobador = app.ComprobadorApp()
    caches = []
    monkeypatch.setattr(
        comprobador.cliente,
        "json",
        lambda url, segundos_cache=0.0, **k: caches.append(segundos_cache) or {"tag_name": VERSION},
    )
    comprobador.comprobar_ahora(manual=True)
    comprobador.comprobar_ahora()
    assert caches == [0, 3600]
    comprobador.cerrar()


def test_se_ofrece_el_instalador_no_el_zip():
    """GitHub devuelve los adjuntos por orden alfabetico y "portable.zip" va antes."""
    version = analizar_release(
        {
            "tag_name": "v0.1.5",
            "assets": [
                {"name": "Farmadex-0.1.5-portable.zip", "browser_download_url": "zip"},
                {"name": "Farmadex-0.1.5-setup.exe", "browser_download_url": "exe"},
            ],
        }
    )
    assert version.url == "exe"


def test_la_version_nueva_se_avisa_en_el_banner_no_en_la_linea_de_estado():
    """El usuario pidio que al abrir el programa se le diga si hay actualizacion.

    Ya se comprobaba al arrancar, pero el aviso iba a la linea de estado del pie,
    que a los pocos segundos la pisa el primer mensaje de la carga de datos: salia
    y desaparecia. El banner, en cambio, se queda hasta que deja de hacer falta.
    """
    import types

    from farmadex.actualizador.app import Version
    from farmadex.ui.overlay import VentanaOverlay

    avisos, estado = {}, []
    falso = types.SimpleNamespace(
        _aviso=lambda clave, texto: avisos.__setitem__(clave, texto),
        estado=types.SimpleNamespace(setText=estado.append),
        ajustes=types.SimpleNamespace(anunciar_version=lambda *a, **k: None),
        nueva_version=None,
        actualizacion_lista=None,
        _fallo_actualizacion=None,
        config={"actualizar_automaticamente": False},
    )
    falso._avisar_descarga_manual = lambda v, motivo=None: VentanaOverlay._avisar_descarga_manual(falso, v, motivo)
    falso._conviene_autoactualizar = lambda v: VentanaOverlay._conviene_autoactualizar(falso, v)
    version = Version(etiqueta="v9.9.9", url="https://ejemplo/Farmadex-setup.exe", notas="")

    VentanaOverlay._hay_version_nueva(falso, version)

    assert "v9.9.9" in avisos["version"]
    assert version.url in avisos["version"], "tiene que poder pincharse para descargar"
    assert estado == [], "la linea de estado se pisa sola: el aviso no puede vivir ahi"
