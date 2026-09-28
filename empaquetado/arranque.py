"""Punto de entrada del ejecutable.

No se usa `farmadex/__main__.py` porque PyInstaller no sigue bien los imports
relativos de un modulo `__main__` dentro de un paquete: se quedaba sin Qt.
"""

import sys

# "Farmadex.exe --video <url> ...": el reproductor de guias (farmadex/video.py), un
# proceso aparte que no debe arrancar Qt ni la aplicacion; se enruta antes de importarlas.
if "--video" in sys.argv[1:]:
    from farmadex.video import enrutar

    raise SystemExit(enrutar(sys.argv[1:]))

# "Farmadex.exe --comprobar-rapidfuzz": lo lanza construir.ps1 tras empaquetar. Sale con 0 si
# rapidfuzz carga su version compilada y con 3 si ha caido a Python puro (casar nombres
# pasaria de milisegundos a segundos). No abre ventanas ni toca los datos del usuario.
if "--comprobar-rapidfuzz" in sys.argv[1:]:
    from rapidfuzz import fuzz, process

    lento = fuzz.ratio.__module__.endswith("_py") or process.cdist.__module__.endswith("_py")
    raise SystemExit(3 if lento else 0)

# "Farmadex.exe --autoprueba <carpeta>": la pasada de pruebas como un jugador antes de publicar
# (farmadex/autoprueba.py). Sin ventanas visibles, con sus propios datos y su propio candado de
# instancia dentro de <carpeta>: no toca el Farmadex abierto ni los datos del usuario. Va antes de
# importar la app porque tiene que fijar FARMADEX_DATOS antes de que se lean las rutas.
if "--autoprueba" in sys.argv[1:] or "--autoprueba-carga" in sys.argv[1:]:
    from farmadex.autoprueba import main as autoprueba

    raise SystemExit(autoprueba(sys.argv[1:]))

from farmadex.app import main  # noqa: E402

raise SystemExit(main())
