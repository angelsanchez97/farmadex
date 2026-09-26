"""Buscar en el diseno C: ficha en paneles, tira de rondas, pasos, barra de teclas y teclas."""

from __future__ import annotations

from urllib.parse import unquote

import pytest

pytest.importorskip("PySide6")


@pytest.fixture()
def aplicacion():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def buscador(indice_poblado, monkeypatch, aplicacion, tmp_path):
    from farmadex import config, idiomas
    from farmadex.datos import indice as modulo_indice
    from farmadex.ui.pestana_buscador import PestanaBuscador

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    con, _, _ = indice_poblado
    monkeypatch.setattr(modulo_indice, "conectar", lambda *a, **k: con)
    pestana = PestanaBuscador()
    pestana.habilitar(True)
    return pestana


def _buscar(pestana, texto: str) -> None:
    pestana.caja.setText(texto)
    pestana._temporizador.stop()
    pestana._buscar()


def _id(con, nombre_en: str) -> int:
    return con.execute("SELECT id FROM items WHERE nombre_en = ?", (nombre_en,)).fetchone()[0]


def _tecla(pestana, destino, clave, texto=""):
    """Manda una pulsacion a `destino` pasando por el filtro de teclas de la pagina."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    evento = QKeyEvent(QEvent.KeyPress, clave, Qt.NoModifier, texto)
    return pestana._teclas.eventFilter(destino, evento)


# -- ficha de mision ----------------------------------------------------------------------


def test_ficha_de_mision_con_cabecera_tira_y_paneles_por_rotacion(buscador):
    from farmadex.ui.estilo_c import PanelC
    from farmadex.ui.ficha_c import TiraRondas

    nodo = buscador.con.execute("SELECT id FROM nodos WHERE nombre_en = 'Hydron'").fetchone()[0]
    buscador.abrir_mision(f"nodo:{nodo}")
    texto = buscador.ficha.toPlainText()
    assert "HYDRON" in texto.upper() and "SEDNA" in texto and "QUÉ TE DAN Y CUÁNDO" in texto and "QUÉ HACER" in texto
    tiras = buscador.ficha.findChildren(TiraRondas)
    assert len(tiras) == 1
    # Defensa: A, A, B, C cada 3 oleadas, dos vueltas.
    assert [c[0] for c in tiras[0].celdas] == list("AABCAABC")
    assert tiras[0].celdas[0][1] == "oleada 3" and tiras[0].celdas[3][1] == "oleada 12"
    assert "oleadas 12, 24, 36" in tiras[0].celdas[3][2]
    rotulos = [p.rotulo.texto_completo() for p in buscador.ficha.findChildren(PanelC) if p.rotulo is not None]
    assert any("ROTACIÓN A" in r for r in rotulos)


def test_los_paneles_de_rotacion_se_despliegan_con_y_n_mas(buscador):
    from farmadex.ui import pestana_buscador as pb

    premios = [{"item_id": i, "nombre_en": f"Cosa {i}", "nombre_es": f"Cosa {i}", "padre_en": None,
                "padre_es": None, "rareza": "Common", "probabilidad": 5.0} for i in range(9)]
    corto = buscador._filas_rotacion(premios, False, "A")
    assert corto.count("<tr>") == pb.MAX_FILAS_ROTACION and "href='mas:A'" in corto and "y 3 más" in corto
    entero = buscador._filas_rotacion(premios, True, "A")
    assert entero.count("<tr>") == 9 and "ver menos" in entero


def test_tira_de_rondas_segun_el_modo(buscador):
    assert [c[0] for c in buscador._celdas_tira("Spy")] == ["A", "B", "C"]
    assert buscador._celdas_tira("Disruption") == []  # tiene su propia tabla
    assert buscador._celdas_tira("Exterminate") == []  # un premio al terminar, sin rondas
    assert buscador._celdas_tira("Survival")[3][1] == "min 20"


def test_pista_de_eras_por_rotacion(buscador):
    premios = {"A": [{"nombre_en": "Neo A1 Relic"}], "B": [{"nombre_en": "Axi A1 Relic"}],
               "C": [{"nombre_en": "Axi B2 Relic"}, {"nombre_en": "Neo A1 Relic"}]}
    pista = buscador._pista_eras(premios)
    assert "reliquias Axi solo salen en: B, C." in pista and "Neo" in pista


# -- ficha de objeto -----------------------------------------------------------------------


def test_ficha_de_objeto_en_dos_columnas_con_pedestal_e_insignias(buscador):
    from farmadex.ui.estilo_c import Pedestal
    from farmadex.ui.ficha_c import InsigniaGlosa

    buscador.ficha.resize(1100, 700)
    buscador.abrir(_id(buscador.con, "Axi A7 Relic"))
    assert len(buscador.ficha.findChildren(Pedestal)) == 1
    insignias = buscador.ficha.findChildren(InsigniaGlosa)
    claves = {i.clave for i in insignias}
    assert {"reliquia", "era", "boveda"} <= claves
    # La insignia se lee en mayusculas pero su enlace del glosario queda intacto.
    reliquia = next(i for i in insignias if i.clave == "reliquia")
    assert "glosa:reliquia" in reliquia.text() and "RELIQUIA" in reliquia.text()


def test_pieza_prime_con_pasos_y_el_set(buscador):
    from farmadex.ui.estilo_c import CasillaC

    sistemas = buscador.con.execute(
        "SELECT id FROM items WHERE unique_name LIKE '%AshPrimeSystemsComponent'"
    ).fetchone()[0]
    buscador.abrir(sistemas)
    texto = buscador.ficha.toPlainText()
    assert "CÓMO CONSEGUIRLO" in texto and "PASO 1" in texto and "Consigue la reliquia" in texto
    assert "Elige la pieza al acabar" in texto
    casillas = buscador.ficha.findChildren(CasillaC)
    assert len(casillas) >= 2
    marcada = [c for c in casillas if c._marcado]
    assert len(marcada) == 1 and "tú estás aquí" in marcada[0].sub.text()
    # Pulsar otra pieza del set abre su ficha.
    otra = next(c for c in casillas if not c._marcado)
    otra.pulsado.emit()
    assert buscador._actual != sistemas and buscador._datos_actuales["padre"] is not None


def test_set_con_donde_se_consigue_pieza_a_pieza(buscador):
    buscador.abrir(_id(buscador.con, "Ash Prime"))
    texto = buscador.ficha.toPlainText()
    assert "DÓNDE SE CONSIGUE" in texto
    assert "Sistemas" in texto and "Chasis" in texto
    html = unquote(buscador.ficha.toHtml())
    assert "item:" in html and "glosa:" in html


def test_el_html_entero_sigue_teniendo_todo(buscador):
    # `_html` junta los mismos trozos que los paneles: referencia de que no se pierde nada.
    from farmadex.datos import items

    html = buscador._html(items.ficha(buscador.con, _id(buscador.con, "Axi A7 Relic")))
    assert "Contenido en Radiante".upper() in html and "glosa:reliquia" in html


# -- barra de teclas y teclas ---------------------------------------------------------------


def test_la_barra_de_teclas_dice_lo_que_sirve(buscador):
    assert buscador.barra_teclas is None  # sin ficha, sin barra
    _buscar(buscador, "ash prime")
    teclas = set(buscador.barra_teclas.textos)
    assert {"+", "W", "Y", "C"} <= teclas and "Esc" not in teclas
    buscador.abrir(_id(buscador.con, "Axi A7 Relic"))
    assert "Esc" in buscador.barra_teclas.textos
    assert "O" not in buscador.barra_teclas.textos  # una reliquia no tiene builds


def test_las_teclas_de_la_ficha(buscador, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    _buscar(buscador, "ash prime")
    ash = buscador._actual
    objetivos, wikis, videos = [], [], []
    buscador.anadir_objetivo.connect(lambda i, s: objetivos.append((i, s)))
    buscador.boton_wiki.clicked.connect(lambda: wikis.append(1))
    buscador.boton_youtube.clicked.connect(lambda: videos.append(1))
    monkeypatch.setattr(buscador, "_abrir_wiki", lambda: None)
    monkeypatch.setattr(buscador, "_abrir_youtube", lambda: None)
    lista = buscador.lista
    assert _tecla(buscador, lista, Qt.Key_Plus, "+") and objetivos == [(ash, False)]
    assert _tecla(buscador, lista, Qt.Key_W, "w") and wikis == [1]
    assert _tecla(buscador, lista, Qt.Key_Y, "y") and videos == [1]
    assert _tecla(buscador, lista, Qt.Key_C, "c")
    assert QGuiApplication.clipboard().text() == "Ash Prime"
    # Una letra cualquiera sigue su camino (la lista salta al resultado que empieza por ella).
    assert not _tecla(buscador, lista, Qt.Key_Q, "q")


def test_esc_vuelve_solo_si_hay_adonde(buscador):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    _buscar(buscador, "ash prime")
    primero = buscador._actual
    sobre = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Escape, Qt.NoModifier)
    # Con una sola ficha, Esc es de la ventana (esconderla): no se lo quita.
    assert not buscador._teclas.eventFilter(buscador.lista, sobre)
    assert not _tecla(buscador, buscador.lista, Qt.Key_Escape)
    buscador.abrir(_id(buscador.con, "Axi A7 Relic"))
    sobre = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Escape, Qt.NoModifier)
    assert buscador._teclas.eventFilter(buscador.lista, sobre) and sobre.isAccepted()
    assert _tecla(buscador, buscador.lista, Qt.Key_Escape)
    assert buscador._actual == primero


def test_sin_ficha_las_teclas_no_hacen_nada(buscador):
    from PySide6.QtCore import Qt

    assert not _tecla(buscador, buscador.lista, Qt.Key_W, "w")
    assert not _tecla(buscador, buscador.lista, Qt.Key_Plus, "+")


# -- piezas ----------------------------------------------------------------------------------


def test_ficha_c_habla_como_el_qtextbrowser_de_antes(aplicacion):
    from farmadex.ui.estilo_c import PanelC
    from farmadex.ui.ficha_c import FichaC, etiqueta

    ficha = FichaC()
    assert ficha.toPlainText() == ""
    ficha.setHtml("<p>Hola <a href='item:3'>mundo</a></p>")
    assert ficha.toPlainText() == "Hola mundo" and "item:3" in ficha.toHtml()
    assert ficha.document().toPlainText() == "Hola mundo"
    ficha.vaciar()
    panel = PanelC("Titulo")
    panel.capa.addWidget(etiqueta("Sedna", "rotulo", mayus=True))
    escondida = etiqueta("no se ve")
    escondida.hide()
    panel.capa.addWidget(escondida)
    ficha.anadir(panel)
    ficha.anadir(None)  # un panel vacio no rompe nada
    # En pantalla va en mayusculas; el HTML guarda el texto original.
    assert "SEDNA" in ficha.toPlainText() and "Sedna" in ficha.toHtml()
    assert "no se ve" not in ficha.toPlainText()
    ficha.clear()
    assert ficha.toPlainText() == ""


def test_bloque_html_mide_lo_que_su_texto(aplicacion):
    from farmadex.ui.ficha_c import BloqueHtml

    bloque = BloqueHtml("<p>una</p>")
    bloque.resize(300, 10)
    bloque._ajustar()
    corto = bloque.height()
    bloque.setHtml("<p>una</p><p>dos</p><p>tres</p><p>cuatro</p>")
    bloque._ajustar()
    assert bloque.height() > corto
    assert bloque.document().size().height() <= bloque.viewport().height() + 2


def test_estadisticas_y_dano_de_un_arma():
    from farmadex.ui import ficha_detalles

    arma = {"critico": 0.12, "mult_critico": 2.0, "estado": 0.26, "cadencia": 9.5833, "cargador": 75.0,
            "recarga": 2.15, "gatillo": "Auto", "dano": {"impact": 1.75, "slash": 21.0}}
    filas = ficha_detalles.estadisticas_arma(arma)
    nombres = [f[0] for f in filas]
    assert "Probabilidad crítica" in nombres and "Recarga" in nombres
    critico = next(f for f in filas if f[0] == "Probabilidad crítica")
    assert critico[1] == "12%" and critico[2] == pytest.approx(0.24)
    recarga = next(f for f in filas if f[0] == "Recarga")
    assert recarga[2] == pytest.approx(1 - 2.15 / 5)  # la recarga corta llena mas
    gatillo = next(f for f in filas if f[0] == "Gatillo")
    assert gatillo[2] is None
    dano = ficha_detalles.dano_arma(arma)
    assert [d[0] for d in dano] == ["impact", "slash"] and dano[1][2] == 21.0


def test_la_leyenda_lleva_rombos():
    from farmadex.ui import colores_tipo

    assert "&#9670;" in colores_tipo.leyenda_html(["mod"])
