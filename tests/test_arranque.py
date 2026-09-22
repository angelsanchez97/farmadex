"""Inicio con Windows: alta y baja en HKCU\\...\\Run con la escritura inyectada (nunca el registro real)."""

from __future__ import annotations

import sys

from farmadex import arranque


class RegistroFalso:
    def __init__(self):
        self.valores: dict[str, str] = {}

    def escribir(self, nombre, comando):
        self.valores[nombre] = comando

    def borrar(self, nombre):
        self.valores.pop(nombre, None)

    def leer(self, nombre):
        return self.valores.get(nombre)


def test_comando_apunta_al_exe_con_bandeja_y_nada_desde_el_codigo(monkeypatch):
    assert arranque.comando_arranque(r"C:\Programas\Farmadex\Farmadex.exe") == (
        r'"C:\Programas\Farmadex\Farmadex.exe" --bandeja'
    )
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert arranque.comando_arranque() is None


def test_activar_y_desactivar_pasan_por_la_escritura_inyectada():
    reg = RegistroFalso()
    assert arranque.activar('"C:\\x\\Farmadex.exe" --bandeja', escribir=reg.escribir)
    assert reg.valores == {arranque.NOMBRE_VALOR: '"C:\\x\\Farmadex.exe" --bandeja'}
    assert arranque.esta_activo(leer=reg.leer)
    assert arranque.desactivar(borrar=reg.borrar)
    assert reg.valores == {}
    assert not arranque.esta_activo(leer=reg.leer)
    assert arranque.desactivar(borrar=reg.borrar)  # quitar lo que no esta no es un fallo


def test_sincronizar_sigue_al_ajuste(monkeypatch):
    reg = RegistroFalso()
    monkeypatch.delattr(sys, "frozen", raising=False)
    # Desde el codigo no hay comando: activar no puede y lo dice con False.
    assert arranque.sincronizar(True, escribir=reg.escribir, borrar=reg.borrar, leer=reg.leer) is False
    assert reg.valores == {}
    assert arranque.sincronizar(True, comando='"x.exe" --bandeja', escribir=reg.escribir, leer=reg.leer)
    assert arranque.NOMBRE_VALOR in reg.valores
    assert arranque.sincronizar(False, escribir=reg.escribir, borrar=reg.borrar, leer=reg.leer)
    assert reg.valores == {}


def test_un_registro_que_falla_no_revienta():
    def reventar(*a):
        raise OSError("acceso denegado")

    assert arranque.activar('"x.exe" --bandeja', escribir=reventar) is False
    assert arranque.desactivar(borrar=reventar) is False
    assert arranque.esta_activo(leer=reventar) is False


def test_el_argumento_de_bandeja_se_reconoce():
    assert arranque.arrancado_en_bandeja(["Farmadex.exe", "--bandeja"])
    assert not arranque.arrancado_en_bandeja(["Farmadex.exe"])


def test_en_bandeja_no_se_muestra_la_ventana(monkeypatch):
    """`Aplicacion.ejecutar` con en_bandeja=True no llama a `ventana.mostrar`."""
    from farmadex import app as modulo_app

    llamadas = []

    class Ventana:
        def mostrar(self):
            llamadas.append("mostrar")

    class Qt:
        def exec(self):
            return 0

    aplicacion = modulo_app.Aplicacion.__new__(modulo_app.Aplicacion)
    aplicacion.log = modulo_app.obtener("prueba")
    aplicacion.ventana = Ventana()
    aplicacion.qt = Qt()
    aplicacion.en_bandeja = True
    assert aplicacion.ejecutar() == 0
    assert llamadas == []
    aplicacion.en_bandeja = False
    aplicacion.ejecutar()
    assert llamadas == ["mostrar"]
