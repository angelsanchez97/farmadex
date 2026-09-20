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
