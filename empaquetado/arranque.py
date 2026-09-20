"""Punto de entrada del ejecutable.

No se usa `farmadex/__main__.py` porque PyInstaller no sigue bien los imports
relativos de un modulo `__main__` dentro de un paquete: se quedaba sin Qt.
"""

from farmadex.app import main

raise SystemExit(main())
