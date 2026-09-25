"""Los dos formatos de WFCD (warframe-items) y lo que pasa cuando la fuente cambia.

El 2026-09-24 WFCD (PR #992) saco las piezas de receta a un catalogo aparte,
Components.json, y dejo en cada objeto solo {"uniqueName", "itemCount"} de sus
piezas. El mismo dia quito i18n.json (todos los idiomas juntos) y lo partio en
i18n/<idioma>.json. La actualizacion de datos de los usuarios empezo a fallar con
un 404 y la barra de estado ensenaba la excepcion de httpx entera.

Aqui se comprueba que los dos formatos dan el mismo indice, que un fichero opcional
que falte no tumba la actualizacion, que sin lo esencial no se instala un indice a
medias, y que al usuario le llega un mensaje corto.
"""
from __future__ import annotations

import json
import shutil

import httpx
import pytest

from farmadex.datos import descargas, indice
from farmadex.datos.descargas import ErrorDescarga, FuenteCambiada, extraer_idioma
from farmadex.datos.items import ImportadorItems

from conftest import FIXTURES

NUEVO = FIXTURES / "wfcd_nuevo"
ASH = "/Lotus/Powersuits/Ninja/NinjaPrime"
SISTEMAS = "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeSystemsComponent"
CHASIS = "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeChassisComponent"
CELULA = "/Lotus/Types/Items/MiscItems/OrokinCell"


def _leer(ruta):
    return json.loads(ruta.read_text(encoding="utf-8"))


def _importar_nuevo(con) -> ImportadorItems:
    indice.importar_glosario_idiomas(con)
    importador = ImportadorItems(
        con,
        extraer_idioma(_leer(NUEVO / "i18n" / "es.json"), "es"),
        {"fr": extraer_idioma(_leer(NUEVO / "i18n" / "fr.json"), "fr")},
    )
    importador.cargar_referencias(
        _leer(NUEVO / "Components.json"), [NUEVO / "Warframes.json", NUEVO / "Resources.json"]
    )
    for nombre in ("Warframes", "Resources"):
        importador.importar_categoria(NUEVO / f"{nombre}.json")
    return importador


def _pieza(con, unico):
    return con.execute(
        "SELECT i.nombre_en, i.nombre_es, p.unique_name, i.ducados, i.imagen, i.comerciable,"
        " i.item_count, i.descripcion_es FROM items i LEFT JOIN items p ON p.id = i.padre_id"
        " WHERE i.unique_name = ?",
        (unico,),
    ).fetchone()


def _fuentes(con, unico):
    return sorted(
        con.execute(
            "SELECT f.tipo, f.origen_texto, f.refinamiento, f.probabilidad FROM fuentes f"
            " JOIN items i ON i.id = f.item_id WHERE i.unique_name = ?",
            (unico,),
        ).fetchall()
    )


# -- importacion ---------------------------------------------------------


def test_formato_nuevo_completa_las_piezas_con_components_json(con):
    importador = _importar_nuevo(con)
    assert importador.referencias_vistas == 3
    assert importador.referencias_sin_resolver == set()

    nombre_en, nombre_es, padre, ducados, imagen, comerciable, cantidad, desc = _pieza(con, CHASIS)
    # El i18n nuevo dice "Chasis de Ash Prime"; la pieza lleva solo su parte, como antes,
    # porque la busqueda y el OCR le anteponen el padre.
    assert (nombre_en, nombre_es, padre) == ("Chassis", "Chasis", ASH)
    assert (ducados, imagen, comerciable, cantidad) == (15, "GenericWarframePrimeChassis.png", 1, 1)
    assert desc == "Componente del chasis del warframe Ash Prime."
    assert _pieza(con, SISTEMAS)[:4] == ("Systems", "Sistemas", ASH, 65)
    assert [f[1] for f in _fuentes(con, SISTEMAS)] == ["Axi A7 Relic (Intact)", "Axi A7 Relic (Radiant)"]

    # En frances tampoco entra el nombre compuesto: sale el del glosario.
    fr = con.execute(
        "SELECT n.nombre FROM items_nombres n JOIN items i ON i.id = n.item_id"
        " WHERE i.unique_name = ? AND n.idioma = 'fr'",
        (CHASIS,),
    ).fetchone()
    assert fr == ("Châssis",)

    # Un ingrediente que no es pieza (no esta en Components.json) sale de su categoria,
    # con su nombre de i18n, y al llegar su ficha propia deja de colgar de Ash Prime.
    celula = _pieza(con, CELULA)
    assert celula[1] == "Célula orokin" and celula[2] is None


def test_los_dos_formatos_dan_las_mismas_piezas(con, tmp_path):
    """Formato antiguo (fixtures/Warframes.json, piezas enteras) contra el nuevo."""
    importador = ImportadorItems(con, {})
    importador.importar_categoria(FIXTURES / "Warframes.json")
    antiguo = {u: (_pieza(con, u)[:3], _fuentes(con, u)) for u in (SISTEMAS, CHASIS)}

    import sqlite3

    otra = sqlite3.connect(tmp_path / "nuevo.sqlite")
    indice.crear_esquema(otra)
    indice.importar_glosario(otra)
    _importar_nuevo(otra)
    nuevo = {u: (_pieza(otra, u)[:3], _fuentes(otra, u)) for u in (SISTEMAS, CHASIS)}
    otra.close()
    assert antiguo == nuevo


def test_con_components_json_viejo_y_piezas_enteras_manda_lo_que_trae_el_objeto(con):
    """Si WFCD vuelve al formato antiguo, un Components.json que se quedo en disco no estorba."""
    importador = ImportadorItems(con, {})
    importador.cargar_referencias([{"uniqueName": CHASIS, "name": "Otro nombre"}])
    importador.importar_categoria(FIXTURES / "Warframes.json")
    assert importador.referencias_vistas == 0
    assert _pieza(con, CHASIS)[:3] == ("Chassis", "Chasis", ASH)


def test_sin_components_json_no_se_construye_el_indice(con, monkeypatch):
    importador = ImportadorItems(con, {})
    importador.importar_categoria(NUEVO / "Warframes.json")
    assert importador.referencias_sin_resolver == {SISTEMAS, CHASIS, CELULA}
    monkeypatch.setattr(indice, "UMBRAL_PIEZAS_PERDIDAS", 0)
    with pytest.raises(FuenteCambiada, match="Components.json"):
        indice.comprobar_piezas(importador)


def test_un_indice_sin_lo_esencial_no_pasa_la_comprobacion(indice_poblado):
    con, _, _ = indice_poblado
    with pytest.raises(FuenteCambiada) as error:
        indice.comprobar_indice(con)
    # Los fixtures solo traen Warframes y Relics: el resto de lo esencial falta.
    assert "Primary" in str(error.value) and "Warframes" not in str(error.value)


def test_construir_conserva_el_indice_anterior_si_la_fuente_esta_rota(tmp_path, monkeypatch):
    datos = tmp_path / "datos"
    datos.mkdir()
    shutil.copy(NUEVO / "Warframes.json", datos / "Warframes.json")
    shutil.copy(NUEVO / "Resources.json", datos / "Resources.json")
    for nombre in ("Primary", "Secondary", "Melee", "Relics"):
        (datos / f"{nombre}.json").write_text("[]", encoding="utf-8")
    anterior = tmp_path / "indice.sqlite"
    anterior.write_bytes(b"indice anterior")

    class DescargadorFalso:
        def __init__(self, progreso=None):
            self.estado = descargas.EstadoDatos()

        def sincronizar(self, forzar=False):
            return True

        def cerrar(self):
            pass

    monkeypatch.setattr(indice, "Descargador", DescargadorFalso)
    monkeypatch.setattr(indice, "DIR_DATOS", datos)
    monkeypatch.setattr(indice, "RUTA_INDICE", anterior)
    monkeypatch.setattr(indice, "crear_carpetas", lambda: None)
    monkeypatch.setattr(indice, "UMBRAL_PIEZAS_PERDIDAS", 0)

    # Referencias sin Components.json: no se instala nada ni queda un .nuevo a medias.
    with pytest.raises(FuenteCambiada):
        indice.construir()
    assert anterior.read_bytes() == b"indice anterior"
    assert not list(tmp_path.glob("indice.nuevo*"))

    # Falta un catalogo esencial: ni se empieza.
    (datos / "Relics.json").unlink()
    with pytest.raises(FuenteCambiada, match="Relics"):
        indice.construir()
    assert anterior.read_bytes() == b"indice anterior"


# -- traducciones ----------------------------------------------------------


def test_extraer_idioma_reconoce_los_dos_formatos_por_contenido():
    nuevo = _leer(NUEVO / "i18n" / "es.json")
    es = extraer_idioma(nuevo, "es")
    assert es[CHASIS]["name"] == "Chasis de Ash Prime"
    assert "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeBlueprint" not in es  # vacio

    antiguo = {
        ASH: {"es": {"name": "Ash Prime"}, "fr": {"name": "Ash Prime FR"}},
        CELULA: {"fr": {"name": "Cellule Orokin"}},  # sin castellano
    }
    assert extraer_idioma(antiguo, "es") == {ASH: {"name": "Ash Prime"}}
    assert extraer_idioma(antiguo, "fr")[CELULA] == {"name": "Cellule Orokin"}
    assert extraer_idioma(["no", "es", "un", "dict"], "es") == {}


# -- descargas ---------------------------------------------------------------


class Fuente:
    """Un WFCD de mentira: ficheros por nombre (relativo a data/json/) y lo que se pidio."""

    def __init__(self, ficheros: dict):
        self.ficheros = ficheros
        self.pedidos: list[str] = []

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        nombre = peticion.url.path.split("/data/json/", 1)[-1]
        self.pedidos.append(nombre)
        if nombre not in self.ficheros:
            return httpx.Response(404, text="404: Not Found")
        return httpx.Response(200, json=self.ficheros[nombre])


def _catalogo_basico() -> dict:
    ficheros = {f"{c}.json": [] for c in descargas.CATEGORIAS_ITEMS}
    ficheros["Warframes.json"] = _leer(NUEVO / "Warframes.json")
    return ficheros


@pytest.fixture()
def descargador(tmp_path, monkeypatch):
    monkeypatch.setattr(descargas, "DIR_DATOS", tmp_path)
    monkeypatch.setattr(descargas, "RUTA_ESTADO_DATOS", tmp_path / "estado_datos.json")
    monkeypatch.setattr(descargas.time, "sleep", lambda s: None)
    creados = []

    def crear(fuente):
        d = descargas.Descargador(cliente=httpx.Client(transport=httpx.MockTransport(fuente)))
        creados.append(d)
        return d

    yield crear
    for d in creados:
        d.cerrar()


def test_formato_nuevo_baja_solo_los_idiomas_que_se_usan(descargador, tmp_path):
    ficheros = _catalogo_basico()
    ficheros["Components.json"] = _leer(NUEVO / "Components.json")
    for idioma in ("es", *descargas.IDIOMAS_EXTRA, "ja", "ru"):
        ficheros[f"i18n/{idioma}.json"] = {ASH: {"name": f"Ash Prime ({idioma})"}}
    fuente = Fuente(ficheros)
    d = descargador(fuente)
    d._descargar_catalogo(d.rutas_items())

    assert "i18n.json" not in fuente.pedidos  # el fichero grande ni se intenta
    assert "i18n/ja.json" not in fuente.pedidos and "i18n/ru.json" not in fuente.pedidos
    assert _leer(tmp_path / "i18n_es.json") == {ASH: {"name": "Ash Prime (es)"}}
    assert _leer(tmp_path / "i18n_pl.json") == {ASH: {"name": "Ash Prime (pl)"}}
    assert (tmp_path / "Components.json").exists()
    assert not list(tmp_path.glob("*.descarga"))


def test_formato_antiguo_cae_al_i18n_json_y_no_pide_components(descargador, tmp_path):
    ficheros = _catalogo_basico()
    ficheros["i18n.json"] = {
        ASH: {"es": {"name": "Ash Prime"}, "fr": {"name": "Ash Prime"}},
        CELULA: {"es": {"name": "Célula orokin"}},
    }
    d = descargador(Fuente(ficheros))
    d._descargar_catalogo(d.rutas_items())  # sin Components.json ni i18n/: no lanza

    assert _leer(tmp_path / "i18n_es.json")[CELULA] == {"name": "Célula orokin"}
    assert _leer(tmp_path / "i18n_fr.json") == {ASH: {"name": "Ash Prime"}}
    assert not (tmp_path / "i18n_de.json").exists()  # no habia aleman: se sigue sin el
    assert not (tmp_path / "i18n.json").exists()  # el crudo de 50 MB no se queda en disco


def test_un_opcional_que_falta_no_tumba_la_actualizacion(descargador, tmp_path):
    ficheros = _catalogo_basico()
    ficheros["i18n/es.json"] = {ASH: {"name": "Ash Prime"}}
    del ficheros["Skins.json"]
    (tmp_path / "Skins.json").write_text('[{"uniqueName": "/viejo", "name": "Viejo"}]', encoding="utf-8")
    del ficheros["Honoria.json"]  # y sin copia anterior
    d = descargador(Fuente(ficheros))
    d._descargar_catalogo(d.rutas_items())

    assert "Viejo" in (tmp_path / "Skins.json").read_text(encoding="utf-8")  # la anterior sigue
    assert not (tmp_path / "Honoria.json").exists()
    assert (tmp_path / "Warframes.json").exists()
    # Lo opcional no cuenta para volver a bajar el catalogo en cada arranque.
    assert (tmp_path / "Honoria.json") not in d.rutas_imprescindibles()


def test_un_esencial_que_falta_para_la_actualizacion(descargador):
    ficheros = _catalogo_basico()
    del ficheros["Relics.json"]
    fuente = Fuente(ficheros)
    d = descargador(fuente)
    with pytest.raises(FuenteCambiada, match="Relics"):
        d._descargar_catalogo(d.rutas_items())
    assert fuente.pedidos.count("Relics.json") == 1  # un 404 no se reintenta


def test_recetas_nuevas_sin_components_json_obligan_a_bajar_otra_vez(descargador, tmp_path):
    """Lo que dejo en disco la 0.3.0 el dia del cambio: categorias nuevas y el corte en el 404."""
    d = descargador(Fuente({}))
    rutas = d.rutas_items()
    shutil.copy(FIXTURES / "Warframes.json", rutas["Warframes"])  # piezas enteras
    assert d._faltan_piezas(rutas) is False
    shutil.copy(NUEVO / "Warframes.json", rutas["Warframes"])  # piezas por referencia
    assert d._faltan_piezas(rutas) is True
    shutil.copy(NUEVO / "Components.json", d.ruta_piezas())
    assert d._faltan_piezas(rutas) is False


def test_sin_castellano_en_ningun_formato_no_se_sigue(descargador):
    d = descargador(Fuente(_catalogo_basico()))
    with pytest.raises(FuenteCambiada, match="castellano"):
        d._descargar_catalogo(d.rutas_items())


def test_sin_castellano_nuevo_se_usa_el_anterior(descargador, tmp_path):
    (tmp_path / "i18n_es.json").write_text(json.dumps({ASH: {"name": "Ash Prime"}}), encoding="utf-8")
    d = descargador(Fuente(_catalogo_basico()))
    d._descargar_catalogo(d.rutas_items())
    assert _leer(tmp_path / "i18n_es.json") == {ASH: {"name": "Ash Prime"}}


# -- mensaje al usuario ------------------------------------------------------


def test_el_motivo_para_el_usuario_es_corto_y_sin_urls():
    pytest.importorskip("PySide6")
    from farmadex import idiomas
    from farmadex.tareas import motivo_para_el_usuario

    idiomas.cargar("es")
    url = "https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/i18n.json"
    respuesta = httpx.Response(404, request=httpx.Request("GET", url))
    error_httpx = httpx.HTTPStatusError("Client error '404 Not Found'", request=respuesta.request,
                                        response=respuesta)
    casos = {
        FuenteCambiada("WFCD ya no publica Relics.json"): "la fuente ha cambiado",
        ErrorDescarga(url, error_httpx, 404): "la fuente ha cambiado",
        ErrorDescarga(url, httpx.ConnectError("sin red"), None): "sin conexion con la fuente",
        ErrorDescarga(url, None, 503): "la fuente no responde",
        httpx.ConnectTimeout("lento"): "sin conexion con la fuente",
        ValueError("otra cosa"): "fallo inesperado; detalles en el registro",
    }
    for error, esperado in casos.items():
        motivo = motivo_para_el_usuario(error)
        assert motivo == esperado
        assert "http" not in motivo and "mozilla" not in motivo


def test_la_pieza_se_llama_como_en_el_juego_sin_el_padre():
    """El juego dice "Pala Superior De Daikyu Prime"; el glosario propio decia "Extremidad
    superior" y el OCR no lo reconocia. Se usa el nombre de WFCD quitandole el padre."""
    from farmadex.datos.items import _sin_padre

    assert _sin_padre("Pala superior de Daikyu Prime", "Daikyu Prime") == "Pala superior"
    assert _sin_padre("Empuñadura de Daikyu Prime", "Daikyu Prime") == "Empuñadura"
    assert _sin_padre("Châssis d'Ash Prime", "Ash Prime") == "Châssis"
    assert _sin_padre("Telaio di Ash Prime", "Ash Prime") == "Telaio"
    assert _sin_padre("Daikyu Prime Oberer Wurfarm", "Daikyu Prime") == "Oberer Wurfarm"
    assert _sin_padre("Ash Prime", "Ash Prime") is None
    assert _sin_padre("Chasis", "Ash Prime") is None
