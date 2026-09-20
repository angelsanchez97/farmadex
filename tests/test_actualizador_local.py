"""Las versiones nuevas se recogen de la carpeta donde se compilan."""

import pytest

from farmadex.actualizador import local


def crear(carpeta, *nombres):
    for nombre in nombres:
        (carpeta / nombre).write_bytes(b"x")
    return carpeta


def test_encuentra_una_version_posterior(tmp_path):
    crear(tmp_path, "Farmadex-0.2.0-setup.exe")
    version = local.buscar(tmp_path, "0.1.0")
    assert version.etiqueta == "0.2.0"
    assert version.url.endswith("Farmadex-0.2.0-setup.exe")


def test_ignora_la_misma_version_y_las_anteriores(tmp_path):
    crear(tmp_path, "Farmadex-0.1.0-setup.exe", "Farmadex-0.0.9-setup.exe")
    assert local.buscar(tmp_path, "0.1.0") is None


def test_se_queda_con_la_mas_alta_por_numero(tmp_path):
    crear(tmp_path, "Farmadex-0.9.0-setup.exe", "Farmadex-0.10.0-setup.exe")
    assert local.buscar(tmp_path, "0.1.0").etiqueta == "0.10.0"


def test_prefiere_el_instalador_al_zip(tmp_path):
    crear(tmp_path, "Farmadex-0.2.0-portable.zip", "Farmadex-0.2.0-setup.exe")
    assert local.buscar(tmp_path, "0.1.0").url.endswith(".exe")


def test_el_zip_vale_si_no_hay_instalador(tmp_path):
    crear(tmp_path, "Farmadex-0.2.0-portable.zip")
    assert local.buscar(tmp_path, "0.1.0").url.endswith(".zip")


def test_ignora_lo_que_no_sea_un_artefacto(tmp_path):
    crear(tmp_path, "notas.txt", "Farmadex.exe", "OtroPrograma-9.9.9-setup.exe")
    assert local.buscar(tmp_path, "0.1.0") is None


def test_carpeta_inexistente(tmp_path):
    assert local.buscar(tmp_path / "no-existe", "0.1.0") is None


def test_las_notas_salen_del_changelog(tmp_path):
    crear(tmp_path, "Farmadex-0.2.0-setup.exe")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Cambios\n\n## 0.2.0\n\n- Arreglado el OCR\n\n## 0.1.0\n\n- Primera\n",
        encoding="utf-8",
    )
    assert "Arreglado el OCR" in local.buscar(tmp_path, "0.1.0").notas


@pytest.mark.parametrize("nombre", ["Farmadex-0.2-setup.exe", "farmadex-setup.exe"])
def test_nombres_mal_formados(tmp_path, nombre):
    crear(tmp_path, nombre)
    assert local.buscar(tmp_path, "0.1.0") is None
