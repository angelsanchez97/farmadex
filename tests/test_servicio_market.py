"""La cola de precios del buscador no atiende peticiones que ya nadie quiere."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


class MercadoFalso:
    def __init__(self):
        self.pedidos = []

    def precios(self, slug):
        self.pedidos.append(slug)
        return slug


def test_las_peticiones_viejas_de_la_cola_se_saltan():
    """Escribir "ash prime" encolaba una peticion por tecla y se atendian todas."""
    from farmadex.online.servicio_market import ServicioMarket

    servicio = ServicioMarket()
    servicio.market = MercadoFalso()
    llegados = []
    servicio.listo.connect(lambda slug, precios: llegados.append(slug))

    # Tres peticiones encoladas; al anotar, la ultima es "ash_prime_set".
    for slug in ("ash", "ash_prime", "ash_prime_set"):
        servicio.anotar(slug)
    for slug in ("ash", "ash_prime", "ash_prime_set"):
        servicio.pedir(slug)

    assert servicio.market.pedidos == ["ash_prime_set"]
    assert llegados == ["ash_prime_set"]


def test_sin_anotar_se_comporta_como_antes():
    from farmadex.online.servicio_market import ServicioMarket

    servicio = ServicioMarket()
    servicio.market = MercadoFalso()
    servicio.pedir("rhino_prime_set")
    assert servicio.market.pedidos == ["rhino_prime_set"]
