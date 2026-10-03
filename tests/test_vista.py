"""Lo que sale solo en el juego: icono de comerciable, titulo, precio, agrietados y colocacion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pytest

from farmadex.agrietados import analisis, grados
from farmadex.agrietados.mercado import Subasta, calcular_horquilla
from farmadex.captura import vista
from farmadex.captura.ocr import Leido
from farmadex.ui import vista_objeto as VO


# -- icono de comerciable ---------------------------------------------------------------


def _fondo(alto=500, ancho=700, semilla=3):
    rng = np.random.default_rng(semilla)
    img = rng.integers(10, 40, (alto, ancho, 3), dtype=np.uint8)
    return img


def _pegar_icono(img, x, y, escala):
    """El icono como lo pinta el juego a ese tamano, mezclado sobre el fondo."""
    import cv2

    w, h = int(round(vista.ANCHO_ICONO * escala)), int(round(vista.ALTO_ICONO * escala))
    icono = cv2.resize(vista.plantilla_icono(), (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
    zona = img[y:y + h, x:x + w].astype(np.float32)
    img[y:y + h, x:x + w] = (zona * (1 - icono[..., None]) + 210 * icono[..., None]).astype(np.uint8)
    return img


@pytest.mark.parametrize("alto_juego", [720, 1080, 1440, 2160])
def test_encuentra_el_icono_a_cualquier_resolucion(alto_juego):
    img = _pegar_icono(_fondo(int(alto_juego * 0.75), int(alto_juego * 1.24)), 300, 60, alto_juego / 1080)
    encontrado = vista.buscar_icono(img, alto_juego)
    assert encontrado is not None
    assert abs(encontrado.x - 300) <= 4 and abs(encontrado.y - 60) <= 4


def test_icono_con_la_interfaz_grande():
    img = _pegar_icono(_fondo(810, 1340), 500, 200, 1.42)
    assert vista.buscar_icono(img, 1080) is not None


def test_sin_icono_no_encuentra_nada():
    img = _fondo()
    # Texto y rayas que no son el icono.
    img[100:104, 50:400] = 200
    img[200:260, 300:304] = 200
    assert vista.buscar_icono(img, 1080) is None


def test_el_boton_de_comercio_del_chat_no_cuenta():
    img = _pegar_icono(_fondo(810, 1340), 500, 700, 1.0)
    assert vista.buscar_icono(img, 1080) is not None
    assert vista.buscar_icono(img, 1080, y_maxima=650) is None


# -- titulo -------------------------------------------------------------------------------


def test_plano_prime_en_varios_idiomas():
    assert vista.es_plano_prime("NIDUS PRIME BLUEPRINT")
    assert vista.es_plano_prime("Plano de Burston Prime")
    assert vista.es_plano_prime("Schéma : Nidus Prime")
    assert not vista.es_plano_prime("NIDUS PRIME")  # el warframe hecho no se vende
    assert not vista.es_plano_prime("SERRATION")


class CasadorFalso:
    def __init__(self, tabla):
        self.tabla = tabla

    def casar(self, texto, umbral=82):
        for clave, (iid, etiqueta, puntos) in self.tabla.items():
            if clave in texto.upper():
                return iid, etiqueta, puntos
        return None, "", 0.0


def test_titulo_que_no_casa_no_da_objeto():
    lineas = [Leido("XJQZ PRIME", 10, 10, 100, 20, 0.9)]
    lectura = vista.interpretar_titulo(lineas, lineas, CasadorFalso({}))
    assert lectura.item_id is None and lectura.motivo


def test_titulo_con_poca_seguridad_no_da_objeto():
    lineas = [Leido("SERATON", 10, 10, 100, 20, 0.9)]
    lectura = vista.interpretar_titulo(lineas, lineas, CasadorFalso({"SERATON": (1, "Serration", 80.0)}))
    assert lectura.item_id is None


def test_titulo_de_plano_exige_prime_y_plano():
    casador = CasadorFalso({"NIDUS": (7, "Nidus Prime Blueprint", 95.0)})
    solo = [Leido("NIDUS PRIME", 10, 10, 100, 20, 0.9)]
    assert vista.interpretar_titulo(solo, solo, casador, exigir_prime=True).item_id is None
    plano = [Leido("NIDUS PRIME BLUEPRINT", 10, 10, 100, 20, 0.9)]
    assert vista.interpretar_titulo(plano, plano, casador, exigir_prime=True).item_id == 7


def test_los_planos_sin_icono_estan_apagados():
    """En las capturas reales llevan icono; la busqueda sin icono colaba nombres de la pantalla."""
    assert vista.PLANO_SIN_ICONO is False


def test_titulo_es_lo_de_encima_de_la_fila_del_icono():
    icono = vista.IconoEncontrado(400, 80, 28, 0.95, 25)
    l1 = Leido("BANSHEE PRIME NEUROPTICS", 60, 20, 300, 20, 0.9)
    l2 = Leido("BLUEPRINT", 60, 44, 120, 20, 0.9)
    precio = Leido("3,500", 90, 84, 60, 20, 0.9)
    lejos = Leido("Astilla Prime Barrel", 60, -60, 200, 18, 0.9)
    assert vista.lineas_de_titulo([precio, l2, lejos, l1], icono) == [l1, l2]


def test_titulo_con_la_fila_de_rombos_en_medio():
    icono = vista.IconoEncontrado(400, 100, 28, 0.95, 25)
    titulo = Leido("ATLAS PRIME BLUEPRINT", 60, 30, 300, 22, 0.9)
    assert vista.lineas_de_titulo([titulo], icono) == [titulo]


def test_medio_titulo_no_vale_con_icono():
    """Con icono se casa el titulo entero: "ASH PRIME" suelto no sale de dos lineas."""
    casador = CasadorFalso({"ASH PRIME CHASSIS BLUEPRINT": (3, "Ash Prime Chassis Blueprint", 97.0)})
    lineas = [Leido("ASH PRIME CHASSIS", 10, 10, 100, 20, 0.9), Leido("BLUEPRINT", 10, 32, 100, 20, 0.9)]
    assert vista.interpretar_titulo(lineas, lineas, casador).item_id == 3


def test_cabecera_de_mejoras():
    assert vista.es_cabecera_mejoras([Leido("MEJORAS/OCTAVIA PRIME [30]", 0, 0, 10, 10, 0.8)])
    assert vista.es_cabecera_mejoras([Leido("UPGRADES: NYX PRIME RANG 30", 0, 0, 10, 10, 0.8)])
    assert vista.es_cabecera_mejoras([Leido("IDGRADES:NYXDRIMERANG3O4", 0, 0, 10, 10, 0.8)])
    assert not vista.es_cabecera_mejoras([Leido("INVENTORY/TRADE", 0, 0, 10, 10, 0.8)])
    assert not vista.es_cabecera_mejoras([Leido("7.113.215 10.984", 0, 0, 10, 10, 0.8)])


def test_cabecera_tapada_vale_la_barra_de_capacidad():
    """Una grabacion o un aviso tapan "MEJORAS": debajo sigue "CAPACIDAD 2/74" (capturas
    reales en castellano a 1080p/1440p/4K, en ingles a 4K con la cabecera cortada, en ruso)."""
    assert vista.es_cabecera_mejoras([Leido("Fecha de grabacion:", 1, 8, 364, 40, 0.9),
                                      Leido("CAPACIDAD", 156, 95, 116, 22, 0.85), Leido("2/74", 512, 93, 58, 27, 0.8)])
    assert vista.es_cabecera_mejoras([Leido("CAPACITY", 359, 52, 92, 23, 0.83), Leido("11/60", 670, 50, 64, 28, 0.83)])
    assert vista.es_cabecera_mejoras([Leido("BMECTWMOCTb", 118, 107, 157, 29, 0.84), Leido("0/60", 382, 114, 54, 24, 0.8)])
    assert vista.es_cabecera_mejoras([Leido("POIEMNOSC", 100, 120, 110, 20, 0.85), Leido("67/74", 400, 121, 50, 20, 0.8)])
    # La palabra sola, o los numeros en otra fila, no bastan.
    assert not vista.es_cabecera_mejoras([Leido("CAPACIDAD", 156, 95, 116, 22, 0.85)])
    assert not vista.es_cabecera_mejoras([Leido("CAPACIDAD", 156, 95, 116, 22, 0.85), Leido("2/74", 512, 160, 58, 27, 0.8)])
    assert not vista.es_cabecera_mejoras([Leido("CALIDAD", 156, 95, 116, 22, 0.85), Leido("2/74", 512, 93, 58, 27, 0.8)])


def test_cabecera_cortada_con_la_cola_del_rango():
    """La tarjeta ampliada tapa media cabecera: "POTENZIA" + "...YR PRIME GRADO 30" (italiano
    con mando), "ULEPSZ" + "14-RIMERANGA30" (polaco), y en ruso leido con letras latinas."""
    assert vista.es_cabecera_mejoras([Leido("POTENZIA", 561, 66, 187, 32, 0.85),
                                      Leido("18/RPRIMEGRADO30", 923, 63, 436, 34, 0.87)])
    assert vista.es_cabecera_mejoras([Leido("ULEPSZ", 669, 93, 131, 38, 0.85), Leido("14-RIMERANGA30", 961, 87, 347, 40, 0.84)])
    assert vista.es_cabecera_mejoras([Leido("yIYWEHMA: PEBEHAHT NPAИM PAHI 3O ()", 615, 71, 814, 49, 0.8)])
    assert vista.es_cabecera_mejoras([Leido("yNyYWEHMA: HOKTYA PAHF 30 (", 664, 70, 621, 44, 0.71)])
    # Sin la cola del rango en la fila, la palabra cortada no basta ("MEJORAR" de un boton).
    assert not vista.es_cabecera_mejoras([Leido("ULEPSZ", 669, 93, 131, 38, 0.85)])
    assert not vista.es_cabecera_mejoras([Leido("MEJORAR", 669, 93, 131, 38, 0.85), Leido("TODOS", 961, 87, 100, 40, 0.84)])


# -- agrietados: disparador ---------------------------------------------------------------


def test_morado_de_agrietado():
    img = np.full((400, 300, 3), 20, np.uint8)
    assert not vista.parece_agrietado(img)
    img[50:350, 40:60] = (200, 90, 150)  # BGR: morado del marco
    img[50:350, 240:260] = (200, 90, 150)
    assert vista.parece_agrietado(img)


def test_franja_quieta_avisa_una_vez():
    q = vista.Quieta()
    a = np.full((50, 400, 3), 30, np.uint8)
    b = np.full((50, 400, 3), 200, np.uint8)
    assert not q.observar(a, 0.0)
    assert q.observar(a, 0.2)  # quieta: una vez
    assert not q.observar(a, 0.4)
    assert not q.observar(b, 0.6)  # cambia
    assert q.t_cambio == 0.6
    assert q.observar(b, 0.8)


# -- precio ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class PrecioFalso:
    slug: str
    rango: int | None
    venta_min: int | None
    venta_mediana: float | None
    compra_max: int | None
    min_30d: int | None
    max_30d: int | None
    media_30d: float | None
    volumen_30d: int | None
    fecha: datetime | None


class PreciosFalsos:
    fecha = datetime(2026, 9, 30, tzinfo=timezone.utc)

    def __init__(self, datos, rangos=None):
        self.datos = datos
        self._rangos = rangos or {}

    def buscar(self, slug, rango=None):
        return self.datos.get((slug, rango))

    def rangos(self, slug):
        return self._rangos.get(slug, [])


def _precio(slug, rango, venta, compra, mn, mx):
    return PrecioFalso(slug, rango, venta, venta, compra, mn, mx, (mn + mx) / 2 if mn and mx else None, 40,
                       datetime(2026, 9, 30, tzinfo=timezone.utc))


def test_precio_sin_rangos():
    pd = PreciosFalsos({("nidus_prime_blueprint", None): _precio("nidus_prime_blueprint", None, 12, 9, 8, 20),
                        ("nidus_prime_set", None): _precio("nidus_prime_set", None, 90, 80, 70, 120)})
    obj = VO.ObjetoVisto(1, "nidus_prime_blueprint", "Nidus Prime Blueprint", slug_set="nidus_prime_set")
    textos = " / ".join(VO.CajaJuego.textos(type("C", (), {"filas": VO.filas_precio(obj, pd)})()))
    assert "12 p" in textos and "9 p" in textos and "8 p" in textos and "20 p" in textos
    assert "90 p" in textos  # el set


def test_precio_por_rangos_con_el_leido():
    datos = {("serration", r): _precio("serration", r, 5 + r, 3 + r, 2 + r, 9 + r) for r in (0, 5, 10)}
    pd = PreciosFalsos(datos, {"serration": list(range(11))})
    obj = VO.ObjetoVisto(1, "serration", "Serration", rango=5)
    filas = VO.filas_precio(obj, pd)
    cabecera = next(f for f in filas if f[0] == "cols")
    assert cabecera[1] == ["", "R0", "R5", "R10"]


def test_precio_sin_datos_no_inventa():
    pd = PreciosFalsos({})
    obj = VO.ObjetoVisto(1, "algo", "Algo")
    textos = " ".join(t for f in VO.filas_precio(obj, pd) for t in f[1:] if isinstance(t, str))
    assert " p" not in textos.replace("warframe.market", "")


def test_precio_sin_fichero():
    filas = VO.filas_precio(VO.ObjetoVisto(1, "x", "X"), None)
    assert any(f[0] == "texto" for f in filas)
    assert not any(f[0] in ("fila", "cols") for f in filas)


def test_dato_que_falta_dice_sin_datos():
    pd = PreciosFalsos({("x", None): _precio("x", None, 10, None, 5, 15)})
    filas = VO.filas_precio(VO.ObjetoVisto(1, "x", "X"), pd)
    compra = next(f for f in filas if f[0] == "fila" and "Compran" in f[1])
    assert compra[2] == "sin datos"


def test_rangos_a_ensenar():
    assert VO.rangos_a_ensenar([], 3) == []
    assert VO.rangos_a_ensenar(list(range(6)), None) == [0, 5]
    assert VO.rangos_a_ensenar(list(range(6)), 3) == [0, 3, 5]
    assert VO.rangos_a_ensenar(list(range(6)), 9) == [0, 5]


# -- agrietados: analisis -----------------------------------------------------------------


def _subasta(precio, atributos):
    return Subasta(precio, None, atributos, 0, 8, 10, "madurai", "x", "vendedor", "ingame")


def _valor(slug, clase, disp, pos, neg, posicion, negativo=False):
    mn, mx = grados.rango(slug, clase, disp, pos, neg, negativo)
    return mn + (mx - mn) * posicion if not negativo else mx - (mx - mn) * posicion


def test_comparar_con_parecidos():
    clase, disp = "rifle", 1.0
    tuyas = [("critical_chance", _valor("critical_chance", clase, disp, 2, 0, 0.9), False),
             ("multishot", _valor("multishot", clase, disp, 2, 0, 0.9), False)]
    subastas = [_subasta(100 + 10 * i, [("critical_chance", _valor("critical_chance", clase, disp, 2, 0, p), False),
                                        ("multishot", _valor("multishot", clase, disp, 2, 0, p), False)])
                for i, p in enumerate((0.1, 0.2, 0.3, 0.4, 0.5, 0.95))]
    c = analisis.comparar(tuyas, clase, disp, subastas)
    assert c.muestras == 6 and c.suficiente
    assert c.posicion == "encima"
    assert c.por_encima == 5
    assert c.n_mejores == 1 and c.precio_mejores == 150


def test_comparar_descarta_valores_imposibles_y_pocas_muestras():
    clase, disp = "rifle", 1.0
    tuyas = [("critical_chance", _valor("critical_chance", clase, disp, 2, 0, 0.5), False),
             ("multishot", _valor("multishot", clase, disp, 2, 0, 0.5), False)]
    malas = [_subasta(50, [("critical_chance", 999.0, False), ("multishot", 1.0, False)])]
    c = analisis.comparar(tuyas, clase, disp, malas)
    assert c.descartadas == 1 and c.muestras == 0 and not c.suficiente and c.posicion == ""


def test_panel_riven_sin_tarjeta_fiable_no_evalua():
    class T:
        arma_nombre, arma_texto, nombre, velado, fiable, estadisticas = "Braton", "Braton", "Visi-tron", False, False, []

    filas = VO.filas_riven(VO.DatosRiven(tarjeta=T()))
    assert not any(f[0] == "fila" for f in filas)


def test_panel_riven_completo():
    clase, disp = "rifle", 1.0

    class Arma:
        slug, clase, disposicion = "braton", "rifle", 1.0

    class E:
        def __init__(self, slug, valor):
            self.slug, self.valor, self.negativo, self.entendida = slug, valor, False, True

    class T:
        arma_nombre, arma_texto, nombre, velado, fiable = "Braton", "Braton", "Crita-tron", False, True
        estadisticas = [E("critical_chance", _valor("critical_chance", clase, disp, 2, 0, 0.8)),
                        E("multishot", _valor("multishot", clase, disp, 2, 0, 0.8))]

    stats = [(e.slug, e.valor, False) for e in T.estadisticas]
    subastas = [_subasta(100 + i, [("critical_chance", _valor("critical_chance", clase, disp, 2, 0, 0.3), False),
                                   ("multishot", _valor("multishot", clase, disp, 2, 0, 0.3), False)]) for i in range(6)]
    d = VO.DatosRiven(tarjeta=T(), arma=Arma(), evaluaciones=grados.evaluar(stats, clase, disp),
                      horquilla=calcular_horquilla("braton", [s.precio for s in subastas], "exacto"),
                      subastas=subastas, comparacion=analisis.comparar(stats, clase, disp, subastas))
    textos = " / ".join(VO.CajaJuego.textos(type("C", (), {"filas": VO.filas_riven(d)})()))
    assert "por encima" in textos
    assert "vendedor" in textos


# -- colocacion -----------------------------------------------------------------------------


def test_precio_no_tapa_el_recuadro_del_juego():
    caja = (800, 300, 400, 200)
    x, y = VO.colocar_precio((300, 150), caja, (790, 320), (0, 0, 1920, 1080))
    assert not (x < 1200 and x + 300 > 800 and y < 500 and y + 150 > 300)


def test_panel_riven_a_media_altura_a_la_izquierda():
    x, y = VO.colocar_panel_riven((360, 400), (0, 0, 2560, 1440))
    assert x < 100 and abs((y + 200) - 720) <= 1


# -- el vigia: cuando mira y cuando no ---------------------------------------------------


class _Pantalla:
    """Sustituye `captura.pantalla` en el vigia: una imagen fija y un raton que se mueve a mano."""

    def __init__(self, monkeypatch, imagen):
        from farmadex.captura import pantalla

        self.imagen, self.cursor, self.capturas, self.delante = imagen, (500, 400), 0, True
        self.region = pantalla.Region(0, 0, imagen.shape[1], imagen.shape[0])
        monkeypatch.setattr(pantalla, "ventana_juego", lambda: 7)
        monkeypatch.setattr(pantalla, "_ventana_activa", lambda: 7 if self.delante else 1)
        monkeypatch.setattr(pantalla, "region_ventana", lambda hwnd: self.region)
        monkeypatch.setattr(pantalla, "_posicion_cursor", lambda: self.cursor)
        monkeypatch.setattr(pantalla, "descartar_propias", lambda img, region, *a, **k: img)
        monkeypatch.setattr(pantalla, "capturar_sin_ocultar", self.capturar)
        self.cursor_a_la_vista = True
        monkeypatch.setattr(vista, "cursor_visible", lambda: self.cursor_a_la_vista)

    def capturar(self, r):
        self.capturas += 1
        return np.ascontiguousarray(self.imagen[r.y:r.y + r.alto, r.x:r.x + r.ancho])


def _vigia(monkeypatch, reloj):
    v = vista.VigiaVistas("rapidocr", precio=True, rivens=False, builds=False)
    monkeypatch.setattr(vista.time, "monotonic", lambda: reloj[0])
    return v


def test_el_vigia_no_captura_nada_con_el_raton_en_movimiento(monkeypatch):
    p = _Pantalla(monkeypatch, _fondo(1080, 1920))
    reloj = [100.0]
    v = _vigia(monkeypatch, reloj)
    for i in range(30):  # jugando: el raton no para
        p.cursor = (500 + 20 * i, 400)
        reloj[0] += 0.1
        v.tic()
    assert p.capturas == 0


def test_en_partida_con_el_cursor_escondido_no_se_captura_nada(monkeypatch):
    p = _Pantalla(monkeypatch, _fondo(1080, 1920))
    p.cursor_a_la_vista = False
    reloj = [100.0]
    v = vista.VigiaVistas("rapidocr", precio=True, rivens=True, builds=True)
    monkeypatch.setattr(vista.time, "monotonic", lambda: reloj[0])
    for _ in range(50):  # raton "quieto" (el juego lo tiene cogido) y pantalla quieta
        reloj[0] += 0.1
        v.tic()
    assert p.capturas == 0 and v.sondeos == 0


def test_en_un_menu_quieto_solo_se_miran_los_testigos(monkeypatch):
    p = _Pantalla(monkeypatch, _fondo(1080, 1920))
    reloj = [100.0]
    v = vista.VigiaVistas("rapidocr", precio=False, rivens=True, builds=True)
    monkeypatch.setattr(vista.time, "monotonic", lambda: reloj[0])
    leidas = []
    monkeypatch.setattr(v, "mirar_cabecera", lambda *a, **k: leidas.append("cabecera"))
    monkeypatch.setattr(v, "mirar_centro", lambda *a, **k: leidas.append("centro"))
    for _ in range(50):
        reloj[0] += 0.1
        v.tic()
    # Una vez al quedarse quieta la pantalla, y ya no mas mientras no cambie.
    assert leidas == ["cabecera", "centro"]
    assert v.sondeos == 50


def test_el_vigia_no_mira_si_el_juego_no_esta_delante(monkeypatch):
    p = _Pantalla(monkeypatch, _fondo(1080, 1920))
    p.delante = False
    reloj = [100.0]
    v = _vigia(monkeypatch, reloj)
    for _ in range(20):
        reloj[0] += 0.1
        v.tic()
    assert p.capturas == 0


def test_raton_quieto_sin_icono_mira_un_rato_y_deja_de_mirar(monkeypatch):
    p = _Pantalla(monkeypatch, _fondo(1080, 1920))
    reloj = [100.0]
    v = _vigia(monkeypatch, reloj)
    for _ in range(100):  # diez segundos quieto
        reloj[0] += 0.1
        v.tic()
    # Solo durante el primer segundo y medio de la parada; luego, nada hasta que se mueva.
    assert 1 <= p.capturas <= int(vista.BUSCAR_ICONO_HASTA_S / vista.REINTENTO_ICONO_S) + 1
    assert v.lecturas["precio"] == 0


def test_icono_a_la_vista_lee_una_vez_y_al_irse_el_raton_quita_el_recuadro(monkeypatch):
    img = _pegar_icono(_fondo(1080, 1920), 900, 300, 1.0)
    p = _Pantalla(monkeypatch, img)
    reloj = [100.0]
    v = _vigia(monkeypatch, reloj)
    leidos, fuera, leyendo = [], [], []
    v.objeto_fuera.connect(lambda: fuera.append(1))
    v.leyendo_precio.connect(lambda punto: leyendo.append(punto))

    def leer_titulo(imagen, recorte, region, icono, x, y, t_visto, filete=None):
        leidos.append((recorte.x + icono.x, recorte.y + icono.y))
        v._resuelto, v._mostrando = True, (x, y)
        return VO.ObjetoVisto(1, "serration", "Serration")

    monkeypatch.setattr(v, "_leer_titulo", leer_titulo)
    for _ in range(20):
        reloj[0] += 0.1
        v.tic()
    assert len(leidos) == 1 and abs(leidos[0][0] - 900) <= 3 and abs(leidos[0][1] - 300) <= 3
    assert leyendo == [(500, 400)]
    p.cursor = (700, 600)
    reloj[0] += 0.1
    v.tic()
    assert fuera == [1]


def test_titulo_a_medio_salir_se_reintenta_y_luego_se_rinde(monkeypatch):
    img = _pegar_icono(_fondo(1080, 1920), 900, 300, 1.0)
    _Pantalla(monkeypatch, img)
    reloj = [100.0]
    v = _vigia(monkeypatch, reloj)
    intentos, rendido = [], []
    v.sin_objeto.connect(lambda motivo: rendido.append(motivo))
    monkeypatch.setattr(v, "_leer_titulo", lambda *a, **k: intentos.append(1))
    for _ in range(40):
        reloj[0] += 0.1
        v.tic()
    assert len(intentos) == vista.INTENTOS_TITULO and rendido == [""]


# -- el controlador (ventanas de verdad, sin pantalla) ------------------------------------


@pytest.fixture()
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_controlador_ensena_y_quita_el_precio(qapp, monkeypatch):
    pd = PreciosFalsos({("serration", None): _precio("serration", None, 10, 8, 5, 15)})
    monkeypatch.setattr(VO, "_precios", lambda: pd)
    c = VO.ControladorVistas(None, con_red=False)
    try:
        c.mostrar_precio(VO.ObjetoVisto(1, "serration", "Serration", caja=(800, 300, 400, 200), cursor=(700, 350),
                                        t_visto=__import__("time").monotonic()))
        assert c.caja_precio.isVisible()
        assert any("10 p" in x for x in c.caja_precio.textos())
        assert "precio" in c.ultimo_ms
        c.esconder_precio()
        assert not c.caja_precio.isVisible()
    finally:
        c.cerrar()


def test_controlador_panel_de_agrietado_sin_red(qapp):
    class T:
        arma_nombre, arma_texto, nombre, velado, fiable, estadisticas, arma_slug = "Braton", "Braton", "X", True, False, [], None

    c = VO.ControladorVistas(None, con_red=False)
    try:
        c.mostrar_riven(T(), 0.0)
        assert c.caja_riven.isVisible()
        c.esconder_riven()
        assert not c.caja_riven.isVisible()
    finally:
        c.cerrar()


def test_el_vigia_se_precalienta_antes_de_la_primera_vista(monkeypatch):
    """La primera tarjeta de agrietado de la sesion no paga la carga del casador ni la del lector."""
    hechos = []
    v = vista.VigiaVistas("rapidocr", precio=False, rivens=True, builds=False)
    monkeypatch.setattr(v, "preparar", lambda: hechos.append("preparar") or True)
    monkeypatch.setattr(v, "_lector_riven", lambda: hechos.append("lector"))
    v._precalentar()
    assert hechos == ["preparar", "lector"]
    # Sin agrietados activos no se carga su lector; sin indice no se hace nada (se preparara al leer).
    hechos.clear()
    v.activo_rivens = False
    v._precalentar()
    assert hechos == ["preparar"]
    hechos.clear()
    v.activo_rivens = True
    monkeypatch.setattr(v, "preparar", lambda: hechos.append("preparar") and False)
    v._precalentar()
    assert hechos == ["preparar"]
    # Un fallo al adelantar trabajo no rompe nada.
    monkeypatch.setattr(v, "preparar", lambda: 1 / 0)
    v._precalentar()


def test_el_precalentado_se_hace_una_vez_con_el_juego_delante(monkeypatch):
    p = _Pantalla(monkeypatch, _fondo(1080, 1920))
    reloj = [100.0]
    v = vista.VigiaVistas("rapidocr", precio=False, rivens=True, builds=False)
    monkeypatch.setattr(vista.time, "monotonic", lambda: reloj[0])
    hechos = []
    monkeypatch.setattr(v, "_precalentar", lambda: hechos.append(1))
    monkeypatch.setattr(v, "_sondear", lambda *a, **k: None)
    v.tic()
    assert hechos == []  # sin iniciar (tests, autoprueba a mano) no se adelanta nada
    v._precalentar_pendiente = True
    p.delante = False
    v.tic()
    assert hechos == []  # el juego detras: todavia no
    p.delante = True
    for _ in range(3):
        reloj[0] += 0.1
        v.tic()
    assert hechos == [1]
