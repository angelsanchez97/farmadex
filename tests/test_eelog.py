"""Lo que se saca de EE.log: eventos de la pantalla de reliquias y pistas para adelantar precios.

Las lineas son calcos de un EE.log real (septiembre de 2026), con los ids de
jugador sustituidos por hexadecimal inventado.
"""

from farmadex.registro import eelog
from farmadex.registro.eelog import VigilanteEELog, clasificar, leer_eventos, leer_lineas, pista

EQUIPAR = (
    "213.036 Script [Info]: Dialog.lua: Dialog::CreateOkCancel(description=¿Seguro que quieres "
    "equipar Reliquia Lith K5 [PERFECTA] para esta misión? Esta será consumida si sellas la "
    "Fisura Del Vacío., title= leftItem=/Menu/Confirm_Item_Yes, rightItem=/Menu/Confirm_Item_No)"
)
REFINAR = (
    "207.672 Script [Info]: Dialog.lua: Dialog::CreateOkCancel(description=¿Refinar Reliquia "
    "Lith S18 a RADIANTE? Costará 100., title= leftItem=/Menu/Confirm_Item_Yes)"
)
RECOMPENSA = (
    "404.409 Sys [Info]: VoidProjections: 0123456789abcdef01234567 gets reward "
    "/Lotus/StoreItems/Types/Recipes/Weapons/WeaponParts/BurstonPrimeStock"
)
ABIERTA = "404.207 Script [Info]: ProjectionRewardChoice.lua: Relic rewards initialized"
GOT = "404.409 Script [Info]: ProjectionRewardChoice.lua: Got rewards"


def test_pista_reliquia_equipada_y_refinada():
    assert pista(EQUIPAR) == ("reliquia", "Lith K5")
    assert pista(REFINAR) == ("reliquia", "Lith S18")
    assert pista("100.0 Script [Info]: Dialog.lua: Dialog::CreateOk(description=Hola)") is None


def test_pista_recompensa_traduce_la_ruta_de_tienda_y_no_copia_el_id():
    tipo, valor = pista(RECOMPENSA)
    assert tipo == "recompensa"
    assert valor == "/Lotus/Types/Recipes/Weapons/WeaponParts/BurstonPrimeStock"
    assert "0123456789abcdef" not in valor


def test_nombre_de_reliquia_solo_cuenta_en_dialogos():
    """Un jugador puede llamarse 'Axi A1'; en el chat o en la escuadra no es una pista."""
    assert pista("5.0 Script [Info]: ThemedSquadOverlay.lua: nemesis: adding squad member Axi A1") is None
    assert pista("5.0 Script [Info]: Dialog.lua: nada que ver aqui") is None


def test_pista_no_pisa_a_los_eventos():
    assert clasificar(ABIERTA) == "reliquia_abierta"
    assert pista(ABIERTA) is None
    assert clasificar(RECOMPENSA) is None


def test_leer_lineas_deja_la_linea_a_medias_para_la_siguiente_pasada(tmp_path):
    ruta = tmp_path / "EE.log"
    ruta.write_bytes((EQUIPAR + "\n" + ABIERTA[:20]).encode("utf-8"))
    lineas, pos = leer_lineas(ruta, 0)
    assert lineas == [EQUIPAR]
    assert pos == len((EQUIPAR + "\n").encode("utf-8"))
    ruta.write_bytes((EQUIPAR + "\n" + ABIERTA + "\n" + GOT + "\n").encode("utf-8"))
    eventos, pos2 = leer_eventos(ruta, pos)
    assert eventos == ["reliquia_abierta", "reliquia_recompensas"]
    assert pos2 == ruta.stat().st_size


def test_el_vigilante_emite_eventos_y_pistas_en_orden():
    vigilante = VigilanteEELog("no_existe.log")
    recibido = []
    vigilante.evento.connect(lambda e: recibido.append(("evento", e)))
    vigilante.pista.connect(lambda tipo, valor: recibido.append((tipo, valor)))
    vigilante._procesar([EQUIPAR, "x", ABIERTA, RECOMPENSA, GOT])
    assert recibido == [
        ("reliquia", "Lith K5"),
        ("evento", "reliquia_abierta"),
        ("recompensa", "/Lotus/Types/Recipes/Weapons/WeaponParts/BurstonPrimeStock"),
        ("evento", "reliquia_recompensas"),
    ]


def test_los_marcadores_documentados_siguen_reconocidos():
    for marcador, evento in eelog.EVENTOS.items():
        assert clasificar(f"1.0 Script [Info]: {marcador}") == evento


def test_el_reloj_estima_lo_que_una_linea_espero_en_el_buffer():
    """El juego vuelca EE.log a rafagas: una linea escrita en 100,0 s que se lee
    a la vez que otra escrita en 104,8 s llevaba 4,8 s en el buffer."""
    reloj = eelog.RelojEELog()
    assert reloj.retraso("Sys [Diag]: sin marca de tiempo", ahora=1000.0) is None
    assert reloj.retraso("100.000 Script [Info]: puntual", ahora=1000.0) == 0.0
    # Llega 4,8 s despues de escribirse (junto con una linea recien escrita).
    assert abs(reloj.retraso("100.000 Script [Info]: Got rewards", ahora=1004.8) - 4.8) < 1e-6
    assert reloj.retraso("104.800 Script [Info]: puntual", ahora=1004.8) == 0.0
    # Una linea que llega mas puntual que todas las anteriores baja el desfase.
    assert reloj.retraso("110.000 Script [Info]: mas puntual", ahora=1009.9) == 0.0
    assert abs(reloj.retraso("110.000 Script [Info]: otra", ahora=1010.0) - 0.1) < 1e-6
    reloj.reiniciar()
    assert reloj.retraso("1.000 Script [Info]: el juego arranco de nuevo", ahora=2000.0) == 0.0


def test_el_vigilante_anota_el_retraso_de_cada_evento(tmp_path):
    vigilante = VigilanteEELog(tmp_path / "EE.log")
    vigilante.reloj.retraso("404.000 Script [Info]: puntual", ahora=1000.0)
    eventos: list[str] = []
    vigilante.evento.connect(eventos.append)
    vigilante._procesar([ABIERTA, GOT])
    assert eventos == ["reliquia_abierta", "reliquia_recompensas"]
    retrasos = vigilante.retrasos
    assert set(retrasos) == {"reliquia_abierta", "reliquia_recompensas"}
    # Las dos llegaron juntas, asi que la escrita antes (404,207) lleva 0,2 s mas esperando.
    assert abs((retrasos["reliquia_abierta"] - retrasos["reliquia_recompensas"]) - 0.202) < 1e-3
