"""Rendimiento 0.6.2: lo que no se ve se hace al ensenarse, rapidfuzz bajo demanda, la
ficha sin consultas repetidas, el lector pasivo mas espaciado y la autoprueba fiel."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from test_ruta_prime import _item, _premio, prime  # noqa: E402,F401 - fixture del indice sintetico

from farmadex import idiomas  # noqa: E402
from farmadex.estado import usuario_db  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# -- rapidfuzz perezoso ------------------------------------------------------------------


def test_difuso_se_comporta_como_rapidfuzz():
    from rapidfuzz import fuzz as fuzz_real
    from rapidfuzz import process as proceso_real

    from farmadex.datos import difuso

    assert difuso.fuzz.ratio("excalibur", "excalibor") == fuzz_real.ratio("excalibur", "excalibor")
    assert difuso.rf_process.extractOne("braton", ["braton prime", "boar"], scorer=difuso.fuzz.ratio) == \
        proceso_real.extractOne("braton", ["braton prime", "boar"], scorer=fuzz_real.ratio)
    assert difuso.Levenshtein.distance("abc", "abd") == 1
    assert "cargado" in repr(difuso.fuzz)


def test_ningun_modulo_importa_rapidfuzz_al_cargarse():
    """Si alguien vuelve a poner `from rapidfuzz import ...` arriba, el arranque paga ~1 s."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "src" / "farmadex"
    culpables = []
    for fichero in raiz.rglob("*.py"):
        for linea in fichero.read_text(encoding="utf-8").splitlines():
            if linea.startswith(("from rapidfuzz", "import rapidfuzz")):
                culpables.append(f"{fichero.relative_to(raiz)}: {linea}")
    assert culpables == []


# -- Primes y Mundo: al ensenarse ---------------------------------------------------------


@pytest.fixture()
def entorno_primes(app, con, prime, tmp_path, monkeypatch):  # noqa: F811
    from farmadex import config

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    braton = _item(con, "/P/BratonPrime", "Braton Prime", "Braton Prime")
    cano = _item(con, "/P/BratonPrimeBarrel", "Barrel", "Canon", padre=braton, tipo="Componente")
    _premio(con, prime["lith"], cano, {"Intact": 11.0, "Radiant": 10.0})
    con.commit()
    return con, usuario_db.conectar(tmp_path / "usuario.sqlite")


def test_primes_escondida_monta_la_rejilla_al_verse(entorno_primes):
    from farmadex.ui.pestana_primes import PestanaPrimes

    con, usuario = entorno_primes
    ventana = QWidget()
    pestana = PestanaPrimes(usuario=usuario)
    pestana.setParent(ventana)
    pestana.conectar_indice(con)
    assert pestana._cajas == [] and pestana._rejilla_pendiente
    pestana.refrescar_marcas()  # tampoco pinta nada escondida
    ventana.show()
    QApplication.processEvents()
    assert not pestana._rejilla_pendiente and not pestana._marcas_pendientes
    assert [c._titulo for c in pestana._cajas_sets] == ["Braton Prime", "Caliban Prime"]
    # Ya vista: cambiar de tema escondida solo apunta las marcas, no rehace la rejilla.
    cajas = list(pestana._cajas)
    ventana.hide()
    pestana.repintar()
    assert pestana._marcas_pendientes and not pestana._rejilla_pendiente
    ventana.show()
    QApplication.processEvents()
    assert pestana._cajas == cajas and not pestana._marcas_pendientes
    ventana.close()


def test_primes_suelta_sigue_montando_al_momento(entorno_primes):
    from farmadex.ui.pestana_primes import PestanaPrimes

    con, usuario = entorno_primes
    pestana = PestanaPrimes(usuario=usuario)
    pestana.conectar_indice(con)
    assert len(pestana._cajas_sets) == 2


def test_mundo_escondido_no_se_pinta_hasta_verse(app, monkeypatch):
    from farmadex.ui import pestana_mundo

    ventana = QWidget()
    pestana = pestana_mundo.PestanaMundo()
    pestana.setParent(ventana)
    pintadas = []
    monkeypatch.setattr(pestana, "pintar", lambda: pintadas.append(1))
    pestana.repintar()
    pestana.retraducir()
    pestana.refrescar_objetivos()
    assert pintadas == [] and pestana._pintar_pendiente
    ventana.show()
    QApplication.processEvents()
    assert pintadas == [1] and not pestana._pintar_pendiente
    pestana.repintar()  # a la vista: al momento
    assert pintadas == [1, 1]
    ventana.close()


# -- tema: cada pestana escondida se repinta al ensenarse -------------------------------------


@pytest.fixture()
def ventana(app, tmp_path, monkeypatch):
    from farmadex import config, tareas
    from farmadex.datos import indice

    monkeypatch.setattr(config, "RUTA_CONFIG", tmp_path / "config.json")
    original = usuario_db.conectar
    monkeypatch.setattr(usuario_db, "conectar", lambda ruta=None: original(tmp_path / "usuario.sqlite"))
    monkeypatch.setattr(tareas.TareaDatos, "start", lambda self: None)
    monkeypatch.setattr(indice, "hay_indice", lambda ruta=None: False)
    from farmadex.ui.overlay import VentanaOverlay

    idiomas.cargar("es")
    v = VentanaOverlay()
    v.show()
    yield v
    v.hide()
    idiomas.cargar("es")


def test_cambiar_tema_repinta_ya_lo_visible_y_lo_demas_al_verse(ventana, monkeypatch):
    llamadas = []
    for nombre in ("buscador", "builds", "tablero"):
        pagina = getattr(ventana, nombre)
        monkeypatch.setattr(pagina, "repintar", lambda n=nombre: llamadas.append(n))
    ventana.ir_a("tablero")
    ventana.cambiar_tema(ventana.config.get("tema") or "")
    assert llamadas == ["tablero"]
    ventana.ir_a("buscar")
    QApplication.processEvents()
    assert llamadas == ["tablero", "buscador"]
    # Una sola vez: volver a ensenarla no la repinta otra vez.
    ventana.ir_a("tablero")
    ventana.ir_a("buscar")
    assert llamadas.count("buscador") == 1
    assert ventana.ir_a("builds") is ventana.builds, ventana.ruta_de("builds")
    QApplication.processEvents()
    assert llamadas[-1] == "builds"


# -- ficha: glosario en memoria, misiones cacheadas e imagenes sueltas ---------------------------


def test_glosario_en_memoria_da_lo_mismo_que_el_indice(con):  # noqa: F811
    from farmadex.datos import indice
    from farmadex.ui import pestana_buscador as pb

    con.execute("INSERT OR REPLACE INTO glosario (dominio, en, es) VALUES ('rotacion', 'A', 'A-es')")
    con.commit()
    assert pb._traducir(con, "rotacion", "A") == indice.traducir(con, "rotacion", "A") == "A-es"
    assert pb._traducir(con, "rotacion", "Z") == "Z"
    assert pb._traducir(con, "rotacion", None) == ""
    # Otra conexion (indice nuevo): se vuelve a leer.
    con.execute("UPDATE glosario SET es = 'nuevo' WHERE en = 'A'")
    assert pb._traducir(con, "rotacion", "A") == "A-es"  # misma conexion: la copia en memoria
    pb._glosario_memoria = (None, {})
    assert pb._traducir(con, "rotacion", "A") == "nuevo"


def test_imagen_de_una_pieza_cambia_solo_su_pixmap(monkeypatch):
    from farmadex.ui import pestana_buscador as pb

    llegadas = {}
    falso = SimpleNamespace(pixmap=lambda nombre, lado: llegadas.get(nombre))
    monkeypatch.setattr(pb, "imagenes", lambda: falso)
    rehechas = []
    yo = SimpleNamespace(
        _destinos_imagen={}, _imagenes_ficha=set(), pedestal=None, _datos_actuales=None,
        lista=SimpleNamespace(viewport=lambda: SimpleNamespace(update=lambda: None)),
        _repintado_imagenes=SimpleNamespace(start=lambda: rehechas.append(1)),
    )
    puestas = []
    assert pb.PestanaBuscador._pedir_imagen(yo, "a.png", 46, puestas.append) is None
    assert pb.PestanaBuscador._pedir_imagen(yo, "b.png", 26) is None  # va en el HTML
    llegadas.update({"a.png": "PIX-A", "b.png": "PIX-B"})
    pb.PestanaBuscador._imagen_lista(yo, "a.png")
    assert puestas == ["PIX-A"] and rehechas == []
    pb.PestanaBuscador._imagen_lista(yo, "b.png")
    assert rehechas == [1]

    def borrada(_mapa):
        raise RuntimeError("Internal C++ object already deleted")

    llegadas.clear()
    pb.PestanaBuscador._pedir_imagen(yo, "c.png", 46, borrada)
    llegadas["c.png"] = "PIX-C"
    pb.PestanaBuscador._imagen_lista(yo, "c.png")  # no revienta


# -- lector pasivo -------------------------------------------------------------------------


def test_lector_pasivo_cachea_la_ventana_y_espacia_si_nada_cambia(app, monkeypatch):
    from PySide6.QtCore import QTimer

    from farmadex.captura import lector_pasivo as lp
    from farmadex.captura import pantalla

    busquedas = []
    monkeypatch.setattr(pantalla, "ventana_juego", lambda: busquedas.append(1) or 77)
    monkeypatch.setattr(pantalla, "_ventana_activa", lambda: 77)
    monkeypatch.setattr(pantalla, "region_ventana", lambda hwnd: (0, 0, 10, 10))
    monkeypatch.setattr(pantalla, "capturar_sin_ocultar", lambda region: "imagen")
    monkeypatch.setattr(pantalla, "descartar_propias", lambda imagen, region: imagen)
    lector = lp.LectorPasivo.__new__(lp.LectorPasivo)
    lp.QObject.__init__(lector)
    lector.activo_perfil, lector.activo_inventario = True, False
    lector._ocupado = False
    lector._reliquia_hasta = 0.0
    lector.pantalla_log = None
    lector._hwnd, lector._hwnd_hasta = None, 0.0
    lector._temporizador = QTimer()
    lector._temporizador.setInterval(lp.INTERVALO_MS)
    leidas = []
    monkeypatch.setattr(lector, "leer_imagen", lambda imagen: leidas.append(imagen))
    lector.detector = SimpleNamespace(quietas=2, _iguales=0)

    def observar(_imagen):
        lector.detector._iguales += 1
        return lector.detector._iguales == 2

    lector.detector.observar = observar
    for _ in range(4):
        lector.tic()
    assert busquedas == [1]  # una sola busqueda de la ventana en 2 s
    assert leidas == ["imagen"]
    assert lector._temporizador.interval() == lp.INTERVALO_QUIETO_MS
    lector.pantalla_juego("abierta", "perfil")  # algo cambia: vuelve al ritmo normal
    assert lector._temporizador.interval() == lp.INTERVALO_MS


# -- al abrir y autoprueba ------------------------------------------------------------------


def test_al_abrir_no_espera_mas_de_segundo_y_medio():
    from farmadex.actualizador import al_abrir

    assert al_abrir.PLAZO_CONSULTA_S <= 1.5


def test_autoprueba_entrega_los_deletelater_y_mide_memoria(app):
    from PySide6.QtCore import QObject

    from farmadex import autoprueba

    prueba = autoprueba.Autoprueba.__new__(autoprueba.Autoprueba)
    prueba.app = app
    borrados = []
    objeto = QObject()
    objeto.destroyed.connect(lambda *_: borrados.append(1))
    objeto.deleteLater()
    del objeto
    prueba.bombear(0.01)
    assert borrados == [1]
    memoria = autoprueba.memoria_mb()
    assert memoria is None or memoria > 10
