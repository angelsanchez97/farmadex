"""Relleno de las filas de fuentes segun lo rapido que es conseguir el objeto ahi."""

import pytest


def test_escala_logaritmica_rapido_lleno_lento_minimo():
    from farmadex.ui import relleno_filas as r

    tiempos = [10, 19, 70, 192, 708]
    ref = r.escala(tiempos + [None])
    assert ref == (10, 708)
    valores = [r.fraccion(m, ref) for m in tiempos]
    assert valores[0] == pytest.approx(r.RELLENO_MAX)
    assert valores[-1] == pytest.approx(r.RELLENO_MIN)
    assert valores == sorted(valores, reverse=True)
    # Logaritmica, no lineal: 70 min frente a 12 h sigue ocupando mas de media fila.
    assert valores[2] > 0.5


def test_sin_estimacion_no_lleva_relleno():
    from farmadex.ui import relleno_filas as r

    ref = r.escala([10, 70])
    assert r.fraccion(None, ref) is None
    assert r.marca(None) == ""
    assert r.escala([None, None]) is None


def test_diez_minutos_frente_a_setenta_se_distinguen():
    from farmadex.ui import relleno_filas as r

    ref = r.escala([10, 70])
    rapido, lento = r.fraccion(10, ref), r.fraccion(70, ref)
    assert rapido - lento > 0.5


def test_tiempos_parecidos_no_se_estiran_de_lleno_a_vacio():
    from farmadex.ui import relleno_filas as r

    ref = r.escala([30, 35])
    assert r.fraccion(35, ref) > 0.85


def test_la_ficha_pinta_el_relleno_repartido_por_la_fila():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGradient, QTextCursor
    from PySide6.QtWidgets import QApplication, QTextBrowser

    from farmadex.ui import relleno_filas as r

    app = QApplication.instance() or QApplication([])
    vista = QTextBrowser()
    vista.resize(700, 200)
    r.RellenoFilas(vista)
    fila = ("<tr><td width='6' style='background:#f00'></td><td><a name='{m}'><b>{n}</b></a></td>"
            "<td>Rotacion C</td><td align='right'>12%</td><td align='right'>~10 min</td></tr>")
    vista.setHtml(
        "<table width='100%' cellspacing='0' cellpadding='6'>"
        + fila.format(m=r.marca(0.97), n="Rapida") + fila.format(m=r.marca(0.08), n="Lenta")
        + "<tr><td width='6'></td><td><b>Sin estimacion</b></td><td></td><td></td><td></td></tr></table>"
    )
    vista.show()
    app.processEvents()
    app.processEvents()
    tabla = QTextCursor(vista.document().findBlockByNumber(1)).currentTable()
    assert tabla is not None

    def fondo(f, c):
        return tabla.cellAt(f, c).format().background()

    # La franja de rareza conserva su color.
    assert fondo(0, 0).color().name() == "#ff0000"
    # Rapida: casi toda la fila; la primera celda entera y la ultima cortada.
    assert fondo(0, 1).gradient() is None and fondo(0, 1).style() != Qt.NoBrush
    assert fondo(0, 4).gradient().coordinateMode() == QGradient.ObjectBoundingMode
    # Lenta: solo la primera celda, cortada; el resto sin relleno.
    assert fondo(1, 1).gradient() is not None
    assert fondo(1, 4).style() == Qt.NoBrush
    # Sin estimacion: nada.
    assert all(fondo(2, c).style() == Qt.NoBrush for c in range(1, 5))
    vista.close()


def test_ficha_larga_de_misiones_parecidas_sale_rellena_en_el_acto(monkeypatch):
    """Hornet Strike: 25 misiones entre 1,6 h y 2,1 h debajo de un 'Por donde empezar'.

    El relleno se aplicaba solo con un temporizador; con una ficha larga no llegaba a
    disparar antes de pintarse y la tabla salia sin relleno ninguno.
    """
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import QApplication

    import farmadex.ui.pestana_buscador as pb
    from farmadex.ui import relleno_filas as r

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(pb, "_glosa", lambda con, dominio, en: en or "")
    monkeypatch.setattr(pb, "nombre_bonito", lambda con, texto: texto)
    base = {"jefe": False, "nodo_en": "", "recurso_planeta": False, "rotacion": "C", "etapa": None,
            "standing": None, "probabilidad_enemigo": None, "rareza": "Rare", "motivo": None}
    minutos = [96] + [108] * 8 + [114] * 5 + [120] * 5 + [126] * 6
    grupo = [dict(base, origen_texto=f"Nodo {i} - Espionaje", probabilidad=8.6, minutos_medios=m)
             for i, m in enumerate(minutos)]

    pestana = pb.PestanaBuscador()
    pestana.resize(1100, 700)
    pestana.show()
    relleno_previo = "<p>" + "Texto de cabecera largo. " * 400 + "</p>"
    pestana._poner_ficha(relleno_previo + pestana._tabla_fuentes(grupo, r.escala([96, 126])))

    documento = pestana.ficha.document()
    bloque = documento.begin()
    tabla = None
    while bloque.isValid() and tabla is None:
        tabla = QTextCursor(bloque).currentTable()
        bloque = bloque.next()
    assert tabla is not None and tabla.rows() == len(minutos)
    for fila in range(tabla.rows()):
        # La primera celda de texto va rellena en todas las filas (todas pasan del 80 %).
        assert tabla.cellAt(fila, 1).format().background().style() != Qt.NoBrush, fila
    valores = [r.fraccion(m, r.escala(minutos)) for m in minutos]
    assert min(valores) > 0.8 and max(valores) == pytest.approx(r.RELLENO_MAX)
    pestana.close()
