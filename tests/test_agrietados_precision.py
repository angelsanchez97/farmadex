"""Precision del lector de agrietados: lo que fallaba en recortes reales de Steam y de la wiki.

Las lineas calcan lo que leyo RapidOCR en tarjetas reales (banco del scratchpad, zona rivens):
el candado de "MR 🔒 12" leido como cifra, nombres viejos de estadisticas, el signo al reves del
retroceso, decimales ilegibles, nombres partidos en dos lineas y textos de la interfaz encima.
"""

import json

import numpy as np
import pytest

from farmadex.agrietados import mercado
from farmadex.agrietados.lector import ArmaConocida, LectorTarjeta, _maestria_de, _parece_stat, parsear_texto
from farmadex.captura.ocr import Leido

from conftest import FIXTURES

B = "base_damage_/_melee_damage"


@pytest.fixture(scope="module")
def lector():
    datos = json.load(open(FIXTURES / "market_riven_weapons.json", encoding="utf-8"))
    armas = [ArmaConocida(a.slug, a.nombre_en, a.nombre_en) for a in mercado.analizar_armas(datos)]
    armas += [ArmaConocida(s, n, n) for s, n in (("gram", "Gram"), ("pangolin_sword", "Pangolin Sword"),
                                                  ("lato", "Lato"), ("opticor", "Opticor"),
                                                  ("dual_cleavers", "Dual Cleavers"), ("cyanex", "Cyanex"),
                                                  ("wolf_sledge", "Wolf Sledge"), ("grinlok", "Grinlok"))]
    return LectorTarjeta(armas)


def _stats(t):
    return [(e.slug, e.valor, e.negativo) for e in t.estadisticas]


def _l(texto, x, y, ancho=200, alto=20, conf=0.9):
    return Leido(texto, x, y, ancho, alto, conf)


@pytest.mark.parametrize("cifras,esperada", [("12", 12), ("012", 12), ("611", 11), ("09", 9), ("69", 9),
                                             ("18", 8), ("112", 12), ("7", None), ("0", None), ("17", None), ("99", 9)])
def test_maestria_con_el_candado_leido_como_cifra(cifras, esperada):
    assert _maestria_de(cifras) == esperada


def test_mr_con_candado_centrado(lector):
    t = parsear_texto(["18Y", "TonkorCritacak", "+139.5%CriticalChance", "+103%Puncture", "MR012"], lector)
    assert t.maestria == 12
    t = parsear_texto(["18", "GrinlokArmatron", "+54.8%Damageto", "Corpus", "+65.9%Magazine", "Capacity", "MR611"], lector)
    assert t.maestria == 11


def test_channeling_damage_es_el_combo_inicial_y_no_el_dano(lector):
    t = parsear_texto(["18", "Pangolin Sword", "Torido", "+147.4%*Cold", "+260.6%Channeling", "Damage",
                       "-37.5%AttackSpeed", "MR9"], lector)
    assert t.arma_slug == "pangolin_sword"
    assert t.nombre == "Torido"
    assert _stats(t) == [("cold_damage", 147.4, False), ("channeling_damage", 260.6, False),
                         ("fire_rate_/_attack_speed", 37.5, True)]
    assert t.estadisticas[1].antigua
    t = parsear_texto(["18", "GramAcri-torido", "+89.2%*Cold", "+156.8%Channeling", "Damage",
                       "+104.1%CriticalDamage", "MR9"], lector)
    assert t.arma_slug == "gram" and t.nombre == "Acri-torido"
    assert [s for s, _, _ in _stats(t)] == ["cold_damage", "channeling_damage", "critical_damage"]


def test_melee_combo_efficiency_es_eficiencia_de_ataque_pesado(lector):
    t = parsear_texto(["18", "Wolf Sledge Fortitio", "+102.9%Electricity", "+85.2%MeleeCombo", "Efficiency",
                       "-42.6%StatusChance", "MR10"], lector)
    assert _stats(t)[1] == ("channeling_efficiency", 85.2, False)


def test_retroceso_con_menos_es_una_mejora(lector):
    t = parsear_texto(["18", "Lato Gelimag", "-140.1%WeaponRecoil", "+146.7%*Cold", "-32.3%Damageto", "Grineer",
                       "MR9"], lector)
    assert _stats(t) == [("recoil", 140.1, False), ("cold_damage", 146.7, False), ("damage_vs_grineer", 32.3, True)]
    assert t.fiable, t.avisos


def test_retroceso_con_mas_es_el_negativo(lector):
    t = parsear_texto(["18", "Soma Hexa-visisus", "+82.6%Cslash", "+71.2%StatusChance", "+130.4%Damage",
                       "+9.1%WeaponRecoil", "MR11"], lector)
    assert _stats(t)[-1] == ("recoil", 9.1, True)


def test_decimal_ilegible_no_se_redondea(lector):
    t = parsear_texto(["18", "GramHexa-visinem", "+132.T%StatusChance", "+232.6%MeleeDamage",
                       "+10.8sComboDuration", "-106.3%CriticalDamage", "MR9"], lector)
    assert t.estadisticas[0].valor is None and t.estadisticas[0].slug == "status_chance"
    assert not t.fiable


def test_nombre_partido_en_dos_lineas(lector):
    t = parsear_texto(["18", "Dread Hexa-", "critasus", "+130.5%Slash", "+170.4%CriticalChance",
                       "+109%StatusChance", "-52.1%Zoom", "MR11"], lector)
    assert t.nombre == "Hexa-critasus"
    t = parsear_texto(["18", "DualCleaversSci", "plecidra", "+93%CriticalChanceforSlideAttack", "+97.6%Slash",
                       "+37.2%AttackSpeed", "MR15"], lector)
    assert t.arma_slug == "dual_cleavers"
    assert t.nombre == "Sci-plecidra"


def test_solo_el_nombre_sin_arma_no_inventa_arma(lector):
    t = parsear_texto(["18", "Acri-visicron", "+86.5%MeleeDamage", "+42.5%CriticalChance",
                       "+47.6%CriticalDamage", "MR9"], lector)
    assert t.arma_slug is None
    assert t.nombre == "Acri-visicron"
    assert not t.fiable


def test_texto_de_la_interfaz_encima_no_se_pega_al_arma(lector):
    lineas = [_l("UPGRADES", 89, 2, 238, 25), _l("Cyanex Sati-visinak", 45, 317, 241, 34),
              _l("+162.6%Damage", 77, 352, 177, 22), _l("+65.2%ProjectileSpeed", 44, 376, 243, 22),
              _l("+94.8%Multishot", 79, 401, 174, 18), _l("MR9", 52, 439, 50, 19)]
    t = lector.leer(lineas)
    assert t.arma_slug == "cyanex" and t.nombre == "Sati-visinak"
    lineas = [_l("OpticorVisi-", 60, 280, 150, 20), _l("Sho", 300, 290, 40, 20), _l("armatis", 90, 302, 90, 20),
              _l("+90%CriticalDamage", 50, 326, 190, 18), _l("+39.7%Magazine", 60, 346, 170, 18),
              _l("Capacity", 100, 366, 90, 18), _l("+132.3%Damage", 70, 386, 150, 18), _l("MR12", 50, 420, 50, 18)]
    t = lector.leer(lineas)
    assert t.arma_slug == "opticor" and t.nombre == "Visi-armatis"


def test_capacidad_con_letras_no_es_una_estadistica():
    assert not _parece_stat("18VME")
    assert _parece_stat("+1 Range")
    assert _parece_stat("+3.3PunchThrough")


def test_sin_desvelar_solo_dice_el_tipo(lector):
    t = parsear_texto(["Melee", "MR0"], lector)
    assert t.velado and not t.fiable
    t = parsear_texto(["Melee"], lector)
    assert t.velado


# --- relecturas ------------------------------------------------------------------------------

def _tarjeta_boar():
    return [_l("18-", 280, 52, 39, 22), _l("Boar Hexamag", 155, 415, 179, 30),
            _l("125.6%WeaponRecoil", 128, 449, 236, 22), _l("+129.4%StatusChance", 128, 473, 236, 21),
            _l("MR12", 131, 508, 63, 18)]


def test_pie_releido_contador_por_imagen_manda_sobre_el_icono_leido_como_cifra(lector):
    def releer(caja, escala):
        return [_l("MR 12", 131, 507, 63, 18), _l("56" if escala == 3.0 else "06", 319, 506, 30, 18)]

    t = lector.leer(_tarjeta_boar(), releer=releer, contador=lambda caja, caja_mr, maestria: (True, 6))
    assert t.variado == 6 and not t.pie_dudoso


def test_pie_releido_sin_contador_y_cifras_que_no_cuadran_queda_en_duda(lector):
    def releer(caja, escala):
        return [_l("MR 12", 131, 507, 63, 18), _l("56" if escala == 3.0 else "58", 319, 506, 30, 18)]

    t = lector.leer(_tarjeta_boar(), releer=releer, contador=lambda caja, caja_mr, maestria: (True, None))
    assert t.variado is None and t.pie_dudoso
    assert not t.fiable
    assert any("variado" in a for a in t.avisos)


def test_pie_releido_con_el_icono_como_letra(lector):
    t = lector.leer(_tarjeta_boar(), releer=lambda caja, escala: [_l("MR12", 131, 507, 63, 18), _l("O3", 315, 506, 35, 18)])
    assert t.variado == 3


def test_sin_contador_no_se_inventa(lector):
    t = lector.leer(_tarjeta_boar(), releer=lambda caja, escala: [_l("MR12", 131, 507, 63, 18)],
                    contador=lambda caja, caja_mr, maestria: (False, None))
    assert t.variado is None and not t.pie_dudoso


def test_verificar_valores_que_no_cuadran_entre_lecturas(lector):
    lineas = [_l("181", 242, 2, 46, 27), _l("Dread Sati-visicron", 57, 281, 220, 46),
              _l("+183.7%CriticalChance", 52, 321, 231, 39), _l("+89.2%Multishot", 85, 354, 164, 33),
              _l("+160.3%Damage", 82, 382, 169, 40), _l("MR10", 135, 435, 60, 27)]

    def releer(caja, escala):
        if caja[1] == 321 and escala == 0.75:
            return [_l("+133.7%CriticalChance", 52, 321, 231, 39)]
        return [l for l in lineas if l.y == caja[1]]

    t = lector.leer(lineas, releer=releer, verificar=True)
    assert t.estadisticas[0].valor_dudoso
    assert not t.fiable
    t = lector.leer(lineas, releer=lambda caja, escala: [l for l in lineas if l.y == caja[1]], verificar=True)
    assert not any(e.valor_dudoso for e in t.estadisticas)


def test_valor_fuera_de_rango_se_relee():
    lec = LectorTarjeta([ArmaConocida("grinlok", "Grinlok", "Grinlok", (), 1.0, "rifle")])
    lineas = [_l("18", 291, 45, 30, 18), _l("GrinlokMantides", 85, 288, 222, 32), _l("+45.4%Damageto", 94, 326, 203, 23),
              _l("corpus", 156, 351, 80, 24), _l("f913%StatusDuration", 76, 374, 251, 24), _l("MASTERY9", 122, 411, 143, 24)]
    t = lec.leer(lineas)
    assert t.estadisticas[1].fuera_de_rango and not t.fiable
    t = lec.leer(lineas, releer=lambda caja, escala: [_l("+91.3%StatusDuration", 76, 374, 251, 24)] if caja[1] == 374 else [])
    assert _stats(t)[1] == ("status_duration", 91.3, False)
    assert not t.estadisticas[1].fuera_de_rango


# --- con el OCR de verdad --------------------------------------------------------------------

@pytest.fixture(scope="module")
def motor():
    from farmadex.captura.ocr import MotorOCR

    return MotorOCR()


def test_leer_linea_reconoce_sin_detector(motor):
    import cv2

    img = np.full((48, 200, 3), 20, np.uint8)
    cv2.putText(img, "MR 12", (10, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (200, 160, 230), 2, cv2.LINE_AA)
    texto, confianza = motor.leer_linea(img)
    assert texto.replace(" ", "") == "MR12"
    assert confianza > 0.5
    assert motor.leer_linea(None) == ("", 0.0)


def test_leer_contador_separa_el_icono_de_las_cifras(motor):
    import cv2

    from farmadex.captura.agrietados import leer_contador

    img = np.full((60, 400, 3), 25, np.uint8)
    color = (210, 150, 200)
    cv2.putText(img, "MR 12", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2, cv2.LINE_AA)
    cv2.ellipse(img, (300, 29), (11, 11), 0, 40, 330, color, 3, cv2.LINE_AA)  # el icono de variar
    cv2.putText(img, "6", (322, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2, cv2.LINE_AA)
    hay, veces = leer_contador(img, motor, (200, 14, 180, 30), (8, 14, 100, 30), 12)
    assert hay and veces == 6
    # Sin icono no hay contador, aunque haya algo a la derecha del pie.
    vacia = np.full((60, 400, 3), 25, np.uint8)
    cv2.putText(vacia, "MR 12", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2, cv2.LINE_AA)
    assert leer_contador(vacia, motor, (200, 14, 180, 30), (8, 14, 100, 30), 12) == (False, None)
