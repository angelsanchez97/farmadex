"""Desglose del tiempo medio al pasar el raton y ritmo de juego (Ajustes)."""

from __future__ import annotations

import json
import re

import pytest

from test_ruta_prime import prime  # noqa: F401 - fixture del indice sintetico

from farmadex.datos import eficiencia, ruta_prime

RE_TOOLTIP = re.compile(r"href='glosa:(tiempo_(?:medio|pieza)\?[^']+)'")


@pytest.fixture()
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def config_temporal(tmp_path, monkeypatch):
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    return config


def _ritmo(config, valor: str) -> None:
    datos = config.cargar()
    datos[eficiencia.CLAVE_RITMO] = valor
    config.guardar(datos)


def _formido() -> dict:
    # Deimos/Formido (Caches), rotacion C, 19,36 %: lo que vio el usuario ("~70 min").
    fila = {"tipo": "mision", "modo": "Caches", "rotacion": "C", "probabilidad": 19.36,
            "origen_texto": "Deimos/Formido (Caches)"}
    eficiencia.estimar(fila)
    return fila


def _tooltips(html: str) -> list[str]:
    from farmadex.ui import glosario

    return [glosario.texto(url) for url in RE_TOOLTIP.findall(html)]


# -- desglose -----------------------------------------------------------------------

def test_desglose_de_formido_cuadra_con_lo_que_se_ensena(config_temporal):
    from farmadex.ui import desglose_tiempo

    fila = _formido()
    assert eficiencia.texto_minutos(fila["minutos_medios"]) == "~70 min"
    texto = desglose_tiempo.texto(fila)
    assert texto.splitlines() == [
        "~13.5 min por partida (hasta la rotacion C).",
        "x ~5.2 partidas de media (19.4% cada una) = ~70 min.",
        "Es una media: puede caer antes o tardar mas.",
    ]
    d = eficiencia.desglose(fila)
    assert d["intento"] * d["veces"] == pytest.approx(fila["minutos_medios"], abs=0.1)


@pytest.mark.parametrize(
    ("fila", "trozo"),
    [
        ({"tipo": "mision", "modo": "Capture", "probabilidad": 5.0}, "~2.5 min por partida, contando la carga."),
        ({"tipo": "mision", "modo": "Survival", "rotacion": "C", "probabilidad": 10.0},
         "hasta la rotacion C: 4 rotaciones de ~5 min"),
        ({"tipo": "mision", "modo": "Survival", "rotacion": "A", "probabilidad": 10.0},
         "que dan 2 intentos: ~7.2 min por intento"),
        ({"tipo": "bounty", "origen_texto": "Cetus Bounty", "rotacion": "A", "probabilidad": 20.0},
         "vuelve cada 3 contratos: 3 tandas de ~11.5 min"),
        ({"tipo": "enemigo", "jefe": True, "probabilidad": 97.42}, "combate contra el jefe"),
    ],
)
def test_desglose_segun_la_clase_de_fuente(config_temporal, fila, trozo):
    from farmadex.ui import desglose_tiempo

    eficiencia.estimar(fila)
    texto = desglose_tiempo.texto(fila)
    assert trozo in texto
    assert eficiencia.texto_minutos(fila["minutos_medios"]) in texto


def test_sin_estimacion_no_hay_desglose(config_temporal):
    from farmadex.ui import desglose_tiempo

    fila = {"tipo": "enemigo", "probabilidad": 3.0}
    eficiencia.estimar(fila)
    assert desglose_tiempo.texto(fila) == ""


def test_el_tooltip_lleva_el_desglose_y_el_ritmo(config_temporal):
    from farmadex.ui import desglose_tiempo, glosario

    enlace = glosario.enlace("tiempo_medio", "~70 min", "#fff", detalle=desglose_tiempo.texto(_formido()))
    (tooltip,) = _tooltips(enlace)
    assert "~13.5 min por partida (hasta la rotacion C).<br>x ~5.2 partidas de media" in tooltip
    assert "ritmo de juego Normal (x1)" in tooltip
    # Sin detalle, la explicacion generica (y tambien el ritmo).
    generico = glosario.texto("tiempo_medio")
    assert "dividido por la probabilidad" in generico and "ritmo de juego" in generico


def test_desglose_prime_con_el_modelo_de_ruta_prime(config_temporal):
    from farmadex.ui import desglose_tiempo

    # Io, Defensa rotacion A; 25 % de que caiga la reliquia; pieza al 20 % en Radiante,
    # escuadra de 4 (59 % por fisura).
    sitio = {"tipo": "mision", "modo": "Survival", "rotacion": "A", "origen_texto": "Jupiter/Io (Survival)",
             "reliquias": [{"probabilidad_mision": 25.0, "probabilidad": 20.0}]}
    intento, _ = eficiencia.minutos_por_intento(sitio)
    sitio["minutos"] = round(ruta_prime.minutos_pieza(intento, [(25.0, 20.0)], 4), 1)
    assert eficiencia.texto_minutos(sitio["minutos"]) == "~55 min"
    lineas = desglose_tiempo.texto_prime(sitio, 4, "Radiante, escuadra de 4").splitlines()
    assert lineas == [
        "~14.5 min por partida (2 rotaciones A de ~5 min mas llegar, extraer y la carga), que dan 2 intentos: ~7.2 min por intento.",
        "25.0% de que caiga alguna reliquia util -> ~29 min por reliquia.",
        "+ ~3.5 min por fisura para abrirla.",
        "Radiante, escuadra de 4: 59% de sacar la pieza en cada fisura -> ~1.7 fisuras de media.",
        "(~29 + ~3.5 min) x ~1.7 = ~55 min.",
        "Es una media: puede caer antes o tardar mas.",
    ]


# -- ritmo de juego -----------------------------------------------------------------

def test_ritmo_por_defecto_y_valores():
    from farmadex import config

    assert config.POR_DEFECTO["ritmo_juego"] == "normal"
    assert eficiencia.RITMOS == {"rapido": 0.7, "normal": 1.0, "tranquilo": 1.4}


def test_rapido_baja_todos_los_tiempos_en_la_misma_proporcion(config_temporal):
    filas = [
        {"tipo": "mision", "modo": "Caches", "rotacion": "C", "probabilidad": 19.36},
        {"tipo": "mision", "modo": "Capture", "probabilidad": 5.0},
        {"tipo": "mision", "modo": "Survival", "rotacion": "A", "probabilidad": 12.0},
        {"tipo": "bounty", "origen_texto": "Cetus Bounty", "rotacion": "B", "probabilidad": 30.0},
        {"tipo": "enemigo", "jefe": True, "probabilidad": 50.0},
        {"tipo": "transitoria", "origen_texto": "Granum Void", "rotacion": "C", "probabilidad": 8.0},
    ]

    def tiempos():
        for f in filas:
            eficiencia.estimar(f)
        return [f["minutos_medios"] for f in filas]

    normal = tiempos()
    fisura_normal = eficiencia.minutos_fisura()
    pieza_normal = ruta_prime.minutos_pieza(5.75, [(25.0, 20.0)], 4, fisura=None)
    _ritmo(config_temporal, "rapido")
    rapido = tiempos()
    for n, r in zip(normal, rapido):
        assert r == pytest.approx(n * 0.7, abs=0.1)  # los minutos van redondeados a 0.1
    assert sorted(range(len(filas)), key=normal.__getitem__) == sorted(range(len(filas)), key=rapido.__getitem__)
    assert eficiencia.minutos_fisura() == pytest.approx(fisura_normal * 0.7)
    # La ruta prime tambien: mision y fisura escalan juntas.
    assert ruta_prime.minutos_pieza(5.75 * 0.7, [(25.0, 20.0)], 4) == pytest.approx(pieza_normal * 0.7)
    # Y el ritmo sale en el tooltip.
    from farmadex.ui import glosario

    assert "ritmo de juego Rapido (x0.7)" in glosario.texto("tiempo_medio")
    # Un valor raro en config.json no rompe nada: vale el normal.
    _ritmo(config_temporal, "turbo")
    assert tiempos() == normal


def test_ajustes_guarda_el_ritmo_y_avisa(app, config_temporal):
    from farmadex.ui.pestana_ajustes import PestanaAjustes

    ajustes = PestanaAjustes()
    assert ajustes.ritmo.currentData() == "normal"
    assert ajustes.ritmo.count() == 3
    avisos = []
    ajustes.ritmo_cambiado.connect(avisos.append)
    ajustes.ritmo.setCurrentIndex(ajustes.ritmo.findData("tranquilo"))
    assert avisos == ["tranquilo"]
    assert json.loads(config_temporal.RUTA_CONFIG.read_text(encoding="utf-8"))["ritmo_juego"] == "tranquilo"
    assert "x1.4" in ajustes.ritmo.currentText()


# -- ficha y pestana Primes -----------------------------------------------------------

def test_la_ficha_se_recalcula_al_cambiar_el_ritmo(app, con, prime, tmp_path, monkeypatch):  # noqa: F811
    from farmadex import config, tareas
    from farmadex.datos import indice
    from farmadex.estado import usuario_db

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    from farmadex.ui.overlay import VentanaOverlay

    ventana = VentanaOverlay()
    try:
        ventana.buscador.con = con
        ventana.buscador.abrir(prime["plano"])
        assert "~83 min" in ventana.buscador.ficha.toPlainText()  # 82.9 min
        ventana.ajustes.ritmo.setCurrentIndex(ventana.ajustes.ritmo.findData("rapido"))
        assert config.cargar()["ritmo_juego"] == "rapido"
        texto = ventana.buscador.ficha.toPlainText()
        assert "~58 min" in texto and "~83 min" not in texto  # 82.9 x 0.7 = 58 min
    finally:
        ventana.hide()


def test_ficha_con_desglose_en_cada_tiempo(app, con, prime, config_temporal):  # noqa: F811
    from farmadex.ui.pestana_buscador import PestanaBuscador

    buscador = PestanaBuscador()
    buscador.con = con
    buscador.abrir(prime["lith"])  # reliquia: tabla de misiones donde cae
    tooltips = _tooltips(buscador._html(buscador._datos_actuales))
    assert tooltips and all("partidas de media" in x or "intentos de media" in x for x in tooltips)


def test_primes_donde_farmear_con_relleno_y_desglose(app, con, prime, tmp_path, config_temporal):  # noqa: F811
    from farmadex.estado import usuario_db
    from farmadex.ui.pestana_primes import PestanaPrimes

    pestana = PestanaPrimes(usuario=usuario_db.conectar(tmp_path / "usuario.sqlite"))
    pestana.conectar_indice(con)
    caja = next(c for c in pestana._cajas if c.objeto and c.objeto["nombre_en"] == "Caliban Prime")
    caja.casillas["/P/CalibanPrimeBlueprint"].setChecked(True)
    datos = pestana.calcular()
    html = pestana.html_resultado(datos)
    assert html.count("name='relleno-") == len(datos["misiones"])
    tooltips = _tooltips(html)
    # Captura: 2,5 min por partida, 10 % de reliquia -> 25 min; + 3,5 de fisura; 34 % por
    # fisura en escuadra de 4 -> 2,9 fisuras: (25 + 3,5) x 2,9 = ~83 min.
    primero = next(x for x in tooltips if "~2.5 min por partida" in x)
    assert "10.0% de que caiga alguna reliquia util -&gt; ~25 min por reliquia." in primero
    assert "34% de sacar la pieza en cada fisura -&gt; ~2.9 fisuras de media." in primero
    assert "(~25 + ~3.5 min) x ~2.9 = ~83 min." in primero

    # Con ritmo rapido la pestana recalcula aunque tenga misiones en cache.
    _ritmo(config_temporal, "rapido")
    assert pestana.calcular()["misiones"][0]["minutos"] == pytest.approx(82.9 * 0.7, abs=0.1)


def test_textos_de_ritmo_traducidos():
    from farmadex import idiomas
    from farmadex.ui import glosario
    from farmadex.ui.pestana_ajustes import PestanaAjustes

    claves = set(glosario.NOMBRES_RITMO.values()) | set(PestanaAjustes.RITMOS.values())
    for ruta in sorted(idiomas.dir_catalogos().glob("*.json")):
        catalogo = json.loads(ruta.read_text(encoding="utf-8"))
        assert not claves - set(catalogo), ruta.stem
