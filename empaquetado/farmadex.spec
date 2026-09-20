# Receta de PyInstaller para Farmadex. Se usa desde empaquetado/construir.ps1.
# one-dir (no one-file): arranca mucho mas rapido y no descomprime 200 MB en %Temp%
# cada vez que se abre.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

RAIZ = Path(SPECPATH).parent

datos = [
    (str(RAIZ / "src/farmadex/datos/esquema.sql"), "farmadex/datos"),
    (str(RAIZ / "src/farmadex/datos/glosario_es.json"), "farmadex/datos"),
    (str(RAIZ / "recursos/iconos/farmadex.ico"), "recursos/iconos"),
    (str(RAIZ / "recursos/idiomas"), "recursos/idiomas"),
]
# RapidOCR carga sus piezas por nombre en tiempo de ejecucion
# (ch_ppocr_v3_det.TextDetector y companía), asi que no basta con los datos:
# hay que arrastrar el paquete entero o al arrancar falta la mitad.
ocr_datos, ocr_binarios, ocr_ocultos = collect_all("rapidocr_onnxruntime")
onnx_datos, onnx_binarios, onnx_ocultos = collect_all("onnxruntime")
datos += ocr_datos + onnx_datos

ocultos = ocr_ocultos + onnx_ocultos + [
    "farmadex",
    "farmadex.app",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "onnxruntime.capi._pybind_state",
    "mss.windows",
]

# Qt trae mucho que aqui no se usa; fuera reduce unos 120 MB.
excluidos = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "tkinter",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "pytest",
]

analisis = Analysis(
    [str(RAIZ / "empaquetado/arranque.py")],
    pathex=[str(RAIZ / "src")],
    binaries=ocr_binarios + onnx_binarios,
    datas=datos,
    hiddenimports=ocultos,
    hookspath=[],
    runtime_hooks=[],
    excludes=excluidos,
    noarchive=False,
)

pyz = PYZ(analisis.pure)

exe = EXE(
    pyz,
    analisis.scripts,
    [],
    exclude_binaries=True,
    name="Farmadex",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # sin ventana de consola
    icon=str(RAIZ / "recursos/iconos/farmadex.ico"),
    manifest=str(RAIZ / "empaquetado/manifiesto.xml"),
)

# Lo que Qt y OpenCV traen y aqui no se usa. opengl32sw.dll son 20 MB de
# OpenGL por software que solo hacen falta sin tarjeta grafica; qml, Quick y
# las traducciones de Qt no se tocan en toda la aplicacion.
sobra = (
    "opengl32sw.dll",
    "Qt6Quick",
    "Qt6Qml",
    "Qt6OpenGL",
    "Qt6Pdf",
    "Qt6VirtualKeyboard",
    "Qt6Designer",
    "PySide6/translations",
    "PySide6/qml",
    "PySide6/resources",
    "cv2/data/",
    "opencv_videoio",
)


def sobra_esto(destino: str) -> bool:
    ruta = destino.replace("\\", "/")
    return any(marca in ruta for marca in sobra)


analisis.binaries = TOC([x for x in analisis.binaries if not sobra_esto(x[0])])
analisis.datas = TOC([x for x in analisis.datas if not sobra_esto(x[0])])

coll = COLLECT(
    exe,
    analisis.binaries,
    analisis.datas,
    strip=False,
    upx=False,
    name="Farmadex",
)
