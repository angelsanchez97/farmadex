import json
import sqlite3

import pytest

from farmadex import perfil as P
from farmadex.estado import usuario_db
from farmadex.perfil import maestria

from conftest import FIXTURES

RUTA_PERFIL = FIXTURES / "perfil_recortado.json"

# Fichas de catalogo minimas para casar con el fixture de perfil.
ITEMS_CATALOGO = [
    # (unique_name, nombre_en, categoria, tipo)
    ("/Lotus/Powersuits/Excalibur/Excalibur", "Excalibur", "Warframes", "Warframe"),
    ("/Lotus/Weapons/Tenno/Rifle/StartingRifle", "Braton", "Primary", "Rifle"),
    ("/Lotus/Weapons/MK1Series/MK1Kunai", "MK1-Kunai", "Secondary", "Throwing"),
    ("/Lotus/Weapons/Grineer/Bows/GrnBow/GrnBowWeapon", "Kuva Bramma", "Primary", "Bow"),
    ("/Lotus/Powersuits/EntratiMech/NechroTech", "Voidrig", "Warframes", "Necramech"),
    ("/Lotus/Weapons/Ostron/Melee/ModularMelee01/Tip/TipOne", "Balla", "Misc", "Zaw Component"),
    ("/Lotus/Weapons/Ostron/Melee/ModularMelee01/Handle/HandleOne", "Peye", "Misc", "Zaw Component"),
    ("/Lotus/Types/Sentinels/SentinelPowersuits/CarrierPowerSuit", "Carrier", "Sentinels", "Sentinel"),
    ("/Lotus/Types/Game/CatbrowPet/CheshireCatbrowPetPowerSuit", "Smeeta Kavat", "Pets", "Pets"),
    ("/Lotus/Weapons/Sentients/OperatorAmplifiers/SentTrainingAmplifier/SentAmpTrainingBarrel",
     "Mote Prism", "Misc", "Amp"),
    ("/Lotus/Types/Vehicles/Hoverboard/HoverboardParts/PartComponents/HoverboardCorpusA/HoverboardCorpusADeck",
     "Flatbelly", "Misc", "K-Drive Component"),
    ("/Lotus/Weapons/Tenno/Melee/Swords/DarkSword/DarkSword", "Dark Sword", "Melee", "Melee"),
    ("/Lotus/Types/Recipes/Weapons/BratonBlueprint", "Braton Blueprint", "Primary", "Componente"),
    ("/Lotus/Types/Items/MiscItems/Ferrite", "Ferrite", "Resources", "Resource"),
]


@pytest.fixture()
def usuario(tmp_path):
    con = usuario_db.conectar(tmp_path / "usuario.sqlite")
    yield con
    con.close()


@pytest.fixture()
def catalogo(indice_poblado):
    con, _, _ = indice_poblado  # trae Ash Prime, Axi A7 y los nodos Abaddon e Hydron
    con.executemany(
        "INSERT OR IGNORE INTO items (unique_name, nombre_en, categoria, tipo) VALUES (?, ?, ?, ?)",
        ITEMS_CATALOGO,
    )
    con.commit()
    return con


def _id(catalogo, nombre_en):
    return catalogo.execute("SELECT id FROM items WHERE nombre_en = ?", (nombre_en,)).fetchone()[0]


# --- lectura --------------------------------------------------------------------------


def test_carga_el_fixture_y_limpia_el_glifo_de_plataforma():
    perfil = P.cargar(RUTA_PERFIL)
    assert perfil.nombre == "TennoPrueba"
    assert perfil.rango == 21
    assert perfil.account_id == "0123456789abcdef01234567"
    assert perfil.creado.year == 2013
    assert perfil.clan == "Clan de Prueba" and perfil.clan_nivel == 2
    assert perfil.plataformas == ["TennoPrueba"]
    assert len(perfil.xp) == 26
    assert perfil.xp_por_item["/Lotus/Weapons/MK1Series/MK1Kunai"] == 100000
    assert len(perfil.nodos) == 6
    assert next(n for n in perfil.nodos if n.tag == "ClanNode0").camino_acero
    assert not next(n for n in perfil.nodos if n.tag == "SolNode203").camino_acero
    assert perfil.intrinsecos["LPS_ENGINEERING"] == 4
    assert [s.tag for s in perfil.sindicatos][0] == "SteelMeridianSyndicate"
    assert perfil.sindicatos[1].standing == -44000
    assert perfil.reputacion_diaria["DailyFocus"] == 250000
    assert perfil.desafios["KillEnemiesWithMelee"] == 4321
    assert perfil.estadisticas["MissionsCompleted"] == 1400
    assert "Weapons" in perfil.estadisticas_listas and "MissionsCompleted" not in perfil.estadisticas_listas
    assert perfil.cache_expira.year == 2025


def test_fichero_recortado_da_error_claro(tmp_path):
    texto = RUTA_PERFIL.read_text(encoding="utf-8")
    roto = tmp_path / "roto.json"
    roto.write_text(texto[: len(texto) // 2], encoding="utf-8")
    with pytest.raises(P.PerfilInvalido, match="recortado o corrupto"):
        P.cargar(roto)


def test_json_de_otra_cosa_da_error_claro():
    # El worldstate es un JSON valido pero no un perfil.
    with pytest.raises(P.PerfilInvalido, match="Results"):
        P.cargar(FIXTURES / "worldstate.json")


def test_fichero_inexistente_vacio_o_binario(tmp_path):
    with pytest.raises(P.PerfilInvalido, match="No existe"):
        P.cargar(tmp_path / "nada.json")
    vacio = tmp_path / "vacio.json"
    vacio.write_bytes(b"")
    with pytest.raises(P.PerfilInvalido, match="vacio"):
        P.cargar(vacio)
    binario = tmp_path / "bin.json"
    binario.write_bytes(bytes(range(128, 256)))
    with pytest.raises(P.PerfilInvalido, match="UTF-8"):
        P.cargar(binario)


def test_campos_opcionales_ausentes_no_rompen():
    minimo = {
        "Results": [
            {"DisplayName": "Solo", "PlayerLevel": "7", "LoadOutInventory": {"XPInfo": [
                {"ItemType": "/Lotus/Powersuits/Excalibur/Excalibur", "XP": 12},
                {"ItemType": "", "XP": 5},
                "basura",
            ]}}
        ]
    }
    perfil = P.interpretar(minimo)
    assert perfil.rango == 7 and len(perfil.xp) == 1
    assert perfil.nodos == [] and perfil.sindicatos == [] and perfil.estadisticas == {}
    assert perfil.operador_desbloqueado is None and perfil.creado is None

    with pytest.raises(P.PerfilInvalido, match="PlayerLevel"):
        P.interpretar({"Results": [{"DisplayName": "x", "LoadOutInventory": {"XPInfo": []}}]})
    with pytest.raises(P.PerfilInvalido, match="XPInfo"):
        P.interpretar({"Results": [{"DisplayName": "x", "PlayerLevel": 1}]})


# --- reglas de maestria ------------------------------------------------------------------


def test_umbrales_por_tipo():
    assert maestria.umbral_xp("Warframes", "Warframe", "Excalibur") == 900_000
    assert maestria.umbral_xp("Warframes", "Necramech", "Voidrig") == 1_600_000
    assert maestria.umbral_xp("Primary", "Rifle", "Braton") == 450_000
    assert maestria.umbral_xp("Primary", "Bow", "Kuva Bramma") == 800_000
    assert maestria.umbral_xp("Melee", "Melee", "Paracesis") == 800_000
    assert maestria.umbral_xp("Secondary", "Pistol", "Tenet Cycron") == 800_000
    assert maestria.umbral_xp("Melee", "Melee", "Kuvas No Es Kuva") == 450_000
    assert maestria.umbral_xp("Pets", "Pets", "Smeeta Kavat") == 900_000
    assert maestria.umbral_xp("Sentinels", "Companion Weapon", "Sweeper") == 450_000
    assert maestria.umbral_xp("Primary", "Componente", "Braton Blueprint") is None
    assert maestria.umbral_xp("Mods", None, "Serration") is None
    assert maestria.umbral_xp("Misc", "Exalted Weapon", "Exalted Blade") is None
    # Modulares: solo la pieza que lleva la XP.
    assert maestria.umbral_xp("Misc", "Zaw Component", "Balla", ".../Tip/TipOne") == 450_000
    assert maestria.umbral_xp("Misc", "Zaw Component", "Balla", ".../Tip/PvPVariantTipOne") is None
    assert maestria.umbral_xp("Misc", "Zaw Component", "Peye", ".../Handle/HandleOne") is None
    assert maestria.umbral_xp("Misc", "Kitgun Component", "Gaze", ".../Barrel/X") == 450_000
    assert maestria.umbral_xp("Misc", "Kitgun Component", "Slap", ".../Clip/X") is None
    assert maestria.umbral_xp("Misc", "K-Drive Component", "Flatbelly", ".../HoverboardCorpusADeck") == 900_000
    assert maestria.umbral_xp("Misc", "K-Drive Component", "Wingnut", ".../HoverboardCorpusAFront") is None


def test_rango_actual():
    assert maestria.rango_actual(0, 450_000) == 0
    assert maestria.rango_actual(100_000, 450_000) == 14  # 500 * 14^2 = 98.000
    assert maestria.rango_actual(4_000_000, 900_000) == 30
    assert maestria.rango_actual(1_000_000, 1_600_000) == 31


# --- guardado y consultas ------------------------------------------------------------------


def test_importar_guarda_y_casa_con_el_catalogo(usuario, catalogo):
    resultado = P.importar(RUTA_PERFIL, usuario, catalogo)
    assert resultado.segundos < 2
    assert resultado.casado.total == 26
    assert resultado.casado.casan == 10  # el arnes de Railjack no esta en el catalogo
    assert "/Lotus/Types/Game/CrewShip/RailJack/DefaultHarness" in resultado.casado.sin_catalogo
    assert resultado.casado.nodos_total == 6
    assert resultado.casado.nodos_casan == 1  # solo Abaddon esta en el catalogo de pruebas

    meta = P.resumen(usuario)
    assert meta["nombre"] == "TennoPrueba" and meta["rango"] == 21
    assert meta["objetos_xp"] == 26 and meta["fichero"].endswith("perfil_recortado.json")
    assert meta["intrinsecos"]["LPS_PILOTING"] == 3
    assert meta["sindicatos"][0]["tag"] == "SteelMeridianSyndicate"
    assert P.estadistica(usuario, "MissionsCompleted") == 1400
    assert P.estadistica(usuario, "Weapons")[0]["kills"] == 1001
    assert P.estadistica(usuario, "NoExiste") is None


def test_estado_de_cada_objeto(usuario, catalogo):
    P.importar(RUTA_PERFIL, usuario, catalogo)

    excalibur = P.estado_de(usuario, catalogo, _id(catalogo, "Excalibur"))
    assert excalibur.dominado and excalibur.rango == 30 and excalibur.porcentaje == 100.0

    kunai = P.estado_de(usuario, catalogo, _id(catalogo, "MK1-Kunai"))
    assert kunai.estado == P.A_MEDIAS and kunai.xp == 100000 and kunai.umbral == 450_000
    assert kunai.rango == 14

    bramma = P.estado_de(usuario, catalogo, _id(catalogo, "Kuva Bramma"))
    assert bramma.estado == P.A_MEDIAS and bramma.umbral == 800_000  # 500k no basta para el 40

    voidrig = P.estado_de(usuario, catalogo, _id(catalogo, "Voidrig"))
    assert voidrig.estado == P.A_MEDIAS and voidrig.umbral == 1_600_000

    assert P.estado_de(usuario, catalogo, _id(catalogo, "Dark Sword")).estado == P.SIN_TOCAR
    assert P.estado_de(usuario, catalogo, _id(catalogo, "Ash Prime")).estado == P.SIN_TOCAR
    assert P.estado_de(usuario, catalogo, _id(catalogo, "Braton Blueprint")).estado == P.NO_APLICA
    assert P.estado_de(usuario, catalogo, _id(catalogo, "Ferrite")).estado == P.NO_APLICA
    assert P.estado_de(usuario, catalogo, 999999).estado == P.NO_APLICA

    assert P.estado_por_unique_name(
        usuario, catalogo, "/Lotus/Types/Sentinels/SentinelPowersuits/CarrierPowerSuit"
    ).dominado
    assert P.estado_por_unique_name(usuario, catalogo, "/no/existe").estado == P.NO_APLICA


def test_sin_perfil_todo_esta_sin_tocar(usuario, catalogo):
    assert not P.hay_perfil(usuario)
    assert P.estado_de(usuario, catalogo, _id(catalogo, "Excalibur")).estado == P.SIN_TOCAR
    assert P.resumen(usuario) is None


def test_pendientes_por_categoria_y_resumen(usuario, catalogo):
    P.importar(RUTA_PERFIL, usuario, catalogo)
    pendientes = P.pendientes_por_categoria(usuario, catalogo)

    # Excalibur dominado: Warframes solo debe tener pendientes Voidrig y Ash Prime.
    assert [f["nombre_en"] for f in pendientes["Warframes"]] == ["Voidrig", "Ash Prime"]
    assert pendientes["Warframes"][0]["estado"] == P.A_MEDIAS
    assert pendientes["Warframes"][1]["estado"] == P.SIN_TOCAR
    # Los componentes (planos, piezas) no aparecen nunca.
    assert all(f["tipo"] != "Componente" for filas in pendientes.values() for f in filas)
    assert "Braton Blueprint" not in [f["nombre_en"] for f in pendientes.get("Primary", [])]
    # El zaw se cuenta por la hoja; la empunadura Peye no es masterizable.
    nombres_misc = [f["nombre_en"] for f in pendientes.get("Misc", [])]
    assert "Peye" not in nombres_misc
    # Kuva Bramma a medias y Braton dominado.
    assert [f["nombre_en"] for f in pendientes["Primary"]] == ["Kuva Bramma"]
    assert [f["nombre_en"] for f in pendientes["Melee"]] == ["Dark Sword"]
    assert "Sentinels" not in pendientes and "Pets" not in pendientes

    resumen = P.resumen_maestria(usuario, catalogo)
    assert resumen["Warframes"] == {"total": 3, P.DOMINADO: 1, P.A_MEDIAS: 1, P.SIN_TOCAR: 1}
    assert resumen["Primary"] == {"total": 2, P.DOMINADO: 1, P.A_MEDIAS: 1, P.SIN_TOCAR: 0}
    assert resumen["Misc"]["total"] == 3 and resumen["Misc"][P.DOMINADO] == 3


def test_nodos_pendientes(usuario, catalogo):
    P.importar(RUTA_PERFIL, usuario, catalogo)
    # El catalogo de pruebas tiene Abaddon (SolNode203, hecho) e Hydron (SolNode48, no).
    pendientes = P.nodos_pendientes(usuario, catalogo)
    assert [n["unique_name"] for n in pendientes] == ["SolNode48"]
    assert pendientes[0]["nombre"] == "Hydron" and pendientes[0]["planeta"] == "Sedna"
    # En Camino de Acero faltan los dos.
    acero = P.nodos_pendientes(usuario, catalogo, camino_acero=True)
    assert {n["unique_name"] for n in acero} == {"SolNode203", "SolNode48"}
    assert P.nodo_hecho(usuario, "SolNode203") == (True, False)
    assert P.nodo_hecho(usuario, "ClanNode0") == (True, True)
    assert P.nodo_hecho(usuario, "SolNode48") == (False, False)


def test_reimportar_sustituye_sin_duplicar(usuario, catalogo, tmp_path):
    P.importar(RUTA_PERFIL, usuario, catalogo)
    datos = json.loads(RUTA_PERFIL.read_text(encoding="utf-8"))
    datos["Results"][0]["PlayerLevel"] = 22
    datos["Results"][0]["LoadOutInventory"]["XPInfo"] = datos["Results"][0]["LoadOutInventory"]["XPInfo"][:5]
    datos["Results"][0]["Missions"] = []
    nuevo = tmp_path / "perfil2.json"
    nuevo.write_text(json.dumps(datos), encoding="utf-8")

    P.importar(nuevo, usuario, catalogo)
    assert P.resumen(usuario)["rango"] == 22
    assert usuario.execute("SELECT COUNT(*) FROM perfil_xp").fetchone()[0] == 5
    assert usuario.execute("SELECT COUNT(*) FROM perfil_nodos").fetchone()[0] == 0
    assert usuario.execute("SELECT COUNT(*) FROM perfil_meta WHERE clave = 'nombre'").fetchone()[0] == 1


def test_un_fichero_invalido_no_borra_el_perfil_guardado(usuario, catalogo, tmp_path):
    P.importar(RUTA_PERFIL, usuario, catalogo)
    malo = tmp_path / "malo.json"
    malo.write_text("{", encoding="utf-8")
    with pytest.raises(P.PerfilInvalido):
        P.importar(malo, usuario, catalogo)
    assert P.resumen(usuario)["rango"] == 21


def test_las_tablas_conviven_con_el_esquema_del_usuario(tmp_path):
    ruta = tmp_path / "usuario.sqlite"
    con = usuario_db.conectar(ruta)
    P.preparar(con)
    con.close()
    # Reabrir con el modulo del usuario no rompe ni borra las tablas de perfil.
    con = usuario_db.conectar(ruta)
    tablas = {t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"objetivos", "perfil_xp", "perfil_nodos", "perfil_meta"} <= tablas
    con.close()
