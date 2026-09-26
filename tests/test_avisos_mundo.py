"""Avisos de Windows del mundo: que se avisa segun lo marcado, y nada dos veces."""

from datetime import datetime, timedelta, timezone

from farmadex import idiomas
from farmadex.online import avisos_mundo as am
from farmadex.online import worldstate as ws

AHORA = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _en(minutos):
    return AHORA + timedelta(minutes=minutos)


def _mundo():
    idiomas.cargar("es")
    F = ws.Fisura
    baro = ws.Baro("Baro Ki'Teer", "Larunda, Mercurio", True, _en(-60), _en(2000), [
        ws.ObjetoBaro("Primed Flow", "/Mods/PrimedFlow", 350, 100000, 5, "Flujo Prime", objetivo=True),
    ])
    return ws.Mundo(
        momento=AHORA,
        fisuras=[
            F("Meso", "Hydron, Sedna", "Cascada del Vacio", "Grineer", _en(40), modo="Void Cascade", faccion="Grineer"),
            F("Meso", "Ose, Europa", "Cascada del Vacio", "Corpus", _en(40), acero=True, modo="Void Cascade",
              faccion="Corpus"),
            F("Lith", "Casini, Ceres", "Captura", "Grineer", _en(30), modo="Capture", faccion="Grineer"),
            F("Axi", "Ur, Urano", "Captura", "Grineer", _en(-5), modo="Capture"),  # terminada
            F("Neo", "Proxima", "Exterminio", "Grineer", _en(50), tormenta=True, modo="Extermination"),
        ],
        ciclos=[ws.Ciclo("Cetus", "noche", _en(20), clave="cetusCycle", estado_en="night")],
        invasiones=[
            ws.Invasion("Selkie, Sedna", "Asedio", "Corpus", "Grineer", "Orokin Catalyst Blueprint", 40, objetos=[
                ws.ObjetoPremio("Orokin Catalyst Blueprint", 1, item_id=9, nombre_es="Plano de Catalizador Orokin")]),
            ws.Invasion("Marid, Sedna", "Asedio", "Corpus", "Grineer", "3x Fieldron", 10,
                        objetos=[ws.ObjetoPremio("Fieldron", 3)]),
        ],
        alertas=[ws.Recompensa("Kiliken, Venus - Forma", _en(90))],
        arbitracion=ws.Recompensa("Casta, Ceres", _en(30), "Defensa - Grineer", tipo="Defense", faccion="Grineer"),
        sortie=[ws.Recompensa("Hyf - Defensa", _en(600))],
        arcontes=[ws.Recompensa("Io - Defensa", _en(3000))],
        acero=[ws.Recompensa("50,000 Kuva", _en(3000), "55 de esencia")],
        baro_detalle=baro,
    )


def _claves(prefs, **kw):
    return [a.clave.split("|")[0] for a in am.calcular(_mundo(), prefs, AHORA, **kw)]


def test_todo_viene_apagado():
    assert am.calcular(_mundo(), None, AHORA) == []
    assert am.calcular(_mundo(), {}, AHORA) == []
    assert not am.alguno_activo({})
    assert all(v is False for k, v in am.POR_DEFECTO.items() if isinstance(v, bool))


def test_fisuras_por_tipo_era_y_dificultad():
    prefs = {"fisuras": True, "fisuras_tipos": ["Void Cascade"]}
    avisos = am.calcular(_mundo(), prefs, AHORA)
    assert [a.texto for a in avisos] == [
        "Fisura Meso de Cascada del Vacío en Hydron, Sedna",
        "Fisura Meso de Cascada del Vacío en Ose, Europa (Camino de Acero)",
    ]
    assert len(am.calcular(_mundo(), {**prefs, "fisuras_dificultad": "acero"}, AHORA)) == 1
    assert len(am.calcular(_mundo(), {**prefs, "fisuras_dificultad": "normal"}, AHORA)) == 1
    assert am.calcular(_mundo(), {**prefs, "fisuras_eras": ["Lith"]}, AHORA) == []
    # Sin tipos marcados no avisa de todas (seria un aluvion); las terminadas y las
    # tormentas de Railjack tampoco.
    assert am.calcular(_mundo(), {"fisuras": True}, AHORA) == []
    capturas = am.calcular(_mundo(), {"fisuras": True, "fisuras_tipos": ["Capture", "Exterminate"]}, AHORA)
    assert [a.texto for a in capturas] == ["Fisura Lith de Captura en Casini, Ceres"]


def test_fisuras_solo_de_las_facciones_preferidas():
    prefs = {"fisuras": True, "fisuras_tipos": ["Void Cascade"], "fisuras_solo_facciones": True}
    assert len(am.calcular(_mundo(), prefs, AHORA, facciones={"corpus"})) == 1
    # Sin facciones elegidas, la casilla no esconde nada.
    assert len(am.calcular(_mundo(), prefs, AHORA, facciones=set())) == 2


def test_baro_teshin_palladino_y_el_resto():
    prefs = {clave: True for clave, v in am.POR_DEFECTO.items() if isinstance(v, bool)}
    prefs["fisuras"] = False
    claves = _claves(prefs)
    for esperado in ("baro", "baro_objetivo", "teshin", "palladino", "arbitraje", "invasion", "alerta",
                     "incursion", "arcontes", "cetus"):
        assert esperado in claves, esperado
    textos = [a.texto for a in am.calcular(_mundo(), prefs, AHORA)]
    assert "Ha llegado Baro Ki'Teer a Larunda, Mercurio" in textos
    assert "Baro Ki'Teer trae algo de tus objetivos: Flujo Prime" in textos
    assert "Teshin (Camino de Acero) ofrece esta semana: 50.000 de Kuva" in textos


def test_teshin_solo_si_toca_lo_pedido_y_sin_api_por_la_rotacion():
    mundo = _mundo()
    assert _claves({"teshin_kuva": True}) == ["teshin"]
    assert _claves({"teshin_umbra": True}) == []
    mundo.acero = []
    # 2026-09-14 es la semana del Plano de Forma Umbra (la misma cuenta que browse.wf).
    lunes = datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert am.teshin_de_la_semana(lunes) == "Umbra Forma Blueprint"
    assert [a.clave.split("|")[0] for a in am.calcular(mundo, {"teshin_umbra": True}, lunes)] == ["teshin"]
    assert am.inicio_semana(lunes) == datetime(2026, 9, 14, tzinfo=timezone.utc)


def test_invasiones_por_palabras_en_los_dos_idiomas():
    assert _claves({"invasiones": True, "invasiones_palabras": "catalizador"}) == ["invasion"]
    assert _claves({"invasiones": True, "invasiones_palabras": "Catalyst"}) == ["invasion"]
    assert _claves({"invasiones": True, "invasiones_palabras": "fieldron, catalyst"}) == ["invasion", "invasion"]
    assert _claves({"invasiones": True, "invasiones_palabras": ""}) == []
    texto = am.calcular(_mundo(), {"invasiones": True, "invasiones_palabras": "fieldron"}, AHORA)[0].texto
    assert texto == "Invasion en Marid, Sedna: 3x Fieldron"


def test_arbitraje_por_tipo():
    assert _claves({"arbitraje": True}) == ["arbitraje"]
    assert _claves({"arbitraje": True, "arbitraje_tipos": ["Defense"]}) == ["arbitraje"]
    assert _claves({"arbitraje": True, "arbitraje_tipos": ["Survival"]}) == []


def test_el_avisador_no_repite_y_olvida_lo_caducado():
    prefs = {"fisuras": True, "fisuras_tipos": ["Void Cascade"], "palladino": True}
    avisador = am.Avisador()
    primeros = avisador.nuevos(am.calcular(_mundo(), prefs, AHORA), AHORA)
    assert len(primeros) == 3
    # Un minuto despues, lo mismo: nada nuevo.
    assert avisador.nuevos(am.calcular(_mundo(), prefs, AHORA + timedelta(minutes=1)), AHORA) == []
    # Lo apuntado sobrevive a reiniciar Farmadex (se guarda en la configuracion).
    otro = am.Avisador(dict(avisador.enviados))
    assert otro.nuevos(am.calcular(_mundo(), prefs, AHORA), AHORA) == []
    # La semana siguiente, Palladino vuelve a avisar; las fisuras ya caducadas se olvidan.
    despues = AHORA + timedelta(days=7)
    nuevos = otro.nuevos(am.calcular(_mundo(), {"palladino": True}, despues), despues)
    assert [a.clave.split("|")[0] for a in nuevos] == ["palladino"]
    assert not any(c.startswith("fisura") for c in otro.enviados)


def test_juntar_resume_si_hay_muchos():
    avisos = [am.Aviso(str(i), f"aviso {i}", AHORA) for i in range(6)]
    texto = am.juntar(avisos)
    assert texto.splitlines()[:4] == ["aviso 0", "aviso 1", "aviso 2", "aviso 3"]
    assert "2 avisos mas" in texto


def test_normalizar_aguanta_una_configuracion_rota():
    prefs = am.normalizar({"fisuras": 1, "fisuras_tipos": "Void Cascade", "fisuras_dificultad": "rara",
                           "invasiones_palabras": None, "otra": 3})
    assert prefs["fisuras"] is True and prefs["fisuras_tipos"] == []
    assert prefs["fisuras_dificultad"] == "cualquiera"
    assert prefs["invasiones_palabras"] == am.POR_DEFECTO["invasiones_palabras"]
    assert "otra" not in prefs


def test_objetos_premio_de_warframestat_y_del_crudo_de_de():
    class Traductor:
        def objeto(self, unique_name, nombre_en):
            if unique_name == "/Lotus/Types/Recipes/Components/OrokinCatalystBlueprint":
                return {"id": 7, "nombre_es": "Plano"}
            return None

        def padre(self, item_id):
            return "Catalizador Orokin" if item_id == 7 else ""

    idiomas.cargar("es")
    wfstat = {"items": ["Wraith Twin Vipers Receiver"], "countedItems": [
        {"uniqueName": "/Lotus/Types/Recipes/Components/OrokinCatalystBlueprint",
         "type": "Orokin Catalyst Blueprint", "count": 1}]}
    objetos = ws.objetos_premio(wfstat, Traductor())
    assert [o.nombre_mostrar for o in objetos] == ["Wraith Twin Vipers Receiver", "Plano de Catalizador Orokin"]
    assert objetos[1].item_id == 7 and objetos[0].item_id is None
    # El crudo de DE solo trae la ruta: el nombre se saca de ella.
    de = {"countedItems": [{"count": 3, "type": "DetoniteInjectorBlueprint",
                            "key": "/Lotus/StoreItems/Types/Recipes/Components/DetoniteInjectorBlueprint"}]}
    (objeto,) = ws.objetos_premio(de)
    assert (objeto.nombre_en, objeto.cantidad) == ("Detonite Injector Blueprint", 3)
    assert objeto.unique_name == "/Lotus/Types/Recipes/Components/DetoniteInjectorBlueprint"
