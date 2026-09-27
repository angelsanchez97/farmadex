"""Objetivos: "Recursos de fabricación (x de y listos)" se lee en la fila, sin pasar el raton.

En 0.5 la fila decia debajo del sitio cuantos recursos faltaban; el rediseno C lo dejo solo
en el tooltip de la flecha.
"""

from farmadex.ui.estilo_c import EtiquetaC
from test_objetivos_ui import _fila_de, pestana  # noqa: F401 - pestana es un fixture


def _visible(fila) -> EtiquetaC:
    return fila.enlace_recursos


def test_la_fila_ensena_los_recursos_listos_a_la_vista(pestana, indice_poblado):  # noqa: F811
    con, _, _ = indice_poblado
    mag = con.execute("SELECT id FROM items WHERE unique_name = '/Mag'").fetchone()[0]
    pestana.anadir_item(mag)
    fila = _fila_de(pestana, "Magistar")
    enlace = _visible(fila)
    assert enlace is not None and not enlace.isHidden()
    assert "Recursos de fabricación (0 de 3 listos)" in enlace.text()
    assert "▸" in enlace.text()
    # Pulsarlo abre los recursos, igual que la flecha.
    enlace.linkActivated.emit("recursos:")
    fila = _fila_de(pestana, "Magistar")
    assert not fila.panel_recursos.isHidden() and "▾" in _visible(fila).text()
    fila.completar.click()
    assert "3 de 3 listos" in _visible(_fila_de(pestana, "Magistar")).text()


def test_sin_recursos_no_hay_linea(pestana):  # noqa: F811
    from farmadex.estado import objetivos

    objetivos.anadir(pestana.usuario, "/Suelto", "Suelto", 3)
    pestana.refrescar()
    assert _fila_de(pestana, "Suelto").enlace_recursos is None
