"""Rediseno C: navegacion centralizada (ir_a) y la pagina Tablero."""

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.estado import objetivos as estado_objetivos  # noqa: E402
from farmadex.estado import usuario_db  # noqa: E402
from farmadex.online.worldstate import Ciclo, Fisura, Mundo  # noqa: E402
from farmadex.ui import pestana_tablero  # noqa: E402

AHORA = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# -- navegacion -------------------------------------------------------------------------


@pytest.fixture()
def ventana(app, tmp_path, monkeypatch):
    from farmadex import config, tareas
    from farmadex.datos import indice

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    from farmadex.ui.overlay import VentanaOverlay

    idiomas.cargar("es")
    v = VentanaOverlay()
    v.show()
    yield v
    v.hide()
    idiomas.cargar("es")


def test_se_abre_en_el_tablero_con_el_menu_de_la_maqueta(ventana):
    from farmadex.ui.overlay import SECCIONES

    assert ventana.pagina_actual() is ventana.tablero
    assert ventana.ruta_actual() == "tablero"
    assert [c for c, _t in SECCIONES] == ["tablero", "buscar", "metas", "mundo", "herramientas", "ajustes"]
    assert ventana.menu.activa() == "tablero"
    assert ventana.boton_modo.text() == "Modo juego"


@pytest.mark.parametrize("destino, ruta, atributo", [
    ("buscar", "buscar", "buscador"),
    ("metas/primes", "metas/primes", "primes"),
    ("perfil", "metas/perfil", "perfil"),
    ("objetivos", "metas/objetivos", "objetivos"),
    ("builds", "herramientas/build", "builds"),
    ("herramientas/agrietados", "herramientas/agrietados", "agrietados"),
    ("video", "herramientas/video", "video"),
    ("web", "herramientas/web", "web"),
    ("mundo", "mundo", "mundo"),
    ("ajustes", "ajustes", "ajustes"),
])
def test_ir_a_acepta_rutas_alias_y_widgets(ventana, destino, ruta, atributo):
    pagina = getattr(ventana, atributo)
    assert ventana.ir_a(destino) is pagina
    assert ventana.ruta_actual() == ruta
    assert ventana.menu.activa() == ruta.split("/")[0]
    if "/" in ruta:
        seccion = ventana._seccion_con_sub(ruta.split("/")[0])
        assert seccion.subpestanas.activa() == ruta.split("/")[1]
    ventana.ir_a("tablero")
    assert ventana.ir_a(pagina) is pagina


def test_una_seccion_sola_vuelve_a_su_ultima_sub_pestana(ventana):
    ventana.ir_a("metas/perfil")
    ventana.ir_a("mundo")
    assert ventana.ir_a("metas") is ventana.perfil


def test_ruta_desconocida_no_cambia_nada(ventana):
    ventana.ir_a("mundo")
    assert ventana.ir_a("no-existe") is None
    assert ventana.pagina_actual() is ventana.mundo


def test_el_menu_y_las_sub_pestanas_navegan(ventana):
    ventana.menu.entrada("herramientas").click()
    assert ventana.menu.activa() == "herramientas"
    ventana._seccion_con_sub("herramientas").subpestanas.entrada("agrietados").click()
    assert ventana.pagina_actual() is ventana.agrietados


def test_las_rutas_internas_llegan_a_su_pagina(ventana):
    abiertos = []
    ventana.buscador.abrir = lambda item_id, recordar=True: abiertos.append(item_id)
    ventana._abrir_desde_cursor(5, "")
    assert ventana.pagina_actual() is ventana.buscador and abiertos == [5]
    ventana.tablero.abrir_item.emit(6)
    assert abiertos == [5, 6]
    ventana.tablero.navegar.emit("metas/objetivos")
    assert ventana.pagina_actual() is ventana.objetivos
    ventana._buscar_desde_mundo("forma")
    assert ventana.pagina_actual() is ventana.buscador and ventana.buscador.caja.text() == "forma"
    ventana.video.abrir = lambda url: None
    ventana.abrir_video("https://www.youtube.com/watch?v=x")
    assert ventana.pagina_actual() is ventana.video
    ventana.web.abrir = lambda url: None
    ventana.abrir_web("https://overframe.gg")
    assert ventana.pagina_actual() is ventana.web


def test_lo_tecleado_en_el_tablero_sigue_en_buscar(ventana):
    ventana.ir_a("tablero")
    ventana.tablero.caja.setText("c")
    ventana.tablero.caja.textEdited.emit("c")
    assert ventana.pagina_actual() is ventana.buscador
    assert ventana.buscador.caja.text() == "c"
    assert ventana.tablero.caja.text() == ""


def test_modo_video_esconde_menu_y_sub_pestanas(ventana):
    ventana.aplicar_modo("video")
    assert ventana.pagina_actual() is ventana.video
    assert not ventana.menu.isVisibleTo(ventana)
    assert not ventana._seccion_con_sub("herramientas").subpestanas.isVisibleTo(ventana)
    ventana.aplicar_modo("completo")
    assert ventana.menu.isVisibleTo(ventana)
    assert ventana._seccion_con_sub("herramientas").subpestanas.isVisibleTo(ventana)


def test_el_menu_cambia_de_idioma(ventana):
    ventana.cambiar_idioma("en")
    assert ventana.menu.entrada("metas").text() == "My goals"
    assert ventana.menu.entrada("herramientas").text() == "Tools"
    assert ventana._seccion_con_sub("herramientas").subpestanas.entrada("agrietados").text() == "Rivens"
    assert ventana.boton_modo.text() == "Game mode"


def test_la_cabecera_estrecha_quita_lo_accesorio_sin_perder_el_menu(ventana):
    # La pantalla de pruebas mide 800 px: ahi no cabe todo lo de la maqueta (1280).
    ventana.resize(800, 600)
    QApplication.processEvents()
    ventana._ajustar_cabecera()
    assert ventana.menu.isVisibleTo(ventana)
    assert not ventana.boton_modo.pista
    # En la compacta no hay menu: vuelve el nombre.
    ventana.aplicar_modo("compacto")
    assert ventana.titulo.isVisibleTo(ventana) and not ventana.menu.isVisibleTo(ventana)


def test_la_bandeja_abre_ajustes_por_la_navegacion(ventana, monkeypatch):
    from farmadex import app as modulo_app

    falsa = type("App", (), {"ventana": ventana})()
    monkeypatch.setattr(ventana, "mostrar", lambda: None)
    modulo_app.Aplicacion._abrir_ajustes(falsa)
    assert ventana.pagina_actual() is ventana.ajustes


# -- datos del tablero --------------------------------------------------------------------


@pytest.fixture()
def usuario(tmp_path):
    con = usuario_db.conectar(tmp_path / "u.sqlite")
    yield con
    con.close()


def _ruta(nombre_relic: str | None, minutos: float | None, boveda: bool = False, tipo: str = "reliquia"):
    reliquia = {"nombre_en": f"{nombre_relic} Relic", "nombre_es": f"Reliquia {nombre_relic}"} if nombre_relic else None
    return {"tipo": tipo, "reliquia": reliquia, "solo_en_boveda": boveda, "minutos_pieza": minutos,
            "minutos_medios": minutos, "mision": {"donde": "Hepit, Vacio", "mision": "Captura"}}


@pytest.fixture()
def rutas(monkeypatch):
    tabla = {
        "/chasis": _ruta("Neo C11", 84),
        "/sistemas": _ruta("Lith S19", 69),
        "/ash": _ruta("Axi A7", 30, boveda=True),
        "/celula": _ruta(None, 10, tipo="mision"),
    }
    monkeypatch.setattr(estado_objetivos, "ruta_de", lambda indice, unico: tabla.get(unico))
    monkeypatch.setattr(pestana_tablero, "_item", lambda indice, unico: None)
    return tabla


def _metas(usuario):
    estado_objetivos.anadir(usuario, "/chasis", "Citrine Prime: Chasis", grupo="/citrine", grupo_nombre="Citrine Prime")
    estado_objetivos.anadir(usuario, "/sistemas", "Citrine Prime: Sistemas", grupo="/citrine", grupo_nombre="Citrine Prime")
    estado_objetivos.anadir(usuario, "/ash", "Ash Prime: Sistemas")
    estado_objetivos.anadir(usuario, "/celula", "Celula orokin", 5)


def test_pasos_de_lo_mas_rapido_a_lo_que_esta_en_la_boveda(usuario, rutas):
    _metas(usuario)
    pasos = pestana_tablero.pasos_pendientes(object(), usuario)
    assert [p.objetivo.unique_name for p in pasos] == ["/celula", "/sistemas", "/chasis", "/ash"]
    assert pasos[1].reliquia == "Lith S19" and pasos[1].era == "Lith"
    assert pasos[-1].boveda and not pasos[-1].farmeable
    assert not pasos[0].es_reliquia


def test_las_eras_son_las_mismas_que_marca_mundo(usuario, rutas):
    _metas(usuario)
    pasos = pestana_tablero.pasos_pendientes(object(), usuario)
    assert pestana_tablero.eras_de(pasos) == estado_objetivos.eras_necesarias(object(), usuario)
    assert set(pestana_tablero.eras_de(pasos)) == {"Lith", "Neo"}


def test_completados_fuera_y_rutas_guardadas(usuario, rutas, monkeypatch):
    _metas(usuario)
    ash = next(o for o in estado_objetivos.listar(usuario) if o.unique_name == "/ash")
    estado_objetivos.completar(usuario, ash.id)
    cache = {}
    pestana_tablero.pasos_pendientes(object(), usuario, cache)
    llamadas = []
    monkeypatch.setattr(estado_objetivos, "ruta_de", lambda i, u: llamadas.append(u))
    pasos = pestana_tablero.pasos_pendientes(object(), usuario, cache)
    assert llamadas == [] and "/ash" not in [p.objetivo.unique_name for p in pasos]


def _fisura(era, nodo, mision, minutos, acero=False):
    return Fisura(era=era, nodo=nodo, mision=mision, enemigo="Grineer", expira=AHORA + timedelta(minutes=minutos),
                  acero=acero)


def test_fisuras_que_te_sirven(usuario, rutas):
    _metas(usuario)
    pasos = pestana_tablero.pasos_pendientes(object(), usuario)
    mundo = Mundo(fisuras=[
        _fisura("Lith", "Afrodita, Venus", "Defensa movil", 111),
        _fisura("Neo", "Neso, Neptuno", "Exterminio", 25),
        _fisura("Axi", "Xini, Eris", "Interceptacion", 50),     # Axi solo en boveda: no sirve
        _fisura("Lith", "Cambria, Tierra", "Espionaje", 100, acero=True),  # Acero: fuera
        _fisura("Lith", "Vieja, Marte", "Captura", -5),          # ya cerrada
    ])
    utiles = pestana_tablero.fisuras_utiles(mundo, pasos, AHORA)
    assert [f.nodo for f, _p in utiles] == ["Neso, Neptuno", "Afrodita, Venus"]
    assert utiles[1][1].objetivo.unique_name == "/sistemas"
    assert pestana_tablero.fisuras_abiertas(mundo, "Lith", AHORA) == 1
    assert pestana_tablero.fisuras_utiles(None, pasos) == []


@pytest.mark.parametrize("minutos, texto", [(None, ""), (9.6, "10 min"), (69, "1 h 09 min"), (120, "2 h"),
                                            (60 * 72, "3 d")])
def test_texto_tiempo(minutos, texto):
    assert pestana_tablero.texto_tiempo(minutos) == texto


# -- la pagina -------------------------------------------------------------------------------


@pytest.fixture()
def tablero(app, usuario, monkeypatch):
    monkeypatch.setattr(pestana_tablero, "_ahora", lambda: AHORA)
    idiomas.cargar("es")
    import sqlite3

    t = pestana_tablero.PestanaTablero()
    # Un indice vacio: las rutas salen de la tabla falsa de `rutas`.
    t.conectar(sqlite3.connect(":memory:"), usuario)
    t.resize(1200, 700)
    return t


def _textos(widget):
    from PySide6.QtWidgets import QLabel

    return " | ".join(e.text() for e in widget.findChildren(QLabel) if e.isVisibleTo(widget))


def test_sin_metas_invita_a_anadir_una(tablero):
    tablero.refrescar()
    assert "AÚN NO TIENES METAS" in _textos(tablero.heroe)
    assert "Todavía no tienes metas" in _textos(tablero.panel_metas)
    assert "Cargando el estado del mundo" in _textos(tablero.panel_fisuras)
    assert "Cargando el estado del mundo" in _textos(tablero.panel_ciclos)


def test_con_metas_ensena_el_siguiente_paso_y_las_fisuras(tablero, usuario, rutas):
    _metas(usuario)
    mundo = Mundo(
        fisuras=[_fisura("Lith", "Afrodita, Venus", "Defensa movil", 111), _fisura("Neo", "Neso, Neptuno", "Exterminio", 25)],
        ciclos=[Ciclo("Cetus", "noche", AHORA + timedelta(minutes=73), estado_en="night")],
    )
    tablero.actualizar_mundo(mundo)
    tablero.refrescar()
    heroe = _textos(tablero.heroe)
    assert "CELULA OROKIN" in heroe and "10 MIN" in heroe and "Llevas 0 de 5" in heroe
    assert "Citrine Prime: Sistemas" in heroe  # "Despues": la siguiente que se puede farmear
    fisuras = _textos(tablero.panel_fisuras)
    assert fisuras.index("Neso, Neptuno") < fisuras.index("Afrodita, Venus")
    assert "1 h 13 min" in _textos(tablero.panel_ciclos)
    assert "Celula orokin" in _textos(tablero.panel_metas)


def test_siguiente_paso_de_reliquia_dice_en_que_fisura_abrirla(tablero, usuario, rutas):
    estado_objetivos.anadir(usuario, "/sistemas", "Citrine Prime: Sistemas", grupo="/citrine", grupo_nombre="Citrine Prime")
    estado_objetivos.anadir(usuario, "/chasis", "Citrine Prime: Chasis", grupo="/citrine", grupo_nombre="Citrine Prime")
    tablero.actualizar_mundo(Mundo(fisuras=[_fisura("Lith", "Afrodita, Venus", "Defensa movil", 111)]))
    tablero.refrescar()
    heroe = _textos(tablero.heroe)
    assert "ÁBRELA EN UNA FISURA LITH" in heroe and "1 abierta ahora" in heroe
    assert "Lith S19" in heroe and "Te faltan 2 piezas de Citrine Prime para el set" in heroe


def test_sin_datos_del_mundo_lo_dice(tablero, usuario, rutas):
    _metas(usuario)
    tablero.marcar_desactualizado("sin red")
    tablero.refrescar()
    assert "No se pudo leer el estado del mundo" in _textos(tablero.panel_fisuras)
    assert "Sin datos del mundo todavía" in _textos(tablero.heroe) or "CELULA" in _textos(tablero.heroe)


def test_solo_recalcula_a_la_vista(tablero, usuario, rutas, monkeypatch):
    llamadas = []
    original = pestana_tablero.pasos_pendientes
    monkeypatch.setattr(pestana_tablero, "pasos_pendientes", lambda *a, **k: llamadas.append(1) or original(*a, **k))
    tablero.hide()
    tablero.marcar_sucio()
    assert llamadas == [] and tablero._sucio
    tablero.show()
    tablero._diferido.timeout.emit()
    assert llamadas == [1] and not tablero._sucio


def test_el_buscador_del_tablero_emite_lo_tecleado(tablero):
    recibido = []
    tablero.buscar.connect(recibido.append)
    tablero.caja.setText("ash")
    tablero.caja.textEdited.emit("ash")
    assert recibido == ["ash"] and tablero.caja.text() == ""


def test_con_el_indice_de_prueba_no_revienta(app, usuario, indice_poblado):
    con, _importador, _drops = indice_poblado
    unico = "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeSystemsComponent"
    estado_objetivos.anadir(usuario, unico, "Ash Prime: Sistemas", indice=con)
    pasos = pestana_tablero.pasos_pendientes(con, usuario)
    assert len(pasos) == 1 and pasos[0].item is not None
    assert pestana_tablero.eras_de(pasos) == estado_objetivos.eras_necesarias(con, usuario)
    t = pestana_tablero.PestanaTablero()
    t.conectar(con, usuario)
    t.refrescar()
    assert pasos[0].nombre in _textos(t.heroe).title() or pasos[0].nombre.upper() in _textos(t.heroe)


def test_con_metas_pero_sin_indice_todavia_espera_a_los_datos(app, usuario, rutas):
    _metas(usuario)
    t = pestana_tablero.PestanaTablero()
    t.conectar(None, usuario)
    t.refrescar()
    assert "Comprobando datos..." in _textos(t.heroe)
    assert "AÚN NO TIENES METAS" not in _textos(t.heroe)
