"""Pestana Mundo (rediseno C) sin pantalla: sub-pestanas, fisuras por era con las utiles en
dorado, caducadas fuera, Baro, Teshin, Hoy, invasiones y lo que dice cuando no hay datos."""

import os
import re
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QBoxLayout, QLabel  # noqa: E402

from farmadex import idiomas  # noqa: E402
from farmadex.online import avisos_mundo  # noqa: E402
from farmadex.online import worldstate as ws  # noqa: E402
from farmadex.ui import pestana_mundo  # noqa: E402
from farmadex.ui.estilo_c import EtiquetaC  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    from farmadex import config as modulo

    monkeypatch.setattr(modulo, "RUTA_CONFIG", tmp_path / "config.json")
    idiomas.cargar("es")
    yield modulo
    idiomas.cargar("es")


def _en(minutos):
    return datetime.now(timezone.utc) + timedelta(minutes=minutos)


def _mundo(baro_activo=True):
    F = ws.Fisura
    fisuras = [
        F("Neo", "Ukko, Vacio", "Captura", "Corrupto", _en(60)),
        F("Neo", "Cerberus, Pluton", "Intercepcion", "Corpus", _en(90)),
        F("Neo", "Oceanum, Pluton", "Espionaje", "Corpus", _en(20)),
        F("Neo", "Selkie, Sedna", "Supervivencia", "Grineer", _en(90), acero=True),
        F("Lith", "Casini, Ceres", "Captura", "Grineer", _en(5.5)),
        F("Meso", "Encelado, Saturno", "Sabotaje", "Grineer", _en(-5)),  # terminada
        F("Axi", "Ur, Urano", "Sabotaje", "Grineer", _en(50), tormenta=True),
        F("Omnia", "Tuvul, Zariman", "Cascada del Vacio", "Corrupto", _en(40)),
    ]
    inventario = [
        ws.ObjetoBaro("Prisma Gorgon", "/x", 600, 125000, 2, "Gorgon Prisma", "Primary"),
        ws.ObjetoBaro("Sands of Inaros", "/y", 100, 25000, 3, "Arenas de Inaros", "Quests", objetivo=True),
    ]
    baro = ws.Baro("Baro Ki'Teer", "Larunda, Mercurio", baro_activo,
                   llegada=_en(-100) if baro_activo else _en(3000),
                   expira=_en(1000) if baro_activo else _en(3000 + 2880),
                   inventario=inventario if baro_activo else [])
    return ws.Mundo(
        momento=datetime.now(timezone.utc), fisuras=fisuras,
        ciclos=[ws.Ciclo("Cetus", "noche", _en(30), clave="cetusCycle", estado_en="night")],
        invasiones=[ws.Invasion("Marid, Sedna", "Siege", "Corpus", "Grineer", "1x Forma", 40)] * 7,
        sortie=[ws.Recompensa("Hyf, Deimos - Defensa", _en(200), "Bow Only"),
                ws.Recompensa("Ose, Europa - Captura", _en(200))],
        nightwave=[ws.Recompensa("[diario] Uno", _en(100)), ws.Recompensa("[semanal] Dos", _en(900)),
                   ws.Recompensa("[elite] Tres", _en(900))],
        acero=[ws.Recompensa("50,000 Kuva", _en(3000), "55 de esencia")],
        baro_cabecera=baro.cabecera(), baro_detalle=baro,
    )


def _textos(widget) -> list[str]:
    """Los textos de las etiquetas visibles de un panel (el texto entero si esta recortado)."""
    salida = []
    for etiqueta in widget.findChildren(QLabel):
        if etiqueta.isHidden() or etiqueta.parent() is None:
            continue
        salida.append(etiqueta.texto_completo() if isinstance(etiqueta, EtiquetaC) else etiqueta.text())
    return salida


def _plano(widget) -> str:
    return re.sub(r"<[^>]+>", "", " | ".join(_textos(widget)))


def _tarjetas(panel, era=None):
    return [c for c in panel.findChildren(pestana_mundo.TarjetaFisura)
            if c.parent() is not None and not c.isHidden() and (era is None or c.fisura.era == era)]


@pytest.fixture()
def mundo(app):
    pestana = pestana_mundo.PestanaMundo()
    pestana._eras_necesarias = {"Neo": ["Canon de Athodai Prime"]}
    pestana.actualizar(_mundo())
    return pestana


# -- fisuras --------------------------------------------------------------------------


def test_las_terminadas_no_salen_y_las_rapidas_van_primero(mundo):
    panel = mundo.fisuras_todo
    nodos = [c.fisura.nodo for c in _tarjetas(panel)]
    assert not any("Encelado" in n for n in nodos), "una fisura terminada no puede aparecer"
    # Por defecto solo las normales: ni Acero ni Tormenta.
    assert not any("Selkie" in n or "Ur," in n for n in nodos)
    # En su columna, captura (rapida) por delante de espionaje, e intercepcion (sin fin) al final.
    assert [c.fisura.nodo for c in _tarjetas(panel, "Neo")] == ["Ukko, Vacio", "Oceanum, Pluton", "Cerberus, Pluton"]
    # Lo urgente (menos de 10 minutos) va en naranja.
    (casini,) = _tarjetas(panel, "Lith")
    assert "font-weight:bold" in casini.tiempo.text() and "5 min" in casini.tiempo.text()
    # Omnia no tiene columna: va en la nota de abajo.
    assert "Omnia" in _plano(panel) and "Tuvul, Zariman" in _plano(panel)


def test_lo_que_sirve_para_tus_metas_va_con_borde_dorado_y_estrella(mundo):
    neo = _tarjetas(mundo.fisuras_todo, "Neo")
    assert all(c.util for c in neo)
    assert "★ para Canon de Athodai Prime" in re.sub(r"<[^>]+>", "", neo[0].abajo.text())
    (casini,) = _tarjetas(mundo.fisuras_todo, "Lith")
    assert not casini.util and "Grineer" in casini.abajo.text()
    assert "con borde dorado" in _plano(mundo.fisuras_todo)


def test_fisuras_para_tus_metas_ensena_las_mas_rapidas(mundo):
    lineas = [x for x in _textos(mundo.metas) if "Canon de Athodai" in x]
    # Dos por era como mucho, las mas rapidas.
    assert len(lineas) == 2
    assert "Ukko" in lineas[0] and "Oceanum" in lineas[1]
    assert mundo.metas.extra.text() == "2 de 3"


def test_sin_metas_se_explica_y_sin_fisura_util_se_dice_que_hace_falta(mundo):
    mundo._eras_necesarias = {}
    mundo.pintar()
    assert "Añade objetivos en Mis metas" in _plano(mundo.metas)
    assert not any(c.util for c in _tarjetas(mundo.fisuras_todo))
    mundo._eras_necesarias = {"Requiem": ["Reliquia Requiem I"]}
    mundo.pintar()
    assert "Necesitas" in _plano(mundo.metas) and "Requiem" in _plano(mundo.metas)
    assert "Necesitas" in _plano(mundo.fisuras_todo)


def test_los_botones_de_tipo_eligen_normales_acero_y_tormentas(mundo, config):
    assert mundo.botones_modo["normal"].isChecked() and not mundo.botones_modo["acero"].isChecked()
    mundo.botones_modo["acero"].setChecked(True)
    nodos = [c.fisura.nodo for c in _tarjetas(mundo.fisuras_todo)]
    assert "Selkie, Sedna" in nodos
    # Con varios tipos a la vista, la de Acero lo dice.
    selkie = next(c for c in _tarjetas(mundo.fisuras_todo) if c.fisura.nodo == "Selkie, Sedna")
    assert "Acero" in selkie.abajo.text()
    # Los dos paneles (TODO y FISURAS) dicen lo mismo y se recuerda.
    assert mundo.fisuras_completo.botones_modo["acero"].isChecked()
    assert config.cargar()[pestana_mundo.CLAVE_MODOS] == ["normal", "acero"]
    assert pestana_mundo.PestanaMundo().modos_activos() == {"normal", "acero"}
    # Nunca se queda sin ninguno.
    mundo.botones_modo["normal"].setChecked(False)
    mundo.botones_modo["acero"].setChecked(False)
    assert mundo.modos_activos() == {"acero"} and mundo.botones_modo["acero"].isChecked()


def test_todo_limita_las_columnas_y_fisuras_ensena_todas(app):
    pestana = pestana_mundo.PestanaMundo()
    datos = _mundo()
    datos.fisuras = [ws.Fisura("Meso", f"Nodo{i}, Marte", "Captura", "Grineer", _en(60 + i)) for i in range(6)]
    pestana.actualizar(datos)
    assert len(_tarjetas(pestana.fisuras_todo, "Meso")) == pestana_mundo.MAX_POR_COLUMNA
    assert "y 2 más" in _plano(pestana.fisuras_todo)
    assert len(_tarjetas(pestana.fisuras_completo, "Meso")) == 6
    pestana._enlace("sub:fisuras")
    assert pestana.diseno == "fisuras"


def test_un_reloj_que_termina_esconde_su_tarjeta(mundo):
    panel = mundo.fisuras_todo
    tarjeta = _tarjetas(panel, "Lith")[0]
    indice = next(i for i, (e, _f, _o) in enumerate(panel.relojes) if e is tarjeta.tiempo)
    etiqueta, _funcion, ocultar = panel.relojes[indice]
    panel.relojes[indice] = (etiqueta, lambda: None, ocultar)
    panel.refrescar_relojes()
    assert tarjeta.isHidden()


def test_rapidez_de_misiones():
    assert pestana_mundo.rapidez("Captura") < pestana_mundo.rapidez("Espionaje")
    assert pestana_mundo.rapidez("Espionaje") < pestana_mundo.rapidez("Supervivencia")
    assert pestana_mundo.rapidez("Excavación") == pestana_mundo.rapidez("Excavation")
    assert pestana_mundo.rapidez("Algo raro") == 6


def test_tiempo_restante_legible():
    ahora = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    casos = ((45 / 60, "45 s"), (15, "15 min"), (69, "1 h 09 min"), (60 * 51, "2 d 3 h"), (-1, "terminado"))
    for minutos, esperado in casos:
        assert pestana_mundo.tiempo_restante(ahora + timedelta(minutes=minutos), ahora) == esperado


# -- sub-pestanas -----------------------------------------------------------------------


def test_las_sub_pestanas_se_recuerdan_y_lista_o_tablero_abren_todo(app, config):
    pestana = pestana_mundo.PestanaMundo()
    assert pestana.diseno == "todo" and pestana.subpestanas.activa() == "todo"
    cambios = []
    pestana.diseno_cambiado.connect(cambios.append)
    pestana.subpestanas.cambiada.emit("tienda")
    assert pestana.diseno == "tienda" and cambios == ["tienda"]
    assert pestana.vistas.currentWidget() is pestana.vistas_por_clave["tienda"]
    assert config.cargar()["diseno_mundo"] == "tienda"
    assert pestana_mundo.PestanaMundo().diseno == "tienda"
    # Los valores de antes del rediseno (selector Lista/Tablero) abren TODO.
    datos = config.cargar()
    datos["diseno_mundo"] = "tablero"
    config.guardar(datos)
    vieja = pestana_mundo.PestanaMundo()
    assert vieja.diseno == "todo" and config.cargar()["diseno_mundo"] == "todo"
    assert pestana_mundo.PestanaMundo(diseno="lista").diseno == "todo"
    vieja.cambiar_diseno("fisuras")
    assert vieja.diseno == "fisuras"


def test_cambia_de_idioma(mundo):
    assert mundo.fisuras_todo.title() == "Fisuras del Vacío"
    idiomas.cargar("en")
    mundo.retraducir()
    assert mundo.fisuras_todo.title() == "Void Fissures"
    assert mundo.metas.title() == "Fissures for your goals"
    assert mundo.botones_modo["acero"].text() == "Steel Path"
    assert mundo.subpestanas.entrada("tienda").text() == "Baro and Teshin"


def test_en_ventana_estrecha_los_paneles_se_apilan(mundo):
    mundo.resize(1400, 800)
    mundo._reordenar()
    assert all(capa.direction() == QBoxLayout.LeftToRight for capa, _u in mundo._reflujo)
    mundo.resize(760, 600)
    mundo._reordenar()
    assert all(capa.direction() == QBoxLayout.TopToBottom for capa, _u in mundo._reflujo)


# -- Baro y Teshin ----------------------------------------------------------------------


def test_baro_presente_con_inventario_y_lo_de_tus_metas_primero(mundo):
    tienda = _textos(mundo.baro_tienda)
    assert any(x.startswith("SE VA EN") for x in tienda)
    lineas = [x for x in tienda if "ducados" in x]
    assert "Arenas de Inaros" in lineas[0] and "cubre un objetivo" in lineas[0]
    assert "600 ducados" in lineas[1]
    # En TODO solo lo que te sirve, y un enlace a verlo todo.
    todo = _plano(mundo.baro_todo)
    assert "Arenas de Inaros" in todo and "Gorgon Prisma" not in todo
    assert "Trae 2 cosas; 1 te sirven" in todo
    assert any("href='sub:tienda'" in x for x in _textos(mundo.baro_todo))


def test_baro_ausente_cuenta_atras_y_boton_de_avisar(mundo, config):
    mundo.actualizar(_mundo(baro_activo=False))
    textos = _textos(mundo.baro_todo)
    assert any(x.startswith("LLEGA EN 2 D") for x in textos)
    assert any("se queda 2 días" in x for x in textos)
    boton = next(b for b in mundo.baro_todo.findChildren(pestana_mundo.BotonC) if b.property("clave_aviso") == "baro")
    boton.setChecked(True)
    assert config.cargar()[avisos_mundo.CLAVE_CONFIG]["baro"] is True
    # Personalizar dice lo mismo.
    assert mundo.pagina_ajustes.casillas["baro"].isChecked()


def test_baro_que_ya_se_ha_ido_lo_dice(mundo):
    datos = _mundo()
    datos.baro_detalle.expira = _en(-5)
    mundo.actualizar(datos)
    assert any("YA SE HA IDO" in x for x in _textos(mundo.baro_tienda))


def test_los_enlaces_de_baro_abren_la_ficha(mundo):
    recibidos = []
    mundo.abrir_item.connect(recibidos.append)
    mundo.baro_tienda._activar("item:2")
    assert recibidos == [2]
    assert any("href='item:3'" in x for x in _textos(mundo.baro_tienda))


def test_teshin_de_la_api_con_su_coste_y_las_proximas_semanas(mundo):
    textos = _plano(mundo.teshin_tienda)
    assert "50.000 de Kuva" in textos and "55 de esencia" in textos
    assert "rotación semanal fija" not in textos  # lo ha publicado la API: dato seguro
    # Despues de la Kuva viene el mod agrietado de kitgun (orden fijo del juego).
    assert "Mod Agrietado de kitgun" in textos and "3 Formas" in textos
    assert "Palladino" in textos
    assert "Mod Agrietado de kitgun" not in _plano(mundo.teshin_todo)


def test_teshin_sin_dato_de_la_api_lo_dice(mundo):
    datos = _mundo()
    datos.acero = []
    mundo.actualizar(datos)
    assert "rotación semanal fija" in _plano(mundo.teshin_todo)


def test_teshin_desconocido_no_inventa_las_semanas_siguientes():
    ahora = datetime.now(timezone.utc)
    mundo = ws.Mundo(acero=[ws.Recompensa("Algo nuevo", ahora + timedelta(days=2))])
    assert avisos_mundo.teshin_actual(mundo, ahora)[2] == "api"
    assert avisos_mundo.teshin_siguientes(mundo, ahora) is None
    conocido = ws.Mundo(acero=[ws.Recompensa("Umbra Forma Blueprint", ahora + timedelta(days=2))])
    siguientes = avisos_mundo.teshin_siguientes(conocido, ahora, 2)
    assert [n for n, _ in siguientes] == ["50,000 Kuva", "Kitgun Riven Mod"]
    assert siguientes[0][1] == ahora + timedelta(days=2)
    assert avisos_mundo.teshin_actual(ws.Mundo(), ahora)[2] == "rotacion"


# -- Hoy, invasiones, alertas, ciclos --------------------------------------------------------


def test_hoy_resume_incursion_arcontes_onda_nocturna_y_arbitraje(mundo):
    textos = _plano(mundo.hoy)
    assert "Hyf, Deimos y 1 más" in textos
    assert "1 diario · 2 semanales" in textos
    assert textos.count("sin publicar ahora") == 2  # arcontes y arbitraje
    mundo._enlace("sub:eventos")
    assert mundo.diseno == "eventos"


def test_las_invasiones_se_resumen_en_todo_y_salen_enteras_en_su_pestana(mundo):
    todo = _textos(mundo.invasiones_todo)
    assert sum("Marid" in x for x in todo) == pestana_mundo.MAX_INVASIONES
    assert "y 3 invasiones más" in _plano(mundo.invasiones_todo)
    assert sum("Marid" in x for x in _textos(mundo.invasiones_eventos)) == 7
    assert mundo.invasiones_todo.findChildren(pestana_mundo.BarraBandos)


def test_sin_alertas_lo_dice_y_ofrece_avisar(mundo):
    assert "Ahora no hay ninguna alerta." in _plano(mundo.alertas_todo)
    assert any(b.property("clave_aviso") == "alertas" for b in mundo.alertas_todo.findChildren(pestana_mundo.BotonC))


def test_ciclos_con_su_cuenta_atras(mundo):
    textos = _textos(mundo.ciclos)
    assert "Cetus" in textos and "noche" in textos and any(x.endswith("min") for x in textos)


# -- que dice la pestana cuando no hay nada que pintar ----------------------------


def test_con_datos_frescos_y_filtro_que_no_deja_pasar_nada_se_culpa_al_filtro(mundo):
    mundo.acciones_faccion["infested"].setChecked(True)
    texto = _plano(mundo.fisuras_todo)
    assert "ninguna pasa el filtro" in texto and "Normales" in texto
    assert "7 fisuras abiertas" in texto  # las 8 del ejemplo menos la terminada
    assert mundo.aviso.text() == ""
    assert mundo.estado_datos() == "fresco"


def test_con_datos_frescos_y_de_verdad_sin_fisuras_no_se_menciona_el_filtro(app):
    pestana = pestana_mundo.PestanaMundo()
    datos = _mundo()
    datos.fisuras = []
    pestana.actualizar(datos)
    assert "Ahora mismo no hay ninguna fisura abierta" in _plano(pestana.fisuras_todo)


def test_con_la_api_desfasada_se_dice_de_cuando_son_los_datos(app):
    pestana = pestana_mundo.PestanaMundo()
    pestana._eras_necesarias = {"Neo": ["Canon de Athodai Prime"]}
    datos = _mundo()
    datos.momento = datetime.now(timezone.utc) - timedelta(hours=2, minutes=10)
    for f in datos.fisuras:
        f.expira = _en(-60)  # todas caducadas, como el 2026-09-22
    datos.ciclos = []
    datos.sortie = []
    pestana.actualizar(datos)
    assert pestana.estado_datos() == "viejo"
    assert pestana.aviso.text() == "El estado del mundo que publica la API es de hace 2 h 10 min"
    for bloque in (pestana.fisuras_todo, pestana.ciclos, pestana.sortie, pestana.metas, pestana.teshin_todo):
        texto = _plano(bloque)
        assert "es de hace 2 h 10 min" in texto, (bloque.clave, texto)
        assert "filtro" not in texto
    # El aviso del servicio ("la API devuelve datos de hace N min") no lo tapa.
    pestana.marcar_desactualizado("la API devuelve datos de hace 130 min")
    assert "hace 2 h 10 min" in pestana.aviso.text()
    assert "es de hace 2 h 10 min" in _plano(pestana.fisuras_todo)
    # Y en ingles cambia el texto, no la logica.
    idiomas.cargar("en")
    pestana.retraducir()
    assert "2 h 10 min old" in pestana.aviso.text()


def test_la_edad_se_escribe_en_minutos_u_horas(app):
    pestana = pestana_mundo.PestanaMundo()
    datos = _mundo()
    for minutos, esperado in ((35, "35 min"), (120, "2 h"), (61, "1 h 1 min")):
        datos.momento = datetime.now(timezone.utc) - timedelta(minutes=minutos, seconds=5)
        pestana.mundo = datos
        assert pestana._edad() == esperado


def test_con_datos_frescos_el_pie_dice_de_cuando_son(mundo):
    assert mundo.pie.text() == "Datos del juego de hace 0 min · se actualiza solo cada minuto"


def test_si_la_consulta_fallo_y_no_hay_nada_se_dice_el_motivo(app):
    pestana = pestana_mundo.PestanaMundo()
    pestana.marcar_desactualizado("HTTP 502")
    assert pestana.estado_datos() == "fallo"
    assert "HTTP 502" in pestana.aviso.text()
    assert "No se ha podido consultar el estado del mundo (HTTP 502)" in _plano(pestana.fisuras_todo)


def test_si_la_consulta_falla_con_datos_frescos_se_ensena_lo_ultimo(mundo):
    mundo.marcar_desactualizado("HTTP 502")
    assert mundo.estado_datos() == "fresco"
    assert "lo último conocido" in mundo.aviso.text()
    assert _tarjetas(mundo.fisuras_todo, "Lith")


def test_con_el_respaldo_de_de_se_avisa_en_suave(app):
    pestana = pestana_mundo.PestanaMundo()
    datos = _mundo()
    datos.fuente = "de"
    pestana.actualizar(datos)
    assert "worldState oficial de DE" in pestana.aviso.text()


def test_el_mundo_escondido_se_pinta_al_ensenarse():
    """El estado del mundo llega cada poco y pintarlo cuesta ~40 ms en el hilo de la
    ventana: con la seccion Mundo sin verse se deja para cuando se ensene."""
    from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

    from farmadex.ui.pestana_mundo import PestanaMundo

    QApplication.instance() or QApplication([])
    pila = QStackedWidget()
    otra = QWidget()
    pestana = PestanaMundo()
    pila.addWidget(otra)
    pila.addWidget(pestana)
    pila.setCurrentWidget(otra)
    pila.show()
    pintadas = []
    original = pestana.pintar
    pestana.pintar = lambda: pintadas.append(1) or original()
    pestana.actualizar(_mundo())
    assert pintadas == [] and pestana.mundo is not None
    pila.setCurrentWidget(pestana)
    assert pintadas == [1]
    pila.setCurrentWidget(otra)
    pila.setCurrentWidget(pestana)
    assert pintadas == [1]  # sin datos nuevos no se repinta
    pila.hide()
