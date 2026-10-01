"""Recursos como meta: buscador, cuanto falta, donde cae, y lo que suma la lectura de fin de mision."""

import pytest
from PySide6.QtWidgets import QApplication

from farmadex import config
from farmadex.captura import fin_mision as FM
from farmadex.estado import objetivos, usuario_db
from farmadex.ui import pestana_objetivos

PLASTIDOS = "/Lotus/Types/Items/MiscItems/Plastids"
NEURODOS = "/Lotus/Types/Items/MiscItems/Neurode"
PLACA = "/Lotus/Types/Items/MiscItems/AlloyPlate"


def _recursos(con):
    con.executemany(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, descripcion_es, categoria) VALUES (?, ?, ?, ?, 'Resources')",
        [
            (PLASTIDOS, "Plastids", "Plástidos", "Ubicación: Saturno, Urano, Fobos, Plutón y Eris."),
            (NEURODOS, "Neurodes", "Neurodos", "Ubicación: Tierra, Deimos, Eris y Lua."),
            (PLACA, "Alloy Plate", "Placa de aleación", "Ubicación: Venus, Fobos, Ceres, Júpiter, Plutón y Sedna."),
            ("/Lotus/Types/Items/MiscItems/OrokinCell", "Orokin Cell", "Célula orokin", ""),
        ],
    )
    con.execute(
        "INSERT INTO items (unique_name, nombre_en, nombre_es, categoria) VALUES ('/Arma', 'Plasma Sword', 'Espada de plasma', 'Melee')"
    )
    con.commit()


@pytest.fixture()
def usuario(tmp_path):
    con = usuario_db.conectar(tmp_path / "u.sqlite")
    yield con
    con.close()


@pytest.fixture()
def pestana(tmp_path, monkeypatch, con):
    QApplication.instance() or QApplication([])
    _recursos(con)
    real = usuario_db.conectar
    monkeypatch.setattr(pestana_objetivos.usuario_db, "conectar", lambda *a, **k: real(tmp_path / "u.sqlite"))
    p = pestana_objetivos.PestanaObjetivos()
    p.conectar_indice(con)
    yield p
    p.usuario.close()


def _fila(p, unico):
    for i in range(p.caja_filas.count()):
        w = p.caja_filas.itemAt(i).widget()
        if getattr(w, "objetivo", None) is not None and w.objetivo.unique_name == unico:
            return w
    raise AssertionError(f"no hay fila de {unico}")


# -- buscador ---------------------------------------------------------------------------


def test_buscador_solo_recursos_en_tu_idioma_y_sin_tildes(con):
    _recursos(con)
    assert objetivos.buscar_recursos(con, "plast") == [(PLASTIDOS, "Plástidos")]
    assert objetivos.buscar_recursos(con, "PLÁSTIDOS") == [(PLASTIDOS, "Plástidos")]
    # Quien juega en ingles escribe el nombre ingles y lo encuentra igual, en su idioma.
    assert objetivos.buscar_recursos(con, "alloy") == [(PLACA, "Placa de aleación")]
    assert objetivos.buscar_recursos(con, "plast", castellano=False) == [(PLASTIDOS, "Plastids")]
    # Un arma no es un recurso.
    assert objetivos.buscar_recursos(con, "plasma") == []
    assert objetivos.buscar_recursos(con, "zzz") == []


def test_buscador_sin_texto_los_da_todos_y_primero_los_que_empiezan(con):
    _recursos(con)
    assert [n for _, n in objetivos.buscar_recursos(con, "")] == [
        "Célula orokin", "Neurodos", "Placa de aleación", "Plástidos"]
    # "pla": Placa y Plastidos empiezan asi.
    assert [n for _, n in objetivos.buscar_recursos(con, "pla")] == ["Placa de aleación", "Plástidos"]
    assert objetivos.buscar_recursos(None, "pla") == []


# -- estado -------------------------------------------------------------------------------


def test_la_misma_mision_no_se_cuenta_dos_veces(usuario):
    oid = objetivos.anadir(usuario, PLASTIDOS, "Plástidos", 5000, categoria=objetivos.RECURSOS)
    assert objetivos.sumar_de_mision(usuario, PLASTIDOS, 1196, "m1").actual == 1196
    assert objetivos.sumar_de_mision(usuario, PLASTIDOS, 1196, "m1") is None
    assert objetivos.obtener_objetivo(usuario, oid).actual == 1196
    assert objetivos.sumar_de_mision(usuario, PLASTIDOS, 804, "m2").actual == 2000
    origenes = usuario.execute("SELECT origen, cantidad, detalle FROM progreso_eventos ORDER BY id").fetchall()
    assert origenes == [("fin_mision", 1196, "m1"), ("fin_mision", 804, "m2")]


def test_no_pasa_de_la_meta_ni_suma_cosas_raras(usuario):
    oid = objetivos.anadir(usuario, NEURODOS, "Neurodos", 10, categoria=objetivos.RECURSOS)
    assert objetivos.sumar_de_mision(usuario, NEURODOS, 0, "m1") is None
    assert objetivos.sumar_de_mision(usuario, NEURODOS, -3, "m1") is None
    assert objetivos.sumar_de_mision(usuario, NEURODOS, 4, "") is None
    assert objetivos.sumar_de_mision(usuario, "/NoEsMeta", 4, "m1") is None
    hecho = objetivos.sumar_de_mision(usuario, NEURODOS, 25, "m1")
    assert hecho.actual == 10 and hecho.completado
    # Completado: ya no se le suma nada ni se busca en la pantalla.
    assert objetivos.sumar_de_mision(usuario, NEURODOS, 2, "m2") is None
    assert objetivos.recursos_pendientes(usuario) == []
    assert objetivos.obtener_objetivo(usuario, oid).actual == 10


def test_pendientes_solo_recursos_sin_completar_y_reiniciar(usuario):
    oid = objetivos.anadir(usuario, PLASTIDOS, "Plástidos", 5000, categoria=objetivos.RECURSOS)
    objetivos.anadir(usuario, "/Arma", "Espada", 1, categoria=objetivos.ARMAS)
    assert objetivos.recursos_pendientes(usuario) == [PLASTIDOS]
    objetivos.sumar(usuario, oid, 300)
    assert objetivos.reiniciar(usuario, oid).actual == 0
    assert objetivos.obtener_objetivo(usuario, oid).objetivo == 5000


# -- la pestana ---------------------------------------------------------------------------


def test_anadir_un_recurso_con_meta_ensena_barra_falta_y_donde_cae(pestana):
    pestana.anadir_recurso(PLASTIDOS, "Plástidos", 5000)
    fila = _fila(pestana, PLASTIDOS)
    assert fila.objetivo.categoria == objetivos.RECURSOS
    assert fila.barra is not None and fila.barra.progreso == 0
    assert fila.falta.text() == "Te faltan 5.000 · llevas el 0%"
    assert "Saturno" in fila.donde.text() and "Urano" in fila.donde.text()

    objetivos.sumar(pestana.usuario, fila.objetivo.id, 1250)
    pestana._tras_cambio(fila.clave)  # pasa a "En progreso" y la pestana la sigue
    fila = _fila(pestana, PLASTIDOS)
    assert fila.falta.text() == "Te faltan 3.750 · llevas el 25%"
    assert fila.barra.progreso == pytest.approx(0.25)


def test_meta_conseguida(pestana):
    oid = pestana.anadir_recurso(NEURODOS, "Neurodos", 10)
    objetivos.sumar(pestana.usuario, oid, 10)
    pestana._tras_cambio(f"o:{oid}")
    fila = _fila(pestana, NEURODOS)
    assert fila.falta.text() == "¡Meta conseguida!" and fila.barra.progreso == 1


def test_lo_que_no_es_un_recurso_sigue_como_estaba(pestana):
    objetivos.anadir(pestana.usuario, "/Arma", "Espada de plasma", 1, categoria=objetivos.ARMAS)
    pestana.refrescar()
    fila = _fila(pestana, "/Arma")
    assert fila.barra is None and fila.falta is None


def test_dialogo_de_recurso_busca_y_devuelve_lo_elegido(pestana):
    dialogo = pestana_objetivos.DialogoRecurso(pestana.indice)
    assert dialogo.lista.count() == 4
    dialogo.buscador.setText("neuro")
    assert [dialogo.lista.item(i).text() for i in range(dialogo.lista.count())] == ["Neurodos"]
    dialogo.meta.setValue(10)
    assert dialogo.elegido() == (NEURODOS, "Neurodos", 10)
    dialogo.buscador.setText("zzz")
    assert dialogo.elegido() is None
    assert not dialogo.botones.button(pestana_objetivos.QDialogButtonBox.Ok).isEnabled()
    assert not dialogo.sin_resultados.isHidden()


def test_editar_permite_corregir_a_mano_y_empezar_de_cero(pestana):
    oid = pestana.anadir_recurso(PLASTIDOS, "Plástidos", 5000)
    objetivos.sumar(pestana.usuario, oid, 1200)
    pestana._tras_cambio(f"o:{oid}")
    dialogo = _fila(pestana, PLASTIDOS)._dialogo()
    assert dialogo.valores() == (5000, 1200)
    dialogo.actual.setValue(1300)  # corregir a mano
    assert dialogo.valores() == (5000, 1300)
    dialogo.reiniciar.click()
    assert dialogo.valores() == (5000, 0)


def test_el_conteo_solo_viene_apagado_y_se_enciende_desde_la_pestana(pestana):
    assert config.POR_DEFECTO["recursos_fin_mision_auto"] is False
    assert not pestana.auto_recursos.isChecked()
    avisos = []
    pestana.recursos_auto_cambiado.connect(avisos.append)
    pestana.auto_recursos.setChecked(True)
    assert avisos == [True] and config.cargar()["recursos_fin_mision_auto"] is True
    assert "pantalla de resultados" in pestana.aviso.text()
    pestana.auto_recursos.setChecked(False)
    assert avisos == [True, False] and config.cargar()["recursos_fin_mision_auto"] is False


def test_resultado_de_la_mision_suma_lo_seguro_y_dice_lo_que_no_pudo_leer(pestana):
    pestana.anadir_recurso(PLASTIDOS, "Plástidos", 5000)
    pestana.anadir_recurso(NEURODOS, "Neurodos", 10)
    pestana.anadir_recurso(PLACA, "Placa de aleación", 3000)
    assert sorted(pestana.recursos_pendientes()) == sorted([PLASTIDOS, NEURODOS, PLACA])

    resultado = FM.Resultado("m1", {PLASTIDOS: 1196}, {NEURODOS: FM.CIFRA_DUDOSA, PLACA: FM.NO_VISTO})
    texto = pestana.resultado_fin_mision(resultado)
    assert "+1.196 Plástidos" in texto
    assert "No he podido leer bien Neurodos" in texto
    assert "No he visto Placa de aleación" in texto
    assert pestana.aviso.text() == texto and not pestana.aviso.isHidden()
    actual = {o.unique_name: o.actual for o in objetivos.listar(pestana.usuario)}
    assert actual == {PLASTIDOS: 1196, NEURODOS: 0, PLACA: 0}

    # La misma mision otra vez (segunda lectura, reinicio de Farmadex...): no cuenta doble.
    texto = pestana.resultado_fin_mision(FM.Resultado("m1", {PLASTIDOS: 1196}, {}))
    assert texto == ""
    assert {o.unique_name: o.actual for o in objetivos.listar(pestana.usuario)}[PLASTIDOS] == 1196


def _con_receta(con, unico):
    """Le pone al recurso una receta de dos ingredientes (el indice trae alguna asi)."""
    padre = con.execute("SELECT id FROM items WHERE unique_name = ?", (unico,)).fetchone()[0]
    for otro in (PLACA, "/Lotus/Types/Items/MiscItems/OrokinCell"):
        item = con.execute("SELECT id FROM items WHERE unique_name = ?", (otro,)).fetchone()[0]
        con.execute("INSERT INTO recetas (padre_id, item_id, cantidad) VALUES (?, ?, 2)", (padre, item))
    con.commit()


def test_un_recurso_que_cae_por_los_planetas_no_ensena_receta_y_uno_fabricable_si(pestana):
    _con_receta(pestana.indice, NEURODOS)  # cae en la Tierra, Deimos...: se farmea
    _con_receta(pestana.indice, "/Lotus/Types/Items/MiscItems/OrokinCell")  # sin planetas: se queda la receta
    pestana.anadir_recurso(NEURODOS, "Neurodos", 10)
    pestana.anadir_recurso("/Lotus/Types/Items/MiscItems/OrokinCell", "Célula orokin", 5)
    assert _fila(pestana, NEURODOS).panel_recursos is None
    assert "Tierra" in _fila(pestana, NEURODOS).donde.text()
    assert _fila(pestana, "/Lotus/Types/Items/MiscItems/OrokinCell").panel_recursos is not None
