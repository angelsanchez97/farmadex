import os
import sqlite3
import tempfile
from pathlib import Path

# Antes de importar nada de farmadex: las rutas de datos se resuelven al importar
# `config`, y sin esto las pruebas escriben en la carpeta de verdad del usuario.
# Ya paso una vez con config.json, que le cambio el tema sin que el tocara nada;
# el registro a fichero estaba haciendo lo mismo con su log.
os.environ.setdefault("FARMADEX_DATOS", str(Path(tempfile.gettempdir()) / "farmadex-pruebas"))

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "ventana_win32: crea una ventana Win32 real; corre en un proceso aparte"
    )


@pytest.fixture(autouse=True)
def _sin_ventanas_externas(monkeypatch):
    """Ninguna prueba abre carpetas, el Explorador ni el navegador en el PC de verdad.

    El usuario juega mientras se pasan las pruebas, y una ventana del Explorador que
    salta encima le corta la partida. Las pruebas que comprueban que algo se "abre"
    sustituyen estas funciones por las suyas, que ganan sobre esta.
    """
    import subprocess

    popen_real = subprocess.Popen

    def popen_sin_explorador(args, *resto, **kw):
        programa = str(args[0] if isinstance(args, (list, tuple)) else args).lower()
        if "explorer" in programa:
            return None
        return popen_real(args, *resto, **kw)

    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "Popen", popen_sin_explorador)
    try:
        from PySide6.QtGui import QDesktopServices

        monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda *a, **k: True))
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _configuracion_limpia():
    """La configuracion se comparte entre modulos: que no viaje de una prueba a otra."""
    from farmadex import config

    config._compartida = None
    yield
    config._compartida = None


@pytest.fixture()
def con(tmp_path, monkeypatch):
    """Indice vacio en disco temporal, con el esquema y el glosario cargados."""
    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    from farmadex.datos import indice

    conexion = sqlite3.connect(tmp_path / "prueba.sqlite")
    indice.crear_esquema(conexion)
    indice.importar_glosario(conexion)
    yield conexion
    conexion.close()


@pytest.fixture()
def indice_poblado(con):
    """Importa los fixtures recortados: Ash Prime, Axi A7, dos nodos y missionRewards."""
    from farmadex.datos.drops import ImportadorDrops
    from farmadex.datos.items import ImportadorItems

    i18n = {
        "/Lotus/Powersuits/Ninja/NinjaPrime": {"name": "Ash Prime"},
        "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeSystemsComponent": {"name": "Sistemas"},
        "/Lotus/Types/Recipes/WarframeRecipes/AshPrimeChassisComponent": {"name": "Chasis"},
    }
    importador = ImportadorItems(con, i18n)
    for nombre in ("Warframes", "Relics", "Node"):
        importador.importar_categoria(FIXTURES / f"{nombre}.json")
    importador.enlazar_reliquias()

    drops = ImportadorDrops(con, importador.alias)
    drops.mission_rewards(FIXTURES / "missionRewards.json")
    con.commit()

    from farmadex.datos import indice

    indice.poblar_busqueda(con)
    return con, importador, drops
