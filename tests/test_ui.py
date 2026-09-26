"""Pruebas de la interfaz sin pantalla: ajustes, temas y cache de imagenes."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex.ui import widgets  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def ajustes(app, tmp_path, monkeypatch):
    # config.py fija sus rutas al importarse: si otra prueba ya lo importo, la
    # variable de entorno no vale y el tema cambiado se guardaria en la
    # configuracion real del usuario. Se apunta el fichero a mano.
    from farmadex import config

    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_ajustes import PestanaAjustes

    return PestanaAjustes()


def test_el_bloque_version_siempre_esta_y_pide_comprobar(ajustes):
    from farmadex import VERSION

    assert VERSION in ajustes.etiqueta_version.text()
    assert ajustes.aviso_version.isVisibleTo(ajustes)
    assert not ajustes.boton_instalar.isVisibleTo(ajustes)

    pedidas = []
    ajustes.comprobar_version.connect(lambda: pedidas.append(1))
    ajustes.boton_comprobar.click()
    assert pedidas == [1]
    assert "Comprobando" in ajustes.aviso_version.text()

    ajustes.estado_version("Estas en la ultima version")
    assert ajustes.aviso_version.text() == "Estas en la ultima version"


def test_anunciar_version_local_ensena_el_boton_de_instalar(ajustes):
    class Version:
        etiqueta = "0.9.9"
        url = "x"

    recibidas = []
    ajustes.instalar_version.connect(recibidas.append)
    ajustes.anunciar_version(Version(), local=True)
    assert ajustes.boton_instalar.isVisibleTo(ajustes)
    assert "0.9.9" in ajustes.aviso_version.text()
    ajustes.boton_instalar.click()
    assert len(recibidas) == 1


def test_cambiar_el_tema_lo_guarda_y_lo_avisa(ajustes):
    from farmadex.config import cargar

    # Se parte de otro tema a proposito: si el guardado ya fuera 'orokin', el
    # combo no cambiaria y la prueba pasaria o fallaria segun la configuracion
    # que tuviera el usuario en su equipo.
    ajustes.tema.setCurrentIndex(ajustes.tema.findData("vacio"))
    temas = []
    ajustes.tema_cambiado.connect(temas.append)
    ajustes.tema.setCurrentIndex(ajustes.tema.findData("orokin"))
    assert temas == ["orokin"]
    assert cargar()["tema"] == "orokin"


def test_la_disposicion_de_mundo_ya_no_esta_en_ajustes(ajustes):
    """Se elige en la propia pestana Mundo (feedback del tester, 4.2)."""
    assert not hasattr(ajustes, "diseno_mundo")


def test_elegir_tema_cambia_la_paleta_y_la_hoja(monkeypatch):
    original = dict(widgets.PALETA)
    try:
        paleta = widgets.elegir_tema("tenno")
        assert paleta["acento"] == widgets.TEMAS["tenno"]["acento"]
        assert widgets.TEMAS["tenno"]["acento"] in widgets.hoja_estilos()
        # Un nombre desconocido cae al tema por defecto, no revienta.
        # (el por defecto se lee de la constante: cambiarlo no debe romper la prueba)
        assert (
            widgets.elegir_tema("no existe")["acento"]
            == widgets.TEMAS[widgets.TEMA_POR_DEFECTO]["acento"]
        )
    finally:
        widgets.elegir_tema(next(k for k, v in widgets.TEMAS.items() if v["acento"] == original["acento"]))


def test_cache_de_imagenes_no_descarga_al_pintar(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QColor, QImage

    cache = widgets.CacheImagenes(tmp_path)
    descargas = []
    monkeypatch.setattr(cache, "_descargar", lambda: descargas.append(list(cache._cola)))

    assert cache.pixmap(None) is None
    # Falta en disco: se pide en segundo plano y de momento no hay nada que pintar.
    assert cache.pixmap("ash.png", 40) is None
    assert "ash.png" in cache._pendientes
    # Esta en disco: se devuelve escalada sin tocar la red.
    imagen = QImage(128, 128, QImage.Format_ARGB32)
    imagen.fill(QColor("white"))
    imagen.save(str(tmp_path / "forma.png"))
    mapa = cache.pixmap("forma.png", 40)
    assert mapa is not None and mapa.width() == 40
    assert cache.pixmap("forma.png", 40) is mapa  # cacheada en memoria


def test_categoria_en_espanol():
    from farmadex.ui.pestana_buscador import categoria_es

    assert categoria_es("Warframes") == "Warframe"
    assert categoria_es("Primary", "Componente") == "Arma primaria · pieza"
    assert categoria_es("Inventada") == "Inventada"
