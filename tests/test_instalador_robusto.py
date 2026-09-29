"""Instalacion a prueba de cortes: la version anterior queda intacta si algo falla.

Comprobaciones del .iss (estaticas) y del lado de Farmadex que lee lo que dejo el
setup. La prueba de verdad (compilar, instalar en una carpeta aparte, matar el setup a
mitad, ficheros bloqueados, .exe roto o colgado...) se hizo a mano con una build de
prueba aislada; ademas, si Inno Setup esta instalado, aqui se compila el .iss de verdad
con una carga minima para pillar errores del script de Pascal.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from farmadex.actualizador import instalacion

RAIZ = Path(__file__).resolve().parents[1]
ISS = (RAIZ / "empaquetado" / "instalador.iss").read_text(encoding="utf-8")


def _seccion(nombre: str) -> str:
    m = re.search(rf"^\[{nombre}\]\s*\n(.*?)(?=^\[\w+\]\s*$)", ISS, re.M | re.S)
    assert m, nombre
    return m.group(1)


def test_los_ficheros_nuevos_se_copian_aparte_y_no_encima():
    ficheros = [l for l in _seccion("Files").splitlines() if l.startswith("Source:")]
    principal = next(l for l in ficheros if "{#Origen}" in l)
    assert 'DestDir: "{app}\\_nuevo"' in principal
    # Nada borra la version instalada antes de tener la nueva entera.
    borrados = [l for l in _seccion("InstallDelete").splitlines() if l.startswith("Type:")]
    assert not any("_internal" in l for l in borrados)
    assert 'Name: "{app}\\_nuevo"' in _seccion("InstallDelete")


def test_se_comprueba_y_se_conmuta_al_final_con_vuelta_atras():
    assert "ssPostInstall" in ISS
    for pieza in ("ComprobarNueva", "Conmutar", "DeshacerConmutacion", "RecuperarConmutacionInterrumpida",
                  "_conmutacion.txt", "--comprobar-rapidfuzz", "WaitForExit"):
        assert pieza in ISS, pieza
    # Se cuentan ficheros y bytes al compilar para saber si la copia esta entera.
    assert "#define FicherosEsperados Contar(Origen, 0)" in ISS
    assert "#define BytesEsperados Contar(Origen, 1)" in ISS
    # Si falla, el setup devuelve error (el envoltorio de la actualizacion automatica abre la
    # version de siempre) y no relanza nada el mismo.
    assert re.search(r"function GetCustomSetupExitCode: Integer;.*?Result := 9", ISS, re.S)
    assert not any("EsActualizacionAutomatica" in l for l in _seccion("Run").splitlines() if l.startswith("Filename"))
    assert "if Completada and EsActualizacionAutomatica then" in ISS
    # El asistente no dice "instalado" cuando no lo esta.
    assert "wpFinished" in ISS and "FinishedHeadingLabel" in ISS


def test_la_marca_de_no_completada_es_la_misma_en_los_dos_lados():
    assert f"MarcaNoCompletada = '{instalacion.MARCA_NO_COMPLETADA}';" in ISS


def test_la_desinstalacion_no_borra_datos_sin_preguntar_y_cierra_farmadex_antes():
    assert "function InitializeUninstall: Boolean;" in ISS and "PedirCierreFarmadex" in ISS
    # En silencio (sin nadie a quien preguntar) los datos se quedan; la respuesta por
    # defecto de la pregunta es "No".
    assert "not UninstallSilent" in ISS
    assert re.search(r"SuppressibleMsgBox\('Borrar tambien tus datos.*?MB_YESNO, IDNO\)", ISS, re.S)
    # El "abrir con Windows" que puso Farmadex por su cuenta no se queda colgando.
    assert "RegDeleteValue(HKCU, 'Software\\Microsoft\\Windows\\CurrentVersion\\Run'" in ISS
    assert 'Type: filesandordirs; Name: "{app}"' in _seccion("UninstallDelete")


def _log(ruta: Path, momento: float, *textos: str) -> None:
    hora = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(momento + 1))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("".join(f"{hora}.123   {t}\n" for t in textos), encoding="utf-8")


def test_el_motivo_de_no_completada_sale_limpio(tmp_path):
    momento = time.time()
    ruta = tmp_path / "instalador.log"
    _log(ruta, momento, "Log opened.", "Installation process succeeded.",
         "No se ha podido completar la instalacion: hay ficheros del programa en uso (_internal). "
         "La version anterior sigue instalada.",
         "Defaulting to OK for suppressed message box (OK):", "Need to restart Windows? No",
         "Deinitializing Setup.", "Log closed.")
    assert instalacion.diagnostico_instalador(momento, ruta) == (
        "detenido", "hay ficheros del programa en uso (_internal)")


def test_el_mutex_lleva_el_sufijo_de_los_datos_de_prueba():
    from farmadex.instancia_unica import _sufijo_datos

    assert instalacion.MUTEX == instalacion.MUTEX_BASE + _sufijo_datos()
    assert instalacion.MUTEX_BASE == "FarmadexEnEjecucion"


def _iscc() -> Path | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base and (Path(base) / "Inno Setup 6" / "ISCC.exe").exists():
            return Path(base) / "Inno Setup 6" / "ISCC.exe"
    return None


@pytest.mark.skipif(os.name != "nt" or _iscc() is None, reason="hace falta Inno Setup 6 en Windows")
def test_el_iss_compila_de_verdad(tmp_path):
    """Compila el .iss real (con otro AppId y otro nombre) sobre una carga de dos ficheros.
    Un error en el Pascal no se ve en ninguna otra prueba: solo al compilar."""
    origen = tmp_path / "carga"
    (origen / "_internal").mkdir(parents=True)
    (origen / "FarmadexPruebaCompila.exe").write_bytes(b"MZ" + b"\0" * 100)
    (origen / "_internal" / "a.txt").write_text("hola", encoding="utf-8")
    salida = tmp_path / "setups"
    r = subprocess.run(
        [str(_iscc()), "/Q", "/DVersionApp=9.9.9", "/DNombreApp=FarmadexPruebaCompila",
         "/DIdApp={{9E2B7C41-5B1A-4F0E-9E1E-PRUEBACOMPIL}", f"/DOrigen={origen}", f"/O{salida}",
         str(RAIZ / "empaquetado" / "instalador.iss")],
        capture_output=True, text=True, timeout=300, cwd=RAIZ / "empaquetado",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert (salida / "FarmadexPruebaCompila-9.9.9-setup.exe").exists()
    shutil.rmtree(salida, ignore_errors=True)
