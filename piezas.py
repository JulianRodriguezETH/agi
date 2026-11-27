"""Piezas de la interfaz de AGI que usa agi.py: acceso, visor de fotos, deteccion
en segundo plano, panel de usuarios y respaldo.

Necesita: PySide6-Essentials, onnxruntime, opencv-python, numpy.
"""
import datetime
import os
import sys
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

import contar
import datos
import seguridad
import vuelo

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELO = os.path.join(AQUI, "modelos", "reses_s.onnx")
CONF_MIN = 0.20          # se detecta con umbral bajo y el control deslizante filtra
CONF_DEFECTO = 0.30
ARCHIVO_REVISION = "conteo_revision.json"
CAJA_IA, CAJA_MANUAL = (90, 165, 255), (95, 211, 141)   # RGB de los recuadros: azul lo que conto el programa, verde lo agregado a mano
CAIDA_ALERTA = 5.0       # % de caida entre dos conteos que se resalta en el historial

# Tema oscuro y sobrio: fondo negro, tarjetas gris carbon, texto blanco. El acento es el propio blanco y,
# para lo destacado, un azul pizarra; no hay color de marca aparte.
TINTA, GRIS, FONDO, LINEA, ACENTO = "#0A0A0A", "#A6A6A6", "#000000", "#262626", "#FFFFFF"
CLARO = "#D9D9D9"        # texto secundario sobre las tarjetas destacadas
TEXTO, SUPERFICIE, RELIEVE, BORDE = "#FFFFFF", "#141414", "#1F1F1F", "#333333"   # TINTA queda para texto sobre blanco
VERDE, ROJO, AZUL = "#5FD38D", "#FF7B72", "#9DBDF2"                               # estados, legibles sobre negro
FONDO_VERDE, FONDO_ROJO = "#12301F", "#3A1614"
SELECCION = "#1E2A40"    # fila o texto seleccionado
# tarjeta destacada: degradado azul pizarra que se apaga hacia el negro
DEGRADADO = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #34486A, stop:1 #10141B)"
DEGRADADO_SUAVE = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1D2636, stop:1 #0B0D11)"      # el mismo, mas apagado
SOMBRAS = os.environ.get("AGI_SIN_SOMBRAS") != "1"
_fuentes_listas = False


def tomar_candado(carpeta):
    """Una sola ventana de AGI por carpeta de datos: dos a la vez podrian pisarse la base.
    Devuelve el candado (hay que conservarlo vivo) o None si AGI ya esta abierto."""
    os.makedirs(carpeta, exist_ok=True)
    candado = QtCore.QLockFile(os.path.join(carpeta, "agi.lock"))
    candado.setStaleLockTime(0)          # solo se da por abandonado si el proceso que lo puso ya no existe
    return candado if candado.tryLock(200) else None


def instalar_registro_errores(carpeta):
    """Cualquier error que nadie atrapo se anota en agi_errores.log y se le dice a la persona,
    en vez de que la ventana se cierre sin explicacion. Devuelve la ruta del registro."""
    ruta = os.path.join(carpeta, "agi_errores.log")
    avisando = []

    def anotar(tipo, valor, traza, avisar=True):
        try:
            os.makedirs(carpeta, exist_ok=True)
            if os.path.exists(ruta) and os.path.getsize(ruta) > 1 << 20:
                os.replace(ruta, ruta + ".1")           # se conserva solo el registro anterior
            with open(ruta, "a", encoding="utf8") as fh:
                fh.write(f"\n--- {datetime.datetime.now().isoformat(timespec='seconds')} · AGI {datos.VERSION}\n")
                fh.write("".join(traceback.format_exception(tipo, valor, traza)))
        except OSError:
            pass
        if avisar and not avisando and QtWidgets.QApplication.instance() is not None:
            avisando.append(1)
            try:
                QtWidgets.QMessageBox.critical(None, "AGI", "An unexpected error occurred. AGI is still open and what you already "
                                               f"saved is safe.\n\nThe details were written to:\n{ruta}\n\n"
                                               "If it happens again, that file helps find the fault.")
            finally:
                avisando.clear()

    sys.excepthook = anotar
    threading.excepthook = lambda a: anotar(a.exc_type, a.exc_value, a.exc_traceback, avisar=False)
    return ruta


def comprobar_modelo(ruta):
    """Compara el modelo con la huella que viene al lado (reses_s.onnx.sha256). Devuelve None si
    coincide o no hay huella, o el problema en palabras sencillas."""
    huella = ruta + ".sha256"
    if not os.path.exists(huella):
        return None
    try:
        with open(huella, encoding="ascii") as fh:
            esperada = fh.read().split()[0].strip().lower()
    except (OSError, IndexError, UnicodeDecodeError):
        return "Could not read the counting model's fingerprint. Reinstall AGI."
    if seguridad.sha256_archivo(ruta) != esperada:
        return "The counting model is not the original: the file is damaged or was changed. Reinstall AGI."
    return None


def cargar_fuentes():
    """Registra Manrope (titulos y numeros). Si falta la carpeta, Qt usa la letra del sistema."""
    global _fuentes_listas
    if _fuentes_listas or QtWidgets.QApplication.instance() is None:
        return
    for nombre in ("Manrope-Bold.ttf", "Manrope-SemiBold.ttf"):
        ruta = os.path.join(AQUI, "fuentes", nombre)
        if os.path.exists(ruta):
            QtGui.QFontDatabase.addApplicationFont(ruta)
    _fuentes_listas = True




_sello, _sello_tam = None, {}


def _imagen_sello(lado):
    """El logo de AGI (icono/agi_512.png) reducido con cuidado al tamano pedido. None si el archivo falta."""
    global _sello
    if _sello is None:
        ruta = os.path.join(AQUI, "icono", "agi_512.png")
        _sello = QtGui.QImage(ruta) if os.path.exists(ruta) else QtGui.QImage()
    if _sello.isNull():
        return None
    if lado not in _sello_tam:
        _sello_tam[lado] = _sello.scaled(lado, lado, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                         QtCore.Qt.TransformationMode.SmoothTransformation)
    return _sello_tam[lado]


def pintar_marca(p, x, y, lado):
    """El logo de AGI: una res que tambien es un dron (cuernos con helices sobre el lente). Si falta la imagen, se dibuja aqui mismo."""
    img = _imagen_sello(int(round(lado * 2)))                 # al doble, para pantallas de alta densidad
    if img is None:
        return _pintar_marca_dibujo(p, x, y, lado)
    p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QtCore.QRectF(x, y, lado, lado), img)


def _pintar_marca_dibujo(p, x, y, lado):
    """Respaldo, con el mismo trazo de icono/agi_marca.svg: cuadro negro, los cuernos con una helice en cada punta
    y el aro con su punto (el lente del dron)."""
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    u = lado / 512.0
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), max(1.0, 4 * u)))
    p.setBrush(QtGui.QColor("#000000"))
    p.drawRoundedRect(QtCore.QRectF(x + 2 * u, y + 2 * u, lado - 4 * u, lado - 4 * u), 112 * u, 112 * u)
    P = lambda a, b: QtCore.QPointF(x + a * u, y + b * u)
    pluma = QtGui.QPen(QtGui.QColor("#FFFFFF"), 34 * u)
    pluma.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    p.setPen(pluma)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    p.drawEllipse(P(256, 328), 78 * u, 78 * u)
    cuernos = QtGui.QPainterPath(P(136, 136))
    cuernos.cubicTo(P(146, 208), P(196, 250), P(256, 250))
    cuernos.cubicTo(P(316, 250), P(366, 208), P(376, 136))
    p.drawPath(cuernos)
    pluma.setWidthF(24 * u)
    p.setPen(pluma)
    p.drawLine(P(94, 124), P(178, 124))
    p.drawLine(P(334, 124), P(418, 124))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#FFFFFF"))
    p.drawEllipse(P(256, 328), 23 * u, 23 * u)


def pixmap_marca(lado=64):
    pm = QtGui.QPixmap(lado, lado)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    pintar_marca(p, 0, 0, lado)
    p.end()
    return pm


class Marca(QtWidgets.QWidget):
    """Logo de AGI, con o sin el nombre al lado."""

    def __init__(self, lado=32, nombre=True, color="#FFFFFF"):
        super().__init__()
        cargar_fuentes()
        self.lado, self.nombre, self.color = lado, nombre, color
        self.letra = QtGui.QFont("Manrope")
        self.letra.setPixelSize(round(lado * 0.56))
        self.letra.setBold(True)
        self.letra.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, lado * 0.09)
        ancho = lado
        if nombre:
            ancho += round(lado * 0.38) + QtGui.QFontMetrics(self.letra).horizontalAdvance("AGI") + 2
        self.setFixedSize(ancho, lado)
        self.setAccessibleName("AGI")

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        pintar_marca(p, 0, 0, self.lado)
        if self.nombre:
            p.setFont(self.letra)
            p.setPen(QtGui.QColor(self.color))
            p.drawText(QtCore.QRectF(self.lado + round(self.lado * 0.38), 0, self.width(), self.lado),
                       QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, "AGI")


def _iconos():
    """Los trazos de cada icono sobre una cuadricula de 24: una lista de (tipo, datos) que icono() dibuja."""
    P = QtCore.QPointF
    cuernos = QtGui.QPainterPath(P(6.6, 4.8))
    cuernos.cubicTo(P(7.1, 8.5), P(9.4, 10.6), P(12, 10.6))
    cuernos.cubicTo(P(14.6, 10.6), P(16.9, 8.5), P(17.4, 4.8))
    candado = QtGui.QPainterPath(P(8, 11))
    candado.lineTo(8, 8)
    candado.arcTo(QtCore.QRectF(8, 4, 8, 8), 180, -180)
    candado.lineTo(16, 11)
    escudo = QtGui.QPainterPath(P(12, 3.2))
    escudo.lineTo(19, 5.8)
    escudo.lineTo(19, 11)
    escudo.cubicTo(P(19, 15.3), P(16.1, 18.8), P(12, 20.6))
    escudo.cubicTo(P(7.9, 18.8), P(5, 15.3), P(5, 11))
    escudo.lineTo(5, 5.8)
    escudo.closeSubpath()
    pin = QtGui.QPainterPath(P(12, 20.5))
    pin.cubicTo(P(8, 16.4), P(6, 13.4), P(6, 10.4))
    pin.cubicTo(P(6, 6.8), P(8.7, 4), P(12, 4))
    pin.cubicTo(P(15.3, 4), P(18, 6.8), P(18, 10.4))
    pin.cubicTo(P(18, 13.4), P(16, 16.4), P(12, 20.5))
    esquinas = [("linea", [P(4, 8.5), P(4, 4), P(8.5, 4)]), ("linea", [P(15.5, 4), P(20, 4), P(20, 8.5)]),
                ("linea", [P(20, 15.5), P(20, 20), P(15.5, 20)]), ("linea", [P(8.5, 20), P(4, 20), P(4, 15.5)])]
    return {
        "check": [("linea", [P(5, 12.5), P(9.5, 17), P(19, 7.5)])],
        "candado": [("caja", (5, 11, 14, 9, 2)), ("camino", candado)],
        "res": [("camino", cuernos), ("circulo", (12, 15.2, 4.4)), ("linea", [P(4.4, 4.5), P(8.8, 4.5)]),
                ("linea", [P(15.2, 4.5), P(19.6, 4.5)]), ("punto", (12, 15.2, 1.3))],
        "modelo": esquinas + [("punto", (12, 12, 2.2))],
        "mas": [("circulo", (12, 12, 8.2)), ("linea", [P(12, 8.4), P(12, 15.6)]), ("linea", [P(8.4, 12), P(15.6, 12)])],
        "menos": [("circulo", (12, 12, 8.2)), ("linea", [P(8.4, 12), P(15.6, 12)])],
        "cuadre": [("linea", [P(4.5, 8.5), P(19.5, 8.5)]), ("linea", [P(16, 5), P(19.5, 8.5), P(16, 12)]),
                   ("linea", [P(19.5, 15.5), P(4.5, 15.5)]), ("linea", [P(8, 12), P(4.5, 15.5), P(8, 19)])],
        "lupa": [("circulo", (10.8, 10.8, 6.2)), ("linea", [P(15.4, 15.4), P(20, 20)])],
        "mapa": [("camino", pin), ("circulo", (12, 10.4, 2.3))],
        "escudo": [("camino", escudo), ("linea", [P(9, 11.8), P(11.3, 14.1), P(15.2, 9.8)])],
        "corral": [("linea", [P(3.5, 9), P(20.5, 9)]), ("linea", [P(3.5, 15), P(20.5, 15)]), ("linea", [P(6.5, 5.5), P(6.5, 19)]),
                   ("linea", [P(12, 5.5), P(12, 19)]), ("linea", [P(17.5, 5.5), P(17.5, 19)])],
        "video": [("caja", (3.5, 6, 17, 12, 3)), ("linea", [P(10.3, 9.4), P(14.6, 12), P(10.3, 14.6), P(10.3, 9.4)])],
        "tabla": [("caja", (4, 5, 16, 14, 2.5)), ("linea", [P(4, 10), P(20, 10)]), ("linea", [P(10, 10), P(10, 19)])],
        "nube": [("linea", [P(12, 15.5), P(12, 6)]), ("linea", [P(8.3, 9.6), P(12, 6), P(15.7, 9.6)]),
                 ("linea", [P(5, 15.5), P(5, 19), P(19, 19), P(19, 15.5)])],
    }


def icono(nombre, color, lado=16):
    """Iconos de linea dibujados aqui para no depender de archivos (los nombres estan en _iconos)."""
    pm = QtGui.QPixmap(lado * 2, lado * 2)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.scale(lado * 2 / 24.0, lado * 2 / 24.0)
    pluma = QtGui.QPen(QtGui.QColor(color), 2.4 if nombre == "check" else (2.0 if lado <= 16 else 1.6))
    pluma.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pluma.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pluma)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    for tipo, d in _iconos().get(nombre, ()):
        if tipo == "linea":
            p.drawPolyline(QtGui.QPolygonF(d))
        elif tipo == "camino":
            p.drawPath(d)
        elif tipo == "circulo":
            p.drawEllipse(QtCore.QPointF(d[0], d[1]), d[2], d[2])
        elif tipo == "caja":
            p.drawRoundedRect(QtCore.QRectF(d[0], d[1], d[2], d[3]), d[4], d[4])
        elif tipo == "punto":
            p.setBrush(QtGui.QColor(color))
            p.drawEllipse(QtCore.QPointF(d[0], d[1]), d[2], d[2])
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return pm


def insignia(nombre, lado=48):
    """Un icono de linea dentro de un circulo translucido: encabeza las tarjetas y los datos destacados."""
    e = QtWidgets.QLabel()
    e.setObjectName("insignia")
    e.setFixedSize(lado, lado)
    e.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    e.setPixmap(icono(nombre, "#FFFFFF", round(lado * 0.46)))
    e.setStyleSheet(f"background: rgba(182, 211, 255, 0.10); border: 1px solid rgba(255, 255, 255, 0.16); "
                    f"border-radius: {lado // 2 - 1}px;")
    return e


# Como se pinta cada panel segun su nombre: (radio de las esquinas, acabado)
PANELES = {"premio": (18, "destacado"), "anuncio": (18, "destacado"), "heroe": (14, "destacado"), "aviso": (12, "destacado"),
           "caja_oscura": (12, "destacado"), "beneficios": (18, "suave"), "tarjeta": (16, "carta"), "caja": (12, "caja"),
           "panel_marca": (0, "marca")}


_termica = []


def _foto_termica():
    """La toma termica de fondo de la pantalla de entrada (icono/termica.jpg). None si el archivo falta."""
    if not _termica:
        ruta = os.path.join(AQUI, "icono", "termica.jpg")
        img = QtGui.QImage(ruta) if os.path.exists(ruta) else QtGui.QImage()
        _termica.append(None if img.isNull() else img)
    return _termica[0]


class Panel(QtWidgets.QFrame):
    """Tarjeta pintada a mano, para darle profundidad: un degradado azul pizarra que se apaga hacia el negro, una luz
    suave que entra por la esquina de arriba y un borde fino mas claro arriba que abajo, como un vidrio.
    El panel de la marca (entrada y bloqueo) lleva de fondo una toma termica de ejemplo.
    El acabado sale del nombre del objeto (ver PANELES); con otro nombre se comporta como un QFrame cualquiera."""

    def paintEvent(self, ev):
        radio, tipo = PANELES.get(self.objectName(), (0, None))
        if tipo is None:
            return super().paintEvent(ev)
        C, P = QtGui.QColor, QtCore.QPointF
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        forma = QtGui.QPainterPath()
        forma.addRoundedRect(r, radio, radio)
        borde_arriba, borde_abajo = 46, 10
        if tipo == "marca":                     # la pantalla de entrada: una toma termica al fondo, velada en azul
            p.fillPath(forma, C("#05070B"))
            foto = _foto_termica()
            if foto is not None:
                escala = max(r.width() / foto.width(), r.height() / foto.height())
                w, h = foto.width() * escala, foto.height() * escala
                p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
                p.setOpacity(0.5)
                p.drawImage(QtCore.QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h), foto)
                p.setOpacity(1.0)
            g = QtGui.QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0.0, C(107, 155, 225, 96))
            g.setColorAt(1.0, C(5, 7, 11, 150))
            p.fillPath(forma, g)
            velo = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
            velo.setColorAt(0.0, C(0, 0, 0, 70))
            velo.setColorAt(0.45, C(0, 0, 0, 40))
            velo.setColorAt(1.0, C(0, 0, 0, 170))
            p.fillPath(forma, velo)
            return
        if tipo == "destacado":
            p.fillPath(forma, C("#0A0D13"))
            g = QtGui.QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0.0, C(107, 155, 225, 132))
            g.setColorAt(0.55, C(107, 155, 225, 46))
            g.setColorAt(1.0, C(107, 155, 225, 10))
            p.fillPath(forma, g)
            luz = QtGui.QRadialGradient(P(r.left() + r.width() * 0.22, r.top()), max(r.width() * 0.62, 180.0))
            luz.setColorAt(0.0, C(190, 215, 255, 64))
            luz.setColorAt(1.0, C(190, 215, 255, 0))
            p.fillPath(forma, luz)
            borde_arriba, borde_abajo = 86, 14
        elif tipo == "suave":
            p.fillPath(forma, C("#0B0D11"))
            g = QtGui.QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0.0, C(107, 155, 225, 58))
            g.setColorAt(1.0, C(107, 155, 225, 0))
            p.fillPath(forma, g)
        elif tipo == "carta":
            g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0.0, C("#1B1B1D"))
            g.setColorAt(1.0, C("#101011"))
            p.fillPath(forma, g)
            luz = QtGui.QRadialGradient(P(r.center().x(), r.top()), max(r.width() * 0.55, 160.0))
            luz.setColorAt(0.0, C(150, 185, 255, 20))
            luz.setColorAt(1.0, C(150, 185, 255, 0))
            p.fillPath(forma, luz)
        else:                                   # caja: un vidrio apenas mas claro que lo que tiene debajo
            p.fillPath(forma, C(255, 255, 255, 14))
            borde_arriba, borde_abajo = 30, 8
        b = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
        b.setColorAt(0.0, C(255, 255, 255, borde_arriba))
        b.setColorAt(1.0, C(255, 255, 255, borde_abajo))
        p.setPen(QtGui.QPen(QtGui.QBrush(b), 1.0))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawPath(forma)


def brillo(w):
    """Un resplandor azul bajo la tarjeta destacada de una pantalla. Solo para tarjetas que no estan dentro de otra con sombra."""
    if SOMBRAS:
        e = QtWidgets.QGraphicsDropShadowEffect(w)
        e.setBlurRadius(56)
        e.setOffset(0, 14)
        e.setColor(QtGui.QColor(64, 112, 210, 64))
        w.setGraphicsEffect(e)
    return w


def sombra(w):
    """Sombra suave bajo tarjetas y tablas. AGI_SIN_SOMBRAS=1 la apaga si un equipo la dibuja mal."""
    if SOMBRAS:
        e = QtWidgets.QGraphicsDropShadowEffect(w)
        e.setBlurRadius(20)          # corta: no debe llegar al widget de abajo, que la taparia
        e.setOffset(0, 4)
        e.setColor(QtGui.QColor(0, 0, 0, 120))
        w.setGraphicsEffect(e)
    return w


def carpeta_datos():
    """Donde viven la base cifrada y las llaves (se puede cambiar con GANADERIA_DATOS)."""
    return os.environ.get("GANADERIA_DATOS") or os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"), "GanaderiaDron")


def crear_sesion(carpeta, usuario, clave):
    """Primer arranque. Devuelve (base, llave, codigo_de_recuperacion)."""
    llave, codigo = seguridad.crear_almacen(carpeta, usuario, clave)
    base = datos.Base(carpeta, llave, usuario)
    base.iniciar(usuario)
    base.anotar("sesion_iniciada")
    return base, llave, codigo


def abrir_sesion(carpeta, usuario, clave):
    llave, nueva = seguridad.abrir_almacen2(carpeta, usuario, clave)
    try:
        base = datos.Base(carpeta, llave, usuario)
        if nueva is not None:                   # se fue la luz antes de cambiar la llave de la base
            base.terminar_rotacion(nueva, ya_cambiada=False)
    except seguridad.ErrorAcceso:
        if nueva is None:
            raise
        base = datos.Base(carpeta, nueva, usuario)      # se fue la luz despues de cambiarla
        base.terminar_rotacion(nueva, ya_cambiada=True)
    if base.rol is None:
        base.cerrar()
        raise seguridad.ErrorAcceso("User deactivated.")
    fallos = seguridad.fallos_sin_avisar(carpeta)
    if fallos:
        base.anotar("intentos_fallidos", {"cuantos": fallos})     # que el dueno sepa que alguien tanteo
    base.anotar("sesion_iniciada")
    return base, base.llave


class DialogoAcceso(QtWidgets.QDialog):
    """Crea el almacen la primera vez; despues pide usuario y contrasena."""

    def __init__(self, carpeta):
        super().__init__()
        self.carpeta, self.base, self.llave = carpeta, None, None
        self.nuevo = not seguridad.existe_almacen(carpeta)
        cargar_fuentes()
        self.setWindowTitle("AGI")
        self.setWindowIcon(QtGui.QIcon(pixmap_marca(64)))
        self.setMinimumSize(880, 560)
        self.usuario = QtWidgets.QLineEdit()        # se escribe: no se muestran las cuentas que existen
        self.clave = QtWidgets.QLineEdit()
        self.clave.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.clave2 = QtWidgets.QLineEdit()
        self.clave2.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.aviso = QtWidgets.QLabel()
        self.aviso.setObjectName("error")
        self.aviso.setWordWrap(True)

        def texto(t, nombre=None):
            e = QtWidgets.QLabel(t)
            e.setWordWrap(True)
            if nombre:
                e.setObjectName(nombre)
            return e

        raiz = QtWidgets.QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        # Mitad izquierda: la marca y lo que el servicio garantiza
        panel = Panel()
        panel.setObjectName("panel_marca")
        panel.setFixedWidth(400)
        pl = QtWidgets.QVBoxLayout(panel)
        pl.setContentsMargins(44, 44, 44, 44)
        pl.setSpacing(0)
        pl.addWidget(Marca(72))
        pl.addStretch(1)
        pl.addWidget(texto("Drone cattle counting, reviewed and signed.", "lema"))
        pl.addSpacing(14)
        pl.addWidget(texto("Cattle inventory from the air: every animal is recorded once, with human review and a digital signature.", "lema_sub"))
        pl.addStretch(1)
        for garantia in ("Data encrypted on this computer", "Signed, verifiable reports", "Automatic backup"):
            linea = QtWidgets.QHBoxLayout()
            linea.setSpacing(12)
            marca = QtWidgets.QLabel()
            marca.setPixmap(icono("check", ACENTO, 18))
            marca.setFixedSize(18, 18)
            linea.addWidget(marca)
            linea.addWidget(texto(garantia), 1)
            pl.addLayout(linea)
            pl.addSpacing(12)
        raiz.addWidget(panel)

        # Mitad derecha: el formulario
        caja = QtWidgets.QWidget()
        caja.setMaximumWidth(380)
        f = QtWidgets.QVBoxLayout(caja)
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(8)
        f.addWidget(texto("Create account" if self.nuevo else "Sign in", "entrar_titulo"))
        f.addWidget(texto("First time on this computer: create your account. Only you know the password, and it "
                          f"encrypts your data (at least {seguridad.LARGO_MINIMO} characters)." if self.nuevo
                          else "With this computer's user and password.", "sub"))
        f.addSpacing(14)
        campos = [("User", self.usuario), ("Password", self.clave)]
        if self.nuevo:
            campos.append(("Repeat the password", self.clave2))
        for rotulo, campo in campos:
            e = texto(rotulo, "campo")
            e.setBuddy(campo)
            campo.setMinimumHeight(46)
            f.addWidget(e)
            f.addWidget(campo)
            f.addSpacing(8)
        f.addWidget(self.aviso)
        ok = QtWidgets.QPushButton("Create" if self.nuevo else "Sign in")
        ok.setObjectName("primario")
        ok.setMinimumHeight(48)
        ok.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self.intentar)
        f.addWidget(ok)
        if not self.nuevo:
            otro = QtWidgets.QPushButton("Forgot my password…")
            otro.clicked.connect(self.recuperar)
        else:
            otro = QtWidgets.QPushButton("Restore from a backup…")
            otro.setToolTip("For a new computer: brings back the ranch, the counts and the reports from the backup USB")
            otro.clicked.connect(self.restaurar)
        otro.setObjectName("plano")
        otro.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        otro.setAutoDefault(False)
        f.addWidget(otro)
        derecha = QtWidgets.QVBoxLayout()
        derecha.setContentsMargins(56, 48, 56, 48)
        derecha.addStretch(1)
        derecha.addWidget(caja)
        derecha.addStretch(1)
        raiz.addStretch(1)
        raiz.addLayout(derecha, 100)
        raiz.addStretch(1)
        self.usuario.setFocus()

    RESTAURADO = 2      # codigo de salida: se restauro un respaldo, hay que pedir la contrasena

    def restaurar(self):
        origen = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder with the backups")
        if origen:
            self.restaurar_desde(origen)

    def restaurar_desde(self, origen):
        try:
            usado = datos.restaurar_respaldo(origen, self.carpeta)
        except (ValueError, OSError) as err:
            self.aviso.setText(str(err))
            return
        QtWidgets.QMessageBox.information(self, "Backup restored",
                                          f"Restored {os.path.basename(usado)}.\nSign in with your usual user and password.")
        self.done(self.RESTAURADO)

    def intentar(self):
        usuario, clave = self.usuario.text().strip(), self.clave.text()
        try:
            if self.nuevo:
                if not usuario:
                    raise ValueError("The user name is missing.")
                if clave != self.clave2.text():
                    raise ValueError("The two passwords don't match.")
                self.base, self.llave, codigo = crear_sesion(self.carpeta, usuario, clave)
                QtWidgets.QMessageBox.information(
                    self, "Recovery code",
                    f"Write this code on paper and keep it away from the computer:\n\n"
                    f"{codigo}\n\nIt's the only way in if the password is forgotten. Without it nobody can recover "
                    "your data. It won't be shown again.")
            else:
                self.base, self.llave = abrir_sesion(self.carpeta, usuario, clave)
            self.accept()
        except (ValueError, seguridad.ErrorAcceso) as err:
            self.aviso.setText(str(err))
            self.clave.clear()

    def recuperar(self):
        codigo, ok = QtWidgets.QInputDialog.getText(self, "Recover access", "Recovery code:")
        if not ok:
            return
        nueva, ok = QtWidgets.QInputDialog.getText(self, "Recover access",
                                                   f"New password for {self.usuario.text().strip()}:",
                                                   QtWidgets.QLineEdit.EchoMode.Password)
        if not ok:
            return
        try:
            llave = seguridad.abrir_con_recuperacion(self.carpeta, codigo)
            usuario = self.usuario.text().strip()
            if usuario not in seguridad.usuarios_con_llave(self.carpeta):
                raise ValueError("Type your user name first.")
            seguridad.poner_ranura(self.carpeta, llave, usuario, nueva)
            b = datos.Base(self.carpeta, llave, usuario)
            b.anotar("acceso_recuperado", "with the recovery code")   # que quede constancia
            b.cerrar()
            self.aviso.setText("Password changed. Sign in with the new one.")
        except (ValueError, seguridad.ErrorAcceso) as err:
            self.aviso.setText("Wrong code." if isinstance(err, seguridad.ErrorAcceso) else str(err))


ROL_VISIBLE = {"admin": "admin", "operador": "operator"}     # como se muestra cada rol


class DialogoUsuarios(QtWidgets.QDialog):
    """Panel del administrador: perfiles de quienes usan el programa."""
    COLUMNAS = ("User", "Role", "Status", "Created", "Last sign-in", "Sign-ins", "Counts", "Cattle counted", "Last action")
    NOMBRES = {"sesion_iniciada": "signed in", "conteo_guardado": "saved a count", "reporte_exportado": "exported a report",
               "finca_creada": "created a ranch", "usuario_creado": "created a user", "usuario_desactivado": "deactivated a user",
               "clave_restablecida": "reset a password", "clave_cambiada": "changed their password",
               "rol_cambiado": "changed a role", "datos_exportados": "exported the data", "conteo_borrado": "deleted a count",
               "almacen_creado": "created the key store",
               "acceso_recuperado": "recovered access",
               "respaldo_hecho": "made a backup", "respaldo_configurado": "chose the backup folder",
               "referencia_anotada": "entered a corral count", "movimiento_anotado": "logged a movement",
               "excel_exportado": "exported to Excel", "finca_renombrada": "fixed the ranch name"}

    def __init__(self, base, llave, padre=None):
        super().__init__(padre)
        self.base, self.llave = base, llave
        self.setWindowTitle("Users")
        self.resize(900, 560)
        self.tabla = QtWidgets.QTableWidget(0, len(self.COLUMNAS))
        self.tabla.setHorizontalHeaderLabels([c.upper() for c in self.COLUMNAS])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(46)
        self.tabla.setShowGrid(False)
        self.tabla.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.tabla.horizontalHeader().setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.tabla.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.horizontalHeader().setStretchLastSection(True)
        self.tabla.currentCellChanged.connect(lambda fila, *_: self.ver(fila))
        self.actividad = QtWidgets.QPlainTextEdit()
        self.actividad.setReadOnly(True)
        self.actividad.setMaximumHeight(200)
        self.estado = QtWidgets.QLabel()
        botones = QtWidgets.QHBoxLayout()
        for texto, accion in (("New user…", self.nuevo), ("Reset password…", self.restablecer),
                              ("Change role", self.cambiar_rol), ("Deactivate", self.desactivar)):
            b = QtWidgets.QPushButton(texto)
            b.clicked.connect(accion)
            botones.addWidget(b)
        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(self.tabla)
        v.addWidget(QtWidgets.QLabel("Recent activity of the selected user"))
        v.addWidget(self.actividad)
        v.addLayout(botones)
        v.addWidget(self.estado)
        self.cargar()

    @staticmethod
    def _fecha(iso):
        return iso[:16].replace("T", " ") if iso else "never"

    def cargar(self, elegir=None):
        self.perfiles = self.base.perfiles()
        self.tabla.setRowCount(len(self.perfiles))
        for i, p in enumerate(self.perfiles):
            celdas = (p["nombre"], ROL_VISIBLE.get(p["rol"], p["rol"]), "active" if p["activo"] else "deactivated", self._fecha(p["creado"]),
                      self._fecha(p["ultimo_ingreso"]), p["ingresos"], p["conteos"], p["reses_contadas"],
                      self.NOMBRES.get(p["ultima_accion"], p["ultima_accion"] or ""))
            for j, valor in enumerate(celdas):
                it = QtWidgets.QTableWidgetItem(str(valor))
                if not p["activo"]:
                    it.setForeground(QtGui.QColor(150, 150, 150))
                self.tabla.setItem(i, j, it)
        self.tabla.resizeColumnsToContents()
        nombres = [p["nombre"] for p in self.perfiles]
        fila = nombres.index(elegir) if elegir in nombres else 0
        self.tabla.setCurrentCell(fila, 0)
        self.ver(fila)            # si la fila no cambia, Qt no avisa: se refresca a mano

    def elegido(self):
        f = self.tabla.currentRow()
        return self.perfiles[f]["nombre"] if 0 <= f < len(self.perfiles) else None

    def ver(self, fila):
        if not 0 <= fila < len(self.perfiles):
            return
        lineas = []
        for momento, accion, detalle in self.base.actividad_de(self.perfiles[fila]["nombre"]):
            lineas.append(f"{self._fecha(momento)}   {self.NOMBRES.get(accion, accion)}   {detalle if detalle else ''}")
        self.actividad.setPlainText("\n".join(lineas) or "No activity.")

    def _hacer(self, fn, mensaje, elegir=None):
        try:
            fn()
            self.estado.setStyleSheet("")
            self.estado.setText(mensaje)
        except Exception as err:  # noqa: BLE001 - se muestra al usuario
            self.estado.setStyleSheet(f"color: {ROJO};")
            self.estado.setText(str(err))
        self.cargar(elegir or self.elegido())

    def nuevo(self):
        nombre, ok = QtWidgets.QInputDialog.getText(self, "New user", "User name:")
        if not ok or not nombre.strip():
            return
        clave, ok = QtWidgets.QInputDialog.getText(self, "New user", f"Initial password for {nombre.strip()}:",
                                                   QtWidgets.QLineEdit.EchoMode.Password)
        if not ok:
            return
        rol, ok = QtWidgets.QInputDialog.getItem(self, "New user", "Rol:", ["operador", "admin"], 0, False)
        if ok:
            self._hacer(lambda: self.base.crear_usuario(self.llave, nombre, clave, rol),
                        f"User {nombre.strip()} created as {rol}.", nombre.strip())

    def restablecer(self):
        nombre = self.elegido()
        if not nombre:
            return
        clave, ok = QtWidgets.QInputDialog.getText(self, "Reset password", f"New password for {nombre}:",
                                                   QtWidgets.QLineEdit.EchoMode.Password)
        if ok:
            self._hacer(lambda: self.base.restablecer_clave(self.llave, nombre, clave),
                        f"Password for {nombre} reset. If the user was deactivated, it's active again.")

    def cambiar_rol(self):
        nombre = self.elegido()
        if not nombre:
            return
        actual = next(p["rol"] for p in self.perfiles if p["nombre"] == nombre)
        nuevo = "operador" if actual == "admin" else "admin"
        self._hacer(lambda: self.base.cambiar_rol(nombre, nuevo), f"{nombre} is now {ROL_VISIBLE.get(nuevo, nuevo)}.")

    def desactivar(self):
        nombre = self.elegido()
        if not nombre:
            return
        r = QtWidgets.QMessageBox.question(self, "Deactivate", f"Deactivate {nombre}? They won't be able to sign in until "
                                           "you reset their password. Their history is kept.")
        if r == QtWidgets.QMessageBox.StandardButton.Yes:
            self._hacer(lambda: self.base.desactivar_usuario(nombre), f"{nombre} deactivated. The database key was changed.")


class DialogoRespaldo(QtWidgets.QDialog):
    """El respaldo explicado: para que sirve, que hacer con el y como se recupera; y los botones para hacerlo."""

    def __init__(self, base, padre=None):
        super().__init__(padre)
        self.base = base
        self.setWindowTitle("Backup")
        self.resize(760, 640)
        # estado arriba: protegido o no, y lo que se perderia hoy
        self.icono = QtWidgets.QLabel()
        self.icono.setFixedSize(40, 40)
        self.icono.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.titulo = QtWidgets.QLabel()
        self.titulo.setObjectName("destacado")
        self.estado = QtWidgets.QLabel()
        self.estado.setObjectName("gris")
        self.estado.setWordWrap(True)
        cab = Panel()
        cab.setObjectName("tarjeta")
        lc = QtWidgets.QHBoxLayout(cab)
        lc.setContentsMargins(22, 18, 22, 18)
        lc.setSpacing(16)
        lc.addWidget(self.icono, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        tx = QtWidgets.QVBoxLayout()
        tx.setSpacing(4)
        tx.addWidget(self.titulo)
        tx.addWidget(self.estado)
        lc.addLayout(tx, 1)
        # para que sirve / que hacer
        def bloque(titulo, puntos):
            caja = Panel()
            caja.setObjectName("caja")
            lb = QtWidgets.QVBoxLayout(caja)
            lb.setContentsMargins(18, 14, 18, 16)
            lb.setSpacing(8)
            t = QtWidgets.QLabel(titulo)
            t.setObjectName("seccion")
            lb.addWidget(t)
            for n, texto in enumerate(puntos, 1):
                e = QtWidgets.QLabel(f"<table cellspacing='0'><tr><td style='padding-right:10px; font-weight:600'>{n}</td>"
                                     f"<td>{texto}</td></tr></table>")
                e.setWordWrap(True)
                lb.addWidget(e)
            lb.addStretch(1)
            return caja
        sirve = bloque("What is it for?", [
            "If the computer breaks, gets lost or stolen, the backup brings back <b>everything</b>: the ranch, the "
            "counts, the movements and the signed PDF reports. Each backup is a full copy, from day one.",
            "It's encrypted: whoever finds the drive can't read anything without your password.",
            "It doesn't keep the videos (they're large): copy them separately if you want them."])
        hacer = bloque("What do I do with it?", [
            "Plug in a USB drive (or use your OneDrive or Google Drive folder) and choose it below. You do this only once.",
            "Keep the USB drive <b>away from the computer</b>: not in the same bag or the same room.",
            "If something happens one day: install AGI on the new computer, choose <b>“Restore from a backup”</b>, "
            "pick the USB drive and sign in with your usual password."])
        info = QtWidgets.QHBoxLayout()
        info.setSpacing(12)
        info.addWidget(sirve, 1)
        info.addWidget(hacer, 1)
        # carpeta y botones
        self.carpeta = QtWidgets.QLineEdit(base.config("carpeta_respaldo", ""))
        self.carpeta.setReadOnly(True)
        self.carpeta.setPlaceholderText("You haven't chosen where to back up yet")
        self.b_elegir = QtWidgets.QPushButton("Choose USB or folder…")
        self.b_elegir.setObjectName("secundario")
        self.b_elegir.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.b_elegir.clicked.connect(self.elegir)
        self.b_elegir.setEnabled(base.rol == "admin")
        self.al_cerrar = QtWidgets.QCheckBox("Back up automatically when closing AGI, if anything changed (recommended)")
        self.al_cerrar.setChecked(base.config("respaldo_al_cerrar", "1") == "1")
        self.al_cerrar.setEnabled(base.rol == "admin")
        self.al_cerrar.toggled.connect(lambda v: base.poner_config("respaldo_al_cerrar", "1" if v else "0"))
        self.b_ahora = QtWidgets.QPushButton("Back up now")
        self.b_ahora.setObjectName("primario")
        self.b_ahora.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.b_ahora.clicked.connect(self.ahora)
        self.lista = QtWidgets.QLabel()
        self.lista.setObjectName("gris")
        self.lista.setWordWrap(True)
        self.aviso = QtWidgets.QLabel()
        self.aviso.setWordWrap(True)
        self.aviso.setStyleSheet(f"color: {ROJO};")
        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(10)
        fila.addWidget(self.carpeta, 1)
        fila.addWidget(self.b_elegir)
        abajo = QtWidgets.QHBoxLayout()
        abajo.addWidget(self.al_cerrar, 1)
        abajo.addWidget(self.b_ahora)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(14)
        v.addWidget(cab)
        v.addLayout(info)
        t = QtWidgets.QLabel("Where it's saved")
        t.setObjectName("seccion")
        v.addWidget(t)
        v.addLayout(fila)
        v.addWidget(self.aviso)
        v.addLayout(abajo)
        v.addWidget(self.lista)
        v.addStretch(1)
        self.refrescar()

    def refrescar(self):
        texto, urgente = texto_respaldo(self.base)
        conteos, movs, pdfs = self.base.resumen_datos()
        self.titulo.setText("Your data is not protected" if urgente else "Your data is protected")
        self.icono.setPixmap(icono("candado" if urgente else "check", ROJO if urgente else VERDE, 22))
        self.icono.setStyleSheet(f"background: {FONDO_ROJO if urgente else FONDO_VERDE}; border-radius: 20px;")
        perder = (f" If this computer broke today, you'd lose {conteos} count{'s' if conteos != 1 else ''}, "
                  f"{movs} movement{'s' if movs != 1 else ''} and {pdfs} signed report{'s' if pdfs != 1 else ''}."
                  if urgente and conteos else "")
        self.estado.setText(texto + perder)
        destino = self.base.config("carpeta_respaldo", "")
        self.carpeta.setText(destino)
        self.b_ahora.setEnabled(bool(destino))
        self.aviso.setText("That folder is on the same disk as the data: if the disk fails or the laptop is stolen, "
                           "both are lost. Use a USB drive or a cloud-synced folder."
                           if destino and datos.mismo_disco(destino, self.base.carpeta) else "")
        hay = datos.respaldos_en(destino) if destino and os.path.isdir(destino) else []
        fechas = [f"{d[9:13]}-{d[13:15]}-{d[15:17]} {d[18:20]}:{d[20:22]}" for d in hay[:3]]
        self.lista.setText(f"That folder has {len(hay)} backup{'s' if len(hay) != 1 else ''} (AGI keeps the last "
                           f"{datos.MAX_RESPALDOS} and deletes older ones). Most recent: {', '.join(fechas)}." if hay else "")

    def elegir(self):
        carpeta = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for the backups (USB or cloud)")
        if carpeta:
            self.base.poner_carpeta_respaldo(carpeta)
            self.refrescar()

    def ahora(self):
        try:
            ruta = self.base.respaldar()
            self.aviso.setText("")
            self.refrescar()
            self.estado.setText(f"Backup made and verified: {os.path.basename(ruta)}.")
        except Exception as err:  # noqa: BLE001 - se muestra al usuario
            self.refrescar()
            self.aviso.setText(f"Could not back up: {err}")


def texto_respaldo(base):
    """(texto, urgente) sobre el estado del respaldo, para mostrar en pantalla."""
    if not base.config("carpeta_respaldo"):
        return "No backup set up: the data only exists on this computer.", True
    dias = base.dias_sin_respaldo()
    if dias is None:
        return "No backup has been made yet.", True
    pendiente = base.hay_cambios_sin_respaldar()
    hace = "today" if dias < 1 else ("yesterday" if dias < 2 else f"{int(dias)} days ago")
    if dias >= datos.DIAS_AVISO_RESPALDO and pendiente:
        return f"Last backup {hace}, and there are changes not backed up.", True
    return f"Last backup: {hace}" + (" (there are new changes not backed up)." if pendiente else "."), False


def leer_imagen(ruta):
    """cv2.imread falla en Windows con tildes o enes en la ruta; esto no."""
    crudo = np.fromfile(ruta, dtype=np.uint8)
    return cv2.imdecode(crudo, cv2.IMREAD_COLOR)


def guardar_imagen(ruta, img, calidad=88):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, calidad])
    if ok:
        buf.tofile(ruta)


class Foto:
    def __init__(self, ruta):
        self.ruta = ruta
        self.nombre = os.path.basename(ruta)
        self.dets = []            # {"caja": [x1,y1,x2,y2], "conf": float, "origen": "ia"|"manual", "quitada": bool}
        self.procesada = False
        self.revisada = False
        self.danada = False       # no se pudo leer: queda fuera del conteo y se avisa

    def visibles(self, umbral):
        """Detecciones que cuentan, en orden de lectura (asi se numeran)."""
        v = [d for d in self.dets if not d["quitada"] and not d.get("repetida") and (d["origen"] == "manual" or d["conf"] >= umbral)]
        if not v:
            return []
        orden = contar.ordenar(np.array([d["caja"] for d in v], dtype=np.float32))
        return [v[i] for i in orden]

    def resumen(self, umbral):
        v = self.visibles(umbral)
        manual = sum(1 for d in v if d["origen"] == "manual")
        quitadas = sum(1 for d in self.dets if d["quitada"] and d["origen"] == "ia" and d["conf"] >= umbral)
        repetidas = sum(1 for d in self.dets if d.get("repetida") and not d["quitada"] and d["conf"] >= umbral)
        return {"total": len(v), "ia": len(v) - manual, "manual": manual, "quitadas": quitadas, "repetidas": repetidas}

    def repetidas(self, umbral):
        """Reses que ya se habian contado en un punto anterior: se muestran, pero no suman."""
        return [d for d in self.dets if d.get("repetida") and not d["quitada"] and d["conf"] >= umbral]


class Extractor(QtCore.QThread):
    """Lee los videos en segundo plano: saca los puntos de conteo y los une en un mismo plano."""
    avance = QtCore.Signal(int, int)
    uniendo = QtCore.Signal(int, int)
    listo = QtCore.Signal(str, float, int)        # carpeta, duracion en segundos, cuantos puntos
    fallo = QtCore.Signal(str)

    def __init__(self, videos, carpeta):
        super().__init__()
        self.videos, self.carpeta = list(videos), carpeta
        self.cancelar = False

    def run(self):
        try:
            rutas = vuelo.extraer(self.videos, self.carpeta, avance=self.avance.emit, cancelar=lambda: self.cancelar)
            if self.cancelar:
                return
            info = vuelo.leer(self.carpeta)
            vuelo.guardar_union(self.carpeta, vuelo.unir(rutas, info, avance=self.uniendo.emit))
            self.listo.emit(self.carpeta, sum(v["duracion_s"] for v in info["videos"]), len(rutas))
        except Exception as err:  # noqa: BLE001 - se muestra al usuario
            self.fallo.emit(str(err))


class Detector(QtCore.QThread):
    """Corre el modelo en segundo plano para no congelar la ventana."""
    avance = QtCore.Signal(int, int, str)
    foto_lista = QtCore.Signal(int, object, object)
    foto_danada = QtCore.Signal(int)
    fallo = QtCore.Signal(str)

    def __init__(self, fotos, indices, modelo, escala=1.0):
        super().__init__()
        self.fotos, self.indices, self.modelo, self.escala = fotos, indices, modelo, escala
        self.cancelar = False

    def run(self):
        try:
            problema = comprobar_modelo(self.modelo)
            if problema:
                self.fallo.emit(problema)
                return
            sesion = contar.cargar_modelo(self.modelo)
            for n, i in enumerate(self.indices):
                if self.cancelar:
                    break
                self.avance.emit(n, len(self.indices), self.fotos[i].nombre)
                img = leer_imagen(self.fotos[i].ruta)
                if img is None:
                    self.foto_danada.emit(i)
                    continue
                cajas, punt = contar.detectar(sesion, img, conf=CONF_MIN, escala=self.escala)
                self.foto_lista.emit(i, cajas, punt)
            self.avance.emit(len(self.indices), len(self.indices), "")
        except Exception as err:  # noqa: BLE001 - se muestra al usuario
            self.fallo.emit(str(err))


class Visor(QtWidgets.QGraphicsView):
    """Muestra la foto con los cuadros. Modos: mover, agregar, quitar."""
    agregada = QtCore.Signal(float, float, float, float)
    quitada = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QtGui.QColor(13, 13, 13))
        self.modo = "mover"
        self.pix = None
        self.elementos = []
        self.dets = []
        self.inicio = None
        self.goma = None
        self.tam_defecto = 40.0
        self.poner_modo("mover")

    def poner_modo(self, modo):
        self.modo = modo
        mover = modo == "mover"
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag if mover
                         else QtWidgets.QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(QtCore.Qt.CursorShape.OpenHandCursor if mover else (
            QtCore.Qt.CursorShape.CrossCursor if modo == "agregar" else QtCore.Qt.CursorShape.PointingHandCursor))

    def poner_foto(self, img_bgr):
        self.scene().clear()
        self.elementos = []
        self.pix = None
        if img_bgr is None:
            return
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()
        self.pix = self.scene().addPixmap(QtGui.QPixmap.fromImage(qimg))
        self.scene().setSceneRect(0, 0, w, h)
        self.ajustar()

    def poner_cuadro(self, img_bgr):
        """Video en marcha: cambia solo la imagen, sin tocar el acercamiento ni los cuadros."""
        if self.pix is None:
            return self.poner_foto(img_bgr)
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        self.pix.setPixmap(QtGui.QPixmap.fromImage(QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()))

    def desplazar_cajas(self, dx, dy, visibles=True):
        """Mueve los cuadros con el suelo mientras el video avanza."""
        for it in self.elementos:
            it.setPos(it.data(1) + QtCore.QPointF(dx, dy))
            it.setVisible(visibles)

    def ajustar(self):
        if self.pix:
            self.fitInView(self.scene().sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def poner_cajas(self, dets, repetidas=()):
        for it in self.elementos:
            self.scene().removeItem(it)
        self.elementos = []
        fuente = QtGui.QFont()
        fuente.setPointSize(9)
        fuente.setBold(True)
        for d in repetidas:          # ya contadas antes: linea blanca punteada y el numero de la original, en gris
            x1, y1, x2, y2 = d["caja"]
            pluma = QtGui.QPen(QtGui.QColor(255, 255, 255), 1.5, QtCore.Qt.PenStyle.DotLine)
            pluma.setCosmetic(True)
            r = self.scene().addRect(QtCore.QRectF(x1, y1, x2 - x1, y2 - y1), pluma)
            r.setData(1, QtCore.QPointF(0, 0))
            self.elementos.append(r)
            if "id" in d:
                t = QtWidgets.QGraphicsSimpleTextItem(f"#{d['id']}")
                t.setFont(fuente)
                t.setBrush(QtGui.QColor(20, 19, 15))
                alto_t = t.boundingRect().height()
                fondo = QtWidgets.QGraphicsRectItem(t.boundingRect().adjusted(-2, 0, 2, 0).translated(0, -alto_t))
                fondo.setBrush(QtGui.QColor(235, 235, 230, 220))
                fondo.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
                fondo.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                fondo.setPos(x1, y1)
                t.setParentItem(fondo)
                t.setPos(0, -alto_t)
                fondo.setData(1, QtCore.QPointF(x1, y1))
                self.scene().addItem(fondo)
                self.elementos.append(fondo)
        self.dets = list(dets)      # los items guardan el indice: Qt copiaria el dict
        if dets:
            lados = [max(d["caja"][2] - d["caja"][0], d["caja"][3] - d["caja"][1]) for d in dets]
            self.tam_defecto = float(np.median(lados))
        for n, d in enumerate(dets, 1):
            x1, y1, x2, y2 = d["caja"]
            color = QtGui.QColor(*(CAJA_MANUAL if d["origen"] == "manual" else CAJA_IA))
            pluma = QtGui.QPen(color, 2)
            pluma.setCosmetic(True)                      # mismo grosor con cualquier zoom
            r = self.scene().addRect(QtCore.QRectF(x1, y1, x2 - x1, y2 - y1), pluma)
            r.setData(0, n - 1)
            r.setData(1, QtCore.QPointF(0, 0))            # posicion sin desplazar
            t = QtWidgets.QGraphicsSimpleTextItem(f"#{d.get('id', n)}")
            t.setFont(fuente)
            t.setBrush(QtGui.QColor(0, 0, 0))
            alto_t = t.boundingRect().height()
            fondo = QtWidgets.QGraphicsRectItem(t.boundingRect().adjusted(-2, 0, 2, 0).translated(0, -alto_t))
            fondo.setBrush(color)
            fondo.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
            # la etiqueta no cambia de tamano con el zoom y queda encima del cuadro
            fondo.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            fondo.setPos(x1, y1)
            t.setParentItem(fondo)
            t.setPos(0, -alto_t)
            fondo.setData(0, n - 1)
            fondo.setData(1, QtCore.QPointF(x1, y1))
            self.scene().addItem(fondo)
            self.elementos += [r, fondo]

    def _det_en(self, pos):
        for it in self.items(pos):
            i = it.data(0)
            if i is None and it.parentItem() is not None:
                i = it.parentItem().data(0)
            if i is not None and 0 <= int(i) < len(self.dets):
                return self.dets[int(i)]
        return None

    def wheelEvent(self, ev):
        f = 1.25 if ev.angleDelta().y() > 0 else 0.8
        self.scale(f, f)

    def mousePressEvent(self, ev):
        if self.pix is None:
            return super().mousePressEvent(ev)
        derecho = ev.button() == QtCore.Qt.MouseButton.RightButton
        if derecho or (self.modo == "quitar" and ev.button() == QtCore.Qt.MouseButton.LeftButton):
            d = self._det_en(ev.position().toPoint())
            if d is not None:
                self.quitada.emit(d)
            return
        if self.modo == "agregar" and ev.button() == QtCore.Qt.MouseButton.LeftButton:
            self.inicio = self.mapToScene(ev.position().toPoint())
            pluma = QtGui.QPen(QtGui.QColor(*CAJA_MANUAL), 2, QtCore.Qt.PenStyle.DashLine)
            pluma.setCosmetic(True)
            self.goma = self.scene().addRect(QtCore.QRectF(self.inicio, self.inicio), pluma)
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self.goma is not None:
            self.goma.setRect(QtCore.QRectF(self.inicio, self.mapToScene(ev.position().toPoint())).normalized())
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self.goma is not None:
            r = self.goma.rect()
            self.scene().removeItem(self.goma)
            self.goma = None
            if r.width() < 6 or r.height() < 6:          # clic sin arrastrar: cuadro de tamano tipico
                t = self.tam_defecto
                r = QtCore.QRectF(self.inicio.x() - t / 2, self.inicio.y() - t / 2, t, t)
            r = r.intersected(self.scene().sceneRect())
            if r.width() >= 4 and r.height() >= 4:
                self.agregada.emit(r.left(), r.top(), r.right(), r.bottom())
            return
        super().mouseReleaseEvent(ev)
