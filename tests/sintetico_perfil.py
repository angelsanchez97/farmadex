"""Pantallas sinteticas de Perfil > Equipamiento para probar el OCR sin el juego.

Imitan la estructura de las capturas reales del usuario (2560x1440, en espanol):
pestanas arriba, fila MAS USADO con porcentajes, barra "COMPLETADO x/y" con el
nombre de la categoria, y rejilla de 8 columnas de placas claras semitransparentes
sobre un fondo vistoso. Las dominadas llevan "RANGO MAXIMO" bajo el nombre; las no
dominadas van en gris, sin segunda linea y con el nombre algo mas abajo.

Las capturas reales viven en tests/fixtures/capturas_perfil/ y son la medida de
verdad; esto sirve para probar variantes (otros textos, otras resoluciones).
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TEXTO = (236, 240, 246)
TEXTO_APAGADO = (158, 164, 176)
CIAN = (90, 220, 240)
PLACA = (70, 82, 104)

FUENTES = ("seguisb.ttf", "segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf")

PESTANAS = ("PERFIL", "EQUIPAMIENTO", "ESTADÍSTICAS", "SINDICATOS", "DESAFÍOS", "LISTA DE DESEADOS")
MAS_USADO = ("INAROS PRIME", "AMPREX", "NUKOR KUVA", "GUANDAO PRIME", "HELIOS PRIME",
             "DESARMADOR PRIME", "VITZAL", "MAUSOLON", "VERITUX")


def fuente(tamano: int) -> ImageFont.FreeTypeFont:
    for nombre in FUENTES:
        try:
            return ImageFont.truetype(nombre, tamano)
        except OSError:
            continue
    return ImageFont.load_default()  # pragma: no cover


def pintar_pagina(
    tarjetas: list[tuple[str, bool | int | None]],
    categoria: str = "WARFRAME",
    completado: tuple[int, int] = (108, 116),
    ancho: int = 2560,
    alto: int = 1440,
    columnas: int = 8,
    linea_maximo: str = "RANGO MÁXIMO",
    con_mas_usado: bool = True,
    ruido: int = 6,
    semilla: int = 0,
) -> np.ndarray:
    """Devuelve la pantalla como array BGR (igual que `pantalla.capturar`).

    Cada tarjeta es (nombre, estado): True dominada, False no dominada, un entero
    "RANGO n" a medias, None sin linea.
    """
    k = ancho / 2560  # todo va en proporcion a la captura real
    img = _fondo(ancho, alto, semilla)
    d = ImageDraw.Draw(img, "RGBA")
    f_pestana, f_peq, f_nombre, f_rango = fuente(int(30 * k)), fuente(int(24 * k)), fuente(int(24 * k)), fuente(int(26 * k))

    x = int(610 * k)
    for i, p in enumerate(PESTANAS):
        d.text((x, int(135 * k)), p, fill=TEXTO if i == 1 else TEXTO_APAGADO, font=f_pestana)
        x += int(d.textlength(p, font=f_pestana)) + int(50 * k)

    if con_mas_usado:
        d.text((int(1210 * k), int(195 * k)), "MÁS USADO", fill=TEXTO_APAGADO, font=f_peq)
        paso = int(265 * k)
        for i, nombre in enumerate(MAS_USADO):
            x0 = int(190 * k) + i * paso
            d.text((x0 + int(100 * k), int(256 * k)), f"{12 + 7 * i}.0 %", fill=TEXTO, font=f_peq)
            d.rectangle((x0, int(300 * k), x0 + paso - int(20 * k), int(470 * k)), fill=PLACA + (170,))
            d.text((x0 + int(8 * k), int(405 * k)), nombre, fill=TEXTO, font=f_nombre)
            d.text((x0 + int(8 * k), int(433 * k)), linea_maximo, fill=CIAN, font=f_rango)

    y_barra = int(510 * k)
    d.rectangle((0, y_barra - int(20 * k), ancho, y_barra + int(45 * k)), fill=(20, 26, 40, 200))
    d.text((int(194 * k), y_barra), "COMPLETADO", fill=TEXTO_APAGADO, font=f_peq)
    d.text((int(477 * k), y_barra - int(8 * k)), f"{completado[0]}/{completado[1]}", fill=TEXTO, font=fuente(int(34 * k)))
    d.text((int(1009 * k), y_barra), categoria, fill=TEXTO, font=fuente(int(34 * k)))
    d.text((int(1910 * k), y_barra + int(6 * k)), "ORDENAR POR: NOMBRE", fill=TEXTO_APAGADO, font=f_peq)

    paso_x = int(275 * k)
    paso_y = int(255 * k)
    x_ini, y_ini = int(180 * k), int(600 * k)
    for n, (nombre, estado) in enumerate(tarjetas):
        fila, col = divmod(n, columnas)
        x0 = x_ini + col * paso_x
        y0 = y_ini + fila * paso_y
        if y0 + paso_y > alto - int(80 * k):
            break
        dominada = estado is True
        d.rectangle((x0, y0, x0 + paso_x - int(20 * k), y0 + paso_y - int(30 * k)),
                    fill=PLACA + (150 if dominada or isinstance(estado, int) else 90,))
        if dominada or (isinstance(estado, int) and not isinstance(estado, bool)):
            d.text((x0 + int(10 * k), y0 + int(140 * k)), nombre, fill=TEXTO, font=f_nombre)
            texto = linea_maximo if dominada else f"RANGO {estado}"
            d.text((x0 + int(10 * k), y0 + int(166 * k)), texto, fill=CIAN, font=f_rango)
            d.rectangle((x0 + int(10 * k), y0 + int(200 * k), x0 + paso_x - int(30 * k), y0 + int(206 * k)),
                        fill=CIAN)
        else:
            d.text((x0 + int(10 * k), y0 + int(166 * k)), nombre, fill=TEXTO_APAGADO, font=f_nombre)
    d.text((int(2000 * k), alto - int(105 * k)), "CAMBIAR HONORÍA", fill=TEXTO, font=f_peq)
    d.text((int(2335 * k), alto - int(108 * k)), "SALIR", fill=TEXTO, font=fuente(int(32 * k)))
    return _a_bgr(img, ruido, semilla)


def pintar_cabecera_perfil(nombre: str, rango_maestria: int, ancho=1920, alto=1080) -> np.ndarray:
    """Portada del perfil: nombre del jugador y "RANGO DE MAESTRÍA" con la cifra debajo."""
    img = _fondo(ancho, alto, 3)
    d = ImageDraw.Draw(img)
    d.text((120, 80), nombre.upper(), fill=TEXTO, font=fuente(40))
    d.text((120, 200), "RANGO DE MAESTRÍA", fill=TEXTO_APAGADO, font=fuente(22))
    d.text((120, 236), str(rango_maestria), fill=CIAN, font=fuente(64))
    d.text((120, 340), "CLAN", fill=TEXTO_APAGADO, font=fuente(22))
    d.text((120, 372), "TENNO DE PRUEBA", fill=TEXTO, font=fuente(28))
    return _a_bgr(img, 0, 0)


def _fondo(ancho: int, alto: int, semilla: int) -> Image.Image:
    """Degradado con manchas de color, como la warframe y sus efectos detras del menu."""
    yy, xx = np.mgrid[0:alto, 0:ancho].astype(np.float32)
    r = 30 + 60 * (xx / ancho)
    g = 20 + 40 * (yy / alto)
    b = 60 + 80 * ((xx + yy) / (ancho + alto))
    gen = np.random.default_rng(semilla)
    for _ in range(6):
        cx, cy = gen.uniform(0, ancho), gen.uniform(0, alto)
        radio = gen.uniform(150, 450)
        mancha = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * radio**2)))
        r += 90 * mancha * gen.uniform(0.2, 1)
        g += 60 * mancha * gen.uniform(0.2, 1)
        b += 120 * mancha * gen.uniform(0.2, 1)
    arr = np.stack([r, g, b], axis=2)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def _a_bgr(img: Image.Image, ruido: int, semilla: int) -> np.ndarray:
    arr = np.array(img.convert("RGB")).astype(np.int16)
    if ruido:
        arr += np.random.default_rng(semilla).normal(0, ruido, arr.shape).astype(np.int16)
    return np.clip(arr, 0, 255).astype(np.uint8)[:, :, ::-1].copy()
