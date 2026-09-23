"""Casado y busqueda con el juego en frances, aleman y portugues.

WFCD (warframe-items) trae el nombre completo de los objetos en estos idiomas,
pero no el de las piezas sueltas ("Chassis", "Barrel"): esas se completan con
glosario_fr.json / glosario_de.json / glosario_pt.json, igual que ya se hacia
con glosario_es.json. Estos glosarios tambien traen la palabra local de
"Blueprint" (Plan/Bauplan/Projeto), que el casador quita de delante o detras
del texto leido, igual que ya hacia con "Plano" y "Blueprint".
"""

import json

from farmadex.captura.ocr import Casador
from farmadex.datos import indice
from farmadex.datos.items import ImportadorItems


def _importar_multi(con, tmp_path, catalogos: dict, i18n: dict, idiomas_extra: dict) -> ImportadorItems:
    indice.importar_glosario_idiomas(con)
    importador = ImportadorItems(con, i18n, idiomas_extra)
    for nombre, objetos in catalogos.items():
        ruta = tmp_path / f"{nombre}.json"
        ruta.write_text(json.dumps(objetos), encoding="utf-8")
        importador.importar_categoria(ruta)
    importador.promocionar_ingredientes()
    importador.registrar_piezas_con_nombre_propio()
    indice.poblar_busqueda(con)
    con.commit()
    return importador


CATALOGOS = {
    "Warframes": [
        {"uniqueName": "/Lotus/Powersuits/Sentient/CalibanPrime", "name": "Caliban Prime",
         "category": "Warframes",
         "components": [{"uniqueName": "/Lotus/Types/Recipes/WarframeRecipes/CalibanPrimeChassisComponent",
                          "name": "Chassis"}]},
    ],
    "Primary": [
        {"uniqueName": "/Lotus/Weapons/Tenno/Rifle/BratonPrimeWeapon", "name": "Braton Prime",
         "category": "Primary",
         "components": [{"uniqueName": "/Lotus/Weapons/Tenno/Rifle/BratonPrimeBarrelComponent",
                          "name": "Barrel"}]},
    ],
    "Resources": [
        {"uniqueName": "/Lotus/Types/Items/MiscItems/OrokinCell", "name": "Orokin Cell",
         "category": "Resources"},
    ],
}

I18N_ES = {
    "/Lotus/Powersuits/Sentient/CalibanPrime": {"name": "Caliban Prime"},
    "/Lotus/Weapons/Tenno/Rifle/BratonPrimeWeapon": {"name": "Braton Prime"},
    "/Lotus/Types/Items/MiscItems/OrokinCell": {"name": "Celula orokin"},
}

# Los nombres propios (Caliban Prime, Braton Prime) no cambian de idioma, tal como
# los trae de verdad warframe-items; solo el recurso, que si tiene traduccion real.
IDIOMAS_EXTRA = {
    "fr": {
        "/Lotus/Powersuits/Sentient/CalibanPrime": {"name": "Caliban Prime"},
        "/Lotus/Weapons/Tenno/Rifle/BratonPrimeWeapon": {"name": "Braton Prime"},
        "/Lotus/Types/Items/MiscItems/OrokinCell": {"name": "Cellule Orokin"},
    },
    "de": {
        "/Lotus/Powersuits/Sentient/CalibanPrime": {"name": "Caliban Prime"},
        "/Lotus/Weapons/Tenno/Rifle/BratonPrimeWeapon": {"name": "Braton Prime"},
        "/Lotus/Types/Items/MiscItems/OrokinCell": {"name": "Orokin Zelle"},
    },
    "pt": {
        "/Lotus/Powersuits/Sentient/CalibanPrime": {"name": "Caliban Prime"},
        "/Lotus/Weapons/Tenno/Rifle/BratonPrimeWeapon": {"name": "Braton Prime"},
        "/Lotus/Types/Items/MiscItems/OrokinCell": {"name": "Celula Orokin"},
    },
}


def _casador(con, tmp_path):
    _importar_multi(con, tmp_path, CATALOGOS, I18N_ES, IDIOMAS_EXTRA)
    return Casador(con)


def test_pieza_de_warframe_con_plano_delante_en_frances(con, tmp_path):
    casador = _casador(con, tmp_path)
    iid, etiqueta, puntos = casador.casar("Plan de Chassis de Caliban Prime")
    assert "Chassis" in etiqueta and puntos == 100.0
    # No se confunde con un plano principal de la warframe (aqui no existe, pero
    # el prefijo frances tiene que quitarse igual que "plano"/"blueprint").
    assert iid is not None


def test_pieza_de_warframe_con_plano_delante_en_aleman(con, tmp_path):
    casador = _casador(con, tmp_path)
    iid, etiqueta, puntos = casador.casar("Bauplan Chassis von Caliban Prime")
    assert "Chassis" in etiqueta and puntos == 100.0
    assert iid is not None


def test_pieza_de_warframe_con_plano_delante_en_portugues(con, tmp_path):
    casador = _casador(con, tmp_path)
    iid, etiqueta, puntos = casador.casar("Projeto do Chassi de Caliban Prime")
    assert "Caliban Prime" in etiqueta and puntos == 100.0
    assert iid is not None


def test_pieza_de_arma_en_los_tres_idiomas(con, tmp_path):
    casador = _casador(con, tmp_path)
    for texto in ("Canon de Braton Prime", "Lauf von Braton Prime", "Cano do Braton Prime"):
        iid, etiqueta, puntos = casador.casar(texto)
        assert iid is not None, texto
        assert "Braton Prime" in etiqueta, texto
        assert puntos == 100.0, texto


def test_recurso_en_los_tres_idiomas(con, tmp_path):
    casador = _casador(con, tmp_path)
    orokin_id = con.execute(
        "SELECT id FROM items WHERE unique_name = '/Lotus/Types/Items/MiscItems/OrokinCell'"
    ).fetchone()[0]
    for texto in ("Cellule Orokin", "Orokin Zelle", "Celula Orokin"):
        iid, etiqueta, puntos = casador.casar(texto)
        assert iid == orokin_id, texto
        assert puntos == 100.0, texto


def test_casado_no_se_rompe_en_espanol_ni_ingles(con, tmp_path):
    """El casado en es/en, que ya tenia pruebas propias, no cambia con los idiomas nuevos."""
    casador = _casador(con, tmp_path)
    iid, etiqueta, puntos = casador.casar("Plano De Chasis De Caliban Prime")
    assert "Caliban Prime" in etiqueta and puntos == 100.0
    iid, etiqueta, puntos = casador.casar("Caliban Prime Chassis Blueprint")
    assert "Caliban Prime" in etiqueta and puntos == 100.0


def test_busqueda_encuentra_un_nombre_en_frances(con, tmp_path):
    _importar_multi(con, tmp_path, CATALOGOS, I18N_ES, IDIOMAS_EXTRA)
    resultados = indice.buscar(con, "cellule orokin")
    assert resultados and resultados[0]["nivel"] == 0
    orokin_id = con.execute(
        "SELECT id FROM items WHERE unique_name = '/Lotus/Types/Items/MiscItems/OrokinCell'"
    ).fetchone()[0]
    assert resultados[0]["item_id"] == orokin_id
