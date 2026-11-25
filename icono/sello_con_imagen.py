"""Monta una ilustracion (por ejemplo, la cabeza de toro) en el centro del sello de AGI y saca todos los archivos.

  python icono/sello_con_imagen.py toro.png

Deja en icono/: agi.ico, agi_256.png, agi_512.png, agi_sello.png (con letras), agi_logo_claro.png,
agi_logo_oscuro.png y muestra.png. La ilustracion debe venir sobre fondo blanco y centrada.
"""
import os
import struct
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
sys.path.insert(0, AQUI)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtGui, QtWidgets

import piezas
from opciones import AMARILLO, AZUL, BLANCO, P
from opciones2 import SERIF, texto_arco


def _centro(p, foto, radio, zoom=1.0):
    """La ilustracion recortada en circulo, llenando el disco blanco."""
    p.save()
    recorte = QtGui.QPainterPath()
    recorte.addEllipse(P(50, 50), radio, radio)
    p.setClipPath(recorte)
    lado = min(foto.width(), foto.height()) / zoom
    origen = QtCore.QRectF((foto.width() - lado) / 2, (foto.height() - lado) / 2, lado, lado)
    p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QtCore.QRectF(50 - radio, 50 - radio, 2 * radio, 2 * radio), foto, origen)
    p.restore()


def sello(p, foto, letras=True, zoom=1.0):
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(AZUL))
    p.drawEllipse(QtCore.QRectF(0, 0, 100, 100))
    radio = 33.5 if letras else 41.0
    p.setBrush(QtGui.QColor(BLANCO))
    p.drawEllipse(P(50, 50), radio, radio)
    _centro(p, foto, radio, zoom)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QColor(AMARILLO), 1.6 if letras else 3))
    p.drawEllipse(P(50, 50), radio + 2.6, radio + 2.6)
    if letras:
        letra = QtGui.QFont("Manrope SemiBold")
        letra.setPixelSize(7)
        letra.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, 1.3)
        texto_arco(p, "CONTEO DE GANADO CON DRON", 42.6, letra, BLANCO)
        letra.setPixelSize(8)
        letra.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, 1.6)
        texto_arco(p, "AGI", 42.9, letra, AMARILLO, abajo=True)


def imagen(foto, lado, letras, zoom):
    img = QtGui.QImage(lado, lado, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(img)
    p.scale(lado / 100.0, lado / 100.0)
    sello(p, foto, letras, zoom)
    p.end()
    return img


def _png(img):
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def guardar_ico(ruta, foto, zoom, lados=(16, 20, 24, 32, 40, 48, 64, 128, 256)):
    datos = [_png(imagen(foto, n, False, zoom)) for n in lados]
    pos, entradas = 6 + 16 * len(lados), b""
    for n, d in zip(lados, datos):
        entradas += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(d), pos)
        pos += len(d)
    with open(ruta, "wb") as fh:
        fh.write(struct.pack("<HHH", 0, 1, len(lados)) + entradas + b"".join(datos))


def logo(foto, zoom, fondo, color_nombre, color_linea, alto=400):
    nombre = QtGui.QFont(SERIF); nombre.setPixelSize(round(alto * 0.56)); nombre.setBold(True)
    nombre.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, alto * 0.08)
    linea = QtGui.QFont("Manrope SemiBold"); linea.setPixelSize(round(alto * 0.1))
    linea.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, alto * 0.021)
    ancho_texto = max(QtGui.QFontMetricsF(nombre).horizontalAdvance("AGI"), QtGui.QFontMetricsF(linea).horizontalAdvance("CONTEO DE GANADO CON DRON"))
    m = round(alto * 0.3)
    img = QtGui.QImage(round(alto * 1.22 + ancho_texto) + 2 * m, alto + 2 * m, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor(fondo) if fondo else QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
    p.drawImage(P(m, m), imagen(foto, alto, True, zoom))
    x = m + alto * 1.22
    p.setFont(nombre); p.setPen(QtGui.QColor(color_nombre)); p.drawText(P(x, m + alto * 0.56), "AGI")
    p.setPen(QtGui.QPen(QtGui.QColor(AMARILLO), max(2.0, alto * 0.012))); p.drawLine(P(x + 2, m + alto * 0.66), P(x + ancho_texto * 0.62, m + alto * 0.66))
    p.setFont(linea); p.setPen(QtGui.QColor(color_linea)); p.drawText(P(x + 2, m + alto * 0.82), "CONTEO DE GANADO CON DRON")
    p.end()
    return img


def muestra(foto, zoom):
    hoja = QtGui.QImage(1200, 760, QtGui.QImage.Format.Format_ARGB32)
    hoja.fill(QtGui.QColor("#FFFFFF"))
    p = QtGui.QPainter(hoja)
    p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(P(40, 40), imagen(foto, 420, True, zoom))
    claro = logo(foto, zoom, None, AZUL, piezas.GRIS, 150)
    p.drawImage(P(500, 20), claro)
    p.fillRect(QtCore.QRectF(520, 270, 640, 190), QtGui.QColor(piezas.TINTA))
    p.drawImage(P(500, 250), logo(foto, zoom, None, "#FFFFFF", piezas.CLARO, 150))
    p.fillRect(QtCore.QRectF(0, 500, 1200, 260), QtGui.QColor(piezas.FONDO))
    x = 60
    for n in (160, 96, 64, 48, 32, 24, 16):
        p.drawImage(P(x, 700 - n - 30), imagen(foto, n, False, zoom))
        x += n + 50
    p.end()
    return hoja


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    zoom = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    piezas.cargar_fuentes()
    foto = QtGui.QImage(sys.argv[1]).convertToFormat(QtGui.QImage.Format.Format_ARGB32)
    if foto.isNull():
        sys.exit("No se pudo abrir la imagen.")
    guardar_ico(os.path.join(AQUI, "agi.ico"), foto, zoom)
    imagen(foto, 256, False, zoom).save(os.path.join(AQUI, "agi_256.png"))
    imagen(foto, 512, False, zoom).save(os.path.join(AQUI, "agi_512.png"))
    imagen(foto, 1024, True, zoom).save(os.path.join(AQUI, "agi_sello.png"))
    logo(foto, zoom, None, AZUL, piezas.GRIS).save(os.path.join(AQUI, "agi_logo_claro.png"))
    logo(foto, zoom, None, "#FFFFFF", piezas.CLARO).save(os.path.join(AQUI, "agi_logo_oscuro.png"))
    muestra(foto, zoom).save(os.path.join(AQUI, "muestra.png"))
    print("listo: agi.ico, agi_256.png, agi_512.png, agi_sello.png, agi_logo_claro.png, agi_logo_oscuro.png, muestra.png")


if __name__ == "__main__":
    main()
