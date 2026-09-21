import sys

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


def test_el_motivo_distingue_el_atajo_ocupado_de_otros_errores():
    from farmadex.hotkeys import ERROR_HOTKEY_ALREADY_REGISTERED, motivo_registro

    assert "otro programa" in motivo_registro(ERROR_HOTKEY_ALREADY_REGISTERED, "Ctrl+Alt+W")
    otro = motivo_registro(1400, "Ctrl+Alt+W")
    assert "otro programa" not in otro and "1400" in otro


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="RegisterHotKey es de Windows")
def test_un_atajo_que_ya_tiene_otro_programa_se_avisa_no_se_calla():
    """Se registra la combinacion desde fuera y el gestor tiene que decir que esta ocupada."""
    import ctypes
    import time

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from farmadex.hotkeys import GestorHotkeys, parsear

    QApplication.instance() or QApplication([])
    combinacion = "Ctrl+Alt+Shift+F12"
    modificadores, tecla = parsear(combinacion)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    identificador = 0x7A11
    if not user32.RegisterHotKey(None, identificador, modificadores, tecla):
        pytest.skip("esta maquina ya tiene ocupado el atajo de prueba")
    fallos = []
    registrados = []
    gestor = GestorHotkeys({"ocupado": combinacion, "libre": "Ctrl+Alt+Shift+F11"})
    gestor.fallo.connect(lambda n, m: fallos.append((n, m)), Qt.DirectConnection)
    try:
        gestor.start()
        # El registro pasa nada mas arrancar el hilo; el bucle de mensajes viene despues.
        limite = time.monotonic() + 3
        while time.monotonic() < limite and not gestor._ids:
            time.sleep(0.02)
        registrados = list(gestor._ids.values())
    finally:
        gestor.parar()
        user32.UnregisterHotKey(None, identificador)
    assert [n for n, _ in fallos] == ["ocupado"]
    assert "otro programa" in fallos[0][1]
    assert registrados == ["libre"]
    assert not gestor.isRunning()
