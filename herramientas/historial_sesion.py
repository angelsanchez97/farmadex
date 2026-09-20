"""Herramienta de consola del historial de sesion (sin interfaz).

Subordenes:
  resumen   [--dia 2026-09-20]                 resumen del dia (hoy por defecto), tambien --json
  exportar  [--salida ruta] [--plantilla f]    escribe el fichero de texto para OBS
  huecos                                       lista los huecos que admite la plantilla
  simular   [--n 6]                            mete lecturas y eventos de prueba en una base APARTE
  seguir    [--eelog ruta] [--salida ruta]     vigila EE.log y reexporta el fichero con cada evento

Todas admiten --db ruta para trabajar sobre otra base (por defecto la del usuario).
`simular` se niega a escribir en la base real: exige --db.

Uso:
  .venv/Scripts/python.exe herramientas/historial_sesion.py resumen
  .venv/Scripts/python.exe herramientas/historial_sesion.py simular --db %TEMP%/prueba.sqlite
  .venv/Scripts/python.exe herramientas/historial_sesion.py exportar --db %TEMP%/prueba.sqlite --salida %TEMP%/obs.txt
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmadex.captura.reliquias import Recompensa  # noqa: E402
from farmadex.config import RUTA_USUARIO_DB  # noqa: E402
from farmadex.estado import historial, usuario_db  # noqa: E402

PIEZAS_DE_PRUEBA = [
    ("/Lotus/P/AshSystems", "Ash Prime Systems", 45.0, 100, "rara"),
    ("/Lotus/P/BratonBarrel", "Braton Prime Barrel", 1.5, 15, "comun"),
    ("/Lotus/P/NikanaLink", "Nikana Prime Link", 8.0, 45, "poco comun"),
    ("/Lotus/P/Forma", "Forma Blueprint", 0.0, None, "comun"),
    ("/Lotus/P/Desconocida", "Pieza Sin Precio", None, None, None),
]


def _conectar(ruta: str | None):
    return usuario_db.conectar(Path(ruta)) if ruta else usuario_db.conectar()


def _leer_plantilla(ruta: str | None) -> str:
    if not ruta:
        return historial.PLANTILLA_OBS
    return Path(ruta).read_text(encoding="utf-8").rstrip("\n")


def cmd_resumen(args) -> int:
    con = _conectar(args.db)
    try:
        dia = date.fromisoformat(args.dia) if args.dia else date.today()
        resumen = historial.resumen_dia(con, dia)
    finally:
        con.close()
    if args.json:
        print(json.dumps(resumen.como_dict(), ensure_ascii=False, indent=2))
    else:
        print(historial.texto_resumen(resumen))
    return 0


def cmd_exportar(args) -> int:
    con = _conectar(args.db)
    try:
        resumen = historial.resumen_dia(con)
    finally:
        con.close()
    ruta = historial.exportar_obs(
        resumen, args.salida or historial.RUTA_OBS_POR_DEFECTO, _leer_plantilla(args.plantilla)
    )
    print(f"Escrito {ruta}:")
    print(ruta.read_text(encoding="utf-8"))
    return 0


def cmd_huecos(args) -> int:
    print("Huecos admitidos en la plantilla (se escriben entre llaves):")
    for hueco in historial.HUECOS:
        print(f"  {{{hueco}}}")
    print("\nPlantilla por defecto:\n  " + historial.PLANTILLA_OBS)
    return 0


def cmd_simular(args) -> int:
    if not args.db or Path(args.db).resolve() == Path(RUTA_USUARIO_DB).resolve():
        print("simular exige --db con una base de prueba; no se escribe en la del usuario.")
        return 2
    rng = random.Random(args.semilla)
    con = _conectar(args.db)
    try:
        ahora = datetime.now().replace(second=0, microsecond=0)
        for i in range(args.n):
            cuando = ahora - timedelta(minutes=(args.n - i) * 7)
            historial.registrar_evento(con, "mision_completada", cuando.isoformat(timespec="seconds"))
            historial.registrar_evento(con, "reliquia_abierta", cuando.isoformat(timespec="seconds"))
            elegidas = rng.sample(PIEZAS_DE_PRUEBA, 4)
            recompensas = [
                Recompensa(item_id=k + 1, nombre=nombre, texto_ocr=nombre.upper(), caja=(0, 0, 1, 1),
                           unique_name=unico, valor=valor, ducados=ducados, rareza=rareza)
                for k, (unico, nombre, valor, ducados, rareza) in enumerate(elegidas)
            ]
            con_valor = [r for r in recompensas if r.valor is not None]
            if con_valor:
                max(con_valor, key=lambda r: r.valor).mejor = True
            historial.registrar_lectura(
                con, recompensas, leido_en=(cuando + timedelta(minutes=1)).isoformat(timespec="seconds")
            )
        print(f"Simuladas {args.n} reliquias en {args.db}")
        print(historial.texto_resumen(historial.resumen_dia(con)))
    finally:
        con.close()
    return 0


def cmd_seguir(args) -> int:
    """Sin Qt: lee EE.log en bucle con `registro.eelog.leer_eventos` y reexporta con cada evento."""
    from farmadex.config import cargar
    from farmadex.registro.eelog import leer_eventos

    ruta_log = Path(args.eelog or cargar()["ruta_eelog"])
    con = _conectar(args.db)
    sesion = historial.Sesion(con, args.salida or historial.RUTA_OBS_POR_DEFECTO, _leer_plantilla(args.plantilla))
    print(f"Vigilando {ruta_log}; exportando a {sesion.ruta_obs}. Ctrl+C para parar.")
    posicion = ruta_log.stat().st_size if ruta_log.exists() else 0
    sesion.exportar()
    try:
        while True:
            if ruta_log.exists():
                tamano = ruta_log.stat().st_size
                if tamano < posicion:
                    posicion = 0
                if tamano > posicion:
                    eventos, posicion = leer_eventos(ruta_log, posicion)
                    for evento in eventos:
                        print(datetime.now().strftime("%H:%M:%S"), evento)
                        sesion.evento(evento)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        con.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("--db", help="ruta de la base de datos (por defecto la del usuario)")
    sub = ap.add_subparsers(dest="orden", required=True)

    p = sub.add_parser("resumen", parents=[comun])
    p.add_argument("--dia", help="AAAA-MM-DD (hoy por defecto)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(f=cmd_resumen)

    p = sub.add_parser("exportar", parents=[comun])
    p.add_argument("--salida", help="fichero de texto para OBS")
    p.add_argument("--plantilla", help="fichero con la plantilla (una linea con huecos)")
    p.set_defaults(f=cmd_exportar)

    p = sub.add_parser("huecos", parents=[comun])
    p.set_defaults(f=cmd_huecos)

    p = sub.add_parser("simular", parents=[comun])
    p.add_argument("--n", type=int, default=6)
    p.add_argument("--semilla", type=int, default=7)
    p.set_defaults(f=cmd_simular)

    p = sub.add_parser("seguir", parents=[comun])
    p.add_argument("--eelog", help="ruta de EE.log (por defecto la de la configuracion)")
    p.add_argument("--salida", help="fichero de texto para OBS")
    p.add_argument("--plantilla", help="fichero con la plantilla")
    p.set_defaults(f=cmd_seguir)

    args = ap.parse_args()
    return args.f(args)


if __name__ == "__main__":
    raise SystemExit(main())
