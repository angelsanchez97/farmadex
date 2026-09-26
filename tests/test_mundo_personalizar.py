"""Pestana Mundo: personalizar (bloques, facciones, disposicion), texto copiable,
recompensas que abren su ficha y avisos de Windows que no se repiten."""

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.online import avisos_mundo  # noqa: E402
from farmadex.online import worldstate as ws  # noqa: E402
from farmadex.ui import pestana_mundo  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def config(tmp_path, monkeypatch):
    from farmadex import config as modulo

    monkeypatch.setattr(modulo, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    return modulo


def _en(minutos):
    return datetime.now(timezone.utc) + timedelta(minutes=minutos)


def _mundo():
    F = ws.Fisura
    return ws.Mundo(
        momento=datetime.now(timezone.utc),
        fisuras=[
            F("Meso", "Hydron, Sedna", "Cascada del Vacio", "Grineer", _en(40), modo="Void Cascade", faccion="Grineer"),
            F("Neo", "Xini, Eris", "Intercepcion", "Infestados", _en(60), modo="Interception", faccion="Infested"),
            F("Axi", "Ose, Europa", "Captura", "Corpus", _en(30), modo="Capture", faccion="Corpus"),
        ],
        ciclos=[
            ws.Ciclo("Tierra", "dia", _en(30), clave="earthCycle", estado_en="day"),
            ws.Ciclo("Cetus", "noche", _en(30), clave="cetusCycle", estado_en="night"),
            ws.Ciclo("Duviri", "alegria", _en(30), clave="duviriCycle", estado_en="joy"),
        ],
        invasiones=[ws.Invasion("Selkie, Sedna", "Asedio", "Corpus", "Grineer", "x", 40, objetos=[
            ws.ObjetoPremio("Orokin Catalyst Blueprint", 1, item_id=77, nombre_es="Plano de Catalizador Orokin"),
            ws.ObjetoPremio("Wraith Twin Vipers Receiver", 1),
        ])],
        sortie=[ws.Recompensa("Hyf - Defensa", _en(200))],
    )


def _textos(seccion) -> list[str]:
    return [seccion.caja.itemAt(i).widget().text() for i in range(seccion.caja.count())
            if isinstance(seccion.caja.itemAt(i).widget(), QLabel)]


def _pestana(**kw):
    pestana = pestana_mundo.PestanaMundo(**kw)
    pestana.actualizar(_mundo())
    return pestana


def test_el_texto_se_puede_seleccionar_y_copiar(app, config):
    pestana = _pestana()
    etiqueta = pestana.tarjetas["fisuras"].caja.itemAt(0).widget()
    assert etiqueta.textInteractionFlags() & Qt.TextSelectableByMouse
    assert etiqueta.textInteractionFlags() & Qt.LinksAccessibleByMouse


def test_duviri_va_en_su_linea_alineada_a_la_izquierda(app, config):
    pestana = _pestana(diseno="lista")
    lineas = _textos(pestana.tarjetas["ahora"])
    assert any(texto.startswith("<b>Duviri</b>") for texto in lineas)
    etiqueta = next(pestana.tarjetas["ahora"].caja.itemAt(i).widget()
                    for i in range(pestana.tarjetas["ahora"].caja.count())
                    if isinstance(pestana.tarjetas["ahora"].caja.itemAt(i).widget(), QLabel))
    assert etiqueta.alignment() & Qt.AlignLeft


def test_facciones_color_y_filtro_que_se_recuerda(app, config):
    pestana = _pestana()
    texto = " ".join(_textos(pestana.tarjetas["fisuras"]))
    assert pestana_mundo.COLORES_FACCION["grineer"] in texto
    assert pestana_mundo.COLORES_FACCION["corpus"] in texto
    pestana.acciones_faccion["corpus"].setChecked(True)
    textos = _textos(pestana.tarjetas["fisuras"])
    assert len(textos) == 1 and "Ose, Europa" in textos[0]
    assert pestana.filtro_faccion.text() == "Facciones: 1"
    assert config.cargar()["mundo_facciones"] == ["corpus"]
    # Otra pestana (otra sesion) sale con el mismo filtro.
    otra = _pestana()
    assert len(_textos(otra.tarjetas["fisuras"])) == 1
    otra._todas_las_facciones()
    assert len(_textos(otra.tarjetas["fisuras"])) == 3


def test_esconder_bloques_desde_personalizar(app, config):
    pestana = _pestana()
    assert not pestana.tarjetas["sortie"].isHidden()
    pestana.boton_personalizar.setChecked(True)
    assert pestana.paginas.currentWidget() is pestana.pagina_ajustes
    pestana.pagina_ajustes.casillas_secciones["sortie"].setChecked(False)
    assert pestana.tarjetas["sortie"].isHidden()
    assert config.cargar()["mundo_secciones_ocultas"] == ["sortie"]
    # Sigue escondido despues de repintar con datos nuevos.
    pestana.actualizar(_mundo())
    assert pestana.tarjetas["sortie"].isHidden()
    pestana.pagina_ajustes.casillas_secciones["sortie"].setChecked(True)
    assert not pestana.tarjetas["sortie"].isHidden()
    pestana.pagina_ajustes.volver.emit()
    assert pestana.paginas.currentWidget() is pestana.desplazable


def test_lista_o_tablero_se_elige_en_la_pestana(app, config):
    pestana = _pestana(diseno="lista")
    cambios = []
    pestana.diseno_cambiado.connect(cambios.append)
    pestana.selector_diseno.setCurrentIndex(pestana.selector_diseno.findData("tablero"))
    assert pestana.diseno == "tablero" and cambios == ["tablero"]
    assert config.cargar()["diseno_mundo"] == "tablero"
    assert pestana.tarjetas["ahora"].isHidden() and not pestana.tarjetas["ciclos"].isHidden()
    assert len(_textos(pestana.tarjetas["fisuras"])) >= 3  # se repinta con los mismos datos
    # Sin decirle nada, la siguiente sale como se dejo.
    assert pestana_mundo.PestanaMundo().diseno == "tablero"


def test_las_recompensas_abren_su_ficha_o_se_buscan(app, config):
    pestana = _pestana()
    pestana._plegadas["invasiones"] = False
    (linea,) = _textos(pestana.tarjetas["invasiones"])
    assert "href='item:77'" in linea and "Plano de Catalizador Orokin" in linea
    assert "href='buscar:Wraith%20Twin%20Vipers%20Receiver'" in linea
    abiertos, buscados = [], []
    pestana.abrir_item.connect(abiertos.append)
    pestana.buscar_texto.connect(buscados.append)
    pestana.tarjetas["invasiones"]._activar("item:77")
    pestana.tarjetas["invasiones"]._activar("buscar:Wraith%20Twin%20Vipers%20Receiver")
    assert abiertos == [77] and buscados == ["Wraith Twin Vipers Receiver"]


def test_los_avisos_salen_una_vez_y_solo_si_se_piden(app, config):
    pestana = pestana_mundo.PestanaMundo()
    avisos = []
    pestana.aviso_windows.connect(avisos.append)
    pestana.actualizar(_mundo())
    assert avisos == []  # todo apagado por defecto
    datos = config.cargar()
    datos[avisos_mundo.CLAVE_CONFIG] = {"fisuras": True, "fisuras_tipos": ["Void Cascade"], "noche_cetus": True}
    config.guardar(datos)
    pestana.actualizar(_mundo())
    assert len(avisos) == 1
    assert "Cascada del Vacío en Hydron, Sedna" in avisos[0] and "Cetus" in avisos[0]
    pestana.actualizar(_mundo())
    assert len(avisos) == 1  # el mismo mundo otra vez: nada
    # Tampoco al abrir Farmadex de nuevo.
    otra = pestana_mundo.PestanaMundo()
    otra.aviso_windows.connect(avisos.append)
    otra.actualizar(_mundo())
    assert len(avisos) == 1


def test_con_datos_viejos_no_se_avisa(app, config):
    datos = config.cargar()
    datos[avisos_mundo.CLAVE_CONFIG] = {"noche_cetus": True}
    config.guardar(datos)
    pestana = pestana_mundo.PestanaMundo()
    avisos = []
    pestana.aviso_windows.connect(avisos.append)
    mundo = _mundo()
    mundo.momento = datetime.now(timezone.utc) - timedelta(hours=2)
    pestana.actualizar(mundo)
    assert avisos == []


def test_personalizar_guarda_los_avisos_y_prueba(app, config):
    pestana = _pestana()
    panel = pestana.pagina_ajustes
    assert not panel.caja_fisuras.isEnabled()
    panel.casillas["fisuras"].setChecked(True)
    assert panel.caja_fisuras.isEnabled()
    panel.tipos_fisura["Void Cascade"].setChecked(True)
    panel.eras["Meso"].setChecked(True)
    prefs = config.cargar()[avisos_mundo.CLAVE_CONFIG]
    assert prefs["fisuras"] and prefs["fisuras_tipos"] == ["Void Cascade"] and prefs["fisuras_eras"] == ["Meso"]
    avisos = []
    pestana.aviso_windows.connect(avisos.append)
    panel.boton_probar.click()
    assert len(avisos) == 1
    # Al volver a Mundo se aplica lo marcado: la Cascada abierta avisa ya.
    pestana.boton_personalizar.setChecked(True)
    pestana.boton_personalizar.setChecked(False)
    assert len(avisos) == 2 and "Cascada" in avisos[1]


def test_baro_marca_lo_que_esta_en_objetivos(app, config, tmp_path):
    from farmadex.estado import objetivos as estado_objetivos
    from farmadex.estado import usuario_db

    usuario = usuario_db.conectar(tmp_path / "usuario.sqlite")
    estado_objetivos.anadir(usuario, "/Mods/PrimedFlow", "Flujo Prime")
    pestana = pestana_mundo.PestanaMundo()
    pestana.usuario = usuario
    mundo = _mundo()
    mundo.baro_detalle = ws.Baro("Baro Ki'Teer", "Larunda", True, _en(-10), _en(900), [
        ws.ObjetoBaro("Primed Flow", "/Mods/PrimedFlow", 350, 1000, 5, "Flujo Prime"),
        ws.ObjetoBaro("Otra cosa", "/Otra", 100, 1000, 6, "Otra cosa"),
    ])
    pestana.actualizar(mundo)
    assert [o.nombre for o in mundo.baro_detalle.objetivos()] == ["Primed Flow"]
