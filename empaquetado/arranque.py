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

from farmadex.app import main  # noqa: E402

raise SystemExit(main())
