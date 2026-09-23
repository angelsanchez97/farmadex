"""Lo que el vigilante de EE.log cuenta de si mismo para el diagnostico, y la ruta por defecto."""

from farmadex.registro.eelog import VigilanteEELog, leer_lineas
from test_eelog import ABIERTA, GOT


def test_el_estado_dice_si_el_fichero_existe_y_que_se_ha_leido(tmp_path):
    ruta = tmp_path / "EE.log"
    vigilante = VigilanteEELog(ruta)
    estado = vigilante.estado()
    assert estado.ruta == str(ruta) and not estado.existe and estado.lineas == 0

    ruta.write_bytes((ABIERTA + "\n" + GOT + "\n").encode("utf-8"))
    # Lo que hace `run` en una pasada, sin arrancar el hilo.
    lineas, _posicion = leer_lineas(ruta, 0)
    vigilante._estado.lineas += len(lineas)
    vigilante._procesar(lineas)
    estado = vigilante.estado()
    assert estado.existe and estado.tamano == ruta.stat().st_size
    assert estado.lineas == 2 and estado.eventos == 2
    assert estado.ultimo_evento == "reliquia_recompensas" and estado.ultimo_evento_en is not None
    # Ninguna linea del fichero viaja en el estado (correo, IP, id de jugador).
    assert "ProjectionRewardChoice" not in repr(estado)
    # Es una copia: tocarla no cambia lo que ve el hilo.
    estado.lineas = 999
    assert vigilante.estado().lineas == 2


def test_si_la_ruta_configurada_no_existe_se_pasa_a_la_de_siempre(tmp_path):
    """config.json copiado de otro equipo: antes se esperaba para siempre en silencio."""
    de_siempre = tmp_path / "Warframe" / "EE.log"
    de_siempre.parent.mkdir()
    de_siempre.write_bytes(b"cabecera\n")
    vigilante = VigilanteEELog(tmp_path / "otra" / "EE.log", ruta_por_defecto=de_siempre)
    assert vigilante._cambiar_a_la_ruta_por_defecto()
    assert vigilante.ruta == de_siempre
    assert vigilante.estado().ruta == str(de_siempre)
    # Si tampoco existe la de siempre, no hay a que cambiar.
    otro = VigilanteEELog(tmp_path / "otra" / "EE.log", ruta_por_defecto=tmp_path / "nada" / "EE.log")
    assert not otro._cambiar_a_la_ruta_por_defecto()
    assert otro.ruta == tmp_path / "otra" / "EE.log"
    # Y sin ruta por defecto (pruebas, codigo viejo) tampoco.
    assert not VigilanteEELog(tmp_path / "otra" / "EE.log")._cambiar_a_la_ruta_por_defecto()
