"""Fin de mision: la cifra con dos digitos pegados delante ("229.254") no se pierde al quitar el
icono, sin aceptar nunca una relectura que no coincida (caso real de Steam, 03/10)."""

import pytest

from farmadex.captura import fin_mision as FM

from test_fin_mision import LINEAS_1080_ES, PLASTIDOS, MotorFalso, _imagen, nombres  # noqa: F401


class MotorSecuencia(MotorFalso):
    """El reconocedor devuelve, por orden, lo de `recortes` (las dos relecturas recortadas y
    luego las dos sin recortar)."""

    def __init__(self, lineas, recortes):
        super().__init__(lineas)
        self.recortes = list(recortes)

    def _cargar(self):
        motor = self

        class Interno:
            @staticmethod
            def text_recognizer(_imagenes):
                return [motor.recortes.pop(0) if motor.recortes else ("", 0.0)], 0.0

        return Interno()


def test_el_corte_del_icono_se_come_cifras_y_la_lectura_entera_las_confirma(nombres):  # noqa: F811
    motor = MotorSecuencia(LINEAS_1080_ES, [("196", 0.8), ("196", 0.8), ("1,196", 0.8), ("1,196", 0.75)])
    placas = FM.leer_imagen(_imagen(), motor, nombres, {PLASTIDOS})
    assert [(p.cantidad, p.motivo) for p in placas] == [(1196, "")]


@pytest.mark.parametrize("enteras", [[("1,196", 0.8), ("1,198", 0.8)], [("1,196", 0.8), ("1,196", 0.1)],
                                     [("11,196", 0.9), ("11,196", 0.9)]])
def test_sin_las_dos_lecturas_enteras_iguales_no_vale(nombres, enteras):  # noqa: F811
    motor = MotorSecuencia(LINEAS_1080_ES, [("196", 0.8), ("196", 0.8)] + enteras)
    placas = FM.leer_imagen(_imagen(), motor, nombres, {PLASTIDOS})
    assert [(p.cantidad, p.motivo) for p in placas] == [(None, FM.CIFRA_DUDOSA)]
