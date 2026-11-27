"""Saca todos los archivos del logo de AGI a partir del trazo de icono/agi_marca.svg.

  python icono/logo.py

Deja en icono/: agi.ico, agi_256.png, agi_512.png (el icono: trazo blanco en un cuadro negro),
agi_logo_oscuro.png (trazo y nombre en blanco, para fondos oscuros) y agi_logo_claro.png (en negro, para fondos claros).
Solo necesita PySide6-Essentials, que ya usa la aplicacion.
"""
import os
import struct
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

SVG = open(os.path.join(AQUI, "agi_marca.svg"), encoding="utf8").read()
FAMILIA = "Manrope"


def icono(lado):
    """El icono completo (cuadro negro con el trazo) a 'lado' pixeles."""
    img = QtGui.QImage(lado, lado, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    QtSvg.QSvgRenderer(QtCore.QByteArray(SVG.encode("utf8"))).render(p, QtCore.QRectF(0, 0, lado, lado))
    p.end()
    return img


def trazo(lado, color):
    """Solo el trazo, sin el cuadro, en el color pedido y sobre fondo transparente."""
    solo = SVG[:SVG.index("<rect")] + SVG[SVG.index('<g id="trazo"'):]
    solo = solo.replace('stroke="#FFFFFF"', f'stroke="{color}"').replace('fill="#FFFFFF"', f'fill="{color}"')
    img = QtGui.QImage(lado, lado, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    QtSvg.QSvgRenderer(QtCore.QByteArray(solo.encode("utf8"))).render(p, QtCore.QRectF(0, 0, lado, lado))
    p.end()
    return img


def _png(img):
    datos = QtCore.QByteArray()
    bufer = QtCore.QBuffer(datos)
    bufer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    img.save(bufer, "PNG")
    return bytes(datos)


def guardar_ico(ruta, lados=(16, 20, 24, 32, 40, 48, 64, 128, 256)):
    datos = [_png(icono(n)) for n in lados]
    pos, entradas = 6 + 16 * len(lados), b""
    for n, d in zip(lados, datos):
        entradas += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(d), pos)
        pos += len(d)
    with open(ruta, "wb") as fh:
        fh.write(struct.pack("<HHH", 0, 1, len(lados)) + entradas + b"".join(datos))


def logo(color, alto=400):
    """El trazo y, al lado, el nombre en Manrope con las letras separadas."""
    letra = QtGui.QFont(FAMILIA)
    letra.setWeight(QtGui.QFont.Weight.DemiBold)
    letra.setPixelSize(round(alto * 0.5))
    letra.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, alto * 0.11)
    ancho_texto = QtGui.QFontMetricsF(letra).horizontalAdvance("AGI") - alto * 0.11      # sin el espacio tras la ultima letra
    m = round(alto * 0.3)
    img = QtGui.QImage(round(alto * 1.08 + ancho_texto) + 2 * m, alto + 2 * m, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
    p.drawImage(QtCore.QPointF(m - alto * 0.1, m), trazo(alto, color))
    p.setFont(letra)
    p.setPen(QtGui.QColor(color))
    p.drawText(QtCore.QRectF(m + alto * 1.0, m, ancho_texto + alto, alto),
               QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, "AGI")
    p.end()
    return img


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    global FAMILIA
    n = QtGui.QFontDatabase.addApplicationFont(os.path.join(AQUI, "..", "fuentes", "Manrope-SemiBold.ttf"))
    FAMILIA = (QtGui.QFontDatabase.applicationFontFamilies(n) or ["Manrope"])[0]
    guardar_ico(os.path.join(AQUI, "agi.ico"))
    icono(256).save(os.path.join(AQUI, "agi_256.png"))
    icono(512).save(os.path.join(AQUI, "agi_512.png"))
    logo("#FFFFFF").save(os.path.join(AQUI, "agi_logo_oscuro.png"))
    logo("#0A0A0A").save(os.path.join(AQUI, "agi_logo_claro.png"))
    del app
    print("listo: agi.ico, agi_256.png, agi_512.png, agi_logo_oscuro.png, agi_logo_claro.png")


if __name__ == "__main__":
    main()
