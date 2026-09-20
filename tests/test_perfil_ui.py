"""Pestana Perfil y marca de maestria en el buscador, sin pantalla."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex import perfil as P  # noqa: E402
from farmadex.estado import usuario_db  # noqa: E402

from conftest import FIXTURES  # noqa: E402
from test_perfil import ITEMS_CATALOGO  # noqa: E402

RUTA_PERFIL = FIXTURES / "perfil_recortado.json"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def catalogo(indice_poblado):
    con, _, _ = indice_poblado
    con.executemany(
        "INSERT OR IGNORE INTO items (unique_name, nombre_en, categoria, tipo) VALUES (?, ?, ?, ?)",
        ITEMS_CATALOGO,
    )
    con.commit()
    return con


@pytest.fixture()
def usuario(tmp_path):
    con = usuario_db.conectar(tmp_path / "usuario.sqlite")
    yield con
    con.close()


@pytest.fixture()
def pestana(app, usuario, catalogo, monkeypatch, tmp_path):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_perfil import PestanaPerfil

    idiomas.cargar("es")
    p = PestanaPerfil(usuario)
    p.conectar_indice(catalogo)
    yield p
    idiomas.cargar("es")


def _id(catalogo, nombre_en):
    return catalogo.execute("SELECT id FROM items WHERE nombre_en = ?", (nombre_en,)).fetchone()[0]


def test_sin_perfil_dice_que_no_hay_fuente_y_como_importar(pestana):
    texto = pestana.vista.toPlainText()
    # DE cerro la descarga del perfil (403): nada de mandar al usuario a una URL rota.
    assert "warframe.com/api" not in texto and "getProfileViewingData" not in texto
    assert "Digital Extremes" in texto
    assert "Importar perfil (JSON)..." in texto
    assert not pestana.filtro_acero.isVisibleTo(pestana)
    assert not pestana.hay_perfil()


def test_importar_ensena_resumen_pendientes_y_nodos(pestana, catalogo):
    cambios = []
    pestana.perfil_cambiado.connect(lambda: cambios.append(1))
    pestana.importar(RUTA_PERFIL, en_segundo_plano=False)
    assert cambios == [1]
    assert pestana.hay_perfil()
    assert "importado" in pestana.estado.text()
    texto = pestana.vista.toPlainText()
    assert "Rango de maestria 21" in texto
    assert "MAESTRIA POR CATEGORIA" in texto
    assert "POR DOMINAR" in texto
    assert "NODOS PENDIENTES" in texto
    # Los sindicatos y los intrinsecos del fixture salen con su nombre del juego.
    assert "Meridiano de Acero" in texto and "Pilotaje" in texto
    # Un nodo del catalogo que el perfil no trae hecho aparece como pendiente.
    assert "Hydron" in texto or "Abaddon" in texto


def test_un_json_recortado_da_aviso_claro_sin_dialogo(pestana, tmp_path):
    malo = tmp_path / "malo.json"
    malo.write_text(RUTA_PERFIL.read_text(encoding="utf-8")[:500], encoding="utf-8")
    pestana.importar(malo, en_segundo_plano=False)
    assert not pestana.hay_perfil()
    assert "No se ha importado" in pestana.estado.text()
    assert "recortado" in pestana.estado.text()
    # Y un JSON de otra cosa tampoco cuela.
    otro = tmp_path / "otro.json"
    otro.write_text(json.dumps({"hola": 1}), encoding="utf-8")
    pestana.importar(otro, en_segundo_plano=False)
    assert "No se ha importado" in pestana.estado.text()


def test_la_importacion_en_segundo_plano_termina(pestana, app):
    pestana.importar(RUTA_PERFIL)
    assert pestana._lector is not None
    assert pestana._lector.wait(5000)
    for _ in range(20):
        app.processEvents()
    assert pestana.hay_perfil()
    assert pestana.boton.isEnabled()


def test_la_pestana_cambia_de_idioma(pestana):
    pestana.importar(RUTA_PERFIL, en_segundo_plano=False)
    idiomas.cargar("en")
    pestana.retraducir()
    assert pestana.boton.text() == "Import profile (JSON)..."
    texto = pestana.vista.toPlainText()
    assert "Mastery Rank 21" in texto
    assert "Steel Meridian" in texto


def test_el_buscador_marca_dominado_a_medias_y_sin_tocar(app, usuario, catalogo, monkeypatch, tmp_path):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_buscador import PestanaBuscador

    idiomas.cargar("es")
    buscador = PestanaBuscador()
    buscador.con = catalogo
    # Sin perfil: la ficha no lleva ninguna marca, como hasta ahora.
    buscador.conectar_usuario(usuario)
    buscador.abrir(_id(catalogo, "Excalibur"))
    assert "Dominado" not in buscador.ficha.toPlainText()
    assert "Sin dominar" not in buscador.ficha.toPlainText()

    P.importar(RUTA_PERFIL, usuario, catalogo)
    buscador.refrescar_perfil()
    buscador.abrir(_id(catalogo, "Excalibur"))
    assert "Dominado" in buscador.ficha.toPlainText()
    buscador.abrir(_id(catalogo, "MK1-Kunai"))  # 100.000 de 450.000 XP
    assert "Maestria 22 % (rango 14)" in buscador.ficha.toPlainText()
    buscador.abrir(_id(catalogo, "Dark Sword"))
    assert "Sin dominar" in buscador.ficha.toPlainText()
    # Una pieza hereda la marca del objeto al que pertenece; un recurso no lleva ninguna.
    buscador.abrir(_id(catalogo, "Ferrite"))
    ficha = buscador.ficha.toPlainText()
    assert "Dominado" not in ficha and "Sin dominar" not in ficha and "Maestria" not in ficha


def test_estado_con_padre_sube_a_la_pieza(usuario, catalogo):
    from farmadex.ui.maestria import estado_con_padre, texto_maestria

    P.importar(RUTA_PERFIL, usuario, catalogo)
    pieza = catalogo.execute(
        "SELECT id FROM items WHERE nombre_en = 'Systems' AND padre_id IS NOT NULL LIMIT 1"
    ).fetchone()
    assert pieza, "el fixture de Ash Prime trae sus piezas"
    estado = estado_con_padre(usuario, catalogo, pieza[0])
    # Ash Prime no esta en el perfil: la pieza sale como 'sin dominar', no como 'no aplica'.
    assert estado.estado == P.SIN_TOCAR
    assert texto_maestria(estado) == "Sin dominar"
