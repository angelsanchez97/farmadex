"""El registro no puede quedarse mudo en silencio.

En el ejecutable sin consola `sys.stderr` es None y `logging` traga los fallos de
sus handlers sin decir nada. Aqui se comprueba que un fallo al escribir queda
apuntado en `registro_errores.txt`, que el fichero se reabre, que la cabecera dice
version y ruta, y que si AppData esta redirigido (contenedor) se avisa.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

from farmadex import NOMBRE_APP, VERSION
from farmadex import registro_log


@pytest.fixture()
def registro_limpio(tmp_path, monkeypatch):
    """Un `configurar()` desde cero sobre `tmp_path`, sin tocar el logger global de la suite."""
    raiz = logging.getLogger("prueba-registro")
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
    monkeypatch.setattr(registro_log, "_configurado", False)
    monkeypatch.setattr(registro_log, "_fallos", 0)
    monkeypatch.setattr(registro_log, "_ultimo_fallo", None)
    monkeypatch.setattr(registro_log, "RUTA_LOG", tmp_path / "logs" / "farmadex.log")
    monkeypatch.setattr(registro_log, "RUTA_ERRORES_REGISTRO", tmp_path / "logs" / "registro_errores.txt")
    monkeypatch.setattr(registro_log, "crear_carpetas", lambda: (tmp_path / "logs").mkdir(exist_ok=True))
    monkeypatch.setattr(registro_log, "NOMBRE_APP", "prueba-registro")
    yield tmp_path
    for h in list(raiz.handlers):
        h.close()
        raiz.removeHandler(h)


def _lineas(ruta: Path) -> list[str]:
    return ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []


def test_la_cabecera_dice_version_ruta_y_pid(registro_limpio):
    raiz = registro_log.configurar()
    lineas = _lineas(registro_limpio / "logs" / "farmadex.log")
    assert len(lineas) >= 1
    assert VERSION in lineas[0] and str(registro_limpio / "logs" / "farmadex.log") in lineas[0]
    assert f"pid {os.getpid()}" in lineas[0] and "codigo sin congelar" in lineas[0]
    assert raiz.handlers and isinstance(raiz.handlers[0], registro_log.FicheroRotativoSeguro)


def test_sin_stderr_no_hay_handler_de_consola_y_el_fichero_sigue(registro_limpio, monkeypatch):
    """Como en el .exe sin consola: stderr None. Nada de StreamHandler(None) mudo."""
    monkeypatch.setattr(sys, "stderr", None)
    raiz = registro_log.configurar()
    assert all(not isinstance(h, logging.StreamHandler) or isinstance(h, logging.FileHandler) for h in raiz.handlers)
    registro_log.obtener("x").info("hola sin consola")
    assert any("hola sin consola" in l for l in _lineas(registro_limpio / "logs" / "farmadex.log"))
    assert registro_log.fallos_del_registro() == (0, None)


def test_un_fallo_al_escribir_se_apunta_y_el_fichero_se_reabre(registro_limpio, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)  # como en el .exe: logging no imprimiria nada
    raiz = registro_log.configurar()
    fichero = raiz.handlers[0]
    log = registro_log.obtener("x")

    # El stream se rompe por debajo (handle cerrado, disco...): la linea se pierde,
    # pero queda constancia y la siguiente vuelve a entrar.
    class Roto:
        def write(self, *_):
            raise OSError(22, "Invalid argument")

        def flush(self):
            pass

        def close(self):
            pass

        def tell(self):  # RotatingFileHandler mira el tamano antes de escribir
            return 1

        def seek(self, *_):
            pass

    fichero.stream = Roto()
    log.info("esta se pierde")
    log.info("esta ya entra")

    errores = (registro_limpio / "logs" / "registro_errores.txt").read_text(encoding="utf-8")
    assert "fallo 1 del registro" in errores and "Invalid argument" in errores
    assert "Linea perdida: prueba-registro.x INFO: esta se pierde" in errores
    n, ultimo = registro_log.fallos_del_registro()
    assert n == 1 and "Invalid argument" in (ultimo or "")
    lineas = _lineas(registro_limpio / "logs" / "farmadex.log")
    assert any("esta ya entra" in l for l in lineas) and not any("esta se pierde" in l for l in lineas)


def test_si_no_se_puede_abrir_el_fichero_se_arranca_igual_y_se_dice(registro_limpio, monkeypatch):
    def abrir_roto(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(registro_log, "FicheroRotativoSeguro", abrir_roto)
    raiz = registro_log.configurar()  # no lanza
    assert not any(isinstance(h, logging.FileHandler) for h in raiz.handlers)
    errores = (registro_limpio / "logs" / "registro_errores.txt").read_text(encoding="utf-8")
    assert "Permission denied" in errores and "abrir" in errores


def test_apuntar_fallos_tiene_techo_pero_sigue_contando(registro_limpio, monkeypatch):
    monkeypatch.setattr(registro_log, "MAX_FALLOS_APUNTADOS", 2)
    ruta = registro_limpio / "logs" / "registro_errores.txt"
    ruta.parent.mkdir(exist_ok=True)
    for i in range(4):
        registro_log.apuntar_fallo_registro("prueba", f"detalle {i}")
    texto = ruta.read_text(encoding="utf-8")
    assert "detalle 0" in texto and "detalle 1" in texto and "detalle 2" not in texto
    assert registro_log.fallos_del_registro()[0] == 4


@pytest.mark.skipif(os.name != "nt", reason="GetFinalPathNameByHandle es de Windows")
def test_ruta_real_resuelve_por_handle(tmp_path):
    fichero = tmp_path / "a.log"
    fichero.write_text("x")
    real = registro_log.ruta_real(fichero)
    assert real is not None and os.path.normcase(str(real)) == os.path.normcase(str(fichero.resolve()))
    assert registro_log.ruta_real(tmp_path / "no-existe.log") is None


def test_se_avisa_si_el_registro_esta_redirigido(registro_limpio, monkeypatch):
    """AppData virtualizado (contenedor): la ruta es la misma pero el fichero no es
    el del usuario. La cabecera lo tiene que gritar."""
    otro = Path("C:/Users/x/AppData/Local/Packages/Claude_abc/LocalCache/Local/Farmadex/logs/farmadex.log")
    monkeypatch.setattr(registro_log, "ruta_real", lambda ruta: otro)
    registro_log.configurar()
    lineas = _lineas(registro_limpio / "logs" / "farmadex.log")
    assert any("REDIRIGIDO" in l and "LocalCache" in l and "NO es el registro" in l for l in lineas)


def test_sin_redireccion_no_se_avisa(registro_limpio, monkeypatch):
    monkeypatch.setattr(registro_log, "ruta_real", lambda ruta: (registro_limpio / "logs" / "farmadex.log").resolve())
    registro_log.configurar()
    assert not any("REDIRIGIDO" in l for l in _lineas(registro_limpio / "logs" / "farmadex.log"))


def test_probar_ocr_deja_claro_en_el_log_que_no_es_una_sesion(monkeypatch):
    """`Farmadex.exe --probar-ocr` escribe dos lineas y sale: que no se confunda con
    una sesion que se quedo muda."""
    from farmadex import app

    escritas = []
    monkeypatch.setattr(app, "probar_ocr", lambda: 0)
    monkeypatch.setattr(app, "obtener", lambda nombre: type("L", (), {"info": lambda self, m, *a: escritas.append(m % a)})())
    assert app.main(["Farmadex.exe", "--probar-ocr"]) == 0
    assert any("--probar-ocr" in m and "sale" in m for m in escritas)
