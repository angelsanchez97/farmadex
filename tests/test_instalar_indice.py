"""Cambiar el indice por uno nuevo con el viejo abierto (WinError 32 tras actualizar)."""

import sqlite3

from farmadex.datos.indice import instalar_indice


def _base(ruta, filas):
    con = sqlite3.connect(ruta)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(filas)])
    con.commit()
    return con


def test_se_instala_con_el_indice_viejo_abierto(tmp_path):
    destino = tmp_path / "indice.sqlite"
    nuevo = tmp_path / "indice.nuevo"
    escritor = _base(destino, 1)
    lector = sqlite3.connect(destino)  # como el lector de reliquias o una pestana
    assert lector.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    _base(nuevo, 5).close()

    instalar_indice(nuevo, destino)

    assert lector.execute("SELECT count(*) FROM t").fetchone()[0] == 5
    assert not nuevo.exists()
    lector.close()
    escritor.close()


def test_sin_indice_previo_se_mueve_tal_cual(tmp_path):
    destino = tmp_path / "indice.sqlite"
    nuevo = tmp_path / "indice.nuevo"
    _base(nuevo, 3).close()
    instalar_indice(nuevo, destino)
    con = sqlite3.connect(destino)
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 3
    con.close()


def test_un_indice_viejo_roto_se_sustituye(tmp_path):
    destino = tmp_path / "indice.sqlite"
    destino.write_bytes(b"esto no es una base de datos" * 100)
    nuevo = tmp_path / "indice.nuevo"
    _base(nuevo, 2).close()
    instalar_indice(nuevo, destino)
    con = sqlite3.connect(destino)
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 2
    con.close()


def test_reemplazar_aguanta_un_destino_bloqueado_un_momento(tmp_path, monkeypatch):
    """OBS leyendo el texto del directo justo al sustituirlo: PermissionError y reintento."""
    import os

    from farmadex import ficheros

    destino = tmp_path / "obs.txt"
    destino.write_text("viejo", encoding="utf-8")
    fallos = {"n": 2}
    real = os.replace

    def replace_bloqueado(a, b):
        if fallos["n"]:
            fallos["n"] -= 1
            raise PermissionError(32, "en uso")
        real(a, b)

    monkeypatch.setattr(ficheros.os, "replace", replace_bloqueado)
    monkeypatch.setattr(ficheros, "ESPERA_S", 0)
    ficheros.escribir_texto(destino, "nuevo")
    assert destino.read_text(encoding="utf-8") == "nuevo"

    fallos["n"] = 99  # bloqueado todo el rato: se escribe encima igualmente
    ficheros.escribir_texto(destino, "otra vez")
    assert destino.read_text(encoding="utf-8") == "otra vez"


def test_recompensa_de_ee_log_casa_con_el_objeto_sacado_de_la_tabla_de_de():
    """Lo recien salido tiene ruta inventada; la de EE.log puede usar el nombre interno."""
    from farmadex.datos.indice import fila_por_ruta

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, unique_name TEXT, nombre_en TEXT)")
    con.executemany("INSERT INTO items VALUES (?, ?, ?)", [
        (1, "/Lotus/Powersuits/Geode/Geode", "Citrine"),
        (2, "/Farmadex/DE/CitrinePrimeChassisComponent", "Chassis"),
        (3, "/Farmadex/DE/CitrinePrimeBlueprint", "Blueprint"),
        (4, "/Farmadex/DE/CitrinePrimeNeuropticsComponent", "Neuroptics"),
    ])
    rutas = "/Lotus/StoreItems/Types/Recipes/WarframeRecipes/"
    assert fila_por_ruta(con, rutas + "GeodePrimeChassisBlueprint") == (2,)
    assert fila_por_ruta(con, rutas + "CitrinePrimeChassisBlueprint") == (2,)
    assert fila_por_ruta(con, rutas + "GeodePrimeHelmetBlueprint") == (4,)
    assert fila_por_ruta(con, rutas + "GeodePrimeBlueprint") == (3,)
    assert fila_por_ruta(con, rutas + "AshPrimeChassisBlueprint") is None


def test_un_indice_de_version_compatible_se_sigue_usando_si_no_se_puede_reconstruir(tmp_path):
    """Sin red tras actualizar: mejor el indice de la version anterior que "Error preparando los datos"."""
    from farmadex.datos import indice

    ruta = tmp_path / "indice.sqlite"
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE meta (clave TEXT, valor TEXT)")
    con.execute("CREATE TABLE items (id INTEGER)")
    con.execute("INSERT INTO items VALUES (1)")
    con.executemany("INSERT INTO meta VALUES (?, ?)", [("construido_en", "ayer"), ("esquema_version", "8")])
    con.commit()
    con.close()
    assert indice.hay_indice(ruta) and not indice.indice_al_dia(ruta)
    con = sqlite3.connect(ruta)
    con.execute("UPDATE meta SET valor = '5' WHERE clave = 'esquema_version'")
    con.commit()
    con.close()
    assert not indice.hay_indice(ruta)  # demasiado viejo: otra estructura de tablas
