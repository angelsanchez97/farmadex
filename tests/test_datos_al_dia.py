"""El aviso "Datos del juego" de Ajustes: distinguir "nos falta algo por bajar" de "DE no
ha publicado nada mas nuevo desde el parche".

Lo reporto el usuario con captura: el recuadro decia siempre, en naranja, que los datos
iban por detras del juego (build del 19/08, tablas de drops del 25/06), cuando esas tablas
eran las ultimas que DE habia publicado. Como DE puede pasar meses sin tocarlas, el aviso
se quedaba fijo y dejaba de significar nada.
"""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from farmadex.datos import descargas, indice
from farmadex.datos.descargas import EstadoDatos, fuentes_pendientes

ATRASADAS = [("tablas de drops", "2026-06-25")]


def test_estado_sabe_si_lo_descargado_es_lo_ultimo_publicado():
    sin_comprobar = EstadoDatos(drops_hash="abc")
    assert sin_comprobar.al_dia_con_lo_publicado("tablas de drops") is None
    al_dia = EstadoDatos(drops_hash="abc", publicado_drops_hash="abc")
    assert al_dia.al_dia_con_lo_publicado("tablas de drops") is True
    atrasado = EstadoDatos(drops_hash="abc", publicado_drops_hash="def")
    assert atrasado.al_dia_con_lo_publicado("tablas de drops") is False
    assert EstadoDatos().al_dia_con_lo_publicado("otra cosa") is None

    # Solo queda pendiente lo que tiene algo mas nuevo publicado (o no se ha podido mirar).
    assert fuentes_pendientes(al_dia, ATRASADAS) == []
    assert fuentes_pendientes(atrasado, ATRASADAS) == ATRASADAS
    assert fuentes_pendientes(sin_comprobar, ATRASADAS) == ATRASADAS


def test_texto_del_aviso_en_los_dos_casos():
    build = date(2026, 8, 19)
    # (a) hay algo publicado que no tenemos: es cosa nuestra, en tono de aviso siempre.
    texto, aviso = indice.texto_desfase(ATRASADAS, ATRASADAS, "2026.08.19.11.06", build, reciente=False)
    assert aviso is True
    assert "van por detras" in texto and "2026-06-25" in texto
    # (b) tenemos lo ultimo publicado: no suena a fallo, y pasado el parche va en tono neutro.
    texto, aviso = indice.texto_desfase(ATRASADAS, [], "2026.08.19.11.06", build, reciente=False)
    assert aviso is False
    assert "van por detras" not in texto
    assert "lo mas reciente" in texto and "2026-06-25" in texto and "2026-08-19" in texto
    # (b) los dias siguientes al parche si se avisa: puede faltar contenido de verdad.
    _, aviso = indice.texto_desfase(ATRASADAS, [], "2026.08.19.11.06", build, reciente=True)
    assert aviso is True


def test_comprobar_la_version_publicada_la_deja_apuntada_sin_otra_peticion(tmp_path, monkeypatch):
    monkeypatch.setattr(descargas, "RUTA_ESTADO_DATOS", tmp_path / "estado_datos.json")
    monkeypatch.setattr(descargas, "crear_carpetas", lambda: None)
    peticiones = []

    def servidor(peticion):
        peticiones.append(str(peticion.url))
        if peticion.url.path.endswith("info.json"):
            return httpx.Response(200, json={"hash": "h-publicado", "modified": "1782419611000"})
        return httpx.Response(200, json=[{"sha": "s-publicado", "commit": {"committer": {"date": "2026-09-19T04:35:20Z"}}}])

    cliente = httpx.Client(transport=httpx.MockTransport(servidor))
    d = descargas.Descargador(cliente=cliente)
    d.estado.drops_hash, d.estado.items_sha = "h-publicado", "s-viejo"
    assert d.version_drops()[0] == "h-publicado"
    assert d.version_items()[0] == "s-publicado"
    d.cerrar()

    guardado = json.loads((tmp_path / "estado_datos.json").read_text(encoding="utf-8"))
    assert guardado["publicado_drops_hash"] == "h-publicado"
    assert guardado["publicado_items_sha"] == "s-publicado"
    assert guardado["comprobado_en"]
    # Ajustes lo lee del fichero: las tablas de drops estan al dia, el catalogo no.
    estado = EstadoDatos.cargar()
    assert estado.al_dia_con_lo_publicado("tablas de drops") is True
    assert estado.al_dia_con_lo_publicado("catalogo de objetos") is False
    assert len(peticiones) == 2


def test_el_aviso_de_ajustes_cambia_de_color_segun_el_tono(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from farmadex import config, idiomas
    from farmadex.ui.pestana_ajustes import PestanaAjustes
    from farmadex.ui.widgets import PALETA

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    ajustes = PestanaAjustes()
    ajustes.ir_a("datos")  # Ajustes va por secciones: el aviso vive en Datos del juego
    ajustes.avisar_parche("van por detras", aviso=True)
    assert PALETA["aviso"] in ajustes.aviso_parche.styleSheet()
    ajustes.avisar_parche("tienes lo ultimo publicado", aviso=False)
    assert PALETA["suave"] in ajustes.aviso_parche.styleSheet()
    assert ajustes.aviso_parche.isVisibleTo(ajustes)
    ajustes.repintar()  # el cambio de tema no devuelve el naranja
    assert PALETA["suave"] in ajustes.aviso_parche.styleSheet()


def test_las_claves_nuevas_estan_en_los_cuatro_catalogos():
    from farmadex.idiomas import dir_catalogos

    texto, _ = indice.texto_desfase(ATRASADAS, [], "x", date(2026, 8, 19), reciente=False)
    clave = ("Tienes lo mas reciente que han publicado WFCD y DE ({detalle}). El juego se actualizo "
             "despues ({fecha_build}); si ese parche cambio algo, aparecera cuando publiquen sus tablas.")
    assert texto.startswith("Tienes lo mas reciente")
    for codigo in ("en", "fr", "de", "pt"):
        catalogo = json.loads((dir_catalogos() / f"{codigo}.json").read_text(encoding="utf-8"))
        assert clave in catalogo, codigo
