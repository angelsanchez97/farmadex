"""Historial de sesion: registro, resumen del dia y fichero para OBS."""

import json
import sqlite3
from datetime import date

import pytest

from farmadex.captura.comparador import Puntuacion, Veredicto
from farmadex.captura.reliquias import Recompensa
from farmadex.estado import historial, usuario_db


@pytest.fixture()
def usuario(tmp_path, monkeypatch):
    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    con = usuario_db.conectar(tmp_path / "usuario.sqlite")
    yield con
    con.close()


def _r(unico, nombre, valor=None, ducados=None, mejor=False, objetivo="", platino=None):
    return Recompensa(
        item_id=1, nombre=nombre, texto_ocr=nombre.upper(), caja=(0, 0, 1, 1),
        unique_name=unico, valor=valor, ducados=ducados, mejor=mejor, objetivo=objetivo, platino=platino,
    )


def test_migracion_desde_la_version_1_anade_columnas_sin_perder_filas(tmp_path, monkeypatch):
    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    ruta = tmp_path / "viejo.sqlite"
    viejo = sqlite3.connect(ruta)
    viejo.executescript(
        "CREATE TABLE meta (clave TEXT PRIMARY KEY, valor TEXT);"
        "INSERT INTO meta VALUES ('esquema_version', '1');"
        "CREATE TABLE historial_recompensas (id INTEGER PRIMARY KEY, leido_en TEXT NOT NULL, "
        "textos_ocr TEXT NOT NULL, items_json TEXT NOT NULL, elegido_unique_name TEXT);"
        "INSERT INTO historial_recompensas (leido_en, textos_ocr, items_json) VALUES "
        "('2026-09-19T20:00:00', 'X', '[]');"
    )
    viejo.commit()
    viejo.close()

    con = usuario_db.conectar(ruta)
    columnas = {f[1] for f in con.execute("PRAGMA table_info(historial_recompensas)")}
    assert {"mejor_unique_name", "valor_platino", "ducados"} <= columnas
    assert con.execute("SELECT COUNT(*) FROM historial_recompensas").fetchone()[0] == 1
    assert con.execute("SELECT valor FROM meta WHERE clave='esquema_version'").fetchone()[0] == "2"
    assert con.execute("SELECT COUNT(*) FROM historial_eventos").fetchone()[0] == 0
    con.close()


def test_registrar_lectura_guarda_la_mejor_y_su_valor(usuario):
    recompensas = [_r("/a", "Braton Barrel", valor=1.5, ducados=15), _r("/b", "Ash Systems", valor=45.0, ducados=100, mejor=True)]
    lectura_id = historial.registrar_lectura(usuario, recompensas, leido_en="2026-09-20T21:10:00")
    fila = usuario.execute(
        "SELECT mejor_unique_name, valor_platino, ducados, elegido_unique_name, items_json "
        "FROM historial_recompensas WHERE id = ?", (lectura_id,)
    ).fetchone()
    assert fila[:4] == ("/b", 45.0, 100, None)
    assert [i["nombre"] for i in json.loads(fila[4])] == ["Braton Barrel", "Ash Systems"]


def test_si_nadie_esta_marcada_se_usa_el_indice_del_veredicto(usuario):
    recompensas = [_r("/a", "A", valor=2.0), _r("/b", "B", valor=9.0)]
    v = Veredicto([Puntuacion(1, "A"), Puntuacion(1, "B")], mejor=1, seguro=True, motivo="")
    lectura_id = historial.registrar_lectura(usuario, recompensas, v)
    assert usuario.execute(
        "SELECT mejor_unique_name FROM historial_recompensas WHERE id = ?", (lectura_id,)
    ).fetchone()[0] == "/b"


def test_resumen_del_dia_cuenta_eventos_y_suma_valor(usuario):
    historial.registrar_evento(usuario, "reliquia_abierta", "2026-09-20T20:00:00")
    historial.registrar_evento(usuario, "reliquia_abierta", "2026-09-20T20:05:00")
    historial.registrar_evento(usuario, "mision_completada", "2026-09-20T20:04:00")
    historial.registrar_evento(usuario, "reliquia_abierta", "2026-09-19T20:00:00")  # ayer
    assert historial.registrar_evento(usuario, "reliquia_recompensas") is None  # no cuenta

    historial.registrar_lectura(
        usuario, [_r("/b", "Ash Systems", valor=45.0, ducados=100, mejor=True)], leido_en="2026-09-20T20:01:00"
    )
    historial.registrar_lectura(
        usuario, [_r("/b", "Ash Systems", valor=40.0, ducados=100, mejor=True, objetivo="0/1")],
        leido_en="2026-09-20T20:06:00",
    )
    historial.registrar_lectura(usuario, [_r("/c", "Forma", valor=None, mejor=True)], leido_en="2026-09-20T20:09:00")
    historial.registrar_lectura(usuario, [_r("/z", "Ayer", valor=99.0, mejor=True)], leido_en="2026-09-19T20:09:00")

    r = historial.resumen_dia(usuario, date(2026, 9, 20))
    assert r.reliquias_abiertas == 2 and r.misiones == 1 and r.lecturas == 3
    assert r.valor_platino == 85.0 and r.ducados == 200
    assert r.valor_estimado is True and r.sin_valorar == 1
    assert [(c.nombre, c.veces) for c in r.caidas] == [("Ash Systems", 2), ("Forma", 1)]
    assert r.caidas[0].valor == 85.0
    assert r.objetivos == ["Ash Systems"]
    assert r.ultima == "Forma" and r.ultima_hora == "20:09"


def test_sin_eventos_de_eelog_se_cuentan_las_lecturas(usuario):
    historial.registrar_lectura(usuario, [_r("/b", "X", valor=1.0, mejor=True)], leido_en="2026-09-20T20:01:00")
    assert historial.resumen_dia(usuario, date(2026, 9, 20)).reliquias_abiertas == 1


def test_marcar_elegida_quita_la_estimacion(usuario):
    lectura_id = historial.registrar_lectura(
        usuario,
        [_r("/a", "A", valor=1.5, ducados=15), _r("/b", "B", valor=45.0, ducados=100, mejor=True)],
        leido_en="2026-09-20T20:01:00",
    )
    assert historial.marcar_elegida(usuario, lectura_id, "/a")
    r = historial.resumen_dia(usuario, date(2026, 9, 20))
    assert r.valor_platino == 1.5 and r.ducados == 15 and r.valor_estimado is False
    assert not historial.marcar_elegida(usuario, 9999, "/a")


def test_plantilla_de_obs_y_escritura_atomica(usuario, tmp_path):
    historial.registrar_evento(usuario, "reliquia_abierta", "2026-09-20T20:00:00")
    historial.registrar_lectura(
        usuario, [_r("/b", "Ash Prime Systems", valor=45.4, ducados=100, mejor=True)], leido_en="2026-09-20T20:01:00"
    )
    r = historial.resumen_dia(usuario, date(2026, 9, 20))
    texto = historial.renderizar(r)
    assert texto == "Reliquias: 1 | Misiones: 0 | Valor: ~45p / 100 ducados | Ultima: Ash Prime Systems"

    ruta = tmp_path / "obs" / "sesion.txt"
    historial.exportar_obs(r, ruta, "{caidas} {estimado}{platino}p {desconocido}")
    assert ruta.read_text(encoding="utf-8") == "Ash Prime Systems ~45p {desconocido}"
    assert not ruta.with_suffix(".txt.tmp").exists()


def test_plantilla_rota_no_tira_la_exportacion(usuario):
    r = historial.resumen_dia(usuario, date(2026, 9, 20))
    assert historial.renderizar(r, "{reliquias") == historial.renderizar(r)


def test_sesion_enlaza_eventos_lecturas_y_exportacion(usuario, tmp_path):
    ruta = tmp_path / "obs.txt"
    sesion = historial.Sesion(usuario, ruta, "{reliquias}/{misiones}/{ultima}")
    sesion.evento("reliquia_abierta")
    sesion.evento("reliquia_recompensas")  # no cuenta ni reexporta
    assert ruta.read_text(encoding="utf-8") == "1/0/-"
    assert sesion.lectura([]) is None
    sesion.lectura([_r("/b", "Ash Systems", valor=45.0, mejor=True)])
    sesion.evento("mision_completada")
    assert ruta.read_text(encoding="utf-8") == "1/1/Ash Systems"
    assert "Reliquias abiertas: 1" in historial.texto_resumen(sesion.resumen())
