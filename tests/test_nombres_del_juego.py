"""Los nombres del indice son los que pinta el juego en cada idioma.

Medido el 2026-10-02 contra lo que publica Digital Extremes (el "Public Export"): los
mods, arcanos, armas y warframes ya coincidian, pero las piezas no. En frances, aleman
y portugues salian de un glosario propio que no dice lo que el juego ("Neuroptique"
por "Neuroptiques", "Poignee" por "Manche"), en italiano y polaco no habia nombre, y
unas pocas colgaban del objeto equivocado (las Neuropticas de Volt, de Chroma). De
cada 100 piezas leidas en italiano o polaco, casi ninguna casaba exacta.

Aqui se comprueba la lectura de lo que publica DE (con la red simulada), que un idioma
sin manifiesto o un manifiesto roto no tumban nada, y que el indice queda con los
nombres del juego: lo leido en pantalla casa exacto.
"""

from __future__ import annotations

import json
import lzma

import httpx
import pytest

from farmadex.captura.ocr import Casador
from farmadex.datos import descargas, indice, nombres_oficiales
from farmadex.datos.items import ImportadorItems, _nombre, _se_lee_igual, _sin_padre, _suelto

# -- lo que publica DE ----------------------------------------------------


def _indice_de(idioma: str, manifiestos: dict[str, str], como_de: bool = True) -> bytes:
    """Un index_<idioma>.txt.lzma como los de DE: LZMA "a solas", con el tamano exacto
    en la cabecera Y marca de final (lo que Python no se traga sin el arreglo)."""
    texto = "\r\n".join(f"{m}_{idioma}.json!{v}" for m, v in manifiestos.items()) + "\r\nExportManifest.json!00_x"
    crudo = texto.encode()
    comprimido = lzma.compress(crudo, format=lzma.FORMAT_ALONE)
    if como_de:
        comprimido = comprimido[:5] + len(crudo).to_bytes(8, "little") + comprimido[13:]
    return comprimido


def _manifiesto(nombres: dict[str, str], seccion: str = "ExportResources") -> bytes:
    return json.dumps(
        {seccion: [{"uniqueName": u, "name": n, "description": "x"} for u, n in nombres.items()]},
        ensure_ascii=False,
    ).encode()


ASH = "/Lotus/Powersuits/Ninja/NinjaPrime"
NEURO = "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeHelmetComponent"
OFICIAL = {
    "es": {NEURO: "Neurópticas de Ash Prime"},
    "en": {NEURO: "Ash Prime Neuroptics"},
    "fr": {NEURO: "Ash Prime - Neuroptiques"},
}
RELLENO = {f"/Lotus/Relleno/{i}": f"Relleno {i}" for i in range(10)}


class Servidor:
    """content.warframe.com de mentira: indices y manifiestos por idioma."""

    def __init__(self, idiomas=("es", "en", "fr"), manifiestos=("ExportResources",)):
        self.version = {i: "00_v1" for i in idiomas}
        self.nombres = {i: {**RELLENO, **OFICIAL.get(i, {})} for i in idiomas}
        self.manifiestos = manifiestos
        self.rotos: set[str] = set()
        self.sin_manifiesto: set[str] = set()
        self.caido = False
        self.pedidas: list[str] = []

    def descargar(self, url: str, destino) -> None:
        self.pedidas.append(url)
        if self.caido:
            raise RuntimeError("sin conexion")
        nombre = url.rsplit("/", 1)[-1]
        if nombre.startswith("index_"):
            idioma = nombre.removeprefix("index_").split(".")[0]
            if idioma not in self.version:
                raise RuntimeError("404")
            lista = {} if idioma in self.sin_manifiesto else {m: self.version[idioma] for m in self.manifiestos}
            lista["ExportUpgrades"] = "00_otro"
            destino.write_bytes(_indice_de(idioma, lista))
            return
        idioma = nombre.split("!")[0].removesuffix(".json").rsplit("_", 1)[-1]
        destino.write_bytes(b'{"ExportResources": [{"uniqueName": ' if idioma in self.rotos
                            else _manifiesto(self.nombres[idioma]))


def _sincronizar(servidor, carpeta, **kw):
    return nombres_oficiales.sincronizar(
        servidor.descargar, carpeta, idiomas=("es", "en", "fr"), manifiestos=servidor.manifiestos, **kw
    )


def test_el_indice_de_de_se_descomprime_aunque_declare_el_tamano():
    lista = {"ExportResources": "00_b04Iyow6pv2ymnF85st3LQ", "ExportWeapons": "00_i8N0d5AFGElFrKQgnHtrjg"}
    for como_de in (True, False):
        leido = nombres_oficiales.leer_indice(
            nombres_oficiales.descomprimir_indice(_indice_de("es", lista, como_de))
        )
        assert leido["ExportResources"] == "ExportResources_es.json!00_b04Iyow6pv2ymnF85st3LQ"
        assert leido["ExportWeapons"].endswith("!00_i8N0d5AFGElFrKQgnHtrjg")
        assert leido["ExportManifest"] == "ExportManifest.json!00_x"  # el unico sin idioma
    with pytest.raises(nombres_oficiales.ManifiestoRoto):
        nombres_oficiales.descomprimir_indice(b"<html>no es lzma, es una pagina de error</html>")
    with pytest.raises(nombres_oficiales.ManifiestoRoto):
        nombres_oficiales.descomprimir_indice(b"")


def test_el_manifiesto_se_lee_con_los_nombres_como_en_pantalla():
    crudo = (
        '{"ExportWarframes": [{"uniqueName": "/a/Amesha", "name": "<ARCHWING> Amesha"},'
        ' {"uniqueName": "/a/SinTraducir", "name": "/Lotus/Language/Items/Algo"},'
        ' {"uniqueName": "/a/Vacio", "name": ""}],'
        ' "ExportAbilities": [{"abilityUniqueName": "/h/1", "abilityName": "No es un objeto"}],'
        # Un salto de linea de verdad dentro del texto, como los trae DE en algunos.
        ' "ExportResources": [{"uniqueName": "/r/Tema", "name": "Tema de Gauss Prime\r\n\\"Redline\\""},'
        ' {"uniqueName": "/r/Carpeta", "name": "File-a-Style<RETRO_TM> Binder"},'
        ' {"uniqueName": "/r/Ordner", "name": "File-a-Style<RETRO_TM>: Ordner"},'
        ' {"uniqueName": "/r/Dentro", "name": "Fuera", "partes": [{"uniqueName": "/r/Hija", "name": "Dentro"}]},'
        ' {"uniqueName": "/r/Otro", "name": "Otro  mas"}]}'
    )
    assert nombres_oficiales.leer_manifiesto(crudo.encode()) == {
        "/a/Amesha": "Amesha",
        "/r/Tema": 'Tema de Gauss Prime "Redline"',
        "/r/Carpeta": "File-a-Style Binder",
        "/r/Ordner": "File-a-Style: Ordner",
        "/r/Dentro": "Fuera",
        "/r/Hija": "Dentro",
        "/r/Otro": "Otro mas",
    }


@pytest.mark.parametrize("roto", [
    b"", b"<html>503</html>", b'{"ExportResources": [{"uniqueName": "/a", "na', b"[1, 2, 3]",
    b'{"ExportResources": []}', b'{"ExportResources": [{"uniqueName": "/a", "name": "Solo uno"}]}',
])
def test_un_manifiesto_roto_se_rechaza(roto):
    with pytest.raises(nombres_oficiales.ManifiestoRoto):
        nombres_oficiales.leer_manifiesto(roto)


def test_se_baja_una_vez_y_luego_solo_se_mira_la_version(tmp_path):
    servidor = Servidor()
    assert _sincronizar(servidor, tmp_path) == {"es": "nuevo", "en": "nuevo", "fr": "nuevo"}
    assert len(servidor.pedidas) == 6  # un indice y un manifiesto por idioma
    assert nombres_oficiales.cargar(tmp_path, ("es", "en", "fr"))["fr"][NEURO] == "Ash Prime - Neuroptiques"
    assert not list(tmp_path.glob("*.descarga")) and not list(tmp_path.glob("*.tmp"))  # sin restos

    servidor.pedidas.clear()
    assert _sincronizar(servidor, tmp_path) == {"es": "al_dia", "en": "al_dia", "fr": "al_dia"}
    assert len(servidor.pedidas) == 3 and all("index_" in u for u in servidor.pedidas)

    # Sale un parche: DE publica otra version de un idioma y solo ese se vuelve a bajar.
    servidor.version["fr"] = "00_v2"
    servidor.nombres["fr"][NEURO] = "Ash Prime - Neuroptiques (nouveau)"
    assert _sincronizar(servidor, tmp_path) == {"es": "al_dia", "en": "al_dia", "fr": "nuevo"}
    assert nombres_oficiales.cargar(tmp_path, ("fr",))["fr"][NEURO].endswith("(nouveau)")


def test_un_idioma_sin_manifiesto_no_estorba_a_los_demas(tmp_path):
    servidor = Servidor(idiomas=("es", "en"))  # de frances DE no publica ni el indice
    assert _sincronizar(servidor, tmp_path) == {"es": "nuevo", "en": "nuevo", "fr": "sin_datos"}
    assert set(nombres_oficiales.cargar(tmp_path, ("es", "en", "fr"))) == {"es", "en"}

    # Y si el indice esta pero no trae el manifiesto que hace falta, lo mismo.
    otro = Servidor()
    otro.sin_manifiesto.add("en")
    assert _sincronizar(otro, tmp_path / "otro") == {"es": "nuevo", "en": "sin_datos", "fr": "nuevo"}


def test_un_manifiesto_corrupto_deja_lo_que_habia(tmp_path):
    servidor = Servidor()
    _sincronizar(servidor, tmp_path)
    servidor.version = dict.fromkeys(servidor.version, "00_v2")
    servidor.rotos.add("es")
    assert _sincronizar(servidor, tmp_path) == {"es": "anterior", "en": "nuevo", "fr": "nuevo"}
    assert nombres_oficiales.cargar(tmp_path, ("es",))["es"][NEURO] == "Neurópticas de Ash Prime"
    # Sin nada guardado de antes, ese idioma se queda sin nombres oficiales y ya esta.
    assert _sincronizar(servidor, tmp_path / "limpio")["es"] == "sin_datos"
    assert "es" not in nombres_oficiales.cargar(tmp_path / "limpio", ("es", "en", "fr"))


def test_sin_red_no_se_insiste_y_se_sigue_con_lo_guardado(tmp_path):
    servidor = Servidor()
    _sincronizar(servidor, tmp_path)
    servidor.caido = True
    servidor.pedidas.clear()
    hay_red = [True]

    def seguir():
        return hay_red[0]

    def descargar(url, destino):
        try:
            servidor.descargar(url, destino)
        finally:
            hay_red[0] = len(servidor.pedidas) < 2  # como el Descargador: dos fallos = sin red

    resultado = nombres_oficiales.sincronizar(descargar, tmp_path, idiomas=("es", "en", "fr"),
                                              manifiestos=servidor.manifiestos, seguir=seguir)
    assert resultado == {"es": "anterior", "en": "anterior", "fr": "anterior"}
    assert len(servidor.pedidas) == 2  # el indice del primer idioma en los dos servidores, y nada mas
    assert nombres_oficiales.cargar(tmp_path, ("es",))["es"][NEURO] == "Neurópticas de Ash Prime"


def test_si_el_servidor_de_siempre_falla_se_prueba_el_de_origen(tmp_path):
    servidor = Servidor()
    fallos = []

    def descargar(url, destino):
        if url.startswith(nombres_oficiales.URL_BASE + "index_"):
            fallos.append(url)
            raise RuntimeError("503")
        servidor.descargar(url, destino)

    resultado = nombres_oficiales.sincronizar(descargar, tmp_path, idiomas=("es",), manifiestos=("ExportResources",))
    assert resultado == {"es": "nuevo"} and len(fallos) == 1


def test_un_fichero_guardado_que_no_se_deja_leer_no_cuenta(tmp_path):
    nombres_oficiales.ruta_idioma(tmp_path, "es").write_text("{esto no es json", encoding="utf-8")
    nombres_oficiales.ruta_idioma(tmp_path, "en").write_text('{"version": 99, "nombres": {"/a": "b"}}', encoding="utf-8")
    nombres_oficiales.ruta_idioma(tmp_path, "fr").write_text('["una lista"]', encoding="utf-8")
    assert nombres_oficiales.cargar(tmp_path, ("es", "en", "fr", "de")) == {}


# -- el Descargador, con la red simulada -----------------------------------


@pytest.fixture()
def descargador(tmp_path, monkeypatch):
    monkeypatch.setattr(descargas, "RUTA_ESTADO_DATOS", tmp_path / "estado_datos.json")
    monkeypatch.setattr(descargas, "DIR_DATOS", tmp_path)
    monkeypatch.setattr(descargas, "crear_carpetas", lambda: None)
    esperas = []
    monkeypatch.setattr(descargas.time, "sleep", esperas.append)

    def crear(responder):
        pedidas = []

        def servir(peticion):
            pedidas.append(str(peticion.url))
            return responder(peticion)

        d = descargas.Descargador(cliente=httpx.Client(transport=httpx.MockTransport(servir)))
        d.pedidas, d.esperas = pedidas, esperas
        return d

    return crear


def _de_mentira(estado: dict):
    """Responde como content.warframe.com segun `estado` ({"version", "roto", "sin"})."""
    def responder(peticion):
        nombre = str(peticion.url).rsplit("/", 1)[-1]
        if "warframe.com/PublicExport/" not in str(peticion.url):
            return httpx.Response(404)
        if nombre.startswith("index_"):
            idioma = nombre.removeprefix("index_").split(".")[0]
            if idioma in estado.get("sin", ()):
                return httpx.Response(404)
            lista = {m: estado["version"] for m in nombres_oficiales.MANIFIESTOS}
            return httpx.Response(200, content=_indice_de(idioma, lista))
        idioma = nombre.split("%21")[0].split("!")[0].removesuffix(".json").rsplit("_", 1)[-1]
        if idioma in estado.get("roto", ()):
            return httpx.Response(200, content=b'{"ExportResources": [{"uniqueName"')
        return httpx.Response(200, content=_manifiesto({**RELLENO, **OFICIAL.get(idioma, {})}))

    return responder


def test_el_descargador_baja_los_nombres_y_avisa_de_que_hay_que_rehacer_el_indice(descargador, tmp_path):
    estado = {"version": "00_v1"}
    d = descargador(_de_mentira(estado))
    assert d._sincronizar_nombres_oficiales() is True
    carpeta = d.carpeta_nombres_oficiales()
    assert carpeta == tmp_path / "oficial"
    guardados = nombres_oficiales.cargar(carpeta)
    assert set(guardados) == set(nombres_oficiales.IDIOMAS)
    assert guardados["fr"][NEURO] == "Ash Prime - Neuroptiques"
    # La segunda vez no hay nada nuevo: no se baja ningun manifiesto ni se rehace nada.
    d.pedidas.clear()
    assert d._sincronizar_nombres_oficiales() is False
    assert len(d.pedidas) == len(nombres_oficiales.IDIOMAS) and all("index_" in u for u in d.pedidas)
    assert d.esperas == []
    # Con un parche nuevo si.
    estado["version"] = "00_v2"
    assert d._sincronizar_nombres_oficiales() is True


def test_el_descargador_aguanta_un_idioma_sin_manifiesto_y_otro_corrupto(descargador):
    d = descargador(_de_mentira({"version": "00_v1", "sin": {"pl"}, "roto": {"it"}}))
    assert d._sincronizar_nombres_oficiales() is True  # los demas si han entrado
    guardados = nombres_oficiales.cargar(d.carpeta_nombres_oficiales())
    assert set(guardados) == set(nombres_oficiales.IDIOMAS) - {"pl", "it"}
    assert d.esperas == []  # un 404 no se reintenta


def test_el_descargador_sin_red_ni_pregunta_ni_espera(descargador):
    def sin_red(peticion):
        raise httpx.ConnectError("sin red", request=peticion)

    d = descargador(sin_red)
    assert d._sincronizar_nombres_oficiales() is False
    assert d.esperas == []
    assert len(d.pedidas) <= 2  # los dos servidores de DE una vez, y se da por hecho que no hay red
    assert d.sin_red()
    d.pedidas.clear()
    assert d._sincronizar_nombres_oficiales() is False and d.pedidas == []


def test_un_fallo_inesperado_en_los_nombres_no_tumba_la_actualizacion(descargador, monkeypatch):
    def reventar(*a, **k):
        raise ZeroDivisionError("algo que nadie esperaba")

    monkeypatch.setattr(nombres_oficiales, "sincronizar", reventar)
    d = descargador(lambda peticion: httpx.Response(200))
    assert d._sincronizar_nombres_oficiales() is False


# -- el indice con los nombres del juego ----------------------------------

VOLT, CHROMA = "/Lotus/Powersuits/Volt/Volt", "/Lotus/Powersuits/Dragon/Dragon"
VOLT_NEURO = "/Lotus/Types/Recipes/WarframeRecipes/VOLTHelmetComponent"
CHROMA_NEURO = "/Lotus/Types/Recipes/WarframeRecipes/ChromaHelmetComponent"
ASH_NEURO = NEURO
ASH_CHASIS = "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeChassisComponent"
ROTA, WAR = "/Lotus/Weapons/Tenno/Melee/Swords/StalkerTwo/StalkerTwoSmallSword", "/Lotus/Weapons/Tenno/Melee/War"
HOJA_WAR = "/Lotus/Types/Recipes/Weapons/WeaponParts/WarBlade"
MAZO = "/Lotus/Weapons/Tenno/Melee/ThrowingHammer"
MOTOR = "/Lotus/Types/Recipes/Weapons/WeaponParts/ThrowingHammerMotor"

PIEZAS = [
    {"uniqueName": ASH_NEURO, "name": "Neuroptics", "parentUniqueNames": [ASH]},
    {"uniqueName": ASH_CHASIS, "name": "Chassis", "parentUniqueNames": [ASH]},
    {"uniqueName": VOLT_NEURO, "name": "Neuroptics", "parentUniqueNames": [CHROMA, VOLT]},
    {"uniqueName": CHROMA_NEURO, "name": "Neuroptics", "parentUniqueNames": [CHROMA]},
    {"uniqueName": HOJA_WAR, "name": "War Blade", "parentUniqueNames": [ROTA]},
    {"uniqueName": MOTOR, "name": "Motor", "parentUniqueNames": [MAZO]},
]
CATALOGOS = {
    "Warframes": [
        {"uniqueName": ASH, "name": "Ash Prime", "category": "Warframes",
         "components": [{"uniqueName": ASH_NEURO, "itemCount": 1}, {"uniqueName": ASH_CHASIS, "itemCount": 1}]},
        # Chroma va antes que Volt, y su receta pide las neuropticas de Volt.
        {"uniqueName": CHROMA, "name": "Chroma", "category": "Warframes",
         "components": [{"uniqueName": VOLT_NEURO, "itemCount": 1}, {"uniqueName": CHROMA_NEURO, "itemCount": 1}]},
        {"uniqueName": VOLT, "name": "Volt", "category": "Warframes",
         "components": [{"uniqueName": VOLT_NEURO, "itemCount": 1}]},
    ],
    "Melee": [
        {"uniqueName": ROTA, "name": "Broken War", "category": "Melee",
         "components": [{"uniqueName": HOJA_WAR, "itemCount": 1}]},
        # War se fabrica con una Broken War: un objeto con ficha propia que ademas es ingrediente.
        {"uniqueName": WAR, "name": "War", "category": "Melee",
         "components": [{"uniqueName": ROTA, "itemCount": 1}]},
        {"uniqueName": MAZO, "name": "Wolf Sledge", "category": "Melee",
         "components": [{"uniqueName": MOTOR, "itemCount": 1}]},
    ],
}
# Como lo trae WFCD: en castellano el nombre entero; en los demas, las piezas ya sin el
# objeto ("- Neuroptiques" en frances e italiano, "Neuroptyka" en polaco y aleman).
I18N_ES = {
    ASH: {"name": "Ash Prime"}, VOLT: {"name": "Volt"}, CHROMA: {"name": "Chroma"},
    ROTA: {"name": "War Rota"}, WAR: {"name": "War"}, MAZO: {"name": "Mazo del Lobo"},
    ASH_NEURO: {"name": "Neurópticas de Ash Prime"}, ASH_CHASIS: {"name": "Chasis de Ash Prime"},
    VOLT_NEURO: {"name": "Neurópticas de Volt"}, CHROMA_NEURO: {"name": "Neurópticas de Chroma"},
    HOJA_WAR: {"name": "Hoja de War"}, MOTOR: {"name": "Motor del Mazo del Lobo"},
}
WFCD_EXTRA = {
    "fr": {ASH: {"name": "Ash Prime"}, VOLT: {"name": "Volt"}, CHROMA: {"name": "Chroma"},
           ROTA: {"name": "War Brisée"}, WAR: {"name": "War"}, MAZO: {"name": "Marteau du Loup"},
           ASH_NEURO: {"name": "- Neuroptiques"}, ASH_CHASIS: {"name": "- Châssis"},
           VOLT_NEURO: {"name": "- Neuroptiques"}, CHROMA_NEURO: {"name": "- Neuroptiques"},
           HOJA_WAR: {"name": "War - Lame"}, MOTOR: {"name": "- Moteur"}},
    "pl": {ASH: {"name": "Ash Prime"}, VOLT: {"name": "Volt"}, CHROMA: {"name": "Chroma"},
           ROTA: {"name": "War Strzaskany"}, WAR: {"name": "War"}, MAZO: {"name": "Wilczy Kafar"},
           ASH_NEURO: {"name": "Neuroptyka"}, ASH_CHASIS: {"name": "Powłoka"},
           VOLT_NEURO: {"name": "Neuroptyka"}, CHROMA_NEURO: {"name": "Neuroptyka"},
           HOJA_WAR: {"name": "War: Ostrze"}, MOTOR: {"name": "Silnik"}},
}
# Como lo publica DE: siempre el nombre entero.
DE_OFICIAL = {
    "en": {ASH_NEURO: "Ash Prime Neuroptics", ASH_CHASIS: "Ash Prime Chassis", VOLT_NEURO: "Volt Neuroptics",
           CHROMA_NEURO: "Chroma Neuroptics", HOJA_WAR: "War Blade", MOTOR: "Wolf Sledge Motor",
           ROTA: "Broken War", MAZO: "Wolf Sledge"},
    "es": {u: v["name"] for u, v in I18N_ES.items()},
    "fr": {ASH_NEURO: "Ash Prime - Neuroptiques", ASH_CHASIS: "Ash Prime - Châssis",
           VOLT_NEURO: "Volt - Neuroptiques", CHROMA_NEURO: "Chroma - Neuroptiques",
           HOJA_WAR: "War - Lame", MOTOR: "Marteau du Loup - Moteur", ROTA: "War Brisée",
           MAZO: "Marteau du Loup"},
    "pl": {ASH_NEURO: "Ash Prime: Neuroptyka", ASH_CHASIS: "Ash Prime: Powłoka", VOLT_NEURO: "Volt: Neuroptyka",
           CHROMA_NEURO: "Chroma: Neuroptyka", HOJA_WAR: "War: Ostrze", MOTOR: "Wilczy Kafar: Silnik",
           ROTA: "War Strzaskany", MAZO: "Wilczy Kafar"},
}


def _importar(con, tmp_path, i18n=None, extra=None, oficiales=None, catalogos=None, piezas=PIEZAS):
    indice.importar_glosario_idiomas(con)
    importador = ImportadorItems(con, I18N_ES if i18n is None else i18n, extra, oficiales)
    rutas = []
    for nombre, objetos in (catalogos or CATALOGOS).items():
        ruta = tmp_path / f"{nombre}.json"
        ruta.write_text(json.dumps(objetos), encoding="utf-8")
        rutas.append(ruta)
    if piezas is not None:
        importador.cargar_referencias(piezas, rutas)
    for ruta in rutas:
        importador.importar_categoria(ruta)
    importador.promocionar_ingredientes()
    importador.registrar_piezas_con_nombre_propio()
    indice.poblar_busqueda(con)
    con.commit()
    return importador


def _id(con, unico):
    return con.execute("SELECT id FROM items WHERE unique_name = ?", (unico,)).fetchone()[0]


def _en(con, unico, idioma):
    fila = con.execute(
        "SELECT n.nombre FROM items_nombres n JOIN items i ON i.id = n.item_id"
        " WHERE i.unique_name = ? AND n.idioma = ?", (unico, idioma)).fetchone()
    return fila[0] if fila else None


# Lo que pinta el juego en cada idioma, y la pieza que es.
EN_PANTALLA = [
    ("Neurópticas de Ash Prime", ASH_NEURO), ("Chasis de Ash Prime", ASH_CHASIS),
    ("Ash Prime Neuroptics", ASH_NEURO), ("Ash Prime - Neuroptiques", ASH_NEURO),
    ("Ash Prime - Châssis", ASH_CHASIS), ("Ash Prime: Neuroptyka", ASH_NEURO), ("Ash Prime: Powłoka", ASH_CHASIS),
    ("Neurópticas de Volt", VOLT_NEURO), ("Volt Neuroptics", VOLT_NEURO), ("Volt - Neuroptiques", VOLT_NEURO),
    ("Volt: Neuroptyka", VOLT_NEURO), ("Neurópticas de Chroma", CHROMA_NEURO),
    ("Chroma - Neuroptiques", CHROMA_NEURO), ("Chroma: Neuroptyka", CHROMA_NEURO),
    ("Hoja de War", HOJA_WAR), ("War Blade", HOJA_WAR), ("War - Lame", HOJA_WAR), ("War: Ostrze", HOJA_WAR),
    ("Motor del Mazo del Lobo", MOTOR), ("Marteau du Loup - Moteur", MOTOR), ("Wilczy Kafar: Silnik", MOTOR),
    ("Wolf Sledge Motor", MOTOR), ("War Brisée", ROTA), ("War Strzaskany", ROTA), ("War Rota", ROTA),
]


@pytest.mark.parametrize("fuente", ["solo_wfcd", "solo_de", "los_dos"])
def test_lo_que_pinta_el_juego_casa_exacto_en_todos_los_idiomas(con, tmp_path, fuente):
    """Con los nombres de DE, con solo los de WFCD (DE sin poder bajarse) y con los dos."""
    extra = WFCD_EXTRA if fuente != "solo_de" else {
        idioma: {u: v for u, v in datos.items() if u in (ASH, VOLT, CHROMA, WAR, ROTA, MAZO)}
        for idioma, datos in WFCD_EXTRA.items()}
    _importar(con, tmp_path, extra=extra, oficiales=DE_OFICIAL if fuente != "solo_wfcd" else None)
    casador = Casador(con)
    for texto, unico in EN_PANTALLA:
        iid, etiqueta, puntos = casador.casar(texto)
        assert (iid, puntos) == (_id(con, unico), 100.0), (fuente, texto, etiqueta, puntos)
    # La pieza guarda solo su parte, en el idioma del juego, y no la del glosario.
    assert _en(con, ASH_NEURO, "fr") == "Neuroptiques" and _en(con, ASH_CHASIS, "fr") == "Châssis"
    assert _en(con, ASH_NEURO, "pl") == "Neuroptyka" and _en(con, ASH_CHASIS, "pl") == "Powłoka"
    assert con.execute("SELECT nombre_es FROM items WHERE unique_name = ?", (ASH_NEURO,)).fetchone()[0] == "Neurópticas"


def test_lo_que_el_indice_decia_antes_se_sigue_reconociendo_y_encontrando(con, tmp_path):
    _importar(con, tmp_path, extra=WFCD_EXTRA, oficiales=DE_OFICIAL)
    # El glosario propio decia "Neuroptique" (en singular): ya no es el nombre, pero vale.
    assert con.execute(
        "SELECT a.nombre, a.origen FROM items_alias a WHERE a.item_id = ? AND a.idioma = 'fr'",
        (_id(con, ASH_NEURO),)).fetchall() == [("Ash Prime Neuroptique", "anterior")]
    assert Casador(con).casar("Ash Prime Neuroptique")[::2] == (_id(con, ASH_NEURO), 100.0)
    assert indice.buscar(con, "ash prime neuroptique")[0]["item_id"] == _id(con, ASH_NEURO)
    assert indice.buscar(con, "ash prime neuroptiques")[0]["item_id"] == _id(con, ASH_NEURO)
    assert indice.buscar(con, "hoja de war")[0]["item_id"] == _id(con, HOJA_WAR)


def test_una_pieza_compartida_cuelga_del_objeto_del_que_lleva_el_nombre(con, tmp_path):
    """Las Neuropticas de Volt entran tambien en la receta de Chroma, que va antes: se
    quedaban como pieza de Chroma y la ficha de Volt salia sin neuropticas."""
    importador = _importar(con, tmp_path, extra=WFCD_EXTRA)
    padre = con.execute(
        "SELECT p.unique_name FROM items i JOIN items p ON p.id = i.padre_id WHERE i.unique_name = ?",
        (VOLT_NEURO,)).fetchone()[0]
    assert padre == VOLT
    # En la receta de Chroma sigue estando, y las tablas de drops dan con cada una.
    assert con.execute("SELECT count(*) FROM recetas WHERE item_id = ?", (_id(con, VOLT_NEURO),)).fetchone()[0] == 2
    assert importador.alias["volt neuroptics"] == _id(con, VOLT_NEURO)
    assert importador.alias["chroma neuroptics"] == _id(con, CHROMA_NEURO)


def test_un_objeto_que_ademas_es_ingrediente_conserva_su_nombre_entero(con, tmp_path):
    """Broken War es ingrediente de War: sus nombres en frances y polaco se pisaban con
    los de pieza y "War Brisée" se quedaba en "Brisée"."""
    _importar(con, tmp_path, extra=WFCD_EXTRA)
    assert _en(con, ROTA, "fr") == "War Brisée" and _en(con, ROTA, "pl") == "War Strzaskany"
    assert con.execute("SELECT padre_id FROM items WHERE unique_name = ?", (ROTA,)).fetchone()[0] is None


def test_sin_nombre_oficial_se_queda_el_que_habia_y_queda_apuntado(con, tmp_path):
    """Nada de inventar: sin nombre de DE vale el de WFCD; sin ninguno, el del glosario
    (y en un idioma sin glosario, nada). `origen_nombres` dice cuantos hay de cada."""
    # DE solo ha podido bajarse en frances, y de aleman WFCD no trae las piezas.
    aleman = {u: v for u, v in WFCD_EXTRA["pl"].items() if u in (ASH, VOLT, CHROMA, WAR, ROTA, MAZO)}
    importador = _importar(con, tmp_path, extra={"pl": WFCD_EXTRA["pl"], "de": aleman, "it": {}},
                           oficiales={"fr": DE_OFICIAL["fr"]})
    assert _en(con, ASH_NEURO, "fr") == "Neuroptiques"  # de DE
    assert _en(con, ASH_NEURO, "pl") == "Neuroptyka"  # de WFCD
    assert _en(con, ASH_NEURO, "de") == "Neuroptik"  # del glosario: es lo que habia
    assert _en(con, ASH_NEURO, "it") is None  # ni glosario: no se inventa
    origen = importador.origen_nombres
    assert origen["fr"]["oficial"] >= 6 and origen["pl"]["wfcd"] >= 6
    assert origen["de"]["glosario"] >= 2 and origen["it"]["sin"] >= 6


def test_una_palabra_suelta_no_se_convierte_en_el_nombre_de_un_objeto(con, tmp_path):
    """Formato antiguo de WFCD: la pieza viene dentro del objeto y su traduccion es solo
    la palabra ("Chasis"). Como nombre entero haria casar cualquier "Chasis" con ella."""
    catalogos = {"Warframes": [{"uniqueName": ASH, "name": "Ash Prime", "category": "Warframes",
                                "components": [{"uniqueName": ASH_CHASIS, "name": "Chassis"}]}]}
    _importar(con, tmp_path, i18n={ASH: {"name": "Ash Prime"}, ASH_CHASIS: {"name": "Chasis"}},
              oficiales={"es": {ASH_CHASIS: "Chasis"}}, catalogos=catalogos, piezas=None)
    assert con.execute("SELECT count(*) FROM items_alias").fetchone()[0] == 0
    assert Casador(con).casar("Chasis")[0] is None
    assert Casador(con).casar("Chasis de Ash Prime")[::2] == (_id(con, ASH_CHASIS), 100.0)


def test_las_reliquias_llevan_el_nombre_del_juego_en_cada_idioma(con, tmp_path):
    reliquias = [
        {"uniqueName": f"/Lotus/Types/Game/Projections/T1VoidProjectionA{calidad}", "name": f"Lith A1 {refinamiento}",
         "category": "Relics"}
        for calidad, refinamiento in (("Bronze", "Intact"), ("Gold", "Flawless"))
    ] + [
        {"uniqueName": "/Lotus/Types/Game/Projections/T5VoidProjectionIBronze", "name": "Requiem I Intact",
         "category": "Relics"},
        {"uniqueName": "/Lotus/Types/Game/Projections/T6VoidProjectionCBronze", "name": "Vanguard C1 Intact",
         "category": "Relics"},
    ]
    lith, requiem, vanguardia = (r["uniqueName"] for r in (reliquias[0], reliquias[2], reliquias[3]))
    i18n = {lith: {"name": "Reliquia Lith A1"}, requiem: {"name": "Reliquia Réquiem I"},
            vanguardia: {"name": "Reliquia Vanguardia C1"}}
    extra = {"fr": {lith: {"name": "Relique Lith A1"}, requiem: {"name": "Relique Requiem I"}},
             "de": {lith: {"name": "Lith-Relikt: A1"}, requiem: {"name": "Otra cosa sin su codigo"}}}
    _importar(con, tmp_path, i18n=i18n, extra=extra, catalogos={"Relics": reliquias}, piezas=None)
    nombres = dict(con.execute("SELECT unique_name, nombre_es FROM items WHERE categoria = 'Relics'"))
    assert nombres == {"RELIQUIA/Lith A1": "Reliquia Lith A1", "RELIQUIA/Requiem I": "Reliquia Réquiem I",
                       "RELIQUIA/Vanguard C1": "Reliquia Vanguard C1"}
    assert _en(con, "RELIQUIA/Lith A1", "fr") == "Relique Lith A1"
    assert _en(con, "RELIQUIA/Lith A1", "de") == "Lith-Relikt: A1"
    assert _en(con, "RELIQUIA/Requiem I", "de") is None  # no nombra esa reliquia: no se usa
    casador = Casador(con)
    for texto, unico in (("Relique Lith A1", "RELIQUIA/Lith A1"), ("Lith-Relikt: A1", "RELIQUIA/Lith A1"),
                         ("Reliquia Vanguardia C1", "RELIQUIA/Vanguard C1"),
                         ("Reliquia Vanguard C1", "RELIQUIA/Vanguard C1")):
        assert casador.casar(texto)[::2] == (_id(con, unico), 100.0), texto


def test_un_indice_de_antes_sin_la_tabla_de_alias_se_lee_igual(con, tmp_path):
    _importar(con, tmp_path, extra=WFCD_EXTRA)
    con.execute("DROP TABLE items_alias")
    casador = Casador(con)
    assert casador.casar("Ash Prime - Neuroptiques")[::2] == (_id(con, ASH_NEURO), 100.0)
    assert indice.poblar_busqueda(con) > 0
    assert indice.buscar(con, "neuropticas ash prime")[0]["item_id"] == _id(con, ASH_NEURO)


def test_los_alias_respetan_las_categorias_y_el_filtro_del_casador(con, tmp_path):
    _importar(con, tmp_path, extra=WFCD_EXTRA, oficiales=DE_OFICIAL)
    assert Casador(con, ("Warframes",)).casar("Hoja de War")[0] is None
    sin_piezas = Casador(con, ("Melee",), filtro=lambda categoria, tipo, unico: tipo != "Componente")
    assert sin_piezas.casar("Hoja de War")[0] is None
    assert sin_piezas.casar("War Rota")[0] == _id(con, ROTA)


def test_los_nombres_se_limpian_como_se_leen_en_pantalla():
    assert _nombre("<ARCHWING> Amesha") == "Amesha"
    assert _nombre("File-a-Style<RETRO_TM> Notepad") == "File-a-Style Notepad"
    assert _nombre("File-a-Style<RETRO_TM>: Ordner") == "File-a-Style: Ordner"
    assert _nombre("Celular Kinemantik<RETRO_TM>") == "Celular Kinemantik"
    assert _nombre('Tema de Gauss Prime\r\n"Redline"') == 'Tema de Gauss Prime "Redline"'
    assert _nombre("<SOLO_ETIQUETA>") == "<SOLO_ETIQUETA>"  # sin nada mas, se deja como viene
    assert _sin_padre("Ash Prime - Châssis", "Ash Prime") == "Châssis"
    assert _sin_padre("Ash Prime: Powłoka", "Ash Prime") == "Powłoka"
    assert _sin_padre("Equinox (Aspecto Noturno)", "Equinox") == "Aspecto Noturno"
    assert _sin_padre("Pala superior de Daikyu Prime", "Daikyu Prime") == "Pala superior"
    assert _sin_padre("Chassis d'Ash Prime", "Ash Prime") == "Chassis"
    assert _sin_padre("Warframe - Algo", "War") is not None  # sin palabra entera, como antes
    assert _suelto("- Neuroptiques") == "Neuroptiques" and _suelto(" : ") is None
    assert _se_lee_igual("Chasis de Ash Prime", "Ash Prime Chasis")
    assert _se_lee_igual("Ash Prime - Neuroptiques", "Ash Prime Neuroptiques")
    assert not _se_lee_igual("Motor del Mazo del Lobo", "Mazo del Lobo Motor")
    assert not _se_lee_igual("Hoja de War", "Broken War Hoja de War")


def test_la_version_del_indice_obliga_a_rehacerlo_una_vez():
    assert indice.VERSION_ESQUEMA == "16" and "16" in indice.ESQUEMAS_COMPATIBLES
    assert "15" in indice.ESQUEMAS_COMPATIBLES  # el de antes se sigue pudiendo usar mientras tanto
