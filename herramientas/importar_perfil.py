"""Importa el JSON de perfil que el jugador descargo a mano y muestra un resumen.

Uso: python herramientas/importar_perfil.py RUTA.json [--solo-leer] [--db RUTA.sqlite]
                                                      [--sin-catalogo] [--pendientes N]

  --solo-leer      valida y resume el fichero sin guardar nada
  --db             base de datos del usuario (por defecto la real, en %LocalAppData%)
  --sin-catalogo   no casa con el indice (util si aun no esta construido)
  --pendientes N   cuantos objetos pendientes ensenar por categoria (por defecto 5)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmadex import perfil as P  # noqa: E402
from farmadex.config import RUTA_USUARIO_DB  # noqa: E402
from farmadex.datos import indice as modulo_indice  # noqa: E402
from farmadex.estado import usuario_db  # noqa: E402

NOMBRES_INTRINSECOS = {
    "LPS_PILOTING": "Pilotaje", "LPS_GUNNERY": "Artilleria", "LPS_TACTICAL": "Tactica",
    "LPS_ENGINEERING": "Ingenieria", "LPS_COMMAND": "Mando",
    "LPS_DRIFT_RIDING": "Monta (Drifter)", "LPS_DRIFT_COMBAT": "Combate (Drifter)",
    "LPS_DRIFT_OPPORTUNITY": "Oportunidad (Drifter)", "LPS_DRIFT_ENDURANCE": "Resistencia (Drifter)",
}


def _horas(segundos) -> str:
    try:
        return f"{int(segundos) // 3600} h"
    except (TypeError, ValueError):
        return "?"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ruta", type=Path)
    ap.add_argument("--solo-leer", action="store_true")
    ap.add_argument("--db", type=Path, default=RUTA_USUARIO_DB)
    ap.add_argument("--sin-catalogo", action="store_true")
    ap.add_argument("--pendientes", type=int, default=5)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    inicio = time.perf_counter()
    try:
        perfil = P.cargar(args.ruta)
    except P.PerfilInvalido as e:
        print(f"ERROR: {e}")
        return 2
    print(f"Leido en {time.perf_counter() - inicio:.2f} s: {args.ruta} ({args.ruta.stat().st_size // 1024} KB)")
    print(f"  Jugador: {perfil.nombre}  MR {perfil.rango}  cuenta {perfil.account_id or '?'}")
    if perfil.creado:
        print(f"  Cuenta creada: {perfil.creado:%Y-%m-%d}")
    if perfil.clan:
        print(f"  Clan: {perfil.clan} (nivel {perfil.clan_nivel})")
    if perfil.cache_expira:
        print(f"  Cache de DE valida hasta: {perfil.cache_expira:%Y-%m-%d %H:%M} UTC")
    print(f"  Objetos con XP: {len(perfil.xp)}   nodos jugados: {len(perfil.nodos)} "
          f"(Camino de Acero: {sum(n.camino_acero for n in perfil.nodos)})")
    print(f"  Sindicatos: {len(perfil.sindicatos)}   desafios: {len(perfil.desafios)}   "
          f"estadisticas: {len(perfil.estadisticas)} contadores")
    if perfil.intrinsecos:
        partes = [f"{NOMBRES_INTRINSECOS.get(k, k)} {v}" for k, v in perfil.intrinsecos.items()
                  if k.startswith("LPS_")]
        print("  Intrinsecos: " + ", ".join(partes))
    st = perfil.estadisticas
    if st:
        print(f"  Misiones completadas: {st.get('MissionsCompleted', '?')}   "
              f"tiempo jugado: {_horas(st.get('TimePlayedSec'))}   "
              f"muertes: {st.get('Deaths', '?')}")

    if args.solo_leer:
        print("Solo lectura: no se ha guardado nada.")
        return 0

    usuario = usuario_db.conectar(args.db)
    t = time.perf_counter()
    P.guardar(usuario, perfil, args.ruta)
    print(f"Guardado en {args.db} en {time.perf_counter() - t:.2f} s")

    if args.sin_catalogo or not modulo_indice.hay_indice():
        if not args.sin_catalogo:
            print("No hay indice construido: no se casa con el catalogo.")
        return 0

    indice = modulo_indice.conectar()
    t = time.perf_counter()
    casado = P.casar_con_catalogo(usuario, indice)
    print(f"Catalogo: casan {casado.casan}/{casado.total} objetos ({casado.porcentaje:.1f} %) "
          f"y {casado.nodos_casan}/{casado.nodos_total} nodos, en {time.perf_counter() - t:.2f} s")
    if casado.sin_catalogo:
        print("  Objetos sin ficha en el catalogo:")
        for u in casado.sin_catalogo[:15]:
            print(f"    {u}")
        if len(casado.sin_catalogo) > 15:
            print(f"    ... y {len(casado.sin_catalogo) - 15} mas")
    if casado.nodos_sin_catalogo:
        prefijos = Counter(''.join(c for c in t if not c.isdigit()) for t in casado.nodos_sin_catalogo)
        print("  Nodos sin ficha en el catalogo, por tipo: "
              + ", ".join(f"{p} {n}" for p, n in prefijos.most_common(8)))

    t = time.perf_counter()
    print("Maestria por categoria (dominados / a medias / sin tocar / total):")
    for categoria, c in P.resumen_maestria(usuario, indice).items():
        print(f"  {categoria:12} {c[P.DOMINADO]:4} / {c[P.A_MEDIAS]:4} / {c[P.SIN_TOCAR]:4} / {c['total']:4}")
    pendientes = P.pendientes_por_categoria(usuario, indice)
    if args.pendientes > 0:
        print(f"Pendientes (los {args.pendientes} mas avanzados por categoria):")
        for categoria, filas in pendientes.items():
            print(f"  {categoria} ({len(filas)} pendientes)")
            for f in filas[: args.pendientes]:
                print(f"    {f['nombre_es']:32} rango {f['rango']:2}  {f['xp']:>9}/{f['umbral']}")
    nodos = P.nodos_pendientes(usuario, indice)
    acero = P.nodos_pendientes(usuario, indice, camino_acero=True)
    print(f"Nodos del mapa pendientes: {len(nodos)} en normal, {len(acero)} en Camino de Acero")
    for n in nodos[:10]:
        print(f"    {n['planeta']} / {n['nombre']}")
    print(f"Consultas en {time.perf_counter() - t:.2f} s; total {time.perf_counter() - inicio:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
