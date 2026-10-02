"""Validacion cruzada de la pantalla de mejoras: los huecos que se ven ocupados frente a
los mods leidos, la relectura de la tarjeta que falta y la tarjeta "No he podido leer este
mod" en la rejilla. Con pantallas sinteticas (sin red) y con la captura real del usuario
(Grendel Prime, juego en castellano, tema de colores propio) con la que la 0.6.11 dejo dos
huecos vacios sin avisar."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sintetico_builds as SINT  # noqa: E402
from farmadex.captura import builds as B  # noqa: E402
from farmadex.captura import huecos_build as H  # noqa: E402
from farmadex.captura.ocr import Leido, MotorOCR, Reconocido  # noqa: E402
from farmadex.datos import disposicion_build as D  # noqa: E402
from test_captura import _insertar  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

MODS = [
    ("/m/Vitality", "Vitality", "Vitalidad", "Mods"),
    ("/m/Redirection", "Redirection", "Redirección", "Mods"),
    ("/m/Intensify", "Intensify", "Intensificación", "Mods"),
    ("/m/Continuity", "Continuity", "Continuidad", "Mods"),
    ("/m/Stretch", "Stretch", "Estirar", "Mods"),
    ("/m/Streamline", "Streamline", "Simplificación", "Mods"),
    ("/m/Flow", "Flow", "Flujo", "Mods"),
    ("/m/Rush", "Rush", "Prisa", "Mods"),
    ("/m/SteelFiber", "Steel Fiber", "Fibra de acero", "Mods"),
    ("/m/Equilibrium", "Equilibrium", "Equilibrio", "Mods"),
    ("/m/ThiefsWit", "Thief's Wit", "Astucia del ladrón", "Mods"),
    ("/m/EnergySiphon", "Energy Siphon", "Sifón de energía", "Mods"),
    ("/w/Excalibur", "Excalibur", "Excalibur", "Warframes"),
]
# La captura real del usuario (tema de colores propio, Farmadex abierto encima de la coleccion).
GRENDEL = [
    ("/w/GrendelPrime", "Grendel Prime", "Grendel Prime", "Warframes"),
    ("/w/Grendel", "Grendel", "Grendel", "Warframes"),
    ("/m/CorrosiveProjection", "Corrosive Projection", "Proyección corrosiva", "Mods"),
    ("/m/PrimedFlow", "Primed Flow", "Flujo Prime", "Mods"),
    ("/m/Adaptation", "Adaptation", "Adaptación", "Mods"),
    ("/m/SaxumCarapace", "Saxum Carapace", "Caparazón de Saxum", "Mods"),
    ("/m/CarnisCarapace", "Carnis Carapace", "Caparazón de Carnis", "Mods"),
    ("/m/JugulusCarapace", "Jugulus Carapace", "Caparazón de Jugulus", "Mods"),
    ("/m/TransientFortitude", "Transient Fortitude", "Fortaleza transitoria", "Mods"),
    ("/m/UmbralFiber", "Umbral Fiber", "Fibra Umbral", "Mods"),
    ("/m/UmbralVitality", "Umbral Vitality", "Vitalidad Umbral", "Mods"),
    ("/m/UmbralIntensify", "Umbral Intensify", "Intensificación Umbral", "Mods"),
    ("/m/ArchonContinuity", "Archon Continuity", "Continuidad Arconte", "Mods"),
    ("/m/Intolerant", "Intolerant", "Intolerante", "Mods"),
    ("/m/CatalyzingShields", "Catalyzing Shields", "Escudos catalizadores", "Mods"),
    ("/m/RollingGuard", "Rolling Guard", "Guardia ondulante", "Mods"),
    ("/m/PrimedSureFooted", "Primed Sure Footed", "Pies firmes Prime", "Mods"),
    ("/a/Grace", "Arcane Grace", "Gracia Arcana", "Arcanes"),
    ("/a/Guardian", "Arcane Guardian", "Guardián Arcano", "Arcanes"),
    ("/a/Energize", "Arcane Energize", "Energizar Arcano", "Arcanes"),
]


def _catalogo(con, filas, auras=()):
    ids = _insertar(con, [(u, en, es, cat, None, None) for u, en, es, cat in filas])
    for unique in ids:
        if unique.startswith("/w/"):
            con.execute("UPDATE items SET tipo = 'Warframe' WHERE unique_name = ?", (unique,))
        elif unique.startswith("/m/"):
            con.execute("UPDATE items SET tipo = 'Warframe Mod' WHERE unique_name = ?", (unique,))
    for unique in auras:
        con.execute("INSERT OR REPLACE INTO detalles (item_id, datos) VALUES (?, ?)",
                    (ids[unique], json.dumps({"compat": "AURA"})))
    con.commit()
    return ids


@pytest.fixture()
def catalogo(con):
    return con, _catalogo(con, MODS, auras=("/m/EnergySiphon",))


@pytest.fixture(scope="module")
def motor():
    return MotorOCR()


# -- limpieza de lo leido en una tarjeta ----------------------------------------------------

def test_limpiar_nombre_tarjeta_quita_signos_y_fichas():
    # Lo que leyo el OCR en la captura real del usuario: un destello como apostrofo y una
    # ficha detras ("Caparazon de'Saxum 1" daba "parecido 88 %").
    assert "Caparazon de Saxum" in B.limpiar_nombre_tarjeta("Caparazon de'Saxum 1")
    assert "Caparazon de Saxum" in B.limpiar_nombre_tarjeta("Caparazon de' Saxum J")
    assert B.limpiar_nombre_tarjeta("16Y Fortaleza transitoria") == ["Fortaleza transitoria"]
    assert B.limpiar_nombre_tarjeta("16 Sacrificial Steel") == ["Sacrificial Steel"]
    # Nada que limpiar: ninguna variante (no se gasta casado de mas).
    assert B.limpiar_nombre_tarjeta("Flujo Prime") == []


def test_limpiar_nombre_tarjeta_no_deja_una_palabra_sola_si_quito_algo_delante():
    # "1 Fury" era un "Primed Fury" tapado por la camara del streamer ("d Fury" leido con
    # una cifra): quedarse con "Fury" seria inventar otro mod.
    assert B.limpiar_nombre_tarjeta("1 Fury") == []
    assert B.limpiar_nombre_tarjeta("d Fury") == []


def test_el_casado_limpio_sube_la_seguridad_del_mismo_mod(catalogo):
    con, ids = catalogo
    casador = B.crear_casador(con)
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    linea = Leido("Fibra de'acero 1", 700, 400, 150, 22, 0.9)
    r = Reconocido("Fibra de'acero 1", ids["/m/SteelFiber"], "Fibra de acero", 88.0, (700, 400, 150, 22))
    nuevos = B._casar_limpios([linea], [r], casador, categorias)
    assert nuevos == [] and r.puntuacion == 100.0
    # Una linea que no caso por los restos, casa limpia; una que no es nombre, no.
    lineas = [Leido("16Y Astucia del'ladron", 700, 500, 150, 22, 0.9), Leido("+50% Astucia", 700, 600, 150, 22, 0.9)]
    nuevos = B._casar_limpios(lineas, [], casador, categorias)
    assert [n.item_id for n in nuevos] == [ids["/m/ThiefsWit"]]


# -- huecos vacios frente a tarjetas puestas ---------------------------------------------------

def _pantalla(equipados, **kw):
    return SINT.pintar_arsenal("Excalibur", equipados, ["Flow", "Rush"], semilla=3, **kw)


def test_un_hueco_vacio_del_juego_se_distingue_de_una_tarjeta():
    imagen = _pantalla(["Energy Siphon", "Vitality", "", "Intensify"])
    # Las tarjetas del sintetico: aura en (846, 204), mods en (600 + 244 * col, 340 + 136 * fila), de 226 x 112.
    assert H.parece_vacio(imagen, (844, 340, 226, 112))       # mod2: vacio
    assert H.parece_vacio(imagen, (1090, 204, 226, 112))      # exilus: vacio
    assert not H.parece_vacio(imagen, (600, 340, 226, 112))   # mod1: Vitality
    assert not H.parece_vacio(imagen, (1088, 340, 226, 112))  # mod3: Intensify
    assert not H.parece_vacio(imagen, (846, 204, 226, 112))   # aura


def test_las_medidas_no_dependen_de_la_resolucion():
    for ancho, alto in ((1280, 720), (2560, 1440)):
        k = ancho / 1920
        imagen = _pantalla(["Energy Siphon", "Vitality", "", "Intensify"], ancho=ancho, alto=alto)
        assert H.parece_vacio(imagen, (int(844 * k), int(340 * k), int(226 * k), int(112 * k)))
        assert not H.parece_vacio(imagen, (int(600 * k), int(340 * k), int(226 * k), int(112 * k)))


# -- la validacion cruzada entera, con OCR ------------------------------------------------------

def _leer(con, motor, imagen):
    casador = B.crear_casador(con)
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    return B.leer_build(imagen, motor, casador, categorias, H.cargar_tipos_de_hueco(con))


def test_tarjeta_que_no_se_lee_se_dice_en_su_hueco(catalogo, motor):
    con, ids = catalogo
    # mod3 lleva una tarjeta cuyo nombre no es ningun mod del catalogo (una tarjeta que el
    # OCR no entiende), mod6 lleva una tarjeta con el nombre tapado; mod2 y mod8 estan vacios.
    equipados = ["Energy Siphon", "Vitality", "", "Zqwvx Plorbatt", "Continuity", "Stretch", "#tapada", "Equilibrium", ""]
    build = _leer(con, motor, _pantalla(equipados))
    assert build.equipo is not None and build.equipo.item_id == ids["/w/Excalibur"]
    leidos = {r.item_id for r in build.equipados}
    assert leidos == {ids[u] for u in ("/m/EnergySiphon", "/m/Vitality", "/m/Continuity", "/m/Stretch", "/m/Equilibrium")}
    assert build.colocacion is not None and build.colocacion.segura
    assert build.colocacion.mods.get("aura") == 0 and build.colocacion.mods.get("mod1") is not None
    # Los dos huecos con tarjeta sin leer se dicen, con lo que se leyo; los vacios, no.
    no_leidos = {h.clave: h for h in build.no_leidos}
    assert set(no_leidos) == {"mod3", "mod6"}, [(h.clave, h.texto, h.motivo) for h in build.no_leidos]
    assert "Zqwvx" in no_leidos["mod3"].texto and no_leidos["mod3"].motivo == "sin_reconocer"
    assert no_leidos["mod6"].motivo == "tapado" and "%" in no_leidos["mod6"].texto
    assert build.huecos_vistos == 7
    assert not [r for r in build.equipados if r.item_id not in leidos]  # nada inventado
    assert "huecos" in build.tiempos


def test_sin_tarjetas_sin_leer_no_hay_avisos(catalogo, motor):
    con, ids = catalogo
    build = _leer(con, motor, _pantalla(["Energy Siphon", "Vitality", "Redirection", "Intensify", "Continuity",
                                          "Stretch", "Streamline", "Equilibrium", "Thief's Wit"]))
    assert len(build.equipados) == 9 and build.no_leidos == [] and build.huecos_vistos == 9
    assert build.colocacion.segura and set(build.colocacion.mods) == {"aura", *(f"mod{n}" for n in range(1, 9))}


def test_el_mod_suelto_de_una_tarjeta_ampliada_vuelve_a_su_hueco():
    # Rejilla medida en una captura real (Haalvu a 1440p): la tarjeta ampliada bajo el cursor
    # crece hacia abajo desde su borde de arriba, el nombre baja una fila y media y no caia
    # en ningun hueco. Es el mod2 (el mas alto de su columna); el mod6 queda tapado debajo.
    xs = (-0.23, -0.002, 0.226, 0.455)
    mods = [D.Punto("mod", xs[0], 0.321), D.Punto("mod", xs[2], 0.318), D.Punto("mod", xs[3], 0.319),
            D.Punto("mod", xs[0], 0.445), D.Punto("mod", xs[2], 0.447), D.Punto("mod", xs[3], 0.446),
            D.Punto("mod", xs[1], 0.51)]
    col = D.colocar("arma", mods, [])
    assert col.segura and col.sueltos_mods == [6]
    build = B.Build(equipados=[Reconocido("x", n, "x", 100.0, (int(960 + p.x * 1080 - 60), int(p.y * 1080 - 20), 120, 20))
                               for n, p in enumerate(mods, 1)], ancho=1920, alto=1080)
    H.recolocar_sueltos(col, build, None, 1920, 1080)
    assert col.sueltos_mods == [] and col.mods["mod2"] == 6 and "mod6" not in col.mods
    # Un aura ampliada (mantener pulsado para mejorar): su nombre cae en la fila de abajo,
    # pero un aura solo puede ir en el hueco del aura.
    mods = [D.Punto("mod", xs[0], 0.39), D.Punto("mod", xs[2], 0.39), D.Punto("mod", xs[3], 0.39),
            D.Punto("mod", xs[0], 0.516), D.Punto("mod", xs[2], 0.516), D.Punto("mod", xs[3], 0.516),
            D.Punto("aura", xs[1], 0.4)]
    col = D.colocar("warframe", mods, [])
    assert col.segura and col.sueltos_mods == [6]
    build = B.Build(equipados=[Reconocido("x", n, "x", 100.0, (int(960 + p.x * 1080 - 60), int(p.y * 1080 - 20), 120, 20))
                               for n, p in enumerate(mods, 1)], ancho=1920, alto=1080)
    H.recolocar_sueltos(col, build, H.TiposDeHueco(auras={7}), 1920, 1080)
    assert col.mods["aura"] == 6 and "mod2" not in col.mods


def test_la_rejilla_mide_donde_cae_cada_hueco():
    mods = [D.Punto("mod", -0.23, 0.32), D.Punto("mod", -0.002, 0.321), D.Punto("mod", 0.226, 0.318),
            D.Punto("mod", 0.455, 0.319), D.Punto("mod", -0.23, 0.445)]
    col = D.colocar("arma", mods, [])
    assert col.segura and abs(col.paso - 0.228) < 0.006
    hueco = next(h for h in col.huecos if h.clave == "mod6")
    cx, yb = col.centro_de(hueco)
    assert abs(cx - (-0.002)) < 0.01 and abs(yb - 0.445) < 0.01
    caja = H.caja_de_hueco(col, hueco, 1920, 1080)
    assert caja is not None and abs(caja[0] + caja[2] / 2 - 958) < 12 and caja[1] < 0.445 * 1080 < caja[1] + caja[3]


# -- la captura real del usuario ----------------------------------------------------------------

@pytest.fixture()
def catalogo_grendel(con):
    return con, _catalogo(con, GRENDEL, auras=("/m/CorrosiveProjection",))


def test_captura_real_del_usuario_sale_entera(catalogo_grendel, motor):
    """Grendel Prime, juego en castellano, tema de colores propio. La 0.6.11 dio "7 mods
    equipados" y dejo vacios Caparazon de Saxum y Caparazon de Carnis sin avisar."""
    import cv2

    con, ids = catalogo_grendel
    imagen = cv2.imread(str(FIXTURES / "capturas_build" / "grendel_prime_usuario.jpg"))
    assert imagen is not None
    build = _leer(con, motor, imagen)
    assert build.equipo is not None and build.equipo.item_id == ids["/w/GrendelPrime"]
    esperados = {ids[u] for u in ("/m/CorrosiveProjection", "/m/PrimedFlow", "/m/Adaptation", "/m/SaxumCarapace",
                                  "/m/CarnisCarapace", "/m/TransientFortitude", "/m/UmbralFiber", "/m/UmbralVitality",
                                  "/m/UmbralIntensify")}
    assert {r.item_id for r in build.equipados} == esperados, [r.nombre for r in build.equipados]
    assert {r.item_id for r in build.arcanos} == {ids["/a/Grace"], ids["/a/Guardian"]}
    # Los nombres estan escritos tal cual en la pantalla: nada de "parecido 88 %".
    saxum = next(r for r in build.equipados if r.item_id == ids["/m/SaxumCarapace"])
    assert saxum.puntuacion == 100.0
    assert build.no_leidos == [] and build.colocacion.segura
    huecos = {clave: build.equipados[i].item_id for clave, i in build.colocacion.mods.items()}
    assert huecos["aura"] == ids["/m/CorrosiveProjection"] and huecos["mod3"] == ids["/m/SaxumCarapace"]
    assert huecos["mod4"] == ids["/m/CarnisCarapace"] and "exilus" not in huecos
    assert {clave: build.arcanos[j].item_id for clave, j in build.colocacion.arcanos.items()} == {
        "arcano1": ids["/a/Grace"], "arcano2": ids["/a/Guardian"]}


def test_el_cirilico_leido_con_letras_latinas_se_reconoce():
    # Lo que deja el OCR latino al leer la pantalla rusa (capturas reales).
    rusas = ["BMECTWMOCTb", "CekpeTbl", "HenpepbIBHocTb", "YcToMuMBOCTb", "CnoCo6HocTb"]
    assert B.parece_cirilico([Leido(t, 0, 0, 100, 20, 0.9) for t in rusas])
    latinas = ["Primed Flow", "Umbral Vitality", "Steel Charge", "Blind Rage", "Augur Reach", "Archon: Kontinuitat"]
    assert not B.parece_cirilico([Leido(t, 0, 0, 100, 20, 0.9) for t in latinas])


# -- mas casos reales del banco de 2026-10 -------------------------------------------------------

def test_el_filtro_deja_pasar_las_armas_de_moa():
    # Viven en ".../MoaPetComponents/TazronWeapon": solo cuenta "Component" en el ultimo tramo.
    assert B._filtro_build("Primary", "Companion Weapon", "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/TazronWeapon")
    assert not B._filtro_build("Primary", "Componente", "/Lotus/Types/Recipes/Weapons/WeaponParts/BratonPrimeBarrelComponent")


def test_sin_cabecera_el_equipo_de_reserva_solo_si_esta_arriba_y_es_exacto(catalogo):
    con, ids = catalogo
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    # "mesPrime" (la cola de un "Pies firmes Prime" tapado) en medio de las tarjetas: no es el equipo.
    abajo = Reconocido("mesPrime", ids["/w/Excalibur"], "Excalibur", 88.0, (900, 400, 100, 20))
    build = B.separar_build([Leido("Vitalidad", 700, 398, 120, 20, 0.9), Leido("BUSCAR...", 106, 638, 120, 20, 0.9)],
                            [abajo], categorias, None, ancho=1920, alto=1080)
    assert build.equipo is None
    arriba = Reconocido("EXCALIBUR", ids["/w/Excalibur"], "Excalibur", 100.0, (700, 40, 300, 30))
    build = B.separar_build([Leido("BUSCAR...", 106, 638, 120, 20, 0.9)], [arriba], categorias, None, ancho=1920, alto=1080)
    assert build.equipo is not None and build.equipo.item_id == ids["/w/Excalibur"]


def test_pantalla_recortada_sin_coleccion_lo_de_arriba_es_lo_equipado(catalogo):
    con, ids = catalogo
    categorias = dict(con.execute("SELECT id, categoria FROM items"))
    # Un montaje de video sin la caja de buscar: 8 mods en dos filas por encima del 62 %.
    recs = [Reconocido(n, ids[u], n, 100.0, (600 + 244 * (i % 4), 340 + 136 * (i // 4), 120, 20))
            for i, (u, n) in enumerate([("/m/Vitality", "Vitality"), ("/m/Redirection", "Redirection"),
                                        ("/m/Intensify", "Intensify"), ("/m/Continuity", "Continuity"),
                                        ("/m/Stretch", "Stretch"), ("/m/Streamline", "Streamline"),
                                        ("/m/Flow", "Flow"), ("/m/Rush", "Rush")])]
    build = B.separar_build([], recs, categorias, None, ancho=1920, alto=1080)
    assert build.separador == "arriba" and len(build.equipados) == 8 and not build.coleccion and not build.aviso
    # Con un mod por debajo del 62 % no vale esta regla (deciden las filas o, si no, la coleccion).
    recs.append(Reconocido("Steel Fiber", ids["/m/SteelFiber"], "Steel Fiber", 100.0, (600, 760, 120, 20)))
    build = B.separar_build([], recs, categorias, None, ancho=1920, alto=1080)
    assert build.separador != "arriba"


def test_la_ranura_de_arcano_bloqueada_es_un_hueco_vacio():
    assert B.RE_HUECO_VACIO.search("Requires Melee Arcane Adapter")
    assert B.RE_HUECO_VACIO.search("Benotigt Sekundar Arkana-Adapter")
    assert not B.RE_HUECO_VACIO.search("Arcane Energize")


def test_el_rotulo_buscar_tiene_que_ir_en_mayusculas():
    assert B.es_rotulo_buscar("BUSCAR...") and B.es_rotulo_buscar("|BUSCAR.") and B.es_rotulo_buscar("SEARCH...")
    assert not B.es_rotulo_buscar("Buscar")  # el mod Scavenge en castellano


def test_las_ayudas_abiertas_se_agrupan_aunque_lleven_titulo_e_imagen():
    # Titulo en mayusculas, hueco de la imagen y descripcion debajo, con el mismo borde izquierdo.
    lineas = [Leido("BREACH SURGE", 600, 200, 200, 30, 0.9), Leido("MAX RANK", 600, 235, 120, 20, 0.9),
              Leido("Open a dimensional breach to", 600, 520, 300, 22, 0.9),
              Leido("blind enemies within 15m.", 600, 548, 300, 22, 0.9),
              Leido("Energy: 50 per cast", 600, 576, 300, 22, 0.9),
              Leido("BACK", 1700, 1040, 60, 20, 0.9)]  # el pie de la pantalla, para saber su alto
    zonas = H.zonas_de_ayuda(lineas)
    assert len(zonas) == 1 and zonas[0][1] < 200 and zonas[0][1] + zonas[0][3] > 598
    # Dos lineas sueltas de un nombre de tarjeta no son una ayuda.
    assert H.zonas_de_ayuda([Leido("Primed Bane of", 600, 400, 150, 22, 0.9), Leido("Grineer", 620, 426, 80, 22, 0.9)]) == []


def test_un_agrietado_en_un_hueco_se_dice_como_tal():
    build = B.Build(equipo=Reconocido("FALCOR", 1, "Falcor", 100.0, (0, 0, 1, 1)))
    assert H._parece_agrietado("Falcor Para-critanem", build)
    assert H._parece_agrietado("Visi-critacan", build)
    assert not H._parece_agrietado("Condition Overload", build)


def test_el_mod_adaptation_no_es_la_ranura_sin_adaptador():
    # "Adaptation" / "Adaptacion" es un mod; la ranura bloqueada dice "Requires ... Adapter".
    assert not B.RE_HUECO_VACIO.search("Adaptation") and not B.RE_HUECO_VACIO.search("Adaptacion")
    assert B.RE_HUECO_VACIO.search("Requires Exilus Adapter") and B.RE_HUECO_VACIO.search("Wymaga Adapter Exilus")


def test_sin_rango_con_el_laurel_pegado_y_ranga_zero():
    assert "NUNCHASA" in B._nombres_de_equipo("UNRANKED NUNCHASA PSS")
    assert "KOMPRESSA" in B._nombres_de_equipo("RANGA ZERO KOMPRESSA")
