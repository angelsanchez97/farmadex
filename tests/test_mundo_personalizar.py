"""Pestana Mundo: personalizar (bloques, facciones), texto copiable, recompensas que abren
su ficha y avisos de Windows que no se repiten."""

import os
import re
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


def _pestana(**kw):
    pestana = pestana_mundo.PestanaMundo(**kw)
    pestana.actualizar(_mundo())
    return pestana


def _tarjetas(pestana):
    return [c for c in pestana.fisuras_todo.findChildren(pestana_mundo.TarjetaFisura) if c.parent() is not None]


def test_el_texto_se_puede_seleccionar_y_copiar(app, config):
    pestana = _pestana()
    etiquetas = [e for bloque in (pestana.fisuras_todo, pestana.invasiones_todo, pestana.ciclos, pestana.hoy)
                 for e in bloque.findChildren(QLabel) if e.parent() is not None and e.text()]
    assert etiquetas
    tarjeta = _tarjetas(pestana)[0]
    for etiqueta in (tarjeta.nombre, tarjeta.detalle, tarjeta.abajo):
        assert etiqueta.textInteractionFlags() & Qt.TextSelectableByMouse
        assert etiqueta.textInteractionFlags() & Qt.LinksAccessibleByMouse
    premios = next(e for e in pestana.invasiones_todo.findChildren(QLabel) if "href='item:77'" in e.text())
    assert premios.textInteractionFlags() & Qt.TextSelectableByMouse


def test_facciones_color_y_filtro_que_se_recuerda(app, config):
    pestana = _pestana()
    colores = {c.color_barra for c in _tarjetas(pestana)}
    assert pestana_mundo.COLORES_FACCION["grineer"] in colores
    assert pestana_mundo.COLORES_FACCION["corpus"] in colores
    pestana.acciones_faccion["corpus"].setChecked(True)
    assert [c.fisura.nodo for c in _tarjetas(pestana)] == ["Ose, Europa"]
    assert pestana.filtro_faccion.text() == "Facciones: 1"
    assert pestana.fisuras_completo.boton_facciones.text() == "Facciones: 1"
    assert config.cargar()["mundo_facciones"] == ["corpus"]
    # Otra pestana (otra sesion) sale con el mismo filtro.
    otra = _pestana()
    assert len(_tarjetas(otra)) == 1
    otra._todas_las_facciones()
    assert len(_tarjetas(otra)) == 3


def test_lo_elegido_sobrevive_a_cerrar_farmadex(app, config):
    """Las claves de Mundo tienen que estar en config.POR_DEFECTO: si no, `cargar` las tira."""
    pestana = _pestana()
    pestana.acciones_faccion["corpus"].setChecked(True)
    pestana.botones_modo["acero"].setChecked(True)
    pestana.boton_personalizar.setChecked(True)
    pestana.pagina_ajustes.casillas_secciones["ciclos"].setChecked(False)
    pestana.pagina_ajustes.casillas["baro"].setChecked(True)
    releida = config.cargar(recargar=True)
    assert releida["mundo_facciones"] == ["corpus"]
    assert releida["mundo_modos_fisura"] == ["normal", "acero"]
    assert releida["mundo_secciones_ocultas"] == ["ciclos"]
    assert releida[avisos_mundo.CLAVE_CONFIG]["baro"] is True


def test_esconder_bloques_desde_personalizar(app, config):
    pestana = _pestana()
    assert not pestana.sortie.isHidden()
    pestana.boton_personalizar.setChecked(True)
    assert pestana.paginas.currentWidget() is pestana.pagina_ajustes
    assert pestana.boton_personalizar.isHidden()  # dentro, el boton es "Volver a Mundo"
    pestana.pagina_ajustes.casillas_secciones["sortie"].setChecked(False)
    assert pestana.sortie.isHidden()
    assert config.cargar()["mundo_secciones_ocultas"] == ["sortie"]
    # En HOY desaparecen la incursion y los arcontes, pero no el resto.
    textos = " ".join(e.text() for e in pestana.hoy.findChildren(QLabel) if e.parent() is not None).upper()
    assert "INCURSION" not in textos and "ARCONTES" not in textos
    assert "ARBITRAJE" in textos and "ONDA NOCTURNA" in textos
    # Sigue escondido despues de repintar con datos nuevos.
    pestana.actualizar(_mundo())
    assert pestana.sortie.isHidden()
    pestana.pagina_ajustes.casillas_secciones["sortie"].setChecked(True)
    assert not pestana.sortie.isHidden()
    pestana.pagina_ajustes.volver.emit()
    assert pestana.paginas.currentWidget() is pestana.vistas
    assert not pestana.boton_personalizar.isHidden()


def test_esconder_un_tipo_de_fisura_quita_su_boton(app, config):
    pestana = _pestana()
    pestana.pagina_ajustes.casillas_secciones["tormentas"].setChecked(False)
    assert pestana.botones_modo["tormenta"].isHidden()
    assert not pestana.botones_modo["acero"].isHidden()
    for clave in ("fisuras", "acero"):
        pestana.pagina_ajustes.casillas_secciones[clave].setChecked(False)
    assert pestana.fisuras_todo.isHidden() and pestana.fisuras_completo.isHidden()


def test_una_sub_pestana_saca_de_personalizar(app, config):
    pestana = _pestana()
    pestana.boton_personalizar.setChecked(True)
    pestana.subpestanas.cambiada.emit("eventos")
    assert pestana.paginas.currentWidget() is pestana.vistas and pestana.diseno == "eventos"


def test_las_recompensas_abren_su_ficha_o_se_buscan(app, config):
    pestana = _pestana()
    (linea,) = [e.text() for e in pestana.invasiones_todo.findChildren(QLabel)
                if e.parent() is not None and "href=" in e.text()]
    assert "href='item:77'" in linea and "Plano de Catalizador Orokin" in linea
    assert "href='buscar:Wraith%20Twin%20Vipers%20Receiver'" in linea
    abiertos, buscados = [], []
    pestana.abrir_item.connect(abiertos.append)
    pestana.buscar_texto.connect(buscados.append)
    pestana.invasiones_todo._activar("item:77")
    pestana.invasiones_todo._activar("buscar:Wraith%20Twin%20Vipers%20Receiver")
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
    panel.dificultad.botones["normal"].setChecked(True)
    prefs = config.cargar()[avisos_mundo.CLAVE_CONFIG]
    assert prefs["fisuras"] and prefs["fisuras_tipos"] == ["Void Cascade"] and prefs["fisuras_eras"] == ["Meso"]
    assert prefs["fisuras_dificultad"] == "normal"
    avisos = []
    pestana.aviso_windows.connect(avisos.append)
    panel.boton_probar.click()
    assert len(avisos) == 1
    # Al volver a Mundo se aplica lo marcado: la Cascada abierta avisa ya.
    pestana.boton_personalizar.setChecked(True)
    pestana.boton_personalizar.setChecked(False)
    assert len(avisos) == 2 and "Cascada" in avisos[1]


def test_las_palabras_de_las_invasiones_salen_en_su_aviso(app, config):
    panel = _pestana().pagina_ajustes
    assert panel.filas_aviso["invasiones"].texto.texto_completo() == "Invasiones con: Orokin, Forma, Exilus"
    panel.palabras.setText("Nitain;  Forma")
    panel.palabras.editingFinished.emit()
    assert panel.filas_aviso["invasiones"].texto.texto_completo() == "Invasiones con: Nitain, Forma"
    assert config.cargar()[avisos_mundo.CLAVE_CONFIG]["invasiones_palabras"] == "Nitain;  Forma"


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
    textos = " ".join(re.sub(r"<[^>]+>", "", e.text()) for e in pestana.baro_todo.findChildren(QLabel)
                      if e.parent() is not None)
    assert "Flujo Prime" in textos and "Otra cosa" not in textos
