"""Botin deducido de EE.log, pantallas del menu y almacen de cantidades del inventario."""

from __future__ import annotations

import sqlite3

import pytest

from farmadex.estado import inventario as estado_inventario
from farmadex.estado import objetivos as estado_objetivos
from farmadex.estado import usuario_db
from farmadex.registro import eelog
from farmadex.registro.botin import Botin
from farmadex.registro.eelog import VigilanteEELog, pantalla_de, pista

# Calcos de un EE.log real (septiembre de 2026), sin nombres ni ids de jugador.
ARSENAL = "43.746 Input [Info]: Subscribing for /Lotus/Interface/LoadOutRedux.swf with input filter /Lotus/Types/Input/LoadoutReduxInputFilter"
ARSENAL_ABIERTO = "43.700 Script [Info]: LoadOutRedux.lua: Background::ScreenOpened(screenName=LoadOut)"
ESCUADRA = "61.634 Script [Info]: ThemedSquadOverlay.lua: Background::OpenScreen(screenName=InvitePanel, openFromMovie=nil, ignoreIfOpen=nil, openAsAsync=nil)"
ATRAS = "44.926 Script [Info]: LoadOutRedux.lua: Background::GoToPreviousScreen(skipScreens=1)"
PAUSA = "60.169 Sys [Info]: Executing command: /EE/Editor/ToolMenus/Commands/CmdShowPauseMenu"
DIALOGO = "44.000 Input [Info]: Subscribing for /Lotus/Interface/Dialog.swf with input filter /Lotus/Types/Input/DialogInputFilter"
NUEVA = "50.000 Input [Info]: Subscribing for /Lotus/Interface/PantallaInventada.swf with input filter x"
REMOTOS_0 = "30.100 Script [Info]: Progress.lua: Num remote players 0"
REMOTOS_1 = "30.100 Script [Info]: Progress.lua: Num remote players 1"
RECOMPENSA = (
    "404.409 Sys [Info]: VoidProjections: 0123456789abcdef01234567 gets reward "
    "/Lotus/StoreItems/Types/Recipes/Weapons/WeaponParts/BurstonPrimeStock"
)
STOCK = "/Lotus/Types/Recipes/Weapons/WeaponParts/BurstonPrimeStock"


# --- pantallas en EE.log ---------------------------------------------------------


def test_pantalla_de_reconoce_el_arsenal_por_las_dos_lineas():
    assert pantalla_de(ARSENAL) == ("abierta", "arsenal")
    assert pantalla_de(ARSENAL_ABIERTO) == ("abierta", "arsenal")


def test_pantalla_de_cierre_pausa_y_paneles_superpuestos():
    assert pantalla_de(ATRAS) == ("cerrada", "")
    assert pantalla_de(PAUSA) == ("pausa", "")
    assert pantalla_de(DIALOGO) is None  # el dialogo no cambia de pantalla
    assert pantalla_de(ESCUADRA) is None
    assert pantalla_de("1.0 Sys [Info]: nada que ver") is None


def test_pantalla_nueva_se_devuelve_con_interrogacion_y_se_anota_una_vez(caplog):
    eelog._pantallas_desconocidas.clear()
    with caplog.at_level("INFO", logger="farmadex.eelog"):
        assert pantalla_de(NUEVA) == ("abierta", "?PantallaInventada")
        assert pantalla_de(NUEVA) == ("abierta", "?PantallaInventada")
    assert sum("PantallaInventada" in r.message for r in caplog.records) == 1


def test_los_candidatos_de_perfil_inventario_y_fundicion_estan_en_la_tabla():
    for nombre in ("Profile", "Inventory", "Foundry"):
        assert pantalla_de(f"1.0 Script [Info]: X.lua: Background::OpenScreen(screenName={nombre}, x=nil)")[1] in (
            "perfil", "inventario", "fundicion"
        )


def test_el_vigilante_emite_pantallas_y_remotos():
    vigilante = VigilanteEELog("no_existe.log")
    recibido = []
    vigilante.pantalla.connect(lambda a, n: recibido.append((a, n)))
    vigilante.pista.connect(lambda t, v: recibido.append((t, v)))
    vigilante._procesar([REMOTOS_0, ARSENAL_ABIERTO, ATRAS, PAUSA])
    assert recibido == [("remotos", "0"), ("abierta", "arsenal"), ("cerrada", ""), ("pausa", "")]


def test_pista_remotos():
    assert pista(REMOTOS_1) == ("remotos", "1")


# --- botin -------------------------------------------------------------------------


def _botin(activo=True):
    sumas = []
    return Botin(lambda u, n, o: sumas.append((u, n, o)), activo), sumas


def test_en_solitario_con_una_recompensa_se_suma_al_elegir():
    botin, sumas = _botin()
    botin.pista("remotos", "0")
    botin.evento("reliquia_abierta")
    botin.pista(*pista(RECOMPENSA))
    assert sumas == []  # todavia no: hasta que se cierra la eleccion
    assert botin.evento("reliquia_elegida") == STOCK
    assert sumas == [(STOCK, 1, "eelog")]
    assert botin.evento("reliquia_elegida") is None  # no se suma dos veces


@pytest.mark.parametrize("remotos, lineas", [("1", 1), ("0", 2), (None, 1)])
def test_en_escuadra_o_sin_saber_no_se_suma_nada(remotos, lineas):
    botin, sumas = _botin()
    if remotos is not None:
        botin.pista("remotos", remotos)
    botin.evento("reliquia_abierta")
    for _ in range(lineas):
        botin.pista("recompensa", STOCK)
    assert botin.evento("reliquia_elegida") is None
    assert sumas == []


def test_apagado_desde_ajustes_no_suma():
    botin, sumas = _botin(activo=False)
    botin.pista("remotos", "0")
    botin.evento("reliquia_abierta")
    botin.pista("recompensa", STOCK)
    assert botin.evento("reliquia_elegida") is None
    assert sumas == []


def test_una_recompensa_fuera_de_la_pantalla_de_reliquia_se_ignora():
    botin, sumas = _botin()
    botin.pista("remotos", "0")
    botin.pista("recompensa", STOCK)  # sin "reliquia_abierta" delante
    botin.evento("reliquia_abierta")
    assert botin.evento("reliquia_elegida") is None


def test_un_fallo_al_sumar_no_revienta_el_vigilante():
    def reventar(*a):
        raise sqlite3.OperationalError("database is locked")

    botin = Botin(reventar, True)
    botin.pista("remotos", "0")
    botin.evento("reliquia_abierta")
    botin.pista("recompensa", STOCK)
    assert botin.evento("reliquia_elegida") is None


# --- almacen del inventario ----------------------------------------------------------


class _Cantidad:
    def __init__(self, unique_name, cantidad, nombre="", confianza=0.9):
        self.unique_name, self.cantidad, self.nombre, self.confianza = unique_name, cantidad, nombre, confianza


@pytest.fixture()
def usuario(tmp_path):
    con = usuario_db.conectar(tmp_path / "usuario.sqlite")
    yield con
    con.close()


def test_guardar_fusiona_sin_borrar_lo_que_no_se_ve(usuario):
    assert estado_inventario.guardar(usuario, [_Cantidad("/a", 3, "A"), _Cantidad("/b", 0, "B")], "inventario") == 2
    assert estado_inventario.guardar(usuario, [_Cantidad("/a", 5, "A")], "inventario") == 1
    a = estado_inventario.cantidad_de(usuario, "/a")
    b = estado_inventario.cantidad_de(usuario, "/b")
    assert (a.cantidad, a.veces, a.pantalla) == (5, 2, "inventario")
    assert (b.cantidad, b.veces) == (0, 1)
    assert a.leido_en and estado_inventario.cantidad_de(usuario, "/c") is None
    assert estado_inventario.hay_lecturas(usuario)


def test_lecturas_invalidas_se_descartan(usuario):
    assert estado_inventario.guardar(usuario, [_Cantidad("", 3), _Cantidad("/x", -1), _Cantidad("/y", None)]) == 0
    assert not estado_inventario.hay_lecturas(usuario)


def test_sincronizar_sube_los_objetivos_pero_nunca_los_baja(usuario):
    sistemas = estado_objetivos.anadir(usuario, "/sys", "Sistemas", 5)
    chasis = estado_objetivos.anadir(usuario, "/chs", "Chasis", 2)
    estado_objetivos.sumar(usuario, chasis, 2)  # ya lo tenia completo a mano
    estado_inventario.guardar(usuario, [_Cantidad("/sys", 3), _Cantidad("/chs", 1), _Cantidad("/otro", 9)])

    cambios = estado_inventario.sincronizar_objetivos(usuario)

    assert cambios == [("/sys", 0, 3)]
    por_item = {o.unique_name: o for o in estado_objetivos.listar(usuario)}
    assert (por_item["/sys"].actual, por_item["/sys"].completado) == (3, False)
    assert (por_item["/chs"].actual, por_item["/chs"].completado) == (2, True)  # no se baja a 1
    origen = usuario.execute(
        "SELECT origen, detalle FROM progreso_eventos WHERE objetivo_id = ?", (sistemas,)
    ).fetchone()
    assert origen == ("inventario", "inventario: 3")
    assert estado_inventario.sincronizar_objetivos(usuario) == []  # idempotente
