"""Actualizar desde la app sustituye la version anterior sin dejar restos ni copias.

- El instalador de la carpeta de compilaciones, con Farmadex instalado, va en silencio
  y en modo actualizacion (espera, sustituye, vuelve a abrir), como el descargado.
- Ese instalador no es nuestro: no se borra al acabar (los descargados si).
"""

from __future__ import annotations

import json

from farmadex import VERSION
from farmadex.actualizador import instalacion, local
from farmadex.actualizador.app import Version


def test_con_farmadex_instalado_el_instalador_local_va_en_silencio(tmp_path, monkeypatch):
    setup = tmp_path / "Farmadex-9.9.9-setup.exe"
    setup.write_bytes(b"x")
    llamadas = []
    monkeypatch.setattr(
        instalacion, "instalar_silencioso", lambda ruta, etiqueta, **k: llamadas.append((ruta, etiqueta, k)) or True
    )
    monkeypatch.setattr(local.subprocess, "Popen", lambda *a, **k: llamadas.append("asistente"))
    assert local.instalar(Version(etiqueta="9.9.9", url=str(setup), notas=""), silencioso=True)
    assert llamadas == [(setup, "9.9.9", {"borrar_al_acabar": False})]


def test_desde_la_portable_o_el_codigo_se_abre_el_asistente(tmp_path, monkeypatch):
    setup = tmp_path / "Farmadex-9.9.9-setup.exe"
    setup.write_bytes(b"x")
    llamadas = []
    monkeypatch.setattr(instalacion, "instalar_silencioso", lambda *a, **k: llamadas.append("silencio"))
    monkeypatch.setattr(local.subprocess, "Popen", lambda orden, **k: llamadas.append(orden))
    monkeypatch.setattr(instalacion, "es_instalacion_por_instalador", lambda *a, **k: False)
    assert local.instalar(Version(etiqueta="9.9.9", url=str(setup), notas=""))
    assert llamadas == [[str(setup)]]


def test_el_instalador_local_no_se_borra_al_acabar(tmp_path, monkeypatch):
    monkeypatch.setattr(instalacion, "DIR_LOGS", tmp_path / "logs")
    monkeypatch.setattr(instalacion, "RUTA_PENDIENTE", tmp_path / "pendiente.json")
    monkeypatch.setattr(instalacion, "RUTA_FALLIDA", tmp_path / "fallida.json")
    monkeypatch.setattr(instalacion.subprocess, "Popen", lambda orden, **k: None)
    setup = tmp_path / f"Farmadex-{VERSION}-setup.exe"
    setup.write_bytes(b"x")
    assert instalacion.instalar_silencioso(setup, VERSION, ejecutable_actual=tmp_path / "F.exe", borrar_al_acabar=False)
    assert json.loads((tmp_path / "pendiente.json").read_text())["borrar_setup"] is False
    # Siguiente arranque: ya es esa version. El setup de la carpeta sigue ahi.
    assert instalacion.resultado_instalacion_anterior() == ("instalada", VERSION)
    assert setup.exists()


def test_el_descargado_si_se_borra(tmp_path, monkeypatch):
    monkeypatch.setattr(instalacion, "DIR_LOGS", tmp_path / "logs")
    monkeypatch.setattr(instalacion, "RUTA_PENDIENTE", tmp_path / "pendiente.json")
    monkeypatch.setattr(instalacion, "RUTA_FALLIDA", tmp_path / "fallida.json")
    monkeypatch.setattr(instalacion.subprocess, "Popen", lambda orden, **k: None)
    setup = tmp_path / f"Farmadex-{VERSION}-setup.exe"
    setup.write_bytes(b"x")
    assert instalacion.instalar_silencioso(setup, VERSION, ejecutable_actual=tmp_path / "F.exe")
    assert instalacion.resultado_instalacion_anterior() == ("instalada", VERSION)
    assert not setup.exists()
