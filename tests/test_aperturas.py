"""Historial de aperturas de reliquias y el consejo de vender o fundir."""

import json
import os
import sqlite3
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from farmadex.captura.reliquias import Recompensa  # noqa: E402
from farmadex.datos import vender_fundir  # noqa: E402
from farmadex.estado import aperturas  # noqa: E402
from farmadex.estado.aperturas import Apertura, Grabador, Opcion  # noqa: E402
from farmadex.registro import eelog  # noqa: E402

SISTEMAS = "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeSystemsComponent"
CHASIS = "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeChassisComponent"
CANON = "/Lotus/Types/Recipes/Weapons/WeaponParts/BratonPrimeBarrel"
FORMA = "/Lotus/Types/Recipes/Components/FormaBlueprint"


# -- vender o fundir ----------------------------------------------------------------------


def test_fundir_cuando_da_muchos_ducados_por_platino():
    c = vender_fundir.aconsejar(5, 100, vendedores=5, compradores=3)
    assert c.clave == vender_fundir.FUNDIR and "20" in c.motivo


def test_vender_cuando_el_platino_compensa():
    c = vender_fundir.aconsejar(15, 45, vendedores=5, compradores=2)
    assert c.clave == vender_fundir.VENDER


def test_franja_muerta_da_igual():
    assert vender_fundir.aconsejar(7, 65, vendedores=5, compradores=1).clave == vender_fundir.IGUAL


def test_mercado_poco_liquido_baja_el_listón_de_fundir():
    # 65/7 = 9,3: con mercado normal da igual; si nadie compra y hay pocos vendedores, fundir.
    c = vender_fundir.aconsejar(7, 65, vendedores=2, compradores=0)
    assert c.clave == vender_fundir.FUNDIR and "nadie la compra" in c.motivo


def test_la_meta_gana_a_la_cuenta():
    c = vender_fundir.aconsejar(1, 100, es_meta=True)
    assert c.clave == vender_fundir.FALTA


@pytest.mark.parametrize("platino,ducados,edad", [
    (None, 100, 0), (10, None, 0), (10, 0, 0), (10, 45, None), (10, 45, 13 * 3600), (0, 45, 0),
])
def test_sin_precio_sin_ducados_o_precio_viejo_no_se_aconseja(platino, ducados, edad):
    assert vender_fundir.aconsejar(platino, ducados, edad_s=edad) is None


# -- EE.log: reliquia y refinamiento del dialogo de equipar -------------------------------


def test_reliquia_equipada_con_su_refinamiento_en_varios_idiomas():
    base = "12.3 Script [Info]: Dialog.lua: Dialog::CreateOkCancel(description=¿Seguro que quieres equipar Reliquia {}"
    assert eelog.reliquia_equipada(base.format("Lith K5 [PERFECTA] para esta misión?")) == "Lith K5|Flawless"
    assert eelog.reliquia_equipada(base.format("Axi A7 [RADIANT] ...")) == "Axi A7|Radiant"
    assert eelog.reliquia_equipada(base.format("Neo N1 [INTACTE] ...")) == "Neo N1|Intact"
    # Una palabra que no se conoce: la reliquia si, el refinamiento no se inventa.
    assert eelog.reliquia_equipada(base.format("Meso M2 [ZZZZ] ...")) == "Meso M2|"
    # El dialogo de refinar no dice que reliquia se usa.
    assert eelog.reliquia_equipada("Dialog.lua: ¿Refinar Reliquia Lith S18 a RADIANTE? Costará 100.") is None
    # Fuera de un dialogo del juego (chat) no vale.
    assert eelog.reliquia_equipada("Chat: equipa Reliquia Lith K5 [PERFECTA]") is None


# -- grabador ---------------------------------------------------------------------------


@pytest.fixture()
def usuario():
    from farmadex.estado import usuario_db

    con = sqlite3.connect(":memory:")
    con.executescript(usuario_db.ESQUEMA)
    aperturas.preparar(con)
    yield con
    con.close()


class Reloj:
    def __init__(self):
        self.ahora = datetime(2026, 9, 29, 20, 0, 0)

    def __call__(self):
        return self.ahora

    def avanzar(self, segundos):
        self.ahora += timedelta(seconds=segundos)


# Axi A7: Sistemas raro, Chasis poco comun, Canon comun. El Forma no sale de ella.
TABLA = {("Axi A7", SISTEMAS): "Rare", ("Axi A7", CHASIS): "Uncommon", ("Axi A7", CANON): "Common"}


def _grabador(usuario, reloj=None):
    return Grabador(usuario, rareza_en=lambda r, u: TABLA.get((r, u)),
                    resolver=lambda ruta: (ruta.replace("/StoreItems", ""), "N:" + ruta.rsplit("/", 1)[-1]),
                    reloj=reloj or Reloj())


def _rec(item_id, unique_name, nombre, ducados=None, platino=None, vendedores=0, compradores=None):
    r = Recompensa(item_id, nombre, nombre.upper(), (0, 0, 10, 10), ducados=ducados, platino=platino)
    r.unique_name = unique_name
    r.vendedores, r.compradores = vendedores, compradores
    return r


def test_solitario_con_una_sola_recompensa_en_el_log_se_apunta_como_obtenida(usuario):
    g = _grabador(usuario)
    g.pista("remotos", "0")
    g.pista("reliquia_equipada", "Axi A7|Radiant")
    g.evento("reliquia_abierta")
    g.pista("recompensa", SISTEMAS)
    g.leidas([_rec(1, SISTEMAS, "Sistemas de Ash Prime", ducados=100)])
    g.veredicto([_rec(1, SISTEMAS, "Sistemas de Ash Prime", ducados=100, platino=12, vendedores=5, compradores=2)])
    g.evento("reliquia_cerrada")
    [a] = aperturas.listar(usuario)
    assert a.fuente == "eelog" and a.en_solitario is True
    assert a.obtenida == SISTEMAS and a.como == aperturas.COMO_EELOG and a.sorteo_propio
    assert (a.reliquia, a.refinamiento, a.rareza_obtenida) == ("Axi A7", "Radiant", "Rare")
    # El precio que trajo el veredicto queda guardado para el historial.
    assert aperturas.precios(usuario, [SISTEMAS])[SISTEMAS].platino == 12


def test_en_escuadra_no_se_apunta_ninguna_como_obtenida(usuario):
    g = _grabador(usuario)
    g.pista("remotos", "3")
    g.evento("reliquia_abierta")
    for ruta in (SISTEMAS, CHASIS):
        g.pista("recompensa", ruta)
    g.leidas([_rec(1, SISTEMAS, "Sistemas"), _rec(2, CHASIS, "Chasis"), _rec(3, CANON, "Cañón"),
                 _rec(0, "", "???")])
    g.evento("reliquia_cerrada")
    [a] = aperturas.listar(usuario)
    assert a.obtenida is None and not a.confirmada and a.en_solitario is False
    # La tarjeta sin identificar no se guarda como opcion inventada.
    assert {o.unique_name for o in a.opciones} == {SISTEMAS, CHASIS, CANON}


def test_solitario_con_lectura_que_no_cuadra_no_se_confirma(usuario):
    g = _grabador(usuario)
    g.pista("remotos", "0")
    g.evento("reliquia_abierta")
    g.pista("recompensa", SISTEMAS)
    g.leidas([_rec(2, CHASIS, "Chasis")])  # el OCR leyo otra pieza: contradiccion
    g.evento("reliquia_cerrada")
    [a] = aperturas.listar(usuario)
    assert a.obtenida is None


def test_sin_saber_si_ibas_solo_no_se_confirma(usuario):
    g = _grabador(usuario)
    g.evento("reliquia_abierta")
    g.pista("recompensa", SISTEMAS)
    g.evento("reliquia_cerrada")
    [a] = aperturas.listar(usuario)
    assert a.obtenida is None and a.en_solitario is None


def test_la_ruta_de_tienda_de_eelog_se_casa_con_la_del_ocr(usuario):
    g = _grabador(usuario)
    g.pista("remotos", "0")
    g.evento("reliquia_abierta")
    g.pista("recompensa", SISTEMAS.replace("/Lotus/", "/Lotus/StoreItems/"))
    g.leidas([_rec(1, SISTEMAS, "Sistemas")])
    g.evento("reliquia_cerrada")
    [a] = aperturas.listar(usuario)
    assert a.obtenida == SISTEMAS and len(a.opciones) == 1


def test_reliquia_del_dialogo_que_no_suelta_la_pieza_se_descarta(usuario):
    g = _grabador(usuario)
    g.pista("remotos", "0")
    g.pista("reliquia_equipada", "Axi A7|Radiant")
    g.evento("reliquia_abierta")
    g.pista("recompensa", FORMA)
    g.evento("reliquia_cerrada")
    [a] = aperturas.listar(usuario)
    assert a.obtenida == FORMA  # la pieza si es segura (lo dijo el juego)
    assert a.reliquia is None and a.refinamiento is None and a.rareza_obtenida is None


def test_el_dialogo_vale_para_una_sola_apertura(usuario):
    g = _grabador(usuario)
    g.pista("remotos", "0")
    g.pista("reliquia_equipada", "Axi A7|Radiant")
    for _ in range(2):
        g.evento("reliquia_abierta")
        g.pista("recompensa", CANON)
        g.evento("reliquia_cerrada")
    segunda, primera = aperturas.listar(usuario)
    assert primera.reliquia == "Axi A7" and segunda.reliquia is None


def test_atajo_sin_eelog_guarda_opciones_y_junta_lecturas_de_la_misma_pantalla(usuario):
    reloj = Reloj()
    g = _grabador(usuario, reloj)
    g.leidas([_rec(1, SISTEMAS, "Sistemas"), _rec(2, CHASIS, "Chasis")])
    reloj.avanzar(5)
    g.leidas([_rec(1, SISTEMAS, "Sistemas"), _rec(2, CHASIS, "Chasis"), _rec(3, CANON, "Cañón")])
    [a] = aperturas.listar(usuario)
    assert a.fuente == "atajo" and a.obtenida is None and len(a.opciones) == 3
    # Otra pantalla que solo comparte una pieza (el Forma de otra reliquia) es otra apertura.
    reloj.avanzar(5)
    g.leidas([_rec(1, SISTEMAS, "Sistemas"), _rec(4, FORMA, "Forma"), _rec(5, "/x/a", "A"), _rec(6, "/x/b", "B")])
    assert len(aperturas.listar(usuario)) == 2
    # La misma mucho despues, tambien.
    reloj.avanzar(200)
    g.leidas([_rec(1, SISTEMAS, "Sistemas")])
    assert len(aperturas.listar(usuario)) == 3


def test_lectura_tardia_tras_el_cierre_se_junta_con_su_apertura(usuario):
    reloj = Reloj()
    g = _grabador(usuario, reloj)
    g.pista("remotos", "3")
    g.evento("reliquia_abierta")
    g.leidas([_rec(1, SISTEMAS, "Sistemas")])
    g.evento("reliquia_cerrada")
    reloj.avanzar(2)
    g.leidas([_rec(1, SISTEMAS, "Sistemas"), _rec(2, CHASIS, "Chasis")])
    [a] = aperturas.listar(usuario)
    assert len(a.opciones) == 2


def test_apagado_no_guarda_nada(usuario):
    g = _grabador(usuario)
    g.activo = False
    g.evento("reliquia_abierta")
    g.pista("recompensa", SISTEMAS)
    g.evento("reliquia_cerrada")
    g.leidas([_rec(1, SISTEMAS, "Sistemas")])
    assert aperturas.listar(usuario) == []


def test_de_eelog_no_se_guarda_el_id_de_jugador(usuario, tmp_path):
    """Las lineas reales llevan el id de jugador: al historial solo llega la ruta del objeto."""
    vigilante = eelog.VigilanteEELog(tmp_path / "no.log")
    g = _grabador(usuario)
    vigilante.evento.connect(g.evento)
    vigilante.pista.connect(g.pista)
    id_jugador = "5f1e2d3c4b5a69788796a5b4"
    vigilante._procesar([
        "10.0 Script [Info]: Progress.lua: Num remote players 0",
        "11.0 Script [Info]: ProjectionRewardChoice.lua: Relic rewards initialized",
        f"11.5 Sys [Info]: VoidProjections: {id_jugador} gets reward /Lotus/StoreItems/Types/Recipes/"
        "WarframeRecipes/AshPrimeSystemsComponent",
        "12.0 Script [Info]: ProjectionRewardChoice.lua: Relic reward screen shut down",
    ])
    [a] = aperturas.listar(usuario)
    assert a.obtenida == SISTEMAS
    volcado = json.dumps([list(f) for f in usuario.execute("SELECT * FROM aperturas")])
    assert id_jugador not in volcado and "@" not in volcado


# -- marcar, borrar -----------------------------------------------------------------------


def test_el_usuario_marca_cual_se_quedo_y_solo_de_las_opciones(usuario):
    a = Apertura(None, "2026-09-29T20:00:00", "eelog", [Opcion(SISTEMAS, "Sistemas", 100), Opcion(CHASIS, "Chasis", 45)])
    ident = aperturas.guardar(usuario, a)
    assert not aperturas.marcar_obtenida(usuario, ident, FORMA)  # no estaba en pantalla
    assert aperturas.marcar_obtenida(usuario, ident, CHASIS)
    b = aperturas.obtener_apertura(usuario, ident)
    assert b.obtenida == CHASIS and b.como == aperturas.COMO_USUARIO and not b.sorteo_propio
    assert aperturas.marcar_obtenida(usuario, ident, None)
    assert aperturas.obtener_apertura(usuario, ident).obtenida is None
    assert aperturas.borrar_todo(usuario) == 1 and aperturas.listar(usuario) == []


# -- estadisticas -------------------------------------------------------------------------


def _sorteo(rareza, refinamiento="Radiant"):
    return Apertura(None, "2026-09-29T20:00:00", "eelog", [], refinamiento=refinamiento, obtenida=SISTEMAS,
                    sorteo_propio=True, rareza_obtenida=rareza)


def test_suerte_con_pocas_aperturas_no_saca_conclusiones():
    s = aperturas.suerte([_sorteo("Rare")] * 3)
    assert s.poca_muestra and s.muestra == 3
    rara = s.por_rareza[2]
    assert rara.obtenidas == 3 and rara.esperadas == pytest.approx(0.3)


def test_suerte_solo_cuenta_sorteos_propios_con_refinamiento():
    otras = [Apertura(None, "x", "eelog", [], obtenida=SISTEMAS, como="usuario", rareza_obtenida="Rare"),
             _sorteo("Rare", refinamiento=None)]
    assert aperturas.suerte(otras).muestra == 0


def test_suerte_con_muestra_suficiente():
    normal = [_sorteo("Rare")] * 4 + [_sorteo("Uncommon")] * 16 + [_sorteo("Common")] * 20
    assert aperturas.suerte(normal).veredicto == "normal"
    mucha = [_sorteo("Rare")] * 15 + [_sorteo("Common")] * 25
    assert aperturas.suerte(mucha).veredicto == "mas"
    poca = [_sorteo("Common")] * 60 + [_sorteo("Uncommon")] * 40
    assert aperturas.suerte(poca).veredicto == "menos"


def test_totales_suman_solo_lo_confirmado_y_con_precio_reciente(usuario):
    ahora = datetime(2026, 9, 29, 20, 0, 0)
    lista = [
        Apertura(None, "a", "eelog", [Opcion(SISTEMAS, "S", 100)], obtenida=SISTEMAS),
        Apertura(None, "b", "eelog", [Opcion(CHASIS, "C", 45)], obtenida=CHASIS),
        Apertura(None, "c", "eelog", [Opcion(CANON, "B", 15)]),  # sin confirmar: no suma
    ]
    aperturas.guardar_precios(usuario, [(SISTEMAS, "s", 12, 5, 1)], visto_en=(ahora - timedelta(hours=1)).isoformat())
    aperturas.guardar_precios(usuario, [(CHASIS, "c", 30, 5, 1)], visto_en=(ahora - timedelta(days=3)).isoformat())
    tot = aperturas.totales(usuario, lista, vender_fundir.EDAD_MAXIMA_S, ahora)
    assert (tot.aperturas, tot.confirmadas, tot.sin_confirmar) == (3, 2, 1)
    assert tot.ducados == 145 and tot.platino == 12 and tot.sin_precio == 1


def test_aperturas_que_faltan_para_una_meta(con, usuario):
    con.executemany("INSERT INTO items (id, unique_name, nombre_en, vaulted, categoria) VALUES (?,?,?,?,'X')", [
        (1, SISTEMAS, "Systems", 0), (10, "RELIQUIA/Axi A7", "Axi A7 Relic", 1), (11, "RELIQUIA/Neo N9", "Neo N9", 0),
    ])
    con.executemany("INSERT INTO reliquia_recompensas VALUES (?,?,?,?,?)", [
        (10, "Intact", 1, "Rare", 2.0), (10, "Radiant", 1, "Rare", 10.0),
        (11, "Intact", 1, "Uncommon", 11.0), (11, "Radiant", 1, "Uncommon", 20.0),
    ])
    usuario.execute("INSERT INTO objetivos (item_unique_name, nombre, creado_en) VALUES (?, 'Sistemas', 'x')",
                    (SISTEMAS,))
    [f] = aperturas.aperturas_que_faltan(con, usuario, "Radiant")
    # Primero lo que se consigue hoy (Neo N9 fuera de boveda), aunque la de boveda tenga menos.
    assert f.reliquia == "Neo N9" and not f.reliquia_vaulted and f.probabilidad == 20.0
    assert f.aperturas_solo == pytest.approx(5.0)
    assert f.rondas_escuadra == pytest.approx(1 / (1 - 0.8 ** 4))


def test_refinamiento_habitual_necesita_datos():
    assert aperturas.refinamiento_habitual([_sorteo("Rare")] * 2) is None
    lista = [_sorteo("Rare", "Radiant")] * 3 + [_sorteo("Rare", "Intact")]
    assert aperturas.refinamiento_habitual(lista) == "Radiant"


# -- comparador y panel -------------------------------------------------------------------


def test_el_veredicto_trae_el_consejo_de_vender_o_fundir(con):
    from farmadex.captura.comparador import puntuar
    from farmadex.online.market import Orden, Precios

    con.executemany(
        "INSERT INTO items (id, unique_name, nombre_en, categoria, comerciable, ducados, market_slug) "
        "VALUES (?,?,?,?,?,?,?)",
        [(1, SISTEMAS, "Ash Prime Systems", "Warframes", 1, 100, "ash"),
         (2, CANON, "Braton Prime Barrel", "Primary", 1, 15, "braton")],
    )

    def precios_de(slug):
        p = Precios(slug=slug)
        valor = {"ash": 4, "braton": 9}[slug]
        p.ventas = [Orden(valor + i, 1, "u", "ingame") for i in range(5)]
        p.compras = [Orden(valor - 1, 1, "c", "ingame")]
        return p

    recompensas = [_rec(1, "", "Ash Prime Systems"), _rec(2, "", "Braton Prime Barrel")]
    puntuar(recompensas, con, precios_de)
    assert recompensas[0].consejo == "fundir" and recompensas[0].consejo_texto
    assert recompensas[1].consejo == "vender"
    assert recompensas[0].compradores == 1 and recompensas[0].vendedores == 5


def test_sin_precio_el_veredicto_no_aconseja(con):
    from farmadex.captura.comparador import puntuar

    con.execute("INSERT INTO items (id, unique_name, nombre_en, comerciable, ducados, market_slug, categoria) "
                "VALUES (1, ?, 'X', 1, 100, 'x', 'Warframes')", (SISTEMAS,))
    recompensas = [_rec(1, "", "X")]
    puntuar(recompensas, con, None)
    assert recompensas[0].consejo == ""


def test_el_panel_ensena_el_consejo_al_llegar_el_veredicto():
    from PySide6.QtWidgets import QApplication

    from farmadex.captura.comparador import Veredicto
    from farmadex.ui.panel_recompensas import PanelRecompensas

    QApplication.instance() or QApplication([])
    panel = PanelRecompensas()
    en_pantalla = [_rec(1, SISTEMAS, "Sistemas", ducados=100)]
    panel.mostrar(en_pantalla)
    assert not any("fundir" in texto.lower() for texto, *_ in panel._detalles(panel.recompensas[0]))
    llegada = [_rec(1, SISTEMAS, "Sistemas", ducados=100, platino=5)]
    llegada[0].consejo, llegada[0].consejo_texto = "fundir", "Mejor fundir"
    panel.marcar_veredicto(llegada, Veredicto([], 0, True, ""))
    assert any(texto == "Mejor fundir" for texto, *_ in panel._detalles(panel.recompensas[0]))
    panel.hide()


# -- la vista -----------------------------------------------------------------------------


def test_la_vista_del_historial_se_pinta_y_borra(usuario, con, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    from farmadex.ui.pestana_historial import PestanaHistorial

    QApplication.instance() or QApplication([])
    con.executemany("INSERT INTO items (id, unique_name, nombre_en, nombre_es, ducados, market_slug, categoria) "
                    "VALUES (?,?,?,?,?,?,'Warframes')",
                    [(1, SISTEMAS, "Systems", "Sistemas", 100, "ash"), (2, CHASIS, "Chassis", "Chasis", 45, "ch")])
    ahora = datetime.now().replace(microsecond=0)
    ident = aperturas.guardar(usuario, Apertura(
        None, ahora.isoformat(), "eelog", [Opcion(SISTEMAS, "Sistemas", 100), Opcion(CHASIS, "Chasis", 45)],
        reliquia="Axi A7", refinamiento="Radiant", en_solitario=False))
    aperturas.guardar_precios(usuario, [(SISTEMAS, "ash", 5, 5, 1), (CHASIS, "ch", 20, 5, 1)])
    vista = PestanaHistorial(usuario, {})
    vista.conectar_indice(con)
    vista.pintar()
    texto = vista.texto_plano()
    assert "Aperturas guardadas: 1 (0 con la pieza confirmada, 1 sin confirmar)" in texto
    assert "Sin confirmar" in texto and "Reliquia Axi A7 (Radiante)" in texto
    assert "Mejor fundir" in texto and "Mejor vender" in texto
    assert "pocas" in texto or "Todavía no hay" in texto
    vista._elegido(ident, SISTEMAS)
    vista.pintar()
    texto = vista.texto_plano()
    assert "Te llevaste: Sistemas (lo marcaste tú)" in texto and "Ducados de lo que te has llevado: 100" in texto
    assert "unos 5" in texto  # platino estimado con el precio reciente
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    vista.pedir_borrar()
    assert aperturas.listar(usuario) == []
    vista.pintar()  # (en la ventana se repinta solo al estar a la vista)
    assert "Aún no hay aperturas" in vista.texto_plano()


def test_un_veredicto_atrasado_de_otra_pantalla_no_se_cuela(usuario):
    """El comparador tarda (precios): su veredicto puede llegar con la siguiente reliquia ya abierta."""
    reloj = Reloj()
    g = _grabador(usuario, reloj)
    g.pista("remotos", "3")
    g.evento("reliquia_abierta")
    g.leidas([_rec(1, SISTEMAS, "Sistemas"), _rec(2, CHASIS, "Chasis")])
    g.evento("reliquia_cerrada")
    reloj.avanzar(120)
    g.evento("reliquia_abierta")
    g.leidas([_rec(3, CANON, "Cañón"), _rec(4, FORMA, "Forma")])
    # Llega ahora el veredicto de la pantalla anterior, con precios.
    g.veredicto([_rec(1, SISTEMAS, "Sistemas", platino=12), _rec(2, CHASIS, "Chasis", platino=7)])
    g.veredicto([_rec(3, CANON, "Cañón", platino=3)])
    g.evento("reliquia_cerrada")
    segunda, primera = aperturas.listar(usuario)
    assert {o.unique_name for o in segunda.opciones} == {CANON, FORMA}
    assert {o.unique_name for o in primera.opciones} == {SISTEMAS, CHASIS}
    assert next(o for o in segunda.opciones if o.unique_name == CANON).platino == 3
    # Los precios si se guardan: son del mercado, valen para el historial.
    assert set(aperturas.precios(usuario, [SISTEMAS, CHASIS, CANON])) == {SISTEMAS, CHASIS, CANON}


def test_el_veredicto_completa_el_precio_de_la_ultima_ya_guardada(usuario):
    g = _grabador(usuario)
    g.leidas([_rec(1, SISTEMAS, "Sistemas")])  # atajo: se guarda ya, sin precio
    g.veredicto([_rec(1, SISTEMAS, "Sistemas", platino=12)])
    [a] = aperturas.listar(usuario)
    assert a.opciones[0].platino == 12
