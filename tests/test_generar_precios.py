"""Generador de la foto diaria de precios (herramientas/precios/generar.py), sin red."""

from __future__ import annotations

import gzip
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

RUTA = Path(__file__).resolve().parents[1] / "herramientas" / "precios" / "generar.py"
_spec = importlib.util.spec_from_file_location("generar_precios", RUTA)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

HOY = datetime(2026, 9, 30, tzinfo=timezone.utc)


def _orden(tipo, platino, rango=None, estado="ingame", cantidad=1, subtipo=None, visible=True):
    o = {"type": tipo, "platinum": platino, "quantity": cantidad, "visible": visible,
         "user": {"status": estado, "ingameName": "x"}}
    if rango is not None:
        o["rank"] = rango
    if subtipo:
        o["subtype"] = subtipo
    return o


def test_ordenes_solo_conectados_y_por_rango():
    ordenes = [
        _orden("sell", 300, 5, "offline"),       # desconectado: no cuenta
        _orden("sell", 120, 5), _orden("sell", 125, 5, "online"), _orden("sell", 140, 5),
        _orden("sell", 150, 5), _orden("sell", 160, 5), _orden("sell", 999, 5),
        _orden("sell", 8, 0, cantidad=70), _orden("buy", 90, 5), _orden("buy", 95, 5, "offline"),
        _orden("sell", 1, 5, visible=False),     # oculta: no cuenta
    ]
    r = gen.resumir_ordenes(ordenes)
    assert r["5"] == {"venta_min": 120, "venta_mediana": 140, "compra_max": 90,
                      "vendedores": 6, "compradores": 1, "cantidad_venta": 6}
    assert r["0"]["venta_min"] == 8 and r["0"]["compra_max"] is None and r["0"]["cantidad_venta"] == 70


def test_ordenes_con_subtipo_y_sin_rango():
    r = gen.resumir_ordenes([_orden("sell", 10, subtipo="intact"), _orden("sell", 30, subtipo="radiant"),
                             _orden("sell", 60), _orden("sell", 61)])
    assert r["|intact"]["venta_min"] == 10 and r["|radiant"]["venta_min"] == 30
    assert r[""]["venta_mediana"] == 60.5


def _fila(dia, vol, mn, mx, media, mediana, rango=None, subtipo=None):
    f = {"datetime": f"{dia}T00:00:00.000+00:00", "volume": vol, "min_price": mn, "max_price": mx,
         "avg_price": media, "median": mediana}
    if rango is not None:
        f["mod_rank"] = rango
    if subtipo:
        f["subtype"] = subtipo
    return f


def test_estadisticas_30_dias_por_rango():
    datos = {"payload": {"statistics_closed": {
        "90days": [
            _fila("2026-08-01", 50, 1, 999, 500, 500, 5),   # fuera de los 30 dias
            _fila("2026-09-10", 10, 100, 150, 120, 118, 5),
            _fila("2026-09-20", 30, 90, 170, 140, 138, 5),
            _fila("2026-09-21", 0, 1, 1, 1, 1, 5),           # sin ventas: no cuenta
            _fila("2026-09-29", 100, 3, 10, 7, 8, 0),
        ],
        "48hours": [{"volume": 4, "mod_rank": 5}, {"volume": 3, "mod_rank": 5}],
    }}}
    r = gen.resumir_estadisticas(datos, HOY)
    assert r["5"]["min_30d"] == 90 and r["5"]["max_30d"] == 170
    assert r["5"]["media_30d"] == 135 and r["5"]["volumen_30d"] == 40  # (120*10+140*30)/40
    assert r["5"]["mediana_30d"] == 138 and r["5"]["dias_30d"] == 2 and r["5"]["volumen_48h"] == 7
    assert r["0"]["volumen_30d"] == 100 and r["0"]["volumen_48h"] == 0


def test_combinar_y_validar(tmp_path):
    o = gen.resumir_ordenes([_orden("sell", 120, 5)])
    s = gen.resumir_estadisticas({"payload": {"statistics_closed": {
        "90days": [_fila("2026-09-20", 30, 90, 170, 140, 138, 5)]}}}, HOY)
    p = gen.combinar(o, s)
    assert len(p["5"]) == len(gen.CAMPOS)
    assert p["5"][gen.CAMPOS.index("venta_min")] == 120 and p["5"][gen.CAMPOS.index("volumen_30d")] == 30
    doc = {"formato": 1, "fecha": datetime.now(timezone.utc).isoformat(), "campos": gen.CAMPOS,
           "resumen": {"catalogo": 1, "con_estadisticas": 1},
           "objetos": {"arcane_energize": {"n": "Arcane Energize", "r": 5, "t": [], "p": p}}}
    ruta = tmp_path / "p.json.gz"
    ruta.write_bytes(gzip.compress(json.dumps(doc).encode()))
    assert gen.validar(ruta, completo=False) == []
    problemas = gen.validar(ruta)
    assert any("objetos" in x for x in problemas)  # uno solo no basta para publicar
    ruta.write_bytes(b"roto")
    assert gen.validar(ruta)
    vacio = {**doc, "objetos": {}}
    ruta.write_bytes(gzip.compress(json.dumps(vacio).encode()))
    assert gen.validar(ruta, completo=False)  # sin el testigo no se publica
