"""Pantallas sinteticas de la pantalla de mejoras del arsenal y tarjetas de agrietado.

Imitan la captura real de la wiki (Arsenal_Upgrade_Screen 41.0.7, 1920x1080, en
ingles): cabecera "UPGRADES / EXCALIBUR [30]", panel de estadisticas a la izquierda,
dos filas de tarjetas de mod equipadas en el centro, la caja "SEARCH..." y dos
filas de la coleccion debajo. Cada tarjeta lleva el nombre centrado en letra
pequena (~20 px) sobre una ilustracion, que es lo que le cuesta al OCR.

Las tarjetas de agrietado copian las de la wiki: nombre del arma y del agrietado,
estadisticas con signo y porcentaje (una por linea, las largas a dos), y abajo
"MR 12" y las veces variado.

Las capturas reales que se bajaron para calibrar (wiki oficial, derechos de
terceros) NO estan en el repositorio; esto es lo que corre en las pruebas.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

TEXTO = (236, 236, 240)
SUAVE = (170, 170, 180)
DORADO = (214, 182, 110)
LILA = (196, 170, 236)
FUENTES = ("segoeui.ttf", "seguisb.ttf", "arial.ttf", "arialbd.ttf")
FUENTES_NEGRITA = ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "arial.ttf")


def fuente(tamano: int, negrita: bool = False) -> ImageFont.FreeTypeFont:
    for nombre in FUENTES_NEGRITA if negrita else FUENTES:
        try:
            return ImageFont.truetype(nombre, tamano)
        except OSError:
            continue
    return ImageFont.load_default()  # pragma: no cover


def _fondo(ancho: int, alto: int, semilla: int) -> Image.Image:
    """Nave con luces y sombras, como detras del arsenal."""
    yy, xx = np.mgrid[0:alto, 0:ancho].astype(np.float32)
    base = 26 + 30 * (yy / alto)
    r = base + 8 * (xx / ancho)
    g = base + 6
    b = base + 18
    gen = np.random.default_rng(semilla)
    for _ in range(5):
        cx, cy = gen.uniform(0, ancho), gen.uniform(0, alto)
        radio = gen.uniform(200, 500)
        mancha = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * radio**2)))
        r += 70 * mancha * gen.uniform(0.2, 1)
        g += 60 * mancha * gen.uniform(0.2, 1)
        b += 90 * mancha * gen.uniform(0.2, 1)
    arr = np.stack([r, g, b], axis=2)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def _tarjeta_mod(d: ImageDraw.ImageDraw, x0: int, y0: int, ancho: int, alto: int, nombre: str,
                 f: ImageFont.FreeTypeFont, gen, k: float, coste: int = 4) -> None:
    """Placa con una 'ilustracion' de manchas detras del nombre, como en el juego."""
    color = tuple(int(c) for c in gen.uniform(40, 110, 3))
    d.rectangle((x0, y0, x0 + ancho, y0 + alto), fill=color + (230,))
    for _ in range(3):
        cx, cy = gen.uniform(x0, x0 + ancho), gen.uniform(y0, y0 + alto)
        rad = gen.uniform(15, 45) * k
        tono = tuple(int(c) for c in gen.uniform(60, 160, 3))
        d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=tono + (120,))
    # Banda oscura tras el nombre (el juego oscurece esa franja) y el nombre centrado.
    d.rectangle((x0, y0 + alto * 0.42, x0 + ancho, y0 + alto * 0.72), fill=(20, 22, 30, 150))
    # El juego encoge la letra de los nombres largos para que quepan en la tarjeta.
    f_nombre = f
    while d.textlength(nombre, font=f_nombre) > ancho * 0.92 and f_nombre.size > 9:
        f_nombre = fuente(f_nombre.size - 1)
    d.text((x0 + ancho / 2, y0 + alto * 0.57), nombre, fill=TEXTO, font=f_nombre, anchor="mm")
    d.text((x0 + ancho - 14 * k, y0 + 12 * k), f"{coste}", fill=TEXTO, font=f, anchor="mm")
    d.rectangle((x0, y0 + alto - 6 * k, x0 + ancho, y0 + alto), fill=(60, 62, 74, 255))


def pintar_arsenal(
    equipo: str,
    equipados: list[str],
    coleccion: list[str],
    ancho: int = 1920,
    alto: int = 1080,
    idioma: str = "en",
    ruido: int = 4,
    semilla: int = 0,
    desenfoque: float = 0.0,
) -> np.ndarray:
    """Pantalla de mejoras como array BGR (lo que devuelve `pantalla.capturar`)."""
    k = ancho / 1920
    gen = np.random.default_rng(semilla)
    img = _fondo(ancho, alto, semilla)
    d = ImageDraw.Draw(img, "RGBA")
    f_cab = fuente(int(34 * k), negrita=True)
    f_peq = fuente(int(19 * k))
    f_nombre = fuente(int(20 * k))
    f_ui = fuente(int(22 * k))

    palabra = {"en": "UPGRADES", "es": "MEJORAS", "fr": "AMÉLIORATIONS", "de": "VERBESSERUNGEN", "pt": "MELHORIAS"}[idioma]
    d.text((190 * k, 48 * k), f"{palabra} / {equipo.upper()} [30]", fill=DORADO, font=f_cab)
    d.text((1560 * k, 58 * k), "446,940   50   1,265", fill=TEXTO, font=f_peq)

    # Panel de estadisticas a la izquierda.
    d.rectangle((96 * k, 112 * k, 520 * k, 620 * k), fill=(14, 16, 22, 200))
    d.text((106 * k, 118 * k), {"en": "CAPACITY", "es": "CAPACIDAD"}.get(idioma, "CAPACITY"), fill=TEXTO, font=f_ui)
    d.text((460 * k, 118 * k), "3/37", fill=TEXTO, font=f_ui)
    filas = (("Health", "Salud", "571"), ("Shield", "Escudo", "572"), ("Armor", "Armadura", "240"),
             ("Energy", "Energía", "150"), ("Sprint Speed", "Velocidad", "1"))
    for i, (en, es, valor) in enumerate(filas):
        y = (168 + 22 * i) * k
        d.text((106 * k, y), es if idioma == "es" else en, fill=SUAVE, font=f_peq)
        d.text((510 * k, y), valor, fill=TEXTO, font=f_peq, anchor="ra")
    d.text((106 * k, 300 * k), {"en": "ABILITY", "es": "HABILIDAD"}.get(idioma, "ABILITY"), fill=TEXTO, font=f_peq)
    for i, (en, es, valor) in enumerate((("Duration", "Duración", "110%"), ("Efficiency", "Eficiencia", "105%"),
                                         ("Range", "Alcance", "115%"), ("Strength", "Fuerza", "120%"))):
        y = (324 + 22 * i) * k
        d.text((106 * k, y), es if idioma == "es" else en, fill=SUAVE, font=f_peq)
        d.text((510 * k, y), valor, fill=TEXTO, font=f_peq, anchor="ra")
    d.text((900 * k, 124 * k), "CONFIG A", fill=DORADO, font=f_ui)
    d.text((1060 * k, 124 * k), "CONFIG B", fill=SUAVE, font=f_ui)
    d.text((1210 * k, 124 * k), "CONFIG C", fill=SUAVE, font=f_ui)

    # Tarjetas equipadas: aura arriba y dos filas de cuatro.
    ancho_t, alto_t = int(226 * k), int(112 * k)
    posiciones = [(846 * k, 204 * k)] + [
        ((600 + 244 * col) * k, (340 + 136 * fila) * k) for fila in range(2) for col in range(4)
    ]
    for (x0, y0), nombre in zip(posiciones, equipados):
        _tarjeta_mod(d, int(x0), int(y0), ancho_t, alto_t, nombre, f_nombre, gen, k)

    # Caja de busqueda y filtros.
    d.rectangle((96 * k, 632 * k, 520 * k, 664 * k), fill=(14, 16, 22, 220))
    d.text((106 * k, 638 * k), {"en": "SEARCH...", "es": "BUSCAR..."}.get(idioma, "SEARCH..."), fill=SUAVE, font=f_ui)
    d.text((940 * k, 606 * k), {"en": "ALL", "es": "TODOS"}.get(idioma, "ALL"), fill=TEXTO, font=f_ui)
    d.text((1410 * k, 638 * k), {"en": "DRAIN", "es": "CONSUMO"}.get(idioma, "DRAIN"), fill=SUAVE, font=f_ui)

    # Coleccion: dos filas de ocho.
    for n, nombre in enumerate(coleccion[:16]):
        fila, col = divmod(n, 8)
        x0 = (100 + 250 * col) * k
        y0 = (692 + 134 * fila) * k
        _tarjeta_mod(d, int(x0), int(y0), ancho_t, alto_t, nombre, f_nombre, gen, k)

    d.text((1330 * k, 996 * k), {"en": "ACTIONS", "es": "ACCIONES"}.get(idioma, "ACTIONS"), fill=DORADO, font=f_ui)
    d.text((1470 * k, 996 * k), "MODS", fill=DORADO, font=f_ui)
    d.text((1570 * k, 996 * k), {"en": "REMOVE ALL", "es": "QUITAR TODO"}.get(idioma, "REMOVE ALL"), fill=DORADO, font=f_ui)
    d.text((1750 * k, 996 * k), {"en": "BACK", "es": "ATRÁS"}.get(idioma, "BACK"), fill=DORADO, font=f_ui)
    return _a_bgr(img, ruido, semilla, desenfoque)


def pintar_tarjeta_agrietado(
    arma: str,
    nombre: str,
    estadisticas: list[tuple[str, float, str]],
    maestria: int = 12,
    variado: int | None = 3,
    ancho: int = 316,
    alto: int = 400,
    ruido: int = 3,
    semilla: int = 0,
    desenfoque: float = 0.0,
    en_dos_lineas: bool = False,
    unidades: dict[str, str] | None = None,
) -> np.ndarray:
    """Tarjeta de agrietado como array BGR.

    `estadisticas` son (signo "+"/"-", valor, texto) tal y como los escribe el juego;
    `unidades` permite cambiar el "%" por "" o "s" para un atributo por su texto.
    """
    k = ancho / 316
    gen = np.random.default_rng(semilla)
    yy, xx = np.mgrid[0:alto, 0:ancho].astype(np.float32)
    base = np.stack([24 + 14 * (yy / alto), 16 + 8 * (yy / alto), 40 + 20 * (yy / alto)], axis=2)
    for _ in range(4):
        cx, cy = gen.uniform(0, ancho), gen.uniform(0, alto * 0.5)
        rad = gen.uniform(40, 120) * k
        mancha = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * rad**2)))[:, :, None]
        base += mancha * gen.uniform(30, 120, 3)
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((0, alto * 0.36, ancho, alto), fill=(30, 20, 48, 190))
    d.rectangle((0, 0, ancho, alto), outline=(150, 120, 200), width=int(3 * k))
    f_cab = fuente(int(19 * k))
    f_stat = fuente(int(15 * k))
    f_pie = fuente(int(14 * k))
    d.text((ancho - 28 * k, 14 * k), "18", fill=TEXTO, font=f_pie)
    y = alto * 0.40
    if en_dos_lineas:
        d.text((ancho / 2, y), arma, fill=TEXTO, font=f_cab, anchor="mm")
        y += 22 * k
        d.text((ancho / 2, y), nombre, fill=TEXTO, font=f_cab, anchor="mm")
    else:
        d.text((ancho / 2, y), f"{arma} {nombre}", fill=TEXTO, font=f_cab, anchor="mm")
    y += 28 * k
    for signo, valor, texto in estadisticas:
        unidad = (unidades or {}).get(texto, "%")
        numero = f"{valor:.1f}".rstrip("0").rstrip(".")
        linea = f"{signo}{numero}{unidad} {texto}"
        largo = d.textlength(linea, font=f_stat)
        if largo > ancho * 0.9 and " " in texto:
            palabras = texto.split()
            corte = len(palabras) // 2 + 1
            d.text((ancho / 2, y), f"{signo}{numero}{unidad} {' '.join(palabras[:corte])}", fill=LILA, font=f_stat, anchor="mm")
            y += 18 * k
            d.text((ancho / 2, y), " ".join(palabras[corte:]), fill=LILA, font=f_stat, anchor="mm")
        else:
            d.text((ancho / 2, y), linea, fill=LILA, font=f_stat, anchor="mm")
        y += 20 * k
    d.text((14 * k, alto - 30 * k), f"MR {maestria}", fill=TEXTO, font=f_pie)
    if variado is not None:
        # El icono de "variado" (flecha circular) se pinta como un circulo: el OCR lo lee
        # como "O" o "0", igual que en las capturas reales.
        d.text((ancho - 14 * k, alto - 30 * k), f"{variado}", fill=TEXTO, font=f_pie, anchor="ra")
        r = 6 * k
        cx = ancho - 14 * k - d.textlength(f"{variado}", font=f_pie) - 10 * k
        cy = alto - 30 * k + 8 * k
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=TEXTO, width=max(1, int(2 * k)))
    return _a_bgr(img, ruido, semilla, desenfoque)


def _a_bgr(img: Image.Image, ruido: int, semilla: int, desenfoque: float = 0.0) -> np.ndarray:
    if desenfoque:
        img = img.filter(ImageFilter.GaussianBlur(desenfoque))
    arr = np.array(img.convert("RGB")).astype(np.int16)
    if ruido:
        arr += np.random.default_rng(semilla).normal(0, ruido, arr.shape).astype(np.int16)
    return np.clip(arr, 0, 255).astype(np.uint8)[:, :, ::-1].copy()
