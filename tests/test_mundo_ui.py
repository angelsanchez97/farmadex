"""Pestana Mundo sin pantalla: jerarquia, caducadas fuera, objetivos marcados, Baro."""

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.online import worldstate as ws  # noqa: E402
from farmadex.ui import pestana_mundo  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _en(minutos):
    return datetime.now(timezone.utc) + timedelta(minutes=minutos)


def _mundo(baro_activo=True):
    F = ws.Fisura
    fisuras = [
        F("Neo", "Ukko, Vacio", "Captura", "Corrupto", _en(60)),
        F("Neo", "Cerberus, Pluton", "Intercepcion", "Corpus", _en(90)),
        F("Neo", "Oceanum, Pluton", "Espionaje", "Corpus", _en(20)),
        F("Neo", "Selkie, Sedna", "Supervivencia", "Grineer", _en(90), acero=True),
        F("Lith", "Casini, Ceres", "Captura", "Grineer", _en(5.5)),
        F("Meso", "Encelado, Saturno", "Sabotaje", "Grineer", _en(-5)),  # terminada
        F("Axi", "Ur, Urano", "Sabotaje", "Grineer", _en(50), tormenta=True),
    ]
    inventario = [
        ws.ObjetoBaro("Prisma Gorgon", "/x", 600, 125000, 2, "Gorgon Prisma", "Primary"),
        ws.ObjetoBaro("Sands of Inaros", "/y", 100, 25000, 3, "Arenas de Inaros", "Quests", objetivo=True),
    ]
    baro = ws.Baro("Baro Ki'Teer", "Larunda, Mercurio", baro_activo,
                   llegada=_en(-100) if baro_activo else _en(3000),
                   expira=_en(1000) if baro_activo else None,
                   inventario=inventario if baro_activo else [])
    return ws.Mundo(
        momento=datetime.now(timezone.utc), fisuras=fisuras,
        ciclos=[ws.Ciclo("Cetus", "dia", _en(30))],
        invasiones=[ws.Invasion("Marid, Sedna", "Siege", "Corpus", "Grineer", "1x Forma", 40)] * 7,
        sortie=[ws.Recompensa("Hyf, Deimos - Defensa", _en(200), "Bow Only")],
        baro_cabecera=baro.cabecera(), baro_detalle=baro,
    )


def _textos(seccion) -> list[str]:
    """Los textos de las lineas visibles de un bloque, en su orden."""
    salida = []
    for i in range(seccion.caja.count()):
        w = seccion.caja.itemAt(i).widget()
        if isinstance(w, QLabel) and not w.isHidden():
            salida.append(w.text())
    return salida


@pytest.fixture()
def mundo(app):
    idiomas.cargar("es")
    pestana = pestana_mundo.PestanaMundo()
    pestana._eras_necesarias = {"Neo": ["Canon de Athodai Prime"]}
    pestana.actualizar(_mundo())
    yield pestana
    idiomas.cargar("es")


def test_las_terminadas_no_salen_y_las_rapidas_van_primero(mundo):
    lineas = _textos(mundo.tarjetas["fisuras"])
    assert not any("Encelado" in x for x in lineas), "una fisura terminada no puede aparecer"
    # Captura (rapida) por delante de Intercepcion (sin fin).
    assert "Casini" in lineas[0]
    assert mundo.tarjetas["fisuras"].extra.text() == "2"
    # Lo urgente (menos de 10 minutos) va en naranja.
    assert "font-weight:bold" in lineas[0] and "5m" in lineas[0]


def test_lo_que_sirve_para_un_objetivo_va_arriba_y_marcado(mundo):
    objetivos = mundo.tarjetas["objetivos"]
    assert not objetivos.isHidden()
    lineas = _textos(objetivos)
    # Dos por era como mucho, las mas rapidas, y sin las de Acero salvo que se filtre.
    assert len(lineas) == 2
    assert "Ukko" in lineas[0] and "Oceanum" in lineas[1]
    assert all("Canon de Athodai Prime" in x for x in lineas)
    assert objetivos.extra.text() == "2 de 4"
    # La tercera Neo sigue abajo, marcada con la flecha al objetivo.
    resto = _textos(mundo.tarjetas["fisuras"])
    assert any("Cerberus" in x and "Canon de Athodai" in x for x in resto)


def test_sin_objetivos_el_bloque_desaparece_y_sin_fisura_util_lo_dice(mundo):
    mundo._eras_necesarias = {}
    mundo.pintar()
    assert mundo.tarjetas["objetivos"].isHidden()
    mundo._eras_necesarias = {"Requiem": ["Reliquia Requiem I"]}
    mundo.pintar()
    lineas = _textos(mundo.tarjetas["objetivos"])
    assert len(lineas) == 1 and "Necesitas" in lineas[0] and "Requiem" in lineas[0]


def test_acero_y_tormentas_van_aparte_y_plegadas(mundo):
    acero, tormentas = mundo.tarjetas["acero"], mundo.tarjetas["tormentas"]
    assert acero.plegada() and tormentas.plegada()
    assert "Selkie" in _textos(acero)[0] and "Ur, Urano" in _textos(tormentas)[0]
    acero.boton.click()
    assert not acero.plegada()
    mundo.pintar()  # un refresco del mundo no vuelve a plegarla
    assert not acero.plegada()


def test_el_filtro_de_modo_mete_las_de_acero_en_objetivos(mundo):
    mundo.filtro_modo.setCurrentIndex(mundo.filtro_modo.findData("Camino de Acero"))
    lineas = _textos(mundo.tarjetas["objetivos"])
    assert len(lineas) == 1 and "Selkie" in lineas[0]


def test_baro_presente_con_inventario_y_objetivo_primero(mundo):
    baro = mundo.tarjetas["baro"]
    lineas = _textos(baro)
    assert "Larunda" in lineas[0]
    assert "Arenas de Inaros" in lineas[1] and "cubre un objetivo" in lineas[1]
    assert "600 ducados" in lineas[2]
    assert "se va en" in baro.extra.text()


def test_baro_ausente_con_cuenta_atras(mundo):
    mundo.actualizar(_mundo(baro_activo=False))
    baro = mundo.tarjetas["baro"]
    assert "llega en" in baro.extra.text() and "2d" in baro.extra.text()
    assert "Larunda" in _textos(baro)[0]


def test_las_invasiones_se_resumen(mundo):
    lineas = _textos(mundo.tarjetas["invasiones"])
    assert len(lineas) == pestana_mundo.MAX_INVASIONES + 1
    assert "2 invasiones mas" in lineas[-1]


def test_un_reloj_que_termina_esconde_su_linea(mundo):
    seccion = mundo.tarjetas["fisuras"]
    etiqueta, base, _ = seccion.relojes[0]
    seccion.relojes[0] = (etiqueta, base, _en(-1))
    seccion.refrescar_relojes()
    assert etiqueta.isHidden()


@pytest.mark.parametrize("diseno", pestana_mundo.DISENOS)
def test_los_dos_disenos_pintan_lo_mismo_y_cambian_de_idioma(app, diseno):
    idiomas.cargar("es")
    pestana = pestana_mundo.PestanaMundo(diseno=diseno)
    pestana._eras_necesarias = {"Neo": ["Forma"]}
    pestana.actualizar(_mundo())
    assert pestana.tarjetas["fisuras"].title() == "Fisuras del Vacio"
    assert _textos(pestana.tarjetas["objetivos"])
    if diseno == "tablero":
        assert pestana.tarjetas["ahora"].isHidden() and not pestana.tarjetas["ciclos"].isHidden()
        # Agrupadas por era: la cabecera "Lith · 1" precede a Casini.
        assert any("Lith" in x and "1" in x for x in _textos(pestana.tarjetas["fisuras"]))
    else:
        assert pestana.tarjetas["ciclos"].isHidden() and not pestana.tarjetas["ahora"].isHidden()
    idiomas.cargar("en")
    pestana.retraducir()
    assert pestana.tarjetas["fisuras"].title() == "Void Fissures"
    assert pestana.tarjetas["objetivos"].title() == "For your goals"
    idiomas.cargar("es")


def test_los_enlaces_de_baro_abren_la_ficha(mundo):
    recibidos = []
    mundo.abrir_item.connect(recibidos.append)
    mundo.tarjetas["baro"]._activar("item:2")
    assert recibidos == [2]


def test_rapidez_de_misiones():
    assert pestana_mundo.rapidez("Captura") < pestana_mundo.rapidez("Espionaje")
    assert pestana_mundo.rapidez("Espionaje") < pestana_mundo.rapidez("Supervivencia")
    assert pestana_mundo.rapidez("Excavación") == pestana_mundo.rapidez("Excavation")
    assert pestana_mundo.rapidez("Algo raro") == 6
