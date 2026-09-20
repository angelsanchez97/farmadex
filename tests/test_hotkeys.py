import pytest

from farmadex.hotkeys import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, parsear


def test_combinacion_normal():
    modificadores, tecla = parsear("Ctrl+Alt+W")
    assert modificadores == MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
    assert tecla == ord("W")


def test_no_distingue_mayusculas_ni_espacios():
    assert parsear("ctrl + shift + q") == (MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, ord("Q"))


def test_teclas_con_nombre():
    assert parsear("Alt+F5")[1] == 0x74
    assert parsear("Ctrl+Espacio")[1] == 0x20


@pytest.mark.parametrize(
    "combinacion",
    ["", "W", "Ctrl", "Ctrl+Alt+W+Q", "Ctrl+tecla_inventada"],
)
def test_combinaciones_invalidas(combinacion):
    with pytest.raises(ValueError):
        parsear(combinacion)
