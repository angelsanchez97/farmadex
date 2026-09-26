"""Propuesta A - "Cinco puertas": barra lateral con 5 grupos grandes y tipografia con jerarquia.

La idea: el programa sigue siendo el mismo, pero en vez de 10 pestanas iguales hay cinco
puertas grandes con icono y nombre (Buscar, Mis metas, Mundo, Herramientas, Ajustes) y cada
pagina tiene un titulo grande, un bloque protagonista y el detalle debajo. El modo juego es
una tira de busqueda tipo "lanzador", no la ventana encogida.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLineEdit, QVBoxLayout, QWidget

from comun import (BASE, T_NORMAL, T_PEQUENO, T_PORTADA, T_SECCION, T_TITULO, caja, chip, columna,
                   fila, hoja, icono, imagen, lbl, minutos_txt, plural)
from farmadex.ui import colores_tipo

P = dict(BASE)
NAV = (("buscar", "Buscar", ""), ("metas", "Mis metas", "4"), ("mundo", "Mundo", ""),
       ("herramientas", "Herramientas", ""), ("ajustes", "Ajustes", ""))


def _raiz(ancho: int, alto: int) -> QFrame:
    r = QFrame()
    r.setObjectName("raiz")
    r.setStyleSheet(hoja(P) + f"QFrame#raiz {{ background: {P['fondo']}; }}")
    r.setFixedSize(ancho, alto)
    return r


def _boton(texto: str, principal: bool = False, ico: str | None = None) -> QFrame:
    b = QFrame()
    b.setObjectName("boton")
    fondo = P["acento"] if principal else P["panel2"]
    tinta = P["acento_texto"] if principal else P["texto"]
    b.setStyleSheet(f"QFrame#boton {{ background: {fondo}; border: 1px solid {fondo if principal else P['borde']};"
                    f" border-radius: 9px; }}")
    capa = fila(*( [icono(ico, 15, tinta)] if ico else []), lbl(texto, T_NORMAL, tinta, 600), margen=(12, 8, 14, 8), espacio=4)
    b.setLayout(capa)
    return b


def _barra_lateral(activa: str) -> QFrame:
    barra = QFrame()
    barra.setObjectName("barra")
    barra.setFixedWidth(232)
    barra.setStyleSheet(f"QFrame#barra {{ background: {P['panel']}; border-right: 1px solid {P['borde']}; }}")
    capa = QVBoxLayout(barra)
    capa.setContentsMargins(14, 20, 14, 18)
    capa.setSpacing(6)
    capa.addLayout(fila(lbl("Farmadex", 22, P["acento"], 700), None, margen=(10, 0, 0, 0)))
    capa.addSpacing(22)
    for clave, texto, insignia in NAV:
        activo = clave == activa
        b = QFrame()
        b.setObjectName("nav")
        b.setFixedHeight(54)
        b.setStyleSheet(
            f"QFrame#nav {{ background: {P['panel2'] if activo else 'transparent'}; border-radius: 10px;"
            f" border-left: 4px solid {P['acento'] if activo else 'transparent'}; }}"
        )
        color = P["acento"] if activo else P["texto"]
        partes = [icono(clave, 21, color), lbl(texto, 17, color, 600 if activo else 500), None]
        if insignia:
            partes.append(chip(insignia, P["acento"], relleno=True))
        b.setLayout(fila(*partes, margen=(10, 0, 12, 0), espacio=10))
        capa.addWidget(b)
    capa.addStretch(1)
    # El modo juego, grande y con su tecla: es lo que se usa en partida.
    juego = QFrame()
    juego.setObjectName("juego")
    juego.setStyleSheet(f"QFrame#juego {{ background: {P['fondo']}; border: 1px solid {P['acento']}; border-radius: 12px; }}")
    juego.setLayout(columna(
        fila(icono("juego", 22, P["acento"]), lbl("Modo juego", 16, P["texto"], 600), None, espacio=8),
        lbl("Pulsa Ctrl+Alt+W dentro del juego", T_PEQUENO, P["suave"], envolver=True),
        margen=(12, 12, 12, 12), espacio=4,
    ))
    capa.addWidget(juego)
    capa.addSpacing(8)
    capa.addLayout(fila(icono("info", 14, P["suave"]), lbl("Guía rápida", T_PEQUENO, P["suave"]), None, margen=(8, 0, 0, 0), espacio=2))
    return barra


def _titulo_pagina(titulo: str, subtitulo: str) -> QVBoxLayout:
    return columna(lbl(titulo, T_PORTADA, P["texto"], 700), lbl(subtitulo, T_NORMAL, P["suave"]), espacio=2)


def _estado(vaulted: bool) -> QWidget:
    return chip("En bóveda" if vaulted else "Se puede farmear", P["boveda"] if vaulted else P["ok"])


def inicio(d) -> QWidget:
    r = _raiz(1280, 800)
    capa = fila(margen=(0, 0, 0, 0), espacio=0)
    r.setLayout(capa)
    capa.addWidget(_barra_lateral("buscar"))
    cont = QVBoxLayout()
    cont.setContentsMargins(36, 30, 36, 24)
    cont.setSpacing(14)
    capa.addLayout(cont, 1)
    cont.addLayout(_titulo_pagina("Buscar", "Escribe cualquier cosa del juego: un objeto, una pieza, una reliquia o una misión"))
    caja_busqueda = QLineEdit(d.busqueda_texto)
    caja_busqueda.setFixedHeight(56)
    caja_busqueda.setStyleSheet(f"font-size: 20px; border-color: {P['acento']}; padding-left: 18px;")
    cont.addWidget(caja_busqueda)
    tipos = sorted({x["tipo"] for x in d.resultados}, key=list(colores_tipo.TIPOS).index)
    ley = [lbl(f"{len(d.resultados)} resultados", T_NORMAL, P["suave"], 600), 12]
    for t in tipos:
        ley.append(chip(colores_tipo.nombre(t), colores_tipo.color(t, P["fondo"])))
    cont.addLayout(fila(*ley, None, espacio=6))
    lista = caja(P["panel"], P["borde"])
    lcapa = QVBoxLayout(lista)
    lcapa.setContentsMargins(6, 6, 6, 6)
    lcapa.setSpacing(2)
    for i, x in enumerate(d.resultados[:7]):
        filaw = QFrame()
        filaw.setObjectName("res")
        sel = i == 3
        filaw.setStyleSheet(f"QFrame#res {{ background: {P['panel2'] if sel else 'transparent'}; border-radius: 8px; }}")
        col = colores_tipo.color(x["tipo"], P["panel"])
        textos = columna(lbl(x["nombre"], 17, P["texto"], 600),
                         fila(chip(x["tipo_txt"], col), *( [chip("Pieza", P["suave"])] if x["pieza"] else []),
                              _estado(x["vaulted"]), None, espacio=6), espacio=4)
        filaw.setLayout(fila(imagen(x["imagen"], 44), 6, textos, None,
                             lbl("Ver cómo conseguirlo", T_PEQUENO, P["acento"] if sel else P["tenue"], 600),
                             icono("derecha", 14, P["acento"] if sel else P["tenue"]), margen=(10, 6, 12, 6), espacio=8))
        filaw.setFixedHeight(66)
        lcapa.addWidget(filaw)
    lcapa.addStretch(1)
    cont.addWidget(lista, 1)
    cont.addLayout(fila(lbl("Consejo: con ↑ ↓ y Enter no necesitas el ratón", T_PEQUENO, P["tenue"]), None))
    return r


def ficha(d) -> QWidget:
    f = d.ficha
    r = _raiz(1280, 800)
    capa = fila(margen=(0, 0, 0, 0), espacio=0)
    r.setLayout(capa)
    capa.addWidget(_barra_lateral("buscar"))
    cont = QVBoxLayout()
    cont.setContentsMargins(36, 22, 36, 24)
    cont.setSpacing(14)
    capa.addLayout(cont, 1)
    cont.addLayout(fila(icono("atras", 13, P["acento"]), lbl(f"Volver a «{d.busqueda_texto}»", T_NORMAL, P["acento"], 600), None, espacio=2))
    # Cabecera: nombre enorme, etiquetas y la accion principal.
    cab = columna(
        lbl(f["nombre"], 28, P["texto"], 700),
        fila(chip("Warframe", colores_tipo.color("warframe", P["fondo"])), chip(f"Pieza de {f['padre']}", P["suave"]),
             _estado(f["vaulted"]), chip(f"{f['ducados']} ducados", P["acento"]), None, espacio=6),
        espacio=6,
    )
    acciones = columna(fila(_boton("Wiki", ico="web"), _boton("Añadir a mis metas", True, "mas"), espacio=10), None)
    cont.addLayout(fila(imagen(f["imagen_padre"], 76), 8, cab, None, acciones, espacio=10))
    # Protagonista: los tres pasos. Es lo unico que hace falta leer.
    heroe = caja(P["panel"], P["acento"], izq=None)
    hcapa = QVBoxLayout(heroe)
    hcapa.setContentsMargins(22, 16, 22, 18)
    hcapa.setSpacing(12)
    hcapa.addLayout(fila(lbl("CÓMO CONSEGUIRLO", T_PEQUENO, P["acento"], 700, espaciado=1.5), None,
                         lbl(f"En total, unas <b style='color:{P['texto']}'>{minutos_txt(f['min_pieza'])}</b> con escuadra de {f['escuadra']}",
                             T_NORMAL, P["suave"])))
    pasos = (
        ("1", f"Consigue la reliquia {f['reliquia']}", f"Juega {f['mision']} en {f['donde']}. Tardas unos {minutos_txt(f['min_reliquia'])}."),
        ("2", f"Ábrela en una fisura {f['era']}", f"Refínala a Radiante antes: {f['prob_radiante']:.0f} % de que salga la pieza."),
        ("3", "Recoge la pieza", "Elige el Chasis en la pantalla de recompensas al acabar la fisura."),
    )
    prow = fila(espacio=14)
    for n, t, det in pasos:
        paso = QFrame()
        paso.setLayout(fila(
            _numero(n), columna(lbl(t, 18, P["texto"], 600, envolver=True), lbl(det, T_NORMAL, P["suave"], envolver=True), None, espacio=4),
            espacio=12,
        ))
        prow.addWidget(paso, 1)
    hcapa.addLayout(prow)
    cont.addWidget(heroe)
    # Detalle: dos columnas mas pequenas.
    abajo = fila(espacio=16)
    izq = caja(P["panel"], P["borde"])
    izq.setLayout(columna(
        lbl("Otras misiones donde cae la reliquia", T_SECCION, P["texto"], 600), 4,
        *[fila(lbl(m["donde"], T_NORMAL, P["texto"], 600), lbl(m["mision"], T_NORMAL, P["suave"]), None,
               lbl(minutos_txt(m["min"]), T_NORMAL, P["suave"]), espacio=8) for m in f["otras"]],
        None, margen=(18, 14, 18, 14), espacio=8,
    ))
    der = caja(P["panel"], P["borde"])
    rel = f["reliquias"][0]
    nombres = {"Intact": "Intacta", "Exceptional": "Excepcional", "Flawless": "Impecable", "Radiant": "Radiante"}
    barras = []
    for k in ("Intact", "Exceptional", "Flawless", "Radiant"):
        barras.append(fila(lbl(nombres[k], T_NORMAL, P["suave"]), None, lbl(f"{rel['probs'][k]:.0f} %", T_NORMAL, P["texto"], 600), espacio=6))
    der.setLayout(columna(
        fila(lbl(f"Reliquia {rel['nombre']}", T_SECCION, P["texto"], 600), None, _estado(rel["vaulted"])),
        lbl("Probabilidad de que salga, según cómo la refines", T_PEQUENO, P["tenue"]),
        *barras, None, margen=(18, 14, 18, 14), espacio=6,
    ))
    abajo.addWidget(izq, 3)
    abajo.addWidget(der, 2)
    cont.addLayout(abajo)
    # El set completo, para saber que mas falta.
    set_ = caja(P["panel"], P["borde"])
    piezas = [lbl(f"El set de {f['padre']}", T_SECCION, P["texto"], 600), 14]
    for h in f["hermanas"]:
        actual = h["id"] == f["id"]
        piezas.append(chip(h["nombre"], P["acento"] if actual else P["suave"], relleno=actual, tam=T_NORMAL))
    set_.setLayout(fila(*piezas, None, margen=(18, 12, 18, 12), espacio=8))
    cont.addWidget(set_)
    # Lo que pasa ahora en el juego y afecta a esta pieza (del worldState real).
    abiertas = [x for x in d.fisuras if x["era"] == f["era"]]
    ahora = caja(P["panel"], P["borde"], izq=P["ok"] if abiertas else P["tenue"])
    filas_f = [fila(lbl(x["nodo"], T_NORMAL, P["texto"], 600), lbl(f"{x['mision']} · {x['enemigo']}", T_NORMAL, P["suave"]), None,
                    icono("reloj", 13, P["suave"]), lbl(x["resta"], T_NORMAL, P["suave"]), espacio=8) for x in abiertas[:3]]
    ahora.setLayout(columna(
        lbl(f"Ahora mismo hay {plural(len(abiertas), 'fisura ' + f['era'] + ' abierta', 'fisuras ' + f['era'] + ' abiertas')}" if abiertas else f"Ahora no hay fisuras {f['era']}",
            T_SECCION, P["texto"], 600),
        *filas_f, margen=(18, 12, 18, 12), espacio=6,
    ))
    cont.addWidget(ahora)
    cont.addStretch(1)
    return r


def _numero(n: str) -> QWidget:
    e = lbl(n, 20, P["acento_texto"], 700)
    e.setAlignment(Qt.AlignCenter)
    e.setFixedSize(38, 38)
    e.setStyleSheet(f"background: {P['acento']}; color: {P['acento_texto']}; border-radius: 19px;")
    col = QWidget()
    col.setLayout(columna(e, None))
    return col


def compacto(d) -> QWidget:
    """Tira de busqueda tipo lanzador: una linea para escribir y una linea de respuesta."""
    f = d.ficha
    r = QFrame()
    r.setObjectName("tira")
    r.setStyleSheet(hoja(P) + f"QFrame#tira {{ background: {P['fondo']}; border: 1px solid {P['acento']}; border-radius: 14px; }}")
    r.setFixedSize(760, 170)
    capa = QVBoxLayout(r)
    capa.setContentsMargins(16, 12, 16, 12)
    capa.setSpacing(8)
    caja_b = QLineEdit("chasis citrine")
    caja_b.setStyleSheet(f"font-size: 18px; background: {P['panel']}; border-color: {P['borde']};")
    capa.addLayout(fila(icono("buscar", 18, P["acento"]), caja_b, icono("pin", 16, P["acento"]),
                        icono("ventana", 16, P["suave"]), icono("cerrar", 14, P["suave"]), espacio=8))
    resp = caja(P["panel"], P["borde"], izq=P["ok"], radio=10)
    resp.setLayout(columna(
        fila(lbl(f["nombre"], 19, P["texto"], 700), chip("Se puede farmear", P["ok"]), None,
             lbl(minutos_txt(f["min_pieza"]), 19, P["acento"], 700), espacio=10),
        lbl(f"Reliquia <b style='color:{P['texto']}'>{f['reliquia']}</b> · {f['mision']} en "
            f"<b style='color:{P['texto']}'>{f['donde']}</b> · ábrela en fisura {f['era']}", 15, P["suave"]),
        margen=(14, 8, 14, 8), espacio=2,
    ))
    capa.addWidget(resp)
    capa.addLayout(fila(lbl("Enter: ficha completa   ·   ↑ ↓: otro resultado (1 de 12)   ·   Ctrl+Alt+W: ocultar", T_PEQUENO, P["tenue"]), None))
    return r
