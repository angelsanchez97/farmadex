import sys

if "--autoprueba" in sys.argv[1:] or "--autoprueba-carga" in sys.argv[1:]:
    # Antes de importar la app: la autoprueba fija su propia carpeta de datos (autoprueba.py).
    from .autoprueba import main as autoprueba

    raise SystemExit(autoprueba(sys.argv[1:]))

from .app import main

raise SystemExit(main())
