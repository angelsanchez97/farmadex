"""Comprobaciones estaticas de la receta de PyInstaller y del instalador.

No compilan nada: miran que lo que el codigo carga en tiempo de ejecucion este
en la receta, que es justo lo que rompio el OCR la primera vez que se congelo.
"""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SPEC = (RAIZ / "empaquetado" / "farmadex.spec").read_text(encoding="utf-8")
ISS = (RAIZ / "empaquetado" / "instalador.iss").read_text(encoding="utf-8")
PS1 = (RAIZ / "empaquetado" / "construir.ps1").read_text(encoding="utf-8")
SRC = RAIZ / "src" / "farmadex"


def test_el_paquete_de_ocr_que_importa_el_codigo_va_entero_en_la_receta():
    codigo = (SRC / "captura" / "ocr.py").read_text(encoding="utf-8")
    paquetes = set(re.findall(r"^\s*(?:from|import)\s+(rapidocr\w*)", codigo, re.M))
    assert paquetes, "ocr.py ya no importa ningun rapidocr*: revisar la receta"
    for paquete in paquetes:
        assert f'collect_all("{paquete}")' in SPEC, f"falta collect_all de {paquete} en el .spec"


def test_todo_recurso_no_python_del_paquete_esta_en_la_receta():
    recursos = [
        r for r in SRC.rglob("*")
        if r.is_file() and r.suffix != ".py" and "__pycache__" not in r.parts
    ]
    assert recursos
    for recurso in recursos:
        relativo = recurso.relative_to(RAIZ).as_posix()
        assert relativo in SPEC, f"{relativo} no esta en los datos del .spec"


def test_los_catalogos_de_idiomas_y_el_icono_van_dentro():
    assert "recursos/idiomas" in SPEC
    assert "recursos/iconos/farmadex.ico" in SPEC
    assert (RAIZ / "recursos" / "iconos" / "farmadex.ico").exists()


def test_los_modulos_que_se_cargan_por_nombre_estan_como_ocultos():
    for oculto in ("mss.windows", "onnxruntime.capi._pybind_state", "farmadex.app"):
        assert f'"{oculto}"' in SPEC


def test_el_arranque_congelado_llama_al_mismo_main():
    arranque = (RAIZ / "empaquetado" / "arranque.py").read_text(encoding="utf-8")
    assert "from farmadex.app import main" in arranque
    assert "empaquetado/arranque.py" in SPEC


def test_el_instalador_lleva_el_runtime_de_visual_c_y_el_script_lo_descarga():
    """Qt y ONNX Runtime necesitan el VC++ 2015-2022: sin el, en un Windows limpio
    el programa no abre. El .iss lo instala si falta y construir.ps1 lo baja si no esta."""
    assert "vc_redist.x64.exe" in ISS
    assert "FaltaVCRedist" in ISS
    assert "vc_redist.x64.exe" in PS1
    assert "aka.ms/vs/17/release/vc_redist.x64.exe" in PS1


def test_el_instalador_no_pide_administrador_y_va_por_usuario():
    assert "PrivilegesRequired=lowest" in ISS
    assert "{localappdata}\\Programs" in ISS
    manifiesto = (RAIZ / "empaquetado" / "manifiesto.xml").read_text(encoding="utf-8")
    assert 'level="asInvoker"' in manifiesto


def test_los_scripts_de_empaquetado_no_llevan_caracteres_de_control():
    """Una ruta "empaquetado\vc_redist" escrita desde Python se convirtio en un
    tabulador vertical: el script paraba en Test-Path justo antes del instalador."""
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "empaquetado"
    for fichero in list(raiz.glob("*.ps1")) + list(raiz.glob("*.iss")) + list(raiz.glob("*.spec")):
        malos = re.findall(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", fichero.read_bytes())
        assert not malos, f"{fichero.name} lleva caracteres de control: {malos}"
