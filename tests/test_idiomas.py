"""Traduccion de la interfaz: catalogos JSON con el castellano como clave."""

import json
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from farmadex import idiomas  # noqa: E402

CATALOGOS = sorted(idiomas.dir_catalogos().glob("*.json"))


@pytest.fixture()
def castellano_al_salir():
    yield
    idiomas.cargar("es")


def test_hay_un_catalogo_por_idioma_salvo_el_castellano():
    assert {r.stem for r in CATALOGOS} == set(idiomas.IDIOMAS) - {"es"}


def test_sin_traduccion_sale_el_castellano(castellano_al_salir):
    idiomas.cargar("es")
    assert idiomas.t("Buscar") == "Buscar"
    assert idiomas.t("{n} resultados", n=3) == "3 resultados"
    idiomas.cargar("en")
    assert idiomas.t("Buscar") == "Search"
    assert idiomas.t("{n} resultados", n=3) == "3 results"
    # Lo que no esta en el catalogo se queda en castellano, nunca una clave rara.
    assert idiomas.t("Texto que no existe") == "Texto que no existe"


def test_codigos_raros_caen_al_castellano_y_auto_resuelve(castellano_al_salir):
    assert idiomas.cargar("klingon") == "es"
    assert idiomas.cargar(None) in idiomas.IDIOMAS
    assert idiomas.resolver(idiomas.AUTOMATICO) in idiomas.IDIOMAS


def test_nombre_y_glosa_siguen_al_idioma(castellano_al_salir):
    fila = {"nombre_es": "Sistemas", "nombre_en": "Systems", "padre_es": None, "padre_en": "Ash Prime"}
    idiomas.cargar("es")
    assert idiomas.nombre(fila) == "Sistemas"
    assert idiomas.nombre(fila, "padre") == "Ash Prime"
    assert idiomas.glosa("Comun", "Common") == "Comun"
    idiomas.cargar("fr")
    assert idiomas.nombre(fila) == "Systems"
    assert idiomas.glosa("Comun", "Common") == "Commun"
    # Un termino que el catalogo no trae sale en el ingles del juego, no en castellano.
    assert idiomas.glosa("Defensa movil", "Mobile Defense") == "Mobile Defense"


@pytest.mark.parametrize("ruta", CATALOGOS, ids=lambda r: r.stem)
def test_los_catalogos_tienen_las_mismas_claves_y_los_mismos_huecos(ruta):
    referencia = json.loads((idiomas.dir_catalogos() / "en.json").read_text(encoding="utf-8"))
    catalogo = json.loads(ruta.read_text(encoding="utf-8"))
    claves = {k for k in catalogo if not k.startswith("_")}
    assert claves == {k for k in referencia if not k.startswith("_")}
    for clave in claves:
        assert catalogo[clave].strip(), f"traduccion vacia de {clave!r} en {ruta.stem}"
        assert set(re.findall(r"\{(\w+)\}", clave)) == set(re.findall(r"\{(\w+)\}", catalogo[clave])), (
            f"huecos distintos en {ruta.stem}: {clave!r}"
        )


def test_un_hueco_mal_escrito_en_el_catalogo_no_rompe_la_interfaz(castellano_al_salir, monkeypatch):
    idiomas.cargar("en")
    monkeypatch.setitem(idiomas._catalogo, "{n} resultados", "{cuenta} results")
    assert idiomas.t("{n} resultados", n=2) == "2 resultados"


def test_las_pestanas_cambian_de_idioma_al_vuelo(castellano_al_salir, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    # config.py fija sus rutas al importarse, asi que la variable de entorno llega
    # tarde: se apunta la ruta del fichero a mano para no pisar la configuracion real.
    from farmadex import config
    from farmadex.config import cargar

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_ajustes import PestanaAjustes
    from farmadex.ui.pestana_buscador import PestanaBuscador
    from farmadex.ui.pestana_mundo import PestanaMundo

    idiomas.cargar("es")
    ajustes, buscador, mundo = PestanaAjustes(), PestanaBuscador(), PestanaMundo()
    assert buscador.boton_objetivo.text() == "+ Objetivo"
    assert mundo.tarjetas["fisuras"].title() == "Fisuras del Vacio"

    codigos = []
    ajustes.idioma_cambiado.connect(codigos.append)
    ajustes.idioma.setCurrentIndex(ajustes.idioma.findData("en"))
    assert codigos == ["en"]
    assert cargar()["idioma_ui"] == "en"

    # Lo que hace la ventana al recibir la senal.
    idiomas.cargar("en")
    for pestana in (ajustes, buscador, mundo):
        pestana.retraducir()
    assert buscador.boton_objetivo.text() == "+ Goal"
    assert mundo.tarjetas["fisuras"].title() == "Void Fissures"
    assert mundo.filtro_modo.itemText(2) == "Steel Path"
    assert mundo.filtro_modo.itemData(2) == "Camino de Acero"  # el filtro compara por clave
    assert ajustes.tema.itemText(0) == "Void (blue)"
    assert ajustes.aviso_version.text() == "You are on the latest version"


def _claves_del_codigo() -> set[str]:
    """Todo texto que pasa por t(): los literales de las llamadas y los diccionarios de textos."""
    import ast
    from pathlib import Path

    raiz = Path(idiomas.__file__).parent
    claves: set[str] = set()
    for ruta in raiz.rglob("*.py"):
        for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
            if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)):
                continue
            # t("...") y self._fijo(poner, "...") de Ajustes, que traduce su segundo argumento.
            if nodo.func.id == "t" and nodo.args:
                literal = nodo.args[0]
            elif nodo.func.id == "_fijo" and len(nodo.args) >= 2:
                literal = nodo.args[1]
            else:
                continue
            if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                claves.add(literal.value)
        # Los atajos de Ajustes que pasan por _fijo con la clave como variable:
        # self._boton("..."), self._grupo("..."), self._nota("...") y self._fila(form, "...", campo).
        for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
            if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)):
                continue
            if nodo.func.attr in ("_boton", "_grupo", "_nota") and nodo.args:
                literal = nodo.args[0]
            elif nodo.func.attr == "_fila" and len(nodo.args) >= 2:
                literal = nodo.args[1]
            else:
                continue
            if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                claves.add(literal.value)
    # Textos que llegan a t() desde constantes, no como literal en la llamada.
    from farmadex.captura import reliquias
    from farmadex.datos import modos_mision
    from farmadex.online import worldstate
    from farmadex.ui import glosario, pestana_buscador, pestana_mundo, pestana_perfil, pestana_primes, widgets
    from farmadex.ui.pestana_ajustes import PestanaAjustes

    for grupo in (
        pestana_perfil.SINDICATOS.values(), pestana_perfil.INTRINSECOS.values(),
        pestana_mundo.ERAS, pestana_mundo.MODOS, pestana_mundo.TITULOS.values(),
        # Glosario: titulo y explicacion de cada termino.
        (texto for par in glosario.TERMINOS.values() for texto in par),
        pestana_buscador.CATEGORIAS_ES.values(), pestana_buscador.MOTIVOS_SIN_ESTIMACION.values(),
        (tema["titulo"] for tema in widgets.TEMAS.values()),
        PestanaAjustes.MODOS_PANTALLA.values(), worldstate.CICLOS.values(),
        worldstate.ESTADOS_CICLO.values(), (reliquias.AVISO_DATOS, reliquias.AVISO_MOTOR),
        # Titulos de las pestanas (VentanaOverlay._titulos_pestanas los pasa por t()).
        ("Buscar", "Objetivos", "Primes", "Mundo", "Perfil", "Ajustes"),
        pestana_primes.NOMBRES_REFINAMIENTO.values(),
        # Que hacer y como van las recompensas de cada tipo de mision.
        modos_mision.textos(),
    ):
        claves.update(grupo)
    return claves


@pytest.mark.parametrize("ruta", CATALOGOS, ids=lambda r: r.stem)
def test_todo_lo_que_pasa_por_t_esta_en_cada_catalogo(ruta):
    """Si alguien anade un t("texto nuevo") y no lo traduce, esto lo canta con la clave exacta."""
    catalogo = json.loads(ruta.read_text(encoding="utf-8"))
    faltan = sorted(_claves_del_codigo() - set(catalogo))
    assert not faltan, f"faltan {len(faltan)} claves en {ruta.stem}.json: {faltan}"
