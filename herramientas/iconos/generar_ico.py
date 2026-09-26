"""Convierte un icono en SVG en un .ico de Windows con varios tamanos.

Uso:
    .venv/Scripts/python herramientas/iconos/generar_ico.py RUTA.svg [--salida RUTA.ico]

Cada tamano (16, 24, 32, 48, 64, 128 y 256 px) se dibuja por separado desde el SVG,
en vez de encoger una imagen grande: asi los tamanos pequenos (bandeja del sistema y
barra de tareas) salen nitidos. El de 256 va comprimido en PNG y el resto como mapa de
bits de 32 bits con transparencia, que es lo que espera Windows.

NO sustituye nada del programa: por defecto deja el resultado en
herramientas/iconos/salida/. Al terminar dice que ficheros habria que cambiar para
aplicarlo.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
TAMANOS = (16, 24, 32, 48, 64, 128, 256)
SALIDA_POR_DEFECTO = Path(__file__).resolve().parent / "salida" / "farmadex.ico"
# El .ico que usa el programa hoy. Esta herramienta nunca escribe ahi.
ICO_DEL_PROGRAMA = RAIZ / "recursos" / "iconos" / "farmadex.ico"

PASOS_PARA_APLICAR = """\
Para aplicar el icono nuevo habria que:
  1. Copiar {ico} encima de recursos/iconos/farmadex.ico.
     Ese fichero lo usan el .exe (empaquetado/farmadex.spec, icon=...), el propio
     paquete (se copia dentro como dato) y el instalador (empaquetado/instalador.iss,
     SetupIconFile).
  2. Copiar el SVG elegido a recursos/iconos/farmadex.svg, para tener el original.
  3. Cambiar icono_bandeja() en src/farmadex/ui/overlay.py: hoy dibuja a mano una "F"
     azul; deberia cargar recursos/iconos/farmadex.ico (junto al codigo o dentro del
     paquete de PyInstaller, como hace acerca_de.py con su imagen). Ese icono es el de
     la bandeja junto al reloj y el de los avisos.
  4. Reconstruir con empaquetado/construir.ps1. Windows guarda en cache los iconos de
     los accesos directos: si tras reinstalar sigue saliendo el viejo, es la cache.
"""


def _renderizador(svg: Path) -> QSvgRenderer:
    renderizador = QSvgRenderer(QByteArray(svg.read_bytes()))
    if not renderizador.isValid():
        raise ValueError(f"El SVG no se puede leer: {svg}")
    return renderizador


def dibujar(renderizador: QSvgRenderer, lado: int) -> QImage:
    """El SVG dibujado a `lado` x `lado`, con transparencia (ARGB sin premultiplicar)."""
    imagen = QImage(lado, lado, QImage.Format_ARGB32_Premultiplied)
    imagen.fill(Qt.transparent)
    pintor = QPainter(imagen)
    pintor.setRenderHint(QPainter.Antialiasing)
    pintor.setRenderHint(QPainter.SmoothPixmapTransform)
    renderizador.render(pintor, QRectF(0, 0, lado, lado))
    pintor.end()
    return imagen.convertToFormat(QImage.Format_ARGB32)


def _como_png(imagen: QImage) -> bytes:
    datos = QByteArray()
    bufer = QBuffer(datos)
    bufer.open(QIODevice.WriteOnly)
    imagen.save(bufer, "PNG")
    bufer.close()
    return bytes(datos)


def _como_bmp(imagen: QImage) -> bytes:
    """Entrada de .ico clasica: cabecera BITMAPINFOHEADER + pixeles BGRA de abajo arriba
    + mascara AND (a cero: la transparencia la da el canal alfa)."""
    lado = imagen.width()
    cabecera = struct.pack("<IiiHHIIiiII", 40, lado, lado * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    filas = []
    for y in range(lado - 1, -1, -1):
        # En Format_ARGB32 y maquina little-endian cada pixel ya esta en orden B, G, R, A.
        filas.append(bytes(imagen.constScanLine(y))[: lado * 4])
    ancho_mascara = ((lado + 31) // 32) * 4
    mascara = bytes(ancho_mascara * lado)
    return cabecera + b"".join(filas) + mascara


def construir_ico(svg: Path, tamanos=TAMANOS) -> bytes:
    """Bytes de un .ico con una imagen por tamano, cada una dibujada desde el SVG."""
    if sys.byteorder != "little":  # pragma: no cover - Windows siempre es little-endian
        raise RuntimeError("Solo preparado para maquinas little-endian")
    QApplication.instance() or QApplication([])  # QApplication: si luego se crean widgets en el mismo proceso (tests), no revienta
    renderizador = _renderizador(svg)
    entradas = []
    for lado in tamanos:
        imagen = dibujar(renderizador, lado)
        entradas.append((lado, _como_png(imagen) if lado >= 256 else _como_bmp(imagen)))

    cabecera = struct.pack("<HHH", 0, 1, len(entradas))
    desplazamiento = 6 + 16 * len(entradas)
    directorio, cuerpo = b"", b""
    for lado, datos in entradas:
        dim = 0 if lado >= 256 else lado  # 0 significa 256 en el formato .ico
        directorio += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(datos), desplazamiento)
        cuerpo += datos
        desplazamiento += len(datos)
    return cabecera + directorio + cuerpo


def generar(svg: Path, salida: Path = SALIDA_POR_DEFECTO) -> Path:
    if salida.resolve() == ICO_DEL_PROGRAMA.resolve():
        raise ValueError("Esta herramienta no sustituye el icono del programa; elige otra salida.")
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_bytes(construir_ico(svg))
    return salida


def main(argv=None) -> int:
    analizador = argparse.ArgumentParser(description="SVG -> .ico multi-tamano para Farmadex")
    analizador.add_argument("svg", type=Path, help="icono de partida en SVG")
    analizador.add_argument("--salida", type=Path, default=SALIDA_POR_DEFECTO,
                            help=f"donde dejar el .ico (por defecto {SALIDA_POR_DEFECTO})")
    args = analizador.parse_args(argv)
    ico = generar(args.svg, args.salida)
    print(f"Icono generado: {ico} ({', '.join(str(t) for t in TAMANOS)} px)")
    print()
    print(PASOS_PARA_APLICAR.format(ico=ico))
    return 0


if __name__ == "__main__":
    sys.exit(main())
