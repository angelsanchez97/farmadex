"""Captura y lectura de la tarjeta de un agrietado que hay bajo el cursor.

El usuario pone el raton sobre la tarjeta (en el arsenal, en los mods o en el
comercio) y pulsa el atajo: se captura un recuadro alrededor del cursor del
tamano de una tarjeta, se lee con el OCR y `agrietados.lector` lo interpreta.
Las armas con agrietado (y su disposicion) vienen de warframe.market a traves
de `agrietados.mercado`, que las guarda en disco; los nombres en castellano
salen del indice.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Signal, Slot

from ..agrietados import mercado
from ..agrietados.lector import ArmaConocida, LectorTarjeta, TarjetaLeida
from ..idiomas import t
from ..registro_log import obtener
from . import pantalla
from .ocr import ErrorMotorOCR, Leido, resumen_tiempos, unir_filas
from .reliquias import LectorBase

log = obtener("captura.agrietados")

# Una tarjeta mide unos 316x400 px a 1080p; el recuadro va holgado y se escala con
# la ventana del juego para que a 1440p siga cabiendo entera.
ANCHO_TARJETA, ALTO_TARJETA = 560, 760
MINIMO_CONFIANZA = 0.4
# Por debajo de esta altura el OCR pierde decimales: se amplia la captura antes de leer.
ALTO_MINIMO_LECTURA = 500
# Y por encima de esta (el recuadro de una pantalla 4K) se reduce: el texto sigue sobrado de
# grande y el OCR con entradas enormes se quedaba con cientos de MB que no devolvia.
ALTO_MAXIMO_LECTURA = 1520


def armas_conocidas(con=None) -> list[ArmaConocida]:
    """Las armas con agrietado, con su nombre en castellano si el indice lo tiene y en los
    otros idiomas del juego que traiga (frances, aleman, portugues, italiano, polaco)."""
    return armas_con_nombres(mercado.compartido().armas(), con)


def armas_con_nombres(armas, con=None) -> list[ArmaConocida]:
    nombres_es: dict[str, str] = {}
    otros: dict[str, list[str]] = {}
    if con is not None and armas:
        try:
            filas = con.execute("SELECT unique_name, nombre_es FROM items WHERE nombre_es IS NOT NULL")
            nombres_es = {u: n for u, n in filas if n}
        except Exception as e:  # noqa: BLE001 - sin nombres en castellano se lee igual
            log.debug("Sin nombres en castellano para las armas: %s", e)
        try:
            filas = con.execute("SELECT i.unique_name, n.nombre FROM items_nombres n JOIN items i ON i.id = n.item_id")
            for unico, nombre in filas:
                if nombre and nombre not in otros.setdefault(unico, []):
                    otros[unico].append(nombre)
        except Exception as e:  # noqa: BLE001 - indice viejo sin otros idiomas
            log.debug("Sin nombres en otros idiomas para las armas: %s", e)
    return [ArmaConocida(a.slug, nombres_es.get(a.unique_name) or a.nombre_en, a.nombre_en,
                         tuple(otros.get(a.unique_name, ())), getattr(a, "disposicion", None),
                         getattr(a, "clase", "") or "") for a in armas]


class LectorAgrietado(LectorBase):
    """Lee la tarjeta bajo el cursor en el hilo de captura y la devuelve por senal."""

    leida = Signal(object)  # TarjetaLeida

    def __init__(self, motor_ocr: str = "rapidocr", parent=None):
        super().__init__(motor_ocr, None, parent)
        self.lector: LectorTarjeta | None = None

    @Slot()
    def iniciar(self) -> None:
        from ..datos import indice

        self._precalentar()
        con = indice.conectar() if indice.hay_indice() else None
        try:
            armas = armas_conocidas(con)
        finally:
            if con is not None:
                con.close()
        if armas:
            self.lector = LectorTarjeta(armas)
        else:
            log.warning("Sin lista de armas con agrietado (hace falta red la primera vez)")
        pantalla.declarar_dpi()

    @Slot()
    def leer_ahora(self) -> None:
        if self._ocupado:
            return
        self._ocupado = True
        try:
            self._leer()
        except Exception:  # noqa: BLE001 - nunca un dialogo de error
            log.exception("Fallo inesperado leyendo un agrietado")
            self.estado.emit(t("Fallo al leer la pantalla (mira el registro)"))
            self.leida.emit(TarjetaLeida(avisos=[t("Fallo al leer la pantalla (mira el registro)")]))
        finally:
            self._ocupado = False

    def _leer(self) -> None:
        if self.lector is None:
            self.iniciar()
            if self.lector is None:
                self.estado.emit(t("Falta la lista de armas con agrietado: hace falta conexión la primera vez"))
                self.leida.emit(TarjetaLeida(avisos=[t("Falta la lista de armas con agrietado: hace falta conexión la primera vez")]))
                return
        if self.motor.fallo:
            self._avisar_motor(self.motor.fallo)
            self.leida.emit(TarjetaLeida(avisos=[t("El lector de pantalla no está disponible")]))
            return
        self.estado.emit(t("Leyendo la tarjeta bajo el cursor..."))
        inicio = time.perf_counter()
        juego = pantalla.region_juego()
        escala = (juego.alto / 1080.0) if juego else 1.0
        region = pantalla.region_alrededor_del_cursor(
            int(ANCHO_TARJETA * escala), int(ALTO_TARJETA * escala), limite=juego
        )
        imagen = pantalla.capturar(region)
        if imagen is None:
            self.estado.emit(t("No se pudo capturar la pantalla"))
            self.leida.emit(TarjetaLeida(avisos=[t("No se pudo capturar la pantalla")]))
            return
        capturado = time.perf_counter()
        try:
            tarjeta = leer_tarjeta(imagen, self.motor, self.lector)
        except ErrorMotorOCR as e:
            self._avisar_motor(str(e))
            self.leida.emit(TarjetaLeida(avisos=[t("El lector de pantalla no está disponible")]))
            return
        fin = time.perf_counter()
        tiempos = getattr(self.motor, "tiempos", None) or {}
        ocr = tiempos.get("total", 0.0)
        log.info("Agrietado leido en %.0f ms (captura %.0f ms, %s, interpretar %.0f ms): arma=%s nombre=%s "
                 "stats=%d fiable=%s avisos=%s",
                 (fin - inicio) * 1000, (capturado - inicio) * 1000, resumen_tiempos(tiempos),
                 max(0.0, fin - capturado - ocr) * 1000, tarjeta.arma_slug, tarjeta.nombre,
                 len(tarjeta.estadisticas), tarjeta.fiable, tarjeta.avisos)
        if tarjeta.velado:
            self.estado.emit(t("La tarjeta está velada: no hay nada que evaluar"))
        elif tarjeta.fiable:
            self.estado.emit(t("Agrietado leído: {arma} {nombre}", arma=tarjeta.arma_nombre, nombre=tarjeta.nombre))
        elif not tarjeta.estadisticas and not tarjeta.arma_texto:
            self.estado.emit(t("No se ve ninguna tarjeta de agrietado bajo el cursor"))
        else:
            self.estado.emit(t("Agrietado leído a medias: revisa lo que falta"))
        self.leida.emit(tarjeta)


def leer_tarjeta(imagen, motor, lector: LectorTarjeta) -> TarjetaLeida:
    """OCR del recuadro (ampliado si es pequeno) e interpretacion de la tarjeta."""
    alto = imagen.shape[0]
    if alto < ALTO_MINIMO_LECTURA or alto > ALTO_MAXIMO_LECTURA:
        try:
            import cv2

            if alto < ALTO_MINIMO_LECTURA:
                factor, modo = ALTO_MINIMO_LECTURA / alto, cv2.INTER_CUBIC
            else:
                factor, modo = ALTO_MAXIMO_LECTURA / alto, cv2.INTER_AREA
            imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=modo)
        except ImportError:  # pragma: no cover - cv2 viene con rapidocr
            pass
    lineas = [l for l in unir_filas(motor.leer(imagen)) if l.confianza >= MINIMO_CONFIANZA]

    def releer(caja, escala: float):
        """Un trozo de la tarjeta ampliado y leido otra vez; las cajas vuelven a las
        coordenadas de `imagen`."""
        import cv2

        x, y, w, h = caja
        mx, my = int(h * 0.6), int(h * 0.45)
        x0, y0 = max(0, int(x - mx)), max(0, int(y - my))
        x1, y1 = min(imagen.shape[1], int(x + w + mx)), min(imagen.shape[0], int(y + h + my))
        trozo = imagen[y0:y1, x0:x1]
        if trozo.size == 0:
            return []
        grande = cv2.resize(trozo, None, fx=escala, fy=escala,
                            interpolation=cv2.INTER_CUBIC if escala >= 1 else cv2.INTER_AREA)
        salida = []
        # leer_tira: detector y reconocedor sin el reescalado a 736 px de RapidOCR (~30 ms);
        # con `leer` cada relectura costaba cientos de ms.
        for l in unir_filas(motor.leer_tira(grande)):
            if l.confianza < MINIMO_CONFIANZA:
                continue
            salida.append(Leido(l.texto, x0 + int(l.x / escala), y0 + int(l.y / escala),
                                max(1, int(l.ancho / escala)), max(1, int(l.alto / escala)), l.confianza))
        return salida

    return lector.leer(lineas, releer=releer, contador=lambda caja, caja_mr=None, maestria=None: leer_contador(imagen, motor, caja, caja_mr, maestria))


# Alto, en pixeles, al que se lleva la fila del pie para separar el icono de variar de sus cifras.
ALTO_CONTADOR = 48


def leer_contador(imagen, motor, caja, caja_mr=None, maestria: int | None = None) -> tuple[bool, int | None]:
    """El contador de veces variado ("↻ 6"), mirando la imagen y no solo el OCR.

    `caja` (x, y, ancho, alto) es la mitad derecha de la fila del pie, a la altura de "MR 12".
    El detector de texto se salta a menudo un trozo tan pequeno y, cuando lo ve, lee el icono
    como una cifra mas ("56" por "↻ 6"): un contador inventado cambia el precio. Aqui se
    separan las piezas por su forma: el icono es redondo (tan ancho como alto) y va el primero;
    lo que le sigue son las cifras, que se leen solas. Devuelve (hay_icono, veces | None).
    """
    import cv2
    import numpy as np

    x, y, w, h = (int(v) for v in caja)
    if h < 6 or w < h:
        return False, None
    margen = int(h * 0.4)
    y0, y1 = max(0, y - margen), min(imagen.shape[0], y + h + margen)
    x0, x1 = max(0, x), min(imagen.shape[1], x + w)
    banda = imagen[y0:y1, x0:x1]
    if banda.size == 0 or banda.shape[1] < h:
        return False, None
    gris = banda.max(axis=2) if banda.ndim == 3 else banda
    factor = ALTO_CONTADOR / h
    gris = cv2.resize(gris, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    gris = cv2.GaussianBlur(gris, (3, 3), 0)
    # La tinta se mide contra la de "MR 12", que esta en la misma fila y con el mismo color: en
    # un fondo liso sin contador no hay nada tan claro, y un umbral automatico inventaria piezas.
    if caja_mr is not None:
        mx, my, mw, mh = (int(v) for v in caja_mr)
        muestra = imagen[max(0, my):my + mh, max(0, mx):mx + mw]
        muestra = muestra.max(axis=2) if muestra.ndim == 3 else muestra
        if muestra.size == 0:
            return False, None
        oscuro, claro = float(np.median(gris)), float(np.percentile(muestra, 97))
        if claro - oscuro < 35:
            return False, None
        _, tinta = cv2.threshold(gris, oscuro + 0.5 * (claro - oscuro), 255, cv2.THRESH_BINARY)
    else:
        if float(gris.max()) - float(np.median(gris)) < 60:
            return False, None
        _, tinta = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, _, datos, _ = cv2.connectedComponentsWithStats(tinta, 8)
    alto_banda, ancho_banda = tinta.shape
    arriba, abajo = (y - y0) * factor, (y - y0 + h) * factor
    piezas = []
    for i in range(1, n):
        px, py, pw, ph, area = (int(v) for v in datos[i])
        if py <= 0 or py + ph >= alto_banda:  # toca el borde: el marco de la tarjeta
            continue
        if not 0.42 * ALTO_CONTADOR <= ph <= 1.1 * ALTO_CONTADOR:
            continue
        if not arriba - 0.15 * ALTO_CONTADOR <= py + ph / 2 <= abajo + 0.15 * ALTO_CONTADOR:
            continue
        if pw > 1.5 * ph or area < 0.12 * pw * ph:
            continue
        piezas.append((px, py, pw, ph))
    piezas.sort()
    # El icono: la primera pieza redonda. Las cifras son mas estrechas que altas.
    icono = next((i for i, p in enumerate(piezas) if p[2] >= 0.78 * p[3]), None)
    if icono is None:
        return False, None
    cifras = []
    previa = piezas[icono]
    for p in piezas[icono + 1:]:
        hueco = p[0] - (previa[0] + previa[2])
        tope = 1.2 * ALTO_CONTADOR if not cifras else 0.5 * ALTO_CONTADOR
        if hueco > tope or p[2] > 0.85 * p[3] or abs(p[3] - piezas[icono][3]) > 0.35 * piezas[icono][3]:
            break
        cifras.append(p)
        previa = p
    if not 1 <= len(cifras) <= 3:
        return True, None
    cx0 = cifras[0][0] - 4
    cx1 = cifras[-1][0] + cifras[-1][2] + 4
    cy0 = max(0, min(p[1] for p in cifras) - 8)
    cy1 = min(alto_banda, max(p[1] + p[3] for p in cifras) + 8)
    recorte = gris[cy0:cy1, max(0, cx0):min(ancho_banda, cx1)]
    # Las cifras solas, con aire a los lados del color del fondo.
    fondo = int(np.median(gris[tinta == 0])) if (tinta == 0).any() else 0
    lienzo = np.full((recorte.shape[0], recorte.shape[1] + 2 * ALTO_CONTADOR), fondo, np.uint8)
    lienzo[:, ALTO_CONTADOR:ALTO_CONTADOR + recorte.shape[1]] = recorte
    texto, confianza = motor.leer_linea(cv2.cvtColor(lienzo, cv2.COLOR_GRAY2BGR))
    texto = texto.replace(" ", "").replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
    if confianza >= MINIMO_CONFIANZA and texto.isdigit() and len(texto) == len(cifras):
        return True, int(texto)
    # Una cifra sola (sobre todo un "1") no le dice nada al reconocedor. Se le da contexto: la
    # maestria, que ya se leyo bien, y detras las cifras del contador sin el icono. De lo que
    # lea se quita la maestria y tiene que quedar justo el numero de cifras que se ven.
    if caja_mr is None or maestria is None:
        return True, None
    mx, my, mw, mh = (int(v) for v in caja_mr)
    trozo_mr = imagen[y0:y1, max(0, mx - margen):min(imagen.shape[1], mx + mw + margen)]
    if trozo_mr.size == 0:
        return True, None
    gris_mr = trozo_mr.max(axis=2) if trozo_mr.ndim == 3 else trozo_mr
    gris_mr = cv2.resize(gris_mr, (max(1, round(gris_mr.shape[1] * factor)), alto_banda), interpolation=cv2.INTER_CUBIC)
    tira = gris[:, max(0, cx0):min(ancho_banda, cx1)]
    hueco = np.full((alto_banda, ALTO_CONTADOR // 2), fondo, np.uint8)
    junto = np.hstack([hueco, gris_mr, hueco, tira, hueco])
    texto, confianza = motor.leer_linea(cv2.cvtColor(junto, cv2.COLOR_GRAY2BGR))
    digitos = "".join(c for c in texto.replace("O", "0").replace("l", "1").replace("I", "1") if c.isdigit())
    resto = digitos[len(str(maestria)):]
    if confianza < MINIMO_CONFIANZA or not digitos.startswith(str(maestria)) or len(resto) != len(cifras):
        return True, None
    return True, int(resto)
