"""Prueba de consola del comparador de recompensas, sin abrir el juego.

Se le dan de 1 a 4 nombres de pieza (como los leeria el OCR), se buscan en el
indice, se piden precios a warframe.market y se imprime el veredicto con sus
tiempos por fase. Sirve para comprobar el criterio y para medir si el veredicto
llega antes de que expire la cuenta atras de la pantalla de recompensas.

Uso:
  .venv/Scripts/python.exe herramientas/comparar_reliquias.py "Ash Prime Systems" "Braton Prime Barrel" "Forma Blueprint"
  ... --solo            sin ajuste de escuadra (usa la mediana en vez del vendedor mas barato)
  ... --sin-red         no llama a warframe.market (puntua con ducados y rareza)
  ... --medir 5         repite la puntuacion 5 veces y saca los tiempos (la primera en frio, el resto con cache)
  ... --usuario         cruza con los objetivos pendientes de la base del usuario

Hace falta el indice real construido (la app lo crea la primera vez).
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmadex.captura.comparador import PLAZO_PRECIOS_S, puntuar  # noqa: E402
from farmadex.captura.reliquias import Recompensa, resumir  # noqa: E402
from farmadex.datos import indice  # noqa: E402


def _resolver(con, nombres: list[str]) -> list[Recompensa]:
    recompensas = []
    for i, nombre in enumerate(nombres):
        resultados = indice.buscar(con, nombre, limite=1)
        if not resultados:
            print(f"  ! '{nombre}' no esta en el indice; se ignora")
            continue
        r = resultados[0]
        padre = r.get("padre_es") or r.get("padre_en")
        nombre_es = r.get("nombre_es") or r.get("nombre_en") or nombre
        recompensas.append(
            Recompensa(
                item_id=r["item_id"],
                nombre=f"{padre}: {nombre_es}" if padre else nombre_es,
                texto_ocr=nombre.upper(),
                caja=(100 + 400 * i, 300, 300, 60),
            )
        )
    return recompensas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nombres", nargs="+", help="1-4 nombres de pieza tal y como salen en pantalla")
    ap.add_argument("--solo", action="store_true", help="sin ajuste de escuadra")
    ap.add_argument("--sin-red", action="store_true", help="no consultar warframe.market")
    ap.add_argument("--medir", type=int, default=1, metavar="N", help="repetir N veces y medir")
    ap.add_argument("--usuario", action="store_true", help="cruzar con los objetivos del usuario")
    ap.add_argument("--plazo", type=float, default=PLAZO_PRECIOS_S, help="segundos maximos para precios")
    args = ap.parse_args()

    if not indice.hay_indice():
        print("No hay indice construido: abre Farmadex una vez para que lo cree.")
        return 2
    con = indice.conectar()
    usuario = None
    if args.usuario:
        from farmadex.estado import usuario_db

        usuario = usuario_db.conectar()

    precios_de = None
    market = None
    if not args.sin_red:
        from farmadex.online.market import Market

        market = Market()
        precios_de = market.precios

    totales = []
    veredicto = None
    recompensas = []
    try:
        for vuelta in range(max(1, args.medir)):
            recompensas = _resolver(con, args.nombres[:4])
            if not recompensas:
                print("Ninguna pieza reconocida.")
                return 1
            veredicto = puntuar(
                recompensas, con, precios_de, usuario, escuadra=not args.solo, plazo_s=args.plazo
            )
            totales.append(veredicto.tiempos_ms["total"])
            if args.medir > 1:
                tm = veredicto.tiempos_ms
                print(
                    f"  vuelta {vuelta + 1}: total {tm['total']:.0f} ms "
                    f"(completar {tm['completar']:.1f}, precios {tm['precios']:.0f}, puntuar {tm['puntuar']:.2f})"
                )
    finally:
        if market is not None:
            market.cerrar()
        con.close()
        if usuario is not None:
            usuario.close()

    print()
    print("Modo:", "solo" if args.solo else "escuadra de 4")
    for p in veredicto.puntuaciones:
        marca = ">>" if veredicto.elegida is p else "  "
        valor = f"{p.valor:.1f}p eq." if p.valor is not None else "?"
        print(
            f"{marca} {p.nombre:<32} valor {valor:<10} platino {p.platino if p.platino is not None else '-':<5} "
            f"ducados {p.ducados if p.ducados is not None else '-':<4} rareza {p.rareza or '?':<10} "
            f"objetivo {p.objetivo or '-':<5} confianza {p.confianza}"
            + (f"  [{'; '.join(p.notas)}]" if p.notas else "")
        )
    print()
    print("Veredicto:", veredicto.resumen())
    print("Resumen etiquetas:", resumir(recompensas))
    tm = veredicto.tiempos_ms
    print(
        f"Tiempos (ultima vuelta): total {tm['total']:.0f} ms | completar {tm['completar']:.1f} | "
        f"precios {tm['precios']:.0f} | puntuar {tm['puntuar']:.2f}"
    )
    if len(totales) > 1:
        print(
            f"Medida en {len(totales)} vueltas: primera (frio) {totales[0]:.0f} ms, "
            f"resto mediana {statistics.median(totales[1:]):.0f} ms, max {max(totales[1:]):.0f} ms"
        )
    print(
        "Presupuesto real: + 1500 ms de espera de animacion + 600-1300 ms de OCR "
        "= veredicto en pantalla unos 2.5-5 s despues de 'Got rewards' (cuenta atras ~15 s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
