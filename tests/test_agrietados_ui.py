"""Pestanas Build y Agrietados, sin pantalla ni red."""

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.agrietados import mercado  # noqa: E402
from farmadex.agrietados.lector import ArmaConocida, LectorTarjeta, TarjetaLeida, parsear_texto  # noqa: E402
from farmadex.captura.builds import Build  # noqa: E402
from farmadex.captura.ocr import Reconocido  # noqa: E402

from conftest import FIXTURES  # noqa: E402
from test_captura import _insertar  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def armas():
    return mercado.analizar_armas(json.load(open(FIXTURES / "market_riven_weapons.json", encoding="utf-8")))


@pytest.fixture()
def pestana(app, armas, monkeypatch, tmp_path):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    from farmadex.ui.pestana_agrietados import PestanaAgrietados

    idiomas.cargar("es")
    p = PestanaAgrietados(con_red=False)
    p.poner_armas(armas)
    yield p
    idiomas.cargar("es")


def _tarjeta(armas, lineas) -> TarjetaLeida:
    lector = LectorTarjeta([ArmaConocida(a.slug, a.nombre_en, a.nombre_en) for a in armas])
    return parsear_texto(lineas, lector)


def test_tarjeta_fiable_rellena_y_evalua_sola(pestana, armas):
    rubico = next(a for a in armas if a.slug == "rubico")
    from farmadex.agrietados import grados

    def centro(slug, negativo=False):
        minimo, maximo = grados.rango(slug, rubico.clase, rubico.disposicion, 3, 1, negativo=negativo)
        return abs(round((minimo + maximo) / 2, 1))

    tarjeta = _tarjeta(armas, [
        "Rubico Hexa-critacron",
        f"+{centro('status_chance')}% Status Chance",
        f"+{centro('critical_chance')}% Critical Chance",
        f"+{centro('critical_damage')}% Critical Damage",
        f"-{centro('damage_vs_corpus', True)}% Damage to Corpus",
        "MR 12", "O 4",
    ])
    assert tarjeta.fiable, tarjeta.avisos
    pestana.mostrar_tarjeta(tarjeta)
    assert pestana.arma_elegida().slug == "rubico"
    assert pestana.maestria.value() == 12 and pestana.variado.value() == 4
    assert pestana.nombre.text() == "Hexa-critacron"
    assert [e.grado for e in pestana.evaluaciones] == ["B", "B", "B", "B"]
    assert pestana.tabla.rowCount() == 4
    assert pestana.tabla.item(3, 0).text().startswith("Daño a Corpus")
    assert "Grados: B, B, B, B" in pestana.veredicto.text()
    assert "disposicion" in pestana.disposicion.text()


def test_tarjeta_dudosa_no_evalua_y_avisa(pestana, armas):
    tarjeta = _tarjeta(armas, ["Boar", "+125.6%WeaponRecoil", "+129.4%StatusChance", "48.1%Multishot", "MR12"])
    assert not tarjeta.fiable
    pestana.mostrar_tarjeta(tarjeta)
    assert pestana.evaluaciones == [] and pestana.tabla.rowCount() == 0
    assert "revisa" in pestana.estado.text().lower()
    assert pestana.arma_elegida().slug == "boar"
    # El usuario corrige (marca la negativa) y evalua a mano.
    pestana.filas[2][2].setChecked(True)
    pestana.evaluar()
    assert len(pestana.evaluaciones) == 3 and pestana.evaluaciones[2].negativo


def test_entrada_a_mano(pestana):
    assert pestana.elegir_arma("soma")
    pestana.poner_estadisticas([("multishot", 60.0, False), ("critical_chance", 100.0, False), ("zoom", 20.0, True)])
    assert pestana.estadisticas() == [("multishot", 60.0, False), ("critical_chance", 100.0, False), ("zoom", -20.0, True)]
    pestana.evaluar()
    assert len(pestana.evaluaciones) == 3
    assert pestana.tabla.rowCount() == 3
    pestana.limpiar()
    assert pestana.tabla.rowCount() == 0 and pestana.estadisticas() == [] and pestana.arma_elegida() is None


def test_reparto_imposible_se_rechaza(pestana):
    pestana.elegir_arma("soma")
    pestana.poner_estadisticas([("multishot", 60.0, False)])
    pestana.evaluar()
    assert "al menos dos" in pestana.veredicto.text()
    pestana.poner_estadisticas([("multishot", 60.0, False), ("zoom", 20.0, True), ("recoil", 20.0, True)])
    pestana.evaluar()
    assert "como mucho 1 negativa" in pestana.veredicto.text()


def test_valor_fuera_de_rango_se_dice(pestana):
    pestana.elegir_arma("soma")
    pestana.poner_estadisticas([("multishot", 900.0, False), ("critical_chance", 100.0, False)])
    pestana.evaluar()
    assert "no entra en lo posible" in pestana.veredicto.text()
    assert pestana.tabla.item(0, 3).text() == "fuera de rango"


def test_velada(pestana, armas):
    pestana.mostrar_tarjeta(_tarjeta(armas, ["???", "Rifle Riven Mod", "VEILED"]))
    assert "velada" in pestana.estado.text()


def test_texto_precio():
    from farmadex.ui.pestana_agrietados import texto_precio

    resumen = mercado.analizar_subastas("rubico", json.load(open(FIXTURES / "market_riven_auctions.json", encoding="utf-8")))
    medias = mercado.analizar_medias_de((FIXTURES / "de_weekly_rivens.txt").read_text(encoding="utf-8"))
    texto = texto_precio(resumen, None, medias[("rubico", True)], variado=3)
    assert "subastas parecidas" in texto and f"{resumen.minimo}p" in texto and "200p" in texto
    assert "variados" in texto
    vacio = texto_precio(mercado.ResumenSubastas(arma="rubico"), None, None)
    assert "no hay subastas" in vacio
    error = texto_precio(mercado.ResumenSubastas(arma="rubico", error="HTTP 503"), None, None)
    assert "HTTP 503" in error


def test_precio_de_otra_arma_se_ignora(pestana):
    pestana._precio_pedido = "soma"
    pestana._precio_listo("rubico", mercado.ResumenSubastas(arma="rubico"), None, None)
    assert pestana.precio.text() == ""


def test_puntos_de_disposicion():
    from farmadex.ui.pestana_agrietados import puntos_disposicion

    assert puntos_disposicion(1.4) == "●●●●●"
    assert puntos_disposicion(1.0) == "●●●○○"
    assert puntos_disposicion(0.5) == "●○○○○"


# -- pestana Build -----------------------------------------------------------------------


@pytest.fixture()
def builds(app, con, monkeypatch, tmp_path):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    ids = _insertar(con, [
        ("/w/Excalibur", "Excalibur", "Excalibur", "Warframes", None, None),
        ("/m/Vitality", "Vitality", "Vitalidad", "Mods", None, None),
        ("/m/Flow", "Flow", "Flujo", "Mods", None, None),
        ("/a/Energize", "Arcane Energize", "Energizar Arcano", "Arcanes", None, None),
    ])
    from farmadex.ui.pestana_builds import PestanaBuilds

    idiomas.cargar("es")
    p = PestanaBuilds()
    p.conectar_indice(con)
    return p, ids


def _rec(ids, unique, nombre):
    return Reconocido(nombre, ids[unique], nombre, 100.0, (0, 0, 10, 10))


def test_build_se_lista_y_se_pulsa(builds):
    p, ids = builds
    build = Build(
        equipo=_rec(ids, "/w/Excalibur", "Excalibur"),
        equipados=[_rec(ids, "/m/Vitality", "Vitalidad")],
        coleccion=[_rec(ids, "/m/Flow", "Flujo")],
        arcanos=[_rec(ids, "/a/Energize", "Energizar Arcano")],
        sin_identificar=["Absorci"],
    )
    p.mostrar_build(build)
    assert p.ids_listados() == [ids["/w/Excalibur"], ids["/m/Vitality"], ids["/a/Energize"], ids["/m/Flow"]]
    assert "Excalibur" in p.estado.text() and "2 mods" in p.estado.text()
    textos = [p.lista.item(i).text() for i in range(p.lista.count())]
    assert any("Absorci" in t for t in textos)
    assert any("(Mod)" in t for t in textos) and any("(Arcano)" in t for t in textos)
    abiertos = []
    p.abrir_item.connect(abiertos.append)
    fila = next(p.lista.item(i) for i in range(p.lista.count()) if p.lista.item(i).data(Qt.UserRole) == ids["/m/Flow"])
    p._pulsado(fila)
    assert abiertos == [ids["/m/Flow"]]
    # Una cabecera no abre nada.
    p._pulsado(p.lista.item(0))
    assert abiertos == [ids["/m/Flow"]]


def test_build_vacia(builds):
    p, _ = builds
    p.mostrar_build(Build(sin_identificar=["CONFIG A"]))
    assert p.ids_listados() == []
    assert "No se ha reconocido nada" in p.estado.text()
    p.retraducir()
    assert "Leer la pantalla de mejoras" in p.boton.text()


def test_destruir_la_pestana_con_red_no_mata_el_proceso(tmp_path):
    """Un QThread vivo al destruir la pestana hacia que Qt cortase el proceso (codigo 127)."""
    import subprocess
    import sys

    codigo = (
        "from PySide6.QtWidgets import QApplication\n"
        "import shiboken6\n"
        "from farmadex.agrietados import mercado\n"
        "mercado.MercadoAgrietados.armas = lambda self, forzar_red=False: []\n"
        "app = QApplication([])\n"
        "from farmadex.ui.pestana_agrietados import PestanaAgrietados\n"
        "p = PestanaAgrietados()\n"
        "shiboken6.delete(p)\n"
        "print('OK')\n"
    )
    entorno = dict(os.environ, QT_QPA_PLATFORM="offscreen", FARMADEX_DATOS=str(tmp_path),
                   PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    r = subprocess.run([sys.executable, "-c", codigo], env=entorno, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-500:]
