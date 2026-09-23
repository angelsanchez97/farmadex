"""Diagnostico de reliquias: veredictos claros por causa, e informe sin EE.log."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from farmadex import diagnostico
from farmadex.captura.pantalla import Region
from farmadex.diagnostico import AVISO, DATO, MAL, OK, guardar_informe, recoger
from farmadex.registro.eelog import EstadoEELog

AHORA = 1_800_000_000.0


def _textos(d, estado=None):
    return [l.texto for l in d.lineas if estado is None or l.estado == estado]


def _todo_bien(**cambios):
    base = dict(
        eelog=EstadoEELog(ruta="C:/x/EE.log", existe=True, tamano=4096, modificado=AHORA - 10,
                          ultima_lectura=AHORA - 5, lineas=120, eventos=2,
                          ultimo_evento="reliquia_recompensas", ultimo_evento_en=AHORA - 120),
        ruta_eelog_configurada="C:/x/EE.log", ruta_eelog_por_defecto="C:/x/EE.log",
        modo_pantalla="sin_bordes", juego=Region(0, 0, 2560, 1440), monitor_juego=Region(0, 0, 2560, 1440),
        motor_fallo=None, motor_cargado=True, config={"ocr_reliquias_auto": True, "estilo_recompensas": "etiquetas"},
        datos_listos=True, hay_indice=True, ultima_pantalla=AHORA - 60,
        ultima_lectura=(AHORA - 59, 4), ultima_pintada=(AHORA - 59, 4), ahora=AHORA,
    )
    base.update(cambios)
    return recoger(**base)


def test_con_todo_bien_no_hay_ningun_problema():
    d = _todo_bien()
    assert d.problemas == []
    assert any("EE.log encontrado" in t for t in _textos(d, OK))
    assert any("120 lineas" in t and "hace 5 s" in t for t in _textos(d, OK))
    assert any("reliquia_recompensas" in t and "hace 2 min" in t for t in _textos(d, OK))
    assert any("2560x1440" in t for t in _textos(d, OK))
    assert "[OK]" in d.texto() and "[MAL]" not in d.texto()


def test_sin_eelog_se_dice_donde_se_busco_y_donde_deberia_estar():
    d = _todo_bien(
        eelog=EstadoEELog(ruta="D:/copiado/EE.log", existe=False),
        ruta_eelog_configurada="D:/copiado/EE.log", ruta_eelog_por_defecto="C:/Users/x/AppData/Local/Warframe/EE.log",
    )
    [problema] = [t for t in _textos(d, MAL) if "EE.log" in t]
    assert "D:/copiado/EE.log" in problema and "C:/Users/x/AppData/Local/Warframe/EE.log" in problema


def test_eelog_que_no_se_puede_leer_y_juego_parado_se_distinguen():
    d = _todo_bien(eelog=EstadoEELog(ruta="C:/x/EE.log", existe=True, error="[Errno 13] Permission denied"))
    assert any("Permission denied" in t for t in _textos(d, MAL))
    d = _todo_bien(eelog=EstadoEELog(ruta="C:/x/EE.log", existe=True, tamano=10, modificado=AHORA - 3600 * 5))
    assert any("no ha escrito nada" in t and "hace 5 h" in t for t in _textos(d, AVISO))


def test_pantalla_completa_exclusiva_es_un_problema_con_el_arreglo_dicho():
    d = _todo_bien(modo_pantalla="exclusivo")
    [problema] = _textos(d, MAL)
    assert "exclusiva" in problema and "Ventana sin bordes" in problema


def test_motor_ocr_caido_lectura_apagada_y_datos_sin_descargar_son_problemas():
    d = _todo_bien(motor_fallo="ImportError: onnxruntime")
    assert any("onnxruntime" in t for t in _textos(d, MAL))
    d = _todo_bien(config={"ocr_reliquias_auto": False, "hotkey_reliquias": "Ctrl+Alt+R"})
    assert any("DESACTIVADA" in t and "Ctrl+Alt+R" in t for t in _textos(d, MAL))
    d = _todo_bien(datos_listos=False, hay_indice=False, eelog=None)
    assert any("No hay datos" in t for t in _textos(d, MAL))
    assert any("vigilancia de EE.log no ha arrancado" in t for t in _textos(d, MAL))


def test_se_distingue_no_leido_de_leido_pero_no_pintado():
    d = _todo_bien(ultima_lectura=None, ultima_pintada=None)
    assert any("no se leyo nada" in t for t in _textos(d, MAL))
    d = _todo_bien(ultima_lectura=(AHORA - 59, 0), ultima_pintada=None)
    assert any("no se reconocio ninguna" in t for t in _textos(d, MAL))
    d = _todo_bien(ultima_pintada=None)
    assert any("no se pintaron" in t for t in _textos(d, MAL))
    # Sin ninguna pantalla vista, no es un problema: es que aun no se abrio ninguna reliquia.
    d = _todo_bien(ultima_pantalla=None, ultima_lectura=None, ultima_pintada=None)
    assert d.problemas == [] and any("Ninguna pantalla" in t for t in _textos(d, DATO))


def test_monitores_escala_y_ventana_ausente_salen_como_dato():
    d = _todo_bien(monitores=2, escala=1.25, juego=None, monitor_juego=Region(2560, 0, 1920, 1080))
    assert any("2 monitores" in t and "1920x1080" in t for t in _textos(d, DATO))
    assert any("125%" in t for t in _textos(d, DATO))
    assert any("No se ve la ventana" in t for t in _textos(d, AVISO))


def test_el_html_lleva_color_por_veredicto_y_escapa_el_texto():
    d = _todo_bien(eelog=EstadoEELog(ruta="C:/a<b>/EE.log", existe=False))
    html = d.html({"ok": "#0f0", "mal": "#f00", "aviso": "#fa0", "dato": "#999"})
    assert 'color:#f00">[MAL]</span>' in html and "&lt;b&gt;" in html and "<b>" not in html


# --- informe -----------------------------------------------------------------------


@pytest.fixture()
def carpeta_datos(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "farmadex.log").write_text("linea de registro\n", encoding="utf-8")
    (logs / "farmadex.log.1").write_text("rotado\n", encoding="utf-8")
    (logs / "registro_errores.txt").write_text("fallo\n", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"tema": "orokin"}', encoding="utf-8")
    # Un EE.log copiado a la carpeta de logs por quien sea: NO puede entrar.
    (logs / "EE.log").write_text("correo@personal.com 1.2.3.4\n", encoding="utf-8")
    monkeypatch.setattr(diagnostico, "RUTA_LOG", logs / "farmadex.log")
    monkeypatch.setattr(diagnostico, "RUTA_ERRORES_REGISTRO", logs / "registro_errores.txt")
    monkeypatch.setattr(diagnostico, "RUTA_CONFIG", tmp_path / "config.json")
    return tmp_path


def test_el_informe_lleva_el_diagnostico_y_el_registro_pero_nunca_eelog(carpeta_datos, tmp_path):
    d = _todo_bien(modo_pantalla="exclusivo")
    destino = tmp_path / "Escritorio"
    ruta = guardar_informe(d, destino)
    assert ruta.parent == destino and ruta.name.startswith("Farmadex-diagnostico-") and ruta.suffix == ".zip"
    with zipfile.ZipFile(ruta) as z:
        nombres = set(z.namelist())
        assert {"diagnostico.txt", "farmadex.log", "farmadex.log.1", "registro_errores.txt", "config.json"} == nombres
        texto = z.read("diagnostico.txt").decode("utf-8")
        assert "[MAL]" in texto and "exclusiva" in texto and "no contiene EE.log" in texto
        for nombre in nombres:
            assert "correo@personal.com" not in z.read(nombre).decode("utf-8", "replace")


def test_el_informe_acepta_texto_suelto_y_crea_la_carpeta(carpeta_datos, tmp_path):
    ruta = guardar_informe("solo texto", tmp_path / "nueva" / "carpeta")
    with zipfile.ZipFile(ruta) as z:
        assert "solo texto" in z.read("diagnostico.txt").decode("utf-8")


def test_ficheros_prohibidos_no_dependen_de_mayusculas(carpeta_datos, monkeypatch):
    monkeypatch.setattr(diagnostico, "RUTA_LOG", carpeta_datos / "logs" / "EE.LOG")
    assert all(f.name.lower() != "ee.log" for f in diagnostico.ficheros_del_informe())


def test_la_carpeta_del_escritorio_existe_o_se_cae_a_la_de_datos():
    carpeta = diagnostico.carpeta_escritorio()
    assert isinstance(carpeta, Path) and (carpeta.is_dir() or carpeta == diagnostico.DIR_BASE)
