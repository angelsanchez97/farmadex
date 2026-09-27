# Receta de PyInstaller para Farmadex. Se usa desde empaquetado/construir.ps1.
# one-dir (no one-file): arranca mucho mas rapido y no descomprime 200 MB en %Temp%
# cada vez que se abre.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_delvewheel_libs_directory

RAIZ = Path(SPECPATH).parent

datos = [
    (str(RAIZ / "src/farmadex/datos/esquema.sql"), "farmadex/datos"),
    (str(RAIZ / "src/farmadex/datos/glosario_es.json"), "farmadex/datos"),
    (str(RAIZ / "src/farmadex/datos/glosario_fr.json"), "farmadex/datos"),
    (str(RAIZ / "src/farmadex/datos/glosario_de.json"), "farmadex/datos"),
    (str(RAIZ / "src/farmadex/datos/glosario_pt.json"), "farmadex/datos"),
    (str(RAIZ / "recursos/iconos/farmadex.ico"), "recursos/iconos"),
    (str(RAIZ / "recursos/idiomas"), "recursos/idiomas"),
    # La respuesta de soporte de DE que ensena Ajustes > Acerca de (ui/acerca_de.py).
    (str(RAIZ / "docs/img/respuesta_soporte_de.png"), "docs/img"),
]
# RapidOCR carga sus piezas por nombre en tiempo de ejecucion
# (ch_ppocr_v3_det.TextDetector y companía), asi que no basta con los datos:
# hay que arrastrar el paquete entero o al arrancar falta la mitad.
ocr_datos, ocr_binarios, ocr_ocultos = collect_all("rapidocr_onnxruntime")
onnx_datos, onnx_binarios, onnx_ocultos = collect_all("onnxruntime")
# rapidfuzz elige en tiempo de ejecucion entre sus modulos compilados (*_cpp, *_cpp_avx2) y
# los de Python puro. Sin arrastrar el paquete entero, en el .exe faltaba alguna pieza que
# importan los compilados y caia a Python puro: casar una build tardaba segundos (0.6.1).
rf_datos, rf_binarios, rf_ocultos = collect_all("rapidfuzz")
# Pero la causa real era otra: los compilados de rapidfuzz enlazan contra una copia
# renombrada del runtime de C++ (msvcp140-<huella>.dll) que viene en site-packages/rapidfuzz.libs,
# y rapidfuzz/__init__ solo la encuentra si esa carpeta esta junto al paquete. PyInstaller la
# metia en numpy.libs (numpy trae el mismo fichero), rapidfuzz.libs no existia en el .exe,
# el compilado no cargaba y rapidfuzz caia en silencio a Python puro. construir.ps1 lo vigila.
rf_datos, rf_binarios = collect_delvewheel_libs_directory("rapidfuzz", datas=rf_datos, binaries=rf_binarios)
datos += ocr_datos + onnx_datos + rf_datos

ocultos = ocr_ocultos + onnx_ocultos + rf_ocultos + [
    "farmadex",
    "farmadex.app",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "onnxruntime.capi._pybind_state",
    "mss.windows",
    # Reproductor de guias (Farmadex.exe --video): pywebview elige su motor en tiempo de
    # ejecucion y carga WinForms/WebView2 por pythonnet, asi que PyInstaller no lo ve solo.
    # Sus DLL (Microsoft.Web.WebView2.*.dll, WebBrowserInterop) las mete el hook que trae
    # el propio pywebview; Python.Runtime.dll, el de pythonnet de pyinstaller-hooks-contrib.
    "farmadex.video",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "clr",
    "clr_loader",
    "pythonnet",
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
    binaries=ocr_binarios + onnx_binarios + rf_binarios,
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
