"""Validacion cruzada de la pantalla de mejoras: los huecos que se VEN ocupados frente a los
mods que se leyeron.

Una build leida con un mod de menos es una build inutil, y peor si no se avisa. Con los
nombres que si se leyeron se mide la rejilla de huecos del juego (datos/disposicion_build.py)
y, por cada hueco en el que no cayo ningun nombre, se mira la propia imagen de la tarjeta:

- si el hueco esta claramente vacio (el recuadro gris translucido del juego, sin letras ni
  dibujo), no hay nada que leer;
- si no, se recorta la tarjeta, se amplia y se vuelve a leer por separado, tal cual y con
  un preprocesado que no depende del color (el canal mas fuerte, y en negativo), por si el
  tema de colores del jugador o una tarjeta medio tapada se la comieron en la pasada grande;
- si aun asi no sale un mod, el hueco se devuelve como "no leido" con lo que se leyo ahi,
  para que la interfaz lo pinte como "no he podido leer este mod" en vez de dejarlo vacio.

Nunca se inventa: una relectura solo vale si casa con un mod con la misma seguridad que la
pasada grande, y un mod ya equipado no se repite (el juego no deja llevar dos iguales).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..datos import disposicion_build as disposicion
from ..registro_log import obtener
from .ocr import RE_RANGO_TARJETA, Casador, ErrorMotorOCR, Leido, Reconocido, unir_filas

log = obtener("builds")

# Donde cae la tarjeta de un mod respecto al punto de su nombre (x centro, y borde de abajo),
# en pasos de columna y de fila. Medido en capturas reales: el nombre va a un 70 % del alto
# de la tarjeta (0,685 filas) y la tarjeta mide 0,915 pasos de ancho.
TARJETA_ARRIBA, TARJETA_ABAJO, TARJETA_MEDIO_ANCHO = 0.48, 0.21, 0.4575
# El bloque de un arcano (icono, nombre y rombos del rango) respecto al borde de abajo del nombre.
ARCANO_ARRIBA, ARCANO_ABAJO, ARCANO_MEDIO_ANCHO = 0.62, 0.16, 0.45
# Tamano al que se normaliza el recorte para medirlo (independiente de la resolucion) y
# alto al que se amplia para releerlo (los nombres miden ~20 px a 1080p; el reconocedor
# del OCR trabaja a 48 px de alto de linea).
ANCHO_MEDIDA, ALTO_MEDIDA = 300, 200
ALTO_RELECTURA = 260
# Un hueco vacio del juego: recuadro translucido liso. Medido sobre el banco de capturas
# reales (recortes normalizados a 300x200): los vacios de verdad quedan por debajo de
# estos dos a la vez (bordes hasta 0,019 y desviacion hasta 24, salvo un video de 4K muy
# comprimido: 0,042 y 31) y las tarjetas puestas los superan con holgura (bordes desde
# 0,059 y desviacion desde 28). Lo que queda entre medias se relee con el OCR.
VACIO_BORDES, VACIO_DESVIACION = 0.03, 28.0
# Y lo que, sin ninguna letra que leer, es sin duda una tarjeta (o algo encima del hueco):
# el dibujo de una tarjeta tapada por otra ampliada da bordes de 0,079, desviacion de 44 o
# brillo de 0,66 segun la ilustracion; un hueco vacio nunca llega a ninguno de los tres.
OCUPADO_BORDES, OCUPADO_DESVIACION, OCUPADO_BRILLO = 0.05, 40.0, 0.03
MINIMO_CONFIANZA_RELECTURA = 0.5


@dataclass
class HuecoNoLeido:
    """Un hueco que se ve ocupado pero del que no salio ningun mod."""

    clave: str                               # "mod3", "aura", "arcano1"...
    tipo: str                                # "mod", "aura", "exilus", "postura", "arcano"
    caja: tuple[int, int, int, int]          # x, y, ancho, alto de la tarjeta en la captura
    texto: str = ""                          # lo que se leyo ahi (vacio si nada)
    # "tapado" (hay texto pero no es un nombre de mod: la ayuda de otra tarjeta encima),
    # "sin_reconocer" (parece un nombre pero no casa) o "sin_texto" (dibujo sin letras).
    motivo: str = "sin_texto"


@dataclass
class TiposDeHueco:
    """Lo que hace falta del indice para saber que plantilla de huecos tiene el equipo y que
    mods son auras o posturas (van en su hueco propio)."""

    tipos: dict[int, str] = field(default_factory=dict)   # item_id -> tipo del indice
    auras: set[int] = field(default_factory=set)
    posturas: set[int] = field(default_factory=set)

    def tipo_de_mod(self, item_id: int) -> str:
        if item_id in self.auras:
            return "aura"
        if item_id in self.posturas:
            return "postura"
        return "mod"


def cargar_tipos_de_hueco(con) -> TiposDeHueco:
    """Las mismas consultas que usa la pestana Build para pintar la rejilla."""
    salida = TiposDeHueco()
    try:
        salida.tipos = dict(con.execute("SELECT id, tipo FROM items"))
    except Exception:  # noqa: BLE001 - indice raro: sin tipos se usa solo la categoria
        salida.tipos = {}
    try:
        salida.posturas = {i for (i,) in con.execute(
            "SELECT id FROM items WHERE categoria = 'Mods' AND tipo = 'Stance Mod'")}
    except Exception:  # noqa: BLE001
        salida.posturas = set()
    try:
        salida.auras = {i for (i,) in con.execute(
            "SELECT item_id FROM detalles WHERE datos LIKE '%\"compat\": \"AURA\"%'")}
    except Exception:  # noqa: BLE001 - indice sin detalles: no se distinguen
        salida.auras = set()
    return salida


def colocar_build(build, categorias: dict[int, str], tipos: TiposDeHueco | None) -> disposicion.Disposicion | None:
    """La colocacion de lo leido en los huecos del equipo, como la hace la pestana; None si
    el equipo no tiene plantilla (companeros, archwing, equipo sin reconocer)."""
    if build.equipo is None or not build.ancho or not build.alto:
        return None
    tipos = tipos or TiposDeHueco()
    clases = disposicion.plantillas_de(categorias.get(build.equipo.item_id), tipos.tipos.get(build.equipo.item_id))
    if not clases:
        return None
    puntos = [disposicion.punto_de(r.caja, build.ancho, build.alto, tipos.tipo_de_mod(r.item_id)) for r in build.equipados]
    arcanos = [disposicion.punto_de(r.caja, build.ancho, build.alto, "arcano") for r in build.arcanos]
    colocaciones = [disposicion.colocar(clase, puntos, arcanos, medio_ancho=build.ancho / 2 / build.alto) for clase in clases]
    if len(colocaciones) == 1:
        return colocaciones[0]
    # Varias plantillas posibles (armas exaltadas): la que coloca mas de lo leido, si es una sola.
    seguras = [c for c in colocaciones if c.segura]
    if not seguras:
        return colocaciones[0]
    mejor = max(len(c.mods) + len(c.arcanos) for c in seguras)
    empatadas = [c for c in seguras if len(c.mods) + len(c.arcanos) == mejor]
    if any(c.mods != empatadas[0].mods or c.arcanos != empatadas[0].arcanos for c in empatadas[1:]):
        return disposicion.Disposicion(clase=empatadas[0].clase, huecos=list(empatadas[0].huecos),
                                       sueltos_mods=list(range(len(puntos))), sueltos_arcanos=list(range(len(arcanos))),
                                       motivo="ambigua")
    return empatadas[0]


def caja_de_hueco(colocacion: disposicion.Disposicion, hueco: disposicion.Hueco, ancho: int, alto: int):
    """(x, y, ancho, alto) en pixeles de la tarjeta (o del bloque del arcano) de ese hueco."""
    centro = colocacion.centro_de(hueco)
    if centro is None:
        return None
    cx, yb = centro
    paso = colocacion.paso * alto
    fila = paso * disposicion.RELACION_FILAS
    x_c, y_b = cx * alto + ancho / 2, yb * alto
    if hueco.tipo == "arcano":
        x0, x1 = x_c - ARCANO_MEDIO_ANCHO * paso, x_c + ARCANO_MEDIO_ANCHO * paso
        y0, y1 = y_b - ARCANO_ARRIBA * fila, y_b + ARCANO_ABAJO * fila
    else:
        x0, x1 = x_c - TARJETA_MEDIO_ANCHO * paso, x_c + TARJETA_MEDIO_ANCHO * paso
        y0, y1 = y_b - TARJETA_ARRIBA * fila, y_b + TARJETA_ABAJO * fila
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(ancho, int(x1)), min(alto, int(y1))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return x0, y0, x1 - x0, y1 - y0


def medidas_de_tarjeta(imagen, caja) -> dict[str, float]:
    """Cuanto "dibujo" hay en la banda del nombre de la tarjeta, sobre el recorte normalizado:
    densidad de bordes, desviacion del brillo y fraccion de pixeles claros."""
    import cv2
    import numpy as np

    x, y, w, h = caja
    recorte = imagen[y:y + h, x:x + w]
    if recorte.size == 0:
        return {"bordes": 0.0, "desviacion": 0.0, "brillo": 0.0}
    recorte = cv2.resize(recorte, (ANCHO_MEDIDA, ALTO_MEDIDA), interpolation=cv2.INTER_AREA)
    fuerte = recorte.max(axis=2) if recorte.ndim == 3 else recorte
    banda = fuerte[int(ALTO_MEDIDA * 0.5):int(ALTO_MEDIDA * 0.95), int(ANCHO_MEDIDA * 0.1):int(ANCHO_MEDIDA * 0.9)]
    bordes = cv2.Canny(np.ascontiguousarray(banda), 80, 160)
    return {"bordes": float((bordes > 0).mean()), "desviacion": float(banda.std()), "brillo": float((banda >= 200).mean())}


def parece_vacio(imagen, caja) -> bool:
    """Si el hueco es sin duda el recuadro vacio del juego (no hace falta ni releerlo)."""
    m = medidas_de_tarjeta(imagen, caja)
    return m["bordes"] < VACIO_BORDES and m["desviacion"] < VACIO_DESVIACION


def parece_ocupado(imagen, caja) -> bool:
    """Si en el hueco hay sin duda una tarjeta o algo encima, aunque no se lea ninguna letra."""
    m = medidas_de_tarjeta(imagen, caja)
    return m["bordes"] >= OCUPADO_BORDES or m["desviacion"] >= OCUPADO_DESVIACION or m["brillo"] >= OCUPADO_BRILLO


def variantes_de_lectura(recorte):
    """El recorte ampliado, tal cual y sin color (canal mas fuerte y su negativo), en BGR."""
    import cv2
    import numpy as np

    h, w = recorte.shape[:2]
    if h < ALTO_RELECTURA:
        factor = ALTO_RELECTURA / h
        recorte = cv2.resize(recorte, (max(1, round(w * factor)), ALTO_RELECTURA), interpolation=cv2.INTER_CUBIC)
    fuerte = np.ascontiguousarray(recorte.max(axis=2))
    return [recorte, np.dstack([fuerte] * 3), np.dstack([255 - fuerte] * 3)]


RE_RANGO_SUELTO = re.compile(r"^\W*\d{1,2}\W{0,2}[A-Za-z]?\W*$")


def _candidatos(lineas: list[Leido], alto_recorte: int) -> list[tuple[str, list[Leido]]]:
    """Textos a casar en una tarjeta releida: cada linea (sin el rango de arriba) y las
    parejas de lineas seguidas (nombres a dos lineas)."""
    utiles = [l for l in sorted(lineas, key=lambda l: (l.y, l.x))
              if not RE_RANGO_TARJETA.match(l.texto.strip()) and not RE_RANGO_SUELTO.match(l.texto)
              and len(re.sub(r"[^A-Za-zÀ-ɏ]", "", l.texto)) >= 3]
    salida: list[tuple[str, list[Leido]]] = []
    for i, l in enumerate(utiles):
        salida.append((l.texto, [l]))
        if i + 1 < len(utiles):
            salida.append((f"{l.texto} {utiles[i + 1].texto}", [l, utiles[i + 1]]))
    return salida


def _todo_mayusculas(texto: str) -> bool:
    letras = [c for c in texto if c.isalpha()]
    return len(letras) >= 4 and all(c.isupper() for c in letras)


def releer_tarjeta(imagen, caja, motor, casador: Casador, categorias: dict[int, str], umbral: int,
                   categoria: str = "Mods", limpiar=None, solo_ids=None) -> tuple[Reconocido | None, str]:
    """Relee la tarjeta de un hueco por separado: (lo reconocido o None, el mejor texto leido).

    `limpiar(texto) -> list[str]` da las variantes del texto sin la basura que el OCR pega a
    los nombres (lo pone builds.py); sin el solo se prueba el texto tal cual.
    Con `solo_ids` solo vale lo que case con uno de esos objetos.
    """
    x, y, w, h = caja
    recorte = imagen[y:y + h, x:x + w]
    if recorte.size == 0 or getattr(recorte, "ndim", 0) != 3:
        return None, ""
    escala = max(1.0, ALTO_RELECTURA / h)
    mejor_texto = ""
    for variante in variantes_de_lectura(recorte):
        try:
            leidos = motor.leer_tira(variante)
        except ErrorMotorOCR:
            return None, mejor_texto
        lineas = unir_filas([l for l in leidos if l.confianza >= MINIMO_CONFIANZA_RELECTURA])
        for texto, trozos in _candidatos(lineas, variante.shape[0]):
            if _todo_mayusculas(texto):
                continue
            if not mejor_texto or len(texto) > len(mejor_texto):
                mejor_texto = texto
            intentos = [texto] + ([t for t in limpiar(texto) if t != texto] if limpiar else [])
            for intento in intentos:
                item_id, etiqueta, puntos = casador.casar(intento, umbral)
                if item_id and categorias.get(item_id) == categoria and (solo_ids is None or item_id in solo_ids):
                    x0 = min(l.x for l in trozos) / escala + x
                    y0 = min(l.y for l in trozos) / escala + y
                    x1 = max(l.x + l.ancho for l in trozos) / escala + x
                    y1 = max(l.y + l.alto for l in trozos) / escala + y
                    return Reconocido(texto, item_id, etiqueta, puntos, (int(x0), int(y0), int(x1 - x0), int(y1 - y0))), texto
    return None, mejor_texto


def _texto_en(lineas: list[Leido], caja) -> list[Leido]:
    """Las lineas de la pasada grande cuyo centro cae dentro de la caja."""
    x, y, w, h = caja
    return [l for l in lineas if x <= l.x + l.ancho / 2 <= x + w and y <= l.y + l.alto / 2 <= y + h]


def completar_huecos(imagen, build, motor, casador: Casador, categorias: dict[int, str],
                     tipos: TiposDeHueco | None, umbral: int, limpiar=None) -> None:
    """Rellena `build.colocacion`, `build.huecos_vistos` y `build.no_leidos`, y anade a
    `build.equipados`/`build.arcanos` lo que salga de releer las tarjetas sin nombre."""
    build.no_leidos = []
    colocacion = colocar_build(build, categorias, tipos)
    build.colocacion = colocacion
    if colocacion is None or not colocacion.segura or not colocacion.paso:
        return
    ancho, alto = build.ancho, build.alto
    tapados_por_ampliada = recolocar_sueltos(colocacion, build, tipos, ancho, alto, imagen)
    zonas_ayuda = zonas_que_tapan(build.lineas, alto)
    zonas_ampliadas = zonas_de_tarjetas_ampliadas(build)
    equipados_ids = {r.item_id for r in build.equipados}
    arcanos_ids = {r.item_id for r in build.arcanos}
    nuevos = False
    vistos = 0
    for hueco in colocacion.huecos:
        es_arcano = hueco.tipo == "arcano"
        asignado = colocacion.arcanos.get(hueco.clave) if es_arcano else colocacion.mods.get(hueco.clave)
        if asignado is not None:
            vistos += 1
            continue
        caja = caja_de_hueco(colocacion, hueco, ancho, alto)
        if caja is None:
            continue
        dentro = _texto_en(build.lineas, caja)
        if _admite_rotulo_de_vacio(hueco) and any(_es_hueco_vacio(l.texto) for l in dentro):
            continue  # "RANURA DE ARCANO VACIA", "Requires Exilus Adapter": vacio de verdad
        if hueco.clave in tapados_por_ampliada or _tapado_por_ayuda(caja, zonas_ampliadas):
            vistos += 1
            build.no_leidos.append(HuecoNoLeido(hueco.clave, hueco.tipo, caja, "", "tapado"))
            log.info("Hueco %s: tapado por una tarjeta ampliada", hueco.clave)
            continue
        if not dentro and _tapado_por_ayuda(caja, zonas_ayuda):
            # Debajo de la ayuda de otra tarjeta o de un arcano (un panel oscuro con su
            # descripcion): se ve liso como un hueco vacio, pero no se sabe que hay.
            vistos += 1
            build.no_leidos.append(HuecoNoLeido(hueco.clave, hueco.tipo, caja, "", "tapado"))
            log.info("Hueco %s: tapado por una ayuda abierta", hueco.clave)
            continue
        if not dentro and parece_vacio(imagen, caja):
            continue
        # Hay algo: tarjeta puesta cuyo nombre no caso, o tapada. Se relee aparte.
        categoria = "Arcanes" if es_arcano else "Mods"
        reconocido, texto = releer_tarjeta(imagen, caja, motor, casador, categorias, umbral, categoria, limpiar)
        if reconocido is None and dentro and limpiar:
            # Lo que leyo la pasada grande ahi, limpio de restos del rango y signos.
            for l in dentro:
                for intento in limpiar(l.texto):
                    item_id, etiqueta, puntos = casador.casar(intento, umbral)
                    if item_id and categorias.get(item_id) == categoria:
                        reconocido = Reconocido(l.texto, item_id, etiqueta, puntos, (l.x, l.y, l.ancho, l.alto))
                        break
                if reconocido is not None:
                    break
        vistos += 1
        if reconocido is not None:
            ya = reconocido.item_id in (arcanos_ids if es_arcano else equipados_ids)
            if ya:
                # El mismo mod ya esta en otro hueco: lo que hay aqui es su tarjeta ampliada
                # (crece hacia abajo y tapa este hueco). No se repite el mod, y el hueco queda
                # como tapado: debajo hay una tarjeta que no se ve (captura real de Uriel con
                # el aura ampliada sobre el mod2).
                build.no_leidos.append(HuecoNoLeido(hueco.clave, hueco.tipo, caja, texto, "tapado"))
                log.info("Hueco %s: tapado por la tarjeta ampliada de %r", hueco.clave, reconocido.nombre)
                continue
            log.info("Hueco %s: releida la tarjeta aparte: %r -> %s (%.0f)", hueco.clave, reconocido.texto_ocr,
                     reconocido.nombre, reconocido.puntuacion)
            if es_arcano:
                build.arcanos.append(reconocido); arcanos_ids.add(reconocido.item_id)
            else:
                build.equipados.append(reconocido); equipados_ids.add(reconocido.item_id)
            nuevos = True
            continue
        texto = texto or " ".join(l.texto for l in dentro)
        if texto and _admite_rotulo_de_vacio(hueco) and _es_hueco_vacio(texto):
            continue  # lo releido dice que esta vacio ("Wymaga Adapter Exilus")
        if not texto and not parece_ocupado(imagen, caja):
            # Ni una letra y un aspecto entre vacio y tarjeta (un hueco vacio en un video
            # muy comprimido): se da por vacio antes que avisar de un mod que no esta.
            vistos -= 1
            continue
        motivo = "sin_texto" if not texto else ("tapado" if _parece_ayuda(texto, dentro) else "sin_reconocer")
        if motivo == "sin_reconocer" and _parece_agrietado(texto, build):
            # Un mod agrietado (riven): "Falcor Para-critanem", el nombre del arma y un nombre
            # inventado por el juego. No esta en el catalogo y no es un fallo de lectura.
            motivo = "agrietado"
        build.no_leidos.append(HuecoNoLeido(hueco.clave, hueco.tipo, caja, texto, motivo))
        log.info("Hueco %s: se ve ocupado pero no se pudo leer (%s): %r", hueco.clave, motivo, texto)
    build.huecos_vistos = vistos
    if nuevos:
        # Con los mods nuevos la rejilla se vuelve a calcular (ahora caen en su hueco).
        build.colocacion = colocar_build(build, categorias, tipos)


def zona_de_tarjeta_ampliada(build, reconocido: Reconocido, zonas=None) -> tuple[int, int, int, int] | None:
    """La caja de la descripcion de la tarjeta si `reconocido` es el nombre de una tarjeta
    ampliada (la que el juego agranda bajo el raton o la que se lleva cogida): un bloque de
    frases que empieza en el nombre y va centrado con el; None si es una tarjeta normal."""
    x, y, w, h = reconocido.caja
    cx = x + w / 2
    paso = _paso_en_pixeles(build)
    if zonas is None:
        zonas = zonas_de_ayuda(build.lineas, margen=False)
    for zx, zy, zw, zh in zonas:
        if abs(zx + zw / 2 - cx) <= DESCENTRADO_DUDA * paso and zy - 1.5 * h <= y <= zy + h and zh >= 2.5 * h:
            return zx, zy, zw, zh
    # Una tarjeta de descripcion corta ("+110% Status Duration") no llega a bloque de ayuda:
    # se reconoce por esa linea con cifras y, debajo, el rotulo del tipo en mayusculas
    # ("MELEE", "WARFRAME", "PISTOLA"), todo centrado con el nombre (captura real de
    # Lasting Sting ampliada en Harmony).
    debajo = [l for l in build.lineas
              if abs(l.x + l.ancho / 2 - cx) <= DESCENTRADO_DUDA * paso and y + h <= l.y + l.alto / 2 <= y + h + 5 * h]
    frases = [l for l in debajo if RE_LINEA_DE_EFECTO.search(l.texto) and len(l.texto.strip()) >= 6]
    rotulos = [l for l in debajo if RE_ROTULO_DE_TIPO.match(l.texto.strip())
               and any(f.y + f.alto / 2 < l.y + l.alto / 2 for f in frases)]
    if frases and rotulos:
        partes = [reconocido.caja] + [(l.x, l.y, l.ancho, l.alto) for l in frases + rotulos]
        x0, y0 = min(p[0] for p in partes), min(p[1] for p in partes)
        x1, y1 = max(p[0] + p[2] for p in partes), max(p[1] + p[3] for p in partes)
        return x0, y0, x1 - x0, y1 - y0
    return None


RE_LINEA_DE_EFECTO = re.compile(r"[%+]|\d")
RE_ROTULO_DE_TIPO = re.compile(r"^[A-ZÁÉÍÓÚÄÖÜÇÑ][A-ZÁÉÍÓÚÄÖÜÇÑ\-]{2,15}(?: [A-ZÁÉÍÓÚÄÖÜÇÑ\-]{2,15})?$")


# Una tarjeta ampliada bajo el raton lleva el nombre hasta ~1,5 veces mas alto que el de
# las tarjetas normales (medido en 132 tarjetas ampliadas del banco: mediana 1,11, maxima
# 1,48). Una tarjeta cogida con el raton y arrastrada se pinta mucho mas grande (1,9): no
# esta en ningun hueco, asi que no se puede decir que este puesta.
ALTURA_TARJETA_EN_LA_MANO = 1.7


def _alto_maximo(build, reconocido: Reconocido) -> int:
    x, y, w, h = reconocido.caja
    dentro = [l.alto for l in build.lineas if x <= l.x + l.ancho / 2 <= x + w and y <= l.y + l.alto / 2 <= y + h]
    return max(dentro) if dentro else h


def apartar_tarjetas_en_la_mano(build) -> None:
    """Saca de `build.equipados` la tarjeta que el jugador lleva cogida con el raton (una
    tarjeta ampliada mucho mas grande que las demas) y la deja como dudosa en
    `build.sin_identificar`: "Disciplina de combate" arrastrada por encima del rotulo hacia
    el hueco del aura salia como puesta (captura real)."""
    import statistics

    if not build.equipados:
        return
    zonas = zonas_de_ayuda(build.lineas, margen=False)
    ampliadas = {id(r) for r in build.equipados if zona_de_tarjeta_ampliada(build, r, zonas) is not None}
    if not ampliadas:
        return
    normales = [_alto_maximo(build, r) for r in list(build.equipados) + list(build.coleccion) if id(r) not in ampliadas]
    if len(normales) < 3:
        return
    normal = statistics.median(normales)
    quitar = [r for r in build.equipados
              if id(r) in ampliadas and _alto_maximo(build, r) >= ALTURA_TARJETA_EN_LA_MANO * normal]
    for r in quitar:
        log.info("Mod %r: tarjeta cogida con el raton (mucho mayor que las demas): no se da por puesta", r.nombre)
        build.equipados.remove(r)
        build.sin_identificar.append(f"{r.nombre} (¿puesta?)")


# Cuanto se mueve el nombre de una tarjeta ampliada respecto al de su hueco, en filas
# (medido en ~60 tarjetas ampliadas del banco con su hueco de verdad: de -0,35 a +1,53).
BAJADA_MINIMA, BAJADA_MAXIMA = -0.36, 1.6


def recolocar_sueltos(colocacion: disposicion.Disposicion, build, tipos: TiposDeHueco | None,
                      ancho: int, alto: int, imagen=None) -> set[str]:
    """Un mod leido que no cayo en ningun hueco (su tarjeta estaba ampliada bajo el cursor)
    va al hueco que le toca, si se sabe cual es. La tarjeta ampliada crece hacia arriba y
    hacia abajo y su nombre baja entre media fila y fila y media respecto al de su hueco
    (medido en ~60 tarjetas ampliadas del banco con su hueco de verdad), asi que tapa
    tambien el hueco de encima o el de debajo de su columna. Si solo hay un hueco libre (y
    que no se ve vacio) que le pueda tocar, va ahi y los que tape debajo quedan como "no
    leidos". Si hay dos (un mod del mod7 con el nombre media fila mas abajo y el mod3
    tapado; uno del exilus con el nombre fila y media mas abajo y el mod3 tapado), no se
    sabe cual es el suyo: el mod se queda suelto (puesto, pero sin hueco) y los dos huecos
    como no leidos, en vez de ponerlo en el que no es (capturas reales)."""
    tapados: set[str] = set()
    if not colocacion.paso or not colocacion.sueltos_mods:
        return tapados
    tipos = tipos or TiposDeHueco()
    paso = colocacion.paso * alto
    fila = paso * disposicion.RELACION_FILAS
    libres = [h for h in colocacion.huecos if h.tipo != "arcano" and h.clave not in colocacion.mods]
    for i in sorted(colocacion.sueltos_mods, key=lambda i: build.equipados[i].caja[1]):
        r = build.equipados[i]
        tipo = tipos.tipo_de_mod(r.item_id)
        x, y, w, h = r.caja
        cx, cy = x + w / 2, y + h / 2
        candidatos = []
        for hueco in libres:
            if tipo not in disposicion._ACEPTA[hueco.tipo]:
                continue
            centro = colocacion.centro_de(hueco)
            if centro is None:
                continue
            hx = centro[0] * alto + ancho / 2
            arriba = centro[1] * alto - TARJETA_ARRIBA * fila  # borde de arriba de la tarjeta
            baja = (y + h - centro[1] * alto) / fila  # cuanto ha bajado el nombre, en filas
            if abs(cx - hx) > 0.3 * paso or not (BAJADA_MINIMA <= baja <= BAJADA_MAXIMA):
                continue
            caja = caja_de_hueco(colocacion, hueco, ancho, alto)
            if imagen is not None and caja is not None and parece_vacio(imagen, caja):
                continue
            candidatos.append((arriba, hueco))
        if len(candidatos) > 1:
            log.info("Mod suelto %r (tarjeta ampliada): puede ser de %s; no se sabe cual", r.nombre,
                     ", ".join(hu.clave for _a, hu in candidatos))
            for _a, hueco in candidatos:
                tapados.add(hueco.clave)
                libres.remove(hueco)
            continue
        if candidatos:
            _arriba, mejor = candidatos[0]
            colocacion.mods[mejor.clave] = i
            colocacion.sueltos_mods.remove(i)
            libres.remove(mejor)
            log.debug("Mod suelto %r (tarjeta ampliada) colocado en %s", r.nombre, mejor.clave)
            # Los huecos libres de la misma columna que quedan bajo la tarjeta ampliada (hasta
            # un poco por debajo del nombre) estan tapados por ella, se vea lo que se vea.
            fondo = y + h + 0.3 * fila
            for hueco in list(libres):
                centro = colocacion.centro_de(hueco)
                if centro is None or hueco is mejor:
                    continue
                hx = centro[0] * alto + ancho / 2
                arriba_h = centro[1] * alto - TARJETA_ARRIBA * fila
                if abs(hx - cx) <= 0.3 * paso and _arriba < arriba_h < fondo:
                    tapados.add(hueco.clave)
    return tapados


RE_FRASE_AYUDA = re.compile(r"[%\d]|[.,:;]\s*$|^[a-záéíóúñ]")
MINIMO_LINEAS_AYUDA = 3
SOLAPE_TAPADO = 0.35


def zonas_de_ayuda(lineas: list[Leido], margen: bool = True) -> list[tuple[int, int, int, int]]:
    """Las cajas (x, y, ancho, alto) de los paneles de ayuda abiertos: bloques de tres o mas
    lineas de descripcion (frases con cifras, signos o en minuscula) una debajo de otra. La
    ayuda de un mod o de un arcano se pinta encima de los huecos y los tapa. Con `margen` la
    caja lleva el borde del panel alrededor del texto; sin el, solo lo que ocupa el texto."""
    # Se agrupan todas las lineas (el titulo de la ayuda y sus rotulos no son frases, pero
    # estan en el mismo panel) y solo cuentan los grupos con dos frases o mas: la tarjeta de
    # un mod (su rango y su nombre a dos lineas) no llega.
    grupos: list[list[Leido]] = []
    for l in sorted(lineas, key=lambda l: l.y):
        for grupo in grupos:
            ultima = grupo[-1]
            solape_x = min(ultima.x + ultima.ancho, l.x + l.ancho) - max(ultima.x, l.x)
            if solape_x > 0 and -0.3 * l.alto <= l.y - (ultima.y + ultima.alto) <= 1.6 * max(ultima.alto, l.alto):
                grupo.append(l)
                break
        else:
            grupos.append([l])
    # La ayuda de una habilidad lleva el titulo ("BREACH SURGE / MAX RANK"), debajo una imagen
    # sin texto y debajo la descripcion: dos grupos con el mismo borde izquierdo. Se juntan
    # (captura real: el titulo tapaba el mod1 y se tomaba por un hueco vacio).
    alto_pantalla = max((l.y + l.alto for l in lineas), default=1080)
    ancho_pantalla = max((l.x + l.ancho for l in lineas), default=1920)
    grupos.sort(key=lambda g: g[0].y)
    juntos: list[list[Leido]] = []
    for grupo in grupos:
        for otro in juntos:
            x_otro = min(l.x for l in otro)
            abajo_otro = max(l.y + l.alto for l in otro)
            # El titulo de la ayuda nunca esta en la franja de arriba (ahi van las pestanas
            # "CONFIG A", que no son una ayuda y se juntaban con cualquier descripcion).
            # El titulo de una ayuda va en mayusculas ("BREACH SURGE", "MAX RANK"); un nombre
            # de tarjeta ("Energy Siphon") lleva minusculas y no se junta con nada. Los
            # numeros del panel que el OCR pega al titulo ("155%128%") no cuentan.
            if otro[0].y < 0.16 * alto_pantalla or not any(_todo_mayusculas(l.texto) for l in otro) \
                    or any(c.islower() for l in otro for c in l.texto):
                continue
            if abs(min(l.x for l in grupo) - x_otro) <= 0.03 * ancho_pantalla and 0 <= grupo[0].y - abajo_otro <= 0.32 * alto_pantalla:
                otro.extend(grupo)
                break
        else:
            juntos.append(list(grupo))
    zonas = []
    for grupo in juntos:
        frases = sum(1 for l in grupo if RE_FRASE_AYUDA.search(l.texto.strip()))
        if len(grupo) < MINIMO_LINEAS_AYUDA or frases < 2:
            continue
        x0, y0 = min(l.x for l in grupo), min(l.y for l in grupo)
        x1, y1 = max(l.x + l.ancho for l in grupo), max(l.y + l.alto for l in grupo)
        margen_zona = int(max(l.alto for l in grupo) * 0.8) if margen else 0
        zonas.append((x0 - margen_zona, y0 - margen_zona, x1 - x0 + 2 * margen_zona, y1 - y0 + 2 * margen_zona))
    return zonas


def zonas_que_tapan(lineas: list[Leido], alto: int) -> list[tuple[int, int, int, int]]:
    """Las ayudas abiertas que pueden tapar huecos. El rotulo y las pestanas de configuracion
    (con nombres puestos por el jugador en minuscula, "thermal multi", "solo") se agrupaban
    como una ayuda y "tapaban" el exilus vacio de debajo (captura real de Gauss Prime): una
    ayuda no lleva dentro el rotulo de la pantalla. (Una ayuda alta de verdad si puede
    empezar casi arriba del todo y tapar la primera fila: capturas reales.)"""
    from .builds import es_cabecera

    rotulos = [l for l in lineas if l.y < ARRIBA_DE_UNA_AYUDA * alto * 1.5 and es_cabecera(l.texto)]
    return [z for z in zonas_de_ayuda(lineas)
            if not any(z[0] <= l.x + l.ancho / 2 <= z[0] + z[2] and z[1] <= l.y + l.alto / 2 <= z[1] + z[3]
                       for l in rotulos)]


def _tapado_por_ayuda(caja, zonas: list[tuple[int, int, int, int]]) -> bool:
    x, y, w, h = caja
    for zx, zy, zw, zh in zonas:
        solape = max(0, min(x + w, zx + zw) - max(x, zx)) * max(0, min(y + h, zy + zh) - max(y, zy))
        if solape >= SOLAPE_TAPADO * w * h:
            return True
    return False


RE_NOMBRE_AGRIETADO = re.compile(r"(?i)\b[a-z]{3,6}-[a-z]{4,10}\b")


def _parece_agrietado(texto: str, build) -> bool:
    """"Falcor Para-critanem": el nombre del equipo delante, o un nombre con guion de los
    que inventa el juego para los agrietados ("Visi-critacan", "Para-critanem")."""
    from ..datos.items import normalizar

    if RE_NOMBRE_AGRIETADO.search(texto):
        return True
    equipo = getattr(build, "equipo", None)
    if equipo is None:
        return False
    nombre = normalizar(getattr(equipo, "nombre", "") or "")
    leido = normalizar(texto)
    return bool(nombre) and leido.startswith(nombre + " ") and len(leido) > len(nombre) + 3


def _admite_rotulo_de_vacio(hueco: disposicion.Hueco) -> bool:
    """Solo los huecos de arcano y de exilus ponen un rotulo cuando estan vacios ("RANURA DE
    ARCANO VACIA", "Requires Exilus Adapter"). En uno de mod, ese texto es la ayuda de un
    arcano abierta encima ("Requires Primary Arcane Adapter"), no un hueco vacio: la ayuda
    de Primary Merciless tapaba el mod3 y se daba por vacio (captura real de Phenmor)."""
    return hueco.tipo in ("arcano", "exilus")


# La tarjeta ampliada, respecto a su descripcion: tan ancha como ella (o casi un paso) y,
# por encima del nombre, el dibujo, que mide de 0,8 a 1,2 veces su ancho (medido en
# capturas reales de Gyre Prime, Harmony y Citrine Prime).
DIBUJO_SOBRE_EL_NOMBRE = 1.0
ANCHO_MINIMO_AMPLIADA = 0.85


def zonas_de_tarjetas_ampliadas(build) -> list[tuple[int, int, int, int]]:
    """Lo que tapan las tarjetas ampliadas de los mods leidos: su dibujo (por encima del
    nombre) y su descripcion. Crecen hacia arriba y hacia abajo, asi que tapan el hueco de
    encima o el de debajo de su columna aunque ahi se vea "algo" que no parece una tarjeta
    (el dibujo de la ampliada): Equilibrium ampliada en el mod3 de Gyre Prime tapaba el
    exilus, que se daba por vacio (capturas reales)."""
    zonas = zonas_de_ayuda(build.lineas, margen=False)
    paso = _paso_en_pixeles(build)
    salida = []
    for r in build.equipados:
        z = zona_de_tarjeta_ampliada(build, r, zonas)
        if z is None:
            continue
        x, y, w, h = r.caja
        cx = x + w / 2
        ancho = max(z[2], ANCHO_MINIMO_AMPLIADA * paso)
        arriba = y - DIBUJO_SOBRE_EL_NOMBRE * ancho
        salida.append((int(cx - ancho / 2), int(arriba), int(ancho), int(z[1] + z[3] - arriba)))
    return salida


def _es_hueco_vacio(texto: str) -> bool:
    from .builds import RE_HUECO_VACIO

    return bool(RE_HUECO_VACIO.search(texto))


def _parece_ayuda(texto: str, dentro: list[Leido]) -> bool:
    """La descripcion de otra tarjeta encima (varias lineas, frases con cifras o signos)."""
    if len(dentro) >= 3:
        return True
    return bool(re.search(r"[%+\d]|[.,:;]$|[.:]\s", texto.strip())) or len(texto.split()) > 5


# -- Nombres que son parte de otro mas largo -------------------------------------------
# "Intensificación" tambien es el principio de "Intensificación Umbral", "Continuidad" el de
# "Continuidad Prime", "Flow" el final de "Primed Flow"... Si la tarjeta esta tapada o cortada
# justo por donde iria la otra palabra, lo leido es un nombre de verdad pero no se sabe si es
# el mod corto o el largo, y afirmar el corto es inventar (capturas reales: "Intensificación /
# U..." bajo la ayuda de un arcano salia como "Intensificación"; un "Continuidad" cortado por
# una tarjeta ampliada, como "Continuidad"). Entonces se relee la tarjeta aparte y, si la
# palabra que falta no sale, el mod se ensena como dudoso en su hueco, no como seguro.
PASO_SIN_REJILLA = 0.23          # paso de columna (fraccion del alto) si no se midio la rejilla
MEDIO_ANCHO_DUDA = 0.47          # media tarjeta, en pasos
DESCENTRADO_DUDA = 0.15          # lo que tapa no va centrado con el nombre (su propia ayuda si)
LINEAS_DUDA = 1.5                # altos de linea por encima y por debajo del nombre
# Una ayuda abierta o una tarjeta ampliada ocupa un trozo de pantalla; un "bloque de frases"
# mas grande que esto es el panel de estadisticas o media pantalla agrupada, no algo encima.
ANCHO_MAXIMO_AYUDA, ALTO_MAXIMO_AYUDA = 0.33, 0.5
FRANJA_DE_ARRIBA = 0.12
# Por encima de esto va el rotulo de la pantalla ("UPGRADES / GAUSS PRIME [30]").
ARRIBA_DE_UNA_AYUDA = 0.10


def nombres_mas_largos(casador: Casador, categorias: dict[int, str]) -> dict[str, list[tuple[int, str, str, str]]]:
    """Clave de nombre de mod -> [(id, nombre, clave, lado)] de los mods cuyo nombre es ese
    mismo con palabras "detras" o "delante", en el mismo idioma. Una vez por casador."""
    hechos = casador.__dict__.get("_nombres_mas_largos")
    if hechos is None:
        hechos = {}
        de_mods = {clave: valor for clave, valor in casador.candidatos.items() if categorias.get(valor[0]) == "Mods"}
        idiomas = getattr(casador, "idiomas_de_clave", None) or {}
        for clave, (iid, etiqueta) in de_mods.items():
            palabras = clave.split()
            for corte in range(1, len(palabras)):
                for corto, lado in ((" ".join(palabras[:corte]), "detras"), (" ".join(palabras[corte:]), "delante")):
                    otro = de_mods.get(corto)
                    if otro is None or otro[0] == iid:
                        continue
                    # "Guardian" (ingles) no es el principio de "Guardian Armor" en una
                    # pantalla en castellano: los dos nombres tienen que ser del mismo idioma.
                    if idiomas.get(corto) and idiomas.get(clave) and not (idiomas[corto] & idiomas[clave]):
                        continue
                    if (iid, etiqueta, clave, lado) not in hechos.setdefault(corto, []):
                        hechos[corto].append((iid, etiqueta, clave, lado))
        casador._nombres_mas_largos = hechos
    return hechos


def _solapan(a, b) -> bool:
    return min(a[0] + a[2], b[0] + b[2]) > max(a[0], b[0]) and min(a[1] + a[3], b[1] + b[3]) > max(a[1], b[1])


def _paso_en_pixeles(build) -> float:
    colocacion = getattr(build, "colocacion", None)
    return (getattr(colocacion, "paso", 0.0) or PASO_SIN_REJILLA) * (build.alto or 1080)


def _alto_de_linea(build, reconocido: Reconocido) -> int:
    x, y, w, h = reconocido.caja
    dentro = [l.alto for l in build.lineas if x <= l.x + l.ancho / 2 <= x + w and y <= l.y + l.alto / 2 <= y + h]
    return min(dentro) if dentro else h


def zona_de_duda(build, reconocido: Reconocido) -> tuple[int, int, int, int]:
    """La parte de la tarjeta que se relee: media tarjeta a cada lado del centro del nombre y
    linea y media por encima y por debajo."""
    x, y, w, h = reconocido.caja
    paso = _paso_en_pixeles(build)
    linea = _alto_de_linea(build, reconocido)
    cx = x + w / 2
    x0 = int(max(0, cx - MEDIO_ANCHO_DUDA * paso))
    x1 = int(min(build.ancho or cx + paso, cx + MEDIO_ANCHO_DUDA * paso))
    y0 = int(max(0, y - LINEAS_DUDA * linea))
    y1 = int(min(build.alto or y + h + 2 * linea, y + h + LINEAS_DUDA * linea))
    return x0, y0, x1 - x0, y1 - y0


def sitios_de_la_palabra(build, reconocido: Reconocido, lado: str) -> list[tuple[float, float, float, float]]:
    """Donde iria la palabra que falta: "detras", a la derecha del nombre en su linea o en la
    linea de debajo; "delante", a su izquierda o en la linea de encima."""
    x, y, w, h = reconocido.caja
    medio = MEDIO_ANCHO_DUDA * _paso_en_pixeles(build)
    alto = LINEAS_DUDA * _alto_de_linea(build, reconocido)
    cx = x + w / 2
    if lado == "detras":
        return [(x + w, y, cx + medio - (x + w), h), (cx - medio, y + h, 2 * medio, alto)]
    return [(cx - medio, y, x - (cx - medio), h), (cx - medio, y - alto, 2 * medio, alto)]


def lados_tapados(build, reconocido: Reconocido, zonas_ayuda=None) -> set[str]:
    """Los lados del nombre ("delante", "detras") en los que hay encima algo que no es de esta
    tarjeta: una ayuda abierta, una tarjeta ampliada o un texto ajeno. La ayuda de la propia
    tarjeta (ampliada bajo el raton) va centrada con su nombre y no cuenta: ahi el nombre se
    ve entero."""
    x, y, w, h = reconocido.caja
    cx = x + w / 2
    descentrado = DESCENTRADO_DUDA * _paso_en_pixeles(build)
    if zonas_ayuda is None:
        zonas_ayuda = zonas_de_ayuda(build.lineas, margen=False)
    ancho, alto = build.ancho or 1920, build.alto or 1080
    nombres = [r.caja for parte in (build.equipados, build.coleccion, build.arcanos) for r in parte]
    encima = [z for z in zonas_ayuda
              if z[2] <= ANCHO_MAXIMO_AYUDA * ancho and z[3] <= ALTO_MAXIMO_AYUDA * alto
              and z[1] >= FRANJA_DE_ARRIBA * alto  # el rotulo y las pestanas de configuracion no tapan nada
              and abs(z[0] + z[2] / 2 - cx) > descentrado]
    for l in build.lineas:
        centro = (l.x + l.ancho / 2, l.y + l.alto / 2)
        if len(re.sub(r"[^A-Za-zÀ-ɏ]", "", l.texto)) < 3 or abs(centro[0] - cx) <= descentrado:
            continue
        if any(c[0] <= centro[0] <= c[0] + c[2] and c[1] <= centro[1] <= c[1] + c[3] for c in nombres):
            continue  # es el nombre de una tarjeta (esta u otra), no algo encima
        encima.append((l.x, l.y, l.ancho, l.alto))
    tapados = set()
    for lado in ("delante", "detras"):
        sitios = [s for s in sitios_de_la_palabra(build, reconocido, lado) if s[2] > 0 and s[3] > 0]
        if any(_solapan(cosa, sitio) for cosa in encima for sitio in sitios):
            tapados.add(lado)
    return tapados


def apartar_dudosos(imagen, build, motor, casador: Casador, categorias: dict[int, str], umbral: int,
                    limpiar=None) -> None:
    """Los mods leidos cuyo nombre es parte de otro mas largo y cuya tarjeta esta tapada por
    donde iria la palabra que falta: se relee la tarjeta y, si sale el largo, se pone el
    largo; si no, el mod sale de `build.equipados` y queda como dudoso ("X (¿X Umbral?)") en
    su hueco (`build.no_leidos`, motivo "dudoso") o, sin rejilla, en `build.sin_identificar`."""
    from ..datos.items import normalizar

    largos = nombres_mas_largos(casador, categorias)
    if not largos or not build.equipados:
        return
    idiomas_de_clave = getattr(casador, "idiomas_de_clave", None) or {}
    zonas_ayuda = None
    quitar: list[int] = []
    equipados_ids = {r.item_id for r in build.equipados}
    for indice, r in enumerate(build.equipados):
        opciones = largos.get(normalizar(r.nombre)) or largos.get(normalizar(r.texto_ocr))
        if opciones and getattr(build, "idioma", "") and idiomas_de_clave:
            # Con el idioma de la pantalla sabido, solo cuentan los nombres de ese idioma.
            # ("UPGRADES" dice ingles, pero el juego en aleman tambien lo pone.)
            validos = {build.idioma, "de"} if build.idioma == "en" else {build.idioma}
            opciones = [o for o in opciones if validos & idiomas_de_clave.get(o[2], validos)]
        if not opciones:
            continue
        if zonas_ayuda is None:
            zonas_ayuda = zonas_de_ayuda(build.lineas, margen=False)
        tapados = lados_tapados(build, r, zonas_ayuda)
        opciones = [o for o in opciones if o[3] in tapados and o[0] not in equipados_ids]
        if not opciones:
            continue
        ids_largos = {o[0] for o in opciones}
        releido = None
        if imagen is not None and motor is not None:
            releido, _texto = releer_tarjeta(imagen, zona_de_duda(build, r), motor, casador, categorias, umbral,
                                             "Mods", limpiar, solo_ids=ids_largos)
        if releido is not None:
            log.info("Mod %r: releida la tarjeta, es %r", r.nombre, releido.nombre)
            equipados_ids.discard(r.item_id)
            equipados_ids.add(releido.item_id)
            build.equipados[indice] = Reconocido(releido.texto_ocr, releido.item_id, releido.nombre,
                                                 releido.puntuacion, r.caja)
            continue
        alternativas = ", ".join(sorted({o[1] for o in opciones}, key=lambda e: (len(e), e))[:3])
        texto = f"{r.nombre} (¿{alternativas}?)"
        log.info("Mod %r: la tarjeta esta tapada y hay otro mod con mas nombre: dudoso %r", r.nombre, texto)
        quitar.append(indice)
        colocacion = getattr(build, "colocacion", None)
        clave = None
        if colocacion is not None and getattr(colocacion, "segura", False):
            clave = next((c for c, i in colocacion.mods.items() if i == indice), None)
        hueco = next((hu for hu in colocacion.huecos if hu.clave == clave), None) if clave else None
        caja = caja_de_hueco(colocacion, hueco, build.ancho, build.alto) if hueco is not None else None
        if hueco is not None and caja is not None:
            build.no_leidos.append(HuecoNoLeido(hueco.clave, hueco.tipo, caja, texto, "dudoso"))
        else:
            build.sin_identificar.append(texto)
    if not quitar:
        return
    # Fuera de los equipados, y la colocacion (que guarda indices de `equipados`) se ajusta.
    build.equipados = [r for i, r in enumerate(build.equipados) if i not in quitar]
    colocacion = getattr(build, "colocacion", None)
    if colocacion is not None:
        def nuevo(i: int) -> int:
            return i - sum(1 for q in quitar if q < i)

        colocacion.mods = {c: nuevo(i) for c, i in colocacion.mods.items() if i not in quitar}
        colocacion.sueltos_mods = [nuevo(i) for i in colocacion.sueltos_mods if i not in quitar]
