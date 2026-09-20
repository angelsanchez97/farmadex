"""Renderiza las dos propuestas de la pestana Mundo (lista y tablero) con un mundo inventado.

Uso: QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe herramientas/capturas/capturar_mundo.py [es en ...]

El estado del mundo es sintetico pero realista (25 fisuras, Baro, incursion,
invasiones...) para juzgar la jerarquia: en castellano Baro esta en un relevo y en
ingles todavia no ha llegado. Los objetivos se anaden a la BD de la caja de arena,
no a la del usuario. Salidas: mundo_<diseno>_<idioma>.png.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "herramientas"))
from render_ui import preparar_sandbox  # noqa: E402

os.environ["FARMADEX_DATOS"] = str(preparar_sandbox())
sys.path.insert(0, str(RAIZ / "src"))

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from farmadex import tareas  # noqa: E402
from farmadex.datos import indice  # noqa: E402
from farmadex.estado import objetivos as estado_objetivos  # noqa: E402
from farmadex.online import worldstate as ws  # noqa: E402
from farmadex.ui import pestana_mundo  # noqa: E402
from farmadex.ui.overlay import VentanaOverlay  # noqa: E402

DESTINO = Path(__file__).resolve().parent


def _en(minutos: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutos)


def mundo_inventado(baro_activo: bool) -> ws.Mundo:
    F = ws.Fisura
    fisuras = [
        F("Lith", "Casini, Ceres", "Captura", "Grineer", _en(48)),
        F("Lith", "Hydron, Sedna", "Defensa", "Grineer", _en(110)),
        F("Lith", "Pavlov, Lua", "Espionaje", "Corpus", _en(7)),
        F("Meso", "Ose, Europa", "Exterminio", "Corpus", _en(33)),
        F("Meso", "Kappa, Sedna", "Espionaje", "Grineer", _en(95)),
        F("Meso", "Mot, Vacio", "Supervivencia", "Corrupto", _en(140)),
        F("Meso", "Tikal, Tierra", "Excavacion", "Grineer", _en(3)),
        F("Neo", "Ukko, Vacio", "Captura", "Corrupto", _en(62)),
        F("Neo", "Oceanum, Pluton", "Espionaje", "Corpus", _en(21)),
        F("Neo", "Cerberus, Pluton", "Intercepcion", "Corpus", _en(80)),
        F("Axi", "Marduk, Vacio", "Sabotaje", "Corrupto", _en(58)),
        F("Axi", "Ani, Vacio", "Supervivencia", "Corrupto", _en(125)),
        F("Axi", "Apollo, Lua", "Disrupcion", "Corpus", _en(9)),
        F("Requiem", "Taveuni, Fortaleza Kuva", "Supervivencia", "Grineer", _en(70)),
        F("Omnia", "Tuvul Commons, Zariman", "Exterminio", "Grineer", _en(40)),
        F("Lith", "Adaro, Sedna", "Exterminio", "Grineer", _en(66), acero=True),
        F("Meso", "Kadesh, Marte", "Defensa", "Grineer", _en(30), acero=True),
        F("Neo", "Selkie, Sedna", "Supervivencia", "Grineer", _en(90), acero=True),
        F("Axi", "Ur, Urano", "Sabotaje", "Grineer", _en(52), acero=True),
        F("Axi", "Sechura, Pluton", "Defensa", "Corpus", _en(118), acero=True),
        F("Lith", "Bendar Cluster, Tierra", "Escaramuza", "Grineer", _en(75), tormenta=True),
        F("Meso", "Calabash, Venus", "Volatil", "Corpus", _en(66), tormenta=True),
        F("Neo", "Nsu Grid, Velo de Pluton", "Exterminio", "Grineer", _en(44), tormenta=True),
        # Dos ya terminadas: no deben salir.
        F("Meso", "Encelado, Saturno", "Sabotaje", "Grineer", _en(-5)),
        F("Axi", "Oceanum, Pluton", "Espionaje", "Corpus", _en(-40)),
    ]
    ciclos = [
        ws.Ciclo("Tierra", "dia", _en(85)), ws.Ciclo("Cetus", "dia", _en(41)),
        ws.Ciclo("Valle del Orbe", "frio", _en(6)), ws.Ciclo("Llanuras de Cambion", "Fass", _en(41)),
        ws.Ciclo("Zariman", "Corpus", _en(120)), ws.Ciclo("Duviri", "tristeza", _en(58)),
    ]
    invasiones = [
        ws.Invasion("Marid, Sedna", "Corpus Siege", "Corpus", "Grineer", "1x Snipetron Vandal Stock / 1x Latron Wraith Blueprint", 45),
        ws.Invasion("Cambria, Tierra", "Grineer Offensive", "Grineer", "Corpus", "3x Fieldron / 3x Detonite Injector", 72),
        ws.Invasion("Ishtar, Venus", "Infestation Outbreak", "Infestados", "Corpus", "3x Mutagen Mass", 20),
    ]
    sortie = [
        ws.Recompensa("Hyf, Deimos - Defensa movil", _en(263), "Weapon Restriction: Bow Only"),
        ws.Recompensa("M Prime, Mercurio - Defensa", None, "Eximus Stronghold"),
        ws.Recompensa("Xini, Eris - Espionaje", None, "Enemy Elemental Enhancement: Corrosive"),
    ]
    arcontes = [
        ws.Recompensa("Io, Jupiter - Defensa movil", _en(743)),
        ws.Recompensa("Carme, Jupiter - Supervivencia", None),
        ws.Recompensa("Temisto, Jupiter - Asesinato", None),
    ]
    nightwave = [
        ws.Recompensa("[diario] Everything Old is New Again", _en(1000), "1000 de reputacion"),
        ws.Recompensa("[semanal] Mine 8 rare gems in the Plains", _en(4000), "4500 de reputacion"),
        ws.Recompensa("[semanal] Complete 3 Sorties", _en(4000), "4500 de reputacion"),
    ]
    acero = [ws.Recompensa("Umbra Forma Blueprint", _en(743), "150 de esencia")]
    O = ws.ObjetoBaro
    inventario = [
        O("Primed Smite Grineer", "/Lotus/Upgrades/x", 350, 140000, 1, "Castigar Grineer Prime", "Mods", "primed_smite_grineer"),
        O("Prisma Gorgon", "/Lotus/Weapons/x", 600, 125000, 2, "Gorgon Prisma", "Primary", "prisma_gorgon"),
        O("Sands of Inaros Blueprint", "/Lotus/Quests/x", 100, 25000, 3, "Plano de Arenas de Inaros", "Quests", None, objetivo=True),
        O("Dagath Immortal Skin", "/Lotus/Skins/x", 550, 100000, None, "", "Skins"),
        O("Primed Fury", "/Lotus/Upgrades/y", 350, 110000, 4, "Furia Prime", "Mods", "primed_fury"),
        O("Ki'Teer Sekhara", "/Lotus/Misc/x", 250, 150000, None, "", "Misc"),
    ]
    baro = ws.Baro(
        "Baro Ki'Teer", "Larunda, Mercurio", baro_activo,
        llegada=_en(-1400) if baro_activo else _en(4600), expira=_en(1480) if baro_activo else None,
        inventario=inventario if baro_activo else [],
    )
    return ws.Mundo(
        momento=datetime.now(timezone.utc), fisuras=fisuras, ciclos=ciclos, invasiones=invasiones,
        alertas=[ws.Recompensa("Gift of the Lotus: 3x Forma", _en(700))],
        arbitracion=ws.Recompensa("Defensa - Helene, Saturno", _en(38), "Grineer · nivel 60-80"),
        sortie=sortie, arcontes=arcontes, nightwave=nightwave, acero=acero,
        baro=[ws.Recompensa(o.nombre_mostrar, None, f"{o.ducados} ducados") for o in baro.inventario],
        baro_cabecera=baro.cabecera(), baro_detalle=baro,
    )


def objetivos_de_muestra(usuario, con) -> None:
    """Forma (sale en muchas reliquias) y la pieza rara de una reliquia Neo disponible."""
    for o in estado_objetivos.listar(usuario):
        estado_objetivos.borrar(usuario, o.id)
    fila = con.execute("SELECT unique_name, COALESCE(nombre_es, nombre_en) FROM items WHERE nombre_en = 'Forma' AND padre_id IS NULL LIMIT 1").fetchone()
    if fila:
        estado_objetivos.anadir(usuario, fila[0], fila[1], 3)
    fila = con.execute(
        """
        SELECT i.unique_name, COALESCE(i.nombre_es, i.nombre_en) || ' de ' || COALESCE(p.nombre_es, p.nombre_en)
          FROM fuentes f JOIN items r ON r.id = f.origen_id JOIN items i ON i.id = f.item_id
          LEFT JOIN items p ON p.id = i.padre_id
         WHERE f.tipo = 'reliquia' AND r.vaulted = 0 AND r.nombre_en LIKE 'Neo %' AND f.refinamiento = 'Radiant'
           AND i.padre_id IS NOT NULL
         ORDER BY f.probabilidad ASC LIMIT 1
        """
    ).fetchone()
    if fila:
        estado_objetivos.anadir(usuario, fila[0], fila[1], 1)


def main(codigos: list[str]) -> None:
    tareas.TareaDatos.start = lambda self: None
    app = QApplication.instance() or QApplication([])
    ventana = VentanaOverlay()
    ventana.aplicar_modo("completo")
    ventana.resize(1100, 700)
    ventana.show()
    con = indice.conectar()
    objetivos_de_muestra(ventana.objetivos.usuario, con)
    ventana.objetivos.conectar_indice(indice.conectar())

    for diseno in pestana_mundo.DISENOS:
        # Se sustituye la pestana Mundo por una con el diseno pedido.
        indice_pestana = ventana.pestanas.indexOf(ventana.mundo)
        ventana.pestanas.removeTab(indice_pestana)
        ventana.mundo.deleteLater()
        ventana.mundo = pestana_mundo.PestanaMundo(diseno=diseno)
        ventana.pestanas.insertTab(indice_pestana, ventana.mundo, "Mundo")
        ventana.mundo.conectar_objetivos(indice.conectar(), ventana.objetivos.usuario)
        for codigo in codigos:
            ventana.cambiar_idioma(codigo)
            ventana.mundo.actualizar(mundo_inventado(baro_activo=(codigo == "es")))
            ventana.pestanas.setCurrentWidget(ventana.mundo)
            # Los widgets viejos se borran con deleteLater: sin vaciar esa cola se
            # pintarian encima de los nuevos (en la app real lo hace el bucle de eventos).
            app.processEvents()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
            ruta = DESTINO / f"mundo_{diseno}_{codigo}.png"
            ventana.grab().save(str(ruta))
            print(ruta)
    app.quit()


if __name__ == "__main__":
    main(sys.argv[1:] or ["es", "en"])
