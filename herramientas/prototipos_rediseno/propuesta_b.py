"""Propuesta B - "¿Que quieres conseguir?": una portada con buscador gigante y tarjetas.

La idea: no hay pestanas a la vista. Se abre en una portada con una sola pregunta, un
buscador enorme, lo que te interesa ahora mismo (tu proxima pieza, las fisuras que te
sirven) y seis tarjetas grandes para lo demas. La ficha contesta primero con una frase y
tres pasos; el detalle queda plegado. El modo juego es una tarjeta con resultados que se
despliegan debajo, sin cambiar de vista (lo que pidio el tester).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLineEdit, QVBoxLayout, QWidget

from comun import (BASE, T_NORMAL, T_PEQUENO, T_PORTADA, T_SECCION, T_TITULO, caja, chip, columna,
                   fila, hoja, icono, imagen, lbl, minutos_txt, plural)

P = dict(BASE)


def _raiz(ancho: int, alto: int) -> QFrame:
    r = QFrame()
    r.setObjectName("raiz")
    r.setStyleSheet(hoja(P) + f"QFrame#raiz {{ background: {P['fondo']}; }}")
    r.setFixedSize(ancho, alto)
    return r


def _barra_superior(izquierda: list) -> QFrame:
    b = QFrame()
    b.setObjectName("sup")
    b.setFixedHeight(56)
    b.setStyleSheet(f"QFrame#sup {{ border-bottom: 1px solid {P['borde']}; }}")
    derecha = [_pildora("juego", "Modo juego", True), _pildora("ajustes", "Ajustes")]
    b.setLayout(fila(*izquierda, None, *derecha, margen=(24, 0, 24, 0), espacio=10))
    return b


def _pildora(ico: str, texto: str, marcada: bool = False) -> QFrame:
    f = QFrame()
    f.setObjectName("pil")
    f.setFixedHeight(34)
    f.setStyleSheet(f"QFrame#pil {{ border: 1px solid {P['acento'] if marcada else P['borde']}; border-radius: 16px; }}")
    f.setLayout(fila(icono(ico, 15, P["acento"] if marcada else P["suave"]), lbl(texto, T_NORMAL, P["texto"], 600),
                     margen=(10, 5, 14, 5), espacio=4))
    return f


def _tarjeta_accion(ico: str, titulo: str, texto: str, color: str) -> QFrame:
    t = caja(P["panel"], P["borde"], radio=14)
    t.setLayout(fila(
        _burbuja(ico, color),
        columna(lbl(titulo, 17, P["texto"], 600), lbl(texto, T_NORMAL, P["suave"]), None, espacio=2),
        margen=(16, 18, 16, 18), espacio=14,
    ))
    return t


def _burbuja(ico: str, color: str, lado: int = 46) -> QLabel:
    from PySide6.QtGui import QColor

    c = QColor(color)
    e = icono(ico, int(lado * 0.46), color)
    e.setFixedSize(lado, lado)
    e.setStyleSheet(e.styleSheet() + f"background: rgba({c.red()},{c.green()},{c.blue()},40); border-radius: {lado // 2}px;")
    return e


def inicio(d) -> QWidget:
    r = _raiz(1280, 800)
    capa = QVBoxLayout(r)
    capa.setContentsMargins(0, 0, 0, 0)
    capa.setSpacing(0)
    capa.addWidget(_barra_superior([lbl("Farmadex", 20, P["acento"], 700)]))
    cuerpo = QVBoxLayout()
    cuerpo.setContentsMargins(120, 56, 120, 26)
    cuerpo.setSpacing(16)
    capa.addLayout(cuerpo, 1)
    pregunta = lbl("¿Qué quieres conseguir?", 34, P["texto"], 700)
    pregunta.setAlignment(Qt.AlignCenter)
    cuerpo.addWidget(pregunta)
    caja_b = QLineEdit()
    caja_b.setPlaceholderText("Escribe un objeto, una pieza, una reliquia o una misión…")
    caja_b.setFixedHeight(64)
    caja_b.setStyleSheet(f"font-size: 21px; border: 2px solid {P['acento']}; border-radius: 16px; padding-left: 22px;")
    cuerpo.addWidget(caja_b)
    recientes = [lbl("Buscado hace poco:", T_NORMAL, P["tenue"])] + [chip(x, P["suave"], tam=T_NORMAL) for x in ("Citrine Prime", "Célula orokin", "Forma")]
    cuerpo.addLayout(fila(None, *recientes, None, espacio=8))
    cuerpo.addSpacing(6)

    # "Para ti, ahora": lo unico dinamico de la portada.
    cuerpo.addWidget(lbl("PARA TI, AHORA", T_PEQUENO, P["acento"], 700, espaciado=1.5))
    siguiente = min((m for m in d.metas if m.minutos and not m.boveda), key=lambda m: m.minutos)
    t1 = caja(P["panel"], P["acento"], radio=14)
    t1.setLayout(columna(
        fila(icono("metas", 16, P["acento"]), lbl("Tu pieza más cercana", T_NORMAL, P["suave"], 600), None, espacio=4),
        fila(imagen(siguiente.imagen, 46), columna(lbl(siguiente.nombre, 19, P["texto"], 700),
             lbl(f"Reliquia {siguiente.reliquia} · {siguiente.mision} en {siguiente.donde}" if siguiente.reliquia
                 else f"{siguiente.mision}: {siguiente.donde}", T_NORMAL, P["suave"]), espacio=2), espacio=10),
        fila(lbl(minutos_txt(siguiente.minutos), 24, P["acento"], 700), lbl("aprox.", T_NORMAL, P["suave"]), None, espacio=6),
        margen=(18, 14, 18, 14), espacio=8,
    ))
    fis = d.fisuras_para_ti
    t2 = caja(P["panel"], P["borde"], radio=14)
    filas_f = [fila(chip(x["era"], P["ok"]), lbl(x["nodo"], T_NORMAL, P["texto"], 600), lbl(x["mision"], T_NORMAL, P["suave"]),
                    None, lbl(x["resta"], T_NORMAL, P["suave"]), espacio=8) for x in fis[:3]]
    t2.setLayout(columna(
        fila(icono("fisura", 16, P["ok"]), lbl(plural(len(fis), "fisura te sirve ahora", "fisuras te sirven ahora"), T_NORMAL, P["suave"], 600), None, espacio=4),
        *filas_f, None, margen=(18, 14, 18, 14), espacio=8,
    ))
    cuerpo.addLayout(fila(t1, t2, espacio=16))
    cuerpo.addSpacing(6)
    cuerpo.addWidget(lbl("TODO LO DEMÁS", T_PEQUENO, P["acento"], 700, espaciado=1.5))
    rejilla = QGridLayout()
    rejilla.setSpacing(14)
    tarjetas = (
        ("metas", "Mis metas", "Lo que buscas y cuánto te falta", "#e2b455"),
        ("estrella", "Primes que me faltan", "Qué piezas prime tienes y cuáles no", "#4fc3f7"),
        ("mundo", "El mundo ahora", "Fisuras, ciclos, Baro e incursiones", "#8ccf6f"),
        ("reliquia", "Mis reliquias", "Qué abrir y qué vale cada recompensa", "#d7b27a"),
        ("build", "Builds y guías", "Montajes, vídeos y la wiki", "#ff8a50"),
        ("grupo", "Mi perfil", "Maestría y lo que ya tienes", "#c78bff"),
    )
    for i, (ico, t, texto, c) in enumerate(tarjetas):
        rejilla.addWidget(_tarjeta_accion(ico, t, texto, c), i // 3, i % 3)
    cuerpo.addLayout(rejilla)
    cuerpo.addStretch(1)
    return r


def ficha(d) -> QWidget:
    f = d.ficha
    r = _raiz(1280, 800)
    capa = QVBoxLayout(r)
    capa.setContentsMargins(0, 0, 0, 0)
    capa.setSpacing(0)
    caja_b = QLineEdit("chasis citrine prime")
    caja_b.setFixedWidth(460)
    caja_b.setStyleSheet("font-size: 15px; padding: 6px 12px;")
    capa.addWidget(_barra_superior([icono("atras", 15, P["acento"]), lbl("Inicio", T_NORMAL, P["acento"], 600), 18, caja_b]))
    cuerpo = QVBoxLayout()
    cuerpo.setContentsMargins(90, 26, 90, 22)
    cuerpo.setSpacing(16)
    capa.addLayout(cuerpo, 1)
    # 1) La respuesta en una frase. Si solo lees esto, ya sabes que hacer.
    cuerpo.addLayout(fila(imagen(f["imagen_padre"], 56), columna(
        lbl(f["nombre"].upper(), T_PEQUENO + 1, P["acento"], 700, espaciado=1.5),
        lbl(f"Juega <b>{f['mision']}</b> en <b>{f['donde']}</b>, saca la reliquia <b>{f['reliquia']}</b> "
            f"y ábrela en una fisura {f['era']}.", 25, P["texto"], 400, envolver=True),
        espacio=4), espacio=14))
    # 2) Tres cifras grandes.
    cifras = fila(espacio=14)
    for grande, peq, color in ((minutos_txt(f["min_pieza"]), f"hasta tener la pieza (escuadra de {f['escuadra']})", P["acento"]),
                               (f"{f['prob_radiante']:.0f} %", "por reliquia, refinada a Radiante", P["texto"]),
                               ("Se puede farmear", "no está en la bóveda", P["ok"]),
                               (f"{f['ducados']}", "ducados si te sobra", P["texto"])):
        t = caja(P["panel"], P["borde"], radio=14)
        t.setLayout(columna(lbl(grande, 26, color, 700), lbl(peq, T_NORMAL, P["suave"], envolver=True), margen=(18, 12, 18, 12), espacio=2))
        cifras.addWidget(t, 1)
    cuerpo.addLayout(cifras)
    # 3) Los pasos, en vertical y numerados.
    pasos = caja(P["panel"], P["borde"], radio=14)
    pcapa = QVBoxLayout(pasos)
    pcapa.setContentsMargins(20, 14, 20, 14)
    pcapa.setSpacing(10)
    for n, t, det in (
        ("1", f"Ve a {f['donde']} ({f['mision']})", f"Cada partida dura unos minutos; en unos {minutos_txt(f['min_reliquia'])} te habrá caído la reliquia {f['reliquia']}."),
        ("2", f"Refina la reliquia a Radiante y busca una fisura {f['era']}", "Así tienes más probabilidad. Mira abajo cuáles hay abiertas."),
        ("3", f"Al acabar, elige el {f['corto']} en la pantalla de recompensas", "Si sale otra cosa, repite con otra reliquia."),
    ):
        num = lbl(n, 17, P["acento_texto"], 700)
        num.setAlignment(Qt.AlignCenter)
        num.setFixedSize(32, 32)
        num.setStyleSheet(num.styleSheet() + f"background: {P['acento']}; border-radius: 16px;")
        pcapa.addLayout(fila(num, columna(lbl(t, 17, P["texto"], 600), lbl(det, T_NORMAL, P["suave"]), espacio=0), espacio=14))
    cuerpo.addWidget(pasos)
    # 4) Lo demas, plegado: se abre solo si hace falta.
    abiertas = [x for x in d.fisuras if x["era"] == f["era"]]
    for ico, titulo, extra in (
        ("fisura", f"Fisuras {f['era']} abiertas ahora", f"{len(abiertas)} · la primera acaba en {abiertas[0]['resta']}" if abiertas else "ninguna"),
        ("mapa", "Otras misiones donde cae la reliquia", f"{len(f['otras'])} más"),
        ("reliquia", "Probabilidades según el refinamiento", "Intacta, Excepcional, Impecable, Radiante"),
        ("metas", f"El resto del set de {f['padre']}", ", ".join(h["nombre"] for h in f["hermanas"] if h["id"] != f["id"])),
    ):
        pl = caja(P["panel"], P["borde"], radio=10)
        pl.setLayout(fila(icono(ico, 16, P["suave"]), lbl(titulo, 16, P["texto"], 600), lbl(extra, T_NORMAL, P["suave"]), None,
                          icono("abajo", 13, P["suave"]), margen=(16, 9, 16, 9), espacio=10))
        cuerpo.addWidget(pl)
    cuerpo.addStretch(1)
    boton = lbl("＋  Añadir a mis metas", 16, P["acento_texto"], 700)
    boton.setStyleSheet(boton.styleSheet() + f"background: {P['acento']}; border-radius: 12px; padding: 10px 22px;")
    wiki = lbl("Abrir en la wiki", 15, P["texto"], 600)
    wiki.setStyleSheet(wiki.styleSheet() + f"border: 1px solid {P['borde']}; border-radius: 12px; padding: 10px 18px;")
    cuerpo.addLayout(fila(boton, wiki, None, espacio=12))
    return r


def compacto(d) -> QWidget:
    """Tarjeta fija encima del juego; los resultados se despliegan debajo, sin saltar de vista."""
    f = d.ficha
    r = QFrame()
    r.setObjectName("tarjeta")
    r.setStyleSheet(hoja(P) + f"QFrame#tarjeta {{ background: {P['fondo']}; border: 1px solid {P['borde']}; border-radius: 16px; }}")
    r.setFixedWidth(440)
    capa = QVBoxLayout(r)
    capa.setContentsMargins(14, 12, 14, 12)
    capa.setSpacing(8)
    capa.addLayout(fila(lbl("Farmadex", 15, P["acento"], 700), None, chip("Fijada encima del juego", P["acento"]),
                        icono("pin", 15, P["acento"]), icono("ventana", 15, P["suave"]), espacio=6))
    caja_b = QLineEdit("citrine prime")
    caja_b.setStyleSheet("font-size: 17px;")
    capa.addWidget(caja_b)
    # Primer resultado desplegado.
    abierto = caja(P["panel"], P["acento"], radio=12)
    abiertas = [x for x in d.fisuras if x["era"] == f["era"]]
    abierto.setLayout(columna(
        fila(icono("abajo", 12, P["acento"]), lbl(f["nombre"], 17, P["texto"], 700), None,
             lbl(minutos_txt(f["min_pieza"]), 17, P["acento"], 700), espacio=6),
        lbl(f"1. Reliquia <b style='color:{P['texto']}'>{f['reliquia']}</b>: {f['mision']} en <b style='color:{P['texto']}'>{f['donde']}</b>", 14, P["suave"]),
        lbl(f"2. Ábrela en fisura {f['era']} (Radiante: {f['prob_radiante']:.0f} %)", 14, P["suave"]),
        fila(icono("fisura", 13, P["ok"]), lbl(f"{plural(len(abiertas), 'fisura ' + f['era'] + ' abierta', 'fisuras ' + f['era'] + ' abiertas')}: {abiertas[0]['nodo']} ({abiertas[0]['resta']})"
                                                 if abiertas else f"Ahora no hay fisuras {f['era']}", 13, P["ok"]), None, espacio=2),
        margen=(12, 10, 12, 10), espacio=4,
    ))
    capa.addWidget(abierto)
    for x in d.resultados:
        if x["nombre"].startswith(("Sistemas de Citrine Prime", "Neurópticas de Citrine Prime", "Plano de Citrine Prime")):
            cerrado = caja(P["panel"], P["borde"], radio=10)
            cerrado.setLayout(fila(icono("derecha", 12, P["suave"]), lbl(x["nombre"], 15, P["texto"], 600), None,
                                   chip("Warframe", "#4fc3f7"), margen=(12, 7, 12, 7), espacio=6))
            capa.addWidget(cerrado)
    capa.addWidget(lbl("↑ ↓ elegir · Enter desplegar · Ctrl+Alt+W ocultar", T_PEQUENO, P["tenue"]))
    r.adjustSize()
    return r


from PySide6.QtWidgets import QLabel  # noqa: E402  (tipo usado en anotaciones)
